"""Inputs for MRtrix3 tractography (connectome v2), made locally from files already in out/:

- 5TT image (Smith et al. 2012 ACT format: cGM, sGM, WM, CSF, pathological) from the subject's skull-stripped T1:
  3-class Gaussian-mixture tissue partial volumes on a bias-corrected T1 for cGM/WM/CSF, and the
  14 Harvard-Oxford deep nuclei of out/labels_t1.nii.gz as sub-cortical GM (they replace whatever tissue was there).
- the 214-region parcellation (out/labels_t1.nii.gz, unchanged voxels).
Both stay on the T1 1 mm grid; only their header is moved into DWI world space with out/t1_to_dwi.npy
(dipy convention: T1 world = A @ DWI world), i.e. new affine = inv(A) @ T1 affine. No resampling.

FSL (5ttgen fsl) and FreeSurfer (5ttgen hsvs) are not used: this is a simpler, documented substitute.
"""
import sys
from pathlib import Path

import nibabel as nib
import numpy as np
from scipy import ndimage

OUT = Path(__file__).resolve().parents[1] / "out"
dst = Path(sys.argv[1] if len(sys.argv) > 1 else "/home/user/scratch/tract_in")
dst.mkdir(parents=True, exist_ok=True)

t1 = nib.load(OUT / "t1_brain_1mm.nii.gz")
lab = nib.load(OUT / "labels_t1.nii.gz")
mask = nib.load(OUT / "brainmask_t1.nii.gz").get_fdata() > 0
A = np.load(OUT / "t1_to_dwi.npy")
aff = np.linalg.inv(A) @ t1.affine
assert np.allclose(t1.affine, lab.affine)

T = t1.get_fdata().astype(np.float32)
T[~mask] = 0
# crude bias-field correction (no N4 available): divide by a smooth field fitted to the brighter half of the tissue
# (normalised convolution, sigma 15 mm), twice
for _ in range(2):
    sel = mask & (T > np.percentile(T[mask], 50))
    field = ndimage.gaussian_filter(T * sel, 15) / np.maximum(ndimage.gaussian_filter(sel.astype(np.float32), 15), 1e-3)
    T = np.where(mask, T / np.maximum(field, 1e-3) * np.median(T[sel]), 0).astype(np.float32)
# 3-class Gaussian mixture on the bias-corrected intensities (EM, initialised at the histogram's CSF / GM / WM modes),
# posteriors lightly smoothed (sigma 0.7 mm) as a simple spatial prior -> partial-volume fractions
v = T[mask].astype(np.float64)
mu = np.percentile(v, [8, 45, 85])
sd = np.full(3, v.std() / 4)
w = np.full(3, 1 / 3)
for _ in range(200):
    lik = w * np.exp(-0.5 * ((v[:, None] - mu) / sd) ** 2) / sd
    post = lik / lik.sum(1, keepdims=True)
    w, mu = post.mean(0), (post * v[:, None]).sum(0) / post.sum(0)
    sd = np.sqrt((post * (v[:, None] - mu) ** 2).sum(0) / post.sum(0))
pve = np.zeros(T.shape + (3,), np.float32)
pve[mask] = post
pve = np.stack([ndimage.gaussian_filter(pve[..., k], 0.7) for k in range(3)], -1)
pve /= np.maximum(pve.sum(-1, keepdims=True), 1e-6)
print("mixture means / sds:", mu.round(0), sd.round(0), "weights", w.round(2))
csf, gm, wm = (pve[..., k] for k in range(3))
L = lab.get_fdata().astype(np.int32)
sgm = (L > 200).astype(np.float32)                  # 14 deep nuclei = labels 201..214
sgm = np.maximum(sgm, ndimage.gaussian_filter(sgm, 0.5) * (L > 200))
rest = 1 - sgm
tt = np.stack([gm * rest, sgm, wm * rest, csf * rest, np.zeros_like(gm)], -1).astype(np.float32)
tt[~mask] = 0
s = tt.sum(-1, keepdims=True)
tt = np.where(s > 0, tt / np.maximum(s, 1e-6), 0)
nib.save(nib.Nifti1Image(tt, aff), dst / "5tt.nii.gz")
nib.save(nib.Nifti1Image(L.astype(np.int16), aff), dst / "labels.nii.gz")
nib.save(nib.Nifti1Image(mask.astype(np.uint8), aff), dst / "mask_t1grid.nii.gz")
print("5TT volume fractions (cGM, sGM, WM, CSF):", [round(float(tt[..., k].sum() / 1000), 1) for k in range(4)], "cm3")
print("T1 intensity means per class:", [round(float((T * pve[..., k]).sum() / pve[..., k].sum())) for k in range(3)])
print("labels present:", len(np.unique(L)) - 1)
