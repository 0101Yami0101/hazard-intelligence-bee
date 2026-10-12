"""SlideSense's own bundle — the half of the data that is about landslides.

Everything here is model output or landslide evidence. The grid, boundary,
districts, elevation, rivers, roads and gazetteer are NOT here: they are
shared geography and live in assets/base/, loaded by the shell.
"""
from __future__ import annotations

import json

import numpy as np
import streamlit as st

from core.bundle import load_rain_spine, product_dir

SLUG = "landslide"
DIR = product_dir(SLUG)


@st.cache_data(show_spinner=False)
def load_model():
    """Susceptibility surface, the weather-point index, headline metrics and
    the mapped-landslide inventory.

    ⚠️ The rainfall points and climatology are NOT loaded here — they are the
    shared spine and come from core.bundle, because FloodSense reads the same
    ones. See load_rain_spine().
    """
    sus = np.load(DIR / "susceptibility.npz")["sus"]
    near = np.load(DIR / "nearest_point.npz")["near"]
    pts, quant = load_rain_spine()
    met = json.loads((DIR / "metrics.json").read_text())
    p = DIR / "landslides.json"
    inv = json.loads(p.read_text()) if p.exists() else None
    return sus, near, quant, pts, met, inv


@st.cache_data(show_spinner=False)
def load_times_usual() -> dict | None:
    """The measured "times the usual" figures behind the place card
    (scripts/model/check_landslide_times_usual.py): for each level, each band
    of the rain score and each class of ground, how many times as common
    landslides have been. None if the file is not in the bundle — the card
    then shows the level's word alone, never a made-up number."""
    p = DIR / "times_usual.json"
    return json.loads(p.read_text()) if p.exists() else None


# load_forecast now lives in core.rainfall — one cached fetch serves every
# module, so opening FloodSense after SlideSense costs no extra API call.
