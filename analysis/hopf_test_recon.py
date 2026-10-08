"""BOLD-band Hopf model (Deco et al. 2017) on a connectome, only the global coupling G fitted.

Reconstruction of the original quick test (its file was not in the repository). Analytic (linearised) FC for a grid of
G, compared with the mean FC of all runs; with the simulated-data check that matters in practice: at each G, FC r and
FCD KS of 10 simulated 10-minute runs processed like the real data.

    python analysis/hopf_test_recon.py [--conn out/connectome.npz]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from twin import hopf as H  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--conn", default=str(ROOT / "out" / "connectome.npz"))
    a = p.parse_args()
    import torch
    torch.set_num_threads(1)
    runs = H.load_runs(ROOT / "out" / "rest")
    fc, fcd = H.mean_fc(runs), H.fcd_pool(runs)
    W = np.load(a.conn)["weights"]
    SC = H.sc_matrix(np.log1p(W))
    f = H.peak_freqs(runs)
    w, aa = 2 * np.pi * f, np.full(len(W), H.A_BIF)
    Gs = np.geomspace(1e-3, 3.0, 20)
    r_an = H.fit_G(SC, aa, w, fc, Gs)
    rows = []
    for G, ra in zip(Gs, r_an):
        sim = H.simulate_linear(G * SC, aa, w, 10, 600, H.LAG_TR, seed=1)
        rows.append({"G": round(float(G), 4), "fc_r_analytic": round(float(ra), 3),
                     "fc_r_simulated": round(H.fc_r(H.mean_fc(sim), fc), 3),
                     "fcd_ks": round(float(stats.ks_2samp(H.fcd_pool(sim), fcd).statistic), 3)})
    print(json.dumps({"conn": a.conn, "rows": rows}, indent=1))


if __name__ == "__main__":
    main()
