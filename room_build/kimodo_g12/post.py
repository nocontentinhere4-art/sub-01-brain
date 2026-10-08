"""After the shared retarget (G14's mh_retarget.mjs): put the v5 skin where the furniture is, then re-solve the legs.
 - seated (the MakeHuman hips low, head up): the Hip moves so the lowest skin under the hips sits on the seat (0.505 m,
   the live chair), blended in and out with how seated he is;
 - lying (head low): the Hip moves so the lowest skin of the body lies on the clip's mattress (the MakeHuman body's
   lowest point at that moment), never in it;
 - the shift is smoothed (zero phase), then two-bone IK puts the ankles back where they were, raised where a sole would
   go through the floor; planted feet stay planted (the ankle goals are the retarget's, which follow the recorded ones).
python post.py <json dir> <clip> <g14 out.json> <out.json>"""
import json, sys, numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from rt import Skel, qrot, qmul, qinv, qy, qbetween, qnorm, lowpass, two_bone, FPS
from skinlib import mats, skin_setup, skin, seat_low

jdir, clip, inj, outj = sys.argv[1:5]
SEAT = 0.505
import os as _os
SEAT_UP = float(_os.environ.get('SEAT_UP', 0)); SEAT_HIP_Y = float(_os.environ.get('SEAT_HIP_Y', 0)); SOLE_UP = float(_os.environ.get('SOLE_UP', 0.002)); SHIFT_MAX = float(_os.environ.get('SHIFT_MAX', 0.25)); SEAT_FWD = float(_os.environ.get('SEAT_FWD', 0))   # (m) the room fit for seated frames
C = qy(np.pi / 2)
v5 = json.load(open(Path(jdir) / 'v5.json')); rj = json.load(open(inj))
ts = Skel(rj); an = rj['anims'][0]; dur = max(max(c['t']) for c in an['ch']); F = int(round(dur * FPS)) + 1
T, R = ts.sample(an, F)
src = json.load(open(Path(jdir) / f'{clip}.json')); ss = Skel(src); sT, sR = ss.sample(src['anims'][0], F)
sP, sQ, sSc = ss.fk(sT, sR); sP = qrot(C, sP); sQ = qmul(np.broadcast_to(C, sQ.shape), sQ)
mh = json.load(open(Path(jdir) / 'mh_body.json')); mh['mesh'] = mh['mesh'][:1]
vn = [n['name'] for n in v5['nodes']]; mn = [n['name'] for n in mh['nodes']]
J, ibm, V, JI, WW = skin_setup(v5, 6); Jn = np.array([ts.ix[vn[j]] for j in J])
dom = np.array(vn)[J[JI[np.arange(len(JI)), WW.argmax(1)]]]
lower = ['L_Foot', 'R_Foot', 'L_ToeBase', 'R_ToeBase']
sole = np.isin(dom, lower)
seatv = np.isin(dom, ['L_Thigh', 'R_Thigh', 'L_ThighTwist01', 'R_ThighTwist01', 'L_ThighTwist02', 'R_ThighTwist02'])   # trouser seat and thighs (the rigid hoodie hem hangs lower when seated)
mJ, mibm, mV, mJI, mWW = skin_setup(mh, 4)
MHB = all(mn[j] in ss.ix for j in mJ)   # the MakeHuman body (for the lying lift) only when the source is a MakeHuman clip (not Mixamo)
mJn = np.array([ss.ix[mn[j]] for j in mJ]) if MHB else None
backv = np.isin(dom, ['Hip', 'Pelvis', 'Waist', 'Spine01'])   # what lies on a mattress: the lower back and pelvis (the rigid hood stands out behind the neck)
mdom = np.array(mn)[mJ[mJI[np.arange(len(mJI)), mWW.argmax(1)]]]
mback = np.array([d.startswith(('Hips', 'Spine02', 'spine04', 'Spine01', 'pelvis')) for d in mdom])
hipsY = sP[:, ss.ix['Hips'], 1]; headY = sP[:, ss.ix['Head'], 1]
sm = lambda x: np.clip(x, 0, 1) ** 2 * (3 - 2 * np.clip(x, 0, 1))
w_seat = sm((0.74 - hipsY) / 0.10) * sm((headY - 1.0) / 0.1)
w_lie = sm((1.05 - headY) / 0.12)
hi = ts.ix['Hip']
from skinlib import thigh_radius
_P0, _Q0, _S0 = ts.fk(ts.T[None], ts.R[None]); RTH = thigh_radius(skin(mats(_P0, _Q0, _S0), Jn, ibm, V, JI, WW)[0], _P0[0], ts.ix, dom)
print('thigh radius %.3f' % RTH)


def body(T, R):
    P, Q, Sc = ts.fk(T, R); M = mats(P, Q, Sc)
    return P, Q, Sc, M


P, Q, Sc, M = body(T, R)
# the seat in the clip's frame: where the hips rest while he is seated; "over it" within 0.20 m of that (horizontally)
_sc = P[w_seat > 0.9, hi][:, [0, 2]].mean(0) if (w_seat > 0.9).any() else None
over_seat = np.zeros(F, bool) if _sc is None else np.linalg.norm(P[:, hi][:, [0, 2]] - _sc, axis=1) < 0.20
ankles0 = {s: P[:, ts.ix[f'{s}_Foot']].copy() for s in 'LR'}
# planted feet: while an ankle is low and slow (the recorded shuffles drift up to 4.5 cm over a long stance) it is held
# on one spot (the stance's mean), blended in and out over 0.15 s
locks = {}
for s in 'LR':
    a = ankles0[s]; low = a[:, 1] < a[:, 1].min() + 0.03
    v = np.r_[0, np.linalg.norm(np.diff(a[:, [0, 2]], axis=0), axis=1) * FPS]; on = low & (v < 0.15)
    if __import__('os').environ.get('LOCK_MH'):
        # contact from the recorded foot (low and slow over 0.1 s): a stance whose ankle sits a little high on v5
        # (bedtime 9.0-9.8 s) is held too
        m = 'Left' if s == 'L' else 'Right'; am = sP[:, ss.ix[f'{m}Foot']]
        vm = np.r_[np.zeros(3), np.linalg.norm(am[3:, [0, 2]] - am[:-3, [0, 2]], axis=1) * FPS / 3]
        on = on | ((am[:, 1] < am[:, 1].min() + 0.03) & (vm < 0.15))
    g = a.copy(); wmax = np.zeros(F); f0 = None; n = 0
    for f in range(F + 1):
        if f < F and on[f]: f0 = f if f0 is None else f0
        elif f0 is not None:
            if f - f0 >= 9:
                n += 1; lock = a[f0:f, [0, 2]].mean(0)
                for k in range(max(0, f0 - 5), min(F, f + 5)):
                    w = 1.0 if f0 <= k < f else max(0.0, 1 - (f0 - k if k < f0 else k - f + 1) / 5.0)
                    if w > wmax[k]: g[k, [0, 2]] = a[k, [0, 2]] * (1 - w) + lock * w; wmax[k] = w
            f0 = None
    ankles0[s] = g; locks[s] = n
print(clip, 'planted stances locked', locks)
total = np.zeros(F)
for PASS in range(2):
  need = np.zeros(F); hard = np.zeros(F, bool)
  for f0 in range(0, F, 60):
      sl = slice(f0, min(F, f0 + 60))
      X = skin(M[sl], Jn, ibm, V, JI, WW)
      Y = skin(mats(sP[sl], sQ[sl], sSc)[:, :], mJn, mibm, mV, mJI, mWW) if MHB and w_lie[sl].max() > 0 else None
      for k, f in enumerate(range(sl.start, sl.stop)):
          x = X[k]; d = 0.0; wt = 0.0
          if SEAT_HIP_Y and over_seat[f] and P[f, hi, 1] < SEAT_HIP_Y:
              # (the hips over the seat, under its height: he is landing on it or pushing off it, bent forward with his
              # head low, so not "seated" by the weight; the cushion stops him, whatever the blend)
              d += SEAT_HIP_Y - P[f, hi, 1]; wt += 1; hard[f] = True
          elif w_seat[f] > 0:
              lo = seat_low(P[f], ts.ix, RTH)
              if SEAT_HIP_Y: d += w_seat[f] * (SEAT_HIP_Y - P[f, hi, 1]); wt += w_seat[f]   # (the hips' joint at a set height on OUR chair)
              elif lo == lo: d += w_seat[f] * (SEAT + SEAT_UP - lo); wt += w_seat[f]
          if w_lie[f] > 0 and Y is not None and not __import__('os').environ.get('NOLIE'):
              # (off for the room: boy_mh.js lifts him onto its own mattress from his skin every frame (bedLift), so a
              # lift here stacks on top of it and he floats over the bed with the duvet tented)
              pen = Y[k][mback, 1].min() - x[backv, 1].min()          # > 0: the back is under the mattress
              d += pen if pen > 0 else w_lie[f] * pen; wt += w_lie[f]   # never into it, whatever the blend
          need[f] = d
  # keep the peaks: a running max over +-0.25 s before the smoothing, so a short dip is not averaged away (not the
  # seat's floor: a lift spread 0.25 s early would hold him up before he lands, so his hips would bounce on the way down)
  pk = np.array([np.where(hard, 0, need)[max(0, f - 8):f + 9].max() for f in range(F)])
  need = np.where((need > 0) & ~hard, np.maximum(need, lowpass(pk, 2.0)), need)
  need = np.clip(lowpass(need, 3.0), -SHIFT_MAX - total, SHIFT_MAX - total); total += need
  if PASS == 0 and (SEAT_UP or SEAT_FWD):
      # (a fit measured in the room: the contact pass gives how far his thighs sink into OUR cushion and his back into
      # the backrest; the seated frames move up / forward by that, the feet stay planted by the leg IK below)
      fw = SEAT_FWD * w_seat; par0 = ts.parent[hi]
      T[:, hi] = T[:, hi] + qrot(qinv(Q[:, par0]), np.stack([fw, np.zeros(F), np.zeros(F)], -1)) / Sc[par0]
  # move the Hip (in its parent's frame) by the world-vertical shift
  par = ts.parent[hi]
  T[:, hi] = T[:, hi] + qrot(qinv(Q[:, par]), np.stack([np.zeros(F), need, np.zeros(F)], -1)) / Sc[par]
  P, Q, Sc, M = body(T, R)
  # sole clearance per frame at the original ankles: how far below the floor the soles would be
  for it in range(2):
      X = np.concatenate([skin(M[i:i + 60], Jn, ibm, V[sole], JI[sole], WW[sole]) for i in range(0, F, 60)])
      for s in 'LR':
          side = np.array([d.startswith(s + '_') for d in dom[sole]])
          low = X[:, side, 1].min(1)
          lift = lowpass(np.maximum(0, -low + SOLE_UP), 4.0) if it == 0 else np.maximum(0, -low + SOLE_UP)   # (SOLE_UP: the slides under his socks)
          goal = ankles0[s] if it == 0 else P[:, ts.ix[f'{s}_Foot']].copy()
          goal = goal + np.stack([np.zeros(F), lift, np.zeros(F)], -1)
          a, b, c = ts.ix[f'{s}_Thigh'], ts.ix[f'{s}_Calf'], ts.ix[f'{s}_Foot']
          l1 = np.linalg.norm(T[0, b]) * Sc[a]; l2 = np.linalg.norm(T[0, c]) * Sc[b]
          nb, g = two_bone(P[:, a], P[:, b], P[:, c], goal, l1, l2)
          d1 = qbetween(P[:, b] - P[:, a], nb - P[:, a]); Qa = qmul(d1, Q[:, a]); Qb = qmul(d1, Q[:, b])
          pc = nb + qrot(Qb, Sc[b] * T[:, c]); d2 = qbetween(pc - nb, g - nb); Qb = qmul(d2, Qb)
          R[:, a] = qnorm(qmul(qinv(Q[:, ts.parent[a]]), Qa)); R[:, b] = qnorm(qmul(qinv(Qa), Qb)); R[:, c] = qnorm(qmul(qinv(Qb), Q[:, c]))
          P, Q, Sc, M = body(T, R)
# arms: the wrists back onto the MakeHuman wrists (door handle, sill, bed), the hands keep their world rotation
for s, m in (('L', 'Left'), ('R', 'Right')):
    a, b, c = ts.ix[f'{s}_Upperarm'], ts.ix[f'{s}_Forearm'], ts.ix[f'{s}_Hand']
    l1 = np.linalg.norm(T[0, b]) * Sc[a]; l2 = np.linalg.norm(T[0, c]) * Sc[b]
    goal = sP[:, ss.ix[f'{m}Hand']]
    goal = goal + np.array([0, float(_os.environ.get('HAND_UP', 0)), 0])   # (a hand resting on his thigh: on the cloth, not in it)
    KEY = [float(x) for x in _os.environ.get('KEYS', '0,0').split(',')]
    if KEY[0] or KEY[1]:
        # (a performer who typed at another desk: while his hands are out at the keyboard (the wrist 0.30 -> 0.40 m in
        # front of his hips, eased in), they move by [forward, up] onto OUR keyboard; resting hands do not)
        reach = (goal[:, 0] - sP[:, ss.ix['Hips'], 0]) * float(_os.environ.get('K_HIP', 0.91))
        wk = sm((reach - 0.30) / 0.10)
        goal = goal + np.stack([KEY[0] * wk, KEY[1] * wk, np.zeros(F)], -1)
    if _os.environ.get('HANDS_RIDE'):
        # (a source posed on another chair: the hands move with the body as it is fitted onto ours, up and forward)
        goal = goal + np.stack([SEAT_FWD * w_seat, total, np.zeros(F)], -1)
    nb, g = two_bone(P[:, a], P[:, b], P[:, c], goal, l1, l2)
    d1 = qbetween(P[:, b] - P[:, a], nb - P[:, a]); Qa = qmul(d1, Q[:, a]); Qb = qmul(d1, Q[:, b])
    pc = nb + qrot(Qb, Sc[b] * T[:, c]); d2 = qbetween(pc - nb, g - nb); Qb = qmul(d2, Qb)
    R[:, a] = qnorm(qmul(qinv(Q[:, ts.parent[a]]), Qa)); R[:, b] = qnorm(qmul(qinv(Qa), Qb)); R[:, c] = qnorm(qmul(qinv(Qb), Q[:, c]))
    P, Q, Sc, M = body(T, R)
print(clip, 'hip shift: seated max %.3f, lying %.3f..%.3f m' % (total[w_seat > 0.5].max() if (w_seat > 0.5).any() else 0,
      total[w_lie > 0.5].min() if (w_lie > 0.5).any() else 0, total[w_lie > 0.5].max() if (w_lie > 0.5).any() else 0))
if _os.environ.get('SEAT_ORIGIN') and (w_seat > 0.9).any():
    # (a transition the page places by its chair, chairPlace: the seat centre at the clip's origin, as room_stand_up's;
    # the whole clip moves along the floor so his seated hips are there, as the seated loops' are once the page centres them)
    # (at the seated end it joins the page's seated pose by: a sit-down's last frame, a stand-up's first)
    c = P[-1, hi] if P[0, hi, 1] > P[-1, hi, 1] else P[0, hi]; v = np.array([-c[0], 0, -c[2]]); par = ts.parent[hi]
    T[:, hi] = T[:, hi] + qrot(qinv(Q[:, par]), np.broadcast_to(v, (F, 3))) / Sc[par]; P, Q, Sc, M = body(T, R)
    print(clip, 'seated hips moved to the origin by (%.3f, %.3f) m' % (v[0], v[2]))
joints = set(v5['skin']['joints']); jn = {vn[j] for j in joints}
out = {'name': an['name'], 'fps': FPS, 'F': F, 'nodes': [{'name': n['name'], 'parent': n['parent'], 't': n['t'], 'r': n['r'], 's': n['s']} for n in rj['nodes']],
       'rot': {i: np.round(R[:, i], 6).ravel().tolist() for i, n in enumerate(ts.names) if n in jn},
       'trans': {hi: np.round(T[:, hi], 6).ravel().tolist()}}
json.dump(out, open(outj, 'w'))
