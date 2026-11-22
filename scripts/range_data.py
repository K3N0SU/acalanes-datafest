"""
Room to run, by station and hour, for next week: the data behind the "Plan a time range" tool on the site.

expected  riders forecast for next week (entries plus exits). Taken from the day files
          (public/data/days/DATE.json), which add event crowds, service changes and holidays to the
          forecast; falls back to public/data/forecast.json for a day with no day file
room      expected x the margin the cost-trained model learned for that station, weekday and hour
          (95th-percentile forecast / average forecast, summed over 2025; kept between 1.0 and 3.0)

Output: public/data/range.json
Run:    python scripts/range_data.py
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
HOURS = list(range(5, 24))
c = load()
te = c.year == 2025
dow = pd.Series(pd.to_datetime(c.dser.to_numpy()))[te].dt.dayofweek.to_numpy()
q = np.load(CLEAN / "q95_pred_2025.npy").sum(axis=0)[:, :, 5:24]     # station, day, hour
m = np.load(CLEAN / "pred_2025.npy").sum(axis=0)[:, :, 5:24]
ratio = np.ones((len(c.stations), 7, len(HOURS)))
for w in range(7):
    a, b = q[:, dow == w].sum(axis=1), m[:, dow == w].sum(axis=1)
    ratio[:, w] = np.clip(np.where(b > 0, a / np.maximum(b, 1e-9), 1.0), 1.0, 3.0)

f = json.load(open(OUT / "forecast.json", encoding="utf-8"))
week = f["week"]
DAYS = {}
for date in week:
    fp = OUT / "days" / f"{date}.json"
    if fp.exists():
        DAYS[date] = json.load(open(fp, encoding="utf-8")).get("stations", {})
wd = [pd.Timestamp(d).dayofweek for d in week]
stations, tot_e, tot_r = {}, np.zeros((7, len(HOURS))), np.zeros((7, len(HOURS)))
for code, st in f["stations"].items():
    if code not in c.sidx:
        continue
    i = c.sidx[code]
    e = (np.array(st["entries"]) + np.array(st["exits"]))[:, 5:24].astype(float)       # day, hour
    for d, date in enumerate(week):                                                     # events, closures and holidays included
        tot = DAYS.get(date, {}).get(code, {}).get("total")
        if tot and len(tot) >= 24:
            e[d] = np.array(tot, dtype=float)[5:24]
    r = np.array([e[d] * ratio[i, wd[d]] for d in range(7)])
    stations[code] = {"name": st["name"], "expected": np.rint(e).astype(int).tolist(), "room": np.rint(r).astype(int).tolist()}
    tot_e += e
    tot_r += r
out = {"week": week, "hours": HOURS, "standard": 0.95,
       "what": "riders expected next week and the room to run so that riders fit in 95% of hours, by station and hour (entries plus exits at the gates)",
       "all": {"name": "All 50 stations", "expected": np.rint(tot_e).astype(int).tolist(), "room": np.rint(tot_r).astype(int).tolist()},
       "stations": dict(sorted(stations.items(), key=lambda kv: kv[1]["name"])),
       "limits": ["next week is built from 2025 reference days scaled by monthly growth, because BART has published no hourly counts for 2026",
                  "room is in riders per hour at the gates, not cars; BART would turn it into train lengths using train loads we do not have",
                  "event crowds, service changes and holidays come from the day files"],
       "days_with_events_included": sorted(DAYS)}
(OUT / "range.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
print("stations", len(stations), "| week margin", round(float(tot_r.sum() / tot_e.sum()), 3), "| Tue 17:00 all:", int(tot_e[1][12]), int(tot_r[1][12]))
