"""Right after load the phone camera stays in the room (preview/phone-camera, review G26 on ba06b4f: once, the first scene
after the 390 page loaded being "asleep", the follow camera framed the old rig's hips while the v5 layer was not ready
yet, and flew to y 115 m: a black canvas).

1. Live: the 390x844 page is loaded LOADS times with the fake server already sending "asleep", and the page runs its own
   frame() loop for SECONDS (nothing frozen, nothing waited for but the load event). An init script wraps
   requestAnimationFrame and records the camera after every frame (a software-GL frame can take seconds, so sampling
   from outside would miss a short flight). Hard: every frame's camera finite and within the overview's reach of the
   room (the overview sits at (5.2, 5, 6), 9 m out: nothing farther than OUT from the room's centre, nothing higher than
   TOP).
2. Forced: the race above depends on timing, so its cause is also put in by hand: the hips 100 m up (the old rig's
   unscaled skeleton), then not a number; the phone camera's goal must stay the overview.
Skipped without Playwright + Chromium.
"""
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from tests.visual import harness as H          # noqa: E402
from tests.visual.fake_server import Server    # noqa: E402

LOADS, SECONDS = 2, 40                  # (CI: the visual "pages" job has 30 min; the forced case below pins the cause)
OUT, TOP = 10.5, 6.0

RECORD = """(() => { const raf = window.requestAnimationFrame.bind(window);
  const M = window.__camMax = {r: 0, y: -1e9, at: null, frames: 0, nan: 0, ready: null};
  window.requestAnimationFrame = cb => raf(t => { cb(t); const c = window.camera; if (!c) return; const p = c.position; M.frames++;
    if (M.ready === null && window.mh && window.mh.ready) M.ready = +(performance.now() / 1000).toFixed(1);
    if (!Number.isFinite(p.x + p.y + p.z)) { M.nan++; return; }
    const r = Math.hypot(p.x, p.y - 0.6, p.z); if (r > M.r) { M.r = r; M.at = [p.x, p.y, p.z, +(performance.now() / 1000).toFixed(1)]; }
    if (p.y > M.y) M.y = p.y; }); })();"""


def run_loads(loads=LOADS, seconds=SECONDS, log=lambda *a: None):
    from playwright.sync_api import sync_playwright
    out = []
    with Server() as server, sync_playwright() as p:
        exe = H.CHROMIUM if Path(H.CHROMIUM).exists() else None
        browser = p.chromium.launch(executable_path=exe, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        cdn = H.CdnCache(HERE / ".cdn_cache")
        try:
            server.set_scene("sleeping", 23)
            for k in range(loads):
                ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True, has_touch=True)
                pg = ctx.new_page(); errors = []
                pg.on("pageerror", lambda e: errors.append(str(e)))
                pg.add_init_script(RECORD)
                cdn.install(pg)
                pg.goto(server.base + "/room.html?debug&hour=23", wait_until="load")
                t0 = time.time()
                while time.time() - t0 < seconds:
                    pg.wait_for_timeout(1000)
                m = pg.evaluate("window.__camMax")
                out.append({"load": k, **m, "errors": errors[:3]})
                log(f"  load {k}: {m['frames']} frames, farthest {m['r']:.2f} m at {m['at']}, highest y {m['y']:.2f}, "
                    f"{m['nan']} NaN, v5 layer ready at {m['ready']} s")
                ctx.close()
        finally:
            browser.close()
    return out


def test_camera_stays_in_the_room_after_load():
    if not H.chromium_ok():
        pytest.skip("playwright / chromium not installed")
    res = run_loads()
    bad = [f"load {r['load']}: camera at {r['at']} ({r['r']:.1f} m from the room's centre, highest y {r['y']:.1f}), "
           f"{r['nan']} frames not a number" for r in res if r["r"] > OUT or r["y"] > TOP or r["nan"]]
    bad += [f"load {r['load']}: no frames" for r in res if not r["frames"]]
    bad += [f"load {r['load']}: JS error {r['errors']}" for r in res if r["errors"]]
    assert not bad, "right after load the phone camera left the room:\n" + "\n".join(bad)


FORCE = """k => { const H = bones.Hips, keep = H.position.clone(); updateCameraGoal();
  if (k === 'up') H.position.y += 100 / Math.max(1e-6, H.parent.getWorldScale(new THREE.Vector3()).y); else H.position.set(NaN, NaN, NaN);
  boy.updateMatrixWorld(true); updateCameraGoal();
  const g = {pos: camGoal.pos.toArray(), tgt: camGoal.target.toArray(), hips: H.getWorldPosition(new THREE.Vector3()).toArray()};
  H.position.copy(keep); boy.updateMatrixWorld(true); updateCameraGoal(); g.after = camGoal.pos.toArray(); return g; }"""


def test_stale_hips_keep_the_overview():
    if not H.chromium_ok():
        pytest.skip("playwright / chromium not installed")
    from playwright.sync_api import sync_playwright
    h = H.Harness(HERE / "out", log=lambda *a: None)
    with Server() as server, sync_playwright() as p:
        h.server = server; h.base = server.base
        exe = H.CHROMIUM if Path(H.CHROMIUM).exists() else None
        h.browser = p.chromium.launch(executable_path=exe, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        try:
            ctx, pg, st = h.open("390")
            pg.wait_for_function("() => !window.mh || window.mh.ready", timeout=180000)
            h.goto_scene(pg, "sleeping", 23)
            res = {k: pg.evaluate(FORCE, k) for k in ("up", "nan")}
        finally:
            h.browser.close()
    over = [5.2, 5.0, 6.0]
    for k, g in res.items():
        assert all(abs(a - b) < 1e-6 for a, b in zip(g["pos"], over)), f"hips {k} ({g['hips']}): the goal left the overview: {g['pos']}"
        assert abs(g["after"][0] - over[0]) > 0.5, f"hips back in the room: the phone framing should be back, goal {g['after']}"


if __name__ == "__main__":
    run_loads(int(sys.argv[1]) if len(sys.argv) > 1 else LOADS, log=print)
