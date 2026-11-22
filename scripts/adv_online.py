"""Experiments C and the fixed blend. Usage: python adv_online.py tune   (2024 only)   |   python adv_online.py final  (2025, once)"""
import sys, json, itertools, time
from adv_common import *
MODE = sys.argv[1]
c = load(); S = c.S
def Yy(y): return c.Y[:, :, day_idx(c, y), :]
def simples(y):
    di = day_idx(c, y); g = lambda n: np.nan_to_num(c.F[n][:, :, di, :])
    return {"lag7": g("lag7"), "mean4": np.nan_to_num(c.mean4[:, :, di, :]), "med8": g("med8"), "ewm8": g("ewm8"), "lag364_grown": g("lag364_grown")}
def members(y, with_adv):
    m = {"best": np.load(CLEAN / f"pred_{y}.npy")}; m.update(simples(y))
    if with_adv:
        m["analog"] = np.load(CLEAN / f"adv_analog_{y}.npy")
        if (CLEAN / f"adv_transformer_{y}.npy").exists(): m["transformer"] = np.load(CLEAN / f"adv_transformer_{y}.npy")
    return m
def stack(years, with_adv):
    ms = [members(y, with_adv) for y in years]
    names = list(ms[0]); return names, np.stack([np.concatenate([m[n] for m in ms], axis=2) for n in names]), np.concatenate([Yy(y) for y in years], axis=2)

def hedge(P, A, eta, gamma, bs, delay=7):
    """P (M,2,S,T,24). weight for day t uses losses of days <= t-delay only. Hedge with discounted cumulative loss."""
    M, _, _, T, _ = P.shape; nb = 24 // bs
    Pb = P.reshape(M, 2, S, T, nb, bs).sum(-1); Ab = A.reshape(2, S, T, nb, bs).sum(-1)
    err = np.abs(P.reshape(M, 2, S, T, nb, bs) - A.reshape(1, 2, S, T, nb, bs)).sum(-1)
    loss = np.clip(err / (Ab[None] + 5.0), 0, 2)                   # scale-free reward = minus this
    L = np.zeros_like(loss)
    cum = np.zeros((M, 2, S, T + 1, nb))
    for t in range(T): cum[:, :, :, t + 1] = gamma * cum[:, :, :, t] + loss[:, :, :, t]   # cum[:,:,:,k] = state after outcomes of days < k
    Lsel = np.zeros_like(L)
    for t in range(T): Lsel[:, :, :, t] = cum[:, :, :, max(t - delay + 1, 0)]                # outcomes of days <= t-delay
    z = -eta * (Lsel - Lsel.min(0, keepdims=True)); w = np.exp(z); w /= w.sum(0, keepdims=True)
    out = (w[..., None] * P.reshape(M, 2, S, T, nb, bs)).sum(0).reshape(2, S, T, 24)
    return out

def seg(P, A, y):
    di = day_idx(c, y); sp = np.broadcast_to(c.special[di][None, None, :, None], A.shape); wk = np.broadcast_to((c.dser.dt.dayofweek.to_numpy()[di] >= 5)[None, None, :, None], A.shape)
    nz = A[A > 0]; busy = A >= np.percentile(nz, 75)
    return {"all": wape(P, A), "ordinary_days": wape(P[~sp], A[~sp]), "weekends": wape(P[wk], A[wk]), "busiest_quarter": wape(P[busy], A[busy])}

def grid_blend(Ps, A):
    best = (9, None)
    for a in np.arange(0, 1.0001, 0.05):
        for b in np.arange(0, 1.0001 - a, 0.05):
            w = (1 - a - b, a, b); e = wape(sum(wi * p for wi, p in zip(w, Ps)), A)
            if e < best[0]: best = (e, w)
    return best

if MODE == "tune":
    t0 = time.time(); R = {}
    # fixed blends on 2024 (weights chosen on 2024 itself, so their 2024 score is optimistic)
    names, P24, A24 = stack([2024], True); print(names)
    ix = {n: i for i, n in enumerate(names)}
    base = wape(P24[0], A24); R["best_alone"] = base; print("best alone", base)
    for tag, extra in (("best+transformer", ["transformer"]), ("best+analog", ["analog"]), ("best+transformer+analog", ["transformer", "analog"])):
        if len(extra) == 1:
            e, w = min(((wape((1 - a) * P24[0] + a * P24[ix[extra[0]]], A24), a) for a in np.arange(0, 1.0001, 0.05)))
            R["blend_" + tag] = {"error_2024": e, "weights": {"best": 1 - w, extra[0]: w}}
        else:
            e, w = grid_blend([P24[0], P24[ix["transformer"]], P24[ix["analog"]]], A24)
            R["blend_" + tag] = {"error_2024": e, "weights": dict(zip(["best", "transformer", "analog"], map(float, w)))}
        print(tag, R["blend_" + tag])
    # NNLS on all members (2024-fitted)
    from scipy.optimize import nnls
    rs = np.random.RandomState(0); sel = rs.choice(A24.size, 400000, replace=False)
    Mx = np.stack([P24[i].reshape(-1)[sel] for i in range(len(names))], 1); yv = A24.reshape(-1)[sel]; sc = 1 / np.sqrt(yv + 10)
    wn, _ = nnls(Mx * sc[:, None], yv * sc); e = wape(sum(w * P24[i] for i, w in enumerate(wn)), A24)
    R["nnls_all"] = {"error_2024": e, "weights": dict(zip(names, map(float, wn)))}; print("nnls", R["nnls_all"])
    # NNLS weights fitted on 2023 (honest out-of-sample for 2024): members without analog/transformer
    n23, P23, A23 = stack([2023], False); Mx = np.stack([P23[i].reshape(-1)[sel[sel < P23[0].size]] for i in range(len(n23))], 1)
    yv = A23.reshape(-1)[sel[sel < A23.size]]; sc = 1 / np.sqrt(yv + 10); wn2, _ = nnls(Mx * sc[:, None], yv * sc)
    names2, P24b, _ = stack([2024], False)
    R["nnls_fit2023_simple"] = {"error_2024": wape(sum(w * P24b[i] for i, w in enumerate(wn2)), A24), "weights": dict(zip(n23, map(float, wn2)))}; print("nnls2023", R["nnls_fit2023_simple"])
    # online hedge. core members run from 2023; all members from 2024
    res = []
    namesC, PC, AC = stack([2023, 2024], False); n23len = day_idx(c, 2023).size
    for eta, gamma, bs in itertools.product((1, 3, 10, 30), (1.0, 0.99, 0.97), (24, 8, 4)):
        out = hedge(PC, AC, eta, gamma, bs)[:, :, n23len:]; res.append((wape(out, A24), eta, gamma, bs))
    res.sort(); R["online_core_grid_top3"] = res[:3]; R["online_core"] = {"error_2024": res[0][0], "eta": res[0][1], "gamma": res[0][2], "block_hours": res[0][3], "members": namesC}
    print("online core", res[:3])
    res = []
    namesD, PD, AD = stack([2024], True)
    for eta, gamma, bs in itertools.product((1, 3, 10, 30), (1.0, 0.99, 0.97), (24, 8, 4)):
        res.append((wape(hedge(PD, AD, eta, gamma, bs), AD), eta, gamma, bs))
    res.sort(); R["online_all_grid_top3"] = res[:3]; R["online_all"] = {"error_2024": res[0][0], "eta": res[0][1], "gamma": res[0][2], "block_hours": res[0][3], "members": namesD}
    print("online all (2024-only start)", res[:3], round(time.time() - t0), "s")
    json.dump(R, open(CLEAN / "adv_tune_2024.json", "w"), indent=1, default=float)
