"""Blend search on 2024 (coarse 0.1 grid), then apply to 2025 once. Usage: python nn_blend.py"""
import json, itertools
from adv_common import *
import sys
c = load()
def A(y): return c.Y[:, :, np.where(c.year == y)[0], :]
def ens(kind, y, seeds, tag=""):
    fs = [CLEAN / f"nn_{kind}{tag}_s{s}_{y}.npy" for s in seeds]
    fs = [f for f in fs if f.exists()]
    return np.mean([np.load(f) for f in fs], 0), len(fs)
def members(y):
    m = {"trees": np.load(CLEAN / f"pred_{y}.npy"), "old_tf": np.load(CLEAN / f"adv_transformer_{y}.npy"), "similar": np.load(CLEAN / f"adv_analog_{y}.npy")}
    for k in ("mlp", "resmlp", "tf"):
        e, n = ens(k, y, [0, 1, 2]); 
        if n: m[k + "_ens"] = e; m[k + "_n"] = n
    return m
M24 = members(2024); M25 = members(2025)
names = [k for k in M24 if not k.endswith("_n") and k in M25]
print(names, {k: M24[k] for k in M24 if k.endswith("_n")})
a24 = A(2024); a25 = A(2025)
for k in names: print(k, round(wape(M24[k], a24), 4), round(wape(M25[k], a25), 4))
# coarse grid on 2024 over all members (steps of 0.1)
best = (9, None); res = []
grid = [w for w in itertools.product(range(11), repeat=len(names)) if sum(w) == 10]
for w in grid:
    P = sum(wi / 10 * M24[k] for wi, k in zip(w, names)); e = wape(P, a24); res.append((e, w))
res.sort(); print("top5 2024 (in-sample for weights)", [(round(e, 4), dict(zip(names, w))) for e, w in res[:5]])
w = res[0][1]
P25 = sum(wi / 10 * M25[k] for wi, k in zip(w, names)); P24 = sum(wi / 10 * M24[k] for wi, k in zip(w, names))
print("FINAL 2024", wape(P24, a24), "2025", wape(P25, a25))
json.dump({"names": names, "weights": dict(zip(names, [x / 10 for x in w])), "e24": res[0][0], "e25": wape(P25, a25),
           "top5": [(e, dict(zip(names, ww))) for e, ww in res[:5]]}, open(CLEAN / "nn_blend.json", "w"), default=float)
np.save(CLEAN / "nn_blend_tmp_2025.npy", P25.astype(np.float32)); np.save(CLEAN / "nn_blend_tmp_2024.npy", P24.astype(np.float32))
