"""Loading the asset bundles.

Two kinds, and the split is the whole point of the layout:

  assets/base/       geography every product needs — the grid, the state
                     outline, districts, elevation, rivers, roads, the
                     settlement gazetteer. Loaded once, shared by all.
  assets/<product>/  one product's own model output. SlopeSense keeps its
                     susceptibility surface here; FloodSense will keep its
                     own beside it, on the same grid.

Nothing here reads a file that only one hazard cares about — that is what
`product_asset()` is for.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import streamlit as st

from core.grid import Grid

ASSETS = Path(__file__).resolve().parent.parent / "assets"
BASE = ASSETS / "base"


def product_dir(slug: str) -> Path:
    return ASSETS / slug


def _json(path: Path):
    """Optional file — the app must still run if one is absent."""
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


@dataclass(frozen=True)
class BaseLayers:
    """The geography drawn under every product's own layer."""
    boundary: dict
    districts: dict
    rivers: dict | None
    roads: dict | None
    outside: dict | None
    towns: list | None


@st.cache_data(show_spinner=False)
def load_base():
    """Grid + shared geography. Cached for the life of the deployment."""
    grid = Grid.from_json(json.loads((BASE / "grid.json").read_text()))
    layers = BaseLayers(
        boundary=_json(BASE / "boundary.geojson"),
        districts=_json(BASE / "districts.geojson"),
        rivers=_json(BASE / "rivers.geojson"),
        roads=_json(BASE / "roads.geojson"),
        outside=_json(BASE / "outside_mask.geojson"),
        towns=_json(BASE / "towns.json"))
    return grid, layers


@st.cache_data(show_spinner=False)
def load_elevation():
    """Metres per cell, on the same lattice as every forecast. None if absent —
    the 3D view degrades to flat rather than failing."""
    p = BASE / "elevation.npz"
    if not p.exists():
        return None
    z = np.load(p)["elev"].astype(np.float32)
    z[z == 65535] = np.nan
    return z


@st.cache_data(show_spinner=False)
def load_rain_spine():
    """The rainfall query points (219 since 2026-09-22) and their climatology.

    ⚠️ SHARED, not landslide-only. Both hazards are driven by the same rain:
    SlopeSense asks how unusual it is on a slope, FloodSense asks how much of
    it is falling in a catchment upstream. One set of points and one set of
    percentile breakpoints keeps the two answers consistent — and stops the
    flood module importing from the landslide one.
    """
    pts = json.loads((BASE / "points.json").read_text())
    qz = np.load(BASE / "clim_quantiles.npz")
    return pts, {k: qz[k] for k in qz.files}


def product_asset(slug: str, name: str):
    """One product's own file. Returns None when it is not there, so a product
    can ship before every layer it will eventually have."""
    p = product_dir(slug) / name
    if not p.exists():
        return None
    if p.suffix == ".npz":
        return np.load(p)
    return json.loads(p.read_text(encoding="utf-8"))


def has_bundle(slug: str) -> bool:
    """Whether a product has any data at all — what the landing page uses to
    tell a live module from one that is still being built."""
    d = product_dir(slug)
    return d.exists() and any(d.iterdir())
