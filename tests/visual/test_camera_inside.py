"""The camera never looks into anything (preview/camera-clip): from every place a visitor can put the room's camera at
the desk (the owner's angle over his shoulder, inside the chair's back, the desk top, under the desk, the shelf, behind
the monitor, and orbits round the page's target at two distances and two heights), a render with back faces in red has
no more than SPECKS red pixels of 64,000 (one-pixel specks at mesh seams, invisible at full size). Skipped where
headless Chromium or Playwright is missing, like test_visual.py."""
import math
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from tests.visual import harness as H          # noqa: E402
from tests.visual.fake_server import Server    # noqa: E402

SPECKS = 30


def views(pg):
    owner = pg.evaluate("() => { const B = n => boy.getObjectByName(n).getWorldPosition(new THREE.Vector3()); const f = new THREE.Vector3(Math.sin(boy.rotation.y), 0, Math.cos(boy.rotation.y));"
                        " return B('LeftShoulder').addScaledVector(f, -0.06).add(new THREE.Vector3(0, 0.10, 0)).toArray(); }")
    chair = pg.evaluate("() => { const p = room.getObjectByName('chair').getWorldPosition(new THREE.Vector3()); return [p.x, p.y + 0.85, p.z]; }")
    mon = pg.evaluate("() => SURF.monitor.c")
    v = [("owner's angle", {"pos": owner}), ("inside the chair's back", {"pos": chair}),
         ("inside the desk top", {"pos": [mon[0] + 0.3, 0.95, mon[2] + 0.35]}), ("under the desk", {"pos": [mon[0], 0.6, mon[2] + 0.2]}),
         ("in the shelf", {"pos": [0.68, 1.3, -1.35]}), ("behind the monitor, high", {"pos": [mon[0], mon[1] + 0.35, mon[2] - 0.15]})]
    for r in (0.4, 0.8):
        for pol in (0.5, 1.1):
            for k in range(8):
                v.append((f"orbit r {r} polar {pol} azimuth {k * 45}", {"r": r, "pol": pol, "az": k * math.pi / 4}))
    return v


def test_no_view_into_anything(tmp_path):
    if not H.chromium_ok():
        pytest.skip("playwright / chromium not installed")
    from playwright.sync_api import sync_playwright
    h = H.Harness(tmp_path, log=lambda *a: None)
    bad = []
    with Server() as server, sync_playwright() as p:
        h.server = server; h.base = server.base
        exe = H.CHROMIUM if Path(H.CHROMIUM).exists() else None      # (the harness's rule: CI has Playwright's own Chromium)
        h.browser = p.chromium.launch(executable_path=exe, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        ctx, pg, st = h.open("1280"); h.goto_scene(pg, "desk", 20)
        pg.wait_for_function("() => !window.mh || window.mh.ready", timeout=180000)
        pg.evaluate("act('research', {screen: {device: 'desk', id: 'p1', kind: 'page'}}); for (let i = 0; i < 60; i++) animate_(1/30)")
        pg.add_script_tag(path=str(HERE / "camera_inside.js"))
        for name, o in views(pg):
            r = pg.evaluate("o => __cameraInside(o)", o)
            if r["red"] > SPECKS:
                bad.append(f"{name}: {r['red']} back-face pixels of 64000 (camera at {r['cam']})")
        h.browser.close()
    assert not bad, "the camera looks into something:\n" + "\n".join(bad)
