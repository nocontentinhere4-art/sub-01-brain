"""A glance in the page (brain_plan A2): the fake server sends {type: "glance", emoji: "👋"} over the socket as live_server
does when viewers' reactions spike; the room turns his head (room/glance.js GLANCE goes active), the desk states take the
message (room/desk_states.js through the page's deskEv hook) and, seated watching at the desk, he waves (boy_mh.js: the
wave request started by svWave, M.respond counted once, which turns the camera to him: room/glance_cam.js). Skipped where
headless Chromium or Playwright is missing, like test_visual.py."""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from tests.visual import harness as H          # noqa: E402
from tests.visual.fake_server import Server    # noqa: E402


def test_a_glance_over_the_socket_turns_his_head_and_he_waves(tmp_path):
    if not H.chromium_ok():
        pytest.skip("playwright / chromium not installed")
    from playwright.sync_api import sync_playwright
    h = H.Harness(tmp_path, log=lambda *a: None)
    with Server() as server, sync_playwright() as p:
        h.server = server; h.base = server.base
        exe = H.CHROMIUM if Path(H.CHROMIUM).exists() else None
        h.browser = p.chromium.launch(executable_path=exe, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        ctx, pg, st = h.open("1280")
        pg.wait_for_function("() => window.mh && window.mh.ready", timeout=240000)
        pg.wait_for_function("() => mh.M.bedTried", timeout=120000)          # (the Sova layers load after ready: sv in parallel)
        try:
            H.wait_js(pg, "() => !!(mh.M.sv && window.__deskEv && window.GLANCE)", timeout=120000)
        except TimeoutError:
            h.browser.close(); pytest.skip("the desk states are off (not the mixamo character with the Sova layer)")
        h.goto_scene(pg, "video", 14)                                       # seated at the computer, a video on the monitor: he sits back (desk_watch)
        pg.evaluate("__qa.step(1/30, 90)")                                  # (the desk states settle into their watching loop)
        before = pg.evaluate("() => ({respond: mh.M.respond || 0, active: GLANCE.active, wave: !!mh.M.wave, mode: mh.M.mode})")
        assert before["mode"] == "desk_watch" and not before["active"] and not before["wave"], before
        server.send({"type": "glance", "emoji": "\U0001f44b"})             # what live_server broadcasts on a spike of waves
        H.wait_js(pg, "() => GLANCE.active", timeout=10000)                 # the socket's message reached the dispatcher
        pg.evaluate("__qa.step(1/30, 10)")                                  # (the desk states read the hook on a step)
        after = pg.evaluate("() => ({respond: mh.M.respond || 0, wave: !!mh.M.wave, log: mh.M.log.slice(-8).map(x => x[1])})")
        errors = list(st["errors"])
        h.browser.close()
    assert not errors, errors[:3]
    assert after["wave"] and after["respond"] == before["respond"] + 1, after    # he waves back; counted once (the camera turns)
    assert any("wave <glance" in x for x in after["log"]), after
