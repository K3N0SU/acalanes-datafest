"""Extra blend member: sklearn MLP at system-hour and station-day. Selection on 2024; 2025 scored once."""
import os, json
src = open("scripts/lvl_run.py").read()
exec(compile(src.split("# ======================= SYSTEM-HOUR")[0], "lvl_run_head", "exec"))
exec(compile("def _noop(): pass", "x", "exec"))
# re-create helper pieces from the main script (system + station design, without running its model selection)
body = src.split("# ======================= SYSTEM-HOUR")[1].split("m24 = ordn[yidx[2024]]")[0]
exec(compile("#" + body, "lvl_run_sys", "exec"))
body2 = src.split("# ======================= STATION-DAY")[1].split("T24 = T[:, yidx[2024]]")[0]
exec(compile("#" + body2, "lvl_run_stn", "exec"))
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
raw = json.load(open("C:/Users/sefef/AppData/Local/Temp/claude/11b0eb5da7edb6ea/f7351b51-281d-4863-acec-e170b2248fc4/scratchpad/levels_raw.json"))
m24 = ordn[yidx[2024]]; m25 = ordn[yidx[2025]]
def mlp_pred(X, y, scale, tr, te, onehot=None, seeds=(0, 1, 2)):
    Xm = X.copy()
    for j in range(Xm.shape[1]):
        col = Xm[:, j]; med = np.nanmedian(col[tr]); Xm[:, j] = np.where(np.isnan(col), med, col)
    for j in range(Xm.shape[1]):   # log the level-like columns
        if np.nanmin(Xm[tr, j]) >= 0 and np.nanmax(Xm[tr, j]) > 500: Xm[:, j] = np.log1p(Xm[:, j])
    if onehot is not None:
        oh = np.zeros((len(Xm), 50)); oh[np.arange(len(Xm)), Xm[:, onehot].astype(int)] = 1
        Xm = np.column_stack([Xm, oh])
    Xs = StandardScaler().fit(Xm[tr]).transform(Xm)
    tgt = np.log1p(y / scale)   # ratio to recent level, log
    out = 0
    for s in seeds:
        m = MLPRegressor(hidden_layer_sizes=(64, 32), alpha=1e-3, early_stopping=True, max_iter=200, random_state=s, learning_rate_init=2e-3).fit(Xs[tr], tgt[tr])
        out = out + np.expm1(m.predict(Xs[te])) * scale[te]
    return np.maximum(out / len(seeds), 0)
res = {}
for lvl in ("system_hour", "station_day"):
    if lvl == "system_hour":
        X, y, sc, dd = SX, sy, sscale, sday
        hn = raw["system_hour"]["chosen_hgb"]; oh = None
    else:
        X, y, sc, dd = TX, ty_, tscale, tday
        hn = raw["station_day"]["chosen_hgb"]; oh = tn.index("station")
    out = {}
    for ty in (2024, 2025):
        tr = (year[dd] >= 2022) & (year[dd] < ty); te = year[dd] == ty
        pm = mlp_pred(X, y, sc, tr, te, oh)
        ph = pred_hgb(fit_hgb(X[tr], y[tr], sc[tr], CFGS[hn], cat if lvl == "station_day" else None), X[te], sc[te], CFGS[hn])
        sh = (-1, 24) if lvl == "system_hour" else (S, -1)
        out[ty] = dict(mlp=pm.reshape(sh), hgb=ph.reshape(sh))
        out[ty]["adv"] = (A[ty].sum((0, 1)) if lvl == "system_hour" else A[ty].sum(0).sum(2))
    ax = (lambda a: a) if lvl == "system_hour" else (lambda a: a.T)
    act = {2024: Ys[yidx[2024]] if lvl == "system_hour" else T[:, yidx[2024]], 2025: Ys[yidx[2025]] if lvl == "system_hour" else T[:, yidx[2025]]}
    mem24 = {k: ax(v) for k, v in out[2024].items()}
    e24 = {k: wape(v[m24], ax(act[2024])[m24]) for k, v in mem24.items()}
    w, eb = best_blend(mem24, ax(act[2024]), m24)
    p25 = sum(w[k] * out[2025][k] for k in w)
    e25 = {k: wape(ax(v)[m25], ax(act[2025])[m25]) for k, v in out[2025].items()}
    res[lvl] = dict(members_2024=e24, weights_2024=w, blend_2024=eb, members_2025=e25, blend_2025_ordinary=wape(ax(p25)[m25], ax(act[2025])[m25]),
                    blend_2025_all=wape(ax(p25), ax(act[2025])))
    print(lvl, json.dumps(res[lvl], default=float), flush=True)
json.dump(res, open("C:/Users/sefef/AppData/Local/Temp/claude/11b0eb5da7edb6ea/f7351b51-281d-4863-acec-e170b2248fc4/scratchpad/mlp.json", "w"), default=float)
