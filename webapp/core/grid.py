"""The lattice every raster in this app is painted on.

One grid definition, shared by every product. Landslide susceptibility, flood
depth and anything added later all land on the SAME cells, which is what lets
one map draw two hazards without resampling either of them.

Streamlit-free apart from the two caches, so the maths can be tested directly.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import streamlit as st

import core.geo as G


@dataclass(frozen=True)
class Grid:
    """A regular EPSG:4326 lattice — which is exactly why px lookup is
    arithmetic rather than a reprojection. The export reprojects once so this
    side never has to."""
    west: float
    east: float
    south: float
    north: float
    height: int
    width: int

    @classmethod
    def from_json(cls, d: dict) -> "Grid":
        return cls(west=d["west"], east=d["east"], south=d["south"],
                   north=d["north"], height=d["height"], width=d["width"])

    @property
    def shape(self) -> tuple[int, int]:
        return self.height, self.width

    @property
    def dlon(self) -> float:
        return (self.east - self.west) / self.width

    @property
    def dlat(self) -> float:
        return (self.north - self.south) / self.height

    @property
    def cell_km(self) -> float:
        """Ground width of one DISPLAY cell (~0.55 km).

        ⚠️ NOT the model resolution. The export resamples the 100 m model
        raster down for the web overlay; this only turns a cell offset into a
        distance a person can read.
        """
        mid = np.radians((self.south + self.north) / 2)
        return self.dlon * 111.32 * float(np.cos(mid))

    @property
    def bounds(self) -> list[list[float]]:
        """[[south, west], [north, east]] — the order folium wants."""
        return [[self.south, self.west], [self.north, self.east]]

    def to_px(self, lat: float, lon: float):
        """(row, col) or None when the point is off the grid."""
        if not (self.south <= lat <= self.north and self.west <= lon <= self.east):
            return None
        c = int((lon - self.west) / (self.east - self.west) * self.width)
        r = int((self.north - lat) / (self.north - self.south) * self.height)
        return (min(max(r, 0), self.height - 1),
                min(max(c, 0), self.width - 1))

    def to_px_array(self, lat: np.ndarray, lon: np.ndarray):
        """Vectorised px lookup with an in-bounds mask, for thousands of points
        at once — road pieces, route samples, gauge locations."""
        r = ((self.north - lat) / (self.north - self.south) * self.height).astype(int)
        c = ((lon - self.west) / (self.east - self.west) * self.width).astype(int)
        ok = (r >= 0) & (r < self.height) & (c >= 0) & (c < self.width)
        return r, c, ok

    def axes(self) -> tuple[np.ndarray, np.ndarray]:
        """Cell-centre longitude and latitude, as 1-D axes."""
        lon = self.west + (np.arange(self.width) + 0.5) * self.dlon
        lat = self.north - (np.arange(self.height) + 0.5) * self.dlat
        return lon, lat

    def cell_lonlat(self):
        return _cell_lonlat(self.west, self.east, self.south, self.north,
                            self.height, self.width)

    def km_per_row(self) -> float:
        return self.dlat * 111.0

    def km_per_col(self) -> float:
        return self.dlon * 98.9


@st.cache_data(show_spinner=False)
def _cell_lonlat(west, east, south, north, height, width):
    """Centre lon/lat of every cell as 2-D arrays. Built once.

    Keyed on the six primitives rather than the Grid itself: Streamlit hashes
    arguments, and plain floats are the one thing it can never get wrong.
    """
    lon = west + (np.arange(width) + 0.5) * (east - west) / width
    lat = north - (np.arange(height) + 0.5) * (north - south) / height
    return np.meshgrid(lon, lat)


def clip_to(cls: np.ndarray, mask: np.ndarray | None) -> np.ndarray:
    """Blank everything outside `mask`.

    Class 0 renders transparent, so the basemap shows through rather than the
    neighbouring district's forecast.
    """
    if mask is None:
        return cls
    out = np.zeros_like(cls)
    out[mask] = cls[mask]
    return out


def feature_by(features: list[dict], key: str, name: str):
    """The GeoJSON feature whose `properties[key]` equals `name`."""
    for f in features:
        if f["properties"].get(key) == name:
            return f
    return None


def district_raster(grid: Grid, districts: dict) -> tuple[np.ndarray, list[str]]:
    """Which district each cell is in: (ids, names), ids 1-based into names
    and 0 outside every district.

    The real outlines, drawn once. Two things read it — a district's figures
    and the clip that shows one district alone — so they cannot disagree, and
    the daily landslide log (scripts/model/landslide_forecast_log.py) reads
    the same function so the log is the screen.

    ⚠️ It replaced two things that were both wrong (2026-10-10). District
    figures were taken over each district's bounding BOX, which holds large
    parts of its neighbours (Upper Siang: 51,317 cells in its box, 25,928 in
    its outline). And the clip came from a cached polygon_mask() here whose
    cache key left the outline itself out, so it could not tell one district
    from the next — every district picked after the first was shown through
    the first one's outline. That function is gone.

    A cell on a shared border goes to the district listed first (39 cells).
    Not cached here: this module's maths stays testable without Streamlit;
    the page caches it.
    """
    lon, lat = grid.axes()
    ids = np.zeros(grid.shape, dtype=np.uint8)
    names: list[str] = []
    for f in districts.get("features", []):
        m = G.rasterize_polygon(f["geometry"], lon, lat)
        names.append(f["properties"].get("district", "—"))
        ids[m & (ids == 0)] = len(names)
    return ids, names


def disc_mask(grid: Grid, lats, lons, half_km: float) -> np.ndarray:
    """Cells within `half_km` of any of the given points.

    Stamps a disc around each point rather than measuring every cell against
    every point: the direct version for the road network is 288,000 x 4,000
    distance calculations and takes minutes.
    """
    kr, kc = grid.km_per_row(), grid.km_per_col()
    rr = max(int(round(half_km / kr)), 1)
    cc = max(int(round(half_km / kc)), 1)
    dr, dc = np.mgrid[-rr:rr + 1, -cc:cc + 1]
    disc = ((dr * kr) ** 2 + (dc * kc) ** 2) <= half_km ** 2
    m = np.zeros(grid.shape, dtype=bool)
    rows = ((grid.north - np.asarray(lats)) / (grid.north - grid.south)
            * grid.height).astype(int)
    cols = ((np.asarray(lons) - grid.west) / (grid.east - grid.west)
            * grid.width).astype(int)
    for r, c in zip(rows, cols):
        r0, r1 = max(r - rr, 0), min(r + rr + 1, grid.height)
        c0, c1 = max(c - cc, 0), min(c + cc + 1, grid.width)
        if r1 <= r0 or c1 <= c0:
            continue
        m[r0:r1, c0:c1] |= disc[r0 - (r - rr):r1 - (r - rr),
                                c0 - (c - cc):c1 - (c - cc)]
    return m
