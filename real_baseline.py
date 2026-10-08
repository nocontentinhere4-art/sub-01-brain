"""SUB-01's own recorded resting-state activity as the brain's background ("what it does when nobody writes").

Plays the 131 QC-passed resting-state fMRI runs (out/rest/*.npz, z-scored region x time) back in real time,
one after another, interpolating between volumes. The value of each region at the current moment becomes a
slow excitability drive on the simulation: regions that were active in the real brain at that moment in the
scanner oscillate more strongly now. Fast rhythms are simulated; their slow waxing and waning is his.
"""
import glob
import json
from pathlib import Path

import numpy as np


class RealBaseline:
    def __init__(self, brain_names, rest_dir="out/rest", seed=0):
        qc_path = Path(rest_dir) / "qc.json"
        rejected = set()
        if qc_path.exists():
            qc = json.loads(qc_path.read_text())
            rows = qc.get("runs", qc) if isinstance(qc, dict) else qc
            if isinstance(rows, dict):
                rows = [dict(run=k, **v) if isinstance(v, dict) else {"run": k} for k, v in rows.items()]
            rejected = {r.get("run") for r in rows if isinstance(r, dict) and not r.get("kept", True)}
        self.files = [f for f in sorted(glob.glob(f"{rest_dir}/*.npz")) if Path(f).stem not in rejected]
        atlas = json.load(open(Path(rest_dir).parent / "atlas_names.json"))
        self.cols = [atlas.index(n) for n in brain_names]   # atlas column for each brain region
        self.rng = np.random.default_rng(seed)
        self.order = list(self.rng.permutation(len(self.files)))
        self.k = -1
        self._next_run()

    def _next_run(self):
        self.k = (self.k + 1) % len(self.order)
        d = np.load(self.files[self.order[self.k]])
        ts = np.nan_to_num(d["ts"].astype(np.float32))[:, self.cols]
        self.ts, self.tr = ts, float(d["tr"])
        self.run = Path(self.files[self.order[self.k]]).stem
        self.t = 0.0

    def advance(self, dt):
        """Move dt seconds along the recording; returns the z-scored region vector for now."""
        self.t += dt
        pos = self.t / self.tr
        if pos >= len(self.ts) - 1:
            self._next_run()
            pos = 0.0
        i = int(pos)
        f = pos - i
        return (1 - f) * self.ts[i] + f * self.ts[i + 1]

    def status(self):
        ses = self.run.split("_")[1] if "_" in self.run else self.run
        return {"run": ses, "minute": round(self.t / 60, 1), "runs": len(self.files)}
