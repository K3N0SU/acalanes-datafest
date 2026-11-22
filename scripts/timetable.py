"""BART scheduled service (GTFS) compared with 2025 riders, hour by hour.

Reads data/raw/gtfs/google_transit.zip (BART's public GTFS feed) and
data/clean/station_hour.csv.gz, writes public/data/timetable.json.
"""
import json
import zipfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
GTFS = ROOT / "data/raw/gtfs/google_transit.zip"
RIDERS = ROOT / "data/clean/station_hour.csv.gz"
OUT = ROOT / "public/data/timetable.json"
NTD_CAR_HOURS_2024 = 2_333_890  # FTA National Transit Database, BART heavy rail, vehicle revenue hours
HOURS = list(range(5, 25))
DOW = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def read(z, name):
    return pd.read_csv(z.open(name), dtype=str)


def to_hours(t):
    h, m, s = (int(x) for x in t.split(":"))
    return h + m / 60 + s / 3600


def services_on(cal, cdates, d):
    ds = d.strftime("%Y%m%d")
    act = cal[(cal[DOW[d.weekday()]] == "1") & (cal.start_date <= ds) & (cal.end_date >= ds)]
    ids = set(act.service_id)
    ex = cdates[cdates.date == ds]
    ids |= set(ex[ex.exception_type == "1"].service_id)
    ids -= set(ex[ex.exception_type == "2"].service_id)
    return ids


def typical_date(cal, cdates, weekday, start):
    """First date from `start` with this weekday that has no calendar exceptions."""
    d = start + timedelta(days=(weekday - start.weekday()) % 7)
    exc = set(cdates.date)
    while d.strftime("%Y%m%d") in exc:
        d += timedelta(days=7)
    return d


def main():
    z = zipfile.ZipFile(GTFS)
    cal, cdates = read(z, "calendar.txt"), read(z, "calendar_dates.txt")
    trips, routes = read(z, "trips.txt"), read(z, "routes.txt")
    feed = read(z, "feed_info.txt").iloc[0].to_dict()
    st = read(z, "stop_times.txt")[["trip_id", "arrival_time", "departure_time"]]
    st["t"] = st.departure_time.fillna(st.arrival_time).map(to_hours)
    span = st.groupby("trip_id").t.agg(["min", "max"]).rename(columns={"min": "start", "max": "end"})
    trips = trips.join(span, on="trip_id")
    trips["hours"] = trips.end - trips.start

    start = date.fromisoformat(f"{cal.start_date.min()[:4]}-{cal.start_date.min()[4:6]}-{cal.start_date.min()[6:]}")
    start = max(start, date(2026, 11, 30))
    picks = {"weekday": typical_date(cal, cdates, 2, start),
             "saturday": typical_date(cal, cdates, 5, start),
             "sunday": typical_date(cal, cdates, 6, start)}

    days = {}
    for kind, d in picks.items():
        ids = services_on(cal, cdates, d)
        t = trips[trips.service_id.isin(ids)]
        by_hour, concurrent = {}, {}
        for h in HOURS:
            ov = (np.minimum(t.end, h + 1) - np.maximum(t.start, h)).clip(lower=0)
            by_hour[h] = int((ov > 0).sum())
            concurrent[h] = round(float(ov.sum()), 1)
        per_route = (t.merge(routes[["route_id", "route_short_name"]], on="route_id")
                       .groupby("route_short_name").size().sort_values(ascending=False))
        days[kind] = {
            "date_used": d.isoformat(),
            "service_ids": sorted(ids),
            "trips": int(len(t)),
            "train_hours": round(float(t.hours.sum()), 1),
            "trips_running_by_hour": by_hour,
            "avg_trains_in_service_by_hour": concurrent,
            "trips_per_route": {k: int(v) for k, v in per_route.items()},
        }

    week = days["weekday"]["train_hours"] * 5 + days["saturday"]["train_hours"] + days["sunday"]["train_hours"]
    annual = week * 52
    cars = NTD_CAR_HOURS_2024 / annual

    # riders, 2025 only
    r = pd.read_csv(RIDERS, usecols=["date", "hour", "entries"])
    r = r[r.date.str.startswith("2025")]
    sysh = r.groupby(["date", "hour"]).entries.sum().reset_index()
    wd = pd.to_datetime(sysh.date).dt.day_of_week
    sysh["kind"] = np.select([wd < 5, wd == 5], ["weekday", "saturday"], "sunday")
    ndays = sysh.groupby("kind").date.nunique()
    tot = sysh.groupby(["kind", "hour"]).entries.sum()

    load = {}
    for kind in days:
        rows = []
        for h in HOURS:
            ent = float(tot.get((kind, h % 24), 0)) / ndays[kind]
            tr = days[kind]["trips_running_by_hour"][h]
            rows.append({"hour": h, "avg_entries": round(ent),
                         "trains_running": tr,
                         "entries_per_train": round(ent / tr, 1) if tr else None})
        win = [x for x in rows if 6 <= x["hour"] <= 22 and x["entries_per_train"]]
        hi = max(win, key=lambda x: x["entries_per_train"])
        lo = min(win, key=lambda x: x["entries_per_train"])
        emptiest = sorted(win, key=lambda x: x["entries_per_train"])[:3]
        load[kind] = {"by_hour": rows,
                      "busiest_hour": hi, "emptiest_hour": lo,
                      "busiest_to_emptiest_ratio": round(hi["entries_per_train"] / lo["entries_per_train"], 2),
                      "three_emptiest_hours": [x["hour"] for x in emptiest]}

    out = {
        "source": {"gtfs": "BART GTFS feed, https://www.bart.gov/dev/schedules/google_transit.zip",
                   "feed_version": feed.get("feed_version"),
                   "riders": "BART hourly origin-destination ridership, 2025, summed to system entries",
                   "ntd": "FTA National Transit Database 2024, BART vehicle revenue hours"},
        "days": days,
        "train_hours": {"week": round(week, 1), "annual_x52": round(annual)},
        "ntd_check": {"car_hours_2024": NTD_CAR_HOURS_2024,
                      "implied_cars_per_train": round(cars, 2),
                      "plausible_range": [6, 10],
                      "plausible": bool(6 <= cars <= 10)},
        "riders_per_train": load,
        "limits": [
            "The feed lists trains, not how many cars each train has.",
            "Scheduled service, not what actually ran (cancellations and delays are not included).",
            "The current schedule is compared with 2025 riders; the timetable changed during and after 2025.",
            "Train-hours are first to last stop of each trip; deadhead and layover time is not counted.",
            "Riders are station entries in the hour they entered; a trip spans more than one train-hour.",
            "Annual figure is a typical week times 52, ignoring holidays and special schedules.",
        ],
    }
    OUT.write_text(json.dumps(out, indent=1))
    print("annual train-hours", round(annual), "| cars/train", round(cars, 2))
    for k, v in load.items():
        print(k, days[k]["date_used"], "trips", days[k]["trips"], "tr-h", days[k]["train_hours"],
              "| ratio", v["busiest_to_emptiest_ratio"], "busy", v["busiest_hour"]["hour"],
              "empty", v["three_emptiest_hours"])


if __name__ == "__main__":
    main()
