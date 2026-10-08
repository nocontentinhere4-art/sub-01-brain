"""The view out of the room's window (#98 G7): web/room/window_view.js + the photographic plates in web/room/window/.

Checks the asset budget and the plates' sizes, that every source is CC0 or public domain and credited, the lights mask's
encoding, that the committed plates are what room_build/window_cards.py builds from the sources (when the sources are
present: they are not committed), the module's pure parts in node (tests/js/window_view_check.js: the weather pattern's
shares and smoothness, the lit-window curve, the shader's contract against plates.json, the reflection probe, the HDR
hook), the tight wiring in room.html, and that nothing names a brand. The pixels are checked by hand with
tests/room_window_shots.py."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WIN = ROOT / "web" / "room" / "window"
JS = ROOT / "web" / "room" / "window_view.js"
ROOM = ROOT / "web" / "room.html"
GEN = ROOT / "room_build" / "window_cards.py"
SRC = ROOT / "room_build" / "plates"
PLATES = ("mid", "mid_n", "far", "near", "sky", "noise")
BUDGET = 1.5 * 1024 * 1024
FREE = ("cc0", "public domain")


@pytest.fixture(scope="module")
def check():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, str(ROOT / "tests" / "js" / "window_view_check.js")], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def plates():
    return json.loads((WIN / "plates.json").read_text())


def test_assets_exist_and_fit_the_budget():
    names = {f.name for f in WIN.iterdir()}
    for p in PLATES:
        assert f"{p}.webp" in names, p
    assert "mid_l.webp" in names and "plates.json" in names
    total = sum(f.stat().st_size for f in WIN.iterdir()) + JS.stat().st_size
    assert total <= BUDGET, f"{total / 1024:.0f} KB over the 1.5 MB budget"


def test_plates_are_webp_of_the_documented_size(plates):
    from PIL import Image
    for name, size in plates["sizes"].items():
        with Image.open(WIN / name) as im:
            assert im.format == "WEBP" and list(im.size) == size, (name, im.format, im.size)
            assert im.mode == ("RGB" if name in ("sky.webp", "mid_l.webp") else "RGBA"), name
    assert plates["sizes"]["sky.webp"] == [plates["sky"]["size"][0], plates["sky"]["size"][1] * len(plates["sky"]["rows"])]


def test_every_source_is_free_and_credited(plates):
    credits = (ROOT / "web" / "room" / "CREDITS.md").read_text()
    srcs = plates["sources"]
    assert {"mid_day", "mid_night", "far"} <= set(srcs) and set(plates["sky"]["rows"]) <= set(srcs)
    for key, s in srcs.items():
        assert any(k in s["license"].lower() for k in FREE), (key, s["license"])
        assert s["page"] in credits, f"{key}: its page {s['page']} is not in CREDITS.md"
        who = s.get("artist") or ", ".join(s.get("authors", {}))
        assert who and who.split(",")[0].strip() in credits, (key, who)


def test_lights_mask_encodes_pane_and_id():
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(WIN / "mid_l.webp").convert("RGB"))
    pane = a[..., 0] > 200                                                    # R = coverage, full inside a pane
    assert 0.003 < pane.mean() < 0.2
    ids = np.unique(a[..., 2][pane])
    assert len(ids) >= 100 and ids.min() >= 1 and ids.max() <= 250             # hundreds of windows, each its own id
    assert not pane[:40].any()                                                 # nothing lit in the sky


def test_generator_matches_the_committed_plates(tmp_path):
    """when the sources are present (room_build/window_cards.py --fetch), the build reproduces the committed plates"""
    pytest.importorskip("PIL"); pytest.importorskip("numpy"); pytest.importorskip("scipy")
    sys.path.insert(0, str(GEN.parent))
    import importlib
    wc = importlib.import_module("window_cards")
    if not wc.sources_ready():
        pytest.skip("the photographic sources are not fetched (room_build/plates/)")
    wc.OUT = tmp_path
    files = wc.build()
    assert sum(files.values()) <= wc.BUDGET
    import numpy as np
    from PIL import Image
    for f in files:
        if f.endswith(".json") or (tmp_path / f).read_bytes() == (WIN / f).read_bytes():
            continue
        a = np.asarray(Image.open(tmp_path / f).convert("RGBA")).astype(int); b = np.asarray(Image.open(WIN / f).convert("RGBA")).astype(int)
        assert a.shape == b.shape and np.abs(a - b).mean() < 1.5, f"{f} differs from the committed plate: rerun room_build/window_cards.py"
    assert json.loads((tmp_path / "plates.json").read_text())["layers"] == json.loads((WIN / "plates.json").read_text())["layers"]


def test_generator_draws_no_text_and_checks_licences():
    src = GEN.read_text()
    assert "ImageFont" not in src and ".text(" not in src                      # no lettering of any kind
    assert "FREE" in src and 'assert any(k in lic.upper() for k in FREE)' in src   # every fetched source is checked


def test_weather_pattern_shares_and_smoothness(check):
    w = check["weather"]
    assert 0.12 <= w["rain"] <= 0.30, w
    assert 0.22 <= w["overcast"] <= 0.45, w
    assert 0.35 <= w["clear"] <= 0.62, w
    assert w["max_step_per_10min"] < 0.25, w
    assert 1.0 <= w["changes_per_day"] <= 6.0, w
    assert check["deterministic"] and check["range_ok"]


def test_lit_windows_follow_the_evening(check):
    lit = check["lit"]
    assert lit["h20"] > 0.6 and lit["h3"] < 0.2 and lit["h12"] < 0.4 and lit["h24_eq_h0"]
    assert lit["max_jump_per_3min"] < 0.03
    assert check["lit_uniform_follows_hour"]


def test_sun_curve_matches_the_room(check):
    s = check["sun"]
    assert s["noon"] > 0.95 and s["midnight"] < -0.95 and abs(s["rise"]) < 1e-6
    assert check["sun_crosses"]


def test_shader_contract(check):
    t = check["textures"]
    assert t["every_sampler_has_a_uniform"] and check["uniforms_declared"]
    assert set(t["loaded"]) == {f"{p}.webp" for p in PLATES} | {"mid_l.webp"}
    assert all(v is True for k, v in check["layers"].items() if k != "ground"), check["layers"]
    assert check["colorspace_included"] and check["built"] and check["brand_free"] and check["honest_weather"]
    g = check["gain"]
    assert 0.5 <= g["h"] <= 1.0 and 0.3 <= g["v"] <= 1.0 and 0 <= g["pitch"] <= 0.2 and g["pitchMax"] <= 0.5


def test_no_nan_reaches_the_glass(check):
    """G6's environment capture read NaN texels off the pane at night: the probe's render target starts undefined (a
    frozen loop never renders it), so build() clears its six faces and probes at once, the shader scrubs NaN from the
    probe sample and from the final colour, and a NaN hour or dt never reaches a uniform or light.sun"""
    pi = check["probe_init"]
    assert pi["faces_cleared"] == 6 and pi["clears"] == 6 and pi["target_restored"] and pi["probed_at_build"] == 1
    g = check["nan_guard"]
    assert all(v is True for k, v in g.items() if k != "hour"), g
    assert g["hour"] == 12                                                      # the last good hour is kept
    assert check["shader_scrubs_nan"] and check["light_sun_initial"]


def test_probe_emission_weather_and_train(check):
    p = check["probe"]
    assert 2 <= p["renders"] <= 4 and p["plane_visible_after"]                 # the glass's reflection, every ~20 s
    e = check["emission"]
    assert e["plain_day"] == 1 and e["hdr_day"] == 5 and e["hdr_night"] == 0.05 and e["explicit_day"] == 2
    r = check["rain_override"]
    assert r["rain"] > 0.95 and r["cloud"] > 0.95 and r["sun_factor"] < 0.3
    assert check["state_kind_after_reset"] in ("clear", "overcast", "rain")
    tr = check["train"]
    assert tr["steps_visible"] > 10 and tr["directions"] == [-1, 1]


def test_room_html_wiring_is_tight():
    html = ROOM.read_text()
    assert 'import { createWindowView } from "./room/window_view.js";' in html
    assert 'createWindowView(THREE, {base:"room/window/"' in html
    assert "sky = windowView.build(w, scene, renderer);" in html                 # on the GLB's SURF_window marker, as before
    assert "windowView.update(real, hour);" in html                             # once per frame (its whole time), driven by his Tokyo clock
    assert "skyMaterial" not in html and "ShaderMaterial" not in html            # the old in-page sky shader is gone
    assert html.count("windowView") <= 8                                         # a small block, nothing else touched


def test_docs_are_honest_about_the_weather():
    doc = (ROOT / "docs" / "design" / "room-window" / "README.md").read_text()
    assert re.search(r"no weather (feed|API)", doc, re.I) and "deterministic" in doc.lower()
    credits = (ROOT / "web" / "room" / "CREDITS.md").read_text()
    assert "window_cards.py" in credits and "window_view.js" in credits and "not real weather" in credits
