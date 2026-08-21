# Hazard Intelligence — Arunachal Pradesh

Landslide and flood forecasting for Arunachal Pradesh, built on one shared
hazard-agnostic core. Three modules ship behind a single Streamlit app:

| Module | What it is | State |
|---|---|---|
| **SlopeSense** | Landslide forecast | live |
| **FloodSense** | Flood forecast | live — static layer unvalidated by design, see [FLOOD_MODULE.md](docs/design/FLOOD_MODULE.md) |
| **Data Backbone** | Source catalogue + pipeline view | live |

## What's actually built

Measured, not claimed — the fuller accounting is in
[PLATFORM_ARCHITECTURE.md](docs/design/PLATFORM_ARCHITECTURE.md).

- **24 external sources**, 11 groups, 10,572 files, 8.06 GB, every fetch
  recording source, licence, URL, fetch date and checksum
- **One canonical grid**: EPSG:32646, 100 m, 8,202,343 in-state cells
- **34 features per cell** — terrain, soil, geology, land cover, hydrology,
  distances
- **LightGBM susceptibility** at spatial-CV AUC 0.859, plus a percentile
  trigger over 9,555 days of rainfall history

Planned but not built: own sensors, partner intake, a public API, the forecast
archive and outcome log. It is a strong pipeline, not yet a loop.

## Layout

```
webapp/     the deployed app — shell, shared core, one folder per module
scripts/    fetch → build → model → viz, run by hand one stage at a time
models/     trained susceptibility folds + trigger
docs/       design notes, data research, feasibility writeups
reports/    validation output and figures
data/       gitignored — 4+ GB, regenerable via scripts/fetch/
```

## Running it

The app is self-contained: it reads a 4.60 MB bundle in `webapp/assets/` and
calls a free weather service. No database, no API key.

```bash
pip install -r requirements.txt
streamlit run webapp/app.py
```

The geospatial and ML stack (rasterio, geopandas, lightgbm, pysheds) is only
needed to rebuild the bundle, not to serve it — that's what lets the app run on
a free 1 GB host. See [webapp/DEPLOY.md](webapp/DEPLOY.md).

## Notes

Credentials, investor material and raw data are excluded by `.gitignore` and
never belong in this repo.
