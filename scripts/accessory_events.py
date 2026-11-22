"""
Event accessories. Standalone; the main model is not retrained.

1. Crowd predictor ("game importance"). How many people will come to a baseball game, from things
   known in advance: opponent, weekday, month, day or night, opening day, how the season has drawn
   so far. Tested against the plain guess (last season's weekday or weekend average) on attendance,
   and then on what matters: the rider forecast at the station during game hours.
2. Football curve. Riders added at Downtown Berkeley by a Cal home game, measured on 2023 and 2024
   and tested on 2025, against the borrowed baseball curve.

Same rule as every accessory: learn on earlier years, test on a later one.

Input:  data/clean/games.csv, pred_2023..2025.npy
Output: public/data/accessory_events.json; adds DBRK curves to public/data/uplift.json

Run:  python scripts/accessory_events.py
"""

import json

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from bart_core import CLEAN, ROOT, load, wape

OUT = ROOT / "public" / "data"
OFFSETS = list(range(-4, 8))
c = load()
P = {y: np.load(CLEAN / f"pred_{y}.npy") for y in (2023, 2024, 2025)}
year0 = {y: c.didx[pd.Timestamp(f"{y}-01-01")] for y in P}

games = pd.read_csv(CLEAN / "games.csv", parse_dates=["date"])
games = games[(games["attendance"].fillna(0) > 500) & games["station"].isin(c.sidx)]  # a few games have no gate recorded.sort_values(["team", "date", "start_hour"]).reset_index(drop=True)
games["year"] = games["date"].dt.year
games["h0"] = np.floor(games["start_hour"]).astype(int)
games["part"] = np.where(games["start_hour"] < 16, "day", "night")
games["wk"] = np.where(games["date"].dt.dayofweek >= 5, "weekend", "weekday")


def cells(g):
    y, d, s = g["year"], c.didx[g["date"]], c.sidx[g["station"]]
    for j, off in enumerate(OFFSETS):
        h = g["h0"] + off
        if 0 <= h <= 23:
            for k in range(2):
                yield k, j, c.Y[k, s, d, h], P[y][k, s, d - year0[y], h]


def fit_curve(gs):
    """extra riders per attendee by (station, day/night, direction, hour offset)"""
    coef = {}
    for key, grp in gs.groupby(["station", "part"]):
        num = np.zeros((2, len(OFFSETS)))
        for _, g in grp.iterrows():
            for k, j, act, pr in cells(g):
                num[k, j] += act - pr
        coef[key] = (num / grp["attendance"].sum(), len(grp))
    return coef


def game_error(gs, coef, attendance_col, curve_station=None):
    """rider error over game hours, with and without the event layer, for a given attendance estimate"""
    act, base, ev = [], [], []
    for _, g in gs.iterrows():
        cf = coef.get((curve_station or g["station"], g["part"]))
        for k, j, a, pr in cells(g):
            act.append(a); base.append(pr)
            ev.append(max(pr + (g[attendance_col] * cf[0][k, j] if cf else 0), 0))
    return wape(base, act), wape(ev, act), len(act)


# ------------------------------------------------------------------ 1. crowd predictor
bb = games[games["sport"] == "baseball"].copy()
bb["opp"] = bb["opponent"].astype("category").cat.codes
bb["team_id"] = bb["team"].astype("category").cat.codes
bb["dow"], bb["month"] = bb["date"].dt.dayofweek, bb["date"].dt.month
bb["night"] = (bb["part"] == "night").astype(int)
bb["game_no"] = bb.groupby(["team", "year"]).cumcount() + 1
bb["opening_day"] = (bb["game_no"] == 1).astype(int)
prev = bb.groupby(["team", "year"])["attendance"].mean().rename("prev_season").reset_index()
prev["year"] += 1
bb = bb.merge(prev, on=["team", "year"], how="left")
prev_wk = bb.groupby(["team", "year", "wk"])["attendance"].mean().rename("plain_guess").reset_index()
prev_wk["year"] += 1
bb = bb.merge(prev_wk, on=["team", "year", "wk"], how="left")
prev_opp = bb.groupby(["team", "year", "opp"])["attendance"].mean().rename("prev_vs_opp").reset_index()
prev_opp["year"] += 1
bb = bb.merge(prev_opp, on=["team", "year", "opp"], how="left")
# this season so far, using only games at least a week old
bb["season_so_far"] = np.nan
for (team, year), grp in bb.groupby(["team", "year"]):
    for i, g in grp.iterrows():
        past = grp[grp["date"] <= g["date"] - pd.Timedelta(days=7)]["attendance"]
        if len(past) >= 3:
            bb.loc[i, "season_so_far"] = past.mean()
FEATS = ["team_id", "opp", "dow", "month", "night", "game_no", "opening_day", "prev_season", "prev_vs_opp", "season_so_far"]

crowd = {}
bb["predicted"] = np.nan
for ty in (2024, 2025):
    tr, te = bb[(bb["year"] < ty) & (bb["year"] >= 2022)], bb[bb["year"] == ty]
    m = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.05, max_depth=3, min_samples_leaf=8, random_state=7,
                                      categorical_features=[0, 1]).fit(tr[FEATS], np.log(tr["attendance"]))
    bb.loc[te.index, "predicted"] = np.exp(m.predict(te[FEATS]))
    te = bb.loc[te.index]
    coef = fit_curve(bb[(bb["year"] >= 2023) & (bb["year"] < ty)])
    for team, g in te.groupby("team"):
        base, plain, n = game_error(g, coef, "plain_guess")
        _, smart, _ = game_error(g, coef, "predicted")
        _, known, _ = game_error(g, coef, "attendance")
        crowd[f"{team} {ty}"] = {
            "games": int(len(g)), "station": g["station"].iloc[0],
            "attendance_error_plain_guess": round(float((g["plain_guess"] - g["attendance"]).abs().sum() / g["attendance"].sum()), 4),
            "attendance_error_predictor": round(float((g["predicted"] - g["attendance"]).abs().sum() / g["attendance"].sum()), 4),
            "rider_error_model_alone": round(base, 4), "rider_error_event_layer_plain_guess": round(plain, 4),
            "rider_error_event_layer_with_predictor": round(smart, 4), "rider_error_if_attendance_were_known": round(known, 4)}
        print(f"crowd {team} {ty}: attendance {crowd[f'{team} {ty}']['attendance_error_plain_guess']:.3f} -> {crowd[f'{team} {ty}']['attendance_error_predictor']:.3f}"
              f" | riders {base:.3f} -> {plain:.3f} -> {smart:.3f} (known: {known:.3f})")

# ------------------------------------------------------------------ 2. football curve
fb = games[(games["sport"] == "football") & games["year"].isin(P)].copy()
fb_prev = games[games["sport"] == "football"].groupby("year")["attendance"].mean()
fb["expected"] = fb["year"].map(lambda y: fb_prev.get(y - 1))
test, train = fb[fb["year"] == 2025], fb[fb["year"] < 2025]
football_curve = fit_curve(train)
baseball_pooled = {}
bb_fit = bb[(bb["year"] >= 2023) & (bb["year"] < 2025)]
for part, grp in bb_fit.groupby("part"):
    num = np.zeros((2, len(OFFSETS)))
    for _, g in grp.iterrows():
        for k, j, act, pr in cells(g):
            num[k, j] += act - pr
    baseball_pooled[("POOL", part)] = (num / grp["attendance"].sum(), len(grp))
alone, with_baseball, n = game_error(test, baseball_pooled, "expected", curve_station="POOL")
_, with_football, _ = game_error(test, football_curve, "expected")
football = {"games_tested": int(len(test)), "games_learned_from": int(len(train)), "station": "DBRK",
            "rider_error_model_alone": round(alone, 4), "rider_error_borrowed_baseball_curve": round(with_baseball, 4),
            "rider_error_football_curve": round(with_football, 4)}
print("football 2025:", football)

# curves for live use: every football game we have
up = json.loads((OUT / "uplift.json").read_text(encoding="utf-8"))
for (st, part), (cf, n) in fit_curve(fb).items():
    up[f"{st}_{part}"] = {"station": st, "part": part, "games": int(n), "offsets": OFFSETS, "sport": "football",
                          "entries_per_1000": (cf[0] * 1000).round(2).tolist(), "exits_per_1000": (cf[1] * 1000).round(2).tolist()}
(OUT / "uplift.json").write_text(json.dumps(up, indent=1), encoding="utf-8")
(OUT / "accessory_events.json").write_text(json.dumps({"crowd_predictor": crowd, "crowd_predictor_inputs": FEATS, "football_curve": football}, indent=1), encoding="utf-8")
print("wrote accessory_events.json")
