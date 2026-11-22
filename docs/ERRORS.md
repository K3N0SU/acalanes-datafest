# Where the day model is wrong

`scripts/bart_errors.py` -> `public/data/error_analysis.json`. Walk-forward tests for 2023, 2024 and 2025; station total (entering + leaving) per hour, every day of the year. Numbers below are 2025 unless a year is given.

Each station-hour goes in exactly one bucket, so the shares add up.

## The split

| Bucket | Share of riders | Share of the error | Error inside it | Bias | Year error if this were as good as an ordinary weekday |
|---|---|---|---|---|---|
| Whole system 10%+ off that day | 8.1% | 20.4% | 27.4% | +2.0% | 9.3% |
| Holiday period | 1.2% | 1.9% | 17.6% | +2.6% | 10.8% |
| Game hours (Giants, A's, Cal football) | 1.4% | 2.1% | 16.2% | -13.4% | 10.8% |
| Same hours one week after a game | 0.9% | 1.0% | 11.5% | +4.2% | 10.8% |
| Local surge, no known cause | 0.6% | 1.9% | 37.5% | -34.1% | 10.7% |
| Local drop | 0.1% | 0.8% | 64.2% | +62.6% | 10.8% |
| 10pm to midnight | 3.4% | 5.4% | 17.2% | -2.5% | 10.6% |
| Weekend, ordinary | 12.1% | 13.2% | 11.8% | +2.0% | 10.4% |
| Weekday, ordinary | 72.1% | 53.2% | 8.0% | +0.3% | (reference) |
| **All hours** | 100% | 100% | **10.9%** | | |

Counting noise alone is 4.0%: riders arrive at random, so no forecast gets under that. An ordinary weekday sits at 8.0% against a floor of 3.7%.

The ranking is the same in 2023 and 2024 (system exception days 24.5% and 28.5% of the error).

## What the event harness can reach

| Weakness | Size in 2025 | Knowable ahead? | Harness? |
|---|---|---|---|
| Days with far more riders than forecast, not near a holiday (parades, marches, big weekends) | 12 days, 5.5% of the error | Yes, these are announced | Yes: the city-wide layer |
| Local surges at one station | 83 station-days, 206,000 riders nobody forecast, 1.9% of the error | Mostly: 70% of the extra riders fall in 4 hours, the pattern of an event letting out | Yes: the event layer. 38 of the 83 are at Coliseum |
| Game hours | 2.1% of the error; Embarcadero runs 14% under, about 2,900 riders per game day | Yes, from the schedule | Yes, already measured: busiest-hour error at Embarcadero 17.2% -> 9.6% |
| Local drops (a station far under forecast) | 58 station-days, 0.8% of the error | Only planned closures | Partly |
| Days with far fewer riders, not near a holiday (system outages) | 6 days, 4.3% of the error | No | No. Nothing forecasts a network failure a week out |
| Days within 3 days of a holiday that ran 10%+ off | 22 days, 10.6% of the error | Yes, it is the calendar | Not an event problem: see below |

If every reachable row were forecast as well as an ordinary weekday, the year would go from 10.9% to about 10.2%. That is the ceiling for the harness on the whole year. Its value is on the days and stations it touches: a local surge is forecast 34% low today.

### Surges do not repeat, so the model cannot learn them
Only 13% of surge station-days surge again a week later, and 15% the next day. Last week's numbers say nothing about them. They need an event list.

Coliseum is the clearest target: 13 surge days in 2023, 20 in 2024, 38 in 2025, most peaking at 10 or 11pm (people leaving a show). The A's left after 2024, so none of the 2025 ones are baseball. The largest surges of 2025 are listed in the JSON (`local_surges.largest`) for the search agent to source.

### A venue we never measured: how far off is the baseball curve?
Cal football, 19 games. The pooled baseball curve applied as it is overshoots. The multiplier that fits is about 0.5: 0.48 fitted on 2023, 0.53 on 2024-25. With the 2023 value, riders over the game window in 2024-25 are off by 12.3%, against 22.0% for the day model alone and 19.6% for the curve unscaled. So the one number the planner chooses (the multiplier, 0.3 to 3.0) is worth about 10 points here, if it reasons its way to "half of a ballpark crowd". Evening games want less (0.46) than day games (0.57).

## What the harness cannot reach

**Holidays.** The largest single fixable item, and a calendar problem. Simple rules do not hold from year to year, because the answer depends on which weekday the holiday lands on:

| Condition | 2023 | 2024 | 2025 |
|---|---|---|---|
| Dec 18 to 23 | +9.4% | +14.6% | -12.4% |
| Dec 24 to 31 | -3.1% | -12.9% | -18.9% |
| Jan 2 to 5 | -22.0% | -0.8% | -10.8% |
| Federal holiday | -11.6% | -19.5% | +2.5% |
| Day after a federal holiday | -1.2% | -4.5% | -4.5% |

(actual against forecast; minus means the model forecast too many). Only Dec 24 to 31 and the day after a holiday point the same way every year.

**Weekends.** 12.0% on Saturdays and 13.2% on Sundays against 8.0% on weekdays. Half the gap is volume (218 and 163 riders per station-hour against 406, so the noise floor is 4.8% and 5.3% against 3.5%). The rest is the station's daily total: give the model the true total for each station and Saturday falls to 9.6%, Sunday to 9.7%. Weekend days swing with small local things the model has no input for.

**Late night.** 18.8% against a floor of 6.4%. The model has drifted under: bias +1.7% in 2023, -3.1% in 2024, -4.1% in 2025 (entering: -6.2%). Late-night riding is growing faster than the model follows. Only 7% of it is game hours.

**Leaving is harder than entering.** 12.3% against 10.7%, same noise floor. When someone taps out depends on the train. Added together the two partly cancel: 9.3%.

## Corrections that were tried and did not work

| Idea | Result |
|---|---|
| Last year's bias by station, hour, direction and day type, applied to this year | The bias repeats only weakly (correlation 0.37 to 0.43). Full strength: 11.6% -> 12.0% in 2024, no change in 2025. Half strength gains under 0.1 point. |
| Scale today's station forecast by its miss 7 days ago | No link (correlation -0.10 to +0.09). Makes it slightly worse. |
| A fixed correction per weekday or per month | No weekday is off by more than 2% in any year; no month keeps its sign across all three years. |

One thing does carry: a station's miss today predicts the same station tomorrow (correlation 0.40 to 0.48). A forecast refreshed the evening before could use it. The week-ahead forecast cannot.

A few station-hours are off the same way in 2024 and 2025 and carry real riders: Montgomery leaving at 8am on weekdays (+8%, 285 riders a day), Civic Center entering at 5pm (+10%, 211), Embarcadero entering at 5pm (+8%, 147), Embarcadero leaving at 10am (-12%). 57 such cells in all; the list is in the JSON.
