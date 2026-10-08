"""Does SUB-01's real wiring matter? Real connectome vs randomised brains (netneurotools nulls).

Three tests, all against his own recorded resting-state FC (131 QC-passed runs, Fisher-z averaged):
  1. structure only: how well the wiring (and network-communication measures computed on it) predicts
     which region pairs co-activate, vs strength-preserving and geometry-preserving rewired brains;
  2. the simulator on its own (no recorded data as input): sim FC vs his FC, real wiring vs rewired;
  3. the simulator as deployed (his recorded activity as drive, the source of the earlier r = 0.40):
     real wiring vs rewired vs no coupling at all, to see how much of that number the wiring explains.

Run: .venv/bin/python analysis/null_test.py [--quick]
Writes data/analysis/null_test.json and docs/null_test.md.
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import argparse
import glob
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from brain_sim import Brain  # noqa: E402
from real_baseline import RealBaseline  # noqa: E402

OUT = HERE / "data" / "analysis"
def upper(M):
    return M[np.triu_indices(M.shape[0], 1)]


def corr(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    return float(np.corrcoef(a[m], b[m])[0, 1])


# ---------------------------------------------------------------- data
def empirical_fc(names):
    qc = json.loads((HERE / "out/rest/qc.json").read_text())
    atlas = json.load(open(HERE / "out/atlas_names.json"))
    cols = [atlas.index(n) for n in names]
    zs = []
    for f in sorted(glob.glob(str(HERE / "out/rest/*.npz"))):
        if not qc.get(Path(f).stem, {}).get("kept", True):
            continue
        ts = np.nan_to_num(np.load(f)["ts"].astype(float))[:, cols]
        C = np.corrcoef(ts.T)
        np.fill_diagonal(C, 0)
        zs.append(np.arctanh(np.clip(C, -0.999, 0.999)))
    zs = np.array(zs)
    half = len(zs) // 2
    rng = np.random.default_rng(0)
    order = rng.permutation(len(zs))
    split = corr(upper(zs[order[:half]].mean(0)), upper(zs[order[half:]].mean(0)))
    single = np.median([corr(upper(z), upper(zs.mean(0))) for z in zs])
    return np.tanh(zs.mean(0)), len(zs), split, float(single)


# ---------------------------------------------------------------- structure
def predictors(W, D):
    """Pairwise structural predictors of FC (Vazquez-Rodriguez et al. 2019; Goni et al. 2014)."""
    from netneurotools.metrics import communicability_wei, distance_wei_floyd, search_information
    W = (W + W.T) / 2
    cost = np.where(W > 0, -np.log(W / W.max() + 1e-12) + 1e-6, np.inf)
    np.fill_diagonal(cost, 0)
    spl, _ = distance_wei_floyd(cost)
    si = search_information(W, cost)
    si = (si + si.T) / 2
    comm = communicability_wei(W)
    return {"sc": upper(W), "dist": upper(D), "spl": upper(spl), "si": upper(si), "comm": upper(np.log(comm + 1e-12))}


def multilinear_r(P, fc):
    X = np.column_stack([P[k] for k in ("sc", "dist", "spl", "si", "comm")])
    m = np.all(np.isfinite(X), 1)
    X = np.column_stack([np.ones(m.sum()), (X[m] - X[m].mean(0)) / (X[m].std(0) + 1e-12)])
    beta, *_ = np.linalg.lstsq(X, fc[m], rcond=None)
    return corr(X @ beta, fc[m])


def structure_scores(W, D, fc):
    P = predictors(W, D)
    return {"sc_fc": corr(P["sc"], fc),
            "sc_fc_connected": corr(P["sc"][P["sc"] > 0], fc[P["sc"] > 0]),
            "comm_fc": corr(P["comm"], fc),
            "si_fc": corr(-P["si"], fc),
            "multilinear": multilinear_r(P, fc)}


def make_null(args):
    kind, W, D, seed = args
    from netneurotools.networks import match_length_degree_distribution, strength_preserving_rand_sa
    if kind == "strength":
        B, _ = strength_preserving_rand_sa(W, seed=seed)
    else:
        _, B, _ = match_length_degree_distribution(W, D, nbins=10, nswap=int((W > 0).sum()) * 5, seed=seed)
    B = (B + B.T) / 2
    return B / B.sum(1).mean()


# ---------------------------------------------------------------- simulation
HRF_DT = 0.25


def hrf(dt=HRF_DT):
    from scipy.stats import gamma
    t = np.arange(0, 30, dt)
    h = gamma.pdf(t, 6) - gamma.pdf(t, 16) / 6
    return h / h.sum()


def simulate(job):
    """One run of the deployed model; returns sim FC (envelope -> HRF) and, with his drive, the drive FC."""
    W, a, g, his, T, seed = job["W"], job["a"], job["g"], job["his"], job["T"], job["seed"]
    b = Brain(a=a, g=g, seed=seed)
    if W is not None:
        b.W = W
    r = RealBaseline(b.names, rest_dir=str(HERE / "out/rest"), seed=0) if his else None
    env, drv = [], []
    for _ in range(int(T / HRF_DT)):
        if r is not None:
            v = r.advance(HRF_DT)
            b.drive = 1.6 * np.clip(v, -2, 3)
            drv.append(v)
        z = b.run(HRF_DT, every=25)
        env.append(np.abs(z).mean(0))
    env = np.array(env)
    if not np.all(np.isfinite(env)) or env.max() > 1e3:
        return {"diverged": True}
    bold = np.array([np.convolve(env[:, i], hrf())[: len(env)] for i in range(b.n)]).T[int(10 / HRF_DT):]
    out = {"env_fc": np.corrcoef(env.T), "bold_fc": np.corrcoef(bold.T), "diverged": False,
           "mean_amp": float(env.mean())}
    if his:
        out["drive_fc"] = np.corrcoef(np.array(drv).T)
    return out


def pctile(x, nulls):
    nulls = np.asarray([v for v in nulls if np.isfinite(v)])
    return {"real": round(x, 3), "null_mean": round(float(nulls.mean()), 3), "null_sd": round(float(nulls.std()), 3),
            "null_max": round(float(nulls.max()), 3), "n": len(nulls),
            "p": round(float((1 + (nulls >= x).sum()) / (1 + len(nulls))), 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()
    n_struct = (40, 20) if args.quick else (500, 200)       # geometry, strength nulls for test 1
    n_sim = 4 if args.quick else 16                          # nulls of each kind for tests 2-3
    T = 120 if args.quick else 300
    t0 = time.time()

    b = Brain()
    W = b.W
    W = (W + W.T) / 2
    W /= W.sum(1).mean()
    z = np.load(HERE / "out/connectome.npz")
    C = z["centroids"]
    D = np.linalg.norm(C[:, None] - C[None], axis=-1)

    fc, nruns, split, single = empirical_fc(b.names)
    fcu = upper(fc)
    print(f"his FC: {nruns} runs, split-half reliability r={split:.3f}, single run vs mean r={single:.3f}", flush=True)

    with Pool(args.workers) as pool:
        jobs = ([("geometry", W, D, s) for s in range(n_struct[0])] +
                [("strength", W, D, 10_000 + s) for s in range(n_struct[1])])
        nulls = pool.map(make_null, jobs, chunksize=4)
        geo, stren = nulls[: n_struct[0]], nulls[n_struct[0]:]
        print(f"nulls built in {time.time() - t0:.0f}s", flush=True)

        # 1. structure only
        real_s = structure_scores(W, D, fcu)
        geo_s = pool.starmap(structure_scores, [(B, D, fcu) for B in geo], chunksize=8)
        str_s = pool.starmap(structure_scores, [(B, D, fcu) for B in stren], chunksize=8)
        dist_only = corr(-upper(D), fcu)
        test1 = {k: {"geometry_null": pctile(real_s[k], [s[k] for s in geo_s]),
                     "strength_null": pctile(real_s[k], [s[k] for s in str_s])} for k in real_s}
        test1["distance_only_r"] = round(dist_only, 3)
        print("test 1 done", json.dumps(test1)[:400], flush=True)

        # 2. the simulator alone: sweep, then real vs nulls at the best point
        grid = [(a, g) for a in (-5.0, -1.0, -0.3) for g in (2.5, 5.0, 10.0, 20.0)]
        sweep = pool.map(simulate, [dict(W=None, a=a, g=g, his=False, T=T, seed=1) for a, g in grid])
        sweep_rows = []
        for (a, g), s in zip(grid, sweep):
            row = {"a": a, "g": g, "diverged": s["diverged"]}
            if not s["diverged"]:
                row.update(bold_r=round(corr(upper(s["bold_fc"]), fcu), 3),
                           env_r=round(corr(upper(s["env_fc"]), fcu), 3), amp=round(s["mean_amp"], 3))
            sweep_rows.append(row)
        ok = [r for r in sweep_rows if not r["diverged"]]
        best = max(ok, key=lambda r: r["bold_r"])
        print("sweep", sweep_rows, "best", best, flush=True)
        a, g = best["a"], best["g"]
        jobs2 = ([dict(W=None, a=a, g=g, his=False, T=T, seed=s) for s in range(2, 2 + 4)] +
                 [dict(W=B, a=a, g=g, his=False, T=T, seed=2) for B in geo[:n_sim]] +
                 [dict(W=B, a=a, g=g, his=False, T=T, seed=2) for B in stren[:n_sim]])
        res2 = pool.map(simulate, jobs2)
        f = lambda s: corr(upper(s["bold_fc"]), fcu) if not s["diverged"] else np.nan
        real2 = [f(s) for s in res2[:4]]
        test2 = {"sweep": sweep_rows, "best": {"a": a, "g": g},
                 "real_seeds": [round(x, 3) for x in real2],
                 "geometry_null": pctile(float(np.mean(real2)), [f(s) for s in res2[4:4 + n_sim]]),
                 "strength_null": pctile(float(np.mean(real2)), [f(s) for s in res2[4 + n_sim:]])}
        print("test 2 done", json.dumps(test2)[-400:], flush=True)

        # 3. as deployed: his recorded activity as drive (a=-5, g=5), same drive for every wiring
        T3 = 240
        zero = np.zeros_like(W)
        jobs3 = ([dict(W=None, a=-5.0, g=5.0, his=True, T=T3, seed=0),
                  dict(W=zero, a=-5.0, g=5.0, his=True, T=T3, seed=0)] +
                 [dict(W=B, a=-5.0, g=5.0, his=True, T=T3, seed=0) for B in geo[:n_sim]] +
                 [dict(W=B, a=-5.0, g=5.0, his=True, T=T3, seed=0) for B in stren[:n_sim]])
        res3 = pool.map(simulate, jobs3)
    dfc = upper(res3[0]["drive_fc"])

    def g3(s):
        if s["diverged"]:
            return np.nan, np.nan
        return corr(upper(s["env_fc"]), dfc), corr(upper(s["bold_fc"]), fcu)

    r_real, r_zero = g3(res3[0]), g3(res3[1])
    test3 = {"vs_drive_window": {"real": round(r_real[0], 3), "no_coupling": round(r_zero[0], 3),
                                 "geometry_null": pctile(r_real[0], [g3(s)[0] for s in res3[2:2 + n_sim]]),
                                 "strength_null": pctile(r_real[0], [g3(s)[0] for s in res3[2 + n_sim:]])},
             "vs_his_mean_fc": {"real": round(r_real[1], 3), "no_coupling": round(r_zero[1], 3),
                                "geometry_null": pctile(r_real[1], [g3(s)[1] for s in res3[2:2 + n_sim]]),
                                "strength_null": pctile(r_real[1], [g3(s)[1] for s in res3[2 + n_sim:]])}}
    print("test 3 done", json.dumps(test3), flush=True)

    result = {"date": time.strftime("%Y-%m-%d %H:%M"), "quick": args.quick, "regions": b.n,
              "edge_density": round(float((W > 0).mean()), 3),
              "his_fc": {"runs": nruns, "split_half_r": round(split, 3), "single_run_vs_mean_r": round(single, 3)},
              "test1_structure": test1, "test2_model_alone": test2, "test3_as_deployed": test3,
              "seconds": round(time.time() - t0)}
    OUT.mkdir(parents=True, exist_ok=True)
    name = "null_test_quick.json" if args.quick else "null_test.json"
    (OUT / name).write_text(json.dumps(result, indent=1))
    print(f"wrote {OUT / name} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
