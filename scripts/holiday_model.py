"""
A model for holidays only. It is anchored on the holidays themselves and answers two questions:
how deep does a holiday cut (or lift) ridership, and how many days either side does it reach?

It is trained only on days within 6 days of a holiday, from 2019 and 2021 onward, and it works in three
steps, each one handing its answer to the next:

  1. the whole system that day      riders against a clean recent level for that weekday
  2. each station that day          how far the station departs from the system (downtown offices empty, airports fill)
  3. each hour, in and out          how the day's shape changes (a holiday Monday looks like a Sunday)

"Clean recent level" = the median of the same weekday over the last 8 weeks, leaving out any week that was
itself near a holiday. Everything used is at least 7 days old, the same rule as the day model.

Test: walk-forward. The holiday model for 2025 never sees 2025. Inside the holiday window its forecast is
blended with the day model's; the blend weight and the reach are chosen on the earlier test years only.

Input:  data/clean/station_hour.csv.gz, pred_2023/2024/2025.npy (bart_model.py)
Output: public/data/holiday_model.json     results, reach and depth by holiday, the coming holidays
        public/data/holiday_factors.json   multipliers by station, direction and hour for the coming weeks
        data/clean/pred_hol_YYYY.npy       the day model's forecast with the holiday model blended in

Run:  python scripts/holiday_model.py
Use:  from holiday_model import holiday_factor
"""

import json
import warnings
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean"
OUT = ROOT / "public" / "data"
FACTORS = OUT / "holiday_factors.json"
REACH = 6                                    # days either side of a holiday the model is allowed to look
LIVE_FROM, LIVE_TO = "2026-11-21", "2027-01-10"
NAMES = ["New Year's Day", "MLK Day", "Presidents' Day", "Easter", "Memorial Day", "Juneteenth", "Independence Day", "Labor Day",
         "Columbus Day", "Halloween", "Veterans Day", "Thanksgiving", "Day after Thanksgiving", "Christmas Eve", "Christmas Day",
         "New Year's Eve", "Observed holiday"]
NONE = len(NAMES)
# holidays of the same kind share evidence: 0 = the system all but shuts, 1 = Monday federal holidays, 2 = fixed-date federal holidays,
# 3 = the days hanging off a big one, 4 = not a day off
KIND = {"New Year's Day": 0, "Thanksgiving": 0, "Christmas Day": 0, "MLK Day": 1, "Presidents' Day": 1, "Memorial Day": 1, "Labor Day": 1,
        "Columbus Day": 1, "Juneteenth": 2, "Independence Day": 2, "Veterans Day": 2, "Observed holiday": 2, "Day after Thanksgiving": 3,
        "Christmas Eve": 3, "New Year's Eve": 3, "Easter": 4, "Halloween": 4}
import os
# Set-up choices. Six combinations were compared on the 2023 and 2024 tests only; the defaults are the one that won there
# (11.25% against 11.32% to 11.45% for the others). 2025 took no part in the choice.
STAGE1 = os.environ.get("HOL_STAGE1", "both")          # "direct", "profile" or "both" (the average)
DRIFT = os.environ.get("HOL_DRIFT", "0") == "1"        # correct the clean level for how far it has lagged lately
KEEP_TOTALS = os.environ.get("HOL_TOTALS", "0") == "1"  # force each step to keep the total handed down by the step above


# ------------------------------------------------------------------ live use (reads the factors file only)

@lru_cache(maxsize=1)
def _factors():
    return json.loads(FACTORS.read_text(encoding="utf-8")) if FACTORS.exists() else {"stations": [], "days": {}}


def holiday_factor(date, stations):
    """
    Multipliers for one date, shape (2, len(stations), 24): [entering, leaving] x station x hour.
    1.0 everywhere when the date is not near a holiday (or is outside the weeks that were prepared).
    The multiplier is against an ORDINARY day of that weekday, so apply it to a forecast built from a
    reference day that is not a holiday.
    """
    f = _factors()
    out = np.ones((2, len(stations), 24), np.float32)
    day = f["days"].get(str(pd.Timestamp(date).date()))
    if not day:
        return out
    pos = {s: i for i, s in enumerate(f["stations"])}
    arr = np.asarray(day["factor"], np.float32)                      # (2, S, 24)
    for i, s in enumerate(stations):
        if s in pos:
            out[:, i, :] = arr[:, pos[s], :]
    return out


def holiday_note(date):
    """what the model expects for that date, in words-ready form, or None"""
    day = _factors()["days"].get(str(pd.Timestamp(date).date()))
    return {k: day[k] for k in ("anchor", "offset", "system_change")} if day else None


# ------------------------------------------------------------------ calendar

def anchors(y0=2019, y1=2027):
    """date -> holiday name"""
    from dateutil.easter import easter
    from pandas.tseries.holiday import USFederalHolidayCalendar
    out = {}
    floating = {"Birthday of Martin Luther King, Jr.": "MLK Day", "Washington's Birthday": "Presidents' Day", "Memorial Day": "Memorial Day",
                "Labor Day": "Labor Day", "Columbus Day": "Columbus Day", "Thanksgiving Day": "Thanksgiving"}
    for d, name in USFederalHolidayCalendar().holidays(f"{y0}-01-01", f"{y1}-12-31", return_name=True).items():
        if name in floating:
            out[d.normalize()] = floating[name]
            if name == "Thanksgiving Day":
                out[d.normalize() + pd.Timedelta(days=1)] = "Day after Thanksgiving"
    fixed = {"New Year's Day": (1, 1), "Juneteenth": (6, 19), "Independence Day": (7, 4), "Halloween": (10, 31), "Veterans Day": (11, 11),
             "Christmas Eve": (12, 24), "Christmas Day": (12, 25), "New Year's Eve": (12, 31)}
    observed = []
    for y in range(y0, y1 + 1):
        out[pd.Timestamp(easter(y))] = "Easter"
        for name, (m, dd) in fixed.items():
            if name == "Juneteenth" and y < 2021:
                continue
            d = pd.Timestamp(y, m, dd)
            out[d] = name
            if name in ("New Year's Day", "Juneteenth", "Independence Day", "Veterans Day", "Christmas Day") and d.weekday() >= 5:
                observed.append(d - pd.Timedelta(days=1) if d.weekday() == 5 else d + pd.Timedelta(days=1))
    for d in observed:
        out.setdefault(d, "Observed holiday")
    return out


def calendar_features(days):
    """one row per day; everything here is known years ahead"""
    anc = anchors(days[0].year, days[-1].year)
    n = len(days)
    aid = np.array([NAMES.index(anc[d]) if d in anc else NONE for d in days])
    dow = days.dayofweek.to_numpy()
    since, until = np.full(n, 10), np.full(n, 10)
    prev_id, next_id = np.full(n, NONE), np.full(n, NONE)
    prev_dow, next_dow = np.full(n, 7), np.full(n, 7)
    last = None
    for i in range(n):
        if aid[i] != NONE:
            last = i
        if last is not None and i - last <= 9:
            since[i], prev_id[i], prev_dow[i] = i - last, aid[last], dow[last]
    nxt = None
    for i in range(n - 1, -1, -1):
        if aid[i] != NONE:
            nxt = i
        if nxt is not None and nxt - i <= 9:
            until[i], next_id[i], next_dow[i] = nxt - i, aid[nxt], dow[nxt]
    is_a = aid != NONE
    yest, tom = np.roll(is_a, 1), np.roll(is_a, -1)
    bridge = (~is_a) & (((dow == 4) & yest) | ((dow == 0) & tom))          # the Friday after a Thursday holiday, the Monday before a Tuesday one
    xmas = np.full(n, 20)
    for i, d in enumerate(days):
        for y in (d.year - 1, d.year):
            k = (d - pd.Timestamp(y, 12, 25)).days
            if -10 <= k <= 12:
                xmas[i] = k
    season = (xmas >= -5) & (xmas <= 9)                                     # Dec 20 to Jan 3
    f = pd.DataFrame({"dow": dow, "since": since, "until": until, "prev_id": prev_id, "next_id": next_id, "prev_dow": prev_dow,
                      "next_dow": next_dow, "bridge": bridge.astype(int), "xmas_pos": xmas}, index=days)
    return f, aid, season


DAY_COLS = ["dow", "since", "until", "prev_id", "next_id", "prev_dow", "next_dow", "bridge", "xmas_pos", "commute"]
CAT_DAY = [DAY_COLS.index("prev_id"), DAY_COLS.index("next_id")]


def nearest(f, i):
    """(holiday name, signed offset) for row i: minus = days before the holiday"""
    r = f.iloc[i]
    if r["since"] <= r["until"]:
        return (NAMES[int(r["prev_id"])], int(r["since"])) if r["prev_id"] != NONE else (None, None)
    return NAMES[int(r["next_id"])], -int(r["until"])


# ------------------------------------------------------------------ training

def gbm(cat, **kw):
    from sklearn.ensemble import HistGradientBoostingRegressor
    p = dict(loss="absolute_error", max_iter=300, learning_rate=0.05, max_depth=4, min_samples_leaf=5, l2_regularization=1.0,
             categorical_features=cat, random_state=7)
    p.update(kw)
    return HistGradientBoostingRegressor(**p)


class Cascade:
    """system day -> station day -> station hour. Every step predicts a log ratio."""

    def fit(self, D, day_idx):
        d = np.asarray(day_idx)
        X1 = D["Xday"][d]
        # step 1 has two parts. First a profile: for each holiday and each day offset, the typical depth in past years,
        # recent years counting more. Then a small model on what is left (which weekday it fell on, bridge days, commuter share).
        yr = D["year"][d]
        w = 0.7 ** (yr.max() - yr)
        y1 = D["y1"][d]

        def wmedian(m):
            order = np.argsort(y1[m])
            cw = np.cumsum(w[m][order])
            return float(y1[m][order][np.searchsorted(cw, cw[-1] / 2)])

        # the profile is kept separately for weekdays and weekends (New Year's Day on a Saturday is a different thing from
        # New Year's Day on a Monday), and a holiday with few past examples leans on holidays of the same kind
        self.group = {int(k): wmedian(D["gkey"][d] == k) for k in np.unique(D["gkey"][d]) if k >= 0}
        self.profile = {}
        for k in np.unique(D["key"][d]):
            if k >= 0:
                m = D["key"][d] == k
                g = self.group.get(int(D["gkey"][d][m][0]))
                self.profile[int(k)] = wmedian(m) if g is None else (m.sum() * wmedian(m) + g) / (m.sum() + 1)
        self.m1 = gbm(CAT_DAY, max_iter=150, max_depth=3, min_samples_leaf=3).fit(X1, y1 - self._profile(D, d), sample_weight=w)
        self.m1d = gbm(CAT_DAY).fit(X1, y1)                                   # the same question asked directly, no profile
        f1 = self.f1(D, d)
        X2 = self._x2(D, d, f1)
        y2 = (D["y_sd"][:, d] - D["y1"][d][None, :]).ravel()
        self.m2 = gbm(CAT_DAY + [len(DAY_COLS)], max_iter=300, max_depth=6, min_samples_leaf=20).fit(X2, y2, sample_weight=D["B_sd"][:, d].ravel() + 20)
        f2 = self.m2.predict(X2).reshape(D["S"], len(d))
        X3 = self._x3(D, d, f1[None, :] + f2)
        scaled = D["B"][:, :, d, 5:] * np.exp(D["y_sd"][:, d])[None, :, :, None]
        y3 = np.log((D["A"][:, :, d, 5:] + 2) / (scaled + 2)).ravel()
        self.m3 = gbm(CAT_DAY + [len(DAY_COLS)], loss="squared_error", max_iter=200, learning_rate=0.1, max_depth=None, max_leaf_nodes=63,
                      min_samples_leaf=40).fit(X3, y3, sample_weight=D["B"][:, :, d, 5:].ravel() + 1)
        return self

    @staticmethod
    def _x2(D, d, f1):
        S, n = D["S"], len(d)
        day = np.broadcast_to(D["Xday"][d][None], (S, n, len(DAY_COLS))).reshape(S * n, -1)
        st = np.repeat(np.arange(S), n)
        return np.column_stack([day, st, D["st_commute"][:, d].ravel(), np.tile(f1, S)])

    @staticmethod
    def _x3(D, d, depth):
        S, n, H = D["S"], len(d), 19
        shape = (2, S, n, H)
        day = np.broadcast_to(D["Xday"][d][None, None, :, None, :], shape + (len(DAY_COLS),)).reshape(-1, len(DAY_COLS))
        g = lambda a, ax: np.broadcast_to(np.asarray(a, np.float32).reshape([-1 if i == ax else 1 for i in range(4)]), shape).ravel()
        stc = np.broadcast_to(D["st_commute"][:, d][None, :, :, None], shape).ravel()
        dep = np.broadcast_to(depth[None, :, :, None], shape).ravel()
        return np.column_stack([day, g(np.arange(S), 1), stc, dep, g(np.arange(5, 24), 3), g(np.arange(2), 0)]).astype(np.float32)

    def _profile(self, D, d):
        return np.array([self.profile.get(int(k), self.group.get(int(g), 0.0)) for k, g in zip(D["key"][d], D["gkey"][d])])

    def f1(self, D, day_idx):
        d = np.asarray(day_idx)
        direct = self.m1d.predict(D["Xday"][d])
        if STAGE1 == "direct":
            return direct
        prof = self._profile(D, d) + self.m1.predict(D["Xday"][d])
        return prof if STAGE1 == "profile" else (prof + direct) / 2

    def log_factors(self, D, day_idx):
        """f1 (n,), f2 (S, n), f3 (2, S, n, 19)"""
        d = np.asarray(day_idx)
        f1 = self.f1(D, d)
        f2 = self.m2.predict(self._x2(D, d, f1)).reshape(D["S"], len(d))
        f3 = self.m3.predict(self._x3(D, d, f1[None, :] + f2)).reshape(2, D["S"], len(d), 19)
        return f1, f2, f3

    def predict(self, D, day_idx):
        """riders, (2, S, n, 24)"""
        d = np.asarray(day_idx)
        f1, f2, f3 = self.log_factors(D, d)
        B = D["B"][:, :, d, :]
        b_sd = B.sum(axis=(0, 3))                                             # (S, n)
        # each step keeps the total handed down by the step above it
        t_sd = np.maximum((b_sd + 20) * np.exp(f1[None, :] + f2) - 20, 0)
        t_sd *= (b_sd.sum(axis=0) * np.exp(f1) / np.maximum(t_sd.sum(axis=0), 1e-9))[None, :]
        q = B * np.exp(f1[None, :] + f2)[None, :, :, None]
        q[..., 5:] = np.maximum((q[..., 5:] + 2) * np.exp(f3) - 2, 0)
        if KEEP_TOTALS:
            q *= (t_sd / np.maximum(q.sum(axis=(0, 3)), 1e-9))[None, :, :, None]
        return q


def load():
    sh = pd.read_csv(CLEAN / "station_hour.csv.gz", parse_dates=["date"])
    stations = sorted(sh["station"].unique())
    sidx = {s: i for i, s in enumerate(stations)}
    days = pd.date_range("2019-01-01", "2025-12-31", freq="D")
    didx = {d: i for i, d in enumerate(days)}
    S, n = len(stations), len(days)
    A = np.zeros((2, S, n, 24), np.float32)
    si, di, hi = sh["station"].map(sidx).to_numpy(), sh["date"].map(didx).to_numpy(), sh["hour"].to_numpy()
    A[0, si, di, hi], A[1, si, di, hi] = sh["entries"].to_numpy(), sh["exits"].to_numpy()

    all_days = pd.date_range("2019-01-01", "2027-12-31", freq="D")
    f, aid, season = calendar_features(all_days)
    missing = A.sum(axis=(0, 1, 3)) == 0
    is_a = aid[:n] != NONE
    near = is_a | np.roll(is_a, 1) | np.roll(is_a, 2) | np.roll(is_a, -1) | np.roll(is_a, -2)
    dirty = missing | near | season[:n]

    # clean recent level: median of the same weekday over the last 8 weeks, weeks near a holiday left out
    stack, count = [], np.zeros(n, int)
    for j in range(1, 9):
        k = 7 * j
        v = np.full_like(A, np.nan)
        v[:, :, k:, :] = A[:, :, :-k, :]
        bad = np.ones(n, bool)
        bad[k:] = dirty[:-k]
        v[:, :, bad, :] = np.nan
        count += ~bad
        stack.append(v)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        B = np.nanmedian(np.stack(stack), axis=0)
    del stack
    has_base = count >= 3
    B[:, :, ~has_base, :] = 0
    # the median looks about a month back, so it lags when ridership is climbing or the season is turning.
    # Correct it by how far it has been off on ordinary days lately (days 7 to 34 back).
    sa, sb = A.sum(axis=(0, 1, 3)), B.sum(axis=(0, 1, 3))
    plain = ~dirty & has_base & (sb > 0)
    drift = np.ones(n, np.float32)
    for i in range(35, n):
        w = np.arange(i - 34, i - 6)
        w = w[plain[w]]
        if len(w) >= 5:
            drift[i] = np.clip(np.median(sa[w] / sb[w]), 0.8, 1.25)
    if DRIFT:
        B *= drift[None, None, :, None]

    # how commuter-heavy the system and each station are, from the 7 weeks before last week (weekday riders per weekend rider)
    tot = A.sum(axis=(0, 3))                                                # (S, day)
    dow = days.dayofweek.to_numpy()
    commute, st_commute = np.full(n, np.nan, np.float32), np.full((S, n), np.nan, np.float32)
    for i in range(56, n):
        w = np.arange(i - 56, i - 6)
        w = w[~dirty[w]]
        wk, we = w[dow[w] < 5], w[dow[w] >= 5]
        if len(wk) >= 5 and len(we) >= 2:
            a, b = tot[:, wk].mean(axis=1), tot[:, we].mean(axis=1)
            commute[i] = a.sum() / max(b.sum(), 1)
            st_commute[:, i] = np.clip(a / np.maximum(b, 1), 0, 20)
    ok = ~missing & has_base & ~np.isnan(commute)
    commute_all = np.full(len(all_days), np.nanmean(commute[-60:]), np.float32)
    commute_all[:n] = np.where(np.isnan(commute), np.nanmean(commute[-60:]), commute)
    f["commute"] = commute_all
    st_last = np.nanmean(st_commute[:, -60:], axis=1)
    st_all = np.repeat(st_last[:, None], len(all_days), axis=1).astype(np.float32)
    st_all[:, :n] = np.where(np.isnan(st_commute), st_last[:, None], st_commute)

    window = ((f["since"] <= REACH) | (f["until"] <= REACH) | season).to_numpy()
    Bfull = np.zeros((2, S, len(all_days), 24), np.float32)
    Bfull[:, :, :n, :] = B
    Afull = np.zeros_like(Bfull)
    Afull[:, :, :n, :] = A
    a_sd, b_sd = Afull.sum(axis=(0, 3)), Bfull.sum(axis=(0, 3))
    with np.errstate(all="ignore"):
        y1 = np.log(np.maximum(a_sd.sum(axis=0), 1) / np.maximum(b_sd.sum(axis=0), 1))
        y_sd = np.log((a_sd + 20) / (b_sd + 20))
    okf = np.zeros(len(all_days), bool)
    okf[:n] = ok
    key, gkey = np.full(len(all_days), -1), np.full(len(all_days), -1)      # holiday x offset x weekday-or-weekend, for the profile
    wkend = (all_days.dayofweek.to_numpy() >= 5).astype(int)
    for i in range(len(all_days)):
        name, off = nearest(f, i)
        if name is not None and abs(off) <= REACH:
            key[i] = (NAMES.index(name) * 20 + off + REACH) * 2 + wkend[i]
            gkey[i] = (KIND[name] * 20 + off + REACH) * 2 + wkend[i]
    return dict(key=key, gkey=gkey, A=Afull, B=Bfull, S=S, n=n, days=all_days, stations=stations, f=f, aid=aid, season=season, window=window, ok=okf,
                Xday=f[DAY_COLS].to_numpy(np.float32), st_commute=st_all, y1=y1, y_sd=y_sd, B_sd=b_sd, year=all_days.year.to_numpy())


def wape(p, a):
    return float(np.abs(p - a).sum() / max(a.sum(), 1e-9))


def main():
    D = load()
    days, year, f = D["days"], D["year"], D["f"]
    r4 = lambda v: round(float(v), 4)
    train_ok = D["ok"] & D["window"]
    reach_of = np.minimum(f["since"].to_numpy(), f["until"].to_numpy())
    GRID_W, GRID_K = (0.0, 0.25, 0.5, 0.75, 1.0), (0, 1, 2, 3, 6)
    store, results = {}, {}

    for y in (2023, 2024, 2025):
        tr = np.where(train_ok & (year < y))[0]
        te = np.where(year == y)[0]
        casc = Cascade().fit(D, tr)
        win = np.where((year == y) & D["window"] & D["ok"])[0]
        q = casc.predict(D, win)
        P = np.load(CLEAN / f"pred_{y}.npy")
        A = D["A"][:, :, te, :]
        Q = P.copy()
        Q[:, :, win - te[0], :] = q
        store[y] = dict(P=P, Q=Q, A=A, te=te, win=win, casc=casc)
        print(f"{y}: trained on {len(tr)} holiday-window days, {len(win)} window days to forecast")

    def blended(y, w, k):
        s = store[y]
        use = np.zeros(len(s["te"]), bool)
        sel = s["win"][(reach_of[s["win"]] <= k) | D["season"][s["win"]]]
        use[sel - s["te"][0]] = True
        out = s["P"].copy()
        out[:, :, use, :] = (1 - w) * s["P"][:, :, use, :] + w * s["Q"][:, :, use, :]
        return out, use

    def abs_err(y, w, k):
        out, _ = blended(y, w, k)
        return float(np.abs(out.sum(0) - store[y]["A"].sum(0)).sum())

    # one line to compare set-ups on the two earlier years only (2025 is never used to choose anything)
    sel = sum(min(abs_err(p, w, k) for w in GRID_W for k in GRID_K) for p in (2023, 2024)) / sum(float(store[p]["A"].sum()) for p in (2023, 2024))
    print(f"SELECT stage1={STAGE1} drift={int(DRIFT)} totals={int(KEEP_TOTALS)}  best blend error 2023+2024: {sel:.4%}   "
          + "  ".join(f"{p} alone {wape(store[p]['Q'].sum(0)[:, store[p]['win'] - store[p]['te'][0]], store[p]['A'].sum(0)[:, store[p]['win'] - store[p]['te'][0]]):.2%}" for p in (2023, 2024, 2025)))

    for y in (2024, 2025):
        prior = [p for p in (2023, 2024) if p < y]
        best = min(((w, k) for w in GRID_W for k in GRID_K), key=lambda wk: sum(abs_err(p, *wk) for p in prior))
        s = store[y]
        out, use = blended(y, *best)
        np.save(CLEAN / f"pred_hol_{y}.npy", out.astype(np.float32))
        p, q, o, a = s["P"].sum(0), s["Q"].sum(0), out.sum(0), s["A"].sum(0)
        sysr = a.sum(axis=(0, 2)) / p.sum(axis=(0, 2)) - 1
        near3 = np.zeros(len(s["te"]), bool)
        near3[s["win"][(reach_of[s["win"]] <= 3) | D["season"][s["win"]]] - s["te"][0]] = True
        bad = near3 & (np.abs(sysr) > 0.10)
        sys_day = lambda x, m: float(np.mean(np.abs(x[:, m].sum(axis=(0, 2)) / a[:, m].sum(axis=(0, 2)) - 1)))
        rows = []
        for i in np.where(D["aid"][s["te"]] != NONE)[0]:
            if not D["ok"][s["te"][i]]:
                continue
            ad = a[:, i].sum()
            rows.append({"date": str(days[s["te"][i]].date()), "weekday": days[s["te"][i]].day_name()[:3], "holiday": NAMES[D["aid"][s["te"][i]]],
                         "actual_riders": int(ad), "day_model_off_by": r4(p[:, i].sum() / ad - 1), "holiday_model_off_by": r4(q[:, i].sum() / ad - 1),
                         "blend_off_by": r4(o[:, i].sum() / ad - 1), "day_model_hourly_error": r4(wape(p[:, i], a[:, i])),
                         "holiday_model_hourly_error": r4(wape(q[:, i], a[:, i])), "blend_hourly_error": r4(wape(o[:, i], a[:, i]))})
        results[str(y)] = {
            "chosen_on_earlier_years": {"weight_on_holiday_model": best[0], "reach_days": best[1], "years_used": prior},
            "days_changed": int(use.sum()),
            "hourly_error_on_those_days": {"day model": r4(wape(p[:, use], a[:, use])), "holiday model alone": r4(wape(q[:, use], a[:, use])), "blend": r4(wape(o[:, use], a[:, use]))},
            "system_daily_total_error_on_those_days": {"day model": r4(sys_day(p, use)), "holiday model alone": r4(sys_day(q, use)), "blend": r4(sys_day(o, use))},
            "holiday_days_that_were_10pct_off": {"days": int(bad.sum()), "day model": r4(wape(p[:, bad], a[:, bad])) if bad.any() else None,
                                                 "blend": r4(wape(o[:, bad], a[:, bad])) if bad.any() else None},
            "whole_year_hourly_error": {"day model": r4(wape(p, a)), "blend": r4(wape(o, a))},
            "grid_this_year_for_reference": {f"w{w} k{k}": r4(abs_err(y, w, k) / a.sum()) for w in GRID_W for k in GRID_K},
            "holidays": rows}
        r = results[str(y)]
        print(f"\n== {y}  chosen w={best[0]} reach={best[1]} (on {prior})  days changed {r['days_changed']}")
        print("   hourly error on those days:", r["hourly_error_on_those_days"])
        print("   system daily total error:  ", r["system_daily_total_error_on_those_days"])
        print("   holiday days 10%+ off:     ", r["holiday_days_that_were_10pct_off"])
        print("   whole year:                ", r["whole_year_hourly_error"])
        for h in rows:
            print(f"     {h['date']} {h['weekday']} {h['holiday']:<24} day model {h['day_model_off_by']:+.1%}  holiday model {h['holiday_model_off_by']:+.1%}  blend {h['blend_off_by']:+.1%}"
                  f"   hourly {h['day_model_hourly_error']:.1%} -> {h['blend_hourly_error']:.1%}")

    # ---- final model on everything, for the coming holidays and the reach-and-depth table
    all_tr = np.where(train_ok)[0]
    final = Cascade().fit(D, all_tr)
    f1_fit = final.f1(D, all_tr)
    table = {}
    for j, i in enumerate(all_tr):
        name, off = nearest(f, i)
        if name is None or abs(off) > REACH:
            continue
        table.setdefault(name, {}).setdefault(off, []).append((float(D["y1"][i]), float(f1_fit[j])))
    reach = {}
    for name, offs in table.items():
        row = {str(o): {"measured": r4(np.exp(np.median([a for a, _ in v])) - 1), "model": r4(np.exp(np.mean([b for _, b in v])) - 1), "days": len(v)} for o, v in sorted(offs.items())}
        # reach = the unbroken run of days around the holiday that sit 8% or more below an ordinary day
        lo = hi = 0
        while str(lo - 1) in row and row[str(lo - 1)]["model"] <= -0.08:
            lo -= 1
        while str(hi + 1) in row and row[str(hi + 1)]["model"] <= -0.08:
            hi += 1
        reach[name] = {"by_offset": row, "deepest": min(row.items(), key=lambda kv: kv[1]["model"])[0], "reaches_from": lo, "reaches_to": hi}

    # coming holidays: there are no recent counts for those dates, so stand on the latest clean level for each weekday
    live = np.where((days >= LIVE_FROM) & (days <= LIVE_TO) & D["window"])[0]
    last_ok = {w: max(i for i in np.where(D["ok"])[0] if days[i].dayofweek == w) for w in range(7)}
    for i in live:
        D["B"][:, :, i, :] = D["B"][:, :, last_ok[days[i].dayofweek], :]
    f1, f2, f3 = final.log_factors(D, live)
    q_live = final.predict(D, live)
    out_days, coming = {}, []
    for j, i in enumerate(live):
        fac = (q_live[:, :, j, :] + 0.5) / (D["B"][:, :, i, :] + 0.5)
        fac[:, :, :5] = np.exp(f1[j] + f2[:, j])[None, :, None]
        name, off = nearest(f, i)
        out_days[str(days[i].date())] = {"anchor": name, "offset": off, "system_change": r4(np.exp(f1[j]) - 1), "factor": np.round(np.clip(fac, 0.05, 4), 2).tolist()}
        coming.append({"date": str(days[i].date()), "weekday": days[i].day_name()[:3], "holiday": name, "days_from_it": off, "system_change": r4(np.exp(f1[j]) - 1),
                       "stations_most_down": [D["stations"][s] for s in np.argsort(f2[:, j])[:3]], "stations_least_down": [D["stations"][s] for s in np.argsort(-f2[:, j])[:3]]})
    FACTORS.write_text(json.dumps({"what": "multiplier against an ordinary day of that weekday; [entering, leaving] x station x hour", "stations": D["stations"],
                                   "from": LIVE_FROM, "to": LIVE_TO, "days": out_days}), encoding="utf-8")
    (OUT / "holiday_model.json").write_text(json.dumps({
        "what": "a model trained only on days within 6 days of a holiday: system day, then station day, then station hour",
        "trained_on": {"years": "2019, 2021 to the year before the test year", "window_days_in_final_model": int(len(all_tr)), "holidays": NAMES[:-1]},
        "test": results, "reach_and_depth": reach, "coming": coming}, indent=1), encoding="utf-8")
    print("\n== reach and depth (system riders against an ordinary day; model, final fit)")
    for name in NAMES:
        if name in reach:
            r = reach[name]
            print(f"  {name:<24} reach {r['reaches_from']:+d} to {r['reaches_to']:+d}  ", " ".join(f"{o}:{v['model']:+.0%}" for o, v in r["by_offset"].items()))
    print("\n== coming")
    for c in coming:
        print(f"  {c['date']} {c['weekday']} {str(c['holiday']):<24} {c['days_from_it']:+d}  system {c['system_change']:+.1%}  most down {c['stations_most_down']}  least {c['stations_least_down']}")


if __name__ == "__main__":
    main()
