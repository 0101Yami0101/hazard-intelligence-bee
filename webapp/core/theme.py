"""Design layer — the SlopeSense instrument panel, carried over intact.

Identity: deep ink canvas, signal-cyan accent, Sora for display type / Inter for
UI. The accent is deliberately COOL because the hazard ramp is warm
(green -> yellow -> red); a warm accent would compete with the very colours
that carry the meaning.

⚠️ The palette here is the SAME as SlopeSense v1 — accent #2ee6d6, second
#4d8dff — on purpose. The two apps sit side by side in one portfolio, and a
near-miss on brand colour reads as a mistake rather than a family.

Hazard classes use a green->red ramp because it is the convention emergency
managers already read. The out-of-domain grey is deliberately flat and dull: it
must never be mistaken for "safe".

Kept out of app.py so the layout code stays readable.
"""
from __future__ import annotations

CLASS_NAMES = ["Very Low", "Low", "Moderate", "High", "Very High"]
CLASS_COLORS = ["#1a9850", "#a6d96a", "#fee08b", "#f46d43", "#a50026"]
NOT_ASSESSED = "#3a4351"

ACCENT = "#2ee6d6"
ACCENT_2 = "#4d8dff"

# Basemaps. `tiles=None` on the Map plus our own TileLayer is what makes the
# switcher work at all — folium's built-in tiles argument cannot be swapped
# after construction.
CARTO = ('&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> '
         '&copy; <a href="https://carto.com/attributions">CARTO</a>')
# ⚠️ Dark and Light are Esri's gray canvases, not CARTO's `dark_nolabels` /
# `light_nolabels`. Those CARTO base tiles started coming back with "API KEY
# REQUIRED / carto.com/basemaps/apikey" drawn INTO the image (checked
# 2026-09-25 by downloading the tile itself) — a server-side change on
# CARTO's end, nothing in this app. Esri's are free, need no key, and carry no
# watermark. The transparent label overlays below are still CARTO's and still
# clean; if those ever get watermarked too, Esri's World_Dark_Gray_Reference /
# World_Light_Gray_Reference are the drop-in replacement.
ESRI_CANVAS = "Tiles &copy; Esri — Esri, DeLorme, NAVTEQ"
BASEMAPS = {
    "Dark": ("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/"
             "World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}", ESRI_CANVAS),
    "Light": ("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/"
              "World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", ESRI_CANVAS),
    "Terrain": ("https://tile.opentopomap.org/{z}/{x}/{y}.png",
                'Map data &copy; OSM, SRTM · style &copy; '
                '<a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)'),
    "Satellite": ("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/"
                  "MapServer/tile/{z}/{y}/{x}",
                  "Tiles &copy; Esri — Esri, Maxar, Earthstar Geographics"),
}
# Place names, drawn over every basemap. Esri's gray-canvas reference layers,
# not CARTO's `*_only_labels`: those ALSO turned out to carry the "API KEY
# REQUIRED" watermark, but only from ~zoom 10 in (checked 2026-09-25 at
# z8 / z11 / z13) — which is why it first looked fixed at state view.
_ESRI_REF = ("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/"
             "World_{}_Gray_Reference/MapServer/tile/{{z}}/{{y}}/{{x}}")
LABEL_TILES = {
    "Dark": _ESRI_REF.format("Dark"),
    "Satellite": _ESRI_REF.format("Dark"),
    "Terrain": _ESRI_REF.format("Light"),
    "Light": _ESRI_REF.format("Light"),
}
# Boundary and road strokes that read against each basemap.
BOUNDARY_INK = {"Dark": ACCENT, "Satellite": ACCENT,
                "Terrain": "#1f2937", "Light": "#1f2937"}
ROAD_INK = {"Dark": "#93a7bd", "Satellite": "#e5e7eb",
            "Light": "#4a4a4a", "Terrain": "#4a4a4a"}


def _rgb(hexc: str, alpha: int = 210) -> list[int]:
    return [int(hexc[i:i + 2], 16) for i in (1, 3, 5)] + [alpha]


# deck.gl takes colours as RGBA arrays, not hex — same boundary ink, other units.
EDGE_RGB = {k: _rgb(v) for k, v in BOUNDARY_INK.items()}

MAP_MIN_ZOOM = 6
MAP_H = 430          # compact map viewport, matching SlopeSense v1
MAP_H_SM = 360

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Sora:wght@500;600;700&display=swap');

:root{
  --ink:#0b0f14; --panel:#111823; --panel-2:#161f2c; --line:#223044;
  --txt:#e5edf5; --mut:#8fa3ba; --dim:#64798f;
  --accent:#2ee6d6; --accent-2:#4d8dff;
}
html,body,.stApp,p,li,td,th,label,input,textarea,select,button{
  font-family:'Inter',system-ui,-apple-system,sans-serif;
}
h1,h2,h3,h4,h5,h6,[data-testid="stMetricValue"]{
  font-family:'Sora','Inter',sans-serif!important; letter-spacing:-.015em;
}
/* Aurora over the ink canvas — the one flourish; everything else stays quiet. */
.stApp{
  background:
    radial-gradient(1100px 520px at 12% -12%, rgba(46,230,214,.10), transparent 62%),
    radial-gradient(900px 480px at 88% -6%, rgba(77,141,255,.10), transparent 60%),
    var(--ink);
}
.block-container{padding-top:2.1rem; padding-bottom:3rem; max-width:1400px;}

/* Header is made invisible but NOT removed — it reserves the vertical space
   the content sits below. The sidebar's reopen button lives inside the
   toolbar, so hiding the whole toolbar would strand a collapsed sidebar. */
[data-testid="stHeader"]{background:transparent; box-shadow:none;}
[data-testid="stDecoration"],.stAppDeployButton,#MainMenu,footer{display:none;}
[data-testid="stToolbarActions"]{display:none;}
[data-testid="stExpandSidebarButton"]{visibility:visible!important; opacity:1!important;}

/* Map components mount at zero width before their own JS measures the
   container; forcing width at the CSS layer applies first, so that flash
   never paints. */
iframe,[data-testid="stFullScreenFrame"]{width:100%!important;}
iframe{border-radius:14px; border:1px solid var(--line)!important;}
/* Height-locked map shell: switching map mode must not collapse the card and
   bounce everything below it. Hide the scrollbar that the lock implies. */
.st-key-map_shell{overflow:hidden!important;}
.st-key-map_shell::-webkit-scrollbar{display:none;}

/* The click panel beside the map. Locked to the map's height so the two read
   as one card; content taller than that scrolls INSIDE the panel rather than
   stretching the row and leaving dead space next to the map. Unlike the map
   shell this one keeps a scrollbar — it is the only cue that there is more
   below the fold — but a thin, quiet one. */
.st-key-click_shell{
  background:rgba(13,19,27,.55); border:1px solid var(--line);
  border-radius:14px; padding:12px 14px;
}
.st-key-click_shell::-webkit-scrollbar{width:7px;}
.st-key-click_shell::-webkit-scrollbar-track{background:transparent;}
.st-key-click_shell::-webkit-scrollbar-thumb{
  background:var(--line); border-radius:4px;
}
.st-key-click_shell::-webkit-scrollbar-thumb:hover{background:#2f4258;}

/* ---- brand ---- */
.brand{display:flex; align-items:center; gap:11px; margin-bottom:4px;}
.brand-logo{
  width:42px;height:42px;border-radius:13px;display:flex;align-items:center;
  justify-content:center;font-size:20px;color:#06121a;
  background:linear-gradient(135deg,var(--accent),var(--accent-2));
  box-shadow:0 4px 14px rgba(46,230,214,.22);
}
.brand-name{font-family:'Sora',sans-serif;font-weight:700;font-size:1.12rem;
  color:var(--txt);line-height:1.15;letter-spacing:-.02em;}
.brand-tag{font-size:.7rem;color:var(--dim);letter-spacing:.02em;}
.brand-sm .brand-logo{width:34px;height:34px;font-size:16px;border-radius:10px;}
.brand-sm .brand-name{font-size:.95rem;}
.brand-sm .brand-tag{font-size:.62rem;}
.side-label{font-size:.66rem;font-weight:700;letter-spacing:.13em;color:var(--dim);
  text-transform:uppercase;margin:4px 0 2px;}

/* ---- about popover ---- */
.hero-eyebrow{font-size:.7rem;font-weight:700;letter-spacing:.16em;
  color:var(--accent);text-transform:uppercase;margin-bottom:6px;}
.about-stats{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0 2px;}
.about-stats > div{background:var(--panel-2);border:1px solid var(--line);
  border-radius:10px;padding:8px 11px;}
.as-num{display:block;font-family:'Sora',sans-serif;font-weight:700;
  font-size:1.06rem;color:var(--txt);}
.as-lbl{display:block;font-size:.64rem;color:var(--dim);text-transform:uppercase;
  letter-spacing:.06em;margin-top:1px;}

/* ---- alert banner (statewide view) ---- */
.alert-band{
  display:flex;align-items:center;gap:16px;padding:15px 20px;border-radius:16px;
  border:1px solid var(--line);margin-bottom:14px;
  background:linear-gradient(180deg,var(--panel-2),var(--panel));
}
.alert-dot{width:13px;height:13px;border-radius:50%;flex:none;}
.alert-title{font-family:'Sora',sans-serif;font-weight:700;font-size:1.16rem;color:var(--txt);}
.alert-sub{font-size:.82rem;color:var(--mut);margin-top:2px;}
.alert-right{margin-left:auto;text-align:right;}
.alert-num{font-family:'Sora',sans-serif;font-weight:700;font-size:1.5rem;color:var(--txt);}
.alert-lbl{font-size:.63rem;color:var(--dim);text-transform:uppercase;letter-spacing:.09em;}

/* ---- located forecast header ---- */
.loc-head{display:flex;align-items:flex-start;gap:15px;padding:16px 20px;
  border-radius:16px;border:1px solid var(--line);margin-bottom:14px;
  background:linear-gradient(180deg,var(--panel-2),var(--panel));}
.loc-pin{width:38px;height:38px;border-radius:12px;flex:none;display:flex;
  align-items:center;justify-content:center;font-size:18px;color:#06121a;
  background:linear-gradient(135deg,var(--accent),var(--accent-2));
  box-shadow:0 4px 14px rgba(46,230,214,.22);}
.loc-name{font-family:'Sora',sans-serif;font-weight:700;font-size:1.24rem;
  color:var(--txt);line-height:1.2;}
.loc-sub{font-size:.79rem;color:var(--mut);margin-top:3px;}
.loc-right{margin-left:auto;text-align:right;}
.loc-cls{font-family:'Sora',sans-serif;font-weight:700;font-size:1.14rem;}
.loc-lbl{font-size:.63rem;color:var(--dim);text-transform:uppercase;letter-spacing:.09em;}

/* ---- day strip ---- */
[class*="st-key-day_"] button{
  border-radius:12px!important;padding:9px 4px!important;font-weight:600!important;
  border:1px solid var(--line)!important;background:var(--panel-2)!important;
  color:#cfe0ef!important;line-height:1.25!important;
}
[class*="st-key-day_"] button:hover{border-color:var(--accent)!important;color:var(--accent)!important;}
[class*="st-key-nav_"] button{
  text-align:left;justify-content:flex-start;font-weight:600;padding:8px 12px;border-radius:11px;
}
[class*="st-key-nav_"] div[data-testid="stMarkdownContainer"]{text-align:left;}

/* ---- panels / metrics ---- */
div[data-testid="stVerticalBlockBorderWrapper"]{
  background:linear-gradient(180deg,rgba(22,31,44,.92),rgba(17,24,35,.92));
  border-radius:18px;
}
/* ⚠️ min-height, not height. Measured on every page that uses st.metric(): a
   card with a delta line is 110px tall, one without is 85px — the SAME
   defect on SlopeSense, FloodSense and Data Backbone, any time a row mixes
   metrics that carry a delta with ones that don't. min-height fixes the row
   without clipping a metric that ever needs more room than this. Width is
   NOT hardcoded here: st.columns() already gives every metric in a row an
   equal share, and a fixed pixel width would only be correct for one
   specific column count and break every other page's layout. */
[data-testid="stMetric"]{
  background:linear-gradient(180deg,var(--panel-2),var(--panel));
  border:1px solid var(--line);border-radius:16px;padding:13px 16px;
  min-height:118px;
}
[data-testid="stMetricLabel"] p{
  font-size:.68rem!important;font-weight:600!important;text-transform:uppercase;
  letter-spacing:.08em;color:var(--dim)!important;
}
[data-testid="stMetricValue"]{font-size:1.5rem;font-weight:700;color:var(--txt);}
div[data-testid="stExpander"] > details{
  background:var(--panel);border:1px solid var(--line);border-radius:14px;
}
[data-testid="stDataFrame"]{border-radius:12px;}
[data-testid="stSidebar"]{background:#0d131b;border-right:1px solid var(--line);}

/* ---- search ---- */
[data-testid="stSelectbox"] div[data-baseweb="select"] > div{
  background:var(--panel-2)!important;border:1px solid var(--line)!important;
  border-radius:12px!important;
}
[data-testid="stSelectbox"] div[data-baseweb="select"] > div:hover{
  border-color:var(--accent)!important;
}

/* A disabled segmented control (the parked 3D toggle). Muted enough to read
   as unavailable, but the active option stays legible — a control where
   nothing looks selected reads as broken rather than as coming soon. */
[data-testid="stSegmentedControl"] button:disabled{
  opacity:.45; cursor:not-allowed;
}
[data-testid="stSegmentedControl"] button:disabled[aria-checked="true"],
[data-testid="stSegmentedControl"] button:disabled[kind="segmented_controlActive"]{
  opacity:.8; color:var(--txt)!important;
}

/* ---- map card ---- */
.map-head{display:flex;align-items:center;gap:10px;padding:2px 0 10px;}
.mh-dot{width:8px;height:8px;border-radius:50%;background:var(--accent);
  box-shadow:0 0 0 4px rgba(46,230,214,.14);flex:none;}
.mh-title{font-family:'Sora',sans-serif;font-weight:600;font-size:1.02rem;
  color:var(--txt);line-height:1.2;}
.mh-note{margin-left:auto;font-size:.74rem;color:var(--dim);}
.legend-strip{display:flex;gap:6px;flex-wrap:wrap;margin-top:11px;align-items:center;}
.lg{display:inline-flex;align-items:center;gap:7px;background:var(--panel-2);
  border:1px solid var(--line);border-radius:999px;padding:4px 11px;
  font-size:.76rem;color:#c3d3e3;white-space:nowrap;}
.lg i{width:10px;height:10px;border-radius:3px;flex:none;}
.lg b{color:var(--dim);font-weight:600;font-variant-numeric:tabular-nums;}
.lg-note{font-size:.74rem;color:var(--dim);margin-left:auto;}

.strip-label{font-size:.74rem;color:var(--mut);margin:2px 0 7px;}
.strip-label b{color:var(--txt);font-weight:600;}
.insp-place{font-family:'Sora',sans-serif;font-weight:700;font-size:1rem;
  color:var(--txt);margin-bottom:9px;line-height:1.25;}

/* ---- inspector ---- */
.insp-empty{padding:26px 18px;text-align:center;color:var(--dim);font-size:.86rem;
  border:1px dashed var(--line);border-radius:14px;background:rgba(17,24,35,.5);}
.insp-row{display:flex;justify-content:space-between;padding:7px 0;
  border-bottom:1px solid rgba(34,48,68,.6);font-size:.86rem;}
.insp-row:last-child{border-bottom:none;}
.insp-k{color:var(--mut);}
.insp-v{color:var(--txt);font-weight:600;font-variant-numeric:tabular-nums;}
.chip{padding:2px 10px;border-radius:10px;font-weight:700;font-size:.76rem;}

/* ---- buttons ---- */
.stDownloadButton button,.stButton button{
  border-radius:10px;font-weight:600;border:1px solid var(--line);
  background:var(--panel-2);color:#cfe0ef;
}
.stDownloadButton button:hover,.stButton button:hover{
  border-color:var(--accent);color:var(--accent);background:rgba(46,230,214,.06);
}
/* Primary buttons (the active sidebar-nav item, the selected day) stay
   visually distinct from the flat styling above — same selector, higher
   specificity. */
.stButton [data-testid="stBaseButton-primary"]{
  background:linear-gradient(135deg,var(--accent),var(--accent-2))!important;
  border-color:transparent!important;color:#06121a!important;
  box-shadow:0 4px 14px rgba(46,230,214,.25);
}
.stButton [data-testid="stBaseButton-primary"]:hover{
  background:linear-gradient(135deg,var(--accent),var(--accent-2))!important;
  border-color:transparent!important;color:#06121a!important;
}

/* ---- misc ---- */
.eyebrow{font-size:.7rem;font-weight:700;letter-spacing:.16em;color:var(--accent);
  text-transform:uppercase;margin-bottom:6px;}
.caveat{font-size:.79rem;color:var(--dim);border-left:2px solid var(--line);
  padding-left:11px;margin:7px 0;}
.stAlert{border-radius:13px;}
.app-footer{margin-top:30px;padding-top:15px;border-top:1px solid var(--line);
  color:var(--dim);font-size:.78rem;display:flex;gap:14px;flex-wrap:wrap;}
.app-footer b{color:var(--mut);}

/* ---- architecture diagram (Data Backbone → Pipeline) ---- */
/* Five lanes left to right, then the feedback lane underneath. The design
   carries two messages at once and must not blur them:
     SHAPE  — sources funnel into one hub, the hub fans out to consumers, and
              the bottom lane closes the circle.
     STATE  — solid nodes exist; DASHED and dimmed nodes are planned.
   Everything numeric inside a built node is measured off the shipped bundle.
   Full write-up: docs/design/PLATFORM_ARCHITECTURE.md */
.arch{border:1px solid var(--line);border-radius:16px;
  padding:18px 18px 14px;background:var(--panel);margin:4px 0 14px;}
.arch-flow{display:flex;align-items:flex-start;justify-content:center;
  gap:4px;flex-wrap:wrap;}
/* Equal-width lanes: flex-basis 0 so all five divide the row evenly rather
   than sizing to their own content, which is what made the columns drift out
   of line against each other. */
.arch-lane{display:flex;flex-direction:column;gap:7px;
  flex:1 1 0;min-width:148px;}
.arch-lname{display:flex;align-items:center;gap:6px;font-size:.66rem;
  font-weight:700;letter-spacing:.13em;text-transform:uppercase;
  color:var(--dim);height:20px;}
.arch-lic{font-size:13px;color:var(--mut);}
/* ⚠️ Fixed height on every node, not padding alone. Node text varies from
   "Align" to "External archives" and a planned node carries an extra pill —
   left to size themselves, boxes in neighbouring lanes ended up at different
   heights and the rows stopped reading as rows. Centring the content inside
   a fixed box keeps every lane on the same rhythm no matter what it says.
   Shorter than it was: the stat line under the name is gone, so a box only
   ever holds one short line now — and there is no hover state any more,
   since there is nothing left to reveal on hover. */
.arch-node{border:1px solid var(--line);border-radius:11px;
  padding:6px 11px;background:var(--panel-2);
  height:48px;display:flex;flex-direction:column;justify-content:center;
  overflow:hidden;}
.arch-nn{font-family:'Sora',sans-serif;font-size:.82rem;font-weight:700;
  color:var(--txt);line-height:1.2;display:flex;align-items:center;
  gap:6px;flex-wrap:wrap;}
.arch-nd{font-size:.69rem;color:var(--dim);margin-top:3px;line-height:1.25;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
/* A product node wears its own module's accent — the same colour the landing
   tile and that module's sidebar use, so the eye connects them. */
.arch-node.arch-prod{border-color:color-mix(in srgb,var(--nc) 40%,var(--line));
  background:linear-gradient(160deg,color-mix(in srgb,var(--nc) 11%,
             transparent),transparent 72%),var(--panel-2);}
.arch-node.arch-prod .arch-nd{color:var(--nc);font-weight:600;}
/* Planned — dashed, dimmed, and marked. Three signals, because this is the
   one distinction the page cannot afford to have missed. The mark is a
   glyph now, not the word "planned" spelled out — the diagram reads as a
   picture; the legend beneath it is the one place that still spells out
   what the glyph means. */
.arch-node.arch-plan{border-style:dashed;background:transparent;opacity:.62;}
.arch-node.arch-plan .arch-nn{color:var(--mut);}
.arch-tag{font-size:.74rem;line-height:1;color:#ffd08a;
  background:rgba(255,176,32,.15);border:1px solid rgba(255,176,32,.32);
  padding:2px 6px;border-radius:999px;white-space:nowrap;}
/* Roughly level with the middle of the FIRST node in each lane — nodes got
   shorter once their stat line was dropped, so this moved up to match. */
.arch-arrow{align-self:flex-start;font-size:19px;color:var(--dim);
  margin-top:36px;flex-shrink:0;}
/* The return path. Full width, pointing back the other way, so "loop" is
   legible as a shape rather than something to read. */
.arch-loop{display:flex;align-items:center;gap:11px;margin-top:13px;
  border:1px dashed var(--line);border-radius:11px;padding:9px 14px;}
.arch-loop-arrow{color:var(--accent-2);font-size:13px;}
.arch-loop-name{font-family:'Sora',sans-serif;font-size:.82rem;
  font-weight:700;color:var(--mut);flex:1;}
.arch-legend{display:flex;align-items:center;gap:16px;flex-wrap:wrap;
  margin-top:12px;padding-top:10px;border-top:1px solid var(--line);
  font-size:.7rem;color:var(--dim);}
.arch-legend i{display:inline-block;width:22px;height:0;vertical-align:middle;
  margin-right:7px;}
.arch-legend .lg-built{border-top:2px solid var(--mut);}
.arch-legend .lg-plan{border-top:2px dashed var(--dim);}
.arch-hint{margin-left:auto;font-style:italic;}

/* ---- landing page: compact, one screen, no scrolling ---- */
/* Each tile carries its module's accent through --tile, set inline, so the
   colour comes from the registry rather than from a rule per module here.
   Adding a fourth module must not mean adding a fourth CSS block. */
/* The narrower centred column everything else sits inside. min-height ties
   to the viewport so a short composition centres vertically too, rather than
   hugging the top-left corner of a much taller page. The 170px subtracted is
   the block-container's own top/bottom padding plus Streamlit's toolbar —
   measured, not guessed, so the block does not overshoot into a scrollbar. */
.st-key-land_wrap{display:flex!important;flex-direction:column!important;
  justify-content:center!important;min-height:calc(100vh - 170px)!important;
  max-width:1000px!important;margin:0 auto!important;}

/* ---- in-page spinners (e.g. "Fetching live rainfall…") ---- */
/* Streamlit's default is a bare line of grey text. This makes it a card that
   belongs to the design. The module-open OVERLAY below overrides it. */
[data-testid="stSpinner"]{
  background:linear-gradient(180deg,var(--panel-2),var(--panel));
  border:1px solid var(--line);border-radius:16px;
  padding:20px 30px;box-shadow:0 12px 34px rgba(0,0,0,.38);
}
[data-testid="stSpinner"] [data-testid="stMarkdownContainer"] p{
  font-family:'Sora',sans-serif;font-size:1.05rem;font-weight:700;
  color:var(--txt);margin:0;
}
[data-testid="stSpinnerIcon"]{
  width:22px!important;height:22px!important;
  border-width:3px!important;color:var(--accent)!important;
}

/* ⚠️ The module-opening splash is NOT styled here. It is an overlay the
   browser injects on the click itself, outside Streamlit's element tree, and
   it carries its own CSS — see core/splash.py for why it cannot be done from
   Python. Nothing in this file should try to reproduce it. */

.land-head{display:flex;align-items:center;justify-content:center;
  gap:12px;margin:2px 0 22px;}
.land-logo{width:38px;height:38px;border-radius:11px;display:grid;
  place-items:center;font-size:19px;color:var(--accent);
  background:color-mix(in srgb,var(--accent) 14%,transparent);
  border:1px solid color-mix(in srgb,var(--accent) 30%,transparent);
  flex-shrink:0;}
.land-title{font-family:'Sora',sans-serif;font-size:1.5rem;font-weight:700;
  letter-spacing:-.02em;color:var(--txt);line-height:1.15;}
.land-title span{display:block;font-family:'Inter',sans-serif;
  font-size:.68rem;font-weight:700;letter-spacing:.16em;color:var(--mut);
  text-transform:uppercase;margin-top:2px;}

/* Module tiles — compact: icon, name, one-line tag, status pill. No blurbs. */
.tile{position:relative;border:1px solid var(--line);border-radius:15px;
  padding:20px 20px 18px;background:
    linear-gradient(160deg,color-mix(in srgb,var(--tile) 9%,transparent),
                    transparent 62%),var(--panel);
  height:120px;overflow:hidden;}
.tile::before{content:'';position:absolute;inset:0 0 auto 0;height:3px;
  background:var(--tile);opacity:.9;}
.tile-top{display:flex;align-items:center;justify-content:space-between;
  margin-bottom:12px;}
.tile-icon{width:32px;height:32px;border-radius:9px;display:grid;
  place-items:center;font-size:16px;color:var(--tile);
  background:color-mix(in srgb,var(--tile) 14%,transparent);
  border:1px solid color-mix(in srgb,var(--tile) 30%,transparent);}
.tile-name{font-family:'Sora',sans-serif;font-size:1.08rem;font-weight:700;
  letter-spacing:-.015em;color:var(--txt);line-height:1.2;}
.tile-tag{color:var(--mut);font-size:.78rem;margin-top:3px;}
.tile-pill{font-size:.62rem;font-weight:700;letter-spacing:.08em;
  text-transform:uppercase;padding:3px 8px;border-radius:999px;}
.tile-pill.live{color:#7ef0c8;background:rgba(46,230,214,.12);
  border:1px solid rgba(46,230,214,.32);}
.tile-pill.wip{color:#ffd08a;background:rgba(255,176,32,.12);
  border:1px solid rgba(255,176,32,.30);}
/* The "more coming" tile: dashed, dimmer, no accent bleed — reads as an empty
   slot, not a fourth real module competing with the other two. */
.tile-ghost{border:1px dashed var(--line);background:transparent;
  display:flex;flex-direction:column;justify-content:center;
  align-items:center;text-align:center;opacity:.55;}
.tile-ghost::before{display:none;}
.tile-ghost .tile-icon{background:transparent;border:1px dashed var(--dim);
  color:var(--dim);margin-bottom:6px;}
.tile-ghost .tile-name{font-size:.92rem;color:var(--mut);}
.tile-ghost .tile-tag{font-size:.72rem;}
/* The button belongs to the tile above it, so close the gap Streamlit leaves
   between the two blocks. */
[class*="st-key-tile_"] .stButton{margin-top:-6px;}
[class*="st-key-tile_"] .stButton button{border-radius:0 0 13px 13px;
  min-height:2.1rem;padding:2px 8px;}

/* Data Backbone: a horizontal strip below the tiles, not a peer card — it is
   the foundation the modules stand on, not a third choice beside them.
   Styled straight on the real st.container (key="backbone_strip"), the same
   trick as .st-key-click_shell — one element, so its own button sits inline
   instead of stacking below like the tiles above it. */
.land-foot-label{color:var(--dim);font-size:.7rem;text-align:center;
  letter-spacing:.08em;text-transform:uppercase;margin:18px 0 9px;}
.st-key-backbone_strip{border:1px solid var(--line)!important;
  border-radius:13px!important;background:var(--panel-2)!important;
  padding:14px 18px!important;}
.backbone-inline{display:flex;align-items:center;gap:11px;}
.backbone-inline .tile-icon{width:30px;height:30px;font-size:15px;
  flex-shrink:0;}
.backbone-strip-name{font-family:'Sora',sans-serif;font-size:.96rem;
  font-weight:700;color:var(--txt);line-height:1.2;}
.backbone-strip-tag{color:var(--dim);font-size:.78rem;margin-top:1px;}
.st-key-backbone_strip .stButton button{min-height:2.3rem;}

/* Entry animation — the landing block fades and lifts in on every render (it
   is rebuilt from scratch each time, whether that is the first visit of the
   session or a click back from a module), so a little motion belongs here
   without turning into a flicker on every module rerun elsewhere in the app.
   Header first, tiles staggered left to right, the backbone strip last. */
@keyframes landIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
.st-key-land_wrap .land-head{animation:landIn .5s ease-out both;}
.st-key-land_tiles [data-testid="stHorizontalBlock"]>div{
  animation:landIn .5s ease-out both;animation-delay:.08s;}
.st-key-land_tiles [data-testid="stHorizontalBlock"]>div:nth-child(2){animation-delay:.14s;}
.st-key-land_tiles [data-testid="stHorizontalBlock"]>div:nth-child(3){animation-delay:.20s;}
.st-key-land_wrap .land-foot-label,.st-key-land_wrap .st-key-backbone_strip{
  animation:landIn .5s ease-out both;animation-delay:.28s;}
@media (prefers-reduced-motion: reduce){
  .st-key-land_wrap .land-head,
  .st-key-land_tiles [data-testid="stHorizontalBlock"]>div,
  .st-key-land_wrap .land-foot-label,.st-key-land_wrap .st-key-backbone_strip{
    animation:none;}
}
</style>
"""


def chip(idx: int) -> str:
    """Coloured class pill. Dark ink on the pale mid-classes, white elsewhere."""
    ink = "#111" if idx in (1, 2) else "#fff"
    return (f"<span class='chip' style='background:{CLASS_COLORS[idx]};color:{ink}'>"
            f"{CLASS_NAMES[idx]}</span>")


def row(k: str, v: str) -> str:
    return (f"<div class='insp-row'><div class='insp-k'>{k}</div>"
            f"<div class='insp-v'>{v}</div></div>")
