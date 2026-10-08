"""The joins of the behaviour chains (room_build/kimodo/mixamo_chains.json): for each step into the next clip, the last
frame of the one against the first frame of the next, and for each looping clip its own wrap (last -> first):
  - the worst bone-angle jump: the largest angle between the two local rotations of any joint (degrees), and which joint;
  - the hips' jump: the Hip's position in the clip frame (m) and its height alone (a seated slot clip is re-placed by the
    page on its seat, so its horizontal jump is the page's to absorb; its height is not);
  - with the cross-fade the chain gives the join, the jump per frame across it.
python chain_joins.py <mixamo_chains.json> <dir of exp.mjs jsons: x_<clip>.json> [out.json]"""
import json, sys, numpy as np
from rt import Skel, FPS
chains = json.load(open(sys.argv[1]))['chains']; xd = sys.argv[2]; out = {}
cache = {}
def ends(name):
    if name not in cache:
        d = json.load(open(f'{xd}/x_{name}.json')); s = Skel(d); a = d['anims'][0]
        F = int(round(max(max(c['t']) for c in a['ch']) * FPS)) + 1; T, R = s.sample(a, F); P, Q, Sc = s.fk(T, R)
        cache[name] = (s, R[[0, -1]], P[[0, -1], s.ix['Hip']])
    return cache[name]
def jump(a, b, ia, ib, blend):
    sa, Ra, Ha = ends(a); sb, Rb, Hb = ends(b)
    angs = []
    for j, n in enumerate(sa.names):
        if n not in sb.ix or n in ('Root',): continue
        qa, qb = Ra[ia, j], Rb[ib, sb.ix[n]]; angs.append((float(np.degrees(2 * np.arccos(min(1.0, abs(float(np.dot(qa, qb))))))), n))
    angs.sort(reverse=True); worst, wj = angs[0]
    dh = Hb[ib] - Ha[ia]; nf = max(1, round(blend * FPS))
    return {'worstDeg': round(worst, 1), 'joint': wj, 'next': [[n, round(x, 1)] for x, n in angs[1:4]], 'perFrameDeg': round(worst / nf, 2), 'blendFrames': nf,
            'hipsJump_m': round(float(np.linalg.norm(dh)), 3), 'hipsDy_m': round(float(dh[1]), 3)}
for name, steps in chains.items():
    if not isinstance(steps, list): out[name] = steps; continue
    r = []
    for i, st in enumerate(steps):
        if i: r.append({'join': f"{steps[i-1]['clip']} -> {st['clip']}", **jump(steps[i-1]['clip'], st['clip'], 1, 0, st.get('blend', 0))})
        if st.get('loop'): r.append({'wrap': st['clip'], **jump(st['clip'], st['clip'], 1, 0, 0)})
    out[name] = r
    for x in r: print(name, x)
# between chains: the seated loop into the next behaviour and back
for a, b, bl in json.load(open(sys.argv[1])).get('links', []):
    x = {'join': f'{a} -> {b}', **jump(a, b, 1, 0, bl)}; out.setdefault('links', []).append(x); print('link', x)
if len(sys.argv) > 3: json.dump(out, open(sys.argv[3], 'w'), indent=1)
