"""
Structured feeds: events and disruptions straight from the leagues, ticket sellers and agencies.

No AI and no web search in this file. A feed either lists an event or it does not, so there is
nothing to hallucinate and nothing to source-check. It does three jobs:
  1. grades the search agent: of the events the feeds list, how many did the agent also find, and do the times agree?
  2. confirms or corrects start times in public/data/events.json (a feed beats a search result)
  3. adds events the search missed

Feeds, each used only if it is available:
  no key      ESPN schedules (Warriors, Sharks, Cal football and basketball), MLB Stats (Giants),
              BART advisories (BART's public key), SF open data (street closures)
  free key    TICKETMASTER_API_KEY, SEATGEEK_CLIENT_ID, API_511_KEY   in .env

Output: public/data/feeds.json; with --merge also updates public/data/events.json

Run:  python scripts/feeds.py 2026-11-23 [--merge]
"""

import json
import math
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

from event_agent import VENUES, load_env, match_venue

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public" / "data"
UA = {"User-Agent": "Mozilla/5.0"}
TZ = "America/Los_Angeles"
ESPN = {"Golden State Warriors": "basketball/nba/teams/gs", "San Jose Sharks": "hockey/nhl/teams/sj",
        "Cal football": "football/college-football/teams/25", "Cal men's basketball": "basketball/mens-college-basketball/teams/25",
        "Cal women's basketball": "basketball/womens-college-basketball/teams/25"}
KIND = {"Golden State Warriors": "basketball", "San Jose Sharks": "hockey", "Cal football": "football",
        "Cal men's basketball": "basketball", "Cal women's basketball": "basketball"}
BAY = (37.80, -122.27)


def get(url, **kw):
    r = requests.get(url, headers=UA, timeout=30, **kw)
    r.raise_for_status()
    return r.json()


def local(ts):
    t = pd.Timestamp(ts)
    t = t.tz_localize("UTC") if t.tzinfo is None else t
    return t.tz_convert(TZ)


def event(name, venue, when, source, feed, kind, **extra):
    return {"name": name, "venue": venue, "date": str(when.date()), "start_time": when.strftime("%H:%M"),
            "start_hour": round(when.hour + when.minute / 60, 2), "type": kind, "source_url": source, "feed": feed, **extra}


# ------------------------------------------------------------------ feeds without a key

def espn(days):
    out = []
    for team, path in ESPN.items():
        j = get(f"https://site.api.espn.com/apis/site/v2/sports/{path}/schedule")
        for e in j.get("events", []):
            comp = e["competitions"][0]
            when = local(e["date"])
            home = next((t for t in comp["competitors"] if t.get("homeAway") == "home"), None)
            if str(when.date()) not in days or not home:
                continue
            if home["team"].get("displayName", "").split()[0] not in team and team.split()[0] not in home["team"].get("displayName", ""):
                continue  # an away game
            away = next((t for t in comp["competitors"] if t.get("homeAway") == "away"), {})
            link = next((x.get("href") for x in e.get("links", []) if x.get("href")), f"https://www.espn.com/{path.split('/')[1]}/team/schedule")
            out.append(event(f"{team} vs {away.get('team', {}).get('displayName', 'TBD')}", comp.get("venue", {}).get("fullName", ""), when,
                             link, "ESPN schedule", KIND[team], time_is_set=not comp.get("timeValid") is False))
    return out


def mlb(days):
    j = get("https://statsapi.mlb.com/api/v1/schedule", params={"sportId": 1, "teamId": 137, "startDate": days[0], "endDate": days[-1], "hydrate": "venue"})
    out = []
    for d in j.get("dates", []):
        for g in d["games"]:
            if g["teams"]["home"]["team"]["id"] == 137:
                out.append(event(f"San Francisco Giants vs {g['teams']['away']['team']['name']}", g["venue"]["name"], local(g["gameDate"]),
                                 "https://www.mlb.com/giants/schedule", "MLB Stats", "baseball"))
    return out


def bart_advisories():
    """what BART is telling riders right now (its public API key is published in BART's own API documentation)"""
    j = get("https://api.bart.gov/api/bsa.aspx", params={"cmd": "bsa", "key": os.environ.get("BART_API_KEY", "MW9S-E7SL-26DU-VV8V"), "json": "y"})
    out = []
    for b in j.get("root", {}).get("bsa", []):
        text = (b.get("description") or {}).get("#cdata-section", "").strip()
        if text and not any(x in text.lower() for x in ("no delays reported", "no advisories")):
            out.append({"type": "service outage or planned closure", "name": text[:140], "dates": [str(date.today())], "where": b.get("station") or "system-wide",
                        "effect": "service cut", "size": text, "source_url": "https://www.bart.gov/schedules/advisories", "feed": "BART advisories", "posted": b.get("posted")})
    return out


def sf_street_closures(days):
    """street closures the city has permitted (parades, races, street fairs), from SF open data. the dataset is looked up by name"""
    cat = get("https://data.sf.gov/api/catalog/v1", params={"q": "street closures", "limit": 20})
    hit = None
    for r in cat.get("results", []):
        x = r["resource"]
        cols = [c.lower() for c in x.get("columns_field_name", [])]
        if "closure" in x["name"].lower() and any("start" in c for c in cols) and any("end" in c for c in cols):
            hit = (x["id"], x["name"], cols)
            break
    if not hit:
        return [], "no street closure dataset found in the SF open data catalog"
    ds, name, cols = hit
    start = next(c for c in cols if "start" in c)
    end = next(c for c in cols if "end" in c)
    rows = get(f"https://data.sf.gov/resource/{ds}.json", params={"$where": f"{start} <= '{days[-1]}T23:59:59' AND {end} >= '{days[0]}T00:00:00'", "$limit": 500})
    out = []
    for r in rows:
        label = next((str(r[k]) for k in ("event_name", "name", "info", "type", "description", "street") if r.get(k)), "street closure")
        out.append({"type": "parade or festival", "name": label[:120], "dates": [d for d in days if str(r.get(start, ""))[:10] <= d <= str(r.get(end, ""))[:10]],
                    "where": " / ".join(str(r[k]) for k in ("street", "streetname", "from_st", "to_st", "location") if r.get(k))[:120] or "San Francisco",
                    "effect": "more riders", "size": "city street closure permit", "source_url": f"https://data.sf.gov/d/{ds}", "feed": f"SF open data: {name}"})
    return out, f"{len(rows)} closures in the week from '{name}'"


# ------------------------------------------------------------------ feeds that need a free key

def ticketmaster(days):
    j = get("https://app.ticketmaster.com/discovery/v2/events.json", params={
        "apikey": os.environ["TICKETMASTER_API_KEY"].strip(), "latlong": f"{BAY[0]},{BAY[1]}", "radius": 35, "unit": "miles", "size": 200, "sort": "date,asc",
        "startDateTime": f"{days[0]}T08:00:00Z", "endDateTime": f"{(date.fromisoformat(days[-1]) + timedelta(days=1)).isoformat()}T08:00:00Z"})
    out = []
    for e in j.get("_embedded", {}).get("events", []):
        st = e.get("dates", {}).get("start", {})
        if not st.get("localDate") or not st.get("localTime"):
            continue
        when = pd.Timestamp(f"{st['localDate']} {st['localTime']}")
        v = (e.get("_embedded", {}).get("venues") or [{}])[0]
        seg = (e.get("classifications") or [{}])[0].get("segment", {}).get("name", "").lower()
        pr = (e.get("priceRanges") or [{}])[0]
        out.append(event(e.get("name", ""), v.get("name", ""), when, e.get("url", "https://www.ticketmaster.com"), "Ticketmaster",
                         "concert" if seg == "music" else seg or "event", price_from=pr.get("min"), price_to=pr.get("max"),
                         on_sale=e.get("dates", {}).get("status", {}).get("code")))
    return out


def seatgeek(days):
    j = get("https://api.seatgeek.com/2/events", params={
        "client_id": os.environ["SEATGEEK_CLIENT_ID"].strip(), "lat": BAY[0], "lon": BAY[1], "range": "35mi", "per_page": 250,
        "datetime_local.gte": f"{days[0]}T00:00:00", "datetime_local.lte": f"{days[-1]}T23:59:59"})
    out = []
    for e in j.get("events", []):
        when = pd.Timestamp(e["datetime_local"])
        v = e.get("venue", {})
        s = e.get("stats", {})
        out.append(event(e.get("title", ""), v.get("name", ""), when, e.get("url", "https://seatgeek.com"), "SeatGeek", e.get("type", "event"),
                         popularity=e.get("score"), venue_capacity=v.get("capacity"), lowest_price=s.get("lowest_price"), listings=s.get("listing_count")))
    return out


def five11(days):
    j = requests.get("https://api.511.org/transit/servicealerts", params={"api_key": os.environ["API_511_KEY"].strip(), "agency": "BA", "format": "json"}, headers=UA, timeout=30)
    j.raise_for_status()
    data = json.loads(j.content.decode("utf-8-sig"))
    out = []
    for ent in data.get("Entities", []):
        a = ent.get("Alert", {})
        text = next((t.get("Text") for t in a.get("HeaderText", {}).get("Translations", []) if t.get("Text")), "")
        periods = a.get("ActivePeriods", [])
        active = [d for d in days if any(datetime.fromtimestamp(p.get("Start", 0)).date().isoformat() <= d <= datetime.fromtimestamp(p.get("End") or 4102444800).date().isoformat() for p in periods)] or days[:1]
        if text:
            out.append({"type": "service outage or planned closure", "name": text[:140], "dates": active, "where": "BART", "effect": "service cut", "size": text,
                        "source_url": "https://511.org/transit/alerts", "feed": "511.org service alerts"})
    return out


# ------------------------------------------------------------------ compare and merge

def main():
    load_env()
    start = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1][0].isdigit() else date(2026, 11, 23)
    days = [(start + timedelta(days=i)).isoformat() for i in range(7)]
    sources, events, disruptions = [], [], []

    def run(name, fn, kind, needs=None):
        if needs and not os.environ.get(needs, "").strip():
            sources.append({"feed": name, "status": f"off: add {needs} to .env", "items": 0})
            return
        try:
            res = fn()
            note = None
            if isinstance(res, tuple):
                res, note = res
            (events if kind == "events" else disruptions).extend(res)
            sources.append({"feed": name, "status": "ok" + (f" ({note})" if note else ""), "items": len(res)})
        except Exception as e:
            sources.append({"feed": name, "status": f"failed: {type(e).__name__} {str(e)[:100]}", "items": 0})

    run("ESPN schedules", lambda: espn(days), "events")
    run("MLB Stats", lambda: mlb(days), "events")
    run("Ticketmaster Discovery", lambda: ticketmaster(days), "events", "TICKETMASTER_API_KEY")
    run("SeatGeek", lambda: seatgeek(days), "events", "SEATGEEK_CLIENT_ID")
    run("BART advisories", bart_advisories, "disruptions")
    run("SF open data street closures", lambda: sf_street_closures(days), "disruptions")
    run("511.org service alerts", lambda: five11(days), "disruptions", "API_511_KEY")

    # keep events at venues we can map to a station; the rest are listed but not forecast
    mapped, unmapped = [], []
    for e in events:
        v = match_venue(e["venue"], VENUES)
        (mapped if v else unmapped).append({**e, "venue": v["venue"], "station": v["station"], "curve": v["curve"], "capacity": v["capacity"]} if v else e)

    # grade the search agent against the feeds
    path = OUT / "events.json"
    found = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"events": []}
    agent = found.get("events", [])

    def same(a, b):
        return a["venue"] == b["venue"] and a["date"] == b["date"] and abs(a["start_hour"] - b["start_hour"]) <= 3

    rows, gaps = [], []
    for f in mapped:
        m = next((a for a in agent if same(a, f)), None)
        if m:
            gaps.append(round(abs(m["start_hour"] - f["start_hour"]) * 60))
        rows.append({"feed_event": f["name"], "venue": f["venue"], "date": f["date"], "feed_time": f["start_time"], "feed": f["feed"],
                     "search_agent_found_it": bool(m), "search_agent_time": m["start_time"] if m else None, "minutes_apart": gaps[-1] if m else None})
    extra = [a["name"] for a in agent if not any(same(a, f) for f in mapped)]
    grade = {"events_in_feeds_at_mapped_venues": len(mapped), "search_agent_also_found": sum(r["search_agent_found_it"] for r in rows),
             "start_times_within_15_minutes": sum(1 for g in gaps if g <= 15), "largest_time_gap_minutes": max(gaps) if gaps else None,
             "search_agent_events_not_in_any_feed": len(extra)}

    if "--merge" in sys.argv:
        for f in mapped:
            m = next((a for a in agent if same(a, f)), None)
            if m:
                m["confirmed_by_feed"] = f["feed"]
                if abs(m["start_hour"] - f["start_hour"]) * 60 > 15:
                    m["note"] = f"start time corrected from {m['start_time']} to {f['start_time']} by {f['feed']}"
                    m["start_time"], m["start_hour"] = f["start_time"], f["start_hour"]
                for k in ("popularity", "price_from", "lowest_price", "listings", "on_sale"):
                    if f.get(k) is not None:
                        m.setdefault("ticket_signals", {})[k] = f[k]
            else:
                att = int(f["capacity"] * 0.75)
                agent.append({**f, "attendance": att, "attendance_basis": "assumed 75% of capacity", "status": "from a feed", "confirmed_by_feed": f["feed"], "source_opens": True})
        agent.sort(key=lambda e: (e["date"], e["start_hour"]))
        known = {str(d.get("name", "")).lower()[:40] for d in found.get("disruptions", [])}
        found.setdefault("disruptions", []).extend(d for d in disruptions if d.get("dates") and str(d["name"]).lower()[:40] not in known and d["feed"] != "SF open data street closures")
        found["events"], found["feeds"] = agent, {"sources": sources, "grade": grade}
        path.write_text(json.dumps(found, indent=1), encoding="utf-8")

    (OUT / "feeds.json").write_text(json.dumps({"week_of": days[0], "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "sources": sources,
                                                "search_agent_grade": grade, "comparison": rows, "search_agent_only": extra,
                                                "events": mapped, "events_at_venues_we_do_not_map": unmapped[:60], "disruptions": disruptions[:80]}, indent=1), encoding="utf-8")
    for s in sources:
        print(f"{s['feed']:<30} {s['items']:>3} items  {s['status']}")
    for r in rows:
        print(f"  {r['date']} {r['feed_time']} {r['venue'][:24]:<24} {r['feed_event'][:44]:<44} agent: {'yes ' + str(r['search_agent_time']) if r['search_agent_found_it'] else 'MISSED'}")
    print(json.dumps(grade))
    print("search agent only (no feed covers these):", extra)


if __name__ == "__main__":
    main()
