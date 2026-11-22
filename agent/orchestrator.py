"""Three-model event research.

  Claude Opus 5.5 (orchestrator, capped budget)  plans the search, decides what to trust, submits events
    ├─ gemini_search   -> Gemini + Google Search grounding (capped budget): finds facts on the web
    ├─ deepseek_reason -> DeepSeek, multi-pass reasoning on raw inputs (unlimited budget)
    ├─ mlb_schedule    -> official MLB API, no AI
    └─ submit_events   -> final structured list, then the plain-code harness validates it

The AI never outputs a ridership number. Numbers come from the trained model and the measured uplift.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta

import anthropic

from . import pipeline, sources
from .budget import BudgetExceeded, Ledger

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
CLAUDE_EFFORT = os.environ.get("CLAUDE_EFFORT", "high")
MAX_TOKENS = 16000
MAX_ROUNDS = 25

EVENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "venue", "date", "start_time", "expected_attendance", "category", "source_urls", "notes"],
    "properties": {
        "name": {"type": "string"},
        "venue": {"type": "string"},
        "date": {"type": "string", "description": "YYYY-MM-DD"},
        "start_time": {"type": ["string", "null"], "description": "HH:MM 24h Pacific; null only for disruptions"},
        "expected_attendance": {"type": ["integer", "null"]},
        "category": {"type": "string", "enum": ["sports", "concert", "festival", "conference", "parade",
                                                 "protest", "holiday", "other", "disruption"]},
        "source_urls": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string", "description": "how it was confirmed, and anything uncertain"},
    },
}

TOOLS = [
    {
        "name": "gemini_search",
        "description": ("Search the live web through Gemini with Google Search. Returns an answer with source URLs. "
                        "Ask one focused question per call (a venue and a date range, or one event to confirm). "
                        "Costs from the Gemini token budget."),
        "input_schema": {"type": "object", "additionalProperties": False, "required": ["question"],
                         "properties": {"question": {"type": "string"}}},
        "strict": True,
    },
    {
        "name": "deepseek_reason",
        "description": ("Send raw, low-level material (page text, search answers, lists, tables, numbers) to DeepSeek for "
                        "deep multi-pass reasoning: it analyses, critiques its own analysis, then answers. Use it to "
                        "reconcile conflicting sources, deduplicate long event lists, check dates and times against each "
                        "other, or work through tedious detail. Unlimited budget, so hand it the bulky work."),
        "input_schema": {"type": "object", "additionalProperties": False, "required": ["task", "material", "passes"],
                         "properties": {
                             "task": {"type": "string", "description": "what to work out, and the answer format you want"},
                             "material": {"type": "string", "description": "the raw input to reason over"},
                             "passes": {"type": "integer", "description": "1 to 3; 3 = analyse, critique, final"}}},
        "strict": True,
    },
    {
        "name": "mlb_schedule",
        "description": "Official MLB home-game schedule for the Giants and A's in the forecast window. No AI, exact times.",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {}, "required": []},
        "strict": True,
    },
    {
        "name": "submit_events",
        "description": "Submit the final list of events and BART disruptions. Call once, at the end.",
        "input_schema": {"type": "object", "additionalProperties": False, "required": ["events"],
                         "properties": {"events": {"type": "array", "items": EVENT_SCHEMA}}},
        "strict": True,
    },
]


def system_prompt(start: date, end: date, venues: list[dict]) -> str:
    table = "\n".join(f"- {v['venue']} (capacity {v.get('capacity', '?')}, station {v.get('nearest_station', '?')})"
                      for v in venues) or "- (venue table missing; list venues you find but expect them rejected)"
    return f"""You run the event research for Rushcast, a BART crowding forecast.

Goal: find every public event and BART service disruption in the San Francisco Bay Area from {start} to {end}
that could noticeably change how many people enter or leave a BART station, then call submit_events.

Venues we can map to a station (events elsewhere will be rejected by the harness):
{table}

Also look for: conventions at Moscone Center, big concerts and festivals, parades, marathons, protests or marches,
Thanksgiving and holiday events, and BART strikes, track work or station closures (category "disruption").

How to work:
- Use gemini_search for anything on the web. Ask focused questions. Confirm each event's date and start time,
  ideally from the venue's or organizer's own page, and keep the source URLs.
- Use mlb_schedule for baseball. Do not search the web for game times.
- Hand bulky or tedious reasoning to deepseek_reason (merging lists, reconciling sources, checking times).
- Only submit events whose date you found in a source. Never invent an event, a time or an attendance figure;
  use null when attendance is unknown. Never estimate ridership.
- Watch the [token budget] line after each tool round. When Claude or Gemini budget runs low, stop searching and submit
  what you have confirmed.
"""


def run(start: date, venues: list[dict], gemini=None, deepseek=None, ledger: Ledger | None = None,
        client: anthropic.Anthropic | None = None, log=print):
    end = start + timedelta(days=6)
    ledger = ledger or Ledger()
    client = client or anthropic.Anthropic()
    for p in (gemini, deepseek):
        if p is not None:
            p.ledger = ledger
    trace = []

    def call_tool(name, args):
        if name == "gemini_search":
            if gemini is None:
                return "Gemini is not configured (no GEMINI_API_KEY).", True
            text, srcs = gemini.research(
                "Answer from current web sources only. Give dates, start times (Pacific) and venue names exactly as "
                "the sources state them. List every source URL you used.", args["question"])
            return text + "\n\nSources:\n" + "\n".join(f"- {s['title']}: {s['url']}" for s in srcs), False
        if name == "deepseek_reason":
            if deepseek is None:
                return "DeepSeek is not configured (no DEEPSEEK_API_KEY). Do this reasoning yourself.", True
            return deepseek_multipass(deepseek, args["task"], args["material"], max(1, min(3, args["passes"]))), False
        if name == "mlb_schedule":
            games = [g for g in sources.mlb_home_games(start, end) if "_error" not in g]
            return json.dumps(games) if games else "No MLB home games in this window.", False
        return f"Unknown tool {name}", True

    messages = [{"role": "user", "content": f"Research the week {start} to {end} and submit the events."}]
    system = system_prompt(start, end, venues)
    submitted, finalizing, last_input = None, False, 0

    for round_no in range(MAX_ROUNDS):
        # Hard stop: never start a Claude call that would run past the budget.
        projected = last_input + MAX_TOKENS
        rem = ledger.remaining("claude")
        if rem is not None and rem < projected and not finalizing:
            finalizing = True
            note = {"type": "text", "text": "Claude token budget is nearly spent. Call submit_events now with only "
                                            "the events you have already confirmed. Do not call other tools."}
            last = messages[-1]
            if last["role"] == "user" and isinstance(last["content"], list):
                last["content"].append(note)
            else:
                messages.append({"role": "user", "content": [note]})
        if rem is not None and rem <= 0:
            trace.append({"step": "claude", "stopped": "budget exhausted"})
            break

        resp = client.beta.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=TOOLS,
            messages=messages,
            output_config={"effort": CLAUDE_EFFORT},
            cache_control={"type": "ephemeral"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        u = resp.usage
        last_input = (u.input_tokens or 0) + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0)
        ledger.add("claude", last_input + (u.output_tokens or 0))
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason == "refusal":
            trace.append({"step": "claude", "stopped": "refusal", "details": str(resp.stop_details)})
            break
        if resp.stop_reason == "pause_turn":
            continue
        if resp.stop_reason == "max_tokens":
            messages.append({"role": "user", "content": "You hit the output limit. Continue, and keep it shorter."})
            continue

        uses = [b for b in resp.content if b.type == "tool_use"]
        if not uses:
            if submitted is not None:
                break
            messages.append({"role": "user", "content": "Call submit_events with your final list."})
            continue

        results = []
        for b in uses:
            if b.name == "submit_events":
                submitted = b.input.get("events", [])
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": "Received."})
                trace.append({"step": "submit", "events": len(submitted)})
                continue
            try:
                out, is_err = call_tool(b.name, b.input)
            except BudgetExceeded as e:
                out, is_err = f"{e}. Stop using this tool.", True
            except Exception as e:
                out, is_err = f"Tool failed: {e}", True
            trace.append({"step": b.name, "input": b.input, "error": is_err, "chars": len(out)})
            log(f"  round {round_no + 1}: {b.name} {'(error)' if is_err else ''}")
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": out[:30000], "is_error": is_err})

        if submitted is not None:
            break
        # All tool results in one user message, with the budget line after them so Claude can pace itself.
        messages.append({"role": "user", "content": results + [{"type": "text", "text": ledger.status()}]})

    # Plain-code harness: the same rules as the Gemini/DeepSeek pipeline.
    result = {"accepted": [], "flagged": [], "rejected": []}
    for ev in pipeline.dedupe(submitted or []):
        verdict = {"verdict": "confirmed"} if len(ev.get("source_urls") or []) >= 2 else {"verdict": "not_found"}
        status, reasons, clean = pipeline.validate(ev, venues, start, end, verdict)
        if status == "flagged":
            reasons = [r for r in reasons if not r.startswith("not independently")] + ["only one source"]
        clean["reasons"] = reasons
        result[status].append(clean)
    return {"week_start": str(start), "week_end": str(end), "orchestrator": CLAUDE_MODEL,
            "submitted": submitted is not None, "counts": {k: len(v) for k, v in result.items()},
            "budget": ledger.as_dict(), **result, "trace": trace}


DEEPSEEK_SYSTEM = "You are a careful analyst. Work only from the material given. Say clearly when something is uncertain."


def deepseek_multipass(ds, task, material, passes=3):
    """Layered reasoning: analyse -> critique -> final. Unlimited budget, so depth is cheap."""
    analysis = ds.reason(DEEPSEEK_SYSTEM, f"TASK:\n{task}\n\nMATERIAL:\n{material}\n\nWork through this in detail.")
    if passes == 1:
        return analysis
    critique = ds.reason(DEEPSEEK_SYSTEM, f"TASK:\n{task}\n\nMATERIAL:\n{material}\n\nA first analysis:\n{analysis}\n\n"
                                          "List every error, unsupported claim, missed item or date/time conflict in it.")
    if passes == 2:
        return f"{analysis}\n\n--- Critique ---\n{critique}"
    return ds.reason(DEEPSEEK_SYSTEM, f"TASK:\n{task}\n\nMATERIAL:\n{material}\n\nFirst analysis:\n{analysis}\n\n"
                                      f"Critique:\n{critique}\n\nGive the corrected final answer in the format the task asks for.")
