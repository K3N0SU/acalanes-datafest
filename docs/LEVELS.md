# Forecast error by level of detail, and whether forcing totals helps

All errors are WAPE: sum of absolute errors divided by sum of actual riders. Station totals are entering plus leaving. "Ordinary" days exclude holidays, the day after Thanksgiving and Christmas week. Every choice (inputs, settings, blend weights, reconciliation mode) was made on 2024 with models trained on 2022-2023; 2025 was then scored once with models trained on 2022-2024. Numbers: `public/data/levels.json`. Code: `scripts/lvl_feat.py`, `scripts/lvl_run.py`, `scripts/lvl_mlp.py`.

## Result on 2025, ordinary days

| Level | Trees (pred_2025) | Current best (adv) | Level model blended with current best | Detailed forecast after reconciliation |
|---|---|---|---|---|
| One station, one hour | 10.48% | 10.23% | n/a | 10.15% |
| One station, whole day | 6.12% | 6.27% | 6.13% (MLP added: 6.07%) | 6.18% |
| Whole system, one hour | 5.96% | 6.17% | 6.07% | 6.07% |
| Whole system, whole day | 4.05% | 4.46% | n/a | 4.37% |
| Every (direction, station, hour) cell | 12.63% | 12.33% | n/a | 12.25% |

On all 2025 days the cell error goes from 12.84% to 12.74%.

**The 5% target was not reached** at system-hour (best 5.96%) or station-day (best 6.07%). The models trained directly at those levels, on their own, were worse than the current best summed up (2025: system-hour 6.50% for the best tree model, 8.5% for ridge on logs, 7.7% for the MLP; station-day 6.34% tree, 6.50% MLP, against 6.27%). Blending gave only a small gain: the 2024 weights put 0.8 on the summed current best and 0.2 on the level model.

## What was built

- System-hour model: inputs are the same hour 7, 14, 21, 28 days ago, 8-week mean, median, spread and decayed average, last year's value grown by recent year-on-year change, the hours before and after last week, system daily totals, trend, calendar (hour, weekday, month, week, holiday, holiday yesterday and tomorrow, day after Thanksgiving, Christmas week) and the four zones' weather averaged. Variants tried on 2024: boosted trees with absolute-error loss on a ratio target (three sizes), Poisson loss (two sizes), ridge on log values (two strengths). Best on 2024: small absolute-error trees (6.63%) against 5.91% for the summed current best.
- Station-day model: same idea per station with the station as a category. Best on 2024: larger absolute-error trees (6.63%) against 6.02% for the summed current best.
- The summed current best was used as a blend member, not as an input to the trees. Out-of-sample forecasts exist for only 2023 (trees) and 2024, so feeding them in as an input would leave one training year for the 2024 test. Stacking was not tried.
- Reconciliation modes tried on 2024: rescale each station-day to the blended station-day forecast ("stn"), rescale each system-hour ("sys"), both in either order, and three rounds of alternating. All five improved 2024 cell error slightly (12.11% to 12.05-12.09%). The best on 2024, station-day then system-hour, was adopted and applied to 2025 once. Station hourly shape and entering/leaving split are kept.

## What improved and what did not

- Reconciliation helped a little in both years: 2025 ordinary-day cell error 12.33% to 12.25%; station-hour 10.23% to 10.15%. It is a small gain, not a change in kind.
- Against the summed current best, the blended level forecasts improved station-day (6.27% to 6.13%) and system-hour (6.17% to 6.07%) in 2025. But the reconciled detailed forecast does not make the station-day or system-hour totals as good as those forecasts, because the rescale uses the blended target and then re-normalises.
- The tree-only forecast (pred_2025) is better than the blended current best at system-hour and system-day in 2025 (5.96% and 4.05% against 6.17% and 4.46%) but was worse on 2024. The current best was kept as the base because it was chosen on 2024.
- Reconciled arrays on 2025 are slightly worse at system-day (4.37%) than the tree forecast summed (4.05%). Ordinary-day totals were not what the reconciliation was tuned for.
- The MLP (sklearn, 64x32, three seeds, ratio target) was alone worse than trees at both levels. At station-day it got weight 0.2 in the 2024 blend and gave 6.07% on 2025; at system-hour it got weight 0. It is not part of the saved reconciled arrays.

## Why 5% is hard

The remaining error at system level looks like day-to-day shocks that no input available a week ahead describes (events, disruptions, strikes, late weather). The level models have the same information as the detailed model, so they mostly reproduce it. A forecast made seven days ahead from last-week data cannot see those shocks; a lower error would need new information (event calendar, service alerts), not a different model.

## Leakage checks

- Rider inputs are only shifts of 7, 14, ..., 56 and 364 days, windows ending 7 days before the day, and totals of the same kind.
- Programmatic test: all ridership from day 1500 onward was overwritten with noise, and every system-hour and station-day input for days before day 1507 was unchanged. Both passed.
- Same-day inputs are calendar and weather only.
- 2024 choices used models trained before 2024. 2025 rows were first scored at the end, once.
- The blend member (summed current best) comes from walk-forward forecasts.

## Limits

Weather for day d is observed weather in these tests; in live use it would be a forecast. Ordinary-day error excludes holidays, which are the days a rider-facing forecast needs most. The reconciliation clips each rescale to 0.5-2x. Saved arrays: `data/clean/lvl_pred_2024.npy`, `lvl_pred_2025.npy` (shape 2 x 50 x days x 24, the reconciled current best).
