"""
Shared data loading and feature building for the BART model scripts.

One row = one station, one date, one hour, one direction (entering or leaving).
Every feature uses only what is known at least a week ahead, except weather, which is
the weather of the hour itself (observed in tests, forecast in live use).
"""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

from weather import STATION_ZONE

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean"
START, END = "2021-01-01", "2025-12-31"

BASE = ["lag7", "lag14", "lag21", "lag28", "mean8", "med8", "lag364", "hour", "dow", "month",
        "holiday", "day_after_tg", "xmas_week", "station", "kind"]
WEATHER = ["rain_h", "rain_3h", "rain_day", "rain_day_lag7", "tmax_day", "wind_max_day"]
TOURISM = ["tour_idx"]
EXTRA = ["std8", "ewm8", "lag7_prev_hour", "lag7_next_hour", "day_total_lag7", "day_total_4wk", "station_trend",
         "system_trend", "yoy_growth", "lag364_grown", "lag7_was_special", "lag364_was_special", "week_of_year"]
AIRPORTS = ["SFIA", "OAKL"]


def load():
    sh = pd.read_csv(CLEAN / "station_hour.csv.gz", parse_dates=["date"])
    sh = sh[(sh["date"] >= START) & (sh["date"] <= END)]
    stations = sorted(sh["station"].unique())
    sidx = {s: i for i, s in enumerate(stations)}
    days = pd.date_range(START, END, freq="D")
    didx = {d: i for i, d in enumerate(days)}
    S, D = len(stations), len(days)

    Y = np.zeros((2, S, D, 24), dtype=np.float32)
    si, di, hi = sh["station"].map(sidx).to_numpy(), sh["date"].map(didx).to_numpy(), sh["hour"].to_numpy()
    Y[0, si, di, hi] = sh["entries"].to_numpy()
    Y[1, si, di, hi] = sh["exits"].to_numpy()

    def lag(n):
        out = np.full_like(Y, np.nan)
        out[:, :, n:, :] = Y[:, :, :-n, :]
        return out

    L = {n: lag(n) for n in (7, 14, 21, 28, 35, 42, 49, 56)}
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            stack8 = np.stack([L[n] for n in (7, 14, 21, 28, 35, 42, 49, 56)])
            mean8, med8, mean4 = np.nanmean(stack8, axis=0), np.nanmedian(stack8, axis=0), np.nanmean(stack8[:4], axis=0)
    del stack8

    dser = pd.Series(days)
    hol = set(USFederalHolidayCalendar().holidays(START, "2027-12-31").normalize())
    is_hol = dser.isin(hol).to_numpy()
    tg = {d for d in hol if d.month == 11 and d.weekday() == 3}
    day_after_tg = dser.isin({d + pd.Timedelta(days=1) for d in tg}).to_numpy()
    xmas = (((dser.dt.month == 12) & (dser.dt.day >= 24)) | ((dser.dt.month == 1) & (dser.dt.day == 1))).to_numpy()

    def bcast(a, axis):
        shape = [1, 1, 1, 1]
        shape[axis] = len(a)
        return np.broadcast_to(np.asarray(a, dtype=np.float32).reshape(shape), Y.shape)

    F = {
        "lag7": L[7], "lag14": L[14], "lag21": L[21], "lag28": L[28], "mean8": mean8, "med8": med8, "lag364": lag(364),
        "hour": bcast(np.arange(24), 3), "dow": bcast(dser.dt.dayofweek.to_numpy(), 2), "month": bcast(dser.dt.month.to_numpy(), 2),
        "holiday": bcast(is_hol, 2), "day_after_tg": bcast(day_after_tg, 2), "xmas_week": bcast(xmas, 2),
        "station": bcast(np.arange(S), 1), "kind": bcast(np.arange(2), 0),
    }

    # ---- weather, by zone, mapped to stations
    zones = sorted(set(STATION_ZONE.values()))
    wz = {}
    wpath = CLEAN / "weather.csv"
    if wpath.exists():
        w = pd.read_csv(wpath, parse_dates=["date"])
        w = w[w["date"].isin(didx)]
        for z in zones:
            g = w[w["zone"] == z]
            rain = np.zeros((D, 24), np.float32); temp = np.full((D, 24), np.nan, np.float32); wind = np.zeros((D, 24), np.float32)
            gi, gh = g["date"].map(didx).to_numpy(), g["hour"].to_numpy()
            rain[gi, gh], temp[gi, gh], wind[gi, gh] = g["rain_mm"], g["temp_c"], g["wind_kmh"]
            wz[z] = weather_features(rain, temp, wind)
        st_zone = [STATION_ZONE.get(s, "oakland") for s in stations]
        for name in WEATHER:
            per_station = np.stack([wz[z][name] for z in st_zone])  # (S, D, 24)
            F[name] = np.broadcast_to(per_station[None], Y.shape)

    # ---- tourism index: airport-station riders 8 to 14 days back, against their own past year
    air = Y[:, [sidx[a] for a in AIRPORTS if a in sidx]].sum(axis=(0, 1, 3))  # per day
    cs = np.concatenate([[0], np.cumsum(air)])
    tour = np.full(D, np.nan, np.float32)
    for d in range(372, D):
        recent = (cs[d - 7] - cs[d - 14]) / 7
        year = (cs[d - 7] - cs[d - 371]) / 364
        tour[d] = recent / year if year > 0 else np.nan
    F["tour_idx"] = bcast(np.nan_to_num(tour, nan=1.0), 2)

    # ---- second-generation inputs (see EXTRA). All use data at least 7 days old.
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        s8 = np.stack([L[n] for n in (7, 14, 21, 28, 35, 42, 49, 56)])
        F["std8"] = np.nanstd(s8, axis=0)
        wts = (0.6 ** np.arange(8)).astype(np.float32).reshape(8, 1, 1, 1, 1)
        ok = ~np.isnan(s8)
        F["ewm8"] = (np.where(ok, s8, 0) * wts).sum(axis=0) / np.maximum((ok * wts).sum(axis=0), 1e-9)
        del s8, ok
    # the hour before and after, last week (rushes drift by an hour)
    prev_h = np.full_like(Y, np.nan); prev_h[..., 1:] = L[7][..., :-1]
    next_h = np.full_like(Y, np.nan); next_h[..., :-1] = L[7][..., 1:]
    F["lag7_prev_hour"], F["lag7_next_hour"] = prev_h, next_h

    def window(cs, a, b):
        """sum over days [d-a, d-b) for every day d, along the last axis of a cumulative sum"""
        out = np.full(cs.shape[:-1] + (D,), np.nan, np.float32)
        out[..., a:] = cs[..., a - b:D - b] - cs[..., :D - a]
        return out

    day_tot = Y.sum(axis=3)                                   # (2, S, D)
    cs_k = np.concatenate([np.zeros((2, S, 1), np.float32), np.cumsum(day_tot, axis=2)], axis=2)
    st_tot = day_tot.sum(axis=0)                              # (S, D)
    cs_s = np.concatenate([np.zeros((S, 1), np.float32), np.cumsum(st_tot, axis=1)], axis=1)
    cs_sys = np.concatenate([[0], np.cumsum(st_tot.sum(axis=0))]).astype(np.float64)[None]

    day_lag7 = np.full_like(day_tot, np.nan); day_lag7[:, :, 7:] = day_tot[:, :, :-7]
    F["day_total_lag7"] = np.broadcast_to(day_lag7[..., None], Y.shape)
    F["day_total_4wk"] = np.broadcast_to((window(cs_k, 34, 6) / 28)[..., None], Y.shape)
    with np.errstate(all="ignore"):
        st_trend = window(cs_s, 13, 6) / (window(cs_s, 69, 13) / 8)          # last week vs the 8 weeks before
        sys_trend = window(cs_sys, 13, 6) / (window(cs_sys, 69, 13) / 8)
        yoy = window(cs_s, 34, 6) / window(cs_s, 398, 370)                  # last 4 weeks vs the same 4 weeks a year ago
    st_trend = np.clip(np.nan_to_num(st_trend, nan=1.0, posinf=1.0), 0.3, 3)
    yoy = np.clip(np.nan_to_num(yoy, nan=1.0, posinf=1.0), 0.3, 3)
    F["station_trend"] = np.broadcast_to(st_trend[None, :, :, None], Y.shape)
    F["system_trend"] = bcast(np.clip(np.nan_to_num(sys_trend[0], nan=1.0), 0.3, 3), 2)
    F["yoy_growth"] = np.broadcast_to(yoy[None, :, :, None], Y.shape)
    F["lag364_grown"] = F["lag364"] * F["yoy_growth"]         # last year's value, brought up to this year's level
    special = is_hol | day_after_tg | xmas
    F["lag7_was_special"] = bcast(np.concatenate([np.zeros(7, bool), special[:-7]]), 2)
    F["lag364_was_special"] = bcast(np.concatenate([np.zeros(364, bool), special[:-364]]), 2)
    F["week_of_year"] = bcast(dser.dt.isocalendar().week.to_numpy().astype(np.float32), 2)

    return SimpleNamespace(Y=Y, F=F, stations=stations, sidx=sidx, days=days, didx=didx, S=S, D=D, dser=dser,
                           year=dser.dt.year.to_numpy(), is_hol=is_hol, special=(is_hol | day_after_tg | xmas),
                           lag7=L[7], mean4=mean4, wz=wz, st_zone=[STATION_ZONE.get(s, "oakland") for s in stations],
                           tour=tour, has_weather=bool(wz))


def weather_features(rain, temp, wind):
    """rain/temp/wind are (days, 24). returns the model's weather features, each (days, 24)"""
    D = rain.shape[0]
    flat = rain.reshape(-1)
    r3 = flat + np.concatenate([[0], flat[:-1]]) + np.concatenate([[0, 0], flat[:-2]])
    day_total = rain.sum(axis=1)
    lag7 = np.concatenate([np.zeros(7, np.float32), day_total[:-7]]) if D > 7 else np.zeros(D, np.float32)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tmax = np.nanmax(temp, axis=1)
    rep = lambda v: np.repeat(np.asarray(v, np.float32)[:, None], 24, axis=1)
    return {"rain_h": rain.astype(np.float32), "rain_3h": r3.reshape(D, 24).astype(np.float32), "rain_day": rep(day_total),
            "rain_day_lag7": rep(lag7), "tmax_day": rep(tmax), "wind_max_day": rep(wind.max(axis=1))}


def design(c, day_mask, names):
    X = np.column_stack([c.F[n][:, :, day_mask, :].reshape(-1) for n in names])
    y = c.Y[:, :, day_mask, :].reshape(-1)
    return X, y


def wape(pred, act):
    return float(np.abs(np.asarray(pred) - np.asarray(act)).sum() / np.asarray(act).sum())


class Blend:
    """weighted average of fitted members that share one input list.
    A member trained on the ratio target predicts riders / (recent average + 1) and is scaled back here."""

    def __init__(self, models, weights, targets=None, scale_col=None):
        self.models, self.weights = models, weights
        self.targets = targets or ["raw"] * len(models)
        self.scale_col = scale_col

    def predict(self, X):
        out = 0
        targets = getattr(self, "targets", None) or ["raw"] * len(self.models)  # models saved before targets existed
        for m, w, t in zip(self.models, self.weights, targets):
            p = m.predict(X)
            if t == "ratio":
                p = p * (np.nan_to_num(X[:, self.scale_col]) + 1)
            out = out + w * p
        return np.maximum(out, 0)


def members_of(config):
    """normalise both config shapes to a list of members and weights"""
    if "members" in config:
        return config["members"], config["weights"]
    b = config.get("blend")
    first = {k: v for k, v in config.items() if k not in ("label", "blend")}
    if b and b.get("with") == "second":
        return [first, b["second"]], [b["weight"], 1 - b["weight"]]
    return [first], [1.0]


def fit_member(c, cfg, names, test_year):
    """one member, trained on days from cfg['train_from'] (default 2022) up to the year before test_year"""
    from sklearn.ensemble import HistGradientBoostingRegressor
    start = pd.Timestamp(cfg.get("train_from", "2022-01-01"))
    mask = (c.dser >= start).to_numpy() & (c.year < test_year)
    X, y = design(c, mask, names)
    kw = {k: v for k, v in cfg.items() if k not in ("names", "label", "blend", "loss", "target", "train_from")}
    p = dict(max_iter=300, learning_rate=0.08, max_leaf_nodes=63, random_state=7)
    p.update(kw)
    m = HistGradientBoostingRegressor(loss=cfg.get("loss", "poisson"), categorical_features=[names.index("station")], **p)
    if cfg.get("target") == "ratio":
        scale = np.nan_to_num(X[:, names.index("ewm8")]) + 1
        return m.fit(X, y / scale, sample_weight=scale)   # weighted absolute error on the ratio = absolute error in riders
    return m.fit(X, y)


def fit_model(c, config, test_year):
    names = config["names"]
    members, weights = members_of(config)
    models = [fit_member(c, m, names, test_year) for m in members]
    return Blend(models, weights, [m.get("target", "raw") for m in members], names.index("ewm8") if "ewm8" in names else None)
