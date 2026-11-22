"""
One month of Bay Area events, checked and put in the shape the harness reads.

The raw lists in data/calendars/month_raw/*.json were collected from venue, team, organiser and agency pages,
one file per area (San Francisco venues, East Bay, South Bay, conventions and arts, holiday and civic, sports, transit).
Every row carries the page it was read from. This script does the checking:

  1. runs are expanded to one row per date; anything outside the range is dropped
  2. the weekday written on the row must match the calendar (catches listings copied from an earlier year)
  3. every source page is opened again; a page that does not exist drops the row
  4. where the page can be read, the date has to appear on it
  5. the same event found twice (by a venue list and a sports list) is merged
  6. venues are matched to the harness's venue table and to a BART station

Input:  data/calendars/month_raw/*.json
Output: public/data/events_month.json

Run:  python scripts/events_month.py            (add --no-check to skip opening the pages)
"""

import json
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "calendars" / "month_raw"
OUT = ROOT / "public" / "data"
START, END = "2026-11-21", "2026-12-21"
FILL = 0.85                                   # share of a venue's capacity assumed when no page gives a crowd
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
STATION_WORDS = {"civic center": "CIVC", "un plaza": "CIVC", "powell": "POWL", "montgomery": "MONT", "embarcadero": "EMBR", "coliseum": "COLS",
                 "downtown berkeley": "DBRK", "north berkeley": "NBRK", "ashby": "ASHB", "19th": "19TH", "12th": "12TH", "lake merritt": "LAKE",
                 "west oakland": "WOAK", "macarthur": "MCAR", "rockridge": "ROCK", "fruitvale": "FTVL", "16th": "16TH", "24th": "24TH",
                 "glen park": "GLEN", "balboa": "BALB", "daly city": "DALY", "colma": "COLM", "south san francisco": "SSAN", "san bruno": "SBRN",
                 "millbrae": "MLBR", "sfo": "SFIA", "airport": "SFIA", "milpitas": "MLPT", "berryessa": "BERY", "north san jos": "BERY",
                 "warm springs": "WARM", "fremont": "FRMT", "union city": "UCTY", "hayward": "HAYW", "bay fair": "BAYF", "san leandro": "SANL",
                 "castro valley": "CAST", "dublin": "DUBL", "pleasanton": "DUBL", "walnut creek": "WCRK", "pleasant hill": "PHIL", "concord": "CONC",
                 "lafayette": "LAFY", "orinda": "ORIN", "richmond": "RICH", "el cerrito": "DELN", "pittsburg": "PITT", "antioch": "ANTC",
                 "oakland airport": "OAKL"}
KIND = {"nba": "basketball", "basketball": "basketball", "warriors": "basketball", "women's classic": "basketball", "nhl": "hockey", "hockey": "hockey",
        "sharks": "hockey", "pwhl": "hockey", "nfl": "football", "football": "football", "49ers": "football", "big game": "football"}
# venues a long way from any BART station: listed for completeness, not for the station forecast
FAR = ["levi", "stanford", "maples", "cefcu", "paypal park", "san jose civic", "center for the performing arts", "leavey", "provident",
       "saint mary", "university credit union", "war memorial gym", "sobrato", "golden gate park", "botanical", "shoreline"]
GENERIC = {"golden", "state", "warriors", "sharks", "jose", "california", "bears", "mens", "womens", "basketball", "football", "tour", "with",
           "show", "concert", "live", "world", "holiday", "christmas", "symphony", "francisco", "oakland", "ballet", "nutcracker"}


def station_code(text, codes):
    t = (text or "").lower()
    if t.upper() in codes:
        return t.upper()
    for words in sorted(STATION_WORDS, key=len, reverse=True):
        if words in t and STATION_WORDS[words] in codes:
            return STATION_WORDS[words]
    return None


def norm(s):
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


def vk(e):
    """venue key for spotting the same event twice: 'Cow Palace, 2600 Geneva Ave' and 'Cow Palace' are one place"""
    return norm((e.get("venue") or "").split(",")[0])[:18]


def to_hour(t):
    m = re.match(r"^(\d{1,2}):(\d{2})$", str(t or "").strip())
    return (int(m.group(1)) + int(m.group(2)) / 60) if m and int(m.group(1)) < 24 else None


def date_on_page(text, d):
    """is this date written on the page in any common form?"""
    ts = pd.Timestamp(d)
    mon, mon3, day = ts.strftime("%B").lower(), ts.strftime("%b").lower(), ts.day
    t = text.lower()
    pats = [rf"{mon}\s+{day}(\D|$)", rf"{mon3}\.?\s+{day}(\D|$)", rf"(\D|^){day}\s+{mon3}", rf"(\D|^){ts.month}/{day}(\D|$)", ts.strftime("%Y-%m-%d"),
            rf"(\D|^){ts.month}\.{day}(\D|$)", ts.strftime("%Y%m%d"), ts.strftime("%m%d%y"), ts.strftime("%y%m%d")]
    return any(re.search(p, t) for p in pats)


def open_page(url):
    """(state, text): state is 'opens', 'blocked' (the site refuses scripts; not evidence either way) or 'missing'"""
    if not url or not str(url).startswith("http"):
        return "missing", ""
    try:
        r = requests.get(url, headers=UA, timeout=20, allow_redirects=True)
    except requests.RequestException:
        return "blocked", ""
    if r.status_code == 200:
        return "opens", re.sub(r"<[^>]+>", " ", r.text)[:600000]
    if r.status_code in (404, 410):
        return "missing", ""
    return "blocked", ""


def main():
    from event_agent import VENUES, match_venue
    names = {k: v["name"] for k, v in json.loads((OUT / "forecast.json").read_text(encoding="utf-8"))["stations"].items()}
    codes = set(names)
    rows, disruptions, dropped, ongoing = [], [], [], []
    for path in sorted(RAW.glob("*.json")):
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print("unreadable:", path.name, e)
            continue
        for it in items if isinstance(items, list) else []:
            it["list"] = path.stem
            if path.stem == "transit":
                disruptions.append(it)
                continue
            dates = it.get("dates") or ([it["date"]] if it.get("date") else [])
            single = len(dates) == 1
            it["from_run"] = not single
            # an attraction open most days for weeks (ice rink, light show, daily market) is part of the season, not an event on a day
            if len(dates) > 12 and (it.get("type") in ("holiday", "market", "festival", "other") or not it.get("start_time")) and it.get("type") not in ("theatre", "convention"):
                inside = sorted(str(pd.Timestamp(d).date()) for d in dates if START <= str(d)[:10] <= END)
                if inside:
                    ongoing.append({"name": it.get("name"), "venue": it.get("venue"), "city": it.get("city"), "station": station_code(it.get("nearest_bart_station"), codes),
                                    "from": inside[0], "to": inside[-1], "days_in_range": len(inside), "hours": f"{it.get('start_time') or '?'} to {it.get('end_time') or '?'}",
                                    "type": it.get("type"), "source_url": it.get("source_url"), "source_quote": it.get("source_quote"), "confidence": it.get("confidence")})
                continue
            for d in dates:
                try:
                    ts = pd.Timestamp(d)
                except (ValueError, TypeError):
                    dropped.append({**it, "why": f"unreadable date {d}"})
                    continue
                if not (pd.Timestamp(START) <= ts <= pd.Timestamp(END)):
                    continue
                wd = (it.get("weekday") or "")[:3].title()
                if single and wd and wd != ts.strftime("%a"):
                    dropped.append({k: it.get(k) for k in ("name", "venue", "date", "weekday", "source_url", "list")} | {"why": f"written as {wd} but {d} is a {ts.strftime('%a')}: likely another year's listing"})
                    continue
                rows.append({**it, "date": str(ts.date()), "weekday": ts.strftime("%a")})

    # ---- open every source page once
    urls = sorted({r.get("source_url") for r in rows + disruptions if r.get("source_url")})
    pages = {}
    if "--no-check" not in sys.argv:
        with ThreadPoolExecutor(max_workers=16) as pool:
            pages = dict(zip(urls, pool.map(open_page, urls)))
    events, unmapped = [], []
    for r in rows:
        state, text = pages.get(r.get("source_url"), ("not checked", ""))
        if state == "missing":
            dropped.append({k: r.get(k) for k in ("name", "venue", "date", "source_url", "list")} | {"why": "the source page does not exist"})
            continue
        # for one night of a run the page usually prints the range, not each date, so the date test only counts for single events
        seen = date_on_page(text, r["date"]) if state == "opens" and not r.get("from_run") else None
        v = match_venue(r.get("venue"), VENUES)
        cap = (v or {}).get("capacity") or r.get("venue_capacity")
        stated = r.get("expected_attendance")
        full = r.get("sold_out") is True
        att = int(stated) if isinstance(stated, (int, float)) and stated > 0 else (int(cap * (1 if full else FILL)) if isinstance(cap, (int, float)) and cap else None)
        label = f"{r.get('league', '')} {r.get('name', '')} {r.get('type', '')}".lower()
        typ = next((KIND[k] for k in KIND if k in label), r.get("type") or "other")
        if "nutcracker" in label or "ballet" in label:
            typ = "ballet"
        elif "opera" in norm(r.get("name")) and "opera house" not in norm(r.get("name")):
            typ = "opera"
        far = bool(re.search(r"not near|no direct|far from bart|not on bart", (r.get("access_note") or "").lower())) or (not v and any(w in (r.get("venue") or "").lower() for w in FAR))
        e = {"name": r.get("name"), "venue": (v or {}).get("venue") or r.get("venue"), "city": r.get("city"),
             "station": (v or {}).get("station") or station_code(r.get("nearest_bart_station"), codes), "date": r["date"], "weekday": r["weekday"],
             "start_time": r.get("start_time") if to_hour(r.get("start_time")) is not None else None, "start_hour": to_hour(r.get("start_time")),
             "end_time": r.get("end_time"), "type": typ, "attendance": att,
             "attendance_basis": "stated on the page" if att and att == stated else ("listed as sold out: venue capacity" if att and full else
                                                                                      f"venue capacity x {FILL}, an estimate" if att else "no figure on any page"),
             "capacity": cap, "sold_out": r.get("sold_out"), "status": "confirmed", "access_note": r.get("access_note"),
             "source_url": r.get("source_url"), "source_quote": r.get("source_quote"), "source_opens": state, "date_on_page": seen,
             "confidence": r.get("confidence"), "list": r["list"], "curve": (v or {}).get("curve"),
             "one_night_of_a_run": bool(r.get("from_run")), "far_from_bart": far}
        (events if v else unmapped).append(e)

    # ---- the same event found by two lists: keep the row with a start time and a page that shows the date
    def merge(lst):
        best = {}
        for e in lst:
            words = [w for w in norm(e["name"]).split() if len(w) > 3][:2]
            key = (e["date"], vk(e), e["start_time"] or " ".join(words))
            rank = (e["date_on_page"] is True, e["source_opens"] == "opens", e["start_time"] is not None, e["confidence"] == "high")
            if key not in best or rank > best[key][0]:
                best[key] = (rank, e)
        # second pass: two lists giving the same game different start times, or the two halves of a doubleheader
        out, rank_of = [], {}
        for rank, e in sorted(best.values(), key=lambda x: x[0], reverse=True):
            words = {w for w in norm(e["name"]).split() if len(w) > 3} - GENERIC
            twin = next((o for o in out if o["date"] == e["date"] and vk(o) == vk(e) and not o["one_night_of_a_run"]
                         and words & ({w for w in norm(o["name"]).split() if len(w) > 3} - GENERIC)
                         and (o["type"] in ("basketball", "hockey", "football", "sports") or abs((o["start_hour"] or 0) - (e["start_hour"] or 0)) <= 1.5)), None)
            if twin is None:
                out.append(e)
            elif e["start_time"] and not twin["start_time"]:
                twin["start_time"], twin["start_hour"] = e["start_time"], e["start_hour"]
                twin["start_time_from"] = e["source_url"]
            elif e["start_time"] and e["start_time"] != twin["start_time"]:
                twin["also_listed_at"] = sorted(set(twin.get("also_listed_at", []) + [e["start_time"]]))
        timed = {(e["date"], vk(e)) for e in out if e["start_time"]}
        return sorted((e for e in out if e["start_time"] or (e["date"], vk(e)) not in timed or e["type"] in ("convention", "festival", "holiday", "market")),
                      key=lambda e: (e["date"], e["start_hour"] or 0, e["venue"] or ""))

    n_before = len(events) + len(unmapped)
    events, unmapped = merge(events), merge(unmapped)
    dis = []
    for d in disruptions:
        state, _ = pages.get(d.get("source_url"), ("not checked", ""))
        dates = [x for x in (d.get("dates") or []) if START <= str(x)[:10] <= END]
        if state == "missing" or not dates:
            dropped.append({k: d.get(k) for k in ("name", "dates", "source_url", "list")} | {"why": "the source page does not exist" if state == "missing" else "no date in range"})
            continue
        where = d.get("where")
        if isinstance(where, list):
            where = [c for c in (station_code(w, codes) for w in where) if c] or where
        dis.append({"type": d.get("kind"), "name": d.get("name"), "agency": d.get("agency"), "dates": dates, "start_time": d.get("start_time"), "end_time": d.get("end_time"),
                    "where": where, "effect": d.get("expected_effect"), "size": d.get("detail"), "source_url": d.get("source_url"), "source_quote": d.get("source_quote"),
                    "source_opens": state, "confidence": d.get("confidence")})

    by_day = Counter(e["date"] for e in events + unmapped)
    by_station = Counter(e["station"] for e in events + unmapped if e["station"])
    days = [str(d.date()) for d in pd.date_range(START, END)]
    single = [e for e in events + unmapped if not e["one_night_of_a_run"]]
    summary = {"events_at_venues_in_the_harness": len(events), "events_at_other_venues": len(unmapped), "transit_changes": len(dis),
               "season_long_attractions": len(ongoing), "single_events": len(single), "nights_of_runs": len(events) + len(unmapped) - len(single),
               "single_events_with_the_date_found_on_the_page": sum(1 for e in single if e["date_on_page"] is True),
               "single_events_where_the_page_opens_but_the_date_was_not_found": sum(1 for e in single if e["date_on_page"] is False),
               "single_events_whose_page_refuses_scripts": sum(1 for e in single if e["source_opens"] == "blocked"),
               "events_with_no_crowd_figure": sum(1 for e in events + unmapped if not e["attendance"]),
               "events_far_from_bart": sum(1 for e in events + unmapped if e["far_from_bart"]),
               "rows_merged_as_duplicates": n_before - len(events) - len(unmapped), "dropped": len(dropped),
               "source_pages": dict(Counter(s for s, _ in pages.values())),
               "date_seen_on_page": dict(Counter(str(e["date_on_page"]) for e in events + unmapped)),
               "days_with_nothing_found": [d for d in days if d not in by_day],
               "busiest_days": by_day.most_common(6), "by_station": {names.get(k, k): n for k, n in by_station.most_common(12)},
               "largest": [{k: e[k] for k in ("date", "start_time", "name", "venue", "station", "attendance", "attendance_basis")}
                           for e in sorted(events + unmapped, key=lambda e: -(e["attendance"] or 0))[:15]]}
    (OUT / "events_month.json").write_text(json.dumps({
        "range": [START, END], "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "how": "read from venue, team, organiser and agency pages; every source page reopened by scripts/events_month.py",
        "summary": summary, "events": events, "unmapped": unmapped, "ongoing": ongoing, "disruptions": dis, "dropped": dropped}, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "largest"}, indent=1))
    for e in summary["largest"]:
        print(f"  {e['date']} {e['start_time'] or '--:--'} {str(e['attendance']):>7}  {e['name'][:52]:<52} {str(e['venue'])[:26]:<26} {e['station']}")
    print("dropped:")
    for d in dropped[:25]:
        print("  ", str(d.get("name"))[:50], "|", d.get("date") or d.get("dates"), "|", d["why"])


if __name__ == "__main__":
    main()
