# The reasoning harness and the search agent

**The split:** the trained model does the ordinary day. The harness does the exceptions. Accessories ([ACCESSORIES.md](ACCESSORIES.md)) sit between them for conditions that repeat.

| | Handled by | Why |
|---|---|---|
| Weekday and weekend shape, seasons, slow growth, rain | Trained model | Years of examples |
| Conditions that repeat and can be measured (Pride, a convention week, a football Saturday) | Accessories | A handful of past examples each, enough to measure a correction and test it |
| A specific concert, a playoff game, a protest, an outage | Search agent + harness | Maybe zero past examples of this exact thing. It has to be found, sourced and reasoned about, then tied back to something measured |

## 1. The search agent (`scripts/event_agent.py`)
Gemini with Google Search. Every pass runs with extended reasoning switched on, and a summary of that reasoning is kept in the trace next to the answer.

| Pass | What it does |
|---|---|
| Finder | Several searches at once: the known venues in groups of four, plus an open pass for any large event at a venue we did not list |
| Checker | A separate search re-checks each event's date and start time. Disagreement on the date rejects the event; a different time replaces the finder's |
| Demand | For each event: sold out? resale prices? how many did this act or matchup draw elsewhere? how do this week's events compare with each other? |
| Disruptions | Three searches at once: transit (BART advisories, other operators, strikes), city (protests, parades, conventions, gaming events), hazards (weather warnings, smoke, earthquakes, school breaks) |

### The source rule
A claim is kept only if its source is real: a site the search reported retrieving, or **a page we open ourselves** and get a normal response from. A made-up address fails. Everything dropped is counted and listed.

This matters because a language model will happily produce a plausible link. On the first run with a stricter version of this rule, 14 of 15 answers were thrown out; the rule was then changed to open each page directly, which is both stricter on invented links and fairer to real ones.

### Rules (plain code)
Known venue. Date inside the week. A start time that parses. Attendance never above capacity. A sourced attendance figure replaces the default guess (75% of capacity).

### Back-test on real surprises (`scripts/surge_backtest.py`)
The error analysis lists station-days in 2025 where far more people showed up than forecast. The agent gets only the date, the station and the hour the gates peaked, and has to find what happened.

| Of the 24 largest surges of 2025 | Count | Share |
|---|---|---|
| Cause found, with a source page that opened | 18 | 75% |
| Found, and the event's time fits the hour the gates peaked | 16 | 67% |
| Found at a venue in our table | 11 | |
| ...and mapped to the right station | 11 of 11 | |
| Missed | 6 | 25% |

All six misses were answers whose source page would not open, so the source rule threw them out. Some may have been right.

What it found: Nine Inch Nails, Tame Impala (two nights), j-hope (two nights), Laufey, Hans Zimmer, Kaytranada and Tyler, the Creator at Oakland Arena (Coliseum station); the Folsom Street Fair (Civic Center); a lowrider parade and an immigration protest (24th St Mission); the Trans March and Easter in the Park (16th St Mission); Cal Fan Day (Downtown Berkeley); the Cal-Stanford Big Game, which showed up at Millbrae. Most Coliseum surges were arena concerts, a kind of event we have no measured curve for. Full list: `public/data/surge_backtest.json`.

### Run for the week of Nov 23, 2026
13 events accepted, 4 disruptions kept and 3 dropped, 21 sourced claims about crowd size kept and 12 dropped because their source would not open.

### What did not get finished
The Gemini key ran out of prepaid credit partway through the day. Three searches were cut off by it: labelling the unusual days of 2023 to 2025 (the library has one sourced label, so disruptions fall back to the 15% limit), the school and university break calendars, and a rerun of the week's search with the multi-pass version.

### Search without Gemini: what we tried
| Option | Result |
|---|---|
| DeepSeek on its own | Its API has no web search (it accepts only function tools). Asked a date question directly, it answered from memory, cited a page, and got the opponent wrong. Not usable for search. |
| Our own fetch + DeepSeek reading (`scripts/websearch.py`) | We run the query on a public results page, download the pages, and DeepSeek may cite only those. It never invented anything: with poor pages it answered "unknown". But the pages it retrieved were too generic, and it answered 0 of 2 test questions. Kept in the repo, switched off. |
| Claude's web search tool (`claude_client.search`) | Answered the test question correctly in 8 seconds with real page addresses, about $0.10 a call. Works; not used for the published results. |

The provider is one setting, `SEARCH_PROVIDER` in `.env` (`gemini`, `deepseek` or `claude`). Nothing switches on its own, because each one bills a different key.

## 2. The harness (`scripts/harness.py`)
For each event on a day:

| Step | Who | What |
|---|---|---|
| Day model | Trained model + accessories | The ordinary crowd, with the weather forecast swapped in |
| Three specialists, in parallel | DeepSeek | **Crowd** (who comes, how many, weather and turnout), **access** (which measured venue this one resembles, and how much larger or smaller the BART share), **timing** (arrivals, end time, departures). Each answers one narrow question and sees the sourced demand evidence |
| Lead | Claude | Reads the three reports against the measured facts and each other, corrects what does not hold, writes the final plan and lists every override with its reason |
| Rules | Plain code | Bounds on every parameter, then turns the plan into riders per hour. Every override is logged |
| Narrator | DeepSeek | Writes the rider-facing summary from the final numbers. It is handed the numbers and cannot change them |

Each model's own reasoning summary is stored with its answer (`_reasoning`).

### What the AI may and may not do
It **never outputs a rider count**. A plan can only scale and reshape curves that were measured on real games.

| Plan field | Meaning | Limit enforced by code |
|---|---|---|
| `reference` | Which measured venue this one is most like (Oracle Park, the Coliseum, Memorial Stadium, or both ballparks pooled) | Must be a curve that exists |
| `multiplier` | Share of the crowd using this station, against that reference | 0.3 to 3.0 |
| `arrival_profile`, `end_time`, `departure_profile` | When people come and go | Normalised; end must be 45 minutes to 12 hours after the start |
| `weather_turnout` | What the weather does to this crowd | 0.6 to 1.1 |
| `expected_attendance` | Used only if none was sourced | Never above capacity |

Riders = `attendance × turnout × measured share for the reference × multiplier`, spread by the profiles. No more than 45% of a crowd may go through one station. Nobody is put on a train after midnight; those riders are counted separately and flagged.

### Disruptions
For protests, outages, storms and the like, the lead picks which **measured past exception** the item resembles and a factor on the ordinary forecast. Code then cuts that factor back to the range that type really showed in 2023 to 2025 (`public/data/analogues.json`), plus a small margin. With no measured example of that type, the factor may not move riders by more than 15%.

The library of past exceptions is built by `scripts/analogues.py`: it takes the days when the system ran furthest from the forecast and asks the search agent what happened, under the same source rule. The size of each effect is measured; only the label comes from search.

## 3. Who runs on what
| Job | Model | Why |
|---|---|---|
| Web search, source finding | Gemini | Has Google Search built in |
| Three specialists, narrator | DeepSeek | Narrow, cheap questions, many of them |
| Lead: checking and deciding | Claude (medium effort) | One careful call per event |

Set by the keys in `.env`. Without a key, that job falls back to Gemini. All answers are cached on disk, so a rerun costs nothing and gives the same result.

## 4. Tests

### The harness on a kind of event it had no curve for
19 Cal football home games, 2023 to 2025, at Downtown Berkeley. The football curve was hidden; the harness had only the baseball curves and its own reasoning. It was told last season's average crowd, not the real attendance. Error over the 5 hours before kickoff to 7 hours after:

| Forecast | Error |
|---|---|
| Day model alone | 34.3% |
| + pooled baseball curve, applied as is | 32.7% |
| **+ harness: three specialists and a lead, bounded by the rules** | **23.5%** |

The baseball curve alone overshoots, because far fewer football fans arrive by BART at that station than baseball fans do at Embarcadero. The reasoning corrected for that game by game. For comparison, a curve measured directly on football gets 19.1% on the 2025 games, so reasoning recovers most of what measurement would give, with no football data at all.

| Other tests | Where |
|---|---|
| Event layer on baseball it never saw | `events_test.json` |
| The football test above | `harness_test.json` |
| Search agent on past surges | `surge_backtest.json` |
| Search agent against the real MLB schedule for a past week | `agent_test.json` |
| How many claims and items the source rule dropped | in `events.json` |

## 5. Running it
```sh
python scripts/event_agent.py 2026-11-23             # search: events, demand, disruptions -> public/data/events.json
python scripts/harness.py 2026-11-23 --week          # plan every event, apply, write public/data/days/DATE.json
python scripts/harness.py 2027-03-14 --event '{"name":"Stadium concert","venue":"Oracle Park","start_time":"19:00","attendance":40000,"type":"concert"}'
python scripts/harness.py --test football
python scripts/surge_backtest.py 24
python scripts/analogues.py
```

## 6. What a day file contains (`public/data/days/DATE.json`)
```
date, weekday, reference_day, weather { zone: { rain_mm, tmax_c, wind_max_kmh, rain_by_hour[24] } }, weather_source
accessories: [{ accessory, condition, source, learned_from_days }]        conditions applied to the baseline that day
events: [{
  name, venue, station, start_time, attendance, attendance_basis,
  demand:     { demand, expected_attendance, evidence: [{claim, source_url}], claims_dropped_no_source, compared_with_the_others },
  delegation: { specialists: { crowd, access, timing }, overrides: [{field, specialist_said, you_set, why}] },
  plan:       { audience, reference, multiplier, multiplier_reasons[], arrival_profile, end_time, weather_turnout, risks[], confidence, _reasoning },
  review:     { verdict, issues[] },
  applied:    { reference, multiplier, turnout, attendance, bart_arrivals, bart_departures, after_last_train, end_hour, log[] },
  peak_hour, normal_riders_peak, added_riders_peak, times_normal
}]
disruptions: [{ name, type, source_url, scope, hours, factor, basis, reason, confidence, log[] }]
stations:  { CODE: { name, baseline[24], dry[24], event_add[24] | null, disruption_change[24] | null, total[24] } }     entering + leaving per hour
summaries: { CODE: { typical_peak, segments: [{from, to, level, peak}], narration: { segments: [{from, to, why}], advice } } }
ai: { models, calls, from_cache }, bounds
```
`baseline` includes weather and accessories; `dry` is the same day with the rain removed; `total = baseline + event_add + disruption_change`.
