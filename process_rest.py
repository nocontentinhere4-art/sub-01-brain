"""Stream SUB-01's resting-state fMRI runs from OpenNeuro and keep only region time series.

For each run: download BOLD -> mean image -> rigid to the 2022 T1 -> atlas (already
in T1 space) resampled into BOLD space -> mean signal per region -> detrend,
band-pass 0.01-0.1 Hz, z-score -> out/rest/<run>.npz (float16, T x regions).
The raw BOLD file is deleted right after. Runs are processed in parallel worker
processes; runs already in out/rest/ (or rejected in out/rest/qc.json) are skipped.

Usage: python process_rest.py [N_RUNS] [--workers 6]
       python process_rest.py --validate        # QC only: homotopic vs mean correlation
"""
import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")                                     # one thread per worker process

import argparse
import json
import time
import urllib.request
from multiprocessing import Pool
from pathlib import Path

import nibabel as nib
import numpy as np
from dipy.align import affine_registration
from dipy.align.imaffine import AffineMap
from scipy import signal

S3 = "https://s3.amazonaws.com/openneuro.org/"
OUT = Path("out/rest")
QC = OUT / "qc.json"
TMP = Path("data/tmp")
HOMOTOPIC_MIN = 0.3

_labels_t1 = _t1_masked = None                                         # per-worker globals (set by _init)


def atlas_in_t1():
    """Atlas already warped into the 2022 T1 (1 mm) by atlas_subject.py."""
    return nib.load("out/labels_t1.nii.gz")


def _init():
    global _labels_t1, _t1_masked
    _labels_t1 = atlas_in_t1()
    t1_int = nib.load("out/t1_brain_1mm.nii.gz").get_fdata()          # skull-stripped: no face in the repo
    _t1_masked = t1_int * (_labels_t1.get_fdata() > 0)


def run_name(key):
    return Path(key).name.replace("_bold.nii.gz", "")


def fetch(url, dst, tries=3):
    for i in range(tries):
        try:
            urllib.request.urlretrieve(url, dst)
            return
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(5 * 2 ** i)


def process(key, n_regions):
    name = run_name(key)
    dst = OUT / f"{name}.npz"
    if dst.exists():
        return "cached"
    tr = json.loads(urllib.request.urlopen(S3 + key.replace(".nii.gz", ".json")).read())["RepetitionTime"]
    tmp = TMP / Path(key).name
    try:
        fetch(S3 + key, tmp)
        bold = nib.load(tmp)
        data = np.asanyarray(bold.dataobj.get_unscaled())             # raw ints: ~1/4 the RAM of float32
        slope, inter = bold.dataobj.slope, bold.dataobj.inter           # scaling is linear: apply to means
        mean = data.mean(-1, dtype=np.float32) * slope + inter
        _, t1_to_bold = affine_registration(_t1_masked, mean, moving_affine=_labels_t1.affine,
                                            static_affine=bold.affine, nbins=32,
                                            pipeline=["center_of_mass", "translation", "rigid"],
                                            level_iters=[10000, 1000, 100])
        amap = AffineMap(t1_to_bold, domain_grid_shape=mean.shape, domain_grid2world=bold.affine,
                         codomain_grid_shape=_labels_t1.shape, codomain_grid2world=_labels_t1.affine)
        lab = amap.transform(_labels_t1.get_fdata(), interpolation="nearest").astype(int)
        flat = data.reshape(-1, data.shape[-1])
        lab = lab.ravel()
        ts = np.full((data.shape[-1], n_regions), np.nan, np.float32)
        for k in range(1, n_regions + 1):
            vox = flat[lab == k]
            if len(vox) >= 5:
                ts[:, k - 1] = vox.mean(0, dtype=np.float64) * slope + inter
        del data, flat
        ts = ts[5:]                                                    # drop scanner warm-up volumes
        ok = ~np.isnan(ts).any(0)
        x = signal.detrend(ts[:, ok], axis=0)
        b, a = signal.butter(2, [0.01 * 2 * tr, min(0.1 * 2 * tr, 0.99)], btype="band")
        x = signal.filtfilt(b, a, x, axis=0)
        x = (x - x.mean(0)) / (x.std(0) + 1e-6)
        ts[:, ok] = x
        part = OUT / f"{name}.part.npz"                                # atomic: no half-written "cached" runs
        np.savez_compressed(part, ts=ts.astype(np.float16), tr=tr, key=key)
        part.rename(dst)
        return f"{ts.shape[0]} volumes, TR {tr:.2f}s, {ok.sum()} regions with signal"
    finally:
        tmp.unlink(missing_ok=True)                                    # never keep the raw file


def _job(args):
    key, n_regions = args
    t0 = time.time()
    try:
        return key, True, f"{process(key, n_regions)} ({time.time() - t0:.0f}s)"
    except Exception as e:
        return key, False, f"{type(e).__name__}: {e}"


def homotopic_pairs(names):
    """Left/right region pairs matched by name (Schaefer LH_/RH_ parcels, Harvard-Oxford Left/Right)."""
    pairs = []
    for i, x in enumerate(names):
        y = x.replace("_LH_", "_RH_") if "_LH_" in x else "Right " + x[5:] if x.startswith("Left ") else None
        if y in names:
            pairs.append((i, names.index(y)))
    return pairs


def validate(names):
    """Homotopic vs mean inter-region correlation per run; move runs with homotopic < 0.3 out of out/rest/."""
    pairs = np.array(homotopic_pairs(names))
    qc = json.loads(QC.read_text()) if QC.exists() else {}
    rejected_dir = OUT / "rejected"
    for f in sorted(OUT.glob("*.npz")):
        ts = np.load(f)["ts"].astype(np.float64)
        ok = ~np.isnan(ts).any(0)
        c = np.full((ts.shape[1],) * 2, np.nan)
        c[np.ix_(ok, ok)] = np.corrcoef(ts[:, ok].T)
        homo = np.nanmean(c[pairs[:, 0], pairs[:, 1]])
        mean = np.nanmean(c[np.triu_indices(len(c), 1)])
        keep = bool(homo >= HOMOTOPIC_MIN)
        qc[f.stem] = {"homotopic": round(float(homo), 3), "mean": round(float(mean), 3), "kept": keep}
        if not keep:
            rejected_dir.mkdir(exist_ok=True)
            f.rename(rejected_dir / f.name)
    QC.write_text(json.dumps(dict(sorted(qc.items())), indent=1) + "\n")
    kept = {k: v for k, v in qc.items() if v["kept"]}
    dropped = {k: v for k, v in qc.items() if not v["kept"]}
    print(f"QC: {len(kept)} kept, {len(dropped)} dropped (homotopic < {HOMOTOPIC_MIN})")
    if kept:
        print(f"  kept runs: median homotopic {np.median([v['homotopic'] for v in kept.values()]):.2f}, "
              f"median mean {np.median([v['mean'] for v in kept.values()]):.2f}")
    for k, v in sorted(dropped.items()):
        print(f"  dropped {k}: homotopic {v['homotopic']:.2f}, mean {v['mean']:.2f}")
    return qc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("n_runs", nargs="?", type=int, default=1)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--validate", action="store_true", help="only run the QC on out/rest/")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    names = json.load(open("out/atlas_names.json"))
    if args.validate:
        validate(names)
        return
    rejected = {k for k, v in json.loads(QC.read_text()).items() if not v["kept"]} if QC.exists() else set()
    keys = Path("rest_runs.txt").read_text().split()[:args.n_runs]
    todo = [k for k in keys if not (OUT / f"{run_name(k)}.npz").exists() and run_name(k) not in rejected]
    print(f"{len(keys)} runs: {len(keys) - len(todo)} already done, {len(todo)} to process "
          f"with {args.workers} workers", flush=True)
    failed = []
    with Pool(args.workers, initializer=_init) as pool:
        for key, ok, msg in pool.imap_unordered(_job, [(k, len(names)) for k in todo]):
            print(Path(key).name, "->", msg if ok else f"FAILED {msg}", flush=True)
            if not ok:
                failed.append((key, msg))
    print(f"done: {len(todo) - len(failed)} processed, {len(failed)} failed")
    for key, msg in failed:
        print(f"  FAILED {key}: {msg}")
    validate(names)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
