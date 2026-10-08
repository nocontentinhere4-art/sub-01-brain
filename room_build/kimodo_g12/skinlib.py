"""Linear-blend skinning helpers for the QA and the post-pass."""
import numpy as np


def mats(P, Q, Sc):
    """world 4x4 per node from pos/rot/scale (F,N)."""
    x, y, z, w = np.moveaxis(Q, -1, 0)
    R = np.stack([np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], -1),
                  np.stack([2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], -1),
                  np.stack([2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)], -1)], -2)
    M = np.zeros(P.shape[:2] + (4, 4)); M[..., :3, :3] = R * Sc[None, :, None, None]; M[..., :3, 3] = P; M[..., 3, 3] = 1
    return M


def skin_setup(d, step, scale_int=True):
    J = d['skin']['joints']; ibm = np.array(d['skin']['ibm']).reshape(-1, 4, 4).transpose(0, 2, 1)
    V, JI, WW = [], [], []
    for m in d['mesh']:
        p = np.array(m['pos'], float).reshape(-1, 3); j = np.array(m['j']).reshape(-1, 4); w = np.array(m['w'], float).reshape(-1, 4)
        if m['norm']: p = p / 32767.0
        if w.max() > 1.5: w = w / w.sum(1, keepdims=True)
        V.append(p[::step]); JI.append(j[::step]); WW.append(w[::step])
    return np.array(J), ibm, np.concatenate(V), np.concatenate(JI), np.concatenate(WW)


def skin(M, J, ibm, V, JI, WW):
    """M (F,N,4,4) node worlds -> (F,V,3)."""
    S = M[:, J] @ ibm[None]                                  # (F, joints, 4, 4)
    Vh = np.concatenate([V, np.ones((len(V), 1))], 1)
    out = np.zeros((M.shape[0], len(V), 3))
    for k in range(4):
        Sk = S[:, JI[:, k]]                                  # (F, V, 4, 4)
        out += WW[None, :, k, None] * np.einsum('fvij,vj->fvi', Sk, Vh)[..., :3]
    return out




def thigh_radius(X0, P0, ix, dom):
    """The thigh's half-thickness under the bone at bind (trousers included): the 90th percentile distance of the
    thigh's vertices from the hip-knee axis, middle of the thigh, its back (what lies on the seat)."""
    r = []
    for s in 'LR':
        a, b = P0[ix[f'{s}_Thigh']], P0[ix[f'{s}_Calf']]; u = (b - a) / np.linalg.norm(b - a)
        m = np.isin(dom, [f'{s}_Thigh', f'{s}_ThighTwist01', f'{s}_ThighTwist02'])
        v = X0[m] - a; t = v @ u; L = np.linalg.norm(b - a)
        rad = v - t[:, None] * u
        k = (t > 0.3 * L) & (t < 0.7 * L) & (rad[:, 0] < -0.5 * np.linalg.norm(rad, axis=1))   # the back of the thigh (faces +X)
        r.append(np.median(np.linalg.norm(rad[k], axis=1)))
    return float(np.mean(r))


def seat_low(P, ix, r):
    """What rests on a chair seat: the underside of the thighs, from the bones (hip-knee axis, its middle half, less
    the thigh's thickness). Linear-blend skinning collapses the skin at the top of the thigh at a 90 deg hip bend, so
    the skin there is not used (it is reported apart as buttock_sag)."""
    lo = 9.0
    for s in 'LR':
        a, b = P[ix[f'{s}_Thigh']], P[ix[f'{s}_Calf']]
        for t in (0.2,): lo = min(lo, (a + (b - a) * t)[1] - r)    # near the hip end: the knees may sit higher
    return lo
