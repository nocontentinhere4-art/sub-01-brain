"""Arriving at the computer (the live checks: the caption said "is at the computer" while he still stood by the chair for
30-60 s). Two causes, two tests:
- the caption followed the server, whose walk ends seconds before his in the room (he still pulls the chair out and sits
  down): it now says he is going to the desk until the page has him seated;
- his time followed the frame rate (at most 0.1 s per frame): at a few frames a second, a headless check or a slow
  device, he moved at a fraction of real time. A late frame is now caught up in steps.
Skipped where headless Chromium or Playwright is missing, like test_visual.py."""
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from tests.visual import harness as H          # noqa: E402
from tests.visual.fake_server import Server    # noqa: E402

STATE = """() => { const p = pose(); return {story: document.getElementById('story').textContent, at: p.at, step: p.step ? p.step.k : null,
  goal: p.goal ? p.goal.anchor : null}; }"""


def _browser(p, h, server):
    h.server = server; h.base = server.base
    exe = H.CHROMIUM if Path(H.CHROMIUM).exists() else None      # (the harness's rule: CI has Playwright's own Chromium)
    h.browser = p.chromium.launch(executable_path=exe, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
    ctx, pg, st = h.open("1280")
    h.goto_scene(pg, "door", 14)
    pg.wait_for_function("() => !window.mh || window.mh.ready", timeout=180000)
    return pg


def test_caption_says_going_to_the_desk_until_he_sits(tmp_path):
    if not H.chromium_ok():
        pytest.skip("playwright / chromium not installed")
    from playwright.sync_api import sync_playwright
    h = H.Harness(tmp_path, log=lambda *a: None)
    with Server() as server, sync_playwright() as p:
        pg = _browser(p, h, server)
        server.set_scene("computer", 14)                         # the server: arrived, a page on the screen
        H.wait_js(pg, "() => { const p = pose(); return p.goal && p.goal.anchor === 'desk'; }", timeout=15000)
        pg.evaluate("__qa.step(1/30, 3)")
        first = pg.evaluate(STATE)
        assert first["at"] != "desk" or first["step"], first      # (still on his way)
        assert "going to the desk" in first["story"] and "at the computer" not in first["story"], first
        seated = None
        for i in range(30 * 40):                                  # up to 40 s of his time, manual steps
            pg.evaluate("__qa.step(1/30, 1)")
            s = pg.evaluate(STATE)
            if s["at"] == "desk" and (not s["step"] or s["step"] == "chair"):   # (hips on the seat: riding the chair in counts)
                seated = s; break
            assert "at the computer" not in s["story"], (i, s)     # never before he sits
        assert seated, "he never sat down"
        pg.evaluate("__qa.step(1/30, 2)")                          # (re-checked every step: not left to the next tick)
        after = pg.evaluate(STATE)
        assert "at the computer" in after["story"] and "Inokashira" in after["story"], after
        h.browser.close()


def test_he_sits_in_real_time_on_a_slow_frame_rate(tmp_path):
    """The page's own loop (no manual steps) under headless software GL, which draws the room at a fraction of a frame a
    second: from the door he is seated at the desk within 45 s of the server's tick (now ~16 s at 0.11 fps; before, the
    walk alone took ~170 s at 0.24 fps). (Not CPU throttling: that slows his steps as much as the drawing, so no
    catch-up can keep real time - a slow device draws slowly, it does not step slowly.)"""
    if not H.chromium_ok():
        pytest.skip("playwright / chromium not installed")
    from playwright.sync_api import sync_playwright
    h = H.Harness(tmp_path, log=lambda *a: None)
    with Server() as server, sync_playwright() as p:
        pg = _browser(p, h, server)
        pg.evaluate("() => { window.FREEZE = false; }")          # (the harness freezes the page's loop to step it by hand)
        server.set_scene("computer", 14)
        t0 = time.time(); seated = None; frames0 = None
        while time.time() - t0 < 60:
            s = pg.evaluate(STATE)
            if s["goal"] == "desk" and s["at"] == "desk" and not s["step"]:
                seated = time.time() - t0; break
            time.sleep(0.5)
        h.browser.close()
    assert seated is not None and seated < 45, f"not seated within 45 s of real time (seated at {seated})"


CATCH_UP = """async () => {
  const T0 = () => dbg().T, wait = () => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  const late = async (s, back) => { const g = clock.getDelta.bind(clock); let once = true;
    clock.getDelta = () => { g(); if (once) { once = false; return s; } return 0; };   // (one late frame; the next ones no time)
    if (back) document.dispatchEvent(new Event("visibilitychange"));
    const t = T0(); window.FREEZE = false; await wait(); window.FREEZE = true; clock.getDelta = g; return +(T0() - t).toFixed(2); };
  return {slow: await late(20, false), back: await late(20, true)}; }"""


def test_a_slow_frame_is_caught_up_whole(tmp_path):
    """Live 2026-10-08 08:02 (17:04-17:07 Tokyo): "is at the computer" for 3 minutes with the chair empty, and a minute before
    standing by the bed while "lying on the bed listening to music". The live room was still 8d159d2 (his time 0.1 s a
    frame: 1.9 s of his time in 220 s at ~0.09 fps). On main a late frame was caught up 8 s at most, and under headless
    software GL a frame takes 8-16 s while he moves: he ran at ~0.5x real time. A slow frame is now caught up whole (up
    to 30 s); a tab coming back still catches up 8 s at most."""
    if not H.chromium_ok():
        pytest.skip("playwright / chromium not installed")
    from playwright.sync_api import sync_playwright
    h = H.Harness(tmp_path, log=lambda *a: None)
    with Server() as server, sync_playwright() as p:
        pg = _browser(p, h, server)
        r = pg.evaluate(CATCH_UP)
        h.browser.close()
    assert 19.5 <= r["slow"] <= 20.6, r                           # (a 20 s frame: 20 s of his time, in 0.1 s steps)
    assert 7.5 <= r["back"] <= 8.6, r                             # (back from a hidden tab: 8 s, as before)
