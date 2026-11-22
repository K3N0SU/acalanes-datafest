"""
Where is the day model wrong, and which of those misses could the event harness fix?

Every station-hour of a test year is put in exactly one bucket, in this order:

  1. system exception     the whole system was more than 10% off the forecast that day
  2. holiday period       federal holiday, day after Thanksgiving, Christmas week
  3. game hours           a Giants, A's or Cal football home game at that station, 4h before to 7h after the start
  4. week after a game    no game today, but the same station had one 7 days ago (last week's crowd is in the inputs)
  5. local surge          the station's day ran 25% and 600 riders over the forecast, nothing above explains it
  6. local drop           the station's day ran 25% and 600 riders under
  7. late night           10pm to midnight
  8. weekend, ordinary
  9. weekday, ordinary

For each bucket: its share of riders, its share of the absolute error, the error inside it, the bias,
and how far it sits above the counting-noise floor (the part that could in principle be removed).

Input:  data/clean/station_hour.csv.gz, games.csv, pred_2023/2024/2025.npy (bart_model.py)
Output: public/data/error_analysis.json

Run:  python scripts/bart_errors.py
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from scipy.stats import poisson

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean"
OUT = ROOT / "public" / "data"
START, END = "2021-01-01", "2025-12-31"
YEARS = (2023, 2024, 2025)
BUCKETS = ["system exception", "holiday period", "game hours", "week after a game", "local surge", "local drop",
           "late night", "weekend, ordinary", "weekday, ordinary"]
SURGE_SHARE, SURGE_RIDERS = 0.25, 600

# ---- data (same layout as bart_core.load, without the model inputs)
sh = pd.read_csv(CLEAN / "station_hour.csv.gz", parse_dates=["date"])
sh = sh[(sh["date"] >= START) & (sh["date"] <= END)]
stations = sorted(sh["station"].unique())
sidx = {s: i for i, s in enumerate(stations)}
days = pd.date_range(START, END, freq="D")
didx = {d: i for i, d in enumerate(days)}
S, D = len(stations), len(days)
Y = np.zeros((2, S, D, 24), dtype=np.float32)
si, di, hi = sh["station"].map(sidx).to_numpy(), sh["date"].map(didx).to_numpy(), sh["hour"].to_numpy()
Y[0, si, di, hi] = sh["entries"].to_numpy()
Y[1, si, di, hi] = sh["exits"].to_numpy()
T = Y[0] + Y[1]                                              # (station, day, hour)

dser = pd.Series(days)
hol = set(USFederalHolidayCalendar().holidays(START, "2027-12-31").normalize())
is_hol = dser.isin(hol).to_numpy()
tg = {d for d in hol if d.month == 11 and d.weekday() == 3}
day_after_tg = dser.isin({d + pd.Timedelta(days=1) for d in tg}).to_numpy()
xmas = (((dser.dt.month == 12) & (dser.dt.day >= 24)) | ((dser.dt.month == 1) & (dser.dt.day == 1))).to_numpy()
special = is_hol | day_after_tg | xmas
year = dser.dt.year.to_numpy()
dow = dser.dt.dayofweek.to_numpy()

games = pd.read_csv(CLEAN / "games.csv", parse_dates=["date"])
games = games[games["station"].isin(sidx) & games["date"].isin(didx)]
game_cell = np.zeros((S, D, 24), bool)                       # hours touched by a game
game_day = np.zeros((S, D), bool)
for g in games.itertuples():
    s, d, h0 = sidx[g.station], didx[g.date], int(g.start_hour)
    game_day[s, d] = True
    game_cell[s, d, max(5, h0 - 4):min(24, h0 + 8)] = True
echo_cell = np.zeros_like(game_cell)                         # same hours, one week later, when there is no game
echo_cell[:, 7:, :] = game_cell[:, :-7, :]
echo_cell &= ~game_day[:, :, None]


def wape(p, a):
    return float(np.abs(p - a).sum() / max(a.sum(), 1e-9))


def noise(lam):
    """absolute error a perfect forecast of the mean would still make, if riders arrive at random"""
    lam = np.maximum(lam, 1e-6)
    return float((2 * lam * poisson.pmf(np.floor(lam), lam)).sum())


def analyse(y):
    te = year == y
    P = np.load(CLEAN / f"pred_{y}.npy")
    p, a = P[0] + P[1], T[:, te, :]
    dd, dw = days[te], dow[te]
    n = p.shape[1]

    sys_ratio = a.sum(axis=(0, 2)) / p.sum(axis=(0, 2)) - 1                   # per day
    pd_, ad_ = p.sum(axis=2), a.sum(axis=2)                                   # station-day totals
    resid_day = ad_ - pd_
    surge = (resid_day > SURGE_SHARE * pd_) & (resid_day > SURGE_RIDERS)
    drop = (resid_day < -SURGE_SHARE * pd_) & (resid_day < -SURGE_RIDERS)

    b = np.full(p.shape, len(BUCKETS) - 1, np.int8)                           # weekday, ordinary
    b[:, dw >= 5, :] = BUCKETS.index("weekend, ordinary")
    b[:, :, 22:] = BUCKETS.index("late night")
    b[np.broadcast_to(drop[:, :, None], p.shape)] = BUCKETS.index("local drop")
    b[np.broadcast_to(surge[:, :, None], p.shape)] = BUCKETS.index("local surge")
    b[echo_cell[:, te, :]] = BUCKETS.index("week after a game")
    b[game_cell[:, te, :]] = BUCKETS.index("game hours")
    b[:, special[te], :] = BUCKETS.index("holiday period")
    b[:, np.abs(sys_ratio) > 0.10, :] = BUCKETS.index("system exception")

    err = np.abs(p - a)
    tot_err, tot_a = float(err.sum()), float(a.sum())
    ordinary = b == len(BUCKETS) - 1
    ord_wape = wape(p[ordinary], a[ordinary])
    rows = []
    for k, name in enumerate(BUCKETS):
        m = b == k
        if not m.any():
            continue
        e, r, fl = float(err[m].sum()), float(a[m].sum()), noise(p[m])
        rows.append({
            "bucket": name, "share_of_riders": round(r / tot_a, 4), "share_of_error": round(e / tot_err, 4),
            "error": round(e / r, 4), "bias": round(float(p[m].sum() / r - 1), 4),
            "noise_floor": round(fl / r, 4), "error_above_noise": round((e - fl) / tot_a, 4),
            # the whole-year error if this bucket were forecast as well as an ordinary weekday
            "year_error_if_as_good_as_ordinary": round((tot_err - max(e - ord_wape * r, 0)) / tot_a, 4),
        })

    # ---- game hours and the week after, per venue (does last week's crowd leak into this week's forecast?)
    venues = {}
    for st in sorted(games["station"].unique()):
        s = sidx[st]
        gm, em = game_cell[s][te], echo_cell[s][te]
        plain = ~gm & ~em & ~special[te][:, None] & (np.abs(sys_ratio) <= 0.10)[:, None]
        hrs = np.zeros(24, bool); hrs[10:24] = True
        plain &= hrs[None, :]
        row = {}
        for label, m in (("game hours", gm), ("week after a game", em), ("other days, 10am on", plain)):
            if m.any() and a[s][m].sum() > 0:
                row[label] = {"hours": int(m.sum()), "error": round(wape(p[s][m], a[s][m]), 4), "bias": round(float(p[s][m].sum() / a[s][m].sum() - 1), 4),
                              "riders_missed_per_day": round(float((a[s][m] - p[s][m]).sum() / max(m.any(axis=1).sum(), 1)), 0)}
        venues[st] = row

    # ---- unexplained local surges: the event harness's to-do list
    free = ~special[te][None, :] & (np.abs(sys_ratio) <= 0.10)[None, :] & ~game_day[:, te] & surge
    ss, ds = np.where(free)
    surges = sorted(({"date": str(dd[d].date()), "weekday": dd[d].day_name()[:3], "station": stations[s],
                      "forecast": int(pd_[s, d]), "actual": int(ad_[s, d]), "extra_riders": int(resid_day[s, d]),
                      "times_forecast": round(float(ad_[s, d] / pd_[s, d]), 2), "peak_hour": int(np.argmax(a[s, d] - p[s, d]))}
                     for s, d in zip(ss, ds)), key=lambda r: -r["extra_riders"])
    by_station = pd.Series([r["station"] for r in surges]).value_counts().head(12).to_dict() if surges else {}
    # how concentrated is a surge? share of the day's extra riders that falls in its 4 busiest extra hours
    conc = [float(np.sort(np.maximum(a[s, d] - p[s, d], 0))[-4:].sum() / max(np.maximum(a[s, d] - p[s, d], 0).sum(), 1)) for s, d in zip(ss, ds)]
    # does the same station surge again the next day (multi-day events) or 7 days later (a weekly pattern the model should learn)?
    nxt = float(np.mean([free[s, d + 1] for s, d in zip(ss, ds) if d + 1 < n])) if len(ss) else 0.0
    wk = float(np.mean([surge[s, d + 7] for s, d in zip(ss, ds) if d + 7 < n])) if len(ss) else 0.0

    return {"year": y, "error_all_hours": round(tot_err / tot_a, 4), "error_ordinary_weekday": round(ord_wape, 4),
            "noise_floor": round(noise(p) / tot_a, 4), "buckets": rows, "venues": venues,
            "local_surges": {"station_days": len(surges), "share_of_station_days": round(len(surges) / (S * n), 4),
                             "extra_riders_total": int(sum(r["extra_riders"] for r in surges)),
                             "share_in_4_busiest_hours": round(float(np.mean(conc)), 3) if conc else None,
                             "surges_again_next_day": round(nxt, 3), "surges_again_a_week_later": round(wk, 3),
                             "by_station": by_station, "largest": surges[:40]}}


# ------------------------------------------------------------------ part 2: patterns a correction could use
# Everything here is measured the same way in each test year, so a pattern can be called stable or not.

r4 = lambda v: round(float(v), 4)
DATA = {}
SYS = np.full(D, np.nan)                                     # system actual / forecast - 1, per day, test years only
for y in YEARS:
    te = year == y
    P, A = np.load(CLEAN / f"pred_{y}.npy"), Y[:, :, te, :]
    sysr = A.sum(axis=(0, 1, 3)) / P.sum(axis=(0, 1, 3)) - 1
    SYS[te] = sysr
    DATA[y] = dict(P=P, A=A, te=te, sysr=sysr, dow=dow[te], days=days[te], plain=~special[te] & (np.abs(sysr) <= 0.10),
                   quiet=~(game_cell[:, te, :] | echo_cell[:, te, :]))


def shift(mask, k):
    """mask moved k days later (k > 0) or earlier (k < 0)"""
    out = np.zeros(D, bool)
    if k > 0:
        out[k:] = mask[:-k]
    else:
        out[:k] = mask[-k:]
    return out


def kinds(y):
    d, m, res = DATA[y], DATA[y]["plain"], {}
    for name, p, a in (("entering", d["P"][0], d["A"][0]), ("leaving", d["P"][1], d["A"][1]), ("both added", d["P"].sum(0), d["A"].sum(0))):
        p, a = p[:, m], a[:, m]
        res[name] = {"error": r4(wape(p, a)), "bias": r4(p.sum() / a.sum() - 1), "noise_floor": r4(noise(p) / a.sum())}
    return res


DAYTYPE = {"weekday": lambda w: w < 5, "Saturday": lambda w: w == 5, "Sunday": lambda w: w == 6}


def ratio_table(y):
    """actual / forecast by direction, station, hour and day type, on plain days without game hours"""
    d = DATA[y]
    R, W = np.ones((3, 2, S, 24), np.float32), np.zeros((3, 2, S, 24), np.float32)
    for t, f in enumerate(DAYTYPE.values()):
        m = d["plain"] & f(d["dow"])
        keep = d["quiet"][None, :, m, :]
        ps, as_ = (d["P"][:, :, m, :] * keep).sum(axis=2), (d["A"][:, :, m, :] * keep).sum(axis=2)
        ok = ps > 200
        R[t][ok] = as_[ok] / ps[ok]
        W[t] = as_ / max(m.sum(), 1)                           # riders per day of that type
    return R, W


def apply_table(y, R, power):
    d, Pc = DATA[y], DATA[y]["P"].copy()
    for t, f in enumerate(DAYTYPE.values()):
        m = f(d["dow"])
        Pc[:, :, m, :] = Pc[:, :, m, :] * (np.clip(R[t], 0.8, 1.25) ** power)[:, :, None, :]
    return Pc


def score(y, Pc):
    d = DATA[y]
    p, a = Pc.sum(0), d["A"].sum(0)
    return {"all days": r4(wape(p, a)), "plain days": r4(wape(p[:, d["plain"]], a[:, d["plain"]]))}


TABLES = {y: ratio_table(y) for y in YEARS}


def table_test():
    res = {}
    for prev, y in ((2023, 2024), (2024, 2025)):
        (R0, W0), (R1, W1) = TABLES[prev], TABLES[y]
        w = W1.ravel()
        x, z = np.log(R0).ravel(), np.log(R1).ravel()
        mx, mz = np.average(x, weights=w), np.average(z, weights=w)
        corr = np.average((x - mx) * (z - mz), weights=w) / np.sqrt(np.average((x - mx) ** 2, weights=w) * np.average((z - mz) ** 2, weights=w))
        res[f"{prev} table applied to {y}"] = {"does last year's bias repeat (correlation)": r4(corr), "before": score(y, DATA[y]["P"]),
                                              "after, full strength": score(y, apply_table(y, R0, 1.0)), "after, half strength": score(y, apply_table(y, R0, 0.5))}
    return res


def lasting_biases(top=20):
    """station-hours the model gets wrong the same way in 2024 and 2025"""
    (R3, _), (R4, _), (R5, W5) = TABLES[2023], TABLES[2024], TABLES[2025]
    rows = []
    for t, tn in enumerate(DAYTYPE):
        for k, kn in enumerate(("entering", "leaving")):
            for s in range(S):
                for h in range(5, 24):
                    a4, a5 = R4[t, k, s, h] - 1, R5[t, k, s, h] - 1
                    if a4 * a5 > 0 and min(abs(a4), abs(a5)) >= 0.06 and W5[t, k, s, h] >= 40:
                        rows.append({"station": stations[s], "direction": kn, "day": tn, "hour": h, "actual_vs_forecast_2023": r4(R3[t, k, s, h] - 1),
                                     "actual_vs_forecast_2024": r4(a4), "actual_vs_forecast_2025": r4(a5), "riders_per_day": int(W5[t, k, s, h]),
                                     "riders_missed_per_day": int(W5[t, k, s, h] * (1 - 1 / (1 + a5)))})
    return sorted(rows, key=lambda r: -abs(r["riders_missed_per_day"]))[:top], len(rows)


def calendar_conditions():
    mon, dom = dser.dt.month.to_numpy(), dser.dt.day.to_numpy()
    conds = {
        "day before a federal holiday": shift(is_hol, -1) & ~special,
        "day after a federal holiday": shift(is_hol, 1) & ~special,
        "federal holiday": is_hol,
        "day after Thanksgiving": day_after_tg,
        "Mon to Wed of Thanksgiving week": shift(day_after_tg, -2) | shift(day_after_tg, -3) | shift(day_after_tg, -4),
        "Dec 18 to 23": (mon == 12) & (dom >= 18) & (dom <= 23),
        "Dec 24 to 31": (mon == 12) & (dom >= 24),
        "Jan 2 to 5": (mon == 1) & (dom >= 2) & (dom <= 5),
        "one week after a holiday-period day": shift(special, 7) & ~special,
        "one week after the system ran 10%+ high": shift(np.nan_to_num(SYS) > 0.10, 7),
        "one week after the system ran 10%+ low": shift(np.nan_to_num(SYS) < -0.10, 7),
    }
    for k, n in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]):
        conds[n] = (dow == k) & ~special
    for k in range(1, 13):
        conds[f"month {k}"] = (mon == k) & ~special
    rows = []
    for name, c in conds.items():
        per, n = {}, {}
        for y in YEARS:
            d = DATA[y]
            m = c[d["te"]]
            if name.startswith(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "month")) and "Thanksgiving" not in name:
                m = m & (np.abs(d["sysr"]) <= 0.10)             # the slow patterns: leave the exception days out
            n[y] = int(m.sum())
            per[y] = r4(d["A"][:, :, m].sum() / d["P"][:, :, m].sum() - 1) if m.any() else None
        v = [x for x in per.values() if x is not None]
        stable = len(v) == 3 and (all(x > 0 for x in v) or all(x < 0 for x in v)) and min(abs(x) for x in v) >= 0.015
        rows.append({"condition": name, "actual_vs_forecast": per, "days": n, "same_direction_every_year": bool(stable),
                     "learned_on_2023_2024": r4(np.mean(v[:2])) if len(v) == 3 else None})
    return rows


def persistence():
    """does a station's miss today say anything about the same station k days later? (the system-wide part removed)"""
    res = {}
    for y in YEARS:
        d = DATA[y]
        p, a = d["P"].sum(0).sum(2), d["A"].sum(0).sum(2)                        # (station, day)
        r = np.log((a + 50) / (p + 50))
        local = r - np.log(a.sum(0) / p.sum(0))[None]
        ok, row = d["plain"], {}
        for k in (1, 2, 3, 7, 14):
            m = ok[k:] & ok[:-k]
            row[f"{k} days later"] = {"station part": r4(np.corrcoef(local[:, k:][:, m].ravel(), local[:, :-k][:, m].ravel())[0, 1]),
                                      "whole miss": r4(np.corrcoef(r[:, k:][:, m].ravel(), r[:, :-k][:, m].ravel())[0, 1])}
        res[str(y)] = row
    return res


def week_old_miss_test():
    """use the miss from 7 days ago (known when the forecast is made) to scale today's station forecast; strength fitted on the year before"""
    res = {}

    def rd(y):
        d = DATA[y]
        p, a = d["P"].sum(0).sum(2), d["A"].sum(0).sum(2)
        return np.clip(np.log((a + 50) / (p + 50)), -0.5, 0.5)

    for prev, y in ((2023, 2024), (2024, 2025)):
        r0 = rd(prev)
        x, z = r0[:, :-7].ravel(), r0[:, 7:].ravel()
        beta = float((x * z).sum() / (x * x).sum())
        r1, Pc = rd(y), DATA[y]["P"].copy()
        Pc[:, :, 7:, :] = Pc[:, :, 7:, :] * np.exp(beta * r1[:, :-7])[None, :, :, None]
        res[f"{y}, strength fitted on {prev}"] = {"strength": r4(beta), "before": score(y, DATA[y]["P"]), "after": score(y, Pc)}
    return res


def layers(p, a):
    with np.errstate(all="ignore"):
        p1 = p * (a.sum(axis=(0, 2)) / p.sum(axis=(0, 2)))[None, :, None]
        p2 = p * np.nan_to_num(a.sum(axis=2) / p.sum(axis=2), nan=1.0, posinf=1.0)[:, :, None]
    return {"as is": r4(wape(p, a)), "system day total known": r4(wape(p1, a)), "station day total known": r4(wape(p2, a)),
            "noise floor": r4(noise(p) / a.sum()), "riders per station-hour": round(float(a.mean()), 1)}


def weak_spots(y):
    d = DATA[y]
    p, a = d["P"].sum(0), d["A"].sum(0)
    res = {n: layers(p[:, d["plain"] & f(d["dow"]), 5:22], a[:, d["plain"] & f(d["dow"]), 5:22]) for n, f in DAYTYPE.items()}
    m = d["plain"]
    late_p, late_a = p[:, m, 22:], a[:, m, 22:]
    busy = ~d["quiet"][:, m, 22:]                                           # game or week-after-game hours
    late = {"error": r4(wape(late_p, late_a)), "noise floor": r4(noise(late_p) / late_a.sum()), "bias": r4(late_p.sum() / late_a.sum() - 1),
            "riders per station-hour": round(float(late_a.mean()), 1),
            "share of late-night error in game hours": r4(np.abs(late_p - late_a)[busy].sum() / np.abs(late_p - late_a).sum())}
    for k, n in enumerate(("entering", "leaving")):
        lp, la = d["P"][k][:, m, 22:], d["A"][k][:, m, 22:]
        late[n] = {"error": r4(wape(lp, la)), "bias": r4(lp.sum() / la.sum() - 1)}
    res["10pm to midnight"] = late
    return res


def exception_days(y, top=15):
    d = DATA[y]
    p, a = d["P"].sum(0), d["A"].sum(0)
    err = np.abs(p - a)
    near_hol = np.zeros(D, bool)
    for k in (-3, -2, -1, 1, 2, 3):
        near_hol |= shift(special, k)
    near = (near_hol | special)[d["te"]]
    groups = {"more riders than forecast, not near a holiday": (d["sysr"] > 0.10) & ~near,
              "fewer riders than forecast, not near a holiday": (d["sysr"] < -0.10) & ~near,
              "within 3 days of a holiday period": (np.abs(d["sysr"]) > 0.10) & near}
    split = {n: {"days": int(m.sum()), "share_of_riders": r4(a[:, m].sum() / a.sum()), "share_of_error": r4(err[:, m].sum() / err.sum())} for n, m in groups.items()}
    order = np.argsort(-np.abs(d["sysr"]))[:top]
    worst = [{"date": str(d["days"][i].date()), "weekday": d["days"][i].day_name()[:3], "actual_vs_forecast": r4(d["sysr"][i]), "near_holiday": bool(near[i])} for i in order]
    pd_, ad_ = p.sum(axis=2), a.sum(axis=2)
    drop = (ad_ - pd_ < -SURGE_SHARE * pd_) & (ad_ - pd_ < -SURGE_RIDERS) & (np.abs(d["sysr"]) <= 0.10)[None, :] & ~special[d["te"]][None, :]
    ss, ds = np.where(drop)
    drops = sorted(({"date": str(d["days"][j].date()), "weekday": d["days"][j].day_name()[:3], "station": stations[s], "forecast": int(pd_[s, j]),
                     "actual": int(ad_[s, j]), "missing_riders": int(pd_[s, j] - ad_[s, j])} for s, j in zip(ss, ds)), key=lambda r: -r["missing_riders"])
    return {"split": split, "largest": worst, "local_drops": {"station_days": len(drops), "largest": drops[:15]}}


lasting, lasting_n = lasting_biases()
out = {"what": "station total (entering + leaving) per hour, every day of the test year, each hour in one bucket",
       "rules": {"system exception": "system total more than 10% off the forecast", "game hours": "4 hours before the start to 7 after",
                 "local surge": f"station-day more than {SURGE_SHARE:.0%} and {SURGE_RIDERS} riders over the forecast",
                 "plain day": "not a holiday period and the system within 10% of the forecast"},
       "years": {str(y): analyse(y) for y in YEARS},
       "entering_vs_leaving": {str(y): kinds(y) for y in YEARS},
       "station_hour_bias_table": {"test": table_test(), "cells_wrong_the_same_way_2024_and_2025": lasting_n, "largest": lasting},
       "calendar_conditions": calendar_conditions(),
       "miss_persistence": persistence(), "week_old_miss_correction": week_old_miss_test(),
       "weak_spots": {str(y): weak_spots(y) for y in YEARS},
       "exception_days": {str(y): exception_days(y) for y in YEARS}}

print("\n== entering vs leaving (plain days)")
for y, v in out["entering_vs_leaving"].items():
    print(" ", y, {k: (x["error"], x["bias"], x["noise_floor"]) for k, x in v.items()})
print("\n== station-hour bias table, last year's applied to this year")
for k, v in out["station_hour_bias_table"]["test"].items():
    print(" ", k, v)
print("  cells wrong the same way in 2024 and 2025:", lasting_n)
for r in lasting[:20]:
    print(f"    {r['station']:<5}{r['direction']:<9}{r['day']:<9}{r['hour']:>3}h  23 {r['actual_vs_forecast_2023']:+.1%}  24 {r['actual_vs_forecast_2024']:+.1%}  25 {r['actual_vs_forecast_2025']:+.1%}  {r['riders_per_day']:>5}/day  missed {r['riders_missed_per_day']:+d}")
print("\n== calendar conditions (system actual vs forecast)")
for r in out["calendar_conditions"]:
    print(f"  {'*' if r['same_direction_every_year'] else ' '} {r['condition']:<42}", {y: (v, r['days'][y]) for y, v in r["actual_vs_forecast"].items()})
print("\n== does a station's miss repeat?")
for y, v in out["miss_persistence"].items():
    print(" ", y, {k: (x["station part"], x["whole miss"]) for k, x in v.items()})
print("  correction from the week-old miss:", out["week_old_miss_correction"])
print("\n== weak spots")
for y, v in out["weak_spots"].items():
    for k, x in v.items():
        print(" ", y, k, x)
print("\n== exception days")
for y, v in out["exception_days"].items():
    print(" ", y, v["split"])
    print("   ", [(w["date"], w["weekday"], w["actual_vs_forecast"], "H" if w["near_holiday"] else "") for w in v["largest"][:12]])
    print("    local drops:", v["local_drops"]["station_days"], [(w["date"], w["station"], -w["missing_riders"]) for w in v["local_drops"]["largest"][:10]])
(OUT / "error_analysis.json").write_text(json.dumps(out, indent=1), encoding="utf-8")

for y in YEARS:
    r = out["years"][str(y)]
    print(f"\n== {y}  error {r['error_all_hours']:.1%}  ordinary weekday {r['error_ordinary_weekday']:.1%}  noise floor {r['noise_floor']:.1%}")
    print(f"{'bucket':<20}{'riders':>8}{'error':>8}{'wape':>8}{'bias':>8}{'floor':>8}{'>noise':>8}{'if fixed':>10}")
    for b in r["buckets"]:
        print(f"{b['bucket']:<20}{b['share_of_riders']:>8.1%}{b['share_of_error']:>8.1%}{b['error']:>8.1%}{b['bias']:>+8.1%}{b['noise_floor']:>8.1%}"
              f"{b['error_above_noise']:>8.2%}{b['year_error_if_as_good_as_ordinary']:>10.2%}")
    for st, v in r["venues"].items():
        print(" ", st, {k: (x["error"], x["bias"], x["riders_missed_per_day"]) for k, x in v.items()})
    ls = r["local_surges"]
    print(f"  local surges: {ls['station_days']} station-days, {ls['extra_riders_total']:,} extra riders, "
          f"{ls['share_in_4_busiest_hours']} in 4 hours, next day {ls['surges_again_next_day']}, week later {ls['surges_again_a_week_later']}")
    print("  by station:", ls["by_station"])
    if y == 2025:
        for s in ls["largest"][:30]:
            print(f"    {s['date']} {s['weekday']} {s['station']:<5} forecast {s['forecast']:>6} actual {s['actual']:>6}  +{s['extra_riders']:>5}  x{s['times_forecast']}  peak {s['peak_hour']}h")
