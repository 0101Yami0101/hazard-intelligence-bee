"""SlopeSense pages.

Everything lives inside render() on purpose. The page needs about twenty
values that are fixed for one rerun — the grid, the bundle, the sidebar
settings, today's rainfall — and the helpers below close over them instead of
taking twenty arguments each. That is the same shape the module had as a flat
script, which is why moving it here changed no behaviour.
"""
from __future__ import annotations

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
VIEWS = [("📍", "Forecast"), ("🛣️", "Roads"), ("🗺️", "Susceptibility")]


def render(shell) -> None:
    from core.rainfall import load_forecast
    from products.landslide.data import load_model

    grid, geo, ELEV = shell.grid, shell.geo, shell.elev
    PLACES, PLACE_IDX, LOOKUP = shell.places, shell.loc.place_idx, shell.lookup
    H, W = grid.height, grid.width
    WEST, EAST = grid.west, grid.east
    SOUTH, NORTH = grid.south, grid.north
    DLON, DLAT = grid.dlon, grid.dlat
    CELL_KM = grid.cell_km
    DISTRICTS, ROADS = geo.districts, geo.roads

    SUS, NEAR, QUANT, PTS, MET, INVENTORY = load_model()
    fx = load_forecast(tuple(PTS["lat"]), tuple(PTS["lon"]))
    LIVE = fx is not None

    # ─────────────────────── sidebar ─────────────────────────────────────────
    if "view" not in st.session_state:
        st.session_state.view = VIEWS[0][1]

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

    def overlay_group(img=None, districts=False, marker=None, inventory=True):
        return M.overlay_group(grid, s, geo, img=img, districts=districts,
                               marker=marker,
                               extra=inv_extra if inventory else None)

    def legend_strip(names, colors, shares=None, note=""):
        M.legend_strip(names, colors, shares, note, bare=s.bare)

    def day_strip(key, notes=None):
        return M.day_strip(key, days, fut, notes)

    def location_days(sel):
        """That one place's hazard class and score for each of the seven days.

        Returns None when there is no location, or when the location sits on
        ground the model never assessed — in both cases the strip falls back to
        a statewide figure rather than inventing a local one.

        ⚠️ Snaps to the nearest assessed cell via the SAME helper the detail
        panel below uses. Reading SUS[r, c] directly here instead would let the
        strip say "not assessed" while the panel underneath it reported High
        for a slope 2 km away — two numbers for one place, on one screen.
        """
        if not sel:
            return None
        px = latlon_to_px(sel["lat"], sel["lon"])
        if px is None:
            return None
        snap = fc.nearest_assessed(SUS, *px)
        if snap is None:
            return None
        r, c, _ = snap
        su = float(SUS[r, c]) / 254.0
        j = int(NEAR[r, c])
        hz = np.array([su * float(trig[i][j]) for i in fut], dtype=np.float32)
        return hz, fc.classify(hz)

    @st.cache_data(show_spinner=False)
    def statewide_high_share(tag: str) -> list[float]:
        """Share of assessed land at High or Very High, for each forecast day.

        This is the honest statewide headline: it varies across the week (16%
        today to 7% next Monday in testing), it is a share of land rather than a
        probability, and no arithmetic pins it near any particular value.
        """
        out = []
        for i in fut:
            cl = fc.classify(fc.hazard_raster(SUS, NEAR, trig[i]))
            a = cl > 0
            out.append(float((cl[a] >= 4).mean()) if a.any() else 0.0)
        return out

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

    @st.cache_data(show_spinner=False)
    def road_high_km(tag: str) -> list[float]:
        """Kilometres of road at High or above, for each forecast day — the
        number on the day buttons of this view."""
        _, la, lo, km, _, _ = road_chunks()
        out = []
        for i in fut:
            c = sample_classes(fc.classify(fc.hazard_raster(SUS, NEAR, trig[i])),
                               la, lo)
            out.append(float(km[c >= 4].sum()))
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

    def district_feature(label: str):
        """The GeoJSON feature behind a "<name> district" search result."""
        name = label[:-9] if label.endswith(" district") else label
        return GR.feature_by(DISTRICTS["features"], "district", name)

    def district_mask(label: str):
        feat = district_feature(label)
        if feat is None:
            return np.ones(grid.shape, dtype=bool)
        return GR.polygon_mask(feat["geometry"], WEST, EAST, SOUTH, NORTH, H, W)

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

    def hazard_layers(di: int):
        """Everything the map layers need for one forecast day."""
        tri_pts = trig[di]
        hz = fc.hazard_raster(SUS, NEAR, tri_pts)
        cls = fc.classify(hz)
        return tri_pts, hz, cls

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
        out[ok] = (np.digitize(su[ok], np.array([.05, .15, .35, .60],
                                                dtype=np.float32)) + 1).astype(np.uint8)
        return out

    @st.cache_data(show_spinner=False)
    def district_table(cls_bytes: bytes, shape: tuple, tag: str):
        """Share of each district in High / Very High."""
        cls = np.frombuffer(cls_bytes, dtype=np.uint8).reshape(shape)
        rows = []
        for feat in DISTRICTS["features"]:
            name = feat["properties"].get("district", "—")
            gm = feat["geometry"]
            polys = (gm["coordinates"] if gm["type"] == "MultiPolygon"
                     else [gm["coordinates"]])
            lons, lats = [], []
            for poly in polys:
                for x, y in poly[0]:
                    lons.append(x); lats.append(y)
            if not lons:
                continue
            a = latlon_to_px(max(lats), min(lons))
            b = latlon_to_px(min(lats), max(lons))
            if a is None or b is None:
                continue
            sub = cls[a[0]:b[0] + 1, a[1]:b[1] + 1]
            sub = sub[sub > 0]
            if sub.size == 0:
                continue
            rows.append({"District": name,
                         "High+ %": round(100 * float((sub >= 4).mean()), 1),
                         "Peak class": T.CLASS_NAMES[int(sub.max()) - 1],
                         "Assessed cells": int(sub.size)})
        return pd.DataFrame(rows).sort_values("High+ %", ascending=False)

    def place_panel(sel, cls, hz, tri_pts, di, note: str = "") -> None:
        """The SELECTED place, beside the map rather than below it.

        This used to be a separate "clicked point" readout, which meant the map
        could show a pin on one place while the panel described another. There
        is now one selection: searching sets it, and clicking the map sets it
        too. Whatever the pin is on is what this panel is about.

        Height-locked to the map so long content scrolls inside the panel
        instead of stretching the row and leaving dead space beside the map.
        """
        st.markdown("<div class='map-head' style='padding-top:2px'>"
                    "<div class='mh-dot'></div>"
                    "<div class='mh-title'>Selected location</div></div>",
                    unsafe_allow_html=True)
        box = st.container(height=T.MAP_H - 34, border=False, key="click_shell")
        with box:
            if not sel:
                st.markdown("<div class='insp-empty'>No location chosen.<br><br>"
                            "Search a town above, or click anywhere on the map, "
                            "to get that spot's slope susceptibility, how unusual "
                            "the rain is there, and its next seven days.</div>",
                            unsafe_allow_html=True)
                return
            st.markdown(f"<div class='insp-place'>{sel['label']}</div>",
                        unsafe_allow_html=True)
            if note:
                st.markdown(f"<div class='caveat'>{note}</div>",
                            unsafe_allow_html=True)
            px = latlon_to_px(sel["lat"], sel["lon"])
            if px is None:
                st.markdown("<div class='insp-empty'><b>Outside the mapped area"
                            "</b><br>This model covers Arunachal Pradesh only."
                            "</div>", unsafe_allow_html=True)
                return
            r, c = px
            su8, j = int(SUS[r, c]), int(NEAR[r, c])
            if su8 == 255:
                st.markdown("<div class='insp-empty'><b>Not assessed</b><br>"
                            "Permanent ice, open water, or ground flatter than "
                            "10°. The model never trained on this terrain, so it "
                            "reports nothing rather than guessing.</div>",
                            unsafe_allow_html=True)
                return
            su = su8 / 254.0
            near, km = G.nearest_place(sel["lat"], sel["lon"], PLACES)
            st.markdown(
                f"<div style='margin-bottom:9px'>{T.chip(int(cls[r, c]) - 1)}</div>"
                + T.row("Latitude, longitude",
                        f"{sel['lat']:.4f}, {sel['lon']:.4f}")
                + T.row("Nearest settlement",
                        f"{near['label']} · {km:.0f} km" if near else "—")
                + T.row("Susceptibility", f"{su:.3f}")
                + T.row("Trigger (rain vs normal)", f"{tri_pts[j]:.2f}")
                + T.row("Hazard", f"{hz[r, c]:.3f}")
                + T.row("Rain that day", f"{rain[di, j]:.1f} mm"),
                unsafe_allow_html=True)
            st.caption("Next 7 days here")
            st.bar_chart(pd.DataFrame({
                "day": [datetime.fromisoformat(days[i]).strftime("%d %b")
                        for i in fut],
                "hazard": [float(su * trig[i][j]) for i in fut]}
            ).set_index("day"), height=170, color=T.ACCENT_2)

    # ═════════════════════ VIEW: FORECAST ════════════════════════════════════
    if view == "Forecast":
        if not LIVE:
            st.error("**Live rainfall is unavailable right now.** The free "
                     "weather service limits how often it can be queried. The "
                     "susceptibility map still works — open it from the sidebar. "
                     "Try again shortly.")
            st.stop()

        # ---- the map card, at the very top, exactly as SlopeSense v1 ------- #
        with st.container(border=True):
            # This page is the landslide forecast and nothing else.
            # Susceptibility is the static half and has its own tab; the rain
            # trigger is an input to the forecast, not a competing view of it,
            # and is planned for a page of its own. A layer switch with one
            # option is not a choice.
            h1, h3 = st.columns([2.2, 0.42], vertical_alignment="center")
            with h3:
                # ⚠️ 3D is PARKED, not deleted. The control is shown disabled so
                # the feature is visibly coming rather than silently missing, and
                # every 3D code path below is left intact — flip WIP_3D to False
                # and it comes straight back.
                st.segmented_control("View", ["2D", "🔧 3D"], default="2D",
                                     label_visibility="collapsed", disabled=WIP_3D,
                                     help="3D terrain view — under development.")
                dim = "2D"

            # Search row. `accept_new_options` is what lets a visitor type raw
            # coordinates — the gazetteer has 4,648 names but the state has far
            # more places than that, and someone standing on a road cut needs
            # the forecast for exactly where they are.
            s1, s2, s3 = st.columns([5, 1.15, 0.95], vertical_alignment="bottom")
            with s2:
                if st.button("📍 My location", width="stretch",
                             help="Ask the browser where you are. Only used if "
                                  "you are inside Arunachal Pradesh."):
                    ask_again()
                    st.rerun()
            with s3:
                # The map is deliberately left wherever the user panned it, so
                # this is the only way back to the selected place without
                # re-picking it.
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

            sel = G.resolve(st.session_state.search, PLACES, LOOKUP)
            if sel is None and st.session_state.search != G.PROMPT:
                st.warning(f"Could not read **{st.session_state.search}** as a "
                           "place or a coordinate. Try a name from the list, or "
                           "`27.09, 93.61`.")

            with h1:
                M.map_head("Landslide forecast",
                           "" if dim == "3D" else "click anywhere to inspect")

            # Each button carries the outlook FOR THE SELECTED PLACE, so the
            # number beside a date is about somewhere a person actually is.
            #
            # ⚠️ The strip must ALWAYS say which of the two it is showing. It
            # used to fall back to the statewide share in silence, so the buttons
            # read "11% High+" with nothing on screen naming a place — and there
            # was no way to tell whether that was your town or all of Arunachal.
            ld = location_days(sel)
            if ld is not None:
                notes = [T.CLASS_NAMES[k - 1] for k in ld[1]]
                strip_label = f"7-day outlook · <b>{sel['label']}</b>"
            else:
                notes = [f"{100 * x:.0f}% High+"
                         for x in statewide_high_share(days[fut[0]])]
                strip_label = ("7-day outlook · <b>whole state</b> — share of land "
                               "at High or above. Pick a place for a local forecast.")
            st.markdown(f"<div class='strip-label'>{strip_label}</div>",
                        unsafe_allow_html=True)
            di = day_strip("fc", notes)
            sel_day = datetime.fromisoformat(days[di])
            tri_pts, hz, cls = hazard_layers(di)

            # A district is CLIPPED to its own polygon — in 2D and 3D alike. The
            # 3D view used to window to a square box around the centre while 2D
            # showed the whole state, so the same search gave two different
            # answers about what you were looking at.
            dfeat = (district_feature(sel["label"])
                     if sel and sel["kind"] == "district" else None)
            clip = district_mask(sel["label"]) if dfeat else None

            marker = None
            centre, zoom = None, 7
            if sel:
                centre = (sel["lat"], sel["lon"])
                zoom = 11
                marker = (sel["lat"], sel["lon"], sel["label"])
            if dfeat:
                # Frame the district by its own size — they range from Namsai at
                # 1,582 cells to West Siang at 29,159, so one fixed zoom either
                # cropped the big ones or lost the small ones in white space.
                pts = np.array([p for ring in G._rings(dfeat["geometry"])
                                for p in ring])
                # np.ptp(), not ndarray.ptp() — the method was removed in NumPy 2.
                span = max(float(np.ptp(pts[:, 0])), float(np.ptp(pts[:, 1])), 0.05)
                centre = (float(pts[:, 1].mean()), float(pts[:, 0].mean()))
                zoom = float(np.clip(np.log2(360.0 / span) - 1.6, 6, 11))
                marker = None   # the outline says where it is; a pin adds nothing

            # Inspector LEFT, map RIGHT, side by side inside the same card.
            #
            # ⚠️ The map is rendered FIRST even though it sits second on screen:
            # `out` does not exist until st_folium has run, and the inspector
            # needs it. Streamlit places output by which column context it is
            # written into, not by execution order, so writing the map into
            # `cmap` before the panel into `cinfo` still draws the panel left.
            cinfo, cmap = st.columns([1, 2.35], gap="medium")

            with cmap:
                out = None
                img = None
                shown = GR.clip_to(cls, clip)
                if not s.bare:
                    img = M.rgba_overlay(shown, T.CLASS_COLORS)

                # Height-locked shell: switching layer must not collapse the card
                # and bounce the panels below it up for a frame.
                shell_box = st.container(height=T.MAP_H + 8, border=False,
                                         key="map_shell")
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
                            centre=centre or ((SOUTH + NORTH) / 2,
                                              (WEST + EAST) / 2),
                            zoom=(zoom - 1.5) if sel else 6.4,
                            pos_b64=pb, col_b64=cb, n_points=npt,
                            cell_m=cell_m,
                            marker=({"pos": [sel["lon"], sel["lat"]],
                                     "tip": sel["label"]} if sel else None),
                        ), height=T.MAP_H)
                    if dfeat:
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
                    fg = overlay_group(img, districts=s.districts, marker=marker)
                    if dfeat:
                        folium.GeoJson(dfeat, name="Selected district",
                                       style_function=lambda _: {
                                           "color": T.ACCENT, "weight": 2.6,
                                           "fill": False, "opacity": .95}).add_to(fg)
                    fly_c, fly_z = M.fly_to(sel, zoom)
                    with shell_box:
                        # ⚠️ Stable key. Keying on the layer would rebuild the
                        # component on every layer switch, which is exactly the
                        # reset we are avoiding — the layer now travels in the
                        # feature group instead.
                        out = st_folium(m, height=T.MAP_H, use_container_width=True,
                                        pixelated=True,
                                        returned_objects=["last_clicked"],
                                        feature_group_to_add=fg,
                                        center=fly_c, zoom=fly_z, key="fmap")
                    # A click IS a selection: it moves the pin, redraws the day
                    # strip and repoints the panel. Guarded on the coordinates so
                    # the rerun happens once per new click and does not loop.
                    click = (out or {}).get("last_clicked")
                    if click:
                        xy = (round(float(click["lat"]), 5),
                              round(float(click["lng"]), 5))
                        if xy != st.session_state.get("clicked_xy"):
                            st.session_state.clicked_xy = xy
                            st.session_state.pending_place = f"{xy[0]:.4f}, {xy[1]:.4f}"
                            st.rerun()
                if s.bare:
                    legend_strip([], [])
                else:
                    # Shares are of whatever is on screen: the district when one
                    # is clipped, the state otherwise. Quoting statewide shares
                    # under a district's name would be a different number to the
                    # map.
                    base = shown if clip is not None else cls
                    assessed = base > 0
                    shares = [float((base[assessed] == i).mean()) if assessed.any()
                              else 0 for i in range(1, 6)]
                    legend_strip(T.CLASS_NAMES, T.CLASS_COLORS, shares,
                                 note=("share of " + sel["label"] if clip is not None
                                       else "Terrain 100 m · rainfall ~33 km · "
                                            "shaded = outside Arunachal"))

            with cinfo:
                place_panel(sel, cls, hz, tri_pts, di,
                            note=("Clicking to select works on the 2D map."
                                  if dim == "3D" else ""))

        # ---- the located forecast ----------------------------------------- #
        if shell.loc.geo_state == "ok" and shell.loc.user_pt and not shell.loc.user_inside:
            st.info(f"You appear to be at {shell.loc.user_pt[0]:.2f}°N, "
                    f"{shell.loc.user_pt[1]:.2f}°E — **outside Arunachal "
                    "Pradesh**. This forecast covers Arunachal only, so nothing "
                    "has been selected. Search a place above, or click anywhere "
                    "on the map.")
        elif shell.loc.geo_state == "denied":
            st.caption("Location sharing was declined. Search a place above, click "
                       "the map, or press 📍 to try again.")

        if sel is None:
            st.markdown("<div class='insp-empty'>Search a town, a district, or a "
                        "coordinate above to get that location's 7-day outlook."
                        "</div>", unsafe_allow_html=True)
        else:
            px = latlon_to_px(sel["lat"], sel["lon"])
            if px is None:
                st.warning(f"**{sel['label']}** is outside the forecast area. "
                           "This model covers Arunachal Pradesh only.")
            else:
                snap = fc.nearest_assessed(SUS, *px)
                if snap is None:
                    st.markdown(
                        "<div class='insp-empty'><b>Not assessed here</b><br>"
                        "Permanent ice, open water, or ground flatter than 10° for "
                        "several kilometres in every direction. The model never "
                        "trained on this terrain, so it reports nothing rather "
                        "than guessing. Try a nearby settlement.</div>",
                        unsafe_allow_html=True)
                else:
                    r, c, dcells = snap
                    su8, j = int(SUS[r, c]), int(NEAR[r, c])
                    su = su8 / 254.0
                    series = np.array([su * trig[i][j] for i in fut],
                                      dtype=np.float32)
                    dcls = fc.classify(series)
                    here = float(su * tri_pts[j])
                    hcls = int(fc.classify(np.array([here]))[0])
                    worst = int(np.argmax(series))
                    ahead = (sel_day.date() - date.today()).days
                    when = ("today" if ahead == 0 else "tomorrow" if ahead == 1
                            else f"in {ahead} days")
                    conf = "higher confidence" if ahead <= 3 else "lower confidence"
                    st.markdown(f"""
                    <div class="loc-head">
                      <div class="loc-pin">📍</div>
                      <div>
                        <div class="loc-name">{sel['label']}</div>
                        <div class="loc-sub">{sel_day.strftime('%A %d %B %Y')} — {when}
                          · {conf} · {sel['lat']:.4f}°N, {sel['lon']:.4f}°E</div>
                      </div>
                      <div class="loc-right">
                        <div class="loc-cls" style="color:{T.CLASS_COLORS[hcls-1]}">
                          {T.CLASS_NAMES[hcls-1]}</div>
                        <div class="loc-lbl">landslide outlook here</div>
                      </div>
                    </div>""", unsafe_allow_html=True)

                    if dcells > 0:
                        st.markdown(
                            f"<div class='caveat'>The point itself is flat ground, "
                            f"open water or ice, which this model does not score. "
                            f"Shown here is the nearest slope it does assess, "
                            f"<b>{dcells * CELL_KM:.1f} km</b> away — which is the "
                            f"slope that would reach the town, not the ground the "
                            f"town stands on.</div>", unsafe_allow_html=True)

                    k = st.columns(4)
                    k[0].metric("Rain that day", f"{rain[di, j]:.0f} mm")
                    k[1].metric("Rain, previous 7 days",
                                f"{rain[max(di-6, 0):di+1, j].sum():.0f} mm")
                    k[2].metric("Trigger — rain vs normal", f"{tri_pts[j]:.2f}",
                                help="0.90 means wetter than 90% of days on record "
                                     "at this exact spot.")
                    k[3].metric("Slope susceptibility", f"{su:.2f}",
                                help="Static. Terrain, soil, rock and land cover — "
                                     "no rainfall at all.")

                    left, right = st.columns([1.6, 1])
                    with left:
                        M.map_head("Next 7 days here")
                        st.bar_chart(pd.DataFrame({
                            "day": [datetime.fromisoformat(days[i]).strftime("%a %d")
                                    for i in fut],
                            "hazard": series}).set_index("day"),
                            height=210, color=T.ACCENT)
                        peak_day = datetime.fromisoformat(days[fut[worst]])
                        st.markdown(
                            f"<div class='caveat'>Worst day in this window: "
                            f"<b>{peak_day.strftime('%A %d %b')}</b> — "
                            f"{T.CLASS_NAMES[int(dcls[worst])-1]}, "
                            f"hazard {series[worst]:.3f}.</div>",
                            unsafe_allow_html=True)
                    with right:
                        M.map_head("Day by day")
                        st.dataframe(pd.DataFrame({
                            "Day": [datetime.fromisoformat(days[i]).strftime("%a %d %b")
                                    for i in fut],
                            "Rain": [f"{rain[i, j]:.0f} mm" for i in fut],
                            "Trigger": [f"{trig[i][j]:.2f}" for i in fut],
                            "Outlook": [T.CLASS_NAMES[int(x) - 1] for x in dcls]}),
                            width="stretch", hide_index=True, height=280)

        # ---- statewide summary --------------------------------------------- #
        # The dedicated Statewide tab was removed: this page already shows the
        # whole state on the map, so a second page repeating it was a nav item
        # earning nothing. Its NUMBERS were worth keeping though, so they live
        # here, folded away — the district table and its CSV are the only export
        # an operations office actually asked for.
        assessed = cls > 0
        hi = float((cls[assessed] >= 4).mean()) if assessed.any() else 0.0
        with st.expander(f"Statewide summary — {100 * hi:.1f}% of assessed land at "
                         f"High or above on {sel_day.strftime('%d %b')}"):
            n_wet = int((tri_pts >= 0.90).sum())
            k = st.columns(3)
            k[0].metric("Unusually wet points", f"{n_wet} of {len(tri_pts)}",
                        help="Weather points whose 3- and 7-day rain sits in the "
                             "wettest 10% of everything that point has recorded "
                             "since 2010.")
            k[1].metric("Median trigger", f"{np.nanmedian(tri_pts):.2f}",
                        help="The typical point's rainfall percentile — 0.50 is an "
                             "ordinary monsoon day for that place.")
            k[2].metric("Rain, wettest point", f"{np.nanmax(rain[di]):.0f} mm")

            st.markdown("<div class='eyebrow'>District outlook</div>",
                        unsafe_allow_html=True)
            dtab = district_table(cls.tobytes(), cls.shape, days[di])
            st.dataframe(dtab, width="stretch", hide_index=True, height=340,
                         column_config={"High+ %": st.column_config.ProgressColumn(
                             "High+ %", min_value=0, max_value=100, format="%.1f%%")})
            st.download_button("⬇️  District outlook (CSV)",
                               dtab.to_csv(index=False).encode(),
                               f"slopesense_{days[di]}.csv", "text/csv")
            st.caption("District figures are approximate — computed over each "
                       "district's bounding box, not an exact polygon clip.")

    # ═════════════════════ VIEW: ROADS ═══════════════════════════════════════
    elif view == "Roads":
        if not LIVE:
            st.error("**Live rainfall is unavailable right now.** Try again shortly.")
            st.stop()
        if not ROADS:
            st.warning("No road layer in the bundle.")
            st.stop()

        st.markdown("#### Road exposure")

        chunks, c_lat, c_lon, c_km, c_rid, c_hw = road_chunks()

        # ---- pick a route (optional) --------------------------------------- #
        # Empty by default on purpose: the whole-network view is the one that
        # answers "where do I look today", and it should not need two choices
        # before it shows anything.
        NONE = "—"
        labels = [NONE] + [p["label"] for p in PLACES]
        r1, r2, r3 = st.columns([1, 1, 0.42], vertical_alignment="bottom")
        with r1:
            st.selectbox("From", labels, key="rd_from",
                         help="Leave both empty for the whole network.")
        with r2:
            st.selectbox("To", labels, key="rd_to")
        with r3:
            if st.button("Clear route", width="stretch"):
                st.session_state.rd_from = NONE
                st.session_state.rd_to = NONE
                st.rerun()
        p_from = LOOKUP.get(st.session_state.get("rd_from", NONE))
        p_to = LOOKUP.get(st.session_state.get("rd_to", NONE))

        di = day_strip("rd", [f"{k:.0f} km" for k in road_high_km(days[fut[0]])])
        sel_day = datetime.fromisoformat(days[di])
        tri_pts, hz, cls = hazard_layers(di)
        c_cls = sample_classes(cls, c_lat, c_lon)

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

        ahead = (sel_day.date() - date.today()).days

        if route:
            # ---- ONE ROUTE ------------------------------------------------- #
            r_gj, r_lo, r_la, r_at, r_cls = route_geojson(route, cls)
            step = r_at[1] - r_at[0] if len(r_at) > 1 else 0.6
            r_km_by_class = [float((r_cls == cc).sum() * step) for cc in range(1, 6)]
            r_high = r_km_by_class[3] + r_km_by_class[4]
            r_assessed = float(sum(r_km_by_class))
            worst_i = int(np.argmax(r_cls))

            k = st.columns(4)
            k[0].metric("Route length", f"{route_km:,.0f} km")
            k[1].metric("At High or above", f"{r_high:,.0f} km",
                        f"{100*r_high/r_assessed:.0f}% of the route"
                        if r_assessed else "—")
            k[2].metric("Worst point",
                        T.CLASS_NAMES[int(r_cls[worst_i]) - 1] if r_cls[worst_i]
                        else "—", f"km {r_at[worst_i]:.0f}")
            k[3].metric("Lead time", "Today" if ahead == 0 else f"+{ahead} d")
            if max(snap_a, snap_b) > 3:
                st.caption(f"Nearest mapped road is {snap_a:.1f} km from "
                           f"{p_from['label']} and {snap_b:.1f} km from "
                           f"{p_to['label']}; the route starts and ends there.")
        else:
            km_by_class = RD.exposure(c_cls, c_km)
            total_km = float(c_km.sum())
            assessed_km = float(sum(km_by_class))
            high_km = km_by_class[3] + km_by_class[4]
            spots = RD.hotspots(c_cls, c_rid, c_km, c_lat, c_lon)

            k = st.columns(4)
            k[0].metric("Road at High or above", f"{high_km:,.0f} km",
                        f"{100*high_km/assessed_km:.0f}% of assessed network"
                        if assessed_km else "—")
            k[1].metric("Hotspot stretches", f"{len(spots):,}",
                        help="Continuous runs of road at High or above. This is "
                             "the unit you would send a crew to.")
            k[2].metric("Longest stretch",
                        f"{spots[0]['km']:.1f} km" if spots else "—")
            k[3].metric("Lead time", "Today" if ahead == 0 else f"+{ahead} d")

        with st.container(border=True):
            hh1, hh2 = st.columns([2.2, 0.62], vertical_alignment="center")
            with hh2:
                # Parked alongside the Forecast page's toggle — see WIP_3D.
                st.segmented_control("View", ["2D", "🔧 3D"], default="2D",
                                     key="rd_dim", label_visibility="collapsed",
                                     disabled=WIP_3D,
                                     help="3D terrain view — under development.")
                rdim = "2D"
            with hh1:
                M.map_head(f"Roads by forecast — {sel_day.strftime('%d %b')}",
                           "each ~1 km of road coloured by its own forecast")

            # Where the 3D camera opens. On a chosen route, its worst point; on
            # the whole network, today's worst stretch — in both cases the place
            # somebody actually has to make a decision about.
            if route:
                focus, zoom3d = (float(r_la[worst_i]), float(r_lo[worst_i])), 9.6
            elif spots:
                focus, zoom3d = (spots[0]["lat"], spots[0]["lon"]), 10.2
            else:
                focus, zoom3d = ((SOUTH + NORTH) / 2, (WEST + EAST) / 2), 8.0
            if rdim == "3D":
                # A chosen route gets a tight corridor around ITSELF; the network
                # view gets the corridor around every road.
                corr = (route_corridor_mask(tuple(np.round(r_lo, 4)),
                                            tuple(np.round(r_la, 4)),
                                            ROUTE_CORRIDOR_KM) if route
                        else road_corridor_mask(CORRIDOR_KM))
                pb, cb, npt, cell_m = forecast_cells(cls, stride=1, mask=corr,
                                                     alpha=255 * s.opacity)
                shell_box = st.container(height=T.MAP_H + 8, border=False,
                                         key="map_shell")
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
                    ), height=T.MAP_H)
                band = ROUTE_CORRIDOR_KM if route else CORRIDOR_KM
                st.caption(f"Forecast shown only within {band:.0f} km of the "
                           f"{'route' if route else 'road network'} — the ground "
                           f"that can actually reach it. Opens on the worst point; "
                           f"drag to fly along it.")
                legend_strip(T.CLASS_NAMES, T.CLASS_COLORS, None,
                             note="Relief exaggerated 1.25x so mid-altitude "
                                  "ridges read")
            else:
                shell_box = st.container(height=T.MAP_H + 8, border=False,
                                         key="map_shell")
                m = base_map()
                # Roads ride in their OWN feature group, drawn without the hazard
                # raster: painting both would put a red road on red ground and
                # lose the very thing this view exists to show.
                fg = overlay_group(None, districts=s.districts, inventory=False)
                if route:
                    # The rest of the network stays but faint: a route drawn with
                    # no context around it could be anywhere in the state.
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
                    fly_c = ((min(r_la) + max(r_la)) / 2,
                             (min(r_lo) + max(r_lo)) / 2)
                    span = max(max(r_la) - min(r_la), max(r_lo) - min(r_lo), 0.05)
                    fly_z = float(np.clip(np.log2(360.0 / span) - 1.4, 6, 12))
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
                    fly_c, fly_z = None, None
                with shell_box:
                    st_folium(m, height=T.MAP_H, use_container_width=True,
                              pixelated=True, returned_objects=[],
                              feature_group_to_add=fg,
                              center=fly_c, zoom=fly_z, key="rdmap")
                if route:
                    shares = [x / r_assessed if r_assessed else 0
                              for x in r_km_by_class]
                    legend_strip(T.CLASS_NAMES, T.CLASS_COLORS, shares,
                                 note=f"share of the {route_km:,.0f} km route")
                else:
                    shares = [x / assessed_km if assessed_km else 0
                              for x in km_by_class]
                    legend_strip(T.CLASS_NAMES, T.CLASS_COLORS, shares,
                                 note=f"{assessed_km:,.0f} km assessed of "
                                      f"{total_km:,.0f} km mapped")

        if route:
            st.markdown("<div class='eyebrow'>Along the route</div>",
                        unsafe_allow_html=True)
            prof = pd.DataFrame({
                "km": np.round(r_at, 2),
                "Elevation (m)": route_elevation(r_lo, r_la),
                "Outlook (1-5)": [int(cc) if cc else np.nan for cc in r_cls],
            }).set_index("km")
            pc1, pc2 = st.columns(2)
            with pc1:
                st.caption("Elevation along the route")
                st.line_chart(prof[["Elevation (m)"]], height=200, color=T.ACCENT_2)
            with pc2:
                st.caption("Forecast along the route — 5 is Very High")
                st.bar_chart(prof[["Outlook (1-5)"]], height=200, color=T.ACCENT)
            st.download_button(
                f"⬇️  Route profile, {days[di]} (CSV)",
                prof.reset_index().to_csv(index=False).encode(),
                f"route_profile_{days[di]}.csv", "text/csv")
            st.markdown(
                "<div class='caveat'>This is the shortest path over the "
                "<b>mapped</b> network, not a navigation instruction. Where "
                "OpenStreetMap coverage is patchy it can detour, and it knows "
                "nothing about one-way streets, closures or surface quality.</div>",
                unsafe_allow_html=True)
            st.stop()

        st.markdown("<div class='eyebrow'>Worst stretches</div>",
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
            st.download_button(f"⬇️  Road hotspots, {days[di]} (CSV)",
                               pd.DataFrame([
                                   {"nearest_settlement": r["Nearest settlement"],
                                    "outlook": r["Outlook"],
                                    "length_km": r["Length (km)"],
                                    "lat": r["Latitude"], "lon": r["Longitude"]}
                                   for r in [dict(zip(rdf.columns, v))
                                             for v in rdf.values]]).to_csv(index=False).encode(),
                               f"road_hotspots_{days[di]}.csv", "text/csv")
            st.caption("Ranked by severity then length, showing the top 60. "
                       "Coordinates are the midpoint of the stretch.")

        st.markdown("<div class='caveat'><b>The road layer has no names.</b> "
                    "OpenStreetMap gives us 3,489 km of trunk, primary and "
                    "secondary road for Arunachal, but no route numbers, so a "
                    "stretch is identified by the settlement nearest to it rather "
                    "than by \"NH-13, km 47\". Matching to PWD chainage would fix "
                    "that, and is the same ask that would unlock the timing "
                    "model.</div>", unsafe_allow_html=True)
        st.markdown("<div class='caveat'>Exposure is the forecast on the ground "
                    "the road crosses. It does not model the slope above the "
                    "carriageway, which is what actually lands on it — that needs "
                    "road-cut geometry we do not have.</div>",
                    unsafe_allow_html=True)

    # ═════════════════════ VIEW: SUSCEPTIBILITY ══════════════════════════════
    elif view == "Susceptibility":
        st.markdown("#### Susceptibility — the static half")

        with st.container(border=True):
            M.map_head("Statewide susceptibility surface",
                       "scroll to zoom · drag to pan")
            shell_box = st.container(height=T.MAP_H + 8, border=False,
                                     key="map_shell")
            m = base_map()
            fg = overlay_group(None if s.bare else
                               M.rgba_overlay(susceptibility_classes(),
                                              T.CLASS_COLORS),
                               districts=s.districts)
            with shell_box:
                st_folium(m, height=T.MAP_H, use_container_width=True,
                          pixelated=True, returned_objects=[],
                          feature_group_to_add=fg, key="smap")
            legend_strip(T.CLASS_NAMES, T.CLASS_COLORS,
                         note="Static — no rainfall in this layer")

        sr = MET["susceptibility"].get("success_rate", [])
        if sr:
            st.markdown("<div class='eyebrow'>How well it concentrates risk</div>",
                        unsafe_allow_html=True)
            st.dataframe(pd.DataFrame([{
                "Class": r["name"], "% of land": f"{100*r['area_frac']:.0f}%",
                "% of known landslides": f"{100*r['slide_frac']:.0f}%",
                "Concentration": f"{r['lift']:.1f}×"} for r in sr]),
                width="stretch", hide_index=True)
            st.caption("Read the bottom row: the smallest, reddest sliver of the "
                       "state contains a large share of every landslide mapped "
                       "there.")

    # ═════════════════════ VIEW: EVIDENCE ════════════════════════════════════
    elif view == "Evidence":
        st.markdown("#### The evidence base")

        k = st.columns(4)
        k[0].metric("Landslides mapped", f"{len(INVENTORY):,}" if INVENTORY else "—")
        k[1].metric("Days of rainfall", "9,555", "26 years, no gaps")
        k[2].metric("Terrain cells", "8.2 M", "100 m resolution")
        k[3].metric("Model inputs", f"{MET['susceptibility']['n_features']}")

        if INVENTORY:
            with st.container(border=True):
                M.map_head("Where the landslides are",
                           "each point is a surveyed failure, not a model output")
                shell_box = st.container(height=T.MAP_H + 8, border=False,
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
                    st_folium(m, height=T.MAP_H, use_container_width=True,
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
        st.markdown("#### Model & validation")
        su, tr = MET["susceptibility"], MET["trigger"]
        k = st.columns(4)
        k[0].metric("Where — accuracy", f"{su['auc']:.3f}", f"±{su['auc_std']:.3f}")
        k[1].metric("When — accuracy", f"{tr['auc']:.3f}", f"±{tr['auc_ci95']:.3f}")
        k[2].metric("Landslides mapped", f"{MET['labels']['polygons']:,}")
        k[3].metric("Dated events", f"{tr['n_events']}")

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

    st.markdown("<div class='app-footer'><b>SlopeSense Forecast</b>"
                "<span>Hazard = susceptibility × rainfall trigger</span></div>",
                unsafe_allow_html=True)
