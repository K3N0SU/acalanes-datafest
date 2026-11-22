"""Level models + reconciliation. Choices on 2024 (train < 2024); 2025 scored once at the end (train < 2025)."""
import os, sys, json, time, itertools
os.environ["OMP_NUM_THREADS"] = "4"
os.environ["OPENBLAS_NUM_THREADS"] = "4"
sys.path.insert(0, "scripts")
import numpy as np
from bart_core import load, wape, CLEAN
from lvl_feat import sys_features, stn_features, calendar, weather_day
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

t0 = time.time()
c = load()
print("loaded", round(time.time() - t0), flush=True)
Y = c.Y.astype(np.float64)
S, D = c.S, c.D
year = c.year
ordn = ~c.special
cal = calendar(c)
wx = weather_day(c)
wxs = {k: np.stack([c.F[nm][0, s, :, 0] for s in range(S)], axis=1).astype(float)
       for k, nm in (("rain_day", "rain_day"), ("tmax", "tmax_day"), ("wind", "wind_max_day"))}
Ys = Y.sum((0, 1))
T = Y.sum((0, 3))
yidx = {y: np.where(year == y)[0] for y in (2023, 2024, 2025)}
P = {y: np.load(CLEAN / f"pred_{y}.npy").astype(np.float64) for y in (2023, 2024, 2025)}
A = {y: np.load(CLEAN / f"adv_pred_{y}.npy").astype(np.float64) for y in (2024, 2025)}


def lv(p, y, m):
    pt, yt = p.sum(0)[:, m], y.sum(0)[:, m]
    return dict(station_hour=wape(pt, yt), station_day=wape(pt.sum(2), yt.sum(2)), system_hour=wape(pt.sum(0), yt.sum(0)),
                system_day=wape(pt.sum((0, 2)), yt.sum((0, 2))))


def yy(y):
    return Y[:, :, yidx[y], :]


def full(p, y, m):
    d = lv(p, y, m)
    d["cells_ordinary"] = wape(p[:, :, m], y[:, :, m])
    d["cells_all"] = wape(p, y)
    return d


R = {"baseline": {}}
for nm, arr, y in (("trees_2025", P[2025], 2025), ("adv_2025", A[2025], 2025), ("trees_2024", P[2024], 2024), ("adv_2024", A[2024], 2024)):
    R["baseline"][nm] = full(arr, yy(y), ordn[yidx[y]])
    print(nm, {k: round(v, 4) for k, v in R["baseline"][nm].items()}, flush=True)

# ---- leakage test
rng = np.random.default_rng(0)
d0 = 1500
Y2 = Ys.copy(); Y2[d0:] = rng.random((D - d0, 24)) * 1e5
_, _, fa = sys_features(Ys, cal, wx)
_, _, fb = sys_features(Y2, cal, wx)
T2 = T.copy(); T2[:, d0:] = rng.random((S, D - d0)) * 1e4
_, _, ga = stn_features(T, cal, wxs)
_, _, gb = stn_features(T2, cal, wxs)
leak = []
for nm_, a_, b_ in (("system-hour", fa, fb), ("station-day", ga, gb)):
    bad = [k for k in a_ if not np.allclose(a_[k][:d0 + 7], b_[k][:d0 + 7], equal_nan=True)]
    leak.append(f"{nm_} inputs for every day before day d0+7 are unchanged when all ridership from day d0 onward is overwritten with noise: "
                + ("FAIL " + str(bad) if bad else "pass (so no input for day d uses ridership newer than d-7)"))
print(leak, flush=True)


def fit_hgb(X, y, scale, cfg, cat=None):
    p = dict(max_iter=300, learning_rate=0.06, max_leaf_nodes=15, min_samples_leaf=20, random_state=7)
    p.update(cfg["p"])
    m = HistGradientBoostingRegressor(loss=cfg["loss"], categorical_features=cat, **p)
    return m.fit(X, y / scale, sample_weight=scale) if cfg["target"] == "ratio" else m.fit(X, y)


def pred_hgb(m, X, scale, cfg):
    p = m.predict(X)
    return np.maximum(p * scale if cfg["target"] == "ratio" else p, 0)


def best_blend(members, y_, m_, step=0.1):
    names = list(members)
    best = (9, None)
    grid = np.arange(0, 1 + 1e-9, step)
    for w in itertools.product(grid, repeat=len(names) - 1):
        if sum(w) > 1 + 1e-9:
            continue
        ws = list(w) + [1 - sum(w)]
        p = sum(wi * members[n] for wi, n in zip(ws, names))
        e = wape(p[m_], y_[m_])
        if e < best[0]:
            best = (e, {n: round(float(x), 2) for n, x in zip(names, ws)})
    return best[1], best[0]


CFGS = {"abs_ratio": dict(loss="absolute_error", target="ratio", p={}),
        "abs_ratio_big": dict(loss="absolute_error", target="ratio", p=dict(max_leaf_nodes=31, max_iter=400, learning_rate=0.04)),
        "pois": dict(loss="poisson", target="raw", p={}),
        "pois_big": dict(loss="poisson", target="raw", p=dict(max_leaf_nodes=31, max_iter=400, learning_rate=0.04, l2_regularization=1.0)),
        "abs_small": dict(loss="absolute_error", target="ratio", p=dict(max_leaf_nodes=7, max_iter=500, min_samples_leaf=40))}

# ======================= SYSTEM-HOUR =======================
snames, SX, SF = sys_features(Ys, cal, wx)
sday = np.repeat(np.arange(D), 24)
sscale = np.nan_to_num(SX[:, snames.index("med8")]) + 1
sy = Ys.reshape(-1)


def ridge_X(rows):
    base = np.column_stack([np.log1p(SF[k].reshape(-1)) for k in
                            ("lag7", "lag14", "lag21", "lag28", "mean8", "med8", "ewm8", "lag364_grown", "lag7_prev", "lag7_next", "dt_4wk")])
    base = np.where(np.isnan(base), np.nanmean(base[rows], 0), base)
    hr = SF["hour"].reshape(-1).astype(int)
    dw = SF["dow"].reshape(-1).astype(int)
    kind = np.minimum((dw >= 5).astype(int) + 2 * (SF["holiday"].reshape(-1) > 0), 2)
    oh = np.zeros((len(hr), 72)); oh[np.arange(len(hr)), hr * 3 + kind] = 1
    dwoh = np.zeros((len(hr), 7)); dwoh[np.arange(len(hr)), dw] = 1
    ex = np.column_stack([SF[k].reshape(-1) for k in ("holiday", "hol_yest", "hol_tomo", "after_tg", "xmas", "rain_h", "rain_3h", "rain_day",
                                                       "tmax", "wind", "lag7_special")])
    Xr = np.column_stack([base, oh, dwoh, ex, base[:, [0, 5]] * (hr[:, None] >= 0)])
    mu, sd = Xr[rows].mean(0), Xr[rows].std(0) + 1e-9
    return (Xr - mu) / sd


def sys_models(ty, cfgs, which=None):
    tr = (year[sday] >= 2022) & (year[sday] < ty)
    te = year[sday] == ty
    out = {}
    for nm, cfg in cfgs.items():
        if which and nm not in which:
            continue
        out[nm] = pred_hgb(fit_hgb(SX[tr], sy[tr], sscale[tr], cfg), SX[te], sscale[te], cfg)
    Xr = ridge_X(tr)
    for a in (1.0, 30.0):
        nm = f"ridge_a{a:g}"
        if which and nm not in which:
            continue
        out[nm] = np.expm1(Ridge(alpha=a).fit(Xr[tr], np.log1p(sy[tr])).predict(Xr[te]))
    return {k: v.reshape(-1, 24) for k, v in out.items()}


m24 = ordn[yidx[2024]]
y24s = Ys[yidx[2024]]
sp24 = sys_models(2024, CFGS)
sp24["adv_sum"] = A[2024].sum((0, 1))
e = {k: wape(v[m24], y24s[m24]) for k, v in sp24.items()}
print("SYS-HOUR 2024 ordinary", {k: round(v, 4) for k, v in e.items()}, flush=True)
bh = min((k for k in e if k.startswith("abs") or k.startswith("pois")), key=e.get)
br = min((k for k in e if k.startswith("ridge")), key=e.get)
w_sys, e_sys = best_blend({bh: sp24[bh], br: sp24[br], "adv_sum": sp24["adv_sum"]}, y24s, m24)
print("SYS blend", w_sys, round(e_sys, 4), "t", round(time.time() - t0), flush=True)
R["system_hour"] = dict(members_2024_ordinary=e, chosen_hgb=bh, chosen_ridge=br, blend_weights=w_sys, blend_2024_ordinary=e_sys)
H24 = sum(w * sp24[k] for k, w in w_sys.items())

# ======================= STATION-DAY =======================
tn, TX, TF = stn_features(T, cal, wxs)
tday = np.tile(np.arange(D), S)
tscale = np.nan_to_num(TX[:, tn.index("med8")]) + 1
ty_ = T.reshape(-1)
cat = [tn.index("station")]


def stn_models(ty, cfgs, which=None):
    tr = (year[tday] >= 2022) & (year[tday] < ty)
    te = year[tday] == ty
    out = {}
    for nm, cfg in cfgs.items():
        if which and nm not in which:
            continue
        out[nm] = pred_hgb(fit_hgb(TX[tr], ty_[tr], tscale[tr], cfg, cat), TX[te], tscale[te], cfg)
    return {k: v.reshape(S, -1) for k, v in out.items()}  # (S, days of year); te ordering is station-major, day-minor


T24 = T[:, yidx[2024]]
tp24 = stn_models(2024, CFGS)
tp24["adv_sum"] = A[2024].sum(0).sum(2)
e = {k: wape(v[:, m24], T24[:, m24]) for k, v in tp24.items()}
print("STATION-DAY 2024 ordinary", {k: round(v, 4) for k, v in e.items()}, "t", round(time.time() - t0), flush=True)
bt = min((k for k in e if k != "adv_sum"), key=e.get)
w_stn, e_stn = best_blend({bt: tp24[bt].T, "adv_sum": tp24["adv_sum"].T}, T24.T, m24)
print("STN blend", w_stn, round(e_stn, 4), flush=True)
R["station_day"] = dict(members_2024_ordinary=e, chosen_hgb=bt, blend_weights=w_stn, blend_2024_ordinary=e_stn)
G24 = sum(w * tp24[k] for k, w in w_stn.items())


# ======================= RECONCILIATION =======================
def recon(Pb, G, H, mode):
    """Pb (2,S,d,24); G (S,d) station-day target; H (d,24) system-hour target"""
    p = Pb.copy()
    def stn(p):
        return p * np.clip(G / np.maximum(p.sum((0, 3)), 1e-6), 0.5, 2.0)[None, :, :, None]
    def sysh(p):
        return p * np.clip(H / np.maximum(p.sum((0, 1)), 1e-6), 0.5, 2.0)[None, None]
    if mode == "stn":
        return stn(p)
    if mode == "sys":
        return sysh(p)
    if mode == "stn_then_sys":
        return sysh(stn(p))
    if mode == "sys_then_stn":
        return stn(sysh(p))
    if mode == "rake3":
        for _ in range(3):
            p = stn(sysh(p))
        return p
    raise ValueError(mode)


y24 = yy(2024)
base24 = full(A[2024], y24, m24)
rec24 = {}
for mode in ("stn", "sys", "stn_then_sys", "sys_then_stn", "rake3"):
    rec24[mode] = full(recon(A[2024], G24, H24, mode), y24, m24)
    print("RECON 2024", mode, {k: round(v, 4) for k, v in rec24[mode].items()}, flush=True)
print("base 2024", {k: round(v, 4) for k, v in base24.items()})
# adopt the mode with the best 2024 detailed (cells, ordinary) error, only if it beats the base
bm = min(rec24, key=lambda k: rec24[k]["cells_ordinary"])
adopt = rec24[bm]["cells_ordinary"] < base24["cells_ordinary"]
R["reconciliation"] = dict(base_2024=base24, modes_2024=rec24, best_mode=bm, adopted=bool(adopt))
print("best mode", bm, "adopted", adopt, "t", round(time.time() - t0), flush=True)
np.save(CLEAN / "lvl_pred_2024.npy", recon(A[2024], G24, H24, bm).astype(np.float32) if adopt else A[2024].astype(np.float32))

# ======================= FINAL: 2025, scored once =======================
m25 = ordn[yidx[2025]]
y25 = yy(2025)
sp25 = sys_models(2025, CFGS, which=[bh, br])
H25 = sum(w * (A[2025].sum((0, 1)) if k == "adv_sum" else sp25[k]) for k, w in w_sys.items())
tp25 = stn_models(2025, CFGS, which=[bt])
G25 = sum(w * (A[2025].sum(0).sum(2) if k == "adv_sum" else tp25[k]) for k, w in w_stn.items())
Ys25 = Ys[yidx[2025]]
T25 = T[:, yidx[2025]]
sysm = {k: wape(v[m25], Ys25[m25]) for k, v in sp25.items()}
stm = {k: wape(v[:, m25], T25[:, m25]) for k, v in tp25.items()}
R["system_hour"].update(members_2025_ordinary=sysm, blend_2025_ordinary=wape(H25[m25], Ys25[m25]), blend_2025_all=wape(H25, Ys25),
                        adv_sum_2025_ordinary=wape(A[2025].sum((0, 1))[m25], Ys25[m25]))
R["station_day"].update(members_2025_ordinary=stm, blend_2025_ordinary=wape(G25[:, m25], T25[:, m25]), blend_2025_all=wape(G25, T25),
                        adv_sum_2025_ordinary=wape(A[2025].sum(0).sum(2)[:, m25], T25[:, m25]))
Pfin = recon(A[2025], G25, H25, bm) if adopt else A[2025]
R["reconciliation"]["mode_used_2025"] = bm if adopt else "none"
R["reconciliation"]["detailed_2025"] = full(Pfin, y25, m25)
R["reconciliation"]["every_mode_2025_for_information_only"] = {k: full(recon(A[2025], G25, H25, k), y25, m25) for k in ("stn", "sys", "stn_then_sys", "rake3")}
np.save(CLEAN / "lvl_pred_2025.npy", Pfin.astype(np.float32))
R["leakage_checks"] = leak + [
    "level models use ridership only through shifts of 7, 14, ..., 56 and 364 days, windows ending at day d-7, and daily totals of the same kind",
    "calendar (including holiday yesterday/tomorrow) and weather of day d are the only same-day inputs",
    "2024 choices: models trained on 2022-2023 only; 2025 rows never read before the final scoring step",
    "the summed current-best forecast is an out-of-sample blend member (adv_pred_2024 / adv_pred_2025 were produced by walk-forward training)"]
R["elapsed_min"] = round((time.time() - t0) / 60, 1)
json.dump(R, open("C:/Users/sefef/AppData/Local/Temp/claude/11b0eb5da7edb6ea/f7351b51-281d-4863-acec-e170b2248fc4/scratchpad/levels_raw.json", "w"), indent=1, default=float)
print("FINAL", json.dumps({k: R[k] for k in ("system_hour", "station_day")}, default=float)[:3000])
print("RECON25", {k: round(v, 4) for k, v in R["reconciliation"]["detailed_2025"].items()}, flush=True)
