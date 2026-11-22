"""
Back-test of the search agent on real surprises.

The error analysis (scripts/bart_errors.py) lists the station-days in 2025 where far more people
showed up than forecast, with no known cause. The agent is given only the date, the station and
the hour the crowd peaked, and has to find what happened, with a source we can open.

It is scored on three things:
  found      it named a cause and its source is real (the page opens)
  time fits  the event it found started or ended within 4 hours of the hour the gates peaked
  venue fits the venue it named is one we map to that station (when we have that venue)

Input:  public/data/error_analysis.json
Output: public/data/surge_backtest.json

Run:  python scripts/surge_backtest.py [how many, default 24]
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bart_forecast import NAMES
from event_agent import VENUES, ask, load_env, match_venue, parse_json, parse_time, pick_model, source_ok

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public" / "data"


def investigate(key, model, s):
    trace = []
    station = NAMES.get(s["station"], s["station"])
    prompt = f"""Use Google Search. On {s['weekday']} {s['date']}, the BART station "{station}" in the San Francisco Bay Area had about
{s['extra_riders']:,} more riders than a normal {s['weekday']} ({s['times_forecast']}x the forecast), and the busiest hour at the gates was {s['peak_hour']}:00.
Find the event or cause near that station on that date. Check venue calendars, setlists, sports schedules and local news for that exact date.
Only report something you found on a page. If you cannot find it, say unknown. Do not guess.
Return ONLY JSON: {{"cause": "the event, one short sentence" or null, "kind": "concert" | "sports" | "festival or parade" | "protest" | "convention" | "transit disruption elsewhere" | "other" | "unknown",
"venue": str or null, "start_time": "HH:MM" or null, "end_time": "HH:MM" or null, "attendance": integer or null, "source_url": str or null,
"quote": "a short phrase from that page" or null}}"""
    text, sources = ask(key, model, prompt, trace, "surge")
    r = parse_json(text) or {}
    if isinstance(r, list):
        r = r[0] if r else {}
    if not isinstance(r, dict):
        r = {}
    found = bool(r.get("cause")) and r.get("kind") != "unknown" and source_ok(r.get("source_url"), sources, [str(r.get("quote") or "")[:40], str(r.get("venue") or "")[:24]])
    times = [t for t in (parse_time(r.get("start_time") or ""), parse_time(r.get("end_time") or "")) if t is not None]
    time_fits = found and bool(times) and any(abs(t - s["peak_hour"]) <= 4 or abs(t + 24 - s["peak_hour"]) <= 4 for t in times)
    v = match_venue(r.get("venue"), VENUES) if r.get("venue") else None
    return {**s, "station_name": station, "found": found, "cause": r.get("cause") if found else None, "kind": r.get("kind") if found else None,
            "venue": r.get("venue") if found else None, "start_time": r.get("start_time"), "end_time": r.get("end_time"),
            "attendance": r.get("attendance") if found else None, "source_url": r.get("source_url") if found else None,
            "time_fits": bool(time_fits), "venue_known": bool(v), "venue_fits": bool(v and v["station"] == s["station"]),
            "reasoning": (trace[0].get("reasoning") or "")[:600] if trace else "",
            "note": None if found else ("its source could not be opened" if r.get("source_url") else "search found no cause")}


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    surges = json.loads((OUT / "error_analysis.json").read_text(encoding="utf-8"))["years"]["2025"]["local_surges"]["largest"][:n]
    key = load_env()
    model = pick_model(key)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda s: investigate(key, model, s), surges))
    found = [r for r in rows if r["found"]]
    summary = {"surges_tested": len(rows), "cause_found_with_real_source": len(found), "of_those_time_fits": sum(r["time_fits"] for r in found),
               "of_those_at_a_venue_we_map": sum(r["venue_known"] for r in found), "venue_mapped_to_the_right_station": sum(r["venue_fits"] for r in found),
               "extra_riders_in_test": sum(r["extra_riders"] for r in rows), "extra_riders_explained": sum(r["extra_riders"] for r in found if r["time_fits"]),
               "by_kind": {k: sum(1 for r in found if r["kind"] == k) for k in sorted({r["kind"] for r in found})}, "model": model}
    (OUT / "surge_backtest.json").write_text(json.dumps({"summary": summary, "surges": rows}, indent=1), encoding="utf-8")
    for r in rows:
        print(f"{r['date']} {r['station']} +{r['extra_riders']:>5} pk{r['peak_hour']:>2} {'FOUND' if r['found'] else '  -- '} {'t' if r['time_fits'] else ' '}{'v' if r['venue_fits'] else ' '} "
              f"{(r['cause'] or r['note'] or '')[:95]}")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
