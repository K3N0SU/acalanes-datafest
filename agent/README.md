# Event search agent

Finds upcoming Bay Area events and BART disruptions that could change ridership. The AI only **finds and confirms events**. It never outputs a ridership number; numbers come from the trained model and the measured uplift curve.

```
MLB schedule API (official) ─┐
                             ├─> dedupe ─> checker (independent re-search) ─> harness rules ─> events.json + trace
LLM finder (web search) ─────┘
```

## Three-model mode (`orchestrate`)
| Model | Role | Budget |
|---|---|---|
| Claude Opus 5.5 (`claude-opus-5-5`, effort `high`) | Orchestrator: plans searches, decides what to trust, submits the final list | Hard cap `CLAUDE_TOKEN_BUDGET` (default 300,000) |
| Gemini (`gemini_search` tool) | Live web search with Google grounding | Hard cap `GEMINI_TOKEN_BUDGET` (default 150,000) |
| DeepSeek (`deepseek_reason` tool) | Multi-pass reasoning on raw material: analyse, critique, final | Unlimited, tracked |

- **Budget visible to Claude:** after every tool round, Claude sees a `[token budget]` line.
- **Gemini runs out:** the search tool returns "budget exhausted".
- **Claude runs low:** it is told to submit what it has confirmed, and no call starts past the cap.
- **Refusals:** the Claude request has server-side refusal fallback on (`fallbacks: "default"`).
- **Harness:** every submitted event goes through the same plain-code harness. Events with two or more sources are accepted; events with one source are flagged.

```bash
python3 -m agent.set_key claude
python3 -m agent.set_key budget
python3 -m agent.cli orchestrate --start 2026-11-23
```
Needs Python 3.10+ with `pip install anthropic`. On this Mac use `/usr/local/bin/python3`, because `python3` points to Xcode's 3.9.

## Setup
```bash
cp agent/.env.example .env      # then paste keys; .env is git-ignored
python3 -m agent.cli verify-models
python3 -m agent.cli find --start 2026-11-23
python3 -m unittest discover -s agent/tests -t .     # offline tests, no keys needed
```
Python 3.11+, standard library only.

## Providers
| | Gemini | DeepSeek |
|---|---|---|
| Default model | `gemini-3.8-flash` | `deepseek-v4.1-flash` |
| Effort | `medium` (`thinkingLevel`) | `high` (`reasoning_effort`) |
| Web search | Google Search grounding, built in | Our `web_search` + `fetch_page` tools (needs `TAVILY_API_KEY` or `BRAVE_API_KEY`) |

The model names were given by the team and are **not verified**. `verify-models` lists what each key can actually use; if a name is wrong, set `GEMINI_MODEL` / `DEEPSEEK_MODEL` in `.env`.

With both keys, the first provider finds events and the other one checks them, so a single model's mistake can't confirm itself. Choose with `--finder` and `--checker`.

## How the search works
1. **Plan:** queries come from `data/venues.csv` (one per venue) plus fixed categories: conventions, concerts and festivals, BART service changes, street closures and protests, holiday events, team schedules.
2. **Official sources first:** MLB schedule API for Giants home games (exact times, no AI).
3. **Find:** queries are batched and run in parallel. Each batch is an agentic loop: search, open pages, extract JSON.
4. **Check:** every non-official event is re-searched separately and gets `confirmed`, `disputed` or `not_found`.
5. **Harness (plain code):**
   - venue must be in `data/venues.csv`
   - date inside the forecast week and a `HH:MM` start time
   - attendance capped at venue capacity
   - source link required, and the checker must not dispute it
   - result is `accepted`, `flagged` (unconfirmed) or `rejected`, each with reasons
6. **Output:** `public/data/events.json` includes the full trace for the site's "why" panel.

BART disruptions (`category: "disruption"`) are kept as advisories with no venue, because they lower or reroute ridership instead of adding to it.

## Known limits
- Needs `data/venues.csv` (InterstellarApx). Without it every venue event is rejected.
- The A's now play in West Sacramento, so their home games are correctly rejected as not near BART.
- Keyless DuckDuckGo search is bot-blocked, so DeepSeek needs a Tavily or Brave key.
- The agent can miss events. Grade it against `data/events_truth.csv`.
