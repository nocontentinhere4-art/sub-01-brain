"""Put the atlas and a brain mask into SUB-01's own anatomy (2022 T1, 1 mm), once.

Registers the ICBM152 2009 *whole-head* T1 to the subject's whole-head T1 (a
brain-only template stretched to a head is what broke the first version), then
warps the ICBM brain mask, Schaefer-200 and Harvard-Oxford deep nuclei with it.
Also computes the rigid T1 -> 2015 DWI transform.

Outputs: out/t1_1mm.nii.gz, out/brainmask_t1.nii.gz, out/labels_t1.nii.gz,
out/atlas_names.json, out/t1_to_dwi.npy (dipy convention: DWI world -> T1 world).
"""
import json

import nibabel as nib
import numpy as np
from dipy.align import affine_registration, syn_registration
from nilearn import datasets, image
from scipy import ndimage

DEEP = ["Thalamus", "Caudate", "Putamen", "Pallidum", "Hippocampus", "Amygdala", "Accumbens"]


def main():
    t1 = image.resample_img(nib.load("data/sub-01_ses-2022_T1w.nii.gz"), target_affine=np.diag([1.0] * 3),
                            interpolation="continuous", force_resample=True, copy_header=True)
    nib.save(t1, "out/t1_1mm.nii.gz")
    icbm = datasets.fetch_icbm152_2009()
    tpl = nib.load(icbm["t1"])
    T, S = t1.get_fdata(), tpl.get_fdata()

    _, aff = affine_registration(S, T, moving_affine=tpl.affine, static_affine=t1.affine, nbins=32,
                                 pipeline=["center_of_mass", "translation", "rigid", "affine"],
                                 level_iters=[10000, 1000, 100])
    _, mapping = syn_registration(S, T, moving_affine=tpl.affine, static_affine=t1.affine, prealign=aff,
                                  level_iters=[20, 20, 10])

    def warp(img, nearest=True):
        a = image.resample_to_img(img, tpl, interpolation="nearest" if nearest else "continuous",
                                  force_resample=True, copy_header=True)
        return mapping.transform(a.get_fdata(), interpolation="nearest" if nearest else "linear")

    mask = warp(nib.load(icbm["mask"]), nearest=False) > 0.5
    mask = ndimage.binary_fill_holes(mask)
    nib.save(nib.Nifti1Image(mask.astype(np.uint8), t1.affine), "out/brainmask_t1.nii.gz")
    nib.save(nib.Nifti1Image((T * mask).astype(np.float32), t1.affine), "out/t1_brain_1mm.nii.gz")  # no face
    print("brain mask", int(mask.sum()), "voxels (~cm3)", flush=True)

    sch = datasets.fetch_atlas_schaefer_2018(n_rois=200, yeo_networks=7, resolution_mm=1)
    ho = datasets.fetch_atlas_harvard_oxford("sub-maxprob-thr25-1mm")
    names = [str(x.decode() if isinstance(x, bytes) else x) for x in sch.labels if str(x) != "Background"]
    lab = warp(sch.maps).astype(np.int16)
    sub = warp(ho.maps).astype(np.int16)
    ho_names = list(ho.labels)
    for i, nm in enumerate(ho_names):
        if any(k in nm for k in DEEP):
            names.append(nm)
            lab[sub == i] = len(names)          # deep nuclei take priority over cortex
    lab = lab * mask
    nib.save(nib.Nifti1Image(lab, t1.affine), "out/labels_t1.nii.gz")
    json.dump(names, open("out/atlas_names.json", "w"))
    print("labels", len(names), "present", len(np.unique(lab)) - 1, flush=True)

    b0 = nib.load("out/mean_b0.nii.gz")
    _, t1_to_dwi = affine_registration(T * mask, b0.get_fdata(), moving_affine=t1.affine, static_affine=b0.affine,
                                       nbins=32, pipeline=["center_of_mass", "translation", "rigid"],
                                       level_iters=[10000, 1000, 100])
    np.save("out/t1_to_dwi.npy", t1_to_dwi)
    print("saved atlas in subject space", flush=True)


if __name__ == "__main__":
    main()
