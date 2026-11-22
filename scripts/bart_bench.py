"""
Model selection and benchmark.

Rule: every choice (inputs, loss, settings, blend) is made on 2024 only, with models trained on
2022 to 2023. The chosen setup is then trained on 2022 to 2024 and scored ONCE on 2025.

Benchmarked against six methods that need no training:
  last week, 4-week average, 8-week median, exponentially weighted 8 weeks,
  last year grown to this year's level, and a ridge regression on the same lags.

Output: public/data/benchmark.json, data/clean/best_config.json (read by bart_model.py)

Run:  python scripts/bart_bench.py
"""

import json
import time

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

from bart_core import BASE, CLEAN, EXTRA, ROOT, WEATHER, design, load, wape

OUT = ROOT / "public" / "data"
c = load()
V1 = BASE + WEATHER
V2 = V1 + EXTRA
CAT = "station"


def gbm(names, loss="poisson", **kw):
    p = dict(max_iter=300, learning_rate=0.08, max_leaf_nodes=63, random_state=7)
    p.update(kw)
    return HistGradientBoostingRegressor(loss=loss, categorical_features=[names.index(CAT)], **p)


def split(ty):
    return (c.year >= 2022) & (c.year < ty), c.year == ty


def simple_methods(te):
    f = lambda n: np.nan_to_num(c.F[n][:, :, te, :].reshape(-1))
    return {"same hour last week": f("lag7"), "average of last 4 weeks": np.nan_to_num(c.mean4[:, :, te, :].reshape(-1)),
            "median of last 8 weeks": f("med8"), "weighted average of last 8 weeks": f("ewm8"),
            "last year, grown to this year": f("lag364_grown")}


def ridge(ty):
    names = ["lag7", "lag14", "lag21", "lag28", "mean8", "med8", "lag364_grown", "ewm8"]
    tr, te = split(ty)
    Xtr, ytr = design(c, tr, names)
    Xte, _ = design(c, te, names)
    m = Ridge(alpha=1.0).fit(np.nan_to_num(Xtr), ytr)
    return np.maximum(m.predict(np.nan_to_num(Xte)), 0)


def run(names, ty, **kw):
    tr, te = split(ty)
    Xtr, ytr = design(c, tr, names)
    Xte, yte = design(c, te, names)
    t = time.time()
    m = gbm(names, **kw).fit(Xtr, ytr)
    return np.maximum(m.predict(Xte), 0), yte, m, round(time.time() - t)


# ------------------------------------------------------------------ 1. choose on 2024
VARIANTS = {
    "v1: first model (15 everyday inputs + weather)": dict(names=V1),
    "v2: + 13 new inputs": dict(names=V2),
    "v2, optimise absolute error": dict(names=V2, loss="absolute_error"),
    "v2, deeper and slower": dict(names=V2, max_iter=700, learning_rate=0.05, max_leaf_nodes=127, min_samples_leaf=40, l2_regularization=1.0),
    "v2, deeper, absolute error": dict(names=V2, loss="absolute_error", max_iter=700, learning_rate=0.05, max_leaf_nodes=127, min_samples_leaf=40),
}
val, preds24 = {}, {}
for label, cfg in VARIANTS.items():
    p, y24, _, secs = run(ty=2024, **cfg)
    preds24[label] = p
    val[label] = {"error_2024": round(wape(p, y24), 5), "fit_seconds": secs}
    print(f"2024  {val[label]['error_2024']:.4f}  {secs:>4}s  {label}", flush=True)

ranked = sorted(val, key=lambda k: val[k]["error_2024"])
best, second = ranked[0], ranked[1]
# blend the two best, and the best with the 8-week median; weights chosen on 2024
_, te24 = split(2024)
med24 = np.nan_to_num(c.F["med8"][:, :, te24, :].reshape(-1))
blends = {}
for w in (0.5, 0.6, 0.7, 0.8, 0.9):
    blends[f"{w}*best + {round(1 - w, 1)}*second"] = wape(w * preds24[best] + (1 - w) * preds24[second], y24)
    blends[f"{w}*best + {round(1 - w, 1)}*median8"] = wape(w * preds24[best] + (1 - w) * med24, y24)
bkey = min(blends, key=blends.get)
use_blend = blends[bkey] < val[best]["error_2024"] - 0.0005   # only if it clearly helps
print("best single:", best, "| best blend:", bkey, round(blends[bkey], 5), "| use blend:", use_blend, flush=True)

config = {k: v for k, v in VARIANTS[best].items()}
config["label"] = best
if use_blend:
    w = float(bkey.split("*")[0])
    config["blend"] = {"weight": w, "with": "second" if "second" in bkey else "median8",
                       "second": VARIANTS[second] if "second" in bkey else None}
(CLEAN / "best_config.json").write_text(json.dumps(config, indent=1), encoding="utf-8")

# ------------------------------------------------------------------ 2. score once on 2025
tr, te = split(2025)
p_new, y, model, _ = run(ty=2025, **VARIANTS[best])
if use_blend:
    other = run(ty=2025, **VARIANTS[second])[0] if config["blend"]["with"] == "second" else np.nan_to_num(c.F["med8"][:, :, te, :].reshape(-1))
    p_new = config["blend"]["weight"] * p_new + (1 - config["blend"]["weight"]) * other
p_v1 = run(ty=2025, names=V1)[0]
methods = {**simple_methods(te), "ridge regression on the same lags": ridge(2025),
           "first model (v1)": p_v1, "final model": p_new}

shape = (2, c.S, int(te.sum()), 24)
X, _ = design(c, te, ["hour", "dow", "rain_day"])
hour, dow, rain = X[:, 0], X[:, 1], X[:, 2]
special = np.broadcast_to(c.special[te].reshape(1, 1, -1, 1), shape).reshape(-1)
segments = {
    "all hours": np.ones(len(y), bool),
    "ordinary days (no holidays)": ~special,
    "weekday commute hours": (dow < 5) & (((hour >= 6) & (hour < 10)) | ((hour >= 15) & (hour < 19))) & ~special,
    "weekday off-peak": (dow < 5) & ~(((hour >= 6) & (hour < 10)) | ((hour >= 15) & (hour < 19))) & ~special,
    "weekends": (dow >= 5) & ~special,
    "busiest quarter of hours": y >= np.quantile(y[y > 0], 0.75),
    "rainy days (5 mm+)": rain >= 5,
}
oak = np.zeros(shape, bool)
for s in ("12TH", "19TH", "LAKE", "FTVL", "COLS", "WOAK", "MCAR", "ROCK"):
    oak[:, c.sidx[s]] = True
segments["Oakland stations"] = oak.reshape(-1)

table = {name: {seg: round(wape(p[m], y[m]), 4) for seg, m in segments.items()} for name, p in methods.items()}
for name, p in methods.items():
    table[name]["avg miss, riders per station-hour"] = round(float(np.abs(p - y).mean()), 2)
    table[name]["bias"] = round(float((p.sum() - y.sum()) / y.sum()), 4)
    ss_res, ss_tot = float(((p - y) ** 2).sum()), float(((y - y.mean()) ** 2).sum())
    table[name]["r2"] = round(1 - ss_res / ss_tot, 4)

# rider-facing tests, on the station total (entering + leaving) per hour
def by_station_day(p):
    a = p.reshape(shape)
    return a[0] + a[1]  # (S, days, 24)

act = by_station_day(y)
train_days = (c.year >= 2022) & (c.year < 2025)
typical_peak = np.median((c.Y[0][:, train_days, :] + c.Y[1][:, train_days, :]).max(axis=2), axis=1)  # per station, from training years
packed_act = act >= 0.8 * typical_peak[:, None, None]
open_day = act.sum(axis=2) > 50
rider = {}
for name, p in methods.items():
    pr = by_station_day(p)
    exact = (pr.argmax(axis=2) == act.argmax(axis=2))[open_day]
    near = (np.abs(pr.argmax(axis=2) - act.argmax(axis=2)) <= 1)[open_day]
    packed_pr = pr >= 0.8 * typical_peak[:, None, None]
    tp = float((packed_pr & packed_act).sum()); fp = float((packed_pr & ~packed_act).sum()); fn = float((~packed_pr & packed_act).sum())
    day_err = np.abs(pr.sum(axis=2) - act.sum(axis=2)).sum() / act.sum()
    rider[name] = {"names the busiest hour exactly": round(float(exact.mean()), 4), "within one hour": round(float(near.mean()), 4),
                   "packed hours caught": round(tp / (tp + fn), 4), "packed warnings that were right": round(tp / (tp + fp), 4) if tp + fp else None,
                   "daily total error": round(float(day_err), 4)}

# which inputs matter: shuffle one input at a time on a sample of 2025 and see how much worse it gets
names = VARIANTS[best]["names"]
Xte, _ = design(c, te, names)
rng = np.random.default_rng(7)
idx = rng.choice(len(Xte), 300_000, replace=False)
Xs, ys = Xte[idx], y[idx]
base_err = wape(model.predict(Xs), ys)
importance = {}
for j, n in enumerate(names):
    Xp = Xs.copy()
    Xp[:, j] = rng.permutation(Xp[:, j])
    importance[n] = round(wape(np.maximum(model.predict(Xp), 0), ys) - base_err, 4)
importance = dict(sorted(importance.items(), key=lambda kv: -kv[1]))

final, lw, v1 = table["final model"]["all hours"], table["same hour last week"]["all hours"], table["first model (v1)"]["all hours"]
best_simple = min((v["all hours"], k) for k, v in table.items() if k not in ("final model", "first model (v1)"))
summary = {"final_error_2025": final, "vs_last_week": round(1 - final / lw, 3), "vs_best_simple_method": round(1 - final / best_simple[0], 3),
           "best_simple_method": best_simple[1], "vs_first_model": round(1 - final / v1, 3), "chosen": config["label"],
           "blend": config.get("blend"), "station_hours_scored": int(len(y)), "riders_2025": int(c.Y[0][:, te, :].sum())}
(OUT / "benchmark.json").write_text(json.dumps({"summary": summary, "selection_on_2024": val, "blends_on_2024": {k: round(v, 5) for k, v in blends.items()},
                                                "error_2025": table, "rider_tests_2025": rider, "input_importance": importance,
                                                "inputs": names}, indent=1), encoding="utf-8")
print(json.dumps(summary, indent=1))
for name in methods:
    print(f"{table[name]['all hours']:.4f}  commute {table[name]['weekday commute hours']:.4f}  wkend {table[name]['weekends']:.4f}  "
          f"rain {table[name]['rainy days (5 mm+)']:.4f}  peak±1h {rider[name]['within one hour']:.3f}  packed caught {rider[name]['packed hours caught']:.3f}  {name}")
print("top inputs:", list(importance.items())[:8])
