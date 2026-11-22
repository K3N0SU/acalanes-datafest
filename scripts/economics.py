"""
What the system is worth to BART, in cars, riders and dollars.

Three lines, each from a file another script measured:
  1. sizing trains by forecast     scripts/capacity.py   -> capacity.json   (the main one)
  2. event crowds                  the day files          (riders and fares on event days)
  3. return trips not carried      scripts/od_events.py  -> leakage.json    (small; kept because it corrected us)
Dollars use BART's average fare per trip (FY2025: $243.9M on 52.7M trips = $4.63) and the cost inputs in capacity.json.

Output: public/data/economics.json
Run:    python scripts/economics.py [average_fare]
"""

import glob
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public" / "data"
AVG_FARE = float(sys.argv[1]) if len(sys.argv) > 1 else 4.63


def money(x):
    return int(round(x, -2))


def read(name):
    f = OUT / name
    return json.load(open(f, encoding="utf-8")) if f.exists() else None


# ---------------------------------------------------------------- 1. sizing trains by forecast
cap = read("capacity.json")
sizing = None
if cap:
    h = cap["headline"]
    sizing = {"standard": "capacity covers riders in 95% of hours, 2025", "less_capacity_than_a_fixed_timetable": {k.split(",")[0]: v for k, v in h["savings_against_planning_rules"].items() if "timetable" in k},
              "less_capacity_than_a_4_week_average": {k.split(",")[0]: v for k, v in h["savings_against_planning_rules"].items() if "4 weeks" in k},
              "car_hours_a_year": [h["low"]["car_hours_a_year"], h["high"]["car_hours_a_year"]],
              "electricity_dollars_a_year": [h["low"]["electricity_dollars_a_year"], h["high"]["electricity_dollars_a_year"]],
              "share_of_operating_budget": [h["low"]["share_of_operating_budget"], h["high"]["share_of_operating_budget"]],
              "fewer_crowded_hours_with_the_same_cars": cap["fewer_crowded_hours_with_the_same_cars"],
              "precedent": "BART said running shorter trains from September 2023 saved about $12M a year", "note": "electricity only, so a floor"}
tt = read("timetable.json")

# ---------------------------------------------------------------- 2. event crowds in the next 30 days, from the day files
events = []
for f in sorted(glob.glob(str(OUT / "days" / "20*.json"))):
    d = json.load(open(f, encoding="utf-8"))
    for ev in d["events"]:
        a = ev.get("applied")
        if not a:
            continue
        # day files written before the midnight fix left the midnight-hour riders out; the trip data shows BART carries them
        events.append({"date": d["date"], "name": ev["name"], "venue": ev["venue"], "station": ev["station"], "attendance": a["attendance"],
                       "bart_arrivals": a["bart_arrivals"], "bart_departures": a["bart_departures"] + a.get("after_last_train", 0)})
ev = pd.DataFrame(events)
trips = int(ev["bart_arrivals"].sum() + ev["bart_departures"].sum())
next_month = {"window": [ev["date"].min(), ev["date"].max()], "events": int(len(ev)), "attendance": int(ev["attendance"].sum()),
              "event_trips_on_bart": trips, "fare_revenue": money(trips * AVG_FARE)}

ea = json.load(open(OUT / "error_analysis.json", encoding="utf-8"))["years"]["2025"]["local_surges"]
sb = json.load(open(OUT / "surge_backtest.json", encoding="utf-8"))["summary"]
surges = {"station_days_with_a_surge_nobody_planned_for": ea["station_days"], "riders": int(ea["extra_riders_total"]),
          "fares": money(ea["extra_riders_total"] * AVG_FARE), "share_arriving_within_4_hours": ea["share_in_4_busiest_hours"],
          "search_agent_found_the_cause": f"{sb['cause_found_with_real_source']} of {sb['surges_tested']} tested"}

# ---------------------------------------------------------------- 3. return trips
lk = read("leakage.json")
returns = None
if lk:
    returns = {"rows_crunched": lk["rows_crunched"], "riders_not_carried_home": lk["total_not_carried_home"], "fares": money(lk["total_not_carried_home"] * AVG_FARE),
               "by_venue": [{"venue": v["venue"], "events": v["events"], "share_not_carried_home": v["share_not_carried_home"],
                             "leave_by_hour": v["extra_departures_by_hour"], "come_from": v["where_the_crowd_comes_from"]} for v in lk["venues"]],
               "what_it_corrected": "we had assumed nobody rides after midnight; the trip data shows about a third of arena concert riders leave in the midnight hour"}

out = {"average_fare": AVG_FARE, "average_fare_source": "BART FY2025: $243.9M fare revenue on 52.7M trips",
       "sizing_trains_by_forecast": sizing,
       "bart_timetable": None if not tt else {k: tt[k] for k in ("source", "train_hours", "ntd_check", "limits") if k in tt},
       "events_next_30_days": next_month, "surges_2025": surges, "return_trips_2025": returns}
(OUT / "economics.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
print("sizing:", json.dumps(sizing)[:600])
print("next 30 days:", next_month)
print("surges:", surges)
if returns:
    print("returns:", returns["riders_not_carried_home"], returns["fares"])
