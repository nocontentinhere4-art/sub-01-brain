"""Build the anatomy assets for /brain (web/anatomy/, issue #99 G9): what is HIS, what is an atlas, and in which frame.

Frames. The page draws in the "web frame" = the 2015 DWI world frame minus `web/fibres.json` offset (the fibres,
`cortex.bin` and brain.json's `q` are all in it). His 2022 T1 (out/t1_brain_1mm.nii.gz, skull-stripped, no face) sits in
its own world frame; `out/t1_to_dwi.npy` is dipy's static(DWI)->moving(T1) affine, so T1 world -> web is
`inv(t1_to_dwi) @ p - offset` (as build_cortex.py does).

Stages (all cached in --work; rerun one with --only):
  register : ICBM 152 2009c nonlinear asymmetric brain T1 (TemplateFlow; the MNI licence) -> his T1, affine + SyN (dipy),
             then the template's FreeSurfer-style segmentation (desc-carpet dseg: 5 brainstem, 255 cerebellum, 1/2 cerebral
             white matter, 3/4 lateral ventricles) warped into his T1 frame -> work/labels_anat_t1.nii.gz. Only HIS voxels
             are used afterwards: the labels just say which of his voxels are cerebellum / brainstem.
  meshes   : his cerebellum and his brainstem as separate surfaces (marching cubes on his own tissue inside each label,
             light simplification: the cerebellar folia are his, at the T1's 1 mm), and a per-vertex label for cortex.bin
             (cerebrum / cerebellum / brainstem) -> web/anatomy/cerebellum.bin, brainstem.bin, cortex_part.bin.
  volume   : his T1 as a slab atlas PNG (2 mm voxels, one 8-bit grey slice per tile; the cut plane samples it as a 3D
             texture) + the tissue intensity landmarks (CSF / grey / white peaks) -> web/anatomy/t1_atlas.png, anatomy.json.
  veins    : the VENAT venous atlas (Huck 2019, CC BY 4.0): dural sinuses and large veins, affinely fitted through the
             template registration, appended to parts.bin (analysis/venat_veins.py).
  bp3d     : BodyParts3D (DBCLS, CC BY 4.0): cerebral arteries (circle of Willis, ICA, MCA, ACA, PCA, basilar, vertebral),
             dural sinuses / veins, cranial nerves I-XII, optic chiasm, spinal cord, fitted to HIS brain with one similarity
             transform (BodyParts3D cerebrum -> his cortex.bin, bounding-box + ICP), decimated to polylines / low-poly tubes
             -> web/anatomy/parts.json (+ a provenance table).

Honesty: every file in web/anatomy/ carries "source": "his MRI" or "atlas (BodyParts3D)" in anatomy.json; the page's caption
repeats it. Nothing in the atlas is presented as his.
"""
import argparse
import json
import sys
import time
import zipfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "anatomy"
TPL = "https://templateflow.s3.amazonaws.com/tpl-MNI152NLin2009cAsym/"
TPL_FILES = {"t1": "tpl-MNI152NLin2009cAsym_res-01_desc-brain_T1w.nii.gz",
             "mask": "tpl-MNI152NLin2009cAsym_res-01_desc-brain_mask.nii.gz",
             "dseg": "tpl-MNI152NLin2009cAsym_res-01_desc-carpet_dseg.nii.gz",
             "license": "LICENSE"}
BP3D_URL = "https://dbarchive.biosciencedbc.jp/data/bodyparts3d/LATEST/"
BP3D_FILES = ["isa_BP3D_4.0_obj_99.zip", "isa_element_parts.txt", "isa_parts_list_e.txt",
              "partof_element_parts.txt", "partof_parts_list_e.txt"]   # the part-of tree names the whole brain, hemispheres, cord
LAB = {"brainstem": 5, "cerebellum": 255, "wm_l": 1, "wm_r": 2, "lv_l": 3, "lv_r": 4}
PART = {"cerebrum": 1, "cerebellum": 2, "brainstem": 3}       # cortex_part.bin values (uint8 a vertex)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def fetch(url, dst):
    import urllib.request
    dst = Path(dst)
    if dst.exists() and dst.stat().st_size > 0:
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    log("fetch", url)
    urllib.request.urlretrieve(url, dst)
    return dst


def web_from_t1():
    """4x4: his T1 world mm -> the page's frame."""
    t2d = np.load(ROOT / "out" / "t1_to_dwi.npy")
    off = np.array(json.load(open(ROOT / "web" / "fibres.json"))["offset"])
    M = np.linalg.inv(t2d)
    M[:3, 3] -= off
    return M


# ---------------------------------------------------------------- register
def stage_register(work):
    import nibabel as nib
    from dipy.align import affine_registration, syn_registration
    out = work / "labels_anat_t1.nii.gz"
    if out.exists():
        log("register: cached", out)
        return out
    tpl = {k: fetch(TPL + f, work / "tpl" / f) for k, f in TPL_FILES.items()}
    his = nib.load(ROOT / "out" / "t1_brain_1mm.nii.gz")
    mov = nib.load(tpl["t1"])
    T, S = his.get_fdata().astype(np.float64), mov.get_fdata().astype(np.float64)
    T /= np.percentile(T[T > 0], 99.5)
    S /= np.percentile(S[S > 0], 99.5)
    log("register: affine (template brain -> his brain)")
    _, aff = affine_registration(S, T, moving_affine=mov.affine, static_affine=his.affine, nbins=32,
                                 pipeline=["center_of_mass", "translation", "rigid", "affine"],
                                 level_iters=[10000, 1000, 100])
    log("register: SyN")
    _, mapping = syn_registration(S, T, moving_affine=mov.affine, static_affine=his.affine, prealign=aff,
                                  level_iters=[20, 20, 10])
    dseg = nib.load(tpl["dseg"]).get_fdata()
    lab = mapping.transform(dseg, interpolation="nearest").astype(np.int16)
    mask = nib.load(ROOT / "out" / "brainmask_t1.nii.gz").get_fdata() > 0
    lab[~mask] = 0
    nib.save(nib.Nifti1Image(lab, his.affine), out)
    np.save(work / "tpl_affine.npy", aff)
    for k in LAB:
        log(f"  {k}: {int((lab == LAB[k]).sum())} voxels in his brain")
    return out


# ---------------------------------------------------------------- meshes
def his_tissue(work):
    """His grey+white matter (the same 3-class split build_cortex.py used), as a boolean volume in the T1 grid."""
    import nibabel as nib
    from dipy.segment.tissue import TissueClassifierHMRF
    from scipy import ndimage
    cache = work / "tissue_t1.npy"
    if cache.exists():
        return np.load(cache)
    img = nib.load(ROOT / "out" / "t1_brain_1mm.nii.gz")
    t1 = img.get_fdata()
    mask = nib.load(ROOT / "out" / "brainmask_t1.nii.gz").get_fdata() > 0
    x = np.where(mask, t1, 0)
    x = x / np.percentile(x[mask], 99.5)
    _, seg, _ = TissueClassifierHMRF().classify(np.clip(x, 0, 1.2), nclasses=3, beta=0.1, max_iter=10)
    brain = mask & (seg >= 2)
    brain = ndimage.binary_closing(brain, iterations=1)
    np.save(cache, brain)
    return brain


def mesh_of(vol, affine, reduction, smooth=0.8):
    import nibabel as nib
    from scipy import ndimage
    from skimage import measure
    import fast_simplification
    lab, n = ndimage.label(vol)
    if n > 1:
        vol = lab == (np.bincount(lab.ravel())[1:].argmax() + 1)
    vol = ndimage.binary_fill_holes(vol)
    sm = ndimage.gaussian_filter(vol.astype(np.float32), smooth)
    verts, faces, _, _ = measure.marching_cubes(sm, 0.5)
    verts = nib.affines.apply_affine(affine, verts)
    v2, f2 = fast_simplification.simplify(verts.astype(np.float32), faces.astype(np.int64), target_reduction=reduction)
    return v2.astype(np.float64), f2.astype(np.int64)


def stage_meshes(work, labels_path):
    import nibabel as nib
    from scipy import ndimage
    from skimage.filters import threshold_otsu
    WEB.mkdir(parents=True, exist_ok=True)
    img = nib.load(labels_path)
    lab = img.get_fdata().astype(np.int16)
    t1 = nib.load(ROOT / "out" / "t1_brain_1mm.nii.gz").get_fdata()
    M = web_from_t1()
    info = {}
    for name, red in (("cerebellum", 0.55), ("brainstem", 0.7)):
        # his tissue inside the warped label: an Otsu split of HIS intensities there (the whole-brain 3-class split of
        # build_cortex.py calls most of the darker cerebellum and brainstem "CSF": the T1 is dimmer at the bottom of the
        # head), so the fissures between his folia (dark CSF) carve the surface and the tissue is his
        sel = ndimage.binary_dilation(lab == LAB[name], iterations=2)
        vals = t1[sel]
        thr = threshold_otsu(vals[vals > 0])
        vol = sel & (t1 > thr)
        vol = ndimage.binary_opening(vol, iterations=1)
        v, f = mesh_of(vol, img.affine, red, smooth=0.6 if name == "cerebellum" else 0.9)
        vw = nib.affines.apply_affine(M, v)
        (vw.astype(np.float32)).tofile(WEB / f"{name}.bin")
        idx_type = "uint16" if len(v) <= 65535 else "uint32"
        f.astype(np.uint16 if idx_type == "uint16" else np.uint32).tofile(WEB / f"{name}_idx.bin")
        info[name] = {"verts": int(len(v)), "faces": int(len(f)), "idx_type": idx_type, "source": "his MRI", "otsu": round(float(thr), 1),
                      "voxels": int(vol.sum()),
                      "note": f"his own tissue (T1 above an Otsu threshold of his intensities there) inside the warped template "
                              f"label '{name}', marching cubes at 1 mm, {int(red * 100)} % simplified"}
        log(f"meshes: {name} {len(v)} verts {len(f)} faces -> {WEB / (name + '.bin')}")
    # cortex.bin's vertices: which part each one belongs to (nearest labelled voxel, in the T1 grid)
    cv = np.fromfile(ROOT / "web" / "cortex.bin", dtype=np.float32).reshape(-1, 3).astype(np.float64)
    inv = np.linalg.inv(M)
    ijk = np.rint(nib.affines.apply_affine(inv, cv) @ np.linalg.inv(img.affine[:3, :3]).T
                  + np.linalg.inv(img.affine)[:3, 3]).astype(int)
    ijk = np.clip(ijk, 0, np.array(lab.shape) - 1)
    part = np.full(len(cv), PART["cerebrum"], np.uint8)
    # a vertex is cerebellum / brainstem when that label dominates a 5 mm cube around it
    for name in ("cerebellum", "brainstem"):
        sel = (lab == LAB[name]).astype(np.float32)
        dens = ndimage.uniform_filter(sel, size=5)
        part[dens[ijk[:, 0], ijk[:, 1], ijk[:, 2]] > 0.5] = PART[name]
    part.tofile(WEB / "cortex_part.bin")
    info["cortex_part"] = {k: int((part == v).sum()) for k, v in PART.items()}
    log("meshes: cortex parts", info["cortex_part"])
    return info


# ---------------------------------------------------------------- volume
def stage_volume(work, labels_path, step=2.0):
    """His T1 at `step` mm as a tile atlas PNG (8-bit grey), plus the matrix web frame -> atlas voxel and the tissue peaks."""
    import nibabel as nib
    from PIL import Image
    from scipy import ndimage
    img = nib.load(ROOT / "out" / "t1_brain_1mm.nii.gz")
    t1 = img.get_fdata()
    lab = nib.load(labels_path).get_fdata().astype(np.int16)
    tissue = his_tissue(work)
    mask = nib.load(ROOT / "out" / "brainmask_t1.nii.gz").get_fdata() > 0
    hi = np.percentile(t1[tissue], 99.5)
    # tissue landmarks from HIS own histogram (every voxel in the brain mask): the two tallest peaks are grey and white
    # matter (grey the darker on T1), the lowest peak is CSF
    vals = t1[mask & (t1 > 0)] / hi
    hist, edges = np.histogram(vals, bins=120, range=(0, 1.2))
    centres = (edges[:-1] + edges[1:]) / 2
    sm = ndimage.gaussian_filter1d(hist.astype(float), 2)
    peaks = sorted([(sm[i], centres[i]) for i in range(1, len(sm) - 1) if sm[i] > sm[i - 1] and sm[i] > sm[i + 1]], reverse=True)
    top = sorted(c for _, c in peaks[:2])
    gm, wm = (top[0], top[1]) if len(top) == 2 else (np.percentile(vals, 30), np.percentile(vals, 70))
    low = [c for _, c in peaks if c < gm * 0.6]
    csf = float(min(low)) if low else float(gm * 0.3)
    # resample to `step` mm (box filter then stride), masked to the brain
    z = 1.0 / step
    vol = ndimage.zoom(np.where(mask, t1, 0) / hi, z, order=1)
    mk = ndimage.zoom(mask.astype(np.float32), z, order=1) > 0.5
    vol = np.clip(vol, 0, 1.2) / 1.2
    vol[~mk] = 0
    # outside the brain the intensity is filled with the nearest inside value (no dark fringe where the cut's edge is
    # interpolated), and the edge itself is a soft mask in the PNG's alpha: the shader cuts at its half-way contour
    near = ndimage.distance_transform_edt(~mk, return_distances=False, return_indices=True)
    vol = vol[tuple(near)]
    vol8 = np.clip(np.rint(vol * 255), 0, 255).astype(np.uint8)
    vol8[mk & (vol8 == 0)] = 1
    soft = ndimage.gaussian_filter(mk.astype(np.float32), 0.8)
    mask8 = np.clip(np.rint(soft * 255), 0, 255).astype(np.uint8)
    nx, ny, nz = vol8.shape
    cols = int(np.ceil(np.sqrt(nz)))
    rows = int(np.ceil(nz / cols))
    atlas = np.zeros((rows * ny, cols * nx, 2), np.uint8)
    for k in range(nz):
        r, c = divmod(k, cols)
        atlas[r * ny:(r + 1) * ny, c * nx:(c + 1) * nx, 0] = vol8[:, :, k].T   # tile (u = x, v = y): his T1
        atlas[r * ny:(r + 1) * ny, c * nx:(c + 1) * nx, 1] = mask8[:, :, k].T  # the soft brain mask
    WEB.mkdir(parents=True, exist_ok=True)
    Image.fromarray(atlas, mode="LA").save(WEB / "t1_atlas.png", optimize=True)
    # voxel (i,j,k) of the resampled grid -> T1 world: the zoom keeps the corner alignment of scipy.ndimage.zoom
    # (output index i maps to input index i * (in-1)/(out-1))
    scale = np.array([(s - 1) / (o - 1) for s, o in zip(t1.shape, vol8.shape)])
    A = img.affine @ np.diag([*scale, 1.0])
    web_to_vox = np.linalg.inv(web_from_t1() @ A)
    size = (WEB / "t1_atlas.png").stat().st_size
    log(f"volume: {vol8.shape} at {step} mm, atlas {atlas.shape[1]}x{atlas.shape[0]} px, {size / 1024:.0f} KB; "
        f"csf {csf:.2f} grey {gm:.2f} white {wm:.2f} (of the 99.5th percentile)")
    return {"shape": [int(nx), int(ny), int(nz)], "cols": cols, "rows": rows, "step_mm": step,
            "web_to_vox": [round(float(x), 6) for x in web_to_vox.ravel()],
            "tissue": {"csf": round(csf / 1.2, 4), "grey": round(float(gm) / 1.2, 4), "white": round(float(wm) / 1.2, 4)},
            "bytes": size, "source": "his MRI",
            "note": "his 2022 T1 (skull-stripped, no face) resampled to 2 mm, 8-bit, one tile a slice (grey) with a soft brain "
                    "mask in the alpha; intensities as fractions of the 99.5th percentile over 1.2, filled outward past the mask"}


# ---------------------------------------------------------------- BodyParts3D
def stage_bp3d(work):
    from bp3d_parts import build_parts   # noqa: F401  (analysis/bp3d_parts.py)
    files = {f: fetch(BP3D_URL + f, work / "bp3d" / f) for f in BP3D_FILES}
    return build_parts(files, WEB, ROOT, log)


# ---------------------------------------------------------------- veins (VENAT)
def stage_veins(work, meta):
    """Appends the VENAT sinuses / veins to parts.bin as one more part (kind "vein"). Needs stages register and bp3d."""
    import nibabel as nib
    from bp3d_parts import vertex_normals, Q
    from venat_veins import build_veins, URL
    path = fetch(URL, work / "venat" / "VENAT_PartialVolume.nii.gz")
    aff = np.load(work / "tpl_affine.npy")
    cortex = np.fromfile(ROOT / "web" / "cortex.bin", dtype=np.float32).reshape(-1, 3).astype(float)
    cidx = np.fromfile(ROOT / "web" / "cortex_idx.bin", dtype=np.uint32).reshape(-1, 3).astype(int)
    v, f, info = build_veins(path, aff, web_from_t1(), cortex, vertex_normals(cortex, cidx), log)
    parts = meta["parts"]
    parts["parts"] = [r for r in parts["parts"] if r["kind"] != "vein"]
    blob = bytearray((WEB / parts["file"]).read_bytes())
    if parts["parts"]:
        last = parts["parts"][-1]
        end = last["idx"] + last["n_idx"] * (2 if last["idx_type"] == "uint16" else 4)
        del blob[end:]
    while len(blob) % 4:
        blob += b"\0"
    row = {"fma": "", "kind": "vein", "label": "dural sinuses and large veins", "bp3d_name": "", "elements": [], "faces_in": int(len(f)),
           "faces": int(len(f)), "verts": int(len(v)), "pressed": info["pressed"], "pos": len(blob), "source": "atlas (VENAT)"}
    blob += np.rint(v / Q).astype(np.int16).tobytes()
    while len(blob) % 4:
        blob += b"\0"
    row["idx"] = len(blob)
    row["idx_type"] = "uint16" if len(v) <= 65535 else "uint32"
    blob += (f.astype(np.uint16) if row["idx_type"] == "uint16" else f.astype(np.uint32)).tobytes()
    while len(blob) % 4:
        blob += b"\0"
    row["n_idx"] = int(f.size)
    parts["parts"].append(row)
    parts["venat"] = info
    (WEB / parts["file"]).write_bytes(bytes(blob))
    log(f"veins: parts.bin now {len(blob) / 1024:.0f} KB")
    return parts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=str(ROOT / "out" / "anatomy_work"))
    ap.add_argument("--only", nargs="*", default=None, help="stages to run (default: all)")
    a = ap.parse_args()
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    stages = a.only or ["register", "meshes", "volume", "bp3d", "veins"]
    meta_path = WEB / "anatomy.json"
    meta = json.load(open(meta_path)) if meta_path.exists() else {"v": 1}
    labels = work / "labels_anat_t1.nii.gz"
    if "register" in stages:
        labels = stage_register(work)
    if "meshes" in stages:
        meta["meshes"] = stage_meshes(work, labels)
    if "volume" in stages:
        meta["volume"] = stage_volume(work, labels)
    if "bp3d" in stages:
        meta["parts"] = stage_bp3d(work)
    if "veins" in stages:
        meta["parts"] = stage_veins(work, meta)
    meta["frame"] = "web: the 2015 DWI world frame minus web/fibres.json offset (same as cortex.bin and the fibres)"
    meta["template"] = {"name": "ICBM 152 2009c nonlinear asymmetric (TemplateFlow tpl-MNI152NLin2009cAsym)",
                        "use": "only to find which of HIS voxels are cerebellum / brainstem (its segmentation warped onto his T1)",
                        "licence": "Copyright (C) 1993-2004 Louis Collins, MNI, McGill; use, copy, modify and distribute for any purpose without fee, keeping the notice"}
    WEB.mkdir(parents=True, exist_ok=True)
    json.dump(meta, open(meta_path, "w"), indent=1)
    log("wrote", meta_path)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
