"""Where the visitor is, and where they asked about.

Shared because a forecast is only useful somewhere, and that is as true of a
flood as of a landslide. The gazetteer, the browser geolocation handshake and
the one-selection rule all belong to the platform, not to either hazard.

⚠️ Order matters and is why this runs from the shell rather than from a page:
every session-state write here must happen BEFORE the search widget is built,
and the search widget lives inside a product page.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

import core.geo as G
from core.grid import Grid


# The part that runs in the browser: it asks for the position and sends the
# answer back as this component's value (geo_component/index.html).
#
# ⚠️ It replaced a script that wrote the answer into the page's address
# (2026-10-12). Streamlit runs such a script in a sandboxed frame, and a
# sandboxed frame is not allowed to change the address of the page around
# it, so the answer never arrived and the 📍 button did nothing at all, in
# every browser. A component's value needs no such permission.
_ASK = components.declare_component(
    "visitor_position", path=str(Path(__file__).parent / "geo_component"))
_STATES = ("ok", "denied", "failed", "unsupported")


@st.cache_data(show_spinner=False)
def load_places(_towns, _districts):
    """4,648 settlements + 18 districts as one searchable list.

    Cached because it sorts and de-duplicates the whole gazetteer, and it never
    changes within a deployment.
    """
    places = G.build_places(_towns, _districts)
    return places, {p["label"]: p for p in places}


@dataclass
class Locator:
    places: list
    place_idx: dict
    lookup: dict
    me: dict | None
    geo_state: str | None
    user_pt: tuple | None
    user_inside: bool


def resolve_visitor(grid: Grid, towns, districts) -> Locator:
    """Run the whole location handshake, once per rerun, before any widget.

    ⚠️ OPT-IN ONLY. The page never asks where you are on load — the request
    fires solely when the 📍 button is pressed (ask_again). Asking unprompted
    throws a browser permission prompt at a visitor who only wanted to look
    at a map, and it made the app open on a personal location without anyone
    choosing it.

    A press mounts one asking component. Every outcome — allowed, refused,
    timed out, unsupported — comes back as its value, is kept in the session
    and the component is not drawn again, so the browser is asked once per
    press. note() tells the visitor what became of it.
    """
    places, place_idx = load_places(towns, districts)

    ss = st.session_state
    if ss.get("geo_pending"):
        # Keyed by the press, so a second press asks afresh. The container
        # is taken out of the page's flow (theme.py, .st-key-geo_ask): the
        # component shows nothing, and left in the flow it pushed the whole
        # page down a row while the browser was being asked.
        with st.container(key="geo_ask"):
            got = _ASK(key=f"geo_ask_{ss.get('geo_n', 0)}", default=None)
        if isinstance(got, dict) and got.get("state") in _STATES:
            ss.geo_answer = got
            ss.geo_pending = False
            st.rerun()          # draw the page without the asking component
    ans = ss.get("geo_answer") or {}
    geo_state = "ask" if ss.get("geo_pending") else ans.get("state")
    user_pt = None
    if geo_state == "ok":
        try:
            user_pt = (float(ans["lat"]), float(ans["lon"]))
        except (KeyError, TypeError, ValueError):
            geo_state, user_pt = "failed", None
    # A position (or a refusal) can still be given in the address, as
    # ?geo=ok&lat=..&lon=.. — links and the screen checks use it. A press of
    # the button always wins over it.
    qp = st.query_params
    if geo_state is None and qp.get("geo") in _STATES:
        geo_state = qp["geo"]
        if geo_state == "ok":
            try:
                user_pt = (float(qp["lat"]), float(qp["lon"]))
            except (KeyError, ValueError):
                geo_state, user_pt = None, None
    user_inside = bool(user_pt and G.in_area(user_pt[0], user_pt[1],
                                             {"west": grid.west, "east": grid.east,
                                              "south": grid.south, "north": grid.north}))

    me = _me_place(user_pt, user_inside, places)
    # note() speaks only of what a press of the button brought back, or of a
    # position: a refusal merely written in the address is nobody's refusal
    pressed = bool(ss.get("geo_pending") or ans)
    ss.geo_note = (geo_state if (pressed or geo_state == "ok") else None,
                   user_pt, user_inside)

    # Nothing is selected until someone chooses. The forecast is about a place,
    # and picking one for the visitor — their own position or a default town —
    # is a claim we have no business making before they ask.
    if "search" not in st.session_state:
        st.session_state.search = G.PROMPT

    # Adopt the located position ONCE. Without the flag the query string, which
    # survives every rerun, would keep re-selecting it and undo any later search.
    if me and not st.session_state.get("geo_applied"):
        st.session_state.geo_applied = True
        st.session_state.pending_place = me["label"]

    # ⚠️ A map click selects a place, but the click only comes back AFTER the
    # search box has already been built this run — and Streamlit REFUSES to let
    # a widget's session_state be written once the widget exists:
    #     StreamlitAPIException: `st.session_state.search` cannot be modified
    #     after the widget with key `search` is instantiated.
    # So a click parks its coordinates here and the next run adopts them, above,
    # before the box is created. An earlier "use this point" button wrote
    # `search` directly from inside the panel and would have crashed the app.
    if "pending_place" in st.session_state:
        st.session_state.search = st.session_state.pop("pending_place")

    # Two lookups on purpose, and they are NOT interchangeable:
    #   place_idx — the gazetteer alone, which decides whether a label needs
    #               adding to the dropdown's option list.
    #   lookup    — everything resolvable, gazetteer PLUS "My location — near X".
    # Collapsing them broke the single most common path: a visitor standing in
    # Arunachal got "could not read that place", because their own position has
    # a label no gazetteer contains.
    lookup = dict(place_idx)
    if me:
        lookup[me["label"]] = me

    return Locator(places=places, place_idx=place_idx, lookup=lookup, me=me,
                   geo_state=geo_state, user_pt=user_pt, user_inside=user_inside)


def _me_place(user_pt, user_inside, places) -> dict | None:
    """The visitor's own position as a selectable place.

    Only ever built when the browser answered AND the answer lands inside the
    forecast area. Outside Arunachal there is nothing to forecast, so there is
    no place to offer — the app says so rather than quietly snapping to a
    nearby town the visitor never asked for.
    """
    if not user_inside:
        return None
    near, km = G.nearest_place(user_pt[0], user_pt[1], places)
    label = (f"My location — near {near['label']}" if near and km < 25
             else f"My location — {user_pt[0]:.3f}°N, {user_pt[1]:.3f}°E")
    return {"label": label, "lat": user_pt[0], "lon": user_pt[1], "kind": "me"}


def ask_again() -> None:
    """A press of 📍: ask the browser, afresh, on the next run. The last
    answer is dropped so a second press does not silently reuse it."""
    ss = st.session_state
    ss.geo_n = ss.get("geo_n", 0) + 1
    ss.geo_pending = True
    for k in ("geo_answer", "geo_applied"):
        ss.pop(k, None)
    for k in ("geo", "lat", "lon"):
        if k in st.query_params:
            del st.query_params[k]


def note(sel) -> None:
    """What became of a press on 📍, said under the search row.

    Until 2026-10-12 only one page said anything, far down it, and only for
    two of the outcomes — so a refusal, a timeout or a position outside the
    state all looked the same as a button that does nothing.
    """
    state, pt, inside = st.session_state.get("geo_note") or (None, None, False)
    if state == "ask":
        st.info("Waiting for your browser to share your location. If it asks, choose "
                "**Allow**.")
    elif sel is not None or state is None:
        return
    elif state == "ok" and pt and not inside:
        st.info(f"You appear to be at {pt[0]:.2f}°N, {pt[1]:.2f}°E, **outside Arunachal "
                "Pradesh**. This forecast covers Arunachal only, so nothing has been "
                "selected. Search a place above, or click anywhere on the map.")
    elif state == "denied":
        st.warning("Your browser did not allow this site to see your location. Allow "
                   "location for this site (the icon beside the address), then press 📍 "
                   "again. Or search a place above, or click the map.")
    elif state == "failed":
        st.warning("Your browser could not work out where you are. Press 📍 to try again, "
                   "search a place above, or click the map.")
    elif state == "unsupported":
        st.warning("This browser cannot share a location. Search a place above, or click "
                   "the map.")
