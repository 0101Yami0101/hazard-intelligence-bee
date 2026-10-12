"""Place search + browser geolocation — Streamlit-free so it can be tested.

Two jobs:

1. Build ONE searchable index of everywhere a user might want a forecast:
   4,648 settlements, 18 districts, and any latitude/longitude they type in.
   This replaces the old "Jump to" dropdown, which only browsed towns and had
   no way to reach a specific coordinate.

2. Say whether a position the browser gave is inside the forecast area.

⚠️ Geolocation is deliberately NOT a Python dependency. The browser owns the
answer, so the request runs as a tiny component of our own
(core/geo_component, mounted by core/location.py) that hands the result back
as its value. That keeps the deploy at seven pure-Python packages, which is
what lets it run on a free host.
"""
from __future__ import annotations

import re

import numpy as np

# ── coordinate parsing ───────────────────────────────────────────────────────
# Accepts the forms people actually paste: "27.55, 94.21", "27.55 94.21",
# "27.55N 94.21E", "lat 27.55 lon 94.21". Degrees/minutes/seconds is out of
# scope — every source a user would copy from (phone, Google Maps, a GPS
# export) gives decimal degrees.
_NUM = r"[-+]?\d{1,3}(?:\.\d+)?"
_COORD = re.compile(
    rf"^\s*(?:lat\.?\s*[:=]?\s*)?({_NUM})\s*°?\s*([NnSs])?"
    rf"\s*(?:[,;/]|\s)\s*"
    rf"(?:lon\.?g?\.?\s*[:=]?\s*)?({_NUM})\s*°?\s*([EeWw])?\s*$")


def parse_coords(text: str):
    """'27.55, 94.21' -> (27.55, 94.21). None if it is not a coordinate pair.

    Returns None rather than raising, because this runs on every keystroke's
    worth of text the user commits — a non-match simply means "they typed a
    place name", which is the normal case.
    """
    if not text:
        return None
    m = _COORD.match(text.replace("°", " ").strip())
    if not m:
        return None
    a, ha, b, hb = m.groups()
    lat, lon = float(a), float(b)
    if ha and ha.upper() == "S":
        lat = -abs(lat)
    if hb and hb.upper() == "W":
        lon = -abs(lon)
    # Tolerate lon-first input (some exports write x,y). Only swap when the
    # first value cannot be a latitude and the second can — never guess.
    if abs(lat) > 90 and abs(lon) <= 90:
        lat, lon = lon, lat
    if abs(lat) > 90 or abs(lon) > 180:
        return None
    return lat, lon


# ── place index ──────────────────────────────────────────────────────────────
# ⚠️ The shipped gazetteer is APSSDI's SETTLEMENTS layer — 4,648 villages. It is
# excellent at village level and has a real hole at the top: Itanagar, the state
# capital, is not in it, and neither are Yingkiong, Yupia, Koloriang, Longding
# or Ziro town itself (only "Old Ziro" and "Ziro Point"). A search box that
# cannot find the capital is broken, so the capital and the district
# headquarters are named here explicitly.
#
# Only added when the gazetteer has no entry of the same name, so the ones it
# DOES carry (Tawang, Pasighat, Tezu…) keep their surveyed coordinates rather
# than being overwritten by a rounded one.
ANCHORS = [
    ("Itanagar", 27.0844, 93.6053), ("Naharlagun", 27.1039, 93.6953),
    ("Yupia", 27.1500, 93.7500), ("Doimukh", 27.1583, 93.7500),
    ("Ziro", 27.5450, 93.8300), ("Yingkiong", 28.6333, 95.0167),
    ("Koloriang", 27.8833, 93.1000), ("Longding", 26.8833, 95.3333),
    ("Along", 28.1667, 94.8000), ("Mechuka", 28.6000, 94.1500),
    ("Tuting", 28.9500, 95.0000), ("Miao", 27.5000, 96.2167),
    ("Bhalukpong", 27.0167, 92.6333), ("Deomali", 27.1500, 95.4000),
    ("Palin", 27.7167, 93.4833), ("Dirang", 27.3667, 92.2500),
    ("Roing", 28.1500, 95.8333), ("Anini", 28.8000, 95.9000),
    ("Hawai", 27.9500, 96.9167), ("Changlang", 27.1333, 95.7333),
    ("Basar", 27.9833, 94.6833), ("Jairampur", 27.3333, 96.0000),
]


def _ring_centre(geom):
    """Mean of a district's outer ring vertices — good enough to fly the map to."""
    polys = (geom["coordinates"] if geom["type"] == "MultiPolygon"
             else [geom["coordinates"]])
    xs, ys = [], []
    for p in polys:
        for x, y in p[0]:
            xs.append(x)
            ys.append(y)
    if not xs:
        return None
    return sum(ys) / len(ys), sum(xs) / len(xs)


SAME_PLACE_KM = 12.0        # closer than this and it is the same settlement


def _km(lat1, lon1, lat2, lon2) -> float:
    """Flat-earth kilometres. Over a 5-degree state the error is metres."""
    return (((lat1 - lat2) * 110.6) ** 2 + ((lon1 - lon2) * 98.9) ** 2) ** 0.5


def build_places(towns, districts) -> list[dict]:
    """One flat, searchable list: districts, then the anchors, then every village.

    180 of the 4,648 settlement names are not unique (three separate villages
    are called Roing). Duplicates get their coordinates appended so both entries
    stay reachable — silently dropping one would make a real village
    unfindable.

    ⚠️ An anchor is suppressed only when the gazetteer already holds a place of
    that name NEARBY. Matching on name alone was wrong and hid the district
    headquarters at Roing behind three unrelated villages 100 km away.
    """
    out: list[dict] = []
    for f in (districts or {}).get("features", []):
        c = _ring_centre(f["geometry"])
        if c:
            out.append({"label": f"{f['properties'].get('district', '?')} district",
                        "lat": c[0], "lon": c[1], "kind": "district"})
    out.sort(key=lambda d: d["label"])

    towns = list(towns or [])
    counts: dict[str, int] = {}
    for t in towns:
        counts[t["n"]] = counts.get(t["n"], 0) + 1

    villages, used = [], {p["label"] for p in out}
    for t in sorted(towns, key=lambda t: t["n"]):
        label = t["n"]
        if counts[label] > 1:
            label = f"{label}  ({t['y']:.2f}°N {t['x']:.2f}°E)"
        # Six pairs share a name AND round to the same 2 dp — records ~300 m
        # apart for what is really one village. Two identical rows in a
        # dropdown is a bug however it arose, so break the tie outright.
        if label in used:
            n = 2
            while f"{label} #{n}" in used:
                n += 1
            label = f"{label} #{n}"
        used.add(label)
        villages.append({"label": label, "lat": t["y"], "lon": t["x"],
                         "kind": "town"})

    anchors = []
    for name, lat, lon in ANCHORS:
        if any(t["n"] == name and _km(lat, lon, t["y"], t["x"]) <= SAME_PLACE_KM
               for t in towns):
            continue
        # The plain name can still be taken by an unrelated village elsewhere.
        label = name if name not in used else f"{name} (town)"
        used.add(label)
        anchors.append({"label": label, "lat": lat, "lon": lon, "kind": "town"})
    anchors.sort(key=lambda d: d["label"])

    return out + anchors + villages


def resolve(query: str, places: list[dict], index: dict | None = None):
    """Turn whatever is in the search box into a place. Coordinates win.

    Order matters: a user who typed digits meant a coordinate, so that is tried
    before the name index. Anything unrecognised returns None and the caller
    shows the search prompt rather than a wrong location.
    """
    if not query or query == PROMPT:
        return None
    c = parse_coords(query)
    if c:
        return {"label": f"{c[0]:.4f}°N, {c[1]:.4f}°E", "lat": c[0], "lon": c[1],
                "kind": "coords"}
    idx = index if index is not None else {p["label"]: p for p in places}
    return idx.get(query)


PROMPT = "Search a town, district, or type coordinates…"


def nearest_place(lat: float, lon: float, places: list[dict], kind="town"):
    """Closest named place, for labelling a raw coordinate.

    Flat-earth distance on purpose: over Arunachal's ~5° span the error is far
    below the spacing between villages, and this runs over 4,648 candidates on
    every rerun.
    """
    best, bd = None, 1e18
    for p in places:
        if p["kind"] != kind:
            continue
        d = (p["lat"] - lat) ** 2 + ((p["lon"] - lon) * 0.89) ** 2
        if d < bd:
            best, bd = p, d
    if best is None:
        return None, None
    return best, (bd ** 0.5) * 111.0


def in_area(lat: float, lon: float, g: dict, pad: float = 0.0) -> bool:
    """Is this point inside the forecast grid? Used to catch the common case of
    a visitor who is simply not in Arunachal — they get told so, plainly,
    instead of a forecast for the nearest edge pixel."""
    return (g["south"] - pad <= lat <= g["north"] + pad
            and g["west"] - pad <= lon <= g["east"] + pad)


# ── polygon -> grid mask ─────────────────────────────────────────────────────
def _rings(geom):
    """Every ring of a Polygon or MultiPolygon, outer and holes alike."""
    t, c = geom["type"], geom["coordinates"]
    if t == "Polygon":
        return list(c)
    if t == "MultiPolygon":
        return [r for poly in c for r in poly]
    return []


def rasterize_polygon(geom, lons, lats):
    """Which grid cells fall inside a polygon. Returns an (H, W) bool array.

    `lons` and `lats` are the 1-D arrays of cell-centre coordinates.

    Even-odd ray casting, vectorised over the grid: for each edge, flip the
    state of every cell whose westward ray crosses it. XOR over ALL rings means
    holes fall out for free — a cell inside both an outer ring and a hole gets
    flipped twice and ends up outside.

    ⚠️ Restricted to the polygon's bounding box first. Arunachal's districts are
    a twentieth of the state each, so testing the whole 596x1227 grid against
    every edge would be ~20x the work for the same answer.

    Written by hand rather than pulled from rasterio or shapely on purpose:
    those are the heavy geospatial dependencies this app exists without, and at
    216 vertices for the largest district the maths is a dozen lines.
    """
    H, W = len(lats), len(lons)
    out = np.zeros((H, W), dtype=bool)
    rings = [np.asarray(r, dtype="float64") for r in _rings(geom)]
    rings = [r for r in rings if len(r) >= 3]
    if not rings:
        return out

    allpts = np.vstack(rings)
    # Grid rows run north to south, so the row window is found from the top.
    c0 = int(np.searchsorted(lons, allpts[:, 0].min()) - 1)
    c1 = int(np.searchsorted(lons, allpts[:, 0].max()) + 1)
    r0 = int(np.searchsorted(-lats, -allpts[:, 1].max()) - 1)
    r1 = int(np.searchsorted(-lats, -allpts[:, 1].min()) + 1)
    c0, c1 = max(c0, 0), min(c1, W)
    r0, r1 = max(r0, 0), min(r1, H)
    if c1 <= c0 or r1 <= r0:
        return out

    X, Y = np.meshgrid(lons[c0:c1], lats[r0:r1])
    inside = np.zeros(X.shape, dtype=bool)
    for r in rings:
        x1, y1 = r[:-1, 0], r[:-1, 1]
        x2, y2 = r[1:, 0], r[1:, 1]
        for a, b, c, d in zip(x1, y1, x2, y2):
            if b == d:                       # horizontal edge: no crossing
                continue
            straddles = (b > Y) != (d > Y)
            if not straddles.any():
                continue
            xint = a + (Y - b) * (c - a) / (d - b)
            inside ^= straddles & (X < xint)
    out[r0:r1, c0:c1] = inside
    return out
