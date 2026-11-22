"""
Layer 1: the day-to-day model, trained with the setup chosen by bart_bench.py, with walk-forward tests.

Input:  data/clean/station_hour.csv.gz, data/clean/weather.csv, data/clean/best_config.json
Output: public/data/backtest.json     errors by year, by level of detail, by how busy the hour is, and the counting-noise floor
        data/clean/pred_YYYY.npy      out-of-sample predictions, used by bart_events.py
        data/clean/model_2025.joblib  model trained on 2022 to 2024, used for forecasts

Walk-forward: train on years before Y, test on Y, for Y = 2023, 2024, 2025.

Run:  python scripts/bart_model.py
"""

import json

import joblib
import numpy as np
import pandas as pd
from scipy.stats import poisson

from bart_core import BASE, CLEAN, ROOT, WEATHER, design, fit_model, load, wape

OUT = ROOT / "public" / "data"
OUT.mkdir(parents=True, exist_ok=True)
TEST_YEARS = [2023, 2024, 2025]
RAINY_MM = 5.0

cfg_path = CLEAN / "best_config.json"
CONFIG = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {"names": BASE + WEATHER, "label": "first model"}
FULL = CONFIG["names"]
c = load()
print(f"stations {c.S}, days {c.D}, inputs {len(FULL)}, setup: {CONFIG.get('label')}")


def noise_floor(lam):
    """the error a perfect forecast would still make, because riders arrive at random:
    mean |X - m| for a Poisson count with mean m is 2 * m * P(X = floor(m))"""
    lam = np.maximum(lam, 1e-6)
    return float((2 * lam * poisson.pmf(np.floor(lam), lam)).sum() / lam.sum())


results, final_model = {}, None
for ty in TEST_YEARS:
    te = c.year == ty
    model = fit_model(c, CONFIG, ty)
    X, y = design(c, te, FULL)
    p = model.predict(X)
    n_days = int(te.sum())
    shape = (2, c.S, n_days, 24)
    np.save(CLEAN / f"pred_{ty}.npy", p.reshape(shape))

    b7 = np.nan_to_num(c.lag7[:, :, te, :].reshape(-1))
    b4 = np.nan_to_num(c.mean4[:, :, te, :].reshape(-1))
    special = np.broadcast_to(c.special[te].reshape(1, 1, -1, 1), shape).reshape(-1)
    rainy = c.F["rain_day"][:, :, te, :].reshape(-1) >= RAINY_MM
    ordinary = ~special

    def three(mask):
        return {"model": wape(p[mask], y[mask]), "last_week": wape(b7[mask], y[mask]), "last_4_weeks": wape(b4[mask], y[mask])}

    # ordinary days at four levels of detail: (station total per hour) is what a rider sees
    P, A, B = p.reshape(shape), y.reshape(shape), b7.reshape(shape)
    od = ~c.special[te]
    def levels(F):
        st_hr = F[0] + F[1]                       # station x day x hour (entering + leaving)
        return {"station, direction, hour": F[:, :, od, :], "station, hour": st_hr[:, od, :], "station, whole day": st_hr[:, od, :].sum(axis=2),
                "whole system, hour": st_hr[:, od, :].sum(axis=0), "whole system, whole day": st_hr[:, od, :].sum(axis=(0, 2))}
    lp, la, lb = levels(P), levels(A), levels(B)
    by_level = {k: {"model": wape(lp[k], la[k]), "last_week": wape(lb[k], la[k])} for k in la}

    # station-hour totals, grouped by how busy the hour really was
    sp, sa = lp["station, hour"].reshape(-1), la["station, hour"].reshape(-1)
    sb = lb["station, hour"].reshape(-1)
    by_volume = {}
    for label, lo, hi in (("under 100 riders", 0, 100), ("100 to 300", 100, 300), ("300 to 1,000", 300, 1000), ("1,000 to 3,000", 1000, 3000), ("over 3,000", 3000, 1e9)):
        k = (sa >= lo) & (sa < hi)
        by_volume[label] = {"model": wape(sp[k], sa[k]), "last_week": wape(sb[k], sa[k]), "noise_floor": noise_floor(sp[k]),
                            "share_of_riders": float(sa[k].sum() / sa.sum()), "station_hours": int(k.sum())}

    results[ty] = {
        "train_years": [2022, ty - 1], "station_hours": int(len(y)), "riders": int(c.Y[0][:, te, :].sum()),
        "all": three(np.ones(len(y), bool)), "ordinary_days": three(ordinary), "rainy_days": {**three(rainy), "station_days": int(rainy.sum() / 48)},
        "holidays": three(special),
        "mae": {"model": float(np.abs(p - y).mean()), "last_week": float(np.abs(b7 - y).mean()), "last_4_weeks": float(np.abs(b4 - y).mean())},
        "ordinary_days_by_level": by_level,
        "ordinary_days_by_volume": by_volume,
        "noise_floor": {"station, direction, hour": noise_floor(lp["station, direction, hour"].reshape(-1)), "station, hour": noise_floor(sp)},
    }
    r = results[ty]
    print(ty, "all", round(r["all"]["model"], 4), "| ordinary", round(r["ordinary_days"]["model"], 4), "| rainy", round(r["rainy_days"]["model"], 4),
          "| last week", round(r["all"]["last_week"], 4), flush=True)
    if ty == 2025:
        final_model = model
        joblib.dump({"model": model, "features": FULL, "config": {k: v for k, v in CONFIG.items() if k != "names"}}, CLEAN / "model_2025.joblib")
        print("  by level:", {k: round(v["model"], 4) for k, v in by_level.items()})
        print("  noise floor:", {k: round(v, 4) for k, v in r["noise_floor"].items()})
        for k, v in by_volume.items():
            print(f"  {k:>16}: model {v['model']:.3f}  last week {v['last_week']:.3f}  floor {v['noise_floor']:.3f}  riders {v['share_of_riders']:.0%}")

# ---- what rain does, according to the model: the same hours with the rain removed (2025)
te = c.year == 2025
X, y = design(c, te, FULL)
Xdry = X.copy()
for n in ("rain_h", "rain_3h", "rain_day"):
    Xdry[:, FULL.index(n)] = 0
p_wet, p_dry = final_model.predict(X), final_model.predict(Xdry)
hour, dow, rain_day = X[:, FULL.index("hour")], X[:, FULL.index("dow")], X[:, FULL.index("rain_day")]
commute = ((hour >= 6) & (hour < 9)) | ((hour >= 16) & (hour < 19))
groups = {"weekday commute (6-9am, 4-7pm)": (dow < 5) & commute, "weekday midday and evening": (dow < 5) & ~commute, "weekend": dow >= 5}
rain_effect = {}
for band, lo, hi in (("light rain, 1 to 5 mm", 1, 5), ("rainy, 5 to 20 mm", 5, 20), ("heavy rain, over 20 mm", 20, 1e9)):
    sel = (rain_day >= lo) & (rain_day < hi)
    rain_effect[band] = {"station_days": int(sel.sum() / 48)}
    for g, gm in groups.items():
        k = sel & gm
        if k.sum() < 48 * 20:
            continue
        rain_effect[band][g] = {"model_says": round(float(p_wet[k].sum() / p_dry[k].sum() - 1), 4),
                                "actually_happened": round(float(y[k].sum() / p_dry[k].sum() - 1), 4)}

(OUT / "backtest.json").write_text(json.dumps({"stations": c.stations, "features": FULL, "setup": CONFIG.get("label"), "layer1": results,
                                               "rain_effect_2025": rain_effect, "rainy_day_mm": RAINY_MM}, indent=1), encoding="utf-8")
print("hand check 12TH 2025-03-12 entries in array:", int(c.Y[0, c.sidx["12TH"], c.didx[pd.Timestamp("2025-03-12")]].sum()), "(raw file: 5953)")
print("wrote backtest.json. Next: python scripts/bart_events.py")
