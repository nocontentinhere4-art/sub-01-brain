"""Repair the owner's Tripo office chair (docs/design/chair-tripo/chair_owner_raw.fbx, converted to PLY by
room_build/fbx2ply.mjs): the letter-shaped holes and dents Tripo copied from the source photo's label are covered over
with new smooth surface, area by area, leaving the rest of the mesh as it is.

    python room_build/chair_owner_repair.py raw.ply repaired.ply [--report out.json] [--only area]

The letters are true holes with inverted, non-manifold walls, so cutting them out and capping the openings does not hold.
Instead, per area (REGIONS: a box in the model's own frame, the chair facing +z, and a depth window that holds only that
surface, so the frame and the spine behind it are never touched):
  1. the cushion's envelope is sampled (the outermost point facing that side in each 6 mm cell) and a smooth surface is
     fitted to it (a thin-plate spline, refitted 8 times without the cells that sit low: the letters' pits),
  2. the faces that stick out past that surface (the letters' raised fringes) are deleted, only where the cover will
     lie over them,
  3. a cover is laid: a 5 mm grid 1.2 mm proud of the fitted surface, clipped to the area's outline (the letters' holes
     filled), whose last 2.2 cm follow the original surface and tuck 0.8 mm under it, so it blends in with no step,
  4. its texture coordinates come from the faces under it (a fitted map from x, y to u, v), for the textures to come.
The model keeps its per-corner normals and UVs (texture seams) outside the repaired areas. The run is deterministic."""
import argparse
import json
import sys

import numpy as np
from scipy.spatial import cKDTree

# per area: x0, x1, y0, y1 (a rectangle round the letters), zlo, zhi (the depth window holding that surface and not the
# frame or the spine behind it), side (+1: the surface faces +z, the front; -1: it faces -z, the back). Model units (the
# chair is 0.978 tall here, facing +z; build_chair_owner.mjs scales and turns it); near (optional): how far the mesh may
# lie from the fitted surface and still count as this cushion's (6 mm; more where the surface curves away, the headrest's
# recess)
REGIONS = {
    "backrest_front": dict(box=(-0.163, 0.172, 0.598, 0.814), z=(-0.178, -0.110), side=1),
    "backrest_back": dict(box=(-0.174, 0.172, 0.598, 0.834), z=(-0.190, -0.132), side=-1),
    "lumbar_front": dict(box=(-0.140, 0.162, 0.458, 0.592), z=(-0.134, -0.082), side=1),
    "headrest_front": dict(box=(-0.090, 0.130, 0.872, 0.960), z=(-0.175, -0.130), side=1),
    "headrest_back": dict(box=(-0.091, 0.095, 0.879, 0.954), z=(-0.188, -0.140), side=-1, near=0.012),
}


def load_ply(path):
    with open(path, "rb") as f:
        hdr = b""
        while not hdr.endswith(b"end_header\n"):
            hdr += f.read(1)
        h = hdr.decode().split("\n")
        nv = int(next(l for l in h if l.startswith("element vertex")).split()[-1])
        nf = int(next(l for l in h if l.startswith("element face")).split()[-1])
        V = np.frombuffer(f.read(nv * 32), dtype="<f4").reshape(nv, 8).astype(np.float64)
        Fr = np.frombuffer(f.read(nf * 13), dtype=np.uint8).reshape(nf, 13)
    F = np.frombuffer(Fr[:, 1:].tobytes(), dtype="<i4").reshape(nf, 3)
    return V[F]                                                   # (faces, 3 corners, 8: xyz, normal, uv)


def save_ply(path, C):
    nf = len(C); V = C.reshape(-1, 8).astype("<f4")
    hdr = (f"ply\nformat binary_little_endian 1.0\nelement vertex {len(V)}\nproperty float x\nproperty float y\nproperty float z\n"
           f"property float nx\nproperty float ny\nproperty float nz\nproperty float s\nproperty float t\nelement face {nf}\n"
           "property list uchar int vertex_indices\nend_header\n")
    F = np.zeros((nf, 13), dtype=np.uint8); F[:, 0] = 3
    F[:, 1:] = np.frombuffer(np.arange(nf * 3, dtype="<i4").tobytes(), dtype=np.uint8).reshape(nf, 12)
    with open(path, "wb") as f:
        f.write(hdr.encode()); f.write(V.tobytes()); f.write(F.tobytes())


def poly_terms(x, y, deg=3):
    return np.stack([x ** i * y ** j for i in range(deg + 1) for j in range(deg + 1 - i)], axis=-1)


def fit(x, y, v, deg=3):
    A = poly_terms(x, y, deg); c, *_ = np.linalg.lstsq(A, v, rcond=None)
    return lambda X, Y: poly_terms(np.asarray(X), np.asarray(Y), deg) @ c


def surface_z(XY, tri, sd):
    """the depth of the surface of triangles `tri` (n, 3, 3) under each x-y point: the highest (sd +1) or lowest (-1)
    triangle containing it; NaN where none does"""
    out = np.full(len(XY), np.nan)
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    v0, v1 = b[:, :2] - a[:, :2], c[:, :2] - a[:, :2]; den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
    ok = np.abs(den) > 1e-14; a, b, c, v0, v1, den = a[ok], b[ok], c[ok], v0[ok], v1[ok], den[ok]
    lo = np.minimum(np.minimum(a[:, :2], b[:, :2]), c[:, :2]); hi = np.maximum(np.maximum(a[:, :2], b[:, :2]), c[:, :2])
    for k in range(0, len(XY), 256):
        P = XY[k:k + 256]
        inb = (P[:, None, 0] >= lo[None, :, 0]) & (P[:, None, 0] <= hi[None, :, 0]) & (P[:, None, 1] >= lo[None, :, 1]) & (P[:, None, 1] <= hi[None, :, 1])
        for i, j in zip(*np.nonzero(inb)):
            w = P[i] - a[j, :2]; u = (w[0] * v1[j, 1] - v1[j, 0] * w[1]) / den[j]; v = (v0[j, 0] * w[1] - w[0] * v0[j, 1]) / den[j]
            if u < -1e-9 or v < -1e-9 or u + v > 1 + 1e-9: continue
            z = a[j, 2] + u * (b[j, 2] - a[j, 2]) + v * (c[j, 2] - a[j, 2])
            cur = out[k + i]
            if np.isnan(cur) or (z - cur) * sd > 0: out[k + i] = z
    return out


def weld(C):
    """vertex ids per corner (positions welded to 0.01 mm), and the unique positions"""
    key = np.round(C[:, :, :3].reshape(-1, 3) * 1e5).astype(np.int64)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    pos = np.zeros((len(uniq), 3)); np.add.at(pos, inv, C[:, :, :3].reshape(-1, 3)); pos /= np.bincount(inv)[:, None]
    return inv.reshape(-1, 3), pos


def repair(C, name, R, report, step=0.005, lift=0.0012, tuck=0.0008, edge=0.022):
    """cover the area with a clean surface (see the module's docstring)"""
    from scipy.interpolate import RBFInterpolator
    x0, x1, y0, y1 = R["box"]; zlo, zhi = R["z"]; sd = R["side"]
    P = C[:, :, :3]; cen = P.mean(axis=1)
    fn = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]); fa = np.linalg.norm(fn, axis=1); nz = fn[:, 2] / np.maximum(fa, 1e-15)
    inwin = lambda Q: (Q[..., 2] > zlo) & (Q[..., 2] < zhi)
    inbox = lambda Q, m=0.0: (Q[..., 0] > x0 - m) & (Q[..., 0] < x1 + m) & (Q[..., 1] > y0 - m) & (Q[..., 1] < y1 + m)
    # the surface: the envelope (front: highest, back: lowest) per 6 mm cell of the faces facing its way; a thin plate
    # spline through it (the letters' holes leave cells empty; their fringes face the wrong way)
    own = inwin(cen) & inbox(cen, 0.03) & (nz * sd > 0.35)
    pts = cen[own]; cell = np.floor(pts[:, :2] / 0.006).astype(np.int64); key = cell[:, 0] * 1000003 + cell[:, 1]
    order = np.lexsort((-pts[:, 2] * sd, key)); ks = key[order]; env = pts[order][np.r_[True, ks[1:] != ks[:-1]]]
    for _ in range(8):                         # (cells sunk into a pit or a hole are not the surface: dropped, fitted again)
        f = RBFInterpolator(env[:, :2], env[:, 2], kernel="thin_plate_spline", smoothing=3e-4, neighbors=80)
        res = (env[:, 2] - f(env[:, :2])) * sd; ok = res > -0.0008
        if ok.all(): break
        env = env[ok]
    # 1. whatever pokes out past the new surface goes (the letters' raised fringes); the rest stays, under the cover
    d = (cen[:, 2] - f(cen[:, :2])) * sd
    poke = inbox(cen) & inwin(cen) & (d > lift * 0.35) & (d < 0.03)       # (decided below: only where the cover lies)
    gone = np.zeros(len(C), bool)
    # uv: x, y -> u, v fitted on this side's faces in the area (one texture island)
    usel = inbox(cen) & inwin(cen) & (nz * sd > 0.35) & ~gone
    corn = P[usel].reshape(-1, 3); uvs = C[usel][:, :, 6:8].reshape(-1, 2)
    um = (fit(corn[:, 0], corn[:, 1], uvs[:, 0], 2), fit(corn[:, 0], corn[:, 1], uvs[:, 1], 2))
    # 2. the cover: a grid over the rectangle with rounded corners, `lift` proud of the surface, its last `edge` sinking
    # `tuck` under it (no step where it ends)
    nx, ny = int(np.ceil((x1 - x0) / step)), int(np.ceil((y1 - y0) / step))
    gx, gy = np.meshgrid(np.linspace(x0, x1, nx + 1), np.linspace(y0, y1, ny + 1))
    r = 0.02; qx = np.maximum(np.abs(gx - (x0 + x1) / 2) - ((x1 - x0) / 2 - r), 0); qy = np.maximum(np.abs(gy - (y0 + y1) / 2) - ((y1 - y0) / 2 - r), 0)
    inside = np.hypot(qx, qy) < r                                    # (the rounded rectangle)
    dist = np.minimum.reduce([gx - x0, x1 - gx, gy - y0, y1 - gy]) - np.maximum(np.hypot(qx, qy) - 0, 0) * 0
    rim = np.clip(dist / edge, 0, 1); rim = rim * rim * (3 - 2 * rim)
    # along its edge band the cover follows the mesh's own surface (tucked `tuck` under it), inside it the fitted one
    # (`lift` proud); cells with no surface of this side under them (past the cushion's outline) are left out
    face_ok = inwin(cen) & inbox(cen, 0.01) & (nz * sd > 0.2) & ~gone
    XY = np.stack([gx.ravel(), gy.ravel()], 1)
    zs = surface_z(XY, P[face_ok], sd).reshape(gx.shape)
    zf = f(XY).reshape(gx.shape)
    from scipy.ndimage import binary_fill_holes, binary_dilation, binary_erosion, distance_transform_edt
    # the surface under each grid point: this cushion's (within 6 mm of the fit, or `near`: not its neighbour's, not a pit's floor)
    valid = ~np.isnan(zs) & (np.abs(np.nan_to_num(zs, nan=9) - zf) < R.get("near", 0.006))
    outline = binary_fill_holes(binary_erosion(binary_dilation(valid, iterations=2), iterations=2))   # (the letters' holes in)
    inside = inside & outline
    # the tuck: towards the rectangle's edge and towards the cushion's own outline alike
    rim = np.minimum(rim, np.clip(distance_transform_edt(outline) * step / edge, 0, 1) ** 2 * (3 - 2 * np.clip(distance_transform_edt(outline) * step / edge, 0, 1)))
    Z = np.where(valid, (1 - rim) * (np.nan_to_num(zs) - sd * tuck) + rim * (zf + sd * lift), zf + sd * (lift * rim - tuck * (1 - rim)))
    X = np.stack([gx, gy, Z], -1)
    new = []
    for j in range(ny):
        for i in range(nx):
            if not (inside[j, i] and inside[j, i + 1] and inside[j + 1, i] and inside[j + 1, i + 1]): continue
            for t3 in ((X[j, i], X[j, i + 1], X[j + 1, i + 1]), (X[j, i], X[j + 1, i + 1], X[j + 1, i])):
                q = np.array(t3)
                if sd < 0: q = q[[0, 2, 1]]
                n = np.cross(q[1] - q[0], q[2] - q[0]); n /= (np.linalg.norm(n) or 1)
                if n[2] * sd < 0.2: continue                  # (folded where the tuck meets a step: hidden there anyway)
                uv = np.column_stack([um[0](q[:, 0], q[:, 1]), um[1](q[:, 0], q[:, 1])])
                new.append(np.column_stack([q, np.tile(n, (3, 1)), uv]))
    new = np.array(new)
    # the poking faces go only where the cover lies over them fully (its inner part, past the tuck)
    full = inside & (rim > 0.999)
    ci = np.clip(np.round((cen[:, 0] - x0) / (x1 - x0) * nx).astype(int), 0, nx); cj = np.clip(np.round((cen[:, 1] - y0) / (y1 - y0) * ny).astype(int), 0, ny)
    gone = poke & full[cj, ci]
    # smooth normals over the cover itself (its grid)
    report[name] = {"removed_poking_faces": int(gone.sum()), "cover_faces": int(len(new)), "envelope_cells": int(len(env)),
                    "fit_residual_mm": round(float(np.median(np.abs(env[:, 2] - f(env[:, :2])))) * 1000, 2)}
    report[name]["removed_poking_faces"] = int(gone.sum())
    return np.concatenate([C[~gone], new])


def smooth_normals(C, angle=60):
    """per-corner normals again: the area-weighted face normals of each welded vertex, within `angle` of the face's own"""
    ids, pos = weld(C)
    fn = np.cross(C[:, 1, :3] - C[:, 0, :3], C[:, 2, :3] - C[:, 0, :3]); area = np.linalg.norm(fn, axis=1, keepdims=True)
    fu = fn / np.maximum(area, 1e-12)
    acc = np.zeros((len(pos), 3)); np.add.at(acc, ids.ravel(), np.repeat(fn, 3, axis=0))
    vn = acc / np.maximum(np.linalg.norm(acc, axis=1, keepdims=True), 1e-12)
    N = vn[ids]; cosa = (N * fu[:, None, :]).sum(-1); N[cosa < np.cos(np.radians(angle))] = np.repeat(fu[:, None, :], 3, axis=1)[cosa < np.cos(np.radians(angle))]
    C = C.copy(); C[:, :, 3:6] = N; return C


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("src"); ap.add_argument("out"); ap.add_argument("--report", default="")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    C = load_ply(a.src); report = {"faces_in": int(len(C))}
    for name, R in REGIONS.items():
        if a.only and a.only not in name: continue
        C = repair(C, name, R, report)
    C = smooth_normals(C)
    report["faces_out"] = int(len(C))
    save_ply(a.out, C)
    print(json.dumps(report, indent=1))
    if a.report: open(a.report, "w").write(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
