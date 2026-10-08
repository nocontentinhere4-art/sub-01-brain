"""Figures for docs/real_wiring_report.md (connectome v1 vs v2, held-out FC, G curve, per-region fit)."""
import json
import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from twin import hopf as H  # noqa: E402

DOCS = ROOT / "docs" / "real_wiring"
CACHE = ROOT / "data" / "analysis"


def main(tag="v2"):
    DOCS.mkdir(parents=True, exist_ok=True)
    names = json.loads((ROOT / "out" / "atlas_names.json").read_text())
    v1 = np.load(ROOT / "out" / "connectome.npz")["weights"]
    v2 = np.load(ROOT / "out" / "connectome_v2.npz")["weights"]
    # 1. connectomes
    fig, ax = plt.subplots(1, 2, figsize=(9, 4.2))
    for a, W, t in ((ax[0], v1, "v1: dipy deterministic, counts, density 45 %"),
                    (ax[1], v2, "v2: MRtrix3 iFOD2 + SIFT2, density 20 %")):
        im = a.imshow(np.log1p(W / np.median(W[W > 0])), cmap="magma")
        a.set_title(t, fontsize=8)
        a.axhline(99.5, color="w", lw=0.5)
        a.axvline(99.5, color="w", lw=0.5)
        a.set_xticks([50, 150, 207])
        a.set_xticklabels(["left", "right", "deep"], fontsize=7)
        a.set_yticks([])
    fig.suptitle("structural connectomes (log weight / median); white lines split the hemispheres", fontsize=9)
    fig.tight_layout()
    fig.savefig(DOCS / "connectomes.png", dpi=80)
    plt.close(fig)
    # 2. held-out FC: recorded vs simulated (wiring only, EC)
    d = np.load(CACHE / f"rw_{tag}_results.npz")
    inp = np.load(CACHE / f"rw_{tag}_inputs.npz")
    rows = json.loads(str(d["rows"]))
    real = rows[0]
    fh = inp["fc_held"]
    fig, ax = plt.subplots(1, 3, figsize=(12, 4))
    for a, M, t in ((ax[0], fh, f"recorded, held-out half ({int(inp['n_held'])} runs)"),
                    (ax[1], d["fc_sim_g"], f"his wiring x G (r = {real['g_held_fc_r']:.2f})"),
                    (ax[2], d["fc_sim_ec"], f"effective connectivity (r = {real['ec_held_fc_r']:.2f})")):
        M = M.copy()
        np.fill_diagonal(M, np.nan)
        mu = np.nanmean(H.upper(M))
        a.imshow(M - mu, cmap="RdBu_r", vmin=-0.4, vmax=0.4)
        a.set_title(f"{t}\nmean FC {mu:.2f} (shown relative to it)", fontsize=8)
        a.set_xticks([])
        a.set_yticks([])
    fig.suptitle("functional connectivity on sessions never used for fitting", fontsize=10)
    fig.tight_layout()
    fig.savefig(DOCS / "fc_heldout.png", dpi=80)
    plt.close(fig)
    # 3. G curve (fit half objective) + per-region fit by network
    from analysis.real_wiring import G_GRID_SIM
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.6))
    grid = d["G_grid"] if "G_grid" in d.files else G_GRID_SIM
    if len(grid) == len(d["G_curve"]):
        ax[0].semilogx(grid, d["G_curve"], "o-")
    ax[0].axvline(real["G"], color="k", ls=":")
    ax[0].set_xlabel("global coupling G")
    ax[0].set_ylabel("fit half: FC r - FCD KS")
    ax[0].set_title("stage 1: choosing G on the fit half only", fontsize=9)
    nets = ["Vis", "SomMot", "DorsAttn", "SalVentAttn", "Limbic", "Cont", "Default"]
    lab = [next((k for k in nets if f"_{k}_" in nm), "deep") for nm in names]
    for key, off, col in (("g_region_r", -0.18, "#4c78a8"), ("ec_region_r", 0.18, "#f58518")):
        v = np.array(real[key])
        groups = nets + ["deep"]
        ax[1].boxplot([v[[i for i, l in enumerate(lab) if l == g]] for g in groups],
                      positions=np.arange(len(groups)) + off, widths=0.3, patch_artist=True,
                      boxprops=dict(facecolor=col, alpha=0.6), medianprops=dict(color="k"), showfliers=False)
    ax[1].set_xticks(range(8))
    ax[1].set_xticklabels(nets + ["deep"], fontsize=7, rotation=30)
    ax[1].set_ylabel("held-out FC-row r per region")
    ax[1].set_title("per-region fit (blue: wiring x G, orange: EC)", fontsize=9)
    fig.tight_layout()
    fig.savefig(DOCS / "g_curve_regions.png", dpi=110)
    plt.close(fig)
    print("figures in", DOCS)


if __name__ == "__main__":
    main(*(sys.argv[1:] or ["v2"]))
