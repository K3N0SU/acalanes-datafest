"""
Layer 2: find next week's events with Gemini + Google Search, check them, and add their
measured uplift to the baseline forecast.

  finder   -> searches for events at venues near BART stations
  checker  -> a separate pass that re-searches every event and confirms date and start time
  harness  -> plain rules, no AI: known venue, date inside the week, parseable time,
              attendance capped at capacity, a source link. Then applies the uplift curve.

The AI never writes a ridership number. It only returns events. Riders added come from
public/data/uplift.json (measured on past games).

Needs GEMINI_API_KEY in a local .env file (never committed).

Run:   python scripts/event_agent.py 2026-11-23            # live week -> public/data/events.json
Test:  python scripts/event_agent.py 2025-08-11 --test     # past week, graded against the real MLB schedule
"""

import csv
import json
import math
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public" / "data"
API = "https://generativelanguage.googleapis.com/v1beta"

# starter venue table; data/venues.csv (if present) overrides capacities and adds venues
VENUES = [
    {"venue": "Oracle Park", "aliases": ["oracle park"], "station": "EMBR", "capacity": 41915, "curve": "EMBR"},
    {"venue": "Chase Center", "aliases": ["chase center"], "station": "EMBR", "capacity": 18064, "curve": "GENERIC"},
    {"venue": "Oakland Arena", "aliases": ["oakland arena", "oracle arena"], "station": "COLS", "capacity": 19596, "curve": "COLS"},
    {"venue": "Oakland Coliseum", "aliases": ["oakland coliseum", "oakland-alameda county coliseum", "ringcentral coliseum"], "station": "COLS", "capacity": 53200, "curve": "COLS"},
    {"venue": "California Memorial Stadium", "aliases": ["memorial stadium", "cal memorial"], "station": "DBRK", "capacity": 62467, "curve": "DBRK"},
    {"venue": "Greek Theatre", "aliases": ["greek theatre", "greek theater", "hearst greek"], "station": "DBRK", "capacity": 8500, "curve": "GENERIC"},
    {"venue": "Haas Pavilion", "aliases": ["haas pavilion"], "station": "DBRK", "capacity": 11858, "curve": "GENERIC"},
    {"venue": "Fox Theater", "aliases": ["fox theater", "fox theatre", "fox oakland"], "station": "19TH", "capacity": 2800, "curve": "GENERIC"},
    {"venue": "Paramount Theatre", "aliases": ["paramount theatre", "paramount theater"], "station": "19TH", "capacity": 3040, "curve": "GENERIC"},
    {"venue": "Bill Graham Civic Auditorium", "aliases": ["bill graham civic", "bill graham auditorium"], "station": "CIVC", "capacity": 8500, "curve": "GENERIC"},
    {"venue": "The Warfield", "aliases": ["warfield"], "station": "POWL", "capacity": 2300, "curve": "GENERIC"},
    {"venue": "Moscone Center", "aliases": ["moscone"], "station": "POWL", "capacity": 20000, "curve": "GENERIC"},
    {"venue": "SAP Center", "aliases": ["sap center"], "station": "BERY", "capacity": 17562, "curve": "GENERIC"},
]


def load_env():
    for name in (".env", ".env.local"):
        env = ROOT / name
        if not env.exists():
            continue
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                if v.strip():
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        sys.exit("No GEMINI_API_KEY found. Put GEMINI_API_KEY=... in a .env file in the project folder.")
    return key


def pick_model(key):
    if os.environ.get("GEMINI_MODEL"):
        return os.environ["GEMINI_MODEL"]
    try:
        r = requests.get(f"{API}/models", headers={"x-goog-api-key": key}, params={"pageSize": 200}, timeout=60)
        r.raise_for_status()
    except requests.RequestException:
        return "gemini-unavailable"   # searches and reasoning can still run on the other providers
    names = [m["name"].split("/")[-1] for m in r.json().get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]
    flash = [n for n in names if "flash" in n and not any(x in n for x in ("lite", "image", "tts", "live", "audio", "8b"))]
    stable = [n for n in flash if "preview" not in n and "exp" not in n] or flash

    def ver(n):
        m = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        return float(m.group(1)) if m else 0

    stable.sort(key=lambda n: (ver(n), -len(n)), reverse=True)
    if not stable:
        sys.exit(f"no usable Gemini model on this key. models: {names[:10]}")
    return stable[0]


# thinking settings, tried in order; the first one this model accepts is kept for the rest of the run
THINKING = [{"thinkingLevel": "high", "includeThoughts": True}, {"includeThoughts": True}, None]
_thinking = {"i": 0}


def search_provider():
    """which service runs the web searches: SEARCH_PROVIDER in .env = gemini (default), deepseek or claude.
    Nothing switches provider on its own: each one bills a different key."""
    return os.environ.get("SEARCH_PROVIDER", "").strip().lower() or "gemini"


def ask(key, model, prompt, trace, step):
    """one searched call with extended reasoning. returns (answer text, sources) and records in the trace
    what was searched, what was read, and a summary of the model's reasoning"""
    if search_provider() == "deepseek":   # we download the pages, DeepSeek only reads them (scripts/websearch.py)
        import websearch
        text, sources, queries, reasoning = websearch.ask(prompt)
        trace.append({"step": step, "searches": queries, "sources": sources[:12], "grounded": bool(sources),
                      "reasoning": reasoning[:3000], "search_model": "bing pages + " + websearch.MODEL})
        return text, sources
    if search_provider() == "claude":
        import claude_client
        text, sources, queries, reasoning = claude_client.search(prompt, max_uses=int(os.environ.get("SEARCH_MAX_USES", "4")))
        trace.append({"step": step, "searches": queries, "sources": sources[:12], "grounded": bool(sources or queries),
                      "reasoning": reasoning[:3000], "search_model": claude_client.SEARCH_MODEL})
        return text, sources
    r = None
    for attempt in range(7):
        cfg = {"temperature": 0}
        think = THINKING[_thinking["i"]]
        if think:
            cfg["thinkingConfig"] = think
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "tools": [{"google_search": {}}], "generationConfig": cfg}
        try:
            r = requests.post(f"{API}/models/{model}:generateContent", headers={"x-goog-api-key": key}, json=body, timeout=240)
        except requests.RequestException:  # dropped connection: try again
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 200:
            break
        if r.status_code == 400 and think and _thinking["i"] < len(THINKING) - 1:
            _thinking["i"] += 1  # this model does not take that thinking setting: try the next
            continue
        if r.status_code in (429, 500, 503):
            time.sleep(8 * (attempt + 1))
            continue
        raise SystemExit(f"Gemini error {r.status_code}: {r.text[:300]}")
    else:
        raise SystemExit("Gemini kept failing" + (f": {r.status_code} {r.text[:200]}" if r is not None else ": network errors"))
    cand = (r.json().get("candidates") or [{}])[0]
    parts = cand.get("content", {}).get("parts", [])
    text = "".join(x.get("text", "") for x in parts if not x.get("thought"))
    reasoning = " ".join(x.get("text", "") for x in parts if x.get("thought")).strip()
    gm = cand.get("groundingMetadata", {})
    sources = [{"title": ch.get("web", {}).get("title", ""), "url": ch.get("web", {}).get("uri", "")} for ch in gm.get("groundingChunks", [])]
    trace.append({"step": step, "searches": gm.get("webSearchQueries", []), "sources": sources[:12], "grounded": bool(gm.get("groundingChunks")),
                  "reasoning": reasoning[:3000], "thinking": THINKING[_thinking["i"]]})
    return text, sources


def parse_json(text):
    text = re.sub(r"```(?:json)?", "", text)
    for open_c, close_c in (("[", "]"), ("{", "}")):
        a, b = text.find(open_c), text.rfind(close_c)
        if a != -1 and b > a:
            try:
                return json.loads(text[a:b + 1])
            except json.JSONDecodeError:
                continue
    return None


def load_venues():
    venues = [dict(v) for v in VENUES]
    path = ROOT / "data" / "venues.csv"
    if path.exists():
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
                name = row.get("venue", "")
                cap = re.sub(r"[^\d]", "", row.get("capacity", ""))
                hit = next((v for v in venues if name and any(a in name.lower() for a in v["aliases"])), None)
                if hit and cap:
                    hit["capacity"] = int(cap)
    return venues


def match_venue(name, venues):
    n = (name or "").lower()
    return next((v for v in venues if any(a in n for a in v["aliases"])), None)


def parse_time(s):
    s = (s or "").strip().lower().replace(".", "")
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", s)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return h + mi / 60 if 0 <= h <= 23 and 0 <= mi < 60 else None


EVENT_SHAPE = """{"name": str, "venue": the venue name, "date": "YYYY-MM-DD", "start_time": "HH:MM" 24-hour local time,
  "expected_attendance": integer or null, "attendance_basis": "reported" | "typical for this team or venue" | "unknown",
  "source_url": the page where you found the date and time}"""


def find_events(key, model, week_start, venues, trace):
    """several search passes at once: the known venues in small groups, plus an open pass for anything large we did not list"""
    from concurrent.futures import ThreadPoolExecutor
    end = week_start + timedelta(days=6)
    when = f"between {week_start:%A %B %d, %Y} and {end:%A %B %d, %Y}"
    names = [v["venue"] for v in venues]
    groups = [names[i:i + 4] for i in range(0, len(names), 4)]

    def venue_pass(group):
        prompt = f"""Use Google Search to find every ticketed public event (pro and college sports, concerts, shows, conventions) taking place
{when} at these San Francisco Bay Area venues: {", ".join(group)}.
Open each venue's official calendar or the team's official schedule. Do not include events outside those dates.
Return ONLY a JSON array. Each item: {EVENT_SHAPE}
Use the venue names exactly as given. If you cannot find a start time, leave the event out."""
        text, _ = ask(key, model, prompt, trace, "finder: " + ", ".join(group))
        return parse_json(text)

    def open_pass(_):
        prompt = f"""Use Google Search to find any event {when} expected to draw 5,000 or more people within about a 20 minute walk or a short
transfer of a BART station in the San Francisco Bay Area, at a venue NOT in this list: {", ".join(names)}.
Think of stadiums, arenas, theatres, fairgrounds, convention halls, parades, races, festivals, gaming and esports events, graduations.
Return ONLY a JSON array. Each item: {EVENT_SHAPE}
Only include events you found on a page. If you find none, return []."""
        text, _ = ask(key, model, prompt, trace, "finder: open pass for unlisted venues")
        return parse_json(text)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(venue_pass, groups)) + list(pool.map(open_pass, [0]))
    events = [e for res in results if isinstance(res, list) for e in res if isinstance(e, dict)]
    return events, []


def check_events(key, model, events, trace):
    """second, independent pass: re-search each event and confirm date + start time. batches run at once"""
    from concurrent.futures import ThreadPoolExecutor

    def one(start):
        batch = events[start:start + 4]
        listing = "\n".join(f'{j + 1}. "{e.get("name")}" at {e.get("venue")} on {e.get("date")} at {e.get("start_time")}' for j, e in enumerate(batch))
        prompt = f"""Fact-check these event listings with Google Search. For each one, look up the official venue, team or ticketing page
and report what date and local start time that page gives. Do not trust the listing; it may be wrong.

{listing}

Return ONLY a JSON array with one item per listing, in the same order:
{{"n": number, "exists": true | false, "date": "YYYY-MM-DD" or null, "start_time": "HH:MM" 24-hour or null, "source_url": str or null, "note": short str}}"""
        text, _ = ask(key, model, prompt, trace, f"checker {start // 4 + 1}")
        res = parse_json(text)
        res = res if isinstance(res, list) else []
        return [(e, next((x for x in res if isinstance(x, dict) and x.get("n") == j + 1), None)) for j, e in enumerate(batch)]

    with ThreadPoolExecutor(max_workers=4) as pool:
        return [pair for chunk in pool.map(one, range(0, len(events), 4)) for pair in chunk]


def domain(url):
    m = re.match(r"^(?:https?://)?(?:www\.)?([^/:?#]+)", (url or "").strip().lower())
    return m.group(1) if m else ""


_PAGE_CACHE = {}


def check_page(url, terms=()):
    """open the cited page ourselves. 'confirmed' = it loads and mentions one of the terms,
    'exists' = it loads (or is a PDF) but the term was not found, anything else = could not be opened"""
    if not url or not str(url).startswith("http"):
        return "no address"
    key = (url, tuple(terms))
    if key in _PAGE_CACHE:
        return _PAGE_CACHE[key]
    try:
        r = requests.get(url, timeout=15, allow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"})
        if r.status_code != 200:
            out = f"http {r.status_code}"
        elif "html" not in r.headers.get("content-type", "") and "text" not in r.headers.get("content-type", ""):
            out = "exists"
        else:
            text = re.sub(r"<[^>]+>", " ", r.text).lower()
            out = "confirmed" if any(t and len(t) > 3 and t.lower() in text for t in terms) else "exists"
    except requests.RequestException:
        out = "unreachable"
    _PAGE_CACHE[key] = out
    return out


def source_ok(url, sources, terms=()):
    """a claim counts only if its source is real: either a site the search reported retrieving,
    or a page we can open ourselves. A made-up address fails both."""
    d = domain(url)
    if not d or "." not in d:
        return False
    got = {domain(x.get("title")) for x in sources} | {domain(x.get("url")) for x in sources}
    got.discard("")
    if any(d == g or d.endswith("." + g) or g.endswith("." + d) for g in got):
        return True
    return check_page(url, terms) in ("confirmed", "exists")


def research_demand(key, model, events, trace):
    """how big will each crowd really be? every claim needs a real source. batches run at once"""
    from concurrent.futures import ThreadPoolExecutor

    def one(start):
        batch = events[start:start + 3]
        listing = "\n".join(f'{j + 1}. "{e["name"]}" at {e["venue"]} (capacity {e.get("capacity", "unknown")}) on {e["date"]} at {e["start_time"]}' for j, e in enumerate(batch))
        prompt = f"""Use Google Search to judge how large the crowd will be at each event below. Look for evidence such as: sold out or tickets
still available, resale prices against face value, how many people this act or matchup drew at similar venues, the act's or teams' current
popularity (chart position, streaming numbers, standings, rivalry, playoff stakes), whether the venue is set up at full or reduced capacity for it.

{listing}

Every claim must come from a page you found. Do not state anything you cannot cite. If you find nothing for an event, return an empty evidence list.
Return ONLY a JSON array, one item per event in the same order:
{{"n": number, "demand": "low" | "typical" | "high" | "sold_out" | "unknown",
  "expected_attendance": integer or null,
  "evidence": [{{"claim": "one short factual sentence", "source_url": "the page it comes from"}}],
  "compared_with_the_others": "one sentence on which of these events will draw more, and why" or null}}"""
        text, sources = ask(key, model, prompt, trace, f"demand {start // 3 + 1}")
        res = parse_json(text)
        res = res if isinstance(res, list) else []
        out = {}
        for j, e in enumerate(batch):
            r = next((x for x in res if isinstance(x, dict) and x.get("n") == j + 1), None) or {}
            ev = [c for c in (r.get("evidence") or []) if isinstance(c, dict) and c.get("claim")]
            kept = [c for c in ev if source_ok(c.get("source_url"), sources, [str(e["name"])[:24]])]
            out[(e["name"], e["date"])] = {
                "demand": r.get("demand", "unknown") if kept else "unknown",
                "expected_attendance": r.get("expected_attendance") if kept else None,
                "evidence": kept, "claims_dropped_no_source": len(ev) - len(kept),
                "compared_with_the_others": r.get("compared_with_the_others") if kept else None,
            }
        return out

    merged = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for part in pool.map(one, range(0, len(events), 3)):
            merged.update(part)
    return merged


DISRUPTION_TYPES = ["service outage or planned closure", "strike", "severe weather", "wildfire smoke", "earthquake", "protest or march",
                    "parade or festival", "convention", "gaming or esports event", "school break", "other"]


def find_disruptions(key, model, week_start, trace):
    """things that move ridership and are not a ticketed event at one venue. three passes at once; each item needs a real source"""
    from concurrent.futures import ThreadPoolExecutor
    end = week_start + timedelta(days=6)
    when = f"between {week_start:%A %B %d, %Y} and {end:%A %B %d, %Y}"
    shape = f"""{{"type": one of {json.dumps(DISRUPTION_TYPES)}, "name": str, "dates": ["YYYY-MM-DD", ...], "start_time": "HH:MM" or null, "end_time": "HH:MM" or null,
  "where": "system-wide" or a list of BART station names or a neighbourhood, "effect": "more riders" | "fewer riders" | "service cut",
  "size": "one sentence on how big, with a number if the page gives one", "source_url": str}}"""
    passes = {
        "transit": f"""BART's own advisories for the dates {when}: planned track work, single tracking, station or entrance closures, schedule changes,
bus bridges; and the same for the transit that feeds or competes with BART (Muni, AC Transit, Caltrain, ferries), Bay Bridge or freeway closures,
and any transit strike or strike vote""",
        "city": f"""things happening in the San Francisco Bay Area {when} that put crowds on the street: protests, marches and rallies that have
been announced, parades, street festivals, races, large conventions, gaming and esports events, cruise ship calls at Pier 27, graduations""",
        "hazards": f"""natural hazards and public alerts for the San Francisco Bay Area {when}: National Weather Service watches and warnings
(atmospheric river, flooding, high wind, extreme heat), wildfire smoke and air quality alerts, power shutoffs, recent earthquakes;
and school or university breaks in session those days""",
    }

    def one(item):
        name, topic = item
        prompt = f"""Use Google Search to find {topic}.
Only include things you found on a page, with that page's address. If you find nothing, return an empty array. Do not guess.
Return ONLY a JSON array: {shape}"""
        text, sources = ask(key, model, prompt, trace, f"disruptions: {name}")
        res = parse_json(text)
        return [(x, sources) for x in (res if isinstance(res, list) else []) if isinstance(x, dict)]

    with ThreadPoolExecutor(max_workers=3) as pool:
        found = [pair for chunk in pool.map(one, passes.items()) for pair in chunk]
    days = {(week_start + timedelta(days=i)).isoformat() for i in range(7)}
    kept, dropped, seen = [], [], set()
    for it, sources in found:
        it["dates"] = [d for d in (it.get("dates") or []) if d in days]
        key_ = (str(it.get("name", "")).lower()[:40], tuple(it["dates"]))
        if key_ in seen:
            continue
        seen.add(key_)
        if not it["dates"]:
            dropped.append({"name": it.get("name"), "reason": "no date inside the forecast week"})
        elif not source_ok(it.get("source_url"), sources, [str(it.get("name", ""))[:24]]):
            dropped.append({"name": it.get("name"), "reason": "its source could not be opened"})
        else:
            kept.append(it)
    return kept, dropped


def harness(checked, week_start, venues):
    """plain rules. returns accepted events and rejected ones with the reason"""
    ok, bad, seen = [], [], set()
    days = [(week_start + timedelta(days=i)).isoformat() for i in range(7)]
    for e, c in checked:
        def reject(reason):
            bad.append({"name": e.get("name"), "venue": e.get("venue"), "date": e.get("date"), "start_time": e.get("start_time"), "reason": reason})

        v = match_venue(e.get("venue"), venues)
        if not v:
            reject("venue is not in our venue-to-station table"); continue
        if e.get("date") not in days:
            reject("date is outside the forecast week"); continue
        t = parse_time(e.get("start_time"))
        if t is None:
            reject("start time could not be read"); continue
        # the event's own link has to open. the finder sometimes writes a link that looks right and does not exist,
        # so try the finder's, then the checker's, and keep the first that loads
        links = [u for u in (e.get("source_url"), (c or {}).get("source_url")) if u]
        good = next((u for u in links if check_page(u, [str(e.get("name", ""))[:20]]) in ("confirmed", "exists")), None)
        if not good:
            reject("no source link that opens" if links else "no source link"); continue
        if good != e.get("source_url"):
            e = {**e, "source_note": "the finder's link did not open; the checker's did", "source_url": good}
        status, note = "unchecked", ""
        if c:
            ct = parse_time(c.get("start_time")) if c.get("start_time") else None
            if c.get("exists") is False:
                reject("checker could not confirm the event exists" + (f": {c.get('note')}" if c.get("note") else "")); continue
            if c.get("date") and c["date"] != e["date"]:
                reject(f"checker found a different date ({c['date']})"); continue
            if ct is not None and abs(ct - t) > 0.75:
                status, note = "time corrected", f"finder said {e.get('start_time')}, checker's source says {c.get('start_time')}"
                t = ct
            elif ct is not None:
                status = "confirmed"
            else:
                status = "date confirmed, time unconfirmed"
        key = (v["venue"], e["date"], int(t))
        if key in seen:
            continue
        seen.add(key)
        att = e.get("expected_attendance")
        basis = e.get("attendance_basis") or "unknown"
        try:
            att = int(att) if att else None
        except (TypeError, ValueError):
            att = None
        if not att:
            att, basis = int(v["capacity"] * 0.75), "assumed 75% of capacity"
        if att > v["capacity"]:
            att, basis = v["capacity"], basis + " (capped at venue capacity)"
        ok.append({"name": e.get("name"), "venue": v["venue"], "station": v["station"], "curve": v["curve"], "capacity": v["capacity"], "date": e["date"],
                   "start_hour": round(t, 2), "start_time": f"{int(t):02d}:{int(round((t % 1) * 60)):02d}", "attendance": att,
                   "attendance_basis": basis, "status": status, "note": note,
                   "source_url": e.get("source_url") or c.get("source_url"), "checker_source_url": (c or {}).get("source_url")})
    return ok, bad


def apply_uplift(events, week_start):
    """add measured riders per attendee to the baseline forecast"""
    fc = json.loads((OUT / "forecast.json").read_text(encoding="utf-8"))
    up = json.loads((OUT / "uplift.json").read_text(encoding="utf-8"))
    days = fc["week"]
    add = {}
    for e in events:
        part = "day" if e["start_hour"] < 16 else "night"
        curve = up.get(f'{e["curve"]}_{part}') or up.get(f"GENERIC_{part}")
        e["curve_used"] = f'{curve["station"]} {part} games ({curve["games"]} past games)'
        st, d, h0 = e["station"], days.index(e["date"]), int(math.floor(e["start_hour"]))
        a = add.setdefault(st, {"entries": [[0] * 24 for _ in range(7)], "exits": [[0] * 24 for _ in range(7)]})
        base = fc["stations"][st]
        best = (0, None)
        for off, en, ex in zip(curve["offsets"], curve["entries_per_1000"], curve["exits_per_1000"]):
            h = h0 + off
            if not 0 <= h <= 23:
                continue
            de, dx = e["attendance"] / 1000 * en, e["attendance"] / 1000 * ex
            # never push a station-hour below zero
            de = max(de, -(base["entries"][d][h] + a["entries"][d][h]))
            dx = max(dx, -(base["exits"][d][h] + a["exits"][d][h]))
            a["entries"][d][h] += round(de)
            a["exits"][d][h] += round(dx)
            if de + dx > best[0]:
                best = (de + dx, h)
        if best[1] is not None:
            h = best[1]
            normal = base["entries"][d][h] + base["exits"][d][h]
            e["peak_hour"] = h
            e["normal_riders_peak"] = normal
            e["added_riders_peak"] = round(best[0])
            e["times_normal"] = round((normal + best[0]) / normal, 2) if normal else None
    return add


def grade(found, week_start):
    """past-week test: compare what the agent found with the real MLB schedule"""
    truth = []
    with open(ROOT / "data" / "clean" / "games.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d = date.fromisoformat(r["date"])
            if week_start <= d <= week_start + timedelta(days=6):
                truth.append({"date": r["date"], "start_hour": float(r["start_hour"]), "venue": r["venue"], "team": r["team"]})
    hits, time_err = 0, []
    for t in truth:
        m = next((e for e in found if e["date"] == t["date"] and e["venue"] == t["venue"] and abs(e["start_hour"] - t["start_hour"]) < 3), None)
        if m:
            hits += 1
            time_err.append(round(abs(m["start_hour"] - t["start_hour"]) * 60))
    at_ballparks = [e for e in found if e["venue"] in {t["venue"] for t in truth} | {"Oracle Park", "Oakland Coliseum"}]
    false_alarms = [e for e in at_ballparks if not any(e["date"] == t["date"] and e["venue"] == t["venue"] for t in truth)]
    return {"week": week_start.isoformat(), "real_games": len(truth), "found": hits, "missed": len(truth) - hits,
            "avg_start_time_error_min": round(sum(time_err) / len(time_err), 1) if time_err else None,
            "max_start_time_error_min": max(time_err) if time_err else None,
            "events_at_ballparks_not_in_schedule": [f'{e["name"]} {e["date"]}' for e in false_alarms]}


def main():
    week_start = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 11, 23)
    test = "--test" in sys.argv
    key = load_env()
    model = pick_model(key)
    venues = load_venues()
    trace = []
    print("model:", model, "| week of", week_start)

    found, _ = find_events(key, model, week_start, venues, trace)
    print(f"finder returned {len(found)} events")
    checked = check_events(key, model, found, trace) if "--no-check" not in sys.argv else [(e, None) for e in found]
    ok, bad = harness(checked, week_start, venues)
    print(f"harness accepted {len(ok)}, rejected {len(bad)}")
    for e in ok:
        print("  +", e["date"], e["start_time"], e["venue"], "|", e["name"], "|", e["attendance"], "|", e["status"])
    for b in bad:
        print("  -", b["name"], "|", b["reason"])

    if test:
        g = grade(ok, week_start)
        g["model"] = model
        path = OUT / "agent_test.json"
        prev = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        prev = [p for p in prev if p["week"] != g["week"]] + [g]
        path.write_text(json.dumps(sorted(prev, key=lambda p: p["week"]), indent=1), encoding="utf-8")
        print(json.dumps(g, indent=1))
        return

    demand = research_demand(key, model, ok, trace) if ok and "--no-demand" not in sys.argv else {}
    for e in ok:
        d = demand.get((e["name"], e["date"]))
        if not d:
            continue
        e["demand"] = d
        if d["expected_attendance"]:  # a sourced figure replaces the guess, still capped at capacity
            e["attendance"] = min(int(d["expected_attendance"]), e["capacity"])
            e["attendance_basis"] = f"sourced ({len(d['evidence'])} cited claims), demand {d['demand']}"
        print("  demand:", e["name"][:40], "|", d["demand"], "|", e["attendance"], "|", len(d["evidence"]), "sourced claims,", d["claims_dropped_no_source"], "dropped")
    disruptions, dropped = find_disruptions(key, model, week_start, trace) if "--no-disruptions" not in sys.argv else ([], [])
    for x in disruptions:
        print("  disruption:", x.get("type"), "|", x.get("name"), "|", x.get("dates"), "|", x.get("effect"))
    for x in dropped:
        print("  dropped:", x)

    add = apply_uplift(ok, week_start)
    ok.sort(key=lambda e: (e["date"], e["start_hour"]))
    out = {"week_of": week_start.isoformat(), "model": model, "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
           "events": ok, "rejected": bad, "disruptions": disruptions, "disruptions_dropped": dropped, "added": add, "trace": trace,
           "source_rule": "a claim is kept only if its source is a site the search retrieved or a page we could open ourselves",
           "grounded": all(t["grounded"] for t in trace) if trace else False}
    (OUT / "events.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("wrote events.json |", sum(len(t["searches"]) for t in trace), "searches,", sum(len(t["sources"]) for t in trace), "sources")
    for e in ok:
        if e.get("times_normal"):
            print(f'  {e["venue"]} {e["date"]}: {e["station"]} at {e["peak_hour"]}:00 -> {e["times_normal"]}x normal (+{e["added_riders_peak"]})')


if __name__ == "__main__":
    main()
