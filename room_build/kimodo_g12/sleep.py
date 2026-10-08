"""A real sleeping pose at the end of a lying clip (the page holds the clip's last frame as the sleep pose, and its duvet
rises over every raised limb). Over the last BLEND s before the final HOLD s the recorded pose eases into:
  - the body flat on its back, face up, along the recorded head-to-hips direction, at the recorded hips' place;
  - legs straight and together (the rig's rest legs, a few degrees apart), feet relaxed;
  - spine, neck and head in line (rest), so the head lies back on the pillow, chin level;
  - arms straight down along the body, hands beside the hips (low, under the cover), fingers relaxed (rest).
python sleep.py <in.json (clip exported by exp.mjs)> <out.json (writeclip input)> [blend s] [hold s]"""
import json, sys, numpy as np
from rt import Skel, qmul, qinv, qrot, qnorm, qbetween, qslerp, FPS

inp, outp = sys.argv[1:3]
BLEND = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0
HOLD = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
d = json.load(open(inp)); ts = Skel(d); an = d['anims'][0]
dur = max(max(c['t']) for c in an['ch']); F = int(round(dur * FPS)) + 1
T, R = ts.sample(an, F)
P, Q, Sc = ts.fk(T, R)
ix = ts.ix; fl = F - 1
hip = P[fl, ix['Hip']]; head = P[fl, ix['Head']]
along = head - hip; along[1] = 0; along /= np.linalg.norm(along)          # head direction, level
up = np.array([0, 1.0, 0])

# the rest pose's frame: where the body points (hips->head) and faces, from the rig at rest
P0, Q0, S0 = ts.fk(ts.T[None], ts.R[None]); P0, Q0 = P0[0], Q0[0]
rest_along = P0[ix['Head']] - (P0[ix['L_Foot']] + P0[ix['R_Foot']]) / 2; rest_along /= np.linalg.norm(rest_along)   # feet to head: the whole body lies level
# rest facing: the toes' side (foot->toe), made perpendicular to the body axis
rf = (P0[ix['L_ToeBase']] + P0[ix['R_ToeBase']]) / 2 - (P0[ix['L_Foot']] + P0[ix['R_Foot']]) / 2
rf = rf - (rf @ rest_along) * rest_along; rf /= np.linalg.norm(rf)


def frame(a, f):
    s = np.cross(a, f); return np.stack([a, f, s], 1)


Rw = frame(along, up) @ frame(rest_along, rf).T                            # rest body -> lying, face up
w, x, y, z = 0, 0, 0, 0
tr = np.trace(Rw)
qw = np.sqrt(max(0, 1 + tr)) / 2
qx = np.copysign(np.sqrt(max(0, 1 + Rw[0, 0] - Rw[1, 1] - Rw[2, 2])) / 2, Rw[2, 1] - Rw[1, 2])
qy = np.copysign(np.sqrt(max(0, 1 - Rw[0, 0] + Rw[1, 1] - Rw[2, 2])) / 2, Rw[0, 2] - Rw[2, 0])
qz = np.copysign(np.sqrt(max(0, 1 - Rw[0, 0] - Rw[1, 1] + Rw[2, 2])) / 2, Rw[1, 0] - Rw[0, 1])
G = qnorm(np.array([qx, qy, qz, qw]))

# the target pose: every bone at its rest local rotation, the Hip turned by G in the world
Rt = ts.R.copy(); Tt = ts.T.copy()
hi = ix['Hip']; par = ts.parent[hi]
Qpar = Q[fl, par]                                                          # (Root: static)
Rt[hi] = qnorm(qmul(qinv(Qpar), qmul(G, Q0[hi])))
# the hips stay where they lay (the page lifts him onto its mattress from his skin)
Tt[hi] = T[fl, hi]
# arms down along the body: turn each upper arm (in the world) from its rest A-pose direction to point at the feet,
# a little out from the side so the hands lie beside the hips
Pt, Qt, _ = ts.fk(Tt[None], Rt[None]); Pt, Qt = Pt[0], Qt[0]
side = np.cross(along, up)
for s, sg in (('L', 1), ('R', -1)):
    a, b = ix[f'{s}_Upperarm'], ix[f'{s}_Forearm']
    cur = Pt[b] - Pt[a]; cur /= np.linalg.norm(cur)
    sd = side if (Pt[a] - Pt[hi]) @ side > 0 else -side                    # this shoulder's side
    want = -along * np.cos(np.radians(10)) + sd * np.sin(np.radians(10))   # 10 deg out from the body
    Qa = qmul(qbetween(cur, want), Qt[a])
    Rt[a] = qnorm(qmul(qinv(Qt[ts.parent[a]]), Qa))
    # elbows straight: forearm and hand at rest relative to the upper arm (Rt already rest)
Pt, Qt, _ = ts.fk(Tt[None], Rt[None]); Pt, Qt = Pt[0], Qt[0]
# legs together: each thigh turned to point along the body toward the feet, 3 deg out (the rest stance is a wide V)
for s in 'LR':
    a, b = ix[f'{s}_Thigh'], ix[f'{s}_Calf']
    cur = Pt[b] - Pt[a]; cur /= np.linalg.norm(cur)
    sd = side if (Pt[a] - Pt[hi]) @ side > 0 else -side
    want = -along * np.cos(np.radians(3)) + sd * np.sin(np.radians(3))
    Qa = qmul(qbetween(cur, want), Qt[a])
    Rt[a] = qnorm(qmul(qinv(Qt[ts.parent[a]]), Qa))
    Pt, Qt, _ = ts.fk(Tt[None], Rt[None]); Pt, Qt = Pt[0], Qt[0]

# blend: ease from the recorded pose into the target over BLEND s, then hold
f1 = max(0, F - 1 - int(round(HOLD * FPS))); f0 = max(0, f1 - int(round(BLEND * FPS)))
for f in range(f0, F):
    u = 1.0 if f >= f1 else (f - f0) / max(1, f1 - f0); u = u * u * (3 - 2 * u)
    for i in range(len(ts.names)):
        R[f, i] = qslerp(R[f, i], Rt[i], u)
    T[f, hi] = T[f, hi] * (1 - u) + Tt[hi] * u

P2, Q2, _ = ts.fk(T[[fl]], R[[fl]]); P2 = P2[0]
rel = lambda n: float(P2[ix[n], 1] - P2[ix['Hip'], 1])
print('final pose, heights over the hips (m): head %.3f knees %.3f/%.3f hands %.3f/%.3f feet %.3f/%.3f' % (
    rel('Head'), rel('L_Calf'), rel('R_Calf'), rel('L_Hand'), rel('R_Hand'), rel('L_Foot'), rel('R_Foot')))
print('hands from the hips along the body: %.2f / %.2f m' % tuple(float((P2[ix[f'{s}_Hand']] - P2[hi]) @ along) for s in 'LR'))
joints = {n['name'] for n in d['nodes']}
names = ts.names
out = {'name': an['name'], 'fps': FPS, 'F': F, 'nodes': [{'name': n['name'], 'parent': n['parent'], 't': n['t'], 'r': n['r'], 's': n['s']} for n in d['nodes']],
       'rot': {}, 'trans': {hi: np.round(T[:, hi], 6).ravel().tolist()}}
animated = {d['nodes'][c['node']]['name'] for c in an['ch'] if c['path'] == 'rotation'}
for i, n in enumerate(names):
    if n in animated: out['rot'][i] = np.round(R[:, i], 6).ravel().tolist()
json.dump(out, open(outp, 'w'))
