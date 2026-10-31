"""Loading SoilSense's bundle: one folder per state under assets/erosion/."""
from __future__ import annotations

import json
from xml.sax.saxutils import escape

import numpy as np
import pandas as pd
import streamlit as st

from core.bundle import product_dir

ROOT = product_dir("erosion")

# 0 = not scored (left transparent), then slight .. very severe
CLASS_NAMES = ["Slight", "Moderate", "High", "Very high", "Severe", "Very severe"]
CLASS_RANGES = ["< 5", "5–10", "10–20", "20–40", "40–80", "> 80"]
CLASS_COLORS = ["#1a9850", "#a6d96a", "#fee08b", "#fdae61", "#f46d43", "#a50026"]


def regions() -> list[str]:
    """States with an exported bundle, in a fixed order."""
    if not ROOT.exists():
        return []
    return sorted(p.name for p in ROOT.iterdir() if (p / "meta.json").exists())


@st.cache_data(show_spinner=False)
def load(region: str) -> dict:
    d = ROOT / region
    z = np.load(d / "classes.npz")
    read = lambda n: json.loads((d / n).read_text(encoding="utf-8"))
    return {"meta": read("meta.json"),
            "classes": {k: z[k] for k in z.files if k != "bounds"},
            "bounds": z["bounds"].tolist(),
            "catchments": read("catchments.geojson"),
            "districts": read("districts.geojson"),
            "outline": read("outline.geojson"),
            "points": (pd.read_csv(d / "field_points.csv", keep_default_na=False)
                       if (d / "field_points.csv").exists() else None),
            "gpkg": next(d.glob("soilsense_*.gpkg"), None),
            "places": (_places(d / "places.csv.gz") if (d / "places.csv.gz").exists() else None),
            "treatment": (json.loads((d / "treatment.json").read_text()) if (d / "treatment.json").exists() else None),
            "change": ({k: v for k, v in np.load(d / "change.npz").items()}
                       if (d / "change.npz").exists() else None)}


# ---- field-kit files, written here so the app needs no GIS library ----------

def _coords_kml(ring) -> str:
    return " ".join(f"{x:.5f},{y:.5f}" for x, y in ring)


def _polygons(geom):
    return [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]


def _data(props: dict) -> str:
    return "<ExtendedData>" + "".join(
        f'<Data name="{escape(str(k))}"><value>{escape(str(v))}</value></Data>'
        for k, v in props.items()) + "</ExtendedData>"


def kml(fc: dict, name: str, label) -> bytes:
    """GeoJSON polygons -> KML (Google Earth, phones, any GIS)."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
           f"<name>{escape(name)}</name>",
           '<Style id="u"><LineStyle><color>ff58a4e0</color><width>1.5</width></LineStyle>'
           '<PolyStyle><fill>0</fill></PolyStyle></Style>']
    for f in fc["features"]:
        p = f["properties"]
        polys = "".join(
            "<Polygon><outerBoundaryIs><LinearRing><coordinates>" + _coords_kml(poly[0])
            + "</coordinates></LinearRing></outerBoundaryIs>"
            + "".join("<innerBoundaryIs><LinearRing><coordinates>" + _coords_kml(h)
                      + "</coordinates></LinearRing></innerBoundaryIs>" for h in poly[1:])
            + "</Polygon>" for poly in _polygons(f["geometry"]))
        out.append(f"<Placemark><name>{escape(label(p))}</name><styleUrl>#u</styleUrl>"
                   f"{_data(p)}<MultiGeometry>{polys}</MultiGeometry></Placemark>")
    out.append("</Document></kml>")
    return "\n".join(out).encode("utf-8")


def points_kml(df: pd.DataFrame, name: str) -> bytes:
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>', f"<name>{escape(name)}</name>"]
    for r in df.to_dict("records"):
        out.append(f"<Placemark><name>{escape(r['point_id'])}</name>{_data(r)}"
                   f"<Point><coordinates>{r['lon']:.5f},{r['lat']:.5f}</coordinates></Point></Placemark>")
    out.append("</Document></kml>")
    return "\n".join(out).encode("utf-8")


def points_gpx(df: pd.DataFrame, name: str) -> bytes:
    """Waypoints for hand-held GPS units and phone apps."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<gpx version="1.1" creator="SoilSense" xmlns="http://www.topografix.com/GPX/1/1">',
           f"<metadata><name>{escape(name)}</name></metadata>"]
    for r in df.to_dict("records"):
        desc = (f"Catchment #{r['catchment_rank']}, {r['district']}. {r['class']}, about "
                f"{r['est_loss_tpha']} t/ha/yr, slope {r['slope_deg']} deg. Cause: {r['main_cause']}.")
        out.append(f'<wpt lat="{r["lat"]:.5f}" lon="{r["lon"]:.5f}"><name>{escape(r["point_id"])}</name>'
                   f"<desc>{escape(desc)}</desc></wpt>")
    out.append("</gpx>")
    return "\n".join(out).encode("utf-8")


def _places(path) -> pd.DataFrame:
    """The village list; text columns blank (not NaN) where a source had nothing."""
    p = pd.read_csv(path, keep_default_na=False, na_values=[""])
    for c in ("name_as", "district", "source", "place", "bare"):
        if c in p:
            p[c] = p[c].fillna("").astype(str)
    return p
