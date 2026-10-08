"""Extract SUB-01's real cortical surface (the folded outer brain) from the 2022 T1 MRI.

1 mm T1 + brain mask from atlas_subject.py -> 3-class tissue
segmentation (CSF / grey / white) -> grey+white surface via marching cubes ->
simplified mesh, moved into the 2015 DWI frame so it wraps the real fibres.
Writes web/cortex.bin (float32 vertices) + web/cortex_idx.bin (uint32 faces).
"""
import json

import fast_simplification
import nibabel as nib
import numpy as np
from dipy.segment.tissue import TissueClassifierHMRF
from scipy import ndimage
from skimage import measure


def main():
    t1_img = nib.load("out/t1_1mm.nii.gz")
    t1 = t1_img.get_fdata()
    mask = nib.load("out/brainmask_t1.nii.gz").get_fdata() > 0
    print("brain mask voxels", mask.sum(), flush=True)

    # 3-class tissue segmentation inside the mask
    x = np.where(mask, t1, 0)
    x = x / np.percentile(x[mask], 99.5)
    _, seg, _ = TissueClassifierHMRF().classify(np.clip(x, 0, 1.2), nclasses=3, beta=0.1, max_iter=10)
    # classes are ordered by intensity: 1 = CSF, 2 = grey, 3 = white (T1)
    brain = mask & (seg >= 2)
    brain = ndimage.binary_closing(brain, iterations=1)
    lab, n = ndimage.label(brain)
    brain = lab == (np.bincount(lab.ravel())[1:].argmax() + 1)        # largest piece = the brain
    brain = ndimage.binary_fill_holes(brain)
    smooth = ndimage.gaussian_filter(brain.astype(np.float32), 0.8)
    verts, faces, _, _ = measure.marching_cubes(smooth, 0.5)
    verts = nib.affines.apply_affine(t1_img.affine, verts)            # T1 world mm
    print("raw mesh", len(verts), "verts", len(faces), "faces", flush=True)
    v2, f2 = fast_simplification.simplify(verts.astype(np.float32), faces.astype(np.int64), target_reduction=0.8)
    print("simplified", len(v2), "verts", len(f2), "faces", flush=True)

    t1_to_dwi = np.load("out/t1_to_dwi.npy")                          # from atlas_subject.py
    # dipy's affine maps static (DWI) world -> moving (T1) world; vertices go the other way
    v_dwi = nib.affines.apply_affine(np.linalg.inv(t1_to_dwi), v2)
    offset = np.array(json.load(open("web/fibres.json"))["offset"])
    (v_dwi - offset).astype(np.float32).tofile("web/cortex.bin")
    f2.astype(np.uint32).tofile("web/cortex_idx.bin")
    json.dump({"verts": int(len(v2)), "faces": int(len(f2))}, open("web/cortex.json", "w"))
    print("saved web/cortex.*", flush=True)


if __name__ == "__main__":
    main()
