"""The one-page forecast report: both forecasts for one place, one district or
the whole state, on a single printable page.

    build(shell, sel) -> str        a self-contained HTML page (A4, light)

Offered as a download from the two forecast pages. The page hands `build` to
the download button as a function, so the report is worked out when the
button is pressed, not on every rerun of the page.

Rules it keeps (the same as the screens it summarises):
  - Every number comes from the functions the screens use — the landslide
    maths in products/landslide/model.py and core/grid.district_raster, the
    flood snapshot and its helpers in products/flood/live.py. Nothing is
    worked out a second way here.
  - A landslide level is a rank, not a chance. The flood outlook near a place
    is approximate; the river-gauge chance is the checked one; "if a flood
    comes" is capped at 20%+. They are never multiplied together.
  - A river above its line shows "unsure", not a small percentage.
  - It says when each forecast was issued: the landslide outlook is worked
    out from the rain as read now, the flood forecast is the daily run's.

No Streamlit calls: it runs on the download button's own thread, where they
would be ignored. (The cached loaders it calls are safe there.)

docs/design/FORECAST_REPORT.md
"""
from __future__ import annotations

import html
from datetime import date, datetime

import numpy as np

import core.geo as G
import core.grid as GR
import core.rainfall as RN
import core.theme as T

LATER_FROM = 4              # landslide days 5-7: weaker rain forecasts
SUS_CUTS = np.array([.05, .15, .35, .60], dtype=np.float32)
LS_INK = ["#ffffff", "#1a1a1a", "#1a1a1a", "#ffffff", "#ffffff"]


def _e(s) -> str:
    return html.escape(str(s), quote=True)


def _pc(x: float) -> str:
    """A share of land, as the SlideSense pages write it."""
    if 0 < x < 0.0005:
        return "<0.1%"
    return f"{100 * x:.1f}%" if x < 0.0995 else f"{100 * x:.0f}%"


def _day(d: str) -> str:
    dd = datetime.fromisoformat(d).date()
    return "Today" if dd == date.today() else dd.strftime("%a %d")


def _clean(label: str) -> str:
    return label.split("  (")[0].split(" #")[0]


def kind_of(sel) -> str:
    return "state" if not sel else "district" if sel["kind"] == "district" else "point"


# ═════════════════════ landslides ════════════════════════════════════════
def landslide(shell, sel) -> dict:
    """SlideSense's facts for the selection. {"error": ...} when live rain
    cannot be read."""
    import products.landslide.model as fc
    from products.landslide.data import load_model

    grid = shell.grid
    SUS, NEAR, QUANT, PTS, MET, _ = load_model()
    fx = RN.load_forecast(tuple(PTS["lat"]), tuple(PTS["lon"]))
    if fx is None:
        return {"error": "Live rainfall could not be read when this report was made, so "
                         "there is no landslide outlook on it."}
    days, rain = fx
    days = [str(d) for d in days]
    trig = fc.trigger_series(rain, QUANT)
    fut = RN.forecast_days(days)
    out = {"days": [days[i] for i in fut], "points": len(PTS["lat"]), "facts": [], "table": None,
           "note": ""}
    wk = [fc.classify(fc.hazard_raster(SUS, NEAR, trig[i])) for i in fut]
    di = fut[0]
    kind = kind_of(sel)

    def share_strip(shares):
        return [(_pc(x), T.CLASS_COLORS[3] if x >= 0.0005 else "#dfe5ec",
                 "#ffffff" if x >= 0.0005 else "#4a5563") for x in shares]

    def counts(mask=None):
        c = np.array([np.bincount(w[mask] if mask is not None else w.ravel(), minlength=6)
                      for w in wk])
        tot = np.maximum(c[:, 1:].sum(axis=1), 1)
        return c, (c[:, 4] + c[:, 5]) / tot, c[:, 5] / tot

    if kind == "district":
        ids, names = GR.district_raster(grid, shell.geo.districts)
        name = sel["label"][:-9] if sel["label"].endswith(" district") else sel["label"]
        if name not in names:
            kind = "point"
        else:
            mask = ids == names.index(name) + 1
            c, hi, vh = counts(mask)
            peak = int(np.nonzero(c[0, 1:])[0].max()) if c[0, 1:].any() else 0
            pr, pcol, pok = grid.to_px_array(np.asarray(PTS["lat"]), np.asarray(PTS["lon"]))
            inside = np.zeros(len(pok), bool)
            inside[pok] = mask[pr[pok], pcol[pok]]
            pj = np.nonzero(inside)[0]
            if not len(pj):
                px = grid.to_px(sel["lat"], sel["lon"])
                pj = np.array([int(NEAR[px])]) if px is not None else np.arange(len(pok))
            out.update(headline=("Land at High or above", _pc(hi[0]),
                                 f"of {name}'s assessed land, today"),
                       strip=share_strip(hi), strip_what="share of the district at High or above")
            out["facts"] = [
                ("Very High today", _pc(vh[0]) + " of its assessed land"),
                ("Highest level in the district today", T.CLASS_NAMES[peak]),
                ("Rain today", f"{float(rain[di, pj].mean()):.0f} mm "
                               f"(average of {len(pj)} rain point{'s' if len(pj) != 1 else ''})"),
                ("Rain vs normal", f"{100 * float(trig[di, pj].mean()):.0f} of 100"),
            ]
            return out

    if kind == "state":
        c, hi, vh = counts()
        ids, names = GR.district_raster(grid, shell.geo.districts)
        n = np.bincount(ids.ravel().astype(np.int64) * 6 + wk[0].ravel(),
                        minlength=(len(names) + 1) * 6).reshape(-1, 6)
        rows = []
        for k, nm in enumerate(names, start=1):
            cc = n[k, 1:]
            if cc.sum():
                rows.append((nm, round(100 * float(cc[3] + cc[4]) / int(cc.sum()), 1),
                             T.CLASS_NAMES[int(np.nonzero(cc)[0].max())]))
        rows.sort(key=lambda r: -r[1])
        out.update(headline=("Land at High or above", _pc(hi[0]),
                             "of assessed land in Arunachal, today"),
                   strip=share_strip(hi), strip_what="share of the state at High or above")
        out["facts"] = [
            ("Very High today", _pc(vh[0]) + " of assessed land"),
            ("Unusually wet rain points", f"{int((trig[di] >= 0.90).sum())} of {len(trig[di])}"),
            ("Wettest point today", f"{float(np.nanmax(rain[di])):.0f} mm"),
            ("Average rain today", f"{float(np.nanmean(rain[di])):.0f} mm"),
        ]
        out["table"] = ("Districts to watch today", ["District", "At High or above", "Highest level"],
                        [(r[0], f"{r[1]:.1f}%", r[2]) for r in rows[:4]])
        return out

    # a town or a point
    px = grid.to_px(sel["lat"], sel["lon"])
    if px is None:
        out["note"] = "This point is outside the mapped area. The model covers Arunachal Pradesh only."
        return out
    snap = fc.nearest_assessed(SUS, *px)
    if snap is None:
        out["note"] = ("Not assessed here: permanent ice, open water, or ground flatter than 10° "
                       "for several kilometres in every direction. The model reports nothing "
                       "there rather than guessing.")
        return out
    r, c_, dcells = snap
    su, j = int(SUS[r, c_]) / 254.0, int(NEAR[r, c_])
    series = np.array([su * trig[i][j] for i in fut], dtype=np.float32)
    dcls = fc.classify(series)
    k = int(dcls[0])
    # the measured "times the usual" behind each level, band of rain and class
    # of ground (docs/design/LANDSLIDE_TIMES_USUAL.md) — never "level k of 5"
    from products.landslide.data import load_times_usual
    tu = load_times_usual() or {}
    xt = lambda x: f"{max(x, 0.1):.1f}×" if x < 0.95 else f"{x:.0f}×"
    lv = (tu.get("levels") or [None] * 5)[k - 1]
    spot = "here" if dcells <= 0 else "on the nearest slope"
    out.update(headline=(f"{T.CLASS_NAMES[k - 1]}",
                         f"{xt(lv['times_usual'])} the usual" if lv else T.CLASS_NAMES[k - 1],
                         (f"landslide outlook {spot}, today — places and days at this level have "
                          "had about that many times the landslides of an average place and day"
                          if lv else f"landslide outlook {spot}, today")),
               strip=[(T.CLASS_NAMES[int(x) - 1], T.CLASS_COLORS[int(x) - 1], LS_INK[int(x) - 1])
                      for x in dcls], strip_what="level at this place")
    sk = int(np.digitize(su, SUS_CUTS)) + 1
    sr = MET["susceptibility"].get("success_rate", [])
    t0 = float(trig[di][j])
    rb = next((b for b in tu.get("rain_bands", [])
               if b["from"] <= t0 < b["to"] or (b["to"] >= 1.0 and t0 >= b["from"])), None)
    out["facts"] = [
        ("This ground", (f"{xt(sr[sk - 1]['lift'])} the landslides of average ground — "
                         if len(sr) == 5 else "")
         + f"{T.CLASS_NAMES[sk - 1]}, score {su:.2f} of 1, the same every day"),
        ("Rain today", (f"{xt(rb['times_usual'])} the landslides of a usual day here — "
                        if rb else "") + f"rain score {100 * t0:.0f} of 100"),
        ("Rain today, measured", f"{rain[di, j]:.0f} mm"),
        ("Rain, last 7 days", f"{rain[max(di - 6, 0):di + 1, j].sum():.0f} mm"),
    ]
    if dcells > 0:
        out["note"] = (f"The point itself is flat ground, water or ice, which the model does not "
                       f"score. Shown is the nearest slope it does score, "
                       f"{dcells * grid.cell_km:.1f} km away.")
    return out


# ═════════════════════ floods ════════════════════════════════════════════
def flood(shell, sel) -> dict | None:
    """FloodSense's facts for the selection, from the daily run's snapshot.
    None when there is no snapshot."""
    from products.flood import live as L

    if not L.available():
        return None
    grid = shell.grid
    mtime = L.SNAPSHOT.stat().st_mtime
    snap, prob, fmeta = L._load(mtime)
    days, nh = snap["days"], snap.get("near_here")
    slot = L._pixel_slot(mtime, grid.west, grid.north, grid.dlon, grid.dlat, grid.height,
                         grid.width)
    link, codes, levels, placed = L._gauge_assets(prob.shape)
    rivers = [dict(r, lat=placed[r["station_code"]][0], lon=placed[r["station_code"]][1])
              if placed.get(r["station_code"]) else r for r in snap["rivers"]]
    out = {"days": days, "issued": snap["issued_on"], "at": snap["generated_at"][-5:],
           "facts": [], "tables": [], "note": "", "headline": None, "strip": None,
           "gauges": len(rivers)}

    def strip(vals):
        o = []
        for v in vals:
            k = L._band(v)
            o.append((L._pct_short(v), L.CHANCE_COLORS[k] if k else "#dfe5ec",
                      L.CHANCE_INK[k] if k else "#4a5563"))
        return o

    def gauge_row(r):
        xs = r["days"]
        if not xs:
            return None
        d_, x = max(xs.items(), key=lambda t: t[1]["p"])
        un = L._week_unsure(r, xs)
        v, thr = r.get("last_day_max"), r["threshold"]
        now = ("offline" if v is None or r.get("gauge_offline") else
               "ABOVE its line" if v >= thr else "below its line")
        return (r["station_name"], L.UNSURE if un else L._pct_short(x["p"]),
                "—" if un else _day(d_), now, x["p"])

    def gauge_table(rs, title):
        rows = sorted((g for g in (gauge_row(r) for r in rs) if g), key=lambda g: -g[4])[:rows_n]
        if rows:
            out["tables"].append((title, ["River gauge", "Chance it reaches its line",
                                          "Highest day", "River now"],
                                  [g[:4] for g in rows]))

    def area_table(js, title):
        if nh is None or not len(js):
            return
        cen = L._centres(mtime)
        towns = L._town_index(mtime, len(shell.places), shell.places)
        wkc = np.asarray(nh["week"], np.float32)
        rows, seen = [], set()
        for j in sorted(js, key=lambda j: -wkc[j]):
            name = L._area_name(int(j), cen, towns)[0]
            if name not in seen:
                seen.add(name)
                rows.append((name, L._pct_short(float(wkc[j])), L.CHANCE_WORDS[L._band(wkc[j])]))
            if len(rows) == rows_n:
                break
        out["tables"].append((title, ["Area (~10 km)", "Flood chance, 7 days", "Level"], rows))

    kind = kind_of(sel)
    # the state page carries three tables: four rows each keeps it to one sheet
    rows_n = 4 if kind == "state" else 5
    if kind == "district":
        ids, names = GR.district_raster(grid, shell.geo.districts)
        name = sel["label"][:-9] if sel["label"].endswith(" district") else sel["label"]
        if name in names and nh is not None:
            mask = ids == names.index(name) + 1
            cen = L._centres(mtime)
            js = [j for j in range(len(cen[0]))
                  if (p := grid.to_px(float(cen[0][j]), float(cen[1][j]))) is not None and mask[p]]
            if js:
                wkc = np.asarray(nh["week"], np.float32)[js]
                top = float(wkc.max())
                daily = [float(np.asarray(nh["daily"][i], np.float32)[js].max())
                         for i in range(len(days))]
                out["headline"] = (f"{L.CHANCE_WORDS[L._band(top)]} flood chance", L._pct_short(top),
                                   f"highest of the {len(js)} areas in {name}, next 7 days")
                out["strip"], out["strip_what"] = strip(daily), "the highest area in the district"
                area_table(js, f"Areas with the highest outlook in {name}")
            else:
                out["note"] = "No area of this district has ground a river flood can reach."
            inside = [r for r in rivers if "lat" in r and (p := grid.to_px(r["lat"], r["lon"]))
                      is not None and mask[p]]
            if inside:
                gauge_table(inside, f"River gauges in {name}")
            else:
                out["facts"].append(("River gauges in the district", "none"))
            return out
        kind = "point"

    if kind == "state":
        if nh is not None:
            a = nh["arunachal_week"]
            out["headline"] = (f"{L.CHANCE_WORDS[L._band(a)]} flood chance", L._pct_short(a),
                               "at least one recorded flood somewhere in Arunachal, next 7 days")
            out["strip"], out["strip_what"] = strip(nh["arunachal_daily"]), "somewhere in Arunachal"
            area_table(list(np.argsort(-np.asarray(nh["week"], np.float32))[:12]),
                       "Areas with the highest outlook")
        above = [r["station_name"] for r in rivers if r["above_threshold_now"]]
        off = [r["station_name"] for r in rivers if r.get("gauge_offline")]
        out["facts"] = [("Rivers above their line now", ", ".join(above) or "none"),
                        ("Gauges reporting", f"{len(rivers) - len(off)} of {len(rivers)}")]
        gauge_table(rivers, "River gauges with the highest chance")
        return out

    # a town or a point
    pl = L._place(sel, grid, slot, prob)
    if pl is None:
        out["note"] = "This point is outside the mapped area. The forecast covers Arunachal Pradesh only."
        return out
    _, _, k, w, near = pl
    if nh is not None and k >= 0:
        wk = float(nh["week"][k])
        out["headline"] = (f"{L.CHANCE_WORDS[L._band(wk)]} flood chance", L._pct_short(wk),
                           "a flood within about 10 km of here, next 7 days")
        out["strip"] = strip([nh["daily"][i][k] for i in range(len(days))])
        out["strip_what"] = "within about 10 km of here"
        n = int(nh["floods_on_record"][k])
        out["facts"].append(("Floods on record within 10 km",
                             f"{n} flood day{'s' if n != 1 else ''} since {L._evidence_since(nh)}"))
    else:
        out["note"] = ("No flood outlook here: no ground a river flood can reach within about "
                       "10 km.")
    if w >= L.FLOODABLE_MIN or not near:
        out["facts"].append(("If a flood comes nearby, water reaches this spot", L._where_str(w)))
    else:
        out["facts"].append(("If a flood comes nearby, water reaches this spot",
                             f"{L._where_str(w)} — raised ground; the low ground "
                             f"{near[0]:.1f} km away: {L._where_str(near[1])}"))
    own = L._own_gauge(pl, link, codes)
    by = {r["station_code"]: r for r in rivers}
    if own and own[0] in by and by[own[0]]["days"]:
        r = by[own[0]]
        g = gauge_row(r)
        line = "official danger level" if r["official"] else "high-water line (its wettest 2% of days)"
        out["facts"].append((f"River gauge on this river: {r['station_name']}",
                             (f"{g[1]} — the river is above its line now and the next days are "
                              "uncertain" if g[1] == L.UNSURE else
                              f"{g[1]} chance it reaches its {line}, highest "
                              + ("today" if g[2] == "Today" else f"on {g[2]}"))))
        v, thr = r.get("last_day_max"), r["threshold"]
        lv = levels.get(r["station_code"]) or {}
        if v is None or r.get("gauge_offline"):
            out["facts"].append(("River now", "gauge offline"))
        elif lv.get("unit") == "m":
            out["facts"].append(("River now", f"{abs(v - thr):.1f} m "
                                 f"{'above' if v >= thr else 'below'} its line "
                                 f"({datetime.fromisoformat(r['last_complete_day']):%d %b})"))
        else:
            out["facts"].append(("River now", f"{100 * v / thr:.0f}% of its line "
                                 f"({datetime.fromisoformat(r['last_complete_day']):%d %b})"))
    else:
        out["facts"].append(("River gauge on this river", "none measures this stretch"))
    return out


# ═════════════════════ the page ══════════════════════════════════════════
CSS = """
@page{size:A4;margin:9mm 12mm;}
*{box-sizing:border-box;-webkit-print-color-adjust:exact;print-color-adjust:exact;}
body{margin:0;background:#eef1f5;color:#17202b;font:12.5px/1.42 Inter,'Segoe UI',Arial,sans-serif;}
.page{width:186mm;margin:8mm auto;background:#fff;padding:9mm 10mm 7mm;border-radius:6px;
  box-shadow:0 2px 14px rgba(0,0,0,.12);}
@media print{body{background:#fff;}.page{margin:0;padding:0;box-shadow:none;width:auto;}.tip{display:none;}}
.tip{width:186mm;margin:6mm auto -3mm;font-size:12px;color:#55606e;}
.top{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;
  border-bottom:3px solid #12303f;padding-bottom:7px;}
.kick{font-size:10px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:#1b7f8c;}
h1{font:700 22px/1.15 Sora,'Segoe UI',Arial,sans-serif;margin:2px 0 1px;letter-spacing:-.01em;}
.sub{color:#55606e;font-size:11.5px;}
.meta{text-align:right;font-size:11px;color:#55606e;white-space:nowrap;}
.meta b{color:#17202b;}
.sec{margin-top:9px;border:1px solid #d5dce5;border-radius:8px;padding:8px 11px 8px;}
.sec-h{display:flex;align-items:center;gap:8px;margin-bottom:6px;}
.sec-t{font:700 13.5px Sora,'Segoe UI',Arial,sans-serif;white-space:nowrap;}
.tag{font-size:9.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
  border:1px solid #9aa7b6;color:#4a5563;border-radius:999px;padding:1px 8px;}
.sec-n{margin-left:auto;font-size:10.5px;color:#6a7685;white-space:nowrap;}
.head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;}
.big{font:800 26px/1 Sora,'Segoe UI',Arial,sans-serif;letter-spacing:-.02em;}
.word{font:700 13px Sora,'Segoe UI',Arial,sans-serif;text-transform:uppercase;letter-spacing:.03em;}
.what{color:#55606e;font-size:11.5px;}
.strip{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin:6px 0 3px;}
.d{border-radius:5px;text-align:center;padding:4px 2px 5px;border:1px solid rgba(0,0,0,.10);}
.d small{display:block;font-size:9.5px;opacity:.85;}
.d b{font-size:11.5px;}
.d.later{border-style:dashed;border-color:rgba(0,0,0,.35);}
.cap{font-size:10px;color:#6a7685;}
.facts{display:grid;grid-template-columns:1fr 1fr;gap:0 16px;margin-top:6px;}
.f{display:flex;justify-content:space-between;gap:10px;padding:3.5px 0;border-bottom:1px solid #e6ebf1;
  font-size:11.5px;}
.f span{color:#55606e;}.f b{text-align:right;font-weight:600;}
.f.wide{grid-column:1 / -1;}
table{width:100%;border-collapse:collapse;margin-top:3px;font-size:11.5px;}
th{text-align:left;font-size:9.5px;letter-spacing:.07em;text-transform:uppercase;color:#6a7685;
  border-bottom:1px solid #c9d2dd;padding:2px 6px 3px 0;}
td{padding:2px 6px 2px 0;border-bottom:1px solid #e6ebf1;}
.tt{font-size:10.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#4a5563;
  margin-top:6px;}
.note{font-size:11px;color:#4a5563;background:#f3f6f9;border-left:3px solid #9aa7b6;
  padding:5px 9px;margin-top:7px;border-radius:0 5px 5px 0;}
.read{margin-top:8px;font-size:10px;line-height:1.36;color:#3d4856;columns:2;column-gap:18px;}
.read p{margin:0 0 4px;break-inside:avoid;}
.foot{margin-top:8px;padding-top:6px;border-top:1px solid #c9d2dd;display:flex;
  justify-content:space-between;gap:10px;font-size:10px;color:#6a7685;}
"""


def _strip(days, cells, later_from) -> str:
    return "<div class='strip'>" + "".join(
        f"<div class='d{' later' if i >= later_from else ''}' style='background:{col};color:{ink}'>"
        f"<small>{_e(_day(d))}</small><b>{_e(txt)}</b></div>"
        for i, (d, (txt, col, ink)) in enumerate(zip(days, cells))) + "</div>"


def _facts(facts) -> str:
    return "<div class='facts'>" + "".join(
        f"<div class='f{' wide' if len(k) + len(v) > 52 else ''}'><span>{_e(k)}</span>"
        f"<b>{_e(v)}</b></div>" for k, v in facts) + "</div>" if facts else ""


def _table(title, cols, rows) -> str:
    return (f"<div class='tt'>{_e(title)}</div><table><tr>"
            + "".join(f"<th>{_e(c)}</th>" for c in cols) + "</tr>"
            + "".join("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in r) + "</tr>" for r in rows)
            + "</table>")


def build(shell, sel, now: datetime | None = None) -> str:
    """The report as one HTML page."""
    now = now or datetime.now()
    kind = kind_of(sel)
    ls = landslide(shell, sel)
    fl = flood(shell, sel)

    if kind == "state":
        title, sub = "Arunachal Pradesh", "whole state"
    elif kind == "district":
        title, sub = sel["label"], "district · figures are for its own outline"
    else:
        title = _clean(sel["label"])
        near, km = G.nearest_place(sel["lat"], sel["lon"], shell.places)
        sub = f"{sel['lat']:.4f}°N, {sel['lon']:.4f}°E"
        if sel["kind"] in ("coords", "me") and near:
            sub += f" · near {_clean(near['label'])}, {km:.0f} km"

    body = []
    # ── landslides ──
    h = ("<div class='sec'><div class='sec-h'><span class='sec-t'>Landslide outlook</span>"
         "<span class='tag'>≈ a rank, not a chance</span>"
         "<span class='sec-n'>SlideSense · worked out from rain read "
         f"{now:%d %b %H:%M}</span></div>")
    if ls.get("error"):
        h += f"<div class='note'>{_e(ls['error'])}</div>"
    else:
        if ls.get("headline"):
            word, big, what = ls["headline"]
            h += (f"<div class='head'><span class='big'>{_e(big)}</span>"
                  f"<span class='word'>{_e(word)}</span><span class='what'>{_e(what)}</span></div>"
                  + _strip(ls["days"], ls["strip"], LATER_FROM)
                  + f"<div class='cap'>Next 7 days — {_e(ls['strip_what'])}. Dashed days rest on "
                    "rain forecasts that are weaker that far ahead.</div>")
        h += _facts(ls["facts"])
        if ls.get("table"):
            h += _table(*ls["table"])
        if ls.get("note"):
            h += f"<div class='note'>{_e(ls['note'])}</div>"
    body.append(h + "</div>")

    # ── floods ──
    if fl is None:
        body.append("<div class='sec'><div class='sec-h'><span class='sec-t'>Flood outlook</span>"
                    "</div><div class='note'>No flood forecast has been issued yet.</div></div>")
    else:
        from products.flood.live import SURE_DAYS
        issued = date.fromisoformat(fl["issued"])
        age = (now.date() - issued).days
        h = ("<div class='sec'><div class='sec-h'><span class='sec-t'>Flood outlook</span>"
             "<span class='tag'>≈ approximate · ✔ checked at gauges</span>"
             f"<span class='sec-n'>FloodSense · issued {issued:%d %b} {fl['at']}"
             + (f" · {age} day{'s' if age != 1 else ''} old" if age > 0 else "") + "</span></div>")
        if fl.get("headline"):
            word, big, what = fl["headline"]
            h += (f"<div class='head'><span class='big'>{_e(big)}</span>"
                  f"<span class='word'>{_e(word)}</span><span class='what'>{_e(what)}</span></div>"
                  + _strip(fl["days"], fl["strip"], SURE_DAYS)
                  + f"<div class='cap'>Each day — {_e(fl['strip_what'])}. Dashed days rest on rain "
                    "forecasts that are weaker that far ahead.</div>")
        h += _facts(fl["facts"])
        for t in fl["tables"]:
            h += _table(*t)
        if fl.get("note"):
            h += f"<div class='note'>{_e(fl['note'])}</div>"
        body.append(h + "</div>")

    read = (
        "<div class='read'>"
        "<p><b>Landslide level, and “× the usual”.</b> How weak the slope is, times how unusual "
        "the rain is for that exact place, cut into five levels. The × beside it is measured: "
        "how many times as common landslides have been at that level as at an average place on "
        "an average day. A rough figure (about 84 dated landslides). It is not a chance of a "
        "landslide.</p>"
        "<p><b>Flood chance near a place.</b> The chance of a recorded flood within about 10 km. "
        "Approximate: good at telling riskier places and weeks from quieter ones; its exact level "
        "can be off.</p>"
        "<p><b>River gauge chance.</b> The chance a gauged river reaches its line (the official "
        "danger level, or its own wettest 2% of days). Checked every day against the gauge. "
        "“Unsure” means the river is above its line now and the next days cannot be called.</p>"
        "<p><b>If a flood comes.</b> How likely water is to reach the exact spot — a property of "
        "the ground, shown no finer than “20%+”. The numbers are never multiplied together.</p>"
        "<p><b>Not covered.</b> Ice, open water and flat ground for landslides; flash floods in "
        "remote valleys, dam releases and water depth for floods. Rain is read at points about "
        "22 km apart.</p>"
        "<p><b>Not for operational safety decisions.</b> A guide to where to look, not a warning "
        "service.</p></div>")

    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>Forecast report — {_e(title)} — {now:%d %b %Y}</title>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<style>{CSS}</style></head><body>"
        "<div class='tip'>To keep this as a PDF: print it (Ctrl+P) and choose “Save as PDF”.</div>"
        "<div class='page'><div class='top'><div><div class='kick'>Landslide and flood forecast "
        f"report</div><h1>{_e(title)}</h1><div class='sub'>{_e(sub)}</div></div>"
        f"<div class='meta'>Made <b>{now:%d %b %Y, %H:%M}</b><br>Covers the next 7 days</div></div>"
        + "".join(body) + read +
        "<div class='foot'><span>BEE Solutions · SlopeSense · SlideSense and FloodSense · Arunachal Pradesh"
        "</span><span>Forecasts are written down each morning; river forecasts are graded daily."
        "</span>"
        "</div></div></body></html>")


def file_name(sel, now: datetime | None = None) -> str:
    now = now or datetime.now()
    name = "arunachal" if not sel else "".join(
        ch if ch.isalnum() else "_" for ch in _clean(sel["label"]).lower()).strip("_")[:40]
    return f"forecast_report_{name or 'place'}_{now:%Y-%m-%d}.html"

def report_button(shell, sel, key: str) -> None:
    """The download button for the one-page report. The report is built when
    the button is pressed (a function is handed over, not the file)."""
    import streamlit as st
    what = ("Arunachal" if not sel else _clean(sel["label"]))
    st.download_button(f"📄  One-page forecast report · {what}",
                       data=lambda: build(shell, sel).encode("utf-8"),
                       file_name=file_name(sel), mime="text/html", key=key,
                       help="Landslide and flood outlook for this selection on one printable "
                            "page. Opens in any browser; print it to save a PDF.")
