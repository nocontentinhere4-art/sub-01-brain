"""python3 rig/autorig/fit.py <extract dir> <ref.json> <out dir>

The character (extract.mjs: its bind-space mesh and its own 79-joint skin) put on the Mixamo Standard Skeleton
(refskel.mjs: 65 bones, T-pose), without mixamo.com:

1. T-pose. The character's own skin poses it: each arm, hand, finger and leg is swung (and the hand rolled, its roll
   spread down the forearm's twist bones) until it points where the Mixamo T-pose points it. Then baked.
2. Joints. Mixamo's bones placed on the posed character's joints (its skeleton where it has the joint, the mesh where it
   does not: the ankles, the toes, the finger and thumb tips, the top of the head; the finger joints re-centred in the
   finger's own cross-section). Each bone keeps the Mixamo T-pose's world rotation, so a Mixamo clip's local rotations
   give the same world rotations as on Mixamo's own skeleton: the clips play by bone name.
3. Weights. Distance to each bone segment (inverse 4th power), only among the bones the character's own skin already
   gives that part of the body and their neighbours (no arm vertex bound to the ribs), blended with the old skin moved
   onto the new bones, then smoothed over the surface (welded across the head / body / slides seams), 4 per vertex.

Out: mesh.npz (per primitive: T-posed positions, normals, joints, weights) and skel.json (bones: name, parent, world
position in metres, world rotation, from the reference). Work space: metres, y up, feet on y = 0, facing +z.
"""
import json, sys, numpy as np
from scipy.sparse import coo_matrix, diags
from scipy.spatial import cKDTree

EXT, REF, OUT = sys.argv[1:4]
# ---------------------------------------------------------------------------------------------------------- inputs
rig = json.load(open(f"{EXT}/rig.json"))
# bind space -> metres: the size the character is drawn at (extract.mjs: through its armature's scale; v5 0.8508, 1.73 m
# in the page with the slides, as on main). It was 0.875 here (1.75 m without the slides, static.mjs's), which made
# the Mixamo character 1.78 m: 5 cm taller than the v5 the room's chair and desk fits were made for
K = rig.get("worldScale") or 0.875
JN = [j["name"] for j in rig["joints"]]; JI = {n: i for i, n in enumerate(JN)}
JP = [j["parent"] for j in rig["joints"]]
Rw = np.array([[0, 0, -1], [0, 1, 0], [1, 0, 0]], float)      # -90 deg about y: +x (his front in v5) -> +z


def to_ws(p):                                                  # bind space -> work space
    return (p * K) @ Rw.T


P, N, Jo, Wo, F = [], [], [], [], []
for pr in rig["prims"]:
    f = f"{EXT}/{pr['file']}"
    T = np.array(pr["toBind"]).reshape(4, 4).T
    pos = np.fromfile(f + ".pos", np.float32).reshape(-1, 3).astype(float)
    nrm = np.fromfile(f + ".nrm", np.float32).reshape(-1, 3).astype(float)
    pos = pos @ T[:3, :3].T + T[:3, 3]; nrm = nrm @ np.linalg.inv(T[:3, :3])
    P.append(to_ws(pos)); N.append(nrm @ Rw.T)
    Jo.append(np.fromfile(f + ".jnt", np.uint16).reshape(-1, 4).astype(int))
    Wo.append(np.fromfile(f + ".wgt", np.float32).reshape(-1, 4).astype(float))
    F.append(np.fromfile(f + ".idx", np.uint32).reshape(-1, 3).astype(int))
cnt = [len(p) for p in P]; off = np.cumsum([0] + cnt)
V = np.concatenate(P); NV = np.concatenate(N); JO = np.concatenate(Jo); WO = np.concatenate(Wo)
FA = np.concatenate([f + o for f, o in zip(F, off[:-1])])
floor = V[:, 1].min(); V[:, 1] -= floor
J = np.array([to_ws(np.array(j["bind"]).reshape(4, 4).T[:3, 3]) for j in rig["joints"]]); J[:, 1] -= floor
WO = WO / WO.sum(1, keepdims=True)
dom = JO[np.arange(len(JO)), WO.argmax(1)]                       # each vertex's main old joint

ref = json.load(open(REF)); RN = [b["name"] for b in ref]; RI = {n: i for i, n in enumerate(RN)}
RP = np.array([b["p"] for b in ref]) / 100.0; RQ = np.array([b["q"] for b in ref])
rpar = [RI.get(b["parent"], -1) if b["parent"] else -1 for b in ref]
mx = lambda n: "mixamorig:" + n
rdir = lambda a, b: (RP[RI[mx(b)]] - RP[RI[mx(a)]]) / np.linalg.norm(RP[RI[mx(b)]] - RP[RI[mx(a)]])


# ------------------------------------------------------------------------------------------------- small helpers
def unit(v): return v / np.linalg.norm(v)


def rot_between(a, b):                                         # the smallest rotation taking direction a to b
    a, b = unit(a), unit(b); v = np.cross(a, b); c = float(a @ b)
    if np.linalg.norm(v) < 1e-9: return np.eye(3) if c > 0 else axis_angle(unit(np.cross(a, [1, 0, 0]) + 1e-9), np.pi)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx / (1 + c)


def axis_angle(ax, t):
    ax = unit(ax); x, y, z = ax; c, s = np.cos(t), np.sin(t); C = 1 - c
    return np.array([[c + x * x * C, x * y * C - z * s, x * z * C + y * s], [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
                     [z * x * C - y * s, z * y * C + x * s, c + z * z * C]])


def signed_angle(a, b, ax):                                    # a -> b about ax (both projected off ax)
    ax = unit(ax); a = unit(a - (a @ ax) * ax); b = unit(b - (b @ ax) * ax)
    return float(np.arctan2(np.cross(a, b) @ ax, a @ b))


def quat_to_mat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def verts_of(*names, w=0.5):                                   # the vertices mostly on these old joints
    ids = [JI[n] for n in names]
    m = np.zeros(len(V), bool)
    for k in range(4): m |= np.isin(JO[:, k], ids) & (WO[:, k] >= w)
    return m


# ------------------------------------------------------------------------------- 0. the ankles from the mesh
# v5's Foot joints sit on the sole (y ~ 0). The ankle: the lower leg's cross-section centre at Mixamo's ankle height
# (as a fraction of the hip joint's height).
ank_frac = RP[RI[mx("LeftFoot")], 1] / RP[RI[mx("LeftUpLeg")], 1]
ANK = {}
for s in "LR":
    leg = verts_of(f"{s}_CalfTwist02", f"{s}_Foot", f"{s}_CalfTwist01", w=0.3)
    h = J[JI[f"{s}_Thigh"], 1] * ank_frac
    sl = leg & (np.abs(V[:, 1] - h) < 0.006)
    ANK[s] = np.array([V[sl, 0].mean(), h, V[sl, 2].mean()])

# ------------------------------------------------------------------------------------------- 1. the T-pose
# World rotation D[j] per old joint (inherited down the tree); the posed joint p'[j] = p'[par] + D[par] (p[j] - p[par])
D = [np.eye(3) for _ in JN]; Pp = J.copy()
ALIGN = {}                                   # old joint -> (old child point fn, Mixamo target direction)
for s, S in (("L", "Left"), ("R", "Right")):
    ALIGN[f"{s}_Upperarm"] = (lambda P_, s=s: P_[JI[f"{s}_Forearm"]], rdir(f"{S}Arm", f"{S}ForeArm"))
    ALIGN[f"{s}_Forearm"] = (lambda P_, s=s: P_[JI[f"{s}_Hand"]], rdir(f"{S}ForeArm", f"{S}Hand"))
    ALIGN[f"{s}_Thigh"] = (lambda P_, s=s: P_[JI[f"{s}_Calf"]], rdir(f"{S}UpLeg", f"{S}Leg"))
    for f, F_ in ((1, "Thumb"), (2, "Index"), (3, "Middle"), (4, "Ring"), (5, "Pinky")):
        for k in (1, 2):
            ALIGN[f"finger{f}-{k}.{s}"] = (lambda P_, f=f, k=k, s=s: P_[JI[f"finger{f}-{k + 1}.{s}"]], rdir(f"{S}Hand{F_}{k}", f"{S}Hand{F_}{k + 1}"))
        ALIGN[f"finger{f}-3.{s}"] = (None, rdir(f"{S}Hand{F_}3", f"{S}Hand{F_}4"))   # (no child: its own direction, from the one before)
    ALIGN[f"metacarpal1.{s}"] = ALIGN[f"metacarpal2.{s}"] = ALIGN[f"metacarpal3.{s}"] = ALIGN[f"metacarpal4.{s}"] = None
# the calf: to the mesh's ankle
CALF_T = {s: rdir(f"{S}Leg", f"{S}Foot") for s, S in (("L", "Left"), ("R", "Right"))}
TWIST = {}
order = list(range(len(JN)))                                   # (the joints are listed parents first)
assert all(JP[i] < i for i in order)
seg_dir = {}                                                   # a childless finger tip: the direction it was posed at
for i in order:
    n, p = JN[i], JP[i]
    if p >= 0:
        D[i] = D[p].copy(); Pp[i] = Pp[p] + D[p] @ (J[i] - J[p])
    if n.endswith("_Calf"):
        s = n[0]; d = D[i] @ (ANK[s] - J[i]); D[i] = rot_between(d, CALF_T[s]) @ D[i]
    elif n.endswith("_Hand"):
        # the hand: to the middle finger's knuckle, and rolled so the knuckles run across as Mixamo's do (palm down)
        s, S = n[0], "Left" if n[0] == "L" else "Right"
        a = D[i] @ (J[JI[f"finger3-1.{s}"]] - J[i]); R1 = rot_between(a, rdir(f"{S}Hand", f"{S}HandMiddle1"))
        ax = rdir(f"{S}Hand", f"{S}HandMiddle1")
        acr = R1 @ D[i] @ (J[JI[f"finger2-1.{s}"]] - J[JI[f"finger5-1.{s}"]])
        racr = RP[RI[mx(f"{S}HandIndex1")]] - RP[RI[mx(f"{S}HandPinky1")]]
        t = signed_angle(acr, racr, ax); TWIST[s] = t
        D[i] = axis_angle(ax, t) @ R1 @ D[i]
    elif n in ALIGN and ALIGN[n]:
        fn, tgt = ALIGN[n]
        if fn is None:
            par_dir = seg_dir.get(JN[p]); d = par_dir if par_dir is not None else tgt
        else:
            d = D[i] @ (fn(J) - J[i])
        R = rot_between(d, tgt); D[i] = R @ D[i]
        seg_dir[n] = R @ d
# the hand's roll spread down the forearm (its twist bones carry it: 15 % at the elbow, 55 % mid-forearm)
for s in "LR":
    ax = unit(Pp[JI[f"{s}_Hand"]] - Pp[JI[f"{s}_Forearm"]]); fa = D[JI[f"{s}_Forearm"]]
    for n_, k in ((f"{s}_ForearmTwist01", 0.15), (f"{s}_ForearmTwist02", 0.55)):
        D[JI[n_]] = axis_angle(ax, TWIST[s] * k) @ fa
# the hand's descendants were posed from the hand's own D (they were visited after it); recompute positions
for i in order:
    if JP[i] >= 0: Pp[i] = Pp[JP[i]] + D[JP[i]] @ (J[i] - J[JP[i]])
# skin it: v' = sum_j w_j (D_j (v - p_j) + p'_j)
Vt = np.zeros_like(V); Nt = np.zeros_like(NV)
for k in range(4):
    j = JO[:, k]; w = WO[:, k:k + 1]
    Dj = np.stack(D)[j]
    Vt += w * (np.einsum("nab,nb->na", Dj, V - J[j]) + Pp[j]); Nt += w * np.einsum("nab,nb->na", Dj, NV)
Nt /= np.linalg.norm(Nt, axis=1, keepdims=True) + 1e-12
ANKp = {s: Pp[JI[f"{s}_Calf"]] + D[JI[f"{s}_Calf"]] @ (ANK[s] - J[JI[f"{s}_Calf"]]) for s in "LR"}
lift = Vt[:, 1].min(); Vt[:, 1] -= lift; Pp[:, 1] -= lift                 # (straightened legs: the soles back on y = 0)
for s in "LR": ANKp[s][1] -= lift
domW = dom                                                      # (main old joint per vertex, for the regions)


# -------------------------------------------------------------------------------------------- 2. the joints
def cross_centre(pt, axis, mask, half=0.004):                   # the mesh's centre in a thin slab across axis at pt
    d = (Vt[mask] - pt) @ axis; sel = np.abs(d) < half
    if sel.sum() < 6: return pt
    c = Vt[mask][sel].mean(0); return c - ((c - pt) @ axis) * axis     # (moved only across the axis)


def tip(base, axis, mask):                                      # the furthest skin along axis from base, on the axis
    d = (Vt[mask] - base) @ axis
    return base + axis * max(d.max(), 0.005) if mask.any() else base + axis * 0.02


M = {}                                                          # Mixamo name -> work-space position
SHIFT = {}
CENTRE = cross_centre if not __import__("os").environ.get("NOCENTRE") else (lambda pt, ax, m: pt)
M["Hips"] = Pp[JI["Hip"]]
nk = Pp[JI["NeckTwist01"]]; hp = M["Hips"]
M["Spine"] = Pp[JI["Spine01"]]; M["Spine2"] = Pp[JI["Spine02"]]
M["Spine1"] = (M["Spine"] + M["Spine2"]) / 2
M["Neck"] = nk; M["Head"] = Pp[JI["Head"]]
head = domW == JI["Head"]
M["HeadTop_End"] = np.array([M["Head"][0], Vt[head, 1].max(), M["Head"][2]])
for s, S in (("L", "Left"), ("R", "Right")):
    M[f"{S}Shoulder"] = Pp[JI[f"{s}_Clavicle"]]; M[f"{S}Arm"] = Pp[JI[f"{s}_Upperarm"]]
    M[f"{S}ForeArm"] = Pp[JI[f"{s}_Forearm"]]; M[f"{S}Hand"] = Pp[JI[f"{s}_Hand"]]
    hand_ids = [f"{s}_Hand"] + [f"metacarpal{k}.{s}" for k in range(1, 5)] + [f"finger{f}-{k}.{s}" for f in range(1, 6) for k in range(1, 4)]
    for f, F_ in ((1, "Thumb"), (2, "Index"), (3, "Middle"), (4, "Ring"), (5, "Pinky")):
        fm = verts_of(*[f"finger{f}-{k}.{s}" for k in (1, 2, 3)], w=0.4)
        last = verts_of(f"finger{f}-3.{s}", w=0.4)
        for k in (1, 2, 3):
            pt = Pp[JI[f"finger{f}-{k}.{s}"]]
            ax = unit(Pp[JI[f"finger{f}-{k + 1}.{s}"]] - pt) if k < 3 else unit(pt - Pp[JI[f"finger{f}-2.{s}"]])
            # (the knuckles and the whole thumb keep v5's joints: a slab there cuts the palm, not the finger)
            M[f"{S}Hand{F_}{k}"] = CENTRE(pt, ax, fm) if k > 1 and f > 1 else pt
            SHIFT[f"{S}Hand{F_}{k}"] = round(float(np.linalg.norm(M[f"{S}Hand{F_}{k}"] - pt)) * 1000, 1)
            _ = cross_centre(pt, ax, fm) if k > 1 or f == 1 else cross_centre(pt, ax, fm | verts_of(f"metacarpal{f - 1}.{s}", w=0.4))
        ax = unit(M[f"{S}Hand{F_}3"] - M[f"{S}Hand{F_}2"])
        M[f"{S}Hand{F_}4"] = tip(M[f"{S}Hand{F_}3"], ax, last)
    M[f"{S}UpLeg"] = Pp[JI[f"{s}_Thigh"]]; M[f"{S}Leg"] = Pp[JI[f"{s}_Calf"]]; M[f"{S}Foot"] = ANKp[s]
    foot = np.isin(domW, [JI[f"{s}_Foot"], JI[f"{s}_ToeBase"]])
    zt = Vt[foot, 2].max()
    toe = np.array([M[f"{S}Foot"][0], 0, 0])
    r = RP[RI[mx(f"{S}ToeBase")]] - RP[RI[mx(f"{S}Foot")]]; re = RP[RI[mx(f"{S}Toe_End")]] - RP[RI[mx(f"{S}Foot")]]
    frac = r[2] / re[2]                                         # the ball of the foot, as far along as Mixamo's
    tb = M[f"{S}Foot"] + (zt - 0.01 - M[f"{S}Foot"][2]) * frac * np.array([0, 0, 1])
    near = foot & (np.abs(Vt[:, 2] - tb[2]) < 0.006)
    tb[0] = Vt[near, 0].mean(); tb[1] = 0.35 * (Vt[near, 1].max() - Vt[near, 1].min()) + Vt[near, 1].min()
    M[f"{S}ToeBase"] = tb
    te = tb.copy(); te[2] = zt - 0.01; nt = foot & (Vt[:, 2] > zt - 0.02); te[0] = Vt[nt, 0].mean()
    M[f"{S}Toe_End"] = te
# where a joint's place is a convention rather than anatomy, Mixamo's direction from the joint it hangs off decides it
# (the clips rotate these offsets; a 40 deg different hips-to-thigh offset tips the legs' roots)
def snap(child, frm, L=None):                                   # move frm so frm -> child runs as Mixamo's
    d = rdir(frm, child); L = np.linalg.norm(M[child] - M[frm]) if L is None else L; M[frm] = M[child] - d * L
def snap_end(frm, child):                                       # move child so frm -> child runs as Mixamo's
    d = rdir(frm, child); M[child] = M[frm] + d * np.linalg.norm(M[child] - M[frm])
# the hips over the hip joints and the spine up to the neck in Mixamo's proportions (v5's spine joints were Tripo's
# guesses): Mixamo's chain scaled by the hip joints' height, then sheared so it ends on our neck
kh = (M["LeftUpLeg"][1] + M["RightUpLeg"][1]) / (RP[RI[mx("LeftUpLeg")], 1] + RP[RI[mx("RightUpLeg")], 1])
mid = (M["LeftUpLeg"] + M["RightUpLeg"]) / 2; rmid = (RP[RI[mx("LeftUpLeg")]] + RP[RI[mx("RightUpLeg")]]) / 2
M["Hips"] = mid + (RP[RI[mx("Hips")]] - rmid) * kh
rh = RP[RI[mx("Hips")]]; ky = (M["Neck"][1] - M["Hips"][1]) / (RP[RI[mx("Neck")], 1] - rh[1])
pred = lambda n: M["Hips"] + (RP[RI[mx(n)]] - rh) * ky
miss = M["Neck"] - pred("Neck")
for n in ("Spine", "Spine1", "Spine2"):
    M[n] = pred(n) + miss * (RP[RI[mx(n)], 1] - rh[1]) / (RP[RI[mx("Neck")], 1] - rh[1])
for S in ("Left", "Right"):
    snap(f"{S}Arm", f"{S}Shoulder")
snap("Head", "Neck"); snap_end("Head", "HeadTop_End")
for S in ("Left", "Right"):
    f, tb, te = M[f"{S}Foot"], M[f"{S}ToeBase"], M[f"{S}Toe_End"]
    d = rdir(f"{S}Foot", f"{S}ToeBase"); M[f"{S}ToeBase"] = f + d * ((tb[2] - f[2]) / d[2])
    d = rdir(f"{S}ToeBase", f"{S}Toe_End"); M[f"{S}Toe_End"] = M[f"{S}ToeBase"] + d * ((te[2] - M[f"{S}ToeBase"][2]) / d[2])
for k in M: assert np.all(np.isfinite(M[k])), k
assert set(mx(k) for k in M) == set(RN), set(RN) ^ set(mx(k) for k in M)

# -------------------------------------------------------------------------------------------- 3. the weights
NB = len(RN); par = rpar
kids = {i: [c for c in range(NB) if par[c] == i] for i in range(NB)}
END = {i for i in range(NB) if not kids[i]}                     # the end bones (tips): no weight, as Mixamo's
BP = np.array([M[n[len("mixamorig:"):]] for n in RN])


def seg_end(i):                                                 # a bone's segment: to its (main) child
    n = RN[i][len("mixamorig:"):]
    pick = {"Hips": "Spine", "Spine2": "Neck"}
    for side in ("Left", "Right"):
        pick[side + "Hand"] = side + "HandMiddle1"
    c = pick.get(n)
    if c: return BP[RI[mx(c)]]
    if kids[i]: return BP[kids[i][0]]
    return BP[i]


SA = BP.copy(); SB = np.array([seg_end(i) for i in range(NB)])
SA[RI[mx("Hips")]] = (BP[RI[mx("LeftUpLeg")]] + BP[RI[mx("RightUpLeg")]]) / 2   # the hips: from between the hip joints

# the old skin on the new bones
OLD2NEW = {"Root": "Hips", "Hip": "Hips", "Pelvis": "Hips", "Waist": "Hips", "Spine01": "Spine", "Spine02": "Spine2",
           "NeckTwist01": "Neck", "NeckTwist02": "Neck", "Head": "Head"}
for s, S in (("L", "Left"), ("R", "Right")):
    OLD2NEW.update({f"{s}_Clavicle": f"{S}Shoulder", f"{s}_Upperarm": f"{S}Arm", f"{s}_UpperarmTwist01": f"{S}Arm", f"{s}_UpperarmTwist02": f"{S}Arm",
                    f"{s}_Forearm": f"{S}ForeArm", f"{s}_ForearmTwist01": f"{S}ForeArm", f"{s}_ForearmTwist02": f"{S}ForeArm", f"{s}_Hand": f"{S}Hand",
                    f"{s}_Thigh": f"{S}UpLeg", f"{s}_ThighTwist01": f"{S}UpLeg", f"{s}_ThighTwist02": f"{S}UpLeg", f"{s}_Calf": f"{S}Leg",
                    f"{s}_CalfTwist01": f"{S}Leg", f"{s}_CalfTwist02": f"{S}Leg", f"{s}_Foot": f"{S}Foot", f"{s}_ToeBase": f"{S}ToeBase"})
    for k in range(1, 5): OLD2NEW[f"metacarpal{k}.{s}"] = f"{S}Hand"
    for f, F_ in ((1, "Thumb"), (2, "Index"), (3, "Middle"), (4, "Ring"), (5, "Pinky")):
        for k in (1, 2, 3): OLD2NEW[f"finger{f}-{k}.{s}"] = f"{S}Hand{F_}{k}"
o2n = np.array([RI[mx(OLD2NEW[n])] for n in JN])
nv = len(Vt)
WT = np.zeros((nv, NB))
for k in range(4): np.add.at(WT, (np.arange(nv), o2n[JO[:, k]]), WO[:, k])
# (the old Spine01 also covered where Mixamo has Spine1: split by height between Spine and Spine2)
sp, sp1, sp2 = RI[mx("Spine")], RI[mx("Spine1")], RI[mx("Spine2")]
y0, y1, y2 = BP[sp, 1], BP[sp1, 1], BP[sp2, 1]
t = np.clip((Vt[:, 1] - y0) / (y2 - y0), 0, 1)
share = np.clip(1 - np.abs(Vt[:, 1] - y1) / ((y2 - y0) / 2), 0, 1)       # a tent on Spine1's height
for src in (sp, sp2):
    mv = WT[:, src] * share * 0.8; WT[:, src] -= mv; WT[:, sp1] += mv

# allowed bones per vertex: those the old skin (on the new bones) gives it, their parents and children
adj = np.eye(NB, dtype=bool)
for i in range(NB):
    if par[i] >= 0: adj[i, par[i]] = adj[par[i], i] = True
for e in END: adj[e, :] = adj[:, e] = False
adj[sp1, :] |= adj[sp, :] | adj[sp2, :]; adj[:, sp1] |= adj[:, sp] | adj[:, sp2]
allow = (WT > 0.02).astype(float) @ adj.astype(float) > 0
allow[:, list(END)] = False

# a limb bone only within its own span along the limb, plus a margin at each joint: v5's own skin (Tripo's) gives the
# armpit's sleeve 0.18 of the forearm and the chest a little of the thigh, and with the elbow bent 90 deg seated 0.18 of
# the forearm carries the armpit 5-7 cm off (2.4 cm into the hoodie). Measured along the limb in the T-pose (straight)
SPAN = {"elbow": 0.06, "wrist": 0.04, "knee": 0.07, "ankle": 0.05}
for S in ("Left", "Right"):
    for up, mid, low, k1, k2 in (("Arm", "ForeArm", "Hand", "elbow", "wrist"), ("UpLeg", "Leg", "Foot", "knee", "ankle")):
        a, b, c = RI[mx(S + up)], RI[mx(S + mid)], RI[mx(S + low)]
        sb = (Vt - BP[b]) @ unit(BP[b] - BP[a]); sc = (Vt - BP[c]) @ unit(BP[c] - BP[b])
        allow[sb < -SPAN[k1], b] = False; allow[sb > SPAN[k1], a] = False         # (the middle bone: from the joint above it on)
        low_ids = [RI[n] for n in RN if n.startswith(mx(S + low))]                # (the hand and its fingers, the foot and its toes)
        for j in low_ids: allow[sc < -SPAN[k2], j] = False
        allow[sc > SPAN[k2], b] = False
# the sleeve and the hoodie's side as two parts (by the old skin's main joint): away from the shoulder joint the sleeve
# takes nothing of the spine and the hoodie nothing of the arm. v5's skin blends them 0.2-0.3 each way down the armpit,
# so with the arm swung 20 deg forward (Seated_Idle) the blend sheared the sleeve 2.4 cm into the hoodie. Within PIT of
# the shoulder joint (T-pose) both keep everything: the shoulder still rounds over. (Measured against ramps over 6-22 cm
# under the joint: each was worse at the armpit, the back of the shoulder or both.) The price, with linear blending:
# raised high (the T-pose), the arm leaves the back of the armpit behind, a web (the report's tpose_dev: 10,010
# vertices over 5 cm off v5's own T-pose, up to 19.5 cm); with no cut (PIT 9) that is 29 vertices, but seated the
# sleeves go 2.3 cm into the hoodie again. An arm-raise corrective shape would take both; not made yet.
PIT = float(__import__("os").environ.get("AUTORIG_PIT", "0.07"))
SHCUT = float(__import__("os").environ.get("AUTORIG_SHCUT", "0.06"))
TORSO = [RI[mx(n)] for n in ("Hips", "Spine", "Spine1", "Spine2", "Neck", "Head")]
is_torso = np.isin(dom, [JI[n] for n in ("Hip", "Pelvis", "Waist", "Spine01", "Spine02", "NeckTwist01", "NeckTwist02") if n in JI])
# (and the hoodie's hem: v5's skin gives its sides to the thigh, 0.5, so it counted as neither part and kept 0.1 of the
# upper arm: raised, the arm pulled the hem's sides up 5-7 cm, "horns". Skin over the hip joints by 4 cm whose main
# joint is a thigh is the hoodie's)
_thighs = [JI[n] for n in JN if n.startswith(("L_Thigh", "R_Thigh"))]
is_torso |= np.isin(dom, _thighs) & (V[:, 1] > max(J[JI["L_Thigh"], 1], J[JI["R_Thigh"], 1]) + 0.04)
# (the arm part is skin round the arm itself: within SLEEVE of its bind axis (shoulder -> elbow -> wrist, as modelled),
# not before the shoulder joint, and not across from it toward the middle. v5's skin gives the upper arm 0.9 of patches of the hoodie's back and chest inside the
# shoulder (x 0.15 against the joint's 0.20); those are the hoodie's)
SLEEVE = float(__import__("os").environ.get("AUTORIG_SLEEVE", "0.13"))


def round_limb(s, pts):                                         # the vertices within SLEEVE of the polyline pts (bind), past its start
    near = np.zeros(nv, bool)
    for a, b in zip(pts[:-1], pts[1:]):
        ab = b - a; L2 = ab @ ab; t = (V - a) @ ab / L2; c = a + np.clip(t, 0, 1)[:, None] * ab
        near |= (np.linalg.norm(V - c, axis=1) < SLEEVE) & (t > -0.02 / np.sqrt(L2))
    return near


for s, S in (("L", "Left"), ("R", "Right")):
    armJ = [JI[n] for n in JN if n.startswith((f"{s}_Upperarm", f"{s}_Forearm", f"{s}_Hand")) or (n.endswith("." + s) and n.startswith(("finger", "metacarpal")))]
    arm_new = [RI[n] for n in RN if n.startswith((mx(S + "Arm"), mx(S + "ForeArm"), mx(S + "Hand")))]
    far = np.linalg.norm(Vt - BP[RI[mx(S + "Arm")]], axis=1) > PIT
    on_arm = round_limb(s, [J[JI[f"{s}_Upperarm"]], J[JI[f"{s}_Forearm"]], J[JI[f"{s}_Hand"]], J[JI[f"finger3-1.{s}"]]])
    # (and not inside the shoulder joint across the body by more than 2.5 cm: the front of the chest by the armpit is
    # within 13 cm of the axis too, the joint being forward of the sleeve, and with 1.0 of the arm it went 2.4 cm into
    # the chest typing)
    side = 1 if s == "L" else -1
    on_arm &= side * V[:, 0] > side * J[JI[f"{s}_Upperarm"]][0] - 0.025
    is_arm = np.isin(dom, armJ) & on_arm
    is_torso = is_torso | (np.isin(dom, armJ) & ~on_arm)
    for j in arm_new: allow[is_torso & far, j] = False
    for j in TORSO: allow[is_arm & far, j] = False
    # the sleeve takes the clavicle only over the shoulder: v5's skin and the distance term put 0.3-0.45 of it on the
    # sleeve at the armpit, 30 cm under its joint, where the clip's shoulder roll (seated, the shoulders forward) carried
    # the sleeve 4-10 cm through the hoodie (the hoodie's side keeps it: cut there too, the hoodie went 2.5 cm into the
    # sleeve instead)
    allow[is_arm & (Vt[:, 1] < BP[RI[mx(S + "Arm")], 1] - SHCUT), RI[mx(S + "Shoulder")]] = False
# a side's bones only on its own side (and across the middle by 4 cm): the distance term and the smoothing put up to 0.1
# of the right clavicle on the left sleeve's back
for i, n in enumerate(RN):
    if n.startswith(mx("Left")): allow[Vt[:, 0] < -0.04, i] = False
    if n.startswith(mx("Right")): allow[Vt[:, 0] > 0.04, i] = False
# the legs only below the hips: v5's skin puts up to 0.2 of the thigh on the chest at the armpit (1.1 m up), and seated
# (the thigh turned 90 deg) that drags the hoodie's side into the sleeve
HIPCUT = float(__import__("os").environ.get("AUTORIG_HIPCUT", "0.10"))
for S in ("Left", "Right"):
    above = Vt[:, 1] > BP[RI[mx(S + "UpLeg")], 1] + HIPCUT
    for n in RN:
        if n.startswith((mx(S + "UpLeg"), mx(S + "Leg"), mx(S + "Foot"), mx(S + "ToeBase"), mx(S + "Toe"))): allow[above, RI[n]] = False
allow[:, list(END)] = False
lost = ~allow.any(1)                                            # (a vertex left with no bone keeps its old ones)
allow[lost] = WT[lost] > 0.02

# distance to each segment
d2 = np.empty((nv, NB))
for i in range(NB):
    a, b = SA[i], SB[i]; ab = b - a; L2 = ab @ ab
    tt = np.clip(((Vt - a) @ ab) / L2, 0, 1) if L2 > 1e-10 else np.zeros(nv)
    d2[:, i] = ((Vt - a - tt[:, None] * ab) ** 2).sum(1)
WG = np.where(allow, 1.0 / (d2 + 1e-6) ** 2, 0.0)
WG /= WG.sum(1, keepdims=True) + 1e-30

ALPHA = float(__import__("os").environ.get("AUTORIG_ALPHA", "0.5"))     # (geometric share; the rest is the old skin moved over)
ITERS = 12
W = ALPHA * WG + (1 - ALPHA) * WT

# smoothing over the surface, welded across the seams (vertices within 2 mm)
e = np.concatenate([FA[:, [0, 1]], FA[:, [1, 2]], FA[:, [2, 0]]])
pairs = cKDTree(Vt).query_pairs(0.002, output_type="ndarray")
e = np.concatenate([e, pairs])
A = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(nv, nv)); A = ((A + A.T) > 0).astype(float)
Lm = diags(1.0 / np.maximum(np.asarray(A.sum(1)).ravel(), 1)) @ A
for _ in range(ITERS):
    W = 0.5 * W + 0.5 * (Lm @ W); W *= allow; W /= W.sum(1, keepdims=True) + 1e-30
# coincident vertices (the UV and normal seams, the head / body join) get one set of weights, or the seams open
from scipy.sparse.csgraph import connected_components
cp = cKDTree(Vt).query_pairs(2e-4, output_type="ndarray")
ng, lab = connected_components(coo_matrix((np.ones(len(cp)), (cp[:, 0], cp[:, 1])), shape=(nv, nv)), directed=False)
G = np.zeros((ng, NB)); np.add.at(G, lab, W); W = G[lab] / np.bincount(lab, minlength=ng)[lab, None]
# the bind pose: the mesh as modelled (arms down), not the T-pose. Each Mixamo bone's bind is its T-pose placement taken
# back through the rigid T-posing map of the old joint it stands for (map_j: v -> D_j (v - J_j) + Pp_j), so a rigid part
# poses exactly as before, but a vertex shared by two bones is no longer T-posed by the blend of their maps first: with
# a T-posed bind, bringing the arms back down did not undo the T-posing at the armpit (linear blending is not
# invertible where the two maps differ), and the sleeve's top went 2.4 cm into the hoodie. Bound as modelled, a pose
# near the modelled one gives back the modelled mesh. AUTORIG_BIND=tpose: the old T-posed bind.
BIND_T = __import__("os").environ.get("AUTORIG_BIND") == "tpose"
NEW2OLD = {"Hips": "Hip", "Spine": "Spine01", "Spine1": "Spine01", "Spine2": "Spine02", "Neck": "NeckTwist01", "Head": "Head"}
for s, S in (("L", "Left"), ("R", "Right")):
    NEW2OLD.update({f"{S}Shoulder": f"{s}_Clavicle", f"{S}Arm": f"{s}_Upperarm", f"{S}ForeArm": f"{s}_Forearm", f"{S}Hand": f"{s}_Hand",
                    f"{S}UpLeg": f"{s}_Thigh", f"{S}Leg": f"{s}_Calf", f"{S}Foot": f"{s}_Foot", f"{S}ToeBase": f"{s}_ToeBase"})
    for f, F_ in ((1, "Thumb"), (2, "Index"), (3, "Middle"), (4, "Ring"), (5, "Pinky")):
        for k in (1, 2, 3): NEW2OLD[f"{S}Hand{F_}{k}"] = f"finger{f}-{k}.{s}"
BMAP = []                                                       # per Mixamo bone: map_j as a 4x4 (work space, metres)
for i in range(NB):
    b = i
    while RN[b][10:] not in NEW2OLD: b = par[b]                 # (an end bone: its parent's)
    j = JI[NEW2OLD[RN[b][10:]]]; m = np.eye(4); m[:3, :3] = D[j]; m[:3, 3] = Pp[j] - D[j] @ J[j]
    BMAP.append(np.eye(4) if BIND_T else m)
# (V is the bind mesh as extracted, feet on y = 0; Pp carries the T-pose's lift, so map_j already lands on the lifted Vt)
Vb = V; Nb = NV / (np.linalg.norm(NV, axis=1, keepdims=True) + 1e-12)

# 4 per vertex
top = np.argsort(-W, axis=1)[:, :4]; tw = np.take_along_axis(W, top, 1)
tw[tw < 0.01] = 0; tw /= tw.sum(1, keepdims=True)

# how far the new skin's T-pose is from the T-pose v5's own skin made (step 1, which G20's sheet shows whole): where the
# arm and the hoodie part company, a web of skin left behind shows as vertices centimetres off it
_tp = np.zeros_like(Vt)
for c in range(4): _tp += tw[:, c:c + 1] * (np.einsum("nab,nb->na", np.stack(BMAP)[top[:, c], :3, :3], V) + np.stack(BMAP)[top[:, c], :3, 3])
_dv = np.linalg.norm(_tp - Vt, axis=1); TPOSE_DEV = [round(float(np.percentile(_dv, 99)) * 100, 1), round(float(_dv.max()) * 100, 1), int((_dv > 0.05).sum())]
# ---------------------------------------------------------------------------------------------------- out
np.savez(f"{OUT}/mesh.npz", pos=Vt.astype(np.float32), nrm=Nt.astype(np.float32), jnt=top.astype(np.uint16),
         wgt=tw.astype(np.float32), off=off, Vbind=V.astype(np.float32))
PB, NB_ = (Vt, Nt) if BIND_T else (Vb, Nb)
for nm, a in (("pos", PB.astype(np.float32)), ("nrm", NB_.astype(np.float32)), ("jnt", top.astype(np.uint16)), ("wgt", tw.astype(np.float32))):
    a.tofile(f"{OUT}/{nm}.bin")                                 # (raw, for write.mjs; primitives in extract's order, counts in skel.json)
skel = [{"name": RN[i], "parent": RN[par[i]] if par[i] >= 0 else None, "p": BP[i].tolist(), "q": RQ[i].tolist(),
         "bindmap": BMAP[i].T.ravel().tolist()} for i in range(NB)]
rep = {"finger_centring_mm": SHIFT, "twist_deg": {s: round(float(np.degrees(TWIST[s])), 1) for s in TWIST},
       "height_m": round(float(Vt[:, 1].max()), 3), "hips_m": round(float(BP[RI[mx("Hips")], 1]), 3),
       "alpha": ALPHA, "verts": int(nv), "bones": NB, "tpose_dev_cm_p99_max_n5cm": TPOSE_DEV,
       # (the source's bind space (its first primitive's) -> this file's mesh space: kimodo/mx_convert.mjs carries the
       # source's clips over with it)
       "from_source_bind": (np.array([[*(K * Rw[0]), 0], [*(K * Rw[1]), -floor], [*(K * Rw[2]), 0], [0, 0, 0, 1]]).T.ravel()).tolist(),
       "direction_err_deg": {}}
# how far each bone's rest direction is from Mixamo's (the clips assume Mixamo's)
for i in range(NB):
    if par[i] < 0: continue
    a = BP[i] - BP[par[i]]; b = RP[i] - RP[par[i]]
    if np.linalg.norm(a) > 1e-4 and np.linalg.norm(b) > 1e-4:
        rep["direction_err_deg"][RN[i][10:]] = round(float(np.degrees(np.arccos(np.clip(unit(a) @ unit(b), -1, 1)))), 1)
json.dump({"bones": skel, "counts": cnt, "report": rep}, open(f"{OUT}/skel.json", "w"), indent=1)
big = {k: v for k, v in rep["direction_err_deg"].items() if v > 8}
print("T-pose vs v5's own skin (cm p99, max, verts > 5 cm):", TPOSE_DEV)
print(json.dumps({k: rep[k] for k in ("finger_centring_mm", "twist_deg", "height_m", "hips_m", "verts", "bones")}), "direction >10deg:", big)
