"""Every reading of each CWC gauge over the last 3 days, for the gauge graph's
"Last 3 days" view.

CWC's site does not answer from outside India, so the hosted app cannot ask
it. A small cloud job in India (scripts/cloud/modal_hourly.py) fetches every
gauge at twenty past each hour, saves every reading for good, and publishes
the last 3 days at one read-only link, read here.

If the link does not answer, the view says so and the 30-day graph is
unchanged: nothing else on the page depends on this.

FLOOD_HOURLY_URL overrides the link; set it empty to switch it off.
"""
from __future__ import annotations

import os

import requests
import streamlit as st

URL = os.environ.get("FLOOD_HOURLY_URL",
                     "https://pankajkarjay--slopesense-gauge-hourly.us-east.modal.run")


@st.cache_data(ttl=600, show_spinner=False)
def latest() -> dict | None:
    """{"made_at", "hours", "gauges": {code: [[iso time, level], ...]}}, or None."""
    if not URL:
        return None
    try:
        r = requests.get(URL, timeout=15)
        r.raise_for_status()
        d = r.json()
        return d if isinstance(d, dict) and "gauges" in d else None
    except (requests.RequestException, ValueError):
        return None
