# Neural members and the new blend

A transformer is a neural network that looks at a set of inputs (here, the same station's previous Tuesdays, say) and learns which of them to pay attention to when predicting the next one. We also tried a plain multilayer perceptron (MLP), which just stacks fully connected layers over the same inputs, to see whether attention earns its place.

Error is WAPE: sum of absolute errors divided by total riders, over every direction, station, day and hour of the year. Every choice was made on 2024 with models trained only on earlier years. 2025 was then scored once per model with nothing changed. Inputs for day d use ridership from day d-7 or earlier; calendar and weather of day d are allowed.

## Results

| Forecast | 2024 | 2025 |
|---|---|---|
| Gradient-boosted trees | 0.1379 | 0.1305 |
| Old transformer (one seed) | 0.1355 | 0.1369 |
| Similar days | 0.1438 | 0.1486 |
| Previous blend (trees, old transformer, similar days) | 0.1276 | 0.1284 |
| New transformer with trees' context, 3 seeds | 0.1400 | 0.1421 |
| MLP, same inputs, 3 seeds | 0.1357 | 0.1294 |
| Residual MLP (learns the trees' error), 3 seeds | 0.1478 | 0.1309 |
| **New blend** (0.2 trees, 0.3 old transformer, 0.2 similar days, 0.2 MLP, 0.1 residual MLP) | 0.1269 (weights chosen on 2024, so optimistic) | **0.1266** |

Single seeds on 2024: transformer 0.1421 / 0.1434 / 0.1432 (average of the three: 0.1400); MLP 0.1365 / 0.1372 / 0.1371 (average 0.1357); residual MLP 0.1514 / 0.1480 / 0.1512 (average 0.1478). Averaging seeds helps by 0.0008 to 0.0036.

2025 for the final blend, against the trees and the previous blend:

| Slice | New blend | Trees | Previous blend |
|---|---|---|---|
| All cells | 0.1266 | 0.1305 | 0.1284 |
| Ordinary days | 0.1218 | 0.1263 | 0.1233 |
| Weekends | 0.1872 | 0.1842 | 0.1888 |
| Busiest quarter of cells | 0.1040 | 0.1110 | 0.1057 |

## What was tried

- More history: starting training in March 2021 instead of 2022 helped the MLP (2024: 0.137 against 0.141).
- Extra context: the median and exponentially weighted profiles of the last 8 weeks, last year's profile grown to this year's level, station trend, year-over-year growth, holiday flags for last week and last year, week of year, rain and temperature.
- 30 epochs instead of 14 for the MLP: no gain (0.1372, 0.1370, 0.1376).
- Residual learning (predict actual minus tree forecast, scaled by level): worse alone than the trees on 2024 because only 2023 was available to learn from, but it adds a small gain in the blend. A first residual transformer run scored 0.2101 because of a bug (the base profile was added twice); it was discarded and not re-run.

## What worked and what did not

- The MLP matched or beat every single network and was about 4 times faster to train (about a minute per seed against about 3.5 minutes). Attention did not earn its place here.
- The new transformer with the extra context was worse than the old one (0.1400 against 0.1355 on 2024), and got zero weight in the blend. The most likely cause is the short training budget (200 seconds, about 7 epochs on 2 or 3 threads), but this was not tested further.
- The blend gain comes from diversity: the MLP and residual MLP each took 0.1 to 0.2 of the weight, and the old transformer kept 0.3.

## Limits

- Blend weights come from a coarse grid on 2024 and the 2024 score is optimistic. The 2025 gain over the previous blend is 0.0018, which is small, and both beat the trees. Weekends got slightly worse than the trees alone (0.1872 against 0.1842).
- The 2025 models were trained in the same sitting as the 2024 runs of sibling models. No setting was changed after seeing 2025.
- No automated test shifts future ridership and checks that forecasts do not move. The no-leakage argument is from reading the code (see `public/data/neural.json`).
- Scripts: `scripts/nn_train.py`, `nn_blend.py`, `nn_finalize.py`. Final arrays: `data/clean/nn_pred_2024.npy` and `nn_pred_2025.npy`.
