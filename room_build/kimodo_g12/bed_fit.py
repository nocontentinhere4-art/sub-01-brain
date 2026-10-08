"""A lying clip (retargeted onto v5) fitted to the room's bed the way the page places it. The page does not place a lying
clip by its own pose: it turns and moves him by a reference pose (asleep: room_bedtime's last frame; lying awake:
room_bed_lie's last frame), so the clip's hips and heading (hips -> head, level) are moved onto the reference's at its
first frame; and the page lifts him onto the mattress by his lowest skin, re-measured once a second while he lies still,
so his lowest skin is held at the reference's level in every frame (a vertical move of the Hip): no step when he turns over.
python bed_fit.py <ref.x.json> <in.x.json> <out.json (writeclip input)> <v5.json (exp.mjs of web/room/char_v5.glb)>"""
import json, sys, numpy as np
from rt import Skel, qmul, qinv, qrot, qnorm, qy, FPS
from skinlib import mats, skin_setup, skin

ref_p, in_p, out_p, v5_p = sys.argv[1:5]
dr = json.load(open(ref_p)); sr = Skel(dr); ar = dr['anims'][0]; Fr = int(round(max(max(c['t']) for c in ar['ch']) * FPS)) + 1
Tr, Rr = sr.sample(ar, Fr); Pr, Qr, Sr = sr.fk(Tr[[-1]], Rr[[-1]])
d = json.load(open(in_p)); ts = Skel(d); an = d['anims'][0]; F = int(round(max(max(c['t']) for c in an['ch']) * FPS)) + 1
T, R = ts.sample(an, F); hi = ts.ix['Hip']; hd = ts.ix['Head']; par = ts.parent[hi]
P, Q, Sc = ts.fk(T, R)
head = lambda P, f: P[f, hd] - P[f, hi]
a_ref = np.arctan2(head(Pr, 0)[2], head(Pr, 0)[0]); a_in = np.arctan2(head(P, 0)[2], head(P, 0)[0])
th = a_in - a_ref                                            # qy(th) turns the clip's heading onto the reference's
Y = qy(th)
# the Hip's world rotation and position turned about the first frame's hips, then moved onto the reference's hips
c0 = P[0, hi].copy(); Qh = qmul(np.broadcast_to(Y, Q[:, hi].shape), Q[:, hi])
ph = qrot(np.broadcast_to(Y, (F, 4)), P[:, hi] - c0) + np.array([Pr[0, sr.ix['Hip']][0], c0[1], Pr[0, sr.ix['Hip']][2]])
R[:, hi] = qnorm(qmul(qinv(Q[:, par]), Qh))
T[:, hi] = qrot(qinv(Q[:, par]), ph - P[:, par]) / Sc[par]
# his lowest skin held at the reference's level, every vertex of the body the page shows
v5 = json.load(open(v5_p)); vn = [n['name'] for n in v5['nodes']]
J, ibm, V, JI, WW = skin_setup(v5, 1); Jn = np.array([ts.ix[vn[j]] for j in J]); Jr = np.array([sr.ix[vn[j]] for j in J])
low_ref = float(skin(mats(Pr, Qr, Sr), Jr, ibm, V, JI, WW)[0][:, 1].min())
shifts = []
for f0 in range(0, F, 30):
    sl = slice(f0, min(F, f0 + 30)); P2, Q2, S2 = ts.fk(T[sl], R[sl]); X = skin(mats(P2, Q2, S2), Jn, ibm, V, JI, WW)
    for k, f in enumerate(range(sl.start, sl.stop)):
        dy = low_ref - float(X[k][:, 1].min()); shifts.append(dy)
        T[f, hi] = T[f, hi] + qrot(qinv(Q[f, par]), np.array([0, dy, 0])) / Sc[par]
P2, _, _ = ts.fk(T[[0]], R[[0]])
print('turned %.1f deg; hips onto the reference (%.3f, %.3f); lowest skin held (shift %.3f..%.3f m)' % (
    np.degrees(th), Pr[0, sr.ix['Hip']][0], Pr[0, sr.ix['Hip']][2], min(shifts), max(shifts)))
animated = {d['nodes'][c['node']]['name'] for c in an['ch'] if c['path'] == 'rotation'}
out = {'name': an['name'], 'fps': FPS, 'F': F, 'nodes': [{k: n[k] for k in ('name', 'parent', 't', 'r', 's')} for n in d['nodes']],
       'rot': {i: np.round(R[:, i], 6).ravel().tolist() for i, n in enumerate(ts.names) if n in animated},
       'trans': {hi: np.round(T[:, hi], 6).ravel().tolist()}}
json.dump(out, open(out_p, 'w'))
