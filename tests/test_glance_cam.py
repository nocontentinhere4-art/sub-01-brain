"""The camera's turn toward him while he answers viewers (room/glance_cam.js, preview/interactive): its envelope (in 0.6 s,
held ~3 s, out 0.8 s, smooth at both ends) and its wiring - after the page's camera and keepClear() (whose push out of
his body sent the close view through the wall: it checks its own way clear), handed the follow state each frame, the page's
own camera put back after the render; boy_mh.js counts the answers it turns for."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


def test_envelope_eases_in_holds_and_out():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    js = ("const G = await import(process.env.GC); const ts = [-1, 0, 0.3, 0.6, 2, 3.6, 4.0, 4.4, 4.5];"
          "console.log(JSON.stringify({w: ts.map(t => +G.weightAt(t).toFixed(3)), env: G.ENV, len: G.LENGTH, bed: G.BED}));")
    r = subprocess.run([node, "--input-type=module", "-e", js], capture_output=True, text=True, timeout=60,
                       env={**os.environ, "GC": (WEB / "room" / "glance_cam.js").as_uri()})
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["env"] == {"in": 0.6, "hold": 3.0, "out": 0.8}, out
    w = out["w"]
    assert w[0] == 0 and w[1] == 0 and w[2] == 0.5 and w[3] == 1 and w[4] == 1 and w[5] == 1, w   # (eased in, held)
    assert 0 < w[6] < 1 and w[7] == 0 and w[8] == 0, w                                       # (eased out by 4.4 s)
    assert out["bed"] == {"dist": 2.6, "in": 3.0, "out": 2.0}, out          # (on the phone in bed: slowly in, out)


def test_bed_zoom_wide_screens_only_and_only_a_clip_held_phone():
    js = (WEB / "room" / "glance_cam.js").read_text()
    line = next(l for l in js.splitlines() if "wb = Math.max(0, Math.min(1, wb +" in l)
    assert "follows && onPhone && camera.aspect >= 1" in line, line            # (desktop, the camera following him, the phone in his hand)
    assert "B.clips[B.cur].phone" in js


def test_wired_after_the_page_camera_and_put_back_after_the_render():
    html = (WEB / "room.html").read_text()
    assert 'import { createGlanceCam } from "./room/glance_cam.js";' in html
    line = next(l for l in html.splitlines() if "GCAM.apply(" in l)
    assert line.index("controls.update()") < line.index("keepClear()") < line.index("GCAM.apply(") < line.index("renderer.render(scene, camera)") < line.index("GCAM.restore(camera, controls)"), line
    assert "follow && performance.now() - userMovedAt > 20000" in line          # (only while the camera follows him)
    js = (WEB / "room" / "boy_mh.js").read_text()
    assert js.count("M.respond = (M.respond || 0) + 1") == 2, "the wave and the glance answers count"
