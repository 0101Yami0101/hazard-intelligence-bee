# Putting the app online — free, about 10 minutes

The app is self-contained. It reads a **5.33 MB** bundle in `assets/` and calls a
free weather service. No database, no API key, no paid tier.

## How the app is laid out

One deployment, several modules behind a landing page.

```
webapp/
  app.py          the shell — landing page and router, no hazard logic
  core/           the shared spine: grid, geography, maps, search, terrain, 3D
  products/       one folder per module, plus the registry that lists them
    landslide/      SlopeSense — live
    flood/          FloodSense — live (static layer unvalidated)
    backbone/       Data Backbone — catalogue + pipeline view
  assets/
    base/           shared geography + the rainfall spine     (2.14 MB)
    landslide/      SlopeSense model output                   (1.59 MB)
    flood/          FloodSense layers, gauges, daily forecast (1.43 MB)
    backbone/       catalogue, statistics, previews           (0.17 MB)
```

`backbone/` summarises **308 GB** of licensed source data in 0.17 MB and
deliberately contains none of it: histograms instead of cell values, previews
at ~6 km per pixel, and synthetic demo rows. See
`scripts/build/build_backbone_bundle.py` for the rule and how it is enforced.

`base/` holds the rainfall query points and climatology as well as the
geography: **both hazards are driven by the same rain**, so filing them under
one module would make the other import from it. One cached fetch serves every
module, so opening the second costs no extra API call.

The entry point is still `webapp/app.py`, so nothing about deployment changes.
Adding a module means a folder in `products/` and one line in
`products/__init__.py` — the shell, sidebar and landing page all read that
registry rather than naming modules themselves.

---

## Step 1 — put the code on GitHub

⚠️ **This is a separate deployment from the original SlopeSense app**
(`0101Yami0101/SlopeSense`) — deliberately, so this platform gets its own new
link rather than overwriting a working one. This codebase already lives in
its own repo, `0101Yami0101/SlopeSense2` (public), with the remote already
configured locally. Pushing today's changes is just:

```bash
cd D:\CODE\BeeDigital\LandSlideFlood
git push
```

### ✅ Already checked for you

- Credentials are excluded. `misc/PlatformPasswords.txt` and `.env` are ignored.
- Investor/business material (`docs/investor/`, `docs/temp/`) is excluded —
  found sitting in the working tree while preparing this deploy, gitignored
  before anything reached the public repo.
- Repo is **~37.7 MB**. The 11+ GB of raw data and 88 MB of GSI PDFs are
  excluded and regenerable from `scripts/fetch/`.

## Step 2 — deploy

1. Go to **<https://share.streamlit.io>** and sign in with GitHub.
2. **Create app → Deploy a public app from GitHub**.
3. Fill in:
   - **Repository:** `0101Yami0101/SlopeSense2`
   - **Branch:** `main`
   - **Main file path:** `webapp/app.py`
4. Open **Advanced settings** and set a custom app URL — pick something that
   does **not** say "slopesense", since this platform is three modules now,
   not one (e.g. `arunachal-hazard-platform`). Left on auto, Streamlit Cloud
   names it after the repo (`slopesense2`) — already a different link from
   the original app, just a less descriptive one to hand someone.
5. Deploy.

Build takes ~2 minutes — the dependency list is deliberately tiny (numpy, pandas,
pillow, requests, streamlit). **No rasterio, geopandas or lightgbm**, which is
what keeps it inside the free tier's 1 GB.

Your link will be `https://<app-name>.streamlit.app`. That is the URL for your
profile.

Every push to `main` redeploys automatically.

### Alternative — Hugging Face Spaces

Also free. Create a Space with the **Streamlit** SDK and add to its `README.md`:

```yaml
sdk: streamlit
app_file: webapp/app.py
```

> ⚠️ **Vercel and Netlify will not work.** They serve static files and serverless
> functions; Streamlit needs a long-running process and an open WebSocket.

---

## Updating what the app shows

The deployed app never runs the pipeline. To refresh it:

```bash
# refresh rainfall history (only needed occasionally)
python scripts/fetch/fetch_20_openmeteo_climatology.py

# rebuild the bundles
python scripts/run/export_webapp_bundle.py       # base/ + landslide/
python scripts/build/build_flood_layers.py       # flood/
python scripts/build/build_backbone_bundle.py    # backbone/ (run last —
                                                 # it measures the others)

git commit -am "Refresh app bundle" && git push     # auto-redeploys
```

The flood builder needs `rasterio`, `geopandas`, `scipy` and `scikit-image`.
Those are pipeline dependencies only — **the deployed app still installs just
numpy, pandas, pillow, requests, streamlit, folium**, which is what keeps it
inside the free tier.

If the susceptibility model is retrained, re-run
`scripts/model/predict_susceptibility.py` first.

---

## Running it locally

```bash
pip install -r webapp/requirements.txt
streamlit run webapp/app.py
```

---

## Free-tier fit

| Constraint | This app |
|---|---|
| Repo size | ~37.7 MB (data excluded) |
| Bundle the app loads | **5.33 MB** (2.14 shared + 1.59 SlopeSense + 1.43 FloodSense + 0.17 Backbone) |
| Memory | well under 1 GB — a few small arrays |
| Build time | ~2 min, 5 slim dependencies |
| API keys | none — Open-Meteo is keyless |
| Live API calls | **3 per hour**, regardless of traffic (1-hour cache) |

## ⚠️ Two things to know before sharing the link

**Open-Meteo's free tier is for non-commercial use.** Fine for a portfolio piece.
If this ever goes to a paying client, move to a paid tier — see
[RAINFALL_RESOLUTION_LIMITS.md](../docs/design/RAINFALL_RESOLUTION_LIMITS.md),
which also restores full 11 km rainfall detail.

**This remains a research prototype, not an operational safety tool.**
The score is a relative ranking, not a probability, and rainfall is sampled at
~33 km. That used to run as a standing caption on every screen; it was pulled
out of the UI to declutter the product, and belongs in a proper limits
write-up under docs/design/ instead of repeated chrome.
