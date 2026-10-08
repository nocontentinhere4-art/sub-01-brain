"""BOLD-band Hopf whole-brain model (Deco et al. 2017) on SUB-01's wiring vs randomised brains.

Each region is a Stuart-Landau oscillator at its own measured slow peak frequency (0.01-0.1 Hz), just below
the bifurcation (a = -0.02), diffusively coupled through the connectome; x = Re(z) is compared directly to his
band-passed fMRI. Every network (real or null) gets its own best global coupling G (fair comparison).

Run: .venv/bin/python analysis/hopf_test.py [--quick]
Writes data/analysis/hopf_test.json.
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import argparse
import glob
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from scipy import signal

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "analysis"))

from null_test import corr, make_null, upper  # noqa: E402

GS = np.round(np.linspace(0.0, 2.0, 17), 3)
DT, TR, T_SIM, T_SKIP = 0.1, 1.0, 1500.0, 60.0


def load_his(names):
    qc = json.loads((HERE / "out/rest/qc.json").read_text())
    atlas = json.load(open(HERE / "out/atlas_names.json"))
    cols = [atlas.index(n) for n in names]
    zs, psd, trs = [], 0, []
    for f in sorted(glob.glob(str(HERE / "out/rest/*.npz"))):
        if not qc.get(Path(f).stem, {}).get("kept", True):
            continue
        d = np.load(f)
        ts = np.nan_to_num(d["ts"].astype(float))[:, cols]
        tr = float(d["tr"])
        trs.append(tr)
        C = np.corrcoef(ts.T)
        np.fill_diagonal(C, 0)
        zs.append(np.arctanh(np.clip(C, -0.999, 0.999)))
        fr, p = signal.welch(ts, fs=1 / tr, nperseg=min(256, len(ts)), axis=0)
        psd = psd + np.array([np.interp(np.linspace(0.008, 0.11, 104), fr, p[:, i]) for i in range(len(cols))])
    fgrid = np.linspace(0.008, 0.11, 104)
    band = (fgrid >= 0.01) & (fgrid <= 0.1)
    peak = fgrid[band][np.argmax(psd[:, band], 1)]
    return np.tanh(np.mean(zs, 0)), peak, float(np.median(trs))


def hopf_fc(W, g, f_peak, seed, tr):
    rng = np.random.default_rng(seed)
    n = len(f_peak)
    a, beta = -0.02, 0.02
    om = 2 * np.pi * f_peak
    s = W.sum(1)
    x = rng.normal(0, 0.1, n)
    y = rng.normal(0, 0.1, n)
    every = int(round(tr / DT))
    out = []
    sq = np.sqrt(DT) * beta
    for k in range(int(T_SIM / DT)):
        r2 = x * x + y * y
        cx = g * (W @ x - s * x)
        cy = g * (W @ y - s * y)
        dx = (a - r2) * x - om * y + cx
        dy = (a - r2) * y + om * x + cy
        x = x + DT * dx + sq * rng.normal(size=n)
        y = y + DT * dy + sq * rng.normal(size=n)
        if k % every == 0 and k * DT >= T_SKIP:
            out.append(x.copy())
    X = np.array(out)
    if not np.all(np.isfinite(X)):
        return None
    b, a_ = signal.butter(2, [0.01 * 2 * tr, min(0.1 * 2 * tr, 0.99)], btype="band")
    X = signal.filtfilt(b, a_, signal.detrend(X, axis=0), axis=0)
    return np.corrcoef(X.T)


def fit_network(job):
    """Sweep G for one network; return its best fit to his FC and the whole curve."""
    W, f_peak, fcu, seed, tr = job
    curve = []
    for g in GS:
        F = hopf_fc(W, g, f_peak, seed, tr)
        curve.append(corr(upper(F), fcu) if F is not None else np.nan)
    curve = np.array(curve)
    i = int(np.nanargmax(curve))
    return {"best_r": float(curve[i]), "best_g": float(GS[i]), "curve": [round(float(c), 4) for c in curve]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()
    n_null = 8 if args.quick else 60
    t0 = time.time()
    from brain_sim import Brain
    b = Brain()
    W = (b.W + b.W.T) / 2
    W /= W.sum(1).mean()
    C = np.load(HERE / "out/connectome.npz")["centroids"]
    D = np.linalg.norm(C[:, None] - C[None], axis=-1)
    fc, f_peak, tr = load_his(b.names)
    fcu = upper(fc)
    print(f"TR {tr}s, peak freq median {np.median(f_peak):.3f} Hz", flush=True)

    with Pool(args.workers) as pool:
        nulls = pool.map(make_null, [("geometry", W, D, s) for s in range(n_null)] +
                         [("strength", W, D, 10_000 + s) for s in range(n_null)], chunksize=2)
        geo, stren = nulls[:n_null], nulls[n_null:]
        print(f"nulls in {time.time() - t0:.0f}s", flush=True)
        real = pool.map(fit_network, [(W, f_peak, fcu, s, tr) for s in range(4)])
        res_geo = pool.map(fit_network, [(B, f_peak, fcu, 100, tr) for B in geo])
        res_str = pool.map(fit_network, [(B, f_peak, fcu, 100, tr) for B in stren])

    real_r = float(np.mean([r["best_r"] for r in real]))

    def summ(rs):
        v = np.array([r["best_r"] for r in rs])
        return {"mean": round(float(v.mean()), 3), "sd": round(float(v.std()), 3), "max": round(float(v.max()), 3),
                "n": len(v), "p": round(float((1 + (v >= real_r).sum()) / (1 + len(v))), 4),
                "best_g_median": float(np.median([r["best_g"] for r in rs]))}

    result = {"date": time.strftime("%Y-%m-%d %H:%M"), "quick": args.quick, "model": "Hopf (Deco 2017), a=-0.02",
              "tr": tr, "peak_freq_hz_median": round(float(np.median(f_peak)), 4), "G_grid": GS.tolist(),
              "real": {"best_r_seeds": [round(r["best_r"], 3) for r in real], "best_r_mean": round(real_r, 3),
                       "best_g": [r["best_g"] for r in real], "curve_seed0": real[0]["curve"]},
              "geometry_null": summ(res_geo), "strength_null": summ(res_str),
              "uncoupled_r_seed0": real[0]["curve"][0], "seconds": round(time.time() - t0)}
    out = HERE / "data" / "analysis" / ("hopf_test_quick.json" if args.quick else "hopf_test.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1))
    print(json.dumps({k: v for k, v in result.items() if k != "G_grid"}, indent=1))


if __name__ == "__main__":
    main()
