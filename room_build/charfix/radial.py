from lib import *
import sys
def crossings(P, T, c, th, ys):
    d = np.array([np.cos(th), 0, np.sin(th)]); n = np.array([-np.sin(th), 0, np.cos(th)])
    v = P[T]; s = (v - c) @ n
    out = {y: [] for y in ys}
    segs = []
    for k in range(3):
        a, b = v[:, k], v[:, (k + 1) % 3]; sa, sb = s[:, k], s[:, (k + 1) % 3]
        m = (sa < 0) != (sb < 0); t = (sa[m] / (sa[m] - sb[m]))[:, None]; segs.append((np.nonzero(m)[0], a[m] + (b[m] - a[m]) * t))
    from collections import defaultdict
    dd = defaultdict(list)
    for ids, pts in segs:
        for i, p in zip(ids, pts): dd[i].append(p)
    S = [(p[0], p[1]) for p in dd.values() if len(p) == 2]
    for y in ys:
        rs = []
        for a, b in S:
            if (a[1] - y) * (b[1] - y) < 0:
                p = a + (b - a) * ((y - a[1]) / (b[1] - a[1])); r = (p - c) @ d
                if r > 0: rs.append(r)
        out[y] = sorted(rs)
    return S, out
