"""The map-settings block every product shares.

One basemap picker, one opacity slider, one set of layer toggles — rendered
by the shell, not by each product. Two modules with their own near-identical
sidebars is how the look drifts apart, and it is also how a visitor loses
their basemap choice by clicking between them.

Explicit widget keys on purpose: they are what carries a visitor's chosen
basemap from SlopeSense to FloodSense instead of resetting it at the door.
"""
from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

import core.theme as T


@dataclass(frozen=True)
class MapSettings:
    basemap: str
    bare: bool
    opacity: float
    roads: bool
    rivers: bool
    districts: bool
    labels: bool
    minimap: bool
    dim_outside: bool


def map_settings(*, roads_help: str = "Major roads.",
                 rivers_help: str = "Main river stems.",
                 opacity_label: str = "Overlay opacity",
                 rivers_toggle: bool = True) -> MapSettings:
    """Render the shared block into whatever container is active.

    The help strings differ by product — a road means something different to a
    landslide model than to a flood model — so they are arguments rather than
    text baked in here.

    `rivers_toggle=False` drops the Rivers switch, for a page that draws its
    own river layer (FloodSense's forecast: gauged stretches in their gauge's
    colour). `rivers` is then True: the page's rivers are on.
    """
    st.markdown("<div class='side-label'>Map settings</div>",
                unsafe_allow_html=True)
    basemap = st.radio("Basemap", list(T.BASEMAPS), horizontal=True, index=0,
                       label_visibility="collapsed", key="set_basemap")
    bare = st.toggle("🧭 Bare map", value=False, key="set_bare",
                     help="Hide every data layer — just the basemap.")
    opacity = st.slider(opacity_label, 0.0, 1.0, 0.80, 0.05,
                        disabled=bare, key="set_opacity")

    st.markdown("<div class='side-label'>Layers</div>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        roads = st.toggle("Roads", value=True, disabled=bare, key="set_roads",
                          help=roads_help)
        districts = st.toggle("Districts", value=False, disabled=bare,
                              key="set_districts")
        dim_outside = st.toggle("Dim outside", value=True, disabled=bare,
                                key="set_dim",
                                help="Shade everything beyond Arunachal, so the "
                                     "state's narrow waist near 95°E reads as "
                                     "geography rather than a stray line.")
    with c2:
        rivers = (st.toggle("Rivers", value=False, disabled=bare, key="set_rivers",
                            help=rivers_help) if rivers_toggle else True)
        labels = st.toggle("Names", value=True, disabled=bare, key="set_labels")
        minimap = st.toggle("Mini-map", value=False, disabled=bare, key="set_mini")

    if bare:
        # Bare mode wins over every individual toggle. Resolved HERE rather
        # than at each draw site so no view can half-honour it.
        opacity = 0.0
        roads = rivers = districts = minimap = dim_outside = labels = False

    return MapSettings(basemap=basemap, bare=bare, opacity=opacity, roads=roads,
                       rivers=rivers, districts=districts, labels=labels,
                       minimap=minimap, dim_outside=dim_outside)
