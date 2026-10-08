"""Split the owner's repaired Tripo chair (chair_owner_repair.py's output) into the parts of a real mesh office chair, for
their own materials (build_chair_owner.mjs), and give it texture coordinates for tiling micro-textures.

    python room_build/chair_owner_parts.py repaired.ply parts.ply [--preview colours.ply]

Tripo's own UVs belong to its texture atlas, which is not used. Each face gets a box projection instead: the two model
axes across its normal, in metres (the build scales them per material). The parts, by place and facing in the model's
frame (the chair facing +z, its gas lift on x 0, z -0.013, 0.978 tall, the seat cushion's top 0.407):
  mesh     the backrest's and the headrest's mesh, front and back, inside their frame rings
  lumbar   the lumbar pad's front
  seat     the seat cushion (its top and sides; the pan under it is plastic)
  plastic  the frame rings, the spine, the headrest's arm, the arm posts, the seat pan and the mechanism
  armpad   the armrests' tops
  lift     the gas lift's cylinder, between the base's hub and the mechanism
  base     the five-star base and its hub
  caster   the twin-wheel casters
Where a panel meets its frame ring, the faces are cut along a smooth line a fixed distance in from the panel's outline
(their attributes interpolated), so the change of material is a clean edge and not a face-by-face zigzag."""
import argparse
import sys

import numpy as np
from scipy import ndimage

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chair_owner_repair import load_ply  # noqa: E402

PARTS = ["mesh", "lumbar", "seat", "plastic", "armpad", "lift", "base", "caster"]
PREVIEW = {"mesh": (40, 90, 220), "lumbar": (230, 150, 40), "seat": (220, 60, 60), "plastic": (150, 150, 150),
           "armpad": (60, 200, 200), "lift": (240, 240, 120), "base": (60, 180, 80), "caster": (180, 60, 200)}
AXIS = (0.0, -0.013)                                     # the gas lift's x, z
# the panels: which faces outline them (x, y, z, |x|), the y and depth band the cut applies to, how far in the mesh starts
PANELS = [("mesh", lambda x, y, z, ax: (y > 0.56) & (y < 0.86) & (ax < 0.21) & (z > -0.2), (0.60, 0.845, -0.205), 0.030),
          ("mesh", lambda x, y, z, ax: (y > 0.86) & (z > -0.19), (0.86, 1.0, -0.19), 0.016),
          ("lumbar", lambda x, y, z, ax: (y > 0.44) & (y < 0.60) & (ax < 0.18) & (z > -0.15), (0.44, 0.60, -0.15), 0.006)]


class Inset:
    """distance (m) in from the filled, smoothed outline of a set of x-y points (0 outside), bilinear on a 2 mm grid"""
    def __init__(self, xy, step=0.002):
        self.lo = xy.min(0) - 0.01; self.step = step
        n = np.ceil((xy.max(0) + 0.01 - self.lo) / step).astype(int) + 1
        g = np.zeros(n, bool); i = ((xy - self.lo) / step).round().astype(int); g[i[:, 0], i[:, 1]] = True
        g = ndimage.binary_fill_holes(ndimage.binary_closing(g, iterations=3))
        g = ndimage.binary_opening(g, iterations=4)
        self.dt = ndimage.gaussian_filter(ndimage.distance_transform_edt(g) * step, 3)

    def __call__(self, q):
        j = (q - self.lo) / self.step
        return ndimage.map_coordinates(self.dt, [j[..., 0].ravel(), j[..., 1].ravel()], order=1, cval=0).reshape(q.shape[:-1])


def split(C, v, t, sel):
    """cut the faces `sel` whose corner values v (n, 3) straddle t along the line v = t (attributes interpolated)"""
    hi = v > t; k = hi.sum(1); cut = sel & (k > 0) & (k < 3)
    if not cut.any():
        return C
    Cc, vc, hc = C[cut], v[cut], hi[cut]
    lone = np.where(hc.sum(1) == 1, hc.argmax(1), (~hc).argmax(1))
    r = (np.arange(3)[None] + lone[:, None]) % 3; ar = np.arange(len(Cc))[:, None]
    Cc, vc = Cc[ar, r], vc[ar, r]                                       # (the lone corner first, the winding kept)
    a, b, c = Cc[:, 0], Cc[:, 1], Cc[:, 2]
    pab = a + (b - a) * ((t - vc[:, 0]) / (vc[:, 1] - vc[:, 0]))[:, None]
    pac = a + (c - a) * ((t - vc[:, 0]) / (vc[:, 2] - vc[:, 0]))[:, None]
    for p in (pab, pac):
        p[:, 3:6] /= np.linalg.norm(p[:, 3:6], axis=1, keepdims=True) + 1e-9
    T = np.concatenate([np.stack([a, pab, pac], 1), np.stack([pab, b, c], 1), np.stack([pab, c, pac], 1)])
    return np.concatenate([C[~cut], T])


def centres(C):
    c = C[:, :, :3].mean(1); n = C[:, :, 3:6].mean(1)
    return c, n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-9)


def parts(C):
    """(the faces, cut where panels meet their frames; each face's part name)"""
    cuts = []
    for name, rule, (y0, y1, zmin), t in PANELS:
        c, _ = centres(C); x, y, z = c.T
        f = Inset(c[rule(x, y, z, np.abs(x)), :2])
        C = split(C, f(C[:, :, :2]), t, (y > y0 - 0.02) & (y < y1 + 0.02) & (z > zmin))
        cuts.append((name, y0, y1, zmin, t, f))
    c, n = centres(C); x, y, z = c.T; ny, nz = n[:, 1], n[:, 2]; ax = np.abs(x); r = np.hypot(x - AXIS[0], z - AXIS[1])
    L = np.full(len(C), "plastic", dtype=object)
    L[y < 0.145] = "base"
    L[(y < 0.068) & (r > 0.19)] = "caster"
    L[(y >= 0.145) & (y < 0.215) & (r < 0.045)] = "lift"
    L[(y > 0.33) & (y < 0.45) & (z > -0.20) & (ax < 0.25) & (ny > -0.3)] = "seat"
    for name, y0, y1, zmin, t, f in cuts:
        inside = (y > y0 - 0.02) & (y < y1 + 0.02) & (z > zmin) & (f(C[:, :, :2]).mean(1) > t)
        L[inside & ((nz > -0.3) if name == "lumbar" else True)] = name   # (the lumbar pad's back is plastic)
    L[(ax > 0.212) & (z > -0.03) & (z < 0.065) & (y > 0.2) & (y < 0.53)] = "plastic"   # (the arm posts)
    L[(y > 0.49) & (ax > 0.2) & (ny > 0.5)] = "armpad"
    return C, L


def box_uv(C):
    """per face: the two model axes across its dominant normal axis, in metres"""
    _, n = centres(C); k = np.abs(n).argmax(1); P = C[:, :, :3]
    uv = np.empty(C.shape[:2] + (2,), np.float32)
    for axis, (a, b) in enumerate([(2, 1), (0, 2), (0, 1)]):            # (x-facing: z, y; y-facing: x, z; z-facing: x, y)
        m = k == axis; uv[m, :, 0] = P[m, :, a]; uv[m, :, 1] = P[m, :, b]
    return uv


def save(path, C, uv, part):
    """binary PLY: per corner x y z nx ny nz u v part (float32), faces of three"""
    n = len(C) * 3
    V = np.concatenate([C[:, :, :6].reshape(n, 6), uv.reshape(n, 2), np.repeat(part, 3)[:, None]], 1).astype("<f4")
    f = np.zeros(len(C), dtype=[("n", "u1"), ("i", "<i4", 3)]); f["n"] = 3; f["i"] = np.arange(n).reshape(-1, 3)
    props = "".join(f"property float {p}\n" for p in ("x", "y", "z", "nx", "ny", "nz", "s", "t", "part"))
    hdr = f"ply\nformat binary_little_endian 1.0\nelement vertex {n}\n{props}element face {len(C)}\nproperty list uchar int vertex_indices\nend_header\n"
    open(path, "wb").write(hdr.encode() + V.tobytes() + f.tobytes())


def save_preview(path, C, L):
    n = len(C) * 3; K = np.repeat(np.array([PREVIEW[p] for p in L], np.uint8), 3, axis=0)
    v = np.zeros(n, dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("r", "u1"), ("g", "u1"), ("b", "u1")])
    v["x"], v["y"], v["z"] = C[:, :, :3].reshape(n, 3).T; v["r"], v["g"], v["b"] = K.T
    f = np.zeros(len(C), dtype=[("n", "u1"), ("i", "<i4", 3)]); f["n"] = 3; f["i"] = np.arange(n).reshape(-1, 3)
    hdr = (f"ply\nformat binary_little_endian 1.0\nelement vertex {n}\nproperty float x\nproperty float y\nproperty float z\n"
           f"property uchar red\nproperty uchar green\nproperty uchar blue\nelement face {len(C)}\nproperty list uchar int vertex_indices\nend_header\n")
    open(path, "wb").write(hdr.encode() + v.tobytes() + f.tobytes())


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("src"); ap.add_argument("out"); ap.add_argument("--preview", default="")
    a = ap.parse_args()
    C, L = parts(load_ply(a.src))
    save(a.out, C, box_uv(C), np.array([PARTS.index(p) for p in L], np.float32))
    if a.preview:
        save_preview(a.preview, C, L)
    print(len(C), "faces:", {p: int((L == p).sum()) for p in PARTS})


if __name__ == "__main__":
    main()
