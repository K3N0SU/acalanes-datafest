# The model and its test results

Everything here comes from runs on Nov 21, 2026. Numbers are in `public/data/`: `benchmark.json`, `backtest.json`, `diagnosis.json`, `events_test.json`, `accessories.json`, `accessory_events.json`.

**Three layers.** A trained model does the ordinary day, weather included. Accessories correct it for conditions that repeat ([ACCESSORIES.md](ACCESSORIES.md)). A search agent and a reasoning harness handle one-off events and disruptions ([HARNESS.md](HARNESS.md)). An error breakdown by a second analysis is in [ERRORS.md](ERRORS.md).

## The final ensemble (added 14:20)
After the tree model below was finished, we trained neural networks and blended everything. Same rule: choose on 2024, score 2025 once. Details in [ADVANCED.md](ADVANCED.md), [NEURAL.md](NEURAL.md), [LEVELS.md](LEVELS.md) and [BACKGROUND.md](BACKGROUND.md).

| Forecaster | 2025 error, all cells | Weight |
|---|---|---|
| Same hour last week | 20.1% | |
| Gradient-boosted trees (this document) | 13.05% | 20% |
| Deep feed-forward network, 3 random starts | 12.94% | 20% |
| Network trained on the trees' leftover error | 13.09% | 10% |
| Small transformer | 13.69% | 30% |
| Similar-day matching by cosine similarity | 14.86% | 20% |
| **Blend of the five** | **12.66%** | |

- Against the trees alone, the blend is better on ordinary days (12.63% to 12.18%) and the busiest quarter of hours (11.10% to 10.40%), and slightly worse on weekends (18.42% to 18.72%).
- For whole-system daily totals the trees alone remain best (4.05% against 4.43% for the blend).
- The site's live forecast still runs on the trees. Wiring the blend into it is the next step.
- A reward-driven online re-weighting of the forecasters and a reconciliation step were both tested and are not in the final blend.

## Data
| | |
|---|---|
| BART hourly origin-destination ridership | 2021 to 2025 (2019 for comparison). About 9 million rows a year, 222 million trips. |
| Unit | One station, one date, one hour: people entering and people leaving. 50 stations. |
| Weather | Hourly rain, temperature and wind, 2021 to 2025, four Bay Area zones (Open-Meteo). Forecast for the next 16 days. |
| Past events | 731 Giants and A's home games with first pitch and attendance (MLB). 26 Cal football home games (ESPN). |

**Check:** entries at 12th St on March 12, 2025 counted straight from the raw file: 5,953. From our prepared table: 5,953.

## Layer 1: the day model
Two gradient-boosted tree models averaged (scikit-learn `HistGradientBoostingRegressor`; one optimises Poisson likelihood, one absolute error), 34 inputs:

- **Recent pattern:** the same hour 1 to 4 weeks earlier; average, median, weighted average and spread over 8 weeks; the hour before and after, last week; the station's daily total last week and over 4 weeks.
- **Trend:** the station's and the system's last week against the 8 weeks before; growth against the same 4 weeks a year ago; last year's value brought up to this year's level.
- **Calendar:** hour, weekday, month, week of year, holiday flags, and whether last week or last year was a holiday.
- **Weather:** rain that hour, over 3 hours, over the day, and a week earlier; the day's high; strongest wind.

### How it was chosen
Every choice was made on 2024 only, with models trained on 2022 to 2023. The chosen setup was then trained on 2022 to 2024 and scored once on 2025.

| Candidate | Error on 2024 |
|---|---|
| First model: 15 everyday inputs + weather | 14.5% |
| + 13 new inputs, same settings | 14.7% |
| + new inputs, deeper trees, Poisson | 14.2% |
| + new inputs, deeper trees, absolute error | 14.1% |
| **Average of the last two (chosen)** | **13.8%** |

### Benchmark on 2025 (never used for any choice)
Error = riders the forecast got wrong ÷ riders, over every station, direction and hour.

| Method | All hours | Weekday commute | Weekends | Rainy days |
|---|---|---|---|---|
| Same hour last week | 20.1% | 15.3% | 26.4% | 24.6% |
| Average of last 4 weeks | 17.6% | 13.0% | 22.2% | 24.6% |
| Weighted average of last 8 weeks | 17.2% | 12.7% | 21.9% | 24.3% |
| Last year, grown to this year | 17.4% | 12.7% | 24.8% | 20.8% |
| Median of last 8 weeks | 15.8% | 10.6% | 19.7% | 27.1% |
| Ridge regression on the same history | 14.7% | 10.1% | 19.7% | 20.5% |
| First model | 14.1% | 11.1% | 19.6% | 16.4% |
| **Final model** | **13.1%** | **10.2%** | **18.4%** | **14.4%** |

- 35% lower error than "same hour last week", 11% lower than the best method that needs no training, 7% lower than our first model.
- Average miss: 16.2 riders per station-hour, against 24.9 for last week.
- On weekday commute hours a plain ridge regression matches it (10.1% vs 10.2%). The model's edge is everywhere else: weekends, off-peak, rain.

**For a rider:**
| | Same hour last week | Final model |
|---|---|---|
| Names a station's busiest hour of the day, within an hour | 68.0% | 74.4% |
| Packed hours it warned about in advance | 84.4% | 92.1% |
| Its packed warnings that were right | 84.3% | 90.9% |
| Error on a station's daily total | 12.4% | 6.5% |

Walk-forward for all three years: 14.6% (2023), 13.8% (2024), 13.1% (2025).

## How close to perfect is that?
Ordinary days in 2025 (no holidays), station total per hour unless stated.

| Level of detail | Final model | Same hour last week |
|---|---|---|
| Whole system, whole day | **4.0%** | 8.5% |
| One station, whole day | 6.1% | 10.6% |
| Whole system, one hour | 6.0% | 10.7% |
| One station, one hour | 10.5% | 15.7% |

The 10.5% splits into:

| Source | Points | Can it be fixed? |
|---|---|---|
| Counting noise: riders arrive at random | 4.0 | No. A perfect forecast still misses by this much |
| Riders landing in a different hour than usual | 4.7 | Mostly no (see below) |
| One station running high or low that day | 1.1 | Partly: events |
| The whole system running high or low that day | 0.7 | Partly: disruptions and city-wide events |

**The hour-shape error is close to unknowable.** A method that cheats, averaging the same hour from the week before *and the week after* and given the true daily total, scores 10.3%. Our forecast given the same daily total scores 8.7%.

**By how busy the hour is:**
| Station-hour had | Final model | Noise floor | Share of riders |
|---|---|---|---|
| under 100 riders | 27.4% | 10.3% | 5% |
| 100 to 300 | 10.9% | 5.8% | 23% |
| 300 to 1,000 | 8.7% | 3.5% | 45% |
| 1,000 to 3,000 | 9.4% | 2.1% | 21% |

**The days that go wrong are exceptions.** On 29 days in 2025 the whole system was off by more than 10%; error on those days is 27%, on all others 9.3%. The worst are +60% (June 29), +57% (Feb 15), −52% (Sept 5), −38% (May 9). That is what the search agent and harness are for.

## What rain does to ridership
Real riders on rainy days in 2025 against the model's forecast for the same hours with the rain removed:

| | Weekday commute | Weekday midday and evening | Weekend |
|---|---|---|---|
| Light rain, 1 to 5 mm | −1.7% | −1.7% | −3.5% |
| Rain, 5 to 20 mm | −7.8% | −7.5% | −15.2% |
| Heavy rain, over 20 mm | −12.6% | −13.3% | too few days |

Rain takes riders off BART, more when the trip is optional. The model captures about two thirds of the drop. A tourism index built from airport-station riders was tested and made the forecast worse, so it is not used.

## Event uplift: what a game adds
For every past baseball game: riders who showed up at the venue's station minus what the day model expected, by hour from 4 hours before first pitch to 7 after, divided by attendance. Day and night games separately. The curve used for a test year is fitted only on earlier years. Attendance is not known ahead, so the test uses the venue's average from earlier years.

| Games tested | All game hours: without → with | Busiest hour: without → with |
|---|---|---|
| Giants → Embarcadero, 2025 (81 games) | 19.9% → **14.5%** | 17.2% → **9.6%** |
| Giants → Embarcadero, 2024 (81 games) | 19.1% → **16.4%** | 16.8% → **11.1%** |
| A's → Coliseum, 2024 (81 games) | 61.5% → **47.9%** | 74.0% → **47.2%** |

Busiest hour of a game, in riders: Embarcadero 2025: 3,760 came, the day model said 3,136, with the event layer 3,596. Coliseum 2024: 1,391 came, 361, 936.

Football has its own curve, measured on Cal home games: at Downtown Berkeley in 2025, error over game hours goes 29.1% → 19.1%. See [ACCESSORIES.md](ACCESSORIES.md).

**The reasoning harness, with no football curve at all:** on 19 Cal football games the day model alone is off by 34.3%, the borrowed baseball curve by 32.7%, and the harness by 23.5%. See [HARNESS.md](HARNESS.md).

**The search agent on past surprises:** given only a date, a station and the hour the gates peaked, it found the cause of 18 of the 24 largest unexplained surges of 2025, each with a source page that opened.

## Forecasting a future day
BART has not published hourly counts for 2026 (the file is empty). For a target day the model predicts the same weekday 364 or 728 days back in 2025, a year it never trained on, with **the target day's weather forecast swapped in**. Each station is then multiplied by its growth from October 2025 to October 2026 in BART's monthly reports (14.9% system-wide), the switched-on accessories for that date are applied, and the harness adds events and disruptions. Beyond the 16-day weather forecast a dry day is assumed and labelled.

## Limits
1. No 2026 hourly data, so future-day forecasts cannot be tested yet.
2. Station-hour error is bounded by counting noise near 4% and by hour-to-hour randomness. 3 to 5% is reached for whole-system daily totals, not for one station in one hour.
3. The uplift curves come from baseball and college football. Anything else is reasoned from them, within fixed limits.
4. Gate counts are not train-car crowding.
5. The weather test uses the weather that happened. A live forecast uses a weather forecast.
6. The AI layers can be wrong. They never set a rider count, their choices are bounded, their sources are opened and checked, and every override is logged.

## Reproduce
```sh
pip install pandas numpy scikit-learn scipy requests openpyxl joblib anthropic
python scripts/bart_data.py && python scripts/weather.py && python scripts/events_history.py
python scripts/bart_bench.py        # choose the setup on 2024, benchmark on 2025
python scripts/bart_model.py        # walk-forward, error by level, noise floor, rain effect
python scripts/bart_diagnose.py     # where the error comes from
python scripts/bart_events.py       # baseball uplift and its test
python scripts/calendars.py && python scripts/accessories.py && python scripts/accessory_events.py
python scripts/bart_forecast.py 2026-11-23
```
