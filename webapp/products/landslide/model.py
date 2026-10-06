"""Landslide maths — deliberately free of Streamlit so it can be tested.

    hazard = susceptibility (where, static) x trigger (when, daily)

⚠️ The rainfall half moved to core.rainfall. Fetching live rain and scoring it
against each point's own climatology is not a landslide idea — FloodSense reads
the same points — so it belongs to the spine. It is re-exported below so
this module still reads as one forecast.
"""
from __future__ import annotations

import numpy as np

from core.rainfall import (FEATURES, fetch_rain, rolling_totals,  # noqa: F401
                           to_percentile, trigger_series)


def hazard_raster(susceptibility_u8: np.ndarray, nearest: np.ndarray,
                  trigger_pts: np.ndarray) -> np.ndarray:
    """hazard = susceptibility x trigger, as float32 with NaN outside the domain.

    Both terms are needed and neither is enough on its own: a cliff in dry
    weather does not fail, and a downpour on flat stable ground does nothing.
    Multiplying keeps that — near-zero in either term gives near-zero hazard.

    ⚠️ 255 means "not assessed" (ice, open water, slope <= 10 deg). Those cells
    stay NaN and must render as grey, never as "low risk" — the model never saw
    that terrain and has no business scoring it.
    """
    sus = susceptibility_u8.astype(np.float32)
    sus[susceptibility_u8 == 255] = np.nan
    sus /= 254.0
    return sus * trigger_pts[nearest]


def nearest_assessed(sus: np.ndarray, r: int, c: int, max_cells: int = 10):
    """Nearest cell the model actually scored. (row, col, distance_in_cells).

    ⚠️ 12% of Arunachal's 4,648 settlements sit on a cell scored 255 — valley
    floors, riverbanks, anything flatter than 10 degrees. Those are exactly the
    towns people search for, and returning "not assessed" is a dead end that is
    also physically misleading: what threatens a valley town is the slope ABOVE
    it, not the flat ground it is built on.

    So the search snaps to the closest scored cell — and the caller must SAY it
    snapped, with the distance. Silently moving someone's location would be the
    dishonest version of this.

    Returns None if nothing is assessed within max_cells, which is the right
    answer for the middle of a large river or a high snowfield.
    """
    if sus[r, c] != 255:
        return r, c, 0.0
    h, w = sus.shape
    r0, r1 = max(r - max_cells, 0), min(r + max_cells + 1, h)
    c0, c1 = max(c - max_cells, 0), min(c + max_cells + 1, w)
    ok = np.argwhere(sus[r0:r1, c0:c1] != 255)
    if ok.size == 0:
        return None
    d = (ok[:, 0] + r0 - r) ** 2 + (ok[:, 1] + c0 - c) ** 2
    i = int(np.argmin(d))
    return int(ok[i, 0] + r0), int(ok[i, 1] + c0), float(np.sqrt(d[i]))


def classify(h: np.ndarray, breaks_pct=(50, 75, 90, 97)) -> np.ndarray:
    """1..5 by fixed hazard cuts; 0 = not assessed.

    Cuts are deliberately top-heavy rather than equal fifths: Very High is ~3%
    of the state, which is what makes the map actionable instead of colouring a
    fifth of Arunachal red.
    """
    cuts = np.array([0.02, 0.06, 0.15, 0.30], dtype=np.float32)
    out = np.zeros(h.shape, dtype=np.uint8)
    ok = np.isfinite(h)
    out[ok] = (np.digitize(h[ok], cuts) + 1).astype(np.uint8)
    return out
