"""Build web/neuron_render/cells.json: the six real NeuroMorpho.Org cells of #78 (CC BY 4.0), this time as branched
polylines WITH THEIR RADII, for the microscopy-grade close-ups of #88 (web/neuron_render/neuron_render.js).

    python analysis/build_neuron_render.py            # downloads (cached in data/morph_cache/, shared with #78), writes
    python analysis/build_neuron_render.py --offline  # from the cache only

Same cells, same access (NeuroMorpho.Org API + direct .swc links, named user agent), same credits
(docs/spiking/morphology_credits.md). None of them is from the person whose MRI the brain model is built from.

Per cell type the asset holds unbranched paths (soma/branch point -> branch point/tip), each a polyline of nodes
x y z r (micrometres), its kind (1 axon, 2 basal dendrite, 3 apical dendrite), its branch order and the path distance
of its first node from the soma; the first node of a path repeats its parent's node so every path is a closed tube.
Budget: <= `nodes` per cell (the renderer strides them for lower levels of detail); the axon is cut to its local arbor
(`axon_reach` um of path from the soma: the human cells' full axons run 24-57 mm) and gets `axon_share` of the budget;
then the shortest terminal branches are pruned and the paths are simplified by Ramer-Douglas-Peucker to the smallest
tolerance that fits.

Radii: taken from the reconstruction where it measured them (`radii: "measured"`: the two human cells, the MSN, the
relay cell, the amygdala cell). The CA1 cell cd2351 (1995) carries one constant radius (0.15 um on nearly every node),
so its thickness is drawn from published typical values instead (`radii: "typical"`): Megias et al. 2001 (CA1
pyramidal: apical trunk ~3 um proximally tapering to ~1 um, oblique and basal dendrites 0.5-1 um), with a linear
taper by path distance. Every radius is clamped to >= 0.1 um (below a pixel in any close-up).
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "analysis"))
import build_morphologies as BM  # noqa: E402  (fetch, parse_swc, tree, sections, rdp, path_len, orient, PAPERS)

OUT = HERE / "web" / "neuron_render" / "cells.json"

# type -> (NeuroMorpho.Org id, node budget, axon's share, axon reach (um of path), orientation, radii, myelinated)
CELLS = {
    "pyramidal": (107146, 1500, 0.30, 900.0, "apical", "measured", True),      # human L2/3 (Tamas)
    "basket": (107145, 1200, 0.45, 450.0, "none", "measured", True),           # human L2/3 basket (Tamas); PV cells are myelinated
    "medium_spiny": (10032, 900, 0.10, 400.0, "none", "measured", False),      # rat accumbens shell (Spiga)
    "relay": (115363, 1200, 0.15, 400.0, "none", "measured", True),            # rat VPM relay (Markram)
    "ca1_pyramidal": (222, 1500, 0.25, 900.0, "apical", "typical", True),      # rat CA1 (Amaral): constant radius in the file
    "amygdala_principal": (139102, 1200, 0.20, 400.0, "none", "measured", True),   # mouse BLA principal (Hsueh)
}
R_MIN = 0.1
# typical radii (um) by kind for cells whose reconstruction has no measured radii: (proximal, distal, taper length um)
TYPICAL = {1: (0.5, 0.3, 300.0), 2: (0.6, 0.25, 250.0), 3: (1.5, 0.4, 400.0)}       # Megias et al. 2001 (CA1)


def cut_reach(pos, kids, par_of, typ, reach, is_kind):
    """Drop every node of `is_kind` beyond `reach` um of path from the soma (and its subtree)."""
    dist = {0: 0.0}
    order = [0]
    for n in order:
        for c in kids.get(n, []):
            dist[c] = dist[n] + float(np.linalg.norm(pos[c] - pos[n]))
            order.append(c)
    kids = {k: list(v) for k, v in kids.items()}
    for n, cs in kids.items():
        kids[n] = [c for c in cs if not (is_kind(c) and dist[c] > reach)]
    return kids


def simplify_paths(pos, kids, budget, starts=None):
    """Prune, then RDP to the smallest tolerance that fits `budget` nodes. Returns [(path node ids kept)], eps."""
    if budget <= 0:
        return [], 0.0
    kids = BM.prune(pos, kids, max(1, int(budget * 0.35)), starts)
    starts = [st for st in (starts or []) if st[1] in kids.get(st[0], [])] if starts is not None else None
    secs = BM.sections(pos, kids, starts)
    if not secs:
        return [], 0.0
    lo, hi, best = 0.05, 200.0, None
    for _ in range(40):
        eps = math.sqrt(lo * hi)
        paths, n = [], 0
        for s in secs:
            keep = BM.rdp(np.array([pos[i] for i in s]), eps)
            p = [s[j] for j in keep]
            paths.append(p)
            n += len(p)
        if n <= budget:
            best, hi = (paths, eps), eps
        else:
            lo = eps
    return best if best else ([], hi)


def build(meta, text, spec):
    nid, budget, axon_share, reach, how, radii, myelinated = spec
    nodes = BM.parse_swc(text)
    pos, typ, kids, soma_r, par_of = BM.tree(nodes)
    rad = {i: n["r"] for i, n in nodes.items()}
    rad[0] = soma_r
    is_ax = lambda i: typ.get(i) == 2
    kids = cut_reach(pos, kids, par_of, typ, reach, is_ax)
    kids_ax = {n: [c for c in cs if is_ax(c)] for n, cs in kids.items()}
    kids_de = {n: [c for c in cs if not is_ax(c)] for n, cs in kids.items()}
    ax_starts = [(par_of[c], c) for c in typ if c and is_ax(c) and not is_ax(par_of[c]) and c in kids.get(par_of[c], [])]
    n_ax = int(round(budget * axon_share)) if ax_starts else 0
    paths_ax, _ = simplify_paths(pos, kids_ax, n_ax, ax_starts)
    paths_de, eps = simplify_paths(pos, kids_de, budget - sum(len(p) for p in paths_ax))
    paths = paths_de + paths_ax
    # orientation from every kept node
    allp = sorted({i for p in paths for i in p})
    P = np.array([pos[i] - pos[0] for i in allp])
    K = np.array([BM.KIND.get(typ.get(i, 3), 2) if i else 0 for i in allp])
    R = BM.orient(P, K, how)
    # path distance from the soma along the kept paths (parents first)
    dist, order_of = {0: 0.0}, {0: 0}
    pend = list(paths)
    for _ in range(len(paths) + 1):
        nxt = []
        for p in pend:
            if p[0] in dist:
                d = dist[p[0]]
                for a, b in zip(p, p[1:]):
                    d += float(np.linalg.norm(pos[b] - pos[a]))
                    dist[b] = d
                order_of[p[-1]] = order_of[p[0]] + 1
            else:
                nxt.append(p)
        if not nxt:
            break
        if len(nxt) == len(pend):                                  # a path whose parent was pruned: hang it on the soma
            for p in nxt:
                dist.setdefault(p[0], float(np.linalg.norm(pos[p[0]] - pos[0])))
                order_of.setdefault(p[0], 1)
        pend = nxt
    out_paths, n_nodes, lens = [], 0, {1: 0.0, 2: 0.0, 3: 0.0}
    for p in paths:
        k = BM.KIND.get(typ[p[-1]], 2)
        arr = []
        for i in p:
            q = (pos[i] - pos[0]) @ R.T
            if radii == "measured":
                r = rad[i] if i else max(rad[p[1]], R_MIN)
            else:
                r0, r1, L = TYPICAL[k]
                r = r1 + (r0 - r1) * max(0.0, 1 - dist[i] / L)
            if i == 0:
                r = max(r, R_MIN)
            arr += [round(float(q[0]), 1), round(float(q[1]), 1), round(float(q[2]), 1), round(float(max(r, R_MIN)), 2)]
        out_paths.append({"k": k, "o": order_of[p[0]], "d0": round(dist[p[0]], 1), "p": arr})
        n_nodes += len(p)
        lens[k] += dist[p[-1]] - dist[p[0]]
    lo, hi = P.min(0) @ R.T, P.max(0) @ R.T
    allq = P @ R.T
    return {
        "nmo_id": f"NMO_{meta['neuron_id']:05d}", "neuron_id": meta["neuron_id"], "name": meta["neuron_name"],
        "archive": meta["archive"], "species": meta["species"], "region": meta["brain_region"],
        "cell_type": meta["cell_type"], "integrity": meta["physical_Integrity"],
        "n_nodes": n_nodes, "n_paths": len(out_paths), "rdp_um": round(eps, 2), "soma_r": round(float(soma_r), 1),
        "radii": radii, "myelinated": myelinated,
        "axon_len": round(lens[1], 1), "dend_len": round(lens[2] + lens[3], 1),
        "box": [round(float(x), 1) for x in (*allq.min(0), *allq.max(0))],
        "paths": out_paths,
        "license": "CC BY 4.0", "source": f"https://neuromorpho.org/neuron_info.jsp?neuron_name={meta['neuron_name']}",
        "paper": BM.PAPERS.get((meta.get("reference_pmid") or [""])[0], ", ".join(meta.get("reference_doi") or [])),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    cells = {}
    for kind, spec in CELLS.items():
        meta, text = BM.fetch(spec[0], args.offline)
        cells[kind] = c = build(meta, text, spec)
        print(f"{kind:18s} {c['nmo_id']} {c['species']:6s} {c['n_nodes']:5d} nodes in {c['n_paths']:4d} paths (RDP {c['rdp_um']} um), "
              f"axon {c['axon_len']:.0f} um, dendrites {c['dend_len']:.0f} um, radii {c['radii']}, soma r {c['soma_r']}")
    out = {"v": 1, "units": "um", "license": "CC BY 4.0 (NeuroMorpho.Org); simplified",
           "note": "Real reconstructed neurons from NeuroMorpho.Org, simplified, with their radii where measured; "
                   "illustrative shapes, not from the scanned person; the simulated network uses point neurons.",
           "cite": BM.NMO_CITE, "cells": cells}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    print(f"wrote {OUT.relative_to(HERE)} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
