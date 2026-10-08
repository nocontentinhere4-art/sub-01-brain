"""The dural sinuses and large cerebral veins from the VENAT atlas (analysis/build_anatomy.py, stage `veins`).

VENAT (Huck J et al. 2019, "High resolution atlas of the venous brain vasculature from 7 T quantitative susceptibility
maps", Brain Struct Funct 224:2467; figshare 10.6084/m9.figshare.7205960, CC BY 4.0): a population atlas (20 adults) of
the veins in MNI space at 0.5 mm. `VENAT_PartialVolume.nii.gz` is the mean partial volume of vein in each voxel. Its
iso-surface at `TH`, keeping only the connected pieces of at least `MIN_VOX` voxels, gives the superior sagittal, straight
and transverse sinuses, the internal cerebral veins and the larger superficial veins; the small bridging veins are below
the threshold and are NOT drawn (the caption says so).

Into his frame: the template -> his T1 affine saved by stage `register` (dipy: static (his) world -> moving (template)
world, so the inverse is applied), then T1 world -> the page frame (build_anatomy.web_from_t1). An affine fit of a
population atlas: the caption calls it an atlas, fitted to his brain. Veins just under his cortex surface are pressed
onto it like the arteries (bp3d_parts.press_to_surface).
"""
import numpy as np

TH = 0.4                   # partial volume of vein, 0..0.83 in the atlas (below 0.4 the sinuses merge into fat blobs)
MIN_VOX = 500              # 0.06 cm3 at 0.5 mm: the sinuses and named veins, not specks
FACES = 14000
URL = "https://ndownloader.figshare.com/files/13267316"
ATTRIBUTION = ("VENAT venous atlas, Huck et al. 2019 (Brain Struct Funct 224:2467; figshare 10.6084/m9.figshare.7205960), "
               "CC BY 4.0")


def build_veins(path, affine_tpl_to_his, web_from_t1, cortex, cnorm, log=print):
    import nibabel as nib
    from scipy import ndimage
    from skimage import measure
    from bp3d_parts import decimate, press_to_surface
    img = nib.load(path)
    pv = img.get_fdata().astype(np.float32)
    m = pv > TH
    lab, n = ndimage.label(m)
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    keep = np.isin(lab, np.nonzero(sizes >= MIN_VOX)[0])
    log(f"veins: {int(m.sum())} voxels above {TH}, {n} pieces, {int((sizes >= MIN_VOX).sum())} kept ({int(keep.sum())} voxels)")
    sm = ndimage.gaussian_filter(np.where(keep, pv, 0.0), 0.7)
    verts, faces, _, _ = measure.marching_cubes(sm, TH * 0.95)
    v = nib.affines.apply_affine(img.affine, verts)                                  # MNI mm
    v = nib.affines.apply_affine(np.linalg.inv(affine_tpl_to_his), v)               # his T1 world
    v = nib.affines.apply_affine(web_from_t1, v)                                      # the page frame
    v, f = decimate(v, faces.astype(int), FACES)
    v, pressed = press_to_surface(v, cortex, cnorm, inside_mm=5.0, out_mm=0.5)
    log(f"veins: {len(v)} verts, {len(f)} faces, {pressed} pressed onto his surface")
    return v, f, {"threshold": TH, "min_voxels": MIN_VOX, "pressed": pressed, "attribution": ATTRIBUTION, "licence": "CC BY 4.0",
                  "source_url": URL, "note": "population atlas (20 adults), iso-surface of the mean vein partial volume, "
                  "affinely fitted to his T1 through the template registration; bridging veins below the threshold are not drawn"}
