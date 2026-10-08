"""Export nodes, strongest edges and a glass-brain surface for the live page."""
import json

import numpy as np
from nilearn import datasets, plotting, surface

from brain_sim import GROUPS, Brain

b = Brain()
sch = datasets.fetch_atlas_schaefer_2018(n_rois=200, yeo_networks=7, resolution_mm=1)
ho = datasets.fetch_atlas_harvard_oxford("sub-maxprob-thr25-1mm")
sch_names = [str(x.decode() if isinstance(x, bytes) else x) for x in sch.labels if str(x) != "Background"]
sch_xyz = plotting.find_parcellation_cut_coords(sch.maps)
ho_xyz, ho_lab = plotting.find_parcellation_cut_coords(ho.maps, return_label_names=True)
ho_names = list(ho.labels)


def xyz(nm):
    if nm.startswith("7Networks"):
        return sch_xyz[sch_names.index(nm)]
    return ho_xyz[list(ho_lab).index(ho_names.index(nm))]


def group(nm):
    for g, pats in GROUPS.items():
        if any(p in nm for p in pats):
            return g
    return "other"


z = np.load("out/connectome.npz", allow_pickle=True)
all_names = [str(x) for x in z["names"]]
offset = np.array(json.load(open("web/fibres.json"))["offset"])
nodes = []
for nm, c in zip(b.names, b.centroids):
    nodes.append({"name": nm.replace("7Networks_", ""), "group": group(nm),
                  "p": [round(float(v), 1) for v in xyz(nm)],                 # MNI (glass brain)
                  "q": [round(float(v), 1) for v in np.asarray(c) - offset],   # native, same frame as fibres
                  "lab": all_names.index(nm) + 1})                             # atlas label in labels_dwi
W = b.W
iu = np.triu_indices(b.n, 1)
w = W[iu]
top = np.argsort(w)[::-1][:900]
edges = [[int(iu[0][k]), int(iu[1][k]), round(float(w[k] / w[top[0]]), 3)] for k in top]

fs = datasets.fetch_surf_fsaverage("fsaverage5")
mesh = {}
for hemi in ("left", "right"):
    coords, faces = surface.load_surf_mesh(fs[f"pial_{hemi}"])
    mesh[hemi] = {"v": np.round(coords, 1).ravel().tolist(), "f": faces.ravel().tolist()}

json.dump({"nodes": nodes, "edges": edges, "mesh": mesh, "groups": list(GROUPS)},
          open("web/brain.json", "w"), separators=(",", ":"))
print(len(nodes), "nodes", len(edges), "edges")
