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

import core.theme as T
from core.bundle import BaseLayers
from core.grid import Grid
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
    m = folium.Map(location=[(grid.south + grid.north) / 2,
                             (grid.west + grid.east) / 2],
                   zoom_start=7, tiles=None, control_scale=True)
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
    if s.labels:
        folium.TileLayer(T.LABEL_TILES[s.basemap], attr=T.ESRI_CANVAS, name="Labels",
                         pane="labels", control=False,
                         min_zoom=T.MAP_MIN_ZOOM, no_wrap=True).add_to(m)
    Fullscreen(position="topleft").add_to(m)
    if s.minimap:
        MiniMap(toggle_display=True, minimized=True).add_to(m)
    return m


def overlay_group(grid: Grid, s: MapSettings, geo: BaseLayers, img=None,
                  districts: bool = False, marker=None, extra=None):
    """Everything that changes — as ONE feature group, swapped in place.

    Draw order matters and is the order things are added here: dimming mask,
    raster overlay, rivers, roads, districts, state edge, the product's own
    extras, marker.

    `extra` is a callable taking the feature group. That is the seam where a
    product adds what only it has — SlopeSense drops its landslide inventory
    in there — without this function growing a branch per hazard.
    """
    fg = folium.FeatureGroup(name="layers")
    if s.bare:
        return fg
    if s.dim_outside and geo.outside:
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


def fly_to(sel, zoom):
    """center/zoom for st_folium — but ONLY when the target actually changed.

    Passing the selected location every rerun would drag the map back the
    instant someone panned away and then clicked a day button. Returning
    (None, None) leaves the live map exactly where the user put it.
    """
    if not sel:
        return None, None
    sig = (f"{sel['lat']:.4f},{sel['lon']:.4f},{zoom},"
           f"{st.session_state.get('recentre', 0)}")
    if sig == st.session_state.get("map_target"):
        return None, None
    st.session_state.map_target = sig
    return (sel["lat"], sel["lon"]), zoom


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
    cols = st.columns(len(fut))
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
