"""The day's forecast, fetched from where the daily run publishes it.

The daily forecast runs in the cloud (Modal) every morning and publishes its
snapshot — the same live_forecast.json the app ships with — at one fixed,
read-only link. The app checks it about once an hour and, when it is a newer
issue than the copy on disk, puts it in that copy's place. Every page keeps
reading the file on disk as before, so nothing else changes.

Only the first check after the server starts makes the page wait (up to
FIRST_WAIT_S), so a visitor who wakes a sleeping app gets today's forecast,
not the bundled one. Later checks run in the background; the page picks the
new file up on its next rerun. The link can take several seconds to answer
when it has been idle.

If the link does not answer, nothing happens: the app shows the last copy it
has, which on a fresh start is the one bundled with the app. A forecast
never goes missing because the link is down; it only goes stale, and the
pages already say how old the forecast is. A failed check is tried again
after RETRY_S.

FLOOD_FEED_URL overrides the link; set it empty to switch fetching off.
"""
from __future__ import annotations

import json
import os
import threading
import time

import requests
import streamlit as st

from products.flood.data import DIR

SNAPSHOT = DIR / "live_forecast.json"
FEED_URL = os.environ.get("FLOOD_FEED_URL",
                          "https://pankajkarjay--slopesense-flood-latest.us-east.modal.run")
CHECK_EVERY_S = 3600
RETRY_S = 300
FIRST_WAIT_S = 10
TIMEOUT_S = 20


def _issue(snap: dict) -> tuple[str, str]:
    """Which issue a snapshot is: its day, then the time it was made."""
    return str(snap.get("issued_on", "")), str(snap.get("generated_at", ""))


def _apply(body: bytes) -> None:
    """Put the fetched snapshot on disk if it is a newer issue than the copy there."""
    new = json.loads(body)
    old = json.loads(SNAPSHOT.read_text()) if SNAPSHOT.exists() else {}
    if isinstance(new, dict) and new.get("days") and _issue(new) > _issue(old):
        tmp = SNAPSHOT.with_name(SNAPSHOT.name + ".part")
        tmp.write_bytes(body)
        os.replace(tmp, SNAPSHOT)


def _pull(state: dict) -> None:
    ok = False
    try:
        r = requests.get(FEED_URL, timeout=TIMEOUT_S)
        r.raise_for_status()
        if r.content != state["body"]:
            _apply(r.content)
            state["body"] = r.content
        ok = True
    except (requests.RequestException, OSError, ValueError):
        pass
    finally:
        state["next"] = time.time() + (CHECK_EVERY_S if ok else RETRY_S)
        state["busy"] = False


@st.cache_resource(show_spinner=False)
def _state() -> dict:
    """Shared by every visitor of this server: one check at a time."""
    return {"lock": threading.Lock(), "busy": False, "next": 0.0, "body": None, "first": True}


def refresh() -> None:
    if not FEED_URL:
        return
    state = _state()
    with state["lock"]:
        if state["busy"] or time.time() < state["next"]:
            return
        state["busy"] = True
        first, state["first"] = state["first"], False
    t = threading.Thread(target=_pull, args=(state,), daemon=True)
    t.start()
    if first:
        t.join(FIRST_WAIT_S)
