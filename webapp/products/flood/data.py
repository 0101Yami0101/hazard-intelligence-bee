"""FloodSense's own bundle.

Terrain-derived layers and the catchment routing graph. The grid, boundary,
rivers, gazetteer and — importantly — the rainfall points and climatology are
NOT here: they are the shared spine, and both hazards read the same ones.
"""
from __future__ import annotations

import json

import numpy as np
import streamlit as st

from core.bundle import product_dir

SLUG = "flood"
DIR = product_dir(SLUG)


def available() -> bool:
    return (DIR / "floodprone.npz").exists()


@st.cache_data(show_spinner=False)
def load_static():
    """Flood-prone classes and index, HAND in metres, the size of the drainage
    each cell sits above, and the share of each display cell that is low."""
    fp = np.load(DIR / "floodprone.npz")
    hd = np.load(DIR / "hand.npz")
    met = json.loads((DIR / "metrics.json").read_text())
    return fp["cls"], fp["idx"], hd["hand"], hd["chan_km2"], hd["frac"], met


@st.cache_data(show_spinner=False)
def load_where():
    """The calibrated location model (WHERE) on the display grid: chance a
    spot is under water IF a flood is reported within about 5 km — the same
    layer the live forecast uses to decide what counts as low ground. Each
    display cell holds the highest 100 m value inside it. NaN outside the
    state. Returns (prob, meta)."""
    z = np.load(DIR / "floodprob.npz")["prob"]
    meta = json.loads((DIR / "floodprob.json").read_text())
    prob = np.where(z == meta["nodata"], np.nan, z / meta["scale"]).astype(np.float32)
    return prob, meta


@st.cache_data(show_spinner=False)
def catchment_points() -> int | None:
    """How many rainfall points the catchment -> point mapping was built for;
    None for a bundle from before that was recorded. The mapping holds
    positions in points.json, so a count that doesn't match the points being
    fetched means every catchment would read another place's rain."""
    c = np.load(DIR / "catchments.npz")
    return int(c["n_points"]) if "n_points" in c.files else None


@st.cache_data(show_spinner=False)
def load_catchments():
    """Basin id per cell, plus the routing graph the rain is carried along."""
    c = np.load(DIR / "catchments.npz")
    return (c["bid"], c["next_down"], c["order"], c["up_area"],
            c["sub_area"], c["rain_pt"])
