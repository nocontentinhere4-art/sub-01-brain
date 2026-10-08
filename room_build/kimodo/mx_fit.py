"""python kimodo/mx_fit.py <char.json> <clip.json> <row.json> <out.json> [report.json]

A Mixamo clip baked for the Mixamo-rigged character (web/room/char_mixamo.glb) and OUR chair: the clip plays on the
character's own skeleton bone for bone (no retarget: the same 65 bones, the same rest rotations), and the fit is
G12's seated fit (kimodo_g12/post.py) on this skeleton, plus the arm clearance this body needs:
  - the hips' translation as char_mixamo.js plays it (into the body's frame, scaled by hip height over the clip's own);
  - seated (hips low, head up), the hip joints (the UpLegs' mean: where v5's Hip joint is, so G12's numbers carry over)
    at seatHipY over the floor and seatForward forward; over the seat and under that height (landing on it, pushing
    off it) the cushion stops them, whatever the blend;
  - the spine tipped forward by pitch degrees (seated);
  - the feet: planted stances locked, and each sole (his skin and the slides) soleUp over the floor, by leg IK;
  - the wrists where the clip's rotations put them on him (carried up and forward with him onto our seat), + handUp
    (the performer's armrests and desk were lower than ours), and moved by keys [forward, up] while the hands are out
    at the keyboard (eased in by reach), by arm IK;
  - the sleeves off the hoodie: the performer's arms hung against a slimmer body. Where a sleeve vertex is more than
    clearMax inside the hoodie (qa.html's test: behind the nearest hoodie vertex's normal, within 2.5 cm), the elbow
    swings out about the shoulder-wrist line (the wrist and the hand stay where they are), and where that is not
    enough (the arm straight) the whole arm swings out from the shoulder; per frame, the least that clears, smoothed;
  - trim [from, to] (s): only that stretch; seatOrigin: moved along the floor so the seated hip joints are at the
    origin (a transition the page places by its chair).
char.json, clip.json: kimodo_g12/exp.mjs (char: ALLMESH=1, its skin and every skinned mesh); row.json: the clip's row
(kimodo/mx_clips.json, defaults merged). out.json: kimodo_g12/writeclip.mjs's input, on the character's nodes."""
import json, sys, os, numpy as np
from pathlib import Path
from scipy.spatial import cKDTree
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "kimodo_g12"))
from rt import Skel, qrot, qmul, qinv, qbetween, qnorm, lowpass, two_bone, FPS
from skinlib import mats

CH, CL, ROW, OUT = sys.argv[1:5]; REP = sys.argv[5] if len(sys.argv) > 5 else None
row = json.load(open(ROW)) if os.path.exists(ROW) else json.loads(ROW)
g = lambda k, d=0.0: row.get(k, d)
strip = lambda n: n.split(":")[-1].replace("mixamorig", "")
cd, kd = json.load(open(CH)), json.load(open(CL))
cs, ks = Skel(cd), Skel(kd)
cix = {strip(n): i for i, n in enumerate(cs.names) if "mixamorig" in n}; kix = {strip(n): i for i, n in enumerate(ks.names) if "mixamorig" in n}
an = kd["anims"][0]; dur = max(max(c["t"]) for c in an["ch"])
t0, t1 = g("trim", [0, dur]); F = int(round((t1 - t0) * FPS)) + 1
kT, kR = ks.sample(an, int(round(t1 * FPS)) + 1); kT, kR = kT[-F:], kR[-F:]
kP, kQ, kSc = ks.fk(kT, kR)


def hip_height(sk, ix):                                       # the hips over the lowest foot joint, at rest
    P, _, _ = sk.fk(sk.T[None], sk.R[None]); P = P[0]
    return P[ix["Hips"], 1] - min(P[ix[n], 1] for n in ("LeftFoot", "RightFoot", "LeftToeBase", "RightToeBase"))


k = hip_height(cs, cix) / hip_height(ks, kix)
# ---- the clip on the character: every bone's local rotation as recorded; the hips in the body's frame, scaled
T = np.repeat(cs.T[None], F, 0); R = np.repeat(cs.R[None], F, 0)
for n, i in cix.items():
    if n in kix: R[:, i] = kR[:, kix[n]]
hi = cix["Hips"]; cpar, kpar = cs.parent[hi], ks.parent[kix["Hips"]]
P0, Q0, S0 = cs.fk(cs.T[None], cs.R[None])                    # the character's hips parent (the 0.01 node) at rest
kHp, kHq = kP[:, kix["Hips"]], kQ[:, kix["Hips"]]             # the clip's hips in its world (metres, the 0.01 node)
body = kHp * k                                                # (char_mixamo.js fixClip: the travel and the height scaled by k)
T[:, hi] = qrot(qinv(np.broadcast_to(Q0[0, cpar], (F, 4))), body - P0[0, cpar]) / S0[cpar]
R[:, hi] = qnorm(qmul(qinv(np.broadcast_to(Q0[0, cpar], (F, 4))), kHq))


def body_fk(T, R):
    P, Q, Sc = cs.fk(T, R); return P, Q, Sc, mats(P, Q, Sc)


P, Q, Sc, M = body_fk(T, R)
# ---- his skin (every skinned mesh: the slides are under his soles) for the soles, the seat and the arm clearance
J = np.array(cd["skin"]["joints"]); IBM = np.array(cd["skin"]["ibm"]).reshape(-1, 4, 4).transpose(0, 2, 1)
VV, JJ, WW, MESH = [], [], [], []
for m in cd["mesh"]:
    p = np.array(m["pos"], float).reshape(-1, 3); j = np.array(m["j"]).reshape(-1, 4); w = np.array(m["w"], float).reshape(-1, 4)
    if w.max() > 1.5: w = w / w.sum(1, keepdims=True)
    VV.append(p); JJ.append(j); WW.append(w); MESH += [m.get("mesh") or ""] * len(p)
V = np.concatenate(VV); JI = np.concatenate(JJ); WI = np.concatenate(WW); MESH = np.array(MESH)
jn = [strip(cs.names[j]) for j in J]; dom = np.array(jn)[JI[np.arange(len(JI)), WI.argmax(1)]]
Vh = np.c_[V, np.ones(len(V))]


def skin_at(M, ids):                                           # (F, 4, 4) node worlds -> his skin at ids (F, n, 3)
    S = M[:, J] @ IBM[None]
    out = np.zeros((M.shape[0], len(ids), 3))
    for c in range(4):
        out += WI[ids, c][None, :, None] * np.einsum("fvij,vj->fvi", S[:, JI[ids, c]], Vh[ids])[..., :3]
    return out


def skin_n(Mf, ids):                                           # one frame, positions and normals (normals from the
    S = (Mf[J] @ IBM)                                          # blended matrices' rotation: qa.html's transformDirection)
    A = np.einsum("vk,vkab->vab", WI[ids], S[JI[ids]])
    x = np.einsum("vab,vb->va", A[:, :3, :], Vh[ids])
    return x, A


sole = np.where(np.isin(dom, ["LeftFoot", "RightFoot", "LeftToeBase", "RightToeBase"]))[0][::3]
side_of = np.array(["L" if d.startswith("Left") else "R" for d in dom[sole]])
# ---- seated (hips low and the head up), by his own heights
# (the seat height is the hip joints': the mean of the two UpLeg joints, where v5's Hip joint is and where G12 measured
# seatHipY on our chair; the Mixamo Hips joint sits about 5 cm higher)
H0 = hip_height(cs, cix); joints = lambda P: (P[:, cix["LeftUpLeg"]] + P[:, cix["RightUpLeg"]]) / 2
hipsY, headY = joints(P)[:, 1], P[:, cix["Head"], 1]
sm = lambda x: np.clip(x, 0, 1) ** 2 * (3 - 2 * np.clip(x, 0, 1))
w_seat = sm((0.78 * H0 - hipsY) / 0.08) * sm((headY - hipsY - 0.40) / 0.1)   # (the hips low, the torso up over them)
SEAT_Y, FWD, PITCH = g("seatHipY", 0.0), g("seatForward", 0.0), np.radians(g("pitch", 0.0))
seated = w_seat > 0.9
sc = joints(P)[seated][:, [0, 2]].mean(0) if seated.any() else None
over_seat = np.zeros(F, bool) if sc is None else np.linalg.norm(joints(P)[:, [0, 2]] - sc, axis=1) < 0.20
rep = {"frames": F, "k_hip": round(float(k), 4), "seated_frames": int(seated.sum())}
# ---- the hips: up to the seat height (the cushion stops them when over it), forward
need = np.zeros(F); hard = np.zeros(F, bool)
for f in range(F):
    if SEAT_Y and over_seat[f] and hipsY[f] < SEAT_Y: need[f] = SEAT_Y - hipsY[f]; hard[f] = True
    elif SEAT_Y and w_seat[f] > 0: need[f] = w_seat[f] * (SEAT_Y - hipsY[f])
pk = np.array([np.where(hard, 0, need)[max(0, f - 8):f + 9].max() for f in range(F)])
need = np.where((need > 0) & ~hard, np.maximum(need, lowpass(pk, 2.0)), need)
need = lowpass(need, 3.0)
shift = np.stack([np.zeros(F), need, FWD * w_seat], -1)       # (the body faces +z)
T[:, hi] += qrot(qinv(np.broadcast_to(Q0[0, cpar], (F, 4))), shift) / S0[cpar]
rep["hip_lift_m"] = [round(float(need.min()), 3), round(float(need.max()), 3)]
if PITCH:                                                     # the spine tipped forward about his left-right axis
    sp = cix["Spine"]; P, Q, Sc, M = body_fk(T, R)
    ax = P[:, cix["LeftUpLeg"]] - P[:, cix["RightUpLeg"]]; ax /= np.linalg.norm(ax, axis=1, keepdims=True)
    a = PITCH * w_seat / 2; dq = np.concatenate([ax * np.sin(a)[:, None], np.cos(a)[:, None]], 1)
    Qn = qmul(dq, Q[:, sp]); R[:, sp] = qnorm(qmul(qinv(Q[:, cs.parent[sp]]), Qn))
P, Q, Sc, M = body_fk(T, R)
def axis_q(ax, ang):
    ax = ax / (np.linalg.norm(ax, axis=-1, keepdims=True) + 1e-12); return np.concatenate([ax * np.sin(ang / 2)[..., None], np.cos(ang / 2)[..., None]], -1)


# ---- the feet: planted stances locked (low and slow, held on the stance's mean), each sole SOLE over the floor
SOLE = g("soleUp", 0.002)
ank0 = {}
for s, S in (("L", "Left"), ("R", "Right")):
    a = P[:, cix[S + "Foot"]].copy(); low = a[:, 1] < a[:, 1].min() + 0.03
    v = np.r_[0, np.linalg.norm(np.diff(a[:, [0, 2]], axis=0), axis=1) * FPS]; on = low & (v < 0.15)
    gl = a.copy(); wmax = np.zeros(F); f0 = None
    for f in range(F + 1):
        if f < F and on[f]: f0 = f if f0 is None else f0
        elif f0 is not None:
            if f - f0 >= 9:
                lock = a[f0:f, [0, 2]].mean(0)
                for kk in range(max(0, f0 - 5), min(F, f + 5)):
                    w = 1.0 if f0 <= kk < f else max(0.0, 1 - (f0 - kk if kk < f0 else kk - f + 1) / 5.0)
                    if w > wmax[kk]: gl[kk, [0, 2]] = a[kk, [0, 2]] * (1 - w) + lock * w; wmax[kk] = w
            f0 = None
    ank0[s] = gl


def ik(T, R, P, Q, Sc, a, b, c, goal):                         # two-bone IK a-b-c onto goal; c keeps its world rotation
    l1 = np.linalg.norm(T[0, b]) * Sc[a]; l2 = np.linalg.norm(T[0, c]) * Sc[b]
    nb, gg = two_bone(P[:, a], P[:, b], P[:, c], goal, l1, l2)
    d1 = qbetween(P[:, b] - P[:, a], nb - P[:, a]); Qa = qmul(d1, Q[:, a]); Qb = qmul(d1, Q[:, b])
    pc = nb + qrot(Qb, Sc[b] * T[:, c]); d2 = qbetween(pc - nb, gg - nb); Qb = qmul(d2, Qb)
    R[:, a] = qnorm(qmul(qinv(Q[:, cs.parent[a]]), Qa)); R[:, b] = qnorm(qmul(qinv(Qa), Qb)); R[:, c] = qnorm(qmul(qinv(Qb), Q[:, c]))


for it in range(2):
    X = np.concatenate([skin_at(M[i:i + 40], sole) for i in range(0, F, 40)])
    for s, S in (("L", "Left"), ("R", "Right")):
        low = X[:, side_of == s, 1].min(1)
        lift = (lowpass(-low + SOLE, 4.0) if it == 0 else -low + SOLE)
        goal = (ank0[s] if it == 0 else P[:, cix[S + "Foot"]].copy()) + np.stack([np.zeros(F), lift if it == 0 else np.maximum(0, lift), np.zeros(F)], -1)
        ik(T, R, P, Q, Sc, cix[S + "UpLeg"], cix[S + "Leg"], cix[S + "Foot"], goal); P, Q, Sc, M = body_fk(T, R)
# the knees up to kneeY (seated): our chair is high for him, and with his feet flat (his shin and ankle reach 0.48 m)
# his thighs slope down through the cushion's front edge; as on a high chair, his heels come up and he rests on the
# balls of his feet (v5's seated clips have his knees at 0.55 m the same way). The heel rises by what the knee lacks,
# the foot turned toes-down about his left-right axis so the ball stays where it was
KNEE = g("kneeY", 0.0)
rep["knees_before_m"] = [round(float(P[w_seat > 0.5, cix[S + "Leg"], 1].mean()), 3) if (w_seat > 0.5).any() else None for S in ("Left", "Right")]
if KNEE:
    # (seated, and while his hips are over the seat and near its height: landing on it and pushing off it his thighs
    # press on its front edge just the same)
    w_knee = np.maximum(w_seat, over_seat * sm((SEAT_Y + 0.12 - joints(P)[:, 1]) / 0.12)) if SEAT_Y else w_seat
    for s, S in (("L", "Left"), ("R", "Right")):
        a, b, c, t = cix[S + "UpLeg"], cix[S + "Leg"], cix[S + "Foot"], cix[S + "ToeBase"]
        raise_ = lowpass(np.maximum(0, KNEE - P[:, b, 1]) * w_knee, 3.0)
        lat = P[:, cix["LeftUpLeg"]] - P[:, cix["RightUpLeg"]]; lat /= np.linalg.norm(lat, axis=1, keepdims=True)
        foot = np.linalg.norm((P[:, t] - P[:, c])[:, [0, 2]], axis=1)                  # (ankle to the ball, across the floor)
        ang = np.arcsin(np.clip(raise_ / np.maximum(foot, 0.05), 0, 0.9))
        Qf = qmul(axis_q(lat, ang), Q[:, c])                                            # (toes down: about +lat, his left)
        ik(T, R, P, Q, Sc, a, b, c, P[:, c] + np.stack([np.zeros(F), raise_, np.zeros(F)], -1)); P, Q, Sc, M = body_fk(T, R)
        R[:, c] = qnorm(qmul(qinv(Q[:, b]), Qf)); P, Q, Sc, M = body_fk(T, R)
        rep.setdefault("heel_raise_cm", {})[s] = round(float(raise_.max()) * 100, 1)
    for s, S in (("L", "Left"), ("R", "Right")):              # (and no sole under the floor after it: lifted where one is)
        X = np.concatenate([skin_at(M[i:i + 40], sole) for i in range(0, F, 40)]); low = X[:, side_of == s, 1].min(1)
        ik(T, R, P, Q, Sc, cix[S + "UpLeg"], cix[S + "Leg"], cix[S + "Foot"], P[:, cix[S + "Foot"]] + np.stack([np.zeros(F), np.maximum(0, SOLE - low), np.zeros(F)], -1))
        P, Q, Sc, M = body_fk(T, R)
X = np.concatenate([skin_at(M[i:i + 40], sole) for i in range(0, F, 40)])
rep["soles_cm"] = {s: [round(float(X[:, side_of == s, 1].min(1).min() * 100), 1), round(float(X[:, side_of == s, 1].min(1).max() * 100), 1)] for s in "LR"}
# ---- the wrists: the performer's (scaled to him) + handUp; at the keyboard, moved by keys
HUP = g("handUp", 0.0); KEYS = g("keys", [0, 0])
for s, S in (("L", "Left"), ("R", "Right")):
    # (his own wrist as the clip's rotations put it, carried with him onto our seat (the performer sat 16-24 cm lower,
    # at his size), then handUp puts it on our furniture: back down onto our armrests, or off his thighs. Not the
    # performer's wrist: his shoulders are not ours, and reaching for it pulled the right arm across the chest)
    goal = P[:, cix[S + "Hand"]] + np.array([0, HUP, 0])
    if KEYS[0] or KEYS[1]:
        reach = goal[:, 2] - P[:, hi, 2]; wk = sm((reach - 0.30) / 0.10)
        goal = goal + np.stack([np.zeros(F), KEYS[1] * wk, KEYS[0] * wk], -1)
    ik(T, R, P, Q, Sc, cix[S + "Arm"], cix[S + "ForeArm"], cix[S + "Hand"], goal); P, Q, Sc, M = body_fk(T, R)
# ---- the sleeves off the hoodie
CLEAR = g("clearMax", 0.008)
NRM = np.concatenate([np.array(m["nrm"], float).reshape(-1, 3) for m in cd["mesh"]])
TOR = np.where(np.isin(dom, ["Hips", "Spine", "Spine1", "Spine2"]))[0][::2]           # (every 2nd, as qa.html)
ARM = {S: np.where(np.isin(dom, [S + "Arm", S + "ForeArm"]))[0][::2] for S in ("Left", "Right")}


def hoodie(Mf):                                                # the hoodie this frame: its skin, normals, a tree (the arm's
    xt, At = skin_n(Mf, TOR); nt = np.einsum("vab,vb->va", At[:, :3, :3], NRM[TOR])   # swing leaves it where it is)
    return xt, nt / (np.linalg.norm(nt, axis=1, keepdims=True) + 1e-12), cKDTree(xt)


def depth(Mf, S, hd=None, where=False):                       # the deepest sleeve vertex inside the hoodie (m), one frame
    xt, nt, tree = hd or hoodie(Mf)
    xa, _ = skin_n(Mf, ARM[S]); d, kk = tree.query(xa, distance_upper_bound=0.025); ok = d < 0.025; kk = np.where(ok, kk, 0)
    dot = np.where(ok, ((xa - xt[kk]) * nt[kk]).sum(1), 0)
    if where == "verts":                                      # (the vertices themselves: bind place, weights, the hoodie's)
        h = np.where(dot < -CLEAR)[0]; o = h[np.argsort(dot[h])][:6]
        wt = lambda v: " ".join(f"{jn[JI[v, c]]}:{WI[v, c]:.2f}" for c in range(4) if WI[v, c] > 0.01)
        return [(round(float(-dot[i]) * 100, 1), V[ARM[S][i]].round(3).tolist(), wt(ARM[S][i]), V[TOR[kk[i]]].round(3).tolist(), wt(TOR[kk[i]])) for i in o]
    if where:                                                 # (which parts: the sleeve's and the hoodie's main bones, and how high)
        h = dot < -CLEAR; from collections import Counter
        return Counter(f"{dom[a]}>{dom[TOR[b]]}@{xa[i, 1]:.1f}" for i, (a, b) in enumerate(zip(ARM[S], kk)) if h[i]).most_common(4)
    return float(max(0.0, -dot.min()))



def swing(T, R, S, sw, ab):
    """The elbow out about the shoulder-wrist line by sw (the wrist stays, the hand keeps its turn), then the whole arm
    out from the shoulder about his forward axis by ab (radians, per frame). T, R: (n, N, ...), changed in place."""
    n = len(T); P, Q, Sc = cs.fk(T, R)
    a, b, c = cix[S + "Arm"], cix[S + "ForeArm"], cix[S + "Hand"]; sg = 1.0 if S == "Left" else -1.0
    up = P[:, cix["Spine2"]] - P[:, hi]; fwd = qrot(Q[:, cix["Spine2"]], np.broadcast_to(np.array([0, 0, 1.0]), (n, 3)))
    out = np.cross(up, fwd) * sg; out /= np.linalg.norm(out, axis=1, keepdims=True)    # (his left is +x facing +z)
    ax = P[:, c] - P[:, a]; ax /= np.linalg.norm(ax, axis=1, keepdims=True)
    dirn = np.sign(np.einsum("fi,fi->f", np.cross(ax, P[:, b] - P[:, a]), out) + 1e-9)  # (the turn that takes the elbow outward)
    hq = Q[:, c].copy()
    R[:, a] = qnorm(qmul(qinv(Q[:, cs.parent[a]]), qmul(axis_q(ax, sw * dirn), Q[:, a])))
    P, Q, Sc = cs.fk(T, R); R[:, c] = qnorm(qmul(qinv(Q[:, b]), hq))
    fwd = qrot(Q[:, cix["Spine2"]], np.broadcast_to(np.array([0, 0, 1.0]), (n, 3)))
    R[:, a] = qnorm(qmul(qinv(Q[:, cs.parent[a]]), qmul(axis_q(fwd, sg * ab), Q[:, a])))
    P, Q, Sc = cs.fk(T, R); return P, Q, Sc, mats(P, Q, Sc)


def both(M):                                                  # the two arms' depth every frame (one hoodie per frame)
    out = {"Left": np.zeros(F), "Right": np.zeros(F)}
    for f in range(F):
        hd = hoodie(M[f])
        for S in out: out[S][f] = depth(M[f], S, hd)
    return out


before = both(M)
rep["arm_in_torso_before_cm"] = {S: round(float(v.max()) * 100, 1) for S, v in before.items()}
if os.environ.get("MX_DIAG"):                                 # (where the sleeves are in the hoodie before the clearance, and stop)
    tips = [cix[f"{S}Hand{f}3"] for S in ("Left", "Right") for f in ("Index", "Middle", "Ring", "Pinky")]; rep["fingertips_mean"] = P[:, tips].mean((0, 1)).round(3).tolist()
    for S, v in before.items():
        for f in list(np.argsort(-v)[:2]) + [F // 2]: print(S, int(f), round(float(v[f]) * 100, 1), depth(M[f], S, where=True))
        if os.environ.get("MX_DIAG") == "verts":
            for x in depth(M[int(v.argmax())], S, where="verts"): print("  ", x)
    print(json.dumps(rep)); sys.exit(0)
STEP = np.radians(2); MAXSW, MAXAB = np.radians(g("swingMax", 30)), np.radians(g("abductMax", 24))
SW = {S: np.zeros(F) for S in ("Left", "Right")}; AB = {S: np.zeros(F) for S in ("Left", "Right")}


def least(f, S, hd):                                          # one frame: the least swing that clears, then abduction;
    best, bd = (0.0, 0.0), 9                                  # none clears: the one that comes closest
    for ab in np.arange(0, MAXAB + 1e-6, STEP):
        for sw in np.arange(0 if ab else STEP, MAXSW + 1e-6, STEP):
            T1, R1 = T0[f:f + 1].copy(), R0[f:f + 1].copy(); M1 = swing(T1, R1, S, np.array([sw]), np.array([ab]))[3]
            d = depth(M1[0], S, hd)
            if d <= CLEAR: return sw, ab
            if d < bd - 0.001: best, bd = (sw, ab), d
            if ab and sw >= STEP * 4: break                   # (with the arm out, the swing past 8 deg adds little)
    return best


T0, R0 = T.copy(), R.copy(); cur = before
for rnd in range(3):                                          # (every 2nd frame that needs it, then any frame still over)
    todo = {S: np.where(cur[S] > CLEAR)[0] for S in SW}
    if not any(len(v) for v in todo.values()): break
    for S in SW:
        fs = todo[S][::2] if rnd == 0 else todo[S]
        for f in fs:
            sw, ab = least(f, S, hoodie(body_fk(T0[f:f + 1], R0[f:f + 1])[3][0]))
            if rnd: sw, ab = max(sw, SW[S][f] + STEP), max(ab, AB[S][f])
            SW[S][f], AB[S][f] = max(SW[S][f], sw), max(AB[S][f], ab)
        for A in (SW, AB):                                    # smoothed, never under what a frame needed (a running max
            pk = np.array([A[S][max(0, f - 6):f + 7].max() for f in range(F)]); A[S] = np.maximum(lowpass(pk, 1.5), A[S])   # over +-0.2 s first)
    T, R = T0.copy(), R0.copy()
    for S in SW: P, Q, Sc, M = swing(T, R, S, SW[S], AB[S])
    cur = both(M)
after = cur
rep["arm_in_torso_after_cm"] = {S: round(float(v.max()) * 100, 1) for S, v in after.items()}
rep["arm_frames_over"] = {S: int((v > CLEAR).sum()) for S, v in after.items()}
rep["arm_worst"] = {S: [int(v.argmax()), depth(M[int(v.argmax())], S, where=True)] for S, v in after.items() if v.max() > CLEAR}
rep["swing_deg"] = {S: round(float(np.degrees(SW[S].max())), 1) for S in SW}; rep["abduct_deg"] = {S: round(float(np.degrees(AB[S].max())), 1) for S in AB}
# ---- placed: the seated hips at the origin (a transition the page places by its chair)
if g("seatOrigin") and seated.any():
    J2 = joints(P); c = J2[-1] if J2[0, 1] > J2[-1, 1] else J2[0]; v = np.array([-c[0], 0, -c[2]])
    T[:, hi] += qrot(qinv(np.broadcast_to(Q0[0, cpar], (F, 4))), np.broadcast_to(v, (F, 3))) / S0[cpar]
    P, Q, Sc, M = body_fk(T, R); rep["origin_shift_m"] = [round(float(v[0]), 3), round(float(v[2]), 3)]
rep["knees_m"] = [round(float(P[w_seat > 0.5, cix[S + "Leg"], 1].mean()), 3) if (w_seat > 0.5).any() else None for S in ("Left", "Right")]
rep["hip_joints_seated_m"] = [round(float(x), 3) for x in joints(P)[seated].mean(0)] if seated.any() else None
# the performer's keyboard point after the fit (the page rolls him and the chair so it lands on the room's keyboard):
# the mean of his last finger joints, both hands, while they are out at the keyboard
tips = [cix[f"{S}Hand{f}3"] for S in ("Left", "Right") for f in ("Index", "Middle", "Ring", "Pinky")]
rep["fingertips_mean"] = [round(float(x), 3) for x in P[:, tips].mean((0, 1))]
names = [n["name"] for n in cd["nodes"]]
out = {"name": an["name"], "fps": FPS, "F": F, "nodes": [{"name": n["name"], "parent": n["parent"], "t": n["t"], "r": n["r"], "s": n["s"]} for n in cd["nodes"]],
       "rot": {int(i): np.round(R[:, i], 6).ravel().tolist() for i in cix.values()}, "trans": {int(hi): np.round(T[:, hi], 5).ravel().tolist()}}
json.dump(out, open(OUT, "w"))
if REP: json.dump(rep, open(REP, "w"), indent=1)
print(json.dumps(rep))
