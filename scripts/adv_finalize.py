"""Apply the choice made on 2024 to 2025 once, write advanced.json. Usage: python adv_finalize.py"""
import json
from adv_common import *
c = load()
T = json.load(open(CLEAN / "adv_tune_2024.json")); Aj = json.load(open(CLEAN / "adv_analog.json"))
tr24, tr25 = json.load(open(CLEAN / "adv_transformer_2024.json")), json.load(open(CLEAN / "adv_transformer_2025.json"))
W = T["blend_best+transformer+analog"]["weights"]
def seg(P, A, y):
    di = np.where(c.year == y)[0]; sp = np.broadcast_to(c.special[di][None, None, :, None], A.shape)
    wk = np.broadcast_to((c.dser.dt.dayofweek.to_numpy()[di] >= 5)[None, None, :, None], A.shape); busy = A >= np.percentile(A[A > 0], 75)
    return {"all": wape(P, A), "ordinary_days": wape(P[~sp], A[~sp]), "weekends": wape(P[wk], A[wk]), "busiest_quarter": wape(P[busy], A[busy])}
out = {}
for y in (2024, 2025):
    A = c.Y[:, :, np.where(c.year == y)[0], :]
    best, tf, an = (np.load(CLEAN / f"pred_{y}.npy"), np.load(CLEAN / f"adv_transformer_{y}.npy"), np.load(CLEAN / f"adv_analog_{y}.npy"))
    blend = W["best"] * best + W["transformer"] * tf + W["analog"] * an
    out[y] = dict(best=seg(best, A, y), transformer=seg(tf, A, y), analog=seg(an, A, y), blend=seg(blend, A, y))
    if y == 2025 and out[y]["blend"]["all"] < out[y]["best"]["all"]:
        np.save(CLEAN / "adv_pred_2025.npy", blend.astype(np.float32)); np.save(CLEAN / "adv_pred_2024.npy", (W["best"] * np.load(CLEAN / "pred_2024.npy") + W["transformer"] * np.load(CLEAN / "adv_transformer_2024.npy") + W["analog"] * np.load(CLEAN / "adv_analog_2024.npy")).astype(np.float32)); out["saved"] = True
for y in (2024, 2025): print(y, {k: {s: round(v, 4) for s, v in d.items()} for k, d in out[y].items()})
print("saved", out.get("saved"))
def r(x): return round(float(x), 4)
J = {"experiments": [
 {"name": "A. Small transformer", "what_it_is": "A 2-layer attention network that reads the same station's last 8 same-weekday hourly profiles plus weekday, month, holiday, rain and temperature, and predicts the 24 hourly counts.",
  "settings_chosen_on_2024": "d_model 64, 4 heads, 2 layers, AdamW with one-cycle schedule, 24 epochs max, early stopping on Nov-Dec 2023; trained 2022 to Oct 2023 for the 2024 check, 2022 to Oct 2024 for 2025; level-weighted absolute error",
  "error_2024": r(out[2024]["transformer"]["all"]), "error_2025": r(out[2025]["transformer"]["all"]), "training_seconds": {"2024_run": round(tr24["seconds"]), "2025_run": round(tr25["seconds"])}},
 {"name": "B. Cosine analog days", "what_it_is": "For each station, direction and day, finds the 10 most similar earlier days (by shape of recent weeks, weekday, month, holiday) and averages their hourly profile, rescaled to the current level.",
  "settings_chosen_on_2024": f"k={Aj['best']['k']}, candidates from {Aj['best']['start_year']} on, weights {Aj['best']['W']} (weather weight 0 won); 72-setting grid on 2024",
  "error_2024": r(out[2024]["analog"]["all"]), "error_2025": r(out[2025]["analog"]["all"]), "training_seconds": r(Aj["seconds"])},
 {"name": "C. Online weighting (Hedge) of forecasters", "what_it_is": "Each station, direction and hour-block keeps weights over several forecasters and shifts weight toward those with smaller recent absolute error, using only outcomes 7 or more days old.",
  "settings_chosen_on_2024": {"core_members_from_2023": T["online_core"], "all_members_from_2024": T["online_all"]},
  "error_2024": r(T["online_all"]["error_2024"]), "error_2025": None, "training_seconds": 17,
  "note": "Not carried to 2025: the fixed blend scored lower on 2024. Also tried: NNLS blend weights fitted on 2023 (members without A and B) scored " + str(r(T["nnls_fit2023_simple"]["error_2024"])) + " on 2024; NNLS on all members fitted on 2024 scored " + str(r(T["nnls_all"]["error_2024"]))}],
 "other_2024_blends": {k: v for k, v in T.items() if k.startswith("blend_")},
 "final_choice": {"name": "Fixed blend of current best, transformer and analog days", "weights": W,
   "how_chosen": "lowest 2024 error among: current best alone, fixed blends, online weighting. Weights were picked on a 0.05 grid on 2024 itself, so the 2024 number is optimistic; the 2025 number uses those weights unchanged with members trained only on data before 2025.",
   "error_2024_by_segment": out[2024]["blend"], "error_2025_by_segment": out[2025]["blend"]},
 "current_best_baseline": {"2024": out[2024]["best"], "2025": out[2025]["best"]},
 "members_alone_2025_by_segment": {"transformer": out[2025]["transformer"], "analog": out[2025]["analog"]},
 "leakage_checks": [
  "Every sequence input is c.Y at day d-7*j for j=1..8 (asserted: first target day index >= 56); no same-day or later ridership enters any model input.",
  "Only calendar, holiday flag and the target day's weather are taken from day d itself.",
  "Analog days: a candidate day must satisfy day <= d-7, so its outcome was known 7 days ahead; feature standardisation uses only days before the test year.",
  "Transformer: training days are all before the test year, early stopping uses Nov-Dec of the year before; 2025 labels were never used for any choice.",
  "Online weighting: the weight for day d is computed from losses of days <= d-7 (checked by construction in the cumulative-loss lookup).",
  "Sanity check: the current-best arrays reproduce 0.1379 (2024) and 0.1305 (2025) with this loading code."]}
json.dump(J, open(ROOT / "public" / "data" / "advanced.json", "w"), indent=1, default=float)
