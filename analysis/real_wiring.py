"""Does SUB-01's wiring do the work?

The BOLD-band Hopf slow layer (twin/hopf.py) is fitted on HALF of the subject's 131 QC-passed resting-state runs and
scored on the OTHER half (split by session). The identical pipeline is run on the real connectome and on randomised
connectomes that keep its geometry (Betzel & Bassett 2018, degree + edge-length preserving) or its node strengths
(simulated annealing, Milisav et al.), both from netneurotools (BSD-3).

    python analysis/real_wiring.py prep   --conn out/connectome_v2.npz --tag v2 --nulls 100
    python analysis/real_wiring.py run    --tag v2 --workers 30            # heavy part (RunPod CPU pod)
    python analysis/real_wiring.py report --tags old v2

Per network: stage 1 = only the global coupling G is fitted (C = G * SC: the wiring fixes the whole pattern);
stage 2 = effective connectivity on the network's own edges + homotopic pairs (Deco et al. 2019; Gilson et al. 2016).
Held-out scores: FC r (analytic and simulated), FCD KS distance (simulated), per-region FC-row r.
p-value per metric: (1 + #nulls at least as good as the real connectome) / (1 + #nulls).
"""
import argparse
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from twin import hopf as H  # noqa: E402

CACHE = ROOT / "data" / "analysis"
DOCS = ROOT / "docs" / "real_wiring"
G_GRID_SIM = np.geomspace(0.3, 300.0, 20)
SIM_RUNS, SIM_S, SIM_TR, SIM_SEED = 20, 600.0, H.LAG_TR, 12345
FCD_SAMPLE = 200_000


def transform(W):
    """Model weights from the connectome: log(1 + w), symmetric, zero diagonal (same for real and nulls)."""
    W = np.log1p(np.asarray(W, float))
    W = (W + W.T) / 2
    np.fill_diagonal(W, 0)
    return W


def _null(args):
    kind, Wt, D, seed = args
    import contextlib
    import io
    from netneurotools import networks
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        if kind == "geometry":
            E = int((Wt > 0).sum() // 2)
            _, newW, _ = networks.match_length_degree_distribution(Wt, D, nbins=10, nswap=E * 20, seed=seed)
            return (newW + newW.T) / 2
        return networks.strength_preserving_rand_sa(Wt, seed=seed)[0]


def make_nulls(Wt, D, n, seed0=0, workers=1):
    jobs = [(k, Wt, D, seed0 + i) for k in ("geometry", "strength") for i in range(n)]
    with Pool(workers) as pool:
        out = pool.map(_null, jobs)
    return np.array(out[:n]), np.array(out[n:])


def prep(a):
    import json as js
    z = np.load(a.conn)
    names = js.loads((ROOT / "out" / "atlas_names.json").read_text())
    runs = H.load_runs(ROOT / "out" / "rest")
    fit, held, info = H.split_by_session(runs)
    rng = np.random.default_rng(0)
    pool = lambda rs: rng.choice(H.fcd_pool(rs), FCD_SAMPLE, replace=False).astype(np.float32)
    Wt = transform(z["weights"])
    c = z["centroids"]
    D = np.linalg.norm(c[:, None] - c[None], axis=-1)
    t = time.time()
    geo, stren = make_nulls(Wt, D, a.nulls, workers=a.workers) if a.nulls else (np.zeros((0,) + Wt.shape),) * 2
    print(f"{2 * a.nulls} nulls in {time.time() - t:.0f} s", flush=True)
    nets = np.concatenate([Wt[None], geo, stren]).astype(np.float32)
    kinds = np.array(["real"] + ["geometry"] * a.nulls + ["strength"] * a.nulls)
    out = CACHE / f"rw_{a.tag}_inputs.npz"
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, nets=nets, kinds=kinds, freqs=H.peak_freqs(fit), fc_fit=H.mean_fc(fit),
                        fc_held=H.mean_fc(held), covt_fit=H.mean_lagged_cov(fit), fcd_fit=pool(fit), fcd_held=pool(held),
                        hom=np.array(H.homotopic_pairs(names)), split=json.dumps(info),
                        n_fit=len(fit), n_held=len(held), conn=str(a.conn), D=D.astype(np.float32))
    print("wrote", out, nets.shape, flush=True)


_S = {}


def _init(path):
    import torch
    torch.set_num_threads(1)                       # (batched complex LU in multi-threaded MKL is unreliable)
    d = np.load(path, allow_pickle=False)
    _S.update({k: d[k] for k in d.files})


def one(i):
    import torch
    from scipy import stats
    d = _S
    W = d["nets"][i].astype(np.float64)
    n = len(W)
    a = np.full(n, H.A_BIF)
    w = 2 * np.pi * d["freqs"]
    fe, fh, ce = d["fc_fit"], d["fc_held"], d["covt_fit"]
    SC = H.sc_matrix(W)
    res = {"i": int(i), "kind": str(d["kinds"][i]), "density": float((W > 0).sum() / (n * (n - 1))),
           "scfc_held_r": H.fc_r(W, fh), "scfc_fit_r": H.fc_r(W, fe)}          # W is already log(1 + w)

    def score(C, tag):
        FCm, _, stable = H.linear_stats(torch.as_tensor(C)[None], torch.as_tensor(a), torch.as_tensor(w))
        sim = H.simulate_linear(C, a, w, SIM_RUNS, SIM_S, SIM_TR, seed=SIM_SEED)
        fs = H.mean_fc(sim)
        fcd_s = H.fcd_pool(sim)
        res.update({f"{tag}_fit_fc_r": H.fc_r(FCm[0].numpy(), fe),
                    f"{tag}_held_fc_r_analytic": H.fc_r(FCm[0].numpy(), fh),
                    f"{tag}_held_fc_r": H.fc_r(fs, fh),
                    f"{tag}_held_fcd_ks": float(stats.ks_2samp(fcd_s, d["fcd_held"]).statistic),
                    f"{tag}_fit_fcd_ks": float(stats.ks_2samp(fcd_s, d["fcd_fit"]).statistic),
                    f"{tag}_region_r": H.region_fit(fs, fh).tolist(),
                    f"{tag}_stable": bool(stable[0])})
        return fs

    # stage 1: G maximising (simulated FC r - FCD KS) on the FIT half (Deco et al. 2017 choose G by FCD KS; FC r alone
    # degenerates to G -> 0, where model FC is a first-order copy of SC but far too weak to be measurable in finite runs)
    r = []
    for G in G_GRID_SIM:
        sim = H.simulate_linear(G * SC, a, w, 4, SIM_S, SIM_TR, seed=SIM_SEED + 1)
        r.append(H.fc_r(H.mean_fc(sim), fe) - float(stats.ks_2samp(H.fcd_pool(sim), d["fcd_fit"]).statistic))
    r = np.array(r)
    G = float(G_GRID_SIM[int(np.argmax(r))])
    res["G"] = G
    fs1 = score(G * SC, "g")
    mask = (W > 0).astype(float)
    for p, q in d["hom"]:
        mask[p, q] = mask[q, p] = 1
    C0 = G * SC
    add = (mask > 0) & (C0 == 0)
    C0[add] = np.median(C0[C0 > 0])
    EC, hist = H.fit_ec(C0[None], mask[None], a, w, fe, ce, iters=300)
    EC = EC[0].numpy()
    res["ec_iters"] = len(hist)
    fs2 = score(EC, "ec")
    if i == 0:
        res["EC"] = EC.astype(np.float32)
        res["G_curve"] = r.tolist()
        res["G_grid"] = G_GRID_SIM.tolist()
        res["fc_sim_g"], res["fc_sim_ec"] = fs1.astype(np.float32), fs2.astype(np.float32)
    return res


def add_nulls(a):
    """Generate the nulls for an inputs file made with --nulls 0 (in parallel; used on the pod)."""
    path = CACHE / f"rw_{a.tag}_inputs.npz"
    d = dict(np.load(path))
    Wt, D = d["nets"][0].astype(np.float64), d["D"].astype(np.float64)
    t = time.time()
    geo, stren = make_nulls(Wt, D, a.nulls, workers=a.workers)
    print(f"{2 * a.nulls} nulls in {time.time() - t:.0f} s", flush=True)
    d["nets"] = np.concatenate([Wt[None], geo, stren]).astype(np.float32)
    d["kinds"] = np.array(["real"] + ["geometry"] * a.nulls + ["strength"] * a.nulls)
    np.savez_compressed(path, **d)


def run(a):
    path = CACHE / f"rw_{a.tag}_inputs.npz"
    n = len(np.load(path)["kinds"])
    idx = list(range(n if a.limit is None else min(n, a.limit)))
    t = time.time()
    out = []
    def save(rows):
        rows = sorted([dict(r) for r in rows], key=lambda r: r["i"])
        real = next((r for r in rows if r["i"] == 0), None)
        extra = {k: real.pop(k) for k in ("EC", "G_curve", "G_grid", "fc_sim_g", "fc_sim_ec") if real and k in real}
        tmp = CACHE / f"rw_{a.tag}_results.part.npz"
        np.savez_compressed(tmp, rows=json.dumps(rows), **extra)
        tmp.replace(CACHE / f"rw_{a.tag}_results.npz")          # partial results survive a time-out

    with Pool(a.workers, initializer=_init, initargs=(str(path),)) as pool:
        for k, res in enumerate(pool.imap(one, idx)):            # in order: the real connectome comes first
            out.append(res)
            if k % 10 == 0 or k == len(idx) - 1:
                save(out)
                print(f"{k + 1}/{len(idx)} networks, {time.time() - t:.0f} s", flush=True)
    print(f"done {len(out)} networks in {time.time() - t:.0f} s", flush=True)


METRICS = [("scfc_held_r", "SC-FC r (held-out FC)", 1), ("g_held_fc_r", "G-only: FC r", 1),
           ("g_held_fc_r_analytic", "G-only: FC r (noise-free)", 1), ("ec_held_fc_r_analytic", "EC: FC r (noise-free)", 1),
           ("g_held_fcd_ks", "G-only: FCD KS", -1), ("ec_held_fc_r", "EC: FC r", 1), ("ec_held_fcd_ks", "EC: FCD KS", -1),
           ("g_region_med", "G-only: median region r", 1), ("ec_region_med", "EC: median region r", 1)]


def summarise(rows):
    for r in rows:
        r["g_region_med"] = float(np.nanmedian(r["g_region_r"]))
        r["ec_region_med"] = float(np.nanmedian(r["ec_region_r"]))
    real = rows[0]
    out = {"real": {k: real[k] for k, _, _ in METRICS} | {"G": real["G"], "density": real["density"]}, "nulls": {}}
    for fam in ("geometry", "strength"):
        nl = [r for r in rows if r["kind"] == fam]
        if not nl:
            continue
        fam_out = {"n": len(nl)}
        for k, label, sign in METRICS:
            v = np.array([r[k] for r in nl])
            better = (sign * v >= sign * real[k]).sum()
            fam_out[k] = {"null_mean": float(v.mean()), "null_sd": float(v.std()), "null_max" if sign > 0 else "null_min":
                          float(v.max() if sign > 0 else v.min()), "p": float((1 + better) / (1 + len(v))),
                          "real_beats_all": bool(better == 0)}
        out["nulls"][fam] = fam_out
    return out


def export(a):
    """Write twin/data/slow_layer.npz: the fitted slow layer of the REAL connectome for the live model (small, committed)."""
    d = np.load(CACHE / f"rw_{a.tag}_results.npz")
    rows = json.loads(str(d["rows"]))
    inp = np.load(CACHE / f"rw_{a.tag}_inputs.npz")
    s = summarise(rows)
    real = rows[0]
    W = inp["nets"][0].astype(np.float64)
    names = json.loads((ROOT / "out" / "atlas_names.json").read_text())
    p = lambda fam, k: s["nulls"][fam][k]["p"]
    meta = {"connectome": Path(str(inp["conn"])).stem, "conn_file": str(inp["conn"]), "results": a.tag,
            "heldout_fc_r": round(real["ec_held_fc_r"], 3), "heldout_fcd_ks": round(real["ec_held_fcd_ks"], 3),
            "wiring_only_heldout_fc_r": round(real["g_held_fc_r"], 3), "G": real["G"],
            "null_p_geometry": round(p("geometry", "ec_held_fc_r"), 3), "null_p_strength": round(p("strength", "ec_held_fc_r"), 3),
            "wiring_only_null_p_geometry": round(p("geometry", "g_held_fc_r"), 3),
            "wiring_only_null_p_strength": round(p("strength", "g_held_fc_r"), 3),
            "wiring_only_null_mean_geometry": round(s["nulls"]["geometry"]["g_held_fc_r"]["null_mean"], 3),
            "wiring_only_null_mean_strength": round(s["nulls"]["strength"]["g_held_fc_r"]["null_mean"], 3),
            "split": json.loads(str(inp["split"])), "fit": "twin/hopf.py + analysis/real_wiring.py"}
    out = ROOT / "twin" / "data" / "slow_layer.npz"
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, C=d["EC"].astype(np.float32), C_wiring=(real["G"] * H.sc_matrix(W)).astype(np.float32),
                        freqs=inp["freqs"].astype(np.float32), a=H.A_BIF, beta=H.BETA, names=np.array(names),
                        meta=json.dumps(meta))
    print("wrote", out, json.dumps(meta)[:400])


def report(a):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    DOCS.mkdir(parents=True, exist_ok=True)
    summary = {}
    for tag in a.tags:
        d = np.load(CACHE / f"rw_{tag}_results.npz")
        rows = json.loads(str(d["rows"]))
        inp = CACHE / f"rw_{tag}_inputs.npz"
        nets = np.load(inp)["nets"] if inp.exists() else []
        if len(nets) == len(rows):          # SC-FC from the stored networks (W = log(1 + w), applied once)
            fh = np.load(inp)["fc_held"]
            for r in rows:
                r["scfc_held_r"] = H.fc_r(nets[r["i"]].astype(np.float64), fh)
        summary[tag] = summarise(rows)
        fig, ax = plt.subplots(1, len(METRICS), figsize=(3.1 * len(METRICS), 2.8))
        for axk, (k, label, sign) in zip(ax, METRICS):
            for fam, col in (("geometry", "#4c78a8"), ("strength", "#f58518")):
                v = [r[k] for r in rows if r["kind"] == fam]
                axk.hist(v, bins=20, alpha=0.6, color=col, label=f"{fam} nulls")
            axk.axvline(rows[0][k], color="k", lw=2, label="his connectome")
            axk.set_title(label, fontsize=8)
            axk.tick_params(labelsize=7)
        ax[0].legend(fontsize=6)
        fig.suptitle(f"connectome {tag}: held-out scores, real vs randomised wiring", fontsize=9)
        fig.tight_layout()
        fig.savefig(DOCS / f"nulls_{tag}.png", dpi=110)
        plt.close(fig)
    (DOCS / "results.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)
    q = sp.add_parser("prep")
    q.add_argument("--conn", required=True)
    q.add_argument("--tag", required=True)
    q.add_argument("--nulls", type=int, default=100)
    q.add_argument("--workers", type=int, default=1)
    q = sp.add_parser("nulls")
    q.add_argument("--tag", required=True)
    q.add_argument("--nulls", type=int, default=100)
    q.add_argument("--workers", type=int, default=2)
    q = sp.add_parser("run")
    q.add_argument("--tag", required=True)
    q.add_argument("--workers", type=int, default=2)
    q.add_argument("--limit", type=int)
    q = sp.add_parser("export")
    q.add_argument("--tag", required=True)
    q = sp.add_parser("report")
    q.add_argument("--tags", nargs="+", required=True)
    a = p.parse_args()
    {"prep": prep, "nulls": add_nulls, "run": run, "export": export, "report": report}[a.cmd](a)
