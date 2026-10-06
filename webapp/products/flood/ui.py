"""FloodSense's shared look — the pieces every FloodSense page is built from.

Split out of live.py on 2026-09-29, when the Flood-prone ground and
Catchments pages were made over in the forecast page's dashboard style
(docs/design/FLOOD_SCREEN_PLAN.md): one stylesheet, one set of badges for the
kinds of number, the same tiles, header, map title and river layer — so the
three pages read as one product.

Design rules they share: minimum text on screen, every explanation behind an
ⓘ or a badge's hover, and every number wearing the badge of what KIND of
number it is (forecast, outlook, estimate, measured, input, record).
"""
from __future__ import annotations

import html
import re

import folium
import numpy as np
import streamlit as st

import core.geo as G

# Rivers on the map: a stretch a gauge measures (its checked forecast
# applies there) glows bright, warm once its chance is 2%+; every other river
# is a quieter blue. Width follows the size of the river.
RIVER_QUIET = "#5cc8ff"
RIVER_OTHER = "#2a6bb0"
MAP_H = 480


# The kinds of number (see the module docstring). (glyph, name, colour,
# border style, what it means). The colours stay clear of the warm chance
# ramp: a badge says WHAT a number is, the ramp says how big it is.
TIERS = {
    "forecast": ("✔", "Forecast", "#4d8dff", "solid",
                 "Checked forecast: the chance a gauged river reaches its line. Graded every "
                 "day against the gauge's real readings — the strongest number here."),
    "outlook": ("≈", "Outlook", "#c4a7ff", "dashed",
                "Approximate outlook: the chance of a flood within about 10 km. Good at telling "
                "riskier places and weeks from quieter ones; its exact level can be off."),
    "estimate": ("◆", "Estimate", "#2bb3ad", "solid",
                 "Ground estimate: IF a flood comes nearby, the chance this spot is under water. "
                 "From the shape of the land — the same every day."),
    "measured": ("●", "Measured", "#cfd8e3", "solid",
                 "Measured: a real reading from a river gauge."),
    "input": ("☂", "Input", "#7fd4f0", "dotted",
              "Input: what feeds the forecast (rain, soil wetness). Not a flood chance."),
    "record": ("◷", "Record", "#e0c080", "solid",
               "Record: floods confirmed in the past (radar, satellite flood maps or a river "
               "gauge crossing its line). History, not a forecast."),
}


FS_CSS = """
<style>
.block-container{max-width:1720px!important;padding-top:1.5rem!important;}
/* ---- kinds of number ---- */
.fs-badge{display:inline-flex;align-items:center;gap:4px;font:700 .6rem/1.65 Inter,sans-serif;
  letter-spacing:.09em;text-transform:uppercase;color:var(--c);border:1px solid var(--c);
  border-radius:999px;padding:0 8px;background:color-mix(in srgb,var(--c) 11%,transparent);
  white-space:nowrap;vertical-align:middle;}
/* ---- hover explanations: the ⓘ and every badge ---- */
.fs-tip{position:relative;cursor:help;}
.fs-i{color:var(--dim);font-size:.82rem;margin-left:5px;font-style:normal;font-weight:400;
  letter-spacing:0;text-transform:none;}
.fs-i:hover{color:var(--accent);}
.fs-tip:hover::after{content:attr(data-tip);position:absolute;z-index:10000;left:50%;
  bottom:calc(100% + 8px);transform:translateX(-50%);width:max-content;max-width:300px;
  white-space:normal;text-align:left;background:#0a1018;border:1px solid #2f4258;
  color:#dbe6f1;font:500 .74rem/1.42 Inter,sans-serif;letter-spacing:0;text-transform:none;
  padding:8px 11px;border-radius:10px;box-shadow:0 10px 28px rgba(0,0,0,.55);
  pointer-events:none;}
.fs-tip.down:hover::after{bottom:auto;top:calc(100% + 8px);}
.fs-tip.left:hover::after{left:auto;right:-6px;transform:none;}
.fs-tip.right:hover::after{left:-6px;transform:none;}
/* ---- header ---- */
.fs-head{display:flex;align-items:center;gap:12px;}
.fs-logo{width:42px;height:42px;border-radius:13px;display:grid;place-items:center;
  font-size:21px;color:#06121a;flex:none;
  background:linear-gradient(135deg,#4d8dff,#2ee6d6);box-shadow:0 4px 16px rgba(77,141,255,.32);}
.fs-title{font:700 1.22rem/1.15 Sora,sans-serif;color:var(--txt);letter-spacing:-.02em;}
.fs-issued{font-size:.74rem;color:var(--mut);display:flex;align-items:center;gap:6px;
  margin-top:3px;flex-wrap:wrap;}
.fs-dot{width:8px;height:8px;border-radius:50%;display:inline-block;flex:none;
  box-shadow:0 0 0 3px color-mix(in srgb,currentColor 0%,transparent);}
.fs-key{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin:2px 0 12px;}
.fs-key-l{font-size:.6rem;font-weight:700;letter-spacing:.16em;color:var(--dim);
  text-transform:uppercase;margin-right:3px;}
/* ---- tiles ---- */
.fs-tiles{display:grid;gap:10px;margin-bottom:12px;}
.fs-tile{position:relative;background:linear-gradient(180deg,var(--panel-2),var(--panel));
  border:1px solid var(--line);border-radius:14px;padding:10px 13px 11px;min-width:0;}
.fs-tile-top{display:flex;justify-content:space-between;align-items:center;gap:6px;
  margin-bottom:6px;min-height:22px;}
.fs-tile-v{font:700 1.5rem/1.1 Sora,sans-serif;color:var(--txt);letter-spacing:-.02em;
  font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.fs-tile-v small{font-size:.9rem;color:var(--dim);font-weight:600;margin-left:2px;}
.fs-tile-l{font-size:.66rem;font-weight:600;letter-spacing:.07em;text-transform:uppercase;
  color:var(--mut);margin-top:5px;}
.fs-tile-s{font-size:.72rem;color:var(--dim);margin-top:2px;line-height:1.35;
  overflow:hidden;text-overflow:ellipsis;}
/* ---- hero (the headline outlook) ---- */
.fs-hero{position:relative;border-radius:16px;padding:14px 16px 12px;margin-bottom:12px;
  border:1px solid color-mix(in srgb,var(--c) 55%,var(--line));
  background:radial-gradient(420px 170px at 0% 0%,color-mix(in srgb,var(--c) 28%,transparent),
             transparent 72%),linear-gradient(180deg,var(--panel-2),var(--panel));}
.fs-hero-top{display:flex;align-items:center;gap:11px;}
.fs-hero-ic{width:42px;height:42px;border-radius:12px;display:grid;place-items:center;
  font-size:21px;flex:none;background:color-mix(in srgb,var(--c) 24%,transparent);
  border:1px solid color-mix(in srgb,var(--c) 48%,transparent);}
.fs-hero-word{font:700 .92rem/1.2 Sora,sans-serif;color:var(--t);text-transform:uppercase;
  letter-spacing:.02em;}
.fs-hero-sub{font-size:.74rem;color:var(--mut);margin-top:1px;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap;}
.fs-hero-row{display:flex;align-items:flex-end;justify-content:space-between;gap:8px;
  flex-wrap:wrap;margin:12px 0 3px;}
.fs-hero-badge{margin-bottom:6px;}
.fs-hero-num{font:800 2.8rem/1 Sora,sans-serif;color:var(--t);letter-spacing:-.035em;
  font-variant-numeric:tabular-nums;}
.fs-hero-when{font-size:.74rem;color:var(--mut);}
.fs-spark{display:flex;align-items:flex-end;gap:6px;height:62px;margin-top:10px;}
.fs-sb{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;
  gap:3px;height:100%;}
.fs-sb i{display:block;width:100%;border-radius:4px 4px 2px 2px;background:var(--b);}
.fs-sb span{font-size:.6rem;color:var(--dim);font-variant-numeric:tabular-nums;}
.fs-sb.later i{opacity:.42;}
.fs-sb.on i{box-shadow:0 0 0 2px var(--txt);}
.fs-sb.on span{color:var(--txt);font-weight:700;}
/* ---- place name ---- */
.fs-place{font:700 1.02rem/1.25 Sora,sans-serif;color:var(--txt);overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap;margin-bottom:10px;}
.fs-place small{display:block;font:500 .7rem Inter,sans-serif;color:var(--dim);}
.fs-empty{padding:16px 14px;text-align:center;color:var(--dim);font-size:.82rem;
  border:1px dashed var(--line);border-radius:14px;background:rgba(17,24,35,.5);margin-bottom:10px;}
/* ---- cards ---- */
.fs-sec{display:flex;align-items:center;gap:8px;margin:2px 0 8px;}
.fs-sec-t{font-size:.66rem;font-weight:700;letter-spacing:.15em;text-transform:uppercase;
  color:var(--mut);}
.fs-sec-n{font-size:.72rem;color:var(--dim);margin-left:auto;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;}
.fs-row{display:flex;align-items:center;gap:10px;padding:7px 0;
  border-bottom:1px solid rgba(34,48,68,.55);font-size:.82rem;color:var(--txt);}
.fs-row:last-child{border-bottom:none;}
.fs-ic{width:26px;height:26px;border-radius:8px;display:grid;place-items:center;font-size:12px;
  flex:none;background:color-mix(in srgb,var(--c) 17%,transparent);color:var(--c);
  border:1px solid color-mix(in srgb,var(--c) 30%,transparent);}
.fs-row-t{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.fs-row-r{margin-left:auto;white-space:nowrap;font-variant-numeric:tabular-nums;}
.fs-was{color:var(--dim);}
.fs-up{color:#f46d43;font-size:.7rem;}
.fs-dn{color:#5cc8ff;font-size:.7rem;}
.fs-eq{color:var(--dim);font-size:.7rem;}
.fs-chip{display:inline-block;min-width:50px;text-align:center;padding:2px 7px;border-radius:8px;
  font:700 .76rem Inter,sans-serif;background:var(--c);color:var(--k);
  font-variant-numeric:tabular-nums;}
/* ---- rivers list (conditions) ---- */
.fs-rhead,.fs-rrow{display:grid;grid-template-columns:minmax(0,1fr) 104px 58px;align-items:center;
  gap:8px;}
.fs-rhead{padding:0 0 5px;border-bottom:1px solid var(--line);}
.fs-rhead .fs-sec-t{white-space:nowrap;letter-spacing:.06em;font-size:.6rem;}
.fs-rrow{padding:6px 0;border-bottom:1px solid rgba(34,48,68,.55);}
.fs-rrow.own{background:rgba(77,141,255,.09);border-radius:9px;padding:6px 6px;margin:0 -6px;}
.fs-rname{font-size:.8rem;color:var(--txt);white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;}
.fs-rname small{color:var(--dim);font-size:.64rem;display:block;}
/* ---- soil meter ---- */
.fs-meter{position:relative;height:10px;border-radius:6px;margin:14px 2px 4px;
  background:linear-gradient(90deg,#8a6a3a,#4a4f55 45%,#2f7fb8 78%,#7fd4f0);}
.fs-meter i{position:absolute;top:-5px;width:5px;height:20px;border-radius:3px;background:#fff;
  transform:translateX(-50%);box-shadow:0 0 0 2px #0b0f14;}
.fs-meter-l{display:flex;justify-content:space-between;font-size:.62rem;color:var(--dim);}
.fs-big{font:700 1.6rem/1.1 Sora,sans-serif;color:var(--txt);letter-spacing:-.02em;}
.fs-big small{font-size:.8rem;color:var(--mut);font-weight:600;}
.fs-pill{display:inline-block;padding:3px 10px;border-radius:999px;font-size:.72rem;
  font-weight:600;border:1px solid var(--c);color:var(--c);
  background:color-mix(in srgb,var(--c) 10%,transparent);margin-top:8px;}
.fs-foot{font-size:.7rem;color:var(--dim);margin-top:8px;}
/* ---- map legend ---- */
.fs-legend{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px;align-items:center;}
.fs-legend .lg{padding:3px 9px;font-size:.72rem;gap:5px;}
.fs-legend .lg span{color:var(--dim);font-size:.66rem;}
.fs-sym{display:inline-flex;align-items:center;gap:6px;font-size:.72rem;color:var(--mut);
  margin-right:10px;white-space:nowrap;}
/* ---- 7-day outlook buttons ---- */
:is([class*="st-key-flv_d"],[class*="st-key-flc_d"]) button{padding:6px 2px!important;min-height:0!important;
  line-height:1.2!important;border-radius:11px!important;}
:is([class*="st-key-flv_d"],[class*="st-key-flc_d"]) button p{font-size:.7rem!important;}
:is([class*="st-key-flv_d"],[class*="st-key-flc_d"]) button strong{font:700 1.02rem Sora,sans-serif!important;}
[class*="st-key-fs_hot_"] button{justify-content:flex-start!important;text-align:left!important;
  padding:6px 12px!important;}
:is([class*="st-key-flv_d"],[class*="st-key-flc_d"]) button p,:is([class*="st-key-flv_d"],[class*="st-key-flc_d"]) button strong{white-space:nowrap;}
.st-key-fs_head button p{white-space:nowrap;}
/* ---- the main row: place | map | side panel ----
   Side by side while each has room (1,304 px of page), all three ending on
   one line. Narrower, the side panel drops under the map and lays its
   blocks side by side. The width is the row's own (a container query), so
   the sidebar opening or closing counts as well as the window. The map's
   620 px is what the whole state needs at its starting zoom. */
.st-key-fs_main{container-type:inline-size;container-name:fsmain;}
[data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-fs_col_m){flex-wrap:nowrap;align-items:stretch;}
[data-testid="stColumn"]:has(.st-key-fs_col_l){flex:1 1 296px!important;min-width:296px;}
[data-testid="stColumn"]:has(.st-key-fs_col_m){flex:5 1 620px!important;min-width:620px;}
[data-testid="stColumn"]:has(.st-key-fs_col_r){flex:1 1 324px!important;min-width:324px;}
/* each panel fills its column, so their bottom edges line up; so do the
   cards of any row keyed fs_eq_* */
[data-testid="stLayoutWrapper"]:has(> :is(.st-key-fs_col_l,.st-key-fs_col_m,.st-key-fs_col_r,.st-key-fs_mapcard,.st-key-fs_r_b,[class*="st-key-fs_eq_"])){flex:1 1 auto;}
/* what takes up the slack inside a panel: a block marked fs-grow, and the
   rows of a list of buttons — each only so far, so nothing balloons */
.st-key-fs_main [data-testid="stElementContainer"]:has(.fs-grow),.st-key-fs_main [data-testid="stElementContainer"] div:has(.fs-grow){display:flex;
  flex-direction:column;flex:1 1 auto;min-height:0;}
.fs-grow{flex:1 1 auto;}
/* Streamlit pulls whatever follows a text block up by 1rem. At the foot of
   a panel that leaves its last line hanging below the panel's edge. */
:is(.st-key-fs_col_l,.st-key-fs_col_r,.st-key-fs_r_a,.st-key-fs_r_b,.st-key-fs_r_c,.st-key-fs_mapcard)
  > [data-testid="stElementContainer"]:last-child [data-testid="stMarkdownContainer"]{margin-bottom:0!important;}
.fs-tiles.fs-grow{grid-auto-rows:1fr;margin-bottom:0;max-height:var(--cap,none);}
.fs-hero.fs-grow{display:flex;flex-direction:column;}
.fs-hero.fs-grow .fs-spark{margin-top:auto;}
.fs-rlist,.fs-rows{display:flex;flex-direction:column;}
.fs-rlist .fs-rrow,.fs-rows .fs-row{flex:1 1 auto;max-height:66px;}
.fs-rrow.more,.fs-rhead.more{display:none;}
.st-key-fs_main :is([class*="st-key-fs_hot_"],[class*="st-key-fs_pick_"]){flex:1 1 auto;max-height:64px;display:flex;flex-direction:column;}
.st-key-fs_main :is([class*="st-key-fs_hot_"],[class*="st-key-fs_pick_"]) .stButton{flex:1 1 auto;display:flex;flex-direction:column;min-height:0;}
.st-key-fs_main :is([class*="st-key-fs_hot_"],[class*="st-key-fs_pick_"]) .stButton > div{flex:1 1 auto;min-height:0;}
.st-key-fs_main :is([class*="st-key-fs_hot_"],[class*="st-key-fs_pick_"]) .stButton > div > span,.st-key-fs_main :is([class*="st-key-fs_hot_"],[class*="st-key-fs_pick_"]) .stButton > div > span > span,
.st-key-fs_main :is([class*="st-key-fs_hot_"],[class*="st-key-fs_pick_"]) .stButton > div button{height:100%;}
@container fsmain (max-width:1303px){
  [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-fs_col_m){flex-wrap:wrap;}
  [data-testid="stColumn"]:has(.st-key-fs_col_m){flex:3 1 540px!important;min-width:540px;}
  [data-testid="stColumn"]:has(.st-key-fs_col_r){flex:1 1 100%!important;}
  /* the side panel's three blocks: first and last on the left, the list on the right */
  .st-key-fs_col_r:has(.st-key-fs_r_c){display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);
    column-gap:32px;row-gap:16px;align-content:start;}
  .st-key-fs_col_r [data-testid="stLayoutWrapper"]:has(> .st-key-fs_r_a){grid-column:1;grid-row:1;}
  .st-key-fs_col_r [data-testid="stLayoutWrapper"]:has(> .st-key-fs_r_b){grid-column:2;grid-row:1 / span 2;
    align-self:stretch!important;height:100%;}
  .st-key-fs_col_r [data-testid="stLayoutWrapper"]:has(> .st-key-fs_r_c){grid-column:1;grid-row:2;align-self:end;}
  /* the forecast page: its day buttons in one line, its rivers in two columns */
  .st-key-fs_col_r:not(:has(.st-key-fs_r_c)) .st-key-fs_r_a{flex-direction:row;flex-wrap:wrap;}
  .st-key-fs_col_r:not(:has(.st-key-fs_r_c)) .st-key-fs_r_a > [data-testid="stElementContainer"]{flex:1 1 100%;}
  .st-key-fs_col_r:not(:has(.st-key-fs_r_c)) .st-key-fs_r_a > [data-testid="stLayoutWrapper"]{flex:1 1 0;min-width:0;}
  .fs-rlist{display:grid;grid-auto-flow:column;grid-template-rows:repeat(5,auto);
    grid-template-columns:minmax(0,1fr) minmax(0,1fr);column-gap:32px;}
  .fs-rrow.more,.fs-rhead.more{display:grid;}
}
@container fsmain (max-width:760px){
  [data-testid="stColumn"]:has(.st-key-fs_col_l),[data-testid="stColumn"]:has(.st-key-fs_col_m),[data-testid="stColumn"]:has(.st-key-fs_col_r){flex:1 1 100%!important;min-width:0;}
  .st-key-fs_col_r:has(.st-key-fs_r_c){display:flex;}
  .st-key-fs_col_r:not(:has(.st-key-fs_r_c)) .st-key-fs_r_a > [data-testid="stLayoutWrapper"]{flex:1 1 100%;}
  .fs-rlist{display:flex;}
  .fs-rrow.more,.fs-rhead.more{display:none;}
}
/* a row of small tiles inside a narrow card (the track record) */
.fs-tight .fs-tile{padding:9px 10px 10px;}
.fs-tight .fs-tile-v{font-size:1.16rem;}
@media (max-width:1100px){.fs-tiles{grid-template-columns:repeat(2,minmax(0,1fr))!important;}}
/* ---- "what this page is not", beside the key ---- */
.fs-note{margin-left:8px;font-size:.7rem;color:var(--mut);border:1px dashed var(--line);
  border-radius:999px;padding:1px 10px;white-space:nowrap;}
/* ---- horizontal bars ---- */
.fs-hb{display:grid;grid-template-columns:78px minmax(0,1fr) 64px;align-items:center;gap:9px;
  padding:5px 0;font-size:.78rem;color:var(--txt);}
.fs-hb-l{color:var(--mut);white-space:nowrap;}
.fs-hb-t{height:12px;border-radius:6px;background:rgba(34,48,68,.6);overflow:hidden;}
.fs-hb-t i{display:block;height:100%;border-radius:6px;}
.fs-hb-v{text-align:right;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap;}
/* ---- a list row that is a button (catchments to watch, exposed places) ---- */
[class*="st-key-fs_pick_"] button{justify-content:space-between!important;padding:5px 12px!important;
  min-height:0!important;}
[class*="st-key-fs_pick_"] button p{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
</style>
"""


# ── small formatting helpers ─────────────────────────────────────────────────
def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def _plain(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s)


def _i(text: str, where: str = "") -> str:
    """An ⓘ whose explanation shows on hover. `where` places the bubble:
    "down", "left" (anchored to the right edge), "right", or a mix."""
    return f"<span class='fs-tip fs-i {where}' data-tip='{_esc(_plain(text))}'>ⓘ</span>"


def badge(tier: str, more: str = "", where: str = "", mini: bool = False) -> str:
    """The badge that says what kind of number sits next to it; `mini` is
    the glyph alone, for tight spots (the key at the top names each one)."""
    g, name, col, style, tip = TIERS[tier]
    t = f"{name}. " * mini + tip + (" " + _plain(more) if more else "")
    return (f"<span class='fs-badge fs-tip {where}' data-tip='{_esc(t)}' "
            f"style='--c:{col};border-style:{style}'>{g}{'' if mini else ' ' + name}</span>")


def _tile(label: str, value: str, sub: str = "", tier: str | None = None,
          color: str | None = None, tip: str = "", where: str = "") -> str:
    """One number, big: its badge on top, then the value, what it is, and
    one line of context. The explanation sits behind the ⓘ."""
    top = (f"<div class='fs-tile-top'>{badge(tier, where=where) if tier else '<span></span>'}"
           f"{_i(tip, where) if tip else ''}</div>") if (tier or tip) else ""
    return (f"<div class='fs-tile'>{top}"
            f"<div class='fs-tile-v' style='color:{color or 'var(--txt)'}'>{value}</div>"
            f"<div class='fs-tile-l'>{label}</div>"
            + (f"<div class='fs-tile-s'>{sub}</div>" if sub else "") + "</div>")


def _tiles(items: list[str], cols: int, grow: bool = False) -> str:
    """`grow`: in the main row, the tiles take up the panel's spare height
    (so it ends level with the map) — up to a limit, so none balloons."""
    rows = -(-len(items) // cols)
    return (f"<div class='fs-tiles{' fs-grow' if grow else ''}' style='grid-template-columns:"
            f"repeat({cols},minmax(0,1fr))" + (f";--cap:{rows * 215}px" if grow else "") + "'>"
            f"{''.join(items)}</div>")


def _sec(title: str, *extra: str, note: str = "") -> str:
    """A section title: small caps, its badges, and a note on the right."""
    return (f"<div class='fs-sec'><span class='fs-sec-t'>{title}</span>{''.join(extra)}"
            + (f"<span class='fs-sec-n'>{note}</span>" if note else "") + "</div>")


def _row(icon: str, color: str, text: str, right: str = "") -> str:
    return (f"<div class='fs-row'><div class='fs-ic' style='--c:{color}'>{icon}</div>"
            f"<div class='fs-row-t'>{text}</div><div class='fs-row-r'>{right}</div></div>")


def _km(lat1, lon1, lat2, lon2) -> float:
    c = np.cos(np.radians((lat1 + lat2) / 2))
    return float(111.2 * np.hypot(lat2 - lat1, (lon2 - lon1) * c))


def _dist(km: float) -> str:
    return "under 1 km" if km < 1 else f"{km:.0f} km"


def _clean(label: str) -> str:
    """A gazetteer label without the coordinates or #n that tell same-name
    villages apart — for map labels, where the position already does."""
    return label.split("  (")[0].split(" #")[0]


# ── the map's own layers ─────────────────────────────────────────────────────
def _river_w(km2: float) -> float:
    return 1.1 if km2 < 300 else 1.8 if km2 < 1500 else 2.8 if km2 < 8000 else 4.0


@st.cache_data(show_spinner=False)
def _river_segments(key: tuple, _rivers: dict, _grid, _chan: np.ndarray, _gauge):
    """Every mapped river line as (coordinates, width, gauge index or -1):
    width from the size of the river at its middle, the gauge from the same
    link raster the "gauge on this river" lookup reads — so a stretch drawn
    as a gauge's is exactly where a click says that gauge applies."""
    out = []
    for f in _rivers.get("features", []):
        gm = f["geometry"]
        for line in ([gm["coordinates"]] if gm["type"] == "LineString" else gm["coordinates"]):
            n = len(line)
            if n < 2:
                continue
            a, b = line[(n - 1) // 2], line[n // 2]
            px = _grid.to_px((a[1] + b[1]) / 2, (a[0] + b[0]) / 2)
            km2 = float(_chan[px]) if px else 0.0
            g = int(_gauge[px]) if (px and _gauge is not None) else -1
            out.append(([[round(x, 3), round(y, 3)] for x, y in line], _river_w(km2), g))
    return out


def _draw_rivers(fg, segs, reach: dict, own_g: int) -> None:
    """Quiet blue rivers, then each gauged stretch glowing in its gauge's
    colour. `reach` = {gauge index: (colour, tooltip)}."""
    plain, gauged = [], []
    for coords, w, g in segs:
        geom = {"type": "LineString", "coordinates": coords}
        if g >= 0 and g in reach:
            col, tip = reach[g]
            gauged.append({"type": "Feature", "geometry": geom, "properties": {
                "w": w + (1.8 if g == own_g else 0.7), "c": col, "t": tip}})
        else:
            plain.append({"type": "Feature", "geometry": geom, "properties": {"w": w}})
    if plain:
        folium.GeoJson({"type": "FeatureCollection", "features": plain}, name="Rivers",
                       style_function=lambda f: {"color": RIVER_OTHER, "opacity": .85,
                                                 "weight": f["properties"]["w"]}).add_to(fg)
    if gauged:
        fc = {"type": "FeatureCollection", "features": gauged}
        folium.GeoJson(fc, name="Gauged glow",
                       style_function=lambda f: {"color": f["properties"]["c"], "opacity": .2,
                                                 "weight": f["properties"]["w"] + 4}).add_to(fg)
        folium.GeoJson(fc, name="Gauged rivers",
                       style_function=lambda f: {"color": f["properties"]["c"], "opacity": .96,
                                                 "weight": f["properties"]["w"]},
                       tooltip=folium.GeoJsonTooltip(["t"], labels=False)).add_to(fg)


@st.cache_data(show_spinner=False)
def _upstream(b0: int) -> tuple[np.ndarray, np.ndarray]:
    """(area, edge) masks of everything that drains to catchment b0 (0-based),
    itself included — "where the water reaching this place falls"."""
    from products.flood.data import load_catchments
    bid, nxt = load_catchments()[:2]
    kids: dict[int, list[int]] = {}
    for i, d in enumerate(nxt):
        if d >= 0:
            kids.setdefault(int(d), []).append(i)
    seen, stack = {b0}, [b0]
    while stack:
        for c in kids.get(stack.pop(), []):
            if c not in seen:
                seen.add(c)
                stack.append(c)
    m = (bid > 0) & np.isin(bid.astype(np.int32) - 1, np.fromiter(seen, np.int32))
    inner = (np.roll(m, 1, 0) & np.roll(m, -1, 0) & np.roll(m, 1, 1) & np.roll(m, -1, 1))
    return m, m & ~inner


def _catchment_of(pl) -> int | None:
    if pl is None:
        return None
    from products.flood.data import load_catchments
    b = int(load_catchments()[0][pl[0], pl[1]])
    return b - 1 if b > 0 else None


# ── page furniture shared by the FloodSense pages ───────────────────────────
def page_head(title: str, sub: str, icon: str = "◈", search_row=None):
    """Logo, title, one line under it, and the place search (the same
    session key on every page, so a place picked on one is still picked on
    the next). Returns the selected place, or None."""
    head = st.container(key="fs_head")
    h1, h2 = head.columns([1.3, 3.8], vertical_alignment="center")
    with h1:
        st.markdown(f"<div class='fs-head'><div class='fs-logo'>{icon}</div><div>"
                    f"<div class='fs-title'>{title}</div>"
                    f"<div class='fs-issued'>{sub}</div></div></div>", unsafe_allow_html=True)
    sel = None
    with h2:
        if search_row is not None:
            sel = search_row()
    if sel is None and st.session_state.get("search") not in (None, G.PROMPT):
        st.warning(f"Could not read **{st.session_state.search}** as a place or a coordinate.")
    return sel


def key_row(*tiers: str, note: str = "") -> None:
    """The badges this page uses, and one short "what this is not" note."""
    st.markdown("<div class='fs-key'><span class='fs-key-l'>Key</span>"
                + "".join(badge(t, where="down") for t in tiers)
                + (f"<span class='fs-note'>{note}</span>" if note else "") + "</div>",
                unsafe_allow_html=True)


def main_row():
    """Place | map | side panel. Each page puts a keyed container in each
    column (fs_col_l / fs_col_m / fs_col_r) and the side panel's blocks in
    fs_r_a / fs_r_b (/ fs_r_c); the stylesheet does the rest — the three
    panels end on one line, and the side panel drops under the map when the
    row (fs_main) is too narrow for three."""
    return st.container(key="fs_main").columns([1.12, 2.5, 1.22], gap="medium")


def place_title(sel, sub: str | None = None) -> None:
    """The selected place's name, with ✕ back to all of Arunachal."""
    n1, n2 = st.columns([5, 1], vertical_alignment="center")
    with n1:
        s = sub if sub is not None else f"{sel['lat']:.4f}°N, {sel['lon']:.4f}°E"
        st.markdown(f"<div class='fs-place'>{_esc(sel['label'])}<small>{s}</small></div>",
                    unsafe_allow_html=True)
    with n2:
        if st.button("✕", key="fs_clear", help="Back to all of Arunachal"):
            st.session_state.pending_place = G.PROMPT
            st.rerun()


def state_title(hint: str = "search a place or click the map") -> None:
    st.markdown(f"<div class='fs-place'>All of Arunachal<small>{hint}</small></div>",
                unsafe_allow_html=True)


def map_title(title: str, *badges: str, layers=()) -> dict:
    """The map card's title row, its badges, and a Layers menu of
    (key, label, default) toggles. Returns {key: on}."""
    t1, t2 = st.columns([6, 1], vertical_alignment="center")
    with t1:
        st.markdown("<div class='map-head' style='padding:0'><div class='mh-dot'></div>"
                    f"<div class='mh-title'>{title}</div>"
                    f"<div style='margin-left:10px;display:flex;gap:6px'>{''.join(badges)}</div>"
                    "</div>", unsafe_allow_html=True)
    out = {}
    with t2:
        with st.popover(":material/layers:", width="stretch", help="Map layers"):
            for key, label, default in layers:
                out[key] = st.toggle(label, value=default, key=key)
    return out


def take_click(out) -> None:
    """A click on the map selects that spot — on every FloodSense page."""
    click = (out or {}).get("last_clicked")
    if click:
        xy = (round(float(click["lat"]), 5), round(float(click["lng"]), 5))
        if xy != st.session_state.get("clicked_xy"):
            st.session_state.clicked_xy = xy
            st.session_state.pending_place = f"{xy[0]:.4f}, {xy[1]:.4f}"
            st.rerun()


def plain_rivers(fg, geo, grid) -> None:
    """Every mapped river, drawn by size, with no gauge colouring — for the
    pages that are not about a day's forecast. Its own cache key: the
    forecast page's segments carry gauge indices, these do not."""
    if not geo.rivers:
        return
    from products.flood.data import load_static
    segs = _river_segments((len(geo.rivers.get("features", [])), "plain"),
                           geo.rivers, grid, load_static()[3], None)
    _draw_rivers(fg, segs, {}, -1)


def sym(kind: str, label: str, color: str = RIVER_OTHER) -> str:
    """One map-legend symbol: "line", "box" (an outline) or "diamond"."""
    svg = {
        "line": f"<svg width='22' height='8'><line x1='0' y1='4' x2='22' y2='4' "
                f"stroke='{color}' stroke-width='2.5'/></svg>",
        "box": f"<svg width='16' height='12'><rect x='1' y='1' width='14' height='10' rx='2' "
               f"fill='none' stroke='{color}' stroke-width='1.5'/></svg>",
        "diamond": "<svg width='12' height='12'><rect x='2' y='2' width='8' height='8' "
                   "transform='rotate(45 6 6)' fill='#dbe7f3' stroke='#4d8dff' "
                   "stroke-width='1.5'/></svg>",
    }[kind]
    return f"<span class='fs-sym'>{svg}{label}</span>"


def legend(names, colors, shares=None, subs=None, tip: str = "", syms: str = "") -> str:
    """Colour chips (with the share of what is shown), an ⓘ, then symbols."""
    chips = "".join(
        f"<div class='lg'><i style='background:{c}'></i>{n}"
        + (f" <span>{subs[j]}</span>" if subs else "")
        + (f"<b>{100*shares[j]:.0f}%</b>" if shares is not None else "") + "</div>"
        for j, (n, c) in enumerate(zip(names, colors)))
    return (f"<div class='fs-legend'>{chips}{_i(tip, 'left') if tip else ''}</div>"
            + (f"<div class='fs-legend' style='margin-top:6px'>{syms}</div>" if syms else ""))


def hero(word: str, value: str, sub: str, when: str, color: str, text: str,
         icon: str, tier: str, more: str = "", bars_html: str = "", grow: bool = False) -> str:
    """The headline card of a page: a word for the level, one big number,
    what and when, and a row of bars. `grow`: it takes the panel's spare
    height, the bars staying at its foot."""
    return (f"<div class='fs-hero{' fs-grow' if grow else ''}' style='--c:{color};--t:{text}'>"
            f"<div class='fs-hero-top'><div class='fs-hero-ic'>{icon}</div>"
            f"<div style='min-width:0;flex:1'><div class='fs-hero-word'>{word}</div>"
            f"<div class='fs-hero-sub'>{sub}</div></div></div>"
            f"<div class='fs-hero-row'><div class='fs-hero-num'>{value}</div>"
            f"<div class='fs-hero-badge'>{badge(tier, more, 'down left')}</div></div>"
            f"<div class='fs-hero-when'>{when}</div>{bars_html}</div>")


def bars(vals, labels, colors, tips, on: int = -1, faded=(), floor: float = 0.0) -> str:
    """A row of small bars (the headline card's): heights relative to the
    largest, or to `floor` when everything is smaller than that."""
    mx = max(max(vals) if len(vals) else 0.0, floor, 1e-12)
    out = []
    for i, (v, lab, col, tip) in enumerate(zip(vals, labels, colors, tips)):
        cls = ("later " if i in faded else "") + ("on" if i == on else "")
        out.append(f"<div class='fs-sb {cls}'><i class='fs-tip' data-tip='{_esc(tip)}' "
                   f"style='height:{5 + 42 * (v / mx):.0f}px;--b:{col}'></i>"
                   f"<span>{lab}</span></div>")
    return f"<div class='fs-spark'>{''.join(out)}</div>"


def hbars(rows, mx: float | None = None) -> str:
    """Horizontal bars: rows of (label, value, shown, colour, tip), scaled to
    the largest value, or to `mx` so separate groups share one scale."""
    mx = mx or max((r[1] for r in rows), default=1.0) or 1.0
    return "".join(
        f"<div class='fs-hb fs-tip right' data-tip='{_esc(tip)}'><div class='fs-hb-l'>{lab}</div>"
        f"<div class='fs-hb-t'><i style='width:{100 * v / mx:.0f}%;background:{col}'></i></div>"
        f"<div class='fs-hb-v'>{shown}</div></div>"
        for lab, v, shown, col, tip in rows)
