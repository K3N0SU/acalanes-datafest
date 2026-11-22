"""
What a better forecast is worth to BART: fewer empty cars for the same crowding standard.

BART pays for every car it runs, full or empty. Capacity is planned as expected riders plus a
safety margin, and the worse the forecast, the bigger the margin has to be. Here each planning
method gets the margin it needs so that capacity covers the riders in 90, 95 or 99% of hours.
The margin is set on 2024 and applied to 2025 unchanged, so 2025 is a fair test.

Methods compared:
  same hour last week         the obvious guess
  average of last 4 weeks     a planner's rule of thumb
  fixed timetable             set twice a year by weekday and hour from the previous 13 weeks
  timetable with its own      the strongest plan without a forecast: each station, weekday and hour
  margin per hour             gets the 95th percentile of the previous 26 weeks
  tree models                 our gradient-boosted trees
  final ensemble              our five forecasters blended (60% neural networks)
  cost-trained trees          trees trained on a 95th-percentile loss: running short costs more than running long

Dollars use published BART and FTA figures (see SOURCES). Only electricity is counted, as a floor.

Output: public/data/capacity.json
Run:    python scripts/capacity.py
"""

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bart_core import CLEAN, ROOT, load  # noqa: E402

OUT = ROOT / "public" / "data"

CAR_HOURS = 2_333_890          # vehicle revenue hours, FTA National Transit Database 2024 agency profile
ELECTRICITY = 53_700_000       # dollars, "Electric Power" line, BART FY25 Q4 financial report
TRACTION_SHARE = 0.81          # share of purchased electricity that moves trains (BART)
OPERATING = 1_061_500_000      # dollars, total operating expense FY25 (BART FY25 Q4 financial report, unaudited)
PRECEDENT = 12_000_000         # dollars a year BART said it saved by running shorter trains from September 2023
POWER_PER_CAR_HOUR = ELECTRICITY * TRACTION_SHARE / CAR_HOURS
SOURCES = [
    {"what": "car-hours run a year (vehicle revenue hours)", "value": CAR_HOURS, "source": "FTA National Transit Database, 2024 agency profile for BART", "status": "from a search excerpt"},
    {"what": "electricity cost a year", "value": ELECTRICITY, "source": "BART FY25 fourth-quarter financial report", "status": "from a search excerpt"},
    {"what": "share of electricity that moves trains", "value": TRACTION_SHARE, "source": "BART", "status": "from a search excerpt"},
    {"what": "total operating expense", "value": OPERATING, "source": "BART FY25 fourth-quarter financial report, unaudited", "status": "from a search excerpt"},
    {"what": "saving from shorter trains, per year", "value": PRECEDENT, "source": "bart.gov/node/41246 (2023)", "status": "confirmed"},
]

c = load()
dates = pd.Series(pd.to_datetime(c.dser.to_numpy()))
dow = dates.dt.dayofweek.to_numpy()


def totals(x):
    """(direction, station, day, hour) -> entries plus exits by station, day and service hour (5 AM to midnight)"""
    return (x[0] + x[1])[:, :, 5:24]


T_ALL = totals(c.Y)


def timetable():
    """a schedule fixed for six months at a time: each weekday and hour gets the average of the previous 13 weeks"""
    out = np.full(T_ALL.shape, np.nan)
    for y in (2024, 2025):
        for start, end in ((pd.Timestamp(y, 1, 1), pd.Timestamp(y, 7, 1)), (pd.Timestamp(y, 7, 1), pd.Timestamp(y + 1, 1, 1))):
            cur = ((dates >= start) & (dates < end)).to_numpy()
            ref = ((dates >= start - pd.Timedelta(days=91)) & (dates < start)).to_numpy()
            for w in range(7):
                out[:, cur & (dow == w), :] = T_ALL[:, ref & (dow == w), :].mean(axis=1, keepdims=True)
    return out


def timetable_peak():
    """the strongest plan without a forecast: each station, weekday and hour gets its own margin, the 95th percentile of the previous 26 weeks"""
    out = np.full(T_ALL.shape, np.nan)
    for y in (2024, 2025):
        for start, end in ((pd.Timestamp(y, 1, 1), pd.Timestamp(y, 7, 1)), (pd.Timestamp(y, 7, 1), pd.Timestamp(y + 1, 1, 1))):
            cur = ((dates >= start) & (dates < end)).to_numpy()
            ref = ((dates >= start - pd.Timedelta(days=182)) & (dates < start)).to_numpy()
            for w in range(7):
                out[:, cur & (dow == w), :] = np.quantile(T_ALL[:, ref & (dow == w), :], 0.95, axis=1, keepdims=True)
    return out


def rolling_peak(weeks=26):
    """not a timetable: a rule refreshed every week. each station and hour gets the 95th percentile of the same weekday
    over the previous 26 weeks, the newest of them 7 days old. the strongest plan without machine learning that we found"""
    T = T_ALL.astype("float32")
    stack = np.full((weeks,) + T.shape, np.nan, dtype="float32")
    for k in range(1, weeks + 1):
        stack[k - 1][:, 7 * k:, :] = T[:, :-7 * k, :]
    return np.nanquantile(stack, 0.95, axis=0)


TT = timetable()
TP = timetable_peak()
RP = rolling_peak()


def methods(y):
    te = c.year == y
    return T_ALL[:, te], {
        "same hour last week": totals(np.nan_to_num(c.lag7))[:, te],
        "average of last 4 weeks": totals(np.nan_to_num(c.mean4))[:, te],
        "fixed timetable": TT[:, te],
        "timetable with its own margin per hour": TP[:, te],
        "weekly rolling rule": RP[:, te],
        "tree models": totals(np.load(CLEAN / f"pred_{y}.npy")),
        "final ensemble": totals(np.load(CLEAN / f"nn_pred_{y}.npy")),
        # trained on the cost of being wrong (95th-percentile loss) instead of average error: scripts/capacity_quantile.py
        **({"cost-trained trees": totals(np.load(CLEAN / f"q95_pred_{y}.npy"))} if (CLEAN / f"q95_pred_{y}.npy").exists() else {}),
    }


def level(x, kind):
    return x.sum(axis=0).reshape(-1) if kind == "system" else x.reshape(-1)


def margin_for(pred, act, target):
    ok = (act > 0) & (pred > 0)
    return float(np.quantile(act[ok] / pred[ok], target) - 1)


A24, M24 = methods(2024)
A25, M25 = methods(2025)
RULES = ("same hour last week", "average of last 4 weeks", "fixed timetable", "timetable with its own margin per hour", "weekly rolling rule")
# which of our models to put forward is decided on 2024: the one needing the least capacity to cover 95% of 2024 station-hours
_a24 = A24.reshape(-1)
PICK_2024 = {n: round(float((M24[n].reshape(-1) * (1 + margin_for(M24[n].reshape(-1), _a24, 0.95))).sum() / _a24.sum()), 4) for n in M24 if n not in RULES}
OURS = min(PICK_2024, key=PICK_2024.get)
levels = {}
for kind in ("station", "system"):
    a24, a25 = level(A24, kind), level(A25, kind)
    ok = a25 > 0
    levels[kind] = {}
    for target in (0.90, 0.95, 0.99):
        rows = {}
        for name in M24:
            p24, p25 = level(M24[name], kind), level(M25[name], kind)
            m = margin_for(p24, a24, target)
            cap = p25 * (1 + m)
            rows[name] = {"method": name, "margin": round(m, 4), "covered_2025": round(float((cap[ok] >= a25[ok]).mean()), 4),
                          "capacity_per_rider": round(float(cap.sum() / a25.sum()), 4),
                          "idle_capacity": round(float(np.maximum(cap - a25, 0).sum() / a25.sum()), 4)}
        for name, r in rows.items():
            r["less_capacity_than"] = {b: round(1 - r["capacity_per_rider"] / rows[b]["capacity_per_rider"], 4) for b in RULES if b != name}
        levels[kind][f"{target:.2f}"] = list(rows.values())

# the mirror image: with the same number of cars as the 4-week rule runs, how often is an hour over capacity?
same_cars = {}
for kind in ("station", "system"):
    a25 = level(A25, kind)
    ok = a25 > 0
    budget = next(r for r in levels[kind]["0.95"] if r["method"] == "average of last 4 weeks")["capacity_per_rider"]
    same_cars[kind] = {"cars_run_per_rider": budget, "methods": []}
    for name in M25:
        p25 = level(M25[name], kind)
        cap = p25 * (budget * a25.sum() / p25.sum())
        same_cars[kind]["methods"].append({"method": name, "hours_over_capacity": round(float((a25[ok] > cap[ok]).mean()), 4),
                                           "riders_over_capacity": round(float(np.maximum(a25 - cap, 0).sum() / a25.sum()), 4)})


# the fair dollar comparison: every method gets the margin that covers exactly 95% of hours in 2025,
# so all of them meet the same achieved standard (a margin set on 2024 can go stale: the timetable's did)
equal = {}
for kind in ("station", "system"):
    a25 = level(A25, kind)
    rows = {}
    for name in M25:
        p25 = level(M25[name], kind)
        m = margin_for(p25, a25, 0.95)
        rows[name] = {"method": name, "margin": round(m, 4), "capacity_per_rider": round(float((p25 * (1 + m)).sum() / a25.sum()), 4)}
    for name, r in rows.items():
        r["less_capacity_than"] = {b: round(1 - r["capacity_per_rider"] / rows[b]["capacity_per_rider"], 4) for b in RULES if b != name}
    equal[kind] = list(rows.values())


def saving(kind, base, method=OURS):
    return next(r for r in equal[kind] if r["method"] == method)["less_capacity_than"][base]


def dollars(share):
    hours = share * CAR_HOURS
    return {"share_of_car_hours": round(share, 4), "car_hours_a_year": int(round(hours, -2)), "electricity_dollars_a_year": int(round(hours * POWER_PER_CAR_HOUR, -4)),
            "share_of_operating_budget": round(hours * POWER_PER_CAR_HOUR / OPERATING, 5)}


cands = {f"{kind} level, against {base}": saving(kind, base) for kind in ("station", "system") for base in ("average of last 4 weeks", "fixed timetable", "timetable with its own margin per hour")}
low_k, high_k = min(cands, key=cands.get), max(cands, key=cands.get)
out = {
    "what": "capacity each planning method must run so that it covers the riders in a given share of hours; margin set on 2024, tested on 2025",
    "demand_measure": "entries plus exits by station and hour, 5 AM to midnight, 50 stations",
    "decisions_a_year": int(A25.size),
    "levels": levels,
    "same_cars": same_cars,
    "equal_standard_2025": {"what": "capacity needed when every method covers exactly 95% of 2025 hours", "levels": equal},
    "fewer_crowded_hours_with_the_same_cars": {kind: round(1 - next(m for m in same_cars[kind]["methods"] if m["method"] == OURS)["hours_over_capacity"]
                                                              / next(m for m in same_cars[kind]["methods"] if m["method"] == "timetable with its own margin per hour")["hours_over_capacity"], 4) for kind in same_cars},
    "fewer_crowded_hours_than_a_plain_timetable": {kind: round(1 - next(m for m in same_cars[kind]["methods"] if m["method"] == OURS)["hours_over_capacity"]
                                                                  / next(m for m in same_cars[kind]["methods"] if m["method"] == "fixed timetable")["hours_over_capacity"], 4) for kind in same_cars},
    "headline": {"standard": 0.95, "method": OURS, "chosen_on_2024_capacity_per_rider": PICK_2024, "savings_against_planning_rules": {k: round(v, 4) for k, v in cands.items()},
                 "against_same_hour_last_week": {"station": saving("station", "same hour last week"), "system": saving("system", "same hour last week")},
                 "against_weekly_rolling_rule": {kind: {"less_capacity": saving(kind, "weekly rolling rule"), **dollars(saving(kind, "weekly rolling rule"))} for kind in ("station", "system")},
                 "low": {"basis": low_k, **dollars(cands[low_k])}, "high": {"basis": high_k, **dollars(cands[high_k])}},
    "dollar_inputs": {"car_hours_a_year": CAR_HOURS, "power_dollars_per_car_hour": round(POWER_PER_CAR_HOUR, 2), "all_costs_dollars_per_car_hour": round(OPERATING / CAR_HOURS),
                      "operating_budget": OPERATING, "bart_saving_from_shorter_trains_2023": PRECEDENT, "sources": SOURCES},
    "assumptions": ["car-hours scale with the capacity planned; BART already changes train length by schedule",
                    "only electricity is counted, so the dollar figure is a floor: car wear and maintenance are left out because we could not measure them",
                    "drivers, stations and track are paid either way and are not counted",
                    "demand is gate entries and exits, not how full each train is between stations",
                    "the fixed timetable here is our stand-in for one; it is not BART's actual schedule"],
}
(OUT / "capacity.json").write_text(json.dumps(out, indent=1), encoding="utf-8")

for kind in ("station", "system"):
    print(f"--- {kind} hour, 95% standard")
    for r in levels[kind]["0.95"]:
        print(f"  {r['method']:<26} margin {r['margin']:>6.1%} | covered {r['covered_2025']:.1%} | capacity {r['capacity_per_rider']:.3f}x")
    print("  same cars:", {m["method"]: m["hours_over_capacity"] for m in same_cars[kind]["methods"]})
for kind in equal:
    print(f"--- {kind} hour, equal 95% achieved on 2025:", {r["method"]: r["capacity_per_rider"] for r in equal[kind]})
print("fewer crowded hours, same cars:", out["fewer_crowded_hours_with_the_same_cars"])
print("chosen on 2024:", OURS, PICK_2024)
print("vs weekly rolling rule:", out["headline"]["against_weekly_rolling_rule"])
print("savings:", {k: f"{v:.1%}" for k, v in cands.items()})
print("low:", out["headline"]["low"])
print("high:", out["headline"]["high"])
print("power per car-hour:", round(POWER_PER_CAR_HOUR, 2))
