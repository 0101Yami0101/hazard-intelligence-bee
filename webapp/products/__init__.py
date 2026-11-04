"""The module registry.

Adding a product means adding a folder and one entry below. Nothing in the
shell, the sidebar or the landing page needs to learn about it — they all read
this list.

Each product folder holds:
    __init__.py   the MANIFEST — everything the landing page needs, and no code
    view.py       a render(shell) function, called once per rerun
    model.py      the maths, kept free of Streamlit so it can be tested
and its data lives in assets/<slug>/, on the shared grid from assets/base/.

⚠️ Manifests are DATA. The view modules are imported lazily, inside render(),
so opening the landing page does not pay the import cost of every product's
numpy and folium work — only the one actually opened.
"""
from __future__ import annotations

import importlib
import os
from dataclasses import dataclass

# A module shown as "under development" is listed but cannot be opened. On our
# own machines SLOPESENSE_SHOW_WIP=1 opens it anyway, so work on it goes on;
# the public app never sets it.
SHOW_WIP = os.environ.get("SLOPESENSE_SHOW_WIP") == "1"


@dataclass(frozen=True)
class Product:
    slug: str          # folder name, URL value, asset directory
    name: str          # the module's own brand
    hazard: str        # what it forecasts, in one plain word
    icon: str
    tagline: str       # one line, on the card
    blurb: str         # two or three sentences, on the card
    accent: str
    status: str        # "live" | "building" | "development" | "foundation"
    kind: str = "product"   # "product" cards lead, "foundation" sits beneath
    # The session-state key the module's OWN sidebar loop reads/writes for its
    # current tab. Each module picked its own name historically (SlideSense:
    # "view", FloodSense: "fl_view", Data Backbone: "bb_view") — this is what
    # lets the shared popover below write to the right one.
    nav_key: str = "view"
    # Pages that exist but don't earn a permanent sidebar slot — reached
    # instead from the shared ℹ️ popover next to the module's name.
    # (icon, label, disabled_reason) — disabled_reason is None for a normal
    # clickable entry, or a string that renders it disabled and greyed, with
    # that string as the hover explanation (e.g. a page still being
    # validated, not yet fit to show anyone outside the team).
    extra_nav: tuple[tuple[str, str, str | None], ...] = ()
    # The state the module covers, for the side menu's tag. Every module was
    # Arunachal until SoilSense (Assam, 2026-10-19).
    region: str = "Arunachal Pradesh"

    @property
    def available(self) -> bool:
        # A "building" module opens too: its tile carries the 🔧 Building pill
        # and its pages say what is not finished. Only "foundation"-style
        # placeholders without a page would stay shut, and a module marked
        # "development" (listed, not opened yet) unless SHOW_WIP is set.
        return self.status in ("live", "building") or (self.status == "development" and SHOW_WIP)

    def render(self, shell) -> None:
        importlib.import_module(f"products.{self.slug}.view").render(shell)


REGISTRY: list[Product] = [
    Product(
        slug="landslide",
        name="SlideSense",
        hazard="Landslides",
        icon="◭",
        tagline="7-day landslide outlook · statewide",
        blurb="Where slopes are weak, learned from 35,744 mapped failures, "
              "multiplied by how unusual this week's rain is for that exact "
              "place. Searchable down to the village, with road exposure in "
              "kilometres.",
        accent="#2ee6d6",
        status="live",
        nav_key="view",
        extra_nav=(("🧭", "Evidence", None),
                   ("📊", "Model & Validation", None))),
    Product(
        slug="flood",
        name="FloodSense",
        hazard="Floods",
        icon="◈",
        tagline="7-day river flood outlook · statewide",
        blurb="A daily flood forecast from live rain and 32 river gauges: a "
              "checked chance of each gauged river reaching danger level, and "
              "an approximate chance of a flood near every place over the next "
              "7 days. Every forecast is logged and graded against what happened.",
        accent="#4d8dff",
        status="live",
        nav_key="fl_view",
        extra_nav=(("📋", "How to read this forecast", None),)),
    Product(
        slug="erosion",
        name="SoilSense",
        hazard="Soil erosion",
        icon="◬",
        tagline="Soil erosion risk · Assam",
        blurb="Where rain washes soil off the land, from rain strength, soil, slope "
              "and ground cover on the same backbone, moved to a second state. "
              "Ranks small catchments and districts for conservation work, each "
              "with its main cause and how firm the ranking is.",
        accent="#e0a458",
        # Shown but closed on the public app for now (user, 2026-11-04).
        status="development",
        nav_key="er_view",
        region="Assam"),
    Product(
        slug="backbone",
        name="Data Backbone",
        hazard="The pipeline",
        icon="⛁",
        tagline="What every module is built on",
        blurb="One rainfall archive, one terrain model, one grid, one "
              "gazetteer. Every forecast above stands on this, and it is the "
              "part that makes the next hazard cheap rather than another "
              "project.",
        accent="#8b9bb4",
        status="live",
        kind="foundation",
        nav_key="bb_view"),
]

BY_SLUG = {p.slug: p for p in REGISTRY}


def get(slug: str | None) -> Product | None:
    return BY_SLUG.get(slug) if slug else None
