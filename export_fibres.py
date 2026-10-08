"""Export SUB-01's real tractography (traced nerve-fibre bundles) for the web viewer.

Re-runs the same CSD tracking as build_connectome.py, keeps a random subset of
streamlines, resamples each to 24 points and writes web/fibres.bin (float32
x,y,z per point, centred on the brain) + web/fibres.json (counts).
"""
import json
from pathlib import Path

import nibabel as nib
import numpy as np
from dipy.core.gradients import gradient_table
from dipy.data import default_sphere
from dipy.direction import peaks_from_model
from dipy.reconst.csdeconv import ConstrainedSphericalDeconvModel, auto_response_ssst
from dipy.segment.mask import median_otsu
from dipy.tracking import utils
from dipy.tracking.local_tracking import LocalTracking
from dipy.tracking.stopping_criterion import ThresholdStoppingCriterion
from dipy.tracking.streamline import Streamlines, length, set_number_of_points

D = Path("data")
DWI = "sub-01_ses-2015_acq-g79_dir-pe0_dwi"
KEEP = 60000
PTS = 24


def main():
    img = nib.load(D / f"{DWI}.nii.gz")
    data = img.get_fdata(dtype=np.float32)
    bvals = np.loadtxt(D / f"{DWI}.bval")
    bvecs = np.loadtxt(D / f"{DWI}.bvec")
    bvals = np.where(bvals < 50, 0, np.round(bvals / 500) * 500)
    gtab = gradient_table(bvals, bvecs=bvecs)
    _, mask = median_otsu(data, vol_idx=np.where(gtab.b0s_mask)[0], median_radius=3, numpass=2)
    fa = nib.load("out/fa.nii.gz").get_fdata()
    hi = (bvals == 0) | (bvals == 3000)
    g_hi = gradient_table(bvals[hi], bvecs=bvecs[:, hi] if bvecs.shape[0] == 3 else bvecs[hi])
    resp, _ = auto_response_ssst(g_hi, data[..., hi], roi_radii=10, fa_thr=0.7)
    peaks = peaks_from_model(ConstrainedSphericalDeconvModel(g_hi, resp, sh_order_max=6), data[..., hi],
                             default_sphere, relative_peak_threshold=0.5, min_separation_angle=25,
                             mask=mask, npeaks=3, parallel=True, num_processes=16)
    seeds = utils.seeds_from_mask((fa > 0.25) & mask, img.affine, density=2)
    sl = Streamlines(s for s in LocalTracking(peaks, ThresholdStoppingCriterion(fa, 0.15), seeds,
                                              img.affine, step_size=0.75, max_cross=1) if len(s) > 1)
    lens = np.array(list(length(sl)))
    good = np.where(lens > 30)[0]
    total = len(good)
    rng = np.random.default_rng(1)
    pick = rng.choice(good, size=min(KEEP, total), replace=False)
    sub = set_number_of_points(Streamlines([sl[i] for i in pick]), PTS)
    arr = np.asarray(sub, dtype=np.float32)            # (n, PTS, 3), scanner mm
    # atlas label at each end (labels_dwi already grown into white matter by build_connectome)
    lab_img = nib.load("out/labels_dwi.nii.gz")
    lab = lab_img.get_fdata().astype(np.int16)
    inv = np.linalg.inv(lab_img.affine)
    ends = np.zeros((arr.shape[0], 2), np.int16)
    for j, idx in enumerate((0, PTS - 1)):
        vox = np.rint(nib.affines.apply_affine(inv, arr[:, idx])).astype(int)
        vox = np.clip(vox, 0, np.array(lab.shape) - 1)
        ends[:, j] = lab[vox[:, 0], vox[:, 1], vox[:, 2]]
    offset = arr.reshape(-1, 3).mean(0)
    arr -= offset
    arr.tofile("web/fibres.bin")
    ends.tofile("web/fibres_ends.bin")
    json.dump({"n": int(arr.shape[0]), "pts": PTS, "total": int(total), "offset": offset.round(2).tolist(),
               "ends_labelled": int((ends > 0).all(1).sum())}, open("web/fibres.json", "w"))
    print(f"total streamlines >30mm: {total}, exported {arr.shape[0]}")


if __name__ == "__main__":
    main()
