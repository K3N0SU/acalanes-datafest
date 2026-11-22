"""
The reasoning harness: turns "there is an event that day" into an hour-by-hour station forecast.

Layers, in order:
  1. Day model      trained model gives the ordinary crowd for that day, weather included
                    (bart_forecast.Forecaster). Handles weekdays, seasons, tourism, rain.
  2. Planner (AI)   Gemini reasons about the one-off event: who comes, how many take BART
                    compared with the venues we have measured, when they arrive, when it ends,
                    what the weather does to turnout. It returns a plan with its reasons.
  3. Critic (AI)    a second, separate pass challenges the plan against the measured numbers.
  4. Rules (code)   bounds on every parameter. The plan can only scale and reshape curves that
                    were measured on real games; it cannot invent riders. Every clamp is logged.
  5. Narrator (AI)  writes the rider-facing summary from the final numbers. It gets the numbers,
                    it does not make them.

Events come in from outside (the search agent's public/data/events.json, or --event).

Which model does what, set by the keys in .env (GEMINI_API_KEY is always needed):
  planner and critic  Claude when ANTHROPIC_API_KEY is set, otherwise Gemini
  narrator            DeepSeek when DEEPSEEK_API_KEY is set, otherwise Gemini
  web search          Gemini (scripts/event_agent.py)
With --no-llm it runs layers 1 and 4 only, using the measured curve as is. That is also the
comparison in the test.

Run:
  python scripts/harness.py 2026-11-28
  python scripts/harness.py 2027-03-14 --event '{"name":"Stadium concert","venue":"Oracle Park","start_time":"19:00","attendance":40000,"type":"concert"}'
  python scripts/harness.py --test football      # events of a kind we have no measured curve for
"""

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from event_agent import API, load_env, load_venues, match_venue, parse_time, pick_model

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public" / "data"
DAYS = OUT / "days"
CACHE = ROOT / "data" / "cache" / "llm"

# hard limits the plan cannot leave
BOUNDS = {"multiplier": (0.3, 3.0), "turnout": (0.6, 1.1), "max_bart_share": 0.45,
          "arrival_offsets": (-6, 1), "departure_offsets": (-1, 3), "service_hours": (5, 23)}
DEFAULT_HOURS = {"baseball": 2.9, "football": 3.4, "concert": 3.5, "basketball": 2.4, "hockey": 2.6, "festival": 6.0, "convention": 8.0}
LEVELS = [(0.8, "packed"), (0.55, "busy"), (0.3, "steady"), (0.0, "quiet")]
WALK = {"Oracle Park": "15 minute walk from Embarcadero, or a Muni transfer; very little parking",
        "Oakland Coliseum": "footbridge straight from the station; very large parking lot",
        "Oakland Arena": "footbridge straight from the station; very large parking lot",
        "California Memorial Stadium": "20 to 25 minute uphill walk from Downtown Berkeley; almost no parking; many students walk",
        "Chase Center": "not on BART; riders transfer to Muni at Embarcadero or Powell; some parking",
        "Greek Theatre": "20 minute uphill walk from Downtown Berkeley; almost no parking",
        "Fox Theater": "one block from 19th St; some garages", "Paramount Theatre": "one block from 19th St; some garages",
        "Bill Graham Civic Auditorium": "across the plaza from Civic Center; some garages"}


# ------------------------------------------------------------------ measured curves

def measured():
    """summaries of uplift.json in the shape the planner and the rules use"""
    up = json.loads((OUT / "uplift.json").read_text(encoding="utf-8"))
    out = {}
    for key, u in up.items():
        arr = {o: max(v, 0) for o, v in zip(u["offsets"], u["exits_per_1000"]) if -4 <= o <= 0}
        dep = {o: max(v, 0) for o, v in zip(u["offsets"], u["entries_per_1000"]) if 2 <= o <= 7}
        a, d = sum(arr.values()), sum(dep.values())
        out[key] = {"games": u["games"], "arrive_share": a / 1000, "leave_share": d / 1000,
                    "arrival_profile": {o: v / a for o, v in arr.items()} if a else {},
                    # baseball ends about 3 hours after the start hour: re-express departures relative to the end
                    "departure_profile": {o - 3: v / d for o, v in dep.items()} if d else {}}
    return out


def rain_facts():
    try:
        bt = json.loads((OUT / "backtest.json").read_text(encoding="utf-8"))
        return bt.get("rain_effect_2025", {})
    except Exception:
        return {}


# ------------------------------------------------------------------ LLM plumbing

class LLM:
    """
    Routes each kind of call to a provider, by which keys are in .env:
      reason (lead, or planner and critic)  -> Claude if ANTHROPIC_API_KEY is set, otherwise Gemini
      worker (the three specialists)        -> DeepSeek if DEEPSEEK_API_KEY is set
      write  (narrator)                     -> DeepSeek if DEEPSEEK_API_KEY is set, otherwise Gemini
    Web search stays with Gemini (scripts/event_agent.py).
    Every answer is cached on disk by provider, model and prompt.
    """

    def __init__(self, enabled=True):
        self.enabled = enabled
        self.calls = self.cached = 0
        self.used = {}
        self.model = None
        if not enabled:
            return
        self.key = load_env()  # also loads .env into the environment for the other providers
        self.gemini_model = pick_model(self.key)
        CACHE.mkdir(parents=True, exist_ok=True)
        import os
        import claude_client
        self.claude = claude_client if claude_client.available() else None
        self.deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
        self.deepseek_model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
        self.routes = {
            "reason": ("claude", self.claude.MODEL) if self.claude else ("gemini", self.gemini_model),
            "write": ("deepseek", self.deepseek_model) if self.deepseek_key else ("gemini", self.gemini_model),
            "worker": ("deepseek", self.deepseek_model) if self.deepseek_key else ("gemini", self.gemini_model),
        }
        self.delegate = bool(self.deepseek_key)
        self.model = ", ".join(f"{role}: {m}" for role, (_, m) in self.routes.items())

    def _gemini(self, prompt, temperature):
        r = None
        think = {"includeThoughts": True}
        for attempt in range(6):
            cfg = {"temperature": temperature, "responseMimeType": "application/json"}
            if think:
                cfg["thinkingConfig"] = think
            body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": cfg}
            try:
                r = requests.post(f"{API}/models/{self.gemini_model}:generateContent", headers={"x-goog-api-key": self.key}, json=body, timeout=180)
            except requests.RequestException:  # dropped connection: try again
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code == 200:
                break
            if r.status_code == 400 and think:
                think = None  # this model does not take the thinking setting
                continue
            if r.status_code in (429, 500, 503):
                time.sleep(10 * (attempt + 1))
                continue
            raise SystemExit(f"Gemini error {r.status_code}: {r.text[:300]}")
        else:
            raise SystemExit("Gemini kept failing" + (f": {r.status_code} {r.text[:200]}" if r is not None else ": network errors"))
        parts = (r.json().get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        return ("".join(x.get("text", "") for x in parts if not x.get("thought")),
                " ".join(x.get("text", "") for x in parts if x.get("thought")))

    def _deepseek(self, prompt, temperature):
        body = {"model": self.deepseek_model, "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature, "response_format": {"type": "json_object"}}
        for attempt in range(5):
            try:
                r = requests.post("https://api.deepseek.com/chat/completions", headers={"Authorization": f"Bearer {self.deepseek_key}"}, json=body, timeout=240)
            except requests.RequestException:  # dropped connection: try again
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code == 200:
                msg = r.json()["choices"][0]["message"]
                return msg["content"], (msg.get("reasoning_content") or "")
            if r.status_code in (429, 500, 503):
                time.sleep(8 * (attempt + 1))
                continue
            raise SystemExit(f"DeepSeek error {r.status_code}: {r.text[:300]}")
        raise SystemExit("DeepSeek kept failing")

    def json(self, prompt, temperature=0.2, role="reason"):
        provider, model = self.routes[role]
        tag = hashlib.sha1(f"{provider}|{model}|{prompt}".encode("utf-8")).hexdigest()[:20]
        path = CACHE / f"{tag}.json"
        if path.exists():
            self.cached += 1
            self.used[role] = model
            return json.loads(path.read_text(encoding="utf-8"))
        if provider == "claude":
            text, model, reasoning = self.claude.ask(prompt)
        elif provider == "deepseek":
            text, reasoning = self._deepseek(prompt, temperature)
        else:
            text, reasoning = self._gemini(prompt, temperature)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            a, b = text.find("{"), text.rfind("}")
            data = json.loads(text[a:b + 1]) if a != -1 and b > a else {}
        if isinstance(data, dict) and reasoning:
            data["_reasoning"] = reasoning.strip()[:2500]   # the model's own summary of how it got there, kept with the answer
            data["_model"] = model
        self.calls += 1
        self.used[role] = model
        path.write_text(json.dumps(data), encoding="utf-8")
        return data


# ------------------------------------------------------------------ layers 2 and 3

def facts_block(m, rain):
    lines = ["MEASURED ON REAL GAMES (BART fare gates, extra riders at the venue's station against an ordinary day):"]
    names = {"EMBR": "Oracle Park -> Embarcadero station (15 min walk, little parking, Muni and ferries compete)",
             "COLS": "Oakland Coliseum -> Coliseum station (footbridge at the door, very large parking lot)",
             "GENERIC": "both ballparks pooled"}
    names["DBRK"] = "California Memorial Stadium -> Downtown Berkeley station (college football; 20 to 25 min uphill walk, students walk)"
    for key in ("EMBR_night", "EMBR_day", "COLS_night", "COLS_day", "DBRK_night", "DBRK_day", "GENERIC_night", "GENERIC_day"):
        if key not in m:
            continue
        st, part = key.split("_")
        u = m[key]
        prof = ", ".join(f"{o:+d}h {v:.0%}" for o, v in sorted(u["arrival_profile"].items()))
        dep = ", ".join(f"{o:+d}h {v:.0%}" for o, v in sorted(u["departure_profile"].items()))
        lines.append(f"- reference \"{st}\" {part} games ({u['games']} games): {names[st]}. "
                     f"{u['arrive_share']:.1%} of the crowd arrives through that station, {u['leave_share']:.1%} leaves through it. "
                     f"Arrivals by hour relative to the start hour: {prof}. Departures by hour relative to the end hour: {dep}.")
    if rain:
        lines.append("MEASURED EFFECT OF RAIN ON ORDINARY RIDERSHIP (2025, real riders against a dry-day forecast):")
        for band, g in rain.items():
            parts = [f"{k}: {v['actually_happened']:+.1%}" for k, v in g.items() if isinstance(v, dict)]
            lines.append(f"- {band}: " + "; ".join(parts))
        lines.append("The day model already applies this to ordinary riders. You only judge what the weather does to THIS event's turnout.")
    return "\n".join(lines)


def evidence_block(event):
    """sourced claims about how big this crowd will be, from the search agent (only claims whose source it retrieved)"""
    d = event.get("demand") or {}
    ev = d.get("evidence") or []
    if not ev:
        return "Sourced evidence on crowd size: none found. Treat the attendance figure as a default, and say so in risks.\n"
    lines = [f"Sourced evidence on crowd size (demand rated {d.get('demand')}):"]
    lines += [f"  - {c['claim']} [{c.get('source_url')}]" for c in ev[:6]]
    if d.get("compared_with_the_others"):
        lines.append(f"  Against the other events that week: {d['compared_with_the_others']}")
    return "\n".join(lines) + "\n"


def describe(event, venue, weather_note, base_hours):
    return (f"EVENT: {event.get('name')} ({event.get('type', 'unknown type')})\n"
            f"Venue: {venue['venue']}, capacity {venue['capacity']:,}. Nearest BART station: {venue['station']}. "
            f"Access: {WALK.get(venue['venue'], 'no notes')}.\n"
            f"Date: {event['date']} ({pd.Timestamp(event['date']).day_name()}). Start: {event['start_time']}. "
            f"Expected attendance: {event.get('attendance') or 'unknown'} ({event.get('attendance_basis', 'given')}).\n"
            f"Other details: {event.get('details', 'none')}\n"
            f"{evidence_block(event)}"
            f"Weather at the venue that day: {weather_note}\n"
            f"Ordinary riders through {venue['station']} that day by hour (entries + exits), from the day model: "
            + ", ".join(f"{h}:00 {int(v)}" for h, v in base_hours.items()))


PLAN_SCHEMA = """{
  "audience": "who comes, in one or two sentences: age, local or from out of town, how they usually travel",
  "expected_attendance": integer,
  "attendance_reason": str,
  "reference": "EMBR" | "COLS" | "DBRK" | "GENERIC",  // a measured venue listed above whose access is most like this one
  "reference_reason": str,
  "multiplier": number,                                // BART share against that reference: 1.0 = same share of the crowd uses this station
  "multiplier_reasons": [str, ...],                    // one reason per factor: parking, walk, crowd type, competing transit, time of day
  "arrival_profile": {"-4": n, "-3": n, "-2": n, "-1": n, "0": n, "1": n},   // share of BART arrivals by hour relative to the start hour, sums to 1
  "arrival_reason": str,
  "end_time": "HH:MM",                                 // when most people leave, 24-hour local time
  "end_reason": str,
  "departure_profile": {"-1": n, "0": n, "1": n, "2": n},                    // share of BART departures by hour relative to the end hour, sums to 1
  "departure_reason": str,
  "weather_turnout": number,                           // 1.0 = weather changes nothing for this event
  "weather_reason": str,
  "other_stations": [{"station": str, "why": str}],    // where else riders will notice it; words only, no numbers
  "risks": [str, ...],                                 // what could make this wrong
  "confidence": "low" | "medium" | "high"
}"""


def plan_event(llm, event, venue, m, rain, weather_note, base_hours):
    prompt = f"""You are the planning layer of a transit crowd forecast for BART (San Francisco Bay Area rail).
A statistical model already forecasts the ordinary crowd. Your job is the exception: one event that the model cannot know about.
You do not output rider counts. You output a plan that scales and reshapes curves measured on real games. Code applies it.

{facts_block(m, rain)}

{describe(event, venue, weather_note, base_hours)}

Reason step by step about this specific event, then answer with ONLY a JSON object of this shape:
{PLAN_SCHEMA}

Rules you must respect, because code enforces them: multiplier between {BOUNDS['multiplier'][0]} and {BOUNDS['multiplier'][1]};
weather_turnout between {BOUNDS['turnout'][0]} and {BOUNDS['turnout'][1]}; BART trains run about 5:00 to midnight, so anyone leaving after
midnight cannot use BART; attendance cannot exceed capacity. Excluding flights: assume visitors are already in the Bay Area.
Be specific to this event and this venue. If you are unsure, say so in risks and lower your confidence."""
    return llm.json(prompt)


def critique(llm, event, venue, plan, m, rain, weather_note, base_hours):
    prompt = f"""You are the reviewer in a transit crowd forecast. Another analyst wrote the plan below for one event.
Challenge it against the measured facts. Look for: a multiplier with no real justification, arrivals that ignore doors or tailgating,
an end time that is too early or too late for this kind of event, departures after BART's last trains (about midnight),
attendance above what the venue or the act can draw, weather ignored for an outdoor event or over-weighted for an indoor one.

{facts_block(m, rain)}

{describe(event, venue, weather_note, base_hours)}

PLAN UNDER REVIEW:
{json.dumps(plan, indent=1)}

Answer with ONLY a JSON object:
{{"verdict": "accept" | "revise", "issues": [str, ...],
  "revised": {{ only the plan fields you would change, with the same names and shapes }},
  "why": str}}
Only revise when you can name the specific fact that the plan gets wrong."""
    return llm.json(prompt, temperature=0.1)


# ------------------------------------------------------------------ delegation: three specialists, one lead

SPECIALISTS = {
    "crowd": ("Who comes and how many. Judge the audience (age, local or visiting, how they usually travel), the realistic attendance, "
              "and what the weather does to turnout for THIS event (outdoor or indoor).",
              """{"audience": str, "expected_attendance": integer, "attendance_reason": str,
 "weather_turnout": number between 0.6 and 1.1 (1.0 = no effect), "weather_reason": str, "risks": [str]}"""),
    "access": ("How this crowd gets to this venue. Pick the measured venue whose access is most like it, then say how much larger or "
               "smaller the BART share should be, one reason per factor: parking, walking distance, crowd type, competing transit, time of day.",
               """{"reference": one of the measured references listed above ("EMBR", "COLS", "DBRK" if listed, "GENERIC"), "reference_reason": str,
 "multiplier": number between 0.3 and 3.0 (1.0 = same share as the reference), "multiplier_reasons": [str],
 "other_stations": [{"station": str, "why": str}], "risks": [str]}"""),
    "timing": ("When people arrive and leave. Think about doors, openers, tailgating, how long this kind of event runs, and BART's last trains (about midnight).",
               """{"arrival_profile": {"-4": n, "-3": n, "-2": n, "-1": n, "0": n, "1": n}  (share of BART arrivals by hour relative to the start hour, sums to 1),
 "arrival_reason": str, "end_time": "HH:MM" 24-hour, "end_reason": str,
 "departure_profile": {"-1": n, "0": n, "1": n, "2": n}  (share of BART departures by hour relative to the end hour, sums to 1),
 "departure_reason": str, "risks": [str]}"""),
}


def delegate_plan(llm, event, venue, m, rain, weather_note, base_hours):
    """three specialists answer one narrow question each, in parallel; the lead checks them and writes the plan"""
    from concurrent.futures import ThreadPoolExecutor
    facts, desc = facts_block(m, rain), describe(event, venue, weather_note, base_hours)

    def ask(name):
        job, schema = SPECIALISTS[name]
        prompt = (f"You are one specialist on a transit crowd forecast for BART (San Francisco Bay Area rail). Your one job: {job}\n"
                  f"You do not output rider counts. Stay inside your job. Be specific to this event.\n\n{facts}\n\n{desc}\n\n"
                  f"Answer with ONLY a JSON object of this shape:\n{schema}")
        return name, llm.json(prompt, temperature=0.2, role="worker")

    with ThreadPoolExecutor(max_workers=3) as pool:
        reports = dict(pool.map(ask, SPECIALISTS))

    lead = f"""You lead a transit crowd forecast for BART. Three specialists each answered one part of the question for the event below.
Check every claim against the measured facts and against each other. Keep what holds, correct what does not, and write the final plan.
You do not output rider counts: code applies your plan to curves measured on real games, within fixed limits
(multiplier {BOUNDS['multiplier'][0]} to {BOUNDS['multiplier'][1]}, weather_turnout {BOUNDS['turnout'][0]} to {BOUNDS['turnout'][1]}, no riders after midnight, attendance never above capacity).

{facts}

{desc}

SPECIALIST REPORTS:
{json.dumps(reports, indent=1)}

Answer with ONLY a JSON object: the final plan in this shape,
{PLAN_SCHEMA}
plus one more field:
"overrides": [{{"field": str, "specialist_said": str, "you_set": str, "why": str}}]   // empty if you changed nothing"""
    plan = llm.json(lead, role="reason")
    overrides = plan.get("overrides") or []
    review = {"verdict": "revise" if overrides else "accept",
              "issues": [f"{o.get('field')}: {o.get('why')}" for o in overrides if isinstance(o, dict)],
              "by": "lead, after reading three specialist reports"}
    return plan, review, {"specialists": reports, "overrides": overrides}


def make_plan(llm, event, venue, m, rain, weather_note, base_hours, log):
    """delegated when the worker model is available, otherwise planner then critic"""
    if llm.delegate:
        return delegate_plan(llm, event, venue, m, rain, weather_note, base_hours)
    plan = plan_event(llm, event, venue, m, rain, weather_note, base_hours)
    review = critique(llm, event, venue, plan, m, rain, weather_note, base_hours)
    return merge_revision(plan, review, log), review, None


# ------------------------------------------------------------------ layer 4: rules

def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def clean_profile(raw, lo, hi, fallback, log, name):
    prof = {}
    try:
        for k, v in (raw or {}).items():
            o = int(str(k).replace("+", ""))
            if lo <= o <= hi and float(v) > 0:
                prof[o] = float(v)
    except (TypeError, ValueError):
        prof = {}
    if not prof:
        if raw:
            log.append(f"{name}: plan gave nothing usable, measured profile used")
        prof = {o: v for o, v in fallback.items() if lo <= o <= hi} or {0: 1.0}
    total = sum(prof.values())
    return {o: v / total for o, v in prof.items()}


def apply_plan(event, venue, plan, m):
    """turn a plan into riders per hour at the venue station. returns exits_add[24], entries_add[24], details"""
    log = []
    part = "day" if event["start_hour"] < 16 else "night"
    ref = str((plan or {}).get("reference") or venue["curve"]).upper()
    if f"{ref}_{part}" not in m:
        log.append(f"reference '{ref}' is not a measured curve, pooled curve used")
        ref = "GENERIC"
    u = m[f"{ref}_{part}"]

    mult = (plan or {}).get("multiplier", 1.0)
    try:
        mult = float(mult)
    except (TypeError, ValueError):
        mult = 1.0
    cm = clamp(mult, *BOUNDS["multiplier"])
    if cm != mult:
        log.append(f"multiplier {mult} outside limits, set to {cm}")
    turnout = (plan or {}).get("weather_turnout", 1.0)
    try:
        turnout = float(turnout)
    except (TypeError, ValueError):
        turnout = 1.0
    ct = clamp(turnout, *BOUNDS["turnout"])
    if ct != turnout:
        log.append(f"weather turnout {turnout} outside limits, set to {ct}")

    att = event.get("attendance") or (plan or {}).get("expected_attendance") or int(venue["capacity"] * 0.75)
    att = int(att)
    if att > venue["capacity"]:
        log.append(f"attendance {att:,} above capacity, capped at {venue['capacity']:,}")
        att = venue["capacity"]

    arrive = att * ct * u["arrive_share"] * cm
    leave = att * ct * u["leave_share"] * cm
    cap = att * BOUNDS["max_bart_share"]
    if arrive > cap:
        log.append(f"arrivals {arrive:,.0f} above {BOUNDS['max_bart_share']:.0%} of the crowd, capped")
        arrive = cap
    if leave > cap:
        leave = cap

    h0 = int(math.floor(event["start_hour"]))
    end = parse_time((plan or {}).get("end_time") or "")
    default_end = event["start_hour"] + DEFAULT_HOURS.get(str(event.get("type", "")).lower(), 3.0)
    if end is None:
        end = default_end
    elif end < event["start_hour"]:  # past midnight
        end += 24
    if not (event["start_hour"] + 0.75 <= end <= event["start_hour"] + 12):
        log.append("end time not believable, default length for this kind of event used")
        end = default_end
    hend = int(math.floor(end))

    a_prof = clean_profile((plan or {}).get("arrival_profile"), *BOUNDS["arrival_offsets"], u["arrival_profile"], log, "arrival profile")
    d_prof = clean_profile((plan or {}).get("departure_profile"), *BOUNDS["departure_offsets"], u["departure_profile"], log, "departure profile")

    lo, hi = BOUNDS["service_hours"]
    exits, entries, stranded, late = [0.0] * 24, [0.0] * 24, 0.0, 0.0
    for o, share in a_prof.items():
        h = h0 + o
        if lo <= h <= hi:
            exits[h] += arrive * share
    for o, share in d_prof.items():
        h = hend + o
        if lo <= h <= hi:
            entries[h] += leave * share
        elif h == 24:
            # measured on 2025 trips: BART carries the midnight hour (31% of arena concert riders leave then). counted, not charted
            late += leave * share
        else:
            stranded += leave * share
    if late > 1:
        log.append(f"about {late:,.0f} riders leave in the midnight hour, on the last trains; counted in the total, not on the hourly chart")
    if stranded > 1:
        log.append(f"about {stranded:,.0f} riders would be leaving after 1 AM, when the last trains have gone; not counted, flagged")
    return exits, entries, {"reference": f"{ref} {part} games ({u['games']} measured)", "multiplier": round(cm, 2), "turnout": round(ct, 2),
                            "attendance": att, "bart_arrivals": round(arrive), "bart_departures": round(leave - stranded),
                            "after_last_train": round(stranded), "end_hour": round(end % 24, 2), "log": log}


def merge_revision(plan, review, log):
    revised = (review or {}).get("revised") or {}
    if (review or {}).get("verdict") == "revise" and isinstance(revised, dict):
        for k, v in revised.items():
            if k in plan and v not in (None, "", {}, []):
                plan[k] = v
                log.append(f"reviewer changed {k}")
    return plan


# ------------------------------------------------------------------ disruptions and city-wide events

UNMEASURED_LIMIT = 0.15   # with no measured past example, a disruption may move riders by at most 15%
MARGIN = 0.10             # how far past the measured range a factor may go


def analogue_library():
    path = OUT / "analogues.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"by_type": {}, "days": []}


def plan_disruptions(llm, date, items, station_names, weather_note):
    lib = analogue_library()
    measured_days = [f"  - {d['date']}: {d['actual_vs_forecast']:+.0%} system-wide, {d['type']}: {d['cause']}" for d in lib["days"] if d.get("verified")]
    prompt = f"""You plan how city-wide disruptions change BART ridership on {date} ({pd.Timestamp(date).day_name()}).
A statistical model already forecasts the ordinary day, weather included. You only handle the items below, which a search agent found
and which each cite a page it retrieved.

MEASURED PAST EXCEPTIONS (real riders against the forecast on that day in 2025; the only evidence of size you may lean on):
{chr(10).join(measured_days) or "  none available"}
Measured range by type: {json.dumps(lib["by_type"])}

Weather that day: {weather_note}
BART stations (code: name): {json.dumps(station_names)}

ITEMS FOR THIS DAY:
{json.dumps(items, indent=1)}

For each item decide whether it will move ridership enough to matter, where, when, and by how much, as a factor on the ordinary forecast
(0.6 = 40% fewer riders, 1.3 = 30% more). Pick the measured type it most resembles; if none fits, say "none" and stay within 0.85 to 1.15.
A factor outside the measured range for its type will be cut back by code.
Return ONLY a JSON object: {{"items": [{{"name": str, "applies": true | false, "scope": "system" or [station codes],
"from_hour": 0-23, "to_hour": 1-24, "analogue_type": str, "factor": number, "reason": str, "confidence": "low" | "medium" | "high"}}]}}"""
    return llm.json(prompt, role="reason"), lib


def apply_disruptions(plan, lib, items, stations, base):
    """returns per-station rider change by hour, and what was applied"""
    delta, applied = {}, []
    by_name = {i.get("name"): i for i in items}
    for it in (plan or {}).get("items", []):
        if not isinstance(it, dict) or not it.get("applies"):
            continue
        log = []
        try:
            f = float(it.get("factor", 1.0))
        except (TypeError, ValueError):
            continue
        rng = lib["by_type"].get(it.get("analogue_type"))
        if rng:
            lo, hi = 1 + min(rng["min"], 0) - MARGIN, 1 + max(rng["max"], 0) + MARGIN
            basis = f"{rng['days']} measured day(s) of type '{it['analogue_type']}' ({rng['min']:+.0%} to {rng['max']:+.0%})"
        else:
            lo, hi = 1 - UNMEASURED_LIMIT, 1 + UNMEASURED_LIMIT
            basis = "no measured past example: limited to 15% either way"
        cf = clamp(f, max(lo, 0.2), min(hi, 2.0))
        if cf != f:
            log.append(f"factor {f} outside what was measured, set to {round(cf, 2)}")
        scope = it.get("scope")
        codes = stations if scope == "system" or not isinstance(scope, list) else [x for x in scope if x in base]
        if not codes:
            continue
        try:
            h0, h1 = int(it.get("from_hour", 0)), int(it.get("to_hour", 24))
        except (TypeError, ValueError):
            h0, h1 = 0, 24
        h0, h1 = max(0, min(h0, 23)), max(1, min(h1, 24))
        for st in codes:
            d = delta.setdefault(st, np.zeros(24))
            d[h0:h1] += base[st][h0:h1] * (cf - 1)
        applied.append({"name": it.get("name"), "source_url": (by_name.get(it.get("name")) or {}).get("source_url"),
                        "type": (by_name.get(it.get("name")) or {}).get("type"), "scope": "system" if len(codes) == len(stations) else codes,
                        "hours": [h0, h1], "factor": round(cf, 2), "basis": basis, "reason": it.get("reason"),
                        "confidence": it.get("confidence"), "log": log})
    return delta, applied


# ------------------------------------------------------------------ layer 5: summary

def segments(total, typical_peak):
    segs = []
    for h in range(5, 24):
        r = total[h] / typical_peak if typical_peak else 0
        level = next(name for cut, name in LEVELS if r >= cut)
        if segs and segs[-1]["level"] == level:
            segs[-1]["to"] = h + 1
            segs[-1]["peak"] = max(segs[-1]["peak"], int(total[h]))
        else:
            segs.append({"from": h, "to": h + 1, "level": level, "peak": int(total[h])})
    return segs


def narrate(llm, station_name, date, segs, events, weather_note):
    if not llm.enabled:
        return None
    prompt = f"""Write for a BART rider checking {station_name} on {date} ({pd.Timestamp(date).day_name()}).
These crowd levels were computed from the forecast. Do not change them or add numbers that are not here.
Segments (hours in 24h time, 'peak' = people through the gates in the busiest hour of the segment): {json.dumps(segs)}
Events affecting this station: {json.dumps([{k: e.get(k) for k in ('name', 'venue', 'start_time', 'attendance')} for e in events])}
Weather: {weather_note}
Answer with ONLY JSON: {{"segments": [{{"from": int, "to": int, "why": "one short plain sentence on why this stretch is like this"}}],
"advice": "one or two sentences: when to travel and when to avoid, for someone not going to the event"}}
Plain words. No hype."""
    return llm.json(prompt, temperature=0.3, role="write")


# ------------------------------------------------------------------ one day

def weather_note_for(day, zone, start_hour=None):
    w = (day.get("weather") or {}).get(zone)
    if not w:
        return "no forecast available this far ahead; a dry day is assumed"
    note = f"{w['rain_mm']} mm of rain over the day, high of {w['tmax_c']} C, wind up to {w['wind_max_kmh']} km/h"
    if start_hour is not None:
        h = int(start_hour)
        around = sum(w["rain_by_hour"][max(h - 3, 0):min(h + 4, 24)])
        note += f"; {around:.1f} mm in the hours around the event"
    return note


def run_day(date, events, llm, forecaster, venues, m, rain, disruptions=None):
    c = forecaster.c
    day = forecaster.day(date)
    base = {s: (day["entries"][i] + day["exits"][i]) for i, s in enumerate(c.stations)}
    dry = {s: (day["dry_entries"][i] + day["dry_exits"][i]) for i, s in enumerate(c.stations)}
    add = {}
    out_events = []
    if llm.enabled and len(events) > 1:
        from concurrent.futures import ThreadPoolExecutor

        def warm(e):
            venue = match_venue(e.get("venue"), venues)
            t = e.get("start_hour") if e.get("start_hour") is not None else parse_time(e.get("start_time"))
            if not venue or t is None:
                return
            e = {**e, "date": str(pd.Timestamp(date).date()), "start_hour": t, "start_time": f"{int(t):02d}:{int(round((t % 1) * 60)):02d}"}
            st = venue["station"]
            make_plan(llm, e, venue, m, rain, weather_note_for(day, c.st_zone[c.sidx[st]], t), {h: base[st][h] for h in range(5, 24)}, [])

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(warm, events))
    for e in events:
        venue = match_venue(e.get("venue"), venues)
        if not venue:
            out_events.append({**e, "skipped": "venue is not in the venue table"})
            continue
        t = e.get("start_hour") if e.get("start_hour") is not None else parse_time(e.get("start_time"))
        if t is None:
            out_events.append({**e, "skipped": "start time could not be read"})
            continue
        e = {**e, "date": str(pd.Timestamp(date).date()), "start_hour": t, "start_time": f"{int(t):02d}:{int(round((t % 1) * 60)):02d}"}
        st = venue["station"]
        zone = c.st_zone[c.sidx[st]]
        wnote = weather_note_for(day, zone, t)
        base_hours = {h: base[st][h] for h in range(5, 24)}
        plan, review, delegation, hlog = None, None, None, []
        if llm.enabled:
            plan, review, delegation = make_plan(llm, e, venue, m, rain, wnote, base_hours, hlog)
        exits, entries, det = apply_plan(e, venue, plan, m)
        det["log"] = hlog + det["log"]
        a = add.setdefault(st, np.zeros(24))
        a += np.array(exits) + np.array(entries)
        tot = np.array(exits) + np.array(entries)
        pk = int(tot.argmax())
        out_events.append({**e, "venue": venue["venue"], "station": st, "plan": plan, "review": review, "delegation": delegation, "applied": det,
                           "peak_hour": pk, "normal_riders_peak": int(base[st][pk]), "added_riders_peak": int(tot[pk]),
                           "times_normal": round(float((base[st][pk] + tot[pk]) / base[st][pk]), 2) if base[st][pk] > 0 else None})

    ddelta, dapplied = {}, []
    if disruptions and llm.enabled:
        from bart_forecast import NAMES
        dplan, lib = plan_disruptions(llm, day["date"], disruptions, {s: NAMES.get(s, s) for s in c.stations}, weather_note_for(day, "oakland"))
        ddelta, dapplied = apply_disruptions(dplan, lib, disruptions, list(c.stations), base)

    stations = {}
    for i, s in enumerate(c.stations):
        total = np.maximum(base[s] + add.get(s, 0) + ddelta.get(s, 0), 0)
        stations[s] = {"baseline": base[s].round(0).astype(int).tolist(), "dry": dry[s].round(0).astype(int).tolist(),
                       "event_add": (np.round(add[s]).astype(int).tolist() if s in add else None),
                       "disruption_change": (np.round(ddelta[s]).astype(int).tolist() if s in ddelta else None),
                       "total": np.round(total).astype(int).tolist()}
    summaries = {}
    for s in add:
        i = c.sidx[s]
        # the station's usual busiest hour: median daily peak over the last 90 days of data, scaled to today
        typical_peak = float(np.median((c.Y[0, i, -90:, :] + c.Y[1, i, -90:, :]).max(axis=1))) * forecaster.scale[i]
        segs = segments(np.array(stations[s]["total"]), typical_peak)
        evs = [e for e in out_events if e.get("station") == s]
        text = narrate(llm, s, str(pd.Timestamp(date).date()), segs, evs, weather_note_for(day, c.st_zone[i]))
        summaries[s] = {"typical_peak": round(typical_peak), "segments": segs, "narration": text}
    return {"date": day["date"], "weekday": pd.Timestamp(date).day_name(), "reference_day": day["reference_day"],
            "weather": day["weather"], "weather_source": day["weather_source"], "events": out_events,
            "accessories": day.get("accessories", []), "holiday": day.get("holiday"),
            "disruptions": dapplied, "disruptions_found": disruptions or [],
            "stations": stations, "summaries": summaries,
            "ai": {"models": llm.used, "calls": llm.calls, "from_cache": llm.cached} if llm.enabled else None,
            "bounds": BOUNDS}


# ------------------------------------------------------------------ test on a kind of event with no measured curve

def test_football(llm, venues, m, rain):
    from bart_core import CLEAN, load, wape
    c = load()
    P = {y: np.load(CLEAN / f"pred_{y}.npy") for y in (2023, 2024, 2025)}
    year0 = {y: c.didx[pd.Timestamp(f"{y}-01-01")] for y in P}
    games = pd.read_csv(CLEAN / "games.csv", parse_dates=["date"])
    fb = games[games["sport"] == "football"].copy()
    fb["year"] = fb["date"].dt.year
    venue = {**match_venue("California Memorial Stadium", venues), "curve": "GENERIC"}
    m = {k: v for k, v in m.items() if not k.startswith("DBRK")}
    s = c.sidx["DBRK"]
    rows, A, B, G, H = [], [], [], [], []
    if llm.enabled:  # plan all games concurrently; answers are cached, the loop below reads them
        from concurrent.futures import ThreadPoolExecutor

        def warm(g):
            y, d = g["year"], c.didx[g["date"]]
            prior = fb[fb["year"] == y - 1]["attendance"].mean()
            e = {"name": f"Cal football vs {g['opponent']}", "type": "football", "venue": venue["venue"], "date": str(g["date"].date()),
                 "start_hour": float(g["start_hour"]), "start_time": f"{int(g['start_hour']):02d}:{int(round((g['start_hour'] % 1) * 60)):02d}",
                 "attendance": int(prior), "attendance_basis": "last season's average home crowd",
                 "details": "college football home game; students live within walking distance of the stadium"}
            pe, px = P[y][0, s, d - year0[y]], P[y][1, s, d - year0[y]]
            make_plan(llm, e, venue, m, rain, "weather not given in this test; assume it changes nothing", {h: float(pe[h] + px[h]) for h in range(5, 24)}, [])

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(warm, [g for _, g in fb[fb["year"].isin(P)].iterrows()]))
    for _, g in fb[fb["year"].isin(P)].iterrows():
        y, d = g["year"], c.didx[g["date"]]
        prior = fb[fb["year"] == y - 1]["attendance"].mean()  # attendance is not known ahead: last season's average
        e = {"name": f"Cal football vs {g['opponent']}", "type": "football", "venue": venue["venue"], "date": str(g["date"].date()),
             "start_hour": float(g["start_hour"]), "start_time": f"{int(g['start_hour']):02d}:{int(round((g['start_hour'] % 1) * 60)):02d}",
             "attendance": int(prior), "attendance_basis": "last season's average home crowd",
             "details": "college football home game; students live within walking distance of the stadium"}
        pe, px = P[y][0, s, d - year0[y]], P[y][1, s, d - year0[y]]
        base_hours = {h: float(pe[h] + px[h]) for h in range(5, 24)}
        gx, ge, _ = apply_plan(e, venue, None, m)  # measured curve as is, no reasoning
        if llm.enabled:
            plan, review, _ = make_plan(llm, e, venue, m, rain, "weather not given in this test; assume it changes nothing", base_hours, [])
            hx, he, det = apply_plan(e, venue, plan, m)
        else:
            plan, hx, he, det = None, gx, ge, {}
        h0 = int(g["start_hour"])
        hrs = [h for h in range(h0 - 5, h0 + 8) if 5 <= h <= 23]
        act = [c.Y[0, s, d, h] for h in hrs] + [c.Y[1, s, d, h] for h in hrs]
        base = [pe[h] for h in hrs] + [px[h] for h in hrs]
        gen = [pe[h] + ge[h] for h in hrs] + [px[h] + gx[h] for h in hrs]
        har = [pe[h] + he[h] for h in hrs] + [px[h] + hx[h] for h in hrs]
        A += act; B += base; G += gen; H += har
        rows.append({"date": e["date"], "opponent": g["opponent"], "start": e["start_time"], "real_attendance": int(g["attendance"]),
                     "riders_actual": int(sum(act)), "riders_model_alone": int(sum(base)), "riders_measured_curve": int(sum(gen)),
                     "riders_harness": int(sum(har)),
                     "err_model_alone": round(wape(base, act), 3), "err_measured_curve": round(wape(gen, act), 3), "err_harness": round(wape(har, act), 3),
                     "multiplier": det.get("multiplier"), "reference": det.get("reference"),
                     "why": (plan or {}).get("multiplier_reasons")})
        print(rows[-1]["date"], rows[-1]["opponent"][:22].ljust(22), "actual", rows[-1]["riders_actual"], "| alone", rows[-1]["riders_model_alone"],
              "| curve", rows[-1]["riders_measured_curve"], "| harness", rows[-1]["riders_harness"], "| x", det.get("multiplier"))
    summary = {"what": "Cal football home games at Memorial Stadium -> Downtown Berkeley, 2023 to 2025. No football was used to measure any curve.",
               "games": len(rows), "window": "5 hours before kickoff to 7 hours after",
               "err_model_alone": round(wape(B, A), 4), "err_measured_curve_no_reasoning": round(wape(G, A), 4),
               "err_harness": round(wape(H, A), 4) if llm.enabled else None,
               "ai_model": (llm.routes["reason"][1] if llm.enabled else None), "attendance_given": "last season's average, not the real gate"}
    (OUT / "harness_test.json").write_text(json.dumps({"summary": summary, "games": rows}, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


# ------------------------------------------------------------------ cli

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?")
    ap.add_argument("--event", action="append", default=[], help="JSON for one event; repeatable")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--test", choices=["football"])
    ap.add_argument("--week", action="store_true", help="run the 7 days starting at the given date")
    ap.add_argument("--days", type=int, default=0, help="run this many days starting at the given date")
    ap.add_argument("--events-file", help="read events and disruptions from this file (same shape as public/data/events.json)")
    a = ap.parse_args()

    llm = LLM(enabled=not a.no_llm)
    venues, m, rain = load_venues(), measured(), rain_facts()
    if a.test:
        return test_football(llm, venues, m, rain)
    if not a.date:
        sys.exit("give a date, e.g. 2026-11-28")

    events = [json.loads(x) for x in a.event]
    src = OUT / "events.json"
    if not events and src.exists():  # events found by the search agent
        events = [e for e in json.loads(src.read_text(encoding="utf-8")).get("events", []) if e.get("date") == a.date]
    from bart_forecast import NAMES, Forecaster
    f = Forecaster()
    if a.events_file:
        src = Path(a.events_file)
    found = json.loads(src.read_text(encoding="utf-8")) if src.exists() else {}
    a.week = a.week or a.days > 1
    dates = [str(d.date()) for d in pd.date_range(a.date, periods=a.days or (7 if a.week else 1), freq="D")]
    DAYS.mkdir(parents=True, exist_ok=True)
    for dt in dates[:-1] if a.week else []:   # all days but the last; the last one falls through to the code below
        ev = [e for e in found.get("events", []) if e.get("date") == dt]
        dis = [x for x in found.get("disruptions", []) if dt in (x.get("dates") or [])]
        d_ = run_day(dt, ev, llm, f, venues, m, rain, dis)
        for s_ in d_["stations"]:
            d_["stations"][s_]["name"] = NAMES.get(s_, s_)
        (DAYS / f"{dt}.json").write_text(json.dumps(d_, separators=(",", ":")), encoding="utf-8")
        print(f"{dt}: {len(d_['events'])} events, {len(d_['disruptions'])} disruptions applied, {len(d_['accessories'])} accessories", flush=True)
    a.date = dates[-1]
    if a.week or not events:
        events = [e for e in found.get("events", []) if e.get("date") == a.date]
    disruptions = [x for x in found.get("disruptions", []) if a.date in (x.get("dates") or [])]
    day = run_day(a.date, events, llm, f, venues, m, rain, disruptions)
    for s in day["stations"]:
        day["stations"][s]["name"] = NAMES.get(s, s)
    DAYS.mkdir(parents=True, exist_ok=True)
    (DAYS / f"{a.date}.json").write_text(json.dumps(day, separators=(",", ":")), encoding="utf-8")
    index = sorted(p.stem for p in DAYS.glob("20*.json"))
    (DAYS / "index.json").write_text(json.dumps(index), encoding="utf-8")
    print(f"wrote public/data/days/{a.date}.json | reference day {day['reference_day']} | weather: {day['weather_source']}")
    for x in day["disruptions"]:
        print(f"  disruption: {x['name']} -> x{x['factor']} on {x['scope'] if x['scope'] == 'system' else len(x['scope'])} "
              f"{'' if x['scope'] == 'system' else 'stations '}hours {x['hours']} | {x['basis']}")
    for e in day["events"]:
        if e.get("skipped"):
            print("  skipped:", e.get("name"), "|", e["skipped"]); continue
        ap_ = e["applied"]
        print(f"  {e['name']} @ {e['venue']} {e['start_time']} -> {e['station']}: x{ap_['multiplier']} of {ap_['reference']}, "
              f"{ap_['bart_arrivals']:,} arrive / {ap_['bart_departures']:,} leave by BART; peak {e['peak_hour']}:00 = {e['times_normal']}x normal")
        for line in ap_["log"]:
            print("     rule:", line)


if __name__ == "__main__":
    main()
