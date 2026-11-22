"""Neural members. Usage: python nn_train.py KIND YEAR SEEDS THREADS   KIND = tf | mlp | res | resmlp
tf/mlp predict the level profile; res/resmlp predict (actual - tree forecast)/level. Inputs only from day d-7 or earlier
(plus calendar/weather of day d). Writes data/clean/nn_<kind>_s<seed>_<year>.npy and .json."""
import os, sys, time, json
os.environ["OMP_NUM_THREADS"] = sys.argv[4]
from adv_common import *
import torch, torch.nn as nn
torch.set_num_threads(int(sys.argv[4]))
KIND, TEST, SEEDS = sys.argv[1], int(sys.argv[2]), [int(s) for s in sys.argv[3].split(",")]
RES = KIND.startswith("res"); MLP = KIND.endswith("mlp")
EPOCHS_MAX, TCAP, BS = int(os.environ.get("NN_EP", 14)), int(os.environ.get("NN_TCAP", 200)), 1024
c = load(); S = c.S
FIRST = 56 if not RES else 0

def samples(di, tree=None):
    hist, level, ctx = inputs(c, di)
    n = len(di); lv = level + 1.0
    def g(name): return c.F[name][:, :, di, :]
    med8 = g("med8"); ewm8 = g("ewm8")
    l364 = np.where(np.isnan(g("lag364_grown")), med8, g("lag364_grown"))
    toks = [hist[:, :, :, j, :] for j in range(8)] + [np.nan_to_num(med8), np.nan_to_num(ewm8), np.nan_to_num(l364)]
    if RES: toks.append(tree[:, :, di, :])
    X = np.stack([t / lv[..., None] for t in toks], axis=3).reshape(-1, len(toks), 24).astype(np.float32)
    X = np.clip(X, 0, 20)
    def b(a): return np.broadcast_to(a, (2, S, n)).reshape(-1)
    dow, mon, sp = b(ctx["dow"][None, None, :]), b(ctx["month"][None, None, :]), b(ctx["special"][None, None, :])
    rain, tmax = b(ctx["rain"][None]), b(ctx["tmax"][None])
    stt = g("station_trend")[..., 0]; yoy = g("yoy_growth")[..., 0]
    l7s = g("lag7_was_special")[..., 0]; l364s = g("lag364_was_special")[..., 0]; woy = g("week_of_year")[..., 0]
    num = np.stack([sp, np.log1p(rain), (tmax - 18) / 8, b(stt) - 1, b(yoy) - 1, b(l7s), b(l364s), b(woy) / 52], 1).astype(np.float32)
    kind = np.broadcast_to(np.arange(2)[:, None, None], (2, S, n)).reshape(-1)
    st = np.broadcast_to(np.arange(S)[None, :, None], (2, S, n)).reshape(-1)
    y = c.Y[:, :, di, :].reshape(-1, 24) / lv.reshape(-1, 1)
    base = X[:, -1, :] if RES else X[:, :8].mean(1)
    if RES: y = y - base
    return dict(X=X, kind=kind, st=st, dow=dow, mon=mon, num=np.nan_to_num(num), y=y.astype(np.float32), w=lv.reshape(-1).astype(np.float32), base=base.astype(np.float32))

class Net(nn.Module):
    def __init__(s, ntok, d=64):
        super().__init__()
        s.inp = nn.Linear(24, d); s.pos = nn.Parameter(torch.randn(ntok + 1, d) * 0.02)
        s.st = nn.Embedding(S, d); s.kind = nn.Embedding(2, d); s.dow = nn.Embedding(7, d); s.mon = nn.Embedding(12, d)
        s.num = nn.Linear(8, d)
        layer = nn.TransformerEncoderLayer(d, 4, 128, 0.05, batch_first=True, norm_first=True)
        s.enc = nn.TransformerEncoder(layer, 2); s.norm = nn.LayerNorm(d); s.head = nn.Linear(d, 24)
        if RES: nn.init.zeros_(s.head.weight); nn.init.zeros_(s.head.bias)
    def forward(s, b):
        ctxt = (s.st(b["st"]) + s.kind(b["kind"]) + s.dow(b["dow"]) + s.mon(b["mon"]) + s.num(b["num"])).unsqueeze(1)
        h = s.enc(torch.cat([ctxt, s.inp(b["X"])], 1) + s.pos)
        return (0 if RES else b["base"]) + s.head(s.norm(h[:, 0]))

class Mlp(nn.Module):
    def __init__(s, ntok, d=32):
        super().__init__()
        s.st = nn.Embedding(S, d); s.kind = nn.Embedding(2, d); s.dow = nn.Embedding(7, d); s.mon = nn.Embedding(12, d)
        s.net = nn.Sequential(nn.Linear(ntok * 24 + 4 * d + 8, 512), nn.GELU(), nn.Dropout(0.05), nn.Linear(512, 256), nn.GELU(), nn.Linear(256, 24))
        if RES: nn.init.zeros_(s.net[-1].weight); nn.init.zeros_(s.net[-1].bias)
    def forward(s, b):
        z = torch.cat([b["X"].flatten(1), s.st(b["st"]), s.kind(b["kind"]), s.dow(b["dow"]), s.mon(b["mon"]), b["num"]], 1)
        return (0 if RES else b["base"]) + s.net(z)

def tens(d, idx):
    out = {k: torch.from_numpy(v[idx]) for k, v in d.items()}
    for k in ("kind", "st", "dow", "mon"): out[k] = out[k].long()
    return out
def post(o, b): return o if RES else torch.relu(o)
def loss_fn(o, b): return ((post(o, b) - b["y"]).abs().sum(1) * b["w"]).sum() / (b["y"].shape[0] * 24 * b["w"].mean())
def predict(net, d, bs=8192):
    net.eval(); out = []
    with torch.no_grad():
        for i in range(0, len(d["y"]), bs): out.append(post(net(tens(d, np.arange(i, min(i + bs, len(d["y"]))))), None).numpy())
    return np.concatenate(out)
def val_wape(pv, d):  # in level-normalised space; for RES add base back and compare to true y
    if RES: pv = np.maximum(pv + d["base"], 0); yt = d["y"] + d["base"]
    else: yt = d["y"]
    return float((np.abs(pv - yt).sum(1) * d["w"]).sum() / (yt.sum(1) * d["w"]).sum())

tree = None
if RES:
    tree = np.zeros_like(c.Y)
    for y in (2023, 2024, 2025):
        if y <= TEST: tree[:, :, c.year == y, :] = np.load(CLEAN / f"pred_{y}.npy")
    lo = 2023
else: lo = int(os.environ.get("NN_LO", 2021))
di_all = np.where((c.year >= lo) & (c.year < TEST))[0]; di_all = di_all[di_all >= FIRST] if not RES else di_all
val_cut = np.where(c.year == TEST - 1)[0][-61]
di_tr, di_va = di_all[di_all < val_cut], di_all[di_all >= val_cut]
dtr, dva = samples(di_tr, tree), samples(di_va, tree)
dte_idx = day_idx(c, TEST); dte = samples(dte_idx, tree)
ntok = dtr["X"].shape[1]
A = c.Y[:, :, dte_idx, :]
print(KIND, TEST, "train n", len(dtr["y"]), "tokens", ntok, flush=True)
for seed in SEEDS:
    torch.manual_seed(seed); np.random.seed(seed); t0 = time.time()
    net = (Mlp if MLP else Net)(ntok); npar = sum(p.numel() for p in net.parameters())
    opt = torch.optim.AdamW(net.parameters(), 2e-3, weight_decay=1e-2)
    steps = EPOCHS_MAX * (len(dtr["y"]) // BS + 1); sched = torch.optim.lr_scheduler.OneCycleLR(opt, 2e-3, total_steps=steps)
    best, best_state, bad = 9, None, 0
    for ep in range(EPOCHS_MAX):
        net.train(); perm = np.random.permutation(len(dtr["y"]))
        for i in range(0, len(perm), BS):
            b = tens(dtr, perm[i:i + BS]); opt.zero_grad(); l = loss_fn(net(b), b); l.backward(); opt.step(); sched.step()
        v = val_wape(predict(net, dva), dva)
        print(seed, ep, "val", round(v, 4), round(time.time() - t0), "s", flush=True)
        if v < best: best, bad, best_state = v, 0, {k: x.clone() for k, x in net.state_dict().items()}
        else:
            bad += 1
            if bad >= 5: break
        if time.time() - t0 > TCAP: break
    net.load_state_dict(best_state)
    p = predict(net, dte)
    P = (np.maximum(p + dte["base"], 0) if RES else p) * dte["w"][:, None]
    P = P.reshape(2, S, len(dte_idx), 24)
    np.save(CLEAN / f"nn_{KIND}{os.environ.get("NN_TAG","")}_s{seed}_{TEST}.npy", P.astype(np.float32))
    secs = time.time() - t0
    print("RESULT", KIND, TEST, seed, "wape", wape(P, A), "secs", secs, flush=True)
    json.dump({"kind": KIND, "year": TEST, "seed": seed, "wape": wape(P, A), "seconds": secs, "val_best": best, "params": npar, "epochs_run": ep + 1}, open(CLEAN / f"nn_{KIND}{os.environ.get("NN_TAG","")}_s{seed}_{TEST}.json", "w"))
