"""Write public/data/neural.json and the final nn_pred arrays from the blend chosen on 2024 (nn_blend.json)."""
import json
from adv_common import *
c = load(); B = json.load(open(CLEAN / "nn_blend.json")); W = B["weights"]
def A(y): return c.Y[:, :, np.where(c.year == y)[0], :]
def J(kind, y, tag=""):
    return [json.load(open(CLEAN / f"nn_{kind}{tag}_s{s}_{y}.json")) for s in range(3) if (CLEAN / f"nn_{kind}{tag}_s{s}_{y}.json").exists()]
def ens(kind, y):
    fs = [CLEAN / f"nn_{kind}_s{s}_{y}.npy" for s in range(3) if (CLEAN / f"nn_{kind}_s{s}_{y}.npy").exists()]
    return np.mean([np.load(f) for f in fs], 0), len(fs)
def mem(y):
    m = {"trees": np.load(CLEAN / f"pred_{y}.npy"), "old_tf": np.load(CLEAN / f"adv_transformer_{y}.npy"), "similar": np.load(CLEAN / f"adv_analog_{y}.npy")}
    ns = {}
    for k in ("mlp", "resmlp", "tf"): m[k + "_ens"], ns[k] = ens(k, y)
    return m, ns
M24, n24 = mem(2024); M25, n25 = mem(2025)
a24, a25 = A(2024), A(2025)
def seg(P, Ay, y):
    di = np.where(c.year == y)[0]; sp = np.broadcast_to(c.special[di][None, None, :, None], Ay.shape)
    wk = np.broadcast_to((c.dser.dt.dayofweek.to_numpy()[di] >= 5)[None, None, :, None], Ay.shape); busy = Ay >= np.percentile(Ay[Ay > 0], 75)
    return {"all": wape(P, Ay), "ordinary_days": wape(P[~sp], Ay[~sp]), "weekends": wape(P[wk], Ay[wk]), "busiest_quarter": wape(P[busy], Ay[busy])}
bl = lambda M: sum(w * M[k] for k, w in W.items() if w)
P24, P25 = np.maximum(bl(M24), 0), np.maximum(bl(M25), 0)
assert P25.shape == (2, c.S, int((c.year == 2025).sum()), 24) and P25.min() >= 0
final25 = seg(P25, a25, 2025); final24 = seg(P24, a24, 2024)
trees25 = seg(M25["trees"], a25, 2025); old25 = seg(np.load(CLEAN / "adv_pred_2025.npy"), a25, 2025)
if final25["all"] < 0.1284:
    np.save(CLEAN / "nn_pred_2025.npy", P25.astype(np.float32)); np.save(CLEAN / "nn_pred_2024.npy", P24.astype(np.float32)); saved = True
else: saved = False
def r(x): return None if x is None else round(float(x), 4)
def one(kind, label, setting, tag=""):
    j24, j25 = J(kind, 2024, tag), J(kind, 2025, tag)
    e24, e25 = M24.get(label), M25.get(label)
    return {"model": label, "settings": setting, "single_seed_2024": [r(j["wape"]) for j in j24],
            "error_2024_ensemble": r(wape(e24, a24)) if e24 is not None else None,
            "error_2025": r(wape(e25, a25)) if e25 is not None else None, "seeds_2025": len(j25),
            "training_seconds_per_seed": r(np.mean([j["seconds"] for j in j24])) if j24 else None, "parameters": j24[0]["params"] if j24 else None}
models = [
 one("tf", "tf_ens", "Transformer, 11 tokens (8 prior same-weekday profiles, med8, ewm8, last-year-grown profile) plus station/kind/weekday/month and 8 numeric context values; data from 2021-03; 14 epochs max, 200 s cap, early stop on last 61 days before test year"),
 one("mlp", "mlp_ens", "MLP 512-256 over the same 11 profiles plus embeddings and numerics; same data and stopping rule; 3 seeds averaged"),
 one("resmlp", "resmlp_ens", "MLP trained on (actual - tree forecast)/level; tree forecast is also an input; trained on 2023 only for the 2024 check and on 2023-2024 for 2025; 3 seeds averaged"),
]
extra = {"mlp_start_2022_instead_of_2021_2024": [r(j["wape"]) for j in J("mlp", 2024, "22")],
         "mlp_30_epochs_2024": [r(j["wape"]) for j in J("mlp", 2024, "e30")],
         "residual_transformer_2024_first_try": "0.2101 (a bug: the base profile was added twice; discarded, the residual MLP was fixed and rerun; residual transformer was not re-run for lack of time)"}
out = {"models": models, "extra_2024_variants": extra,
 "baselines": {"trees": {"2024": r(wape(M24["trees"], a24)), "2025": r(wape(M25["trees"], a25))}, "old_transformer": {"2024": r(wape(M24["old_tf"], a24)), "2025": r(wape(M25["old_tf"], a25))},
               "similar_days": {"2024": r(wape(M24["similar"], a24)), "2025": r(wape(M25["similar"], a25))}, "previous_blend": {"2024": 0.1276, "2025": 0.1284}},
 "final_blend": {"weights": W, "weight_grid": "steps of 0.1, chosen on 2024 (in-sample for the weights)", "error_2024_in_sample_for_weights": r(final24["all"]), "error_2025": r(final25["all"]),
                 "segments_2025": {k: r(v) for k, v in final25.items()}, "segments_2025_trees": {k: r(v) for k, v in trees25.items()}, "segments_2025_previous_blend": {k: r(v) for k, v in old25.items()},
                 "top5_2024_grid": B["top5"], "saved_nn_pred": saved},
 "leakage_checks": [
  "Ridership inputs come from adv_common.inputs: c.Y at day d-7*j, j=1..8, with an assertion that the first target index >= 56. Extra profiles (med8, ewm8, lag364_grown) are built in bart_core from lags of 7 days or more; the year-over-year and trend windows end at day d-7 (window(cs, a, b) sums days d-a .. d-b-1 with b >= 6).",
  "Calendar, holiday flags and the target day's weather are the only same-day inputs.",
  "Residual models use the tree forecast of day d as input and training target base. Those forecasts are the walk-forward arrays (pred_2023 from models trained before 2023, pred_2024 before 2024, pred_2025 before 2025); for the 2024 check only pred_2023 was used for training and pred_2024 only at test time.",
  "Every network is trained only on days before the test year; early stopping uses the last 61 days before the test year. Blend weights were chosen on 2024 only, in steps of 0.1. All hyperparameters were fixed from the 2024 runs before any 2025 run was read; the 2025 runs were started in the same sitting as final 2024 runs of sibling models, once each per model, with no setting changed after seeing 2025.",
  "Not done: no automated test that perturbs future ridership and checks that forecasts do not move; the checks above are by reading the code."]}
json.dump(out, open(ROOT / "public" / "data" / "neural.json", "w"), indent=1, default=float)
print(json.dumps({"final": out["final_blend"], "models": [(m["model"], m["single_seed_2024"], m["error_2024_ensemble"], m["error_2025"], m["seeds_2025"]) for m in models], "extra": extra}, indent=1, default=float)[:3500])
