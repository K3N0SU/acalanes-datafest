# The holiday model

`scripts/holiday_model.py` -> `public/data/holiday_model.json`, `public/data/holiday_factors.json`.

The day model's worst days are around holidays: in 2025, 22 of them made up 10.6% of the whole year's error (`docs/ERRORS.md`). A fixed correction per holiday does not work, because the answer depends on which weekday the holiday lands on. So holidays get their own model.

## How it works
It is trained **only on days within 6 days of a holiday** (16 holidays a year, 2019 and 2021 onward, about 750 days), and it measures everything against a *clean recent level*: the median of the same weekday over the last 8 weeks, skipping any week that was itself near a holiday.

Three steps, each handing its answer to the next:

| Step | Question | Learns from |
|---|---|---|
| 1. System, per day | How deep does this holiday cut, and how many days either side? | Which holiday, days before or after it, the weekday it landed on, bridge days, how commuter-heavy the system is right now. Two estimates averaged: a profile of past years (weekdays and weekends kept apart, recent years counting more, similar holidays sharing evidence) and a direct model. |
| 2. Station, per day | Which stations fall more than the system, which less? | The station, and how commuter-heavy it is. Downtown office stations empty; airports hold. |
| 3. Hour, in and out | How does the shape of the day change? | Hour, direction, station, and the depth from steps 1 and 2. |

Inside the holiday window the result is blended with the day model. The blend weight (0.75 on the holiday model) and the reach (6 days) were chosen on the 2023 and 2024 tests. 2025 took no part in any choice.

## Test on 2025 (not seen in training or tuning)

| | Day model | With the holiday model |
|---|---|---|
| The 163 days within 6 days of a holiday, error per station-hour | 12.6% | 12.2% |
| The 24 of those days where the system ran 10%+ off | 26.9% | 21.5% |
| Whole year | 10.87% | 10.70% |
| Whole year, 2024 | 11.63% | 10.86% |

On the holidays themselves (system total off by, then error per station-hour):

| 2025 | Day model | Holiday model alone | Blend | Hourly error |
|---|---|---|---|---|
| Christmas Day | +86% | +30% | +44% | 86.6% -> 50.5% |
| Christmas Eve | +29% | +3% | +10% | 37.3% -> 18.6% |
| MLK Day | +26% | -16% | -5% | 35.7% -> 16.8% |
| Thanksgiving | -22% | +12% | +4% | 27.3% -> 18.6% |
| Veterans Day | -20% | +2% | -3% | 21.8% -> 12.6% |
| Juneteenth | -19% | -1% | -6% | 21.7% -> 14.0% |
| New Year's Day | +9% | -16% | -10% | 37.5% -> 29.9% |
| Presidents' Day | -17% | -9% | -11% | 18.8% -> 16.0% |
| Labor Day | +7% | +6% | +7% | 16.8% -> 18.5% |
| New Year's Eve | 0% | +10% | +8% | 14.5% -> 18.6% |

Better on 11 of 16 holidays, worse on 5 (Easter, Memorial Day, Labor Day, the day after Thanksgiving, New Year's Eve).

## How far and how deep
System riders against an ordinary day of that weekday (final model, all years):

| Holiday | The day | Reach |
|---|---|---|
| Christmas Day | -74% | Starts 5 days before Christmas Eve (-8%, -9%, -16%, -21%, -28%), Eve -51%, then -47%, -35%, -25% and runs into New Year |
| Thanksgiving | -74% | 3 days before (-9%, -19%, -30%); the Friday after -45%, Saturday -16%, Sunday -8% |
| New Year's Day | -54% | 5 days after (-29%, -25%, -19%, -17%, -16%) |
| Memorial Day | -55% | The day only; the Sunday before runs +22% |
| Labor Day | -52% | The day only |
| MLK Day | -47% | The day only |
| Independence Day | -44% | 2 days after (-14%, -8%) |
| Presidents' Day | -41% | The day only |
| Veterans Day | -21% | The day only |
| Columbus Day | -18% | The day only |
| Juneteenth | -16% | The day only |
| Halloween | -6% | None |
| Easter | +8% | None |

So two periods reach far: Thanksgiving week and Dec 19 to Jan 6. Every other holiday is one day.

## Limits
- Four to six past examples per holiday, and only two or three on a weekday for the fixed-date ones. That is why the gain is real but not large, and why some holidays get worse.
- Christmas Day is still 44% over. BART ran a far thinner day in 2024 and 2025 than in the earlier years the model learned from.
- 2019 is pre-pandemic; the commuter-share input is what lets it be used at all.
- The factors file covers 2026-11-21 to 2027-01-10. Rerun the script to extend it.

## Live use
```python
from holiday_model import holiday_factor
f = holiday_factor("2026-11-26", stations)   # (2, n_stations, 24), 1.0 away from holidays
```
The multiplier is against an ordinary day of that weekday, so it goes on a forecast built from a reference day that is not a holiday.
