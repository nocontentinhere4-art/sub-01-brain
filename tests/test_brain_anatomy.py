"""The brain as a real specimen (#99 G9, web/brain_anatomy.js + web/anatomy/): the assets say what is HIS and what is an
atlas, sit in the page's frame and inside the budget; the renderer (run in node with a THREE stub,
tests/js/brain_anatomy_check.js) swaps the page's materials only while a realistic view is on and restores them, cuts
on the right plane, loads parts lazily, drops to the low tier on a slow frame rate, and every caption carries the
provenance and "A model, not a mind."; the hook in index.html, the credits and /about name the licences."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
ANAT = WEB / "anatomy"
BUDGET_MB = 6.0
ATTR = "BodyParts3D, © The Database Center for Life Science licensed under CC Attribution 4.0 International"


@pytest.fixture(scope="module")
def meta():
    return json.loads((ANAT / "anatomy.json").read_text())


@pytest.fixture(scope="module")
def check():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, str(ROOT / "tests" / "js" / "brain_anatomy_check.js")], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


# --- assets -------------------------------------------------------------------------------------------------------
def test_assets_within_budget_and_lazy():
    files = [p for p in ANAT.iterdir() if p.is_file() and p.suffix != ".md"]
    total = sum(p.stat().st_size for p in files)
    assert total <= BUDGET_MB * 1024 * 1024, f"{total / 1e6:.1f} MB"
    html = (WEB / "index.html").read_text()
    assert "/brain_anatomy.js" in html and '<script src="/brain_anatomy.js"' not in html   # injected on the first click, never at load
    assert "/anatomy/" in html


def test_his_meshes_sit_inside_his_brain(meta):
    cortex = np.fromfile(WEB / "cortex.bin", dtype=np.float32).reshape(-1, 3)
    lo, hi = cortex.min(0), cortex.max(0)
    for name in ("cerebellum", "brainstem"):
        v = np.fromfile(ANAT / f"{name}.bin", dtype=np.float32).reshape(-1, 3)
        info = meta["meshes"][name]
        f = np.fromfile(ANAT / f"{name}_idx.bin", dtype=np.uint16 if info["idx_type"] == "uint16" else np.uint32)
        assert info["source"] == "his MRI" and len(v) == info["verts"] and len(f) == 3 * info["faces"]
        assert f.max() < len(v) and len(f) >= 3 * 5000
        below = 25 if name == "brainstem" else 6                                      # cortex.bin stops above the medulla
        assert np.all(v.min(0) >= lo - [6, 6, below]) and np.all(v.max(0) <= hi + 6), name   # in the page's frame, within his brain
        assert v[:, 2].mean() < cortex[:, 2].mean()                                   # below the cerebrum
    assert np.fromfile(ANAT / "cortex_part.bin", dtype=np.uint8).shape == (len(cortex),)
    parts = meta["meshes"]["cortex_part"]
    assert parts["cerebrum"] > parts["cerebellum"] > parts["brainstem"] > 100


def test_cut_volume_is_his_t1_in_the_page_frame(meta):
    from PIL import Image
    vol = meta["volume"]
    img = Image.open(ANAT / "t1_atlas.png")
    assert img.mode == "LA" and img.size == (vol["cols"] * vol["shape"][0], vol["rows"] * vol["shape"][1])   # grey: his T1; alpha: a soft brain mask
    assert vol["cols"] * vol["rows"] >= vol["shape"][2] and vol["step_mm"] == 2.0 and vol["source"] == "his MRI"
    t = vol["tissue"]
    assert 0 < t["csf"] < t["grey"] < t["white"] < 1                                  # his own landmarks, in byte units
    M = np.array(vol["web_to_vox"]).reshape(4, 4)
    cortex = np.fromfile(WEB / "cortex.bin", dtype=np.float32).reshape(-1, 3)
    ctr = np.append(cortex.mean(0), 1.0)
    vox = M @ ctr
    assert np.all(vox[:3] > 0) and np.all(vox[:3] < np.array(vol["shape"]) - 1)        # the brain's centre is inside the volume
    a = np.asarray(img)
    nx, ny = vol["shape"][:2]
    k = int(round(vox[2]))
    tile = a[(k // vol["cols"]) * ny:(k // vol["cols"] + 1) * ny, (k % vol["cols"]) * nx:(k % vol["cols"] + 1) * nx]
    assert tile[int(round(vox[1])), int(round(vox[0])), 1] > 200                       # inside his brain mask there
    assert 0.08 < (a[..., 1] > 127).mean() < 0.5                                       # the tiles hold brain, not padding
    assert len(np.unique(a[..., 1])) > 20                                              # the mask is soft (no 2 mm steps on the cut's edge)


def test_atlas_parts_are_labelled_fitted_and_credited(meta):
    p = meta["parts"]
    assert p["attribution"] == ATTR and "CC BY 4.0" in p["licence"]
    assert 0 < p["fit"]["rms_mm"] < 4.0 and 0.7 < p["fit"]["scale"] < 1.3                # one similarity transform, a close fit
    kinds = {r["kind"] for r in p["parts"]}
    assert {"artery", "nerve", "gland", "cord", "vein"} <= kinds
    labels = " ".join(r["label"] for r in p["parts"])
    for name in ("internal carotid", "anterior cerebral", "middle cerebral", "posterior cerebral", "communicating", "basilar",
                 "vertebral", "optic nerve", "optic chiasm", "trochlear", "pituitary", "spinal cord", "sinuses"):
        assert name in labels, name
    for r in p["parts"]:
        assert r["source"].startswith("atlas (")
    for missing in ("olfactory (I)", "vagus (X)", "hypoglossal (XII)"):
        assert missing in p["not_in_atlas"]                                           # said, not invented
    assert "VENAT" in p["venat"]["attribution"] and p["venat"]["licence"] == "CC BY 4.0"
    blob = (ANAT / p["file"]).read_bytes()
    cortex = np.fromfile(WEB / "cortex.bin", dtype=np.float32).reshape(-1, 3)
    lo, hi = cortex.min(0), cortex.max(0)
    for r in p["parts"]:
        v = np.frombuffer(blob, dtype=np.int16, count=r["verts"] * 3, offset=r["pos"]).reshape(-1, 3) * p["unit_mm"]
        assert np.all(v.min(0) > lo - 80) and np.all(v.max(0) < hi + 40), r["label"]   # around his brain (the neck stub below)
        assert r["pos"] % 4 == 0 and r["idx"] % 4 == 0
    arteries = [r for r in p["parts"] if r["kind"] == "artery"]
    assert sum(r["pressed"] for r in arteries) > 500                                   # cortical branches pressed onto his surface


# --- the renderer in node --------------------------------------------------------------------------------------------
def test_parts_parse_and_sit_around_his_brain(check):
    bb = check["cortex_bbox"]
    for pr in check["parts"]:
        assert pr["bad_indices"] == 0 and pr["tris"] > 20
        assert all(pr["min"][k] > bb["min"][k] - 80 and pr["max"][k] < bb["max"][k] + 40 for k in range(3)), pr["label"]


def test_sulcal_depth_from_his_own_mesh(check):
    s = check["sulcal"]
    assert s["n"] == 61954 and s["min"] == 0 and s["max"] == 1
    assert 0.1 < s["mean"] < 0.6 and 0.05 < s["frac_deep"] < 0.5                        # gyral crowns and sulcal floors, both
    assert s["ms"] < 4000


def test_cut_plane_maths(check):
    c = check["cut"]
    bb = check["cortex_bbox"]
    assert c["coronal"]["n"] == [0, 1, 0] and abs(c["coronal"]["value_mm"] - (bb["min"][1] + bb["max"][1]) / 2) < 1e-6
    assert c["sagittal"]["n"] == [-1, 0, 0] and c["sagittal"]["d"] == -c["sagittal"]["value_mm"]
    assert c["axial"]["n"] == [0, 0, 1] and c["axial"]["value_mm"] == bb["max"][2]
    assert c["bogus"]["axis"] == "coronal" and c["bogus"]["value_mm"] == bb["max"][1]    # clamped, defaulted
    t = check["tissue"]
    assert t["csf"][0] < t["grey"][0] < t["white"][0] and t["grey"][0] < t["mid"][0] < t["white"][0]


def test_views_swap_and_restore_the_pages_materials(check):
    v = check["views"]
    assert v["fresh"]["cortexMat"] == "swapped" and v["fresh"]["fibresMat"] == "swapped" and v["fresh"]["meshes"] is True
    assert {"his_cerebellum", "his_brainstem"} <= set(v["fresh"]["drawn"]) and "cut_cap" not in v["fresh"]["drawn"]
    assert sorted(v["fresh"]["cortexPart"]) == [0, 1, 2, 3]                             # his cortex vertices carry their part (0: a crumb, not drawn)
    assert v["fresh"]["winding"] == -1 and v["fresh"]["fibresDrawn"] is False             # cortex.bin is wound clockwise: handled; no fibre ends poking through
    assert v["bundles"]["fibresDrawn"] is True and v["glow"]["fibresDrawn"] is True
    assert v["bundles"]["bundleShared"] is True                                          # the page's own stage / activity / pulse uniforms drive the bundles
    assert v["fixed"]["cut"] is True and "cut_cap" in v["fixed"]["drawn"]
    assert v["bundles"]["cortexMat"] == "swapped" and v["bundles"]["fibresMat"] == "swapped" and v["bundles"]["cut"] is False
    assert "his_cerebellum" not in v["bundles"]["drawn"]
    assert v["glow"]["cortexMat"] == "orig" and v["glow"]["fibresMat"] == "orig" and v["glow"]["drawn"] == []
    assert v["back"]["cortexMat"] == "orig" and v["back"]["fibresMat"] == "orig"
    assert v["disposed"]["inScene"] == 0 and v["disposed"]["dpr"] == 2


def test_layers_load_atlas_parts_lazily(check):
    v = check["views"]
    assert v["fresh"]["drawn"].count("atlas_artery") == 0                                 # nothing atlas until a layer is on
    d = v["layers"]["drawn"]
    assert v["layers"]["parts"] is True and "atlas_artery" in d and "atlas_nerve" in d and "atlas_vein" in d and "atlas_cord" in d
    c = v["fixed_cut"]
    assert c["cut"]["axis"] == "sagittal" and abs(c["cut"]["t"] - 0.3) < 1e-9 and c["clip"][:3] == [-1, 0, 0] and c["clip"][4] == 1
    assert c["cap"] == [{"visible": True, "pos": c["cap"][0]["pos"]}] and abs(c["cap"][0]["pos"][0] - c["cut"]["value_mm"]) < 0.1


def test_low_tier_on_a_slow_frame_rate(check):
    t = check["views"]["tier"]
    assert t["tier"] == "low" and t["fps"] == 20 and t["dpr"] == 1.25 and t["caption_has_low"]


def test_page_zoom_fades_our_materials_and_nothing_is_a_dot(check):
    f = check["views"]["fade"]
    assert f["alpha"] == 0.4 and f["transparent"] is True and f["depthWrite"] is False      # window.zoomBrain (B's zoom) fades the specimen
    assert f["back"] == {"alpha": 1, "transparent": False}
    js = (WEB / "brain_anatomy.js").read_text()
    for marker in ("THREE.Points", "Sprite", "gl_PointSize", ".arc("):                     # the owner's rule: no dots or sprites
        assert marker not in js, marker


def test_captions_say_what_is_his_and_what_is_atlas(check):
    v = check["views"]
    for name in ("fresh", "fixed", "bundles"):
        cap = v[name]["caption"]
        assert "from HIS MRI" in cap and "A model, not a mind." in cap
        assert "cortex" in cap and ("cerebellum" in cap) == (name != "bundles")
    assert "his T1" in v["fixed"]["caption"] and "coronal" in v["fixed"]["caption"]
    cap = v["layers"]["caption"]
    assert "BodyParts3D" in cap and "CC BY 4.0" in cap and "surface error" in cap and "VENAT" in cap
    assert "not drawn" in cap and "olfactory (I)" in cap and "bridging veins" in cap
    for word in ("conscious", "understands", "feels"):
        assert word not in cap


# --- wording and credits ------------------------------------------------------------------------------------------
def test_hook_credits_and_about():
    html = (WEB / "index.html").read_text()
    assert html.count("brain_anatomy hook (G9") >= 3 and 'data-v="fresh"' in html and 'data-v="fixed"' in html and 'data-a="nerves"' in html
    assert '(MINI ? "glow" : "fresh")' in html and "glows" not in html                     # fresh is the default view; the mini keeps the page's look
    js = (WEB / "brain_anatomy.js").read_text()
    assert "A model, not a mind" in js and "nothing is invented" in js
    credits = (ANAT / "CREDITS.md").read_text()
    about = re.sub(r"\s+", " ", (WEB / "about.html").read_text())
    for text in (credits, about):
        assert ATTR in text and "VENAT" in text and "CC BY 4.0" in text and "Louis Collins" in text
    doc = (ROOT / "docs" / "research" / "real_brain_sources.md").read_text()
    for name in ("BigBrain", "Allen", "Julich", "HCP", "Sketchfab", "NonCommercial"):
        assert name in doc
