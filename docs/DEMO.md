# Demo script (5 minutes)

**The current script is `deck/SCRIPT.md`** (built from `deck/content.json`, about 680 words, Hengyi and Mohammed's parts marked). Open the notes window with `deck/prompter.bat`: it shows the script split by speaker with a timer, and it does not appear in screen capture or screen share. On a projector that mirrors the laptop screen it WILL show, so use "Extend" display mode and keep it on the laptop.

## How it sells (the pitch in four lines)
- **Buyer:** BART. Fares cover 23% of operating costs and the fiscal 2027 gap is about $375M.
- **What it does:** tells BART how many cars each station and hour needs. BART pays for every car it runs, full or empty.
- **Measured on 2025:** a model trained on the cost of running short needs 5 to 8% fewer cars than the best timetable we could build, and 10 to 12% fewer than a plain one, for the same crowding standard. About $2.1M to $5.8M a year in electricity alone. Or keep the cars and cut overcrowded hours by about 60%.
- **Why not by hand:** 347,000 station-hour decisions a year. Details and sources in `docs/ECONOMICS.md`.

The older rider-facing walk-through below is kept for reference.

## Earlier version
Follows the five parts the organizers asked for: question, data, build, finding, limit. Times are targets; rehearse to 4:30.

## 1. Question (0:30)
> "You can't see a crowd on BART coming until you're standing in it. We asked: can BART's own gate counts, plus an agent that reads what's happening in the city, tell you a week ahead which hours your station will be packed, and when to leave instead?"

## 2. Data (0:40)
> "BART publishes every trip by hour and station. We used 2021 through 2025: 222 million trips, 50 stations. We joined five years of hourly weather, and the schedules of 731 baseball games and 26 Cal football games with their attendance."

> "One thing we found in the data: BART has not published hourly counts for 2026. The file is there and it is empty. So everything we test, we test on 2025, and next week's forecast is scaled up using BART's monthly totals. We say that on the site."

## 3. Build (1:30, on the live site)
Show the site. Pick **Downtown Berkeley, Saturday Nov 28**.
> "Three layers. First, a model trained on the gate counts gives the ordinary day, weather included. Second, small add-ons correct it for things that repeat, like Pride or a football Saturday. Each add-on had to prove itself on 2024 before we switched it on. Third, a search agent looks up what's actually happening that week."

Point at an event the agent found (Cal football, or Steve Lacy at Bill Graham).
> "It found this event, checked the date and time on a second search, and looked for evidence of how big the crowd will be. Every claim has a source, and we open each source page ourselves. If the page doesn't load, the claim is thrown out."

> "Then three small AI specialists each answer one narrow question: who's coming, how they'll get there, and when. A lead model checks them against each other and against what we measured. The AI never writes a rider number. It can only scale curves we measured on real games, inside fixed limits, and code logs every time it overrides the AI."

## 4. Finding (1:20)
Show the benchmark table.
> "On 2025, a year the model never saw, the obvious guess, 'same as this hour last week', is off by 20%. The best method with no training is off by 14.7%. Ours is off by 13.1%. For the whole system's daily total, we're within 4%."

> "For a rider: it names a station's busiest hour, within an hour, 74% of the time, and it catches 92% of packed hours in advance."

Show the game-day chart.
> "And on the days that break the pattern: at Embarcadero, in the busiest hour of a Giants game, the model alone is off by 17%. With the event layer it's under 10%. For Cal football at Downtown Berkeley, 29% down to 19%. On Pride Sunday, 40% down to 27%."

> "The finding we didn't expect: most of what we thought would matter, doesn't. We tested 23 conditions, from conventions to gas prices to daylight. Three passed. The model already knows the rest from its own history. What it can't know is a one-off event, and that is exactly what the search agent is for."

## 5. Limit (0:40)
> "Three honest limits. One: no 2026 hourly data, so next week's forecast can't be checked yet. Two: one station in one hour can't be forecast perfectly, because riders arrive at random. About 4 points of our error is pure counting noise that no model can remove. Three: our event curves come from baseball and football; a concert is reasoned from those, inside limits, not measured."

> "Next: get BART's live counts so it can check itself daily, and measure concerts directly."

## Numbers sheet
| Claim | Number | Where it's from |
|---|---|---|
| Trips in the data | 222 million, 2021 to 2025, 50 stations | `backtest.json` |
| Error, all hours, 2025 | 13.1% vs 20.1% (last week) vs 14.7% (best untrained) | `benchmark.json` |
| Whole-system daily total | 4.0% vs 8.5% | `backtest.json` |
| One station's daily total | 6.1% vs 10.6% | `backtest.json` |
| One station, one hour, ordinary days | 10.5% vs 15.7% | `backtest.json` |
| Busiest hour named within an hour | 74% vs 68% | `benchmark.json` |
| Packed hours caught | 92% vs 84% | `benchmark.json` |
| Rainy days | 14.4% vs 24.6% | `benchmark.json` |
| Rain effect, 5 to 20 mm | −8% weekday, −15% weekend | `backtest.json` |
| Giants at Embarcadero, busiest hour, 2025 | 17.2% → 9.6% (81 games) | `events_test.json` |
| Cal football at Downtown Berkeley, 2025 | 29.1% → 19.1% (6 games) | `accessory_events.json` |
| Pride Sunday 2025 | 40.2% → 26.8% | `accessories.json` |
| Conditions tested / kept | 23 / 3 | `accessories.json` |
| Harness on football, no football curve | 34.3% → 32.7% (borrowed curve) → 23.5% (harness), 19 games | `harness_test.json` |
| Search agent on past surges | cause found for 18 of 24, each with a source that opened | `surge_backtest.json` |
| Counting noise | 4.0 of the 10.5 points | `diagnosis.json` |
| Exception days | 29 days in 2025 off by 10%+; 27% error on them, 9.3% on the rest | `diagnosis.json` |
| Growth applied for 2026 | 14.9% system-wide, Oct 2025 to Oct 2026 | `forecast.json` |

## Questions judges may ask
**"Why not just use last week?"** We tested it. It is 35% worse, and far worse on rainy days (24.6% vs 14.4%) because it doesn't know it rained last week or will rain this week.

**"How do you know the AI isn't making things up?"** Three ways. It never produces a rider count, only a plan that code applies to measured curves within limits. Every claim needs a source, and we open the source page ourselves; what fails is dropped and counted. And a second model checks the first.

**"Did you tune on your test data?"** No. Every choice was made on 2024 with models trained on earlier years. 2025 was scored once.

**"Why is your error 13% and not 5%?"** At the level of one station in one hour, about 4 points are counting noise: people arrive at random. A method that cheats, using the week before and the week after, does worse than ours. For daily totals across the system, we are at 4%.

**"What didn't work?"** Most of the add-ons: conventions, gas prices, airport traffic, daylight, air quality, several festivals. A tourism index made the model worse. We left them off and show the numbers.

**"How would BART use this?"** Station staffing and crowd messaging for the days that break the pattern, and a rider-facing "leave at 4, not 5" tip. It runs on public data and could rerun weekly.

**"Is rain good or bad for ridership?"** Bad. We expected some riders to switch from bikes. On a rainy day weekday ridership drops about 8% and weekend ridership about 15%.
