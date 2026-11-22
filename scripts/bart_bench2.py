"""
Second round of model selection. Same rule as bart_bench.py: choose on 2024, score once on 2025.

Candidates added to the current pair (deep Poisson + deep absolute-error):
  ratio    predicts riders / recent average, weighted so it still optimises error in riders
  long     the Poisson member trained from mid-2021, not 2022
  bigger   1,500 trees at a lower learning rate
Every equal-weight combination of two to four members is tried on 2024; the best wins only if it
beats the current pair by a clear margin.

Output: data/clean/best_config.json (new 'members' format), public/data/benchmark_round2.json

Run:  python scripts/bart_bench2.py
"""

import itertools
import json
import time

import numpy as np

from bart_core import BASE, CLEAN, EXTRA, ROOT, WEATHER, Blend, design, fit_member, load, wape

OUT = ROOT / "public" / "data"
c = load()
NAMES = BASE + WEATHER + EXTRA
DEEP = dict(max_iter=700, learning_rate=0.05, max_leaf_nodes=127, min_samples_leaf=40)
MEMBERS = {
    "poisson": dict(loss="poisson", l2_regularization=1.0, **DEEP),
    "absolute": dict(loss="absolute_error", **DEEP),
    "ratio": dict(loss="absolute_error", target="ratio", **DEEP),
    "long": dict(loss="poisson", l2_regularization=1.0, train_from="2021-07-01", **DEEP),
    "bigger": dict(loss="poisson", l2_regularization=1.0, max_iter=1500, learning_rate=0.03, max_leaf_nodes=127, min_samples_leaf=40),
}
SCALE = NAMES.index("ewm8")


def predict(model, cfg, X):
    p = model.predict(X)
    if cfg.get("target") == "ratio":
        p = p * (np.nan_to_num(X[:, SCALE]) + 1)
    return np.maximum(p, 0)


def fit_all(ty, keys):
    te = c.year == ty
    X, y = design(c, te, NAMES)
    preds, models = {}, {}
    for k in keys:
        t = time.time()
        models[k] = fit_member(c, MEMBERS[k], NAMES, ty)
        preds[k] = predict(models[k], MEMBERS[k], X)
        print(f"{ty}  {wape(preds[k], y):.4f}  {round(time.time() - t):>4}s  {k}", flush=True)
    return preds, models, y


# ---- choose on 2024
p24, _, y24 = fit_all(2024, list(MEMBERS))
single = {k: round(wape(p, y24), 5) for k, p in p24.items()}
combos = {}
for r in (2, 3, 4):
    for combo in itertools.combinations(MEMBERS, r):
        combos["+".join(combo)] = round(wape(sum(p24[k] for k in combo) / r, y24), 5)
current = combos["poisson+absolute"]
best = min(combos, key=combos.get)
adopt = combos[best] < current - 0.0005
chosen = best.split("+") if adopt else ["poisson", "absolute"]
print("current pair on 2024:", current, "| best combination:", best, combos[best], "| adopt:", adopt, flush=True)

config = {"names": NAMES, "label": "blend of " + " + ".join(chosen), "members": [MEMBERS[k] for k in chosen], "weights": [1 / len(chosen)] * len(chosen)}
(CLEAN / "best_config.json").write_text(json.dumps(config, indent=1), encoding="utf-8")

# ---- score once on 2025
keys25 = sorted(set(chosen) | {"poisson", "absolute"})
p25, _, y25 = fit_all(2025, keys25)
old = wape((p25["poisson"] + p25["absolute"]) / 2, y25)
new = wape(sum(p25[k] for k in chosen) / len(chosen), y25)
out = {"selection_on_2024": {"single_members": single, "combinations": dict(sorted(combos.items(), key=lambda kv: kv[1])[:8]),
                             "current_pair": current, "best": best, "adopted": adopt},
       "error_2025": {"round 1 pair": round(old, 5), "chosen": round(new, 5), "chosen_members": chosen}}
(OUT / "benchmark_round2.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
print(json.dumps(out["error_2025"]))
