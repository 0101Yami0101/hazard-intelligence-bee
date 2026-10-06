"""FloodSense — the live, model-based forecast screen.

Reads assets/flood/live_forecast.json, written every morning by
scripts/model/flood_forecast_live.py (scheduled 08:30). The models behind it
need scikit-learn and 100 m rasters, which this free-hosted app deliberately
does not carry, so there the page shows the latest issued snapshot and says
how old it is. Run locally beside the full project, it can also run the real
models on demand ("Run now", `--no-log`: the screen refreshes, the track
record keeps the scheduled 08:30 issue).

LAYOUT — the dashboard makeover of 2026-09-28, after the user's reference
mock-up: minimum text, maximum visuals, every explanation behind an ⓘ or a
badge's hover.

    header      title, when it was issued, place search, run now
    key         the kinds of number, as badges (hover for what each means)
    KPI strip   statewide: outlook, areas at 10%+, rivers, gauges
    main row    selected place | map | 7-day outlook + conditions
    below       what changed · needs attention · track record
    rivers      one gauge's graph | every gauge x every day (click to open)
    folded      all-rivers table, flood report, how to read

THE KINDS OF NUMBER — each wears its badge wherever it appears, so a checked
forecast can never be mistaken for an approximate one:

    FORECAST  ✔  a gauged river's chance of reaching its line that day —
                 checked daily against the gauge. The strongest number here.
    OUTLOOK   ≈  chance of a recorded flood within ~10 km of a place, each
                 day and over 7 days. APPROXIMATE: it failed its
                 pre-registered calibration test (the flood record's own rate
                 moved ~2x between recent years) and is shown by the user's
                 decision of 2026-09-27 with the measured error beside it.
    ESTIMATE  ◆  chance a spot is under water IF a flood comes nearby (the
                 location model) — a property of the ground, not of a day.
    MEASURED  ●  a real gauge reading.
    INPUT     ☂  rain and soil wetness — what feeds the forecast.
    RECORD    ◷  floods confirmed in the past.

They are never multiplied together on screen. "Times normal" is still
computed and logged by the daily run, but not shown: it read like the rain
being handed back to the user (docs/design/FLOOD_SCREEN_PLAN.md).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date, datetime

import altair as alt
import folium
import numpy as np
import pandas as pd
import streamlit as st
from branca.element import Html
from folium.utilities import escape_backticks
from streamlit_folium import st_folium

import core.geo as G
import core.mapping as M
import core.theme as T
from products.flood.data import DIR
# the look every FloodSense page shares (badges, tiles, the stylesheet, the
# river layer) lives in ui.py since 2026-09-29
from products.flood.ui import (FS_CSS, MAP_H, RIVER_OTHER, RIVER_QUIET, TIERS,
                               _catchment_of, _clean, _dist, _draw_rivers, _esc, _i,
                               _km, _river_segments, _row, _sec, _tile, _tiles,
                               _upstream, badge, main_row)

SNAPSHOT = DIR / "live_forecast.json"

# Running locally, beside the full project, the page can run the real models
# itself (scikit-learn, rasterio and the model files are all there). On the
# free host none of that exists, and the page only shows the snapshot.
PROJECT = DIR.parents[2]
PIPELINE = PROJECT / "scripts" / "model" / "flood_forecast_live.py"


def can_run_models() -> bool:
    import importlib.util
    return (PIPELINE.exists() and (PROJECT / "models" / "flood_forecast" / "day_model.pkl").exists()
            and all(importlib.util.find_spec(m) for m in ("sklearn", "rasterio")))


def run_models() -> bool:
    """Run the forecast now (no track-record write) and stream its progress.
    A subprocess, not an import: the pipeline has its own module names and
    paths, and a fresh process always runs the current code."""
    import os
    import subprocess
    import sys
    env = dict(os.environ, PYTHONUTF8="1", LOKY_MAX_CPU_COUNT="4")
    with st.status("Running the flood models on live rain and river gauges…",
                   expanded=True) as box:
        proc = subprocess.Popen([sys.executable, str(PIPELINE), "--no-log"], cwd=PROJECT,
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
        for line in proc.stdout:
            line = line.rstrip()
            if line.strip() and not any(x in line for x in ("Warning", "warn(", "WARNING",
                                                            "[clean]", "Traceback (most")):
                box.write(line)
        ok = proc.wait() == 0
        box.update(label="Forecast updated." if ok else "The run failed — see the lines above.",
                   state="complete" if ok else "error", expanded=not ok)
    return ok


# One chance scale for every number on the screen — places and rivers alike.
# The edges are the river models' existing band edges (2/5/10/25%), so the
# logged band codes are unchanged; only the words shown are. The old words
# (Watch/Alert/Warning/Danger) are gone: "Danger" for a 25% chance of
# reaching the river's DANGER LEVEL said the same word for two things. The
# level words below never use "warning" or "danger" for the same reason.
CHANCE_CUTS = np.array([0.02, 0.05, 0.10, 0.25], dtype=np.float32)
CHANCE_NAMES = ["under 2%", "2–5%", "5–10%", "10–25%", "25%+"]
CHANCE_WORDS = ["Very low", "Low", "Moderate", "Elevated", "High"]
# Grey while quiet, warm colours only once a chance is worth noticing.
CHANCE_COLORS = ["#5b6573", "#fee08b", "#fdae61", "#f46d43", "#a50026"]
# The same levels as TEXT on the dark panels (the fills above are too dark,
# or too pale, to read as type), and the ink that reads ON each fill.
CHANCE_TEXT = ["#b8c4d2", "#fee08b", "#fdae61", "#f46d43", "#ff5a73"]
CHANCE_INK = ["#e5edf5", "#1a1a1a", "#1a1a1a", "#ffffff", "#ffffff"]
# Only ground the location model says water can reach if a flood comes.
FLOODABLE_MIN = 0.10
# Days 4-7 ride on forecast rain, which is weak that far ahead in mountains.
SURE_DAYS = 3













def _chance_class(p) -> np.ndarray:
    return np.digitize(np.asarray(p, np.float32), CHANCE_CUTS)


def _band(p) -> int:
    return int(_chance_class(0.0 if p is None or not np.isfinite(p) else p))


def _pct(p) -> str:
    """One format for every chance in a sentence. Never 0% or 100%: the
    record behind these numbers is too thin to promise either."""
    if p is None or not np.isfinite(p):
        return "—"
    if p < 0.001:
        return "under 0.1%"
    if p >= 0.95:
        return "over 95%"
    return f"{100*p:.1f}%" if p < 0.10 else f"{100*p:.0f}%"


def _pct_short(p) -> str:
    """The same, as a headline number."""
    if p is None or not np.isfinite(p):
        return "—"
    if p < 0.001:
        return "<0.1%"
    if p >= 0.95:
        return ">95%"
    return f"{100*p:.1f}%" if p < 0.10 else f"{100*p:.0f}%"


def _where_str(w: float) -> str:
    """The "if a flood comes" chance as shown: capped at "20%+". Inside
    Arunachal the top ranges came true about half as often as they say, and a
    terrain correction did not hold up (Gate B), so no finer number is shown
    above 20%. Under 2% reads "<2%" — the map leaves that ground blank, and
    the record is too thin to say "0%"."""
    return "20%+" if w >= 0.20 else "<2%" if w < 0.02 else f"{100*w:.0f}%"


def _where_color(w: float) -> str:
    return "#9df0de" if w >= 0.20 else "#2bb3ad" if w >= 0.05 else "#7aa8a6"


def _checked_note(w: float, top: list[dict]) -> str:
    """The checked rate for the range this chance falls in, inside Arunachal —
    read from floodprob.json, never typed."""
    for b in top:
        if b["p_lo"] <= w < b["p_hi"] or (b is top[-1] and w >= b["p_lo"]):
            return (f"In past checks inside Arunachal, spots given "
                    f"{100*b['p_lo']:.0f}–{100*b['p_hi']:.0f}% went under water about "
                    f"{100*b['happened']:.0f}% of the time when a flood came.")
    return ""










def _chip(p: float) -> str:
    k = _band(p)
    return (f"<span class='fs-chip' style='--c:{CHANCE_COLORS[k]};--k:{CHANCE_INK[k]}'>"
            f"{_pct_short(p)}</span>")


def _move(a0: float, a1: float) -> str:
    """was → now, with an arrow: warm up, cool down."""
    arrow = ("<span class='fs-up'>▲</span>" if a1 > a0 * 1.05 + 1e-9 else
             "<span class='fs-dn'>▼</span>" if a1 < a0 * 0.95 - 1e-9 else
             "<span class='fs-eq'>=</span>")
    return (f"<span class='fs-was'>{_pct_short(a0)}</span> → "
            f"<b style='color:{CHANCE_TEXT[_band(a1)]}'>{_pct_short(a1)}</b> {arrow}")


def _day_label(d: str) -> str:
    dd = datetime.fromisoformat(d).date()
    return "Today" if dd == date.today() else dd.strftime("%a %d %b")


def _day_short(d: str) -> str:
    dd = datetime.fromisoformat(d).date()
    return "Today" if dd == date.today() else dd.strftime("%a %d")


def _when(days: list[str], period: int) -> str:
    if period < 0:
        return (f"Next 7 days · {datetime.fromisoformat(days[0]):%d %b} – "
                f"{datetime.fromisoformat(days[-1]):%d %b}")
    return datetime.fromisoformat(days[period]).strftime("%A %d %b")








# ── the snapshot and its lookups ─────────────────────────────────────────────
def available() -> bool:
    return SNAPSHOT.exists() and (DIR / "floodprob.npz").exists()


@st.cache_data(show_spinner=False)
def _load(mtime: float):
    snap = json.loads(SNAPSHOT.read_text())
    z = np.load(DIR / "floodprob.npz")["prob"]
    meta = json.loads((DIR / "floodprob.json").read_text())
    prob = np.where(z == meta["nodata"], np.nan, z / meta["scale"]).astype(np.float32)
    return snap, prob, meta


@st.cache_data(show_spinner=False)
def _pixel_slot(mtime: float, west, north, dlon, dlat, h, w):
    """Display pixel -> column of the snapshot's per-place arrays, -1 if none."""
    snap, _, _ = _load(mtime)
    L = snap["lattice"]
    lat = north - (np.arange(h) + 0.5) * dlat
    lon = west + (np.arange(w) + 0.5) * dlon
    r = np.rint((L["lat_max"] - lat) / L["deg"]).astype(int)[:, None]
    c = np.rint((lon - L["lon_min"]) / L["deg"]).astype(int)[None, :]
    ok = (r >= 0) & (r < L["nlat"]) & (c >= 0) & (c < L["nlon"])
    k = np.where(ok, r * L["nlon"] + c, -1)
    slot = np.full(L["nlat"] * L["nlon"], -1, dtype=np.int32)
    slot[np.asarray(snap["cells"])] = np.arange(len(snap["cells"]))
    return np.where(k >= 0, slot[np.clip(k, 0, None)], -1)


@st.cache_data(show_spinner=False)
def _centres(mtime: float):
    """(lat, lon) of each snapshot place — the centre of its ~10 km rain cell."""
    snap, _, _ = _load(mtime)
    L = snap["lattice"]
    r, c = np.divmod(np.asarray(snap["cells"]), L["nlon"])
    return L["lat_max"] - r * L["deg"], L["lon_min"] + c * L["deg"]


@st.cache_data(show_spinner=False)
def _town_index(mtime: float, n: int, _places):
    """Every settlement's position, gazetteer label and snapshot place
    (-1 when its ~10 km cell has no ground a flood can reach)."""
    snap, _, _ = _load(mtime)
    L = snap["lattice"]
    pos = {int(c): i for i, c in enumerate(snap["cells"])}
    tw = [p for p in _places if p["kind"] == "town"]
    lat = np.array([p["lat"] for p in tw], np.float64)
    lon = np.array([p["lon"] for p in tw], np.float64)
    r = np.rint((L["lat_max"] - lat) / L["deg"]).astype(int)
    c = np.rint((lon - L["lon_min"]) / L["deg"]).astype(int)
    ok = (r >= 0) & (r < L["nlat"]) & (c >= 0) & (c < L["nlon"])
    k = np.where(ok, r * L["nlon"] + c, -1)
    slot = np.array([pos.get(int(x), -1) if x >= 0 else -1 for x in k], np.int32)
    return lat, lon, slot, [p["label"] for p in tw]


def _area_name(j: int, cen, towns) -> tuple[str, str, float, float]:
    """A name for snapshot place j: (shown name, what to put in the search
    box to select it, lat, lon to label). The settlement nearest the cell's
    centre among those INSIDE the cell, so selecting it shows the same
    number; else "near <nearest settlement>", selected by coordinates."""
    lat, lon, slot, labels = towns
    clat, clon = float(cen[0][j]), float(cen[1][j])
    inside = np.flatnonzero(slot == j)
    if inside.size:
        d = (lat[inside] - clat) ** 2 + ((lon[inside] - clon) * 0.89) ** 2
        t = int(inside[np.argmin(d)])
        return _clean(labels[t]), labels[t], float(lat[t]), float(lon[t])
    d = (lat - clat) ** 2 + ((lon - clon) * 0.89) ** 2
    t = int(np.argmin(d))
    return f"near {_clean(labels[t])}", f"{clat:.4f}, {clon:.4f}", clat, clon


def _area_classes(chance: np.ndarray, slot: np.ndarray, prob: np.ndarray) -> np.ndarray:
    """Low ground coloured by its place's near-here chance (1..5); 0 = blank."""
    out = np.zeros(slot.shape, np.uint8)
    ok = (slot >= 0) & (np.nan_to_num(prob) >= FLOODABLE_MIN)
    out[ok] = (_chance_class(chance[slot[ok]]) + 1).astype(np.uint8)
    return out


def _place(sel, grid, slot, prob):
    """(row, col, place slot, chance-if-a-flood-comes, nearest low ground) for
    the selected place, or None when it is off the mapped grid."""
    if not sel:
        return None
    px = grid.to_px(sel["lat"], sel["lon"])
    if px is None:
        return None
    r, c = px
    w = float(prob[r, c]) if np.isfinite(prob[r, c]) else 0.0
    return r, c, int(slot[r, c]), w, _nearest_floodable(prob, r, c, grid.cell_km)


def _nearest_floodable(prob, r, c, cell_km, max_rings: int = 20):
    """(km, chance, row, col) of the nearest ground a flood can reach, within
    ~10 km. A town often sits on a terrace just above its river — Pasighat
    reads 0.3% while the Siang bank 1 km away reads 28% — and "unlikely here"
    without "but the river bank next door is not" would mislead."""
    h, w_ = prob.shape
    for k in range(1, max_rings + 1):
        r0, r1, c0, c1 = max(r - k, 0), min(r + k + 1, h), max(c - k, 0), min(c + k + 1, w_)
        sub = np.nan_to_num(prob[r0:r1, c0:c1])
        hit = np.argwhere(sub >= FLOODABLE_MIN)
        if hit.size:
            d = np.hypot(hit[:, 0] + r0 - r, hit[:, 1] + c0 - c)
            j = int(np.argmin(d))
            return (float(d[j] * cell_km), float(sub[hit[j, 0], hit[j, 1]]),
                    int(hit[j, 0] + r0), int(hit[j, 1] + c0))
    return None


@st.cache_data(show_spinner=False)
def _gauge_assets(shape: tuple):
    """The static gauge assets: which gauge is on each display cell's river
    (build_gauge_link.py) and the lines each gauge's graph draws
    (build_gauge_levels.py), and where each gauge sits on the map's rivers
    ([lat, lon], None when no river of its size is near its published spot).
    Missing or mis-shaped files -> no link."""
    link, codes, placed = None, [], {}
    if (DIR / "gauge_link.json").exists():
        gj = json.loads((DIR / "gauge_link.json").read_text())
        placed = {c: p.get("placed") for c, p in gj.get("per_gauge", {}).items() if "placed" in p}
        if (DIR / "gauge_link.npz").exists():
            z = np.load(DIR / "gauge_link.npz")
            if tuple(z["gauge"].shape) == tuple(shape):
                link = (z["gauge"], z["relation"], z["km10"],
                        z["river"] if "river" in z.files else None)
                codes = gj["codes"]
    levels = (json.loads((DIR / "gauge_levels.json").read_text())
              if (DIR / "gauge_levels.json").exists() else {})
    return link, codes, levels, placed


def _own_gauge(pl, link, codes):
    """(code, relation, km along the river, via_km) for the gauge on this
    place's own river — looked up at the spot, or, when the spot is raised
    ground with no gauge of its own, at its nearest low ground (via_km = how
    far that is; the screen says so). None when neither has a gauge on its
    river (build_gauge_link.py has the rule)."""
    if pl is None or link is None:
        return None
    r, c, _, w, near = pl
    g, rel, km10 = link[:3]
    if g[r, c] >= 0:
        return codes[int(g[r, c])], int(rel[r, c]), float(km10[r, c]) / 10, None
    if w < FLOODABLE_MIN and near is not None and g[near[2], near[3]] >= 0:
        rr, cc = near[2], near[3]
        return codes[int(g[rr, cc])], int(rel[rr, cc]), float(km10[rr, cc]) / 10, near[0]
    return None


def _river_at(pl, link) -> str | None:
    """Why a place has no gauge: "here" = a river runs beside this spot,
    "near" = only beside its nearest low ground, None = beside no river a
    flood can come from (or no river data)."""
    if pl is None or link is None or link[3] is None:
        return None
    r, c, _, w, near = pl
    if link[3][r, c]:
        return "here"
    if w < FLOODABLE_MIN and near is not None and link[3][near[2], near[3]]:
        return "near"
    return None


def _river_p(xs: dict) -> float:
    return max(x["p"] for x in xs.values())


def _error_line(nh: dict) -> str:
    """The measured error, in words — read from the snapshot, never typed."""
    m = nh.get("measured_error")
    if not m:
        return ""
    return (f"In past checks, in the ranges where most floods fell, the number that "
            f"really happened was between {m['happened_over_said_low']:.1f}× and "
            f"{m['happened_over_said_high']:.0f}× what it said.{high_said_more(m)} "
            f"It is best at telling "
            f"riskier places and weeks from quieter ones — right about "
            f"{100*m['ranking_auc']:.0f} times in 100. Days 4–7 rest on rain forecasts "
            "that are less reliable that far ahead.")


def high_said_more(m: dict | None) -> str:
    """One sentence, when measured: at its highest numbers, where few floods
    fell, the outlook said MORE than happened. Without it, the error range
    (ranges with 10+ floods only) reads as "it always says too little"
    (near_here.fit, docs/design/OLDER_FLOODS_TEST.md §5c). "" otherwise."""
    h = (m or {}).get("high_ranges_said_more")
    if not h:
        return ""
    return (f" At its highest numbers ({h['from_pct']:g}% and up), where few floods fell, "
            f"it said more than happened — about {h['said_pct']:.0f}% said, "
            f"{h['happened_pct']:.0f}% happened.")


def learned_years(snap: dict) -> str | None:
    """"2003–2023": the years the day model learned which rain brings floods,
    from the snapshot's method block (models/flood_forecast/_meta.json) —
    None for a snapshot from before it was recorded."""
    ty = ((snap.get("method") or {}).get("day_model") or {}).get("tree_years") or ""
    a, _, b = ty.partition("-")
    return f"{a}–{b}" if a.isdigit() and b.isdigit() else None


def _evidence_since(nh: dict | None) -> str:
    """The year the "floods on record" count starts — read from the snapshot
    ("..., 2003-01-01..2025-10-31"), never typed: it moved from 2015 to 2003
    on 2026-09-29 (docs/design/OLDER_FLOODS_TEST.md §1)."""
    p = (nh or {}).get("evidence_period") or ""
    y = p.rsplit(", ", 1)[-1][:4]
    return y if y.isdigit() else "2015"


def _evidence_line(nh: dict, k: int) -> str:
    """What is on record near this place, and what that meant in past checks.
    The "floor" and "unreported" readings are shown only while the measured
    ratio supports them (≥ 1.1, OLDER_FLOODS_TEST.md §1)."""
    n = int(nh["floods_on_record"][k])
    by = nh.get("measured_by_level") or {}
    since = _evidence_since(nh)
    if n > 0:
        r = by.get("on_record", {}).get("happened_over_said")
        tail = (f" In past checks, places with floods on record had about {r:.1f}× as many "
                "recorded floods as forecast" + (" — read the outlook as a floor." if r >= 1.1
                                                 else ".") if r else "")
        return (f"{n} flood day{'s' if n != 1 else ''} on record within 10 km "
                f"since {since}.{tail}")
    r = by.get("none_on_record", {}).get("happened_over_said")
    tail = (f" In past checks, places like this recorded about {r:.1f}× the floods forecast"
            + (" — often because floods there go unreported." if r >= 1.1 else ".")
            if r else "")
    return (f"No floods on record within 10 km since {since}, so the outlook here rests on "
            f"the forecast alone — rain, the shape of the land and, on flat ground, soil "
            f"wetness.{tail}")


def _near_here_graded(nh: dict | None) -> str:
    """One clause on the near-here track record, when anything is graded."""
    if not nh or not nh.get("issues_graded"):
        return (f" ({nh.get('issues_logged', 0)} daily issues written down so far, none "
                "gradable yet)") if nh else ""
    s = (f": {nh['issues_graded']} weeks graded against {nh['new_flood_records']} new flood "
         f"records")
    if nh.get("ranking_auc") is not None:
        s += f", ranking flooded places above the rest {100*nh['ranking_auc']:.0f} times in 100"
    return s








def _gauge_popup(r: dict, unit: str) -> folium.Popup:
    """What a click on a gauge opens: its checked chance for every forecast
    day, and its latest reading against its line. The map lives in its own
    frame, out of reach of the page's CSS, so the styling is inline — light,
    like the map's tooltips."""
    u = f" {unit}" if unit else ""
    cells = []
    for d, x in r["days"].items():
        k = _band(x["p"])
        dd = datetime.fromisoformat(d).date()
        cells.append(
            f"<td style='padding:0 2px;text-align:center'>"
            f"<div style='font-size:10px;color:#5b6673;line-height:1.25'>"
            f"{'Today' if dd == date.today() else dd.strftime('%a')}<br>{dd:%d}</div>"
            f"<div style='margin-top:3px;padding:2px 4px;border-radius:5px;"
            f"background:{CHANCE_COLORS[k]};color:{CHANCE_INK[k]};font-weight:700;"
            f"font-size:11px;white-space:nowrap'>{_pct_short(x['p'])}</div></td>")
    top = ""
    if r["days"]:
        d_, x = max(r["days"].items(), key=lambda t: t[1]["p"])
        top = (f"<div style='margin:6px 0 4px'>Chance of reaching its line: "
               f"<b>{_pct(x['p'])}</b> at most, {_day_short(d_)} · {_esc(x['basis'])}</div>")
    hist = r.get("history") or []
    if hist:
        d, v = hist[-1]
        hot = v >= r["threshold"]
        reading = (f"Latest daily high <b style='color:{'#c0392b' if hot else '#1d2733'}'>"
                   f"{v:,.2f}{u}</b> on {datetime.fromisoformat(d):%d %b}")
    elif r.get("gauge_offline"):
        reading = (f"Gauge offline since {r.get('newest_reading_day') or '—'} — its chances "
                   "rest on rain alone")
    else:
        reading = "No readings in the last 30 days"
    line = (f"Its line {r['threshold']:,.2f}{u} · "
            + ("official danger level" if r["official"] else "the river's own wettest 2% of days"))
    flags = "".join(
        f"<div style='margin-top:3px'>{f}</div>" for f in (
            "<b style='color:#c0392b'>Above its line now</b>" if r["above_threshold_now"] else "",
            "Its exact spot on the river is not known" if r.get("unplaced") else "") if f)
    html_ = (f"<div style='font:12px Inter,system-ui,sans-serif;color:#1d2733;min-width:250px'>"
             f"<div style='font-weight:700;font-size:13px'>{_esc(r['station_name'])} gauge</div>"
             f"<div style='font-size:11px;color:#5b6673'>{r['network']} · checked forecast, "
             f"graded every day against the gauge</div>{top}"
             f"<table style='border-collapse:collapse;margin:2px 0 6px'><tr>{''.join(cells)}"
             f"</tr></table><div>{reading}</div><div style='color:#5b6673'>{line}</div>{flags}"
             f"<div style='margin-top:6px;font-size:11px;color:#5b6673'>Its graph is open under "
             f"<b>Rivers</b>, below the map.</div></div>")
    # ⚠️ The card's inner element gets a random id per run unless pinned, and
    # the map redraws every marker whenever its layer text changes — which
    # closed the card on the rerun its own click triggers. Pinned to the gauge.
    body = Html(escape_backticks(html_), script=True)
    body._id = hashlib.md5(f"gauge-card-{r['station_code']}".encode()).hexdigest()
    return folium.Popup(body, max_width=380)


def _gauge_marker(r: dict, p: float, label: bool, when: str, unit: str = "") -> folium.Marker:
    """A gauge: a diamond, so it never reads as a place. Pale blue while its
    chance is under 2%, the chance colour above; a red halo when the river is
    above its line now; dashed and hollow when the gauge is offline.

    ⚠️ A marker keeps its clicks from the map, so a click on a gauge never
    reaches `last_clicked`. It opens the card, and the page picks the gauge
    up from `last_object_clicked` instead."""
    k = _band(p)
    fill = "#dbe7f3" if k == 0 else CHANCE_COLORS[k]
    edge = "#4d8dff" if k == 0 else "#f5f7fa"
    ring = ("box-shadow:0 0 0 3px #a50026,0 0 12px 4px rgba(244,109,67,.85);"
            if r["above_threshold_now"] else "box-shadow:0 1px 4px rgba(0,0,0,.6);")
    if r.get("gauge_offline"):
        fill, edge, ring = "rgba(11,15,20,.6)", "#8fa3ba", ""
    style = "dashed" if r.get("gauge_offline") else "solid"
    html_ = (f"<div style='position:absolute;left:0;top:0;width:13px;height:13px;"
             f"transform:translate(-50%,-50%) rotate(45deg);background:{fill};"
             f"border:2px {style} {edge};border-radius:3px;{ring}'></div>")
    if label:
        html_ += (f"<div style='position:absolute;left:11px;top:0;transform:translateY(-50%);"
                  f"white-space:nowrap;background:rgba(11,15,20,.88);border:1px solid #4d8dff88;"
                  f"border-radius:7px;padding:1px 7px;font:600 11px Inter,system-ui,sans-serif;"
                  f"color:#e5edf5;box-shadow:0 2px 8px rgba(0,0,0,.45)'>"
                  f"{_esc(r['station_name'])} <b style='color:{CHANCE_TEXT[k]}'>"
                  f"{_pct_short(p)}</b></div>")
    tip = (f"{r['station_name']} gauge — {_pct(p)} chance of reaching its line"
           f" ({when}) · checked forecast"
           + (" · ABOVE its line now" if r["above_threshold_now"] else "")
           + (" · gauge offline" if r.get("gauge_offline") else "")
           + (" · its exact spot on the river is not known" if r.get("unplaced") else "")
           + " · click for each day")
    return folium.Marker([r["lat"], r["lon"]], tooltip=tip, popup=_gauge_popup(r, unit),
                         icon=folium.DivIcon(html=html_, icon_size=(0, 0), icon_anchor=(0, 0)))


def _place_label(name: str, lat: float, lon: float, p: float, when: str) -> list:
    """A named place with its outlook, the way the mock-up labels villages."""
    k = _band(p)
    col = CHANCE_COLORS[k] if k else "#8f99a8"
    html_ = (f"<div style='position:absolute;left:7px;top:0;transform:translateY(-50%);"
             f"white-space:nowrap;background:rgba(11,15,20,.84);border:1px solid {col}66;"
             f"border-left:3px solid {col};border-radius:7px;padding:1px 7px;"
             f"font:600 11px Inter,system-ui,sans-serif;color:#e5edf5;"
             f"box-shadow:0 2px 8px rgba(0,0,0,.45)'>{_esc(name)} "
             f"<span style='color:{CHANCE_TEXT[k]};font-weight:700'>{_pct_short(p)}</span></div>")
    tip = f"{name}: {_pct(p)} chance of a flood within ~10 km ({when}) · approximate outlook"
    return [folium.CircleMarker([lat, lon], radius=3.5, color="#0b0f14", weight=1.5, fill=True,
                                fill_color=col, fill_opacity=1, tooltip=tip),
            folium.Marker([lat, lon], tooltip=tip,
                          icon=folium.DivIcon(html=html_, icon_size=(0, 0), icon_anchor=(0, 0)))]






# ── panels ───────────────────────────────────────────────────────────────────
def _hero(val: float, scope: str, when: str, spark: str = "", more: str = "") -> str:
    """The headline: the outlook's level word, its number, and 7 bars."""
    k = _band(val)
    icon = "🌧️" if k >= 2 else "🌦️" if k == 1 else "☁️"
    return (f"<div class='fs-hero' style='--c:{CHANCE_COLORS[k] if k else '#6b7a8c'};"
            f"--t:{CHANCE_TEXT[k]}'>"
            f"<div class='fs-hero-top'><div class='fs-hero-ic'>{icon}</div>"
            f"<div style='min-width:0;flex:1'><div class='fs-hero-word'>{CHANCE_WORDS[k]} "
            f"flood chance</div><div class='fs-hero-sub'>{scope}</div></div></div>"
            f"<div class='fs-hero-row'><div class='fs-hero-num'>{_pct_short(val)}</div>"
            f"<div class='fs-hero-badge'>{badge('outlook', more, 'down left')}</div></div>"
            f"<div class='fs-hero-when'>{when}</div>{spark}</div>")


def _spark(days: list[str], vals: list[float], on: int = -1) -> str:
    """Seven bars, one per day; days 4-7 faded (weaker rain forecasts).
    Scaled to at least 2% (the first level): a week of 0.01%-0.03% days is
    flat and quiet, not a tall bar beside short ones."""
    mx = max(max(vals), float(CHANCE_CUTS[0]))
    out = []
    for i, (d, v) in enumerate(zip(days, vals)):
        k = _band(v)
        col = CHANCE_COLORS[k] if k else TIERS["outlook"][2]
        h = 5 + 42 * (v / mx)
        cls = ("later " if i >= SURE_DAYS else "") + ("on" if i == on else "")
        tip = f"{_day_label(d)}: {_pct(v)}" + (" · less sure (days 4–7)" if i >= SURE_DAYS else "")
        out.append(f"<div class='fs-sb {cls}'><i class='fs-tip' data-tip='{_esc(tip)}' "
                   f"style='height:{h:.0f}px;--b:{col}'></i>"
                   f"<span>{datetime.fromisoformat(d).day}</span></div>")
    return f"<div class='fs-spark'>{''.join(out)}</div>"


def _spark_svg(hist, line: float, w: int = 104, h: int = 26) -> str:
    """The last 30 days of a gauge's daily highs, with its line dashed red."""
    vals = [float(v) for _, v in (hist or [])][-30:]
    if len(vals) < 2 or line is None:
        return "<span style='color:var(--dim);font-size:.66rem'>no readings</span>"
    lo, hi = min(min(vals), line), max(max(vals), line)
    hi = hi if hi - lo > 1e-9 else lo + 1.0
    pad = 3

    def y(v):
        return pad + (h - 2 * pad) * (1 - (v - lo) / (hi - lo))

    n = len(vals)
    xs = [pad + i * (w - 2 * pad) / (n - 1) for i in range(n)]
    pts = " ".join(f"{x:.1f},{y(v):.1f}" for x, v in zip(xs, vals))
    col = "#ff5a73" if vals[-1] >= line else "#cfd8e3"
    return (f"<svg width='{w}' height='{h}' viewBox='0 0 {w} {h}'>"
            f"<line x1='0' x2='{w}' y1='{y(line):.1f}' y2='{y(line):.1f}' stroke='#f46d43' "
            f"stroke-width='1' stroke-dasharray='3 2' opacity='.85'/>"
            f"<polyline points='{pts}' fill='none' stroke='{col}' stroke-width='1.6' "
            f"stroke-linejoin='round' stroke-linecap='round'/>"
            f"<circle cx='{xs[-1]:.1f}' cy='{y(vals[-1]):.1f}' r='2.6' fill='{col}'/></svg>")


def _place_card(sel, pl, snap, period, rp, fmeta, own, river_at, levels, hot) -> None:
    """Left of the map: the answer for the selected place — the outlook near
    it (the headline, the same kind of number everywhere), what that means
    for this exact spot, the gauge on its own river and what it reads now,
    and how many floods are on record. With nothing selected: Arunachal as
    a whole, and the areas with the highest outlook, one click away."""
    days, nh = snap["days"], snap.get("near_here")
    if not sel:
        st.markdown("<div class='fs-place'>All of Arunachal<small>search a place or click "
                    "the map</small></div>", unsafe_allow_html=True)
        if nh is not None:
            vals = list(nh["arunachal_daily"])
            val = nh["arunachal_week"] if period < 0 else vals[period]
            st.markdown(_hero(val, "somewhere in the state", _when(days, period),
                              _spark(days, vals, period), more=_error_line(nh)),
                        unsafe_allow_html=True)
        if hot:
            # the colours ride with the heading: an element of its own, even an
            # empty one, takes a gap in the panel
            css = "".join(f".st-key-fs_hot_{i} button{{border-left:4px solid "
                          f"{CHANCE_COLORS[_band(h['p'])] if _band(h['p']) else '#8f99a8'}"
                          "!important}" for i, h in enumerate(hot[:5]))
            st.markdown(f"<style>{css}</style>"
                        + _sec("Highest outlook", badge("outlook", where="right"),
                               note="click to open"), unsafe_allow_html=True)
            for i, h in enumerate(hot[:5]):
                if st.button(f"{h['name']}  ·  **{_pct_short(h['p'])}**", key=f"fs_hot_{i}",
                             width="stretch", help=f"Open {h['name']}"):
                    st.session_state.pending_place = h["select"]
                    st.rerun()
        return

    n1, n2 = st.columns([5, 1], vertical_alignment="center")
    with n1:
        sub = f"{sel['lat']:.4f}°N, {sel['lon']:.4f}°E"
        st.markdown(f"<div class='fs-place'>{_esc(sel['label'])}<small>{sub}</small></div>",
                    unsafe_allow_html=True)
    with n2:
        if st.button("✕", key="fs_clear", help="Back to all of Arunachal"):
            st.session_state.pending_place = G.PROMPT
            st.rerun()
    if pl is None:
        st.markdown("<div class='fs-empty'><b>Outside the mapped area</b><br>This forecast "
                    "covers Arunachal Pradesh only.</div>", unsafe_allow_html=True)
        return
    _, _, k, w, near = pl

    # 1. THE OUTLOOK NEAR HERE — the headline, the same kind everywhere
    if nh is not None and k >= 0:
        vals = [nh["daily"][i][k] for i in range(len(days))]
        val = nh["week"][k] if period < 0 else vals[period]
        st.markdown(_hero(val, "within ~10 km of here", _when(days, period),
                          _spark(days, vals, period), more=_error_line(nh)),
                    unsafe_allow_html=True)
    elif nh is None:
        st.info("This snapshot predates the flood-chance numbers. Run the forecast again "
                "(or wait for the 08:30 run).")
    else:
        st.markdown("<div class='fs-empty'>No flood outlook here — no ground a river flood "
                    "can reach within ~10 km.</div>", unsafe_allow_html=True)

    tiles = []
    # 2. THIS SPOT — if a flood comes nearby (location model). Shown capped
    #    at "20%+": a terrain correction for Arunachal's top ranges was
    #    tested and did not hold (Gate B, FLOOD_SCREEN_PLAN.md Phase 3), so
    #    the checked rate for the spot's range sits behind the ⓘ instead.
    top = fmeta.get("checked_in_arunachal_top") or []
    if w >= FLOODABLE_MIN or not near:
        e_sub, note = ("this spot" if w >= FLOODABLE_MIN else "raised ground"), _checked_note(w, top)
    else:
        e_sub = f"raised ground · low ground {near[0]:.1f} km: {_where_str(near[1])}"
        note = _checked_note(near[1], top)
    tiles.append(_tile("If a flood comes", _where_str(w), e_sub, "estimate", _where_color(w),
                       "The chance water reaches this exact spot if a flood is reported within "
                       "about 5 km — from how high it sits above the river, how big that river "
                       "is and how closed-in the valley is. " + note, "right"))

    # 3. THE GAUGE ON THIS PLACE'S OWN RIVER — its checked forecast. Only a
    #    gauge on the same river counts (same flow path, same-size river,
    #    within 60 km: build_gauge_link.py); otherwise the tile says none.
    by_code = {r["station_code"]: (r, xs) for r, xs in rp}
    own_r = None
    if own and own[0] in by_code:
        code, rel, km, via = own
        own_r, xs = by_code[code]
        r = own_r
        what = ("its official danger level" if r["official"]
                else "high water (its own wettest 2% of days)")
        if period < 0:
            di_, x = max(xs.items(), key=lambda t: t[1]["p"])
            when = f"highest day {_day_short(di_)}"
        else:
            x = xs.get(days[period])
            when = _day_short(days[period])
        # km = along the river from this place's river point; "at this spot"
        # only when the click is on (or right beside) the gauge itself
        d_here = _km(sel["lat"], sel["lon"], r["lat"], r["lon"])
        updown = "upstream" if rel == 1 else "downstream"
        if via:
            where_ = (f"at low ground {via:.1f} km away" if km < 1 else
                      f"{km:.0f} km {updown} of low ground {via:.1f} km away")
        elif km < 1:
            where_ = "at this spot" if d_here < 0.5 else f"this stretch, {_dist(d_here)} away"
        else:
            where_ = f"{km:.0f} km {updown}"
        if x:
            tiles.append(_tile("River gauge", _pct_short(x["p"]),
                               f"{_esc(r['station_name'])} · {where_}<br>{when}", "forecast",
                               CHANCE_TEXT[_band(x["p"])],
                               f"Chance the river at {r['station_name']} reaches {what}. Graded "
                               "every day against the gauge's real readings. Its graph is "
                               "below the map.", "left"))
    elif rp:
        r, _ = min(rp, key=lambda t: _km(sel["lat"], sel["lon"], t[0]["lat"], t[0]["lon"]))
        dkm = _km(sel["lat"], sel["lon"], r["lat"], r["lon"])
        name, far = r["station_name"], _dist(dkm)
        if r.get("unplaced") and dkm < 3:
            val, sub, why = "Not matched", f"{name} is near", (
                f"{name}'s gauge is near here, but its exact spot on the river is not known — "
                "its published coordinates are wrong — so it is not matched to places. Pick "
                "it in the river board below to see its graph.")
        elif river_at == "here":
            val, sub, why = "None", "on this river", (
                f"No gauge measures this stretch of river. The nearest one, {name} ({far} "
                "away), is on another river or too far along this one, so its forecast is "
                "not this place's.")
        elif river_at == "near":
            val, sub, why = "None", "on the river at low ground", (
                f"No gauge measures the river at the nearest low ground. The nearest gauge, "
                f"{name} ({far} away), is on another river or too far along it.")
        else:
            val, sub, why = "None", "no river beside this spot", (
                f"No river a flood could come from runs beside this spot. The nearest gauge "
                f"is {name}, {far} away.")
        tiles.append(_tile("River gauge", val, f"{sub}<br>nearest: {_esc(name)}, {far}",
                           "forecast", "var(--dim)", why, "left"))

    # 4. WHAT THAT GAUGE READS NOW — measured, against the line
    if own_r is not None:
        r, lv = own_r, levels.get(own_r["station_code"])
        v, thr = r.get("last_day_max"), r["threshold"]
        unit = lv["unit"] if lv else ""
        line = "danger level" if r["official"] else "high-water line"
        lag = " NWDP gauges publish about 2 days late." if r["network"] == "NWDP" else ""
        if v is None or r.get("gauge_offline"):
            tiles.append(_tile("River now", "Offline",
                               f"since {r.get('newest_reading_day') or '—'}", "measured",
                               "var(--dim)", "The gauge has sent no complete day lately, so its "
                               "chance rests on rain alone." + lag, "right"))
        else:
            d_ = datetime.fromisoformat(r["last_complete_day"]).strftime("%d %b")
            if unit == "m":
                gap = v - thr
                val = f"{gap:+.1f} m"
                sub = f"{'above' if gap >= 0 else 'below'} its {line} · {d_}"
            else:
                val = f"{100*v/thr:.0f}%"
                sub = f"of its {line} · {d_}"
            tiles.append(_tile("River now", val, sub, "measured",
                               "#ff5a73" if v >= thr else "var(--txt)",
                               f"Latest daily high {v:,.2f} {unit} on {d_}; its {line} is "
                               f"{thr:,.2f} {unit}.{lag}", "right"))

    # 5. WHAT IS ON RECORD NEAR HERE
    if nh is not None and k >= 0:
        n = int(nh["floods_on_record"][k])
        tiles.append(_tile("Floods on record", f"{n}",
                           f"flood days · 10 km · since {_evidence_since(nh)}",
                           "record", "var(--txt)" if n else "var(--dim)",
                           _evidence_line(nh, k), "left" if len(tiles) % 2 else "right"))
    st.markdown(_tiles(tiles, 2, grow=True), unsafe_allow_html=True)


def _outlook_buttons(days: list[str], vals: list[float] | None, scope: str) -> None:
    """The period picker, as the mock-up's 7-day outlook: the whole week,
    then each day, each with its outlook and a bar in its level's colour.
    Days 4-7 dashed: they rest on weaker rain forecasts."""
    names = ["7 days"] + ["Today" if datetime.fromisoformat(d).date() == date.today()
                          else datetime.fromisoformat(d).strftime("%a %d") for d in days]
    css = ""
    for j in range(len(names)):
        v = vals[j] if vals else None
        k = _band(v)
        col = CHANCE_COLORS[k] if k else "#8f99a8"
        css += f".st-key-flv_d{j} button{{border-top:3px solid {col}!important}}"
        if j - 1 >= SURE_DAYS:
            css += (f".st-key-flv_d{j} button{{border-left-style:dashed!important;"
                    f"border-right-style:dashed!important;border-bottom-style:dashed!important}}")
    st.markdown(f"<style>{css}</style>"
                + _sec("7-day outlook", badge("outlook", where="left down"), note=scope),
                unsafe_allow_html=True)
    for row in (range(0, 4), range(4, len(names))):
        cols = st.columns(4, gap="small")
        for col, j in zip(cols, row):
            with col:
                v = vals[j] if vals else None
                label = f"{names[j]}  \n**{_pct_short(v)}**" if vals else names[j]
                later = j - 1 >= SURE_DAYS
                if st.button(label, key=f"flv_d{j}", width="stretch",
                             type="primary" if j - 1 == st.session_state.flv_day else "secondary",
                             help=("Less sure: rests on rain forecasts 4–7 days ahead"
                                   if later else None)):
                    st.session_state.flv_day = j - 1
                    st.rerun()


def _rivers_panel(rp, levels, own_code, days) -> None:
    """Conditions → Rivers: the gauges that matter most now — each one's last
    30 days against its line (measured) beside its chance (forecast)."""
    items = sorted(rp, key=lambda t: -_river_p(t[1]))
    if own_code:
        items = ([t for t in items if t[0]["station_code"] == own_code]
                 + [t for t in items if t[0]["station_code"] != own_code])
    def head(more: str = "") -> str:
        return (f"<div class='fs-rhead{more}'><span class='fs-sec-t'>River</span>"
                f"<span class='fs-sec-t'>{badge('measured', 'The last 30 days of daily highs; dashed red: the line.', 'left', True)} 30 days</span>"
                f"<span class='fs-sec-t'>{badge('forecast', where='left', mini=True)} chance</span></div>")

    # Seven rows in one column beside the map. Under the map the list runs
    # in two columns of four: the stylesheet then shows the eighth row and
    # the second heading (both marked "more") — ui.py, the main row.
    rows = []
    for i, (r, xs) in enumerate(items[:8]):
        p = _river_p(xs)
        d_ = max(xs.items(), key=lambda t: t[1]["p"])[0]
        flag = (" <span style='color:#ff5a73' title='above its line now'>▲</span>"
                if r["above_threshold_now"] else
                " <span style='color:var(--dim)' title='gauge offline'>⦸</span>"
                if r.get("gauge_offline") else "")
        own = " own" if r["station_code"] == own_code else ""
        rows.append(f"<div class='fs-rrow{own}{' more' if i == 7 else ''}'>"
                    f"<div class='fs-rname'>{_esc(r['station_name'])}"
                    f"{flag}<small>{r['network']} · {_day_short(d_)}</small></div>"
                    f"{_spark_svg(r.get('history'), r['threshold'])}{_chip(p)}</div>")
    st.markdown("<div class='fs-rlist fs-grow'>" + head() + "".join(rows[:4]) + head(" more")
                + "".join(rows[4:]) + "</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='fs-foot'>All {len(rp)} gauges: the river board below "
                f"{_i('▲ above its line now · ⦸ gauge offline. The chance is for the chosen '
                     'period: the highest day of the week, or that day.', 'left')}</div>",
                unsafe_allow_html=True)


@st.cache_data(show_spinner=False, ttl=3600)
def _upstream_rain(days: tuple, b0: int | None, _rain: np.ndarray) -> list[float]:
    """Mean rain per day over everything draining to catchment b0; the
    state's mean over the rain points when there is no catchment."""
    import products.flood.model as fm
    from products.flood.data import load_catchments
    _, nxt, order, _, sub_area, rain_pt = load_catchments()
    if b0 is None:
        return [float(np.mean(_rain[i])) for i in range(len(days))]
    return [float(fm.accumulate(_rain[i][rain_pt], sub_area, nxt, order)[0][b0])
            for i in range(len(days))]


def _rain_panel(sel, pl) -> None:
    """Conditions → Rain (an INPUT): rain over everything draining to the
    place, the last 10 days and the next 7. Fetched only when this tab is
    open — the forecast itself never needs it on screen."""
    import core.rainfall as RN
    from core.bundle import load_rain_spine
    from products.flood.data import catchment_points, load_catchments
    PTS, _ = load_rain_spine()
    rain_pt = load_catchments()[5]
    ok = catchment_points() == len(PTS["lat"]) and int(rain_pt.max()) < len(PTS["lat"])
    b0 = _catchment_of(pl) if ok else None
    scope = (f"upstream of {sel['label']}" if (sel and b0 is not None)
             else "Arunachal average")
    st.markdown(_sec("Rain", badge("input", where="left"), note=scope), unsafe_allow_html=True)
    fx = RN.load_forecast(tuple(PTS["lat"]), tuple(PTS["lon"]))
    if fx is None:
        st.markdown("<div class='fs-empty'>Live rain is unavailable right now.</div>",
                    unsafe_allow_html=True)
        return
    days, rain = fx
    vals = _upstream_rain(tuple(str(d) for d in days), b0, rain)
    today = date.today().isoformat()
    past = [v for d, v in zip(days, vals) if str(d) < today]
    ahead = [v for d, v in zip(days, vals) if str(d) >= today]
    st.markdown(
        _tiles([_tile("Last 3 days", f"{sum(past[-3:]):.0f}<small>mm</small>", "", None,
                      "#7fd4f0"),
                _tile("Next 3 days", f"{sum(ahead[:3]):.0f}<small>mm</small>", "forecast rain",
                      None, "#7fd4f0")], 2), unsafe_allow_html=True)
    df = pd.DataFrame({"date": pd.to_datetime([str(d) for d in days]), "mm": vals,
                       "kind": ["past" if str(d) < today else "forecast" for d in days]})
    bars = (alt.Chart(df).mark_bar(color="#7fd4f0", cornerRadiusTopLeft=2,
                                   cornerRadiusTopRight=2)
            .encode(x=alt.X("date:T", title=None, axis=alt.Axis(format="%d", labelAngle=0)),
                    y=alt.Y("mm:Q", title="mm/day"),
                    opacity=alt.condition("datum.kind == 'past'", alt.value(1.0),
                                          alt.value(0.42)),
                    tooltip=[alt.Tooltip("date:T", title="day", format="%a %d %b"),
                             alt.Tooltip("mm:Q", title="mm", format=".1f"),
                             alt.Tooltip("kind:N", title="")]))
    now = (alt.Chart(pd.DataFrame({"date": [pd.Timestamp(today)]}))
           .mark_rule(color="#8b95a3", strokeDash=[4, 4]).encode(x="date:T"))
    st.altair_chart(alt.layer(bars, now).properties(height=150, background="transparent")
                    .configure_axis(labelColor="#8b95a3", titleColor="#8b95a3",
                                    gridColor="#8b95a333", domainColor="#8b95a366",
                                    tickColor="#8b95a366")
                    .configure_view(strokeWidth=0), width="stretch")
    st.markdown(f"<div class='fs-foot'>Solid: past 10 days · faded: forecast "
                f"{_i('Mean daily rain over everything that drains to this place (Open-Meteo, '
                     f'{len(PTS['lat'])} points about 22 km apart). An input to the forecast, '
                     'not a flood chance.', 'left')}</div>", unsafe_allow_html=True)


def _soil_to(sw: dict) -> str:
    d = sw.get("soil_data_to")
    return datetime.fromisoformat(d).strftime("%d %b") if d else "—"


def _soil_panel(snap, k: int | None, sel) -> None:
    """Conditions → Soil (an INPUT): how wet the top metre of soil is for the
    time of year, and whether the forecast uses it here — on flat ground only
    (docs/design/SOIL_WETNESS_TEST.md)."""
    sw = snap.get("soil_wetness") or {}
    lag = sw.get("lag_days", 16)
    tip = (f"Top-metre soil water (ERA5-Land) from {lag} days ago — the newest always "
           "available — as this place's own May–October percentile. The forecast uses it on "
           "flat ground only: there it picked flood days better; on steep ground floods come "
           "from one downpour, and it did not help.")
    st.markdown(_sec("Soil wetness", badge("input", where="left"),
                     note=sel["label"] if sel and k is not None and k >= 0 else "flat ground"),
                unsafe_allow_html=True)
    if not sw:
        st.markdown("<div class='fs-empty'>No soil readings in this issue.</div>",
                    unsafe_allow_html=True)
        return
    pct, flat = sw.get("pct_now"), sw.get("flat")
    if not sw.get("used", True):
        st.markdown("<span class='fs-pill' style='--c:#ffb020'>Not fetched today — flat ground "
                    "uses rain only</span>", unsafe_allow_html=True)
    if pct is None or flat is None:
        st.markdown("<div class='fs-empty'>Soil per place appears from the next run.</div>",
                    unsafe_allow_html=True)
        return

    def word(v):
        return ("Drier than usual" if v < 0.25 else "Usual" if v < 0.75 else
                "Wetter than usual" if v < 0.90 else "Very wet")

    if k is not None and k >= 0 and pct[k] is not None:
        v, used = float(pct[k]), bool(flat[k])
        head = f"{100*v:.0f}<small>th percentile</small>"
        pill = (("✔ Used here — flat ground", "#35d07f") if used else
                ("Not used here — steep ground, rain only", "#8fa3ba"))
    else:
        f = [float(p) for p, fl in zip(pct, flat) if fl and p is not None]
        if not f:
            st.markdown("<div class='fs-empty'>No flat-ground readings today.</div>",
                        unsafe_allow_html=True)
            return
        v = float(np.median(f))
        head = f"{100*np.mean(np.array(f) >= 0.75):.0f}%<small> of flat areas wetter than usual</small>"
        pill = (f"✔ Used on {len(f)} flat areas", "#35d07f")
    st.markdown(f"<div class='fs-big'>{head}</div>"
                f"<div style='color:var(--mut);font-size:.78rem;margin-top:2px'>{word(v)}</div>"
                f"<div class='fs-meter'><i style='left:{100*v:.0f}%'></i></div>"
                f"<div class='fs-meter-l'><span>dry</span><span>usual</span><span>wet</span></div>"
                f"<span class='fs-pill' style='--c:{pill[1]}'>{pill[0]}</span>"
                f"<div class='fs-foot'>Readings to {_soil_to(sw)} · {lag}-day lag "
                f"{_i(tip, 'left')}</div>", unsafe_allow_html=True)


def _changes(snap, k: int | None, sel) -> str:
    """What changed since the previous issue — from the `previous` block the
    daily run writes (flood_forecast_live.previous_issue)."""
    pv, nh = snap.get("previous"), snap.get("near_here") or {}
    if not pv:
        return (_sec("What changed") + "<div class='fs-empty'>The first comparison appears "
                "with the next issue.</div>")
    rows = []
    a0, a1 = pv.get("arunachal_week"), nh.get("arunachal_week")
    if a0 is not None and a1 is not None:
        rows.append(_row("≈", TIERS["outlook"][2], "Arunachal · 7 days", _move(a0, a1)))
    wk0, wk1 = pv.get("week"), nh.get("week")
    if wk0 and wk1 and len(wk0) == len(wk1):
        if sel and k is not None and k >= 0:
            rows.append(_row("📍", TIERS["outlook"][2], _esc(sel["label"]), _move(wk0[k], wk1[k])))
        b0, b1 = _chance_class(np.array(wk0)), _chance_class(np.array(wk1))
        rows.append(_row("▦", TIERS["outlook"][2], "Areas changing level",
                         f"<span class='fs-up'>▲</span> <b>{int((b1 > b0).sum())}</b> &nbsp;"
                         f"<span class='fs-dn'>▼</span> <b>{int((b1 < b0).sum())}</b>"))
    moves = []
    for r in snap["rivers"]:
        o = (pv.get("rivers") or {}).get(r["station_code"])
        if o is not None and r["days"]:
            p1 = max(x["p"] for x in r["days"].values())
            moves.append((p1 - o["p"], r["station_name"], o["p"], p1))
    if moves:
        up, dn = max(moves), min(moves)
        if up[0] > 0.001:
            rows.append(_row("≋", TIERS["forecast"][2], f"<b>{_esc(up[1])}</b> rising",
                             _move(up[2], up[3])))
        if dn[0] < -0.001:
            rows.append(_row("≋", TIERS["forecast"][2], f"<b>{_esc(dn[1])}</b> easing",
                             _move(dn[2], dn[3])))
        if up[0] <= 0.001 and dn[0] >= -0.001:
            rows.append(_row("≋", TIERS["forecast"][2], "Rivers", "<span class='fs-was'>"
                             "little change</span>"))
    prev = pv.get("rivers") or {}
    n0 = sum(1 for o in prev.values() if o.get("above_now"))
    n1 = sum(1 for r in snap["rivers"] if r["above_threshold_now"])
    rows.append(_row("▲", "#ff5a73", "Rivers above their line",
                     f"<span class='fs-was'>{n0}</span> → <b>{n1}</b>"))
    went = [r["station_name"] for r in snap["rivers"] if r.get("gauge_offline")
            and not (prev.get(r["station_code"]) or {}).get("offline", True)]
    back = [r["station_name"] for r in snap["rivers"] if not r.get("gauge_offline")
            and (prev.get(r["station_code"]) or {}).get("offline", False)]
    if went or back:
        rows.append(_row("⦸", "#8fa3ba", "Gauges",
                         (f"<span class='fs-up'>−{len(went)}</span> " if went else "")
                         + (f"<span class='fs-dn'>+{len(back)}</span>" if back else "")
                         + _i(("Went offline: " + ", ".join(went) + ". " if went else "")
                              + ("Back: " + ", ".join(back) + "." if back else ""), "left")))
    since = datetime.fromisoformat(pv["issued_on"]).strftime("%d %b")
    return (_sec("What changed", note=f"since {since}")
            + "".join(rows)
            + f"<div class='fs-foot'>Each issue covers its own next 7 days "
              f"{_i('This issue compared with the one before it. The outlook and river chances '
                   'are each for the 7 days that issue covered.', 'right')}</div>")


def _attention(snap, rp, rivers, chance, hot, when: str) -> str:
    """What stands out today, from our own numbers only — no advice we
    cannot back (bridges and evacuation need district data we lack)."""
    rows = []
    above = [r["station_name"] for r in rivers if r["above_threshold_now"]]
    if above:
        rows.append(_row("▲", "#ff5a73", f"<b>{_esc(', '.join(above))}</b> above "
                         f"{'its' if len(above) == 1 else 'their'} line now",
                         badge("measured", where="left")))
    risky = sorted(((r, _river_p(xs), max(xs.items(), key=lambda t: t[1]["p"])[0])
                    for r, xs in rp if _river_p(xs) >= 0.05), key=lambda t: -t[1])
    for r, p, d in risky[:3]:
        rows.append(_row("≋", CHANCE_COLORS[_band(p)], f"<b>{_esc(r['station_name'])}</b> · "
                         f"{_day_short(d)}", _chip(p)))
    if chance is not None:
        n10 = int((chance >= 0.10).sum())
        if n10:
            names = ", ".join(h["name"] for h in hot if h["p"] >= 0.10)[:60]
            rows.append(_row("▦", CHANCE_COLORS[3], f"<b>{n10}</b> area{'s' if n10 != 1 else ''} "
                             f"at 10%+ · {_esc(names)}", badge("outlook", where="left")))
    off = [r["station_name"] for r in rivers if r.get("gauge_offline")]
    if off:
        rows.append(_row("⦸", "#8fa3ba", f"<b>{len(off)}</b> gauges offline",
                         _i("Their chances rest on rain alone: " + ", ".join(off) + ".", "left")))
    sw = snap.get("soil_wetness") or {}
    if sw and not sw.get("used", True):
        rows.append(_row("☂", "#7fd4f0", "Soil readings missing today",
                         _i("Flat ground uses rain only in today's issue.", "left")))
    quiet = not above and not risky and (chance is None or not (chance >= 0.10).any())
    if quiet:
        rows.insert(0, _row("✓", "#35d07f", "Nothing stands out",
                            f"<span class='fs-was'>{when}</span>"))
    return (_sec("Needs attention") + "".join(rows)
            + f"<div class='fs-foot'>From today's numbers only "
              f"{_i('Rivers above their line, rivers at 5%+, areas at 10%+ and gauges offline. '
                   'Advice on bridges, roads or evacuation needs district data and procedures '
                   'this screen does not have.', 'left')}</div>")


def _track(snap) -> str:
    """How the forecast is being proven: written down before, graded after."""
    tr = snap.get("track_record") or {}
    if not tr:
        return _sec("Track record") + "<div class='fs-empty'>No track record yet.</div>"
    chk = tr.get("checked") or {}
    first = datetime.fromisoformat(tr["first_issue"]).strftime("%d %b")
    tip = (f"{tr['forecasts_logged']:,} river forecasts written down since {first}, each graded "
           f"against the gauge once the day has passed. So far {chk.get('n_forecasts', 0)} "
           f"checked; the river reached its line {chk.get('n_times_threshold_reached', 0)} "
           "times. This grows through the monsoon and is what proves the numbers. The outlook "
           "near each place is written down every morning too, and graded once flood records "
           "for those days come in" + _near_here_graded(tr.get("near_here")) + ".")
    nhr = tr.get("near_here") or {}
    return (_sec("Track record", note=f"since {first}")
            + "<div class='fs-tight'>"
            + _tiles([_tile("Written down", f"{tr['forecasts_logged']:,}", "river forecasts"),
                      _tile("Checked", f"{chk.get('n_forecasts', 0):,}", "against the gauge"),
                      _tile("Line reached", f"{chk.get('n_times_threshold_reached', 0)}",
                            "times so far")], 3) + "</div>"
            + f"<div class='fs-foot'>Outlook: {nhr.get('issues_logged', 0)} issue"
              f"{'s' if nhr.get('issues_logged', 0) != 1 else ''} logged · "
              f"{nhr.get('issues_graded', 0)} graded {_i(tip, 'left')}</div>")


# ── one gauge's graph, and the board of all of them ──────────────────────────
def _gauge_lines(lv: dict | None) -> list[tuple]:
    """(label, value, colour, dash) for every line on a gauge's graph: CWC's
    published levels where it publishes them, and the line our chance is for.
    Nothing is drawn that neither source states (build_gauge_levels.py)."""
    if not lv:
        return []
    out = []
    if lv.get("highest") is not None:
        yr = f" ({lv['highest_date'][:4]})" if lv.get("highest_date") else ""
        out.append((f"highest ever{yr} {lv['highest']:.2f}", lv["highest"], "#a50026", [6, 3]))
    if lv.get("danger") is not None:
        out.append((f"danger level {lv['danger']:.2f}", lv["danger"], "#f46d43", [1, 0]))
    if lv.get("warning") is not None:
        out.append((f"warning level {lv['warning']:.2f}", lv["warning"], "#fdae61", [1, 0]))
    if not lv["model_line_is_official_danger"]:
        out.append((f"high water — its wettest 2% of days {lv['model_line']:.2f}",
                    lv["model_line"], "#b39ddb", [4, 2]))
    out.append((f"typical {lv['typical']:.2f}", lv["typical"], "#8b95a3", [2, 3]))
    return out


def _level_forecast(r: dict) -> pd.DataFrame:
    """The level line's points: the last complete day's reading, then each
    day that carries a level forecast (low / middle / high of its daily
    high). Empty when the snapshot holds none for this gauge."""
    rows = [(pd.Timestamp(d), *x["level"]) for d, x in sorted(r["days"].items()) if x.get("level")]
    cols = ["date", "lo", "mid", "hi", "forecast", "range"]
    if not rows or not r.get("last_complete_day") or r.get("last_day_max") is None:
        return pd.DataFrame(columns=cols)
    v = float(r["last_day_max"])
    out = [(pd.Timestamp(r["last_complete_day"]), v, v, v, False, "")]
    out += [(d, lo, mid, hi, True, f"{lo:,.2f} – {hi:,.2f}") for d, lo, mid, hi in rows]
    return pd.DataFrame(out, columns=cols)


def _gauge_chart(r: dict, lv: dict | None, days: list[str]):
    """A river gauge the way Google Flood Hub draws one: the last 30 days of
    measured daily highs, a "Now" line, the river's published warning /
    danger / highest-ever lines — and, below on the same time axis, our
    chance of the river reaching its line on each coming day. Since
    2026-10-06 a dotted line continues the readings: our forecast of the
    daily high, with its likely range, for as many days after the last
    complete day as it was shown to hold (two; FLOOD_SCREEN_PLAN.md,
    Phase 10; FLOOD_WHEN_PILOT_PLAN.md §14)."""
    today = pd.Timestamp(date.today())
    x_dom = [(today - pd.Timedelta(days=30)).isoformat(),
             (pd.Timestamp(days[-1]) + pd.Timedelta(days=1)).isoformat()]
    xs = alt.Scale(domain=x_dom)
    parts = []
    hist = pd.DataFrame(r.get("history") or [], columns=["date", "value"])
    # NWDP part-days (fewer than half the day's readings arrived): hollow dots,
    # never joined to the line — the day's high may be missing, which is why
    # no forecast uses them (flood_gauge_live.fetch_history)
    part = pd.DataFrame(r.get("history_part_days") or [], columns=["date", "value", "readings"])
    lines = _gauge_lines(lv)
    if len(hist) or len(part):
        hist["date"] = pd.to_datetime(hist["date"])
        part["date"] = pd.to_datetime(part["date"])
        # every day of the window; each unbroken run of reported days is its
        # own line segment, so nothing is drawn across days the gauge did not
        # report (NWDP skips whole days). Missing values must not reach the
        # chart as nulls: drawn with invalid=None they sank to the bottom of
        # the axis, as if the river had dropped.
        full = pd.date_range(pd.Timestamp(x_dom[0]), today, freq="D")
        hist = hist.set_index("date").reindex(full).rename_axis("date").reset_index()
        hist["seg"] = hist["value"].isna().cumsum()
        hist = hist[hist["value"].notna()]
        part = part[part["date"] >= full[0]]
        fc = _level_forecast(r)
        vals = (list(hist["value"]) + list(part["value"]) + [v for _, v, _, _ in lines]
                + list(fc["lo"]) + list(fc["hi"]))
        lo, hi = min(vals), max(vals)
        pad = max((hi - lo) * 0.08, 0.05 * max(abs(hi), 1e-9) if hi == lo else 0.0)
        ys = alt.Scale(domain=[lo - pad, hi + pad], zero=False)
        unit = lv["unit"] if lv else ""
        qty = lv["quantity"] if lv else "reading"
        layers = [alt.Chart(hist).mark_line(color=T.ACCENT_2, strokeWidth=2.5,
                                            point=alt.OverlayMarkDef(size=22, color=T.ACCENT_2))
                  .encode(x=alt.X("date:T", scale=xs, title=None),
                          y=alt.Y("value:Q", scale=ys, title=f"{qty} ({unit})"),
                          detail="seg:N",
                          tooltip=[alt.Tooltip("date:T", title="day"),
                                   alt.Tooltip("value:Q", title=f"daily high ({unit})", format=".2f")])]
        if len(part):
            layers.append(alt.Chart(part).mark_point(filled=False, size=48, strokeWidth=1.6,
                                                     color=T.ACCENT_2)
                          .encode(x=alt.X("date:T", scale=xs), y=alt.Y("value:Q", scale=ys),
                                  tooltip=[alt.Tooltip("date:T", title="part day"),
                                           alt.Tooltip("value:Q", format=".2f",
                                                       title=f"high of the readings sent ({unit})"),
                                           alt.Tooltip("readings:Q", title="readings sent, of 96")]))
        if len(fc):
            # the level line: a band for the likely range, a dotted middle line
            # joined to the last complete day's reading, a hollow dot per day
            fx = alt.X("date:T", scale=xs)
            layers.append(alt.Chart(fc).mark_area(color=T.ACCENT_2, opacity=0.16)
                          .encode(x=fx, y=alt.Y("lo:Q", scale=ys), y2="hi:Q"))
            layers.append(alt.Chart(fc).mark_line(color=T.ACCENT_2, strokeWidth=2.2, strokeDash=[5, 4])
                          .encode(x=fx, y=alt.Y("mid:Q", scale=ys)))
            layers.append(alt.Chart(fc[fc["forecast"]]).mark_point(filled=False, size=60, strokeWidth=2,
                                                                  color=T.ACCENT_2)
                          .encode(x=fx, y=alt.Y("mid:Q", scale=ys),
                                  tooltip=[alt.Tooltip("date:T", title="day"),
                                           alt.Tooltip("mid:Q", format=".2f",
                                                       title=f"expected daily high ({unit})"),
                                           alt.Tooltip("range:N", title="likely range (8 in 10)")]))
        for label, v, col, dash in lines:
            d = pd.DataFrame({"value": [v], "label": [label], "date": [pd.Timestamp(x_dom[1])]})
            layers.append(alt.Chart(d).mark_rule(color=col, strokeWidth=1.6, strokeDash=dash)
                          .encode(y=alt.Y("value:Q", scale=ys), tooltip="label:N"))
            layers.append(alt.Chart(d).mark_text(align="right", dy=-6, fontSize=11, color=col)
                          .encode(x=alt.X("date:T", scale=xs), y=alt.Y("value:Q", scale=ys),
                                  text="label:N"))
        now = pd.DataFrame({"date": [today], "t": ["Now"]})
        layers.append(alt.Chart(now).mark_rule(color="#8b95a3", strokeDash=[4, 4])
                      .encode(x=alt.X("date:T", scale=xs)))
        layers.append(alt.Chart(now).mark_text(align="left", dx=4, dy=-4, fontSize=11,
                                               color="#8b95a3", baseline="top")
                      .encode(x=alt.X("date:T", scale=xs), y=alt.value(0), text="t:N"))
        parts.append(alt.layer(*layers).properties(height=250))
    bars = pd.DataFrame([{"date": pd.Timestamp(d), "chance": 100 * x["p"], "shown": _pct(x["p"]),
                          "basis": x["basis"], "color": CHANCE_COLORS[_band(x["p"])]}
                         for d, x in sorted(r["days"].items())])
    what = ("its danger level" if r["official"] else "its wettest-2% mark")
    parts.append(alt.Chart(bars).mark_bar(size=14, cornerRadiusTopLeft=2, cornerRadiusTopRight=2)
                 .encode(x=alt.X("date:T", scale=xs, title=None),
                         y=alt.Y("chance:Q", title=f"chance of reaching {what}, %"),
                         color=alt.Color("color:N", scale=None),
                         tooltip=[alt.Tooltip("date:T", title="day"),
                                  alt.Tooltip("shown:N", title="chance"),
                                  alt.Tooltip("basis:N", title="based on")])
                 .properties(height=110))
    return (alt.vconcat(*parts, spacing=6).resolve_scale(x="shared")
            .properties(background="transparent")
            .configure_axis(labelColor="#8b95a3", titleColor="#8b95a3",
                            gridColor="#8b95a333", domainColor="#8b95a366",
                            tickColor="#8b95a366")
            .configure_view(strokeWidth=0))


def _board(rivers: list[dict], days: list[str]):
    """Every gauge x every day, coloured by its chance — the whole river
    picture at a glance. Clicking a row opens that gauge's graph."""
    order = sorted([r for r in rivers if r["days"]],
                   key=lambda r: -max(x["p"] for x in r["days"].values()))
    rows = []
    for r in order:
        name = r["station_name"] + (" ▲" if r["above_threshold_now"] else
                                    " ⦸" if r.get("gauge_offline") else "")
        for d in days:
            x = r["days"].get(d)
            if not x:
                continue
            p = x["p"]
            k = _band(p)
            rows.append({"code": r["station_code"], "name": name, "day": _day_short(d),
                         "p": p, "shown": _pct(p),
                         "txt": "·" if p < 0.001 else (f"{100*p:.1f}" if p < 0.10 else f"{100*p:.0f}"),
                         "fill": CHANCE_COLORS[k], "ink": CHANCE_INK[k] if k else "#b8c4d2",
                         "basis": x["basis"],
                         "line": "official danger level" if r["official"] else "own wettest 2%"})
    df = pd.DataFrame(rows)
    names = list(dict.fromkeys(df["name"])) if len(df) else []
    dayo = [_day_short(d) for d in days]
    pick = alt.selection_point(name="pick", fields=["code"], on="click")
    base = alt.Chart(df).encode(
        x=alt.X("day:N", sort=dayo, title=None,
                axis=alt.Axis(orient="top", labelAngle=0, labelFontSize=10, ticks=False,
                              domain=False)),
        y=alt.Y("name:N", sort=names, title=None,
                axis=alt.Axis(labelFontSize=11, ticks=False, domain=False, labelLimit=150,
                              labelOverlap=False)))
    rect = (base.mark_rect(cornerRadius=4, stroke="#0b0f14", strokeWidth=2)
            .encode(color=alt.Color("fill:N", scale=None),
                    opacity=alt.condition(pick, alt.value(1.0), alt.value(0.55)),
                    tooltip=[alt.Tooltip("name:N", title="gauge"), alt.Tooltip("day:N"),
                             alt.Tooltip("shown:N", title="chance"),
                             alt.Tooltip("line:N", title="line"),
                             alt.Tooltip("basis:N", title="based on")])
            .add_params(pick))
    text = base.mark_text(fontSize=10, fontWeight=600).encode(
        text="txt:N", color=alt.Color("ink:N", scale=None))
    return (alt.layer(rect, text).properties(height=20 * len(names), background="transparent")
            .configure_axis(labelColor="#b8c4d2", grid=False)
            .configure_view(strokeWidth=0))


def _reading(v: float, unit: str) -> str:
    """A level or flow for a tile. High-altitude gauges read in the thousands
    of metres, where the centimetres matter most: set smaller, never cut off."""
    size = "0.66em" if abs(v) >= 1000 else "0.82em" if abs(v) >= 100 else "1em"
    return f"<span style='font-size:{size}'>{v:,.2f}</span><small>{unit}</small>"


def _gauge_detail(snap, levels, rivers_by: dict, own) -> None:
    """One gauge: four facts, then its Flood-Hub-style graph."""
    order = sorted(rivers_by, key=lambda c: rivers_by[c]["station_name"])
    code = st.selectbox("River gauge", order, key="flv_gauge",
                        format_func=lambda c: rivers_by[c]["station_name"]
                        + (" — on the selected place's river" if own and c == own[0] else ""),
                        label_visibility="collapsed")
    r, lv = rivers_by[code], levels.get(code)
    days = snap["days"]
    unit = lv["unit"] if lv else ""
    last = r.get("history") or []
    tiles = []
    if last:
        d, v = last[-1]
        lag = " NWDP gauges publish about 2 days late." if r["network"] == "NWDP" else ""
        tiles.append(_tile("Latest daily high", _reading(v, unit),
                           datetime.fromisoformat(d).strftime("%d %b"), "measured",
                           "#ff5a73" if v >= r["threshold"] else None,
                           f"The highest reading of that day.{lag}", "right"))
    elif r.get("gauge_offline"):
        tiles.append(_tile("Gauge", "Offline", f"since {r.get('newest_reading_day') or '—'}",
                           "measured", "var(--dim)", "Its chances rest on rain alone.", "right"))
    else:
        tiles.append(_tile("Gauge", "No readings", "last 30 days", "measured", "var(--dim)"))
    line_tip = ("The official CWC danger level." if r["official"] else
                "This river's own wettest 2% of days — "
                + ("CWC's danger level has not been reached in its record."
                   if lv and lv.get("danger") is not None else "no official level is published."))
    tiles.append(_tile("Its line", _reading(r["threshold"], unit),
                       "official danger level" if r["official"] else "own wettest 2%", None,
                       None, line_tip))
    if r["days"]:
        d_, x = max(r["days"].items(), key=lambda t: t[1]["p"])
        tiles.append(_tile("Highest chance", _pct_short(x["p"]), f"{_day_short(d_)} · {x['basis']}",
                           "forecast", CHANCE_TEXT[_band(x["p"])],
                           "The chance the river reaches its line that day — graded every day "
                           "against the gauge.", "left"))
    fc = _level_forecast(r)
    fc = fc[fc["forecast"]] if len(fc) else fc
    net = "Central Water Commission" if r["network"] == "CWC" else "National Water Data Portal"
    if len(fc):
        f1 = fc.iloc[0]
        tiles.append(_tile(f"Expected high, {f1['date'].strftime('%d %b')}",
                           _reading(f1["mid"], unit), f"likely {f1['range']}",
                           "forecast", "#ff5a73" if f1["mid"] >= r["threshold"] else None,
                           "Our forecast of that day's highest reading, and the range 8 in 10 such "
                           f"days have landed in. Readings: {net}.", "left"))
    else:
        tiles.append(_tile("Network", r["network"], net, None, None))
    st.markdown(_tiles(tiles, 4), unsafe_allow_html=True)
    st.altair_chart(_gauge_chart(r, lv, days), width="stretch")
    st.markdown(
        "<div class='fs-foot'>Line: measured daily high · "
        + ("dotted: our forecast of the level · " if len(fc) else "")
        + "horizontal: CWC's levels and our line · bars: our chance each day "
        + _i("Horizontal lines: the levels CWC publishes for this gauge, and the line our "
             "chance is for. Bars: our chance of the river reaching that line on each day, "
             "graded every day against the gauge. "
             + ("Dotted line and shaded band: our forecast of the daily high for the two days "
                "after the last full day of readings; the band is where 8 in 10 such days have "
                "landed. It is not drawn further ahead." if len(fc) else
                "No forecast of the level is drawn for this gauge today: it needs a full day "
                "of readings no more than two days old.")
             + (" Hollow dots: days the gauge sent fewer than half its readings — the day's "
                "high may be missing, so no forecast uses them. Gaps: days it sent nothing."
                if r.get("history_part_days") else ""), "right")
        + "</div>", unsafe_allow_html=True)


# ── flood reports ────────────────────────────────────────────────────────────
REPORTS_CSV = PROJECT / "records" / "flood_events" / "reports.csv"


def _report_destination():
    """Where a flood report can go. ("local", None) when the app runs beside
    the full project — written to records/ and picked up by flood_intake.py;
    ("form", url) when the host configures `flood_report_url` in its
    secrets; (None, None) otherwise — and then no form is shown, so the
    screen never claims reports are collected when they are not."""
    if (PROJECT / "records").exists() and (PROJECT / "scripts" / "model" / "flood_intake.py").exists():
        return "local", None
    try:
        url = st.secrets.get("flood_report_url")
    except Exception:                                               # noqa: BLE001
        url = None
    return ("form", url) if url else (None, None)


def _report_form(sel, grid) -> None:
    kind, url = _report_destination()
    if kind is None:
        return
    with st.expander("📝  Seen a flood? Report it"):
        st.markdown("<div style='color:var(--mut);font-size:.85rem'>Reports help most where "
                    "few floods are on record. Each one joins the flood record as a report — "
                    "the same kind of record the forecast learned from — and is then used to "
                    "grade the forecasts written down before it.</div>", unsafe_allow_html=True)
        if kind == "form":
            st.link_button("Open the report form", url)
            return
        with st.form("flood_report", clear_on_submit=True):
            place = st.text_input("Where", value=sel["label"] if sel else "")
            c1, c2 = st.columns(2)
            lat = c1.number_input("Latitude", value=float(sel["lat"]) if sel else 27.5,
                                  format="%.4f")
            lon = c2.number_input("Longitude", value=float(sel["lon"]) if sel else 94.0,
                                  format="%.4f")
            day = st.date_input("When", value=date.today(), max_value=date.today())
            note = st.text_area("What did you see?", max_chars=500)
            sent = st.form_submit_button("Send report")
        if sent:
            if not (grid.south <= lat <= grid.north and grid.west <= lon <= grid.east):
                st.error("That place is outside the area this forecast covers.")
                return
            REPORTS_CSV.parent.mkdir(parents=True, exist_ok=True)
            row = pd.DataFrame([{"reported_on": date.today().isoformat(), "place": place.strip(),
                                 "lat": round(float(lat), 5), "lon": round(float(lon), 5),
                                 "date": day.isoformat(), "note": note.strip()}])
            row.to_csv(REPORTS_CSV, mode="a", header=not REPORTS_CSV.exists(), index=False)
            st.success("Thank you — recorded. It joins the flood record at the next daily "
                       "run.")


# ── the page ─────────────────────────────────────────────────────────────────
def render(shell, s, search_row) -> None:
    """`search_row` is the flood module's place picker (view.py) — the same
    session key SlopeSense uses, so a place picked in one module is still
    selected in the other."""
    grid, geo = shell.grid, shell.geo
    st.markdown(FS_CSS, unsafe_allow_html=True)
    local = can_run_models()
    if not available():
        if local:
            st.info("**No forecast has been run yet.**")
            if st.button("Run the forecast now", type="primary") and run_models():
                st.rerun()
        else:
            st.info("**No live forecast yet.** It is produced by the daily run "
                    "(`scripts/model/flood_forecast_live.py`).")
        return
    mtime = SNAPSHOT.stat().st_mtime
    snap, prob, fmeta = _load(mtime)
    days = snap["days"]
    nh = snap.get("near_here")
    issued = date.fromisoformat(snap["issued_on"])
    age = (date.today() - issued).days

    # ── header: what this is, when it was issued, where, run now ─────────
    head = st.container(key="fs_head")
    h1, h2, h3 = head.columns([1.15, 3.1, 0.75], vertical_alignment="center")
    with h1:
        dot = "#35d07f" if age <= 0 else "#ffb020" if age == 1 else "#f46d43"
        state = "Today's issue" if age <= 0 else f"{age} day{'s' if age > 1 else ''} old"
        st.markdown(
            f"<div class='fs-head'><div class='fs-logo'>◈</div><div>"
            f"<div class='fs-title'>Flood forecast</div>"
            f"<div class='fs-issued'><span class='fs-dot' style='background:{dot}'></span>"
            f"Issued {issued:%d %b} · {snap['generated_at'][-5:]}"
            + _i(f"{state}, {issued:%d %b %Y}. Live rain ({snap.get('rain_source', 'Open-Meteo')}) and "
                 f"{len(snap['rivers'])} river gauges. Runs every morning at 08:30; each issue "
                 "is written down before the day and graded after.", "down right")
            + "</div></div></div>", unsafe_allow_html=True)
    with h2:
        sel = search_row()
    clicked = False
    with h3:
        if local:
            clicked = st.button("↻ Run now", width="stretch",
                                type="primary" if age > 0 else "secondary",
                                help="Runs the real models on the latest rain and river "
                                     "readings (1–3 minutes). The 08:30 run stays the "
                                     "official, logged forecast; this only refreshes the "
                                     "screen.")
    if sel is None and st.session_state.get("search") not in (None, G.PROMPT):
        st.warning(f"Could not read **{st.session_state.search}** as a place or a coordinate.")
    if local and age > 0:
        st.info(f"Today's forecast hasn't been run yet — this one is from {issued:%d %b}. "
                "Run it now, or it runs by itself at 08:30.")
    elif not local and age > 1:
        st.warning(f"This forecast was issued {age} days ago. It refreshes when the daily "
                   "run's new snapshot is published.")
    if clicked:
        if run_models():
            st.rerun()
        return
    st.markdown("<div class='fs-key'><span class='fs-key-l'>Key</span>"
                + "".join(badge(t, where="down") for t in TIERS) + "</div>",
                unsafe_allow_html=True)

    # ── state shared by every panel ───────────────────────────────────────
    slot = _pixel_slot(mtime, grid.west, grid.north, grid.dlon, grid.dlat,
                       grid.height, grid.width)
    pl = _place(sel, grid, slot, prob)
    link, codes, levels, placed = _gauge_assets(prob.shape)
    own = _own_gauge(pl, link, codes)
    river_at = _river_at(pl, link)
    k_sel = pl[2] if (pl is not None and nh is not None and pl[2] >= 0) else None
    if st.session_state.get("flv_day") not in range(-1, len(days)):
        st.session_state.flv_day = -1
    period = st.session_state.flv_day
    when = "next 7 days" if period < 0 else _day_short(days[period])

    # Each gauge is drawn where it sits on the map's rivers — the point the
    # "gauge on this river" lookup measures from — so clicking its dot reads
    # "at this spot". For all but a few gauges that is within 0.3 km of the
    # published location (build_gauge_link.py).
    rivers = [dict(r, lat=placed[r["station_code"]][0], lon=placed[r["station_code"]][1])
              if placed.get(r["station_code"]) else
              dict(r, unplaced=True) if r["station_code"] in placed else r
              for r in snap["rivers"]]
    # rivers for the chosen period: that day, or each river's highest day
    if period < 0:
        rp = [(r, r["days"]) for r in rivers if r["days"]]
    else:
        rp = [(r, {days[period]: r["days"][days[period]]}) for r in rivers
              if days[period] in r["days"]]

    chance = (np.asarray(nh["week"] if period < 0 else nh["daily"][period], np.float32)
              if nh is not None else None)
    cls = (_area_classes(chance, slot, prob) if chance is not None
           else np.zeros(slot.shape, np.uint8))
    cen = _centres(mtime)
    towns = _town_index(mtime, len(shell.places), shell.places)
    hot = []
    if chance is not None:
        seen = set()
        for j in np.argsort(-chance)[:12]:
            name, pick, la, lo = _area_name(int(j), cen, towns)
            if name not in seen:
                seen.add(name)
                hot.append({"j": int(j), "name": name, "select": pick, "lat": la, "lon": lo,
                            "p": float(chance[j])})
            if len(hot) == 6:
                break

    # ── KPI strip: Arunachal as a whole ────────────────────────────────────
    top = max(rp, key=lambda t: _river_p(t[1])) if rp else None
    high = sum(1 for _, xs in rp if _river_p(xs) >= CHANCE_CUTS[2])
    above = [r["station_name"] for r in rivers if r["above_threshold_now"]]
    off = [r["station_name"] for r in rivers if r.get("gauge_offline")]
    kpis = []
    if nh is not None:
        a = nh["arunachal_week"] if period < 0 else nh["arunachal_daily"][period]
        kpis.append(_tile("Flood anywhere", _pct_short(a), f"Arunachal · {when}", "outlook",
                          CHANCE_TEXT[_band(a)],
                          "Chance of at least one recorded flood somewhere in Arunachal. "
                          + _error_line(nh), "right"))
        n10 = int((chance >= 0.10).sum())
        kpis.append(_tile("Areas at 10%+", f"{n10}<small>/{len(chance):,}</small>",
                          f"~10 km areas · {when}", "outlook",
                          CHANCE_TEXT[3] if n10 else None,
                          "Areas about 10 km across that have ground a flood can reach, with "
                          "an outlook of 10% or more."))
    kpis.append(_tile("Rivers at 10%+", f"{high}<small>/{len(rp)}</small>", f"gauged · {when}",
                      "forecast", CHANCE_TEXT[3] if high else None,
                      "Gauged rivers with a 10% or higher chance of reaching their line"
                      + (" on their highest day this week." if period < 0 else " that day.")))
    if top:
        pt = _river_p(top[1])
        dt = max(top[1].items(), key=lambda t: t[1]["p"])[0]
        kpis.append(_tile("Highest river", _pct_short(pt),
                          f"{_esc(top[0]['station_name'])} · {_day_short(dt)}", "forecast",
                          CHANCE_TEXT[_band(pt)]))
    kpis.append(_tile("Above line now", f"{len(above)}", _esc(", ".join(above)) or "none",
                      "measured", "#ff5a73" if above else None,
                      "Rivers whose latest readings are already above their line.", "left"))
    kpis.append(_tile("Gauges reporting", f"{len(rivers) - len(off)}<small>/{len(rivers)}</small>",
                      f"{len(off)} offline" if off else "all online", "measured", None,
                      ("Offline: " + ", ".join(off) + ". Their chances rest on rain alone.")
                      if off else "Every gauge sent a complete day recently.", "left"))
    st.markdown(_tiles(kpis, len(kpis)), unsafe_allow_html=True)

    # ── main row: place | map | outlook + conditions ────────────────────
    cl, cm, cr = main_row()
    with cl, st.container(key="fs_col_l"):
        _place_card(sel, pl, snap, period, rp, fmeta, own, river_at, levels, hot)

    with cm, st.container(key="fs_col_m"):
        with st.container(border=True, key="fs_mapcard"):
            t1, t2 = st.columns([6, 1], vertical_alignment="center")
            with t1:
                st.markdown(
                    "<div class='map-head' style='padding:0'><div class='mh-dot'></div>"
                    f"<div class='mh-title'>Flood outlook · {when}</div>"
                    f"<div style='margin-left:10px;display:flex;gap:6px'>"
                    f"{badge('outlook', 'Colour on low ground.', 'down')}"
                    f"{badge('forecast', 'Gauges and their river stretches. Click a gauge for its forecast.', 'down')}</div>"
                    "</div>", unsafe_allow_html=True)
            with t2:
                with st.popover(":material/layers:", width="stretch", help="Map layers"):
                    show_rivers = st.toggle("Rivers", value=True, key="fs_lyr_rivers")
                    show_gauges = st.toggle("River gauges", value=True, key="fs_lyr_gauges")
                    show_labels = st.toggle("Place labels", value=True, key="fs_lyr_labels")
                    show_catch = st.toggle("Area draining to the place", value=True,
                                           key="fs_lyr_catch")
            box = st.container(height=MAP_H + 8, border=False, key="map_shell")
            m = M.base_map(grid, s)
            marker = (sel["lat"], sel["lon"], sel["label"]) if sel else None

            img = None
            b0 = _catchment_of(pl) if (sel and show_catch) else None
            if not s.bare:
                img = M.rgba_overlay(cls, CHANCE_COLORS)
                if b0 is not None:
                    area, edge = _upstream(b0)
                    base = np.zeros_like(img)
                    # a soft wash with a faint rim: at street zoom the 500 m
                    # cells show as steps, and a bright rim read as walls
                    base[area] = [127, 212, 240, 42]
                    base[edge] = [127, 212, 240, 95]
                    on = cls > 0
                    base[on] = img[on]
                    img = base

            # map labels: the selected place's neighbours, one per ~10 km
            # area; with nothing selected, the areas with the highest outlook
            labels = []
            if chance is not None and show_labels:
                if sel and pl is not None:
                    d = np.hypot((cen[0] - sel["lat"]) * 111.2,
                                 (cen[1] - sel["lon"]) * 111.2 * np.cos(np.radians(sel["lat"])))
                    near_j = [int(j) for j in np.argsort(d)[:10]
                              if d[j] < 26 and int(j) != (pl[2] if pl else -1)][:6]
                    seen = {sel["label"]}
                    for j in near_j:
                        name, _, la, lo = _area_name(j, cen, towns)
                        if name not in seen:
                            seen.add(name)
                            labels.append((name, la, lo, float(chance[j])))
                else:
                    labels = [(h["name"], h["lat"], h["lon"], h["p"]) for h in hot[:6]]
            # Labels never overlap: each one's box is measured in screen
            # pixels at the zoom it opens at (7 for the state, ~1 px per km;
            # 11 on a place, ~15 px per km) and dropped if it would touch one
            # already placed. Gauge labels go first — they are the checked
            # numbers — the own gauge and any river above its line first.
            ppk = 15.0 if sel else 0.93
            boxes: list[tuple] = []

            def _fits(lat, lon, text) -> bool:
                x = lon * 98.7 * ppk
                y = -lat * 110.6 * ppk
                b = (x - 10, y - 12, x + 52 + 6.6 * len(text), y + 12)
                if any(b[0] < o[2] and o[0] < b[2] and b[1] < o[3] and o[1] < b[3]
                       for o in boxes):
                    return False
                boxes.append(b)
                return True

            glabel = set()
            for r, p in sorted(((r, _river_p(xs)) for r, xs in rp),
                               key=lambda t: (not (own and t[0]["station_code"] == own[0]),
                                              not t[0]["above_threshold_now"], -t[1])):
                if ((p >= CHANCE_CUTS[0] or r["above_threshold_now"]
                     or (own and r["station_code"] == own[0]))
                        and _fits(r["lat"], r["lon"], r["station_name"])):
                    glabel.add(r["station_code"])
            labels = [lab for lab in labels if _fits(lab[1], lab[2], lab[0])]
            labels = labels[:4] if not sel else labels

            own_code = own[0] if own else None
            reach = {}
            gi_own = -1
            if link is not None and show_rivers:
                pmap = {r["station_code"]: (r, _river_p(xs)) for r, xs in rp}
                for gi, c in enumerate(codes):
                    if c in pmap:
                        r, p = pmap[c]
                        k = _band(p)
                        reach[gi] = (RIVER_QUIET if k == 0 else CHANCE_COLORS[k],
                                     f"{r['station_name']} gauge's stretch · {_pct(p)} chance "
                                     f"of reaching its line ({when}) · checked forecast")
                        if c == own_code:
                            gi_own = gi

            def _extras(fg):
                if show_rivers and geo.rivers:
                    from products.flood.data import load_static
                    chan = load_static()[3]
                    segs = _river_segments(
                        (len(geo.rivers.get("features", [])),
                         (DIR / "gauge_link.npz").stat().st_mtime
                         if (DIR / "gauge_link.npz").exists() else 0.0),
                        geo.rivers, grid, chan, link[0] if link is not None else None)
                    _draw_rivers(fg, segs, reach, gi_own)
                for name, la, lo, p in labels:
                    for mk in _place_label(name, la, lo, p, when):
                        mk.add_to(fg)
                if show_gauges:
                    for r, xs in rp:
                        p = _river_p(xs)
                        _gauge_marker(r, p, r["station_code"] in glabel, when,
                                      (levels.get(r["station_code"]) or {}).get("unit", "")
                                      ).add_to(fg)

            # the shared rivers layer stays off: this map draws its own
            fg = M.overlay_group(grid, replace(s, rivers=False), geo, img=img,
                                 districts=s.districts, marker=marker, extra=_extras)
            fly_c, fly_z = M.fly_to(sel, 11)
            with box:
                out = st_folium(m, height=MAP_H, use_container_width=True,
                                pixelated=True,
                                returned_objects=["last_clicked", "last_object_clicked",
                                                  "last_object_clicked_count"],
                                feature_group_to_add=fg, center=fly_c, zoom=fly_z,
                                key="flvmap")
            # A click on a gauge opens its card on the map and points the Rivers
            # graph below at it. Set before that graph's picker is built, so no
            # rerun is needed — and none wanted: the map stays as drawn, so the
            # card stays open. The count makes a second click on the same gauge
            # count again after the board has picked another one.
            obj = (out or {}).get("last_object_clicked")
            if obj:
                tag = ((out or {}).get("last_object_clicked_count"), obj["lat"], obj["lng"])
                if tag != st.session_state.get("flv_map_obj"):
                    st.session_state.flv_map_obj = tag
                    hit = next((r["station_code"] for r, _ in rp
                                if abs(r["lat"] - obj["lat"]) < 1e-6
                                and abs(r["lon"] - obj["lng"]) < 1e-6), None)
                    if hit:
                        st.session_state.flv_gauge = hit
            click = (out or {}).get("last_clicked")
            if click:
                xy = (round(float(click["lat"]), 5), round(float(click["lng"]), 5))
                if xy != st.session_state.get("clicked_xy"):
                    st.session_state.clicked_xy = xy
                    st.session_state.pending_place = f"{xy[0]:.4f}, {xy[1]:.4f}"
                    st.rerun()

            if s.bare:
                M.legend_strip([], [], bare=True)
            else:
                shown = cls > 0
                shares = [float((cls[shown] == i).mean()) if shown.any() else 0
                          for i in range(1, 6)]
                chips = "".join(
                    f"<div class='lg'><i style='background:{c}'></i>{w_} <span>{n_}</span>"
                    f"<b>{100*sh:.0f}%</b></div>"
                    for w_, n_, c, sh in zip(CHANCE_WORDS, CHANCE_NAMES, CHANCE_COLORS, shares))
                sym = (
                    "<span class='fs-sym'><svg width='12' height='12'><rect x='2' y='2' "
                    "width='8' height='8' transform='rotate(45 6 6)' fill='#dbe7f3' "
                    "stroke='#4d8dff' stroke-width='1.5'/></svg>gauge</span>"
                    f"<span class='fs-sym'><svg width='22' height='8'><line x1='0' y1='4' x2='22' "
                    f"y2='4' stroke='{RIVER_QUIET}' stroke-width='3'/></svg>gauged river</span>"
                    f"<span class='fs-sym'><svg width='22' height='8'><line x1='0' y1='4' x2='22' "
                    f"y2='4' stroke='{RIVER_OTHER}' stroke-width='2'/></svg>other river</span>"
                    + ("<span class='fs-sym'><svg width='16' height='12'><rect x='1' y='1' "
                       "width='14' height='10' rx='2' fill='rgba(127,212,240,.15)' "
                       "stroke='#7fd4f0' stroke-width='1.3'/></svg>drains here</span>"
                       if b0 is not None else ""))
                st.markdown(
                    f"<div class='fs-legend'>{chips}"
                    + _i("Colour: the outlook — chance of a flood within ~10 km — shown only "
                         "on low ground a flood can reach. The share is of that ground. Gauges "
                         "and their river stretches use the same scale for their checked "
                         "chance; a red halo means the river is above its line now.", "left")
                    + f"</div><div class='fs-legend' style='margin-top:6px'>{sym}</div>",
                    unsafe_allow_html=True)

    with cr, st.container(key="fs_col_r"):
        if nh is not None:
            if k_sel is not None:
                vals = [nh["week"][k_sel]] + [nh["daily"][i][k_sel] for i in range(len(days))]
                scope = "near " + sel["label"]
            else:
                vals = [nh["arunachal_week"]] + list(nh["arunachal_daily"])
                scope = "anywhere in Arunachal"
        else:
            vals, scope = None, ""
        with st.container(key="fs_r_a"):
            _outlook_buttons(days, vals, scope)
        with st.container(key="fs_r_b"):
            tab = st.segmented_control("Conditions", ["Rivers", "Rain", "Soil"],
                                       default="Rivers", key="flv_cond",
                                       label_visibility="collapsed", width="stretch")
            if tab == "Rain":
                _rain_panel(sel, pl)
            elif tab == "Soil":
                _soil_panel(snap, k_sel, sel)
            else:
                _rivers_panel(rp, levels, own[0] if own else None, days)

    # ── what changed · needs attention · track record ────────────────────
    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3, gap="medium")
    with c1:
        with st.container(border=True, key="fs_eq_1"):
            st.markdown(_changes(snap, k_sel, sel), unsafe_allow_html=True)
    with c2:
        with st.container(border=True, key="fs_eq_2"):
            st.markdown(_attention(snap, rp, rivers, chance, hot, when), unsafe_allow_html=True)
    with c3:
        with st.container(border=True, key="fs_eq_3"):
            st.markdown(_track(snap), unsafe_allow_html=True)

    # ── rivers: one gauge's graph | the board of all of them ─────────────
    rivers_by = {r["station_code"]: r for r in snap["rivers"]}
    if rivers_by:
        place_key = sel["label"] if sel else None
        if own and st.session_state.get("flv_gauge_place") != place_key and own[0] in rivers_by:
            st.session_state.flv_gauge = own[0]
            st.session_state.flv_gauge_place = place_key
        if st.session_state.get("flv_gauge") not in rivers_by:
            st.session_state.flv_gauge = max(rivers_by, key=lambda c: max(
                (x["p"] for x in rivers_by[c]["days"].values()), default=0.0))
        with st.container(border=True):
            st.markdown(_sec("Rivers", badge("measured", where="right"),
                             badge("forecast", where="right"),
                             note="click a row of the board to open its graph"),
                        unsafe_allow_html=True)
            gcol, bcol = st.columns([1.65, 1], gap="large")
            # the board first: a click on it picks the gauge the graph shows,
            # which must be set before the graph's picker is built
            with bcol:
                st.markdown(_sec("Every gauge × every day", note="chance, %"),
                            unsafe_allow_html=True)
                ev = st.altair_chart(_board(snap["rivers"], days), width="stretch",
                                     on_select="rerun", selection_mode="pick", key="fs_board")
                pts = ((ev or {}).get("selection") or {}).get("pick") or []
                code = pts[0].get("code") if pts and isinstance(pts[0], dict) else None
                if code and code != st.session_state.get("fs_board_last"):
                    st.session_state.fs_board_last = code
                    if code in rivers_by and code != st.session_state.get("flv_gauge"):
                        st.session_state.flv_gauge = code
                        st.rerun()
            with gcol:
                _gauge_detail(snap, levels, rivers_by, own)

    # ── folded away: the full table, reports, how to read ────────────────
    with st.expander("📋  All river gauges — table"):
        rows = []
        for r, xs in sorted(rp, key=lambda t: -_river_p(t[1])):
            d_, x = max(xs.items(), key=lambda t: t[1]["p"])
            lvl = r["last_day_max"]
            rows.append({
                "River gauge": r["station_name"],
                "Chance": x["p"],
                "Day": datetime.fromisoformat(d_).strftime("%a %d %b"),
                "Threshold": ("Official danger level" if r["official"]
                              else "River's own top 2% of days"),
                "Based on": x["basis"],
                "Last reading": (f"{lvl:,.2f} on {r['last_complete_day']} "
                                 f"(threshold {r['threshold']:,.2f})" if lvl is not None
                                 else f"gauge offline since {r['newest_reading_day']}"
                                 if r.get("gauge_offline") and r.get("newest_reading_day")
                                 else "gauge offline"),
                "Above now": "YES" if r["above_threshold_now"] else "",
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=360,
                     column_config={"Chance": st.column_config.ProgressColumn(
                         "Chance", min_value=0.0, max_value=1.0, format="percent")})

    _report_form(sel, grid)

    with st.expander("📖  How to read these numbers"):
        m_ = (nh or {}).get("measured_error") or {}
        st.markdown(
            "**Outlook ≈ — flood chance near here.** The chance of a flood within about 10 km "
            "of a place — for each day, and over the next 7 days — worked out from the "
            "forecast rain there and upstream, the shape of the land, and on flat ground how "
            "wet the soil already is"
            + (f", learned from every verified flood of {learned_years(snap)}"
               if learned_years(snap) else "")
            + ". It is **approximate**: tested on 2023–25 floods it had "
            "never seen, it was good at telling riskier places and weeks from quieter "
            + (f"ones (right about {100*m_['ranking_auc']:.0f} times in 100), but in the "
               f"ranges where most floods fell, the number that really happened ran between "
               f"{m_['happened_over_said_low']:.1f}× and {m_['happened_over_said_high']:.0f}× "
               f"what it said.{high_said_more(m_)} "
               if m_ else "ones, but its exact level was not steady from year to year. ")
            + "Treat the percentage as a guide, not an exact figure. It counts floods that "
            "were confirmed independently — by radar, satellite flood maps or river gauges — so "
            "floods nobody recorded, most often short flash floods in remote, steep valleys, "
            "are missing.\n\n"
            "**Forecast ✔ — river gauges.** The chance a gauged river reaches its line (the "
            "official CWC danger level, or the river's own wettest 2% of days), checked every "
            "day against the river's real level.\n\n"
            "**Estimate ◆ — if a flood comes.** How likely water is to reach an exact spot if "
            "a flood comes nearby: a property of the ground, not of the day. Capped at 20%+.\n\n"
            "**Measured ●, Input ☂, Record ◷** — gauge readings; the rain and soil wetness "
            "that feed the forecast; floods confirmed in the past.\n\n"
            "The numbers are never multiplied together. Days 4–7 rest on rain forecasts that "
            "are less reliable that far ahead. The full method and every tested figure: "
            "**How to read this forecast**, from the ℹ️ beside FloodSense in the sidebar.")
