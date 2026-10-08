# v5's hood has open holes round the collar (open-edge loops of its mesh): each filled with a fan of triangles about its
# centre (a part of its own, hood_patches, two-sided), skinned from the nearest hood vertices. The loop along the hood's
# top rim (y 1.49-1.52) is the rim itself, behind the lining: left open. The body's own neck opening (the big loop round
# the neck, the hoodie's neckline) is closed by a band up to the neck's skin (hood_neck_fill, below).
# A hole whose edge lies in one texture chart of the hood takes the hood's own texture there (its edge vertices' UVs,
# the centre their mean: the same fabric, colour and grain as round it); the others (a seam crosses them) take the
# lining's tiled patch (UV by position, 7.6 cm a tile; hood_patches_tiled). Each fan is domed: a middle ring, and the
# centre pushed 4 mm out of the hood (a flat fan read as a plate)
from bnd import *
from scipy.spatial import cKDTree
import os, sys
B = load('v5', 'tripo_node_6bf04053-_0'); P = world_v5(B); UVb = B['TEXCOORD_0']
loops, _, _ = boundary_loops(P, B['idx']); c0 = np.array([0.0017, 0, -0.0109])
sel = [L for L in loops if 1.33 < L.mean(0)[1] < 1.56 and np.hypot(*(L.mean(0) - c0)[[0, 2]]) < 0.2 and not (L[:, 1].min() > 1.49 and len(L) > 100)]
neck = [L for L in sel if np.hypot(*(L.mean(0) - c0)[[0, 2]]) < 0.04 and len(L) > 100]
sel = [L for L in sel if not any(L is q for q in neck)]
kd = cKDTree(P); DOME = 0.004
def dense(A, i):
    w = np.zeros(79)
    for j, x in zip(A['JOINTS_0'][i].astype(int), A['WEIGHTS_0'][i]): w[j] += x
    return w
parts = {'own': ([], [], []), 'tiled': ([], [], [])}
# (the page draws every skinned part's back faces black, as its inside: each fill is wound to face the way it is seen
# from, the hood's patches out of the hood, the neck's band up)
def orient(V, I, i0, want):
    Vv = np.array(V); T = np.array(I[i0:]); f = np.cross(Vv[T[:, 1]] - Vv[T[:, 0]], Vv[T[:, 2]] - Vv[T[:, 0]])
    if (f @ want).sum() < 0:
        for q in range(i0, len(I)): I[q] = [I[q][0], I[q][2], I[q][1]]
for L in sel:
    uvs, prev = [], None                     # each edge vertex's UV: of the copies at its position, the one nearest the last
    for p in L:
        cand = UVb[kd.query_ball_point(p, 1e-5)]
        c = cand[0] if prev is None else cand[np.argmin(np.linalg.norm(cand - prev, axis=1))]; uvs.append(c); prev = c
    uvs = np.array(uvs); one = np.linalg.norm(np.diff(np.r_[uvs, uvs[:1]], axis=0), axis=1).max() < 0.05
    n = len(L); c = L.mean(0)
    nrm = np.zeros(3)                        # the loop's normal (Newell), turned away from the neck's axis
    for k in range(n): a, b = L[k], L[(k + 1) % n]; nrm += np.cross(a - c, b - c)
    nrm /= max(np.linalg.norm(nrm), 1e-12); out = c - c0; out[1] = 0
    if nrm @ out < 0: nrm = -nrm
    mid = 0.5 * (L + c) + 0.75 * DOME * nrm; top = c + DOME * nrm
    V, U, I = parts['own' if one else 'tiled']; base = len(V); i0 = len(I)
    V += list(L) + list(mid) + [top]
    U += list(uvs) + list(0.5 * (uvs + uvs.mean(0))) + [uvs.mean(0)] if one else [None] * (2 * n + 1)
    for k in range(n):
        k2 = (k + 1) % n; I += [[base + k, base + k2, base + n + k2], [base + k, base + n + k2, base + n + k], [base + n + k, base + n + k2, base + 2 * n]]
    orient(V, I, i0, nrm)
# the neckline: the hoodie's own neck opening closed by a band from it to the neck (hood_neck_fill): each neckline
# vertex joined to the neck's skin at its angle, 4 mm over the skin's cut lower edge there (the throat's ends in a ring at
# 1.454 m, the sides' and back's in a saw-toothed cut up to 1.478 m; under it other surfaces of the bust carry on), 2 mm
# inside the skin, so the band runs under it along a smooth line; a middle row bowed 2 mm out. In the lining's fabric, a
# shade darker. As a flat fan across the opening it caught the light as a lighter plate under the chin, and without it
# the hoodie's inside showed black between the lining and the neck (G23's review)
from radial import crossings
H = load('v5', 'tripo_node_6bf04053-_1'); PH = world_v5(H); v = PH[H['idx']]
TH = H['idx'][(v[:, :, 1].max(1) > 1.40) & (v[:, :, 1].min(1) < 1.56) & (np.hypot(v[:, :, 0] - c0[0], v[:, :, 2] - c0[2]).min(1) < 0.12)]
_lp, _, _ = boundary_loops(PH, H['idx']); EH = np.vstack([L for L in _lp if L[:, 1].min() > 1.41 and L[:, 1].max() < 1.56])
eth = np.arctan2(EH[:, 2] - c0[2], EH[:, 0] - c0[0])
parts['neck'] = ([], [], [])
for L in neck:
    n = len(L); V, U, I = parts['neck']; base = len(V); i0 = len(I); hi = []; up = []
    for p in L:
        th = np.arctan2(p[2] - c0[2], p[0] - c0[0]); m = np.abs((eth - th + np.pi) % (2 * np.pi) - np.pi) < np.radians(9)
        cut = EH[m, 1].max() if m.any() else 1.454; up.append(p[1] > cut + 0.002 or abs(th) > np.radians(70))
        yq = round(cut + 0.004, 3); ys = [round(yq + k * 0.002, 3) for k in range(6)]
        _, ch = crossings(PH, TH, c0, th, ys); yy = next((y for y in ys if ch[y]), None)
        r = (max(ch[yy]) if yy else np.hypot(p[0] - c0[0], p[2] - c0[2])) - 0.002
        d = np.array([np.cos(th), 0, np.sin(th)]); hi.append(c0 + d * r + np.array([0, yy or yq, 0]))
    hi = np.array(hi)
    for k in range(3): hi = (np.roll(hi, 1, 0) + 2 * hi + np.roll(hi, -1, 0)) / 4      # (smoothed along the neckline)
    mid = 0.5 * (L + hi)
    radial = mid - c0; radial[:, 1] = 0; radial /= np.linalg.norm(radial, axis=1, keepdims=True); mid += 0.002 * radial
    V += list(L) + list(mid) + list(hi); U += [None] * (3 * n)
    # (only round the front, +-70 deg: at the sides and back the lining meets the skin over its cut and closes the collar
    # itself, and where the neckline runs up the hood's edge, over the skin's cut, it is behind the lining already)
    for r_ in range(2):
        for k in range(n):
            k2 = (k + 1) % n
            if up[k] and up[k2]: continue
            a_, b_, c_, d_ = base + r_ * n + k, base + r_ * n + k2, base + (r_ + 1) * n + k2, base + (r_ + 1) * n + k
            I += [[a_, b_, c_], [a_, c_, d_]]
    orient(V, I, i0, np.array([0, 1.0, 0]))
    print('neck band', len(I) - i0, 'triangles; neckline y', L[:, 1].min().round(3), L[:, 1].max().round(3), '-> skin y', hi[:, 1].min().round(3), hi[:, 1].max().round(3))
for name, (V, U, I) in parts.items():
    if not I: continue
    V = np.array(V); I = np.array(I)
    # (the tiled ones: round the neck's axis in metres, and height; 7.6 cm a tile)
    UV = np.array(U) if name == 'own' else np.c_[np.arctan2(V[:, 2] - c0[2], V[:, 0] - c0[0]) * np.hypot(V[:, 0] - c0[0], V[:, 2] - c0[2]), V[:, 1]] / 0.076
    f = np.cross(V[I[:, 1]] - V[I[:, 0]], V[I[:, 2]] - V[I[:, 0]]); Nn = np.zeros_like(V)
    for k in range(3): np.add.at(Nn, I[:, k], f)
    Nn /= np.maximum(np.linalg.norm(Nn, axis=1, keepdims=True), 1e-12)
    dd, ii = kd.query(V, 4); Wd = np.zeros((len(V), 79))
    for q in range(4):
        for r in range(len(V)): Wd[r] += dense(B, ii[r, q]) / (dd[r, q] + 1e-4)
    Jt = np.argsort(-Wd, 1)[:, :4]; Wt = np.take_along_axis(Wd, Jt, 1); Wt /= Wt.sum(1, keepdims=True)
    od = {'own': 'p_patches', 'tiled': 'p_patches_tiled', 'neck': 'p_neck_fill'}[name]; os.makedirs(od, exist_ok=True)
    for k, a, t in (('P', V, np.float32), ('N', Nn, np.float32), ('UV', UV, np.float32), ('J', Jt, np.uint16), ('W', Wt, np.float32), ('I', I, np.uint32)): a.astype(t).tofile(f'{od}/{k}.bin')
    print(name, len(I), 'triangles')
print(len(sel), 'holes filled:', [len(L) for L in sel], '+ the neck opening (band to the skin)')
