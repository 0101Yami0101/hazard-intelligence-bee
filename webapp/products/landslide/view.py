"""SlideSense pages.

Everything lives inside render() on purpose. The page needs about twenty
values that are fixed for one rerun — the grid, the bundle, the sidebar
settings, today's rainfall — and the helpers below close over them instead of
taking twenty arguments each. That is the same shape the module had as a flat
script, which is why moving it here changed no behaviour.

Since 2026-10-10 the pages are dashboards in FloodSense's style, built from
the same shared pieces (products/flood/ui.py): a header with the place
search, a row of tiles, then place | map | side panel, every number wearing
the badge of what kind of number it is. The maths did not change; district
figures did — they are now taken over each district's real outline
(GR.district_raster), not the box around it. docs/design/SLIDESENSE_SCREEN.md.
"""
from __future__ import annotations

import html
from datetime import date, datetime

import folium
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from folium.plugins import FastMarkerCluster, HeatMap
from streamlit_folium import st_folium

import core.deck3d as D3
import core.geo as G
import core.grid as GR
import core.mapping as M
import core.rainfall as RN
import core.roads as RD
import core.theme as T
import products.landslide.model as fc
from core.location import ask_again
from core.settings import map_settings
from products.flood import ui as U          # the shared dashboard look

# Rain-trigger ramp — BLUE, deliberately not the green-to-red hazard ramp:
# reusing one ramp for both would make "very wet" and "very dangerous" look
# like the same statement.
#
# ⚠️ Kept although the Forecast page no longer draws this layer. The rain
# trigger is getting a page of its own; trigger_classes() below is its
# renderer, and deleting the pair now would only mean writing them again.
TRIG_NAMES = ["Normal", "Above normal", "Wet", "Very wet", "Exceptional"]
TRIG_COLORS = ["#0b3a5b", "#1565a8", "#2f9fd8", "#7fd4f0", "#d8f6ff"]
TRIG_CUTS = np.array([0.50, 0.75, 0.90, 0.97], dtype=np.float32)

# 3D terrain view: built and working, but held back while the surface
# rendering is finished. One flag governs both toggles; nothing else is
# stubbed, so clearing it restores the feature everywhere at once.
WIP_3D = True

# How far from a road the 3D view paints the forecast. Beyond this a slope
# cannot plausibly put debris on the carriageway, and drawing it would bury the
# road in colour that is not about the road.
CORRIDOR_KM = 5.0
ROUTE_CORRIDOR_KM = 4.0   # one route needs less context than the whole net

# Evidence and Model & Validation still exist — the branches near the bottom
# of this file — but no longer earn a permanent sidebar slot. They're reached
# from the shared ℹ️ popover instead (see Product.extra_nav in
# products/__init__.py), which sets st.session_state.view to one of their
# labels directly, so the render logic below needed no change at all.
# The forecast is listed LAST in the side menu (the user, 2026-10-12), but it
# is still the page the module opens on: HOME, not VIEWS[0].
VIEWS = [("🛣️", "Roads"), ("🗺️", "Susceptibility"), ("📍", "Forecast")]
HOME = "Forecast"

MAP_H = U.MAP_H
# The cuts the susceptibility map is drawn with, and the hazard score at
# which a place is Very High (model.classify) — the day bars are scaled to it,
# so a quiet place's bars stay small instead of filling the card.
SUS_CUTS = np.array([.05, .15, .35, .60], dtype=np.float32)
TOP_CUT = 0.30
# Days 5-7 rest on rain forecasts that are weaker that far ahead: dashed.
LATER_FROM = 4
LATER_HELP = "Less sure: rests on rain forecasts this far ahead"
# Levels as they fit on a day button (the full name is the button's hint).
LEVEL_SHORT = ["V.Low", "Low", "Mod", "High", "V.High"]
# Districts to watch: as many as fit beside the map.
WATCH_N = 6


def render(shell) -> None:
    from core.rainfall import load_forecast
    from products.landslide.data import load_model, load_times_usual

    grid, geo, ELEV = shell.grid, shell.geo, shell.elev
    PLACES, PLACE_IDX, LOOKUP = shell.places, shell.loc.place_idx, shell.lookup
    H, W = grid.height, grid.width
    WEST, EAST = grid.west, grid.east
    SOUTH, NORTH = grid.south, grid.north
    DLON, DLAT = grid.dlon, grid.dlat
    CELL_KM = grid.cell_km
    DISTRICTS, ROADS = geo.districts, geo.roads

    SUS, NEAR, QUANT, PTS, MET, INVENTORY = load_model()
    TU = load_times_usual()
    fx = load_forecast(tuple(PTS["lat"]), tuple(PTS["lon"]))
    LIVE = fx is not None

    # ─────────────────────── sidebar ─────────────────────────────────────────
    if "view" not in st.session_state:
        st.session_state.view = HOME

    # Derived, never typed in. An earlier build hardcoded "37,788" in three
    # places; when the inventory was clipped to the state the app kept quoting
    # the old figure while the map drew 494 fewer dots.
    N_INV = len(INVENTORY) if INVENTORY else MET["labels"]["polygons"]

    with st.sidebar:
        for icon, label in VIEWS:
            active = st.session_state.view == label
            if st.button(f"{icon}  {label}", key=f"nav_{label}", width="stretch",
                         type="primary" if active else "secondary"):
                if not active:
                    # Rerun immediately: the other buttons in this same loop
                    # were already rendered from pre-click state, so without
                    # this the highlight lags a click behind.
                    st.session_state.view = label
                    # each page has its own map: without this, picking on
                    # the new page the place last picked on the old one
                    # left the new map where it opened
                    st.session_state.pop("map_target", None)
                    st.rerun()
        view = st.session_state.view

        st.divider()
        s = map_settings(
            opacity_label="Hazard overlay opacity",
            roads_help="5,536 major roads. Road cuts over-steepen slopes — the "
                       "strongest proximity signal in our inventory.",
            rivers_help="7,181 main stems. Rivers undercut slope toes, removing "
                        "what holds them up.")

        st.markdown("<div class='side-label'>Landslide inventory</div>",
                    unsafe_allow_html=True)
        inv_mode = st.radio("Inventory", ["Off", "Heatmap", "Clusters"],
                            horizontal=True, index=0, label_visibility="collapsed",
                            disabled=s.bare, key="ls_inv",
                            help=f"{N_INV:,} landslides mapped by GSI, NRSC Bhuvan "
                                 "and APSAC, clipped to the state — the evidence "
                                 "the model is built on.")
        if s.bare:
            inv_mode = "Off"

    # ─────────────────────── forecast maths ──────────────────────────────────
    if LIVE:
        days, rain = fx
        trig = fc.trigger_series(rain, QUANT)          # (n_days, n_points)
        fut = RN.forecast_days(days)
    else:
        days, rain, trig, fut = [], None, None, []

    def latlon_to_px(lat, lon):
        return grid.to_px(lat, lon)

    def inv_extra(fg):
        """Every mapped landslide inside the state.

        Individual markers would stall the browser at this count, so: a heatmap
        for the density story, or FastMarkerCluster (which buckets client-side)
        when someone wants to drill into individual failures.

        Both plugins carry their own JS. streamlit_folium collects those links
        by walking the map AFTER the feature group has been attached, so they
        load correctly even though the group is not part of the base map —
        verified before relying on it.
        """
        if inv_mode == "Off" or not INVENTORY:
            return
        pts = [(d["y"], d["x"]) for d in INVENTORY]
        if inv_mode == "Heatmap":
            HeatMap(pts, radius=8, blur=11, min_opacity=.35,
                    gradient={0.2: "#1e3a8a", 0.45: "#38bdf8",
                              0.7: "#fde047", 1.0: "#dc2626"},
                    name="Landslide density").add_to(fg)
        else:
            FastMarkerCluster(pts, name="Mapped landslides").add_to(fg)

    def base_map():
        return M.base_map(grid, s)

    def overlay_group(img=None, districts=False, marker=None, inventory=True, more=None,
                      focus=None):
        """`more`: a function that adds the page's own layers after the
        inventory (a route, the full-screen panel). `focus`: the selected
        district's outline, which then alone stays lit."""
        def extra(fg):
            if inventory:
                inv_extra(fg)
            if more is not None:
                more(fg)
        return M.overlay_group(grid, s, geo, img=img, districts=districts,
                               marker=marker, extra=extra, focus=focus)

    def legend_strip(names, colors, shares=None, note=""):
        M.legend_strip(names, colors, shares, note, bare=s.bare)

    @st.cache_resource(show_spinner=False)
    def road_chunks():
        """The network cut into ~1 km pieces. Cached: geometry never changes,
        and only the colour on top of it does. cache_resource for the same
        reason as road_graph — 3,995 pieces are not worth re-copying on every
        rerun."""
        return RD.chunk_roads(ROADS["features"])

    def sample_classes(cls, lat, lon):
        """Hazard class under each road piece. Vectorised — 3,995 pieces a day.

        Out-of-grid pieces return 0 ("not assessed") rather than being dropped,
        so the kilometre totals below always add up to the network length.
        """
        r, c, ok = grid.to_px_array(lat, lon)
        out = np.zeros(len(lat), dtype=np.uint8)
        out[ok] = cls[r[ok], c[ok]]
        return out

    @st.cache_resource(show_spinner=False)
    def road_graph():
        """Routable graph over the mapped network. Built once, ~0.03 s.

        ⚠️ cache_resource, not cache_data: cache_data deep-copies what it
        returns on every access, and this is a 6,843-node dict of dicts fetched
        on every rerun. Nothing mutates it, so sharing one object is both
        correct and far cheaper.
        """
        return RD.build_graph(ROADS["features"])

    @st.cache_data(show_spinner=False)
    def route_between(a_lat, a_lon, b_lat, b_lon):
        """Shortest mapped road between two points, as ([[lon, lat], ...], km).

        Cached on the coordinates: the same pair is re-requested on every day
        button, layer toggle and opacity nudge.
        """
        adj, pos = road_graph()
        na, da = RD.nearest_node(adj, pos, a_lat, a_lon)
        nb, db = RD.nearest_node(adj, pos, b_lat, b_lon)
        line, km = RD.shortest_path(adj, pos, na, nb)
        return line, km, da, db

    def route_geojson(line, cls, step_km: float = 0.6):
        """The route cut into short pieces, each coloured by its own forecast."""
        lo, la, at = RD.densify(line, step_km)
        k = sample_classes(cls, la, lo)
        feats = []
        for i in range(len(at) - 1):
            feats.append({"type": "Feature",
                          "geometry": {"type": "LineString",
                                       "coordinates": [[float(lo[i]), float(la[i])],
                                                       [float(lo[i + 1]), float(la[i + 1])]]},
                          "properties": {"c": int(k[i]),
                                         "cls": T.CLASS_NAMES[k[i] - 1] if k[i]
                                                else "Not assessed",
                                         "km": round(float(at[i]), 1)}})
        return {"type": "FeatureCollection", "features": feats}, lo, la, at, k

    @st.cache_data(show_spinner=False)
    def route_corridor_mask(lons: tuple, lats: tuple, half_km: float):
        """Cells within `half_km` of one route. Cached on the rounded polyline,
        so panning the day strip does not rebuild it."""
        return GR.disc_mask(grid, np.asarray(lats), np.asarray(lons), half_km)

    @st.cache_data(show_spinner=False)
    def road_corridor_mask(half_km: float = 6.0):
        """Cells within `half_km` of a road, as a boolean grid."""
        _, la, lo, _, _, _ = road_chunks()
        return GR.disc_mask(grid, la, lo, half_km)

    def route_elevation(lons, lats):
        """Ground height at each profile sample, in metres. NaN off-grid."""
        out = np.full(len(lons), np.nan)
        if ELEV is None:
            return out
        for i, (lo, la) in enumerate(zip(lons, lats)):
            px = latlon_to_px(la, lo)
            if px is not None and np.isfinite(ELEV[px]):
                out[i] = float(ELEV[px])
        return out

    def route_paths_3d(lons, lats, r_cls, run: int = 6):
        """The route as short 3-D paths, coloured by forecast.

        Grouped into runs of `run` samples so the 3D view carries a few hundred
        path segments rather than one per half-kilometre.
        """
        z = route_elevation(lons, lats)
        z = np.nan_to_num(z, nan=800.0)
        out = []
        for i in range(0, len(lons) - 1, run):
            j = min(i + run, len(lons) - 1)
            k = int(np.max(r_cls[i:j + 1])) if j > i else int(r_cls[i])
            col = T.CLASS_COLORS[k - 1] if k else T.NOT_ASSESSED
            out.append({
                "p": [[float(lons[t]), float(lats[t]),
                       (float(z[t]) + 110.0) * D3.EXAG]
                      for t in range(i, j + 1)],
                "c": [int(col[1:3], 16), int(col[3:5], 16), int(col[5:7], 16)],
                "tip": T.CLASS_NAMES[k - 1] if k else "Not assessed"})
        return out

    def road_geojson(chunks, c_cls, c_km) -> dict:
        """One FeatureCollection of coloured pieces.

        Pieces rather than whole roads on purpose: the longest single road
        feature runs 49 km, and colouring all of it by one value would paint a
        safe valley stretch the same red as the gorge it climbs into.
        """
        return {"type": "FeatureCollection", "features": [
            {"type": "Feature",
             "geometry": {"type": "LineString", "coordinates": ch},
             "properties": {"c": int(k),
                            "cls": T.CLASS_NAMES[k - 1] if k else "Not assessed",
                            "km": round(float(d), 2)}}
            for ch, k, d in zip(chunks, c_cls, c_km)]}

    def forecast_cells(cls, stride: int = 2, mask=None, alpha: float = 205):
        """Every assessed cell as a flat coloured patch lying on the terrain.

        `stride` thins the grid: statewide at stride 1 is ~288,000 patches, a
        multi-megabyte payload rebuilt on every redraw, for detail the camera
        cannot resolve at that height anyway.

        ⚠️ Patch size follows the stride AND is deliberately larger than it.
        Thinning without widening is what turned the surface into polka dots.
        The OVERLAP factor is what makes it read as one skin instead of loose
        tiles: a patch wider than the step to its neighbour covers the drop
        between them, which is the job an extruded block used to do — badly, by
        showing its walls on every slope.
        """
        LON, LAT = grid.cell_lonlat()
        keep = cls > 0
        if mask is not None:
            keep &= mask
        thin = np.zeros_like(keep)
        thin[::stride, ::stride] = True
        keep &= thin
        if not keep.any():
            return "", "", 0, 700.0
        z = ELEV[keep] if ELEV is not None else np.full(int(keep.sum()), 800.0)
        z = np.nan_to_num(z, nan=800.0)
        k = cls[keep].astype(int) - 1
        rgb = np.array([[int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)]
                        for h in T.CLASS_COLORS], dtype=np.uint8)[k]

        # Match SlopeSense v1's proportions: it draws 400 m marks on a 278 m grid.
        OVERLAP = 1.44
        step_lon_m = DLON * stride * 98_900
        step_lat_m = DLAT * stride * 111_000
        cell_m = max(step_lon_m, step_lat_m) * OVERLAP
        # Back to degrees per axis for the corner offset — a square in metres is
        # not a square in degrees, and the offset has to be in the units the
        # coordinates are actually in.
        pb, cb, n = D3.pack_cells(LON[keep], LAT[keep], z, rgb,
                                  cell_m / 98_900, cell_m / 111_000, alpha)
        return pb, cb, n, cell_m

    def road_paths_3d(chunks, c_cls, every: int = 1):
        """Road pieces as 3-D paths, coloured by their own forecast."""
        if ELEV is None:
            return []
        out = []
        for ch, k in zip(chunks[::every], c_cls[::every]):
            pts = []
            for lon, lat in ch:
                px = latlon_to_px(lat, lon)
                z = (800.0 if px is None or not np.isfinite(ELEV[px])
                     else float(ELEV[px]))
                # 5 dp is ~1 m, far finer than a 490 m cell, and trims about a
                # third off the JSON — this whole page is already ~1.9 MB.
                pts.append([round(lon, 5), round(lat, 5),
                            round((z + 90.0) * D3.EXAG, 1)])
            col = (T.CLASS_COLORS[int(k) - 1] if k else T.NOT_ASSESSED)
            out.append({"p": pts,
                        "c": [int(col[1:3], 16), int(col[3:5], 16),
                              int(col[5:7], 16)],
                        "tip": T.CLASS_NAMES[int(k) - 1] if k else "Not assessed"})
        return out

    def trigger_classes(tri_pts):
        """Rain-trigger raster, painted from each cell's nearest weather point.

        ⚠️ Masked to the SAME domain as susceptibility. Rain exists everywhere,
        but showing it on ice and open water invites the reading that those
        cells are part of the assessment — they are not.
        """
        t = tri_pts[NEAR]
        out = np.zeros(t.shape, np.uint8)
        ok = SUS != 255
        out[ok] = (np.digitize(t[ok], TRIG_CUTS) + 1).astype(np.uint8)
        return out

    @st.cache_data(show_spinner=False)
    def susceptibility_classes():
        su = SUS.astype(np.float32)
        su[SUS == 255] = np.nan
        su /= 254.0
        ok = np.isfinite(su)
        out = np.zeros(su.shape, np.uint8)
        out[ok] = (np.digitize(su[ok], SUS_CUTS) + 1).astype(np.uint8)
        return out

    # ─────────────────────── districts ───────────────────────────────────────
    @st.cache_resource(show_spinner=False)
    def district_ids():
        """Which district each cell is in — the real outlines, drawn once
        (GR.district_raster). Every district figure and every district clip
        on these pages reads this one raster."""
        return GR.district_raster(grid, DISTRICTS)

    def district_index(label: str) -> int:
        """1-based id of a "<name> district" search result, 0 if it is not one."""
        name = label[:-9] if label.endswith(" district") else label
        names = district_ids()[1]
        return names.index(name) + 1 if name in names else 0

    def district_counts(cls) -> np.ndarray:
        """Cells of each class (columns 0..5) in each district (rows, 0 = none)."""
        ids, names = district_ids()
        return np.bincount(ids.ravel().astype(np.int64) * 6 + cls.ravel(),
                           minlength=(len(names) + 1) * 6).reshape(-1, 6)

    def district_table(cls) -> pd.DataFrame:
        """Share of each district at High or Very High — over the district's
        own outline. Same columns the page has always exported."""
        n = district_counts(cls)
        rows = []
        for k, name in enumerate(district_ids()[1], start=1):
            c = n[k, 1:]
            tot = int(c.sum())
            if not tot:
                continue
            rows.append({"District": name,
                         "High+ %": round(100 * float(c[3] + c[4]) / tot, 1),
                         "Peak class": T.CLASS_NAMES[int(np.nonzero(c)[0].max())],
                         "Assessed cells": tot})
        return pd.DataFrame(rows).sort_values("High+ %", ascending=False, kind="stable")

    # ─────────────────────── the week, worked out once ───────────────────────
    # Keyed on the rain itself, not only the date: the rain is re-read every
    # hour, and numbers cached under the date alone would go on describing
    # the earlier rain beside a map drawn from the new one.
    RTAG = (f"{days[fut[0]]}|{len(fut)}|{float(np.nansum(rain)):.1f}" if LIVE else "")

    @st.cache_data(show_spinner=False, max_entries=3)
    def week_classes(tag: str) -> np.ndarray:
        """The level of every cell on each forecast day: (days, H, W)."""
        return np.stack([fc.classify(fc.hazard_raster(SUS, NEAR, trig[i])) for i in fut])

    @st.cache_data(show_spinner=False, max_entries=3)
    def week_numbers(tag: str):
        """Per forecast day: share of assessed land at High or above, share at
        Very High, and kilometres of road at High or above.

        ⚠️ Shares of land, never a maximum over places (see M.day_strip: the
        maximum of many percentiles is ~0.99 on an ordinary day)."""
        hi, vh, rkm = [], [], []
        la = lo = km = None
        if ROADS:
            _, la, lo, km, _, _ = road_chunks()
        for cl in week_classes(tag):
            a = cl[cl > 0]
            hi.append(float((a >= 4).mean()) if a.size else 0.0)
            vh.append(float((a == 5).mean()) if a.size else 0.0)
            rkm.append(float(km[sample_classes(cl, la, lo) >= 4].sum()) if ROADS else 0.0)
        return hi, vh, rkm

    # ─────────────────────── small things every page uses ────────────────────
    def pc(x: float) -> str:
        """A share of land. One decimal while it is under 10%: most days the
        whole story is between 0 and 5."""
        if 0 < x < 0.0005:
            # some land is there: "0.0%" beside "highest level: Very High"
            # would read as a contradiction
            return "<0.1%"
        return f"{100 * x:.1f}%" if x < 0.0995 else f"{100 * x:.0f}%"

    def day_name(i: int) -> str:
        d = datetime.fromisoformat(days[i]).date()
        return "Today" if d == date.today() else d.strftime("%a %d")

    def long_day(i: int) -> str:
        d = datetime.fromisoformat(days[i]).date()
        return ("Today · " if d == date.today() else "") + d.strftime("%A %d %b")

    def current_day() -> tuple[int, int]:
        """(index into `days`, position in the week) of the chosen day. One
        key for Forecast and Roads, so the day carries from one to the other."""
        if st.session_state.get("day_i") not in fut:
            st.session_state.day_i = fut[0]
        return st.session_state.day_i, fut.index(st.session_state.day_i)

    def day_buttons(notes: list[str], colors: list[str], head: str,
                    tips: list[str] | None = None) -> None:
        """The day picker, in the same clothes as FloodSense's: four to a row,
        a coloured top edge, the later days dashed."""
        css = ""
        for j, col in enumerate(colors):
            css += f".st-key-sl_d{j} button{{border-top:3px solid {col}!important}}"
            if j >= LATER_FROM:
                css += (f".st-key-sl_d{j} button{{border-left-style:dashed!important;"
                        "border-right-style:dashed!important;"
                        "border-bottom-style:dashed!important}")
        st.markdown(f"<style>{css}</style>{head}", unsafe_allow_html=True)
        for row in range(0, len(fut), 4):
            cols = st.columns(4, gap="small")
            for col, j in zip(cols, range(row, min(row + 4, len(fut)))):
                with col:
                    tip = (tips[j] if tips else "")
                    if j >= LATER_FROM:
                        tip = (tip + " · " if tip else "") + LATER_HELP
                    if st.button(f"{day_name(fut[j])}  \n**{notes[j]}**", key=f"sl_d{j}",
                                 width="stretch", help=tip or None,
                                 type="primary" if fut[j] == st.session_state.day_i
                                 else "secondary"):
                        st.session_state.day_i = fut[j]
                        st.rerun()

    def search_row():
        """The place picker — the SAME session key as FloodSense on purpose:
        a place searched in one module is still selected in the other.

        `accept_new_options` is what lets a visitor type raw coordinates —
        the gazetteer has 4,648 names but the state has far more places than
        that, and someone standing on a road cut needs the forecast for
        exactly where they are."""
        s1, s2, s3 = st.columns([4.2, 1.3, 1.05], vertical_alignment="bottom")
        with s2:
            if st.button("📍 My location", width="stretch",
                         help="Ask the browser where you are. Only used if you "
                              "are inside Arunachal Pradesh."):
                ask_again()
                st.rerun()
        with s3:
            # The map is deliberately left wherever the user panned it, so this
            # is the only way back to the selected place without re-picking it.
            if st.button("⌖ Recentre", width="stretch",
                         help="Snap the map back to the selected location."):
                st.session_state.recentre = st.session_state.get("recentre", 0) + 1
                st.rerun()
        with s1:
            options = [G.PROMPT] + [p["label"] for p in PLACES]
            # Whatever is currently selected must exist in `options`, or
            # Streamlit rejects the session-state value outright. That covers
            # "My location — near X" and any coordinate the visitor typed or
            # picked off the map, none of which are in the gazetteer.
            cur = st.session_state.get("search")
            if cur and cur not in PLACE_IDX and cur != G.PROMPT:
                options.insert(1, cur)
            st.selectbox("Location", options, key="search",
                         accept_new_options=True, label_visibility="collapsed",
                         help=f"{len(PLACES):,} towns, villages and districts "
                              "— or type coordinates such as 27.09, 93.61")
        return G.resolve(st.session_state.search, PLACES, LOOKUP)

    def where(sel) -> dict:
        """What a selection is, worked out ONE way for every panel on a page.

        ⚠️ A town or a point snaps to the nearest assessed cell (see
        fc.nearest_assessed) and every panel reads that same cell. The old
        inspector read the raw cell while the strip above it read the snapped
        one — "not assessed" and "High" for one place, on one screen.

        kind: "none" | "district" | "outside" | "unassessed" | "point".
        """
        if not sel:
            return {"kind": "none"}
        if sel["kind"] == "district":
            k = district_index(sel["label"])
            if k:
                return {"kind": "district", "k": k, "mask": district_ids()[0] == k,
                        "name": district_ids()[1][k - 1],
                        "feat": GR.feature_by(DISTRICTS["features"], "district",
                                              district_ids()[1][k - 1])}
        px = latlon_to_px(sel["lat"], sel["lon"])
        if px is None:
            return {"kind": "outside"}
        snap = fc.nearest_assessed(SUS, *px)
        if snap is None:
            return {"kind": "unassessed", "px": px}
        r, c, dcells = snap
        return {"kind": "point", "px": px, "r": r, "c": c, "dcells": dcells,
                "su": int(SUS[r, c]) / 254.0, "j": int(NEAR[r, c])}

    def place_sub(sel) -> str | None:
        """The line under a place's name: for a bare coordinate, the nearest
        settlement; otherwise its coordinates (the default)."""
        if sel["kind"] == "district":
            return "district · figures are for its own assessed land"
        if sel["kind"] in ("coords", "me"):
            near, km = G.nearest_place(sel["lat"], sel["lon"], PLACES)
            if near:
                return f"near {html.escape(U._clean(near['label']))} · {km:.0f} km"
        return None

    def snap_foot(w: dict) -> str:
        if w.get("dcells", 0) <= 0:
            return ""
        return ("<div class='fs-foot'>Nearest slope the model scores, "
                f"<b>{w['dcells'] * CELL_KM:.1f} km</b> away "
                + U._i("The point itself is flat ground, open water or ice, which this model "
                       "does not score. Shown is the nearest slope it does assess — the slope "
                       "that would reach the town, not the ground the town stands on.", "right")
                + "</div>")

    EMPTY_OUTSIDE = ("<div class='fs-empty'><b>Outside the mapped area</b><br>This model "
                     "covers Arunachal Pradesh only.</div>")
    EMPTY_UNASSESSED = ("<div class='fs-empty'><b>Not assessed here</b><br>Permanent ice, open "
                        "water, or ground flatter than 10° for several kilometres in every "
                        "direction. The model never trained on this terrain, so it reports "
                        "nothing rather than guessing. Try a nearby settlement.</div>")

    def frame(sel, w: dict, zoom_place: float = 11):
        """Where the map should look, the pin, and the clip: (centre, zoom,
        marker, clip mask). A district is framed by its own size — they range
        from Namsai's few cells to West Siang's 29,000, so one fixed zoom
        either cropped the big ones or lost the small ones."""
        if not sel:
            return None, 7, None, None
        if w["kind"] == "district":
            centre, zoom = M.focus_view(w["feat"])
            # the outline says where it is; a pin adds nothing
            return centre, zoom, None, w["mask"]
        return ((sel["lat"], sel["lon"]), zoom_place,
                (sel["lat"], sel["lon"], sel["label"]), None)

    def district_picks(tab: pd.DataFrame, n: int) -> None:
        """A ranked list of districts as buttons: a click selects the district."""
        css = ""
        for i, row in enumerate(tab.head(n).to_dict("records")):
            css += (f".st-key-fs_pick_{i} button{{border-left:4px solid "
                    f"{T.CLASS_COLORS[3]}!important}}")
            label = f"{row['District']} district"
            if st.button(f"{row['District']}  ·  **{row['High+ %']:.1f}%**",
                         key=f"fs_pick_{i}", width="stretch",
                         help=f"Open {row['District']}",
                         disabled=label not in LOOKUP):
                st.session_state.pending_place = label
                st.rerun()
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

    def colour_key(tier: str, names, colors, shares) -> str:
        """The colour key as it rides on the full-screen map."""
        return (U._sec("Colours on the map", U.badge(tier, where="right"))
                + U.legend(names, colors, shares)
                .replace("class='fs-legend'", "class='fs-legend' style='margin-top:0'", 1))

    def dim_toggle(key: str):
        # ⚠️ 3D is PARKED, not deleted. The control is shown disabled so the
        # feature is visibly coming rather than silently missing, and every 3D
        # code path below is left intact — flip WIP_3D to False and it comes
        # straight back.
        def draw():
            st.segmented_control("View", ["2D", "🔧 3D"], default="2D", key=key,
                                 label_visibility="collapsed", disabled=WIP_3D,
                                 help="3D terrain view — under development.")
        return draw

    def to_view(label: str, text: str, key: str) -> None:
        if st.button(text, key=key, width="stretch"):
            st.session_state.view = label
            st.session_state.pop("map_target", None)
            st.rerun()

    # ── "times the usual": the measured number behind each level ─────────────
    # The card used to headline "4 of 5" — the level's place on a scale, set
    # in big type as if it were a measurement. What IS measured is how many
    # times as common landslides have been: at each level (against an average
    # place and day), at each band of the rain score (against a usual day at
    # the same place) and on each class of ground (against average ground).
    # docs/design/LANDSLIDE_TIMES_USUAL.md. Never multiplied on screen.
    def times(x: float) -> str:
        """One figure, as far as about 84 dated landslides support."""
        if x < 0.95:
            return f"{max(x, 0.1):.1f}×"
        return f"{x:.0f}×"

    def level_x(k: int) -> dict | None:
        """The measured figure for level k (1..5), or None if not shipped."""
        rows = (TU or {}).get("levels")
        return rows[k - 1] if rows else None

    def rain_x(t: float) -> dict | None:
        for b in (TU or {}).get("rain_bands", []):
            if b["from"] <= t < b["to"] or (b["to"] >= 1.0 and t >= b["from"]):
                return b
        return None

    def rng(b: dict) -> str:
        return f"{times(b['range_90'][0])} to {times(b['range_90'][1])}"

    N_DATED = (TU or {}).get("landslides", 0)

    def sus_level(su: float) -> int:
        """1..5, on the same cuts the susceptibility map is drawn with."""
        return int(np.digitize(su, SUS_CUTS)) + 1

    st.markdown(U.FS_CSS, unsafe_allow_html=True)

    # ═════════════════════ VIEW: FORECAST ════════════════════════════════════
    if view == "Forecast":
        if not LIVE:
            st.error("**Live rainfall is unavailable right now.** The free "
                     "weather service limits how often it can be queried. The "
                     "susceptibility map still works — open it from the sidebar. "
                     "Try again shortly.")
            st.stop()

        d0, d1 = (datetime.fromisoformat(days[fut[0]]), datetime.fromisoformat(days[fut[-1]]))
        sel = U.page_head(
            "Landslide forecast",
            "<span class='fs-dot' style='background:#35d07f'></span>"
            f"Live rain · {d0:%d %b} to {d1:%d %b}"
            + U._i("Worked out as the page opens: how weak each slope is, times how unusual "
                   f"the rain is at the nearest of {len(PTS['lat'])} rain points (Open-Meteo, "
                   "re-read every hour).", "down right"),
            "◭", search_row)
        U.key_row("sl_outlook", "sl_ground", "sl_input", "sl_record",
                  note=("× = times the usual number of landslides · not a chance" if TU
                        else "A level is a rank, not a chance"))

        di, n = current_day()
        sel_day = datetime.fromisoformat(days[di])
        WK = week_classes(RTAG)
        HI, VH, RKM = week_numbers(RTAG)
        cls, tri_pts = WK[n], trig[di]
        dtab = district_table(cls)
        w = where(sel)
        later = " · less sure this far ahead" if n >= LATER_FROM else ""

        # ── KPI strip: Arunachal as a whole, that day ────────────────────────
        n_wet = int((tri_pts >= 0.90).sum())
        kpis = [
            U._tile("Land at High or above", pc(HI[n]), f"of assessed land · {day_name(di)}",
                    "sl_outlook", T.CLASS_TEXT[3],
                    "Share of the land the model scores that is at High or Very High that "
                    "day. A share of land, not a chance.", "right"),
            U._tile("Very High", pc(VH[n]), f"of assessed land · {day_name(di)}", "sl_outlook",
                    T.CLASS_TEXT[4], "The top level alone."),
        ]
        if len(dtab):
            top_d = dtab.iloc[0]
            kpis.append(U._tile("Most affected district", f"{top_d['High+ %']:.1f}%",
                                f"{html.escape(top_d['District'])} · at High or above",
                                "sl_outlook", None,
                                "The district with the largest share of its own assessed land "
                                "at High or above that day."))
        if ROADS:
            kpis.append(U._tile("Road at High or above", f"{RKM[n]:,.0f}<small> km</small>",
                                f"main roads · {day_name(di)}", "sl_outlook", None,
                                "Kilometres of trunk, primary and secondary road crossing "
                                "ground at High or above. The Roads page shows where."))
        kpis += [
            U._tile("Unusually wet points", f"{n_wet}<small>/{len(tri_pts)}</small>",
                    f"rain points · {day_name(di)}", "sl_input", "#7fd4f0" if n_wet else None,
                    "Rain points whose 3- and 7-day rain sits in the wettest 10% of "
                    "everything that point has recorded since 2010.", "left"),
            U._tile("Wettest point", f"{np.nanmax(rain[di]):.0f}<small> mm</small>",
                    f"rain · {day_name(di)}", "sl_input", None,
                    "The most rain at any one rain point that day.", "left"),
        ]
        st.markdown(U._tiles(kpis, len(kpis)), unsafe_allow_html=True)

        centre, zoom, marker, clip = frame(sel, w)
        daynums = [datetime.fromisoformat(days[i]).day for i in fut]
        series = dcls = dweek = None            # the place's week, when it has one
        cl, cm, cr = U.main_row()

        # ── left: the place, the district, or the state ─────────────────────
        panel = U.Panel(sel)
        with cl, st.container(key="fs_col_l"):
            if w["kind"] == "none":
                U.state_title()
                panel.show(U.hero(
                    "High or above", pc(HI[n]), "of assessed land, statewide",
                    long_day(di) + later, T.CLASS_COLORS[3], T.CLASS_TEXT[3], "⛰",
                    "sl_outlook", bars_html=U.bars(
                        HI, daynums, [T.CLASS_COLORS[3]] * len(fut),
                        [f"{day_name(i)}: {pc(x)} of assessed land at High or above"
                         for i, x in zip(fut, HI)],
                        on=n, faded=range(LATER_FROM, len(fut)), floor=0.05)))
                mean_mm = np.nanmean(rain, axis=1)
                panel.show(
                    U._sec("Rain behind it", U.badge("sl_input", where="right"))
                    + U._tiles([
                        U._tile("Average rain", f"{mean_mm[di]:.0f}<small> mm</small>",
                                f"over {len(PTS['lat'])} points · {day_name(di)}", None, None,
                                "The plain average of that day's rain at the rain points.",
                                "right"),
                        U._tile("Typical rain vs normal",
                                f"{100 * float(np.nanmedian(tri_pts)):.0f}<small>/100</small>",
                                "50 is an ordinary monsoon day", None, None,
                                "The middle rain point's score: where its 3- and 7-day rain "
                                "sits among everything that point has recorded.", "left"),
                        U._tile("Last 3 days", f"{mean_mm[:fut[0]][-3:].sum():.0f}"
                                "<small> mm</small>", "past · state average", None, None,
                                where="right"),
                        U._tile("Next 3 days", f"{mean_mm[fut[0]:][:3].sum():.0f}"
                                "<small> mm</small>", "forecast · state average", None, None,
                                where="left")], 2, grow=True))
            elif w["kind"] == "district":
                U.place_title(sel, place_sub(sel))
                cnt = np.array([np.bincount(c_[w["mask"]], minlength=6) for c_ in WK])
                tot = np.maximum(cnt[:, 1:].sum(axis=1), 1)
                dweek = {"hi": (cnt[:, 4] + cnt[:, 5]) / tot, "vh": cnt[:, 5] / tot}
                panel.show(U.hero(
                    "High or above", pc(dweek["hi"][n]),
                    f"of {html.escape(w['name'])}'s assessed land", long_day(di) + later,
                    T.CLASS_COLORS[3], T.CLASS_TEXT[3], "⛰", "sl_outlook",
                    bars_html=U.bars(
                        list(dweek["hi"]), daynums, [T.CLASS_COLORS[3]] * len(fut),
                        [f"{day_name(i)}: {pc(x)} at High or above"
                         for i, x in zip(fut, dweek["hi"])],
                        on=n, faded=range(LATER_FROM, len(fut)), floor=0.05)))
                # the rain points that sit inside the district; a district too
                # small to hold one reads the point nearest its centre
                pr, pcol, pok = grid.to_px_array(np.asarray(PTS["lat"]), np.asarray(PTS["lon"]))
                inside = np.zeros(len(pok), bool)
                inside[pok] = w["mask"][pr[pok], pcol[pok]]
                pj = np.nonzero(inside)[0]
                if not len(pj):
                    px = latlon_to_px(sel["lat"], sel["lon"])
                    pj = np.array([int(NEAR[px])]) if px is not None else np.arange(len(pok))
                dweek["rain"] = rain[:, pj].mean(axis=1)
                dweek["trig"] = trig[:, pj].mean(axis=1)
                pts_note = (f"average of {len(pj)} rain points" if len(pj) > 1
                            else "nearest rain point")
                peak = int(np.nonzero(cnt[n, 1:])[0].max()) if cnt[n, 1:].any() else 0
                panel.show(U._tiles([
                    U._tile("Very High", pc(dweek["vh"][n]), "of its assessed land",
                            "sl_outlook", T.CLASS_TEXT[4], where="right"),
                    U._tile("Highest level", T.CLASS_NAMES[peak], "anywhere in the district",
                            "sl_outlook", T.CLASS_TEXT[peak], where="left"),
                    U._tile("Rain that day", f"{dweek['rain'][di]:.0f}<small> mm</small>",
                            pts_note, "sl_input", None, where="right"),
                    U._tile("Rain vs normal", f"{100 * float(dweek['trig'][di]):.0f}<small>/100</small>",
                            pts_note, "sl_input", None,
                            "Where the 3- and 7-day rain sits among everything those rain "
                            "points have recorded. 90 is wetter than about 90% of their days.",
                            "left")], 2, grow=True))
            else:
                U.place_title(sel, place_sub(sel))
                if w["kind"] == "outside":
                    panel.show(EMPTY_OUTSIDE)
                elif w["kind"] == "unassessed":
                    panel.show(EMPTY_UNASSESSED)
                else:
                    su, j = w["su"], w["j"]
                    series = np.array([su * trig[i][j] for i in fut], dtype=np.float32)
                    dcls = fc.classify(series)
                    k = int(dcls[n])
                    lx = level_x(k)
                    where_ = "here" if w["dcells"] <= 0 else "on the nearest slope"
                    panel.show(U.hero(
                        T.CLASS_NAMES[k - 1],
                        (times(lx["times_usual"]) + "<small style='font-size:1.05rem;"
                         "margin-left:8px;letter-spacing:0'>the usual</small>") if lx
                        else T.CLASS_NAMES[k - 1],
                        f"landslide outlook {where_}",
                        long_day(di) + later, T.CLASS_COLORS[k - 1], T.CLASS_TEXT[k - 1], "⛰",
                        "sl_outlook",
                        (f"Places and days at {T.CLASS_NAMES[k - 1]} have had about "
                         f"{times(lx['times_usual'])} the landslides of an average place on an "
                         f"average day (likely {rng(lx)}). Measured on {N_DATED} landslides with "
                         "a known date, so it is a rough figure.") if lx else "",
                        bars_html=U.bars(
                            [float(x) for x in series], daynums,
                            [T.CLASS_COLORS[int(x) - 1] for x in dcls],
                            [f"{day_name(i)}: {T.CLASS_NAMES[int(x) - 1]}"
                             + (f" · about {times(level_x(int(x))['times_usual'])} the usual"
                                if level_x(int(x)) else "")
                             for i, x in zip(fut, dcls)],
                            on=n, faded=range(LATER_FROM, len(fut)), floor=TOP_CUT)))
                    sk = sus_level(su)
                    sr_ = MET["susceptibility"].get("success_rate", [])
                    gx = sr_[sk - 1]["lift"] if len(sr_) == 5 else None
                    rx = rain_x(float(tri_pts[j]))
                    panel.show(U._tiles([
                        U._tile("This ground", times(gx) if gx is not None else f"{su:.2f}",
                                "the landslides of average ground · every day" if gx is not None
                                else f"{T.CLASS_NAMES[sk - 1]} · the same every day", "sl_ground",
                                T.CLASS_TEXT[sk - 1],
                                (f"Slopes ranked like this one ({T.CLASS_NAMES[sk - 1]}, score "
                                 f"{su:.2f} of 1) have had about {times(gx)} the mapped landslides "
                                 "of average ground. Measured on ground the model never saw. "
                                 if gx is not None else "") +
                                "From terrain, soil, rock and land cover — no rainfall at all.",
                                "right"),
                        U._tile("Rain today" if n == 0 else "Rain that day",
                                times(rx["times_usual"]) if rx
                                else f"{100 * float(tri_pts[j]):.0f}<small>/100</small>",
                                "landslides against a usual day here" if rx
                                else "3- and 7-day rain, for this spot", "sl_input", None,
                                (f"With rain this unusual, landslides have been about "
                                 f"{times(rx['times_usual'])} as common as on a usual day at the "
                                 f"same place (likely {rng(rx)}; {rx['landslides']} of {N_DATED} "
                                 "dated landslides fell on such days). " if rx else "") +
                                f"Rain score {100 * float(tri_pts[j]):.0f} of 100: where the last 3 "
                                "and 7 days' rain sits among everything this spot has recorded.",
                                "left"),
                        U._tile("Rain that day", f"{rain[di, j]:.0f}<small> mm</small>",
                                day_name(di), "sl_input", None, where="right"),
                        U._tile("Rain, 7 days", f"{rain[max(di - 6, 0):di + 1, j].sum():.0f}"
                                "<small> mm</small>", "the week ending that day", "sl_input",
                                None, where="left")], 2, grow=True) + snap_foot(w))

        # ── centre: the map ──────────────────────────────────────────────────
        shown = GR.clip_to(cls, clip)
        # Shares are of whatever is on screen: the district when one is
        # clipped, the state otherwise. Quoting statewide shares under a
        # district's name would be a different number to the map.
        assessed = shown > 0
        shares = [float((shown[assessed] == i).mean()) if assessed.any() else 0
                  for i in range(1, 6)]
        map_name = f"Landslide outlook · {day_name(di)}"
        with cm, st.container(key="fs_col_m"):
            with st.container(border=True, key="fs_mapcard"):
                U.map_title(map_name,
                            U.badge("sl_outlook", "Colour: the level of each ~550 m square "
                                    "that day.", "down"),
                            right=dim_toggle("sl_dim"), ratio=(4, 2))
                dim = "2D"
                img = None if s.bare else M.rgba_overlay(shown, T.CLASS_COLORS)
                # Height-locked shell: a redraw must not collapse the card and
                # bounce the panels below it up for a frame.
                shell_box = st.container(height=MAP_H + 8, border=False, key="map_shell")
                if dim == "3D":
                    # Zoomed in on one place we can afford every cell; statewide
                    # we cannot. Measured: stride 1 statewide is 288,000 points
                    # and a 6.1 MB payload rebuilt on every redraw, for detail no
                    # camera at that height can resolve. Stride 3 is 32,000 and
                    # 0.7 MB.
                    stride = 1 if sel else 3
                    sub = clip
                    if sub is None and sel:
                        # No polygon to clip to (a town or a coordinate), so the
                        # window is purely a payload limit — say so in the caption
                        # below rather than dressing it up as a boundary.
                        sub = np.zeros((H, W), bool)
                        px = latlon_to_px(sel["lat"], sel["lon"])
                        if px is not None:
                            rad = 90                      # ~45 km of context
                            r0, r1 = max(px[0] - rad, 0), min(px[0] + rad, H)
                            c0, c1 = max(px[1] - rad, 0), min(px[1] + rad, W)
                            sub[r0:r1, c0:c1] = True
                        else:
                            sub = None
                    pb, cb, npt, cell_m = (
                        ("", "", 0, 700.0) if s.bare else forecast_cells(
                            shown, stride=stride, mask=sub,
                            # The sidebar slider governs 3D too — it used to be
                            # silently ignored the moment you switched from 2D.
                            alpha=255 * s.opacity))
                    with shell_box:
                        components.html(D3.html(
                            basemap=s.basemap, bounds=[WEST, SOUTH, EAST, NORTH],
                            centre=centre or ((SOUTH + NORTH) / 2, (WEST + EAST) / 2),
                            zoom=(zoom - 1.5) if sel else 6.4,
                            pos_b64=pb, col_b64=cb, n_points=npt,
                            cell_m=cell_m,
                            marker=({"pos": [sel["lon"], sel["lat"]],
                                     "tip": sel["label"]} if sel else None),
                        ), height=MAP_H)
                    if clip is not None:
                        st.caption(f"Clipped to {sel['label']} — the real "
                                   f"boundary, not a box around it.")
                    elif sel:
                        st.caption("3D draws a ~45 km window around the selected "
                                   "point to keep the page light. That window is "
                                   "a performance limit, not a boundary — pick a "
                                   "district to clip to a real one.")
                    if not sel:
                        st.caption(f"Statewide 3D is thinned to ~{cell_m:,.0f} m "
                                   f"blocks so the page stays light. Search a "
                                   f"place — or click one on the 2D map — for the "
                                   f"full {DLAT * 111_000:.0f} m detail the 2D "
                                   f"map shows.")
                else:
                    m = base_map()

                    def _more(fg):
                        # on the full-screen map the page around it cannot be
                        # seen: the place box and the colour key ride on the map
                        U.fullscreen_panel(map_name, panel.body(colour_key(
                            "sl_outlook", T.CLASS_NAMES, T.CLASS_COLORS, shares))).add_to(fg)

                    fg = overlay_group(img, districts=s.districts, marker=marker, more=_more,
                                       focus=w.get("feat"))
                    fly_c, fly_z = M.fly_to(sel, zoom, centre)
                    with shell_box:
                        # ⚠️ Stable key. Keying on the day or the place would
                        # rebuild the component on every change, which is
                        # exactly the reset we are avoiding — what changes
                        # travels in the feature group instead.
                        out = st_folium(m, height=MAP_H, use_container_width=True,
                                        pixelated=True,
                                        returned_objects=["last_clicked"],
                                        feature_group_to_add=fg,
                                        center=fly_c, zoom=fly_z, key="fmap")
                    # A click IS a selection: it moves the pin, redraws the day
                    # buttons and repoints the panel.
                    U.take_click(out)
                if s.bare:
                    M.legend_strip([], [], bare=True)
                else:
                    st.markdown(U.legend(
                        T.CLASS_NAMES, T.CLASS_COLORS, shares,
                        subs=([times(r_["times_usual"]) for r_ in TU["levels"]]
                              if (TU or {}).get("levels") else None),
                        tip=(("The × beside each level: how many times the landslides of an "
                              "average place and day, measured on dated landslides. "
                              if (TU or {}).get("levels") else "") +
                             "Each ~550 m square's level that day. The share is of "
                             + (f"{w['name']}'s" if clip is not None else "the state's")
                             + " assessed land. Blank: ice, open water or ground flatter than "
                             "10°, which the model does not score. The fine texture is terrain "
                             f"(100 m); rain is read at {len(PTS['lat'])} points about 22 km "
                             "apart."),
                        syms=((U.sym("line", "main road", T.ROAD_INK[s.basemap])
                               if s.roads else "")
                              + (U.sym("box", "selected district", T.ACCENT)
                                 if clip is not None else ""))), unsafe_allow_html=True)

        # ── right: the day picker, districts to watch, roads ────────────────
        with cr, st.container(key="fs_col_r"):
            if series is not None:
                notes = [times(level_x(int(x))["times_usual"]) if level_x(int(x))
                         else LEVEL_SHORT[int(x) - 1] for x in dcls]
                cols_ = [T.CLASS_COLORS[int(x) - 1] for x in dcls]
                tips = [T.CLASS_NAMES[int(x) - 1] for x in dcls]
                scope = "times the usual, at this place" if TU else "level at this place"
            elif dweek is not None:
                notes, cols_, tips = [pc(x) for x in dweek["hi"]], [T.CLASS_COLORS[3]] * len(fut), None
                scope = "share of the district at High+"
            else:
                # ⚠️ The buttons must ALWAYS say which of these they show. They
                # used to fall back to the statewide share in silence, with
                # nothing on screen naming a place.
                notes, cols_, tips = [pc(x) for x in HI], [T.CLASS_COLORS[3]] * len(fut), None
                scope = "share of the state at High+"
            with st.container(key="fs_r_a"):
                day_buttons(notes, cols_, U._sec("7 days", U.badge("sl_outlook", where="left"),
                                                 note=scope), tips)
            with st.container(key="fs_r_b"):
                st.markdown(U._sec("Districts to watch", U.badge("sl_outlook", where="left"),
                                   note=day_name(di)), unsafe_allow_html=True)
                district_picks(dtab, WATCH_N)
                st.markdown("<div class='fs-foot'>Share of each district at High or above "
                            + U._i("Of the land the model scores inside each district's own "
                                   "outline. Click one to open it.", "left") + "</div>",
                            unsafe_allow_html=True)
            with st.container(key="fs_r_c"):
                st.markdown(U._sec("Roads", U.badge("sl_outlook", where="left"))
                            + "<div class='fs-foot' style='margin:0 0 8px'>"
                            + (f"{RKM[n]:,.0f} km of main road cross ground at High or above "
                               f"{'today' if day_name(di) == 'Today' else 'that day'}."
                               if ROADS else "Which stretches, and how many kilometres.")
                            + "</div>", unsafe_allow_html=True)
                to_view("Roads", "🛣️  Open road exposure", "sl_to_roads")

        # ── the place's week, in full ────────────────────────────────────────
        day_lbl = [datetime.fromisoformat(days[i]).strftime("%a %d %b") for i in fut]
        if series is not None or dweek is not None:
            st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
            c1, c2 = st.columns([1.6, 1], gap="medium")
            if series is not None:
                j, worst = w["j"], int(np.argmax(series))
                with c1, st.container(border=True, key="fs_eq_1"):
                    st.markdown(U._sec("Next 7 days here", U.badge("sl_outlook", where="right"),
                                       note="susceptibility × rain vs normal"),
                                unsafe_allow_html=True)
                    st.bar_chart(pd.DataFrame({
                        "day": [datetime.fromisoformat(days[i]).strftime("%a %d")
                                for i in fut],
                        "hazard": series}).set_index("day"),
                        height=210, color=T.ACCENT,
                        sort=False)    # date order: A-Z put Fri before Mon
                    st.markdown(
                        "<div class='fs-foot'>Worst day in this window: "
                        f"<b>{day_lbl[worst]}</b> — {T.CLASS_NAMES[int(dcls[worst]) - 1]}, "
                        f"score {series[worst]:.3f}</div>", unsafe_allow_html=True)
                with c2, st.container(border=True, key="fs_eq_2"):
                    st.markdown(U._sec("Day by day", U.badge("sl_input", where="left")),
                                unsafe_allow_html=True)
                    st.dataframe(pd.DataFrame({
                        "Day": day_lbl,
                        "Rain": [f"{rain[i, j]:.0f} mm" for i in fut],
                        "Trigger": [f"{trig[i][j]:.2f}" for i in fut],
                        "Outlook": [T.CLASS_NAMES[int(x) - 1] for x in dcls]}),
                        width="stretch", hide_index=True, height=280)
            else:
                with c1, st.container(border=True, key="fs_eq_1"):
                    st.markdown(U._sec(f"Next 7 days in {html.escape(w['name'])}",
                                       U.badge("sl_outlook", where="right"),
                                       note="% of its assessed land at High or above"),
                                unsafe_allow_html=True)
                    st.bar_chart(pd.DataFrame({
                        "day": [datetime.fromisoformat(days[i]).strftime("%a %d")
                                for i in fut],
                        "High or above, %": 100 * dweek["hi"]}).set_index("day"),
                        height=210, color=T.CLASS_COLORS[3], sort=False)
                with c2, st.container(border=True, key="fs_eq_2"):
                    st.markdown(U._sec("Day by day", U.badge("sl_input", where="left")),
                                unsafe_allow_html=True)
                    st.dataframe(pd.DataFrame({
                        "Day": day_lbl,
                        "High or above": [pc(x) for x in dweek["hi"]],
                        "Very High": [pc(x) for x in dweek["vh"]],
                        "Rain": [f"{dweek['rain'][i]:.0f} mm" for i in fut]}),
                        width="stretch", hide_index=True, height=280)

        from products.report import report_button
        report_button(shell, sel, "sl_report")

        # ── folded away: every district, how to read ─────────────────────────
        # The district table and its CSV are the one export an operations
        # office actually asked for.
        with st.expander(f"📋  All districts — table · {sel_day.strftime('%d %b')}"):
            st.dataframe(dtab, width="stretch", hide_index=True, height=340,
                         column_config={"High+ %": st.column_config.ProgressColumn(
                             "High+ %", min_value=0, max_value=100, format="%.1f%%")})
            st.download_button("⬇️  District outlook (CSV)",
                               dtab.to_csv(index=False).encode(),
                               f"slidesense_{days[di]}.csv", "text/csv")
            st.caption("Each district's figures are for the land the model scores inside "
                       "its own outline.")

        with st.expander("📖  How to read these levels"):
            su_m, tr_m = MET["susceptibility"], MET["trigger"]
            st.markdown(
                "**Outlook ≈ — the level.** Two things multiplied: how weak the slope is "
                "(*susceptibility*, the same every day) and how unusual the rain is for that "
                "exact place (*rain vs normal*). Both are needed: a cliff in dry weather does "
                "not fail, and a downpour on flat, stable ground does nothing. The result is "
                "cut into five levels, Very Low to Very High.\n\n"
                "**A level is a rank, not a chance.** “High” means “look here first”. It "
                "does not say how likely a landslide is, and the share of land at High is a "
                "share of land, not a probability.\n\n"
                f"**Ground ◆ — susceptibility.** Learned from {MET['labels']['polygons']:,} "
                "mapped landslides and tested on whole regions hidden during training: it "
                f"ranked a landslide spot above a stable one about {100 * su_m['auc']:.0f} "
                "times in 100.\n\n"
                f"**Input ☂ — rain vs normal.** Each rain point's last 3 and 7 days of rain, "
                "scored against everything that point has recorded since 2010: 90 means "
                f"wetter than about 90% of its days. Only {tr_m['n_events']} landslides in "
                "Arunachal have a known date, so this half is a plain rule, not a trained "
                f"model; on those dated slides it was right about {100 * tr_m['auc']:.0f} "
                "times in 100.\n\n"
                "**What it does not cover.** Ice, open water and ground flatter than 10° are "
                "not scored — a town on a valley floor is shown the nearest slope, with the "
                f"distance. Rain is read at {len(PTS['lat'])} points about 22 km apart, so the "
                "map's fine texture is terrain, not weather. Days 5–7 rest on rain forecasts "
                "that are weaker that far ahead, which is why they are dashed. Not for "
                "operational safety decisions.")

    # ═════════════════════ VIEW: ROADS ═══════════════════════════════════════
    elif view == "Roads":
        if not LIVE:
            st.error("**Live rainfall is unavailable right now.** Try again shortly.")
            st.stop()
        if not ROADS:
            st.warning("No road layer in the bundle.")
            st.stop()

        chunks, c_lat, c_lon, c_km, c_rid, c_hw = road_chunks()

        # ---- pick a route (optional) --------------------------------------- #
        # Empty by default on purpose: the whole-network view is the one that
        # answers "where do I look today", and it should not need two choices
        # before it shows anything.
        NONE = "—"
        labels = [NONE] + [p["label"] for p in PLACES]

        def clear_route():
            # ⚠️ In a callback, which runs BEFORE the next rerun builds the two
            # boxes. Writing these keys after the boxes exist — as the button's
            # own `if` used to — is refused by Streamlit outright.
            st.session_state.rd_from = NONE
            st.session_state.rd_to = NONE

        def route_row():
            r1, r2, r3 = st.columns([1, 1, 0.5], vertical_alignment="bottom")
            with r1:
                st.selectbox("From", labels, key="rd_from",
                             help="Leave both empty for the whole network.")
            with r2:
                st.selectbox("To", labels, key="rd_to")
            with r3:
                st.button("Clear route", width="stretch", on_click=clear_route)
            return None

        U.page_head("Road exposure", "Main roads, by the outlook on the ground they cross",
                    "🛣️", route_row, warn=False)
        U.key_row("sl_outlook", note="The ground a road crosses, not the slope above it")
        p_from = LOOKUP.get(st.session_state.get("rd_from", NONE))
        p_to = LOOKUP.get(st.session_state.get("rd_to", NONE))

        di, n = current_day()
        sel_day = datetime.fromisoformat(days[di])
        WK = week_classes(RTAG)
        HI, VH, RKM = week_numbers(RTAG)
        cls = WK[n]
        c_cls = sample_classes(cls, c_lat, c_lon)
        later = " · less sure this far ahead" if n >= LATER_FROM else ""

        route, route_km, snap_a, snap_b = (None, 0.0, 0.0, 0.0)
        if p_from and p_to:
            route, route_km, snap_a, snap_b = route_between(
                p_from["lat"], p_from["lon"], p_to["lat"], p_to["lon"])
            if route is None:
                st.warning(
                    f"**No mapped road connects {p_from['label']} to "
                    f"{p_to['label']}.** The road layer is clipped to Arunachal, "
                    "so any route that legitimately runs through Assam is cut — "
                    "the Tirap and Changlang lobe hangs off one of those. Showing "
                    "the whole network instead.")

        km_by_class = RD.exposure(c_cls, c_km)
        total_km = float(c_km.sum())
        assessed_km = float(sum(km_by_class))
        high_km = km_by_class[3] + km_by_class[4]
        spots = RD.hotspots(c_cls, c_rid, c_km, c_lat, c_lon)

        if route:
            # ---- ONE ROUTE ------------------------------------------------- #
            r_gj, r_lo, r_la, r_at, r_cls = route_geojson(route, cls)
            step = r_at[1] - r_at[0] if len(r_at) > 1 else 0.6
            r_km_by_class = [float((r_cls == cc).sum() * step) for cc in range(1, 6)]
            r_high = r_km_by_class[3] + r_km_by_class[4]
            r_assessed = float(sum(r_km_by_class))
            worst_i = int(np.argmax(r_cls))
            wk_ = int(r_cls[worst_i])
            kpis = [
                U._tile("Route length", f"{route_km:,.0f}<small> km</small>",
                        "by mapped road", None, None,
                        "The shortest path over the mapped network — not a navigation "
                        "instruction.", "right"),
                U._tile("At High or above", f"{r_high:,.0f}<small> km</small>",
                        (f"{100 * r_high / r_assessed:.0f}% of the route" if r_assessed
                         else "—") + f" · {day_name(di)}", "sl_outlook", T.CLASS_TEXT[3]),
                U._tile("Very High", f"{r_km_by_class[4]:,.0f}<small> km</small>",
                        f"of the route · {day_name(di)}", "sl_outlook", T.CLASS_TEXT[4]),
                U._tile("Worst point", T.CLASS_NAMES[wk_ - 1] if wk_ else "—",
                        f"at km {r_at[worst_i]:.0f}", "sl_outlook",
                        T.CLASS_TEXT[wk_ - 1] if wk_ else None, where="left"),
                U._tile("Network at High or above", f"{high_km:,.0f}<small> km</small>",
                        f"all main roads · {day_name(di)}", "sl_outlook", None, where="left"),
            ]
        else:
            jw = int(np.argmax(RKM))
            kpis = [
                U._tile("Road at High or above", f"{high_km:,.0f}<small> km</small>",
                        (f"{100 * high_km / assessed_km:.0f}% of assessed network"
                         if assessed_km else "—") + f" · {day_name(di)}", "sl_outlook",
                        T.CLASS_TEXT[3],
                        "Kilometres of road crossing ground at High or Very High that day.",
                        "right"),
                U._tile("Very High", f"{km_by_class[4]:,.0f}<small> km</small>",
                        f"of road · {day_name(di)}", "sl_outlook", T.CLASS_TEXT[4]),
                U._tile("Hotspot stretches", f"{len(spots):,}", "runs of road at High or above",
                        "sl_outlook", None,
                        "Continuous runs of road at High or above. This is the unit you "
                        "would send a crew to."),
                U._tile("Longest stretch", f"{spots[0]['km']:.1f}<small> km</small>"
                        if spots else "—", "the top-ranked stretch", "sl_outlook", None),
                U._tile("Worst day this week", f"{RKM[jw]:,.0f}<small> km</small>",
                        f"at High or above · {day_name(fut[jw])}", "sl_outlook", None,
                        where="left"),
                U._tile("Road assessed", f"{assessed_km:,.0f}<small> km</small>",
                        f"of {total_km:,.0f} km mapped", None, None,
                        "Trunk, primary and secondary road from OpenStreetMap. The rest "
                        "crosses ground the model does not score.", "left"),
            ]
        st.markdown(U._tiles(kpis, len(kpis)), unsafe_allow_html=True)

        ahead = (sel_day.date() - date.today()).days
        daynums = [datetime.fromisoformat(days[i]).day for i in fut]
        map_name = f"Roads by outlook · {day_name(di)}"
        cl, cm, cr = U.main_row()

        # ── left: the route, or the network's worst stretches ───────────────
        if route:
            panel = U.Panel(None, f"{U._clean(p_from['label'])} → {U._clean(p_to['label'])}",
                            f"{route_km:,.0f} km by mapped road")
        else:
            panel = U.Panel(None, "Whole network", "leave full screen to pick a route")
        with cl, st.container(key="fs_col_l"):
            if route:
                st.markdown(
                    f"<div class='fs-place'>{html.escape(U._clean(p_from['label']))} → "
                    f"{html.escape(U._clean(p_to['label']))}"
                    f"<small>{route_km:,.0f} km by mapped road</small></div>",
                    unsafe_allow_html=True)
                panel.show(U.hero(
                    "High or above", f"{r_high:,.0f}<small style='font-size:1.1rem;margin-left:7px'>km</small>",
                    (f"{100 * r_high / r_assessed:.0f}% of the route" if r_assessed else
                     "of the route"), long_day(di) + later, T.CLASS_COLORS[3],
                    T.CLASS_TEXT[3], "🛣️", "sl_outlook"))
                rmx = max(r_km_by_class) or 1.0
                panel.show(
                    U._sec("Route by level", U.badge("sl_outlook", where="right"), note="km")
                    + "<div class='fs-grow'>" + U.hbars(
                        [(T.CLASS_NAMES[i], r_km_by_class[i], f"{r_km_by_class[i]:,.0f}",
                          T.CLASS_COLORS[i],
                          f"{r_km_by_class[i]:,.1f} km of the route is at {T.CLASS_NAMES[i]}.")
                         for i in range(4, -1, -1)], rmx) + "</div>"
                    + (f"<div class='fs-foot'>Starts {snap_a:.1f} km from "
                       f"{html.escape(U._clean(p_from['label']))}, ends {snap_b:.1f} km from "
                       f"{html.escape(U._clean(p_to['label']))}: the nearest mapped road.</div>"
                       if max(snap_a, snap_b) > 3 else ""))
            else:
                st.markdown("<div class='fs-place'>Whole network<small>pick From and To for "
                            "one route</small></div>", unsafe_allow_html=True)
                panel.show(U.hero(
                    "High or above", f"{high_km:,.0f}<small style='font-size:1.1rem;margin-left:7px'>km"
                    "</small>", "of main road, statewide", long_day(di) + later,
                    T.CLASS_COLORS[3], T.CLASS_TEXT[3], "🛣️", "sl_outlook",
                    bars_html=U.bars(
                        RKM, daynums, [T.CLASS_COLORS[3]] * len(fut),
                        [f"{day_name(i)}: {x:,.0f} km at High or above"
                         for i, x in zip(fut, RKM)],
                        on=n, faded=range(LATER_FROM, len(fut)), floor=50.0)))
                rows_ = ""
                for h in spots[:5]:
                    near, dkm = G.nearest_place(h["lat"], h["lon"], PLACES)
                    rows_ += U._row(
                        "▲", T.CLASS_TEXT[h["peak"] - 1],
                        (f"near {html.escape(U._clean(near['label']))}" if near else "—"),
                        f"<b>{h['km']:.1f} km</b> · {T.CLASS_NAMES[h['peak'] - 1]}")
                panel.show(
                    U._sec("Worst stretches", U.badge("sl_outlook", where="right"),
                           note=day_name(di))
                    + (f"<div class='fs-rows fs-grow'>{rows_}</div>" if rows_ else
                       "<div class='fs-empty fs-grow'>No stretch of road reaches High on "
                       f"{sel_day.strftime('%d %b')}.</div>"))

        # ── centre: the map ──────────────────────────────────────────────────
        if route:
            shares = [x / r_assessed if r_assessed else 0 for x in r_km_by_class]
        else:
            shares = [x / assessed_km if assessed_km else 0 for x in km_by_class]
        with cm, st.container(key="fs_col_m"):
            with st.container(border=True, key="fs_mapcard"):
                U.map_title(map_name,
                            U.badge("sl_outlook", "Each ~1 km of road is coloured by the "
                                    "level of the ground it crosses.", "down"),
                            right=dim_toggle("rd_dim"), ratio=(4, 2))
                # Parked alongside the Forecast page's toggle — see WIP_3D.
                rdim = "2D"

                # Where the 3D camera opens. On a chosen route, its worst point; on
                # the whole network, today's worst stretch — in both cases the place
                # somebody actually has to make a decision about.
                if route:
                    focus, zoom3d = (float(r_la[worst_i]), float(r_lo[worst_i])), 9.6
                elif spots:
                    focus, zoom3d = (spots[0]["lat"], spots[0]["lon"]), 10.2
                else:
                    focus, zoom3d = ((SOUTH + NORTH) / 2, (WEST + EAST) / 2), 8.0
                shell_box = st.container(height=MAP_H + 8, border=False, key="map_shell")
                if rdim == "3D":
                    # A chosen route gets a tight corridor around ITSELF; the network
                    # view gets the corridor around every road.
                    corr = (route_corridor_mask(tuple(np.round(r_lo, 4)),
                                                tuple(np.round(r_la, 4)),
                                                ROUTE_CORRIDOR_KM) if route
                            else road_corridor_mask(CORRIDOR_KM))
                    pb, cb, npt, cell_m = forecast_cells(cls, stride=1, mask=corr,
                                                         alpha=255 * s.opacity)
                    with shell_box:
                        components.html(D3.html(
                            basemap=s.basemap, bounds=[WEST, SOUTH, EAST, NORTH],
                            centre=focus, zoom=10.2, pitch=60,
                            pos_b64=pb, col_b64=cb, n_points=npt,
                            cell_m=cell_m,
                            paths=(route_paths_3d(r_lo, r_la, r_cls) if route
                                   else road_paths_3d(chunks, c_cls)),
                            marker={"pos": [focus[1], focus[0]],
                                    "tip": ("Worst point on the route" if route
                                            else "Worst stretch today")},
                            pin_height=2500,
                        ), height=MAP_H)
                    band = ROUTE_CORRIDOR_KM if route else CORRIDOR_KM
                    st.caption(f"Forecast shown only within {band:.0f} km of the "
                               f"{'route' if route else 'road network'} — the ground "
                               f"that can actually reach it. Opens on the worst point; "
                               f"drag to fly along it.")
                    legend_strip(T.CLASS_NAMES, T.CLASS_COLORS, None,
                                 note="Relief exaggerated 1.25x so mid-altitude "
                                      "ridges read")
                else:
                    m = base_map()

                    def _more(fg):
                        if route:
                            # The rest of the network stays but faint: a route drawn
                            # with no context around it could be anywhere in the state.
                            folium.GeoJson(road_geojson(chunks, c_cls, c_km),
                                           style_function=lambda f: {
                                               "color": "#5b6b7d", "weight": 1.0,
                                               "opacity": 0.32}).add_to(fg)
                            folium.GeoJson(r_gj, name="Route casing",
                                           style_function=lambda f: {
                                               "color": "#05070a", "weight": 7,
                                               "opacity": 0.85}).add_to(fg)
                            folium.GeoJson(
                                r_gj, name="Route by forecast",
                                style_function=lambda f: {
                                    "color": T.CLASS_COLORS[f["properties"]["c"] - 1]
                                             if f["properties"]["c"] else T.NOT_ASSESSED,
                                    "weight": 4.5, "opacity": 1.0},
                                tooltip=folium.GeoJsonTooltip(["cls", "km"],
                                                              aliases=["Outlook:", "At km:"])
                            ).add_to(fg)
                            for pt, lbl in ((p_from, "From"), (p_to, "To")):
                                folium.Marker([pt["lat"], pt["lon"]],
                                              tooltip=f"{lbl}: {pt['label']}",
                                              icon=folium.Icon(color="lightblue",
                                                               icon="location-dot",
                                                               prefix="fa")).add_to(fg)
                        else:
                            folium.GeoJson(
                                road_geojson(chunks, c_cls, c_km),
                                name="Roads by forecast",
                                style_function=lambda f: {
                                    "color": T.CLASS_COLORS[f["properties"]["c"] - 1]
                                             if f["properties"]["c"] else T.NOT_ASSESSED,
                                    "weight": 3.5 if f["properties"]["c"] >= 4 else 2.0,
                                    "opacity": 0.95},
                                tooltip=folium.GeoJsonTooltip(["cls", "km"],
                                                              aliases=["Outlook:",
                                                                       "Length (km):"])
                            ).add_to(fg)
                        U.fullscreen_panel(map_name, panel.body(colour_key(
                            "sl_outlook", T.CLASS_NAMES, T.CLASS_COLORS, shares))).add_to(fg)

                    # Roads ride in their OWN feature group, drawn without the hazard
                    # raster: painting both would put a red road on red ground and
                    # lose the very thing this view exists to show.
                    fg = overlay_group(None, districts=s.districts, inventory=False,
                                       more=_more)
                    if route:
                        fly_c = ((min(r_la) + max(r_la)) / 2, (min(r_lo) + max(r_lo)) / 2)
                        span = max(max(r_la) - min(r_la), max(r_lo) - min(r_lo), 0.05)
                        fly_z = float(np.clip(np.log2(360.0 / span) - 1.4, 6, 12))
                    else:
                        fly_c, fly_z = None, None
                    with shell_box:
                        st_folium(m, height=MAP_H, use_container_width=True,
                                  pixelated=True, returned_objects=[],
                                  feature_group_to_add=fg,
                                  center=fly_c, zoom=fly_z, key="rdmap")
                    if s.bare:
                        M.legend_strip([], [], bare=True)
                    else:
                        st.markdown(U.legend(
                            T.CLASS_NAMES, T.CLASS_COLORS, shares,
                            tip=(f"Share of the {route_km:,.0f} km route at each level."
                                 if route else
                                 f"Share of the {assessed_km:,.0f} km of road the model "
                                 f"scores, of {total_km:,.0f} km mapped.")
                                + " Exposure is the outlook on the ground a road crosses, "
                                  "not the slope above it.",
                            syms=U.sym("line", "not assessed", T.NOT_ASSESSED)),
                            unsafe_allow_html=True)

        # ── right: the day picker, road by level, the forecast ──────────────
        with cr, st.container(key="fs_col_r"):
            with st.container(key="fs_r_a"):
                day_buttons([f"{k:,.0f} km" for k in RKM], [T.CLASS_COLORS[3]] * len(fut),
                            U._sec("7 days", U.badge("sl_outlook", where="left"),
                                   note="network km at High+"))
            with st.container(key="fs_r_b"):
                kmx = max(km_by_class) or 1.0
                st.markdown(
                    U._sec("Network by level", U.badge("sl_outlook", where="left"), note="km")
                    + "<div class='fs-grow'>" + U.hbars(
                        [(T.CLASS_NAMES[i], km_by_class[i], f"{km_by_class[i]:,.0f}",
                          T.CLASS_COLORS[i],
                          f"{km_by_class[i]:,.0f} km of main road crosses ground at "
                          f"{T.CLASS_NAMES[i]} on {sel_day.strftime('%d %b')}.")
                         for i in range(4, -1, -1)], kmx) + "</div>"
                    + "<div class='fs-foot'>"
                    + ("Today" if ahead == 0 else f"{ahead} day{'s' if ahead != 1 else ''} ahead")
                    + f" · {assessed_km:,.0f} km assessed</div>", unsafe_allow_html=True)
            with st.container(key="fs_r_c"):
                st.markdown(U._sec("The ground itself", U.badge("sl_outlook", where="left"))
                            + "<div class='fs-foot' style='margin:0 0 8px'>"
                            f"{pc(HI[n])} of assessed land is at High or above "
                            f"{'today' if ahead == 0 else 'that day'}.</div>",
                            unsafe_allow_html=True)
                to_view("Forecast", "📍  Open the landslide forecast", "sl_to_forecast")

        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
        if route:
            prof = pd.DataFrame({
                "km": np.round(r_at, 2),
                "Elevation (m)": route_elevation(r_lo, r_la),
                "Outlook (1-5)": [int(cc) if cc else np.nan for cc in r_cls],
            }).set_index("km")
            pc1, pc2 = st.columns(2, gap="medium")
            with pc1, st.container(border=True, key="fs_eq_1"):
                st.markdown(U._sec("Elevation along the route", note="metres"),
                            unsafe_allow_html=True)
                st.line_chart(prof[["Elevation (m)"]], height=200, color=T.ACCENT_2)
            with pc2, st.container(border=True, key="fs_eq_2"):
                st.markdown(U._sec("Outlook along the route",
                                   U.badge("sl_outlook", where="left"),
                                   note="5 is Very High"), unsafe_allow_html=True)
                st.bar_chart(prof[["Outlook (1-5)"]], height=200, color=T.ACCENT)
            st.download_button(
                f"⬇️  Route profile, {days[di]} (CSV)",
                prof.reset_index().to_csv(index=False).encode(),
                f"route_profile_{days[di]}.csv", "text/csv")
        else:
            with st.container(border=True):
                st.markdown(U._sec("Worst stretches", U.badge("sl_outlook", where="right"),
                                   note="ranked by level, then length · top 60"),
                            unsafe_allow_html=True)
                if not spots:
                    st.success(f"No road stretch reaches High on "
                               f"{sel_day.strftime('%d %b')}.")
                else:
                    rows = []
                    for h in spots[:60]:
                        near, dkm = G.nearest_place(h["lat"], h["lon"], PLACES)
                        rows.append({"Nearest settlement":
                                         f"{near['label']} ({dkm:.0f} km)" if near else "—",
                                     "Outlook": T.CLASS_NAMES[h["peak"] - 1],
                                     "Length (km)": round(h["km"], 1),
                                     "Latitude": round(h["lat"], 4),
                                     "Longitude": round(h["lon"], 4)})
                    rdf = pd.DataFrame(rows)
                    st.dataframe(rdf, width="stretch", hide_index=True, height=340,
                                 column_config={"Length (km)": st.column_config.ProgressColumn(
                                     "Length (km)", min_value=0,
                                     max_value=float(max(r["Length (km)"] for r in rows)),
                                     format="%.1f km")})
                    st.download_button(
                        f"⬇️  Road hotspots, {days[di]} (CSV)",
                        rdf.rename(columns={"Nearest settlement": "nearest_settlement",
                                            "Outlook": "outlook", "Length (km)": "length_km",
                                            "Latitude": "lat", "Longitude": "lon"}
                                   ).to_csv(index=False).encode(),
                        f"road_hotspots_{days[di]}.csv", "text/csv")

        with st.expander("📖  How to read this page"):
            st.markdown(
                "**What it shows.** Every kilometre of main road, coloured by the landslide "
                "outlook on the ground it crosses that day. A stretch is a continuous run of "
                "road at High or above — the unit you would send a crew to. Coordinates in "
                "the table are the middle of the stretch.\n\n"
                "**The road layer has no names.** OpenStreetMap gives us 3,489 km of trunk, "
                "primary and secondary road for Arunachal, but no route numbers, so a stretch "
                "is named by the settlement nearest to it, not as “NH-13, km 47”. Matching to "
                "PWD chainage would fix that.\n\n"
                "**What it does not model.** Exposure is the outlook on the ground the road "
                "crosses — not the slope above the carriageway, which is what actually lands "
                "on it. That needs road-cut geometry we do not have.\n\n"
                "**A route** is the shortest path over the *mapped* network, not a navigation "
                "instruction. Where OpenStreetMap coverage is patchy it can detour, and it "
                "knows nothing about one-way streets, closures or surface quality.")

    # ═════════════════════ VIEW: SUSCEPTIBILITY ══════════════════════════════
    elif view == "Susceptibility":
        sel = U.page_head("Susceptibility", "Where slopes are weak — the static half", "◆",
                          search_row)
        U.key_row("sl_ground", "sl_record", note="No rain in it — the same every day")

        su_m = MET["susceptibility"]
        sr = su_m.get("success_rate", [])
        scls = susceptibility_classes()
        ids, dnames = district_ids()
        in_state = ids > 0
        w = where(sel)
        centre, zoom, marker, clip = frame(sel, w)

        kpis = [
            U._tile("Checked on unseen ground", f"{100 * su_m['auc']:.0f}<small> in 100</small>",
                    "landslide ranked above stable ground", None, None,
                    "Tested by hiding whole regions during training, so it is scored on "
                    "ground it has never seen: how often a mapped landslide spot was ranked "
                    f"above a spot with none (±{100 * su_m['auc_std']:.0f}).", "right"),
            U._tile("Landslides it learned from", f"{MET['labels']['polygons']:,}",
                    "mapped by GSI, NRSC and APSAC", "sl_record", None),
        ]
        if len(sr) == 5:
            top_land = sr[3]["area_frac"] + sr[4]["area_frac"]
            top_slides = sr[3]["slide_frac"] + sr[4]["slide_frac"]
            kpis += [
                U._tile(f"Top {100 * top_land:.0f}% of land holds",
                        f"{100 * top_slides:.0f}%", "of mapped landslides", "sl_record",
                        T.CLASS_TEXT[3],
                        "The ground ranked High or Very High, and the share of every mapped "
                        "landslide that falls on it."),
                U._tile("Very High ground", f"{sr[4]['lift']:.1f}×",
                        "the landslides of average ground", "sl_record", T.CLASS_TEXT[4],
                        f"The top {100 * sr[4]['area_frac']:.0f}% of land holds "
                        f"{100 * sr[4]['slide_frac']:.0f}% of mapped landslides."),
            ]
        kpis += [
            U._tile("What it reads", f"{su_m['n_features']}", "terrain, soil, rock, land cover",
                    None, None, "The number of inputs the model reads for every 100 m cell.",
                    "left"),
            U._tile("Not scored", pc(float((SUS[in_state] == 255).mean())) if in_state.any()
                    else "—", "of the state · ice, water, flat ground", None, None,
                    "Permanent ice, open water and ground flatter than 10°. The model never "
                    "trained on this terrain, so it reports nothing there.", "left"),
        ]
        st.markdown(U._tiles(kpis, len(kpis)), unsafe_allow_html=True)

        shown = GR.clip_to(scls, clip)
        assessed = shown > 0
        shares = [float((shown[assessed] == i).mean()) if assessed.any() else 0
                  for i in range(1, 6)]
        whose = f"{w['name']}'s" if clip is not None else "the state's"
        map_name = "Slope susceptibility"
        cl, cm, cr = U.main_row()

        # ── left: the place, the district, or how the levels held up ───────
        panel = U.Panel(sel)
        with cl, st.container(key="fs_col_l"):
            if w["kind"] == "none":
                U.state_title()
                if len(sr) == 5:
                    mx = max(r["slide_frac"] for r in sr)
                    panel.show(
                        U._sec("Mapped landslides by level", U.badge("sl_record", where="right"))
                        + U.hbars([(r["name"], r["slide_frac"], f"{100 * r['slide_frac']:.0f}%",
                                    T.CLASS_COLORS[r["cls"] - 1],
                                    f"In the model's test, the ground it ranked {r['name']} "
                                    f"({100 * r['area_frac']:.0f}% of the land) held "
                                    f"{100 * r['slide_frac']:.0f}% of mapped landslides: "
                                    f"{r['lift']:.1f}× average ground.")
                                   for r in sr[::-1]], mx)
                        + f"<span class='fs-pill' style='--c:{T.CLASS_TEXT[4]}'>The reddest "
                        f"{100 * sr[4]['area_frac']:.0f}% of land holds "
                        f"{100 * sr[4]['slide_frac']:.0f}% of them</span>")
                # districts by how much of their scored land is High or above
                stab = district_table(scls)
                st.markdown("<div style='height:10px'></div>"
                            + U._sec("Most susceptible districts",
                                     U.badge("sl_ground", where="right")),
                            unsafe_allow_html=True)
                panel.keep(U._sec("Most susceptible districts",
                                  U.badge("sl_ground", where="right"))
                           + "".join(f"<div class='fsf-row' style='--c:{T.CLASS_COLORS[3]}'>"
                                     f"<span>{html.escape(r_['District'])}</span>"
                                     f"<b>{r_['High+ %']:.1f}%</b></div>"
                                     for r_ in stab.head(5).to_dict("records")))
                district_picks(stab, 5)
            elif w["kind"] == "district":
                U.place_title(sel, place_sub(sel))
                hi_d = shares[3] + shares[4]
                panel.show(U.hero(
                    "High or above", pc(hi_d), f"of {html.escape(w['name'])}'s assessed land",
                    "a property of the ground — the same every day", T.CLASS_COLORS[3],
                    T.CLASS_TEXT[3], "⛰", "sl_ground"))
                st_all = scls[scls > 0]
                panel.show(U._tiles([
                    U._tile("Very High", pc(shares[4]), "of its assessed land", "sl_ground",
                            T.CLASS_TEXT[4], where="right"),
                    U._tile("Statewide", pc(float((st_all >= 4).mean())) if st_all.size else "—",
                            "at High or above, for comparison", "sl_ground", None,
                            where="left"),
                    U._tile("Land scored", f"{int(assessed.sum()) * CELL_KM ** 2:,.0f}"
                            "<small> km²</small>", "inside the district", None, None,
                            "Ground the model scores, counted on the ~550 m map cells.",
                            "right"),
                    U._tile("Not scored", pc(float((SUS[w['mask']] == 255).mean())),
                            "ice, water, flat ground", None, None, where="left")],
                    2, grow=True))
            else:
                U.place_title(sel, place_sub(sel))
                if w["kind"] == "outside":
                    panel.show(EMPTY_OUTSIDE)
                elif w["kind"] == "unassessed":
                    panel.show(EMPTY_UNASSESSED)
                else:
                    su = w["su"]
                    k = sus_level(su)
                    stops, lo_ = [], 0.0
                    for col, hi_ in zip(T.CLASS_COLORS, list(SUS_CUTS) + [1.0]):
                        stops.append(f"{col} {100 * lo_:.0f}% {100 * hi_:.0f}%")
                        lo_ = hi_
                    meter = (f"<div class='fs-meter' style='background:linear-gradient(90deg,"
                             f"{','.join(stops)})'><i style='left:{100 * min(su, 1.0):.0f}%'></i>"
                             "</div><div class='fs-meter-l'><span>0</span><span>0.5</span>"
                             "<span>1</span></div>")
                    panel.show(U.hero(
                        T.CLASS_NAMES[k - 1], f"{su:.2f}",
                        "slope susceptibility here, 0 to 1" if w["dcells"] <= 0
                        else "susceptibility of the nearest slope, 0 to 1",
                        "a property of the ground — the same every day",
                        T.CLASS_COLORS[k - 1], T.CLASS_TEXT[k - 1], "⛰", "sl_ground",
                        bars_html=meter))
                    t = []
                    if len(sr) == 5:
                        r_ = sr[k - 1]
                        t += [U._tile("Mapped landslides", f"{100 * r_['slide_frac']:.0f}%",
                                      f"fall on {r_['name']} ground", "sl_record", None,
                                      f"In the model's test, the ground it ranked {r_['name']} "
                                      f"({100 * r_['area_frac']:.0f}% of the land) held "
                                      f"{100 * r_['slide_frac']:.0f}% of mapped landslides. The "
                                      "map's bands are close to those test bands, not identical.",
                                      "right"),
                              U._tile("Against average", f"{r_['lift']:.1f}×",
                                      "landslides per share of land", "sl_record", None,
                                      "How many times more (or fewer) mapped landslides this "
                                      "level holds than its share of the land.", "left")]
                    if ELEV is not None and np.isfinite(ELEV[w["r"], w["c"]]):
                        t.append(U._tile("Height", f"{float(ELEV[w['r'], w['c']]):,.0f}"
                                         "<small> m</small>", "above sea level", None, None,
                                         where="right"))
                    panel.show(U._tiles(t, 2, grow=True) + snap_foot(w))

        # ── centre: the map ──────────────────────────────────────────────────
        with cm, st.container(key="fs_col_m"):
            with st.container(border=True, key="fs_mapcard"):
                U.map_title(map_name,
                            U.badge("sl_ground", "Colour: how prone each ~550 m square is "
                                    "to fail. No rain in it.", "down"), right=lambda: None)
                shell_box = st.container(height=MAP_H + 8, border=False, key="map_shell")
                m = base_map()

                def _more(fg):
                    U.fullscreen_panel(map_name, panel.body(colour_key(
                        "sl_ground", T.CLASS_NAMES, T.CLASS_COLORS, shares))).add_to(fg)

                fg = overlay_group(None if s.bare else M.rgba_overlay(shown, T.CLASS_COLORS),
                                   districts=s.districts, marker=marker, more=_more,
                                   focus=w.get("feat"))
                fly_c, fly_z = M.fly_to(sel, zoom, centre)
                with shell_box:
                    out = st_folium(m, height=MAP_H, use_container_width=True,
                                    pixelated=True, returned_objects=["last_clicked"],
                                    feature_group_to_add=fg, center=fly_c, zoom=fly_z,
                                    key="smap")
                U.take_click(out)
                if s.bare:
                    M.legend_strip([], [], bare=True)
                else:
                    st.markdown(U.legend(
                        T.CLASS_NAMES, T.CLASS_COLORS, shares,
                        tip=f"How prone each ~550 m square is to fail. The share is of {whose} "
                            "assessed land. Blank: ice, open water or ground flatter than 10°. "
                            "Static — no rainfall in this layer.",
                        syms=((U.sym("line", "main road", T.ROAD_INK[s.basemap])
                               if s.roads else "")
                              + (U.sym("box", "selected district", T.ACCENT)
                                 if clip is not None else ""))), unsafe_allow_html=True)

        # ── right: land by level, what it reads, the forecast ───────────────
        with cr, st.container(key="fs_col_r"):
            with st.container(key="fs_r_a"):
                st.markdown(
                    U._sec("Land by level", U.badge("sl_ground", where="left"),
                           note="of " + ("the district" if clip is not None else "the state"))
                    + U.hbars([(T.CLASS_NAMES[i], shares[i], pc(shares[i]), T.CLASS_COLORS[i],
                                f"{pc(shares[i])} of {whose} assessed land is at "
                                f"{T.CLASS_NAMES[i]}.") for i in range(4, -1, -1)]),
                    unsafe_allow_html=True)
            teal = U.SLOPE_TIERS["sl_ground"][2]
            with st.container(key="fs_r_b"):
                st.markdown(
                    U._sec("What it is read from") + "<div class='fs-rows fs-grow'>"
                    + U._row("◢", teal, "Shape of the slope",
                             U._i("Steepness, the way it faces, how it curves and how water "
                                  "gathers on it — from Copernicus 30 m elevation.", "left"))
                    + U._row("▤", teal, "Soil",
                             U._i("Soil properties from SoilGrids.", "left"))
                    + U._row("◈", teal, "Rock and faults",
                             U._i("Rock type and mapped fault lines (APSSDI).", "left"))
                    + U._row("❖", teal, "Land cover",
                             U._i("Forest, cropland, bare ground, built-up: ESA WorldCover, "
                                  "10 m.", "left"))
                    + U._row("↔", teal, "Roads and rivers nearby",
                             U._i("Road cuts over-steepen slopes and rivers undercut their "
                                  "toes. Part of the road signal is surveyors reaching "
                                  "roadsides more easily, so it is never read as pure "
                                  "physics.", "left"))
                    + U._row("◷", U.SLOPE_TIERS["sl_record"][2],
                             f"{MET['labels']['polygons']:,} mapped landslides",
                             U._i("What it learned from: failure outlines mapped by GSI, and "
                                  "NRSC Bhuvan / APSAC post-monsoon surveys.", "left"))
                    + "</div>", unsafe_allow_html=True)
            with st.container(key="fs_r_c"):
                st.markdown(U._sec("This week's outlook", U.badge("sl_outlook", where="left"))
                            + "<div class='fs-foot' style='margin:0 0 8px'>This map has no "
                              "rain in it. The forecast multiplies it by how unusual the rain "
                              "is, day by day.</div>", unsafe_allow_html=True)
                to_view("Forecast", "📍  Open the landslide forecast", "sl_to_forecast")

        if sr:
            with st.expander("📋  How well it concentrates risk — table"):
                st.dataframe(pd.DataFrame([{
                    "Class": r["name"], "% of land": f"{100*r['area_frac']:.0f}%",
                    "% of known landslides": f"{100*r['slide_frac']:.0f}%",
                    "Concentration": f"{r['lift']:.1f}×"} for r in sr]),
                    width="stretch", hide_index=True)
                st.caption("Read the bottom row: the smallest, reddest sliver of the "
                           "state contains a large share of every landslide mapped "
                           "there.")
        with st.expander("📖  How to read this map"):
            st.markdown(
                "**What this map is.** Not a forecast — there is no rain in it. It answers "
                "one question for every slope: *how prone is this ground to fail?* The answer "
                "comes from the shape of the slope, its soil and rock, what covers it and how "
                f"close it is to a road or a river — learned from {MET['labels']['polygons']:,} "
                "mapped landslides.\n\n"
                "**It is a ranking, not a chance.** The inventory records where slopes failed, "
                "never where they were checked and found sound, so there is no way to turn the "
                "score into a probability. Read 0.60 as “among the most failure-prone ground "
                "in the state”, not as 60%.\n\n"
                "**What it leaves out.** Ice, open water and ground flatter than 10° are not "
                "scored. The landslide forecast multiplies this layer by how unusual the rain "
                "is, day by day.")

    # ═════════════════════ VIEW: EVIDENCE ════════════════════════════════════
    elif view == "Evidence":
        U.page_head("The evidence base", "What the forecast is built from", "🧭", None,
                    warn=False)
        U.key_row("sl_record", "sl_input")
        st.markdown(U._tiles([
            U._tile("Landslides mapped", f"{len(INVENTORY):,}" if INVENTORY else "—",
                    "inside the state", "sl_record"),
            U._tile("Days of rainfall", "9,555", "26 years, no gaps", "sl_input"),
            U._tile("Terrain cells", "8.2 M", "100 m resolution"),
            U._tile("Model inputs", f"{MET['susceptibility']['n_features']}",
                    "read for every cell")], 4), unsafe_allow_html=True)

        if INVENTORY:
            with st.container(border=True):
                M.map_head("Where the landslides are",
                           "each point is a surveyed failure, not a model output")
                shell_box = st.container(height=MAP_H + 8, border=False,
                                         key="map_shell")
                m = base_map()
                # This map IS the inventory, so it always draws the heatmap —
                # independent of the sidebar's inventory control.
                fg = overlay_group(None, districts=s.districts, inventory=False)
                HeatMap([(d["y"], d["x"]) for d in INVENTORY], radius=8, blur=11,
                        min_opacity=.35,
                        gradient={0.2: "#1e3a8a", 0.45: "#38bdf8",
                                  0.7: "#fde047", 1.0: "#dc2626"}).add_to(fg)
                with shell_box:
                    st_folium(m, height=MAP_H, use_container_width=True,
                              pixelated=True, returned_objects=[],
                              feature_group_to_add=fg, key="emap")
            st.caption("Turn on **Roads** in the sidebar — the clustering along "
                       "the road network is real, and it is partly physical (road "
                       "cuts over-steepen slopes) and partly a survey artefact "
                       "(surveyors reach roadsides more easily). We keep the "
                       "feature, but never read its importance as pure physics.")

        src = pd.DataFrame([
            {"Dataset": "GSI National Landslide Inventory",
             "What": "Mapped failure outlines",
             "Scale": "26,459 polygons", "Used for": "Where slopes fail"},
            {"Dataset": "NRSC Bhuvan / APSAC SILAAS",
             "What": "Post-monsoon surveys 2014/17/23",
             "Scale": "11,329 polygons", "Used for": "Where slopes fail"},
            {"Dataset": "NASA Global Landslide Catalog",
             "What": "Landslides with a known date",
             "Scale": "84 events", "Used for": "When they fail"},
            {"Dataset": "NASA GPM IMERG", "What": "Daily rainfall 2000–2026",
             "Scale": "9,555 days", "Used for": "Rainfall history"},
            {"Dataset": "Open-Meteo", "What": "Live + forecast rainfall",
             "Scale": f"{len(PTS['lat'])} points, 7 days", "Used for": "The live forecast"},
            {"Dataset": "Copernicus DEM", "What": "Elevation",
             "Scale": "30 m", "Used for": "Slope, aspect, curvature, wetness"},
            {"Dataset": "SoilGrids", "What": "Soil properties",
             "Scale": "18 layers", "Used for": "Where slopes fail"},
            {"Dataset": "ESA WorldCover", "What": "Land cover",
             "Scale": "10 m", "Used for": "Where slopes fail"},
            {"Dataset": "APSSDI", "What": "Lithology + fault lines",
             "Scale": "4,777 lineaments", "Used for": "Where slopes fail"},
            {"Dataset": "OpenStreetMap", "What": "Road network",
             "Scale": "107,302 ways", "Used for": "Where slopes fail"},
            {"Dataset": "HydroSHEDS", "What": "River network",
             "Scale": "50,800 reaches", "Used for": "Where slopes fail"},
            {"Dataset": "Settlement gazetteer", "What": "Named places for search",
             "Scale": f"{len(PLACES):,} entries", "Used for": "Location forecasts"},
        ])
        st.markdown("<div class='eyebrow'>Every source</div>",
                    unsafe_allow_html=True)
        st.dataframe(src, width="stretch", hide_index=True, height=440)

        st.markdown("<div class='eyebrow'>The imbalance that shapes everything"
                    "</div>", unsafe_allow_html=True)
        a, b = st.columns(2)
        a.markdown("##### Where — abundant\n"
                   f"**{len(INVENTORY):,}** mapped landslides.\n\n"
                   "Enough to train a proper model, test it on regions it has "
                   "never seen, and still have data left over. This half is strong.")
        b.markdown("##### When — scarce\n"
                   f"**{MET['trigger']['n_events']}** landslides with a usable "
                   "date.\n\nThree orders of magnitude fewer. This is why the "
                   "timing half is a transparent rule rather than a learned model "
                   "— and it is the single biggest limit on the whole system.")
        st.markdown("<div class='caveat'>We tried five separate routes to find "
                    "more dated landslides — including reading dates off satellite "
                    "imagery and radar. Four failed, and we documented why. The "
                    "honest position is that this is a data problem, not a "
                    "modelling one.</div>", unsafe_allow_html=True)

    # ═════════════════════ VIEW: MODEL ═══════════════════════════════════════
    else:
        U.page_head("Model & validation", "How it was tested, and its limits", "📊", None,
                    warn=False)
        U.key_row("sl_ground", "sl_input", "sl_record")
        su, tr = MET["susceptibility"], MET["trigger"]
        st.markdown(U._tiles([
            U._tile("Where — accuracy", f"{su['auc']:.3f}", f"±{su['auc_std']:.3f}",
                    "sl_ground"),
            U._tile("When — accuracy", f"{tr['auc']:.3f}", f"±{tr['auc_ci95']:.3f}",
                    "sl_input"),
            U._tile("Landslides mapped", f"{MET['labels']['polygons']:,}",
                    "what the where half learned from", "sl_record"),
            U._tile("Dated events", f"{tr['n_events']}", "what the when half was tested on",
                    "sl_record")], 4), unsafe_allow_html=True)

        st.markdown("##### What those two numbers mean")
        # Read from metrics.json, never typed in. An earlier version hardcoded the
        # event count as 84 while the metric card beside it read 72 — 84 is how
        # many dated events the catalogue holds, 72 is how many survive the
        # filters and actually train the trigger. The page must show the number
        # it used.
        st.markdown(
            f"- **Where ({su['auc']:.3f})** — built from "
            f"{MET['labels']['polygons']:,} mapped landslides, and tested by "
            "hiding whole regions during training, so it is scored on ground it "
            "has never seen.\n"
            f"- **When ({tr['auc']:.3f})** — built from only "
            f"**{tr['n_events']}** landslides whose *date* is known. That is why "
            "it is a transparent rule rather than a learned model: we tested a "
            "fitted model and it performed **worse**.")

        st.markdown("##### Alert thresholds — the trade-off is yours to set")
        st.dataframe(pd.DataFrame([{
            "Alert when trigger ≥": f"{o['threshold']:.2f}",
            "How often it alerts": f"{100*o['alert_rate']:.1f}% of days",
            "Known landslides caught": f"{100*o['event_capture']:.0f}%",
            "Better than chance": f"{o['lift']:.1f}×"}
            for o in tr["operating_points"]]),
            width="stretch", hide_index=True)
        st.caption("Catching more means alerting more. No setting does both — "
                   "that is a policy decision, not a modelling one.")

        st.markdown("##### Limits we will not paper over")
        for c in MET["caveats"]:
            st.markdown(f"<div class='caveat'>{c}</div>", unsafe_allow_html=True)
        st.markdown("<div class='caveat'><b>We cannot give you a false-alarm rate."
                    "</b> An alert day with no reported landslide might mean we "
                    "were wrong — or that a slope failed in an empty valley and "
                    f"nobody recorded it. {tr['n_events']} dated landslides across "
                    "16 years is a fraction of what actually happened. Any such "
                    "number would be invented.</div>", unsafe_allow_html=True)

        with st.expander("Data sources"):
            st.markdown(
                "- **Landslide inventory** — Geological Survey of India; NRSC "
                "Bhuvan / APSAC SILAAS post-monsoon surveys\n"
                "- **Terrain** — Copernicus 30 m DEM\n"
                "- **Soil** — SoilGrids · **Land cover** — ESA WorldCover 10 m\n"
                "- **Rainfall history** — NASA GPM IMERG, 2000–2026\n"
                "- **Live forecast** — Open-Meteo (free tier)\n"
                "- **Dated events** — NASA Global Landslide Catalog")

    st.markdown("<div class='app-footer'><b>SlideSense Forecast</b>"
                "<span>Hazard = susceptibility × rainfall trigger</span></div>",
                unsafe_allow_html=True)
