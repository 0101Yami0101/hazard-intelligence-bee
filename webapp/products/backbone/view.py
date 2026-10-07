"""Data Backbone — the pipeline, shown rather than described.

The pipeline is the asset: the forecasts above it are what it can be pointed
at, and the second hazard cost a fraction of the first precisely because this
layer is shared.

⚠️ TWO RULES THIS MODULE ENFORCES ON ITSELF

1. Every figure is MEASURED from the shipped files, never typed in. A page
   whose whole subject is data integrity cannot quote a stale number — and this
   project has already had a hardcoded landslide count outlive the clip that
   changed it.

2. The DATA ITSELF IS NOT HERE, and the module says so on every page that shows
   any of it. Histograms describe shape without values, previews are ~6 km per
   pixel, and every demo record is synthetic. What IS published in full is
   provenance — source, licence, URL, fetch date — because a client auditing a
   licence needs exactly that, and none of it reveals a data value.
"""
from __future__ import annotations

import json
from datetime import date
from html import escape

import numpy as np
import pandas as pd
import streamlit as st

import core.theme as T
import products as P
from core.bundle import ASSETS, load_rain_spine, product_dir

VIEWS = [("⛁", "Pipeline"), ("📚", "Data catalogue"), ("🔬", "Layer explorer")]

# ── what the RAW file behind each derived layer looks like ──────────────────
# ⚠️ Keyed to the SOURCE, not to the layer. The 34 layers in the explorer are
# processed output — a sample of one would be a sample of our own work. What a
# reader actually wants to see is the shape of the public file we fetched, so
# a slope layer shows the elevation raster it was computed from, and a
# distance-to-road layer shows OpenStreetMap ways rather than distances.
#
# Every sample generated from this is SYNTHETIC. Raster values are drawn from
# the shipped histogram (shape only, no cell ever read); vector rows are made
# up against the real field names. Format is the point, not content.
_RAW_SPEC = {
    "dem": {"src": "Copernicus DEM GLO-30", "kind": "raster",
            "fmt": "GeoTIFF · 30 m grid · metres above sea level",
            "hist": "dem_elev_m", "dec": 0,
            "note": "Slope, curvature, wetness and flow are all computed from "
                    "this one elevation raster — none of them is fetched."},
    "soil": {"src": "SoilGrids", "kind": "raster",
             "fmt": "GeoTIFF · 250 m grid · one file per property and depth",
             "hist": None, "dec": 0,
             "note": "Resampled 250 m → 100 m onto the shared grid."},
    "landcover": {"src": "ESA WorldCover", "kind": "raster",
                  "fmt": "GeoTIFF · 10 m grid · class codes",
                  "hist": "lc_class_cat", "dec": 0,
                  "note": "10 m classes reduced to the majority class per "
                          "100 m cell."},
    "rivers": {"src": "HydroSHEDS HydroRIVERS v10", "kind": "vector",
               "fmt": "vector lines · one record per river reach",
               "fields": ["HYRIV_ID", "ORD_STRA", "UPLAND_SKM", "LENGTH_KM"],
               "note": "UPLAND_SKM — upstream drainage area — is what decides "
                       "which streams a river forecast can reach."},
    "roads": {"src": "OpenStreetMap", "kind": "vector",
              "fmt": "vector ways · one record per road segment",
              "fields": ["osm_id", "highway", "surface", "lanes"],
              "note": "No route numbers in the extract, which is why a road "
                      "stretch is named by its nearest settlement."},
    "lineaments": {"src": "APSSDI lineaments", "kind": "vector",
                   "fmt": "vector lines · one record per mapped structure",
                   "fields": ["fid", "type", "length_km"],
                   "note": "Faults and fractures — distance to the nearest one "
                           "is the model input."},
    "geology": {"src": "APSSDI geology", "kind": "vector",
                "fmt": "vector polygons · one record per mapped unit",
                "fields": ["fid", "rock_group", "lith_unit", "area_km2"],
                "note": "Polygons rasterised to the shared grid as class "
                        "codes."},
}
_VECTOR_VALUES = {
    "highway": ["trunk", "primary", "secondary", "trunk", "primary"],
    "surface": ["asphalt", "unpaved", "asphalt", "gravel", "asphalt"],
    "type": ["fault", "fracture", "shear zone", "fault", "fracture"],
    "rock_group": ["gneiss-granitoid complex", "metamorphic rocks",
                   "plutonic rocks", "unconsolidated sediments",
                   "semi-consolidated sediments"],
    "lith_unit": ["gneiss", "quartzite", "granites", "alluvium - sand & silt",
                  "phyllite"],
}


def _raw_kind(stem: str) -> str:
    if stem.startswith("soil_"):
        return "soil"
    if stem.startswith("geol_"):
        return "geology"
    return {"lc_class_cat": "landcover", "dist_river_m": "rivers",
            "dist_road_m": "roads", "dist_lineament_m": "lineaments"
            }.get(stem, "dem")   # everything else derives from the DEM

# Preview ramp — deep ink through teal to warm white. Deliberately NOT the
# hazard ramp: these thumbnails are elevation, clay content and slope, and
# borrowing green-to-red would make "high value" read as "dangerous".
RAMP = [(11, 15, 20), (17, 46, 66), (23, 92, 110), (46, 160, 150),
        (140, 214, 180), (240, 245, 220)]


@st.cache_data(show_spinner=False)
def _lut() -> np.ndarray:
    """256-colour lookup, with index 0 reserved as 'no data'."""
    anchors = np.asarray(RAMP, np.float32)
    x = np.linspace(0, len(anchors) - 1, 255)
    i0 = np.floor(x).astype(int)
    i1 = np.minimum(i0 + 1, len(anchors) - 1)
    f = (x - i0)[:, None]
    body = anchors[i0] * (1 - f) + anchors[i1] * f
    lut = np.zeros((256, 3), np.uint8)
    lut[0] = (10, 14, 19)                 # no data — the page background
    lut[1:] = body.astype(np.uint8)
    return lut


def _preview(thumb: np.ndarray) -> np.ndarray:
    return _lut()[thumb]


def _bar(df: pd.DataFrame, x: str, y: str, height: int = 240, color=None,
        sort: bool = True):
    """⚠️ `sort=True` (Streamlit's own default) re-sorts bars ALPHABETICALLY
    by the x column, discarding whatever order the DataFrame arrived in —
    caught on this exact page, where a GB-descending sort silently became
    alphabetical the moment it reached the chart. Pass `sort=False` whenever
    the caller has already put the rows in the order they want shown."""
    st.bar_chart(df.set_index(x)[[y]], height=height,
                 color=color or T.ACCENT, sort=sort)


def _draw_from_hist(info: dict, n: int, rng) -> np.ndarray:
    """n values with the same distribution as a layer, and no relation to any
    real cell — the bin is sampled by weight, the value uniformly inside it."""
    h = info.get("hist")
    if h:
        e = np.asarray(h["edges"], float)
        c = np.asarray(h["counts"], float)
        if c.sum() > 0:
            b = rng.choice(len(c), size=n, p=c / c.sum())
            return rng.uniform(e[b], e[b + 1])
    cl = info.get("classes")
    if cl:
        codes = np.array([x["code"] for x in cl], float)
        p = np.array([x["share"] for x in cl], float)
        return rng.choice(codes, size=n, p=p / p.sum())
    return np.zeros(n)


def _synth_raw(stem: str, info: dict, layers: dict, rows: int = 4,
               cols: int = 6):
    """A synthetic sample of the RAW file behind one layer.

    Rasters come back as a small block of pixel values; vectors as a handful
    of feature records with the source's real field names. Returns
    (spec, DataFrame).
    """
    kind = _raw_kind(stem)
    spec = _RAW_SPEC[kind]
    rng = np.random.default_rng(abs(hash(stem)) % (2 ** 32))

    if spec["kind"] == "raster":
        src_info = layers.get(spec["hist"] or stem, info)
        vals = _draw_from_hist(src_info, rows * cols, rng)
        dec = spec["dec"]
        grid = np.round(vals, dec).reshape(rows, cols)
        if dec == 0:
            grid = grid.astype(int)
        return spec, pd.DataFrame(
            grid, columns=[f"col {i}" for i in range(cols)],
            index=[f"row {i}" for i in range(rows)])

    out = {}
    n = 5
    for f in spec["fields"]:
        if f in _VECTOR_VALUES:
            out[f] = _VECTOR_VALUES[f][:n]
        elif f.lower().endswith("id") or f == "fid":
            out[f] = [int(rng.integers(10_000_000, 99_999_999)) for _ in range(n)]
        elif f == "lanes" or f == "ORD_STRA":
            out[f] = [int(rng.integers(1, 5)) for _ in range(n)]
        elif f == "UPLAND_SKM":
            out[f] = [round(float(10 ** rng.uniform(1, 4.3)), 1) for _ in range(n)]
        elif f == "area_km2":
            out[f] = [round(float(10 ** rng.uniform(-0.5, 2.5)), 2) for _ in range(n)]
        else:
            out[f] = [round(float(rng.uniform(0.4, 40)), 2) for _ in range(n)]
    return spec, pd.DataFrame(out)


@st.cache_data(show_spinner=False)
def _shipped_mb() -> tuple[float, int]:
    """What actually ships, measured off disk — the number the Pipeline tab's
    funnel and the What-ships tab both quote, computed once so they can never
    disagree with each other."""
    total, n = 0.0, 0
    for p in ASSETS.iterdir():
        if not p.is_dir():
            continue
        files = [f for f in p.iterdir() if f.is_file()]
        if files:
            total += sum(f.stat().st_size for f in files) / 1e6
            n += 1
    return total, n


# ── the architecture diagram ─────────────────────────────────────────────────
# Five lanes left to right, then the feedback lane underneath. Full write-up
# in docs/design/PLATFORM_ARCHITECTURE.md.
#
# ⚠️ EVERY NODE CARRIES A STATE, and "planned" is drawn differently — dashed,
# dimmed, marked with PLAN_TAG. This module's whole claim is that its
# figures are measured rather than asserted, so drawing an API or a sensor
# feed that does not exist
# as though it were live would be the one unforgivable thing on this page. The
# diagram shows the target architecture AND is honest about how much of it is
# standing, which is more use to a reader than either alone.
#
# ⚠️ _arch_lanes() still computes a real "d" (measured stat) and "t" (hover
# explanation) for every node — deliberately NOT read by _arch_diagram()
# below. The pipeline shape itself is still likely to change, and a box full
# of precise numbers reads as more settled than that is. Keeping the data
# computed, just unrendered, means turning the detail back on later is a
# one-line change in _arch_diagram(), not re-deriving it from scratch.
BUILT, PLAN = "built", "planned"
# The badge on a planned node used to spell out the word "planned" — now a
# single glyph, so the diagram reads as a picture rather than a label to
# parse. The legend at the foot of the diagram is the one place that still
# spells out what it means.
PLAN_TAG = "🔧"

_ARCH_ICON = {"sources": "⇩", "raw": "▤", "process": "✦", "hub": "▦",
              "serve": "↗"}


def _arch_lanes(cat: dict, pipe: dict, tl: dict, ship_mb: float,
                n_bundles: int, n_rain_pts: int, status: dict) -> list[dict]:
    """The five lanes, with the built nodes' numbers measured off the bundle.

    A node the flood work built is drawn as built ONLY when the bundle
    measured it (`status`: gauges being read, mornings the daily run
    completed) — an older bundle, or a checkout without those files, draws
    it as planned, which is then the truth."""
    grid = pipe.get("grid", {})
    rows = grid.get("rows") or 0
    cols = grid.get("columns") or 0
    loop, runs = status.get("loop") or {}, status.get("runs") or {}
    gauges = ([{"n": "Live river gauges", "d": f"{loop['gauges']} gauges · read "
                                               f"every run", "s": BUILT,
                "t": "CWC river levels and NWDP river flows, read fresh at every "
                     "forecast run. What a river forecast starts from, and what "
                     "it is graded against the day after."}]
              if loop.get("gauges") else [])
    daily = ([{"n": "Daily run", "d": f"{runs['n_days_run']} mornings since "
                                      f"{runs['first']}", "s": BUILT,
               "t": "Every morning: live rain and river readings in, the flood "
                    "models run, the forecast written down, yesterday's "
                    "forecasts graded."},
              {"n": "Hosted scheduling", "d": "one machine today", "s": PLAN,
               "t": "The daily run lives on one machine: a morning is missed "
                    "when it is off or a feed does not answer. The full fetch → "
                    "build → export refresh is still run by hand."}]
             if runs.get("n_days_run") else
             [{"n": "Scheduling", "d": "run by hand today", "s": PLAN,
               "t": "Fetch → build → export on a schedule, with rainfall "
                    "incremental. Needed BEFORE any public API: an API serving a "
                    "hub last refreshed by hand three weeks ago is worse than no "
                    "API, because the staleness is invisible."}])
    return [
        {"key": "sources", "name": "Sources", "nodes": [
            {"n": "External archives", "d": f"{cat['n_sources']} sources · "
                                            f"{cat['total_bytes']/1e9:.1f} GB",
             "s": BUILT,
             "t": "NASA, Copernicus, ESA, GSI, HydroSHEDS, OpenStreetMap and "
                  "the state portals."},
            {"n": "Live weather API", "d": f"{n_rain_pts} points · 7-day "
                                           f"horizon", "s": BUILT,
             "t": "Open-Meteo, polled fresh rather than archived — "
                  "rate-limited, keyless, no historical depth of its own. "
                  "The one input that changes every day, which is why this "
                  "is a forecast and not a static map."},
            *gauges,
            {"n": "Own sensors", "d": "telemetry", "s": PLAN,
             "t": "Continuous instrument feeds — a different ingest path from "
                  "a downloaded archive: drifting, prone to dropout, needing "
                  "calibration tracking."},
        ]},
        {"key": "raw", "name": "Raw hub", "nodes": [
            {"n": "Raw store", "d": f"{cat['total_files']:,} files · immutable",
             "s": BUILT,
             "t": "Never edited in place. Every fetch writes its source, "
                  "licence, URL, date and a checksum alongside the data."},
            {"n": "Source vetting", "d": "ad hoc today", "s": PLAN,
             "t": "Every new source checked against something independent "
                  "before a model may trust it. One official reference here "
                  "already failed that check outright — most of its "
                  "flooding sat on ground too steep for water to pond on. "
                  "Today that happens once, by hand, per dataset — not as a "
                  "standing gate."},
            {"n": "Partner intake", "d": "quarantined", "s": PLAN,
             "t": "Field reports and district confirmations, staged and "
                  "validated before they join authoritative data — one bad "
                  "feed contaminating the layer the forecasts are built on is "
                  "very hard to undo."},
        ]},
        {"key": "process", "name": "Processing", "nodes": [
            {"n": "Align", "d": f"{rows/1e6:.1f} M cells · "
                                f"{grid.get('cell_m', 100)} m", "s": BUILT,
             "t": f"Everything reprojected and resampled onto one grid "
                  f"({grid.get('crs', '')}). One lattice is what lets two "
                  f"hazards share a map."},
            {"n": "Feature", "d": f"{cols} columns", "s": BUILT,
             "t": "Slope, curvature, wetness, distances, soil, geology, land "
                  "cover, rainfall percentiles. Terrain is computed once; "
                  "rainfall is rebuilt daily."},
            {"n": "Model", "d": f"{tl.get('n_days', 0):,} days of rain",
             "s": BUILT,
             "t": "Where-it-fails and where-it-floods fitted on verified "
                  "evidence, scored by hiding whole regions; today's rain and "
                  "river readings scored against each place's own history."},
            *daily,
        ]},
        {"key": "hub", "name": "Processed hub", "nodes": [
            {"n": "Analysis-ready", "d": f"{rows/1e6:.1f} M × {cols}",
             "s": BUILT,
             "t": "Hazard-agnostic: the grid, the features, the rainfall "
                  "archive. Shared by every module."},
            {"n": "Model outputs", "d": f"{ship_mb:.1f} MB shipped", "s": BUILT,
             "t": "Product-specific and derived: susceptibility, flood-prone "
                  "ground, the daily forecasts."},
            {"n": "Summaries", "d": f"{n_bundles} bundles · no raw values",
             "s": BUILT,
             "t": "What this module actually shows: shapes, thumbnails and "
                  "synthetic samples, never a real cell or feature row. The "
                  "reason serving anything to an outside consumer is even "
                  "possible without redistributing the licensed data "
                  "underneath it."},
        ]},
        {"key": "serve", "name": "Serve", "nodes": (
            # ⚠️ Forecast products only — kind == "product". Data Backbone is
            # in the registry too, but it IS this diagram: the hub, the
            # processing and the shelves on its left are the Data Backbone.
            # Listing it as something the hub serves would draw the whole
            # module as a consumer of itself.
            [{"n": p.name, "d": p.hazard, "s": BUILT, "accent": p.accent,
              "t": p.tagline}
             for p in P.REGISTRY if getattr(p, "kind", "product") == "product"]
            + [{"n": "Public API", "d": "two shelves", "s": PLAN,
                "t": "Analysis-ready and model outputs as separate products "
                     "with separate terms. Read-only first; auth, rate limits "
                     "and a versioned contract from day one."},
               {"n": "Other apps", "d": "external consumers", "s": PLAN,
                "t": "Companies, startups and institutions building on the "
                     "data. Gated on the licence position of the inputs being "
                     "redistributed."}]
        )},
    ]


def _arch_diagram(lanes: list[dict], status: dict | None = None) -> str:
    """Lanes left to right with arrows between them, then the feedback lane.

    ⚠️ Name-only, on purpose — no stat line, no hover text. See the note
    above _arch_lanes() for why. `nd['n']` and `nd['s']` (built vs planned)
    are the only node fields this function reads; `nd['d']` and `nd['t']`
    exist but are not touched here.
    """
    out = ["<div class='arch'>", "<div class='arch-flow'>"]
    for i, lane in enumerate(lanes):
        out.append("<div class='arch-lane'>")
        out.append(f"<div class='arch-lname'>"
                   f"<span class='arch-lic'>{_ARCH_ICON.get(lane['key'], '•')}"
                   f"</span>{escape(lane['name'])}</div>")
        for nd in lane["nodes"]:
            planned = nd["s"] == PLAN
            accent = nd.get("accent")
            style = f" style='--nc:{accent}'" if accent else ""
            out.append(
                f"<div class='arch-node{' arch-plan' if planned else ''}"
                f"{' arch-prod' if accent else ''}'{style}>"
                f"<div class='arch-nn'>{escape(nd['n'])}"
                + (f"<span class='arch-tag'>{PLAN_TAG}</span>" if planned
                   else "")
                + "</div></div>")
        out.append("</div>")
        if i < len(lanes) - 1:
            out.append("<div class='arch-arrow'>›</div>")
    out.append("</div>")

    # The return path — the whole reason this is a loop and not a funnel.
    # Built for flood forecasts once the bundle has measured a forecast log
    # (every river forecast written down before the day, graded after it);
    # the same loop for landslide forecasts is still to build, and says so.
    if _loop_built(status):
        out.append(
            "<div class='arch-loop' style='border-style:solid'>"
            "<span class='arch-loop-arrow'>◀</span>"
            "<span class='arch-loop-name' style='color:var(--txt)'>Forecast "
            "archive → verification → outcome log</span>"
            "<span style='font-size:.72rem;color:var(--mut)'>flood forecasts"
            "</span><span style='font-size:.72rem;color:var(--dim);border:1px "
            "dashed var(--line);border-radius:999px;padding:1px 9px'>landslide "
            f"forecasts <span class='arch-tag'>{PLAN_TAG}</span></span></div>")
    else:
        out.append(
            "<div class='arch-loop arch-plan'>"
            "<span class='arch-loop-arrow'>◀</span>"
            "<span class='arch-loop-name'>Forecast archive → verification → "
            "outcome log</span>"
            f"<span class='arch-tag'>{PLAN_TAG}</span></div>")
    out.append(
        "<div class='arch-legend'>"
        "<span><i class='lg-built'></i>built</span>"
        f"<span><i class='lg-plan'></i>planned, marked {PLAN_TAG}</span>"
        "</div>")
    out.append("</div>")
    return "".join(out)


def _loop_built(status: dict | None) -> bool:
    return bool(((status or {}).get("loop") or {}).get("forecasts_logged"))


@st.cache_data(show_spinner=False)
def _live_loop(mtime: float) -> dict:
    """The forecast loop's numbers straight from today's flood snapshot.

    The daily run refreshes the flood bundle every morning but not this one
    (rebuilding it reads every raster). So the parts of the status that move
    daily — the latest issue, forecasts written down and graded, gauges
    reporting — are read from the flood module's own shipped file when it is
    there, and from this bundle's build-time copy when it is not. `mtime`
    is the cache key."""
    s = json.loads((product_dir("flood") / "live_forecast.json").read_text(encoding="utf-8"))
    tr = s.get("track_record") or {}
    return {"issued_on": s.get("issued_on"), "generated_at": s.get("generated_at"),
            "gauges": len(s.get("rivers", [])),
            "gauges_offline": sum(1 for r in s.get("rivers", []) if r.get("gauge_offline")),
            "first_issue": tr.get("first_issue"),
            "forecasts_logged": tr.get("forecasts_logged"),
            "forecasts_checked": (tr.get("checked") or {}).get("n_forecasts")}


_KEPT = {"static": "computed once", "archive": "fetched once",
         "daily": "every morning"}


def _status_section(status: dict, built: str) -> None:
    """What the platform holds today, dataset by dataset — counts, spans
    and dates the builder measured, never a data value."""
    loop = dict(status.get("loop") or {})
    snap = product_dir("flood") / "live_forecast.json"
    live = False
    if snap.exists():
        fresh = _live_loop(snap.stat().st_mtime)
        if (fresh.get("issued_on") or "") >= (loop.get("issued_on") or ""):
            loop, live = fresh, True
    runs = status.get("runs") or {}
    rows = [dict(r) for r in status.get("datasets", [])]
    for r in rows:      # the one row that moves every morning
        if r["name"] == "Flood forecast log" and loop.get("forecasts_logged"):
            r["held"] = f"{loop['forecasts_logged']:,} river forecasts"
            r["covers"] = f"{loop.get('first_issue', '')} to {loop.get('issued_on', '')}"
            r["updated"] = loop.get("issued_on", "")
            r["note"] = f"{loop.get('forecasts_checked') or 0:,} graded against the gauges so far."

    st.markdown("<div class='eyebrow' style='margin-top:26px'>What the platform holds "
                "today</div>", unsafe_allow_html=True)
    k = st.columns(4)
    k[0].metric("Datasets", f"{len(rows)}",
                f"{sum(1 for r in rows if r['kept'] == 'daily')} move every morning",
                delta_color="off")
    if loop.get("issued_on"):
        age = (date.today() - date.fromisoformat(loop["issued_on"])).days
        k[1].metric("Latest flood forecast", f"{date.fromisoformat(loop['issued_on']):%d %b}",
                    "issued today" if age <= 0 else f"{age} day{'s' if age > 1 else ''} ago",
                    delta_color="off")
        k[2].metric("Forecasts written down", f"{loop.get('forecasts_logged') or 0:,}",
                    f"{loop.get('forecasts_checked') or 0:,} graded so far", delta_color="off")
        k[3].metric("River gauges", f"{loop['gauges'] - loop['gauges_offline']} of "
                                    f"{loop['gauges']}",
                    "reporting" if not loop["gauges_offline"] else
                    f"reporting · {loop['gauges_offline']} offline", delta_color="off")

    st.dataframe(pd.DataFrame([
        {"Dataset": r["name"], "Held": r["held"], "Covers": r["covers"] or "—",
         "Last changed": r["updated"] or "—", "Kept up to date": _KEPT.get(r["kept"], r["kept"]),
         "Note": r.get("note", "")} for r in rows]),
        width="stretch", hide_index=True, height=35 * len(rows) + 38,
        column_config={"Dataset": st.column_config.TextColumn(width="medium"),
                       "Held": st.column_config.TextColumn(width="medium"),
                       "Note": st.column_config.TextColumn(width="large")})
    bits = [f"Measured when this page's bundle was built, {built}"
            + (", except the forecast figures, which are read from the latest "
               "flood forecast." if live else ".")]
    if runs.get("n_days_run"):
        missed = runs.get("missed") or []
        bits.append(f"The daily run completed on {runs['n_days_run']} mornings from "
                    f"{date.fromisoformat(runs['first']):%d %b} to "
                    f"{date.fromisoformat(runs['last']):%d %b}"
                    + (f"; no completed run on "
                       f"{', '.join(f'{date.fromisoformat(d):%d %b}' for d in missed)}."
                       if missed else ", with none missed."))
    bits.append("“Fetched once” means the archive on disk; river readings and rain "
                "are also read live at every run.")
    st.caption(" ".join(bits))

    if status.get("models"):
        st.markdown("<div class='eyebrow'>Models in use</div>", unsafe_allow_html=True)
        st.dataframe(pd.DataFrame([
            {"Model": m["name"], "Last trained": m["trained"], "What it gives": m["what"]}
            for m in status["models"]]), width="stretch", hide_index=True)


def render(shell) -> None:
    from products.backbone.data import (available, load_catalogue, load_layers,
                                        load_thumbs)

    if not available():
        st.error("**The backbone bundle is missing.** Run "
                 "`python scripts/build/build_backbone_bundle.py` to build it.")
        return

    CAT = load_catalogue()
    L = load_layers()
    LAYERS, PIPE, TL = L["layers"], L["pipeline"], L["timeline"]
    # ⚠️ L["demo_rows"] is deliberately NOT read. The bundle still carries
    # synthetic rows of the 34-column training table, but that table is our own
    # processed output and is no longer shown anywhere — the Layer explorer
    # samples the RAW public sources instead. Left in the bundle so the builder
    # need not change; simply never surfaced.
    LAB, PRIV = L["labels"], L["privacy"]
    # Absent from a bundle built before 2026-10-07: every reader of it copes.
    STATUS = L.get("status") or {}

    if "bb_view" not in st.session_state:
        st.session_state.bb_view = VIEWS[0][1]

    with st.sidebar:
        for icon, label in VIEWS:
            active = st.session_state.bb_view == label
            if st.button(f"{icon}  {label}", key=f"bbnav_{label}", width="stretch",
                         type="primary" if active else "secondary"):
                if not active:
                    st.session_state.bb_view = label
                    st.rerun()
        view = st.session_state.bb_view
        st.divider()
        st.markdown("<div class='side-label'>Bundle</div>", unsafe_allow_html=True)
        st.caption(f"Built {L['generated_utc'][:10]} · every figure measured "
                   f"from the shipped files, none typed in.")
        st.divider()
        st.caption("🔒 Summaries only. No source dataset can be rebuilt from "
                   "anything on these pages.")

    # ═════════════════════ PIPELINE ══════════════════════════════════════
    if view == "Pipeline":
        st.markdown("<div class='eyebrow'>Sources in, forecasts out, and what "
                    "comes back</div>", unsafe_allow_html=True)

        ship_mb, n_bundles = _shipped_mb()
        n_rain_pts = len(load_rain_spine()[0]["lat"])
        lanes = _arch_lanes(CAT, PIPE, TL, ship_mb, n_bundles, n_rain_pts, STATUS)
        st.markdown(_arch_diagram(lanes, STATUS), unsafe_allow_html=True)

        # The loop counts once as built (flood forecasts) when it is; what is
        # left of it (landslide forecasts) is the "+ 1" among the planned.
        built = (sum(1 for ln in lanes for nd in ln["nodes"] if nd["s"] == BUILT)
                 + _loop_built(STATUS))
        plan = sum(1 for ln in lanes for nd in ln["nodes"] if nd["s"] == PLAN)
        ratio = (CAT["total_bytes"] / 1e6 / ship_mb) if ship_mb else 0.0

        k = st.columns(4)
        k[0].metric("Source data", f"{CAT['total_bytes']/1e9:.1f} GB",
                    f"{CAT['total_files']:,} files")
        k[1].metric("Shipped", f"{ship_mb:.1f} MB",
                    f"{ratio:,.0f}× smaller · {n_bundles} bundles")
        k[2].metric("Grid", f"{PIPE['grid']['rows']/1e6:.1f} M cells",
                    f"{PIPE['grid']['cell_m']} m · {PIPE['grid']['crs']}")
        # The loop node is counted among the planned pieces — it is the one
        # that turns this from a pipeline into a pipeline that improves.
        k[3].metric("Architecture", f"{built} built", f"{plan + 1} planned",
                    delta_color="off")
        # ⚠️ Nothing about ONE dataset belongs on this tab. The rainfall
        # archive's depth, span and resolution used to sit here and made the
        # page read as half architecture, half weather — it lives on the Data
        # catalogue tab now, beside the source it describes. What does belong
        # here is the state of ALL of them at once: one row each.
        if STATUS.get("datasets"):
            _status_section(STATUS, L["generated_utc"][:10])

    # ═════════════════════ CATALOGUE ═════════════════════════════════════
    elif view == "Data catalogue":
        st.markdown("<div class='eyebrow'>Every source this platform draws "
                    "from</div>", unsafe_allow_html=True)

        k = st.columns(4)
        k[0].metric("Sources", f"{CAT['n_sources']}")
        k[1].metric("Groups", f"{len(CAT['groups'])}")
        k[2].metric("Raw data held", f"{CAT['total_bytes']/1e9:.1f} GB")
        k[3].metric("Files", f"{CAT['total_files']:,}")

        vol = pd.DataFrame([{"group": g["title"], "GB": round(g["bytes"]/1e9, 2)}
                            for g in CAT["groups"]]).sort_values("GB",
                                                                 ascending=False)
        # One group 30 times the rest put together turns the chart into a
        # single bar: it is left off and named instead.
        rest = vol["GB"].sum() - vol["GB"].max()
        big = vol.iloc[0] if (len(vol) > 1 and vol["GB"].max() > 5 * rest) else None
        _bar(vol.iloc[1:] if big is not None else vol, "group", "GB", height=170,
             sort=False)
        if big is not None:
            st.caption(f"GB held per group. {big['group']} ({big['GB']:,.0f} GB) is left "
                       f"off the chart: it would flatten every other bar.")

        # One flat table, not eleven expanders — licence terms and links are
        # deliberately left off it, so this is source, group, size and fetch
        # date only.
        rows = [{"Group": g["title"], "Source": s["source"],
                 "Files": s["n_files"], "Size (MB)": round(s["bytes"]/1e6, 1),
                 "Fetched": s["fetched"] or "—"}
                for g in CAT["groups"] for s in g["sources"]]
        st.dataframe(
            pd.DataFrame(rows).sort_values("Size (MB)", ascending=False),
            width="stretch", hide_index=True, height=340,
            column_config={"Size (MB)": st.column_config.ProgressColumn(
                # ⚠️ format= is NOT optional here. Leave it out and Streamlit
                # treats the raw MB numbers as 0..1 fractions and multiplies
                # by 100 for the label — a 828 MB source showed as "82,800%".
                "Size (MB)", format="%.1f MB", min_value=0,
                max_value=max((r["Size (MB)"] for r in rows), default=1))})

        # The one source with a TIME dimension worth showing, and the reason
        # the platform can forecast rather than just map. Here beside the
        # sources it belongs to, not on the architecture tab.
        st.markdown("<div class='eyebrow'>Rainfall archive — the depth of history "
                    "a day's rain is scored against</div>", unsafe_allow_html=True)
        yr = pd.DataFrame(TL["by_year"])
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Days on record", f"{TL['n_days']:,}")
        r2.metric("Span", f"{len(yr)} yr", f"{TL['first'][:4]}–{TL['last'][:4]}")
        r3.metric("Resolution", f"~{TL['cell_km']} km")
        r4.metric("Missing", f"{100*(TL.get('nan_frac') or 0):.0f}%")
        _bar(yr, "year", "days", height=170, color=T.ACCENT_2, sort=False)
        st.caption("Days of rainfall per year. Short bars at each end are "
                   "partial years, not gaps.")

        st.markdown("<div class='eyebrow'>Evidence the models are judged on"
                    "</div>", unsafe_allow_html=True)
        if LAB.get("sources"):
            st.dataframe(pd.DataFrame([
                {"Survey": s["name"], "Mapped features": f"{s['features']:,}",
                 "Grid cells": f"{s['cells']:,}"} for s in LAB["sources"]]),
                width="stretch", hide_index=True)
            st.caption(
                f"{LAB['positive_cells']:,} of {LAB['state_cells']:,} cells "
                f"carry a mapped landslide — a prevalence of "
                f"{100*LAB['prevalence']:.2f}%.")
        flood_ev = [r for r in STATUS.get("datasets", [])
                    if r["name"] in ("Verified flood record", "Flood reports to check",
                                     "River levels (CWC)", "River flows (NWDP)",
                                     "Radar scenes (Sentinel-1)")]
        if flood_ev:
            st.dataframe(pd.DataFrame([
                {"Flood evidence": r["name"], "Held": r["held"], "Covers": r["covers"] or "—",
                 "Note": r.get("note", "")} for r in flood_ev]),
                width="stretch", hide_index=True)
            st.caption("A flood counts as evidence only once radar, a satellite flood "
                       "map or a river gauge confirms it; reports alone are candidates.")

    # ═════════════════════ LAYER EXPLORER ════════════════════════════════
    else:
        st.markdown("#### Layer explorer")

        st.info("🔒 **Previews are ~6 km per pixel and histograms are "
                f"{PRIV['histograms']}.** You can see the shape of a layer and "
                "where it has values. You cannot read a cell, and nothing here "
                "can be turned back into the source raster.")

        names = list(LAYERS)
        titles = {k: f"{v['title']}  ·  {v['units']}" for k, v in LAYERS.items()}
        groups = sorted({v["group"] for v in LAYERS.values()})
        gsel = st.segmented_control("Group", ["all"] + groups, default="all",
                                    key="bb_group")
        gsel = gsel or "all"
        opts = [n for n in names if gsel == "all" or LAYERS[n]["group"] == gsel]
        pick = st.selectbox("Layer", opts, format_func=lambda n: titles[n],
                            key="bb_layer", label_visibility="collapsed")
        info = LAYERS[pick]
        thumbs = load_thumbs()

        c1, c2 = st.columns([1.15, 1], gap="medium")
        with c1:
            st.markdown(f"<div class='map-head'><div class='mh-dot'></div>"
                        f"<div class='mh-title'>{info['title']}</div>"
                        f"<div class='mh-note'>preview · ~6 km per pixel</div>"
                        f"</div>", unsafe_allow_html=True)
            if pick in thumbs:
                st.image(_preview(thumbs[pick]), width="stretch")
            st.caption(f"Full layer is {info['shape'][1]:,} × "
                       f"{info['shape'][0]:,} cells at 100 m; this preview is "
                       f"{thumbs[pick].shape[1]} px wide. Dark = outside the "
                       f"state or no data.")
        with c2:
            st.markdown("<div class='map-head'><div class='mh-dot'></div>"
                        "<div class='mh-title'>Distribution</div></div>",
                        unsafe_allow_html=True)
            if info["kind"] == "num":
                h = info["hist"]
                mids = [(h["edges"][i] + h["edges"][i+1]) / 2
                        for i in range(len(h["counts"]))]
                dfh = pd.DataFrame({info["units"]: [round(m, 3) for m in mids],
                                    "cells": h["counts"]})
                _bar(dfh, info["units"], "cells", height=230)
                s = info["stats"]
                st.markdown(
                    T.row("Median", f"{s['p50']:,.2f} {info['units']}")
                    + T.row("Typical range (p25–p75)",
                            f"{s['p25']:,.2f} – {s['p75']:,.2f}")
                    + T.row("Full range (p1–p99)",
                            f"{s['p1']:,.2f} – {s['p99']:,.2f}")
                    + T.row("Coverage", f"{100*info['coverage']:.1f}% of the grid"),
                    unsafe_allow_html=True)
            else:
                cl = pd.DataFrame([
                    {"class": c.get("name", str(c["code"])),
                     "share %": round(100 * c["share"], 2)}
                    for c in info["classes"]])
                _bar(cl, "class", "share %", height=230)
                st.markdown(
                    T.row("Distinct classes", f"{len(info['classes'])} shown")
                    + T.row("Coverage",
                            f"{100*info['coverage']:.1f}% of the grid"),
                    unsafe_allow_html=True)

        # ---- what the raw file behind this layer looks like ---------------- #
        spec, sample = _synth_raw(pick, info, LAYERS)
        with st.expander(f"Sample of the raw source — {spec['src']}"):
            st.caption(f"**{spec['fmt']}**  ·  {spec['note']}")
            if spec["kind"] == "raster":
                st.dataframe(sample, width="stretch")
                st.caption("A block of pixel values as they sit in the source "
                           "raster, before any reprojection or resampling.")
            else:
                st.dataframe(sample, width="stretch", hide_index=True)
                st.caption("Feature records as they arrive, with the source's "
                           "own field names.")
            st.warning(
                "🔒 **Synthetic — these are not real records.** Values are "
                "drawn from the shipped distribution, never read from a cell, "
                "and each column is drawn independently, so no row corresponds "
                "to any real place. What is faithful here is the **format**: "
                "the field names, the units and the shape of a record.")

        st.markdown("<div class='eyebrow'>Coverage across every layer</div>",
                    unsafe_allow_html=True)
        cov = pd.DataFrame([
            {"Layer": v["title"], "Units": v["units"], "Group": v["group"],
             "Coverage %": round(100 * v["coverage"], 1),
             "Cells with a value": f"{v['n_valid']:,}"}
            for v in LAYERS.values()]).sort_values("Coverage %", ascending=False)
        st.dataframe(cov, width="stretch", hide_index=True, height=340,
                     column_config={"Coverage %": st.column_config.ProgressColumn(
                         "Coverage %", min_value=0, max_value=100,
                         format="%.1f%%")})
        st.markdown(
            "<div class='caveat'>Coverage below 100% is not a fault. Soil and "
            "geology are absent under permanent ice and open water, and the "
            "model is told so rather than being handed a guessed value — a "
            "layer that quietly invents numbers where it has none is worse than "
            "one that admits the gap.</div>", unsafe_allow_html=True)

    st.markdown("<div class='app-footer'><b>Data Backbone</b>"
                "<span>One grid · one rainfall archive · one gazetteer</span>"
                "<span>Summaries only — no source data is published</span></div>",
                unsafe_allow_html=True)
