"""FloodSense pages.

    Live forecast        the model-based forecast (live.py), fed by the daily run
    Flood-prone ground   WHERE: chance water reaches a spot IF a flood comes —
                         the same calibrated layer the forecast uses
    Catchments           an INPUT: how unusual the rain upstream of each
                         catchment is, not a forecast

Same structure as SlopeSense, and for the same reason: the product is the
FORECAST, and a forecast is only useful somewhere. The other two screens
explain its inputs; neither may contradict it (2026-09-27: the flood-prone
screen still showed the old rule-based index, and the catchments screen the
removed rule-based forecast's numbers — see docs/design/FLOOD_SCREEN_PLAN.md).

All three are dashboards in one style (2026-09-28/29): the shared pieces —
stylesheet, badges for the kinds of number, tiles, header, map title, river
layer — are in ui.py; each page here only arranges its own numbers.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

import core.geo as G
import core.mapping as M
import core.rainfall as RN
import products.flood.model as fm
from core.bundle import load_rain_spine
from core.location import ask_again
from core.settings import map_settings

# Method & limits still exists — the branch at the bottom of this file — but
# is reached only from the ℹ️ popover (see Product.extra_nav in
# products/__init__.py), and shown there disabled: not ready for anyone
# outside the team to see yet.
# "Live forecast" is the model-based forecast (products/flood/live.py), fed by
# the daily run: calibrated river chances + the area outlook, with place
# search and click. The original rule-based screen ("Rain index": flood-prone
# ground x upstream rain, never checked against real floods) was removed on
# 2026-09-25 — two forecasts that could disagree, with the weaker one the more
# usable, only confused things. Flood-prone ground and Catchments stay: they
# explain the inputs rather than compete with the forecast.
VIEWS = [("🎯", "Live forecast"), ("🗺️", "Flood-prone ground"), ("💧", "Catchments")]
# Reached from the ℹ️ popover (products/__init__.py extra_nav), not the sidebar.
METHOD_VIEW = "How to read this forecast"
# Catchments to watch: as many as fit beside the map without the side panel
# running past it (ui.MAP_H).
WATCH_N = 6

# Catchment-wetness ramp — BLUE, deliberately not the green-to-red hazard ramp.
# "A lot of water is coming" and "this is dangerous" are different statements,
# and one ramp for both would merge them.
WET_NAMES = ["Normal", "Above normal", "Wet", "Very wet", "Exceptional"]
WET_COLORS = ["#0b3a5b", "#1565a8", "#2f9fd8", "#7fd4f0", "#d8f6ff"]
WET_CUTS = np.array([0.50, 0.75, 0.90, 0.97], dtype=np.float32)

# WHERE ranges: the chance a spot is under water IF a flood comes nearby.
# Teal, dim to bright — its own ramp: it is neither rain (blue) nor a
# day's forecast (grey to red).
# Capped at "20%+": inside Arunachal the top ranges came true about half as
# often as they say and a terrain correction did not hold (Gate B), so no
# finer class is drawn above 20%.
WHERE_CUTS = np.array([0.02, 0.05, 0.10, 0.20], dtype=np.float32)
WHERE_NAMES = ["2–5%", "5–10%", "10–20%", "20%+"]
WHERE_COLORS = ["#155e63", "#1b8a8f", "#2bb3ad", "#9df0de"]


def _record_note(radar: dict | None, record: dict | None = None) -> str:
    """What the flood record is and how it was verified — from the daily
    snapshot's `method` block (PARKED §0w-§0x), never typed."""
    if not record:
        return ("<b>Floods nobody recorded.</b> The flood record is built from news reports "
                "of floods; remote valleys are thin on news.")
    r = record["by_route"]
    s = (f"<b>Floods nobody recorded.</b> The forecast learns from {record['events']:,} floods "
         f"that were confirmed independently — by a tested radar check ({r.get('radar', 0):,}), "
         f"Google's Global Flood Database ({r.get('gfd', 0):,}) or a river gauge crossing its "
         f"line ({r.get('gauge', 0) + r.get('gauge-xc', 0):,}); some by more than one.")
    if radar:
        s += (f" The radar check correctly says “no flood” on "
              f"{100*radar['flood_free_dates_correct']:.0f}% of flood-free days.")
    s += (f" Of {record['reports']:,} news reports, {record['reports_verified']:,} could be "
          "confirmed; the rest are not disproved — often no satellite passed in time, or the "
          "water drained first — but they are not used. Floods nobody reported or confirmed, "
          "most often short ones in remote valleys, are missing.")
    return s


# The same levels as text on the dark panels, and the ink that reads ON each
# fill (the pale fills need dark ink).
WHERE_WORDS = ["Unlikely", "Some chance", "Exposed", "Very exposed", "Most exposed"]
WHERE_TEXT = ["#8fa3ba", "#4fb0aa", "#2bc2bb", "#46dccf", "#9df0de"]
WET_TEXT = ["#8fb8d8", "#4d9be0", "#2f9fd8", "#7fd4f0", "#d8f6ff"]


def _where_level(w: float) -> int:
    """0 under 2%, then one level per WHERE range (1..4)."""
    return int(np.digitize(w, WHERE_CUTS))


@st.cache_data(show_spinner=False)
def _exposed_towns(n: int, _places, _grid, _prob) -> list[tuple[str, str, float]]:
    """Settlements ranked by the chance water reaches them if a flood comes:
    (search label, shown name, chance), highest first, one per name."""
    out, seen = [], set()
    tw = [p for p in _places if p["kind"] == "town"]
    vals = []
    for p in tw:
        px = _grid.to_px(p["lat"], p["lon"])
        v = float(_prob[px]) if px and np.isfinite(_prob[px]) else 0.0
        vals.append(v)
    for j in np.argsort(-np.asarray(vals)):
        name = tw[j]["label"].split("  (")[0].split(" #")[0]
        if name not in seen:
            seen.add(name)
            out.append((tw[j]["label"], name, float(vals[j])))
        if len(out) == 8:
            break
    return out


@st.cache_data(show_spinner=False)
def _basin_places(n: int, _bid, _places, west, north, dlat, dlon):
    """Each catchment's centre (of its cells on the map) and the settlement
    nearest it, as a name for tables: (lat, lon, name) arrays."""
    ok = _bid > 0
    r, c = np.nonzero(ok)
    b = _bid[ok].astype(np.int64) - 1
    nb = int(_bid.max())
    cnt = np.maximum(np.bincount(b, minlength=nb), 1)
    lat = north - (np.bincount(b, weights=r, minlength=nb) / cnt + 0.5) * dlat
    lon = west + (np.bincount(b, weights=c, minlength=nb) / cnt + 0.5) * dlon
    tw = [p for p in _places if p["kind"] == "town"]
    tl = np.array([p["lat"] for p in tw], np.float32)
    tn = np.array([p["lon"] for p in tw], np.float32)
    names = []
    for la, lo in zip(lat, lon):
        j = int(np.argmin((tl - la) ** 2 + ((tn - lo) * 0.89) ** 2))
        names.append(tw[j]["label"].split("  (")[0].split(" #")[0])
    return lat, lon, names


@st.cache_data(ttl=3600, show_spinner=False)
def _signals(tag: str, _rain, _trig, _rain_pt, _sub, _nxt, _order):
    """Upstream rain (mm) and how unusual it is (percentile), per day and
    catchment, plus each catchment's upstream area — every day at once, so
    the day buttons, the tiles and the charts all read one computation."""
    mm, pct, area = [], [], None
    for i in range(len(_rain)):
        a, p, area = fm.catchment_signal(_rain[i], _trig[i], _rain_pt, _sub, _nxt, _order)
        mm.append(a)
        pct.append(p)
    return np.array(mm), np.array(pct), area


def _day_buttons(prefix: str, names: list[str], vals: list[str], colors: list[str],
                 state_key: str, later_from: int, help_later: str, head: str = "") -> None:
    """The day picker the FloodSense pages share: 4 per row, a coloured top
    edge, later days dashed. `head`: the section title above it, drawn in the
    same element as the colours (an element of its own takes a gap)."""
    css = ""
    for j, col in enumerate(colors):
        css += f".st-key-{prefix}{j} button{{border-top:3px solid {col}!important}}"
        if j >= later_from:
            css += (f".st-key-{prefix}{j} button{{border-left-style:dashed!important;"
                    f"border-right-style:dashed!important;border-bottom-style:dashed!important}}")
    st.markdown(f"<style>{css}</style>{head}", unsafe_allow_html=True)
    for row in range(0, len(names), 4):
        cols = st.columns(4, gap="small")
        for col, j in zip(cols, range(row, min(row + 4, len(names)))):
            with col:
                if st.button(f"{names[j]}  \n**{vals[j]}**", key=f"{prefix}{j}", width="stretch",
                             type="primary" if j == st.session_state[state_key] else "secondary",
                             help=help_later if j >= later_from else None):
                    st.session_state[state_key] = j
                    st.rerun()


def _to_forecast() -> None:
    if st.button("🎯  Open the flood forecast", key="fs_to_forecast", width="stretch"):
        st.session_state.fl_view = VIEWS[0][1]
        st.session_state.pop("map_target", None)
        st.rerun()


# ═════════════════════ FLOOD-PRONE GROUND ════════════════════════════════
def _flood_prone(shell, s, search_row, hand, chan) -> None:
    """The location model (WHERE) as a dashboard: how much ground a flood
    can reach, how the top colours held up in checks, the map, and — for a
    picked place — its own estimate and the terrain it is read from."""
    from products.flood import ui as U
    from products.flood.data import load_where
    from products.flood.live import FLOODABLE_MIN, _nearest_floodable, _where_str

    grid, geo = shell.grid, shell.geo
    st.markdown(U.FS_CSS, unsafe_allow_html=True)
    sel = U.page_head("Flood-prone ground", "If a flood comes, where the water can go", "◆",
                      search_row)
    U.key_row("estimate", "record", note="No rain in it — the same every day")

    prob, wm = load_where()
    wcls = np.zeros(prob.shape, np.uint8)
    ok = np.isfinite(prob)
    wcls[ok] = np.digitize(prob[ok], WHERE_CUTS).astype(np.uint8)
    area = wm["area_km2_in_state"]
    top = wm.get("checked_in_arunachal_top") or []
    n_fl = wm.get("n_floods_trained_on")
    auc, steep = wm["oof_auc_in_arunachal"], wm["oof_auc_steep"]

    tiles = [
        U._tile("Ground a flood can reach", f"{area['0.10']:,.0f}<small>km²</small>",
                "10%+ if a flood comes", "estimate", WHERE_TEXT[3],
                "Area of Arunachal where, if a flood is reported within about 5 km, the chance "
                "of water reaching the spot is 10% or more. Counted on the 100 m model cells.",
                "right"),
        U._tile("Most exposed", f"{area['0.20']:,.0f}<small>km²</small>", "20%+", "estimate",
                WHERE_TEXT[4], "The same, at 20% or more."),
        U._tile("Any chance", f"{area['0.02']:,.0f}<small>km²</small>", "2%+", "estimate", None,
                "Everything the map colours: 2% or more."),
        U._tile("Checked in Arunachal", f"{100*auc:.0f}<small> in 100</small>",
                "flooded ranked above dry", None, None,
                "Inside Arunachal, on floods held out of its training: how often a spot that "
                "went under water was ranked above one that stayed dry."),
        U._tile("On steep ground", f"{100*steep:.0f}<small> in 100</small>",
                "weaker in narrow valleys", None, WHERE_TEXT[1] if steep < 0.75 else None,
                "The same check on steep ground, where valleys are narrow and the land's shape "
                "says less.", "left"),
        U._tile("Floods it learned from", f"{n_fl:,}" if n_fl else "—", "reported floods",
                "record", None, "Reported floods, and where radar images showed new water "
                "around each one.", "left"),
    ]
    st.markdown(U._tiles(tiles, 6), unsafe_allow_html=True)

    px = grid.to_px(sel["lat"], sel["lon"]) if sel else None
    cl, cm, cr = U.main_row()

    # ── left: the place, or how the top colours held up ─────────────────
    with cl, st.container(key="fs_col_l"):
        if not sel:
            U.state_title()
            if top:
                mx = max(b["said"] for b in top)
                html_ = U._sec("How the top colours held up", U.badge("record", where="right"))
                for b in top:
                    rng = f"{100*b['p_lo']:.0f}–{100*b['p_hi']:.0f}%"
                    html_ += (f"<div class='fs-tile-l' style='margin-top:6px'>Spots given {rng}"
                              "</div>" + U.hbars([
                                  ("said", b["said"], f"{100*b['said']:.0f}%", WHERE_COLORS[2],
                                   f"The map said {100*b['said']:.0f}% on average."),
                                  ("went under", b["happened"], f"{100*b['happened']:.0f}%",
                                   "#cfd8e3", f"In past checks inside Arunachal, "
                                   f"{100*b['happened']:.0f}% of these spots went under water "
                                   "when a flood came.")], mx))
                html_ += (f"<span class='fs-pill' style='--c:{WHERE_TEXT[4]}'>So anything above "
                          f"20% shows as “20%+”</span> "
                          + U._i("A correction by terrain (open plain versus valley) was tested "
                                 "and did not hold up: how much ground a flood covers varies too "
                                 "much from one flood to the next. Below about "
                                 f"{100*top[0]['p_lo']:.0f}% the numbers roughly match what "
                                 "happened.", "right"))
                st.markdown(html_, unsafe_allow_html=True)
            towns = _exposed_towns(len(shell.places), shell.places, grid, prob)
            if towns:
                css = "".join(f".st-key-fs_pick_{i} button{{border-left:4px solid "
                              f"{WHERE_COLORS[max(_where_level(v) - 1, 0)]}!important}}"
                              for i, (_, _, v) in enumerate(towns[:5]))
                st.markdown(f"<style>{css}</style><div style='height:10px'></div>"
                            + U._sec("Most exposed places", U.badge("estimate", where="right")),
                            unsafe_allow_html=True)
                for i, (label, name, v) in enumerate(towns[:5]):
                    if st.button(f"{name}  ·  **{_where_str(v)}**", key=f"fs_pick_{i}",
                                 width="stretch", help=f"Open {name}"):
                        st.session_state.pending_place = label
                        st.rerun()
        else:
            U.place_title(sel)
            if px is None:
                st.markdown("<div class='fs-empty'><b>Outside the mapped area</b><br>This map "
                            "covers Arunachal Pradesh only.</div>", unsafe_allow_html=True)
            else:
                r, c = px
                w = float(prob[r, c]) if np.isfinite(prob[r, c]) else 0.0
                near = _nearest_floodable(prob, r, c, grid.cell_km)
                lvl = _where_level(w)
                w_chk = w if (w >= FLOODABLE_MIN or not near) else near[1]
                chk = next((b for b in top if b["p_lo"] <= w_chk < b["p_hi"]
                            or (b is top[-1] and w_chk >= b["p_lo"])), None)
                meter = (f"<div class='fs-meter' style='background:linear-gradient(90deg,"
                         f"#243240,{WHERE_COLORS[0]} 7%,{WHERE_COLORS[1]} 17%,{WHERE_COLORS[2]} 33%,"
                         f"{WHERE_COLORS[3]} 67%,{WHERE_COLORS[3]})'>"
                         f"<i style='left:{min(w, 0.30) / 0.30 * 100:.0f}%'></i></div>"
                         "<div class='fs-meter-l'><span>0%</span><span>10%</span><span>20%</span>"
                         "<span>30%</span></div>")
                st.markdown(U.hero(WHERE_WORDS[lvl], _where_str(w),
                                   "if a flood comes within ~5 km",
                                   "a property of the ground — the same every day",
                                   WHERE_COLORS[max(lvl - 1, 0)] if lvl else "#6b7a8c",
                                   WHERE_TEXT[lvl], "🌊", "estimate", bars_html=meter),
                            unsafe_allow_html=True)
                h = float(hand[r, c])
                k2 = float(chan[r, c])
                t = [U._tile("Height above river", f"{h:,.0f}<small> m</small>" if h < 2000 else
                             "—", "lowest ground here", None, None,
                             "How high the lowest ground in this ~500 m square sits above the "
                             "nearest river channel (rivers draining 100 km² or more). One of the "
                             "things the estimate is read from.", "right"),
                     U._tile("River size", f"{k2:,.0f}<small> km²</small>" if k2 < 65535 else "—",
                             "drains to the river here", None, None,
                             "The area that drains into the river channel in this square. "
                             "Another thing the estimate is read from.", "left")]
                if w >= FLOODABLE_MIN:
                    t.append(U._tile("Low ground", "Here", "a flood can reach this spot",
                                     "estimate", WHERE_TEXT[3], where="right"))
                elif near:
                    t.append(U._tile("Nearest low ground", f"{near[0]:.1f}<small> km</small>",
                                     f"{_where_str(near[1])} if a flood comes", "estimate",
                                     WHERE_TEXT[_where_level(near[1])],
                                     "This spot is raised ground. A town often sits on a terrace "
                                     "just above its river — the bank nearby can be exposed when "
                                     "the town is not.", "right"))
                else:
                    t.append(U._tile("Nearest low ground", "None", "within ~10 km", "estimate",
                                     "var(--dim)", where="right"))
                if chk:
                    like = "like the low ground nearby" if w_chk != w else "like this one"
                    t.append(U._tile("In past checks", f"~{100*chk['happened']:.0f}%",
                                     f"went under, of spots {like} "
                                     f"({100*chk['p_lo']:.0f}–{100*chk['p_hi']:.0f}%)", "record",
                                     None, "Inside Arunachal, when a flood came, this share of "
                                     "spots in the same range went under water — well under what "
                                     "the colours say.", "left"))
                elif top:
                    t.append(U._tile("In past checks", "≈ as said",
                                     f"below ~{100*top[0]['p_lo']:.0f}% it held up", "record",
                                     None, "Below this range the numbers roughly matched what "
                                     "happened.", "left"))
                st.markdown(U._tiles(t, 2, grow=True), unsafe_allow_html=True)

    # ── centre: the map ──────────────────────────────────────────────────
    with cm, st.container(key="fs_col_m"):
        with st.container(border=True, key="fs_mapcard"):
            lay = U.map_title("If a flood comes · where water can reach",
                              U.badge("estimate", "Colour: the chance each spot is under water "
                                      "if a flood is reported within about 5 km.", "down"),
                              layers=[("fp_lyr_rivers", "Rivers", True)])
            box = st.container(height=U.MAP_H + 8, border=False, key="map_shell")
            m = M.base_map(grid, s)

            def _extras(fg):
                if lay.get("fp_lyr_rivers"):
                    U.plain_rivers(fg, geo, grid)

            fg = M.overlay_group(
                grid, replace(s, rivers=False), geo,
                img=None if s.bare else M.rgba_overlay(wcls, WHERE_COLORS),
                districts=s.districts,
                marker=(sel["lat"], sel["lon"], sel["label"]) if sel else None, extra=_extras)
            fly_c, fly_z = M.fly_to(sel, 11)
            with box:
                out = st_folium(m, height=U.MAP_H, use_container_width=True, pixelated=True,
                                returned_objects=["last_clicked"], feature_group_to_add=fg,
                                center=fly_c, zoom=fly_z, key="flsmap")
            U.take_click(out)
            if s.bare:
                M.legend_strip([], [], bare=True)
            else:
                shown = wcls > 0
                shares = [float((wcls[shown] == i).mean()) if shown.any() else 0
                          for i in range(1, len(WHERE_NAMES) + 1)]
                st.markdown(U.legend(
                    WHERE_WORDS[1:], WHERE_COLORS, shares, WHERE_NAMES,
                    tip="If a flood is reported within about 5 km, the chance water reaches each "
                        "spot. Blank: under 2%. Each ~550 m square shows its highest 100 m "
                        "spot. The share is of the ground coloured. No rain in this map.",
                    syms=U.sym("line", "river, by size")), unsafe_allow_html=True)

    # ── right: ground by level, what it reads, the forecast ───────────────
    with cr, st.container(key="fs_col_r"):
        bands = [("2–5%", area["0.02"] - area["0.05"], WHERE_COLORS[0]),
                 ("5–10%", area["0.05"] - area["0.10"], WHERE_COLORS[1]),
                 ("10–20%", area["0.10"] - area["0.20"], WHERE_COLORS[2]),
                 ("20%+", area["0.20"], WHERE_COLORS[3])]
        with st.container(key="fs_r_a"):
            st.markdown(U._sec("Ground by level", U.badge("estimate", where="left"), note="km²")
                        + U.hbars([(lab, v, f"{v:,.0f}", col,
                                    f"{v:,.0f} km² of Arunachal is in the {lab} range.")
                                   for lab, v, col in bands]), unsafe_allow_html=True)
        teal = WHERE_TEXT[3]
        with st.container(key="fs_r_b"):
            st.markdown(
                U._sec("What it is read from") + "<div class='fs-rows fs-grow'>"
                + U._row("↕", teal, "Height above the river",
                         U._i("How high the spot sits above the nearest river channel.", "left"))
                + U._row("◍", teal, "Size of that river",
                         U._i("How much land drains into that river.", "left"))
                + U._row("↔", teal, "Distance to it",
                         U._i("How far the spot is from the channel.", "left"))
                + U._row("⌒", teal, "How closed-in the valley is",
                         U._i("Open plains spread a flood wide; narrow valleys keep it close to "
                              "the river.", "left"))
                + U._row("◷", U.TIERS["record"][2],
                         f"{n_fl:,} reported floods" if n_fl else "Reported floods",
                         U._i("Learned from where radar images showed new water around reported "
                              "floods.", "left")) + "</div>",
                unsafe_allow_html=True)
        with st.container(key="fs_r_c"):
            st.markdown(U._sec("Today's chance", U.badge("outlook", where="left"),
                               U.badge("forecast", where="left"))
                        + "<div class='fs-foot' style='margin:0 0 8px'>This map has no rain in "
                          "it. The forecast adds when, and uses this same layer for where.</div>",
                        unsafe_allow_html=True)
            _to_forecast()

    with st.expander("📖  How to read this map"):
        st.markdown(
            "**What this map is.** Not a forecast — there is no rain in it. It answers one "
            "question for every spot: *if a flood happens nearby, how likely is the water to "
            "reach here?* The answer comes from the shape of the land — how high the spot sits "
            "above the nearest river, how big that river is and how far away, and how "
            "closed-in the valley is — learned from "
            + (f"{n_fl:,} " if n_fl else "") + "reported floods, from where radar images showed "
            "new water around them. The Live forecast adds *when*, and uses this same layer to "
            "decide which ground to colour.")
        if top:
            checked = "; ".join(
                f"ground given {100*b['p_lo']:.0f}–{100*b['p_hi']:.0f}% went under water about "
                f"{100*b['happened']:.0f}% of the time" for b in top)
            st.markdown(
                "**Read the brightest colours as “most exposed”, not as exact odds.** Checked "
                f"against past floods inside Arunachal: {checked} — well under what the colours "
                "say. A correction by terrain (open plain versus valley) was tested and did not "
                "hold up: how much ground a flood covers varies too much from one flood to the "
                "next. So anything above 20% is shown as “20%+”. Below about "
                f"{100*top[0]['p_lo']:.0f}% the numbers roughly match what happened.")


# ═════════════════════ CATCHMENTS ════════════════════════════════════════
def _catchments(shell, s, search_row, met, bid, nxt, order, sub_area, rain_pt, pts, quant,
                rain_ok) -> None:
    """An INPUT screen as a dashboard: how unusual the rain falling upstream
    of each catchment is, day by day — the rain the forecast turns into
    flood chances, shown here as rain, never as a chance."""
    from products.flood import ui as U

    grid, geo = shell.grid, shell.geo
    st.markdown(U.FS_CSS, unsafe_allow_html=True)
    sel = U.page_head("Catchments", "Rain upstream — what feeds the forecast", "💧", search_row)
    U.key_row("input", note="Not a flood chance")

    fx = RN.load_forecast(tuple(pts["lat"]), tuple(pts["lon"])) if rain_ok else None
    if not rain_ok:
        st.error("**The catchment-to-rain-point table is out of date.** It was built for a "
                 "different set of rain points, so each catchment would show another place's "
                 "rain. Rebuild it with "
                 "`python scripts/build/build_flood_layers.py --rain-points-only`. "
                 "No rain is shown until then.")
    elif fx is None:
        st.warning("Live rainfall is unavailable, so no rain is shown.")

    n_b = int(bid.max())
    MM = PCT = AREA = None
    days, fut, di = [], [], None
    if fx is not None:
        days, rain = fx
        days = [str(d) for d in days]
        trig = RN.trigger_series(rain, quant)
        fut = RN.forecast_days(days)
        MM, PCT, AREA = _signals(f"{days[0]}|{days[-1]}|{float(rain.sum()):.1f}", rain, trig,
                                 rain_pt, sub_area, nxt, order)
        if st.session_state.get("flc_day") not in range(len(fut)):
            st.session_state.flc_day = 0
        di = fut[st.session_state.flc_day]
    lat_b, lon_b, name_b = _basin_places(n_b, bid, shell.places, grid.west, grid.north,
                                         grid.dlat, grid.dlon)

    def day_name(i: int) -> str:
        d = datetime.fromisoformat(days[i]).date()
        return "Today" if d == date.today() else d.strftime("%a %d")

    # "very wet or wetter" — ⚠️ a SHARE, never a maximum. The maximum anomaly
    # over 1,680 catchments is close to 1.0 on an ordinary day, the same trap
    # as the landslide strip that once read 0.99 everywhere: the max of many
    # roughly uniform draws carries almost no information about the weather.
    # (Until 2026-09-27 this screen quoted the removed rule-based forecast.)
    share = ([float(np.mean(PCT[i] >= WET_CUTS[2])) for i in fut] if PCT is not None else [])

    tiles = []
    if PCT is not None:
        p, j = PCT[di], st.session_state.flc_day
        wet_b = int(np.nanargmax(MM[di]))
        tiles += [
            U._tile("Very wet or wetter", f"{100*share[j]:.0f}%",
                    f"of {n_b:,} catchments · {day_name(di)}", "input", WET_TEXT[3],
                    "Catchments whose upstream rain is in their own wettest 10% of days for "
                    "the time of year.", "right"),
            U._tile("Exceptional", f"{int(np.sum(p >= WET_CUTS[3]))}",
                    f"catchments · {day_name(di)}", "input", WET_TEXT[4],
                    "Upstream rain in their own wettest 3% of days."),
            U._tile("Average rain", f"{float(np.mean(rain[di])):.0f}<small> mm</small>",
                    f"over {len(pts['lat'])} points · {day_name(di)}", "input", None,
                    "The plain average of that day's rain at the rain points."),
            U._tile("Wettest upstream", f"{float(MM[di][wet_b]):.0f}<small> mm</small>",
                    f"near {name_b[wet_b]}", "input", WET_TEXT[3],
                    "The highest mean rain over everything draining to one catchment, that day."),
        ]
    cat = met.get("catchments") or {}
    tiles += [
        U._tile("Catchments", f"{n_b:,}", f"HydroSHEDS level {cat.get('level', 12)}", None, None,
                "River catchments from HydroSHEDS HydroBASINS. Rain is carried down each "
                "one's river to everything below it.", "left"),
        U._tile("Rain points", f"{len(pts['lat'])}", "~22 km apart · Open-Meteo", None, None,
                "Live rain is read at these points, 10 days back and 7 ahead, and scored against "
                "16 years of the same source at the same point.", "left"),
    ]
    st.markdown(U._tiles(tiles, len(tiles)), unsafe_allow_html=True)

    px = grid.to_px(sel["lat"], sel["lon"]) if sel else None
    b0 = (int(bid[px]) - 1) if (px is not None and bid[px] > 0) else None
    cl, cm, cr = U.main_row()

    # ── left: the place's upstream rain, or the state's week ──────────────
    with cl, st.container(key="fs_col_l"):
        if MM is None:
            (U.place_title(sel) if sel else U.state_title())
            st.markdown("<div class='fs-empty'>No live rain right now.</div>",
                        unsafe_allow_html=True)
        elif not sel:
            U.state_title()
            j = st.session_state.flc_day
            st.markdown(U.hero(
                "Very wet or wetter", f"{100*share[j]:.0f}%",
                "of catchments, for the time of year", _long_day(days[di]),
                WET_COLORS[3], WET_TEXT[3], "💧", "input",
                "Upstream rain in each catchment's own wettest 10% of days.",
                U.bars(share, [datetime.fromisoformat(days[i]).day for i in fut],
                       [WET_COLORS[3]] * len(fut),
                       [f"{day_name(i)}: {100*v:.0f}% very wet or wetter" for i, v in
                        zip(fut, share)], on=j, faded=range(3, len(fut)), floor=0.10)),
                unsafe_allow_html=True)
            st.markdown(U._sec("Arunachal average rain", U.badge("input", where="right"),
                               note="mm/day"), unsafe_allow_html=True)
            mean_mm = [float(np.mean(rain[i])) for i in range(len(days))]
            st.altair_chart(_rain_chart(days, mean_mm, di, fut[0]), width="stretch")
            st.markdown(U._tiles([
                U._tile("Last 3 days", f"{sum(mean_mm[:fut[0]][-3:]):.0f}<small> mm</small>",
                        "past · state average", "input", None,
                        "Rain over the three days before today, averaged over the rain points.",
                        "right"),
                U._tile("Next 3 days", f"{sum(mean_mm[fut[0]:][:3]):.0f}<small> mm</small>",
                        "forecast · state average", "input", None,
                        "Forecast rain for today and the two days after, averaged over the rain "
                        "points.", "left")], 2, grow=True), unsafe_allow_html=True)
        else:
            U.place_title(sel)
            if b0 is None:
                st.markdown("<div class='fs-empty'>This spot is outside the mapped "
                            "catchments.</div>", unsafe_allow_html=True)
            else:
                v, p = float(MM[di][b0]), float(PCT[di][b0])
                k = int(np.digitize(p, WET_CUTS)) if np.isfinite(p) else 0
                vals = [float(MM[i][b0]) for i in range(len(days))]
                st.markdown(U.hero(
                    f"{WET_NAMES[k]} upstream", f"{v:.0f}<small style='font-size:1.1rem'> mm"
                    "</small>", "mean rain over everything draining here", _long_day(days[di]),
                    WET_COLORS[max(k, 2)], WET_TEXT[k], "💧", "input",
                    "How unusual the rain is for this catchment is what the forecast reads — "
                    "not the millimetres themselves.",
                    U.bars(vals, [datetime.fromisoformat(d).day for d in days],
                           ["#7fd4f0"] * len(days),
                           [f"{day_name(i)}: {x:.1f} mm" + (" (forecast)" if i >= fut[0] else "")
                            for i, x in enumerate(vals)], on=di,
                           faded=range(fut[0], len(days)), floor=5.0)),
                    unsafe_allow_html=True)
                past = [x for i, x in enumerate(vals) if i < fut[0]]
                ahead = vals[fut[0]:]
                st.markdown(U._tiles([
                    U._tile("For the time of year", f"{100*p:.0f}<small>th</small>" if
                            np.isfinite(p) else "—", "percentile, that day", "input", WET_TEXT[k],
                            "Where this upstream rain (its 3- and 7-day totals) sits among 16 "
                            "years of this catchment's own days — the number the forecast "
                            "reads.", "right"),
                    U._tile("Upstream area", f"{float(AREA[b0]):,.0f}<small> km²</small>",
                            "draining to here", None, None,
                            "Everything that drains to this catchment, including land beyond the "
                            "state border where a river rises there.", "left"),
                    U._tile("Last 3 days", f"{sum(past[-3:]):.0f}<small> mm</small>", "past",
                            "input", None, where="right"),
                    U._tile("Next 3 days", f"{sum(ahead[:3]):.0f}<small> mm</small>",
                            "forecast rain", "input", None, where="left")], 2, grow=True),
                    unsafe_allow_html=True)

    # ── centre: the map ──────────────────────────────────────────────────
    with cm, st.container(key="fs_col_m"):
        with st.container(border=True, key="fs_mapcard"):
            when = _long_day(days[di]) if di is not None else ""
            lay = U.map_title(f"Upstream rain vs normal{' · ' + when if when else ''}",
                              U.badge("input", "Colour: how unusual the rain upstream of each "
                                      "catchment is for it — not millimetres.", "down"),
                              layers=[("fc_lyr_rivers", "Rivers", True),
                                      ("fc_lyr_catch", "Area draining to the place", True)])
            box = st.container(height=U.MAP_H + 8, border=False, key="map_shell")
            m = M.base_map(grid, s)
            img = None
            if not s.bare and PCT is not None:
                wr = np.zeros(bid.shape, np.uint8)
                ok = bid > 0
                wr[ok] = (np.digitize(PCT[di][bid[ok] - 1], WET_CUTS) + 1).astype(np.uint8)
                img = M.rgba_overlay(wr, WET_COLORS)
                if b0 is not None and lay.get("fc_lyr_catch"):
                    from products.flood.ui import _upstream
                    _, edge = _upstream(b0)
                    img[edge] = [255, 214, 102, 240]

            def _extras(fg):
                if lay.get("fc_lyr_rivers"):
                    U.plain_rivers(fg, geo, grid)

            fg = M.overlay_group(grid, replace(s, rivers=False), geo, img=img,
                                 districts=s.districts,
                                 marker=(sel["lat"], sel["lon"], sel["label"]) if sel else None,
                                 extra=_extras)
            fly_c, fly_z = M.fly_to(sel, 10)
            with box:
                out = st_folium(m, height=U.MAP_H, use_container_width=True, pixelated=True,
                                returned_objects=["last_clicked"], feature_group_to_add=fg,
                                center=fly_c, zoom=fly_z, key="flcmap")
            U.take_click(out)
            if s.bare:
                M.legend_strip([], [], bare=True)
            else:
                shares = None
                if PCT is not None:
                    cls_b = np.digitize(PCT[di], WET_CUTS)
                    shares = [float(np.mean(cls_b == i)) for i in range(len(WET_NAMES))]
                st.markdown(U.legend(
                    WET_NAMES, WET_COLORS, shares,
                    tip="How unusual the rain falling upstream of each catchment is for that "
                        "catchment — not millimetres, not a river level, and not a flood chance. "
                        "The share is of the 1,680 catchments.",
                    syms=U.sym("line", "river, by size")
                    + (U.sym("box", "drains to the place", "#ffd666")
                       if b0 is not None and lay.get("fc_lyr_catch") else "")),
                    unsafe_allow_html=True)

    # ── right: the day picker and the catchments to watch ─────────────────
    with cr, st.container(key="fs_col_r"):
        if PCT is not None:
            with st.container(key="fs_r_a"):
                _day_buttons("flc_d", [day_name(i) for i in fut],
                             [f"{100*v:.0f}%" for v in share], [WET_COLORS[3]] * len(fut),
                             "flc_day", 3, "Less sure: forecast rain 4–7 days ahead",
                             head=U._sec("7 days", U.badge("input", where="left"),
                                         note="share very wet or wetter"))
            p, mmv = PCT[di], MM[di]
            order_b = sorted(range(n_b), key=lambda b: (-(p[b] if np.isfinite(p[b]) else -1),
                                                        -mmv[b]))
            with st.container(key="fs_r_b"):
                st.markdown(U._sec("Catchments to watch", U.badge("input", where="left"),
                                   note=day_name(di)), unsafe_allow_html=True)
                css, seen, n = "", set(), 0
                for b in order_b:
                    if name_b[b] in seen:
                        continue
                    seen.add(name_b[b])
                    k = int(np.digitize(p[b], WET_CUTS))
                    css += (f".st-key-fs_pick_{n} button{{border-left:4px solid "
                            f"{WET_COLORS[k]}!important}}")
                    if st.button(f"{name_b[b]}  ·  **{mmv[b]:.0f} mm**  ·  {WET_NAMES[k]}",
                                 key=f"fs_pick_{n}", width="stretch",
                                 help=f"Upstream {float(AREA[b]):,.0f} km² · for the time of "
                                      f"year: {100*p[b]:.0f}th percentile. Click to open."):
                        st.session_state.pending_place = f"{lat_b[b]:.4f}, {lon_b[b]:.4f}"
                        st.rerun()
                    n += 1
                    if n == WATCH_N:
                        break
                st.markdown(f"<style>{css}</style>"
                            "<div class='fs-foot'>Ranked by how unusual, then by millimetres "
                            + U._i("Each catchment is named after the settlement nearest its "
                                   "middle. Millimetres: mean rain that day over everything "
                                   "draining to it.", "left") + "</div>", unsafe_allow_html=True)
        with st.container(key="fs_r_c"):
            st.markdown(U._sec("Flood chance", U.badge("outlook", where="left"),
                               U.badge("forecast", where="left"))
                        + "<div class='fs-foot' style='margin:0 0 8px'>The forecast turns this "
                          "rain — with local rain and the shape of the land — into flood "
                          "chances.</div>", unsafe_allow_html=True)
            _to_forecast()

    with st.expander("📖  How to read this page"):
        st.markdown(
            "**What it shows.** For each river catchment, how unusual the rain falling "
            "upstream of it is — everything that drains into it, carried down the river "
            "network — scored against that catchment's own history. A river rises on the "
            "rain that falls anywhere upstream, not just where it is.\n\n"
            "**Why not millimetres.** Arunachal gets from about 800 to over 4,000 mm of rain "
            "a year. 30 mm in three days is an ordinary week in one valley and a soaking on "
            "the northern crest, so each catchment is compared with itself.\n\n"
            "**What it is not.** Not a flood chance and not a river level. The Live forecast "
            "turns this rain — with local rain and the shape of the land — into flood "
            "chances, and checks them against river gauges.")


def _long_day(d: str) -> str:
    dd = datetime.fromisoformat(d).date()
    return ("Today · " if dd == date.today() else "") + dd.strftime("%A %d %b")


def _rain_chart(days: list[str], vals: list[float], di: int, first_future: int):
    """Daily rain, past solid and forecast faded, the chosen day outlined.
    Its height is what makes the left panel about as tall as the map."""
    import altair as alt
    df = pd.DataFrame({"date": pd.to_datetime(days), "mm": vals,
                       "kind": ["past" if i < first_future else "forecast"
                                for i in range(len(days))],
                       "on": [i == di for i in range(len(days))]})
    bars_ = (alt.Chart(df).mark_bar(color="#7fd4f0", cornerRadiusTopLeft=2,
                                    cornerRadiusTopRight=2)
             .encode(x=alt.X("date:T", title=None, axis=alt.Axis(format="%d", labelAngle=0)),
                     y=alt.Y("mm:Q", title=None),
                     opacity=alt.condition("datum.kind == 'past'", alt.value(1.0),
                                           alt.value(0.42)),
                     stroke=alt.condition("datum.on", alt.value("#e5edf5"), alt.value(None)),
                     tooltip=[alt.Tooltip("date:T", title="day", format="%a %d %b"),
                              alt.Tooltip("mm:Q", title="mm", format=".1f"),
                              alt.Tooltip("kind:N", title="")]))
    return (bars_.properties(height=185, background="transparent")
            .configure_axis(labelColor="#8b95a3", titleColor="#8b95a3",
                            gridColor="#8b95a333", domainColor="#8b95a366",
                            tickColor="#8b95a366")
            .configure_view(strokeWidth=0))


def render(shell) -> None:
    from products.flood.data import (available, catchment_points, load_catchments,
                                     load_static, load_where)

    PLACES, PLACE_IDX, LOOKUP = shell.places, shell.loc.place_idx, shell.lookup

    if not available():
        st.error("**The flood bundle is missing.** Run "
                 "`python scripts/build/build_flood_layers.py` to build it.")
        return

    FCLS, FIDX, HAND, CHAN_KM2, FRAC, MET = load_static()
    BID, NEXT_DOWN, ORDER, UP_AREA, SUB_AREA, RAIN_PT = load_catchments()
    PTS, QUANT = load_rain_spine()
    # The catchment -> rain point table holds POSITIONS in points.json. Built
    # for a different set of points, every catchment reads another place's
    # rain — which happened from 2026-09-22 (97 -> 219 points) to 2026-09-27.
    RAIN_OK = (catchment_points() == len(PTS["lat"])
               and int(RAIN_PT.max()) < len(PTS["lat"]))

    if "fl_view" not in st.session_state:
        st.session_state.fl_view = VIEWS[0][1]
    elif st.session_state.fl_view == "Method & limits":
        # renamed 2026-09-27 — a session left on the old page lands on the new
        st.session_state.fl_view = METHOD_VIEW
    elif st.session_state.fl_view in ("Forecast", "Rain index"):
        # screens removed 2026-09-25 — a session left on one lands on the forecast
        st.session_state.fl_view = VIEWS[0][1]

    with st.sidebar:
        for icon, label in VIEWS:
            active = st.session_state.fl_view == label
            if st.button(f"{icon}  {label}", key=f"flnav_{label}", width="stretch",
                         type="primary" if active else "secondary"):
                if not active:
                    st.session_state.fl_view = label
                    # each page has its own map: let it fly to the place
                    st.session_state.pop("map_target", None)
                    st.rerun()
        view = st.session_state.fl_view
        st.divider()
        s = map_settings(
            opacity_label="Flood overlay opacity",
            roads_help="Roads crossing floodplain are where a flood cuts access.",
            rivers_help="The mapped river stems. The blue line is the channel this "
                        "layer measures height above.",
            # every FloodSense map draws its own rivers, with its own Layers menu
            rivers_toggle=False)

    def search_row():
        """Same selection as SlopeSense, and the SAME session key on purpose —
        a place searched in one module is still selected in the other."""
        s1, s2, s3 = st.columns([4.2, 1.3, 1.05], vertical_alignment="bottom")
        with s2:
            if st.button("📍 My location", width="stretch",
                         help="Ask the browser where you are. Only used if you "
                              "are inside Arunachal Pradesh."):
                ask_again()
                st.rerun()
        with s3:
            if st.button("⌖ Recentre", width="stretch",
                         help="Snap the map back to the selected location."):
                st.session_state.recentre = st.session_state.get("recentre", 0) + 1
                st.rerun()
        with s1:
            options = [G.PROMPT] + [p["label"] for p in PLACES]
            cur = st.session_state.get("search")
            if cur and cur not in PLACE_IDX and cur != G.PROMPT:
                options.insert(1, cur)
            st.selectbox("Location", options, key="search",
                         accept_new_options=True, label_visibility="collapsed",
                         help=f"{len(PLACES):,} towns, villages and districts — "
                              "or type coordinates such as 27.09, 93.61")
        return G.resolve(st.session_state.search, PLACES, LOOKUP)

    # ═════════════════════ FORECAST ══════════════════════════════════════
    if view == "Live forecast":
        from products.flood import live
        live.render(shell, s, search_row)

    # ═════════════════════ FLOOD-PRONE GROUND ════════════════════════════
    # The calibrated location model (WHERE) — the SAME layer the live forecast
    # uses to decide what counts as low ground. Until 2026-09-27 this screen
    # showed the old rule-based index (floodprone.npz, never checked against
    # real floods), so the app carried two "where water goes" maps that could
    # disagree. That file still ships, unused on screen, for comparison.
    # Made over as a dashboard on 2026-09-29 (_flood_prone above).
    elif view == "Flood-prone ground":
        _flood_prone(shell, s, search_row, HAND, CHAN_KM2)

    # ═════════════════════ CATCHMENTS ════════════════════════════════════
    # An INPUT screen: how unusual the rain upstream of each catchment is. It
    # used to end with the removed rule-based forecast's "large enough to
    # forecast / watch only" split and a note that gauges were missing —
    # both out of date since the model-based forecast and the 32 gauges.
    # Live rain is fetched only here: the forecast screen reads the daily
    # run's snapshot and never needs it on open. Made over 2026-09-29.
    elif view == "Catchments":
        _catchments(shell, s, search_row, MET, BID, NEXT_DOWN, ORDER, SUB_AREA, RAIN_PT,
                    PTS, QUANT, RAIN_OK)

    # ═════════════════════ HOW TO READ THIS FORECAST ═════════════════════
    # Reached from the ℹ️ popover. Every number on it is read from the files
    # the daily run writes (live_forecast.json, floodprob.json, the gauge
    # assets) — nothing typed — so it cannot drift from what it describes.
    # It replaced "Method & limits", which described the removed rule-based
    # index (2026-09-27, FLOOD_SCREEN_PLAN.md Phase 9).
    else:
        import json as _json
        from products.flood import live
        from products.flood.data import DIR as _DIR
        snap = (_json.loads((_DIR / "live_forecast.json").read_text())
                if (_DIR / "live_forecast.json").exists() else {})
        nh, mf = snap.get("near_here") or {}, snap.get("method") or {}
        _, wm = load_where()
        glink = (_json.loads((_DIR / "gauge_link.json").read_text())
                 if (_DIR / "gauge_link.json").exists() else {})
        glev = (_json.loads((_DIR / "gauge_levels.json").read_text())
                if (_DIR / "gauge_levels.json").exists() else {})
        me, by = nh.get("measured_error") or {}, nh.get("measured_by_level") or {}

        st.markdown("#### How to read this forecast")
        st.markdown("<div class='strip-label'>Three numbers, each with its own meaning. "
                    "They are never multiplied together on screen.</div>",
                    unsafe_allow_html=True)

        st.markdown("##### 1 · Flood chance near here — approximate")
        body = ("The chance of a flood within about 10 km of a place, for each day and over "
                "the next 7 days. The same kind of number for every place in the state. "
                "It is worked out from the forecast rain there and upstream and the shape of "
                "the land — and, on flat ground only, how wet the soil already is — and tuned "
                "to the flood records of the latest complete years.")
        # the years it learns from, read from the model's own record — they
        # moved 2015 -> 2003 on 2026-09-29 (OLDER_FLOODS_TEST.md)
        learned = live.learned_years(snap)
        if learned:
            body += f" It learned which rain brings floods from every verified flood of {learned}."
        sw, sw_today = mf.get("soil"), snap.get("soil_wetness") or {}
        if sw and sw.get("passed"):
            body += (f"\n\n**Soil wetness, flat ground only:** on plains and valley floors, "
                     f"where water collects over days, soaked ground floods sooner. Tested on "
                     f"{sw['test_years']} floods it had never seen, using soil readings "
                     f"{sw['lag_days']} days old (the newest always available), it picked the "
                     f"right flood days about {100*sw['flat_gain']:.0f} more time in 100 on "
                     f"flat ground and {100*sw['arunachal_gain']:.0f} more across Arunachal. On "
                     "steep ground it made things worse — floods there are sudden, from one "
                     "downpour — so it is not used there"
                     + ("; nor for landslides, where it did not help either." if
                        sw.get("landslides_helped") is False else "."))
            if sw_today and not sw_today.get("used", True):
                body += " **Today the soil readings could not be fetched, so flat ground uses rain only.**"
        if me:
            body += (f"\n\n**How it did on floods it had never seen (2023–25):** it picked "
                     f"riskier places and weeks right about {100*me['ranking_auc']:.0f} times "
                     f"in 100. But in the chance ranges where most floods fell, the number "
                     f"that really happened was between {me['happened_over_said_low']:.1f}× and "
                     f"{me['happened_over_said_high']:.0f}× what it said."
                     f"{live.high_said_more(me)} So it did not pass "
                     "the strict test set in advance, and is shown as approximate. The reason "
                     "is in the flood record itself: how many floods get recorded changes from "
                     "year to year — more news coverage, more satellite passes — much more than "
                     "the rain explains.")
        if by:
            on, off = by.get("on_record", {}), by.get("none_on_record", {})
            if on and off:
                # every reading here follows the measured numbers — none is
                # typed as a fact (OLDER_FLOODS_TEST.md §1)
                ra, rb = on["happened_over_said"], off["happened_over_said"]
                aa, ab = on.get("auc"), off.get("auc")
                both = aa is not None and ab is not None
                since = (nh.get("evidence_period") or "").rsplit(", ", 1)[-1][:4]
                body += (f"\n\n**Floods on record near a place** (counted since "
                         f"{since if since.isdigit() else 2015}) "
                         + ("do not make its number more accurate — the test found about the "
                            "same ranking everywhere. They "
                            if both and abs(aa - ab) <= 0.03 else
                            f"change how well it ranks (right about {100*aa:.0f} in 100 where "
                            f"floods are on record, {100*ab:.0f} where none are), and "
                            if both else "")
                         + f"change its level: where floods are on record, about {ra:.1f}× as "
                         "many were recorded as forecast"
                         + (" (read the number as a floor there)" if ra >= 1.1 else "")
                         + f"; where none are on record, about {rb:.1f}×"
                         + (" — often because floods there go unreported." if rb >= 1.1
                            else "."))
        st.markdown(body)

        st.markdown("##### 2 · If a flood comes nearby, chance this spot is under water")
        n_fl = wm.get("n_floods_trained_on")
        body = ("A property of the ground, not of the day: how likely water is to reach this "
                "exact 100 m spot if a flood is reported within about 5 km. It comes from how "
                "high the spot sits above the nearest river, how big that river is, how far "
                "away it is, and how closed-in the valley is — learned from "
                + (f"{n_fl:,} " if n_fl else "") + "reported floods, from where radar "
                "images showed new water around them.")
        body += (f"\n\n**Checked:** inside Arunachal it ranks flooded ground above dry ground "
                 f"about {100*wm['oof_auc_in_arunachal']:.0f} times in 100 (on steep ground "
                 f"{100*wm['oof_auc_steep']:.0f}).")
        top = wm.get("checked_in_arunachal_top") or []
        if top:
            body += (" Its highest ranges come true less often than they say inside Arunachal: "
                     + "; ".join(f"spots given {100*b['p_lo']:.0f}–{100*b['p_hi']:.0f}% went "
                                 f"under water about {100*b['happened']:.0f}% of the time"
                                 for b in top)
                     + ". A correction by terrain was tested and did not hold up — how much "
                       "ground a flood covers varies too much from one flood to the next — "
                       "so anything above 20% is shown as “20%+”, with the checked rate "
                       "beside it.")
        st.markdown(body)

        st.markdown("##### 3 · River gauges — the checked forecast")
        g = mf.get("gauge")
        body = (f"For each of the {len(snap.get('rivers', []))} river gauges read every "
                "morning: the chance the river reaches its line on each coming day — the "
                "official CWC danger level where one exists, otherwise the river's own "
                "wettest 2% of days. It uses the live rain and the river's own readings "
                "over the last week.")
        if g:
            rel = [r for r in g["reliability"] if r["n"] >= 200]
            pairs = "; ".join(f"said {r['said_avg_pct']:.0f}%, {r['happened_pct']:.0f}% happened"
                              for r in rel if r["said_avg_pct"] >= 5)
            body += (f"\n\n**Checked on past years:** at gauges with an official danger level, "
                     f"one day ahead, a warning at {g['warn_at_pct']}% caught "
                     f"{g['caught_pct']:.0f}% of the times the river crossed it (rain alone: "
                     f"{g['rain_only_caught_pct']:.0f}%) and was right {g['right_pct']:.0f}% "
                     f"of the time. When it gives a chance, about that share happens"
                     + (f" ({pairs})." if pairs else "."))
        if glink.get("rule"):
            r_ = glink["rule"]
            body += ("\n\n**A gauge is shown as “on this river” only when it is:** the same "
                     f"flow path, a river of about the same size ({r_['same_river']}), "
                     f"and {r_['near']}. Otherwise the screen says no gauge "
                     "measures that river.")
        n_lines = sum(1 for v in glev.values() if v.get("danger") is not None)
        if glev:
            body += (f"\n\n**Its graph** shows the last 30 days of real readings and, for "
                     f"the {n_lines} gauges where CWC publishes them, the warning, danger and "
                     "highest-ever lines.")
            lvf = mf.get("level")
            if lvf and lvf.get("leads"):
                a = lvf["leads"]["1"]
                b = lvf["leads"].get("2", a)
                body += (" **The dotted line** is our forecast of the river's daily high for "
                         f"the {lvf['draw_to_lead']} days after its last full day of readings; "
                         "the shaded band is its likely range. Checked on past years at CWC "
                         f"gauges: it missed by {a['cwc_miss_m']:.2f} m on average one day on and "
                         f"{b['cwc_miss_m']:.2f} m two days on (assuming no change misses by "
                         f"{a['cwc_no_change_m']:.2f} m and {b['cwc_no_change_m']:.2f} m), and "
                         f"the band held {a['range_holds_pct']:.0f}% of what happened. It is not "
                         "drawn further ahead: beyond that the line and the chance disagreed "
                         "too often.")
            else:
                body += (" There is no forecast line for the level itself — the forecast is "
                         "the chance of crossing, not the level.")
        st.markdown(body)

        st.markdown("##### What it does not count")
        for c in [
            _record_note(mf.get("radar"), mf.get("record")),
            "<b>Short flash floods</b> in remote, steep valleys — the least likely to be "
            "reported, so the chance there is most likely to be too low.",
            "<b>A river sitting right at its line.</b> When a river stays within a few "
            "centimetres of its line for days, whether a day counts as “reached” hangs on "
            "those centimetres, and the chance is least reliable there. Read the level line.",
            "<b>Depth.</b> How deep the water gets needs a 2-D flood model on detailed "
            "elevation data — a different project.",
            "<b>Dam releases.</b> A scheduled release can flood a reach on a dry day.",
            f"<b>Rain between the points.</b> Live rain is read at {len(PTS['lat'])} points "
            "about 22 km apart; days 4–7 rest on rain forecasts that are weaker that far "
            "ahead, which is why they are faded on screen.",
        ]:
            st.markdown(f"<div class='caveat'>{c}</div>", unsafe_allow_html=True)

        st.markdown("##### How it stays honest")
        tr = snap.get("track_record") or {}
        st.markdown(
            "Every forecast is written down each morning, before the day, and graded "
            "afterwards. River forecasts are graded daily against the gauges"
            + (f" — {tr.get('forecasts_logged', 0):,} written down since "
               f"{tr.get('first_issue')}" if tr else "")
            + ". The flood chance near each place is graded when flood records for those "
            "days arrive; new records come from river gauges crossing their lines and from "
            "reports of floods.")

        with st.expander("Data sources"):
            st.markdown(
                f"- **Live rain** — Open-Meteo, {len(PTS['lat'])} points, today + 7 days\n"
                "- **Rain history the models learned from** — NASA GPM IMERG satellite rain\n"
                "- **Flood records** — news-reported floods (Google Groundsource); Sentinel-1 "
                "radar images around each date show where new water appeared\n"
                "- **River gauges** — Central Water Commission flood forecasting (level) and "
                "the National Water Data Portal (flow)\n"
                "- **Terrain and rivers** — Copernicus 30 m elevation (at 100 m), "
                "HydroSHEDS catchments")

    st.markdown("<div class='app-footer'><b>FloodSense</b>"
                "<span>Flood = where water can go × when it is coming</span></div>",
                unsafe_allow_html=True)
