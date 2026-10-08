"""The character switch in room.html, in the page: ?char=v5 loads room/char_v5.glb and its clips (room/mh_v5/),
never room/char_mixamo.glb nor anything under room/mh_mx/, and the rig he moves on is v5's own skeleton; the default room
(the launch's: the mixamo character) the other way round: room/char_mixamo.glb, its mixamorig bones, the clips under room/mh_mx/ and none from
room/mh_v5/. What the page fetched comes from its own resource timing; the bones are the skinned mesh's skeleton. Both
characters' bones are renamed to the page's names when they are prepared (char_v5.js, char_mixamo.js), so a skeleton is
told by its size (each GLB's own skin joint count) and by the bones only it has: v5's twist bones and metacarpals,
Mixamo's fingertips (finger*-4), head end and toe. An inverted switch fails both. Skipped where headless Chromium or Playwright is
missing, like test_visual.py."""
import json
import re
import struct
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from tests.visual import harness as H          # noqa: E402
from tests.visual.fake_server import Server    # noqa: E402

WEB = ROOT / "web" / "room"
PROBE = """() => { const urls = performance.getEntriesByType('resource').map(e => new URL(e.name).pathname);
  const bones = new Set(); boy.traverse(o => { if (o.isSkinnedMesh) for (const b of o.skeleton.bones) bones.add(b.name); });
  return {urls, bones: [...bones]}; }"""


def joints(glb):
    """The GLB's skin joints, by their names in the file."""
    b = glb.read_bytes(); n = struct.unpack_from("<I", b, 12)[0]; g = json.loads(b[20:20 + n])
    return {g["nodes"][j].get("name", "") for s in g.get("skins", []) for j in s["joints"]}


V5_ONLY = re.compile(r"Twist0\d$|^metacarpal\d")                 # (v5: twist bones, metacarpals)
MX_ONLY = re.compile(r"^finger\d-4|^head_end$|^toe1-2")           # (Mixamo: fingertip ends, head top, toe end)


def probe(tmp_path, query):
    from playwright.sync_api import sync_playwright
    h = H.Harness(tmp_path, log=lambda *a: None)
    h.query = query
    with Server() as server, sync_playwright() as p:
        h.server = server; h.base = server.base
        exe = H.CHROMIUM if Path(H.CHROMIUM).exists() else None
        h.browser = p.chromium.launch(executable_path=exe, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        ctx, pg, st = h.open("1280")
        pg.wait_for_function("() => !window.mh || window.mh.ready", timeout=180000)
        r = pg.evaluate(PROBE)
        r["errors"] = list(st["errors"]) + [f for f in st["failed"] if "/room/" in f]
        h.browser.close()
    return r


@pytest.fixture(scope="module")
def skip_without_chromium():
    if not H.chromium_ok():
        pytest.skip("playwright / chromium not installed")


def test_char_v5_page_is_v5(tmp_path, skip_without_chromium):
    r = probe(tmp_path, "&char=v5")
    assert not r["errors"], r["errors"][:3]
    urls = r["urls"]
    assert "/room/char_v5.glb" in urls
    assert "/room/char_mixamo.glb" not in urls and "/room/char_mixamo.js" not in urls
    assert not [u for u in urls if "/room/mh_mx/" in u], [u for u in urls if "/room/mh_mx/" in u][:3]
    assert [u for u in urls if "/room/mh_v5/" in u]
    bones = set(r["bones"]); v5 = joints(WEB / "char_v5.glb")
    assert len(bones) == len(v5), (len(bones), len(v5))
    assert not [b for b in v5 if b.startswith("mixamorig")]
    assert len([b for b in bones if V5_ONLY.search(b)]) >= 20 and not [b for b in bones if MX_ONLY.search(b)]


def test_default_page_is_mixamo(tmp_path, skip_without_chromium):
    r = probe(tmp_path, "")
    assert not r["errors"], r["errors"][:3]
    urls = r["urls"]
    assert "/room/char_mixamo.glb" in urls and "/room/char_mixamo.js" in urls
    assert "/room/char_v5.glb" not in urls
    assert not [u for u in urls if "/room/mh_v5/" in u], [u for u in urls if "/room/mh_v5/" in u][:3]
    assert [u for u in urls if "/room/mh_mx/" in u]
    bones = set(r["bones"]); mx = joints(WEB / "char_mixamo.glb")
    assert len(bones) == len(mx) == 65, (len(bones), len(mx))
    assert all(b.startswith("mixamorig:") for b in mx)
    assert len([b for b in bones if MX_ONLY.search(b)]) == 13 and not [b for b in bones if V5_ONLY.search(b)]
