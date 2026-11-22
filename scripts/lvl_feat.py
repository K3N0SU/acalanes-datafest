"""Level-model feature builders. Every ridership-derived input is a shift of >= 7 days."""
import os
os.environ["OMP_NUM_THREADS"] = "4"
os.environ["OPENBLAS_NUM_THREADS"] = "4"
import warnings
import numpy as np


def shift(a, n):
    """value n days ago along axis 0 (days); NaN where unavailable"""
    out = np.full(a.shape, np.nan, dtype=np.float64)
    out[n:] = a[:-n]
    return out


def win_mean(dt, a, b):
    """mean of days d-a .. d-b inclusive along axis 0 (a > b >= 7); NaN where short"""
    cs = np.concatenate([np.zeros((1,) + dt.shape[1:]), np.cumsum(dt, axis=0)], axis=0)
    D = dt.shape[0]
    out = np.full(dt.shape, np.nan)
    d = np.arange(a, D)
    out[d] = (cs[d - b + 1] - cs[d - a]) / (a - b + 1)
    return out


def core_feats(X):
    f = {}
    L = {n: shift(X, n) for n in (7, 14, 21, 28, 35, 42, 49, 56)}
    st = np.stack([L[n] for n in L])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        f["lag7"], f["lag14"], f["lag21"], f["lag28"] = L[7], L[14], L[21], L[28]
        f["mean8"], f["med8"] = np.nanmean(st, 0), np.nanmedian(st, 0)
        f["std8"] = np.nanstd(st, 0)
        w = (0.6 ** np.arange(8)).reshape((8,) + (1,) * X.ndim)
        ok = ~np.isnan(st)
        f["ewm8"] = (np.where(ok, st, 0) * w).sum(0) / np.maximum((ok * w).sum(0), 1e-9)
    f["lag364"] = shift(X, 364)
    return f


def trend_feats(dtot):
    with np.errstate(all="ignore"):
        tr = win_mean(dtot, 13, 7) / win_mean(dtot, 69, 14)
        w34 = win_mean(dtot, 34, 7)
        yoy = w34 / shift(w34, 364)
    tr = np.clip(np.nan_to_num(tr, nan=1.0, posinf=1.0), 0.3, 3)
    yoy = np.clip(np.nan_to_num(yoy, nan=1.0, posinf=1.0), 0.3, 3)
    return tr, yoy, win_mean(dtot, 34, 7), shift(dtot, 7)


def calendar(c):
    d = c.dser
    h = c.is_hol.astype(float)
    cal = dict(dow=d.dt.dayofweek.to_numpy().astype(float), month=d.dt.month.to_numpy().astype(float),
               week=d.dt.isocalendar().week.to_numpy().astype(float), holiday=h,
               hol_yest=np.concatenate([[0], h[:-1]]), hol_tomo=np.concatenate([h[1:], [0]]),
               after_tg=c.F["day_after_tg"][0, 0, :, 0].astype(float), xmas=c.F["xmas_week"][0, 0, :, 0].astype(float))
    sp = c.special.astype(float)
    cal["lag7_special"] = np.concatenate([np.zeros(7), sp[:-7]])
    cal["lag364_special"] = np.concatenate([np.zeros(364), sp[:-364]])
    return cal


def weather_day(c):
    zs = list(c.wz.values())
    m = lambda k: np.mean([z[k] for z in zs], axis=0).astype(float)
    return dict(rain_h=m("rain_h"), rain_3h=m("rain_3h"), rain_day=m("rain_day")[:, 0], rain_day_lag7=m("rain_day_lag7")[:, 0],
                tmax=m("tmax_day")[:, 0], wind=m("wind_max_day")[:, 0])


def sys_features(Ys, cal, wx):
    """Ys (D,24) system riders -> names, matrix (D*24,k), dict of (D,24) arrays"""
    f = core_feats(Ys)
    dt = Ys.sum(1)
    tr, yoy, dt4, dt7 = trend_feats(dt)
    D = Ys.shape[0]
    rep = lambda v: np.repeat(np.asarray(v, float)[:, None], 24, axis=1)
    prev = np.full((D, 24), np.nan); prev[:, 1:] = f["lag7"][:, :-1]
    nxt = np.full((D, 24), np.nan); nxt[:, :-1] = f["lag7"][:, 1:]
    f.update(lag7_prev=prev, lag7_next=nxt, dt_lag7=rep(dt7), dt_4wk=rep(dt4), trend=rep(tr), yoy=rep(yoy),
             lag364_grown=f["lag364"] * rep(yoy), hour=np.tile(np.arange(24.0), (D, 1)))
    for k, v in cal.items():
        f[k] = rep(v)
    f.update(rain_h=wx["rain_h"], rain_3h=wx["rain_3h"], rain_day=rep(wx["rain_day"]), rain_day_lag7=rep(wx["rain_day_lag7"]),
             tmax=rep(wx["tmax"]), wind=rep(wx["wind"]))
    names = list(f)
    return names, np.column_stack([f[n].reshape(-1) for n in names]), f


def stn_features(T, cal, wxs):
    """T (S,D) station daily totals. rows station-major (S*D)."""
    S, D = T.shape
    Tt = T.T
    f = core_feats(Tt)
    tr, yoy, dt4, dt7 = trend_feats(Tt)
    str_ = trend_feats(T.sum(0))[0]
    f.update(dt_lag7=dt7, dt_4wk=dt4, trend=tr, yoy=yoy, lag364_grown=f["lag364"] * yoy)
    f["sys_trend"] = np.repeat(str_[:, None], S, axis=1)
    rep = lambda v: np.repeat(np.asarray(v, float)[:, None], S, axis=1)
    for k, v in cal.items():
        f[k] = rep(v)
    f["station"] = np.tile(np.arange(S, dtype=float), (D, 1))
    f.update(rain_day=wxs["rain_day"], tmax=wxs["tmax"], wind=wxs["wind"])
    names = list(f)
    return names, np.column_stack([f[n].T.reshape(-1) for n in names]), f
