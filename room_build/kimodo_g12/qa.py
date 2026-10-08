"""Contact QA every 0.1 s: the v5 skin (retargeted clip) against the surfaces the MakeHuman body touches in the same clip.
Both bodies are skinned (linear blend) in the v5 rig's frame (the MakeHuman clip turned 90 deg about Y, as the retarget).
  floor   : lowest v5 sole point (m; < 0 = through the floor)
  slide   : planted feet: ankle drift during each contact (max, m)
  seat    : seated frames: v5 lowest skin under the hips - the chair seat (0.505 m live chair; also vs the MH body's)
  bed     : lying frames: v5 lowest torso/limb skin - the mattress (the MH body's own lowest point there = the clip's mattress)
  hands   : v5 wrist - MH wrist (door handle, window sill, bed push)
python qa.py <json dir> <clip> <retargeted.json> [seat]"""
import json, sys, numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from rt import Skel, qrot, qmul, qy, FPS

jdir, clip, outj = sys.argv[1:4]
SEAT = float(sys.argv[4]) if len(sys.argv) > 4 else 0.505
C = qy(np.pi / 2)


from skinlib import mats, skin_setup, skin, seat_low


# ---- the retargeted v5 clip
v5 = json.load(open(Path(jdir) / 'v5.json')); rj = json.load(open(outj))
ts = Skel(rj)
an = rj['anims'][0]; dur = max(max(c['t']) for c in an['ch'])
tq = np.arange(0, dur + 1e-6, 0.1); F = len(tq)
Fs = int(round(dur * FPS)) + 1
T, R = ts.sample(an, Fs); fi = np.round(tq * FPS).astype(int)
T, R = T[fi], R[fi]
P, Q, Sc = ts.fk(T, R)
M = mats(P, Q, Sc)
# v5's skin joints by name into this file's nodes
vn = [n['name'] for n in v5['nodes']]
J, ibm, V, JI, WW = skin_setup(v5, 5)
Jn = np.array([ts.ix[vn[j]] for j in J])
X = skin(M, Jn, ibm, V, JI, WW)
# which v5 vertices are the soles / the lower body / hands (by dominant joint)
dom = np.array(vn)[J[JI[np.arange(len(JI)), WW.argmax(1)]]]
sole = np.isin(dom, ['L_Foot', 'R_Foot', 'L_ToeBase', 'R_ToeBase'])
seatv = np.isin(dom, ['L_Thigh', 'R_Thigh', 'L_ThighTwist01', 'R_ThighTwist01', 'L_ThighTwist02', 'R_ThighTwist02'])   # trouser seat and thighs (the rigid hoodie hem hangs lower when seated)
torso = ~np.isin(dom, ['L_Foot', 'R_Foot', 'L_ToeBase', 'R_ToeBase', 'L_Calf', 'R_Calf', 'L_CalfTwist01', 'R_CalfTwist01', 'L_CalfTwist02', 'R_CalfTwist02'])

# ---- the MakeHuman body playing the source clip, turned like the retarget
src = json.load(open(Path(jdir) / f'{clip}.json')); mh = json.load(open(Path(jdir) / 'mh_body.json'))
ss = Skel(src); sT, sR = ss.sample(src['anims'][0], Fs); sT, sR = sT[fi], sR[fi]
sP, sQ, sSc = ss.fk(sT, sR)
sP = qrot(C, sP); sQ = qmul(np.broadcast_to(C, sQ.shape), sQ)
sM = mats(sP, sQ, sSc)
mn = [n['name'] for n in mh['nodes']]
mJ, mibm, mV, mJI, mWW = skin_setup(mh, 3)
mh_mesh = mh['mesh'][:1]; mh2 = dict(mh); mh2['mesh'] = mh_mesh
mJ, mibm, mV, mJI, mWW = skin_setup(mh2, 3)
MHB = all(mn[j] in ss.ix for j in mJ)
mJn = np.array([ss.ix[mn[j]] for j in mJ]) if MHB else None
backv = np.isin(dom, ['Hip', 'Pelvis', 'Waist', 'Spine01'])   # what lies on a mattress: the lower back and pelvis (the rigid hood stands out behind the neck)
mdom = np.array(mn)[mJ[mJI[np.arange(len(mJI)), mWW.argmax(1)]]]
mback = np.array([d.startswith(('Hips', 'Spine02', 'spine04', 'Spine01', 'pelvis')) for d in mdom])
Y = skin(sM, mJn, mibm, mV, mJI, mWW) if MHB else None

from skinlib import thigh_radius
_P0, _Q0, _S0 = ts.fk(ts.T[None], ts.R[None]); RTH = thigh_radius(skin(mats(_P0, _Q0, _S0), Jn, ibm, V, JI, WW)[0], _P0[0], ts.ix, dom)
hipsY = sP[:, ss.ix['Hips'], 1]; headY = sP[:, ss.ix['Head'], 1]
seated = (hipsY < 0.68) & (headY > 1.05)
lying = headY < 1.0
rows = []
for f in range(F):
    x, y = X[f], (Y[f] if Y is not None else None)
    row = {'t': round(float(tq[f]), 1), 'floor': float(x[sole, 1].min())}
    hp = sP[f, ss.ix['Hips']]
    if seated[f]:
        lo = seat_low(P[f], ts.ix, RTH)
        row['seat'] = lo - SEAT
        hv = P[f, ts.ix['Hip']]; beh = seatv & (np.linalg.norm(x[:, [0, 2]] - hv[[0, 2]], axis=1) < 0.12)
        row['buttock_sag'] = float(x[beh, 1].min() - SEAT)   # LBS collapse behind the hip joint (artifact, reported)
    if lying[f] and Y is not None:
        row['bed_vs_mh'] = float(x[backv, 1].min() - y[mback, 1].min())
    for s, m in (('L', 'Left'), ('R', 'Right')):
        row[f'hand{s}'] = float(np.linalg.norm(P[f, ts.ix[f'{s}_Hand']] - sP[f, ss.ix[f'{m}Hand']]))
    rows.append(row)
# sliding: ankle drift while the MH ankle is planted (low and still)
slide = 0.0
for s, m in (('L', 'Left'), ('R', 'Right')):
    a = sP[:, ss.ix[f'{m}Foot']]; low = a[:, 1] < a[:, 1].min() + 0.03
    v = np.r_[0, np.linalg.norm(np.diff(a[:, [0, 2]], axis=0), axis=1) / 0.1]; on = low & (v < 0.15)
    b = P[:, ts.ix[f'{s}_Foot']]
    f0 = None
    for f in range(F + 1):
        if f < F and on[f]: f0 = f if f0 is None else f0
        elif f0 is not None:
            if f - f0 >= 3: slide = max(slide, float(np.linalg.norm(b[f0:f, [0, 2]] - b[f0, [0, 2]], axis=1).max()))
            f0 = None
summ = {'clip': clip, 'samples': F, 'floor_min': round(min(r['floor'] for r in rows), 3),
        'slide_max': round(slide, 3),
        'seat_min': round(min([r['seat'] for r in rows if 'seat' in r] or [np.nan]), 3), 'seat_max': round(max([r['seat'] for r in rows if 'seat' in r] or [np.nan]), 3),
        'buttock_sag_min': round(min([r['buttock_sag'] for r in rows if 'buttock_sag' in r] or [np.nan]), 3),
        'bed_vs_mh_min': round(min([r['bed_vs_mh'] for r in rows if 'bed_vs_mh' in r] or [np.nan]), 3),
        'bed_vs_mh_max': round(max([r['bed_vs_mh'] for r in rows if 'bed_vs_mh' in r] or [np.nan]), 3),
        'hand_err_max': round(max(max(r['handL'], r['handR']) for r in rows), 3)}
json.dump({'summary': summ, 'rows': rows}, open(outj.replace('.json', '_qa.json'), 'w'), indent=0)
print(json.dumps(summ))
