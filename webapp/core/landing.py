"""The home page's story — the idea behind the platform, told in five parts.

The first screen of the home page stays what it was: the platform's name and
the module tiles, so someone who only wants a forecast is one click away
(app.py draws that). Everything BELOW it is here: the same story, in the same
order and the same words, as the presenter's script
(docs/PRESENTATION_SCRIPT.md, slide by slide), so the page
can be presented from directly:

    1 The problem      the facts exist, in pieces; nobody keeps score
    2 The idea         do the hard part once, on one shared map
    3 How it works     five steps and a way back; the rules we keep
    4 Running today    a product is a question; the two products; "2 files";
                       "More about SlideSense / FloodSense"
    5 What comes next  more hazards, places, users; stronger every season

Rules for what may be written here (it is a PUBLIC page):
  - no accuracy figures and no built/planned status board — the same rule as
    the client deck; each product is described by what it asks and gives;
  - the "More about" panels are kept to what a visitor needs: what a module
    answers, what is on its screens, how to read it and who it is for;
  - anything not live is drawn dashed and called planned;
  - no state other than Arunachal is named; soil erosion may be named as
    the next hazard;
  - the three figures (sources, squares, years of rain) are read or fixed in
    one place, below, and nowhere else.

The look: the app's own teal and blue stay the main colours. The company's
(beesolutions.in: gold #F5A623 on near-black, the bee mark, small technical
labels in Space Grotesk) is a light touch only — a by-line, the labels, the
closing block. Gold is warm and so is the hazard ramp, so it is kept away
from anything that shows a level.

Every block is ONE line of HTML: st.markdown treats an indented or blank
line inside HTML as Markdown (a code block), which is how a diagram turns
into grey text. _c() does the flattening.

Design note: docs/design/LANDING_PAGE.md.
"""
from __future__ import annotations

import base64
import json
import re
from urllib.parse import quote

import streamlit as st

from core.bundle import ASSETS

SHOTS = ASSETS / "landing"
COMPANY_URL = "https://www.beesolutions.in"

# The figures the page states. Sources are counted from the catalogue the
# Data Backbone module shows; the other two are properties of the grid and of
# the rain archive (8,202,343 in-state cells at 100 m; daily rain from 2000).
SQUARES = "8.2 million"
RAIN_YEARS = "26 years"

SECTIONS = [("problem", "The problem"), ("idea", "The idea"), ("how", "How it works"),
            ("today", "Running today"), ("next", "What comes next")]

_TAGS = [(r"<p class='", "<div class='lp-p "), (r"<p>", "<div class='lp-p'>"), (r"</p>", "</div>"),
         (r"<h([23]) class='", r"<div role='heading' aria-level='\1' class='lp-h\1 "),
         (r"<h([23])>", r"<div role='heading' aria-level='\1' class='lp-h\1'>"), (r"</h[23]>", "</div>"),
         (r"<[uo]l class='([^']*)'>", r"<div role='list' class='\1'>"), (r"</[uo]l>", "</div>"),
         (r"<li>", "<div role='listitem' class='lp-li'>"), (r"</li>", "</div>")]


def _c(s: str) -> str:
    """One line, no indentation — see the module note. Also swaps p, h2, h3,
    ul, ol and li for plain divs with the same role: Streamlit styles those
    tags itself (font size, margins, a link icon and an inner span on every
    heading) and its rules outrank a single class. The blocks below are
    written with the ordinary tags so they stay readable."""
    s = " ".join(line.strip() for line in s.strip().splitlines() if line.strip())
    for a, b in _TAGS:
        s = re.sub(a, b, s)
    return s


def _ic(name: str) -> str:
    return f"<i class='lp-ic lp-ic-{name}'></i>"


@st.cache_data(show_spinner=False)
def n_sources() -> int | None:
    p = ASSETS / "backbone" / "catalogue.json"
    try:
        return int(json.loads(p.read_text(encoding="utf-8"))["n_sources"])
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def shots_css() -> str:
    """The pictures as CSS backgrounds: the two module screens (retake them
    with scripts/run/capture_landing_shots.py) and the company's bee mark. A
    missing file just leaves the space empty: the page must never fail over
    a picture."""
    rules = []
    for cls, name in (("lp-shot-slidesense", "slidesense"), ("lp-shot-floodsense", "floodsense"),
                      ("lp-bee", "bee")):
        p = SHOTS / f"{name}.webp"
        if p.exists():
            b64 = base64.b64encode(p.read_bytes()).decode()
            rules.append(f".{cls}{{background-image:url(data:image/webp;base64,{b64})}}")
    return "<style>" + "".join(rules) + "</style>"


# ───────────────────────────── the pieces ────────────────────────────────────
def nav() -> str:
    links = "".join(f"<a href='#lp-{k}'><i>{i}</i>{t}</a>" for i, (k, t) in enumerate(SECTIONS, 1))
    # The company's mark floats in the top left corner, like the jump bar. On a
    # narrow window there is no room beside the bar, so there the mark rides
    # inside it as its first item instead (the corner one is hidden).
    bee = (f"<a class='lp-nav-bee' href='{COMPANY_URL}' target='_blank' rel='noopener' "
           f"title='Built by BEE Solutions'><i class='lp-bee'></i></a>")
    return _c(f"<nav class='lp-nav' aria-label='The story'>{bee}<a class='lp-nav-top' href='#lp-top' "
              f"title='Back to the top'>◎</a>{links}</nav>"
              f"<a class='lp-brand' href='{COMPANY_URL}' target='_blank' rel='noopener' "
              f"title='Built by BEE Solutions'><i class='lp-bee'></i><span><em>BEE</em> Solutions</span></a>")


def hero_lede() -> str:
    return _c(f"""
    <div class='lp-lede'><b>One shared data backbone for mountain hazards.</b>
    <span>From fragmented mountain data to actionable intelligence.</span></div>""")


def hero_cue() -> str:
    return _c("<div class='lp-cue-row'><a class='lp-cue' href='#lp-problem'>The idea behind it<i>↓</i></a></div>")


def _head(n: int, key: str, eyebrow: str, title: str, lede: str = "") -> str:
    return (f"<div class='lp-head' id='lp-{key}'><p class='lp-eyebrow'><i>0{n}</i>{eyebrow}</p>"
            f"<h2>{title}</h2>" + (f"<p class='lp-sub'>{lede}</p>" if lede else "") + "</div>")


def problem() -> str:
    srcs = [("fine", "Ground height", "every 30 m"), ("mid", "Soil", "every 250 m"),
            ("coarse", "Rain", "every 11 km"), ("shape", "Rock types", "outlines"),
            ("line", "Rivers, roads", "lines"), ("dots", "River gauges", "single points")]
    walls = [("pieces", "Data in pieces", "A dozen agencies, a dozen formats"),
             ("restart", "Starts from zero", "Every project, every time"),
             ("clock", "Maps go stale", "Rain and rivers change daily"),
             ("score", "Nobody keeps score", "Forecasts are never checked")]
    return _c(f"""
    <section class='lp-sec'>
    {_head(1, "problem", "The problem", "The facts already exist. They do not fit together.",
           "All of it has been measured. It sits with a dozen agencies, in a dozen shapes.")}
    <div class='lp-two lp-two-top'>
      <div>
        <div class='lp-srcs' role='img' aria-label='Six kinds of source data, each in a different shape and scale.'>
          {"".join(f"<div class='lp-src'><div class='lp-g lp-g-{g}'></div><b>{a}</b><span>{b}</span></div>"
                   for g, a, b in srcs)}
        </div>
        <p class='lp-cap'>Six sources, six shapes. None lines up with the next.</p>
      </div>
      <div>
        <div class='lp-tiles2'>
          {"".join(f"<div class='lp-tile'>{_ic(ic)}<b>{a}</b><span>{b}</span></div>" for ic, a, b in walls)}
        </div>
        <p class='lp-result'><i>→</i>Static maps. One-off studies. Pilots that never scale.</p>
      </div>
    </div>
    </section>""")


def idea() -> str:
    verbs = [("down", "Collect", "every useful source"), ("shield", "Check", "before trusting it"),
             ("grid", "Line up", "on one shared map"), ("clock", "Keep current", "every day")]
    layers = [("rain", "Rain"), ("river", "Rivers and gauges"), ("soil", "Soil and land cover"),
              ("ground", "Ground shape")]
    return _c(f"""
    <section class='lp-sec'>
    {_head(2, "idea", "The idea", "Do the hard part <em>once</em>. Build everything on top.")}
    <div class='lp-two'>
      <div>
        <div class='lp-tiles2 lp-verbs'>
          {"".join(f"<div class='lp-tile'><span class='lp-step'>{i}</span>{_ic(ic)}<b>{a}</b><span>{b}</span></div>"
                   for i, (ic, a, b) in enumerate(verbs, 1))}
        </div>
        <div class='lp-card lp-football'><div class='lp-sq'></div>
        <p><b>{SQUARES} squares</b>, each the size of a football field. Every source is one more
        layer on the same squares.</p></div>
      </div>
      <div class='lp-stack-wrap'>
        <div class='lp-ontop'><em>Built on top</em><span class='lp-chip slope'>SlideSense</span>
        <span class='lp-chip flood'>FloodSense</span><span class='lp-chip plan'>next</span></div>
        <div class='lp-stack' role='img' aria-label='Four layers of data stacked on the same grid of
        squares: rain, rivers and gauges, soil and land cover, ground shape. A dashed line runs
        straight down through one square on every layer.'>
          {"".join(f"<div class='lp-plane lp-plane-{k}' style='--i:{i}'><b></b></div>"
                   f"<span class='lp-plane-l' style='--i:{i}'>{t}</span>"
                   for i, (k, t) in enumerate(layers))}
          <div class='lp-plumb'></div>
        </div>
        <p class='lp-cap'>One square of ground, read straight down: every fact about it.</p>
      </div>
    </div>
    </section>""")


def how() -> str:
    nodes = [("down", "Collect", "Satellites, maps, gauges, live weather"),
             ("file", "Keep", "The original, untouched"),
             ("grid", "Line up", "Fitted to one shared map"),
             ("shelves", "Shelve", "Ready data · forecasts"),
             ("send", "Serve", "Products read from here")]
    rules = [("grid", "One map for everything", "Products never disagree about a place."),
             ("file", "Keep the original", "Any number traces back to its source."),
             ("shield", "Check before trusting", "Every source is tested first."),
             ("ask", "No hazard built in", "A product brings its own question."),
             ("shelves", "Two shelves", "Base data to build on. Forecasts to decide with."),
             ("loop", "Close the loop", "Every forecast is graded.")]
    n = n_sources()
    stats = ([(str(n), "sources lined up")] if n else []) + [
        (SQUARES, "squares on the shared map"), (RAIN_YEARS, "of daily rain, for every place")]
    return _c(f"""
    <section class='lp-sec'>
    {_head(3, "how", "How it works", "One pipeline, and a way back")}
    <div class='lp-pipe'>
      {"".join(f"<div class='lp-node{' serve' if i == 5 else ''}'><div class='lp-node-top'>{_ic(ic)}<span>0{i}</span></div>"
               f"<h3>{a}</h3><p>{b}</p></div>" for i, (ic, a, b) in enumerate(nodes, 1))}
    </div>
    <div class='lp-return'><span>Every forecast is <b>written down, then checked</b> against what really
    happened.</span><em>comes back in as data</em></div>
    <div class='lp-stats'>
      {"".join(f"<div><b>{a}</b><span>{b}</span></div>" for a, b in stats)}
    </div>
    <p class='lp-mini'>Why you can trust it · rules we keep in mind</p>
    <div class='lp-rules'>
      {"".join(f"<div class='lp-rule'>{_ic(ic)}<div><h3>{a}</h3><p>{b}</p></div></div>" for ic, a, b in rules)}
    </div>
    </section>""")


def backbone_card(accent: str) -> str:
    """Sits beside the real 'Open' button for the Data Backbone module."""
    return _c(f"""
    <div class='lp-prod lp-bone' style='--tile:{accent}'>
      <div><h3 class='lp-prod-name'>Data Backbone</h3>
      <p class='lp-prod-tag'>See it for yourself: every source, on record. Every layer, on one map.</p></div>
    </div>""")


def today_head() -> str:
    rows = [("slope", "SlideSense", "", "Weak ground", "Unusual rain for that place"),
            ("flood", "FloodSense", "", "Ground that water can reach", "Rain upstream and the river's level"),
            ("plan", "Soil erosion", "<small>next</small>", "Slope, soil and plant cover", "How hard the rain falls")]
    return _c(f"""
    <section class='lp-sec lp-sec-open'>
    {_head(4, "today", "Running today", "A product is a question asked of the backbone",
           "Every hazard has the same shape. A product only brings the question.")}
    <div class='lp-eq'>
      <div class='lp-eqb'>{_ic("pin")}<b>WHERE</b><span>can it happen?</span><small>The ground · barely changes</small></div>
      <div class='lp-op'>×</div>
      <div class='lp-eqb'>{_ic("rain")}<b>WHEN</b><span>is something setting it off?</span><small>Rain, rivers · change daily</small></div>
      <div class='lp-op'>=</div>
      <div class='lp-eqb out'>{_ic("calendar")}<b>Forecast</b><span>place by place</span><small>The next seven days</small></div>
    </div>
    <div class='lp-qrows'>
      {"".join(f"<div class='lp-qrow {c}'><b>{n}{tag}</b><span>{a}</span><i>×</i><span>{b}</span></div>"
               for c, n, tag, a, b in rows)}
    </div>
    </section>""")


PRODUCTS = {
    "landslide": dict(
        cls="slope", shot="slidesense", kind="Product one · the landslide forecast",
        ask="Weak ground <em>×</em> unusual rain",
        pts=["A <b>7-day outlook</b> for any place or road",
             "A map in <b>five levels</b>. \"High\" means look here first",
             "Learned from the state's <b>own landslide record</b>"],
        reads=["Ground shape", "Soil", "Rock types", "Land cover", "Rain history", "Live rain"],
        alt="SlideSense screen: the landslide outlook for Itanagar over seven days, beside a map "
            "coloured from very low to very high."),
    "flood": dict(
        cls="flood", shot="floodsense", kind="Product two · the flood forecast",
        ask="Ground water can reach <em>×</em> rain and the river",
        pts=["A <b>7-day flood outlook</b> for any place",
             "Follows the <b>river gauges</b> on its own rivers",
             "<b>Runs by itself</b> every morning, and keeps its own record"],
        reads=["Ground shape", "Drainage", "Rain history", "Live rain", "River gauges", "Forecast log"],
        alt="FloodSense screen: the flood outlook for Pasighat over the next seven days, with river "
            "gauges on a map."),
}


def product_card(slug: str, name: str, accent: str) -> str:
    """One product, above its real 'Open' button. Carries the classes the
    click-to-cover splash reads the module's name and colour from."""
    p = PRODUCTS[slug]
    return _c(f"""
    <div class='lp-prod {p["cls"]}' style='--tile:{accent}'>
      <p class='lp-prod-kind'>{p["kind"]}</p>
      <h3 class='lp-prod-name'>{name}</h3>
      <p class='lp-prod-tag lp-ask'>{p["ask"]}</p>
      <div class='lp-frame'><div class='lp-bar'><i></i><i></i><i></i></div>
      <div class='lp-shot lp-shot-{p["shot"]}' role='img' aria-label='{p["alt"]}'></div></div>
      <ul class='lp-pts'>{"".join(f"<li>{x}</li>" for x in p["pts"])}</ul>
      <div class='lp-reads'><em>Reads from the backbone</em>
      {"".join(f"<span class='lp-chip'>{x}</span>" for x in p["reads"])}</div>
    </div>""")


def saving() -> str:
    # s = SlideSense, f = FloodSense, p = planned, h = in part, - = not needed
    rows = [("Ground shape", "s", "f", "p"), ("Drainage and rivers", "s", "f", "p"),
            ("Soil and land cover", "s", "-", "p"), (f"Rain history, {RAIN_YEARS}", "s", "f", "p"),
            ("Live rain, 7 days ahead", "s", "f", "p"), ("River gauges", "-", "f", "-"),
            ("Roads, places, search", "s", "f", "p"), ("Forecast log and grading", "h", "f", "p")]
    dot = {"s": "<i class='lp-dot s'></i>", "f": "<i class='lp-dot f'></i>", "p": "<i class='lp-dot p'></i>",
           "h": "<i class='lp-dot h'></i>", "-": "<i class='lp-dash'></i>"}
    return _c(f"""
    <section class='lp-sec lp-sec-cont'>
    <p class='lp-mini'>The saving · the same layers, reused by every product</p>
    <div class='lp-two lp-reuse'>
      <div>
        <table class='lp-matrix'>
          <thead><tr><th>Backbone layer</th><th>SlideSense</th><th>FloodSense</th><th>Soil erosion</th></tr></thead>
          <tbody>{"".join(f"<tr><td>{a}</td><td>{dot[b]}</td><td>{dot[c]}</td><td>{dot[d]}</td></tr>"
                          for a, b, c, d in rows)}</tbody>
        </table>
        <div class='lp-legend'><span><i class='lp-dot s'></i>uses it today</span>
        <span><i class='lp-dot h'></i>in part</span><span><i class='lp-dot p'></i>planned</span>
        <span><i class='lp-dash'></i>not needed</span></div>
      </div>
      <div class='lp-card lp-big'>
        <span class='lp-grad'>2<small>files</small></span>
        <p>is all the flood forecast <b>added of its own</b>.</p>
        <p class='lp-also'><b>One rain fetch</b> serves both products.</p>
      </div>
    </div>
    </section>""")


# "More about …": what a module answers, what is on its screens, how to read
# it and who it is for. The method and the testing have their own pages
# inside each module.
LEVELS = [("#1a9850", "Very Low"), ("#a6d96a", "Low"), ("#fee08b", "Moderate"),
          ("#f46d43", "High"), ("#a50026", "Very High")]
CHANCES = [("#5b6573", "Very low"), ("#fee08b", "Low"), ("#fdae61", "Moderate"),
           ("#f46d43", "Elevated"), ("#a50026", "High")]
MORE = {
    "landslide": dict(
        cls="slope", name="SlideSense", what="the landslide forecast",
        asks=["Is the road I depend on likely to be hit this week?",
              "Which districts should we watch today, and tomorrow?",
              "Where is the ground weakest, whatever the weather?"],
        screens=[("calendar", "Forecast", "A seven-day outlook for any town, village or point on the map"),
                 ("road", "Roads", "Kilometres of main road at High or above, and any route between two towns"),
                 ("mountain", "Susceptibility", "How weak the ground is. The same every day"),
                 ("file", "One-page report", "A printable summary for the place on screen")],
        ramp=LEVELS, ramp_t="Five levels",
        read=["A level is a rank. <b>High means look here first.</b>",
              "Beside it, a plain figure such as <b>3× the usual</b>: how many times the usual number of landslides.",
              "It is never a percentage."],
        users=["District disaster management", "Roads and public works", "Power and telecom lines",
               "Tour and transport operators"],
        note="An outlook for an area, days ahead. It does not watch a single slope, and it does not "
             "replace official warnings."),
    "flood": dict(
        cls="flood", name="FloodSense", what="the flood forecast",
        asks=["Could this place flood in the next seven days?",
              "Is the river at this gauge likely to reach its danger line?",
              "Where did the rain fall upstream of us?"],
        screens=[("calendar", "Live forecast", "The chance of a flood near any place, for the week and day by day"),
                 ("wave", "River gauges", "Each river's level against its line, with the days ahead"),
                 ("mountain", "Flood-prone ground", "Where water can reach if a flood comes"),
                 ("rain", "Catchments", "The rain upstream of every place"),
                 ("score", "Track record", "Every forecast written down, then checked against the river"),
                 ("file", "One-page report", "A printable summary for the place on screen")],
        ramp=CHANCES, ramp_t="Five bands of chance",
        read=["A percentage is <b>the chance of a flood</b> over the days shown.",
              "Every number carries a tag saying what kind it is: a forecast, a measurement or a record.",
              "Grey means quiet. Colour appears only when a chance is worth noticing."],
        users=["District disaster management", "Water resources and flood control", "Towns along the rivers",
               "Hydropower operators"],
        note="It runs by itself every morning, and is quietest outside the monsoon, as the rivers are. "
             "It does not replace official flood warnings."),
}


def _more(slug: str) -> str:
    m = MORE[slug]
    return f"""
    <details class='lp-det {m["cls"]}' name='lp-more'>
      <summary><span>More about <b>{m["name"]}</b></span><em>{m["what"]}</em><i></i></summary>
      <div class='lp-det-body'>
        <div class='lp-det-col'>
          <p class='lp-det-t'>{_ic("ask")}Questions it answers</p>
          <div class='lp-asks'>{"".join(f"<p>“{q}”</p>" for q in m["asks"])}</div>
          <p class='lp-det-t'>{_ic("users")}Made for</p>
          <div class='lp-chips'>{"".join(f"<span class='lp-chip'>{u}</span>" for u in m["users"])}</div>
        </div>
        <div class='lp-det-col'>
          <p class='lp-det-t'>{_ic("screen")}What is on screen</p>
          <div class='lp-screens'>{"".join(f"<div>{_ic(ic)}<p><b>{a}</b>{b}</p></div>" for ic, a, b in m["screens"])}</div>
        </div>
        <div class='lp-det-col'>
          <p class='lp-det-t'>{_ic("eye")}How to read it</p>
          <div class='lp-ramp' role='img' aria-label='{m["ramp_t"]}: {", ".join(t for _, t in m["ramp"])}'>
            {"".join(f"<span style='--c:{c}'><i></i>{t}</span>" for c, t in m["ramp"])}</div>
          <div class='lp-reads2'>{"".join(f"<p>{x}</p>" for x in m["read"])}</div>
          <p class='lp-det-note'>{m["note"]}</p>
        </div>
      </div>
    </details>"""


def more() -> str:
    return _c(f"""
    <section class='lp-sec lp-sec-cont'>
    <p class='lp-mini'>A closer look</p>
    <div class='lp-more'>{_more("landslide")}{_more("flood")}</div>
    </section>""")


def nxt() -> str:
    branches = [
        ("mountain", "More hazards", "Anything with a WHERE and a WHEN.",
         [("slope", "Landslides"), ("flood", "Floods"), ("", "Soil erosion · next"),
          ("plan", "Forest fire"), ("plan", "Riverbank erosion"), ("plan", "Drought and dry spells")]),
        ("pin", "More places", "The inputs are global. Each state adds its own records.",
         [("slope", "Arunachal · live"), ("plan", "Other hill states")]),
        ("users", "More users", "Of the data itself, through an open feed.",
         [("plan", "Road planners"), ("plan", "Power and telecom"), ("plan", "Insurers"),
          ("plan", "Researchers"), ("plan", "State systems")])]
    stairs = [("FREE", "today", "Open satellite and government data", "An area, days ahead"),
              ("ASK", "letters, not money", "Records that offices already hold", "Finer and faster"),
              ("PAID", "chosen spots", "Our own sensors, drones, surveys", "One slope or river reach, hours ahead")]
    # general on purpose: no module and no state named here
    nexts = [("More on the same backbone", "New hazards and new places"),
             ("A loop that runs itself", "Every forecast checked, the whole pipeline automatic"),
             ("An open feed", "So others can build on it")]
    return _c(f"""
    <section class='lp-sec'>
    {_head(5, "next", "What comes next", "What else can stand on it")}
    <div class='lp-branches'>
      {"".join(f"<div class='lp-card'><div class='lp-bh'>{_ic(ic)}<h3>{a}</h3></div><p>{b}</p><div class='lp-chips'>"
               + "".join(f"<span class='lp-chip {c}'>{t}</span>" for c, t in chips) + "</div></div>"
               for ic, a, b, chips in branches)}
    </div>
    <div class='lp-road'>One backbone underneath</div>
    <div class='lp-legend lp-legend-c'><span><i class='lp-chip slope'>live</i>live today</span>
    <span><i class='lp-chip'>next</i>being designed</span>
    <span><i class='lp-chip plan'>later</i>planned</span></div>

    <p class='lp-mini'>Why it compounds · it gets stronger every season</p>
    <div class='lp-two lp-time'>
      <div>
        <div class='lp-ring' role='img' aria-label='A loop: a forecast is made, written down, the day
        arrives, the forecast is graded, and the result becomes new data for the next forecast.'>
          <div class='lp-ring-c'></div>
          <i class='a1'></i><i class='a2'></i><i class='a3'></i><i class='a4'></i>
          <span class='n'>Forecast made</span><span class='e'>Written down</span>
          <span class='s'>The day arrives</span><span class='w'>Graded</span>
          <div class='lp-ring-mid'><b>New data</b><small>every time</small></div>
        </div>
        <p class='lp-line'>Code can be copied. <b>Seasons of checked local history cannot.</b></p>
      </div>
      <div>
        <div class='lp-stairs' role='img' aria-label='Three steps the data can climb: free today, then
        records that offices hold, then our own sensors.'>
          {"".join(f"<div class='lp-stair s{i}'><span>{a}<small>{b}</small></span><p>{c}</p><b>{d}</b></div>"
                   for i, (a, b, c, d) in enumerate(stairs, 1))}
        </div>
        <p class='lp-cap'>The data can climb. Each step sharpens every product at once.</p>
      </div>
    </div>
    </section>
    <section class='lp-close'>
      <p class='lp-close-by'><i class='lp-bee'></i>BEE Solutions</p>
      <p class='lp-quote'>An app is a vehicle.<br>The backbone is <em>the road</em>.</p>
      <p class='lp-close-sub'>From fragmented mountain data to actionable intelligence.</p>
      <div class='lp-nexts'>
        {"".join(f"<div class='lp-card'><i>{i}</i><div><b>{a}</b><span>{b}</span></div></div>"
                 for i, (a, b) in enumerate(nexts, 1))}
      </div>
      <div class='lp-comein'><em>Where you come in</em><span class='lp-chip'>a hazard you worry about</span>
      <span class='lp-chip'>a place you are responsible for</span>
      <span class='lp-chip'>records you already hold</span></div>
      <p class='lp-foot'><span>SlopeSense, Hazard Intelligence Platform · Arunachal Pradesh · built by
      <a href='{COMPANY_URL}' target='_blank' rel='noopener'>BEE Solutions</a></span>
      <a href='#lp-top'>Back to the top ↑</a></p>
    </section>""")


# ───────────────────────────── the look ──────────────────────────────────────
# Line icons, drawn as CSS masks so they take the colour of the text around
# them and need no icon font. 24 x 24, stroke only.
_ICONS = {
    "down": "<path d='M12 3v12m0 0l-5-5m5 5l5-5M4 20h16'/>",
    "file": "<path d='M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6'/>",
    "grid": "<path d='M3 3h18v18H3zM9 3v18M15 3v18M3 9h18M3 15h18'/>",
    "shelves": "<path d='M4 3v18M20 3v18M4 10h16M4 19h16M7 10V6h4v4M13 19v-5h4v5'/>",
    "send": "<path d='M21 3L10 14M21 3l-7 18-4-7-7-4z'/>",
    "pieces": "<path d='M3 4h7v7H3zM14 3h7v7h-7zM4 14h7v7H4zM13 13h7v7h-7z'/>",
    "restart": "<path d='M4.5 12a7.5 7.5 0 1 0 2.4-5.5M4 4v4.5h4.5'/>",
    "clock": "<circle cx='12' cy='12' r='9'/><path d='M12 7v5l3 2'/>",
    "score": "<path d='M6 4h12v17H6zM9 2h6v4H9zM9 12l2 2 4-4M9 18h6'/>",
    "shield": "<path d='M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM8.5 12l2.5 2.5 4.5-5'/>",
    "loop": "<path d='M17 2l3 3-3 3M20 5H9a5 5 0 0 0-5 5M7 22l-3-3 3-3M4 19h11a5 5 0 0 0 5-5'/>",
    "ask": "<circle cx='12' cy='12' r='9'/><path d='M9.6 9.4a2.5 2.5 0 1 1 3.6 2.3c-.8.5-1.2 1-1.2 1.9M12 17h.01'/>",
    "mountain": "<path d='M2 20l7-12 4 6 2-3 7 9z'/>",
    "pin": "<path d='M12 21s7-6.5 7-12a7 7 0 1 0-14 0c0 5.5 7 12 7 12z'/><circle cx='12' cy='9' r='2.5'/>",
    "users": "<circle cx='9' cy='8' r='3.5'/><path d='M2.5 20c.5-4 3-6 6.5-6s6 2 6.5 6M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14.5c2 .8 3.2 2.6 3.5 5.5'/>",
    "rain": "<path d='M7 15a4.5 4.5 0 0 1 .6-9 6 6 0 0 1 11.4 2 3.5 3.5 0 0 1-.5 7zM8 18l-1 3M12 18l-1 3M16 18l-1 3'/>",
    "calendar": "<path d='M4 6h16v15H4zM4 10h16M8 3v5M16 3v5M8 14h3M13 14h3M8 17h3'/>",
    "road": "<path d='M8 3L4 21M16 3l4 18M12 4v3M12 10v3M12 16v4'/>",
    "wave": "<path d='M3 8c3-3 6 3 9 0s6-3 9 0M3 13c3-3 6 3 9 0s6-3 9 0M3 18c3-3 6 3 9 0s6-3 9 0'/>",
    "screen": "<path d='M3 4h18v12H3zM8 20h8M12 16v4'/>",
    "eye": "<path d='M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z'/><circle cx='12' cy='12' r='3'/>",
}


def _icons_css() -> str:
    out = []
    for name, body in _ICONS.items():
        svg = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' "
               f"stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'>{body}</svg>")
        out.append(f".lp-ic-{name}{{--m:url(\"data:image/svg+xml,{quote(svg)}\")}}")
    return "".join(out)


def _backdrop_css() -> str:
    """The page's one picture: mountains, drawn as a grid. The ground of a
    mountain state cut into squares is the whole idea, so that is what sits,
    very faintly, along the bottom of the window.

    The picture repeats sideways on a wide screen, so each ridge must END at
    the height it STARTS at (the back one at 170, the front one at 214);
    otherwise the join shows as a cliff."""
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' width='1440' height='300' viewBox='0 0 1440 300'>"
           "<defs><pattern id='g' width='24' height='24' patternUnits='userSpaceOnUse'>"
           "<path d='M24 0H0V24' fill='none' stroke='#2ee6d6' stroke-opacity='.16' stroke-width='1'/></pattern>"
           "<linearGradient id='f' x1='0' y1='0' x2='0' y2='1'><stop offset='0' stop-color='#fff'/>"
           "<stop offset='1' stop-color='#fff' stop-opacity='0'/></linearGradient>"
           "<mask id='m'><rect width='1440' height='300' fill='url(#f)'/></mask></defs>"
           "<path d='M0 170L130 96l110 58L400 30l130 96 110-50 120 70L900 44l140 96 120-52 140 70 140 12V300H0z' "
           "fill='#4d8dff' fill-opacity='.05'/>"
           "<path d='M0 170L130 96l110 58L400 30l130 96 110-50 120 70L900 44l140 96 120-52 140 70 140 12' "
           "fill='none' stroke='#4d8dff' stroke-opacity='.16'/>"
           "<g mask='url(#m)'><path d='M0 214l150-66 130 52 150-84 140 76 130-44 150 70 150-92 140 72 150-50 "
           "150 66V300H0z' fill='url(#g)'/></g>"
           "<path d='M0 214l150-66 130 52 150-84 140 76 130-44 150 70 150-92 140 72 150-50 150 66' "
           "fill='none' stroke='#2ee6d6' stroke-opacity='.22'/></svg>")
    return (".stApp:has(.st-key-land_wrap){background:"
            f"url(\"data:image/svg+xml,{quote(svg)}\") repeat-x center bottom/1440px 300px,"
            "radial-gradient(1100px 520px at 12% -12%, rgba(46,230,214,.10), transparent 62%),"
            "radial-gradient(900px 480px at 88% -6%, rgba(77,141,255,.10), transparent 60%),var(--ink);}")


_BASE_CSS = """
/* ---- home page story (core/landing.py) ---- */
:root{--bee:#F5A623;--bee-2:#FFD85C;}
[data-testid="stMain"]:has(.st-key-land_story){scroll-behavior:smooth;}
.st-key-land_story{max-width:1000px!important;margin:0 auto!important;}
.lp-sec,.lp-close{color:var(--txt);font-size:1rem;line-height:1.5;}
.lp-p,.lp-h2,.lp-h3,.lp-li{margin:0;padding:0;}
.lp-ic{display:inline-block;flex:none;width:20px;height:20px;background:currentColor;
  -webkit-mask:var(--m) center/contain no-repeat;mask:var(--m) center/contain no-repeat;}
/* 'back to the top' means the very top, not the title under the jump bar */
#lp-top{scroll-margin-top:100vh;}
.lp-lede{text-align:center;margin:-6px 0 22px;display:grid;gap:3px;justify-items:center;}
.lp-lede b{font-family:'Sora',sans-serif;font-size:1.12rem;font-weight:600;color:var(--txt);
  letter-spacing:-.01em;}
.lp-lede span{color:var(--mut);font-size:.86rem;}
/* the company's mark: small, gold, a link to its own site. It floats in the
   top left corner and stays there while the page scrolls, in the same pill
   as the jump bar so it reads over whatever passes beneath. */
.lp-bee{display:inline-block;flex:none;width:24px;height:17px;background:center/contain no-repeat;}
.lp-brand{position:fixed;left:14px;top:10px;z-index:1000001;display:inline-flex;align-items:center;gap:9px;
  height:44px;box-sizing:border-box;padding:0 16px 0 11px;border-radius:999px;
  background:color-mix(in srgb,var(--panel) 88%,transparent);border:1px solid var(--line);
  backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);box-shadow:0 8px 26px rgba(0,0,0,.35);
  font-family:'Space Grotesk','Inter',sans-serif;font-size:.72rem;font-weight:500;letter-spacing:.16em;
  text-transform:uppercase;color:var(--mut)!important;text-decoration:none!important;white-space:nowrap;}
.lp-brand .lp-bee{width:32px;height:23px;}
.lp-brand em{font-style:normal;font-weight:700;color:var(--bee);}
.lp-brand:hover{color:var(--txt)!important;border-color:color-mix(in srgb,var(--bee) 45%,var(--line));}
.lp-nav .lp-nav-bee{display:none;padding:4px 6px 4px 8px;}
.lp-nav .lp-nav-bee .lp-bee{width:28px;height:20px;}
/* the platform's name and the line under it, set to the same width */
.land-title{display:grid!important;width:max-content;font-size:2rem!important;letter-spacing:.074em!important;}
.land-title span{text-align:justify;text-align-last:justify;}
.lp-cue-row{display:flex;justify-content:center;}
.lp-cue{display:flex;flex-direction:column;align-items:center;gap:2px;margin:20px auto 0;
  color:var(--mut)!important;text-decoration:none!important;font-size:.72rem;font-weight:600;
  letter-spacing:.14em;text-transform:uppercase;width:max-content;}
.lp-cue i{font-style:normal;font-size:1.05rem;color:var(--accent);animation:lpBob 1.8s ease-in-out infinite;}
.lp-cue:hover{color:var(--txt)!important;}
@keyframes lpBob{0%,100%{transform:translateY(0)}50%{transform:translateY(5px)}}

/* the jump bar: the five parts of the story, always in reach */
.lp-nav{position:fixed;top:10px;left:50%;transform:translateX(-50%);z-index:1000001;
  display:flex;align-items:center;gap:2px;padding:5px 6px;border-radius:999px;
  background:color-mix(in srgb,var(--panel) 88%,transparent);border:1px solid var(--line);
  backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
  box-shadow:0 8px 26px rgba(0,0,0,.35);max-width:calc(100vw - 20px);overflow-x:auto;
  scrollbar-width:none;}
.lp-nav::-webkit-scrollbar{display:none;}
.lp-nav a{flex:none;display:flex;align-items:center;gap:6px;padding:6px 11px;border-radius:999px;
  color:var(--mut)!important;text-decoration:none!important;font-size:.76rem;font-weight:600;
  white-space:nowrap;}
.lp-nav a:hover{color:var(--txt)!important;background:color-mix(in srgb,var(--accent) 12%,transparent);}
.lp-nav a i:not(.lp-bee){font-style:normal;font-size:.62rem;font-weight:700;width:16px;height:16px;border-radius:50%;
  display:grid;place-items:center;color:var(--ink);
  background:linear-gradient(135deg,var(--accent),var(--accent-2));}
.lp-nav .lp-nav-top{color:var(--accent)!important;font-size:.95rem;padding:4px 9px;}

.lp-sec{padding:74px 0 8px;}
.lp-sec-open{padding-bottom:0;}
.lp-sec-cont{padding-top:22px;}
.lp-head{scroll-margin-top:72px;margin-bottom:26px;display:grid;gap:9px;}
.lp-eyebrow{display:flex;align-items:center;gap:10px;margin:0;color:var(--accent);
  font-family:'Space Grotesk','Inter',sans-serif;font-size:.74rem;font-weight:700;letter-spacing:.18em;
  text-transform:uppercase;}
.lp-eyebrow i{font-style:normal;color:var(--bee);letter-spacing:.06em;}
.lp-eyebrow i::after{content:'//';margin-left:10px;color:var(--dim);font-weight:500;}
.lp-head .lp-h2{font-family:'Sora',sans-serif!important;font-size:clamp(1.5rem,1.1rem + 1.7vw,2.15rem);
  font-weight:700;letter-spacing:-.025em;line-height:1.14;color:var(--txt);margin:0;padding:0;}
.lp-head .lp-h2 em,.lp-quote em,.lp-grad{font-style:normal;
  background:linear-gradient(90deg,var(--accent),var(--accent-2));-webkit-background-clip:text;
  background-clip:text;color:transparent;}
.lp-sub{color:var(--mut);font-size:1.02rem;line-height:1.6;max-width:80ch;margin:0;}
.lp-mini{margin:44px 0 16px;color:var(--mut);font-family:'Space Grotesk','Inter',sans-serif;font-size:.72rem;
  font-weight:700;letter-spacing:.14em;text-transform:uppercase;display:flex;align-items:center;gap:12px;}
.lp-mini::after{content:'';flex:1;height:1px;background:var(--line);}
.lp-card{border:1px solid var(--line);border-radius:14px;background:var(--panel);padding:15px 17px;}
.lp-card .lp-h3,.lp-node .lp-h3,.lp-rule .lp-h3{font-family:'Sora',sans-serif!important;font-size:1rem;
  font-weight:600;color:var(--txt);margin:0;padding:0;letter-spacing:-.01em;line-height:1.3;}
.lp-card .lp-p,.lp-node .lp-p,.lp-rule .lp-p{color:var(--mut);font-size:.88rem;line-height:1.5;margin:4px 0 0;}
.lp-two{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,1fr);gap:34px;align-items:center;}
.lp-two-top{align-items:start;}
.lp-cap{color:var(--dim);font-size:.8rem;text-align:center;margin:12px 0 0;}
.lp-chip{display:inline-flex;align-items:center;font-size:.72rem;font-weight:600;padding:4px 10px;
  border-radius:999px;border:1px solid var(--line);color:var(--mut);background:var(--panel-2);
  font-style:normal;white-space:nowrap;}
.lp-chip.slope{color:#06221f;background:var(--accent);border-color:var(--accent);}
.lp-chip.flood{color:#fff;background:var(--accent-2);border-color:var(--accent-2);}
.lp-chip.plan{border-style:dashed;background:transparent;color:var(--dim);}
.lp-chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px;}

/* 2 x 2 tiles: an icon, two words, one short line */
.lp-tiles2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;}
.lp-tile{position:relative;display:grid;gap:2px;align-content:start;padding:14px 15px 13px;min-height:104px;
  border:1px solid var(--line);border-radius:13px;background:var(--panel);}
.lp-tile .lp-ic{width:22px;height:22px;color:var(--mut);margin-bottom:8px;}
.lp-tile b{color:var(--txt);font-family:'Sora',sans-serif;font-size:.98rem;font-weight:600;line-height:1.25;}
.lp-tile span{color:var(--mut);font-size:.84rem;line-height:1.4;}
.lp-verbs .lp-tile .lp-ic{color:var(--accent);}
.lp-step{position:absolute;right:13px;top:12px;font-family:'Space Grotesk','Inter',sans-serif;
  font-size:.7rem!important;font-weight:700;letter-spacing:.1em;color:var(--dim)!important;}
.lp-step::before{content:'0';}

/* 1 · the problem */
.lp-srcs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;}
.lp-src{border:1px solid var(--line);border-radius:13px;background:var(--panel);padding:10px 11px 11px;
  display:grid;gap:1px;}
.lp-src b{color:var(--txt);font-size:.86rem;font-weight:600;line-height:1.3;}
.lp-src span{color:var(--dim);font-size:.74rem;}
.lp-g{height:52px;border-radius:8px;margin-bottom:8px;border:1px solid var(--line);
  background-color:#0d141d;--g:rgba(143,163,186,.38);}
.lp-g-fine{background-image:linear-gradient(var(--g) 1px,transparent 1px),linear-gradient(90deg,var(--g) 1px,transparent 1px);
  background-size:5px 5px;}
.lp-g-mid{background-image:linear-gradient(var(--g) 1px,transparent 1px),linear-gradient(90deg,var(--g) 1px,transparent 1px);
  background-size:11px 11px;}
.lp-g-coarse{background-image:linear-gradient(var(--g) 1px,transparent 1px),linear-gradient(90deg,var(--g) 1px,transparent 1px);
  background-size:26px 26px;}
.lp-g-shape{background-image:radial-gradient(ellipse 34% 52% at 30% 45%,transparent 92%,var(--g) 93%,var(--g) 100%,transparent 101%),
  radial-gradient(ellipse 26% 40% at 72% 58%,transparent 90%,var(--g) 92%,var(--g) 100%,transparent 101%);}
.lp-g-line{background-image:linear-gradient(158deg,transparent 47%,var(--g) 48%,var(--g) 52%,transparent 53%),
  linear-gradient(24deg,transparent 58%,var(--g) 59%,var(--g) 62%,transparent 63%);}
.lp-g-dots{background-image:radial-gradient(circle at 22% 38%,var(--accent) 0 2.6px,transparent 3.4px),
  radial-gradient(circle at 48% 66%,var(--accent) 0 2.6px,transparent 3.4px),
  radial-gradient(circle at 74% 30%,var(--accent) 0 2.6px,transparent 3.4px),
  radial-gradient(circle at 86% 70%,var(--accent) 0 2.6px,transparent 3.4px);}
.lp-result{display:flex;align-items:center;gap:10px;margin:12px 0 0;padding:11px 14px;border-radius:12px;
  border:1px solid color-mix(in srgb,var(--bee) 30%,transparent);
  background:color-mix(in srgb,var(--bee) 7%,transparent);
  font-family:'Sora',sans-serif;font-size:.95rem;font-weight:600;color:var(--bee-2);}
.lp-result i{font-style:normal;color:var(--bee);}

/* 2 · the idea */
.lp-football{display:grid;grid-template-columns:44px 1fr;gap:14px;align-items:center;margin-top:10px;}
.lp-football .lp-p{margin:0!important;font-size:.93rem!important;line-height:1.5!important;}
.lp-football b{color:var(--txt);}
.lp-sq{width:44px;height:44px;border-radius:7px;border:1px solid color-mix(in srgb,var(--accent) 50%,transparent);
  background:linear-gradient(color-mix(in srgb,var(--accent) 34%,transparent) 1px,transparent 1px) 0 0/11px 11px,
    linear-gradient(90deg,color-mix(in srgb,var(--accent) 34%,transparent) 1px,transparent 1px) 0 0/11px 11px,
    linear-gradient(var(--accent),var(--accent)) 11px 22px/11px 11px no-repeat;}
.lp-ontop{display:flex;align-items:center;justify-content:center;gap:7px;margin-bottom:4px;}
.lp-ontop em{font-style:normal;color:var(--dim);font-size:.68rem;font-weight:700;letter-spacing:.14em;
  text-transform:uppercase;margin-right:4px;}
.lp-stack{position:relative;height:330px;max-width:430px;margin:0 auto;}
.lp-plane{position:absolute;left:calc(50% - 180px);top:calc(10px + var(--i) * 62px);width:170px;height:170px;
  transform:translateX(0) rotateX(62deg) rotateZ(45deg);transform-origin:50% 50%;border-radius:6px;
  border:1px solid color-mix(in srgb,var(--c) 70%,transparent);
  background:linear-gradient(color-mix(in srgb,var(--c) 34%,transparent) 1px,transparent 1px) 0 0/21.25px 21.25px,
    linear-gradient(90deg,color-mix(in srgb,var(--c) 34%,transparent) 1px,transparent 1px) 0 0/21.25px 21.25px,
    color-mix(in srgb,var(--c) 20%,#0b0f14);
  box-shadow:0 0 28px color-mix(in srgb,var(--c) 14%,transparent);}
.lp-plane b{position:absolute;left:63.75px;top:63.75px;width:21.25px;height:21.25px;
  background:color-mix(in srgb,var(--c) 85%,#fff);box-shadow:0 0 10px var(--c);}
.lp-plane-rain{--c:#4d8dff;}.lp-plane-river{--c:#3fb8e8;}.lp-plane-soil{--c:#2ee6d6;}.lp-plane-ground{--c:#8b9bb4;}
.lp-plane-l{position:absolute;left:calc(50% + 32px);top:calc(86px + var(--i) * 62px);color:var(--mut);
  font-size:.8rem;font-weight:600;white-space:nowrap;}
.lp-plane-l::before{content:'';display:inline-block;width:18px;height:1px;background:var(--line);
  vertical-align:middle;margin-right:8px;}
.lp-plumb{position:absolute;left:calc(50% - 95px);top:70px;height:232px;width:0;
  border-left:2px dashed color-mix(in srgb,var(--txt) 70%,transparent);}

/* 3 · how it works */
.lp-pipe{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;}
.lp-node{position:relative;border:1px solid var(--line);border-radius:14px;background:var(--panel);
  padding:13px 14px 15px;}
.lp-node-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;}
.lp-node-top .lp-ic{width:22px;height:22px;color:var(--accent);}
.lp-node-top span{color:var(--dim);font-family:'Space Grotesk','Inter',sans-serif;font-size:.68rem;font-weight:700;
  letter-spacing:.12em;}
.lp-node:not(:last-child)::after{content:'›';position:absolute;right:-10px;top:50%;transform:translateY(-50%);
  color:var(--dim);font-size:1rem;z-index:1;}
.lp-node.serve{border-color:color-mix(in srgb,var(--accent) 45%,var(--line));
  background:linear-gradient(160deg,color-mix(in srgb,var(--accent) 10%,transparent),transparent 70%),var(--panel);}
/* the way back: a line that leaves under "Serve" and returns under "Collect" */
.lp-return{position:relative;margin:0 10%;padding:20px 18px 13px;text-align:center;
  border:2px dashed color-mix(in srgb,var(--accent-2) 65%,var(--line));border-top:0;
  border-radius:0 0 20px 20px;color:var(--txt);font-size:.95rem;display:grid;gap:4px;justify-items:center;}
.lp-return::before{content:'';position:absolute;left:-8px;top:-3px;border:7px solid transparent;border-top:0;
  border-bottom:10px solid var(--accent-2);}
.lp-return em{font-style:normal;color:var(--accent-2);font-family:'Space Grotesk','Inter',sans-serif;
  font-size:.68rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;}
.lp-stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:30px;}
.lp-stats div{display:grid;gap:2px;justify-items:center;text-align:center;}
.lp-stats b{font-family:'Sora',sans-serif;font-size:clamp(1.7rem,1.2rem + 2vw,2.5rem);font-weight:700;
  letter-spacing:-.03em;color:var(--txt);line-height:1.1;}
.lp-stats span{color:var(--mut);font-size:.84rem;}
.lp-rules{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;}
.lp-rule{display:grid;grid-template-columns:22px 1fr;gap:13px;align-items:center;padding:13px 15px;
  border:1px solid var(--line);border-radius:13px;background:var(--panel);}
.lp-rule>.lp-ic{width:22px;height:22px;color:var(--accent);}
.lp-rule .lp-h3{font-size:.94rem;}
.lp-rule .lp-p{font-size:.82rem;margin-top:1px;}

/* 4 · running today */
.lp-eq{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;gap:12px;align-items:stretch;}
.lp-eqb{position:relative;border:1px solid var(--line);border-radius:14px;background:var(--panel);
  padding:16px 16px 15px;display:grid;gap:3px;align-content:center;}
.lp-eqb .lp-ic{position:absolute;right:14px;top:14px;width:22px;height:22px;color:var(--dim);}
.lp-eqb b{font-family:'Sora',sans-serif;font-size:1.25rem;font-weight:700;color:var(--txt);letter-spacing:.02em;}
.lp-eqb span{color:var(--txt);font-size:.95rem;}
.lp-eqb small{color:var(--dim);font-size:.66rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;
  margin-top:5px;}
.lp-eqb.out{border-color:color-mix(in srgb,var(--accent) 45%,var(--line));
  background:linear-gradient(160deg,color-mix(in srgb,var(--accent) 10%,transparent),transparent 70%),var(--panel);}
.lp-eqb.out .lp-ic{color:var(--accent);}
.lp-eqb.out b{background:linear-gradient(90deg,var(--accent),var(--accent-2));-webkit-background-clip:text;
  background-clip:text;color:transparent;}
.lp-op{display:grid;place-items:center;color:var(--dim);font-size:1.5rem;font-weight:300;}
.lp-qrows{display:grid;gap:8px;margin:14px 0 22px;}
.lp-qrow{display:grid;grid-template-columns:150px 1fr 24px 1.25fr;gap:10px;align-items:center;padding:10px 15px;
  border-radius:12px;border:1px solid var(--line);border-left:3px solid var(--c);background:var(--panel);
  color:var(--txt);font-size:.92rem;}
.lp-qrow.slope{--c:var(--accent);}.lp-qrow.flood{--c:var(--accent-2);}
.lp-qrow.plan{--c:var(--dim);border-style:dashed;border-left-style:dashed;background:transparent;color:var(--mut);}
.lp-qrow b{font-family:'Sora',sans-serif;font-weight:600;}
.lp-qrow b small{margin-left:7px;font:700 .6rem 'Inter',sans-serif;letter-spacing:.1em;text-transform:uppercase;
  color:var(--dim);border:1px dashed var(--dim);border-radius:999px;padding:2px 6px;}
.lp-qrow i{font-style:normal;color:var(--dim);text-align:center;}
.lp-prod{border:1px solid var(--line);border-top:3px solid var(--tile);border-radius:15px 15px 0 0;
  padding:18px 18px 16px;background:
    linear-gradient(160deg,color-mix(in srgb,var(--tile) 8%,transparent),transparent 55%),var(--panel);
  display:grid;gap:10px;}
.lp-prod-kind{margin:0;color:var(--tile);font-size:.66rem;font-weight:700;letter-spacing:.14em;
  text-transform:uppercase;}
.lp-prod-name{font-family:'Sora',sans-serif!important;font-size:1.35rem!important;font-weight:700!important;
  color:var(--txt);margin:0!important;padding:0!important;letter-spacing:-.02em;}
.lp-prod-tag{margin:0;color:var(--mut);font-size:.9rem;}
.lp-ask{color:var(--txt);font-family:'Sora',sans-serif;font-weight:600;font-size:1rem;}
.lp-ask em{font-style:normal;color:var(--tile);margin:0 3px;}
.lp-frame{border:1px solid var(--line);border-radius:10px;overflow:hidden;background:#0b0f14;
  box-shadow:0 14px 30px rgba(0,0,0,.35);}
.lp-bar{display:flex;gap:5px;padding:7px 9px;background:var(--panel-2);border-bottom:1px solid var(--line);}
.lp-bar i{width:7px;height:7px;border-radius:50%;background:var(--line);}
.lp-shot{aspect-ratio:1280/820;background:#0b0f14 top center/cover no-repeat;}
.lp-pts{list-style:none;margin:2px 0 0;padding:0;display:grid;gap:6px;}
.lp-pts .lp-li{position:relative;margin:0;padding-left:16px;color:var(--mut);font-size:.9rem;line-height:1.45;}
.lp-pts .lp-li::before{content:'';position:absolute;left:0;top:.6em;width:6px;height:6px;border-radius:50%;
  background:var(--tile);}
.lp-pts b{color:var(--txt);font-weight:600;}
.lp-reads{display:flex;flex-wrap:wrap;gap:6px;align-items:center;align-content:flex-start;padding-top:10px;
  border-top:1px solid var(--line);min-height:100px;}
.lp-reads em{flex-basis:100%;font-style:normal;color:var(--dim);font-size:.66rem;font-weight:700;
  letter-spacing:.14em;text-transform:uppercase;}
[class*="st-key-tile_story_"] .stButton{margin-top:-17px!important;}
[class*="st-key-tile_story_"] .stButton button{border-radius:0 0 13px 13px;min-height:2.5rem;}
.lp-bone{border-radius:13px;border-top-width:1px;padding:14px 18px;background:var(--panel-2);}
.lp-bone .lp-prod-name{font-size:1rem!important;}
.st-key-tile_story_backbone{margin-top:22px;}
.st-key-tile_story_backbone .stButton{margin-top:0!important;}
.st-key-tile_story_backbone .stButton button{border-radius:10px;min-height:2.6rem;}
.lp-reuse{grid-template-columns:minmax(0,1.5fr) minmax(0,1fr);}
.lp-matrix{width:100%;border-collapse:collapse;font-size:.9rem;}
.lp-matrix th{color:var(--dim);font-size:.68rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
  text-align:center;padding:0 6px 9px;border:0;}
.lp-matrix th:first-child,.lp-matrix td:first-child{text-align:left;padding-left:0;}
.lp-matrix td{padding:8px 6px;border:0;border-top:1px solid var(--line);color:var(--txt);text-align:center;}
.lp-matrix tr{border:0;background:transparent!important;}
.lp-dot{display:inline-block;width:11px;height:11px;border-radius:50%;vertical-align:middle;}
.lp-dot.s{background:var(--accent);}.lp-dot.f{background:var(--accent-2);}
.lp-dot.p{border:1.5px dashed var(--dim);}
.lp-dot.h{background:linear-gradient(90deg,var(--accent) 50%,transparent 50%);border:1.5px solid var(--accent);}
.lp-dash{display:inline-block;width:10px;height:1.5px;background:var(--line);vertical-align:middle;}
.lp-legend{display:flex;flex-wrap:wrap;gap:8px 18px;margin-top:12px;color:var(--dim);font-size:.76rem;}
.lp-legend span{display:inline-flex;align-items:center;gap:7px;}
.lp-legend-c{justify-content:center;}
.lp-big{display:grid;gap:8px;align-content:center;padding:22px 22px!important;}
.lp-big .lp-grad{font-family:'Sora',sans-serif;font-size:4.4rem;font-weight:700;line-height:1;letter-spacing:-.04em;}
.lp-big .lp-grad small{font-size:1.25rem;margin-left:8px;letter-spacing:0;}
.lp-big .lp-p{font-size:.98rem!important;color:var(--mut)!important;margin:0!important;}
.lp-big b{color:var(--txt);}
.lp-also{padding-top:10px;border-top:1px solid var(--line);}

/* "More about …": two rows that open in place */
.lp-more{display:grid;gap:10px;}
.lp-det{border:1px solid var(--line);border-left:3px solid var(--c);border-radius:13px;background:var(--panel);
  overflow:hidden;}
.lp-det.slope{--c:var(--accent);}.lp-det.flood{--c:var(--accent-2);}
.lp-det summary{list-style:none;cursor:pointer;display:flex;align-items:center;gap:12px;padding:14px 18px;
  color:var(--txt);font-family:'Sora',sans-serif;font-size:1rem;font-weight:500;}
.lp-det summary::-webkit-details-marker{display:none;}
.lp-det summary b{font-weight:700;color:var(--c);}
.lp-det summary em{font-style:normal;color:var(--dim);font-family:'Inter',sans-serif;font-size:.82rem;}
.lp-det summary i{margin-left:auto;width:26px;height:26px;border-radius:50%;border:1px solid var(--line);
  display:grid;place-items:center;font-style:normal;color:var(--c);flex:none;}
.lp-det summary i::before{content:'+';font-size:1.05rem;line-height:1;}
.lp-det[open] summary i::before{content:'–';}
.lp-det summary:hover{background:color-mix(in srgb,var(--c) 6%,transparent);}
.lp-det[open] summary{border-bottom:1px solid var(--line);}
.lp-det-body{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:26px;padding:18px 18px 20px;}
.lp-det-col{display:grid;gap:10px;align-content:start;}
.lp-det-t{display:flex;align-items:center;gap:8px;color:var(--mut);font-family:'Space Grotesk','Inter',sans-serif;
  font-size:.7rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;}
.lp-det-t .lp-ic{width:17px;height:17px;color:var(--c);}
.lp-det-col .lp-det-t:not(:first-child){margin-top:10px;}
.lp-asks{display:grid;gap:7px;}
.lp-asks .lp-p{padding:9px 12px;border-radius:10px 10px 10px 2px;background:var(--panel-2);
  border:1px solid var(--line);color:var(--txt);font-size:.88rem;line-height:1.4;}
.lp-det .lp-chips{margin-top:0;}
.lp-screens{display:grid;gap:9px;}
.lp-screens>div{display:grid;grid-template-columns:20px 1fr;gap:10px;align-items:start;}
.lp-screens .lp-ic{width:18px;height:18px;color:var(--mut);margin-top:2px;}
.lp-screens .lp-p{color:var(--mut);font-size:.84rem;line-height:1.4;}
.lp-screens b{display:block;color:var(--txt);font-size:.9rem;font-weight:600;}
.lp-ramp{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:4px;}
.lp-ramp span{display:grid;gap:5px;color:var(--mut);font-size:.66rem;font-weight:600;text-align:center;line-height:1.2;}
.lp-ramp i{height:9px;border-radius:3px;background:var(--c);}
.lp-reads2{display:grid;gap:6px;}
.lp-reads2 .lp-p{color:var(--mut);font-size:.86rem;line-height:1.45;}
.lp-reads2 b{color:var(--txt);font-weight:600;}
.lp-det-note{margin-top:4px;padding-top:10px;border-top:1px solid var(--line);color:var(--dim);font-size:.8rem;
  line-height:1.45;}

/* 5 · what comes next */
.lp-branches{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;}
.lp-bh{display:flex;align-items:center;gap:9px;}
.lp-bh .lp-ic{color:var(--accent);}
.lp-road{margin-top:12px;padding:9px;border-radius:10px;text-align:center;color:var(--ink);font-size:.74rem;
  font-weight:700;letter-spacing:.14em;text-transform:uppercase;
  background:linear-gradient(90deg,var(--accent),var(--accent-2));}
.lp-time{align-items:center;}
/* the loop, as a ring */
.lp-ring{position:relative;width:340px;height:270px;margin:0 auto;}
.lp-ring-c{position:absolute;left:20px;top:25px;width:300px;height:220px;border-radius:50%;
  border:2px solid color-mix(in srgb,var(--accent) 55%,var(--line));}
.lp-ring>span{position:absolute;transform:translate(-50%,-50%);padding:7px 13px;border-radius:999px;
  border:1px solid var(--line);background:var(--panel);color:var(--txt);font-size:.84rem;font-weight:600;
  white-space:nowrap;}
.lp-ring .n{left:170px;top:25px;}.lp-ring .e{left:320px;top:135px;}
.lp-ring .s{left:170px;top:245px;}.lp-ring .w{left:20px;top:135px;}
.lp-ring>i{position:absolute;width:9px;height:9px;margin:-5px 0 0 -5px;
  border-top:2px solid var(--accent);border-right:2px solid var(--accent);}
.lp-ring .a1{left:276px;top:57px;transform:rotate(81deg);}
.lp-ring .a2{left:276px;top:213px;transform:rotate(189deg);}
.lp-ring .a3{left:64px;top:213px;transform:rotate(261deg);}
.lp-ring .a4{left:64px;top:57px;transform:rotate(9deg);}
.lp-ring-mid{position:absolute;left:170px;top:135px;transform:translate(-50%,-50%);display:grid;gap:1px;
  text-align:center;}
.lp-ring-mid b{font-family:'Sora',sans-serif;font-size:1.3rem;font-weight:700;letter-spacing:-.02em;
  background:linear-gradient(90deg,var(--accent),var(--accent-2));-webkit-background-clip:text;
  background-clip:text;color:transparent;}
.lp-ring-mid small{color:var(--mut);font-size:.8rem;}
.lp-line{margin:14px 0 0;text-align:center;font-family:'Sora',sans-serif;font-size:1.02rem;line-height:1.45;
  color:var(--mut);}
.lp-line b{color:var(--txt);font-weight:600;}
/* the steps the data can climb */
.lp-stairs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;align-items:end;}
.lp-stair{display:grid;gap:5px;align-content:start;padding:12px 13px 13px;border:1px solid var(--line);
  border-top:3px solid var(--c);border-radius:12px;background:var(--panel);}
.lp-stair.s1{--c:var(--accent);min-height:132px;}
.lp-stair.s2{--c:var(--accent-2);min-height:176px;}
.lp-stair.s3{--c:var(--dim);min-height:220px;border-style:dashed;border-top-style:dashed;}
.lp-stair span{font-family:'Sora',sans-serif;font-weight:700;color:var(--txt);font-size:.95rem;letter-spacing:.06em;}
.lp-stair span small{display:block;font:600 .68rem 'Inter',sans-serif;letter-spacing:0;color:var(--dim);}
.lp-stair .lp-p{color:var(--mut);font-size:.8rem;line-height:1.4;}
.lp-stair b{color:var(--txt);font-weight:600;font-size:.84rem;line-height:1.35;}
.lp-close{position:relative;margin:84px 0 10px;padding:40px 26px 22px;border-radius:22px;
  border:1px solid var(--line);text-align:center;overflow:hidden;background:
    radial-gradient(620px 240px at 50% 0%,color-mix(in srgb,var(--accent) 13%,transparent),transparent 70%),
    var(--panel);display:grid;gap:14px;justify-items:center;}
/* a little of the hive, in the corner of the closing block only */
.lp-close::before{content:'';position:absolute;right:-30px;top:-34px;width:230px;height:230px;opacity:.5;
  pointer-events:none;-webkit-mask:radial-gradient(circle at 70% 30%,#000,transparent 68%);
  mask:radial-gradient(circle at 70% 30%,#000,transparent 68%);
  background:url("data:image/svg+xml,%3Csvg width='56' height='100' viewBox='0 0 56 100' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M28 66L0 50V16L28 0l28 16v34L28 66zm0-88L4 20v40l24 14 24-14V20L28-22z' fill='none' stroke='%23F5A623' stroke-opacity='0.28'/%3E%3C/svg%3E");}
.lp-close-by{display:inline-flex;align-items:center;gap:8px;margin:0;color:var(--bee);
  font-family:'Space Grotesk','Inter',sans-serif;font-size:.72rem;font-weight:700;letter-spacing:.2em;
  text-transform:uppercase;}
.lp-quote{margin:0;font-family:'Sora',sans-serif;font-size:clamp(1.6rem,1.1rem + 2.4vw,2.6rem);font-weight:700;
  letter-spacing:-.03em;line-height:1.16;color:var(--txt);}
.lp-close-sub{margin:0;color:var(--mut);font-size:1rem;}
.lp-nexts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;width:100%;margin-top:16px;
  text-align:left;}
.lp-nexts .lp-card{display:grid;grid-template-columns:34px 1fr;gap:12px;align-items:center;background:var(--panel-2);}
.lp-nexts i{font-style:normal;width:34px;height:34px;border-radius:10px;display:grid;place-items:center;
  font-size:.82rem;font-weight:700;color:var(--mut);background:var(--panel);border:1px solid var(--line);}
.lp-nexts b{display:block;color:var(--txt);font-size:.96rem;font-weight:600;}
.lp-nexts span{color:var(--mut);font-size:.84rem;}
.lp-comein{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:center;margin-top:8px;}
.lp-comein em{font-style:normal;color:var(--bee);font-family:'Space Grotesk','Inter',sans-serif;font-size:.7rem;
  font-weight:700;letter-spacing:.14em;text-transform:uppercase;margin-right:4px;}
.lp-comein .lp-chip{font-size:.82rem;padding:7px 14px;color:var(--txt);}
.lp-foot{margin:22px 0 0;padding-top:16px;border-top:1px solid var(--line);width:100%;color:var(--dim);
  font-size:.76rem;display:flex;flex-wrap:wrap;gap:8px 18px;justify-content:space-between;}
.lp-foot a{color:var(--mut)!important;text-decoration:none!important;}
.lp-foot span a{color:var(--bee)!important;}

@media (max-width:900px){
  .lp-pipe{grid-template-columns:repeat(2,minmax(0,1fr));}
  .lp-node:not(:last-child)::after{display:none;}
  .lp-return{margin:12px 0 0;border-top:2px dashed color-mix(in srgb,var(--accent-2) 65%,var(--line));
    border-radius:14px;padding:13px 16px;}
  .lp-return::before{display:none;}
  .lp-rules,.lp-branches,.lp-nexts{grid-template-columns:repeat(2,minmax(0,1fr));}
  .lp-two,.lp-reuse{grid-template-columns:1fr;gap:24px;}
  .lp-det-body{grid-template-columns:1fr;gap:18px;}
}
@media (max-width:1100px){
  /* no room beside the jump bar: the mark moves inside it */
  .lp-brand{display:none;}
  .lp-nav .lp-nav-bee{display:flex;}
}
@media (max-width:760px){
  .lp-sec{padding-top:54px;}
  .lp-eq{grid-template-columns:1fr;}
  .lp-op{font-size:1.2rem;height:8px;}
  .lp-qrow{grid-template-columns:1fr;gap:2px;}
  .lp-qrow i{text-align:left;}
  .lp-nav a{padding:6px 9px;font-size:.72rem;}
  .lp-nav{left:10px;right:10px;transform:none;justify-content:flex-start;}
  .lp-det summary em{display:none;}
}
@media (max-width:560px){
  .lp-pipe,.lp-rules,.lp-branches,.lp-nexts,.lp-stats{grid-template-columns:1fr;}
  .lp-stats{gap:18px;}
  .lp-stairs{grid-template-columns:1fr;}
  .lp-stair.s1,.lp-stair.s2,.lp-stair.s3{min-height:0;}
  .lp-stack{transform:scale(.86);transform-origin:50% 0;height:290px;}
  .lp-ring{transform:scale(.9);transform-origin:50% 0;margin-bottom:-24px;}
  .lp-close{padding:34px 16px 18px;}
}
@media (max-width:380px){
  .lp-ring{left:50%;margin-left:-170px;transform:scale(.84);}
}
@media (prefers-reduced-motion: reduce){
  [data-testid="stMain"]:has(.st-key-land_story){scroll-behavior:auto;}
  .lp-cue i{animation:none;}
}
"""

CSS = ("<style>@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&display=swap');"
       + _BASE_CSS + _icons_css() + _backdrop_css() + "</style>")
