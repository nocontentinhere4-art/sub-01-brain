"""BodyParts3D parts fitted to HIS brain (analysis/build_anatomy.py, stage `bp3d`).

BodyParts3D (DBCLS; https://dbarchive.biosciencedbc.jp/en/bodyparts3d/) is a polygon atlas of one adult body. The NBDC
archive licenses the database under CC BY 4.0 (its licence page, last updated 2025-02-27; the 2011 OBJ headers still
carry the earlier CC BY-SA 2.1 Japan notice). Required attribution: "BodyParts3D, © The Database Center for Life
Science licensed under CC Attribution 4.0 International".

What is taken (and what is not):
  - the cerebral arteries that form the circle of Willis and the main trunks (internal carotid, anterior / middle /
    posterior cerebral, anterior and posterior communicating, basilar, vertebral, cerebellar arteries);
  - the cranial nerves BodyParts3D has: II (optic nerve, chiasm, tract) and IV (trochlear), and the ophthalmic division
    of V; the pituitary gland; the spinal cord stub. BodyParts3D 4.0 has no meshes for I, III, V (trunk), VI-XII and
    no dural sinuses or cerebral veins: those are NOT drawn (the caption says so) rather than invented.
  - NOT the cerebrum, cerebellum or brainstem: those come from his own MRI. BodyParts3D's brain is used only to
    compute the one similarity transform (scale, rotation, translation) that fits the atlas to his brain.

Frame: BodyParts3D is in body millimetres, x to the body's left, y to the back, z up (the brain sits at z ≈ 1460-1630).
The page's frame has x right, y anterior, z superior (MNI-like), so the start is a 180° turn about z, then a
bounding-box scale and a trimmed ICP (Umeyama similarity) of the atlas brain onto his cortex.bin (which includes his
cerebellum and upper brainstem). The residual is written to anatomy.json so the caption can quote it.

Output: web/anatomy/parts.bin (int16 positions in 0.01 mm + uint16/uint32 indices, one block a part) and the table
returned to build_anatomy.py for anatomy.json.
"""
import collections
import io
import json
import zipfile

import numpy as np
from scipy.spatial import cKDTree

# concept -> (kind, label shown, side handling). Names are BodyParts3D's own (isa_parts_list_e.txt).
PARTS = [
    ("FMA3947", "artery", "internal carotid artery"),
    ("FMA50028", "artery", "anterior cerebral artery"),
    ("FMA50169", "artery", "anterior communicating artery"),
    ("FMA50080", "artery", "middle cerebral artery"),
    ("FMA50589", "artery", "posterior cerebral artery"),
    ("FMA50084", "artery", "posterior communicating artery"),
    ("FMA50542", "artery", "basilar artery"),
    ("FMA3956", "artery", "vertebral artery"),
    ("FMA50573", "artery", "superior cerebellar artery"),
    ("FMA50544", "artery", "anterior inferior cerebellar artery"),
    ("FMA50518", "artery", "posterior inferior cerebellar artery"),
    ("FMA50863", "nerve", "optic nerve (II)"),
    ("FMA62045", "nerve", "optic chiasm"),
    ("FMA62046", "nerve", "optic tract"),
    ("FMA52571", "nerve", "oculomotor nerve (III, its orbital branches)"),
    ("FMA50865", "nerve", "trochlear nerve (IV)"),
    ("FMA52621", "nerve", "ophthalmic nerve (V1)"),
    ("FMA13889", "gland", "pituitary gland"),
    ("FMA7647", "cord", "spinal cord (stub)"),
]
FIT = ["FMA61819", "FMA67292", "FMA67944", "FMA79876"]      # left + right cerebral hemisphere, cerebellum, brainstem
MISSING = ["olfactory (I)", "oculomotor trunk (III)", "trigeminal trunk (V)", "abducens (VI)", "facial (VII)",
           "vestibulocochlear (VIII)", "glossopharyngeal (IX)", "vagus (X)", "accessory (XI)", "hypoglossal (XII)",
           "dural venous sinuses", "cerebral and bridging veins"]
FACE_BUDGET = {"artery": 26000, "nerve": 9000, "gland": 600, "cord": 800}   # triangles over all parts of a kind
ATTRIBUTION = "BodyParts3D, © The Database Center for Life Science licensed under CC Attribution 4.0 International"
Q = 0.01                                                                     # int16 position unit, mm
NECK_MM = 30.0                                                               # arteries kept this far below his brain


def elements(files):
    """concept id -> ordered element file ids (both trees), and concept names."""
    el, name = collections.defaultdict(list), {}
    for key in ("isa_element_parts.txt", "partof_element_parts.txt"):   # the is-a tree lacks the hemispheres, brainstem and cord
        for ln in open(files[key], encoding="utf-8", errors="replace"):
            p = ln.rstrip("\r\n").split("\t")
            if len(p) >= 3 and p[0].startswith("FMA") and p[2] not in el[p[0]]:
                el[p[0]].append(p[2])
                name[p[0]] = p[1]
    return el, name


def load_obj(zf, fj):
    v, f = [], []
    try:
        fh = zf.open(f"isa_BP3D_4.0_obj_99/{fj}.obj")
    except KeyError:
        return np.zeros((0, 3)), np.zeros((0, 3), int)
    for ln in io.TextIOWrapper(fh, encoding="utf-8", errors="replace"):
        if ln.startswith("v "):
            v.append([float(x) for x in ln.split()[1:4]])
        elif ln.startswith("f "):
            idx = [int(x.split("/")[0]) - 1 for x in ln.split()[1:]]
            for k in range(1, len(idx) - 1):                     # fan: BodyParts3D faces are triangles anyway
                f.append([idx[0], idx[k], idx[k + 1]])
    return np.array(v, float), np.array(f, int)


def merge(parts):
    vs, fs, off = [], [], 0
    for v, f in parts:
        if len(v) == 0:
            continue
        vs.append(v)
        fs.append(f + off)
        off += len(v)
    if not vs:
        return np.zeros((0, 3)), np.zeros((0, 3), int)
    return np.concatenate(vs), np.concatenate(fs)


def bp3d_to_web0():
    """The 180° turn about z: BodyParts3D x left / y back -> page x right / y front."""
    return np.diag([-1.0, -1.0, 1.0])


def umeyama(src, dst):
    """Similarity (s, R, t) with dst ≈ s R src + t (Umeyama 1991)."""
    mu_s, mu_d = src.mean(0), dst.mean(0)
    xs, xd = src - mu_s, dst - mu_d
    cov = xd.T @ xs / len(src)
    U, D, Vt = np.linalg.svd(cov)
    S = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        S[2, 2] = -1
    R = U @ S @ Vt
    var_s = (xs ** 2).sum() / len(src)
    s = (D * np.diag(S)).sum() / var_s
    t = mu_d - s * R @ mu_s
    return s, R, t


def fit_similarity(src, dst, iters=40, keep=0.8, log=print):
    """Trimmed ICP of src (atlas brain surface points) onto dst (his cortex vertices). Returns 4x4 and the RMS (mm)."""
    tree = cKDTree(dst)
    # start: axes turned, centred, scaled by the bounding box
    R0 = bp3d_to_web0()
    p = src @ R0.T
    s = np.ptp(dst, 0).mean() / np.ptp(p, 0).mean()
    p = (p - p.mean(0)) * s + dst.mean(0)
    M = np.eye(4)
    M[:3, :3] = s * R0
    M[:3, 3] = dst.mean(0) - s * (src @ R0.T).mean(0)
    rms = None
    for it in range(iters):
        d, j = tree.query(p, workers=-1)
        cut = np.quantile(d, keep)
        sel = d <= cut
        s_, R_, t_ = umeyama(p[sel], dst[j[sel]])
        p = p @ (s_ * R_).T + t_
        A = np.eye(4)
        A[:3, :3] = s_ * R_
        A[:3, 3] = t_
        M = A @ M
        rms = float(np.sqrt((d[sel] ** 2).mean()))
        if it % 10 == 9:
            log(f"  icp {it + 1}: rms {rms:.2f} mm (best {int(keep * 100)} %), median {np.median(d):.2f}")
    d, _ = tree.query(p, workers=-1)
    return M, rms, float(np.median(d))


def decimate(v, f, target_faces):
    import fast_simplification
    if len(f) <= target_faces or len(f) < 50:
        return v, f
    red = 1.0 - target_faces / len(f)
    v2, f2 = fast_simplification.simplify(v.astype(np.float32), f.astype(np.int64), target_reduction=red)
    return v2.astype(float), f2.astype(int)


def press_to_surface(v, cortex, normals, inside_mm=7.0, out_mm=0.6):
    """Vessel vertices just under his cortex surface are pressed onto it (the atlas was another brain: its cortical
    branches would otherwise vanish inside his gyri). Deeper vertices (the circle of Willis, the insular segments) stay."""
    tree = cKDTree(cortex)
    d, j = tree.query(v, workers=-1)
    n = normals[j]
    signed = np.einsum("ij,ij->i", v - cortex[j], n)            # > 0 outside his surface
    move = (signed < out_mm) & (signed > -inside_mm)
    v = v.copy()
    v[move] = cortex[j[move]] + n[move] * out_mm
    return v, int(move.sum())


def trim_below(v, f, zmin):
    """Drop the faces entirely below zmin (the neck): a stub of the arteries below the brain is kept."""
    keep = ~np.all(v[f][:, :, 2] < zmin, axis=1)
    f = f[keep]
    used = np.unique(f)
    remap = -np.ones(len(v), int)
    remap[used] = np.arange(len(used))
    return v[used], remap[f]


def vertex_normals(v, f):
    fn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    n = np.zeros_like(v)
    for k in range(3):
        np.add.at(n, f[:, k], fn)
    # outward: away from the hemisphere's centre (a brain is convex enough for this)
    ctr = np.where(v[:, :1] < 0, v[v[:, 0] < 0].mean(0), v[v[:, 0] >= 0].mean(0))
    flip = np.einsum("ij,ij->i", n, v - ctr) < 0
    if flip.mean() > 0.5:
        n = -n
    return n / np.maximum(1e-9, np.linalg.norm(n, axis=1))[:, None]


def build_parts(files, web_dir, root, log=print):
    el, name = elements(files)
    zf = zipfile.ZipFile(files["isa_BP3D_4.0_obj_99.zip"])
    cortex = np.fromfile(root / "web" / "cortex.bin", dtype=np.float32).reshape(-1, 3).astype(float)
    cidx = np.fromfile(root / "web" / "cortex_idx.bin", dtype=np.uint32).reshape(-1, 3).astype(int)
    cnorm = vertex_normals(cortex, cidx)
    # 1. the fit: atlas brain surface points -> his cortex
    fit_v = merge([load_obj(zf, fj) for c in FIT for fj in el[c]])[0]
    rng = np.random.default_rng(0)
    src = fit_v[rng.choice(len(fit_v), min(30000, len(fit_v)), replace=False)]
    log(f"bp3d: fitting {len(src)} atlas brain points to his cortex ({len(cortex)} vertices)")
    M, rms, med = fit_similarity(src, cortex, log=log)
    scale = float(np.cbrt(abs(np.linalg.det(M[:3, :3]))))
    log(f"bp3d: similarity scale {scale:.3f}, rms {rms:.2f} mm, median {med:.2f} mm")

    def to_web(v):
        return v @ M[:3, :3].T + M[:3, 3]

    # 2. the parts
    table, blobs = [], []
    per_kind = collections.Counter()
    for c, kind, label in PARTS:
        v, f = merge([load_obj(zf, fj) for fj in el.get(c, [])])
        if len(f) == 0:
            log(f"bp3d: {label}: no mesh in the archive, skipped")
            continue
        per_kind[kind] += len(f)
        table.append({"fma": c, "kind": kind, "label": label, "bp3d_name": name.get(c, ""), "elements": el.get(c, []),
                      "faces_in": int(len(f)), "_v": v, "_f": f})
    for row in table:
        kind = row["kind"]
        share = row["faces_in"] / per_kind[kind]
        v, f = decimate(row["_v"], row["_f"], max(200, int(FACE_BUDGET[kind] * share)))
        v = to_web(v)
        pressed = 0
        if kind in ("artery", "cord"):
            v, f = trim_below(v, f, cortex[:, 2].min() - NECK_MM)   # the carotid and vertebral arteries run down the neck
        if kind == "artery":
            v, pressed = press_to_surface(v, cortex, cnorm)
        row.update(faces=int(len(f)), verts=int(len(v)), pressed=pressed)
        row["_v"], row["_f"] = v, f
    # 3. one binary: int16 positions (0.01 mm) + indices, 4-byte aligned blocks
    out = bytearray()
    for row in table:
        v, f = row.pop("_v"), row.pop("_f")
        q = np.rint(v / Q).astype(np.int16)
        assert np.all(np.abs(v / Q) < 32767), row["label"]
        row["pos"] = len(out)
        out += q.tobytes()
        while len(out) % 4:
            out += b"\0"
        row["idx"] = len(out)
        if len(v) <= 65535:
            row["idx_type"] = "uint16"
            out += f.astype(np.uint16).tobytes()
        else:
            row["idx_type"] = "uint32"
            out += f.astype(np.uint32).tobytes()
        while len(out) % 4:
            out += b"\0"
        row["n_idx"] = int(f.size)
        row["source"] = "atlas (BodyParts3D)"
    web_dir.mkdir(parents=True, exist_ok=True)
    (web_dir / "parts.bin").write_bytes(bytes(out))
    log(f"bp3d: {len(table)} parts, {sum(r['faces'] for r in table)} triangles, parts.bin {len(out) / 1024:.0f} KB")
    return {"file": "parts.bin", "unit_mm": Q, "parts": table, "fit": {"rms_mm": round(rms, 2), "median_mm": round(med, 2),
            "scale": round(scale, 4), "matrix": [round(float(x), 6) for x in M.ravel()], "trim": 0.8,
            "fit_set": [name.get(c, c) for c in FIT], "note": "one similarity transform (scale, rotation, translation) of the "
            "atlas brain onto his cortex surface; arteries just under his surface pressed onto it"},
            "not_in_atlas": MISSING, "attribution": ATTRIBUTION, "licence": "CC BY 4.0 (NBDC archive licence page, 2025-02-27; "
            "the 2011 OBJ headers say CC BY-SA 2.1 JP); the derived parts.bin is offered under CC BY-SA 4.0, which satisfies both",
            "source_url": "https://dbarchive.biosciencedbc.jp/en/bodyparts3d/", "version": "BP3D 4.0 (isa_BP3D_4.0_obj_99)"}
