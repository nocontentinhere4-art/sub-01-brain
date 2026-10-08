"""Offline builder for twin/data/receptors_214.csv (component: neurochem).

Part of a digital twin model of one real person's brain structure and recorded activity; not a mind, not
conscious, not the person. Receptor maps are *group* data from post-mortem brains, not this person's.

Source (permissive, see twin/data/RECEPTORS_SOURCES.md):
  Zilles K, Palomero-Gallagher N (2017) Multiple transmitter receptors in regions and layers of the human cerebral
  cortex. Front. Neuroanat. 11:78, doi:10.3389/fnana.2017.00078 (CC BY 4.0), Supplementary Table 2 -
  quantitative in-vitro receptor autoradiography, mean density over all layers in fmol/mg protein, 44 cortical
  areas. File mirrored in AlGoulas/receptor_principles (MIT licence), pinned commit below.
Parcel geometry: Schaefer et al. 2018 Cereb. Cortex 28:3095, 200 parcels / 7 networks, MNI centroids from
  ThomasYeoLab/CBIG (MIT licence), pinned commit below.

NOT used (non-commercial licence CC BY-NC-SA 4.0): netneurolab/hansen_receptors and the neuromaps PET annotations.

Mapping 44 areas -> 200 Schaefer parcels: each area gets an APPROXIMATE MNI centroid (hand-set from standard
cytoarchitectonic/Brodmann anatomy, see AREA_MNI - this is the weakest link, +-10-15 mm), both hemispheres share
the same values (the table pools hemispheres), and each parcel takes an inverse-distance-weighted mean of its
K=3 nearest areas (power 2) using |x|. Parcels whose nearest area is > EXTRAP_MM away are flagged "extrapolated".
The 14 Harvard-Oxford subcortical regions get NO data (blank) - autoradiography table is cortex only; the runtime
applies a flagged neutral fallback (see twin/neurochem.py).

Usage:  python -m twin.build_receptors [--xlsx PATH] [--centroids PATH]
"""
import argparse
import csv
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = HERE / "data"

GOULAS_COMMIT = "1a8b8714271d99ffe62f81f93ac42f3e57c952f1"
XLSX_URL = (f"https://raw.githubusercontent.com/AlGoulas/receptor_principles/{GOULAS_COMMIT}"
            "/recept_data/ReceptData.xlsx")
CBIG_COMMIT = "35b5664bec8822e2f77da5e090e96f91d0095be6"
CENTROID_URL = (f"https://raw.githubusercontent.com/ThomasYeoLab/CBIG/{CBIG_COMMIT}/stable_projects/"
                "brain_parcellation/Schaefer2018_LocalGlobal/Parcellations/MNI/Centroid_coordinates/"
                "Schaefer2018_200Parcels_7Networks_order_FSLMNI152_1mm.Centroid_RAS.csv")

# receptor (Zilles table name) -> column name used here
USED = {"D1": "D1", "5-HT1a": "5HT1a", "5-HT2": "5HT2", "a1": "a1", "a2": "a2", "M1": "M1", "a4b2": "a4b2"}
_ASCII = str.maketrans({"\u2081": "1", "\u2082": "2", "\u2083": "3", "\u2084": "4", "\u1d00": "a", "\u1d03": "b",
                        "\u03b1": "a", "\u03b2": "b"})     # M\u2081 -> M1, \u03b1\u2084\u03b2\u2082 -> a4b2, 5-HT\u2081\u1d00 -> 5-HT1a

# Approximate MNI (x, y, z) of each Zilles area, left hemisphere. Hand-set from standard anatomy (Brodmann /
# Julich-Brain nomenclature); NOT from a probabilistic atlas. 37B/37L/37M read as basal/lateral/medial parts of
# area 37; 5L/5M lateral/medial area 5; PFt/PFm/PGa/PGp inferior parietal areas (Caspers et al. 2006).
AREA_MNI = {
    "1": (-48, -26, 52), "2": (-44, -34, 50), "3a": (-34, -24, 50), "3b": (-40, -24, 50),
    "V1": (-10, -88, 4), "V2d": (-10, -92, 18), "V2v": (-12, -82, -8), "V3A": (-24, -86, 26),
    "V3d": (-18, -94, 20), "V3v": (-24, -82, -12), "V4v": (-30, -78, -14),
    "FG1": (-30, -66, -14), "FG2": (-42, -66, -16),
    "37B": (-40, -50, -20), "37L": (-50, -64, 0), "37M": (-30, -50, -12),
    "41": (-42, -24, 8), "42": (-58, -24, 10), "20": (-52, -24, -26), "21": (-60, -30, -8),
    "22": (-58, -28, 4), "36": (-28, -18, -30), "38": (-38, 14, -32),
    "5L": (-28, -46, 62), "5M": (-10, -44, 62),
    "PGa": (-48, -60, 36), "PGp": (-40, -76, 36), "PFt": (-56, -28, 38), "PFm": (-54, -44, 36),
    "24": (-4, 22, 28), "32": (-6, 42, 12), "23": (-4, -32, 32), "31": (-8, -52, 36),
    "4": (-32, -20, 58), "6": (-28, -2, 58), "8": (-28, 22, 50), "9": (-22, 42, 34),
    "10L": (-28, 58, 4), "10M": (-6, 60, 2), "11": (-20, 40, -18),
    "44": (-52, 12, 14), "45": (-50, 28, 10), "46": (-44, 40, 18), "47": (-42, 32, -10),
}
K_NEAREST = 3
IDW_POWER = 2.0
EXTRAP_MM = 20.0


def _fetch(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        with urllib.request.urlopen(url, timeout=60) as r:
            dest.write_bytes(r.read())
    return dest


def read_xlsx_sheet1(path):
    """Minimal stdlib .xlsx reader -> list of rows (list of cell values), sheet1 only."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
    rows = {}
    for c in ET.fromstring(z.read("xl/worksheets/sheet1.xml")).iter(f"{{{ns['m']}}}c"):
        ref = c.get("r")
        col_s, row_s = re.match(r"([A-Z]+)(\d+)", ref).groups()
        col = 0
        for ch in col_s:
            col = col * 26 + ord(ch) - 64
        v = c.find("m:v", ns)
        if v is None:
            is_ = c.find("m:is", ns)
            val = "".join(t.text or "" for t in is_.iter(f"{{{ns['m']}}}t")) if is_ is not None else None
        elif c.get("t") == "s":
            val = shared[int(v.text)]
        elif c.get("t") in ("str", "inlineStr"):
            val = v.text
        else:
            f = float(v.text)
            val = int(f) if f.is_integer() else f
        rows.setdefault(int(row_s), {})[col - 1] = val
    n = max(rows)
    return [[rows.get(r, {}).get(c) for c in range(max(rows.get(r, {0: 0})) + 1)] for r in range(1, n + 1)]


def parse_zilles(rows):
    """-> (areas[44], {receptor: array(44) all-layers density fmol/mg protein})."""
    out, areas = {}, None
    i = 0
    while i < len(rows) - 1:
        r, nxt = rows[i], rows[i + 1]
        if r and isinstance(r[0], str) and nxt and nxt[0] == "Region":
            name = r[0].strip().translate(_ASCII)
            hdr = [str(x).strip() if x is not None else "" for x in nxt]
            col = hdr.index("all layers")
            names, vals = [], []
            j = i + 2
            while len(names) < 44:                      # skip blank rows inside a block
                rr = rows[j]
                j += 1
                if not rr or rr[0] is None or len(rr) <= col or rr[col] is None:
                    continue
                names.append(str(rr[0]).strip())
                vals.append(float(rr[col]))
            if areas is None:
                areas = names
            assert names == areas, f"area order differs in block {name}"
            out[name] = np.array(vals)
            i = j
        else:
            i += 1
    return areas, out


def schaefer_centroids(path, names):
    rows = list(csv.DictReader(open(path)))
    got = [r["ROI Name"] for r in rows]
    if got != names[:200]:
        bad = [(i, a, b) for i, (a, b) in enumerate(zip(got, names)) if a != b][:5]
        raise SystemExit(f"Schaefer order mismatch vs out/atlas_names.json: {bad}")
    return np.array([[float(r["R"]), float(r["A"]), float(r["S"])] for r in rows])


def map_to_parcels(cent, areas):
    A = np.array([AREA_MNI[a] for a in areas], float)
    A[:, 0] = np.abs(A[:, 0])
    P = cent.copy()
    P[:, 0] = np.abs(P[:, 0])
    D = np.linalg.norm(P[:, None, :] - A[None, :, :], axis=2)          # (200, 44) mm
    order = np.argsort(D, axis=1)[:, :K_NEAREST]
    d = np.take_along_axis(D, order, 1)
    w = 1.0 / np.maximum(d, 1.0) ** IDW_POWER
    w /= w.sum(1, keepdims=True)
    return order, d, w


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--xlsx", type=Path, default=None)
    ap.add_argument("--centroids", type=Path, default=None)
    ap.add_argument("--cache", type=Path, default=ROOT / "data" / "cache")
    a = ap.parse_args(argv)
    xlsx = a.xlsx or _fetch(XLSX_URL, a.cache / "ReceptData.xlsx")
    cpath = a.centroids or _fetch(CENTROID_URL, a.cache / "schaefer200_7n_centroids.csv")
    names = json.load(open(ROOT / "out" / "atlas_names.json"))

    areas, dens = parse_zilles(read_xlsx_sheet1(xlsx))
    assert sorted(areas) == sorted(AREA_MNI), set(areas) ^ set(AREA_MNI)
    DATA.mkdir(exist_ok=True)
    with open(DATA / "zilles2017_all_layers.csv", "w", newline="") as f:
        w = csv.writer(f)
        rec = list(dens)
        w.writerow(["area", "mni_x_approx", "mni_y_approx", "mni_z_approx"] + [f"{r} (fmol/mg protein)" for r in rec])
        for j, ar in enumerate(areas):
            w.writerow([ar, *AREA_MNI[ar]] + [f"{dens[r][j]:g}" for r in rec])

    cent = schaefer_centroids(cpath, names)
    order, dist, wts = map_to_parcels(cent, areas)
    cols = list(USED.values())
    with open(DATA / "receptors_214.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["idx", "name", "source", "nearest_area", "nearest_mm", "mni_x", "mni_y", "mni_z"]
                   + [f"{c}_fmol_mg" for c in cols])
        for i, nm in enumerate(names):
            if i < 200:
                src = "autoradiography_idw" + ("_extrapolated" if dist[i, 0] > EXTRAP_MM else "")
                vals = [float(np.dot(wts[i], dens[k][order[i]])) for k in USED]
                w.writerow([i, nm, src, areas[order[i, 0]], f"{dist[i, 0]:.1f}", *[f"{x:g}" for x in cent[i]]]
                           + [f"{v:.1f}" for v in vals])
            else:
                w.writerow([i, nm, "none_subcortical", "", "", "", "", ""] + [""] * len(cols))
    n_ex = int((dist[:, 0] > EXTRAP_MM).sum())
    print(f"wrote {DATA / 'receptors_214.csv'}: 200 cortical parcels ({n_ex} extrapolated > {EXTRAP_MM} mm), "
          f"14 subcortical without data; receptors {cols}")


if __name__ == "__main__":
    main()
