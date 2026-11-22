"""Experiment B: cosine-similarity analog days. Usage: python adv_analog.py   (tunes on 2024, then runs 2025 once with the chosen setting)"""
import itertools, time, json
from adv_common import *
t0 = time.time()
c = load(); S, D = c.S, c.D
# sanity check of the loading code
for y in (2024, 2025):
    print("baseline", y, wape(np.load(CLEAN / f"pred_{y}.npy"), c.Y[:, :, day_idx(c, y), :]))
dall = np.arange(56, D)                      # days that have a full 8-week history
hist, level, ctx = inputs(c, dall)
lv = level + 1.0                             # (2,S,n)
n = len(dall)
last = hist[:, :, :, 0, :] / lv[..., None]   # d-7 profile shape
mean = (hist / lv[..., None, None]).mean(axis=3)   # 8-week mean shape
tot7 = hist[:, :, :, 0, :].sum(-1) / 24.0 / lv     # trend: last week vs 8-week level
dow1 = np.eye(7, dtype=np.float32)[ctx["dow"]]; mon = ctx["month"]
mon_b = np.stack([np.sin(2 * np.pi * mon / 12), np.cos(2 * np.pi * mon / 12)], 1).astype(np.float32)
bc = lambda a: np.broadcast_to(a[None, None], (2, S) + a.shape)
blocks = {"shape": np.concatenate([last, mean], -1), "trend": np.log(np.clip(tot7, .2, 5))[..., None], "dow": bc(dow1), "month": bc(mon_b),
          "special": bc(ctx["special"][:, None]), "weather": np.stack([np.log1p(ctx["rain"]), ctx["tmax"] / 10], -1)[None].repeat(2, 0)}
target = (c.Y[:, :, dall, :] / lv[..., None])      # candidates' actual shapes, normalised by their own level
yr = c.year[dall]

def run(test_year, W, k, start_year):
    tr = yr < test_year
    Zs = []
    for name, B in blocks.items():
        B = B.astype(np.float32)
        mu = B[:, :, tr].reshape(-1, B.shape[-1]).mean(0); sd = B[:, :, tr].reshape(-1, B.shape[-1]).std(0) + 1e-6
        Zs.append((B - mu) / sd * W[name] / np.sqrt(B.shape[-1]))
    Z = np.concatenate(Zs, -1); Z /= (np.linalg.norm(Z, axis=-1, keepdims=True) + 1e-9)
    te = np.where(yr == test_year)[0]; P = np.zeros((2, S, len(te), 24), np.float32)
    pos = np.arange(n)
    for kd in range(2):
        for s in range(S):
            sim = Z[kd, s, te] @ Z[kd, s].T                         # (te, n)
            # candidate must be >= 7 days before the target day AND its own outcome known: dall[cand] <= dall[te]-7
            ok = (dall[None, :] <= dall[te][:, None] - 7) & (yr[None, :] >= start_year)
            sim = np.where(ok, sim, -9)
            idx = np.argpartition(-sim, k, axis=1)[:, :k]
            P[kd, s] = target[kd, s][idx].mean(1) * lv[kd, s, te][:, None]
    return P, te

def score(P, te): return wape(P, c.Y[:, :, dall[te], :])
base = dict(shape=1.0, trend=0.5, dow=3.0, month=0.5, special=2.0, weather=0.5)
res = []
for k, wd, ws, ww, sy in itertools.product((5, 10, 20), (2, 4), (0.5, 1.0), (0, 1.0), (2021, 2022)):
    W = dict(base, dow=wd, shape=ws, weather=ww)
    P, te = run(2024, W, k, sy); e = score(P, te); res.append((e, k, wd, ws, ww, sy)); print(round(e, 4), k, wd, ws, ww, sy, round(time.time() - t0), flush=True)
res.sort(); e, k, wd, ws, ww, sy = res[0]
best = dict(k=k, W=dict(base, dow=wd, shape=ws, weather=ww), start_year=sy)
t1 = time.time(); P24, te = run(2024, best["W"], k, sy); np.save(CLEAN / "adv_analog_2024.npy", P24); e24 = score(P24, te)
secs = time.time() - t1
json.dump({"best": best, "error_2024": e24, "seconds": secs, "grid_top5": res[:5], "grid_worst": res[-1]}, open(CLEAN / "adv_analog.json", "w"))
print("B 2024", e24, "settings", best, flush=True)
