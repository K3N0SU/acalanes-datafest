"""
Where does the day model's error come from? (2025, ordinary days, station total per hour)

1. Counting noise          error a perfect forecast would still make
2. Day level               the whole system runs high or low that day
3. Station-day level       one station runs high or low that day
4. Hour shape              the day's total is right but lands in different hours

Method: rescale the forecast with the true totals ("oracle") one level at a time and see how much
error disappears. Also lists the days the model missed worst, and checks whether a miss today
predicts a miss tomorrow (which a next-day forecast could use).

Input:  data/clean/pred_2025.npy (bart_model.py)
Output: public/data/diagnosis.json

Run:  python scripts/bart_diagnose.py
"""

import json

import numpy as np
import pandas as pd
from scipy.stats import poisson

from bart_core import CLEAN, ROOT, load, wape

OUT = ROOT / "public" / "data"
c = load()
te = c.year == 2025
P = np.load(CLEAN / "pred_2025.npy")
A = c.Y[:, :, te, :]
days = c.days[te]
p, a = P[0] + P[1], A[0] + A[1]                  # (station, day, hour): entering + leaving
ordinary = ~c.special[te]
p, a, days_o = p[:, ordinary, :], a[:, ordinary, :], days[ordinary]


def floor(lam):
    lam = np.maximum(lam, 1e-6)
    return float((2 * lam * poisson.pmf(np.floor(lam), lam)).sum() / lam.sum())


base = wape(p, a)
sys_ratio = a.sum(axis=(0, 2)) / p.sum(axis=(0, 2))                        # per day
p_sys = p * sys_ratio[None, :, None]
with np.errstate(all="ignore"):
    st_ratio = np.nan_to_num(a.sum(axis=2) / p.sum(axis=2), nan=1.0, posinf=1.0)   # per station-day
p_st = p * st_ratio[:, :, None]
steps = {"model as is": base, "if the system's daily total were known": wape(p_sys, a),
         "if each station's daily total were known": wape(p_st, a), "counting noise floor": floor(p)}
parts = {"day level, whole system": base - steps["if the system's daily total were known"],
         "day level, single station": steps["if the system's daily total were known"] - steps["if each station's daily total were known"],
         "hour shape within the day": steps["if each station's daily total were known"] - steps["counting noise floor"],
         "counting noise": steps["counting noise floor"]}

# worst days: the system total against the forecast
day_err = sys_ratio - 1
order = np.argsort(-np.abs(day_err))[:15]
worst = [{"date": str(days_o[i].date()), "weekday": days_o[i].day_name(), "actual_vs_forecast": round(float(day_err[i]), 3)} for i in order]

# does today's miss predict tomorrow's? (all 2025 days in order, ordinary or not, for the lag)
full_ratio = (A.sum(axis=(0, 1, 3)) / P.sum(axis=(0, 1, 3))) - 1
r1 = float(np.corrcoef(full_ratio[1:], full_ratio[:-1])[0, 1])
st_full = np.nan_to_num((A[0] + A[1]).sum(axis=2) / (P[0] + P[1]).sum(axis=2), nan=1.0, posinf=1.0) - 1   # station x day
r1_station = float(np.mean([np.corrcoef(st_full[s, 1:], st_full[s, :-1])[0, 1] for s in range(c.S)]))

# by weekday and by month: is one of them systematically off?
dow = pd.Series(days_o).dt.dayofweek.to_numpy()
by_dow = {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][k]: {"error": round(wape(p[:, dow == k], a[:, dow == k]), 4),
                                                               "bias": round(float(p[:, dow == k].sum() / a[:, dow == k].sum() - 1), 4)} for k in range(7)}
mon = pd.Series(days_o).dt.month.to_numpy()
by_month = {int(k): {"error": round(wape(p[:, mon == k], a[:, mon == k]), 4), "bias": round(float(p[:, mon == k].sum() / a[:, mon == k].sum() - 1), 4)} for k in range(1, 13)}
hr_err = {int(h): round(wape(p[:, :, h], a[:, :, h]), 4) for h in range(5, 24)}
st_err = sorted(((c.stations[s], round(wape(p[s], a[s]), 4), int(a[s].sum() / len(days_o))) for s in range(c.S)), key=lambda t: -t[1])

# ---- how much of the "hour shape" error is knowable at all?
# A look-back that cheats: for each hour, average the same hour one week before AND one week after,
# then give it the true daily total. Nothing that forecasts ahead can beat this by much.
full_a = c.Y[0] + c.Y[1]                                           # all years, (station, day, hour)
idx = np.where(te)[0][ordinary]
ok = (idx + 7 < c.D)
around = (full_a[:, idx[ok] - 7, :] + full_a[:, idx[ok] + 7, :]) / 2
a_ok, p_ok = a[:, ok, :], p[:, ok, :]
with np.errstate(all="ignore"):
    around_scaled = around * np.nan_to_num(a_ok.sum(axis=2) / around.sum(axis=2), nan=1.0, posinf=1.0)[:, :, None]
    p_scaled = p_ok * np.nan_to_num(a_ok.sum(axis=2) / p_ok.sum(axis=2), nan=1.0, posinf=1.0)[:, :, None]
hindsight = {"neighbouring weeks averaged, true daily total given": round(wape(around_scaled, a_ok), 4),
             "our forecast, true daily total given": round(wape(p_scaled, a_ok), 4),
             "neighbouring weeks averaged, as is": round(wape(around, a_ok), 4)}

# ---- the typical day, and the days that are not typical
daily = np.array([wape(p[:, d, :], a[:, d, :]) for d in range(p.shape[1])])
exception = np.abs(day_err) > 0.10                                  # the system total was off by more than 10%
typical = {"median day": round(float(np.median(daily)), 4), "best quarter of days": round(float(np.quantile(daily, 0.25)), 4),
           "worst tenth of days": round(float(np.quantile(daily, 0.9)), 4),
           "days where the whole system was off by over 10%": int(exception.sum()),
           "error on those days": round(wape(p[:, exception, :], a[:, exception, :]), 4),
           "error on all other days": round(wape(p[:, ~exception, :], a[:, ~exception, :]), 4)}

# ---- where riders actually are: weekdays, 6am to 8pm, at the 25 busiest stations
big = np.argsort(-a.sum(axis=(1, 2)))[:25]
wk = dow < 5
core = np.ix_(big, np.where(wk & ~exception)[0], np.arange(6, 20))
core_all = np.ix_(big, np.where(wk)[0], np.arange(6, 20))
core_stats = {"weekdays 6am-8pm, 25 busiest stations": round(wape(p[core_all], a[core_all]), 4),
              "same, leaving out the exception days": round(wape(p[core], a[core]), 4),
              "counting noise floor there": round(floor(p[core]), 4),
              "share of all riders": round(float(a[core_all].sum() / a.sum()), 3)}

out = {"what": "2025, ordinary days, station total per hour", "hindsight_check": hindsight, "typical_day": typical, "core": core_stats, "steps": {k: round(v, 4) for k, v in steps.items()},
       "error_split": {k: round(v, 4) for k, v in parts.items()}, "worst_days": worst,
       "miss_carries_to_next_day": {"whole system": round(r1, 3), "average station": round(r1_station, 3)},
       "by_weekday": by_dow, "by_month": by_month, "by_hour": hr_err,
       "worst_stations": [{"station": s, "error": e, "riders_per_day": n} for s, e, n in st_err[:8]],
       "best_stations": [{"station": s, "error": e, "riders_per_day": n} for s, e, n in st_err[-8:]]}
(OUT / "diagnosis.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
print("steps:", out["steps"])
print("split:", out["error_split"])
print("carry to next day:", out["miss_carries_to_next_day"])
print("weekday:", {k: (v["error"], v["bias"]) for k, v in by_dow.items()})
print("month bias:", {k: v["bias"] for k, v in by_month.items()})
print("hour:", hr_err)
print("worst stations:", st_err[:8])
print("best stations:", st_err[-5:])
for w in worst:
    print("  ", w["date"], w["weekday"][:3], f"{w['actual_vs_forecast']:+.1%}")

print("hindsight:", hindsight)
print("typical:", typical)
print("core:", core_stats)
