"""The zoom (#99): the whole brain -> a cortical column at true size -> the tissue block (NeuronRender, #99 A).

The column's layers are H01's, measured from its public layer annotation (analysis/h01_layers.py ->
docs/spiking/h01_layers.json); its cells are real NeuroMorpho.Org reconstructions at true size, a sparse label of the
neurons H01's density puts there; pyramidal cells stand along the outward cortical normal, the human L5 pyramid's tuft
ends in L1, nothing crosses the pia; only the column's region's spikes light it. The page: a true scale bar, honest
captions, the handoff to NeuronRender.openAt when it exists. The column runs in node with a THREE stub
(tests/js/neuron_zoom_check.js)."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
H01 = json.loads((ROOT / "docs" / "spiking" / "h01_layers.json").read_text())


@pytest.fixture(scope="module")
def check():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    out = subprocess.run([node, str(ROOT / "tests" / "js" / "neuron_zoom_check.js")], capture_output=True, text=True,
                         check=True, timeout=120).stdout
    return json.loads(out)


def test_layers_are_h01s_measurement(check):
    assert H01["license"] == "CC BY 4.0" and "Shapson-Coe" in H01["paper"] and "eadk4858" in H01["paper"]
    assert [[k, v] for k, v in H01["thickness_um"].items()] == check["layersUm"]          # the page uses the measurement
    assert check["neuronsMm3"] == H01["neurons_per_mm3"] == 16000
    assert 1500 < H01["total_um"] < 3500                                                  # human cortex: ~1.5-3.5 mm
    plan = check["plan"]
    assert plan["thickness"] == H01["total_um"] and plan["widthUm"] == 500
    assert 6000 < plan["neurons"] < 8000 and 150 < plan["drawn"] < 260                   # ~3 % drawn, like a Golgi stain
    assert all(L["drawn"] >= 1 for L in plan["layers"])
    tops = [L["top"] for L in plan["layers"]]
    assert tops == sorted(tops) and plan["layers"][0]["top"] == 0


def test_column_at_true_size_along_the_normal(check):
    i = check["info"]
    assert i["drawn"] == check["plan"]["drawn"] and i["segments"] <= 90 * i["drawn"] and check["segmentsPerCell"] <= 90
    assert i["drawCalls"] == len(i["types"]) + 2 <= 6                                     # a call a type + somata + layers
    assert "column-somata" in check["children"] and "column-layers" in check["children"]
    assert all(abs(a - b) < 1e-3 for a, b in zip(check["up"], check["normal"]))           # +y (toward the pia) = normal
    assert all(abs(a - b) < 1e-6 for a, b in zip(check["at0"], check["pos"]))             # depth 0: the pia point
    deep = [p - 1.0 * n for p, n in zip(check["pos"], check["normal"])]                   # 1000 um = 1 mm, true size
    assert all(abs(a - b) < 1e-3 for a, b in zip(check["at1"], deep))


def test_cells_sit_in_their_layers_and_tufts_reach_l1(check):
    plan = {L["name"]: L for L in check["plan"]["layers"]}
    l1 = plan["L1"]["bottom"]
    l5 = [c for c in check["cells"] if c["t"] == "l5_pyramidal"]
    assert len(l5) >= 20 and all(c["layer"] == "L5" for c in l5)
    assert all(0 < c["tip"] < l1 for c in l5)                                             # each tuft ends in L1
    pyr = [c for c in check["cells"] if "pyramidal" in c["t"]]
    assert min(c["tip"] for c in pyr) > 0                                                  # nothing crosses the pia
    for c in check["cells"]:
        L = plan[c["layer"]]
        assert L["top"] <= c["depth"] <= max(L["bottom"], c["depth"] - c["tip"] + 15 + 1e-6) or c["t"] != "l5_pyramidal"
    assert {c["t"] for c in check["cells"]} == {"pyramidal", "basket", "l5_pyramidal"}


def test_only_its_regions_spikes_light_it(check):
    assert check["spiking_offline"] == 0 and check["spiking_other"] == 0 and check["spiking_own"] > 0


def test_page_zoom_wiring_and_honesty():
    html = (ROOT / "web" / "index.html").read_text()
    js = (ROOT / "web" / "neurons3d.js").read_text()
    assert "Neurons3D.column(" in html and "zoomStart(" in html and "zoomFrame(" in html and 'id="n3dive"' in html
    assert "column_morph.json" in html                                                    # lazy: loaded when the zoom starts
    assert "NeuronRender.openAt" in html and "worldPos: zoom.pos, normal: zoom.normal" in html   # the handoff (#99 A)
    assert "NeuronRender.prefetch" in html and "window.zoomBrain" in html
    assert "n3scale" in html and "true scale" in html and "cells drawn ~" in html            # the scale bar says what it measures
    honest = re.search(r'const N3_COLUMN_HONEST = "([^"]+)"', html).group(1)
    for words in ("real data from named public datasets", "NeuroMorpho.Org", "H01", "Shapson-Coe et al. 2024", "CC BY 4.0",
                  "true size", "simulated", "point neurons", "A model, not a mind"):
        assert words in honest, words
    for text in (html.lower(), js.lower()):
        assert "scanned person's neurons" not in text and "his real neurons" not in text
    assert "lightSheet(" in js and "uZoom" in js                                           # optics in the shaders, no post pass


def test_credits():
    about = re.sub(r"\s+", " ", (ROOT / "web" / "about.html").read_text())
    md = re.sub(r"\s+", " ", (ROOT / "docs" / "spiking" / "morphology_credits.md").read_text())
    col = json.loads((ROOT / "web" / "column_morph.json").read_text())
    c = col["cells"]["l5_pyramidal"]
    assert c["nmo_id"] == "NMO_159993" and c["species"] == "human" and c["license"] == "CC BY 4.0"
    assert c["nmo_id"] in about and c["nmo_id"] in md and c["paper"] in md and "Moradi Chameh" in about
    assert "H01" in about and "Shapson-Coe" in about and "eadk4858" in about and "CC BY 4.0" in about
    assert c["box"][4] > 1400                                                              # its apical really reaches ~1.5 mm
