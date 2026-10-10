"""The bed layer (room/boy_mh.js bedStep; room/desk_states/bed: G23's Sova bed clips), in the page: lying with the phone and
asleep, each clip that plays keeps all of him out of the bed (the mattress and the duvet: the page's own bed counter over a
sweep of the clip, as test_visual.py measures the scenes), the phone clips hold the phone in his left hand with its screen
toward his face, and the lift over the face (whose legs go into the mattress) never plays. Skipped where headless Chromium
or Playwright is missing, like test_visual.py."""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from tests.visual import harness as H          # noqa: E402
from tests.visual.fake_server import Server    # noqa: E402

PHONE = ["bed_phone_watch_portrait", "bed_phone_watch_landscape", "bed_phone_typing"]
SLEEP = ["sleep_side", "sleep_roll_to_back", "sleep_back", "sleep_back_idle"]
SCREEN = """() => { phone.updateMatrixWorld(true); const z = new THREE.Vector3().setFromMatrixColumn(phone.matrixWorld, 2).normalize(), p = phone.getWorldPosition(new THREE.Vector3());
  const hd = (bones.headfront || bones.Head).getWorldPosition(new THREE.Vector3()), lh = bones.LeftHand.getWorldPosition(new THREE.Vector3());
  return {vis: phone.visible, byClip: !!phone.userData.byClip, faces: z.dot(hd.clone().sub(p).normalize()), toHand: p.distanceTo(lh), toHead: p.distanceTo(hd)}; }"""


def test_bed_clips_stay_out_of_the_bed_and_hold_the_phone(tmp_path):
    if not H.chromium_ok():
        pytest.skip("playwright / chromium not installed")
    from playwright.sync_api import sync_playwright
    h = H.Harness(tmp_path, log=lambda *a: None)
    rows, phone, played = {}, {}, set()
    with Server() as server, sync_playwright() as p:
        h.server = server; h.base = server.base
        exe = H.CHROMIUM if Path(H.CHROMIUM).exists() else None
        h.browser = p.chromium.launch(executable_path=exe, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        ctx, pg, st = h.open("1280")
        pg.wait_for_function("() => window.mh && window.mh.ready", timeout=240000)
        pg.wait_for_function("() => mh.M.bedTried", timeout=120000)
        if not pg.evaluate("() => !!mh.M.bed"):
            h.browser.close(); pytest.skip("the bed layer is off (not the mixamo character with the Sova layer)")
        assert pg.evaluate("() => !mh.M.bed.clips.bed_phone_lift"), "the lift over the face must not load"
        for scene, names in (("phone", PHONE), ("sleeping", SLEEP)):
            h.goto_scene(pg, scene, 23)
            pg.evaluate("__qa.step(1/30, 30)")
            played.add(pg.evaluate("mh.M.bed.cur"))                          # (what the layer chose by itself)
            for n in names:
                pg.evaluate(f"mh.M.bedForce = '{n}'"); pg.evaluate("__qa.step(1/30, 30)")
                d = pg.evaluate(f"mh.M.bed.clips['{n}'].dur")
                rows[n] = pg.evaluate(f"__qa.bodySweep(2, {min(d, 8):.2f}, 0.5)")["bed"]
                if scene == "phone":
                    phone[n] = pg.evaluate(SCREEN)
            pg.evaluate("mh.M.bedForce = null")
        errors = list(st["errors"])
        h.browser.close()
    assert not errors, errors[:3]
    assert played == {"bed_phone_watch_portrait", "sleep_side"}, played   # (a short on the phone: upright; asleep: on his side first)
    assert all(v == 0 for v in rows.values()), rows
    for n, r in phone.items():
        assert r["vis"] and r["byClip"], (n, r)
        assert r["faces"] > 0.8 and r["toHand"] < 0.2 and 0.12 < r["toHead"] < 0.45, (n, r)
