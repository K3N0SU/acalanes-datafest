"""
Capacity model trained on the cost of being wrong: gradient-boosted trees with a pinball (quantile) loss,
so the forecast is the rider count that is exceeded in only 5% of hours, instead of the average.

Same inputs and walk-forward split as bart_model.py (train on 2022 up to the year before the test year).
Compared against the mean forecast plus one flat safety margin chosen on 2024.

Output: data/clean/q95_pred_2024.npy, q95_pred_2025.npy (shape 2 x 50 x days x 24)
        public/data/capacity_quantile.json
Run:    python scripts/capacity_quantile.py [extra quantiles, e.g. 0.90 0.99]
"""

import json
import sys
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from bart_core import CLEAN, ROOT, design, load

STANDARD = 0.95
MAX_ROWS = 1_500_000
SETTINGS = dict(max_iter=300, learning_rate=0.08, max_leaf_nodes=127, min_samples_leaf=40, random_state=7)
NAMES = json.loads((CLEAN / "best_config.json").read_text(encoding="utf-8"))["names"]
c = load()
rng = np.random.default_rng(7)


def station_hours(F, year):
    """entries + exits by station and service hour (5..23), flattened"""
    return (F[0] + F[1])[:, :, 5:24].reshape(-1)


def actual(year):
    return station_hours(c.Y[:, :, c.year == year, :], year)


def fit_predict(q, year):
    mask = (c.dser >= pd.Timestamp("2022-01-01")).to_numpy() & (c.year < year)
    X, y = design(c, mask, NAMES)
    if len(y) > MAX_ROWS:
        idx = rng.choice(len(y), MAX_ROWS, replace=False)
        X, y = X[idx], y[idx]
    m = HistGradientBoostingRegressor(loss="quantile", quantile=q, categorical_features=[NAMES.index("station")], **SETTINGS)
    m.fit(X, y)
    te = c.year == year
    Xt, _ = design(c, te, NAMES)
    return np.maximum(m.predict(Xt), 0).reshape(2, c.S, int(te.sum()), 24), len(y)


def coverage(cap, act):
    k = act > 0
    return float((cap[k] >= act[k]).mean())


def cap_per_rider(cap, act):
    k = act > 0
    return float(cap[k].sum() / act[k].sum())


def correction_for(cap, act, target=STANDARD):
    """one multiplier so that `target` of station-hours are covered: the target quantile of actual / capacity"""
    k = (act > 0) & (cap > 0)
    return float(np.quantile(act[k] / cap[k], target))


a24, a25 = actual(2024), actual(2025)

# ---- comparison: mean forecast plus one flat margin chosen on 2024
n24 = station_hours(np.load(CLEAN / "nn_pred_2024.npy"), 2024)
n25 = station_hours(np.load(CLEAN / "nn_pred_2025.npy"), 2025)
k = (a24 > 0) & (n24 > 0)
margin = float(np.quantile(a24[k] / n24[k], STANDARD) - 1)
m25 = n25 * (1 + margin)
margin_method = {"margin": round(margin, 4), "coverage_2024": round(coverage(n24 * (1 + margin), a24), 4),
                 "coverage_2025": round(coverage(m25, a25), 4), "capacity_per_rider": round(cap_per_rider(m25, a25), 4)}
print("margin method", margin_method, flush=True)


def run(q, save):
    t0 = time.time()
    p24, rows = fit_predict(q, 2024)
    p25, _ = fit_predict(q, 2025)
    secs = time.time() - t0
    if save:
        np.save(CLEAN / f"q{int(round(q * 100))}_pred_2024.npy", p24)
        np.save(CLEAN / f"q{int(round(q * 100))}_pred_2025.npy", p25)
    s24, s25 = station_hours(p24, 2024), station_hours(p25, 2025)
    raw24, raw25 = coverage(s24, a24), coverage(s25, a25)
    corr = correction_for(s24, a24)
    out = {"quantile": q, "raw_coverage_2024": round(raw24, 4), "raw_coverage_2025": round(raw25, 4),
           "raw_capacity_per_rider": round(cap_per_rider(s25, a25), 4),
           "coverage_2024": round(coverage(s24 * corr, a24), 4), "coverage_2025": round(coverage(s25 * corr, a25), 4),
           "correction": round(corr, 4), "capacity_per_rider": round(cap_per_rider(s25 * corr, a25), 4)}
    print(out, f"{secs:.0f}s", flush=True)
    return out, rows, secs


main, rows, secs = run(STANDARD, True)
others = [run(float(q), False)[0] for q in sys.argv[1:]]

saving = 1 - main["capacity_per_rider"] / margin_method["capacity_per_rider"]
if saving > 0:
    verdict = (f"Trained on the cost of running short, the model covers riders in {main['coverage_2025']:.0%} of 2025 station-hours "
               f"with {saving:.1%} less capacity than a flat safety margin on the average forecast.")
else:
    verdict = (f"Training on the cost of running short did not help: to cover {main['coverage_2025']:.0%} of 2025 station-hours it needs "
               f"{-saving:.1%} more capacity than a flat safety margin on the average forecast.")

result = {
    "what": "Capacity needed so riders fit in 95% of station-hours (entries + exits, 5am to midnight, 2025), "
            "from trees trained on a 95th-percentile loss versus the average forecast plus one flat margin. Both are tuned on 2024 only.",
    "standard": STANDARD,
    "cost_trained": {k: main[k] for k in ("coverage_2024", "coverage_2025", "correction", "capacity_per_rider")}
                    | {"raw_coverage_2025": main["raw_coverage_2025"], "raw_capacity_per_rider": main["raw_capacity_per_rider"]},
    "margin_method": margin_method,
    "less_capacity_than_margin_method": round(saving, 4),
    "verdict": verdict,
    "other_quantiles": others,
    "training": {"rows": rows, "seconds": round(secs), "settings": {"loss": "quantile", "quantile": STANDARD, "train_from": "2022-01-01", **SETTINGS}},
}
(ROOT / "public" / "data" / "capacity_quantile.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
print(verdict)
