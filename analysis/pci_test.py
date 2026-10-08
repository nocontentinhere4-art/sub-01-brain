"""The perturbational complexity index (PCI) on SUB-01's brain model, awake / deep sleep / REM.

PCI is how clinicians estimate whether an unresponsive patient is likely conscious (Casali et al. 2013, Sci Transl
Med 5:198ra105): give a brief magnetic pulse (TMS), record the EEG echo over many trials, keep only the parts of the
response that are statistically significant, and measure how complex (compressible) that spatiotemporal pattern is.
Awake and dreaming people give rich, differentiated echoes (PCI above ~0.31); deep sleep and anaesthesia give
simple ones (below ~0.31) (Casarotto et al. 2016, Ann Neurol 80:718).

Here the "pulse" is a sudden kick to the activity of one region of the model, repeated over many trials in each
sleep stage (parameters from sleep.py), and the "EEG" is the model's regional signal. Same statistics, same
normalised Lempel-Ziv complexity. A model producing a clinical-looking number is NOT evidence that it experiences
anything: PCI is validated on human brains, where it correlates with reported experience.

Run: .venv/bin/python analysis/pci_test.py   -> docs/pci/results.json, docs/pci/pci_*.png
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from brain_sim import Brain  # noqa: E402
from sleep import AWAKE, NREM_DEEP, REM  # noqa: E402

OUT = HERE / "docs" / "pci" / os.environ.get("PCI_TAG", "")
STAGES = {"awake": AWAKE, "deep sleep (NREM)": NREM_DEEP, "dreaming (REM)": REM}
TARGETS = ("7Networks_LH_DorsAttn_Post_1", "7Networks_RH_SomMot_1")       # parietal and sensorimotor sites, as in TMS-EEG studies
TRIALS = int(os.environ.get("PCI_TRIALS", 60))
PRE_MS, POST_MS, BIN_MS = 200, 300, 2
KICK = float(os.environ.get("PCI_KICK", 1.5))                                            # pulse: added to the target's complex state (|z| ~ 0.1 at rest)
ALPHA = 0.01                                          # significance threshold (bootstrap of the baseline maximum)


def run_stage(job):
    name, params, target, seed = job
    b = Brain(seed=seed)
    b.set_rhythm(params["f_hz"], params["coupling"] * float(os.environ.get("PCI_COUPLING_X", 1)), params["noise"])
    b.a = params["a"]
    ti = b.names.index(target)
    b.run(2.0, every=50)                              # settle into the stage
    steps_pre, steps_post = PRE_MS, POST_MS
    trials = []
    for k in range(TRIALS):
        b.run(0.4 + 0.2 * np.random.default_rng(seed * 1000 + k).random(), every=50)   # jittered inter-pulse interval
        rec = []
        for _ in range(steps_pre):
            rec.append(b.step(1).real.copy())
        b.buf[b.t % b.hist, ti] += KICK               # the pulse
        for _ in range(steps_post):
            rec.append(b.step(1).real.copy())
        trials.append(np.array(rec))
    x = np.array(trials)                              # trials x time(ms) x regions
    x = x.reshape(TRIALS, (steps_pre + steps_post) // BIN_MS, BIN_MS, -1).mean(2)   # 2 ms bins
    return name, target, x, b.names


def lz76(s):
    """Lempel-Ziv 1976 complexity (Kaspar & Schuster 1987) of a binary sequence."""
    n = len(s)
    if n == 0:
        return 0
    i, k, l, c, kmax = 0, 1, 1, 1, 1
    while True:
        if s[i + k - 1] == s[l + k - 1]:
            k += 1
            if l + k > n:
                c += 1
                break
        else:
            kmax = max(k, kmax)
            i += 1
            if i == l:
                c += 1
                l += kmax
                if l + 1 > n:
                    break
                i, k, kmax = 0, 1, 1
            else:
                k = 1
    return c


def pci(x, rng):
    """Casali 2013: significant binary matrix from a bootstrap of the baseline, then normalised LZ complexity."""
    nb = PRE_MS // BIN_MS
    base = x[:, :nb] - x[:, :nb].mean(1, keepdims=True)
    post = x[:, nb:] - x[:, :nb].mean(1, keepdims=True)
    evoked = post.mean(0)                             # time x regions, trial average (phase-locked echo)
    sd = base.mean(0).std(0) + 1e-12                  # per-region baseline sd of the trial-averaged signal
    z = np.abs(evoked) / sd
    # bootstrap: shuffle baseline samples across time per trial, take the maximum |z| over regions and time
    maxes = []
    for _ in range(300):
        sh = np.array([tr[rng.permutation(nb)] for tr in base]).mean(0)
        maxes.append((np.abs(sh) / sd).max())
    thr = np.quantile(maxes, 1 - ALPHA)
    sig = (z > thr).astype(np.uint8)                  # time x regions
    order = np.argsort(sig.sum(0))                    # sources sorted by total activity (as in Casali 2013)
    sig = sig[:, order]
    seq = sig.T.flatten()                             # concatenated per source over time
    L = seq.size
    p = seq.mean()
    if p == 0 or p == 1:
        return 0.0, sig, float(p), float(thr)
    h = -p * np.log2(p) - (1 - p) * np.log2(1 - p)
    return float(lz76(seq.tolist()) / (L * h / np.log2(L))), sig, float(p), float(thr)


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [(n, p, tgt, 7 + i) for i, (n, p) in enumerate(STAGES.items()) for tgt in TARGETS]
    with Pool(min(6, len(jobs))) as pool:
        res = pool.map(run_stage, jobs)
    rng = np.random.default_rng(0)
    out = {"method": "Casali 2013 PCI on the model's regional signal; 60 trials, 300 ms, 2 ms bins, alpha 0.01",
           "clinical_reference": "people: conscious > ~0.31 > unconscious (Casarotto 2016)", "stages": {}}
    figs = {}
    for name, target, x, names in res:
        v, sig, p, thr = pci(x, rng)
        out["stages"].setdefault(name, {})[target] = {"pci": round(v, 3), "active_fraction": round(p, 4)}
        figs.setdefault(name, sig)
        print(f"{name:20s} {target:22s} PCI {v:.3f}  active {p:.3f}", flush=True)
    for name, d in out["stages"].items():
        d["mean"] = round(float(np.mean([v["pci"] for v in d.values()])), 3)
    out["seconds"] = round(time.time() - t0)
    (OUT / "results.json").write_text(json.dumps(out, indent=1))
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(1, 3, figsize=(15, 4.6), facecolor="#08080b")
        cols = {"awake": "#ff9a3c", "deep sleep (NREM)": "#4d7cff", "dreaming (REM)": "#c26bff"}
        for ax, (name, sig) in zip(axes, figs.items()):
            ax.imshow(sig.T, aspect="auto", cmap=matplotlib.colors.ListedColormap(["#0c0c12", cols[name]]),
                      extent=[0, POST_MS, 0, sig.shape[1]], interpolation="nearest")
            ax.set_title(f"{name}\nPCI {out['stages'][name]['mean']:.2f}", color="#ececf2", fontsize=13)
            ax.set_xlabel("ms after the pulse", color="#8a8a9c"); ax.set_ylabel("brain regions", color="#8a8a9c")
            ax.tick_params(colors="#8a8a9c")
            for s in ax.spines.values():
                s.set_color("#2a2a36")
        fig.suptitle("Significant response to a simulated pulse (SUB-01 brain model)", color="#ececf2", fontsize=14)
        fig.tight_layout()
        fig.savefig(OUT / "pci_maps.png", dpi=150, facecolor=fig.get_facecolor())
    except Exception as e:
        print("plot skipped:", e)
    print(json.dumps({k: v["mean"] for k, v in out["stages"].items()}), f"{out['seconds']}s")


if __name__ == "__main__":
    main()
