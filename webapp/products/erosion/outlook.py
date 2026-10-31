"""SoilSense's weekly erosive-rain outlook (EROSION_PLAN.md, "E2.1 part 1").

Next week's forecast rain (Open-Meteo, the live feed SlideSense and FloodSense
share) is turned into daily erosivity with InRESatE's model, EI = a * P^b, and set
against the SAME source's history at the same point:

    share     this week's EI as a share of an average year's (dimensionless, so
              Open-Meteo's wetness against satellite rain cancels to first order)
    x normal  that share against the usual share for these days of the year
    loss      share x the erosion map's yearly loss, per catchment and district

Fixed inputs come from scripts/build/erosion_outlook_base.py
(assets/erosion/<region>/outlook_base.npz). Pure numpy, like the rest of the app.
"""
from __future__ import annotations

import json
from datetime import date

import numpy as np
import streamlit as st

from core.rainfall import forecast_days, load_forecast
from products.erosion.data import ROOT


@st.cache_data(show_spinner=False)
def base(region: str):
    d = ROOT / region
    if not (d / "outlook_base.npz").exists():
        return None
    z = np.load(d / "outlook_base.npz")
    return {k: z[k] for k in z.files}, json.loads((d / "outlook_meta.json").read_text())


def compute(z: dict, days, rain) -> dict:
    """The week from a forecast: (days, rain[n_days, n_points])."""
    idx = forecast_days(days)
    p = np.maximum(np.nan_to_num(rain[idx]), 0.0)
    share_day = z["a"][None] * np.power(p, z["b"][None]) / z["ei_year"][None]
    share = share_day.sum(axis=0)
    d0 = date.fromisoformat(str(days[idx[0]])[:10])
    normal = z["season"][d0.timetuple().tm_yday - 1]

    def unit(prefix, n):
        u, pp, v = z[f"{prefix}_u"], z[f"{prefix}_p"].astype(int), z[f"{prefix}_v"]
        wk = np.bincount(u, weights=v * share[pp], minlength=n)
        nm = np.bincount(u, weights=v * normal[pp], minlength=n)
        with np.errstate(invalid="ignore", divide="ignore"):
            return wk, np.where(nm > 0, wk / nm, np.nan)

    n_dis = int(z["dis_n"])
    cat_wk, cat_x = unit("cat", len(z["cat_id"]))
    dis_wk, dis_x = unit("dis", n_dis)
    st_w = z["state"]
    return {"days": [str(days[i])[:10] for i in idx], "start": d0, "rain_mm": p.sum(axis=0),
            "rain_day_mm": p, "share": share, "normal": normal,
            "x_normal": np.where(normal > 0, share / normal, np.nan),
            "cat_week": cat_wk, "cat_x": cat_x, "dis_week": dis_wk, "dis_x": dis_x,
            "state_week": float((st_w * share).sum()),
            "state_x": float((st_w * share).sum() / max((st_w * normal).sum(), 1e-12)),
            "state_day": (st_w[None] * share_day).sum(axis=1),
            "state_share": float(np.average(share, weights=st_w)) if st_w.sum() > 0 else float(share.mean())}


def week(region: str) -> dict | None:
    """This week's outlook, or None without a base, or {'error': ...} without rain."""
    b = base(region)
    if b is None:
        return None
    z, meta = b
    fc = load_forecast(tuple(float(x) for x in z["lat"]), tuple(float(x) for x in z["lon"]))
    if fc is None:
        return {"error": "The live rain forecast could not be fetched just now."}
    days, rain = fc
    out = compute(z, days, rain)
    out["meta"], out["z"] = meta, z
    return out
