"""
Accessories: standalone corrections that sit on top of the main model.

The main model is not retrained and knows nothing about these. Each accessory is a calendar of
conditions (data/calendars/NAME.csv: a convention week, a smoky day, Pride Sunday, after dark...).
For each condition it learns one thing from the main model's past misses: when this condition
held, how far off was the forecast, by hour and by station? That ratio is then applied to the
forecast whenever the condition holds again.

Every condition is measured the same way, so it can be switched off if it does not help:
  choose   learn on 2023, apply to 2024. Kept only if it lowers the error on the hours it touches.
  report   learn on 2023 + 2024, apply to 2025. This is the number we quote.
The main model's forecasts for all three years are out-of-sample (walk-forward), so nothing here
is fitted to the answer it is tested on.

Input:  data/clean/pred_2023..2025.npy, data/calendars/*.csv
Output: public/data/accessories.json  (results, plus the final ratios learned on 2023 to 2025 for live use)

Run:  python scripts/accessories.py
"""

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from bart_core import CLEAN, ROOT, load, wape

OUT = ROOT / "public" / "data"
CAL = ROOT / "data" / "calendars"
YEARS = [2023, 2024, 2025]
SHRINK_DAYS = 1.0          # a station needs evidence on several days before its own ratio is trusted
LIMITS = (0.3, 4.0)        # no accessory may cut a forecast below 30% or raise it above 4x
KEEP_IF_BETTER_BY = 0.01   # relative improvement on 2024 needed to switch a condition on


ALIASES = [("carnaval", "Carnaval San Francisco"), ("chinese new year", "Chinese New Year Parade"), ("lunar new year", "Chinese New Year Parade"),
           ("fleet week", "Fleet Week air show"), ("hardly strictly", "Hardly Strictly Bluegrass"), ("outside lands", "Outside Lands"),
           ("oakland pride", "Oakland Pride"), ("dia de los muertos", "Dia de los Muertos, Fruitvale"), ("july 4", "July 4th fireworks"),
           ("fourth of july", "July 4th fireworks"), ("marathon", "San Francisco Marathon"), ("parade", None), ("k-12", None), ("cal not", None)]
SKIP_TYPES = ("holiday period",)   # holidays have their own model; do not correct them twice


def same_condition(accessory, cat):
    """searches return 'Dreamforce 2024' and 'Dreamforce 2025' as different names. A condition has to be the
    same thing every year to learn from one year and apply to the next, so years are stripped and known names unified.
    All Moscone conventions are pooled: one convention a year is too little to learn from on its own."""
    if accessory == "conventions":
        return "large convention at Moscone Center"
    c = re.sub(r"\(?\b20\d\d\b\)?|'\d\d\b", "", cat)
    c = re.sub(r"\s+", " ", c).strip(" -:,.")
    low = c.lower()
    for key, label in ALIASES:
        if key in low and label:
            return label
    return c


def load_calendars():
    cals = {}
    for path in sorted(CAL.glob("*.csv")):
        df = pd.read_csv(path, dtype=str).fillna("")
        if len(df):
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])
            df["category"] = [same_condition(path.stem, x) for x in df["category"]]
            df = df[~df["category"].str.lower().str.startswith(SKIP_TYPES)]
            cals[path.stem] = df
    return cals


def mask_for(c, rows):
    """boolean (station, day, hour) for one condition"""
    m = np.zeros((c.S, c.D, 24), bool)
    for (stations, h0, h1), g in rows.groupby(["stations", "hour_from", "hour_to"]):
        di = [c.didx[d] for d in g["date"] if d in c.didx]
        if not di:
            continue
        si = [c.sidx[s] for s in stations.split() if s in c.sidx] if stations.strip() else list(range(c.S))
        h0, h1 = int(float(h0 or 0)), int(float(h1 or 24))
        m[np.ix_(si, di, range(h0, h1))] = True
    return m


def learn(A, P, m):
    """ratio by direction, station and hour = (hourly pattern of the miss across all stations) x (how strongly this station shows it)"""
    M = m[None]
    a, p = A * M, P * M
    with np.errstate(all="ignore"):
        hour = np.nan_to_num(a.sum(axis=(1, 2)) / p.sum(axis=(1, 2)), nan=1.0, posinf=1.0)            # (2, 24)
        overall = np.nan_to_num(a.sum(axis=(1, 2, 3)) / p.sum(axis=(1, 2, 3)), nan=1.0, posinf=1.0)   # (2,)
        st_raw = np.nan_to_num(a.sum(axis=(2, 3)) / p.sum(axis=(2, 3)), nan=1.0, posinf=1.0)          # (2, S)
    n_days = m.any(axis=2).sum(axis=1)                                                                # (S,)
    rel = st_raw / np.maximum(overall[:, None], 1e-6)
    station = (n_days[None] * rel + SHRINK_DAYS) / (n_days[None] + SHRINK_DAYS)                       # shrink toward 1
    return np.clip(hour[:, None, :] * station[:, :, None], *LIMITS), int(n_days.max())


def main():
    c = load()
    A = c.Y
    P = np.full_like(A, np.nan)
    for y in YEARS:
        P[:, :, c.year == y, :] = np.load(CLEAN / f"pred_{y}.npy")
    yr = {y: (c.year == y) for y in YEARS}

    def score(m, year, ratio=None):
        """error on the cells this condition touches in one year, before and after"""
        mm = m & yr[year][None, :, None]
        M = np.broadcast_to(mm[None], A.shape)
        if not M.any():
            return None
        a, p = A[M], P[M]
        after = wape(np.broadcast_to(ratio[:, :, None, :], A.shape)[M] * p, a) if ratio is not None else None
        return {"before": wape(p, a), "after": after, "station_hours": int(mm.sum()), "days": int(mm.any(axis=(0, 2)).sum()), "riders": int(a.sum())}

    results, live = [], {}
    final = P.copy()   # 2025 forecast with every switched-on condition applied
    for name, df in load_calendars().items():
        for cat, rows in df.groupby("category"):
            m = mask_for(c, rows)
            train23 = m & yr[2023][None, :, None]
            train2324 = m & (yr[2023] | yr[2024])[None, :, None]
            row = {"accessory": name, "condition": cat, "source": rows["source"].iloc[0], "on": False}
            # choose on 2024
            if train23.any() and (m & yr[2024][None, :, None]).any():
                r23, _ = learn(A, np.nan_to_num(P), train23)
                s24 = score(m, 2024, r23)
                row["check_2024"] = s24
                row["on"] = s24["after"] < s24["before"] * (1 - KEEP_IF_BETTER_BY)
            else:
                row["check_2024"] = None
                row["note"] = "no days in both 2023 and 2024, so it could not be checked; left off"
            # report on 2025
            if train2324.any() and (m & yr[2025][None, :, None]).any():
                r, _ = learn(A, np.nan_to_num(P), train2324)
                row["test_2025"] = score(m, 2025, r)
                if row["on"]:
                    mm = np.broadcast_to((m & yr[2025][None, :, None])[None], A.shape)
                    final[mm] = final[mm] * np.broadcast_to(r[:, :, None, :], A.shape)[mm]
            else:
                row["test_2025"] = None
            # ratios for live use: everything we have, 2023 to 2025
            all3 = m & (yr[2023] | yr[2024] | yr[2025])[None, :, None]
            if row["on"] and all3.any():
                rr, n = learn(A, np.nan_to_num(P), all3)
                live[f"{name}|{cat}"] = {"ratio": rr.round(3).tolist(), "learned_from_days": int(all3.any(axis=(0, 2)).sum())}
            results.append(row)
            t, s = row.get("test_2025"), row.get("check_2024")
            print(f"{'ON ' if row['on'] else 'off'} {name[:16]:<16} {cat[:38]:<38} "
                  f"2024 {'%.3f->%.3f' % (s['before'], s['after']) if s else '   n/a      '}  "
                  f"2025 {'%.3f->%.3f (%d days)' % (t['before'], t['after'], t['days']) if t else 'n/a'}", flush=True)

    te = yr[2025]
    a25, p25, f25 = A[:, :, te, :], P[:, :, te, :], final[:, :, te, :]
    touched = np.abs(f25 - p25) > 1e-9
    ordinary = ~c.special[te]
    overall = {"all_2025_before": wape(p25, a25), "all_2025_after": wape(f25, a25),
               "touched_hours_before": wape(p25[touched], a25[touched]) if touched.any() else None,
               "touched_hours_after": wape(f25[touched], a25[touched]) if touched.any() else None,
               "share_of_station_hours_touched": float(touched.mean()),
               "ordinary_days_before": wape(p25[:, :, ordinary, :], a25[:, :, ordinary, :]),
               "ordinary_days_after": wape(f25[:, :, ordinary, :], a25[:, :, ordinary, :]),
               "conditions_tested": len(results), "conditions_on": sum(r["on"] for r in results)}
    np.save(CLEAN / "pred_2025_with_accessories.npy", f25)
    (OUT / "accessories.json").write_text(json.dumps({"rule": "learn on earlier years, switch on only if 2024 improves, report on 2025",
                                                      "limits": LIMITS, "overall": overall, "conditions": results, "stations": c.stations,
                                                      "live_ratios": live}, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in overall.items()}, indent=1))


def apply_live(date, entries, exits, stations):
    """used by the forecaster: multiply a future day's forecast by every switched-on condition that holds that day.
    entries/exits are (station, 24). Returns the adjusted pair and the list of conditions applied."""
    path = OUT / "accessories.json"
    if not path.exists():
        return entries, exits, []
    acc = json.loads(path.read_text(encoding="utf-8"))
    order = {s: i for i, s in enumerate(acc["stations"])}
    idx = [order[s] for s in stations]
    date = pd.Timestamp(date).normalize()
    used = []
    for name, df in load_calendars().items():
        today = df[df["date"] == date]
        for cat, rows in today.groupby("category"):
            lr = acc["live_ratios"].get(f"{name}|{cat}")
            if not lr:
                continue
            ratio = np.array(lr["ratio"])[:, idx, :]            # (2, S, 24)
            m = np.zeros((len(stations), 24), bool)
            for _, r in rows.iterrows():
                si = [stations.index(s) for s in r["stations"].split() if s in stations] if r["stations"].strip() else list(range(len(stations)))
                m[np.ix_(si, range(int(float(r["hour_from"] or 0)), int(float(r["hour_to"] or 24))))] = True
            entries = np.where(m, entries * ratio[0], entries)
            exits = np.where(m, exits * ratio[1], exits)
            used.append({"accessory": name, "condition": cat, "source": rows["source"].iloc[0], "learned_from_days": lr["learned_from_days"]})
    return entries, exits, used


if __name__ == "__main__":
    main()
