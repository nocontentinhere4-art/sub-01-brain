import json, numpy as np
def load(d, name):
    m = {x['name']: x for x in json.load(open(f'{d}/meta.json'))}[name]; A = {}
    for s, (N, E) in m['attrs'].items(): A[s] = np.fromfile(f'{d}/{name}.{s}.f32', np.float32).reshape(N, E)
    try: A['idx'] = np.fromfile(f'{d}/{name}.idx.u32', np.uint32).reshape(-1, 3)
    except FileNotFoundError: pass
    return A
def skin(d):
    s = json.load(open(f'{d}/skin.json')); W = {j: np.array(m).reshape(4, 4).T for j, m in zip(s['joints'], s['world'])}
    IB = {j: np.array(m).reshape(4, 4).T for j, m in zip(s['joints'], s['ibm'])}
    return s['joints'], W, IB
BODY_T = (0.8505, np.array([-0.0036, 0.8804, -0.0001]))
def world_v5(A, slides=False):
    P = A['POSITION'].astype(np.float64)
    return P if slides else P * BODY_T[0] + BODY_T[1]
def slice_tris(P, T, ax, c):
    v = P[T]; s = v[:, :, ax] - c; segs = []
    for k in range(3):
        a, b = v[:, k], v[:, (k + 1) % 3]; sa, sb = s[:, k], s[:, (k + 1) % 3]
        m = (sa < 0) != (sb < 0); t = (sa[m] / (sa[m] - sb[m]))[:, None]
        segs.append((np.nonzero(m)[0], a[m] + (b[m] - a[m]) * t))
    # pair up the two crossings of each triangle
    from collections import defaultdict
    d = defaultdict(list)
    for ids, pts in segs:
        for i, p in zip(ids, pts): d[i].append(p)
    return [v for v in d.values() if len(v) == 2]
