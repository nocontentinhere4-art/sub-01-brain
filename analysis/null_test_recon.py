"""SC-FC test: does the subject's wiring predict the subject's functional connectivity better than randomised wiring?

Reconstruction of the original analysis (its file was not in the repository): Pearson r between log(1 + streamline
weight) and the mean resting-state FC (Fisher-z average over the 131 QC-passed runs), over all region pairs, for the
real connectome and for N geometry-preserving (degree + edge-length distribution, Betzel & Bassett 2018) and
strength-preserving (simulated annealing) nulls from netneurotools (BSD-3).

    python analysis/null_test_recon.py [--conn out/connectome.npz] [--geo 500] [--strength 100]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from twin import hopf as H  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--conn", default=str(ROOT / "out" / "connectome.npz"))
    p.add_argument("--geo", type=int, default=500)
    p.add_argument("--strength", type=int, default=100)
    a = p.parse_args()
    from netneurotools import networks
    z = np.load(a.conn)
    W = np.log1p(z["weights"].astype(float))
    W = (W + W.T) / 2
    np.fill_diagonal(W, 0)
    c = z["centroids"]
    D = np.linalg.norm(c[:, None] - c[None], axis=-1)
    fc = H.mean_fc(H.load_runs(ROOT / "out" / "rest"))
    real = H.fc_r(W, fc)
    E = int((W > 0).sum() // 2)
    geo = [H.fc_r(networks.match_length_degree_distribution(W, D, nbins=10, nswap=E * 20, seed=k)[1], fc)
           for k in range(a.geo)]
    st = [H.fc_r(networks.strength_preserving_rand_sa(W, seed=k)[0], fc) for k in range(a.strength)]
    out = {"conn": a.conn, "density": float((W > 0).mean()), "scfc_r": real}
    for name, v in (("geometry", geo), ("strength", st)):
        v = np.array(v)
        if len(v):
            out[name] = {"n": len(v), "mean": float(v.mean()), "max": float(v.max()),
                         "p": float((1 + (v >= real).sum()) / (1 + len(v)))}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
