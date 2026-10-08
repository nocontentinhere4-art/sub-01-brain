"""Retarget the MakeHuman room clips (preview/room-mh web/room/mh/) onto the v5 Tripo rig (41 bones).

World-space transfer: each mapped v5 bone turns in the world as its MakeHuman bone turns from its rest (MakeHuman's rest
is world-aligned), after its rest direction is aligned to the MakeHuman bone's (limbs). v5 faces +X; the clips face +Z,
so the facing turn goes on Root. Then zero-phase smoothing of the rotations and the hips, then IK re-solved on the
result: legs to the recorded ankles (feet planted while in contact: locked to one spot), arms to the recorded wrists, and
the hips set so the skin sits on the chair seat / the mattress where the source sits / lies.
python rt.py <json dir> <clip> <out.json>"""
import json, sys, numpy as np
from pathlib import Path

FPS = 30


# ---------- quaternions (x, y, z, w) ----------
def qmul(a, b):
    ax, ay, az, aw = np.moveaxis(a, -1, 0); bx, by, bz, bw = np.moveaxis(b, -1, 0)
    return np.stack([aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz], -1)


def qinv(q): return q * np.array([-1, -1, -1, 1.0])


def qrot(q, v):
    u = q[..., :3]; w = q[..., 3:4]
    t = 2 * np.cross(u, v)
    return v + w * t + np.cross(u, t)


def qnorm(q): return q / np.linalg.norm(q, axis=-1, keepdims=True)


def qbetween(a, b):
    a = a / np.linalg.norm(a, axis=-1, keepdims=True); b = b / np.linalg.norm(b, axis=-1, keepdims=True)
    c = np.cross(a, b); d = (a * b).sum(-1, keepdims=True)
    q = np.concatenate([c, 1 + d], -1)
    bad = q[..., 3] < 1e-8
    if np.any(bad):   # opposite: any perpendicular axis
        perp = np.cross(a, [1.0, 0, 0]); perp = np.where(np.linalg.norm(perp, axis=-1, keepdims=True) < 1e-6, np.cross(a, [0, 1.0, 0]), perp)
        q = np.where(bad[..., None], np.concatenate([perp, np.zeros_like(d)], -1), q)
    return qnorm(q)


def qslerp(a, b, t):
    d = (a * b).sum(-1, keepdims=True); b = np.where(d < 0, -b, b); d = np.abs(d)
    th = np.arccos(np.clip(d, -1, 1)); s = np.sin(th)
    w1 = np.where(s > 1e-6, np.sin((1 - t) * th) / np.where(s > 1e-6, s, 1), 1 - t)
    w2 = np.where(s > 1e-6, np.sin(t * th) / np.where(s > 1e-6, s, 1), t)
    return qnorm(w1 * a + w2 * b)


def qy(angle): return np.array([0, np.sin(angle / 2), 0, np.cos(angle / 2)])


# ---------- skeletons ----------
class Skel:
    def __init__(self, d):
        self.d = d
        self.names = [n['name'] for n in d['nodes']]
        self.ix = {n: i for i, n in enumerate(self.names)}
        self.parent = np.array([n['parent'] for n in d['nodes']])
        self.T = np.array([n['t'] for n in d['nodes']], float); self.R = np.array([n['r'] for n in d['nodes']], float)
        self.S = np.array([n['s'] for n in d['nodes']], float)
        order, seen = [], set()
        def visit(i):
            if i in seen: return
            if self.parent[i] >= 0: visit(self.parent[i])
            seen.add(i); order.append(i)
        for i in range(len(self.names)): visit(i)
        self.order = order

    def fk(self, T, R):
        """T, R: (F, N, 3/4) local. Uniform scales only. Returns world pos (F,N,3), rot (F,N,4), scale (N,)."""
        F, N = T.shape[:2]
        P = np.zeros((F, N, 3)); Q = np.zeros((F, N, 4)); Sc = np.ones(N)
        for i in self.order:
            p = self.parent[i]
            if p < 0:
                P[:, i] = T[:, i]; Q[:, i] = R[:, i]; Sc[i] = self.S[i, 0]
            else:
                P[:, i] = P[:, p] + Sc[p] * qrot(Q[:, p], T[:, i]); Q[:, i] = qmul(Q[:, p], R[:, i]); Sc[i] = Sc[p] * self.S[i, 0]
        return P, Q, Sc

    def sample(self, anim, F):
        """Local T, R per frame (rest where not animated)."""
        T = np.repeat(self.T[None], F, 0); R = np.repeat(self.R[None], F, 0)
        tt = np.arange(F) / FPS
        for c in anim['ch']:
            t = np.array(c['t']); v = np.array(c['v']).reshape(len(t), -1)
            if c['path'] == 'translation':
                T[:, c['node']] = np.stack([np.interp(tt, t, v[:, k]) for k in range(3)], -1)
            elif c['path'] == 'rotation':
                j = np.clip(np.searchsorted(t, tt) - 1, 0, len(t) - 2) if len(t) > 1 else np.zeros(F, int)
                if len(t) == 1:
                    R[:, c['node']] = v[0]; continue
                a = np.clip((tt - t[j]) / np.maximum(t[j + 1] - t[j], 1e-9), 0, 1)[:, None]
                R[:, c['node']] = qslerp(v[j], v[j + 1], a)
        return T, R


# MakeHuman -> v5 (direction: the child whose direction defines the bone, on each side, for the rest alignment)
MAP = {  # v5: (MH, MH child for direction or None, v5 child for direction or None)
    'Hip': ('Hips', None, None), 'Waist': ('Spine02', None, None), 'Spine01': ('Spine01', None, None),
    'Spine02': ('Spine', None, None), 'NeckTwist01': ('neck', None, None), 'NeckTwist02': ('neck03', None, None), 'Head': ('Head', None, None),
}
for s, m in (('L', 'Left'), ('R', 'Right')):
    MAP.update({f'{s}_Clavicle': (f'{m}Shoulder', f'{m}Arm', f'{s}_Upperarm'), f'{s}_Upperarm': (f'{m}Arm', f'{m}ForeArm', f'{s}_Forearm'),
                f'{s}_Forearm': (f'{m}ForeArm', f'{m}Hand', f'{s}_Hand'),
                f'{s}_Hand': (f'{m}Hand', f'finger3-1.{s}', None),
                f'{s}_Thigh': (f'{m}UpLeg', f'{m}Leg', f'{s}_Calf'), f'{s}_Calf': (f'{m}Leg', f'{m}Foot', f'{s}_Foot'),
                f'{s}_Foot': (f'{m}Foot', f'{m}ToeBase', f'{s}_ToeBase')})


def lowpass(x, fc, axis=0):
    """Zero-phase: a Gaussian kernel run once over the reflected signal (symmetric, so no phase shift)."""
    sig = FPS / (2 * np.pi * fc)
    r = int(np.ceil(3 * sig)); k = np.exp(-0.5 * (np.arange(-r, r + 1) / sig) ** 2); k /= k.sum()
    x = np.moveaxis(x, axis, 0); pad = np.concatenate([x[r:0:-1], x, x[-2:-r - 2:-1]], 0) if len(x) > r + 1 else x
    if len(x) <= r + 1: return np.moveaxis(x, 0, axis)
    out = np.apply_along_axis(lambda v: np.convolve(v, k, 'valid'), 0, pad)
    return np.moveaxis(out, 0, axis)


def two_bone(Pa, Pb, Pc, goal, l1, l2):
    """New knee/elbow position for chain a-b-c reaching goal, keeping the bend plane of the current pose."""
    d = goal - Pa; L = np.linalg.norm(d, axis=-1, keepdims=True)
    L = np.clip(L, abs(l1 - l2) + 1e-4, (l1 + l2) * 0.9995); dn = d / np.linalg.norm(d, axis=-1, keepdims=True)
    goal = Pa + dn * L
    pole = Pb - Pa; pole = pole - (pole * dn).sum(-1, keepdims=True) * dn
    pn = np.linalg.norm(pole, axis=-1, keepdims=True); pole = pole / np.maximum(pn, 1e-9)
    a = (l1 ** 2 + L ** 2 - l2 ** 2) / (2 * L)
    h = np.sqrt(np.maximum(l1 ** 2 - a ** 2, 0))
    return Pa + dn * a + pole * h, goal


G = qy(-np.pi / 2)        # v5 faces +X; the clips face +Z


def retarget(jdir, clip, smooth_hz=6.0, arm_ik=True, verbose=True):
    src = json.load(open(Path(jdir) / f'{clip}.json')); tgt = json.load(open(Path(jdir) / 'v5.json'))
    ss, ts = Skel(src), Skel(tgt)
    anim = src['anims'][0]
    dur = max(max(c['t']) for c in anim['ch']); F = int(round(dur * FPS)) + 1
    sT, sR = ss.sample(anim, F)
    Ps, Qs, _ = ss.fk(sT, sR)
    Ps0, Qs0, _ = ss.fk(ss.T[None], ss.R[None]); Ps0, Qs0 = Ps0[0], Qs0[0]
    # target rest with the facing turn on Root
    ri = ts.ix['Root']
    tT0, tR0 = ts.T.copy(), ts.R.copy()
    tR0[ri] = qmul(G, tR0[ri]); tT0[ri] = qrot(G, tT0[ri])
    Pt0, Qt0, Sc = ts.fk(tT0[None], tR0[None]); Pt0, Qt0 = Pt0[0], Qt0[0]
    si, ti = ss.ix, ts.ix
    # per mapped bone: the rest alignment C and the target's world rotation over time
    W = {}; Cs = {}
    for tb, (sb, sc_, tc) in MAP.items():
        D = qmul(Qs[:, si[sb]], qinv(Qs0[si[sb]]))
        C = np.array([0, 0, 0, 1.0])
        if sc_:
            sd = Ps0[si[sc_]] - Ps0[si[sb]]
            td = Pt0[ti[tc]] - Pt0[ti[tb]] if tc else qrot(Qt0[ti[tb]], np.array([0, 1.0, 0]))
            C = qbetween(td, sd)
        if tb[2:] in ('Upperarm', 'Forearm', 'Hand'):
            # the arm's twist: v5's rest palms face the thighs with the thumbs forward (+Z here); MakeHuman's rest thumb
            # points elsewhere. Turn about the (aligned) bone so the rest thumb directions match.
            m = 'Left' if tb[0] == 'L' else 'Right'
            ax = sd / np.linalg.norm(sd)
            th_s = Ps0[si[f'finger1-1.{tb[0]}']] - Ps0[si[f'{m}Hand']]
            th_t = qrot(C, np.array([0, 0, 1.0]))
            pr = lambda v: (v - (v @ ax) * ax) / np.linalg.norm(v - (v @ ax) * ax)
            C = qmul(qbetween(pr(th_t), pr(th_s)), C)
        Cs[tb] = C
        W[tb] = qnorm(qmul(D, qmul(np.broadcast_to(C, D.shape), np.broadcast_to(Qt0[ti[tb]], D.shape))))
    # local rotations through the v5 hierarchy
    T = np.repeat(tT0[None], F, 0); R = np.repeat(tR0[None], F, 0)

    def locals_from_world(R, W):
        Qw = np.zeros((F, len(ts.names), 4))
        for i in ts.order:
            p = ts.parent[i]; n = ts.names[i]
            if n in W and p >= 0: R[:, i] = qnorm(qmul(qinv(Qw[:, p]), W[n]))
            Qw[:, i] = R[:, i] if p < 0 else qmul(Qw[:, p], R[:, i])
        return R
    R = locals_from_world(R, W)
    # hips: the recorded path, the height scaled by the hip heights at rest, the rest offset turned with the hips
    hs, ht = si['Hips'], ti['Hip']
    k = Pt0[ht, 1] / Ps0[hs, 1]
    off = Pt0[ht] - Ps0[hs]; off[1] = 0
    Dh = qmul(Qs[:, hs], qinv(Qs0[hs]))
    goal = Ps[:, hs] + qrot(Dh, np.broadcast_to(off, (F, 3))); goal[:, 1] = Ps[:, hs, 1] * k
    Proot = Pt0[ri]; Qroot = Qt0[ri]
    T[:, ht] = qrot(qinv(Qroot), (goal - Proot) / Sc[ri])
    # zero-phase smoothing of every animated local rotation and the hips' path
    if smooth_hz:
        for i in range(len(ts.names)):
            q = R[:, i].copy()
            for f in range(1, F):
                if (q[f] * q[f - 1]).sum() < 0: q[f] = -q[f]
            R[:, i] = qnorm(lowpass(q, smooth_hz))
        T[:, ht] = lowpass(T[:, ht], smooth_hz)
    info = {'F': F, 'dur': dur, 'k': k}
    return dict(ss=ss, ts=ts, sT=sT, sR=sR, Ps=Ps, Qs=Qs, Ps0=Ps0, Qs0=Qs0, Pt0=Pt0, Qt0=Qt0, T=T, R=R, Sc=Sc, info=info, name=anim['name'])


def solve_ik(r, arm_ik=True, plant=True, belt=None):
    """belt: the ground's velocity in the clip's frame for an in-place loop (the page moves him), m/s"""
    ss, ts, Ps, Qs, Ps0, Pt0, T, R = r['ss'], r['ts'], r['Ps'], r['Qs'], r['Ps0'], r['Pt0'], r['T'], r['R']
    si, ti = ss.ix, ts.ix; F = T.shape[0]
    P, Q, Sc = ts.fk(T, R)
    contacts = {}
    chains = [('L', 'Left', 'leg'), ('R', 'Right', 'leg')] + ([('L', 'Left', 'arm'), ('R', 'Right', 'arm')] if arm_ik else [])
    for s, m, kind in chains:
        a, b, c = (f'{s}_Thigh', f'{s}_Calf', f'{s}_Foot') if kind == 'leg' else (f'{s}_Upperarm', f'{s}_Forearm', f'{s}_Hand')
        sc_ = f'{m}Foot' if kind == 'leg' else f'{m}Hand'
        ia, ib, ic = ti[a], ti[b], ti[c]
        l1 = np.linalg.norm(Pt0[ib] - Pt0[ia]); l2 = np.linalg.norm(Pt0[ic] - Pt0[ib])
        goal = Ps[:, si[sc_]].copy()
        if kind == 'leg':
            # the ankle's rest offset (hip width, ankle height), turned with the foot
            off = Pt0[ic] - Ps0[si[sc_]]
            Df = qmul(Qs[:, si[sc_]], qinv(r['Qs0'][si[sc_]]))
            yaw = np.arctan2(qrot(Df, np.array([0, 0, 1.0]))[:, 0], qrot(Df, np.array([0, 0, 1.0]))[:, 2])
            offr = np.stack([off[0] * np.cos(yaw) + off[2] * np.sin(yaw), np.full(F, off[1]), -off[0] * np.sin(yaw) + off[2] * np.cos(yaw)], -1)
            goal = goal + offr
            goal = lowpass(goal, 6.0)
            if plant:   # in contact: low and still -> one spot for the whole contact
                toe = Ps[:, si[f'{m}ToeBase']]
                h = np.minimum(Ps[:, si[sc_], 1] - Ps0[si[sc_], 1], toe[:, 1] - Ps0[si[f'{m}ToeBase'], 1])
                tt = (np.arange(F) / FPS)[:, None]
                bv = np.zeros(3) if belt is None else np.asarray(belt, float)
                goal = goal - bv * tt                      # into the ground's frame
                v = np.r_[0, np.linalg.norm(np.diff(goal[:, [0, 2]], axis=0), axis=1) * FPS]
                on = (h < 0.045) & (v < 0.3)
                # runs of at least 4 frames
                segs, f0 = [], None
                for f in range(F + 1):
                    if f < F and on[f]:
                        f0 = f if f0 is None else f0
                    elif f0 is not None:
                        if f - f0 >= 4: segs.append((f0, f))
                        f0 = None
                g2 = goal.copy(); wsum = np.zeros(F)
                for f0, f1 in segs:
                    lock = goal[f0:f1].mean(0)
                    for f in range(max(0, f0 - 4), min(F, f1 + 4)):
                        w = 1.0 if f0 <= f < f1 else max(0.0, 1 - (f0 - f if f < f0 else f - f1 + 1) / 5)
                        g2[f] = g2[f] * (1 - w) + lock * w if w > wsum[f] else g2[f]; wsum[f] = max(wsum[f], w)
                goal = g2 + bv * tt; contacts[s] = segs
        newb, g = two_bone(P[:, ia], P[:, ib], P[:, ic], goal, l1, l2)
        # rotate the upper bone, then the lower, to the new joint positions; the end bone keeps its world rotation
        d1 = qbetween(P[:, ib] - P[:, ia], newb - P[:, ia])
        Qa = qmul(d1, Q[:, ia]); Qb = qmul(d1, Q[:, ib])
        pc = newb + qrot(Qb, Sc[ib] * T[:, ic])          # where the end joint lands after the first turn
        d2 = qbetween(pc - newb, g - newb)
        Qb = qmul(d2, Qb)
        Qc_world = Q[:, ic]
        pa_par = ts.parent[ia]
        R[:, ia] = qnorm(qmul(qinv(Q[:, pa_par]), Qa)); R[:, ib] = qnorm(qmul(qinv(Qa), Qb))
        R[:, ic] = qnorm(qmul(qinv(Qb), Qc_world))
        P, Q, Sc = ts.fk(T, R)
    r['contacts'] = contacts
    return r


ANIMATED_T = ('Root', 'Hip')


def export(r, path):
    ts, T, R = r['ts'], r['T'], r['R']
    joints = set(ts.d['skin']['joints'])
    out = {'name': r['name'], 'fps': FPS, 'F': int(T.shape[0]),
           'nodes': [{'name': n['name'], 'parent': n['parent'], 't': n['t'], 'r': n['r'], 's': n['s']} for n in ts.d['nodes'] if not n['name'].startswith('tripo_')],
           'rot': {}, 'trans': {}}
    keep = [i for i, n in enumerate(ts.d['nodes']) if not n['name'].startswith('tripo_')]
    remap = {o: k for k, o in enumerate(keep)}
    for n in out['nodes']: n['parent'] = remap.get(n['parent'], -1)
    for i in keep:
        if i in joints: out['rot'][remap[i]] = np.round(R[:, i], 6).ravel().tolist()
        if ts.names[i] in ANIMATED_T: out['trans'][remap[i]] = np.round(T[:, i], 6).ravel().tolist()
    json.dump(out, open(path, 'w'))


if __name__ == '__main__':
    jdir, clip, outp = sys.argv[1:4]
    r = retarget(jdir, clip); r = solve_ik(r, arm_ik=True, belt=(0, 0, -0.67) if clip == 'room_walk' else None)
    export(r, outp); print(clip, r['info'], {k: len(v) for k, v in r['contacts'].items()})
