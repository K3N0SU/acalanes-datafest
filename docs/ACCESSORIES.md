# Accessories: standalone corrections on top of the main model

The main model is not retrained for any of these and knows nothing about them. Each accessory is a calendar of one condition (Pride Sunday, a convention week, a football Saturday) plus one thing learned from the main model's past misses: when this condition held, how far off was the forecast, by hour and by station? That ratio is applied the next time the condition holds.

## The rule every accessory has to pass
1. **Choose on 2024.** Learn the correction on 2023 only, apply it to 2024. It is switched on only if it lowers the error on the hours it touches by at least 1%.
2. **Report on 2025.** Learn on 2023 + 2024, apply to 2025. That is the number quoted.
3. No accessory may cut a forecast below 30% or raise it above 4 times.

The main model's forecasts for all three years are out-of-sample, so nothing is fitted to the answer it is tested on. An accessory that cannot be checked (no days in both 2023 and 2024) stays off.

## Results
Error = riders the forecast got wrong ÷ riders, on the station-hours the condition touches.

### Switched on
| Accessory | Check on 2024 | Result on 2025 | Data |
|---|---|---|---|
| Football curve, Cal home games at Downtown Berkeley | curve learned on 13 games | **29.1% → 19.1%** (6 games) | ESPN schedule |
| Pride Sunday | 49.9% → 39.9% | **40.2% → 26.8%** | Rule: last Sunday of June |
| Bay to Breakers | 20.9% → 19.7% | **23.2% → 20.1%** | Rule: third Sunday of May |
| Pride Saturday | 22.1% → 21.0% | **19.7% → 18.0%** | Rule: day before Pride Sunday |
| Crowd predictor, where crowds swing (A's at the Coliseum, 2024) | attendance error 50.2% → 38.7% | rider error at game hours **48.0% → 44.6%** | MLB schedule; team has since left Oakland, so no 2025 check |

On the hours the three calendar accessories touch in 2025 (0.8% of all station-hours), error goes from 28.6% to 22.0%. Over the whole year that moves 13.05% to 13.01%: these are rare days, so they matter a lot on the day and little on the annual average.

### Tested and switched off (they did not help)
| Accessory | Check on 2024 | 2025 | Why it is off |
|---|---|---|---|
| Large conventions at Moscone Center, pooled | 8.6% → 9.8% | 11.4% → 12.8% | Worse. The main model's recent-weeks inputs already pick up convention weeks, and conventions differ too much from each other |
| Crowd predictor for Giants games | no gain | slightly worse (14.5% → 14.8%) | Giants crowds are steady; last season's average is already a good guess |
| Borrowed baseball curve for football | | 29.1% → 40.8% | Much worse, which is why football got its own curve |
| Carnaval San Francisco | 19.0% → 20.5% | 18.2% → 18.1% | No gain |
| Fleet Week air show | not checkable | 13.5% → 20.4% | Worse |
| Outside Lands | not checkable | 13.9% → 15.0% | Worse |
| Hardly Strictly Bluegrass | 20.9% → 24.4% | | Worse |
| Oakland Pride | 21.7% → 25.7% | | Worse |
| Dia de los Muertos, Fruitvale | 22.3% → 24.0% | 19.9% → 20.4% | Worse |
| After dark (five conditions, 5 PM to 9 PM) | no gain | no gain | The model already knows the season and the hour |
| Gas price up 8% or more in 8 weeks | 11.4% → 12.0% | 10.9% → 11.1% | Worse |
| Gas price down 8% or more in 8 weeks | 15.1% → 16.3% | 11.4% → 11.5% | Worse |
| Airport traffic up on last year (airport stations) | 16.3% → 16.3% | 16.4% → 16.3% | No gain |
| Unhealthy air (AQI over 100) | 14.9% → 15.7% | no such days | Too few days, and worse on them |

### Would have helped, but could not be checked
| Accessory | 2025 | Why it is off |
|---|---|---|
| Chinese New Year Parade | 38.3% → 27.2% | The search found no sourced 2023 date, so the 2024 check could not run. Left off by the rule |

### Not added
| Factor | Why |
|---|---|
| New fare gate dates | The search returned 49 rows and none passed the source check |
| Office attendance index | No open data |
| Cruise ship calls, other transit failing, two events at one station | No history to measure against. They are handled as search categories in the harness, bounded, and reported as unmeasured |
| School and university breaks | Calendar search failed on a network error; not retried yet |

## What this says
Most of the conditions we expected to matter are already absorbed by the main model, because its inputs include the same hour over the past eight weeks and the same week last year. The ones that pass are **one-day events big enough to swamp that history** (Pride, Bay to Breakers) and **event types with their own shape** (football). That is also where the search agent and the harness earn their place: specific, dated, one-off things.

## How it runs
```sh
python scripts/calendars.py          # build data/calendars/*.csv: rules, public data, sourced search
python scripts/accessories.py        # test every condition, write public/data/accessories.json
python scripts/accessory_events.py   # crowd predictor and football curve
```
`accessories.json` holds every result above plus the final ratios for the switched-on conditions (learned on 2023 to 2025). The forecaster applies them to any future day they cover.
