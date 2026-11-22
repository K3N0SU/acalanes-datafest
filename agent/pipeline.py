"""Find -> Check -> Harness. The AI only finds and confirms events. It never outputs a ridership number."""
import csv
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from . import net, sources
from .config import ROOT

DEFAULT_VENUES = ROOT / "data" / "venues.csv"

# ---------- venue table (owned by InterstellarApx: data/venues.csv) ----------

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def load_venues(path=DEFAULT_VENUES) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            r = {_norm(k).replace(" ", "_"): (v or "").strip() for k, v in r.items()}
            r["capacity_n"] = int(re.sub(r"\D", "", r.get("capacity", "")) or 0)
            rows.append(r)
    return rows


def match_venue(name: str, venues: list[dict]):
    n = _norm(name)
    for v in venues:
        vn = _norm(v.get("venue", ""))
        if vn and (vn == n or vn in n or n in vn):
            return v
    return None


# ---------- query planning ----------

def plan_queries(start: date, end: date, venues: list[dict]) -> list[str]:
    span = f"{start:%B %-d} to {end:%B %-d, %Y}"
    names = [v["venue"] for v in venues] or [
        "Oracle Park", "Chase Center", "Oakland Arena", "Cal Memorial Stadium",
        "Bill Graham Civic Auditorium", "Fox Theater Oakland", "Paramount Theatre Oakland",
        "Greek Theatre Berkeley", "Moscone Center"]
    qs = [f"{n} events {span}" for n in names]
    qs += [
        f"San Francisco Bay Area concerts and festivals {span}",
        f"San Francisco conventions conferences Moscone Center {span}",
        f"Oakland Berkeley major events {span}",
        f"BART service changes track work strike delays {span}",
        f"Bay Area street closures parades marathons protests marches {span}",
        f"Warriors Giants Cal Bears 49ers home game schedule {span}",
        f"Bay Area holiday events Thanksgiving weekend {span}",
    ]
    return qs


# ---------- LLM passes ----------

FIND_SYSTEM = """You are a research assistant finding upcoming public events and transit disruptions
in the San Francisco Bay Area that could change how many people ride BART. Use web search.
Only report events whose date you found in a source. Never guess or invent. Never estimate ridership.
Return ONLY a JSON array (no prose). Each item:
{"name": str, "venue": str, "city": str, "date": "YYYY-MM-DD", "start_time": "HH:MM" (24h, Pacific),
 "end_time": "HH:MM" or null, "expected_attendance": int or null,
 "category": "sports|concert|festival|conference|parade|protest|holiday|other|disruption",
 "source_urls": [str, ...], "notes": str}
Use category "disruption" for BART strikes, track work, closures; put the affected area in "venue"."""

CHECK_SYSTEM = """You verify claims about events. Search for the event independently, ideally on the
organizer's or venue's own site. Return ONLY JSON:
{"verdict": "confirmed|disputed|not_found", "date": "YYYY-MM-DD" or null, "start_time": "HH:MM" or null,
 "source_urls": [str], "reason": str}
confirmed = same event, same date, start time within 30 minutes. disputed = found but date/time differs."""


def extract_json(text: str):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    for opener, closer in (("[", "]"), ("{", "}")):
        i, j = text.find(opener), text.rfind(closer)
        if i != -1 and j > i:
            try:
                return json.loads(text[i:j + 1])
            except json.JSONDecodeError:
                continue
    return None


def find_events(provider, queries, start, end, trace, batch=4):
    """Split queries into batches and run them in parallel; each batch is one agentic research call."""
    groups = [queries[i:i + batch] for i in range(0, len(queries), batch)]

    def run(group):
        prompt = (f"Forecast window: {start} to {end} (inclusive). Search for events in the Bay Area in "
                  f"this window. Suggested searches:\n" + "\n".join(f"- {q}" for q in group) +
                  "\nFollow up on promising results and open event pages to confirm the date and time.")
        local_trace = []
        try:
            text, srcs = provider.research(FIND_SYSTEM, prompt, local_trace)
        except Exception as e:
            trace.append({"step": "find", "error": str(e), "queries": group})
            return []
        items = extract_json(text)
        items = items if isinstance(items, list) else []
        for it in items:
            it["_grounding"] = [s["url"] for s in srcs][:10]
        trace.append({"step": "find", "queries": group, "tool_calls": local_trace, "found": len(items)})
        return items

    with ThreadPoolExecutor(max_workers=min(4, len(groups) or 1)) as ex:
        return [it for part in ex.map(run, groups) for it in part if isinstance(it, dict)]


def check_event(provider, ev, trace):
    prompt = (f"Verify this event:\n{json.dumps({k: ev.get(k) for k in ('name', 'venue', 'city', 'date', 'start_time')})}\n"
              f"It was first reported at: {', '.join(ev.get('source_urls') or [])}. "
              f"Find a DIFFERENT source if you can.")
    try:
        text, srcs = provider.research(CHECK_SYSTEM, prompt, [])
        verdict = extract_json(text)
        if not isinstance(verdict, dict) or "verdict" not in verdict:
            raise ValueError("unparseable verdict")
    except Exception as e:
        trace.append({"step": "check", "event": ev.get("name"), "error": str(e)})
        return {"verdict": "unavailable", "reason": str(e)[:200]}
    trace.append({"step": "check", "event": ev.get("name"), "provider": provider.name,
                  "verdict": verdict["verdict"], "reason": verdict.get("reason", "")})
    return verdict


# ---------- harness (plain rules, no AI) ----------

def _parse_time(s):
    try:
        return datetime.strptime(str(s), "%H:%M").strftime("%H:%M")
    except ValueError:
        return None


def validate(ev, venues, start: date, end: date, verdict=None):
    """Return (status, reasons, cleaned_event). status: accepted | flagged | rejected."""
    reasons, ev = [], dict(ev)
    try:
        d = date.fromisoformat(str(ev.get("date")))
    except ValueError:
        return "rejected", ["date missing or not YYYY-MM-DD"], ev
    if not (start <= d <= end):
        return "rejected", [f"date {d} outside {start}..{end}"], ev

    urls = [u for u in (ev.get("source_urls") or []) if isinstance(u, str) and u.startswith("http")]
    if not urls:
        return "rejected", ["no source link"], ev
    ev["source_urls"] = urls

    if ev.get("category") == "disruption":
        ev["kind"] = "advisory"
    else:
        ev["kind"] = "event"
        v = match_venue(ev.get("venue", ""), venues)
        if v is None:
            return "rejected", [f"venue '{ev.get('venue')}' not in venue table"], ev
        ev["venue_id"], ev["station"] = v["venue"], v.get("nearest_station", "")
        t = _parse_time(ev.get("start_time"))
        if t is None:
            return "rejected", ["start time missing or not HH:MM"], ev
        ev["start_time"] = t
        cap, att = v["capacity_n"], ev.get("expected_attendance")
        if isinstance(att, (int, float)) and cap and att > cap:
            ev["expected_attendance"] = cap
            reasons.append(f"attendance capped at venue capacity {cap}")

    if ev.get("official"):
        return "accepted", reasons + ["official schedule"], ev
    verdict = verdict or {"verdict": "unavailable"}
    ev["check"] = verdict
    if verdict["verdict"] == "confirmed":
        return "accepted", reasons + ["confirmed by independent check"], ev
    if verdict["verdict"] == "disputed":
        return "rejected", reasons + [f"checker disagrees: {verdict.get('reason', '')}"], ev
    return "flagged", reasons + [f"not independently confirmed ({verdict['verdict']})"], ev


def dedupe(events):
    merged = {}
    for ev in events:
        key = (_norm(ev.get("venue", "")), ev.get("date"), (ev.get("start_time") or "")[:2], ev.get("category") == "disruption")
        if key in merged:
            old = merged[key]
            old["source_urls"] = sorted(set(old.get("source_urls", [])) | set(ev.get("source_urls", [])))
            old["official"] = old.get("official") or ev.get("official")
        else:
            merged[key] = dict(ev)
    return list(merged.values())


# ---------- orchestration ----------

def run(start: date, providers: list, venues: list[dict], use_mlb=True, extra_queries=None, check=True):
    trace, raw = [], []
    if use_mlb:
        games = sources.mlb_home_games(start, start + timedelta(days=6))
        for g in games:
            if "_error" in g:
                trace.append({"step": "mlb", "error": g["_error"]})
            else:
                raw.append(g)
        trace.append({"step": "mlb", "games": len([g for g in games if "_error" not in g])})
    end = start + timedelta(days=6)
    finder = providers[0]
    queries = plan_queries(start, end, venues) + (extra_queries or [])
    raw += find_events(finder, queries, start, end, trace)
    raw = dedupe(raw)

    # independent checker: the other provider when we have two, else the same one
    checker = providers[1] if len(providers) > 1 else providers[0]
    result = {"accepted": [], "flagged": [], "rejected": []}
    for ev in raw:
        verdict = None
        if check and not ev.get("official"):
            verdict = check_event(checker, ev, trace)
        status, reasons, clean = validate(ev, venues, start, end, verdict)
        clean["reasons"] = reasons
        clean.pop("_grounding", None)
        result[status].append(clean)
    return {"week_start": str(start), "week_end": str(end), "finder": finder.name,
            "checker": checker.name, "counts": {k: len(v) for k, v in result.items()},
            **result, "trace": trace}
