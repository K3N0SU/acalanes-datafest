"""Build public/geo/bart.json from BART's GTFS feed: stations and real track geometry.

  curl -L -o data/raw/gtfs/bart_gtfs.zip https://www.bart.gov/dev/schedules/google_transit.zip
  (cd data/raw/gtfs && unzip -o bart_gtfs.zip)
  python3 dev/build_geo.py
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
G = ROOT / "data" / "raw" / "gtfs"
OUT = ROOT / "public" / "geo" / "bart.json"
LINES = {"Yellow": "Yellow", "Orange": "Orange", "Green": "Green", "Red": "Red", "Blue": "Blue", "Grey": "Grey"}


def rows(name):
    with open(G / name, newline="", encoding="utf-8-sig") as f:
        yield from csv.DictReader(f)


def simplify(pts, tol):
    """Douglas-Peucker on (lon, lat) pairs, tolerance in degrees."""
    if len(pts) < 3:
        return pts
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = (dx * dx + dy * dy) ** 0.5 or 1e-12
    best, idx = 0.0, 0
    for i in range(1, len(pts) - 1):
        x, y = pts[i]
        d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / norm
        if d > best:
            best, idx = d, i
    if best <= tol:
        return [pts[0], pts[-1]]
    return simplify(pts[: idx + 1], tol)[:-1] + simplify(pts[idx:], tol)


def main():
    stations, platform_parent = {}, {}
    for r in rows("stops.txt"):
        if r["location_type"] == "1":
            stations[r["stop_id"]] = {"name": r["stop_name"], "lat": round(float(r["stop_lat"]), 5),
                                      "lon": round(float(r["stop_lon"]), 5), "lines": []}
        elif r["parent_station"]:
            platform_parent[r["stop_id"]] = r["parent_station"]

    route_line = {}
    for r in rows("routes.txt"):
        key = r["route_short_name"].split("-")[0]
        if key in LINES:
            route_line[r["route_id"]] = (key, "#" + r["route_color"])

    shape_pts = defaultdict(list)
    for r in rows("shapes.txt"):
        shape_pts[r["shape_id"]].append((int(r["shape_pt_sequence"]), float(r["shape_pt_lon"]), float(r["shape_pt_lat"])))

    # longest shape per line = the full run of that line
    trip_info, best = {}, {}
    for r in rows("trips.txt"):
        if r["route_id"] not in route_line:
            continue
        line, color = route_line[r["route_id"]]
        trip_info[r["trip_id"]] = line
        n = len(shape_pts.get(r["shape_id"], []))
        if n and n > best.get(line, ("", 0, ""))[1]:
            best[line] = (r["shape_id"], n, color, r["trip_id"])

    # stations served by each line, from the representative trip
    rep_trips = {v[3]: k for k, v in best.items()}
    served = defaultdict(set)
    for r in rows("stop_times.txt"):
        line = rep_trips.get(r["trip_id"])
        if line:
            served[line].add(platform_parent.get(r["stop_id"], r["stop_id"]))

    lines = []
    for line, (shape_id, _, color, _) in sorted(best.items()):
        pts = [(lon, lat) for _, lon, lat in sorted(shape_pts[shape_id])]
        pts = simplify(pts, 0.00015)
        lines.append({"id": line.lower(), "name": line, "color": color,
                      "coords": [[round(x, 5), round(y, 5)] for x, y in pts]})
        for code in served[line]:
            if code in stations:
                stations[code]["lines"].append(line.lower())

    cities = [  # label anchors for orientation, placed off the tracks on purpose
        {"name": "San Francisco", "lon": -122.505, "lat": 37.792},
        {"name": "Oakland", "lon": -122.175, "lat": 37.838},
        {"name": "San José", "lon": -121.835, "lat": 37.352},
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"source": "BART GTFS (bart.gov/dev/schedules)", "stations": stations,
                               "lines": lines, "cities": cities}, separators=(",", ":")))
    print(f"{len(stations)} stations, {len(lines)} lines, "
          f"{sum(len(l['coords']) for l in lines)} points -> {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------- trains
# Every scheduled BART trip for each day of the forecast week, so the map can place trains where the
# timetable says they are. Trips share a "pattern" (same track shape and stops); each pattern stores its
# geometry, where each stop sits along it (meters), and the median running time to each stop.
import math
import statistics
from datetime import date, timedelta

TRAINS_OUT = ROOT / "public" / "geo" / "trains.json"


def _secs(t):
    h, m, s = (int(x) for x in t.split(":"))
    return h * 3600 + m * 60 + s


def _project(pt, coords):
    """Distance in meters along the polyline to the point nearest pt."""
    lat0 = math.radians(coords[0][1])
    kx, ky = 111320 * math.cos(lat0), 110540
    P = (pt[0] * kx, pt[1] * ky)
    best, along, acc = 1e18, 0.0, 0.0
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        A, B = (x1 * kx, y1 * ky), (x2 * kx, y2 * ky)
        dx, dy = B[0] - A[0], B[1] - A[1]
        L2 = dx * dx + dy * dy or 1e-9
        t = max(0.0, min(1.0, ((P[0] - A[0]) * dx + (P[1] - A[1]) * dy) / L2))
        qx, qy = A[0] + t * dx, A[1] + t * dy
        d = (P[0] - qx) ** 2 + (P[1] - qy) ** 2
        if d < best:
            best, along = d, acc + t * math.sqrt(L2)
        acc += math.sqrt(L2)
    return along


def active_services(day: date):
    dow = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][day.weekday()]
    ymd = day.strftime("%Y%m%d")
    on = {r["service_id"] for r in rows("calendar.txt")
          if r[dow] == "1" and r["start_date"] <= ymd <= r["end_date"]}
    for r in rows("calendar_dates.txt"):
        if r["date"] == ymd:
            (on.add if r["exception_type"] == "1" else on.discard)(r["service_id"])
    return on


def build_trains(week_start: date):
    stations = {r["stop_id"]: (float(r["stop_lon"]), float(r["stop_lat"])) for r in rows("stops.txt") if r["location_type"] == "1"}
    parent = {r["stop_id"]: r["parent_station"] for r in rows("stops.txt") if r["parent_station"]}
    route_line = {}
    for r in rows("routes.txt"):
        key = r["route_short_name"].split("-")[0]
        if key in LINES:
            route_line[r["route_id"]] = key.lower()
    trips = {r["trip_id"]: r for r in rows("trips.txt") if r["route_id"] in route_line}
    times = defaultdict(list)
    for r in rows("stop_times.txt"):
        if r["trip_id"] in trips:
            times[r["trip_id"]].append((int(r["stop_sequence"]), parent.get(r["stop_id"], r["stop_id"]), _secs(r["departure_time"] or r["arrival_time"])))

    shape_pts = defaultdict(list)
    for r in rows("shapes.txt"):
        shape_pts[r["shape_id"]].append((int(r["shape_pt_sequence"]), float(r["shape_pt_lon"]), float(r["shape_pt_lat"])))

    patterns, pat_ids, trip_pat = {}, {}, {}
    pat_offsets = defaultdict(list)
    for tid, st in times.items():
        st.sort()
        stops = tuple(s for _, s, _ in st)
        key = (trips[tid]["shape_id"], stops)
        if key not in pat_ids:
            pat_ids[key] = f"p{len(pat_ids)}"
        pid = pat_ids[key]
        t0 = st[0][2]
        trip_pat[tid] = (pid, t0)
        pat_offsets[pid].append([t - t0 for _, _, t in st])
    for (shape_id, stops), pid in pat_ids.items():
        raw = [(lon, lat) for _, lon, lat in sorted(shape_pts.get(shape_id, []))] or [stations[s] for s in stops]
        coords = simplify(raw, 0.0001) if len(raw) > 2 else raw
        coords = [[round(x, 5), round(y, 5)] for x, y in coords]
        dists = [round(_project(stations[s], coords)) for s in stops]
        offs = [int(statistics.median(col)) for col in zip(*pat_offsets[pid])]
        line = route_line[trips[next(t for t, (p, _) in trip_pat.items() if p == pid)]["route_id"]]
        patterns[pid] = {"line": line, "coords": coords, "stops": list(stops), "dist": dists, "offsets": offs}

    days = {}
    for i in range(7):
        d = week_start + timedelta(days=i)
        today, yesterday = active_services(d), active_services(d - timedelta(days=1))
        runs = []
        for tid, (pid, t0) in trip_pat.items():
            sid = trips[tid]["service_id"]
            if sid in today:
                runs.append([pid, t0])
            if sid in yesterday and t0 + patterns[pid]["offsets"][-1] > 86400:  # after-midnight trips
                runs.append([pid, t0 - 86400])
        runs.sort(key=lambda r: r[1])
        days[d.isoformat()] = runs
    TRAINS_OUT.write_text(json.dumps({"source": "BART GTFS schedule", "patterns": patterns, "days": days}, separators=(",", ":")))
    counts = {k: len(v) for k, v in days.items()}
    print(f"{len(patterns)} patterns, trips per day {counts} -> {TRAINS_OUT} ({TRAINS_OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    fc = json.loads((ROOT / "public" / "data" / "forecast.json").read_text())
    build_trains(date.fromisoformat(fc["week"][0]))
