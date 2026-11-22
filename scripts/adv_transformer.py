"""Experiment A: small transformer over the 8 previous same-weekday 24-hour profiles. Usage: python adv_transformer.py 2024|2025"""
import sys, time, json
from adv_common import *
import torch, torch.nn as nn
torch.set_num_threads(6); torch.manual_seed(0); np.random.seed(0)
TEST = int(sys.argv[1]); EPOCHS_MAX = 24
c = load()
S = c.S

def samples(di):
    hist, level, ctx = inputs(c, di)
    n = len(di)
    lv = level + 1e-3 + 1.0
    X = (hist / lv[:, :, :, None, None]).reshape(-1, 8, 24).astype(np.float32)
    kind = np.broadcast_to(np.arange(2)[:, None, None], (2, S, n)).reshape(-1)
    st = np.broadcast_to(np.arange(S)[None, :, None], (2, S, n)).reshape(-1)
    dow = np.broadcast_to(ctx["dow"][None, None, :], (2, S, n)).reshape(-1)
    mon = np.broadcast_to(ctx["month"][None, None, :], (2, S, n)).reshape(-1)
    sp = np.broadcast_to(ctx["special"][None, None, :], (2, S, n)).reshape(-1)
    rain = np.broadcast_to(ctx["rain"][None], (2, S, n)).reshape(-1)
    tmax = np.broadcast_to(ctx["tmax"][None], (2, S, n)).reshape(-1)
    num = np.stack([sp, np.log1p(rain), (tmax - 18) / 8], axis=1).astype(np.float32)
    y = c.Y[:, :, di, :].reshape(-1, 24) / lv.reshape(-1, 1)
    return dict(X=X, kind=kind, st=st, dow=dow, mon=mon, num=num, y=y.astype(np.float32), w=lv.reshape(-1).astype(np.float32))

class Net(nn.Module):
    def __init__(s, d=64):
        super().__init__()
        s.inp = nn.Linear(24, d); s.pos = nn.Parameter(torch.randn(9, d) * 0.02)
        s.st = nn.Embedding(S, d); s.kind = nn.Embedding(2, d); s.dow = nn.Embedding(7, d); s.mon = nn.Embedding(12, d)
        s.num = nn.Linear(3, d)
        layer = nn.TransformerEncoderLayer(d, 4, 128, 0.05, batch_first=True, norm_first=True)
        s.enc = nn.TransformerEncoder(layer, 2); s.norm = nn.LayerNorm(d); s.head = nn.Linear(d, 24)
    def forward(s, b):
        tok = s.inp(b["X"])
        ctxt = (s.st(b["st"]) + s.kind(b["kind"]) + s.dow(b["dow"]) + s.mon(b["mon"]) + s.num(b["num"])).unsqueeze(1)
        h = s.enc(torch.cat([ctxt, tok], 1) + s.pos)
        base = b["X"].mean(1)                           # residual on the 8-week mean profile
        return torch.relu(base + s.head(s.norm(h[:, 0])))

def tens(d, idx):
    out = {k: torch.from_numpy(v[idx]) for k, v in d.items()}
    for k in ("kind", "st", "dow", "mon"): out[k] = out[k].long()
    return out

def loss_fn(p, b): return ((p - b["y"]).abs().sum(1) * b["w"]).sum() / (b["y"].shape[0] * 24 * b["w"].mean())

def predict(net, d, bs=8192):
    net.eval(); out = []
    with torch.no_grad():
        for i in range(0, len(d["y"]), bs): out.append(net(tens(d, np.arange(i, min(i + bs, len(d["y"]))))).numpy())
    return np.concatenate(out)

t0 = time.time()
di_all = np.where((c.year >= 2022) & (c.year < TEST))[0]
val_cut = np.where(c.year == TEST - 1)[0][-61]   # last ~2 months of the final training year = held-out slice
di_tr, di_va = di_all[di_all < val_cut], di_all[di_all >= val_cut]
dtr, dva = samples(di_tr), samples(di_va)
net = Net(); opt = torch.optim.AdamW(net.parameters(), 2e-3, weight_decay=1e-2)
steps = EPOCHS_MAX * (len(dtr["y"]) // 512 + 1); sched = torch.optim.lr_scheduler.OneCycleLR(opt, 2e-3, total_steps=steps)
best, best_state, bad = 9, None, 0
for ep in range(EPOCHS_MAX):
    net.train(); perm = np.random.permutation(len(dtr["y"]))
    for i in range(0, len(perm), 512):
        b = tens(dtr, perm[i:i + 512]); opt.zero_grad(); l = loss_fn(net(b), b); l.backward(); opt.step(); sched.step()
    pv = predict(net, dva); v = float((np.abs(pv - dva["y"]).sum(1) * dva["w"]).sum() / (dva["y"].sum(1) * dva["w"]).sum())
    print(ep, "val wape", round(v, 4), round(time.time() - t0), "s", flush=True)
    if v < best: best, bad, best_state = v, 0, {k: x.clone() for k, x in net.state_dict().items()}
    else:
        bad += 1
        if bad >= 5 or time.time() - t0 > 540: break
net.load_state_dict(best_state)
dte_idx = day_idx(c, TEST); dte = samples(dte_idx)
p = predict(net, dte) * dte["w"][:, None]
P = p.reshape(2, S, len(dte_idx), 24)
np.save(CLEAN / f"adv_transformer_{TEST}.npy", P)
A = c.Y[:, :, dte_idx, :]
secs = time.time() - t0
print("TEST", TEST, "wape", wape(P, A), "secs", secs)
json.dump({"year": TEST, "wape": wape(P, A), "seconds": secs, "val_wape_best": best}, open(CLEAN / f"adv_transformer_{TEST}.json", "w"))
