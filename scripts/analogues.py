"""
A library of measured exceptions: the days in 2023 to 2025 when the whole system ran far from the
forecast, each explained by a web search that has to produce a real source.

The size of each effect is measured (real riders against the day model). The search only supplies
the label, and a label is kept only when its source is real: a site the search retrieved, or a
page we can open ourselves.

Two uses:
  - the harness bounds what it may do for a new disruption by what past ones of that type did;
  - data/calendars/exceptions.csv feeds the accessories test: learn the effect of each type on
    2023 and 2024, apply it to the 2025 days of the same type, measure.

Input:  data/clean/pred_2023..2025.npy
Output: public/data/analogues.json, data/calendars/exceptions.csv

Run:  python scripts/analogues.py
"""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from event_agent import ask, load_env, parse_json, pick_model, source_ok

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public" / "data"
PER_YEAR = 14
TYPES = ["parade or festival", "protest or march", "sports event", "concert", "convention", "service outage", "strike",
         "severe weather", "wildfire smoke", "earthquake", "holiday period", "other", "unknown"]


def anomalies():
    """the days each year when the system total was furthest from the forecast (federal holidays left out)"""
    from bart_core import CLEAN, load
    c = load()
    rows = []
    for y in (2023, 2024, 2025):
        te = c.year == y
        P, A = np.load(CLEAN / f"pred_{y}.npy"), c.Y[:, :, te, :]
        ratio = A.sum(axis=(0, 1, 3)) / P.sum(axis=(0, 1, 3)) - 1
        days = c.days[te]
        ok = ~c.is_hol[te]
        order = [i for i in np.argsort(-np.abs(ratio)) if ok[i]][:PER_YEAR]
        rows += [{"date": str(days[i].date()), "weekday": days[i].day_name(), "actual_vs_forecast": round(float(ratio[i]), 3)} for i in order]
    return rows


def explain(key, model, day):
    trace = []
    direction = "far more" if day["actual_vs_forecast"] > 0 else "far fewer"
    prompt = f"""Use Google Search. On {day['weekday']} {day['date']}, BART (San Francisco Bay Area rail) carried {direction} riders than normal
for that kind of day ({day['actual_vs_forecast']:+.0%} against a forecast). Find what happened in the Bay Area or on BART that day that explains it.
Only report a cause you found on a page. If you cannot find one, say unknown. Do not guess.
Return ONLY JSON: {{"type": one of {json.dumps(TYPES)}, "cause": "one short sentence", "source_url": "the page that says so" or null,
"quote": "a short phrase from that page that supports it" or null}}"""
    text, sources = ask(key, model, prompt, trace, "analogue")
    r = parse_json(text) or {}
    if isinstance(r, list):
        r = r[0] if r else {}
    if not isinstance(r, dict):
        r = {}
    verified = source_ok(r.get("source_url"), sources, [str(r.get("quote") or "")[:40]])
    if not verified or r.get("type") in (None, "unknown"):
        return {**day, "type": "unknown", "cause": None, "source_url": None, "verified": False,
                "note": "its source could not be opened" if (r.get("source_url") and not verified) else "search found no cause"}
    return {**day, "type": r["type"], "cause": r.get("cause"), "source_url": r.get("source_url"), "quote": r.get("quote"), "verified": True}


def main():
    days = anomalies()
    key = load_env()
    model = pick_model(key)
    with ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(lambda d: explain(key, model, d), days))
    rows.sort(key=lambda r: r["date"])
    ranges = {}
    for r in rows:
        if r["verified"]:
            ranges.setdefault(r["type"], []).append(r["actual_vs_forecast"])
    summary = {t: {"days": len(v), "min": round(min(v), 3), "max": round(max(v), 3)} for t, v in ranges.items()}
    (OUT / "analogues.json").write_text(json.dumps({"model": model, "days_examined": len(rows), "days_labelled": sum(r["verified"] for r in rows),
                                                    "by_type": summary, "days": rows}, indent=1), encoding="utf-8")
    cal = ROOT / "data" / "calendars"
    cal.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([[r["date"], r["type"] + (" (more riders)" if r["actual_vs_forecast"] > 0 else " (fewer riders)"), "", 0, 24, r["source_url"]]
                  for r in rows if r["verified"]], columns=["date", "category", "stations", "hour_from", "hour_to", "source"]).to_csv(cal / "exceptions.csv", index=False)
    for r in rows:
        print(f"{r['date']} {r['actual_vs_forecast']:+.0%}  {r['type']:<20} {'OK ' if r['verified'] else '-- '} {(r.get('cause') or r.get('note') or '')[:100]}")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
