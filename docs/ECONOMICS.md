# What it is worth to BART

Short version: **a better forecast lets BART run fewer cars for the same protection against crowding.** Measured on 2025, a year the models never saw.

## The idea
BART pays for every car it runs, full or empty. Capacity is planned as expected riders plus a safety margin. The worse the forecast, the bigger the margin has to be. A better forecast shrinks the margin.

BART has already shown the lever is real: running shorter trains from September 2023 saved about $12M a year (bart.gov/node/41246). That change was made once, by schedule. This sets it by forecast, for each day and hour.

It is 50 stations x 19 service hours x 365 days = about 347,000 capacity decisions a year. Nobody does that by hand.

## What we measured (`scripts/capacity.py`, `public/data/capacity.json`)
Standard: capacity must cover the riders in 95% of hours. Every plan gets the margin that meets exactly that standard on 2025, so they are compared like for like.

| How capacity is planned | Capacity run per rider, station by station | Whole system |
|---|---|---|
| Same hour last week | 1.57x | 1.39x |
| Average of the last 4 weeks | 1.41x | 1.31x |
| Plain timetable (set twice a year by weekday and hour, one margin for everything) | 1.39x | 1.28x |
| Best timetable (each station, weekday and hour gets its own margin: the 95th percentile of the previous 26 weeks) | 1.32x | 1.20x |
| Weekly rolling rule, no machine learning (95th percentile of the same weekday over the last 26 weeks, refreshed every week) | 1.30x | 1.20x |
| Our final ensemble, trained on average error | 1.32x | 1.23x |
| Our tree models, trained on average error | 1.31x | 1.21x |
| **Our trees, trained on the cost of running short** | **1.22x** | **1.15x** |

- **Our first answer failed.** Sizing cars from our best average forecast only tied the best timetable (1.32 against 1.32 station by station, and worse for the whole system). A forecast trained to be right on average puts the same percentage margin everywhere. A good timetable already knows which hours are jumpy.
- **The fix: train on the cost.** Running short costs more than running long, so we retrained the trees to predict the 95th percentile of riders instead of the middle (`scripts/capacity_quantile.py`, same 34 inputs, trained only on earlier years). It learns where the margin is needed.
- Which of our models to put forward was decided on 2024, where the cost-trained trees also won (1.24 against 1.34 and 1.35).
- **Against the best timetable: 4.8% (whole system) to 7.6% (station by station) fewer cars. Against a plain timetable: 10.4% to 12.0%. Against a 4-week average: 12.6% to 13.4%.**
- **The strongest rule without machine learning that we found is not a timetable** but a rule refreshed every week. Against it the cost-trained model still needs 4.2% (whole system) to 5.5% (station by station) fewer cars, about $1.8M to $2.4M a year in electricity. An independent re-check of this work found that rule; we added it rather than leave it out.
- The mirror image: **with the same number of cars, 61% to 64% fewer overcrowded hours than the best timetable** (1.0% of station-hours over capacity against 2.6%), and 77% to 84% fewer than a plain one.
- Set on 2024 and applied to 2025 unchanged, the cost-trained model covered 95.6% of station-hours and 95.5% of system hours. The plain timetable covered 91.7% of system hours: ridership grew and a timetable does not notice.

## Dollars
| Input | Value | Source | Checked |
|---|---|---|---|
| Car-hours BART runs a year | 2,333,890 | FTA National Transit Database, 2024 profile | search excerpt |
| Electricity a year | $53.7M | BART FY25 fourth-quarter financial report | search excerpt |
| Share of electricity that moves trains | 81% | BART | search excerpt |
| Total operating expense | $1,061.5M | BART FY25 fourth-quarter financial report (unaudited) | search excerpt |
| Saving from shorter trains | about $12M a year | bart.gov/node/41246 | confirmed |

- Power alone: $53.7M x 81% / 2,333,890 = **about $18.64 per car-hour**.
- 4.8% to 13.4% of car-hours = about 111,000 to 313,000 car-hours a year.
- **About $2.1M to $5.8M a year in electricity alone.** The low end is against the best timetable for the whole system; the high end is against a 4-week average, station by station. That is 0.2% to 0.5% of the operating budget.
- This is a floor. Car wear and maintenance also fall with car-hours; we could not measure them, so they are not counted. Drivers, stations and track are paid either way and are not counted. We do not use the all-costs figure of about $455 per car-hour.

## BART's real timetable (`scripts/timetable.py`, `public/data/timetable.json`)
From BART's published schedule feed: 316,394 scheduled train-hours a year. Divided into the FTA's car-hours that is 7.4 cars per train, which fits BART's 6 to 10 car trains, so the two public sources agree.

Riders per scheduled train vary a lot by hour: the busiest hour carries 3.8 times the riders per train of the emptiest on weekdays, 4.4 times on Saturdays, 6.4 times on Sundays. The emptiest weekday hours are 9 PM, 10 PM and 11 AM.

## The smaller lines
- **Surges nobody planned for (2025):** 83 station-days, 206,199 riders, about $955,000 in fares. 70% of those riders arrive within 4 hours. The search agents found the cause of 18 of 24 tested.
- **Events in the next 30 days:** 53 events, about 597,000 attendees, about 75,700 BART trips, about $350,000 in fares.
- **Return trips not carried (`scripts/od_events.py`):** from 9.1 million trip rows, about 28,600 riders a year arrive at an event by BART and do not leave by BART, about $133,000. Small. It mattered because it corrected us: we had assumed nobody rides after midnight, and the data shows about a third of arena concert riders leave in the midnight hour.

## Limits
- Demand here is gate entries and exits, not how full each train is between stations. BART has train loads; we do not.
- BART does not publish how many cars ran on each train, so the saving is a share of the yearly total, not a count of specific cars.
- The saving assumes train length can follow the forecast day by day. Today it changes by schedule.
- Both timetables are our stand-ins, not BART's actual plan. We built the best one we could so the comparison is fair.
- No 2026 hourly data, so everything is tested on 2025.
- The models are given the weather that actually happened on the day. A real forecast a week ahead would be less exact, so real-world results would be somewhat worse on rainy days.
- The margin that meets the 95% standard is set on 2025 for every plan alike. Set on 2024 instead and carried forward, the cost-trained model still covered 95.6% of station-hours.
