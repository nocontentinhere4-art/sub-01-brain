"""Build web/neurons_morph.json: real reconstructed neuron shapes for the 3D close-ups (#78).

Six cells from NeuroMorpho.Org (CC BY 4.0; terms: https://neuromorpho.org/useterm.jsp), one per cell type, human
where the database has one with the parts we draw. None of them is from the person whose MRI the brain model is
built from: no data of that person exist at this scale. The simulated network itself uses point neurons; these shapes
are illustrative (the page says so).

    python analysis/build_morphologies.py            # downloads (cached in data/morph_cache/), simplifies, writes
    python analysis/build_morphologies.py --offline  # from the cache only

Access follows NeuroMorpho.Org's terms: the API for metadata and the direct .swc links, with a named user agent.
Each cell is simplified to at most its type's segment budget (<= 300): unbranched paths are reduced with
Ramer-Douglas-Peucker, and when even one segment per path is too many, the shortest terminal branches are pruned
first. Pyramidal cells (cortex, CA1) are turned so the apical dendrite points up (+y, toward the pia / stratum
radiatum). Units: micrometres, soma at the origin.
Writes web/neurons_morph.json and docs/spiking/morphology_credits.md (every cell, its paper, the three citations
NeuroMorpho.Org asks for).
"""
import argparse
import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent.parent
CACHE = HERE / "data" / "morph_cache"
OUT = HERE / "web" / "neurons_morph.json"
CREDITS = HERE / "docs" / "spiking" / "morphology_credits.md"
UA = {"User-Agent": "SUB-01-morphology-builder/1.0 (+https://github.com/nocontentinhere4-art/sub-01)"}
API = "https://neuromorpho.org/api/neuron/id/{}"
SWC = "https://neuromorpho.org/dableFiles/{archive}/CNG%20version/{name}.CNG.swc"

# type -> (NeuroMorpho.Org neuron id, segment budget, axon's share of it, orientation)
CELLS = {
    "pyramidal": (107146, 300, 0.3, "apical"),      # human neocortex L2/3, dendrites + axon complete (Tamas)
    "basket": (107145, 240, 0.55, "none"),          # human neocortex L2/3 fast-spiking basket cell (Tamas)
    "medium_spiny": (10032, 200, 0.1, "none"),      # rat nucleus accumbens shell (no human MSN in the database)
    "relay": (115363, 220, 0.15, "none"),           # rat VPM thalamocortical relay cell (no human relay cell)
    "ca1_pyramidal": (222, 300, 0.25, "apical"),    # rat hippocampus CA1 (no human CA1 cell with dendrites + axon)
    "amygdala_principal": (139102, 240, 0.25, "none"),   # mouse basolateral amygdala principal cell (no human one)
}
# the cortical column of the zoom (#99) only: its own small asset, loaded when the zoom starts
COLUMN_CELLS = {
    # human anterior temporal cortex L5 pyramid, dendrites complete, no axon reconstructed (Valiante): the deep
    # pyramids of the column, whose apical dendrite really reaches toward L1 (~1.5 mm)
    "l5_pyramidal": (159993, 300, 0.0, "apical"),
}
COLUMN_OUT = HERE / "web" / "column_morph.json"
# No Purkinje cell: the cerebellum is not one of the model's 214 regions, and every close-up shows a simulated region.
PAPERS = {   # PubMed esummary, 2026-10-02
    "27536876": "Molnár G, Rózsa M, Baka J et al. (2016) Human pyramidal to interneuron synapses are mediated by "
                "multi-vesicular release and multiple docked vesicles. eLife 5:e18167. doi:10.7554/eLife.18167",
    "16262671": "Spiga S, Puddu MC, Pisano M et al. (2005) Morphine withdrawal-induced morphological changes in the "
                "nucleus accumbens. Eur J Neurosci 22:2332-40. doi:10.1111/j.1460-9568.2005.04416.x",
    "31095552": "Iavarone E, Yi J, Shi Y et al. (2019) Experimentally-constrained biophysical models of tonic and "
                "burst firing modes in thalamocortical neurons. PLoS Comput Biol 15:e1006753. doi:10.1101/512269",
    "8576427": "Ishizuka N, Cowan WM, Amaral DG (1995) A quantitative analysis of the dendritic organization of "
               "pyramidal cells in the rat hippocampus. J Comp Neurol 362:17-45. doi:10.1002/cne.903620103",
    "33941783": "Moradi Chameh H, Rich S, Wang L et al. (2021) Diversity amongst human cortical pyramidal neurons "
                "revealed via their sag currents and frequency preferences. Nat Commun 12:2497. "
                "doi:10.1038/s41467-021-22741-9",
    "32296306": "Hsu TT, Huang TN, Hsueh YP (2020) Anterior commissure regulates neuronal activity of amygdalae and "
                "influences locomotor activity, social interaction and fear memory in mice. Front Mol Neurosci 13:47. "
                "doi:10.3389/fnmol.2020.00047",
}
NMO_CITE = ("NeuroMorpho.Org (RRID:SCR_002145); Tecuatl C, Ljungquist B, Ascoli GA (2024) Accelerating the continuous "
            "community sharing of digital neuromorphology data. FASEB Bioadv 6(7):207-221. doi:10.1096/fba.2024-00048")
KIND = {2: 1, 3: 2, 4: 3}            # SWC type -> kind: 1 axon, 2 (basal) dendrite, 3 apical dendrite


def get(url, retries=4):
    for i in range(retries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read()
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(3 * (i + 1))


def fetch(nid, offline=False):
    CACHE.mkdir(parents=True, exist_ok=True)
    mp, sp = CACHE / f"{nid}.json", CACHE / f"{nid}.swc"
    if not (mp.exists() and sp.exists()):
        if offline:
            raise SystemExit(f"{nid} is not in {CACHE}; run without --offline")
        meta = json.loads(get(API.format(nid)))
        mp.write_text(json.dumps(meta))
        sp.write_bytes(get(SWC.format(archive=meta["archive"].lower(), name=urllib.parse.quote(meta["neuron_name"]))))
    return json.loads(mp.read_text()), sp.read_text(errors="ignore")


def parse_swc(text):
    rows = [ln.split() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    nodes = {}
    for r in rows:
        i, t, x, y, z, rad, p = int(r[0]), int(float(r[1])), float(r[2]), float(r[3]), float(r[4]), float(r[5]), int(r[6])
        nodes[i] = {"t": t, "p": np.array([x, y, z]), "r": rad, "parent": p}
    return nodes


def tree(nodes):
    """Soma nodes merged into one root (id 0) at their mean; children lists; root radius = largest soma radius."""
    soma = [i for i, n in nodes.items() if n["t"] == 1]
    root = np.mean([nodes[i]["p"] for i in soma], axis=0) if soma else nodes[min(nodes)]["p"]
    soma_r = max([nodes[i]["r"] for i in soma] or [5.0])
    pos, typ, kids, par_of = {0: root}, {0: 1}, {0: []}, {}
    for i, n in nodes.items():
        if n["t"] == 1:
            continue
        pos[i], typ[i] = n["p"], n["t"]
        kids.setdefault(i, [])
    for i, n in nodes.items():
        if n["t"] == 1:
            continue
        par = n["parent"]
        par = 0 if (par == -1 or par not in nodes or nodes[par]["t"] == 1) else par
        kids.setdefault(par, []).append(i)
        par_of[i] = par
    return pos, typ, kids, soma_r, par_of


def sections(pos, kids, starts=None):
    """Unbranched paths [start, ..., end] from the root (or `starts`: (node, first child) pairs) or a branch point
    to a branch point or a tip."""
    out, stack = [], list(starts) if starts is not None else [(0, c) for c in kids[0]]
    while stack:
        start, cur = stack.pop()
        path = [start, cur]
        while len(kids.get(cur, [])) == 1:
            cur = kids[cur][0]
            path.append(cur)
        out.append(path)
        stack.extend((cur, c) for c in kids.get(cur, []))
    return out


def rdp(pts, eps):
    """Indices kept by Ramer-Douglas-Peucker on a polyline."""
    if len(pts) < 3:
        return list(range(len(pts)))
    a, b = pts[0], pts[-1]
    ab = b - a
    L = np.linalg.norm(ab)
    d = (np.linalg.norm(np.cross(pts - a, ab), axis=1) / L) if L > 1e-9 else np.linalg.norm(pts - a, axis=1)
    k = int(np.argmax(d))
    if d[k] <= eps:
        return [0, len(pts) - 1]
    left, right = rdp(pts[:k + 1], eps), rdp(pts[k:], eps)
    return left[:-1] + [i + k for i in right]


def path_len(pos, path):
    return float(sum(np.linalg.norm(pos[path[i + 1]] - pos[path[i]]) for i in range(len(path) - 1)))


def prune(pos, kids, n_max, starts=None):
    """Drop the shortest terminal paths until the tree has at most n_max unbranched paths."""
    kids = {k: list(v) for k, v in kids.items()}
    while True:
        secs = sections(pos, kids, starts)
        if not secs:
            return kids
        if len(secs) <= n_max:
            return kids
        tips = [s for s in secs if not kids.get(s[-1])]
        drop = sorted(tips, key=lambda s: path_len(pos, s))[:max(1, (len(secs) - n_max) // 2)]
        for s in drop:
            kids[s[0]] = [c for c in kids[s[0]] if c != s[1]]
            if starts is not None:
                starts = [st for st in starts if st != (s[0], s[1])]


def simplify(pos, kids, budget, starts=None):
    if budget <= 0:
        return [], 0.0
    kids = prune(pos, kids, int(budget * 0.55), starts)
    starts = [st for st in (starts or []) if st[1] in kids.get(st[0], [])] if starts is not None else None
    secs = sections(pos, kids, starts)
    if not secs:
        return [], 0.0
    lo, hi = 0.05, 200.0
    best = None
    for _ in range(40):                                   # the smallest tolerance that fits the budget
        eps = math.sqrt(lo * hi)
        segs = []
        for s in secs:
            keep = rdp(np.array([pos[i] for i in s]), eps)
            segs += [(s[keep[j]], s[keep[j + 1]]) for j in range(len(keep) - 1)]
        if len(segs) <= budget:
            best, hi = (segs, eps), eps
        else:
            lo = eps
    return best


def rot_to(v, target):
    """Rotation matrix taking unit vector v onto unit vector target."""
    v, target = v / np.linalg.norm(v), target / np.linalg.norm(target)
    c = float(np.dot(v, target))
    if c > 1 - 1e-9:
        return np.eye(3)
    if c < -1 + 1e-9:
        return np.diag([1.0, -1.0, -1.0])
    ax = np.cross(v, target)
    s = np.linalg.norm(ax)
    k = ax / s
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + s * K + (1 - c) * K @ K


def orient(P, kinds, how):
    """P: (n, 3) points relative to the soma. Returns the rotation to apply."""
    if how == "none":
        return np.eye(3)
    sel = P[kinds == 3] if (how == "apical" and (kinds == 3).any()) else P[kinds >= 2]
    R = rot_to(sel.mean(0), np.array([0.0, 1.0, 0.0]))
    Q = P @ R.T
    xz = Q[:, [0, 2]] - Q[:, [0, 2]].mean(0)               # turn about y: the flattest direction goes to z
    w, v = np.linalg.eigh(xz.T @ xz)
    major = v[:, 1]
    a = math.atan2(major[1], major[0])
    Ry = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
    return Ry @ R


def build_cell(meta, text, budget, axon_share, how):
    """The axon and the dendrites are simplified apart, each to its share of the budget, so a long axon cannot
    take every segment."""
    nodes = parse_swc(text)
    pos, typ, kids, soma_r, par_of = tree(nodes)
    is_ax = lambda i: typ.get(i) == 2
    kids_ax = {n: [c for c in cs if is_ax(c)] for n, cs in kids.items()}
    kids_de = {n: [c for c in cs if not is_ax(c)] for n, cs in kids.items()}
    ax_starts = [(par_of[c], c) for c in typ if c and is_ax(c) and not is_ax(par_of[c])]
    n_ax = int(round(budget * axon_share)) if ax_starts else 0
    seg_ax, _ = simplify(pos, kids_ax, n_ax, ax_starts)
    seg_de, eps = simplify(pos, kids_de, budget - len(seg_ax))
    segs = seg_de + seg_ax
    root = pos[0]
    kinds_seg = np.array([KIND.get(typ[b], 2) for a, b in segs])
    A = np.array([pos[a] - root for a, b in segs])
    B = np.array([pos[b] - root for a, b in segs])
    R = orient(np.vstack([A, B]), np.concatenate([kinds_seg, kinds_seg]), how)
    A, B = A @ R.T, B @ R.T
    # path distance from the soma along the simplified tree (for the pulse and the dendritic glow)
    dist = {0: 0.0}
    pending = list(range(len(segs)))
    for _ in range(len(segs) + 1):
        nxt = []
        for k in pending:
            a, b = segs[k]
            if a in dist:
                dist[b] = dist[a] + float(np.linalg.norm(pos[b] - pos[a]))
            else:
                nxt.append(k)
        if not nxt:
            break
        if len(nxt) == len(pending):                        # an axon from a pruned dendrite: straight from the soma
            for k in nxt:
                a, b = segs[k]
                dist.setdefault(a, float(np.linalg.norm(pos[a] - pos[0])))
        pending = nxt
    d0 = np.array([dist[a] for a, b in segs])
    d1 = np.array([dist[b] for a, b in segs])
    axon = kinds_seg == 1
    lo, hi = np.vstack([A, B]).min(0), np.vstack([A, B]).max(0)
    return {
        "nmo_id": f"NMO_{meta['neuron_id']:05d}", "neuron_id": meta["neuron_id"], "name": meta["neuron_name"],
        "archive": meta["archive"], "species": meta["species"], "region": meta["brain_region"],
        "cell_type": meta["cell_type"], "integrity": meta["physical_Integrity"], "domain": meta["domain"],
        "n_seg": len(segs), "rdp_um": round(eps, 2), "soma_r": round(float(soma_r), 1),
        "axon_len": round(float(d1[axon].max()) if axon.any() else 0.0, 1),
        "dend_len": round(float(d1[~axon].max()) if (~axon).any() else 0.0, 1),
        "box": [round(float(x), 1) for x in (*lo, *hi)],
        "pos": [round(float(x), 1) for x in np.hstack([A, B]).ravel()],     # x0 y0 z0 x1 y1 z1 per segment
        "kind": kinds_seg.astype(int).tolist(),
        "dist": [round(float(x), 1) for x in np.stack([d0, d1], 1).ravel()],
        "license": "CC BY 4.0", "source": f"https://neuromorpho.org/neuron_info.jsp?neuron_name={meta['neuron_name']}",
        "paper": PAPERS.get((meta.get("reference_pmid") or [""])[0], ", ".join(meta.get("reference_doi") or [])),
    }


def credits_md(cells):
    lines = ["# Neuron shapes: credits (#78)", "",
             "The neurons on `/brain` (the close-ups, the whole-brain view's small cells, simplified further to at most",
             "40 segments and drawn ~6× enlarged, and the cortical column of the zoom, #99, at true size) are real",
             "reconstructions from **NeuroMorpho.Org**, licensed under the",
             "[Creative Commons Attribution 4.0 International License](https://creativecommons.org/licenses/by/4.0/)",
             "([terms](https://neuromorpho.org/useterm.jsp)). They are simplified (at most 300 segments a cell),",
             "rotated and drawn as lines; these are changes to the original data. They are **illustrative**: the",
             "simulated network uses point neurons (no dendrites are simulated), and **none of these cells is from the",
             "person whose MRI the brain model is built from** — no data of that person exist at this scale.", "",
             "Generated by `analysis/build_morphologies.py`; the asset is `web/neurons_morph.json`.", "",
             "| shown as | NeuroMorpho.Org ID | cell | species | region | archive | original paper |",
             "|---|---|---|---|---|---|---|"]
    for k, c in cells.items():
        lines.append(f"| {k.replace('_', ' ')} | [{c['nmo_id']}]({c['source']}) | {c['name']} | {c['species']} | "
                     f"{', '.join(c['region'][:3])} | {c['archive']} | {c['paper']} |")
    lines += ["", "Citations NeuroMorpho.Org asks for, for every cell above: the original paper (table), and",
              NMO_CITE + ".", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    cells, column = {}, {}
    for kind, (nid, budget, axon_share, how) in COLUMN_CELLS.items():
        meta, text = fetch(nid, args.offline)
        column[kind] = build_cell(meta, text, budget, axon_share, how)
    for kind, (nid, budget, axon_share, how) in CELLS.items():
        meta, text = fetch(nid, args.offline)
        cells[kind] = build_cell(meta, text, budget, axon_share, how)
        c = cells[kind]
        print(f"{kind:13s} {c['nmo_id']} {c['species']:6s} {c['n_seg']:4d} segments (RDP {c['rdp_um']} um), "
              f"axon path {c['axon_len']} um, dendrite path {c['dend_len']} um, box {c['box']}")
    out = {"v": 1, "units": "um", "license": "CC BY 4.0 (NeuroMorpho.Org); simplified",
           "note": "Real reconstructed neurons from NeuroMorpho.Org, simplified; illustrative shapes, not from the "
                   "scanned person; the simulated network uses point neurons.",
           "cite": NMO_CITE, "cells": cells}
    OUT.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    COLUMN_OUT.write_text(json.dumps(dict(out, cells=column), separators=(",", ":"), ensure_ascii=False))
    CREDITS.write_text(credits_md({**cells, **column}))
    print(f"wrote {OUT.relative_to(HERE)} ({OUT.stat().st_size / 1024:.0f} KB) and {CREDITS.relative_to(HERE)}")


if __name__ == "__main__":
    main()
