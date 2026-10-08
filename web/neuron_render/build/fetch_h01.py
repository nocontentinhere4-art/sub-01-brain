"""Build the H01 close-up sets for web/neuron_render/ (#99): REAL electron-microscopy reconstructions of human cortex.

    python web/neuron_render/build/fetch_h01.py              # fetch (cached in data/h01_cache/), decimate, write
    python web/neuron_render/build/fetch_h01.py --quick      # the focus cell only (a smoke run)
    python web/neuron_render/build/fetch_h01.py --offline    # from the cache only

Source: H01 (Shapson-Coe A, Januszewski M, Berger DR et al. (2024) A petavoxel fragment of human cerebral cortex
reconstructed at nanoscale resolution. Science 384:eadk4858, doi:10.1126/science.adk4858), Google Cloud bucket
gs://h01-release, "All released datasets are licensed under a Creative Commons Attribution 4.0 License"
(https://h01-release.storage.googleapis.com/data.html, read 2026-10-02). Read through cloud-volume over HTTPS, once,
at build time; nothing is hot-linked.

What is taken, per set (cortex: a block of human temporal cortex around one layer 2 pyramidal cell):
- the 104 manually proofread cells (gs://h01-release/data/20210601/proofread_104): multi-LOD Draco meshes (LOD 2 for
  the cells in focus, LOD 3 for the others), decimated with quadric simplification (fast-simplification) to the
  triangle targets below; their SWC skeletons with H01's own subcompartment classes per node (axon, dendrite, soma,
  AIS, myelinated axon); their synapses (synapse_locations.csv: this cell's presynaptic sites = its boutons, and its
  incoming synapses);
- glia from the c3 segmentation (automated, not proofread) picked from the soma table (c3/tables/somas.csv:
  ASTROCYTE, OLIGO in layers 2-3);
- a real EM image behind the block: a crop of the 4 nm SEM volume at the 128 nm mip through the focus cell's soma.

Coordinates: H01 nm -> um; the block frame is centred on the focus cell's soma with +y toward the pia (the layer
axis is found from the soma table), x along the slab, z the slab's thickness (~175 um). The focus cell keeps its true
position; the other cells keep their true orientation, cortical depth (y) and z, and are moved laterally (x) to sit
within the field, because the 104 proofread cells are spread over ~12 mm2 of tissue. The manifest records both.

Output: web/neuron_render/h01/<set>.json (manifest with credits, every cell's id, type, layer, offsets) and
<set>.bin.gz (one gzip blob: quantised meshes with per-vertex class / path distance / pulse arrival time, skeletons (the far
tier whole, the focus and hero cells' axons),
synapses), plus <set>_em.jpg. Budget: <= 3 MB per set (checked and printed).
"""
import argparse
import csv
import gzip
import io
import json
import math
import struct
import sys
import time
import zipfile
from collections import deque
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[3]            # repo root
CACHE = HERE / "data" / "h01_cache"
OUT = HERE / "web" / "neuron_render" / "h01"
BUCKET = "gs://h01-release/data/20210601"
HTTP = "https://storage.googleapis.com/h01-release/data/20210601"
SWC_NM = np.array([32.0, 32.0, 33.0])                  # the SWC files are in 32x32x33 nm units (checked against the precomputed skeletons)
SYN_NM = np.array([8.0, 8.0, 33.0])                    # synapse_locations.csv is in 8x8x33 nm voxels (the segmentation's base)
SLOWDOWN = 10000                                      # pulses: real conduction speed / SLOWDOWN (as the renderer states)
V_UNMYELINATED = 0.3                                   # m/s, thin cortical axons (Swadlow 1994)
HURSH = 6.0                                            # m/s per um of outer fibre diameter (Hursh 1939)
G_RATIO = 0.7                                          # Chomiak & Hu 2009
INTERNODE_UM = 100.0                                   # a myelinated stretch is drawn with a node every ~100 um (Rushton 1951)
# H01 subcompartment classes (proofread_104/subcompartments/annotations/info): -1 = unlabelled node
H01_CLASS = {0: "axon", 1: "dendrite", 2: "astrocyte", 3: "soma", 4: "cilium", 5: "AIS", 1000: "myelinated axon",
             1001: "myelinated axon", 1002: "myelinated fragment", 1003: "myelinated fragment", 1004: "myelinated fragment",
             1005: "myelinated fragment"}
# -> renderer kinds: 0 soma, 1 axon (unmyelinated), 2 dendrite, 4 myelinated axon, 5 AIS
KIND = {3: 0, 0: 1, 1: 2, 2: 2, 4: 2, 5: 5, 1000: 4, 1001: 4, 1002: 4, 1003: 4, 1004: 4, 1005: 4}

CITE = ("Shapson-Coe A, Januszewski M, Berger DR et al. (2024) A petavoxel fragment of human cerebral cortex "
        "reconstructed at nanoscale resolution. Science 384:eadk4858. doi:10.1126/science.adk4858")
LICENSE = "CC BY 4.0 (https://h01-release.storage.googleapis.com/data.html: all released datasets are licensed under a Creative Commons Attribution 4.0 License)"

# the sets: which proofread cells (by H01 tags) and how many, per tier. desktop / phone targets in triangles.
SETS = {
    "cortex": {
        "focus": {"tags": ["L2", "pyramidal"], "n": 1},
        "hero": [{"tags": ["L5", "pyramidal"], "n": 1}, {"tags": ["L2", "interneuron"], "n": 1}, {"tags": ["L3", "pyramidal"], "n": 1}],
        "mid": [{"tags": ["L2", "pyramidal"], "n": 3}, {"tags": ["L3", "interneuron"], "n": 2}, {"tags": ["L4", "pyramidal"], "n": 2},
                {"tags": ["L5", "interneuron"], "n": 1}, {"tags": ["L1", "interneuron"], "n": 1}],
        "far": 18,
        "glia": [("ASTROCYTE", 2), ("OLIGO", 3)],
        "em_px": 2560, "em_mip": [64, 64, 66],
    },
}
TRI = {"desktop": {"focus": 70000, "hero": 50000, "mid": 12000, "glia": 8000}, "phone": {"focus": 40000, "hero": 28000, "mid": 8000, "glia": 5000}}
COUNTS = {"desktop": {"hero": 2, "mid": 7, "far": 6, "glia": 4}, "phone": {"hero": 2, "mid": 5, "far": 6, "glia": 3}}
FAR_STRIDE = {"desktop": 6, "phone": 8}
POST_MAX = {"focus": 100000, "hero": 100000, "mid": 1000}       # incoming synapses kept per cell (the mid tier: a sample)
AXON_SKEL_NODES = {"desktop": 2200, "phone": 1800}
BRIDGE_UM = 32.0                                              # an axon skeleton fragment is bridged straight to a closer node within this             # the focus / hero cells also carry their axon's skeleton (thinned to about this
                                                               # many nodes): drawn as a line under the mesh, lit node to node by the pulse


def log(*a):
    print(*a, flush=True)


def get_json(url):
    import urllib.request
    return json.loads(urllib.request.urlopen(url, timeout=120).read())


# ---------- H01 access (cloud-volume), cached ----------
class H01:
    def __init__(self, offline=False):
        self.offline = offline
        self._pr = self._c3 = self._em = None
        CACHE.mkdir(parents=True, exist_ok=True)

    @property
    def pr(self):
        if self._pr is None:
            from cloudvolume import CloudVolume
            self._pr = CloudVolume(f"precomputed://{BUCKET}/proofread_104", use_https=True, progress=False)
        return self._pr

    @property
    def c3(self):
        if self._c3 is None:
            from cloudvolume import CloudVolume
            self._c3 = CloudVolume(f"precomputed://{BUCKET}/c3", use_https=True, progress=False)
        return self._c3

    def cached(self, name, make):
        p = CACHE / name
        if p.exists():
            return p.read_bytes()
        if self.offline:
            raise SystemExit(f"{p} is not cached; run without --offline")
        b = make()
        p.write_bytes(b)
        return b

    def text(self, name, url):
        import urllib.request
        b = self.cached(name, lambda: urllib.request.urlopen(url, timeout=600).read())
        if b[:2] == b"\x1f\x8b":                         # the bucket serves some small files gzip-encoded
            b = gzip.decompress(b)
        return b.decode("utf-8", "ignore")

    def mesh(self, source, sid, lod):
        def make():
            cv = self.pr if source == "pr" else self.c3
            last = None
            for attempt, l in enumerate((lod, lod, lod + 1, lod - 1, 3)):   # a LOD some cells lack: the next one
                try:
                    m = cv.mesh.get(sid, lod=max(0, min(3, l)))[sid]
                    V = np.asarray(m.vertices, np.float32); F = np.asarray(m.faces, np.uint32)
                    return struct.pack("<II", len(V), len(F)) + V.tobytes() + F.tobytes()
                except Exception as e:
                    last = e; time.sleep(1 + attempt)
            raise last
        b = self.cached(f"mesh_{source}_{sid}_lod{lod}.bin", make)
        nv, nf = struct.unpack("<II", b[:8])
        V = np.frombuffer(b[8:8 + nv * 12], np.float32).reshape(nv, 3)
        F = np.frombuffer(b[8 + nv * 12:8 + nv * 12 + nf * 12], np.uint32).reshape(nf, 3)
        return V, F

    def em(self, name, mip, x0, y0, z0, px):
        def make():
            from cloudvolume import CloudVolume
            cv = CloudVolume(f"precomputed://{BUCKET}/4nm_raw", use_https=True, progress=False, mip=mip, fill_missing=True)
            sz = cv.bounds.maxpt
            xs, ys = max(0, min(x0, int(sz[0]) - px)), max(0, min(y0, int(sz[1]) - px))   # a soma near the slab's edge: the crop slides in
            zs = max(0, min(z0, int(sz[2]) - 1))
            img = cv[xs:xs + px, ys:ys + px, zs:zs + 1]
            a = np.asarray(img)[:, :, 0, 0].T.copy()
            return struct.pack("<iii", xs, ys, zs) + a.tobytes()
        b = self.cached(name, make)
        xs, ys, zs = struct.unpack("<iii", b[:12])
        return np.frombuffer(b[12:], np.uint8).reshape(px, px), (xs, ys, zs)


# ---------- skeletons: the SWC fragments with H01's classes, labels propagated, the pulse timed ----------
def load_swc(h, sid):
    """All fragments of one proofread cell: nodes (nm), radius (nm), class, parent, fragment id."""
    zb = h.cached("104_proofread_neurons_swc.zip", lambda: __import__("urllib.request").request.urlopen(
        f"{HTTP}/proofread_104/skeletons/104_proofread_neurons_swc.zip", timeout=900).read())
    z = zipfile.ZipFile(io.BytesIO(zb))
    names = sorted(n for n in z.namelist() if n.split("/")[-1].startswith(f"{sid}.") and n.endswith(".swc"))
    P, R, C, PAR, FR = [], [], [], [], []
    base = 0
    for fi, n in enumerate(names):
        rows = [ln.split() for ln in z.read(n).decode().splitlines() if ln.strip() and not ln.startswith("#")]
        ids = {int(r[0]): k for k, r in enumerate(rows)}
        for r in rows:
            P.append([float(r[2]), float(r[3]), float(r[4])]); R.append(float(r[5])); C.append(int(float(r[1])))
            par = int(r[6]); PAR.append(base + ids[par] if par in ids and par != int(r[0]) else -1); FR.append(fi)
        base += len(rows)
    P = np.array(P) * SWC_NM                       # nm
    return P, np.array(R), np.array(C), np.array(PAR), np.array(FR)


def propagate(C, PAR, n):
    """Unlabelled nodes (-1) take the class of the nearest labelled node along the tree (multi-source BFS)."""
    kids = [[] for _ in range(n)]
    for i, p in enumerate(PAR):
        if p >= 0:
            kids[p].append(i)
    out = C.copy()
    q = deque(i for i in range(n) if C[i] != -1)
    seen = np.zeros(n, bool); seen[list(q)] = True
    while q:
        i = q.popleft()
        for j in list(kids[i]) + ([PAR[i]] if PAR[i] >= 0 else []):
            if not seen[j]:
                seen[j] = True; out[j] = out[i]; q.append(j)
    out[out == -1] = 1                                # a fragment with no label at all: dendrite
    return out


def soma_centre(P, R, soma_nodes):
    """The soma's centre: H01's soma class also sits on a few far-away nodes, so the plain mean of soma nodes can land
    tens of µm off the cell body. The soma is the cluster (within 30 µm) around the thickest soma node."""
    if not len(soma_nodes):
        return P[np.argmax(R)]
    core = soma_nodes[np.argmax(R[soma_nodes])]
    near = soma_nodes[np.linalg.norm(P[soma_nodes] - P[core], axis=1) <= 30000.0]
    return P[near].mean(0)


def reroot(PAR, new_root):
    """The fragment that holds new_root re-rooted there (the parent links on the path to its old root are reversed)."""
    PAR = PAR.copy(); chain = []; i = new_root
    while i >= 0:
        chain.append(i); i = PAR[i]
    for a, b in zip(chain, chain[1:]):
        PAR[b] = a
    PAR[new_root] = -1
    return PAR


ADOPT_NM, ADOPT_MAX_NODES = 4000.0, 400


def adopt_axon_fragments(P, C, CL, FR):
    """H01's SWC fragments: a small fragment with no label at all defaults to dendrite in propagate(); when one of its
    nodes lies within ADOPT_NM of an axon-labelled node of another fragment it is a piece of that axon (the axon's
    skeleton is cut into many such pieces) and takes the axon class, so the pulse runs through it. Two passes, so a
    chain of pieces is adopted."""
    CL = CL.copy()
    from scipy.spatial import cKDTree
    frag_ids = np.unique(FR)
    unl = {f for f in frag_ids if not (C[FR == f] != -1).any() and (FR == f).sum() <= ADOPT_MAX_NODES}
    for _ in range(2):
        ax = np.isin(np.array([KIND.get(int(c), 2) for c in CL]), (1, 4, 5))
        if not ax.any():
            break
        tree = cKDTree(P[ax]); axfr = FR[ax]
        adopted = set()
        for f in unl:
            idx = np.where(FR == f)[0]
            dd, jj = tree.query(P[idx], workers=-1)
            if ((dd <= ADOPT_NM) & (axfr[jj] != f)).any():
                CL[idx] = 0; adopted.add(f)
        unl -= adopted
        if not adopted:
            break
    return CL


def bridge_axon_fragments(P, CL, PAR, FR, soma_nm):
    """The axon's skeleton comes in pieces (the focus cell's in ~20, the first starting tens of µm from the soma). Each
    piece's root is linked to the nearest soma or axon node of another piece within BRIDGE_UM (pieces are taken from
    the soma outward, and a link never closes a loop), so the path distances and pulse times run continuously from
    the soma along the whole axon. The links are straight chords, not H01 geometry; the docs say so."""
    PAR = PAR.copy()
    kinds = np.array([KIND.get(int(c), 2) for c in CL])
    ax = np.isin(kinds, (1, 4, 5))
    cand = np.where(ax | (kinds == 0))[0]
    if not len(cand):
        return PAR
    from scipy.spatial import cKDTree
    tree = cKDTree(P[cand])
    comp = {f: f for f in np.unique(FR)}                   # union-find over fragments

    def find(f):
        while comp[f] != f:
            comp[f] = comp[comp[f]]; f = comp[f]
        return f
    roots = [r for r in np.where(ax & (PAR < 0))[0]]
    roots.sort(key=lambda r: np.linalg.norm(P[r] - soma_nm))
    for r in roots:
        dd, jj = tree.query(P[r], k=min(48, len(cand)))
        for d_, j_ in zip(np.atleast_1d(dd), np.atleast_1d(jj)):
            if d_ > BRIDGE_UM * 1000.0:
                break
            j = cand[j_]
            if find(FR[j]) != find(FR[r]):
                PAR[r] = j; comp[find(FR[r])] = find(FR[j]); break
    return PAR


def time_pulse(P, R, CL, PAR, soma_nm):
    """Path distance (um) from the soma and the pulse's arrival time (s) at every node. The pulse starts at the soma,
    runs the AIS and unmyelinated axon at V_UNMYELINATED / SLOWDOWN, and myelinated stretches at Hursh's speed for
    the node's diameter; within a myelinated stretch the time is quantised to INTERNODE_UM steps (the stretch lights
    internode by internode). Dendrites: d only, t = -1. Fragments not attached to the soma start at their distance
    from the soma centre."""
    n = len(P)
    kids = [[] for _ in range(n)]
    roots = []
    for i, p in enumerate(PAR):
        if p >= 0:
            kids[p].append(i)
        else:
            roots.append(i)
    D = np.zeros(n); T = np.full(n, -1.0)
    vU = V_UNMYELINATED * 1e6 / SLOWDOWN               # um/s on screen
    myel_start = {}
    for r in roots:
        D[r] = float(np.linalg.norm(P[r] - soma_nm)) / 1000.0
        axon_root = KIND.get(CL[r], 2) in (1, 4, 5)
        T[r] = D[r] / vU if axon_root else -1.0
        if KIND.get(CL[r], 2) == 0:
            D[r] = 0.0; T[r] = 0.0
        stack = [r]
        while stack:
            i = stack.pop()
            for j in kids[i]:
                seg = float(np.linalg.norm(P[j] - P[i])) / 1000.0
                D[j] = D[i] + seg
                kj = KIND.get(CL[j], 2)
                if kj in (1, 4, 5) or KIND.get(CL[i], 2) == 0 and kj != 2:
                    base = T[i] if T[i] >= 0 else D[i] / vU
                    if kj == 4:
                        dia = 2 * R[j] / 1000.0 / G_RATIO
                        v = max(2.0, min(15.0, HURSH * dia)) * 1e6 / SLOWDOWN
                        T[j] = base + seg / v
                    else:
                        T[j] = base + seg / vU
                else:
                    T[j] = -1.0
                stack.append(j)
    # saltatory: inside a myelinated stretch, every node shows the time the pulse entered its ~100 um internode
    order = sorted(range(n), key=lambda i: D[i])
    for i in order:
        if KIND.get(CL[i], 2) == 4 and T[i] >= 0:
            p = PAR[i]
            if p >= 0 and KIND.get(CL[p], 2) == 4 and p in myel_start:
                s0, d0, t0 = myel_start[p]
                if D[i] - d0 < INTERNODE_UM:
                    myel_start[i] = (s0, d0, t0); T[i] = t0
                    continue
            myel_start[i] = (i, D[i], T[i])
    return D, T


# ---------- meshes ----------
def decimate(V, F, target):
    """Quadric decimation to <= target faces. fast-simplification can stop short of its target on big meshes (its
    aggressiveness bounds the error per pass), so it is run again on its own output until the target is met."""
    import fast_simplification as fs
    V2, F2 = V.astype(np.float32), F.astype(np.int64)
    for agg in (7, 8, 9, 10, 10, 10):
        if len(F2) <= target * 1.03:
            break
        V2, F2 = fs.simplify(V2, F2, target_count=int(target), agg=agg)
        V2, F2 = np.asarray(V2, np.float32), np.asarray(F2, np.int64)
    return V2, F2


AXON_SHARE = 0.3                                            # of a cell's triangle budget, at most this much goes to its axon


def decimate_split(V, F, tris, P, CL):
    """The axon is thin, so quadric decimation of the whole cell collapses it first and the tube ends up fragmentary;
    the faces whose vertices bind to axon / AIS / myelinated-axon skeleton nodes are decimated on their own budget
    (up to AXON_SHARE of the cell's), the rest of the cell on the remainder, and the two are joined again."""
    kinds = np.array([KIND.get(int(c), 2) for c in CL], np.uint8)[nearest_nodes(P, V)]
    is_ax = np.isin(kinds, (1, 4, 5))
    fax = is_ax[F].sum(1) >= 2                                   # a face is axon when two of its corners are
    parts = []
    for mask, budget in ((fax, min(int(fax.sum()), int(tris * AXON_SHARE))), (~fax, None)):
        Fp = F[mask]
        if not len(Fp):
            continue
        used, inv = np.unique(Fp.ravel(), return_inverse=True)
        Vp, Fp = V[used], inv.reshape(-1, 3)
        if budget is None:
            budget = max(1000, tris - sum(len(f) for _, f in parts))
        if len(Fp) > budget:
            Vp, Fp = decimate(Vp, Fp, budget)
        parts.append((np.asarray(Vp, np.float32), np.asarray(Fp, np.int64)))
    off, Vs, Fs = 0, [], []
    for Vp, Fp in parts:
        Vs.append(Vp); Fs.append(Fp + off); off += len(Vp)
    return np.vstack(Vs), np.vstack(Fs)


def quant(V, lo, hi):
    return np.round((V - lo) / np.maximum(hi - lo, 1e-6) * 65535).clip(0, 65535).astype(np.uint16)


def nearest_nodes(P_nodes, Q):
    from scipy.spatial import cKDTree
    return cKDTree(P_nodes).query(Q, workers=-1)[1]


# ---------- the build ----------
def layer_axis(somas):
    """+y toward the pia? The soma table's layers vs coordinates (voxels)."""
    by = {}
    for r in somas:
        if r["layer"].startswith("Layer "):
            by.setdefault(int(r["layer"][6:]), []).append((float(r["x"]), float(r["y"])))
    mx = {k: np.mean([p[0] for p in v]) for k, v in by.items()}; my = {k: np.mean([p[1] for p in v]) for k, v in by.items()}
    sx = np.corrcoef(list(mx.keys()), list(mx.values()))[0, 1]; sy = np.corrcoef(list(my.keys()), list(my.values()))[0, 1]
    axis = 1 if abs(sy) > abs(sx) else 0
    sign = -1.0 if (sy if axis else sx) > 0 else 1.0          # layer number grows away from the pia
    return axis, sign


def pick_cells(props, spec, used):
    ids, tags, vals = props["inline"]["ids"], props["inline"]["properties"][0]["tags"], props["inline"]["properties"][0]["values"]
    rows = [(i, set(tags[v] for v in vv)) for i, vv in zip(ids, vals)]
    out = []
    for i, t in rows:
        if i in used or not set(spec["tags"]) <= t:
            continue
        out.append(i)
    return out


def build_cell(h, sid, role, tris, soma_table_row=None, source="pr", em_frame=None):
    """One cell -> dict of numpy arrays ready to pack. em_frame: (centre_nm, R 3x3) block frame."""
    t0 = time.time()
    sid = int(sid)
    if source == "pr":
        P, R, C, PAR, FR = load_swc(h, sid)
        # H01's subcompartment labels are sparse (a fifth of the nodes); the cell's own synapses add seeds before the
        # labels are propagated along the tree: a node under one of its presynaptic sites is axon, under an incoming
        # synapse dendrite (explicit H01 labels are never overridden)
        pre_nm, post_nm = synapses_for(h, sid)
        from scipy.spatial import cKDTree
        tree = cKDTree(P)
        for pts, cls in ((pre_nm, 0), (post_nm, 1)):
            if len(pts):
                dd, jj = tree.query(pts, workers=-1)
                for d_, j_ in zip(dd, jj):
                    if d_ <= 1500.0 and C[j_] == -1:
                        C[j_] = cls
        CL = propagate(C, PAR, len(P))
        CL = adopt_axon_fragments(P, C, CL, FR)
        soma_nodes = np.where(CL == 3)[0]
        soma_nm = soma_centre(P, R, soma_nodes)
        if len(soma_nodes):                                   # the soma's fragment is rooted at the soma, so path distances start there
            PAR = reroot(PAR, int(soma_nodes[np.argmin(np.linalg.norm(P[soma_nodes] - soma_nm, axis=1))]))
        PAR = bridge_axon_fragments(P, CL, PAR, FR, soma_nm)
        D, T = time_pulse(P, R, CL, PAR, soma_nm)
        lod = 2 if role in ("focus", "hero") else 3
        V, F = h.mesh("pr", sid, lod)
    else:                                             # glia from c3: mesh only
        lod = 3
        V, F = h.mesh("c3", sid, lod)
        soma_nm = np.array([float(soma_table_row["x"]), float(soma_table_row["y"]), float(soma_table_row["z"])]) * SYN_NM
        P = R = CL = PAR = D = T = None
    if tris and P is not None:
        V2, F2 = decimate_split(V, F, tris, P, CL)
    else:
        V2, F2 = decimate(V, F, tris) if tris else (V.astype(np.float32), F.astype(np.int64))
    # per-vertex binding to the skeleton
    if P is not None:
        j = nearest_nodes(P, V2)
        vk = np.array([KIND.get(int(c), 2) for c in CL], np.uint8)[j]
        vd = D[j]; vt = T[j]
    else:
        vk = np.full(len(V2), 9, np.uint8); vd = np.zeros(len(V2)); vt = np.full(len(V2), -1.0)      # 9: glia
    return dict(sid=sid, role=role, V=V2, F=F2, vk=vk, vd=vd, vt=vt, P=P, R=R, CL=CL, PAR=PAR, D=D, T=T, soma_nm=soma_nm,
                lod=lod, src_faces=len(F), ms=round((time.time() - t0) * 1000))


_SYN = {}
def synapses_for(h, sid):
    if not _SYN:
        txt = h.text("synapse_locations.csv", f"{HTTP}/proofread_104/synapse_locations.csv")
        for row in csv.reader(io.StringIO(txt)):
            if row and row[0].isdigit() and row[2].replace(".", "").isdigit():
                _SYN.setdefault((row[0], row[1]), []).append([float(row[2]), float(row[3]), float(row[4])])
    pre, post = _SYN.get((str(sid), "pre"), []), _SYN.get((str(sid), "post"), [])
    return np.array(pre).reshape(-1, 3) * SYN_NM, np.array(post).reshape(-1, 3) * SYN_NM


class Blob:
    def __init__(self):
        self.parts = []; self.n = 0
    def add(self, arr):
        pad = (-self.n) % 4                                   # typed-array views need offsets aligned to their element size
        if pad:
            self.parts.append(b"\0" * pad); self.n += pad
        b = np.ascontiguousarray(arr).tobytes(); off = self.n; self.parts.append(b); self.n += len(b); return off
    def bytes(self):
        return b"".join(self.parts)


def tags_of(props):
    ids, tags, vals = props["inline"]["ids"], props["inline"]["properties"][0]["tags"], props["inline"]["properties"][0]["values"]
    return {i: [tags[v] for v in vv] for i, vv in zip(ids, vals)}


def pack_set(name, spec, lodname, h, props, somas, frame, cells_desc, out_dir):
    """Write <name>_<lodname>.json + .bin.gz. frame: (centre_nm, R (3x3, nm->block um/1000)). cells_desc: list of
    (sid, role, source, soma_row)."""
    counts = COUNTS[lodname]; tri = TRI[lodname]
    blob = Blob(); manifest_cells = []
    c0, Rm = frame
    to_block = lambda Pnm: ((Pnm - c0) @ Rm.T) / 1000.0           # um in the block frame
    n_role = {"hero": 0, "mid": 0, "far": 0, "glia": 0}
    TAGS = tags_of(props)
    lateral = {"hero": 0, "mid": 0, "far": 0, "glia": 0}
    for sid, role, source, soma_row in cells_desc:
        r = "hero" if role == "focus" else role
        if r != "hero" or role != "focus":
            if n_role[r] >= counts[r]:
                continue
            n_role[r] += 1
        cell = build_cell(h, sid, role, None if role == "far" else tri[role if role in tri else "mid"], soma_row, source)
        soma_b = to_block(cell["soma_nm"])
        # the focus cell keeps its true place; the others keep their orientation and slab depth (z), are spread
        # sideways (x) and brought toward the focus cell's depth (y: a quarter of the real depth difference is kept,
        # so deeper layers still sit lower; the field is ~400 um and layer 5 lies ~1 mm below layer 2)
        if role == "focus":
            shift = np.zeros(3)
        else:
            k = lateral[r]; lateral[r] += 1
            spread = {"hero": 170, "mid": 260, "far": 300, "glia": 120}[r]
            x_target = ((k + 1) // 2) * spread * (1 if k % 2 else -1) + (35 if r == "mid" else 0)
            y_target = float(np.clip(soma_b[1] * 0.25, -220, 220)) + (-60 if r == "glia" else 0)
            shift = np.array([x_target - soma_b[0], y_target - soma_b[1], 0.0])
        entry = {"id": str(sid), "role": role, "source": "H01 proofread_104" if source == "pr" else "H01 c3 segmentation (automated)",
                 "soma": [round(float(x), 1) for x in (soma_b + shift)], "shift_um": [round(float(x), 1) for x in shift],
                 "lod": cell["lod"], "faces_source": int(cell["src_faces"]), "faces": 0 if role == "far" else int(len(cell["F"])),
                 "tags": TAGS.get(str(sid), [soma_row["celltype"].lower(), soma_row["layer"]] if soma_row else [])}
        if role != "far":
            Vb = to_block(cell["V"]) + shift
            lo, hi = Vb.min(0), Vb.max(0)
            entry["bbox"] = [[round(float(x), 2) for x in lo], [round(float(x), 2) for x in hi]]
            q = quant(Vb, lo, hi)
            idx_t = np.uint16 if len(Vb) < 65536 else np.uint32
            entry["mesh"] = {"pos": blob.add(q), "nv": int(len(Vb)), "idx": blob.add(cell["F"].astype(idx_t)), "nf": int(len(cell["F"])),
                             "idx_t": "u16" if idx_t is np.uint16 else "u32",
                             "kind": blob.add(cell["vk"]), "dist": blob.add(np.clip(cell["vd"] * 10, 0, 65535).astype(np.uint16)),
                             "arrive": blob.add(np.where(cell["vt"] < 0, 65535, np.clip(cell["vt"] * 1000, 0, 65534)).astype(np.uint16))}
        if cell["P"] is not None:
            Pb = to_block(cell["P"]) + shift
            kinds_all = np.array([KIND.get(int(c), 2) for c in cell["CL"]], np.uint8)
            cls = cell["CL"]
            entry["classes"] = {H01_CLASS.get(int(c), str(c)): int((cls == c).sum()) for c in np.unique(cls)}
            seglen = np.array([np.linalg.norm(cell["P"][i] - cell["P"][cell["PAR"][i]]) / 1000.0 if cell["PAR"][i] >= 0 else 0.0 for i in range(len(Pb))])
            entry["myelinated_um"] = round(float(seglen[kinds_all == 4].sum()), 1)
            entry["axon_um"] = round(float(seglen[np.isin(kinds_all, (1, 4, 5))].sum()), 1)
            entry["dend_um"] = round(float(seglen[kinds_all == 2].sum()), 1)
            def thin_skel(keep, within=None, max_um=None, par=None):   # the skeleton thinned to the kept nodes; each kept node's parent = its nearest kept ancestor
                par = cell["PAR"] if par is None else par; newidx = -np.ones(len(Pb), int); newidx[keep] = np.arange(keep.sum())
                anc = np.empty(len(Pb), int)
                for i in range(len(Pb)):
                    p = par[i]
                    while p >= 0 and not keep[p] and (within is None or within[p]):   # the walk may not leave `within` (the axon): no chords
                        p = par[p]                                                     # from an axon branch to a far node of another class
                    if p >= 0 and (not keep[p] or (within is not None and not within[p])):
                        p = -1
                    if p >= 0 and max_um is not None and np.linalg.norm(Pb[i] - Pb[p]) > max_um:
                        p = -1                                                         # a link longer than this would be a straight chord
                    anc[i] = p
                kp = np.where(keep)[0]
                lo, hi = Pb[kp].min(0), Pb[kp].max(0)
                box = [[round(float(x), 2) for x in lo], [round(float(x), 2) for x in hi]]
                return box, {"n": int(len(kp)), "pos": blob.add(quant(Pb[kp], lo, hi)),
                             "kind": blob.add(kinds_all[kp]),
                             "parent": blob.add(np.array([newidx[anc[i]] if anc[i] >= 0 else -1 for i in kp], np.int32)),
                             "dist": blob.add(np.clip(cell["D"][kp] * 10, 0, 65535).astype(np.uint16)),
                             "arrive": blob.add(np.where(cell["T"][kp] < 0, 65535, np.clip(cell["T"][kp] * 1000, 0, 65534)).astype(np.uint16))}
            if role == "far":                                   # drawn as lines: the skeleton, every 4th-5th node
                stride = FAR_STRIDE[lodname]
                keep = np.zeros(len(Pb), bool); keep[::stride] = True; keep[cell["PAR"] < 0] = True
                entry["sbbox"], entry["skel"] = thin_skel(keep)
            if role in ("focus", "hero"):                       # the axon's skeleton as well (axon, AIS, myelinated nodes; the soma node as the root)
                ax = np.isin(kinds_all, (1, 4, 5))
                n_ax = int(ax.sum())
                if n_ax:
                    stride = max(1, int(round(n_ax / AXON_SKEL_NODES[lodname])))
                    idx_ax = np.where(ax)[0]
                    keep = np.zeros(len(Pb), bool); keep[idx_ax[::stride]] = True; keep[cell["PAR"] < 0] = True
                    # branch points and tips of the axon stay, so no branch is lost to the stride
                    nchild = np.bincount(cell["PAR"][cell["PAR"] >= 0], minlength=len(Pb))
                    keep[ax & ((nchild != 1))] = True
                    soma_or_ax = ax | (kinds_all == 0)                 # the bridges to the soma were made in build_cell
                    entry["abbox"], entry["askel"] = thin_skel(keep, within=soma_or_ax, max_um=BRIDGE_UM)
            if role != "far":                                   # the real synapses: this cell's boutons (pre) and inputs (post)
                pre, post = synapses_for(h, sid)
                n_all_post = len(post)
                if len(post) > POST_MAX[role]:
                    post = post[np.random.RandomState(1).choice(len(post), POST_MAX[role], replace=False)]
                if len(pre) + len(post):
                    allp = np.vstack([p for p in (pre, post) if len(p)])
                    Sb = to_block(allp) + shift
                    ax_nodes = np.where(np.isin(kinds_all, (1, 4, 5)))[0]
                    if len(pre) and len(ax_nodes):
                        from scipy.spatial import cKDTree
                        dd, jj = cKDTree(cell["P"][ax_nodes]).query(pre, workers=-1)
                        t_pre = np.where(dd <= 4000.0, cell["T"][ax_nodes[jj]], -1.0)   # a presynaptic site within 4 um of the axon
                    else:
                        t_pre = np.full(len(pre), -1.0)
                    lo2, hi2 = Sb.min(0), Sb.max(0)
                    entry["sbbox"] = [[round(float(x), 2) for x in lo2], [round(float(x), 2) for x in hi2]]
                    entry["syn"] = {"npre": int(len(pre)), "npost": int(len(post)), "npost_all": int(n_all_post), "pos": blob.add(quant(Sb, lo2, hi2)),
                                    "pre_arrive": blob.add(np.where(t_pre < 0, 65535, np.clip(t_pre * 1000, 0, 65534)).astype(np.uint16))}
        manifest_cells.append(entry)
        log(f"  {lodname:7s} {role:5s} {sid} {entry.get('faces', 0):6d} tri (of {entry['faces_source']}) skel {entry.get('skel', {}).get('n', 0):6d} "
            f"syn pre {entry.get('syn', {}).get('npre', 0)} post {entry.get('syn', {}).get('npost', 0)} myelin {entry.get('myelinated_um', 0)} um  {cell['ms']} ms")
    raw = blob.bytes(); gz = gzip.compress(raw, 9)
    (out_dir / f"{name}_{lodname}.bin.gz").write_bytes(gz)
    return manifest_cells, len(raw), len(gz)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--set", default="cortex")
    args = ap.parse_args()
    h = H01(args.offline)
    OUT.mkdir(parents=True, exist_ok=True)
    spec = SETS[args.set]
    props = json.loads(h.text("proofread_104_segment_properties.json", f"{HTTP}/proofread_104/segment_properties/info"))
    somas = list(csv.DictReader(io.StringIO(h.text("somas.csv", f"{HTTP}/c3/tables/somas.csv"))))
    axis, sign = layer_axis(somas)
    log(f"layer axis: {'xyz'[axis]}, pia toward {'+' if sign > 0 else '-'}{'xyz'[axis]}")
    # the proofread cells' soma positions (from their SWC soma nodes) to choose the focus cell and the others
    used = set()
    focus_cands = pick_cells(props, spec["focus"], used)
    # the focus: the L2 pyramidal with the most skeleton nodes (the most complete arbor)
    best = None
    for sid in focus_cands if not args.quick else focus_cands[:4]:
        P, R, C, PAR, FR = load_swc(h, sid)
        n_ax = int((propagate(C, PAR, len(P)) == 0).sum())
        if best is None or len(P) + 2 * n_ax > best[1]:
            best = (sid, len(P) + 2 * n_ax)
    focus = best[0]; used.add(focus)
    log("focus cell", focus)
    P, R, C, PAR, FR = load_swc(h, focus)
    CL = propagate(C, PAR, len(P)); soma_nm = soma_centre(P, R, np.where(CL == 3)[0])   # the block frame's origin: the focus soma
    # block frame: +y toward the pia along the layer axis, x along the slab, z through the slab
    Rm = np.zeros((3, 3))
    up = np.zeros(3); up[axis] = sign
    Rm[1] = up; Rm[0] = np.array([0.0, 1.0, 0.0]) if axis == 0 else np.array([1.0, 0.0, 0.0]); Rm[2] = np.cross(Rm[0], Rm[1])
    frame = (soma_nm, Rm)
    cells_desc = [(focus, "focus", "pr", None)]
    if not args.quick:
        for sp in spec["hero"]:
            for sid in pick_cells(props, sp, used)[:sp["n"]]:
                used.add(sid); cells_desc.append((sid, "hero", "pr", None))
        for sp in spec["mid"]:
            for sid in pick_cells(props, sp, used)[:sp["n"]]:
                used.add(sid); cells_desc.append((sid, "mid", "pr", None))
        rest = [i for i in props["inline"]["ids"] if i not in used]
        for sid in rest[:spec["far"]]:
            used.add(sid); cells_desc.append((sid, "far", "pr", None))
        for ct, n in spec["glia"]:
            rows = [r for r in somas if r["celltype"] == ct and r["layer"] in ("Layer 2", "Layer 3") and r["c3_rep_strict"] not in ("NULL", "")]
            sized = []                                          # the largest segments among a few candidates: whole cells, not fragments
            for r in rows[5:5 + 4 * n]:
                try:
                    V, F = h.mesh("c3", int(r["c3_rep_strict"]), 3); sized.append((len(F), r))
                except Exception as e:
                    log("  glia candidate skipped", r["c3_rep_strict"], repr(e)[:80])
            for _, r in sorted(sized, key=lambda x: -x[0])[:n]:
                cells_desc.append((int(r["c3_rep_strict"]), "glia", "c3", r))
    # the EM backdrop: through the focus soma, at the set's mip
    mip = spec["em_mip"]; px = spec["em_px"]
    vox = soma_nm / np.array(mip, float)
    em, (xs, ys, zs) = h.em(f"em_{args.set}_{focus}_{mip[0]}nm_{px}.u8", mip, int(vox[0] - px / 2), int(vox[1] - px / 2), int(vox[2]), px)
    em_centre_nm = (np.array([xs + px / 2, ys + px / 2, zs], float)) * np.array(mip, float)
    em_centre_block = ((em_centre_nm - soma_nm) @ Rm.T) / 1000.0        # where the image's centre sits in the block (um)
    from PIL import Image
    lo_v, hi_v = np.percentile(em[em > 0], 1), np.percentile(em[em > 0], 99)   # a contrast stretch: the coarse mip is flat grey
    em = np.clip((em.astype(np.float32) - lo_v) / max(1.0, hi_v - lo_v) * 255, 0, 255).astype(np.uint8)
    img = Image.fromarray(em)
    img = img.resize((px // 2, px // 2), Image.Resampling.BOX)          # 64 nm -> 128 nm per pixel: half the bytes, the look kept
    if axis == 0:                                     # pia along x: turn the image so the pia is up
        img = img.transpose(Image.Transpose.ROTATE_90)
    if sign > 0 and axis == 1:
        img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    img.save(OUT / f"{args.set}_em.jpg", quality=40)
    em_entry = {"file": f"{args.set}_em.jpg", "nm_per_px": mip[0] * 2, "px": px // 2, "um": round(px * mip[0] / 1000.0, 1),
                "centre": [round(float(x), 1) for x in em_centre_block], "note": "a real SEM image of the same tissue (the 4 nm volume at its 64 nm mip) through the focus cell's soma"}
    sizes = {}
    manifest = {"v": 1, "set": args.set, "units": "um", "source": "H01", "cite": CITE, "license": LICENSE, "bucket": BUCKET,
                "frame": {"pia": "+y", "centre_nm": [round(float(x), 1) for x in soma_nm], "R": Rm.tolist(), "layer_axis": "xyz"[axis]},
                "slowdown": SLOWDOWN, "speeds": {"unmyelinated_m_s": V_UNMYELINATED, "myelinated_m_s_per_um": HURSH, "g_ratio": G_RATIO, "internode_um": INTERNODE_UM},
                "em": em_entry, "lods": {}}
    for lodname in ("desktop", "phone"):
        cells, raw, gz = pack_set(args.set, spec, lodname, h, props, somas, frame, cells_desc, OUT)
        manifest["lods"][lodname] = {"file": f"{args.set}_{lodname}.bin.gz", "bytes": gz, "raw_bytes": raw, "cells": cells,
                                     "triangles": int(sum(c.get("faces", 0) for c in cells))}
        sizes[lodname] = gz
    (OUT / f"{args.set}.json").write_text(json.dumps(manifest, separators=(",", ":")))
    em_bytes = (OUT / f"{args.set}_em.jpg").stat().st_size
    for lodname, gz in sizes.items():
        tot = gz + em_bytes + (OUT / f"{args.set}.json").stat().st_size
        log(f"{args.set} {lodname}: {gz / 1e6:.2f} MB cells + {em_bytes / 1e6:.2f} MB EM + manifest = {tot / 1e6:.2f} MB "
            f"({'OK' if tot <= 3e6 else 'OVER'} the 3 MB budget), {manifest['lods'][lodname]['triangles']} triangles")


if __name__ == "__main__":
    main()
