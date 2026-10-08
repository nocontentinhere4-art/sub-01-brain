"""Render the SUB-01 connectome as a glass brain for posting."""
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from nilearn import plotting

z = np.load("out/connectome.npz", allow_pickle=True)
W = z["weights"].astype(float)
n = min(W.shape[0], len(z["names"]))
W = W[:n, :n]
keep = np.where(W.sum(1) > 0)[0]
W = np.log1p(W[np.ix_(keep, keep)])
# node positions in MNI space (the glass brain is MNI), taken from the atlases themselves
from nilearn import datasets
sch = datasets.fetch_atlas_schaefer_2018(n_rois=200, yeo_networks=7, resolution_mm=1)
ho = datasets.fetch_atlas_harvard_oxford("sub-maxprob-thr25-1mm")
sch_xyz = plotting.find_parcellation_cut_coords(sch.maps)
ho_xyz, ho_lab = plotting.find_parcellation_cut_coords(ho.maps, return_label_names=True)
ho_names = list(ho.labels)
mni = []
for nm in z["names"][:n]:
    nm = str(nm)
    if nm.startswith("7Networks"):
        mni.append(sch_xyz[[str(x.decode() if isinstance(x, bytes) else x) for x in sch.labels if str(x) != "Background"].index(nm)])
    else:
        mni.append(ho_xyz[list(ho_lab).index(ho_names.index(nm))])
C = np.array(mni)[keep]
strength = W.sum(1)

fig = plt.figure(figsize=(16, 9), facecolor="black")
disp = plotting.plot_connectome(
    W, C, edge_threshold="97%", node_size=12 + 60 * strength / strength.max(),
    node_color=plt.cm.plasma(strength / strength.max()), edge_cmap=plt.cm.cool,
    display_mode="lzr", black_bg=True, figure=fig, alpha=0.55,
    edge_kwargs={"linewidth": 0.8, "alpha": 0.6}, colorbar=False,
)
fig.text(0.5, 0.06, f"SUB-01  ·  {len(keep)} regions  ·  {int(z['weights'].sum() / 2):,} fibres wired",
         color="white", ha="center", fontsize=18, family="monospace")
fig.savefig("out/sub01_connectome.png", dpi=150, facecolor="black")
print("saved out/sub01_connectome.png")
