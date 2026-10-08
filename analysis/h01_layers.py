"""Cortical layer thicknesses of the H01 sample (#99), measured from its public layer annotation.

    pip install cloud-volume      # build-time only; the page never loads it
    python analysis/h01_layers.py

H01: Shapson-Coe A, Januszewski M, Berger DR et al. (2024) A petavoxel fragment of human cerebral cortex reconstructed
at nanoscale resolution. Science 384:eadk4858. doi:10.1126/science.adk4858. Data: https://h01-release.storage.googleapis.com
("All released datasets are licensed under a Creative Commons Attribution 4.0 License").

The annotation (gs://h01-release/data/20210601/layers, labels L1-L6 and white matter) is read once at its 8 x 8 x 8.448 um
level (516 x 357 x 21 voxels, ~4.1 x 2.9 x 0.18 mm: the sample is a slab). The cortical depth axis lies in the section
plane, so each layer's thickness is measured in 2D, in three sections (z = 6, 10, 14): the median Euclidean distance
from every pixel of the layer's bottom boundary to its top boundary (for L1, to the pia: the edge of L1 to
outside, ignoring edges within 100 um of the sample's cut faces). The medians of the three sections are written to
docs/spiking/h01_layers.json; web/neurons3d.js H01_LAYERS_UM must match them (tests/test_neuron_zoom.py).
"""
import json
from pathlib import Path

import numpy as np
from scipy import ndimage as nd

HERE = Path(__file__).resolve().parent.parent
OUT = HERE / "docs" / "spiking" / "h01_layers.json"
SRC = "gs://h01-release/data/20210601/layers"


def measure(a, voxel_um=8.0, sections=(6, 10, 14)):
    res = {}
    for z in sections:
        s = a[:, :, z]

        def edge(i, j):
            return (s == i) & nd.binary_dilation(s == j)
        for layer in range(1, 7):
            if layer == 1:
                dt = nd.distance_transform_edt(~edge(1, 0)) * voxel_um
                vals = dt[edge(1, 2)]
                vals = vals[vals > 100]
            else:
                dt = nd.distance_transform_edt(~edge(layer, layer - 1)) * voxel_um
                vals = dt[edge(layer, layer + 1)]
            res.setdefault(layer, []).append(float(np.median(vals)))
    return {f"L{k}": round(float(np.median(v))) for k, v in res.items()}


def main():
    from cloudvolume import CloudVolume
    cv = CloudVolume(SRC, mip=4, use_https=True, progress=False, fill_missing=True)
    assert list(cv.resolution) == [8000, 8000, 8448], cv.resolution
    a = np.asarray(cv[:, :, :])[..., 0].astype(np.int64)
    th = measure(a)
    out = {"source": SRC + " (mip 4: 8 x 8 x 8.448 um)", "license": "CC BY 4.0",
           "paper": "Shapson-Coe A, Januszewski M, Berger DR et al. (2024) Science 384:eadk4858. doi:10.1126/science.adk4858",
           "method": "median boundary-to-boundary distance in sections z = 6, 10, 14 (2D distance transform)",
           "thickness_um": th, "total_um": sum(th.values()),
           "neurons_per_mm3": 16000,
           "neurons_note": "~16k neurons in the ~1 mm3 sample (Shapson-Coe et al., bioRxiv 2021.05.29.446289: 'The number "
                           "of neurons in this human sample is ~16k/1 mm3'); per-layer neuron densities are not used"}
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
