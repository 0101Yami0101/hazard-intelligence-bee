"""Drawing the map — the parts that are identical whatever the hazard is.

Every product paints a class raster over the same geography with the same
controls, so the basemap, the boundary casing, the dimming mask, the legend
and the day strip all live here. What a class MEANS is the product's business;
how it gets onto the screen is not.
"""
from __future__ import annotations

from datetime import datetime

import folium
import numpy as np
import streamlit as st
from folium.plugins import Fullscreen, MiniMap
from folium.raster_layers import ImageOverlay

import core.geo as G
import core.theme as T
from core.bundle import BaseLayers
from core.grid import Grid, feature_by
from core.settings import MapSettings


def rgba_overlay(cls: np.ndarray, colors, alpha: int = 205) -> np.ndarray:
    """Class colours -> RGBA. Not-assessed stays fully TRANSPARENT so the
    basemap shows through — a grey fill would read as a real, low value."""
    out = np.zeros((*cls.shape, 4), dtype=np.uint8)
    for i, hexc in enumerate(colors, start=1):
        m = cls == i
        if m.any():
            out[m, 0] = int(hexc[1:3], 16)
            out[m, 1] = int(hexc[3:5], 16)
            out[m, 2] = int(hexc[5:7], 16)
            out[m, 3] = alpha
    return out


def base_map(grid: Grid, s: MapSettings):
    """The parts of the map that must NEVER change between reruns.

    ⚠️ This is the whole trick behind the map not snapping back to the start
    every time you touch a control. streamlit_folium identifies a map by
    hashing its generated JavaScript. Same JS -> same component -> the browser
    keeps the live Leaflet instance, with whatever the user panned and zoomed
    to. Different JS -> a brand-new component, mounted fresh at zoom_start.

    So the base map is built from FIXED arguments only — never from the
    selected day, the chosen layer, or a searched location. Everything that
    varies goes through overlay_group() and is pushed in as a feature group,
    which streamlit_folium applies to the existing map without remounting it.

    That also means the constructor's location/zoom are only ever the opening
    view. Moving the map afterwards is done with st_folium(center=, zoom=).
    """
    # Whole-number zoom only. zoomSnap/zoomDelta of 0.5 were tried here as a
    # "finer wheel steps" nicety and removed again: at a half step Leaflet does
    # not redraw, it CSS-scales what it already painted, which puts a second
    # resampling pass on top of the overlay for no real benefit.
    #
    # ⚠️ That was NOT the cause of the smeared overlay — see pixelated=True on
    # the st_folium calls for the actual fix. Recorded here because the two
    # look alike and it is an easy wrong conclusion to reach twice.
    m = folium.Map(location=list(T.MAP_OPEN_AT), zoom_start=T.MAP_OPEN_ZOOM,
                   tiles=None, control_scale=True)
    # folium.Map(min_zoom=) is a no-op when tiles=None — it only reaches the
    # default tile layer, which we skip. Leaflet's own option must be set here
    # or scroll-out is unbounded and eventually shows repeated world copies.
    m.options.update(minZoom=T.MAP_MIN_ZOOM,
                     maxBounds=[[grid.south - 1.5, grid.west - 1.5],
                                [grid.north + 1.5, grid.east + 1.5]],
                     maxBoundsViscosity=1.0, worldCopyJump=False)
    url, attr = T.BASEMAPS[s.basemap]
    folium.TileLayer(url, attr=attr, name="Base", control=False,
                     min_zoom=T.MAP_MIN_ZOOM, no_wrap=True).add_to(m)
    # The label pane must exist on the BASE map: panes are Leaflet containers
    # created at map setup, and a feature group cannot conjure one later.
    folium.map.CustomPane("labels", z_index=650).add_to(m)
    # The spotlight on a selected district (overlay_group's `focus`) is drawn
    # here: above the overlays, the lines and the markers (600), so all of
    # them go dark outside the district, and below the place names and the
    # hover tips (650), which stay readable.
    folium.map.CustomPane("spot", z_index=640).add_to(m)
    if s.labels:
        # The names are Esri's too. Under an Esri basemap they carry the SAME
        # credit as the base, which Leaflet then prints once: two different
        # credits wrapped onto a second line and covered the foot of the map.
        folium.TileLayer(T.LABEL_TILES[s.basemap],
                         attr=attr if "Esri" in attr else T.ESRI_CANVAS, name="Labels",
                         pane="labels", control=False,
                         min_zoom=T.MAP_MIN_ZOOM, no_wrap=True).add_to(m)
    Fullscreen(position="topleft").add_to(m)
    if s.minimap:
        MiniMap(toggle_display=True, minimized=True).add_to(m)
    return m


# Wider than anything the map can show, so a shade never ends on screen.
_WORLD = [[30.0, -15.0], [30.0, 70.0], [160.0, 70.0], [160.0, -15.0], [30.0, -15.0]]


def district_feature(geo: BaseLayers, sel):
    """The outline of the selected district, or None when the selection is
    a town, a coordinate or nothing."""
    if not sel or sel.get("kind") != "district" or not geo.districts:
        return None
    label = sel["label"]
    name = label[:-9] if label.endswith(" district") else label
    return feature_by(geo.districts["features"], "district", name)


def focus_view(feat):
    """(centre, zoom) that frames one district so it fills the map.

    The closest whole zoom at which the outline still fits a map 480 px wide
    and 440 px tall — the desktop map with room to spare. On a phone (about
    330 px wide) the widest districts run a little past the sides. Districts
    range from Namsai (0.3 degrees across) to Changlang (1.5), so one fixed
    zoom either cropped the big ones or lost the small ones.

    It replaced `log2(360 / span) - 1.6`, which framed every district at zoom
    6 to 8: Papum Pare came out 90 px wide on a 630 px map (2026-10-12).
    """
    pts = np.array([p for ring in G._rings(feat["geometry"]) for p in ring])
    # np.ptp(), not ndarray.ptp() — the method was removed in NumPy 2.
    d_lon = max(float(np.ptp(pts[:, 0])), 0.05)
    d_lat = max(float(np.ptp(pts[:, 1])), 0.05)
    # the middle of its box, not the mean of its vertices: a stretch of
    # finely drawn border pulls the mean towards itself
    centre = (float(pts[:, 1].min() + pts[:, 1].max()) / 2,
              float(pts[:, 0].min() + pts[:, 0].max()) / 2)
    px_per_deg = min(0.9 * 480 / d_lon,
                     0.9 * 440 * np.cos(np.radians(centre[0])) / d_lat)
    return centre, float(np.clip(np.floor(np.log2(px_per_deg * 360 / 256)), 6, 11))


def _spotlight(fg, feat) -> None:
    """Darken everything except one district, and rim it.

    One shape: the whole view with the district cut out of it. It sits in
    the `spot` pane, above every overlay, line and marker, so the rest of
    Arunachal goes as dark as the land beyond it. Not clickable: a click on
    the dark part must still reach the map and select the place under it.
    """
    g = feat["geometry"]
    outers = ([g["coordinates"][0]] if g["type"] == "Polygon"
              else [poly[0] for poly in g["coordinates"]])
    shade = {"type": "Feature", "properties": {},
             "geometry": {"type": "Polygon", "coordinates": [_WORLD] + outers}}
    folium.GeoJson(shade, name="Outside the district", pane="spot", interactive=False,
                   style_function=lambda _: {"fillColor": "#05070a", "color": "#05070a",
                                             "weight": 0, "fillOpacity": .74,
                                             "fillRule": "evenodd"}).add_to(fg)
    rim = {"type": "Feature", "properties": {}, "geometry": g}
    for ink, weight, alpha in (("#020409", 6, .85), (T.ACCENT, 2.6, .95)):
        folium.GeoJson(rim, name="Selected district", pane="spot", interactive=False,
                       style_function=lambda _, i=ink, w=weight, a=alpha: {
                           "color": i, "weight": w, "opacity": a, "fill": False}
                       ).add_to(fg)


def overlay_group(grid: Grid, s: MapSettings, geo: BaseLayers, img=None,
                  districts: bool = False, marker=None, extra=None, focus=None):
    """Everything that changes — as ONE feature group, swapped in place.

    Draw order matters and is the order things are added here: dimming mask,
    raster overlay, rivers, roads, districts, state edge, the product's own
    extras, marker.

    `extra` is a callable taking the feature group. That is the seam where a
    product adds what only it has — SlideSense drops its landslide inventory
    in there — without this function growing a branch per hazard.

    `focus` is a district's GeoJSON feature (district_feature). With one,
    that district alone stays lit: the shade over the land beyond the state
    is replaced by one over everything beyond the district.
    """
    fg = folium.FeatureGroup(name="layers")
    if s.bare:
        return fg
    if s.dim_outside and geo.outside and focus is None:
        # Arunachal pinches to a narrow neck near 95E, so its two boundary
        # lines run close together and read as a stray line through the state.
        # Dimming the outside makes "inside" unmistakable and the neck legible
        # as real geography rather than a rendering fault.
        folium.GeoJson(geo.outside, name="Outside state",
                       style_function=lambda _: {"fillColor": "#05070a",
                                                 "color": "#05070a",
                                                 "weight": 0, "fillOpacity": .80}
                       ).add_to(fg)
    if img is not None:
        ImageOverlay(img, bounds=grid.bounds, opacity=s.opacity,
                     name="Overlay").add_to(fg)
    if s.rivers and geo.rivers:
        folium.GeoJson(geo.rivers, name="Rivers",
                       style_function=lambda _: {"color": "#1d5fa8", "weight": 1.0,
                                                 "opacity": .7}).add_to(fg)
    if s.roads and geo.roads:
        ink = T.ROAD_INK[s.basemap]
        folium.GeoJson(geo.roads, name="Major roads",
                       style_function=lambda _: {"color": ink, "weight": 1.3,
                                                 "opacity": .85},
                       tooltip=folium.GeoJsonTooltip(["highway"], aliases=["Road:"])
                       ).add_to(fg)
    if districts:
        folium.GeoJson(geo.districts, name="Districts",
                       style_function=lambda _: {"color": "#9fb3c8", "weight": .9,
                                                 "fill": False, "opacity": .55},
                       tooltip=folium.GeoJsonTooltip(["district"], aliases=[""])
                       ).add_to(fg)
    # Casing first, then the bright edge on top. A single hairline over dark
    # terrain reads as a line drawn ACROSS the map; a cased edge reads as the
    # rim of a solid body, which is what stops Arunachal's Assam-facing border
    # looking like a defect.
    folium.GeoJson(geo.boundary, name="State edge",
                   style_function=lambda _: {"color": "#020409", "weight": 6,
                                             "opacity": .85, "fill": False}).add_to(fg)
    folium.GeoJson(geo.boundary, name="State",
                   style_function=lambda _: {"color": T.BOUNDARY_INK[s.basemap],
                                             "weight": 2.2, "fill": False}).add_to(fg)
    if extra is not None:
        extra(fg)
    if focus is not None:
        _spotlight(fg, focus)
    if marker:
        # Halo + pin: at zoom 11 a bare pin is easy to lose against a busy
        # hazard overlay, and this is the one thing on the map the visitor
        # came to find.
        folium.CircleMarker(marker[:2], radius=13, color=T.ACCENT, weight=2,
                            fill=True, fill_color=T.ACCENT, fill_opacity=.16,
                            tooltip=marker[2]).add_to(fg)
        folium.Marker(marker[:2], tooltip=marker[2],
                      icon=folium.Icon(color="lightblue", icon="location-dot",
                                       prefix="fa")).add_to(fg)
    return fg


def fly_to(sel, zoom, at=None):
    """center/zoom for st_folium — but ONLY when the target actually changed.

    Passing the selected location every rerun would drag the map back the
    instant someone panned away and then clicked a day button. Returning
    (None, None) leaves the live map exactly where the user put it.

    `at`: where to centre instead of the selection's own point — a district
    is centred on the middle of its outline (focus_view).
    """
    if not sel:
        return None, None
    sig = (f"{sel['lat']:.4f},{sel['lon']:.4f},{zoom},"
           f"{st.session_state.get('recentre', 0)}")
    if sig == st.session_state.get("map_target"):
        return None, None
    st.session_state.map_target = sig
    return (at or (sel["lat"], sel["lon"])), zoom


def map_head(title: str, note: str = "") -> None:
    st.markdown(f"<div class='map-head'><div class='mh-dot'></div>"
                f"<div class='mh-title'>{title}</div>"
                + (f"<div class='mh-note'>{note}</div>" if note else "")
                + "</div>", unsafe_allow_html=True)


def legend_strip(names, colors, shares=None, note: str = "",
                 bare: bool = False) -> None:
    if bare:
        st.markdown("<div class='legend-strip'><div class='lg'>🧭 Bare map mode "
                    "— data layers hidden</div><div class='lg-note'>Turn it off "
                    "in the sidebar to bring the analysis back</div></div>",
                    unsafe_allow_html=True)
        return
    chips = "".join(
        f"<div class='lg'><i style='background:{c}'></i>{n}"
        + (f"<b>{100*s:.0f}%</b>" if shares is not None else "")
        + "</div>"
        for n, c, s in zip(names, colors, shares if shares is not None else names))
    tail = f"<div class='lg-note'>{note}</div>" if note else ""
    st.markdown(f"<div class='legend-strip'>{chips}{tail}</div>",
                unsafe_allow_html=True)


def day_strip(key: str, days: list[str], fut: list[int],
              notes: list[str] | None = None) -> int:
    """Seven buttons, one per forecast day.

    ⚠️ `notes` must be a number that MEANS something at the scale it is shown
    next to. This strip used to print the statewide MAXIMUM trigger, which was
    a bug worth spelling out: the trigger is a percentile against each point's
    own history, so the maximum over the (then) 97 points is the maximum of 97
    roughly uniform draws. Its expected value is 97/98 = 0.99 on a completely
    ORDINARY day (219/220 with today's 219 points). It read as "99% chance of a landslide" and in fact carried almost no
    information about the weather at all.

    Callers must pass something scale-appropriate: the selected location's own
    outlook, or a share of land — never a maximum over many places.
    """
    if "day_i" not in st.session_state or st.session_state.day_i not in fut:
        st.session_state.day_i = fut[0]
    # keyed so the stylesheet can keep the days four to a row on a phone,
    # where Streamlit would otherwise stack them seven rows deep (theme.py)
    cols = st.container(key=f"daystrip_{key}").columns(len(fut))
    for n, (col, i) in enumerate(zip(cols, fut)):
        d = datetime.fromisoformat(days[i])
        with col:
            # ⚠️ Line 1 is the DAY, line 2 is the OUTLOOK, always — and the
            # break is a markdown hard break (two spaces then a newline),
            # which renders a real <br>.
            #
            # A bare "\n" does NOT work here: Streamlit renders a button label
            # as markdown, and in markdown a single newline collapses to a
            # space. So the old label flowed as one line and split only when
            # it happened to be too wide to fit — "Moderate" wrapped onto a
            # second line while the shorter "High" stayed on the first, and a
            # row of day buttons came out at two different heights.
            lbl = "Today" if n == 0 else d.strftime("%a")
            text = f"{lbl} {d.strftime('%d %b')}"
            if notes:
                text += "  \n" + str(notes[n])
            if st.button(text, key=f"day_{key}_{i}", width="stretch",
                         type="primary" if i == st.session_state.day_i
                         else "secondary"):
                st.session_state.day_i = i
                st.rerun()
    return st.session_state.day_i
