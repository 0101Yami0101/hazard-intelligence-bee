"""SoilSense pages: the erosion map, this week, the village card, change over time,
the priority list, what treating would save, and how to read them.

First version (Phase 0). What it must never do, by design
(docs/design/EROSION_MODULE.md §6, EROSION_PLAN.md register V-16 / V-17):
  - show a class or a rank as a chance;
  - hide that two inputs are unsettled — the rain-strength map and the cover
    value for "tree" land — so both alternative runs are one click away, and
    every top catchment says whether it stays on top under the other rain map;
  - call un-scored land "low": river land, water and towns stay uncoloured.
"""
from __future__ import annotations

import html

import folium
import pandas as pd
import streamlit as st
from folium.plugins import Fullscreen
from folium.raster_layers import ImageOverlay
from streamlit_folium import st_folium

import core.theme as T
from core.mapping import rgba_overlay
from products.erosion import data as D
from products.flood import ui as U          # the shared dashboard look

VIEWS = [("🗺️", "Erosion map"), ("🌧️", "This week"), ("📍", "Village card"),
         ("🛰️", "Change over time"), ("📋", "Priority list"), ("🛠️", "What if we treat it?"),
         ("📖", "How to read this")]
MEASURES = [("replant", "Replant steep open land", "Trees, bamboo or agroforestry on open land of 15° and "
             "steeper: cover value to 0.05 (provisional)"),
            ("terrace", "Bench terraces", "On farmed or cleared land of 8° and steeper: protection value "
             "0.15 (provisional, mid of 0.1–0.2 in Indian hill studies)"),
            ("contour", "Contour bunds or trenches", "On gentler farmed and open land, 1.7–14°: protection "
             "value by slope from Wischmeier & Smith (1978), 0.5–0.9; not effective above 14°")]
# The weekly outlook (E2.1): forecast erosive rain against the place's normal for
# the time of year, in multiples of normal.
X_EDGES = [0.5, 1, 2, 4]
X_NAMES = ["under ½ normal", "½–1× normal", "1–2× normal", "2–4× normal", "over 4× normal"]
X_COLORS = ["#c9d3dd", "#f3d9a4", "#f0a35e", "#d9603b", "#9c2a1b"]
# The dry-season change page (Phase 1, EROSION_PLAN.md "E1.1-E1.3"): bare share of
# each square, measured from Sentinel-2 each 1 Feb - 30 Apr, in percent.
BARE_EDGES = [5, 15, 30, 50, 75]
BARE_NAMES = ["< 5%", "5–15%", "15–30%", "30–50%", "50–75%", "> 75%"]
BARE_COLORS = ["#5f8f4e", "#b5c46e", "#e3c770", "#d08f45", "#a8552b", "#6e2614"]
DIFF_EDGES = [-25, -10, 10, 25]
DIFF_NAMES = ["much greener", "greener", "about the same", "barer", "much barer"]
DIFF_COLORS = ["#1a9850", "#91cf60", "#9aa3ad", "#fc8d59", "#d73027"]
FLAG_COLOR = "#ff3df2"
# AD-01: the AI map, five bands by share of scored land (a relative index, not a loss)
AI_NAMES = ["lower half", "50–75%", "75–90%", "90–97%", "top 3%"]
AI_COLORS = ["#d8d2ef", "#b3a6e3", "#8a73d1", "#6247b8", "#3a1f8f"]
AI_HELP = ("AI map: a tree model learned which squares ISRO's experts marked as eroded on the "
           "national land-degradation map (2015–16), from terrain, soil, rain strength and cover. "
           "Shown as five bands by share of scored land; a rank, not tonnes. On map blocks it never "
           "saw it separated ISRO's eroded land from normal land far better than the formula (0.82 vs "
           "0.66). But on 300 blind satellite pictures it found visibly eroded ground no better than "
           "the formula: a second opinion that follows ISRO's map, not a better map.")
# AD-25: soil estimated to reach a stream, five bands of t/ha/yr
DELIV_NAMES = ["under 0.5", "0.5–1", "1–2", "2–5", "5 or more"]
DELIV_COLORS = ["#dbe9f6", "#a6cbe3", "#5fa2d4", "#2a6fb3", "#0b3d7a"]
DELIV_HELP = ("Soil reaching streams: of the soil each square loses, how much is estimated to reach a "
              "stream, from how well the ground below it connects to the channel (Borselli's connectivity "
              "index and InVEST's delivery ratio, standard settings). This is where check dams and gully "
              "plugs pay most. An estimate, not yet checked against measurements.")
PALETTE = {"ai": AI_COLORS, "deliv": DELIV_COLORS}
RANK_KEY = {"ai": "ai_rank", "deliv": "rank_delivered"}
HOME = "Erosion map"
RUNS = {"main": "Main run", "ired": "Other rain map", "treeC_alt": "Lower forest value"}
RUN_HELP = {
    "main": "Rain strength from InRESatE (closest to the only gauge-measured value, at "
            "Guwahati); cover value 0.03 for land the satellite map calls 'tree'.",
    "ired": "The same, with the other national rain-strength map (IRED). The two maps "
            "agree on the broad picture but not on every catchment.",
    "treeC_alt": "The same, with cover value 0.003 for 'tree' land: right for closed forest, "
                 "too low for tea gardens and jhum fallow, which that class also contains.",
}
ALL = "All of the state"
# Once the tree split is adopted (Phase 1 E1.1, EROSION_PLAN.md) the main run
# measures cover per square, and the third option shows what the split changed.
RUNS_SPLIT = {"main": "Main run", "ired": "Other rain map", "treeC_avg": "Before the tree split"}
RUN_HELP_SPLIT = {
    "main": "Rain strength from InRESatE (closest to the only gauge-measured value, at "
            "Guwahati). Ground cover measured per square: land the satellite map calls 'tree' "
            "is split into forest, tea or bush, regrowing and freshly cleared ground.",
    "ired": RUN_HELP["ired"],
    "treeC_avg": "The same, with one cover value (0.03) for all 'tree' land, as before the "
                 "split: shows what measuring the cover changed.",
}


RUNS_MEASURED = {"main": "Main run", "ired": "Other rain map", "treeC_avg": "Before measured cover"}
RUN_HELP_MEASURED = {
    "main": "Rain strength from InRESatE (closest to the only gauge-measured value, at "
            "Guwahati). Ground cover measured per square from Sentinel-2: the share of each "
            "square left bare in the dry seasons since 2019.",
    "ired": RUN_HELP["ired"],
    "treeC_avg": "The same, with one cover value per land-cover class (0.03 for all 'tree' "
                 "land), as before: shows what measuring the cover changed.",
}


def _runs(meta: dict) -> tuple[dict, dict, str]:
    """(labels, help, comparison key) — the split's or the measured cover's set once adopted."""
    if meta.get("tree_split", {}).get("adopted"):
        return RUNS_SPLIT, RUN_HELP_SPLIT, "treeC_avg"
    if meta.get("measured_cover", {}).get("adopted"):
        return RUNS_MEASURED, RUN_HELP_MEASURED, "treeC_avg"
    return RUNS, RUN_HELP, "treeC_alt"


def _esc(s) -> str:
    return html.escape(str(s))


def _nav() -> str:
    if st.session_state.get("er_view") not in [v for _, v in VIEWS]:
        st.session_state.er_view = HOME
    with st.sidebar:
        for icon, label in VIEWS:
            active = st.session_state.er_view == label
            if st.button(f"{icon}  {label}", key=f"ernav_{label}", width="stretch",
                         type="primary" if active else "secondary"):
                if not active:
                    st.session_state.er_view = label
                    st.rerun()
    return st.session_state.er_view


def _region() -> str | None:
    regs = D.regions()
    with st.sidebar:
        st.divider()
        st.markdown("<div class='side-label'>State</div>", unsafe_allow_html=True)
        if not regs:
            return None
        names = {r: r.title() for r in regs}
        r = st.selectbox("State", regs, format_func=names.get, key="er_region",
                         label_visibility="collapsed")
        st.caption("Arunachal Pradesh: computed with the same code as a test run, "
                   "not yet reviewed for showing (the forest cover question).")
    return r


def _settings():
    with st.sidebar:
        st.divider()
        st.markdown("<div class='side-label'>Map settings</div>", unsafe_allow_html=True)
        basemap = st.radio("Basemap", list(T.BASEMAPS), horizontal=True,
                           index=list(T.BASEMAPS).index(T.BASEMAP_DEFAULT),
                           label_visibility="collapsed", key="set_basemap")
        opacity = st.slider("Overlay opacity", 0.0, 1.0, 0.75, 0.05, key="set_opacity")
        c1, c2 = st.columns(2)
        with c1:
            top = st.toggle("Top 20", value=True, key="er_top",
                            help="Outline the 20 highest-ranked small catchments.")
            dists = st.toggle("Districts", value=False, key="er_dists")
        with c2:
            labels = st.toggle("Names", value=True, key="set_labels")
    return dict(basemap=basemap, opacity=opacity, top=top, districts=dists, labels=labels)


def _district_pick(B) -> str:
    names = sorted(f["properties"]["district"] for f in B["districts"]["features"])
    return st.selectbox("District", [ALL] + names, key="er_district",
                        label_visibility="collapsed",
                        help="Pick a district to zoom to it and see its figures.")


def _feature(B, name):
    return next((f for f in B["districts"]["features"]
                 if f["properties"]["district"] == name), None)


def _bounds(geom) -> list:
    xs, ys = [], []

    def walk(c):
        if isinstance(c[0], (int, float)):
            xs.append(c[0]); ys.append(c[1])
        else:
            for x in c:
                walk(x)
    walk(geom["coordinates"])
    return [[min(ys), min(xs)], [max(ys), max(xs)]]


def _map(B, run: str, s: dict, focus: str, overlays=None, key: str = "") -> None:
    """The state map. `overlays` (RGBA arrays on the class rasters' web grid)
    replace the class layer, for the change page; the top-20 outlines follow
    the main run there."""
    meta = B["meta"]
    m = folium.Map(location=meta["center"], zoom_start=7, tiles=None, control_scale=True)
    m.options.update(minZoom=6, maxBounds=[[meta["bounds"][0][0] - 2, meta["bounds"][0][1] - 2],
                                           [meta["bounds"][1][0] + 2, meta["bounds"][1][1] + 2]])
    url, attr = T.BASEMAPS[s["basemap"]]
    folium.TileLayer(url, attr=attr, name="Base", control=False, no_wrap=True).add_to(m)
    folium.map.CustomPane("labels", z_index=650).add_to(m)
    if s["labels"]:
        folium.TileLayer(T.LABEL_TILES[s["basemap"]],
                         attr=attr if "Esri" in attr else T.ESRI_CANVAS,
                         pane="labels", control=False, no_wrap=True).add_to(m)
    Fullscreen(position="topleft").add_to(m)
    if s["opacity"] > 0:
        base_layer = rgba_overlay(B["classes"][run], PALETTE.get(run, D.CLASS_COLORS), alpha=255)
        for z, rgba in enumerate(overlays or [base_layer]):
            ImageOverlay(rgba, bounds=B["bounds"], opacity=1.0 if z else s["opacity"],
                         interactive=False, zindex=2 + z).add_to(m)
    ink = T.BOUNDARY_INK.get(s["basemap"], T.ACCENT)
    folium.GeoJson(B["outline"], style_function=lambda _: {"color": ink, "weight": 2,
                                                           "fill": False}).add_to(m)
    if s["districts"]:
        folium.GeoJson(B["districts"], style_function=lambda _: {
            "color": "#e5e7eb", "weight": 0.8, "fill": False, "opacity": 0.7}).add_to(m)
    if s["top"]:
        rk = RANK_KEY.get(run, f"rank_{run}")
        top = {"type": "FeatureCollection",
               "features": [f for f in B["catchments"]["features"]
                            if (f["properties"].get(rk) or 10 ** 6) <= 20]}
        fields, aliases = {
            "ai": (["ai_rank", "district", "agreement", "ai_reason", "ai_against"],
                   ["AI rank", "District", "AI and formula", "AI's main reason", "Pulls it down"]),
            "deliv": (["rank_delivered", "district", "delivered_tpha", "delivered_share_pct", "meanA_main"],
                      ["Rank, reaching streams", "District", "Reaching streams (t/ha/yr)",
                       "Share of its loss (%)", "Average loss (t/ha/yr)"]),
        }.get(run, ([f"rank_{run}", "district", f"meanA_{run}", "main_driver", "vs_similar", "mark"],
                    ["Rank", "District", "Average loss (t/ha/yr)", "Main cause", "Against similar slopes", ""]))
        folium.GeoJson(
            top, style_function=lambda _: {"color": "#ffffff", "weight": 1.6,
                                           "fill": True, "fillOpacity": 0.0},
            highlight_function=lambda _: {"weight": 3, "color": "#ffd166"},
            tooltip=folium.GeoJsonTooltip(fields=fields, aliases=aliases, sticky=True)).add_to(m)
    if focus != ALL:
        f = _feature(B, focus)
        if f is not None:
            folium.GeoJson(f, style_function=lambda _: {"color": "#ffd166", "weight": 3,
                                                        "fill": False}).add_to(m)
            m.fit_bounds(_bounds(f["geometry"]))
    st_folium(m, height=U.MAP_H, use_container_width=True, pixelated=True,
              returned_objects=[], key=f"ermap_{run}_{focus}{key}")


def _legend(shares: dict) -> None:
    names = [f"{n} <span>{r}</span>" for n, r in zip(D.CLASS_NAMES, D.CLASS_RANGES)]
    vals = [shares.get(k, 0) / 100 for k in
            ("slight", "moderate", "high", "very high", "severe", "very severe")]
    st.markdown(U.legend(names, D.CLASS_COLORS, vals,
                         tip="Share of scored land in each class, t/ha/yr. Uncoloured land "
                             "is not scored by this method: rivers and land within 2 m of a "
                             "large river, water, towns."), unsafe_allow_html=True)


def _district_card(B, name: str) -> None:
    f = _feature(B, name)
    if f is None:
        return
    p = f["properties"]
    n = len(B["districts"]["features"])
    tiles = [
        U._tile("Average loss", f"{p['meanA_main']:.0f}", "t/ha/yr, scored land", "er_estimate"),
        U._tile("High or worse", f"{p['high_or_worse_pct']:.0f}%", "≥ 10 t/ha/yr", "er_class"),
        U._tile("Rank", f"{p['rank_main']} of {n}", f"other rain map: {p['rank_ired']} · "
                f"{_runs(B['meta'])[0][_runs(B['meta'])[2]].lower()}: "
                f"{p.get('rank_' + _runs(B['meta'])[2], '–')}", "er_rank"),
        U._tile("Total", f"{p['total_t_per_yr'] / 1e6:.1f} Mt",
                f"a year, over {p['scored_km2']:,.0f} km² scored"),
    ]
    st.markdown(U._sec(_esc(name)) + U._tiles(tiles, 2), unsafe_allow_html=True)
    cause = p["main_driver"] + (f", then {p['also']}" if p.get("also") else "")
    # st.caption, not a .fs-note: that style is one line and ran past the panel
    similar = (f" Against districts of similar steepness: **{p['vs_similar']}**, "
               f"{p['vs_similar_x']:.1f}× their average." if p.get("vs_similar") else "")
    reach = (f" About **{p['delivered_tpha']:.1f} t/ha/yr** reaches a stream ({p['delivered_share_pct']:.0f}% of "
             f"its loss; #{int(p['rank_delivered'])} of {n} on that, an estimate)."
             if p.get("delivered_tpha") is not None else "")
    if p.get("N_kg_per_ha") is not None:
        reach += (f" The soil washing off carries about **{p['N_kg_per_ha']:.0f} kg of nitrogen** per hectare a year "
                  f"(≈ {p['urea_bags_per_ha']:.1f} bags of urea, ₹{p['urea_rs_per_ha']:,.0f} at the farmer's price) "
                  f"and {p['topsoil_mm_per_yr']:.1f} mm of topsoil.")
    st.caption(f"Main cause against the state average: **{cause}**.{similar}{reach} "
               f"Typical measures: {p.get('hint', '')} (to confirm with the department). "
               f"{p['not_scored_pct']:.0f}% of the district is not scored "
               f"(river land, water, towns).")


SHORT_CAUSE = {"steep or long slopes": "steep slopes", "heavy rain": "rain",
               "bare or thin cover": "bare ground", "erodible soil": "soil"}


def _similar(p: dict) -> str:
    """'heavy rain, 2.5×' — what sets the unit apart from units as steep as it."""
    return f"{p['vs_similar']}, {p['vs_similar_x']:.1f}×" if p.get("vs_similar") else ""


def _why(p: dict) -> str:
    """The main cause and the second reason, short enough for one line."""
    s = SHORT_CAUSE.get(p["main_driver"], p["main_driver"])
    if p.get("vs_similar"):
        s += (f" · {SHORT_CAUSE.get(p['vs_similar'], p['vs_similar'])} "
              f"{p['vs_similar_x']:.1f}× similar slopes")
    return s


def _firmness(p: dict) -> str:
    """How often the unit is top 20 across 1,000 runs of the unsettled inputs (V-17)."""
    t = p.get("top20_pct")
    if t is None:                                   # before the runs existed: the two-map mark
        firm = p.get("mark") == "top under both rain maps"
        return ("<span style='color:#4cc37a'>firm</span>" if firm
                else "<span style='color:#f5b14c'>rain-dependent</span>")
    col = "#4cc37a" if t >= 80 else "#f5b14c" if t >= 50 else "#9aa3ad"
    return f"<small style='color:{col}'>top 20 in {t:.0f}% of runs</small>"


def _top_list(B, run: str, n: int = 10) -> None:
    if run == "ai":
        feats = sorted((f["properties"] for f in B["catchments"]["features"] if f["properties"].get("ai_rank")),
                       key=lambda p: p["ai_rank"])[:n]
        rows = [U._row(f"#{int(p['ai_rank'])}", "#6247b8", f"{_esc(p['district'])} · {p['scored_km2']:.0f} km²"
                       f"<br><small>AI: {_esc(p['ai_reason'])}</small>",
                       f"<small>{_esc(p['agreement'])}<br>formula #{p['rank_main']}</small>") for p in feats]
        st.markdown(U._sec("Top catchments, AI", U.badge("er_rank", mini=True), note="learned from ISRO's map")
                    + "".join(rows), unsafe_allow_html=True)
        return
    if run == "deliv":
        feats = sorted((f["properties"] for f in B["catchments"]["features"] if f["properties"].get("rank_delivered")),
                       key=lambda p: p["rank_delivered"])[:n]
        rows = [U._row(f"#{int(p['rank_delivered'])}", "#2a6fb3", f"{_esc(p['district'])} · {p['scored_km2']:.0f} km²"
                       f"<br><small>{p['delivered_share_pct']:.0f}% of its loss reaches a stream</small>",
                       f"{p['delivered_tpha']:.1f} t/ha/yr<br><small>loss #{p['rank_main']}</small>") for p in feats]
        st.markdown(U._sec("Top catchments, soil reaching streams", U.badge("er_estimate", mini=True),
                           note="estimate, untested") + "".join(rows), unsafe_allow_html=True)
        return
    feats = sorted((f["properties"] for f in B["catchments"]["features"]),
                   key=lambda p: p[f"rank_{run}"])[:n]
    rows = []
    for p in feats:
        right = f"{p[f'meanA_{run}']:.0f} t/ha/yr" + (f"<br>{_firmness(p)}" if run == "main" else "")
        rows.append(U._row(f"#{p[f'rank_{run}']}", "#e0a458",
                           f"{_esc(p['district'])} · {p['scored_km2']:.0f} km²"
                           f"<br><small>{_esc(_why(p))}</small>", right))
    st.markdown(U._sec("Top catchments", U.badge("er_rank", mini=True),
                       note=_runs(B["meta"])[0][run]) + "".join(rows), unsafe_allow_html=True)


def _map_page(B, s) -> None:
    meta = B["meta"]
    focus = U.page_head("SoilSense · soil erosion",
                        f"{meta['state']} · first version, built {meta['generated_utc'][:10]}",
                        icon="◬", search_row=lambda: _district_pick(B), warn=False)
    U.key_row("er_estimate", "er_class", "er_rank",
              note="Rain-washed soil only: not riverbanks or landslides.")
    sh = meta["shares"]["main"]
    high = sum(sh[k] for k in ("high", "very high", "severe", "very severe"))
    dfeat = sorted((f["properties"] for f in B["districts"]["features"]),
                   key=lambda p: p["rank_main"])
    tiles = [
        U._tile("Land scored", f"{meta['scored_pct']:.0f}%", "the rest is river land, water, towns"),
        U._tile("High or worse", f"{high:.0f}%", "of scored land, ≥ 10 t/ha/yr", "er_class"),
        U._tile("Typical loss", f"{meta['median_A']:.0f}", "t/ha/yr, median of scored land",
                "er_estimate"),
        U._tile("Worst district", _esc(dfeat[0]["district"]),
                f"{dfeat[0]['meanA_main']:.0f} t/ha/yr on average", "er_rank"),
        U._tile("Catchments ranked", f"{meta['n_catchments']}", "small catchments, ≥ 5 km² scored"),
        (U._tile("Robust in the top 20", f"{meta['stability']['catchments_robust_top20']}",
                 f"catchments top 20 in ≥ 80% of {meta['stability']['draws']:,} runs; "
                 f"{meta['stability']['catchments_top20_in_half_the_runs']} in half", "er_rank")
         if meta.get("stability") else
         U._tile("Firm in the top 20", f"{meta['n_top_both']} of 20",
                 "stay top 20 under both rain maps", "er_rank")),
    ]
    st.markdown(U._tiles(tiles, 6), unsafe_allow_html=True)

    runs, helps, _ = _runs(meta)
    if (meta.get("ai") or {}).get("ships") and "ai" in B["classes"]:
        runs, helps = {**runs, "ai": "AI map"}, {**helps, "ai": AI_HELP}
    if meta.get("delivered") and "deliv" in B["classes"]:
        runs, helps = {**runs, "deliv": "Soil reaching streams"}, {**helps, "deliv": DELIV_HELP}
    if st.session_state.get("er_run") not in runs:
        st.session_state.pop("er_run", None)        # an option from before the split
    run = st.segmented_control("Run", list(runs), format_func=runs.get, default="main",
                               key="er_run", label_visibility="collapsed") or "main"
    st.caption(helps[run])
    c_map, c_side = st.columns([2.5, 1.25], gap="medium")
    with c_map:
        _map(B, run, s, focus or ALL)
        if run == "ai":
            import numpy as np
            c = B["classes"]["ai"]
            n = max(int((c > 0).sum()), 1)
            st.markdown(U.legend(AI_NAMES, AI_COLORS, [float((c == i + 1).sum()) / n for i in range(5)],
                                 tip="Bands by share of scored land: the darkest is the 3% the AI ranks "
                                     "most like ISRO's eroded land. A rank, not tonnes."),
                        unsafe_allow_html=True)
        elif run == "deliv":
            dv = meta["delivered"]
            st.markdown(U.legend([f"{n} <span>t/ha/yr</span>" for n in DELIV_NAMES], DELIV_COLORS, dv["class_share"],
                                 tip="Share of scored land in each band: tonnes a year per hectare estimated "
                                     "to reach a stream."), unsafe_allow_html=True)
        else:
            _legend(meta["shares"][run])
        if run == "deliv":
            dv = meta["delivered"]
            st.caption(f"Of the {dv['state_loss_mt']:.0f} million tonnes a year estimated lost across the state, "
                       f"about {dv['state_delivered_mt']:.1f} million ({dv['share_pct']:.0f}%) reaches a stream; "
                       "the rest settles lower on the slope or in fields. Squares wired to a channel matter most "
                       "for silting rivers and reservoirs. An estimate with standard settings, not yet checked "
                       "against measurements: rank catchments, not squares.")
        elif run != "ai":
            st.caption("On tree-covered land a square's class is indicative: one cover value "
                       "stands for forest, tea gardens and jhum fallow alike. Rank catchments, "
                       "not single squares.")
        else:
            st.caption("The AI learned one survey (ISRO, 2015–16) and, on blind satellite pictures, found "
                       "visible erosion no better than the formula. Where the two disagree, a field visit "
                       "decides. Rank catchments, not squares.")
    with c_side:
        if focus and focus != ALL:
            _district_card(B, focus)
        _top_list(B, run)


def _week_page(B, s) -> None:
    import numpy as np
    from products.erosion import outlook as O
    meta = B["meta"]
    focus = U.page_head("This week's erosive rain", f"{meta['state']} · the next 7 days, "
                        "from the live rain forecast", icon="◬",
                        search_row=lambda: _district_pick(B), warn=False)
    W = O.week(meta["region"])
    if W is None:
        st.info("The weekly outlook is not built yet (`scripts/build/erosion_outlook_base.py`).")
        return
    if "error" in W:
        st.warning(W["error"] + " The erosion map and the priority list do not depend on it.")
        return
    U.key_row("er_outlook", "er_input",
              note="Forecast rain set against what is normal at each place for the time of year.")
    z, om = W["z"], W["meta"]
    d0, d1 = W["days"][0], W["days"][-1]
    cls = np.digitize(W["x_normal"], X_EDGES) + 1
    cls[~np.isfinite(W["x_normal"])] = 0
    pix = z["pix"].astype(int)
    grid_cls = np.where(pix > 0, cls[np.maximum(pix - 1, 0)], 0).astype("uint8")
    shares = [float((grid_cls == i + 1).sum()) / max(int((grid_cls > 0).sum()), 1) for i in range(5)]

    feats = B["catchments"]["features"]
    pos = {int(c): i for i, c in enumerate(z["cat_id"])}
    rows = []
    for f in feats:
        p = f["properties"]
        i = pos.get(int(p["HYBAS_ID"]))
        if i is None or not np.isfinite(W["cat_x"][i]):
            continue
        rows.append((float(W["cat_week"][i]), float(W["cat_x"][i]), p))
    rows.sort(key=lambda r: -r[0])
    top_ids = {r[2]["HYBAS_ID"] for r in rows[:10]}

    dnames = om["districts"]
    di = {n: k for k, n in enumerate(dnames)}
    if focus and focus != ALL and focus in di:
        k = di[focus]
        wk, xn, where = float(W["dis_week"][k]), float(W["dis_x"][k]), _esc(focus)
    else:
        wk, xn, where = W["state_week"], W["state_x"], meta["state"]
    tiles = [
        U._tile("Erosive rain vs normal", f"{xn:.1f}×",
                f"{where}, {d0[5:]} to {d1[5:]}, against the usual for these days", "er_outlook"),
        U._tile("Share of a year's erosive rain", f"{100 * W['state_share']:.1f}%",
                f"falls in these 7 days ({om['mean_week_share_pct']:.1f}% in an average week; "
                f"{om['monsoon_week_share_pct']:.1f}% in a mid-monsoon week)", "er_outlook"),
        U._tile("Soil at risk this week", f"{wk:.2f}", "t/ha on average over scored land, "
                f"{where}", "er_outlook"),
        U._tile("Most at risk", _esc(rows[0][2]["district"]) if rows else "–",
                f"catchment #{rows[0][2]['rank_main']} of the year's list, {rows[0][0]:.1f} t/ha "
                "this week" if rows else "", "er_rank"),
    ]
    st.markdown(U._tiles(tiles, 4), unsafe_allow_html=True)

    c_map, c_side = st.columns([2.5, 1.25], gap="medium")
    with c_map:
        top = {"type": "FeatureCollection",
               "features": [f for f in feats if f["properties"]["HYBAS_ID"] in top_ids]}
        B2 = dict(B, catchments=top)
        _map(B2, "main", dict(s, top=False), focus or ALL,
             overlays=[rgba_overlay(grid_cls, X_COLORS, alpha=255)], key=f"_wk{d0}")
        st.markdown(U.legend(X_NAMES, X_COLORS, shares,
                             tip="Each 22 km rain point's forecast erosive rain for the next 7 days, "
                                 "against its own normal for these days of the year (Open-Meteo, "
                                 "2010 onwards), shown on the land the erosion map scores."),
                    unsafe_allow_html=True)
        st.caption("Outlined: the 10 catchments where this week's rain meets the most erodible "
                   "ground. Rain is sampled every 22 km, so read it as a regional picture.")
    with c_side:
        vals = list(W["state_day"])
        st.markdown(U._sec("Day by day, " + where, U.badge("er_outlook", mini=True))
                    + U.bars(vals, [d[8:] for d in W["days"]], ["#d9603b"] * len(vals),
                             [f"{d}: {100 * v / max(sum(vals), 1e-12):.0f}% of the week's erosive rain"
                              for d, v in zip(W["days"], vals)]),
                    unsafe_allow_html=True)
        html_rows = [U._row(f"#{p['rank_main']}", "#d9603b",
                            f"{_esc(p['district'])} · {p['scored_km2']:.0f} km²"
                            f"<br><small>{_esc(_why(p))}</small>",
                            f"{w:.1f} t/ha<br><small>{x:.1f}× normal</small>")
                     for w, x, p in rows[:8]]
        st.markdown(U._sec("Where this week's rain does most harm", U.badge("er_rank", mini=True),
                           note="catchments") + "".join(html_rows), unsafe_allow_html=True)
    with st.expander("All districts this week"):
        import pandas as pd
        dt = pd.DataFrame({"District": dnames, "Soil at risk this week, t/ha": W["dis_week"],
                           "Erosive rain vs normal": W["dis_x"]}).sort_values(
            "Soil at risk this week, t/ha", ascending=False)
        st.dataframe(dt, hide_index=True, width="stretch",
                     column_config={"Soil at risk this week, t/ha": st.column_config.NumberColumn(format="%.2f"),
                                    "Erosive rain vs normal": st.column_config.NumberColumn(format="%.1f×")})
    g = meta.get("outlook_grade")
    if g:
        ga = g["all"]
        st.markdown(U._sec("How well it has worked", U.badge("er_outlook", mini=True),
                           note=f"replayed over {ga['weeks']} monsoon weeks, 2024–2025")
                    + U._row("✔", "#4cc37a", "<b>When</b> an erosive week is coming: good",
                             f"weeks ρ {ga['G2_rho']:.2f} · heavy weeks {round(ga['G3_auc'] * 100 + 1e-6)}%")
                    + U._row("✕", "#e5534b", "<b>Where</b> within the week: weak, read the list as regional",
                             f"places ρ {ga['G1_median_rho']:.2f}"),
                    unsafe_allow_html=True)
        st.caption(f"We re-ran this page for every Monday of the 2024 and 2025 monsoons with the forecasts "
                   f"that were issued then, and compared it with satellite-measured rain (NASA IMERG). "
                   f"Across weeks it ranks the wet, erosive weeks well (ρ {ga['G2_rho']:.2f}; the season's "
                   f"normal alone gives {ga['G2_climatology']:.2f}), and it picks out weeks that turn out at "
                   f"least twice normal at a place {round(ga['G3_auc'] * 100 + 1e-6)}% of the time when compared pairwise. "
                   f"Which places within a week get the rain it ranks only weakly (ρ {ga['G1_median_rho']:.2f}), "
                   "as expected for storm rain forecast on a 22–31 km grid. Pass marks were set before the "
                   "replay; two of three passed.")
    st.caption("How it is made: next week's forecast rain is turned into erosive strength with the "
               "same daily formula as the rain-strength map, and compared with the same forecast "
               "source's own 16-year history at each place, so its known wet bias cancels out. "
               "That week's share of a normal year's erosive rain, applied to the erosion map, "
               "gives the soil at risk. It is an outlook from a forecast, not a measurement: "
               "its rain has been replayed against satellite rain (above); the soil part cannot be "
               "graded with open data.")


# ---- the village card (E2.3): one place, everything SoilSense knows about it ----------

def _fold(s: str) -> str:
    import unicodedata
    return "".join(ch for ch in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(ch)).lower()


def _place_search(P: pd.DataFrame):
    """(row index, note) from a name or 'lat, lon'; (None, None) until something matches."""
    import re
    import numpy as np
    q = st.text_input("Village or town, or a position", key="vc_q",
                      placeholder="Type a name (e.g. Haflong), or 'lat, lon' (e.g. 25.17, 93.02)",
                      label_visibility="collapsed")
    if not q or len(q.strip()) < 2:
        return None, None
    m = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$", q)
    if m:
        la, lo = float(m.group(1)), float(m.group(2))
        cosl = np.cos(np.radians(la))
        d = 111.2 * np.hypot(P.lat.values - la, (P.lon.values - lo) * cosl)
        i = int(np.argmin(d))
        return P.index[i], (f"The nearest listed place to {la:.4f}, {lo:.4f} is "
                            f"{d[i]:.1f} km away; its figures are shown.")
    key = _fold(q.strip())
    names = P.name.map(_fold)
    hits = P[names.str.contains(re.escape(key))]
    if hits.empty:
        st.info("No listed place matches. Try part of the name, or type a position as 'lat, lon'.")
        return None, None
    first = hits[names[hits.index].str.startswith(key)]
    hits = pd.concat([first, hits.drop(first.index)]).head(40)
    i = st.selectbox("Matches", list(hits.index), key="vc_pick", label_visibility="collapsed",
                     format_func=lambda k: f"{P.name[k]} — {P.district[k] or 'Assam'} ({P.place[k]})")
    return i, None


def _unit_props(B, p) -> dict | None:
    hy = int(p.hybas) if pd.notna(p.hybas) else 0
    for f in B["catchments"]["features"]:
        if int(f["properties"]["HYBAS_ID"]) == hy:
            return f["properties"]
    f = _feature(B, p.district)
    return f["properties"] if f else None


def _card_html(p, rows: list[tuple[str, str]], why: str, measures: str, bare_txt: str, state: str) -> bytes:
    body = "".join(f"<tr><td>{_esc(a)}</td><td><b>{_esc(b)}</b></td></tr>" for a, b in rows)
    alt = f"<p class='as'>{_esc(p.name_as)} <small>(Assamese name as mapped on OpenStreetMap)</small></p>" if p.name_as else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>SoilSense · {_esc(p['name'])}</title>
<style>body{{font-family:Arial,sans-serif;max-width:720px;margin:24px auto;color:#111}}h1{{margin:0}}
.sub{{color:#555}}table{{border-collapse:collapse;width:100%;margin:14px 0}}td{{border-bottom:1px solid #ddd;padding:6px}}
.as{{font-size:20px;margin:4px 0}}.box{{background:#f4f3ef;padding:10px 14px;border-radius:6px;margin:10px 0}}
small{{color:#666}}</style></head><body>
<h1>{_esc(p['name'])}</h1>{alt}<p class="sub">{_esc(p.district or state)} · SoilSense soil-erosion card</p>
<table>{body}</table>
<div class="box"><b>Why soil is lost here:</b> {_esc(why)}</div>
<div class="box"><b>What usually helps:</b> {_esc(measures)} <small>(typical measures, to confirm with the Soil Conservation Department)</small></div>
<p><b>Bare ground around here each dry season (Feb–Apr), from satellite pictures:</b> {_esc(bare_txt)}</p>
<p><small>Estimates from the standard soil-loss recipe (RUSLE) on open data; indicative, and shown for the land as if
untreated. Not a measurement at this spot. Places from OpenStreetMap (© OpenStreetMap contributors), GeoNames and the
Survey of India.</small></p></body></html>""".encode("utf-8")


def _village_page(B, s) -> None:
    import numpy as np
    meta = B["meta"]
    U.page_head("Village card", f"{meta['state']} · one place, everything SoilSense knows about it",
                icon="◬", warn=False)
    P = B.get("places")
    if P is None:
        st.info("The village list is not built yet (`scripts/build/erosion_places.py`).")
        return
    U.key_row("er_estimate", "er_class", "er_rank", "er_outlook", "measured",
              note="Figures for the land within about 1 km of the place.")
    i, note = _place_search(P)
    if i is None:
        src = P.source.value_counts()
        st.caption(f"{len(P):,} named places: " + ", ".join(f"{n:,} from {k}" for k, n in src.items())
                   + ". These open lists hold only part of Assam's villages; a position typed as "
                   "'lat, lon' finds the nearest listed place.")
        return
    p = P.loc[i]
    if note:
        st.caption(note)
    names = D.CLASS_NAMES
    cls = names[int(np.digitize(p.loss, [5, 10, 20, 40, 80]))] if pd.notna(p.loss) else "–"
    tiles = [U._tile("Soil loss around here", "–" if pd.isna(p.loss) else f"{p.loss:.0f}",
                     f"t/ha/yr, scored land within about 1 km · {cls.lower()}", "er_estimate"),
             U._tile("High-risk ground", "–" if pd.isna(p.high) else f"{p.high:.0f}%",
                     "of scored land within about 1 km, ≥ 10 t/ha/yr", "er_class"),
             U._tile("Steep ground", "–" if pd.isna(p.steep) else f"{p.steep:.0f}%",
                     "of land within about 1 km, slope ≥ 10°")]
    if pd.notna(p.catchment_rank):
        tp = (f"top 20 in {p.top20_pct:.0f}% of runs" if "top20_pct" in p and pd.notna(p.top20_pct)
              else "")
        tiles.append(U._tile("Its catchment", f"#{int(p.catchment_rank)}",
                             f"of {meta['n_catchments']} ranked · {tp}", "er_rank"))
    else:
        tiles.append(U._tile("Its catchment", "–", "too little scored land to be ranked", "er_rank"))
    week_txt = ""
    try:
        from products.erosion import outlook as O
        W = O.week(meta["region"])
        if W and "error" not in W:
            x = float(W["x_normal"][int(p.pt)])
            week_txt = f"{x:.1f}× normal ({W['rain_mm'][int(p.pt)]:.0f} mm forecast, {W['days'][0][5:]} to {W['days'][-1][5:]})"
            tiles.append(U._tile("This week's erosive rain", f"{x:.1f}×",
                                 f"normal for these days · {W['rain_mm'][int(p.pt)]:.0f} mm forecast",
                                 "er_outlook"))
    except Exception:  # noqa: BLE001 — the card stands without the live rain
        pass
    u0 = _unit_props(B, p)
    if u0 and u0.get("N_gkg") and pd.notna(p.loss):             # AD-29: local loss x the catchment's soil
        nkg = float(p.loss) * float(u0["N_gkg"])
        tiles.append(U._tile("Nitrogen washed off", f"{nkg:.0f} kg/ha",
                             f"a year ≈ {nkg / 0.46 / 45:.1f} bags of urea · if the land is untreated",
                             "er_estimate"))
    alt = (f"<div style='font-size:1.25rem;margin:-4px 0 6px'>{_esc(p.name_as)} "
           f"<small style='color:#9aa3ad'>(Assamese name as mapped on OpenStreetMap)</small></div>"
           if p.name_as else "")
    st.markdown(U._sec(f"{_esc(p['name'])} · {_esc(p.district or meta['state'])}",
                       note=f"{p.place} · from {p.source}") + alt + U._tiles(tiles, len(tiles)),
                unsafe_allow_html=True)
    if pd.notna(p.scored) and p.scored < 50:
        st.caption(f"Only {p.scored:.0f}% of the land around here is scored: the rest is river land, "
                   "water or town, where floods and bank cutting move the soil and this recipe does not apply.")

    u = _unit_props(B, p)
    why = (u["main_driver"] + (f"; against similar slopes: {u['vs_similar']}, {u['vs_similar_x']:.1f}× their average"
                               if u.get("vs_similar") else "")) if u else "–"
    measures = u.get("hint", "") if u else ""
    years = (meta.get("change") or {}).get("years", [])
    bare = [None if v == "" else float(v) for v in str(p.bare).split(";")] if isinstance(p.bare, str) else []
    c1, c2 = st.columns([1.4, 1], gap="medium")
    with c1:
        m = folium.Map(location=[p.lat, p.lon], zoom_start=13, tiles=None, control_scale=True)
        url, attr = T.BASEMAPS["Satellite"] if "Satellite" in T.BASEMAPS else next(iter(T.BASEMAPS.values()))
        folium.TileLayer(url, attr=attr, control=False).add_to(m)
        ImageOverlay(rgba_overlay(B["classes"]["main"], D.CLASS_COLORS, alpha=255), bounds=B["bounds"],
                     opacity=0.55, interactive=False, zindex=2).add_to(m)
        folium.CircleMarker([p.lat, p.lon], radius=7, color="#ffffff", weight=2, fill=True,
                            fill_color="#ffd166", fill_opacity=1, tooltip=p["name"]).add_to(m)
        st_folium(m, height=380, use_container_width=True, returned_objects=[], key=f"vcmap_{i}")
        st.caption("Erosion classes on the map, as on the main map (uncoloured: not scored).")
    with c2:
        st.markdown(U._sec("Why soil is lost here", U.badge("er_rank", mini=True))
                    + f"<div class='fs-note' style='white-space:normal'>{_esc(why)}</div>"
                    + (f"<div class='fs-note' style='white-space:normal;margin-top:6px'>AI view (learned from "
                       f"ISRO's eroded-land map): its catchment ranks <b>#{int(u['ai_rank'])}</b>, "
                       f"{_esc(u.get('agreement', ''))}; main reason: {_esc(u.get('ai_reason', ''))}.</div>"
                       if u and u.get("ai_rank") else "")
                    + U._sec("What usually helps")
                    + f"<div class='fs-note' style='white-space:normal'>{_esc(measures)} "
                      "<small>(typical measures, to confirm with the department)</small></div>",
                    unsafe_allow_html=True)
        if years and bare:
            last = next((f"{y}: {v:.1f}%" for y, v in zip(reversed(years), reversed(bare)) if v is not None), "")
            first = next((f"{y}: {v:.1f}%" for y, v in zip(years, bare) if v is not None), "")
            st.markdown(U._sec("Bare ground around here, each dry season", U.badge("measured", mini=True))
                        + U.bars([v or 0 for v in bare], [str(y)[2:] for y in years], ["#c9a25a"] * len(years),
                                 [f"{y}: {'too cloudy' if v is None else f'{v:.1f}% of scored land bare'}"
                                  for y, v in zip(years, bare)], on=len(years) - 1),
                        unsafe_allow_html=True)
            st.caption(f"Share of the scored land around here that was bare or burnt: {first} → {last}.")
    rows = [("Soil loss around here (estimate)", f"{p.loss:.0f} t/ha/yr ({cls.lower()})" if pd.notna(p.loss) else "–"),
            ("High-risk ground within about 1 km", f"{p.high:.0f}% of scored land" if pd.notna(p.high) else "–"),
            ("Steep ground within about 1 km", f"{p.steep:.0f}% (slope ≥ 10°)" if pd.notna(p.steep) else "–"),
            ("Its catchment's rank", f"#{int(p.catchment_rank)} of {meta['n_catchments']}" if pd.notna(p.catchment_rank) else "not ranked")]
    if week_txt:
        rows.append(("This week's erosive rain", week_txt))
    bare_txt = ", ".join(f"{y}: {'–' if v is None else f'{v:.0f}%'}" for y, v in zip(years, bare)) if bare else "–"
    st.download_button("Printable card (HTML: open it and print to PDF)",
                       _card_html(p, rows, why, measures, bare_txt, meta["state"]),
                       f"soilsense_card_{_fold(p['name']).replace(' ', '_')}.html", "text/html")
    st.caption("An Assamese version of the card needs its wording written and checked by a native "
               "speaker on the team; place names in Assamese are shown where mappers have entered them.")


def _treat_page(B) -> None:
    import numpy as np
    meta = B["meta"]
    U.page_head("What if we treat it?", f"{meta['state']} · soil saved by conservation works, "
                "estimated with the same recipe", icon="◬", warn=False)
    T_ = B.get("treatment")
    if not T_:
        st.info("The treatment table is not built yet (`scripts/build/erosion_treatment.py`).")
        return
    U.key_row("er_estimate", "er_rank",
              note="Estimates: the recipe run with the works in place, land as if untreated today.")
    kind = st.segmented_control("Unit", ["District", "Catchment"], default="District", key="tr_kind",
                                label_visibility="collapsed") or "District"
    if kind == "District":
        U_ = T_["districts"]
        names = U_["id"]
        pick = st.selectbox("District", sorted(names), key="tr_d", label_visibility="collapsed")
        i = names.index(pick)
        title = pick
    else:
        U_ = T_["catchments"]
        props = {int(f["properties"]["HYBAS_ID"]): f["properties"] for f in B["catchments"]["features"]}
        order = sorted((int(h) for h in U_["id"] if int(h) in props), key=lambda h: props[h]["rank_main"])
        h = st.selectbox("Catchment", order, key="tr_c", label_visibility="collapsed",
                         format_func=lambda h: f"#{props[h]['rank_main']} · {props[h]['district']} · "
                                               f"{props[h]['scored_km2']:.0f} km²")
        i = U_["id"].index(h)
        title = f"Catchment #{props[h]['rank_main']}, {props[h]['district']}"
    cols = st.columns(len(MEASURES))
    use = {}
    for col, (k, label, tip) in zip(cols, MEASURES):
        with col:
            on = st.toggle(label, value=(k != "contour"), key=f"tr_on_{k}", help=tip)
            share = st.slider("Share of the eligible land treated", 0, 100, 50, 10, key=f"tr_sh_{k}",
                              disabled=not on, format="%d%%")
            use[k] = share / 100 if on else 0.0
    total = U_["total_t"][i]
    saved = sum(U_[f"{k}_t"][i] * f for k, f in use.items())
    ha = sum(U_[f"{k}_ha"][i] * f for k, f in use.items())
    tiles = [U._tile("Soil lost now", f"{total / 1e3:,.0f}k t" if total >= 1e4 else f"{total:,.0f} t",
                     "a year, as if untreated", "er_estimate"),
             U._tile("Saved by these works", f"{saved / 1e3:,.0f}k t" if saved >= 1e4 else f"{saved:,.0f} t",
                     f"a year · {100 * saved / total:.0f}% less" if total else "", "er_estimate"),
             U._tile("Land treated", f"{ha:,.0f} ha", "eligible land × the shares chosen"),
             U._tile("Saved per hectare treated", f"{saved / ha:,.0f} t" if ha else "–",
                     "a year: where works pay off most", "er_estimate")]
    st.markdown(U._sec(_esc(title)) + U._tiles(tiles, 4), unsafe_allow_html=True)
    rows = []
    for k, label, _ in MEASURES:
        e, t = U_[f"{k}_ha"][i], U_[f"{k}_t"][i]
        rows.append({"Measure": label, "Eligible land, ha": e, "Saved if all treated, t/yr": t,
                     "Saved per ha treated, t/yr": round(t / e, 1) if e else None})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.markdown(U._sec("Where each measure saves most soil per hectare", U.badge("er_rank", mini=True),
                       note="catchments with ≥ 200 eligible ha"), unsafe_allow_html=True)
    C_ = T_["catchments"]
    props = {int(f["properties"]["HYBAS_ID"]): f["properties"] for f in B["catchments"]["features"]}
    tabs = st.tabs([lab for _, lab, _ in MEASURES])
    for tab, (k, label, _) in zip(tabs, MEASURES):
        with tab:
            d = pd.DataFrame({"HYBAS_ID": C_["id"], "ha": C_[f"{k}_ha"], "t": C_[f"{k}_t"]})
            d = d[(d.ha >= 200) & d.HYBAS_ID.isin(props.keys())]
            d["per_ha"] = d.t / d.ha
            d = d.nlargest(15, "per_ha")
            d["Catchment"] = [f"#{props[h]['rank_main']} · {props[h]['district']}" for h in d.HYBAS_ID]
            st.dataframe(d[["Catchment", "ha", "t", "per_ha"]].rename(columns={
                "ha": "Eligible ha", "t": "Saved if all treated, t/yr", "per_ha": "Saved per ha, t/yr"}),
                hide_index=True, width="stretch",
                column_config={"Saved per ha, t/yr": st.column_config.NumberColumn(format="%.0f"),
                               "Saved if all treated, t/yr": st.column_config.NumberColumn(format="localized")})
    st.caption("How it is worked out: the soil-loss recipe (A = rain × soil × slope × cover × protection) "
               "is re-run with the works in place, on the land where each measure applies; one hectare "
               "takes one measure (replanting first, then terraces, then bunds). Values are from the "
               "literature and provisional, to confirm with the Soil Conservation Department; costs per "
               "hectare can be added to rank by soil saved per rupee.")


def _bare_rgba(B, y: int, cmp) -> tuple:
    """(RGBA, legend names, colours, shares) for one dry season, or its change
    against another (percentage points of the square that is bare)."""
    import numpy as np
    b = B["change"][f"bare_{y}"].astype(int)
    seen = b != 255
    if cmp is None:
        cls = np.where(seen, np.digitize(b, BARE_EDGES) + 1, 0)
        names, colors = BARE_NAMES, BARE_COLORS
    else:
        b0 = B["change"][f"bare_{cmp}"].astype(int)
        seen &= b0 != 255
        cls = np.where(seen, np.digitize(b - b0, DIFF_EDGES) + 1, 0)
        names, colors = DIFF_NAMES, DIFF_COLORS
    n = max(int(seen.sum()), 1)
    shares = [float((cls == i + 1).sum()) / n for i in range(len(colors))]
    return rgba_overlay(cls.astype("uint8"), colors, alpha=255), names, colors, shares


def _series(p_or_yearly, years, key):
    """One value per year for a unit (its list) or for the state (yearly dict)."""
    if isinstance(p_or_yearly, dict) and str(years[0]) in p_or_yearly:
        return [p_or_yearly[str(y)].get(key) for y in years]
    v = p_or_yearly.get(key)
    return v if isinstance(v, list) else [None] * len(years)


def _test_rows(ch: dict) -> str:
    t = ch["tests"]
    e3 = ch.get("E3") or {}

    def row(name, ok, text):
        col = "#4cc37a" if ok else ("#9aa3ad" if ok is None else "#e5534b")
        word = "passed" if ok else ("not run yet" if ok is None else "failed")
        return U._row("✔" if ok else ("…" if ok is None else "✕"), col, f"<b>{name}</b><br><small>{text}</small>",
                      f"<span style='color:{col}'>{word}</span>")
    f1, f2, h1 = t["F1_stable_forest"], t["F2_tea"], t["H1_hansen_clearing"]
    pct = lambda v: "–" if v is None else (f"{100 * v:.2f}%" if v < 0.001 else f"{100 * v:.1f}%")
    rows = [
        row("False alarms on stable forest", f1["pass"],
            f"{pct(f1['rate'])} of {f1['cell_years']:,} forest square-years flagged; limit "
            f"{pct(f1['bar'])}. Forest that global forest-loss maps show untouched since 2000."),
        row("False alarms from tea pruning", f2["pass"],
            f"{pct(f2['rate'])} of {f2['cell_years']:,} tea-garden square-years flagged; limit "
            f"{pct(f2['bar'])}."),
        row("Catches real clearing", h1["pass"],
            f"{pct(h1['rate'])} of {h1.get('cell_events', 0):,} squares cleared in 2020–2025 (global "
            f"forest-loss maps) flagged that year or the next; aim {pct(h1['bar'])} or more."),
        row("Blind check on dated satellite pictures", e3.get("pass"),
            (f"flagged squares: {pct(e3['flag']['share_yes'])} showed new bare or burnt ground "
             f"(aim ≥ {pct(e3['flag']['bar'])}); unflagged: {pct(e3['unflagged']['share_yes'])} "
             f"(limit {pct(e3['unflagged']['bar'])})") if e3 else
            "80 pictures, labelled before the answer key is opened."),
    ]
    return "".join(rows)


def _change_page(B, s) -> None:
    meta = B["meta"]
    ch = meta.get("change")
    focus = U.page_head("Change over time", f"{meta['state']} · bare ground each dry season, "
                        "from Sentinel-2 satellite pictures", icon="◬",
                        search_row=lambda: _district_pick(B), warn=False)
    if not ch or B.get("change") is None:
        st.info("The dry-season change layers are not built yet "
                "(`scripts/build/cover_change.py`, then the bundle export).")
        return
    U.key_row("measured", "er_estimate",
              note="Bare ground is measured from satellite pictures. The loss with each year's "
                   "cover is an estimate.")
    years = ch["years"]
    c1, c2 = st.columns([3, 2])
    with c1:
        y = st.segmented_control("Dry season", years, default=years[-1], key="ch_year",
                                 label_visibility="collapsed") or years[-1]
    with c2:
        opts = ["none"] + [v for v in years if v != y]
        cmp = st.selectbox("Compare with", opts, key="ch_cmp", label_visibility="collapsed",
                           format_func=lambda v: "No comparison" if v == "none"
                           else f"Compare with {v}")
    cmp = None if cmp == "none" or cmp == y else int(cmp)
    rgba, names, colors, shares = _bare_rgba(B, y, cmp)
    overlays = [rgba]
    shown = ch["flags_shown"] and f"flag_{y}" in B["change"]
    if shown and s.get("flags", True):
        overlays.append(rgba_overlay(B["change"][f"flag_{y}"], [FLAG_COLOR], alpha=255))
    st.caption(("Share of each square that was bare or burnt in the dry season (1 Feb – 30 Apr), "
                f"{y}." if cmp is None else
                f"Change in the bare share of each square, dry season {cmp} → {y}, in points of "
                "the square.")
               + " Uncoloured land was too cloudy that season, or is river land, water or towns.")

    c_map, c_side = st.columns([2.5, 1.25], gap="medium")
    with c_map:
        _map(B, "main", s, focus or ALL, overlays=overlays, key=f"_ch{y}_{cmp}")
        syms = (f"<div class='lg'><i style='background:{FLAG_COLOR}'></i>new bare ground on a "
                "steep slope</div>") if shown else ""
        st.markdown(U.legend(names, colors, shares, syms=syms,
                             tip="Measured from Sentinel-2 at 10 m: a pixel is bare when its "
                                 "median greenness (NDVI) over the season's clear looks is "
                                 "below 0.30. Shares are of the land seen clearly."),
                    unsafe_allow_html=True)
    with c_side:
        f = _feature(B, focus) if focus and focus != ALL else None
        p = f["properties"] if f else None
        src = p if p else ch["yearly"]
        steep = _series(src, years, "dry_steep_bare" if p else "bare_pct_of_steep_scored_evaluable")
        i = years.index(y)
        base = cmp if cmp is not None else years[0]
        j = years.index(base)
        now, then = steep[i], steep[j]
        where = _esc(focus) if p else meta["state"]
        tiles = [U._tile("Steep land bare", "–" if now is None else f"{now:.1f}%",
                         f"{where}, dry season {y}, slopes ≥ 10°", "measured")]
        if now is not None and then is not None and base != y:
            tiles.append(U._tile(f"Since {base}", f"{now - then:+.1f}",
                                 f"points ({then:.1f}% → {now:.1f}%)", "measured"))
        yr = ch["yearly"][str(y)]
        tiles.append(U._tile("Seen clearly", f"{yr['evaluable_pct_of_scored']:.0f}%",
                             "of scored land; the rest too cloudy that season"))
        loss = _series(src, years, "dry_meanA" if p else "meanA_dry_tpha")
        if loss[i] is not None:
            tiles.append(U._tile("Loss with this year's cover", f"{loss[i]:.1f}",
                                 f"t/ha/yr on average; {loss[j]:.1f} in {base}" if base != y
                                 and loss[j] is not None else "t/ha/yr on average", "er_estimate"))
        if shown:
            new = (_series(p, ch["flag_years"], "dry_new_ha") if p
                   else [ch["yearly"][str(v)].get("flags") for v in ch["flag_years"]])
            k = ch["flag_years"].index(y) if y in ch["flag_years"] else None
            if k is not None and new[k] is not None:
                tiles.append(U._tile("Newly bare, steep", f"{new[k]:,} ha",
                                     f"squares flagged in {y}", "measured"))
        st.markdown(U._sec(where) + U._tiles(tiles, 2), unsafe_allow_html=True)
        vals = [v or 0 for v in steep]
        st.markdown(U._sec("Steep land bare, each dry season", U.badge("measured", mini=True))
                    + U.bars(vals, [str(v)[2:] for v in years], ["#c9a25a"] * len(years),
                             [f"{v}: {'too cloudy' if s_ is None else f'{s_:.1f}%'}"
                              for v, s_ in zip(years, steep)], on=i),
                    unsafe_allow_html=True)
        _change_top(B, y, base)
    st.markdown(U._sec("Tests the change flags must pass before they are shown",
                       note="written down before any result existed")
                + _test_rows(ch), unsafe_allow_html=True)
    if ch.get("attempt", 1) == 2:
        st.caption("These are the second attempt's results. The first flagged any square that "
                   "turned mostly bare; it failed the catch-rate and picture checks, because "
                   "ground that is always sparse in the dry season tipped over the line in dry "
                   f"years. The second also asks for a real loss of greenness (at least "
                   f"{ch.get('drop_min', 0.2):.2f} in NDVI), and was judged on new pictures.")
    if not ch["flags_shown"]:
        st.caption("Until all of them pass, the map shows the measured bare ground only, "
                   "without flags.")


def _change_top(B, y: int, base: int, n: int = 8) -> None:
    years = B["meta"]["change"]["years"]
    i, j = years.index(y), years.index(base)
    rows = []
    for f in B["catchments"]["features"]:
        p = f["properties"]
        sb, ev = p.get("dry_steep_bare"), p.get("dry_eval")
        if not sb or (p.get("dry_steep_km2") or 0) < 5 or base == y:
            continue
        if sb[i] is None or sb[j] is None or (ev[i] or 0) < 50 or (ev[j] or 0) < 50:
            continue
        rows.append((sb[i] - sb[j], p, sb[j], sb[i]))
    if not rows:
        return
    rows.sort(key=lambda r: -r[0])
    html_rows = [U._row(f"#{p['rank_main']}", "#c9a25a",
                        f"{_esc(p['district'])} · {p['dry_steep_km2']:.0f} km² steep",
                        f"{d:+.0f} pts<br><small>{a:.0f}% → {b:.0f}%</small>")
                 for d, p, a, b in rows[:n]]
    st.markdown(U._sec(f"Catchments getting barer, {base} → {y}", U.badge("measured", mini=True),
                       note="steep land, ≥ 5 km²") + "".join(html_rows), unsafe_allow_html=True)


def _table(feats, cols: dict) -> pd.DataFrame:
    df = pd.DataFrame([f["properties"] for f in feats])
    return df[list(cols)].rename(columns=cols)


# Adjustable weights (design §5.5): what an officer can rank catchments by. Each criterion
# becomes a percentile across all ranked catchments; the score is their weighted mean.
# The defaults reproduce the main ranking (average loss only).
CRITERIA = [("avg", "Average loss", "Mean estimated soil loss over the catchment's scored land", 1),
            ("high", "Share of high-risk land", "Share of scored land at ≥ 10 t/ha/yr", 0),
            ("total", "Total soil lost", "Tonnes a year over the whole catchment: big catchments count more", 0),
            ("barer", "Getting barer lately", "Steep ground bare in the dry season: 2024–26 against 2019–21, "
                                              "points of the steep land (measured from satellite)", 0),
            ("villages", "Villages in it", "Named places listed in the catchment (an incomplete list: a rough "
                                           "pointer to people living there)", 0),
            ("deliv", "Soil reaching streams", "Tonnes per hectare a year estimated to reach a stream: where "
                                               "silting of rivers and reservoirs starts (an estimate, untested)", 0)]


def _criteria(B) -> pd.DataFrame:
    """One row per ranked catchment: the raw criteria and their percentiles."""
    import numpy as np
    rows = []
    for f in B["catchments"]["features"]:
        p = f["properties"]
        sb = p.get("dry_steep_bare") or []
        vals = [v for v in sb if v is not None]
        barer = (np.nanmean([v for v in sb[-3:] if v is not None]) - np.nanmean([v for v in sb[:3] if v is not None])
                 if len(vals) >= 6 and (p.get("dry_steep_km2") or 0) >= 5 else np.nan)
        rows.append({"HYBAS_ID": int(p["HYBAS_ID"]), "avg": p["meanA_main"], "high": p["high_or_worse_pct"],
                     "total": p["total_t_per_yr"], "barer": barer, "deliv": p.get("delivered_tpha")})
    c = pd.DataFrame(rows)
    P = B.get("places")
    vill = (P.groupby("hybas").size() if P is not None else pd.Series(dtype=float))
    c["villages"] = c.HYBAS_ID.map(vill).fillna(0)
    for k, *_ in CRITERIA:
        c[f"pct_{k}"] = c[k].rank(pct=True).fillna(0.5) * 100
    return c


def _weights() -> dict:
    with st.expander("⚖️ Rank by what matters to you", expanded=False):
        st.caption("Each slider says how much a criterion counts (0 = ignore). Every criterion is turned "
                   "into a percentile across all ranked catchments, and the list is re-ranked by their "
                   "weighted average. With only 'Average loss' on, the order is the main ranking.")
        cols = st.columns(len(CRITERIA))
        w = {}
        for col, (k, label, tip, default) in zip(cols, CRITERIA):
            with col:
                w[k] = st.slider(label, 0, 5, default, key=f"w_{k}", help=tip)
    return w


def _list_page(B) -> None:
    meta = B["meta"]
    U.page_head("Priority list", f"{meta['state']} · where to survey and treat first",
                icon="◬", warn=False)
    U.key_row("er_rank", "er_estimate",
              note="Ranked by average estimated loss over the scored land of each unit.")
    dname = st.selectbox("Show catchments in", [ALL] + sorted(
        f["properties"]["district"] for f in B["districts"]["features"]), key="er_list_d")
    w = _weights()
    crit = _criteria(B)
    tot = sum(w.values())
    if tot == 0:
        st.info("All weights are 0, so nothing can be ranked. Showing the main ranking.")
        w = {k: d for k, *_, d in CRITERIA}
        tot = sum(w.values())
    crit["score"] = sum(crit[f"pct_{k}"] * v for k, v in w.items() if v) / tot
    # ties (the stored figures are rounded) are broken by the main rank, so the default
    # weights give exactly the main ranking
    main = {int(f["properties"]["HYBAS_ID"]): f["properties"]["rank_main"] for f in B["catchments"]["features"]}
    crit["rank_main"] = crit.HYBAS_ID.map(main)
    crit = crit.sort_values(["score", "rank_main"], ascending=[False, True]).reset_index(drop=True)
    crit["your_rank"] = crit.index + 1
    by_id = crit.set_index("HYBAS_ID")
    custom = w != {k: d for k, *_, d in CRITERIA}
    for f in B["catchments"]["features"]:
        p = f["properties"]
        r = by_id.loc[int(p["HYBAS_ID"])]
        p["similar_txt"] = _similar(p)
        p["your_rank"], p["barer_pts"], p["villages"] = int(r.your_rank), r.barer, int(r.villages)
    feats = sorted(B["catchments"]["features"], key=lambda f: f["properties"]["your_rank"])
    if dname != ALL:
        feats = [f for f in feats if f["properties"]["district"] == dname]
    if not feats:
        st.info("No ranked catchment in this district.")
        return
    cat = _table(feats, {**({"your_rank": "Your rank"} if custom else {}),
                         "rank_main": "Rank", "district": "District", "scored_km2": "km² scored",
                         "meanA_main": "Avg loss t/ha/yr", "high_or_worse_pct": "High or worse %",
                         "main_driver": "Main cause", "similar_txt": "Against similar slopes",
                         "hint": "Typical measures",
                         **({"delivered_tpha": "Reaching streams t/ha/yr"}
                            if "delivered_tpha" in feats[0]["properties"] else {}),
                         **({"N_kg_per_ha": "Nitrogen lost kg/ha/yr"}
                            if "N_kg_per_ha" in feats[0]["properties"] else {}),
                         **({"barer_pts": "Getting barer, pts", "villages": "Villages listed"} if custom else {}),
                         **({"top20_pct": "Top 20 in % of runs", "rank_p05": "Rank, best 5%",
                             "rank_p95": "Rank, worst 5%"} if "top20_pct" in feats[0]["properties"]
                            else {"mark": "Firmness"}),
                         "rank_ired": "Rank, other rain map",
                         f"rank_{_runs(meta)[2]}": f"Rank, {_runs(meta)[0][_runs(meta)[2]].lower()}",
                         **({"ai_rank": "AI rank", "agreement": "AI and formula", "ai_reason": "AI's main reason"}
                            if "ai_rank" in feats[0]["properties"] else {}),
                         "HYBAS_ID": "Catchment id"})
    st.markdown(U._sec("Small catchments", U.badge("er_rank", mini=True),
                       note=(f"{len(cat)} shown · ranked by your weights: "
                             + ", ".join(f"{lab.lower()} {w[k]}" for k, lab, *_ in CRITERIA if w.get(k))
                             if custom else
                             f"{len(cat)} shown · firmness from 1,000 runs of the unsettled inputs")),
                unsafe_allow_html=True)
    st.dataframe(cat, hide_index=True, width="stretch", height=380,
                 column_config={"Avg loss t/ha/yr": st.column_config.NumberColumn(format="%.0f"),
                                "High or worse %": st.column_config.NumberColumn(format="%.0f"),
                                "km² scored": st.column_config.NumberColumn(format="%.0f"),
                                "Your rank": st.column_config.NumberColumn(format="%d"),
                                "Getting barer, pts": st.column_config.NumberColumn(
                                    format="%+.1f", help="Steep ground bare in the dry season, 2024–26 "
                                    "against 2019–21, in points of the steep land. Blank: too little steep land."),
                                "Villages listed": st.column_config.NumberColumn(format="%d"),
                                "Nitrogen lost kg/ha/yr": st.column_config.NumberColumn(
                                    format="%.0f", help="Nitrogen in the soil washed off a hectare in a year "
                                    "(SoilGrids topsoil nitrogen × estimated loss; untreated land)."),
                                "Reaching streams t/ha/yr": st.column_config.NumberColumn(
                                    format="%.1f", help="Estimated soil reaching a stream (connectivity "
                                    "model, standard settings; not yet checked against measurements)."),
                                "Top 20 in % of runs": st.column_config.ProgressColumn(
                                    format="%.0f%%", min_value=0, max_value=100,
                                    help="How often this catchment is in the top 20 when the "
                                         "unsettled inputs vary across their plausible ranges "
                                         "(rain map, forest cover value, other cover values, "
                                         "slope formula), 1,000 runs. 80% or more: robust."),
                                "Against similar slopes": st.column_config.TextColumn(
                                    help="What sets the catchment apart from catchments of "
                                         "similar steepness, and how far above their average. "
                                         "Blank: nothing stands out."),
                                "Typical measures": st.column_config.TextColumn(
                                    help="Standard measures for the causes named. A hint, to "
                                         "confirm with the department and in the field."),
                                "Catchment id": st.column_config.NumberColumn(format="%d")})
    dfeats = sorted(B["districts"]["features"], key=lambda f: f["properties"]["rank_main"])
    for f in dfeats:
        f["properties"]["similar_txt"] = _similar(f["properties"])
    dis = _table(dfeats,
                 {"rank_main": "Rank", "district": "District", "meanA_main": "Avg loss t/ha/yr",
                  "high_or_worse_pct": "High or worse %", "total_t_per_yr": "Total t/yr",
                  "main_driver": "Main cause", "similar_txt": "Against similar slopes",
                  "hint": "Typical measures", "rank_ired": "Rank, other rain map",
                  f"rank_{_runs(meta)[2]}": f"Rank, {_runs(meta)[0][_runs(meta)[2]].lower()}",
                  "not_scored_pct": "Not scored %"})
    dis["Total t/yr"] = (dis["Total t/yr"] / 1000).round().astype(int) * 1000
    st.markdown(U._sec("Districts", U.badge("er_rank", mini=True),
                       note="totals rounded to the nearest 1,000 t"), unsafe_allow_html=True)
    st.dataframe(dis, hide_index=True, width="stretch", height=420,
                 column_config={"Avg loss t/ha/yr": st.column_config.NumberColumn(format="%.0f"),
                                "High or worse %": st.column_config.NumberColumn(format="%.0f"),
                                "Total t/yr": st.column_config.NumberColumn(format="localized"),
                                "Not scored %": st.column_config.NumberColumn(format="%.0f")})
    _downloads(B, dis)
    _field_kit(B)


def _downloads(B, dis: pd.DataFrame) -> None:
    import json
    reg, state = B["meta"]["region"], B["meta"]["state"]
    st.markdown(U._sec("Download for planning and GIS",
                       note="opens in QGIS, ArcGIS, Google Earth or Excel"), unsafe_allow_html=True)
    allc = _table(sorted(B["catchments"]["features"], key=lambda f: f["properties"]["rank_main"]),
                  {k: k for k in B["catchments"]["features"][0]["properties"]})
    label = lambda p: f"#{p['rank_main']} {p['district']}"
    d1, d2, d3 = st.columns(3)
    d1.download_button("Catchments (CSV)", allc.to_csv(index=False).encode(),
                       f"soilsense_catchments_{reg}.csv", "text/csv", width="stretch")
    d2.download_button("Districts (CSV)", dis.to_csv(index=False).encode(),
                       f"soilsense_districts_{reg}.csv", "text/csv", width="stretch")
    d3.download_button("Catchments (GeoJSON)", json.dumps(B["catchments"]).encode(),
                       f"soilsense_catchments_{reg}.geojson", "application/geo+json",
                       width="stretch")
    e1, e2, e3 = st.columns(3)
    kml = "application/vnd.google-earth.kml+xml"
    e1.download_button("Catchments (KML)",
                       D.kml(B["catchments"], f"SoilSense catchments, {state}", label),
                       f"soilsense_catchments_{reg}.kml", kml, width="stretch")
    e2.download_button("Districts (KML)", D.kml(B["districts"], f"SoilSense districts, {state}", label),
                       f"soilsense_districts_{reg}.kml", kml, width="stretch")
    if B.get("gpkg") is not None:
        e3.download_button("Everything (GeoPackage)", B["gpkg"].read_bytes(), B["gpkg"].name,
                           "application/geopackage+sqlite3", width="stretch",
                           help="Catchments, districts and the field points as three layers, "
                                "in latitude/longitude (EPSG:4326).")


def _field_kit(B) -> None:
    pts = B.get("points")
    if pts is None or pts.empty:
        return
    fk = B["meta"].get("field_kit", {})
    reg, state = B["meta"]["region"], B["meta"]["state"]
    st.markdown(U._sec("Field kit", U.badge("er_rank", mini=True),
                       note=f"{len(pts)} points to visit"), unsafe_allow_html=True)
    st.caption(f"In each of the top {fk.get('top', 20)} catchments, the {fk.get('points_per', 5)} "
               f"squares with the highest estimated loss, at least {fk.get('gap_m', 500):.0f} m "
               "apart, so a team sees the worst ground across the catchment. Load the GPS file on "
               "a phone or hand-held unit. The CSV has empty columns for what the team finds "
               "(rills, gullies, bare soil, fresh clearing, existing works, photos), so findings "
               "can come back and be checked against the map. This is a planning list: the blind "
               "field comparison for the pilot uses its own points, chosen without the map's class.")
    # A single square's tonnes are the least certain number here, so the table
    # shows its class; the CSV keeps the estimate for the record.
    show = pts[["point_id", "catchment_rank", "district", "lat", "lon", "class", "slope_deg",
                "main_cause", "vs_similar_slopes"]].rename(columns={
        "point_id": "Point", "catchment_rank": "Catchment #", "district": "District",
        "lat": "Lat", "lon": "Lon", "class": "Class", "slope_deg": "Slope °",
        "main_cause": "Main cause", "vs_similar_slopes": "Against similar slopes"})
    st.dataframe(show, hide_index=True, width="stretch", height=260)
    f1, f2, f3 = st.columns(3)
    kml = "application/vnd.google-earth.kml+xml"
    f1.download_button("Field points (CSV, with form columns)", pts.to_csv(index=False).encode(),
                       f"soilsense_field_points_{reg}.csv", "text/csv", width="stretch")
    f2.download_button("Field points (GPS, GPX)", D.points_gpx(pts, f"SoilSense field points, {state}"),
                       f"soilsense_field_points_{reg}.gpx", "application/gpx+xml", width="stretch")
    f3.download_button("Field points (KML)", D.points_kml(pts, f"SoilSense field points, {state}"),
                       f"soilsense_field_points_{reg}.kml", kml, width="stretch")


def _how_change(meta: dict) -> str:
    """The method page's paragraphs on watching change, and on the outside check."""
    ch, nr = meta.get("change"), meta.get("nrsc")
    out = ["""
**This week's erosive rain.** Every visit fetches the next 7 days' forecast rain at points
about 22 km apart, from the same free forecast service the flood and landslide forecasts use.
Each day's rain is turned into erosive strength with the same daily formula behind the
rain-strength map, and compared with the same service's own 16-year history at that place.
That gives two plain numbers: what share of a normal year's erosive rain falls this week, and
how that compares with what is usual for these days of the year. Applied to the erosion map,
it ranks the catchments where this week's rain will wash off the most soil. It is an outlook
from a forecast, and each day's issue is written down. Replayed over the 2024 and 2025
monsoons against satellite-measured rain, it called **when** the erosive weeks came well, but
**which places** within a week only weakly, so read its catchment list as regional.
"""]
    if ch:
        y0, y1 = ch["years"][0], ch["years"][-1]
        shown = ("They passed every test, so they are on the map."
                 if ch["flags_shown"] else
                 "Until they pass every test, the map shows the measured bare ground only.")
        out.append(f"""
**Watching change, every dry season since {y0}.** In the hills, *jhum* plots are cleared in
winter and burned in March–April, and the ground stays bare until the crop grows after the
monsoon starts. So the heavy monsoon rain falls on whatever the dry season left bare. Each
year from {y0} to {y1}, SoilSense measures from Sentinel-2 satellite pictures (10 m, the
clear looks between 1 February and 30 April) how much of every 100 m square is bare or burnt.
Squares too cloudy that season are left blank, never guessed.

- **Change over time** shows any season, or the change between two seasons.
- **New bare ground on a steep slope** (slope 10° or more, a quarter of the square bare after
  two green seasons) is flagged only after it passes tests written down before any result:
  few false alarms on untouched forest and on tea gardens, most real clearing caught, and a
  blind check on dated satellite pictures. {shown}
- **Loss with each year's cover** reruns the recipe with that dry season's bare ground. It
  shows the effect of the change in cover; it is an estimate, not a measurement of soil.
""")
    ai = meta.get("ai")
    if ai and ai.get("ships"):
        auc_ = ai["auc"]
        out.append(f"""
**An AI map beside the formula.** A tree model (the same kind SlideSense uses) learned which
100 m squares ISRO's experts marked as eroded on the national land-degradation map (2015–16),
from terrain, drainage, soil, rain strength and cover. Tested only on 50 km map blocks it never
saw, it told ISRO's eroded land from normal land with a score of **{auc_['ai_A']:.2f}**, against
**{auc_['formula']:.2f}** for the formula and {auc_['slope_alone']:.2f} for slope alone (0.5 is chance), and it ranked
catchments much more like ISRO's map. Two cautions: it learned one survey's eyes, and its
strongest inputs are broad regional patterns (deep soil stoniness, rain strength), so part of
what it learned may be where that survey's mappers marked erosion. The formula stays: it gives the
tonnes, the reasons and the treatment figures.
""")
        eye = ai.get("eyecheck")
        if eye:
            out.append(f"""
**The blind picture check.** To judge both maps against the ground itself, we drew
{eye['pictures']} squares at random (from every formula class, plus terrain-flagged gully
ground), looked at each on satellite pictures without knowing its scores, and marked visible
erosion: bare or cut slopes, cleared hill patches, slips, gullies. Only {eye['yes']} showed it,
so the check is small. The formula's two worst classes showed visible erosion
**{eye['formula_ratio']:.1f}×** as often as its two mildest (it met its bar, though with so few
eroded squares that could still be chance). The AI's top tenth showed it no more often than its
lower half ({100 * eye['ai_top']:.0f}% vs {100 * eye['ai_low']:.0f}%), and the two scores picked out eroded
squares about equally well ({eye['auc_ai']:.2f} for the AI, {eye['auc_formula']:.2f} for the formula). So the AI
is a second opinion that agrees with ISRO's map; it is **not** a better map of erosion you can
see. The terrain flag for gully-prone ground did no better than other open sloping land, so it
is not shown.
""")
    dv = meta.get("delivered")
    if dv:
        out.append(f"""
**Soil reaching streams.** Not all the soil a slope loses reaches a river: much of it settles
lower down, in hollows and fields. For each square we estimate how well the ground below it
connects to the nearest channel (Borselli's index of connectivity: how steep, how bare and how
far the path is), and turn that into a delivery ratio with the standard settings of InVEST, a
widely used open model. Across the state, about **{dv['state_delivered_mt']:.1f}** of the
**{dv['state_loss_mt']:.0f}** million tonnes lost each year ({dv['share_pct']:.0f}%) is estimated to
reach a stream; the typical square passes on {100 * dv['sdr_p10_p50_p90'][1]:.0f}% of its loss
(the middle 80% of squares: {100 * dv['sdr_p10_p50_p90'][0]:.0f}–{100 * dv['sdr_p10_p50_p90'][2]:.0f}%).
It points to where check dams and gully plugs keep most silt out of rivers and reservoirs.
It is **an estimate, not yet checked against measurements**: Assam's river-mud records are one
hand sample a day on large rivers, without river flow, so they cannot weigh tonnes.
""")
    sv = meta.get("soil_value")
    if sv:
        cr, pr = sv["by_cover"]["cropland"], sv["prices"]
        out.append(f"""
**What the lost soil is worth.** Soil washed off a field takes its nutrients with it. We
multiply each square's estimated loss by the nitrogen and organic carbon in its topsoil
(SoilGrids, the 0–30 cm layers). On Assam's **farmland** ({cr['ha'] / 1e5:.1f} lakh ha scored), the
soil washing off carries about **{cr['N_kg_per_ha_mean']:.0f} kg of nitrogen per hectare a year**
on average (half the farmland under {cr['N_kg_per_ha_median']:.0f}), close to **{cr['urea_bags_per_ha_mean']:.1f} bags of urea**,
or **₹{cr['urea_rs_crore_per_yr']:.0f} crore a year** across the state at the farmer's price
(₹{pr['urea_bag_rs']} per {pr['urea_bag_kg']} kg bag; the true cost with the subsidy is several times higher).
Three cautions: it is for **untreated land** (bunded paddies and terraces lose much less); the
eroded soil is usually *richer* in nutrients than the soil it left, which we do not count; and
on **tree-covered land** the tonnes depend on the unsettled forest cover value, so its total
({sv['by_cover']['tree']['N_t_per_yr_low_treeC'] / 1e3:.0f}–{sv['by_cover']['tree']['N_t_per_yr'] / 1e3:.0f} thousand tonnes of
nitrogen a year) is a range, not a figure.
""")
    sb = meta.get("stability")
    if sb:
        top = ", ".join(f"{d['district']} ({d['top5_pct']:.0f}%)" for d in sb["districts_top5_pct"][:3])
        out.append(f"""
**How firm is each rank?** We re-ran the whole ranking {sb['draws']:,} times, each time
picking the unsettled inputs afresh from their plausible ranges: a blend of the two national
rain maps, a cover value for "tree" land anywhere from closed forest (0.003) to tea-and-*jhum*
(0.1), the other cover values ±50%, and either of two slope formulas. **{sb['catchments_robust_top20']}
catchments are in the top 20 in at least 80% of runs** (shown as robust), and
{sb['catchments_top20_in_half_the_runs']} in at least half. Districts are steadier: {top} are in
the top 5 in about three runs out of four. Survey the robust ones first; treat the rest of the
order as indicative until field checks or better inputs settle it.
""")
    if nr:
        x1, x2, x3 = nr["X1"], nr["X2"], nr["X3"]
        word = lambda p: "passed" if p else "did not pass"
        out.append(f"""
**Checked against ISRO's own map.** NRSC's Land Degradation map (1:50,000, 2015–16) was drawn
by eye from satellite imagery and marks where water is eroding the land. It never saw this
recipe. Against it, before looking, we set three marks:
- land NRSC calls eroded scores higher than land it calls normal **{x1['ours']:.0%}** of the
  time (aim ≥ {x1['bar']:.0%}; {word(x1['pass'])}; the national 250 m map: {x1.get('IWED', 0):.0%});
- catchments rank alike: **ρ {x2['ours']:.2f}** (aim ≥ {x2['bar']:.2f}; {word(x2['pass'])};
  national map {x2.get('IWED', 0):.2f});
- districts rank alike: **ρ {x3['ours']:.2f}** (aim ≥ {x3['bar']:.2f}; {word(x3['pass'])};
  national map {x3.get('IWED', 0):.2f}).
""")
    return "".join(out)


def _how_page(B) -> None:
    meta = B["meta"]
    ck = meta["checks"]
    U.page_head("How to read SoilSense", f"{meta['state']} · method, checks and limits",
                icon="◬", warn=False)
    s1 = ck.get("S1", {}).get("main", {})
    ts = meta.get("tree_split", {})
    if ts.get("adopted"):
        sh = ts.get("share_of_tree_pct", {})
        pick = lambda pre: next((v for k, v in sh.items() if k.startswith(pre)), 0)
        cover_para = (
            "2. **Cover on \"tree\" land, now measured.** The satellite land-cover map calls forest, "
            "tea gardens and *jhum* land all \"tree\". Since Phase 1 each such square is split by "
            "canopy height (1 m) and recent clearing (forest-loss maps to 2025): "
            f"**forest {pick('T4'):.0f}%**, **tea or bush {pick('T3'):.0f}%**, "
            f"**regrowing {pick('T2'):.0f}%**, **freshly cleared {pick('T1'):.0f}%** "
            f"(no height data: {pick('T0'):.0f}%). The tea-versus-forest rule was set on "
            f"{ts.get('outlines', {}).get('tea', '?')} OpenStreetMap tea-garden outlines and "
            f"{ts.get('outlines', {}).get('forest', '?')} forest outlines, and scored "
            f"{ts.get('P1', 0):.2f} on a half it never saw; a blind check on satellite pictures "
            "passed too. *Before the tree split* shows the old single value, for comparison.")
    else:
        cover_para = (
            "2. **Cover on \"tree\" land.** The satellite land-cover map calls forest, tea gardens "
            "and young *jhum* fallow all \"tree\". The value used (0.03) is a fair average for "
            "that mix but too high for closed forest. *Lower forest value* shows the opposite "
            "case. The fix, splitting the class with satellite pictures, is the next phase.")
    st.markdown(f"""
**What it estimates.** How much soil rain washes off the land each year, in tonnes per hectare,
from the standard recipe used in Indian soil-conservation work (RUSLE). It multiplies five things:
**how hard the rain hits** (rain strength), **how easily the soil washes** (soil), **how steep and
long the slope is**, **how bare the ground is** (cover) and **protection** such as bunds and
terraces. Protection is unknown to us, so the map shows land **as if untreated**.

**Kinds of number.**
- *Estimate* (t/ha/yr): indicative, and can be off by a factor of several.
- *Class*: the estimate cut at 5, 10, 20, 40 and 80 t/ha/yr. It is as uncertain as the
  estimate.
- *Rank*: where to act first. It is the firmest number here, and it is marked when it
  depends on the rain map.

None of these is a chance.

**What is not scored** (left uncoloured): rivers and land within 2 m of a large river, water and
towns. On that land floods and bank cutting move the soil, and this recipe sees neither. That is
**{100 - meta['scored_pct']:.0f}%** of {meta['state']}.

**Two inputs are not settled yet, so both alternatives are shown.**
1. **Rain strength.** Two national maps exist. The one used checks within 5% of the only
   gauge-measured value we have (Guwahati); the other is 46% low there, and they disagree
   on the exact catchment order. *Other rain map* shows the difference. Catchments that stay
   in the top 20 under both are marked *firm*.
{cover_para}

**Checks it passed before being shown.**
- Hills come out about **{s1.get('ratio', 0):.0f}×** worse than plains.
- The rain map lands within 5% of the Guwahati gauge; the formula most Indian studies use
  reads 91% low there.
- No class takes most of the land.
- Un-scored land is never given a class.
- The top 20 catchments were each checked by eye on satellite pictures: all are steep, and
  half show cleared or bare slopes.
- Compared with the national 250 m erosion map, the order differs because that map's slope
  factor barely changes between flat and steep ground. Ours follows the slope, so our list
  starts in the hills.

{_how_change(meta)}
**Limits.**
- Sheet and rill erosion only. Not gullies, riverbanks or landslides.
- Satellite rain misses short bursts.
- Soil comes from a 250 m global model.
- The terrain model includes treetops; flat land beside trees is corrected for this.
- District outlines are the Survey of India's official set (35 districts).

**What lifts these limits:**
- the department's treated-area records (protection);
- soil surveys;
- rain-intensity gauges;
- field checks of the ranked catchments.
""")


def render(shell) -> None:
    st.markdown(U.FS_CSS, unsafe_allow_html=True)
    view = _nav()
    region = _region()
    if region is None:
        st.error("**The SoilSense bundle is missing.** Run "
                 "`scripts/run/export_erosion_bundle.py` with REGION set.")
        return
    B = D.load(region)
    if view == "Erosion map":
        s = _settings()
        _map_page(B, s)
    elif view == "This week":
        s = _settings()
        _week_page(B, s)
    elif view == "Village card":
        _village_page(B, {})
    elif view == "What if we treat it?":
        _treat_page(B)
    elif view == "Change over time":
        s = _settings()
        _change_page(B, s)
    elif view == "Priority list":
        _list_page(B)
    else:
        _how_page(B)
