# Rushover

*The right number of cars, every hour.*

**In one line:** a BART crowd forecast that learns the ordinary day from data, corrects itself for conditions that repeat, and finds and reasons about one-off events by searching the web, with every claim sourced.

It answers the organizers' prompt: *"Can local data help people get where they need to go?"*

## The question
Can BART's own fare-gate data, plus an agent that looks up what is happening in the city, tell a rider which hours their station will be packed, and when to leave to avoid it?

## How it works
```
BART hourly counts 2021-2025 + weather ──> 1. Day model ───────────> the ordinary crowd, per station and hour
Calendars of repeating conditions ───────> 2. Accessories ─────────> corrections that passed their own test
Google Search (Gemini) ──────────────────> 3. Search agent ────────> events, crowd-size evidence, disruptions, each with a source we open
Measured curves from past games ─────────> 4. Harness ─────────────> three specialists (DeepSeek) + a lead (Claude) plan each event;
                                                                      code bounds the plan and turns it into riders per hour
                                                                      ↓
                                                               forecast for the day, with the reasons and the sources
```

**The rule that keeps it honest:** the AI never writes a rider count. It finds things, cites them, and chooses how to scale and reshape curves that were measured on real events. Code enforces limits and logs every override.

| Layer | Doc | Headline result (2025, never used for any choice) |
|---|---|---|
| Day model | [MODEL.md](MODEL.md) | 13.1% error against 20.1% for "same hour last week"; 4.0% on whole-system daily totals |
| Accessories | [ACCESSORIES.md](ACCESSORIES.md) | 23 conditions tested, 3 kept. Pride Sunday 40.2% → 26.8%; football at Berkeley 29.1% → 19.1% |
| Event layer | [MODEL.md](MODEL.md) | Giants games at Embarcadero, busiest hour: 17.2% → 9.6% |
| Search agent and harness | [HARNESS.md](HARNESS.md) | Football with no football curve: 34.3% → 23.5%. Found the cause of 18 of 24 past surges, with sources |
| Where the error is | [ERRORS.md](ERRORS.md), `diagnosis.json` | Of 10.5% station-hour error, 4.0 points are counting noise and 4.7 are hour-to-hour randomness |

## Limits
- BART has not published 2026 hourly data. Next week's forecast uses patterns through 2025, scaled with BART's 2026 monthly totals. That cannot be tested yet.
- One station in one hour cannot be forecast to 3 to 5%: riders arrive at random. That accuracy is reached for whole-system daily totals.
- Measured curves exist for baseball and college football only. Other events are reasoned from them within fixed limits.
- "Crowding" is people entering and leaving a station per hour, not how full a train car is.
- The agent can miss an event or misread a time. Sources are opened and checked, and what was dropped is listed.

## Who does what
| | **K3N0SU** | **InterstellarApx** |
|---|---|---|
| **Does** | Data, model, accessories, search agent, harness, tests, the JSON the site reads | The website and its deployment |
| **Owns** | `scripts/`, `public/data/`, `data/`, model docs | `src/`, `index.html`, site config |

Site handoff, with every data file described: [FRONTEND.md](FRONTEND.md). Sign-in and favorites code ready to drop in: `handoff/auth/`.

### In the demo (5 minutes)
| Part | Time |
|---|---|
| Question: you cannot see a crowd coming until you are in it | 0:30 |
| Data: 222 million trips, weather, what BART has not published | 0:40 |
| The site, live: a station next week, an event the agent found, its source and its reasoning | 1:30 |
| Finding: the benchmark table, then where the error comes from | 1:20 |
| Limits and what is next | 0:40 |
| Buffer | 0:20 |

## Timeline
| Time | Milestone |
|---|---|
| 14:30 | Feature freeze |
| 15:15 | Code freeze, rehearsed twice, backup screen recording |
| 15:30 | Present |
