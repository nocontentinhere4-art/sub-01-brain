"""Switching between typing and the mouse at the desk (review F6): the hands must not snap. Before, the right hand jumped
23 cm in one frame when he took the mouse and the left 5.6 cm (the mode picked the code path at once while the weights
crossfaded). Max per-frame movement of each index fingertip across type -> mouse -> type, in the page, frame by frame. A real reach
peaks about 1 m/s (minimum-jerk, bell-shaped): at most 40 mm a frame at 30 fps; at 402e21f the right hand still moved
72 mm in a frame (2+ m/s). And the right elbow: the arm's solve left its swing round the shoulder-wrist line free, and
it leapt up to 22 cm in a frame, also in steady typing.
Skipped where headless Chromium or Playwright is missing, like test_visual.py."""
import math
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from tests.visual import harness as H          # noqa: E402
from tests.visual.fake_server import Server    # noqa: E402

TIP = """() => { const g = n => { const b = boy.getObjectByName(n) || boy.getObjectByName(n.slice(0, -1) + '.' + n.slice(-1)); return b ? b.getWorldPosition(new THREE.Vector3()).toArray() : null; };   // (v5: finger2-3L; mixamo: finger2-3.L)
  return {L: g('finger2-3L'), R: g('finger2-3R'), E: bones.RightForeArm.getWorldPosition(new THREE.Vector3()).toArray()}; }"""
LEFT_MM, RIGHT_MM, ELBOW_MM = 30, 40, 50     # (the right hand travels ~32 cm from the keys to the mouse in 0.8 s, peaking ~25 mm a frame)


def test_no_snap_switching_between_keys_and_mouse(tmp_path):
    if not H.chromium_ok():
        pytest.skip("playwright / chromium not installed")
    from playwright.sync_api import sync_playwright
    h = H.Harness(tmp_path, log=lambda *a: None)
    with Server() as server, sync_playwright() as p:
        h.server = server; h.base = server.base
        exe = H.CHROMIUM if Path(H.CHROMIUM).exists() else None
        h.browser = p.chromium.launch(executable_path=exe, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        ctx, pg, st = h.open("1280")
        h.goto_scene(pg, "desk", 14)
        pg.wait_for_function("() => !window.mh || window.mh.ready", timeout=180000)
        if not pg.evaluate("() => !!(window.mh && mh.M)"):
            h.browser.close(); pytest.skip("the MetaHuman rig is not loaded")
        pg.evaluate("""() => { act('research', {screen: {device: 'desk', id: 'q1', kind: 'page', query: 'ramen near kichijoji'}});
          mh.M.typeUntil = 1e9; for (let i = 0; i < 90; i++) animate_(1/30); }""")
        rows = []
        def run(n):
            for _ in range(n):
                rows.append(pg.evaluate("() => { animate_(1/30); return (" + TIP + ")(); }"))
        run(10)
        pg.evaluate("() => { mh.M.typeUntil = 0; }"); run(45)          # type -> mouse
        pg.evaluate("() => { mh.M.typeUntil = 1e9; }"); run(45)        # mouse -> type
        errors = list(st["errors"])
        h.browser.close()
    jump = {s: max(math.dist(a[s], b[s]) * 1000 for a, b in zip(rows, rows[1:])) for s in ("L", "R", "E")}
    assert not errors, errors[:3]
    assert jump["L"] <= LEFT_MM and jump["R"] <= RIGHT_MM, f"per-frame index tip jump (mm): {jump}"
    assert jump["E"] <= ELBOW_MM, f"per-frame right elbow jump (mm): {jump}"
