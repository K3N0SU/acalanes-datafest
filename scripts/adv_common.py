"""Shared helpers for the advanced experiments (adv_*.py). Uses only ridership >= 7 days before the target day."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from bart_core import CLEAN, ROOT, load, wape

def day_idx(c, year):
    return np.where(c.year == year)[0]

def inputs(c, di):
    """hist (2,S,n,8,24) raw riders on d-7..d-56, level (2,S,n), ctx dict. Lags only reach back, never forward."""
    assert di.min() >= 56
    hist = np.stack([c.Y[:, :, di - 7 * (j + 1), :] for j in range(8)], axis=3)
    level = hist.sum(axis=4).mean(axis=3) / 24.0
    rain_s = np.stack([c.F["rain_day"][0, s, di, 0] for s in range(c.S)])
    tmax_s = np.stack([np.nan_to_num(c.F["tmax_day"][0, s, di, 0], nan=15.0) for s in range(c.S)])
    ctx = dict(dow=c.dser.dt.dayofweek.to_numpy()[di], month=c.dser.dt.month.to_numpy()[di] - 1,
               special=c.special[di].astype(np.float32), rain=rain_s, tmax=tmax_s)
    return hist, level, ctx
