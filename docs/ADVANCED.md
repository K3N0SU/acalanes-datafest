# Advanced forecasting experiments

Three ideas were tried against the current best model (two gradient-boosted tree models, averaged). Error is wape: total absolute error divided by total actual riders, over every station, direction and hour. Every choice was made on 2024 using models trained only on earlier data. The chosen setup was then run on 2025 once.

## What each technique is

| Technique | Plain description |
|---|---|
| A. Small transformer | A small neural network (2 attention layers) reads one station's last 8 same-weekday hourly profiles, plus weekday, month, holiday flag, rain and temperature, and writes out 24 hourly counts. Trained on CPU in 2.5 to 6 minutes. |
| B. Analog days | For each station, direction and day, find the 10 earlier days that look most alike (shape of recent weeks, weekday, month, holiday) and average what happened on them, scaled to the current level. No training. |
| C. Online weighting | Keep a weight for each forecaster per station, direction and hour-block. Shift weight toward forecasters with smaller recent errors, using only outcomes at least 7 days old. |

## Results (wape, lower is better)

| Setup | 2024 | 2025 |
|---|---|---|
| Current best (baseline) | 0.1379 | 0.1305 |
| A. Transformer alone | 0.1355 | 0.1369 |
| B. Analog days alone | 0.1438 | 0.1486 |
| C. Online weighting (best + simple forecasters + A + B) | 0.1298 | not run |
| Fixed blend: best + transformer | 0.1296 | not run |
| Fixed blend: best + analog | 0.1309 | not run |
| **Fixed blend: 35% best, 40% transformer, 25% analog (chosen)** | **0.1276** | **0.1284** |

2025 by segment for the chosen blend and the baseline:

| Segment | Baseline | Blend |
|---|---|---|
| All cells | 0.1305 | 0.1284 |
| Ordinary days | 0.1263 | 0.1233 |
| Weekends | 0.1842 | 0.1888 |
| Busiest quarter of cells | 0.1110 | 0.1057 |

## Adopted and not adopted

- Adopted: the three-way blend, because it had the lowest 2024 error. On 2025 it beat the baseline by 0.0021 overall, and by more on ordinary days and busy cells. It was worse on weekends (0.1888 against 0.1842).
- Not adopted: the transformer alone and analog days alone. Both were worse than the baseline on 2025.
- Not adopted: online weighting. It scored 0.1298 on 2024, behind the fixed blend. Online weights over the baseline and simple forecasters only (learning from 2023) scored 0.1371. An NNLS blend fitted on 2023 scored 0.1401, worse than the baseline.

## Limits

- The blend weights were picked on a 0.05 grid on 2024 itself, so the 2024 figure of 0.1276 is optimistic. The 2025 figure is the fair one, and its gain is small.
- The transformer was better than the baseline on 2024 but worse on 2025; one year of evidence each way. The gain from blending is probably from averaging different kinds of model.
- Hyperparameter searches were small (24 epochs maximum, 72 analog settings, 36 online settings). One random seed.
- Weather for the target day is used as an observed value, as elsewhere in this project; a live forecast would be noisier.
- Not a runtime-tested pipeline: the blend exists as saved arrays (`data/clean/adv_pred_2024.npy`, `adv_pred_2025.npy`), not as a deployed model.
