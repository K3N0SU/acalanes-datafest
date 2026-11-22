"""
Event uplift: how many riders a game adds at the venue's station, hour by hour.

Input:  data/clean/station_hour.csv.gz, data/clean/games.csv, data/clean/pred_YYYY.npy (bart_model.py)
Output: public/data/events_test.json   error on game hours with vs without the event layer
        public/data/uplift.json        riders per 1,000 attendees by hour offset (final curves, used by the harness)

The uplift used to test year Y is fitted only on earlier years, and only on residuals from
predictions the model made for years it had not seen.
Attendance is not known before a game, so the test uses the venue's average from earlier years
(separately for weekday and weekend games).

Run:  python scripts/bart_events.py
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean"
OUT = ROOT / "public" / "data"

PRED_YEARS = [2023, 2024, 2025]
OFFSETS = list(range(-4, 8))

sh = pd.read_csv(CLEAN / "station_hour.csv.gz", parse_dates=["date"])
sh = sh[(sh["date"] >= "2021-01-01") & (sh["date"] <= "2025-12-31")]
stations = sorted(sh["station"].unique())
sidx = {s: i for i, s in enumerate(stations)}
days = pd.date_range("2021-01-01", "2025-12-31", freq="D")
didx = {d: i for i, d in enumerate(days)}
Y = np.zeros((2, len(stations), len(days), 24), dtype=np.float32)
Y[0, sh["station"].map(sidx), sh["date"].map(didx), sh["hour"]] = sh["entries"]
Y[1, sh["station"].map(sidx), sh["date"].map(didx), sh["hour"]] = sh["exits"]
year0 = {y: didx[pd.Timestamp(f"{y}-01-01")] for y in PRED_YEARS}
P = {y: np.load(CLEAN / f"pred_{y}.npy") for y in PRED_YEARS}

games = pd.read_csv(CLEAN / "games.csv", parse_dates=["date"])
games = games[games["station"].isin(sidx) & games["attendance"].notna() & (games.get("sport", "baseball") == "baseball")].copy()
games["year"] = games["date"].dt.year
games["h0"] = np.floor(games["start_hour"]).astype(int)
games["part"] = np.where(games["start_hour"] < 16, "day", "night")
games["wk"] = np.where(games["date"].dt.dayofweek >= 5, "weekend", "weekday")


def cells(g):
    """(kind, offset index, actual, model prediction) around one game"""
    y = g["year"]
    d, s = didx[g["date"]], sidx[g["station"]]
    for j, off in enumerate(OFFSETS):
        h = g["h0"] + off
        if 0 <= h <= 23:
            for k in range(2):
                yield k, j, h, Y[k, s, d, h], P[y][k, s, d - year0[y], h]


def fit(gs):
    """ratio estimator: extra riders per attendee, per (station, day/night, kind, offset)"""
    coef = {}
    for key, grp in gs.groupby(["station", "part"]):
        num = np.zeros((2, len(OFFSETS)))
        for _, g in grp.iterrows():
            for k, j, _, act, pr in cells(g):
                num[k, j] += act - pr
        coef[key] = (num / grp["attendance"].sum(), len(grp))
    att = gs.groupby(["station", "wk"])["attendance"].mean().to_dict()
    return coef, att


def apply(g, coef, att, known_attendance=False):
    c = coef.get((g["station"], g["part"]))
    if c is None:
        return None
    a = g["attendance"] if known_attendance else att.get((g["station"], g["wk"]))
    out = []
    for k, j, h, act, pr in cells(g):
        out.append((k, h, act, pr, max(pr + a * c[0][k, j], 0)))
    return out


def wape(p, a):
    return float(np.abs(np.asarray(p) - np.asarray(a)).sum() / np.asarray(a).sum())


tests = []
for ty in (2024, 2025):
    coef, att = fit(games[(games["year"] >= 2023) & (games["year"] < ty)])
    for st, gs in games[games["year"] == ty].groupby("station"):
        act, base, ev, evk = [], [], [], []
        pk_act, pk_base, pk_ev = [], [], []
        for _, g in gs.iterrows():
            r = apply(g, coef, att)
            rk = apply(g, coef, att, known_attendance=True)
            if r is None:
                continue
            act += [x[2] for x in r]; base += [x[3] for x in r]; ev += [x[4] for x in r]; evk += [x[4] for x in rk]
            # the single busiest hour of that game window (entries + exits)
            tot = {}
            for (k, h, a, b, e) in r:
                t = tot.setdefault(h, [0, 0, 0]); t[0] += a; t[1] += b; t[2] += e
            hmax = max(tot, key=lambda h: tot[h][0])
            pk_act.append(tot[hmax][0]); pk_base.append(tot[hmax][1]); pk_ev.append(tot[hmax][2])
        if not act:
            continue
        row = {"year": ty, "station": st, "games": int(len(gs)), "hours": len(act),
               "wape_without": round(wape(base, act), 4), "wape_with": round(wape(ev, act), 4),
               "wape_with_known_attendance": round(wape(evk, act), 4),
               "peak_hour_wape_without": round(wape(pk_base, pk_act), 4), "peak_hour_wape_with": round(wape(pk_ev, pk_act), 4),
               "peak_hour_avg_actual": round(float(np.mean(pk_act))), "peak_hour_avg_without": round(float(np.mean(pk_base))),
               "peak_hour_avg_with": round(float(np.mean(pk_ev)))}
        row["error_cut"] = round(1 - row["wape_with"] / row["wape_without"], 3)
        tests.append(row)
        print(row)

# example day for the chart: the best-attended 2025 night game
coef25, att25 = fit(games[(games["year"] >= 2023) & (games["year"] < 2025)])
g = games[(games["year"] == 2025) & (games["part"] == "night")].sort_values("attendance", ascending=False).iloc[0]
s, d = sidx[g["station"]], didx[g["date"]]
ex = {"date": str(g["date"].date()), "station": g["station"], "team": g["team"], "start_hour": float(g["start_hour"]),
      "attendance": int(g["attendance"]), "actual": (Y[0, s, d] + Y[1, s, d]).tolist(),
      "without": (P[2025][0, s, d - year0[2025]] + P[2025][1, s, d - year0[2025]]).round(0).tolist()}
w = np.array(ex["without"], dtype=float)
for (k, h, a, b, e) in apply(g, coef25, att25):
    w[h] += e - b
ex["with"] = w.round(0).tolist()

# final curves for live use: fitted on every out-of-sample year we have
coef, att = fit(games[games["year"] >= 2023])
uplift = {}
for (st, part), (c, n) in coef.items():
    uplift[f"{st}_{part}"] = {"station": st, "part": part, "games": int(n), "offsets": OFFSETS,
                              "entries_per_1000": (c[0] * 1000).round(2).tolist(), "exits_per_1000": (c[1] * 1000).round(2).tolist()}
# a generic curve for venues we have no history for: all games pooled
allc = {}
for part, grp in games[games["year"] >= 2023].groupby("part"):
    num = np.zeros((2, len(OFFSETS)))
    for _, gg in grp.iterrows():
        for k, j, _, act, pr in cells(gg):
            num[k, j] += act - pr
    c = num / grp["attendance"].sum()
    uplift[f"GENERIC_{part}"] = {"station": "GENERIC", "part": part, "games": int(len(grp)), "offsets": OFFSETS,
                                 "entries_per_1000": (c[0] * 1000).round(2).tolist(), "exits_per_1000": (c[1] * 1000).round(2).tolist()}
    print(part, "share of attendees arriving by BART (exits, hours -4..0):", round(float(c[1][:5].sum()), 3),
          "| leaving by BART (entries, hours +2..+7):", round(float(c[0][6:].sum()), 3))

(OUT / "events_test.json").write_text(json.dumps({"tests": tests, "example": ex}, indent=1), encoding="utf-8")
(OUT / "uplift.json").write_text(json.dumps(uplift, indent=1), encoding="utf-8")
print("wrote events_test.json, uplift.json")
