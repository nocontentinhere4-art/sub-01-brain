from lib import *
from collections import defaultdict
def boundary_loops(P, T, weld=1e-5):
    # weld by position, count edge uses, chain the edges used once into loops
    key = np.round(P / weld).astype(np.int64); _, wid = np.unique(key, axis=0, return_inverse=True); wid = wid.ravel()
    TT = wid[T]; E = np.sort(np.r_[TT[:, [0, 1]], TT[:, [1, 2]], TT[:, [2, 0]]], axis=1)
    u, cnt = np.unique(E, axis=0, return_counts=True); bd = u[cnt == 1]
    pos = np.zeros((wid.max() + 1, 3)); pos[wid] = P
    adj = defaultdict(list)
    for a, b in bd: adj[a].append(b); adj[b].append(a)
    seen = set(); loops = []
    for s in adj:
        if s in seen: continue
        loop = [s]; seen.add(s); cur = s
        while True:
            nx = [n for n in adj[cur] if n not in seen]
            if not nx: break
            cur = nx[0]; seen.add(cur); loop.append(cur)
        loops.append(pos[loop])
    return loops, len(bd), (cnt > 2).sum()
