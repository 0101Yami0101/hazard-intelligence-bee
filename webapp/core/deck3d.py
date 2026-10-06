"""3D terrain view — the forecast standing on the real shape of the ground.

Why it matters here: a landslide is a slope event, and a flat map is the one
projection that hides slope. In 3D the red ground lines up with the gorge walls
and the forecast shows its reasoning instead of asserting it.

════════════════════════════════════════════════════════════════════════════
WHY CELLS AND NOT A DRAPED IMAGE
════════════════════════════════════════════════════════════════════════════
The obvious approach — hand deck.gl the same PNG the 2D map uses and let it
drape over the terrain mesh — was built and did not render. `_TerrainExtension`
needs a layer whose `operation` contains "terrain" to project onto, and
TerrainLayer is a CompositeLayer: setting `operation` on it does not reach the
mesh sublayers that actually draw. The result is a perfectly good terrain view
with no forecast on it, and no error anywhere.

So the surface is drawn as FLAT PATCHES THAT CARRY THEIR OWN HEIGHT — each
forecast cell placed at [lon, lat, elevation] — which needs no draping and
cannot silently fail. Patches are wider than the grid spacing so they overlap
into a continuous skin. This is what the earlier SlopeSense does: 400 m marks
on a 278 m grid, 1.44x the spacing, flat, lifted clear of the mesh.

⚠️ EXAGGERATION MUST BE APPLIED TO BOTH. The terrain mesh and the point heights
are two independent things that have to agree. Lift the mesh by 1.35 and leave
the points at true metres and the whole surface sinks into the ridges.

════════════════════════════════════════════════════════════════════════════
WHY BINARY
════════════════════════════════════════════════════════════════════════════
A statewide surface is tens of thousands of patches. As JSON objects that is
several megabytes of HTML re-sent on every redraw. Positions and colours are
therefore shipped as base64 typed arrays and fed to deck.gl as binary
attributes: 16 bytes per patch instead of ~70, and no per-patch parsing.
"""
from __future__ import annotations

import base64
import json

import numpy as np

TERRAIN_TILES = ("https://s3.amazonaws.com/elevation-tiles-prod/terrarium/"
                 "{z}/{x}/{y}.png")

# Terrarium encodes height as r*256 + g + b/256 - 32768 metres. Multiplying
# every term by the same factor exaggerates relief without moving sea level.
EXAG = 1.25
DECODER = {"rScaler": 256 * EXAG, "gScaler": 1 * EXAG,
           "bScaler": EXAG / 256, "offset": -32768 * EXAG}
LIFT_M = 60.0        # hold patches clear of the mesh so they never z-fight

# Tile styles WITH cartography baked in — roads, rivers and place names arrive
# as part of the texture, so the 3D view needs no separate label layer.
TEX = {
    # Was CARTO dark_all; CARTO now bakes "API KEY REQUIRED" into its tiles
    # (2026-09-25). Esri's dark canvas carries no place names, so the dark 3D
    # view loses its baked-in labels — the trade for a clean, keyless tile.
    "Dark": ("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/"
             "World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
             "© Esri — World Dark Gray Canvas"),
    "Light": ("https://server.arcgisonline.com/ArcGIS/rest/services/"
              "World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
              "© Esri — World Topo Map"),
    "Terrain": ("https://a.tile.opentopomap.org/{z}/{x}/{y}.png",
                "© OpenTopoMap (CC-BY-SA) · © OpenStreetMap"),
    "Satellite": ("https://server.arcgisonline.com/ArcGIS/rest/services/"
                  "World_Imagery/MapServer/tile/{z}/{y}/{x}",
                  "Imagery © Esri, Maxar"),
}

# deck.gl lights the mesh by MULTIPLYING the texture, which drives an already
# dark basemap to near-black. Lift ambient per style so the tile's own roads and
# labels survive, keeping enough diffuse for the relief to read.
MATERIAL = {
    "Dark": {"ambient": 1.0, "diffuse": 0.75, "shininess": 3,
             "specularColor": [70, 90, 110]},
    "Light": {"ambient": 0.6, "diffuse": 0.55, "shininess": 1,
              "specularColor": [40, 40, 40]},
    "Terrain": {"ambient": 0.6, "diffuse": 0.55, "shininess": 1,
                "specularColor": [40, 40, 40]},
    "Satellite": {"ambient": 0.55, "diffuse": 0.6, "shininess": 2,
                  "specularColor": [50, 50, 50]},
}


def pack_cells(lon, lat, elev_m, rgb, cell_dlon, cell_dlat, alpha=205):
    """Forecast cells as base64 typed arrays for a flat GridCellLayer.

    ⚠️ Positions are the patch's SOUTH-WEST CORNER, not its centre. The layer
    grows each square east and north from the point it is given, so the corner
    is offset by half the PATCH size — not half the grid spacing. Those differ
    whenever patches overlap, and using the spacing there slides the whole
    surface north-east by the difference.

    ⚠️ z is the ground height. These patches are FLAT — see the layer comment
    for why they are not extruded — so there is no block base to subtract.

    `elev_m` is TRUE metres; the exaggeration is applied here so it can never
    drift from the terrain mesh's own.
    """
    n = len(lon)
    pos = np.empty((n, 3), dtype="<f4")
    pos[:, 0] = np.asarray(lon, dtype="float64") - cell_dlon / 2.0
    pos[:, 1] = np.asarray(lat, dtype="float64") - cell_dlat / 2.0
    pos[:, 2] = (np.asarray(elev_m, dtype="float64") + LIFT_M) * EXAG
    col = np.empty((n, 4), dtype=np.uint8)
    col[:, :3] = rgb
    col[:, 3] = int(np.clip(alpha, 0, 255))
    return (base64.b64encode(pos.tobytes()).decode(),
            base64.b64encode(col.tobytes()).decode(), n)


TEMPLATE = """<!doctype html><meta charset="utf-8">
<link rel="preconnect" href="https://unpkg.com">
<link rel="preconnect" href="https://s3.amazonaws.com">
<script src="https://unpkg.com/deck.gl@8.9.36/dist.min.js"></script>
<style>
html,body{margin:0;padding:0;background:transparent;overflow:hidden}
#map{position:absolute;inset:0;border-radius:14px;overflow:hidden;
     border:1px solid #223044;background:#0b0f14}
.badge{position:absolute;bottom:7px;z-index:9;font:10px/1.4 sans-serif;
       color:#8fa3ba;background:rgba(11,15,20,.72);padding:3px 8px;
       border-radius:6px;pointer-events:none}
#attr{right:9px}
#hint{left:9px}
#spin{position:absolute;inset:0;display:flex;align-items:center;
      justify-content:center;z-index:8}
#spin i{width:30px;height:30px;border-radius:50%;display:block;
        border:3px solid rgba(46,230,214,.18);border-top-color:#2ee6d6;
        animation:s .85s linear infinite}
@keyframes s{to{transform:rotate(360deg)}}
</style>
<div id="map"></div>
<div id="spin"><i></i></div>
<div id="attr" class="badge">__ATTR__</div>
<div id="hint" class="badge">drag to pan · right-drag to tilt and rotate · scroll to zoom</div>
<script>
// Right-drag orbits the camera; without this, releasing the right button also
// pops the browser's native context menu over the map.
document.addEventListener('contextmenu', e => e.preventDefault());

const cfg = __CFG__;
const clamp = (v, a, b) => Math.min(Math.max(v, a), b);

function bytes(b64) {
  const bin = atob(b64);
  const a = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i);
  return a;
}

const layers = [
  new deck.TerrainLayer({
    id: 'terrain',
    elevationData: cfg.terrainTiles,
    elevationDecoder: cfg.decoder,
    texture: cfg.texture,
    material: cfg.material,
    maxZoom: 12, minZoom: 2
  })
];

// The forecast surface — FLAT OVERLAPPING PATCHES, so it reads as a skin on
// the terrain rather than as furniture standing on it.
//
// ⚠️ Not extruded. Solid blocks were tried and the side walls of every cell
// showed on any slope — and Arunachal's median slope is 29 degrees, so that
// was almost everywhere. It looked like masonry, not a map.
//
// ⚠️ Not a ScatterplotLayer either. Discs of a fixed radius held together when
// zoomed out and broke into evenly spaced circles as soon as you came close.
//
// The gap between steps is closed by OVERLAP instead of by height: each patch
// is ~1.4x the grid spacing, so a higher patch covers the drop to its
// neighbour. depthTest keeps the nearer patch on top where two overlap, which
// is what stops the overlaps from double-blending into a visible lattice.
//
// Binary attributes: `data` is a length plus raw typed arrays, so deck.gl
// uploads straight to the GPU with no per-cell parsing.
if (cfg.n > 0) {
  const pos = new Float32Array(bytes(cfg.pos).buffer);
  const col = bytes(cfg.col);
  layers.push(new deck.GridCellLayer({
    id: 'forecast',
    data: {length: cfg.n, attributes: {
      getPosition: {value: pos, size: 3},
      getFillColor: {value: col, size: 4}
    }},
    cellSize: cfg.cellSize, extruded: false, coverage: 1,
    // Unlit: the 2D map paints flat class colours, and shading these would
    // make the same class read as two different colours on opposite slopes.
    material: false,
    pickable: false, parameters: {depthTest: true}
  }));
}

if (cfg.paths && cfg.paths.length) layers.push(new deck.PathLayer({
  id: 'roads', data: cfg.paths, getPath: d => d.p, getColor: d => d.c,
  widthUnits: 'meters', getWidth: 90, widthMinPixels: 1.6, widthMaxPixels: 9,
  capRounded: true, jointRounded: true, pickable: true
}));

// The selected place is a COLUMN, not a dot: a flat marker on a ridge is
// invisible from a low camera angle, and it is the thing the visitor came for.
if (cfg.marker) layers.push(new deck.ColumnLayer({
  id: 'pin', data: [cfg.marker], diskResolution: 12, radius: 600,
  extruded: true, pickable: true, getPosition: d => d.pos,
  getElevation: cfg.pinHeight, getFillColor: [46, 230, 214, 180]
}));

document.getElementById('spin').style.display = 'none';
new deck.DeckGL({
  container: 'map', layers,
  initialViewState: {longitude: cfg.centre[1], latitude: cfg.centre[0],
                     zoom: cfg.zoom, pitch: cfg.pitch, bearing: 0},
  controller: {maxPitch: 75, touchRotate: true, dragRotate: true},
  getTooltip: ({object}) => object && object.tip,
  onViewStateChange: ({viewState}) => {
    viewState.longitude = clamp(viewState.longitude, cfg.lock[0], cfg.lock[2]);
    viewState.latitude = clamp(viewState.latitude, cfg.lock[1], cfg.lock[3]);
    viewState.zoom = clamp(viewState.zoom, 5.6, 14.0);
    return viewState;
  }
});
</script>"""


def html(*, basemap: str, bounds: list[float], centre, zoom: float,
         pos_b64: str = "", col_b64: str = "", n_points: int = 0,
         cell_m: float = 700.0, paths=None, marker=None,
         pitch: float = 55.0, pin_height: float = 6000.0) -> str:
    tex, attr = TEX.get(basemap, TEX["Dark"])
    cfg = {
        "terrainTiles": TERRAIN_TILES, "decoder": DECODER, "texture": tex,
        "material": MATERIAL.get(basemap, MATERIAL["Dark"]),
        "pos": pos_b64, "col": col_b64, "n": int(n_points),
        "cellSize": cell_m,
        "paths": paths or [], "marker": marker,
        "centre": [centre[0], centre[1]], "zoom": zoom, "pitch": pitch,
        "pinHeight": pin_height * EXAG,
        # deck.gl has no maxBounds of its own; keep the camera over the region.
        "lock": [bounds[0] - 1.2, bounds[1] - 1.2, bounds[2] + 1.2, bounds[3] + 1.2],
    }
    return (TEMPLATE.replace("__CFG__", json.dumps(cfg))
            .replace("__ATTR__", attr + " · elevation © Mapzen/Tilezen"))
