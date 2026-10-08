"""Connectome v2 from the MRtrix3 run (analysis/pod/tract.sh) - local post-processing, light.

Input: data/analysis/connectome_v2_raw.tar.gz from the pod (per-streamline node assignment, SIFT2 weight, length,
and the size of each independent tracking chunk). Output: out/connectome_v2.npz (the old out/connectome.npz is kept).

    weights   SIFT2 fibre bundle capacity (sum of SIFT2 weights x mu) per edge, after the consistency threshold
    counts    raw streamline counts (no threshold)
    lengths   mean streamline length per edge (mm)
    names, centroids (DWI world mm), and a JSON 'meta' with the pipeline and the threshold used.

Consistency threshold. Within one subject there is no group to compute consistency over, so the tracking itself is
split: it ran as K independent chunks of equal size with different random seeds. Probabilistic tracking with
0.5 M streamlines per chunk reaches ~42 % of all region pairs in EVERY chunk, so presence alone cannot thin the
network. Following consistency-based thresholding (Roberts et al. 2017 NeuroImage 145:118-129, there across subjects),
an edge's consistency is the coefficient of variation of its SIFT2 weight across the K chunks; edges present in all
chunks are ranked by CV and the most consistent ones are kept up to DENSITY. False-positive edges from probabilistic
tracking are mostly weak and erratic (Maier-Hein et al. 2017 Nat Commun 8:1349), so they drop out first.
"""
import io
import json
import sys
import tarfile
from pathlib import Path

import nibabel as nib
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DENSITY = 0.20


def read_raw(path):
    tf = tarfile.open(path)
    get = lambda n: tf.extractfile(n).read().decode()
    txt = lambda n: [l for l in get(n).splitlines() if l.strip() and not l.startswith("#")]
    assign = np.loadtxt(io.StringIO("\n".join(txt("assign.txt"))), dtype=np.int32)
    weights = np.array(" ".join(txt("sift2.txt")).split(), float)
    lengths = np.array(" ".join(txt("lengths.txt")).split(), float)
    counts = [int(l.split()[-1]) for l in txt("chunk_counts.txt")]
    mu = float(txt("mu.txt")[0].split()[0])
    assert len(assign) == len(weights) == len(lengths) == sum(counts), (len(assign), len(weights), len(lengths), sum(counts))
    return assign, weights, lengths, np.repeat(np.arange(len(counts)), counts), mu


def build(raw=ROOT / "data" / "analysis" / "connectome_v2_raw.tar.gz", labels=None, density=DENSITY):
    names = json.loads((ROOT / "out" / "atlas_names.json").read_text())
    n = len(names)
    assign, w, L, chunk, mu = read_raw(raw)
    ok = (assign[:, 0] > 0) & (assign[:, 1] > 0) & (assign[:, 0] != assign[:, 1])
    i, j = assign[ok, 0] - 1, assign[ok, 1] - 1
    K = chunk.max() + 1
    fbc = np.zeros((n, n))
    cnt = np.zeros((n, n))
    lsum = np.zeros((n, n))
    per = np.zeros((K, n, n))
    np.add.at(fbc, (i, j), w[ok] * mu)
    np.add.at(cnt, (i, j), 1)
    np.add.at(lsum, (i, j), L[ok])
    np.add.at(per, (chunk[ok], i, j), w[ok] * mu)
    sym = lambda m: m + m.T
    fbc, cnt, lsum = sym(fbc), sym(cnt), sym(lsum)
    per = per + per.transpose(0, 2, 1)
    frac = (per > 0).mean(0)
    cv = per.std(0) / np.maximum(per.mean(0), 1e-12)
    iu = np.triu_indices(n, 1)
    cand = np.where(frac[iu] == 1.0)[0]
    k = int(round(density * len(iu[0])))
    best = cand[np.argsort(cv[iu][cand], kind="stable")[:k]]
    keep = np.zeros((n, n), bool)
    keep[iu[0][best], iu[1][best]] = True
    keep = keep | keep.T
    lengths = np.where(cnt > 0, lsum / np.maximum(cnt, 1), 0)
    W = np.where(keep, fbc, 0)
    lab_img = nib.load(labels or "/home/user/scratch/tract_in/labels.nii.gz")
    lab = np.asarray(lab_img.dataobj)
    cent = np.array([nib.affines.apply_affine(lab_img.affine, np.argwhere(lab == k + 1).mean(0)) for k in range(n)])
    meta = {"pipeline": "MRtrix3 3.0.8: gradient table corrected with dwigradcheck (x flipped, scanner basis), "
                        "dhollander response, msmt-CSD (b=0/1500/3000), mtnormalise, iFOD2 seeded in the DWI white-matter "
                        "mask (FOD cutoff 0.06, 10-250 mm), SIFT2, tck2connectome (radial search 4 mm). ACT was tried "
                        "with a T1-derived 5TT (analysis/make_5tt.py) but truncated streamlines (pilot median 15 mm vs "
                        "71 mm without ACT), so it is not used.",
            "dwi": "OpenNeuro ds000031 sub-01 ses-2015 acq-g79 dir-pe0 (same DWI as connectome v1)",
            "streamlines": int(len(assign)), "assigned": int(ok.sum()), "chunks": int(K), "mu": mu,
            "threshold": "edges present in all chunks, lowest coefficient of variation of SIFT2 weight across chunks",
            "density": float(keep.sum() / (n * (n - 1))), "density_present_in_all_chunks": float((frac == 1).sum() / (n * (n - 1)))}
    return {"weights": W, "counts": cnt, "lengths": lengths, "fraction_chunks": frac, "cv": cv, "names": np.array(names),
            "centroids": cent, "meta": json.dumps(meta)}


def describe(W, names, fc=None):
    from twin.hopf import homotopic_pairs
    n = len(W)
    hemi = np.array(["_LH_" in s or s.startswith("Left") for s in names])
    inter = hemi[:, None] != hemi[None, :]
    off = ~np.eye(n, dtype=bool)
    hom = homotopic_pairs(list(names))
    hom_l = [(p, q) for p, q in hom if p < q]
    ranks = (W[off] > 0).sum()
    out = {"density": float((W[off] > 0).mean()),
           "inter_density": float((W[inter] > 0).mean()), "intra_density": float((W[~inter & off] > 0).mean()),
           "inter_share_of_weight": float(W[inter].sum() / W.sum()),
           "homotopic_pairs": len(hom_l), "homotopic_with_edge": int(sum(W[p, q] > 0 for p, q in hom_l)),
           "homotopic_weight_percentile": float(np.median([(W[off] < W[p, q]).mean() * 100 for p, q in hom_l])),
           "isolated_regions": int(((W > 0).sum(1) == 0).sum())}
    if fc is not None:
        from twin.hopf import fc_r
        out["scfc_r_log1p"] = fc_r(np.log1p(W), fc)
    return out


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    from twin import hopf as H
    d = build(density=float(sys.argv[1]) if len(sys.argv) > 1 else DENSITY)
    np.savez_compressed(ROOT / "out" / "connectome_v2.npz", **{k: d[k] for k in ("weights", "counts", "lengths",
                                                                                  "names", "centroids", "meta")})
    runs = H.load_runs(ROOT / "out" / "rest")
    fc_all = H.mean_fc(runs)
    old = np.load(ROOT / "out" / "connectome.npz")
    print(json.dumps({"meta": json.loads(d["meta"]), "v1": describe(old["weights"], old["names"], fc_all),
                      "v2": describe(d["weights"], d["names"], fc_all)}, indent=1))
