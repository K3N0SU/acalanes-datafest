"""
Return-trip leakage: riders BART carries TO an event but not home.

BART publishes every origin-to-destination trip by hour (about 9 million rows a year). For each
event night we count, at the venue's station:
  arrivals    trips ending at the station in the hours before the event, above a normal night
  departures  trips starting at the station in the hours after it, above a normal night
"Normal" is the median of the same weekday over the 8 previous weeks, leaving out other event dates.
If 2,400 extra riders arrive and 1,700 extra leave, 700 people who chose BART to get there went
home some other way: a fare BART had already won and then lost.

Also: where the crowd comes from (origin stations) and when it leaves (by hour).

Input:  data/raw/bart_hourly/od-2025.csv.gz, data/clean/games.csv, public/data/surge_backtest.json
Output: public/data/leakage.json

Run:  python scripts/od_events.py [average_fare]
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public" / "data"
FARE = float(sys.argv[1]) if len(sys.argv) > 1 else 4.63
CORRIDOR = {
    **{s: "San Francisco and Peninsula" for s in "EMBR MONT POWL CIVC 16TH 24TH GLEN BALB DALY COLM SSAN SBRN SFIA MLBR".split()},
    **{s: "Oakland core" for s in "12TH 19TH LAKE WOAK MCAR FTVL COLS OAKL".split()},
    **{s: "Berkeley and Richmond" for s in "ROCK ASHB DBRK NBRK PLZA DELN RICH".split()},
    **{s: "Contra Costa (Antioch line)" for s in "ORIN LAFY WCRK PHIL CONC NCON PITT PCTR ANTC".split()},
    **{s: "Tri-Valley (Dublin line)" for s in "CAST WDUB DUBL".split()},
    **{s: "South Alameda and San Jose" for s in "SANL BAYF HAYW SHAY UCTY FRMT WARM MLPT BERY".split()},
}

od = pd.read_csv(ROOT / "data" / "raw" / "bart_hourly" / "od-2025.csv.gz", header=None, names=["date", "hour", "origin", "dest", "trips"],
                 dtype={"hour": "int8", "origin": "category", "dest": "category", "trips": "int32"}, parse_dates=["date"])
# service runs past midnight: count hours 0 to 2 as the end of the previous evening
late = od["hour"] <= 2
od["night"] = od["date"].where(~late, od["date"] - pd.Timedelta(days=1))
od["h"] = od["hour"].where(~late, od["hour"] + 24)
print(f"{len(od):,} origin-destination rows, {od['trips'].sum():,} trips in 2025", flush=True)


def analyse(label, station, events, before=4, after_from=2, after_to=6):
    """events: DataFrame with date and start_hour. windows are in hours relative to the start hour"""
    arr = od[od["dest"] == station].groupby(["night", "h"], observed=True)["trips"].sum().unstack(fill_value=0)
    dep = od[od["origin"] == station].groupby(["night", "h"], observed=True)["trips"].sum().unstack(fill_value=0)
    origins = od[od["dest"] == station].groupby(["night", "h", "origin"], observed=True)["trips"].sum()
    dests = od[od["origin"] == station].groupby(["night", "h", "dest"], observed=True)["trips"].sum()
    event_dates = set(events["date"])
    rows, org_extra, dst_extra, dep_hours = [], {}, {}, {}
    for _, e in events.iterrows():
        d, h0 = e["date"], int(e["start_hour"])
        prior = [d - pd.Timedelta(weeks=k) for k in range(1, 13)]
        prior = [p for p in prior if p not in event_dates and p in arr.index][:8]
        if d not in arr.index or len(prior) < 4:
            continue
        ah = [h for h in range(h0 - before, h0 + 1) if h in arr.columns]
        dh = [h for h in range(h0 + after_from, h0 + after_to + 1) if h in dep.columns and h <= 26]
        a_extra = arr.loc[d, ah].sum() - np.median([arr.loc[p, ah].sum() for p in prior])
        d_extra = dep.loc[d, dh].sum() - np.median([dep.loc[p, dh].sum() for p in prior])
        rows.append({"date": str(d.date()), "start_hour": h0, "extra_arrivals": int(a_extra), "extra_departures": int(d_extra), "not_carried_home": int(a_extra - d_extra)})
        for h in dh:
            dep_hours[h] = dep_hours.get(h, 0) + dep.loc[d, h] - np.median([dep.loc[p, h] for p in prior])
        for (store, series, hours) in ((org_extra, origins, ah), (dst_extra, dests, dh)):
            for h in hours:
                try:
                    today = series.loc[(d, h)]
                except KeyError:
                    continue
                base = pd.concat([series.loc[(p, h)] for p in prior if (p, h) in series.index.droplevel(2)], axis=1).fillna(0).median(axis=1) if prior else 0
                diff = today.sub(base, fill_value=0)
                for st, v in diff.items():
                    store[st] = store.get(st, 0) + v
    if not rows:
        return None
    r = pd.DataFrame(rows)
    a, dd = r["extra_arrivals"].sum(), r["extra_departures"].sum()

    def by_corridor(store):
        s = pd.Series(store)
        s = s[s > 0]
        g = s.groupby(s.index.map(lambda x: CORRIDOR.get(x, "other"))).sum().sort_values(ascending=False)
        return {k: round(float(v / g.sum()), 3) for k, v in g.items()}

    top = pd.Series(org_extra).sort_values(ascending=False).head(6)
    return {"venue": label, "station": station, "events": int(len(r)), "avg_extra_arrivals": int(a / len(r)), "avg_extra_departures": int(dd / len(r)),
            "avg_not_carried_home": int((a - dd) / len(r)), "share_not_carried_home": round(float((a - dd) / a), 3) if a > 0 else None,
            "total_not_carried_home": int(a - dd), "fare_value": int(round((a - dd) * FARE, -2)),
            "extra_departures_by_hour": {(f"{h % 24}:00"): int(v / len(r)) for h, v in sorted(dep_hours.items())},
            "where_the_crowd_comes_from": by_corridor(org_extra), "where_it_goes_home_to": by_corridor(dst_extra),
            "top_origin_stations": {k: int(v / len(r)) for k, v in top.items()},
            "nights": r.sort_values("not_carried_home", ascending=False).head(5).to_dict("records")}


games = pd.read_csv(ROOT / "data" / "clean" / "games.csv", parse_dates=["date"])
games = games[games["date"].dt.year == 2025]
sb = json.load(open(OUT / "surge_backtest.json", encoding="utf-8"))["surges"]
concerts = pd.DataFrame([{"date": pd.Timestamp(s["date"]), "start_hour": 20, "name": s["cause"]} for s in sb
                         if s["found"] and s["station"] == "COLS" and s.get("kind") == "concert"])
results = []
for label, station, ev, kw in (
    ("Arena concerts at Oakland Arena (found by the search agent)", "COLS", concerts, dict(before=4, after_from=2, after_to=6)),
    ("Giants night games at Oracle Park", "EMBR", games[(games["team"] == "Giants") & (games["start_hour"] >= 17)], dict(before=3, after_from=2, after_to=6)),
    ("Giants day games at Oracle Park", "EMBR", games[(games["team"] == "Giants") & (games["start_hour"] < 17)], dict(before=3, after_from=2, after_to=5)),
    ("Cal football at Memorial Stadium", "DBRK", games[games["sport"] == "football"], dict(before=4, after_from=3, after_to=7)),
):
    res = analyse(label, station, ev, **kw) if len(ev) else None
    if res:
        results.append(res)
        print(f"{label}: {res['events']} events | arrive +{res['avg_extra_arrivals']} | leave +{res['avg_extra_departures']} | not carried home {res['avg_not_carried_home']} "
              f"({res['share_not_carried_home']:.0%}) | total {res['total_not_carried_home']:,} = ${res['fare_value']:,}", flush=True)
        print("   leave by hour:", res["extra_departures_by_hour"])
        print("   come from:", res["where_the_crowd_comes_from"])

tot = sum(r["total_not_carried_home"] for r in results if r["total_not_carried_home"] > 0)
out = {"what": "extra riders arriving at an event by BART who did not leave by BART, 2025, from the hourly origin-destination file",
       "rows_crunched": int(len(od)), "average_fare": FARE, "venues": results,
       "total_not_carried_home": int(tot), "fare_value": int(round(tot * FARE, -2)),
       "limits": ["only events we have dates for: 81 Giants games, 6 Cal football games and the arena concerts the search agent identified",
                  "concert start time assumed 8 PM", "some riders leave from a different station, which this counts as not carried home"]}
(OUT / "leakage.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
print("TOTAL not carried home:", f"{tot:,}", "riders = $", f"{tot * FARE:,.0f}")
