"""The module-opening splash — deliberately client-side.

⚠️ READ THIS BEFORE REPLACING IT WITH SOMETHING THAT LOOKS TIDIER IN PYTHON.

Three server-side versions were built and all three failed, for one reason:
Streamlit only swaps the visible page when a script run CONCLUDES. Going from
the landing page to a module (or back) changes the whole script path, and for
the entire duration of that run the browser keeps showing the page it already
had.

  · a placeholder filled then cleared inside one run  — never painted at all
  · st.rerun() to force a splash-only frame           — the abandoned run left
                                                        the old page's own
                                                        elements behind
  · st.spinner() around the load                      — DOES flush mid-run, but
                                                        only ~480 ms in, and it
                                                        paints OVER the still
                                                        visible old page, which
                                                        then survives into the
                                                        half-drawn destination

So the overlay is put up by the browser, on the click itself, with no server
round trip in between — which is the only way "the moment I click" can
actually mean that. Python's only job is to take it down again, once the
destination has finished rendering.

Same-origin: a components.html iframe can reach window.parent.document, and
the overlay is appended to the parent's <body>, outside Streamlit's managed
element tree — so Streamlit will neither prune it early nor fight over it.

Three ways to raise the SAME overlay, for the three ways a visitor arrives
somewhere in this app, plus two ways to take it back down:
    arm()          + dismiss()          landing → a module (tile click)
    arm_home()     + dismiss_landing()  a module → landing ("← All modules")
    cold_start()   + dismiss_landing()  nobody  → landing  (first page load)
The first two are click-armed: something is clicked, and the click itself
(not the Python rerun it triggers) puts the overlay up. The third has no
click to hook — a first-ever visit is the one arrival with no earlier page to
have been clicked FROM — so cold_start() raises it directly, as the first
thing the landing render does.

dismiss() (used leaving a module) removes the overlay as fast as the
destination's own first paint allows, because a module should feel snappy to
open. dismiss_landing() (used arriving at the landing page, from either of
the other two) deliberately holds it a little longer and then restarts the
landing page's own entry animation from a clean start — see LAND_DISMISS_JS —
so that animation always plays out in full on a page the visitor can actually
see, rather than partway, hidden, while racing whatever put the cover up.
"""
from __future__ import annotations

import streamlit.components.v1 as components

_OVERLAY_ID = "hip-splash"

# Idempotent style + overlay() helper, shared by both arm scripts below. Each
# is injected inside its own components.html iframe, in its own JS realm, so
# there is no shared state to worry about beyond the DOM node — hence the
# `getElementById` guard rather than a module-level flag.
_STYLE_AND_OVERLAY_JS = """
  if (!doc.getElementById('hip-splash-style')) {
  const css = doc.createElement('style');
  css.id = 'hip-splash-style';
  css.textContent = `
    #%(ID)s{position:fixed;inset:0;z-index:2147483647;
      display:flex;align-items:center;justify-content:center;
      background:
        radial-gradient(1100px 520px at 12%% -12%%, rgba(46,230,214,.10), transparent 62%%),
        radial-gradient(900px 480px at 88%% -6%%, rgba(77,141,255,.10), transparent 60%%),
        #0b0f14;
      font-family:'Inter',system-ui,sans-serif;}
    /* ⚠️ NO fade-in. A 120 ms ease-out was tried and it is precisely the
       complaint this overlay exists to answer: during the fade the old page's
       elements are still legible through it, which reads as "the old page is
       hanging around". Opaque on the very first frame instead. */
    #%(ID)s .hip-card{display:flex;flex-direction:column;align-items:center;
      gap:15px;}
    #%(ID)s .hip-ring{width:54px;height:54px;border-radius:50%%;
      border:3px solid rgba(255,255,255,.10);
      border-top-color:var(--hipc,#2ee6d6);
      animation:hipspin .8s linear infinite;}
    @keyframes hipspin{to{transform:rotate(360deg)}}
    #%(ID)s .hip-txt{font-family:'Sora','Inter',sans-serif;font-size:1.05rem;
      font-weight:700;color:#e5edf5;letter-spacing:-.01em;}
    #%(ID)s .hip-sub{font-size:.8rem;color:#8fa3ba;margin-top:-9px;}
  `;
  doc.head.appendChild(css);
  }

  function overlay(title, sub, accent) {
    if (doc.getElementById('%(ID)s')) return;
    const ov = doc.createElement('div');
    ov.id = '%(ID)s';
    if (accent) ov.style.setProperty('--hipc', accent);
    const safe = (s) => (s || '').replace(/[<>&]/g, '');
    ov.innerHTML =
      '<div class="hip-card"><div class="hip-ring"></div>' +
      '<div class="hip-txt">' + safe(title) + '</div>' +
      (sub ? '<div class="hip-sub">' + safe(sub) + '</div>' : '') +
      '</div>';
    doc.body.appendChild(ov);
    // Safety net so a stuck overlay can never trap the visitor. Scheduled on
    // the PARENT window, not this iframe — this iframe is torn down during
    // the very navigation being covered, and a timer belonging to it would
    // die with it.
    win.setTimeout(() => { const e = doc.getElementById('%(ID)s');
                           if (e) e.remove(); }, 20000);
  }
""" % {"ID": _OVERLAY_ID}

# Armed on the landing page. Attaches ONE capturing click listener to the
# parent document; the listener puts the overlay up before Streamlit has even
# been told a button was pressed.
ARM_JS = """
<script>
(function () {
  const win = window.parent;
  const doc = win.document;

  // ⚠️ The listener is RE-ATTACHED on every landing render, and the previous
  // one is explicitly removed first. It cannot simply be attached once:
  // although it is registered on the PARENT document, the handler function
  // itself belongs to this iframe's JS realm, and Streamlit destroys this
  // iframe the moment you navigate into a module. Coming back to the landing
  // page, the old listener is a corpse — registered but dead — so an
  // "already armed, skip" guard meant the splash worked exactly once per
  // session. Removing by the handle parked on the parent window is what makes
  // the swap clean rather than stacking a new listener each visit.
  if (win.__hipSplashHandler) {
    doc.removeEventListener('click', win.__hipSplashHandler, true);
  }

  %(STYLE)s

  const handler = function (ev) {
    const btn = ev.target.closest && ev.target.closest('button');
    if (!btn || btn.disabled) return;
    const wrap = btn.closest('[class*="st-key-tile_"], '
                           + '[class*="st-key-backbone_strip"]');
    if (!wrap) return;                       // not a module-opening button
    if (wrap.className.indexOf('tile_ghost') !== -1) return;   // "More modules"
    const tile = wrap.querySelector('.tile, .lp-prod');
    const accent = tile
      ? getComputedStyle(tile).getPropertyValue('--tile').trim() : '';
    const nameEl = wrap.querySelector('.tile-name, .backbone-strip-name, .lp-prod-name');
    const subEl = wrap.querySelector('.tile-tag, .backbone-strip-tag, .lp-prod-tag');
    overlay('Opening ' + (nameEl ? nameEl.textContent : 'module') + '…',
            subEl ? subEl.textContent : '', accent);
  };
  win.__hipSplashHandler = handler;
  doc.addEventListener('click', handler, true);
})();
</script>
""" % {"STYLE": _STYLE_AND_OVERLAY_JS}

# Armed inside a module's sidebar. Same overlay, opposite direction — put up
# the instant "← All modules" is clicked, so the trip back has the same cover
# the trip in already had, rather than a bare page-swap on the way out only.
ARM_HOME_JS = """
<script>
(function () {
  const win = window.parent;
  const doc = win.document;

  if (win.__hipHomeHandler) {
    doc.removeEventListener('click', win.__hipHomeHandler, true);
  }

  %(STYLE)s

  const handler = function (ev) {
    const btn = ev.target.closest && ev.target.closest('button');
    if (!btn || btn.disabled) return;
    const wrap = btn.closest('[class*="st-key-nav_home"]');
    if (!wrap) return;
    overlay('Loading platform…', '', null);
  };
  win.__hipHomeHandler = handler;
  doc.addEventListener('click', handler, true);
})();
</script>
""" % {"STYLE": _STYLE_AND_OVERLAY_JS}

# Raised directly, no click to arm — the very first thing the landing page's
# render does on a visitor's first-ever page load this session. Everything
# else it draws happens underneath this, same as the click-armed versions.
COLD_JS = """
<script>
(function () {
  const win = window.parent;
  const doc = win.document;
  %(STYLE)s
  overlay('Loading platform…', '', null);
})();
</script>
""" % {"STYLE": _STYLE_AND_OVERLAY_JS}

# Rendered once a MODULE has finished drawing. Removing the node is all that
# is needed — it was never part of Streamlit's tree. Kept fast: opening a
# module should feel immediate, so this uncovers it the moment its first
# paint has actually landed, no longer than that.
DISMISS_JS = """
<script>
(function () {
  const doc = window.parent.document;
  const go = () => { const e = doc.getElementById('%(ID)s'); if (e) e.remove(); };
  // One frame of grace so the module's own first paint lands underneath the
  // overlay rather than appearing to flash in behind it.
  requestAnimationFrame(() => requestAnimationFrame(go));
  setTimeout(go, 350);
})();
</script>
""" % {"ID": _OVERLAY_ID}

# Rendered once the LANDING PAGE has finished drawing — reached either via
# cold_start() (first visit) or arm_home() (returning from a module). Unlike
# DISMISS_JS this holds the cover for a fixed, deliberate beat rather than
# racing the paint: a first-visit "Loading platform…" needs to read as an
# intentional moment, not a flicker, and every arrival deserves the same
# timing rather than a fast one and a slow one depending on which way the
# visitor came in.
#
# It then explicitly restarts the landing page's entry animation on the
# elements underneath. That is NOT optional polish: those elements began
# their CSS animation the instant they were inserted, which is BEFORE this
# cover comes off — left alone, the visitor would see it mid-flight or
# already finished, never its actual start. Toggling `animation` off, forcing
# a reflow, then clearing it back to the stylesheet's own value is the
# standard way to force a clean restart regardless of how far the hidden
# animation had already run.
LAND_DISMISS_JS = """
<script>
(function () {
  const doc = window.parent.document;
  setTimeout(() => {
    const e = doc.getElementById('%(ID)s');
    if (e) e.remove();
    const wrap = doc.querySelector('.st-key-land_wrap');
    if (!wrap) return;
    wrap.querySelectorAll(
      '.land-head, .st-key-land_tiles [data-testid="stHorizontalBlock"]>div, '
      + '.land-foot-label, .st-key-backbone_strip'
    ).forEach((el) => {
      el.style.animation = 'none';
      void el.offsetWidth;   // force a reflow — without this the next line is
                              // a no-op and the animation never restarts
      el.style.animation = '';
    });
  }, 550);
})();
</script>
""" % {"ID": _OVERLAY_ID}


def arm() -> None:
    """Call on the landing page, after the module tiles exist."""
    components.html(ARM_JS, height=0)


def arm_home() -> None:
    """Call inside a module, after its "← All modules" button exists."""
    components.html(ARM_HOME_JS, height=0)


def cold_start() -> None:
    """Call as the very first thing on the landing page's render, but ONLY on
    a visitor's first landing this session — see app.py for the session-state
    guard. There is no earlier click to arm a listener on for this one, so
    the overlay goes up directly instead."""
    components.html(COLD_JS, height=0)


def dismiss() -> None:
    """Call at the very end of a MODULE's render."""
    components.html(DISMISS_JS, height=0)


def dismiss_landing() -> None:
    """Call at the very end of the LANDING PAGE's render, whether it was
    reached via cold_start() or arm_home()."""
    components.html(LAND_DISMISS_JS, height=0)
