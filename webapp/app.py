"""BeeDigital hazard platform — Arunachal Pradesh.

This file is the SHELL and nothing else: page setup, the landing page, and the
router that hands control to one module. It contains no hazard maths, no map
drawing and no knowledge of what a landslide or a flood is.

    core/       the shared spine — grid, geography, maps, search, terrain
    products/   one folder per module, plus the registry that lists them
    assets/     base/ is shared geography; <slug>/ is one module's own output

Adding a module is a folder in products/ and one line in products/__init__.py.
That is the whole reason for this layout: the second hazard should cost a
fraction of the first, and the third less again.

Runs on numpy, pandas, folium and streamlit alone — no rasterio, no geopandas,
no model files — which is what lets the whole platform sit on a free 1 GB host.
"""
from __future__ import annotations

import sys
from pathlib import Path

# ⚠️ Must run BEFORE the core/ and products/ imports below.
# `streamlit run` puts the script's own folder on the import path, but nothing
# else does — not the test harness, and not every host's entry point. Without
# this the whole app dies at `import core` with a bare ModuleNotFoundError,
# which says nothing about the real cause.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import streamlit as st

import core.splash as splash
import core.theme as T
import products as P
from core.bundle import load_base, load_elevation
from core.location import resolve_visitor
from core.shell import Shell

st.set_page_config(page_title="BeeDigital Hazard Platform · Arunachal Pradesh",
                   page_icon="◎", layout="wide",
                   initial_sidebar_state="expanded",
                   menu_items={"About": "Landslide and flood forecasting for "
                                        "Arunachal Pradesh."})
st.markdown(T.CSS, unsafe_allow_html=True)
# Warm the TLS handshake for the tile hosts before the map asks for them.
st.markdown(
    '<link rel="preconnect" href="https://server.arcgisonline.com">'
    '<link rel="preconnect" href="https://server.arcgisonline.com">'
    '<link rel="preconnect" href="https://tile.opentopomap.org">',
    unsafe_allow_html=True)


# ─────────────────────────── routing ─────────────────────────────────────────
# The active module lives in the URL, not just in session state, so a link to
# SlopeSense stays a link to SlopeSense — and the browser back button walks
# between modules the way a visitor expects it to.
def _open(slug: str | None) -> None:
    """Switch module. Runs as the button's on_click callback — BEFORE the
    script reruns — never from `if st.button(...)` mid-page.

    ⚠️ That difference is the whole fix for a bug (2026-10-07): called from
    inside the landing page, this ended with st.rerun(), which stopped the
    landing page halfway through drawing itself again. Streamlit then
    sometimes never cleared that half-drawn page, and the landing title sat
    above the module until a reload (2 of 3 fresh visits in a test). As a
    callback, the click's own rerun goes straight to the module: no landing
    page is redrawn, and nothing is left half-done.

    Nothing here raises the splash either. The overlay is already up before
    this runs — core/splash.py puts it there in the browser, on the click
    itself. See that module for why it cannot be done from Python."""
    if slug:
        st.session_state.module = slug
        st.query_params["m"] = slug
    else:
        st.session_state.pop("module", None)
        if "m" in st.query_params:
            del st.query_params["m"]
    # A module switch must not carry the previous one's map camera or selected
    # day across — those keys mean different things in different modules.
    for k in ("map_target", "day_i", "view"):
        st.session_state.pop(k, None)


def _set_page(nav_key: str, label: str) -> None:
    """A page inside a module, as a callback for the same reason as _open."""
    st.session_state[nav_key] = label


if "module" not in st.session_state and st.query_params.get("m"):
    st.session_state.module = st.query_params["m"]
product = P.get(st.session_state.get("module"))


# ─────────────────────────── landing ─────────────────────────────────────────
# Compact and single-screen ON PURPOSE. This used to be a scrolling hero with
# a paragraph per module — the platform's whole pitch is "one pipeline, easy
# to extend", and a page a visitor has to scroll to read undercuts that in
# about four seconds. What is on screen is what a person picks a module from;
# everything else lives inside the module itself.
def _tile(p: P.Product) -> None:
    """One compact module tile — icon, name, one line, status. No blurb.

    The button sits below rather than inside the tile because Streamlit
    cannot put a real widget inside an HTML block; the CSS closes the gap so
    the two read as one piece, the same trick the old door cards used.
    """
    ready = p.available
    pill = ("<span class='tile-pill live'>Live</span>" if p.status == "live"
            else "<span class='tile-pill wip'>🔧 Building</span>"
            if p.status == "building" else "")
    with st.container(border=False, key=f"tile_{p.slug}"):
        st.markdown(
            f"<div class='tile' style='--tile:{p.accent}'>"
            f"<div class='tile-top'><div class='tile-icon'>{p.icon}</div>"
            f"{pill}</div>"
            f"<div class='tile-name'>{p.name}</div>"
            f"<div class='tile-tag'>{p.tagline}</div>"
            "</div>", unsafe_allow_html=True)
        st.button("Open" if ready else "Not ready", key=f"go_{p.slug}",
                  width="stretch", type="primary" if ready else "secondary",
                  on_click=_open, args=(p.slug,))


def _ghost_tile() -> None:
    """An empty slot beside the real modules, not a fourth one competing with
    them — dashed, dimmer, nothing to click. Says the platform is built to
    grow without promising a name or a date for what grows next."""
    with st.container(border=False, key="tile_ghost"):
        st.markdown(
            "<div class='tile tile-ghost'>"
            "<div class='tile-icon'>+</div>"
            "<div class='tile-name'>More modules</div>"
            "<div class='tile-tag'>Built to grow</div>"
            "</div>", unsafe_allow_html=True)
        st.button("—", key="go_ghost", width="stretch", disabled=True)


if product is None:
    # Raised directly (no click to arm) only on the very first landing this
    # session — every later visit gets here via arm_home()'s click-triggered
    # overlay instead, which is already up by the time this line runs.
    if "_landed_once" not in st.session_state:
        st.session_state["_landed_once"] = True
        splash.cold_start()

    # ⚠️ The whole landing composition sits inside ONE narrower, centred
    # column — key="land_wrap" gets styled straight on the real Streamlit
    # container (the same st-key trick as backbone_strip below), which both
    # narrows the block off the page's full 1400px width AND centres it
    # vertically in the viewport, since the content is short enough that a
    # left-and-top-hugging block reads as unfinished rather than compact.
    with st.container(border=False, key="land_wrap"):
        st.markdown(
            "<div class='land-head'><div class='land-logo'>◎</div>"
            "<div class='land-title'>Hazard Intelligence Platform"
            "<span>Arunachal Pradesh</span></div></div>", unsafe_allow_html=True)

        mains = [p for p in P.REGISTRY if p.kind == "product"]
        # Own key, distinct from land_wrap, purely so the entry-animation CSS
        # in theme.py can stagger THIS row's columns without also catching the
        # backbone strip's internal two-column layout below.
        with st.container(border=False, key="land_tiles"):
            cols = st.columns(len(mains) + 1, gap="medium")
            for col, p in zip(cols, mains):
                with col:
                    _tile(p)
            with cols[-1]:
                _ghost_tile()

        bones = [p for p in P.REGISTRY if p.kind == "foundation"]
        if bones:
            bone = bones[0]
            st.markdown("<div class='land-foot-label'>What every module "
                        "above runs on</div>", unsafe_allow_html=True)
            with st.container(border=False, key="backbone_strip"):
                bc1, bc2 = st.columns([5, 1.1], vertical_alignment="center")
                with bc1:
                    st.markdown(
                        f"<div class='backbone-inline'>"
                        f"<div class='tile-icon' style='color:{bone.accent};"
                        f"background:color-mix(in srgb,{bone.accent} 14%,"
                        f"transparent);border-color:color-mix(in srgb,"
                        f"{bone.accent} 30%,transparent)'>{bone.icon}</div>"
                        f"<div><div class='backbone-strip-name'>{bone.name}"
                        f"</div><div class='backbone-strip-tag'>"
                        f"{bone.tagline}</div></div></div>",
                        unsafe_allow_html=True)
                with bc2:
                    st.button("Open →", key=f"go_{bone.slug}", width="stretch",
                              on_click=_open, args=(bone.slug,))

    # Take down whichever overlay got this render here — cold_start() above,
    # or arm_home() from inside a module — and restart the entry animation
    # clean now that it is actually visible. Harmless if neither fired; there
    # is then no #hip-splash node and nothing underneath needs restarting.
    splash.dismiss_landing()
    # Arm the click-to-cover overlay for the trip back IN. Must come AFTER the
    # tiles exist, since the listener reads the module's name and accent out
    # of the tile it was clicked in.
    splash.arm()
    st.stop()


# ─────────────────────────── inside a module ─────────────────────────────────
# The spine is loaded ONCE, here, and handed down. A product that loaded the
# grid itself could disagree with the one the shell drew the boundary on.
GRID, GEO = load_base()
ELEV = load_elevation()
LOC = resolve_visitor(GRID, GEO.towns, GEO.districts)

with st.sidebar:
    bcol, icol = st.columns([4.2, 1], vertical_alignment="center")
    with bcol:
        st.markdown(f"""
        <div class="brand brand-sm">
          <div class="brand-logo" style="color:{product.accent}">{product.icon}</div>
          <div><div class="brand-name">{product.name}</div>
               <div class="brand-tag">ARUNACHAL PRADESH · {product.hazard.upper()}</div></div>
        </div>""", unsafe_allow_html=True)
    with icol:
        with st.popover("ℹ️", width="stretch"):
            st.markdown(f"**{product.name}** — {product.tagline}\n\n{product.blurb}")
            # Pages that exist but don't earn a permanent sidebar slot — see
            # Product.extra_nav. Kept hazard-agnostic on purpose: this file
            # doesn't know what "Evidence" means, only that clicking it sets
            # the RIGHT module's own nav key (nav_key varies per module) and
            # reruns into it. A disabled_why turns the entry into a greyed,
            # unclickable line instead — a page that exists in code but is
            # not ready for anyone outside the team to open yet.
            if product.extra_nav:
                st.divider()
                for icon, label, disabled_why in product.extra_nav:
                    st.button(f"{icon}  {label}", key=f"nav_extra_{label}",
                              width="stretch", disabled=bool(disabled_why),
                              help=disabled_why or None, on_click=_set_page,
                              args=(product.nav_key, label))
    st.button("← All modules", key="nav_home", width="stretch",
              on_click=_open, args=(None,))
    splash.arm_home()
    st.divider()

# ⚠️ try/finally, not a plain call afterwards. Several views call st.stop()
# partway through (no live rainfall, the end of a chosen road route), and
# st.stop() raises — so a dismiss() written after this would simply never run
# and the overlay would stay up over the page. `finally` fires on every exit
# path: normal return, st.stop(), or an unexpected error.
#
# Harmless on reruns that never raised a splash: there is no overlay in the
# document, and the script just removes nothing.
try:
    product.render(Shell(grid=GRID, geo=GEO, elev=ELEV, loc=LOC,
                         product=product))
finally:
    splash.dismiss()
