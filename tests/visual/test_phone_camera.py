"""He is in the picture on a phone (preview/phone-camera). Live defect: on a 390x844 phone, asleep in bed, the camera that
follows him framed the room and left him out (the bed off the left edge); at 1280 he was in it.

For three phones (390x844, 360x780, 430x932, mobile emulation) and 1280x800 for reference, the page's follow camera is run
frame by frame as the page's own frame() runs it (tests/visual/phone_camera.js: updateCameraGoal, the lerp, keepClear),
and each frame his projected bounding box (every visible skinned mesh, skinned on the CPU) is measured:
  - steady modes (the camera on its goal, then 3 s of frames): asleep on his back, turned on his side, lying awake with
    music, the phone in bed, at the desk, standing at the door, walking;
  - transitions (the camera only lerping, as live): getting into bed from the door, getting out of bed to the desk.
Hard, on the phones: in every bed mode and in the transitions into and out of bed, at least MIN_IN of the box inside
the frame (the 3D canvas under the header that covers its top) and his whole head inside, every frame; the same standing
and walking; at the desk (the monitor shot) his head.
1280 is only recorded, by hand (its camera must not change: see docs/qa/phone_camera_STATUS.md). Skipped without Playwright +
Chromium, like test_visual.py. `python -m tests.visual.test_phone_camera` prints the numbers and writes
tests/visual/out/phone_camera.json.
"""
import json
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from tests.visual import harness as H          # noqa: E402
from tests.visual.fake_server import Server    # noqa: E402

MIN_IN = 0.80
PHONES = ("390", "360", "430")
BED = ("sleeping", "sleeping_side", "music", "phone", "into_bed", "out_of_bed")
# off the bed: standing and walking he is framed like in bed; at the desk the page's monitor shot frames the screen over
# his shoulder (54 % of him in it at 1280 too, by design): there only his head must be in frame
OTHER = ("door", "walking")
FRAMES, DT = 90, 1 / 30


def _transition(h, pg, to, hour, done_js, limit_s=60):
    """Send the next scene and run the page frame by frame (camera lerping) until done_js holds (on the way), then 2 s
    more (there: out of bed that is the desk, the monitor shot coming in)."""
    h.server.set_scene(to, hour)
    new = lambda: {"frames": 0, "worst": 1.0, "head_miss": 0, "worst_at": None, "max_cam_step_m": 0.0}   # noqa: E731
    way, there = new(), new()
    t0, extra, n = time.time(), None, 0
    while n < limit_s * 30:
        pg.wait_for_timeout(30)                       # (the fake socket's ticks reach the page between chunks)
        r = pg.evaluate(f"__phoneCam(15, {DT}, false, {done_js if extra is None else 'null'})")
        agg = way if extra is None else there
        n += r["frames"]; agg["frames"] += r["frames"]; agg["head_miss"] += r["head_miss"]
        agg["max_cam_step_m"] = max(agg["max_cam_step_m"], r["max_cam_step_m"])
        if r["worst"] < agg["worst"]:
            agg["worst"], agg["worst_at"] = r["worst"], r["worst_at"]
        if extra is None and r["done"]:
            extra = n + 60
        if extra is not None and n >= extra:
            break
    way["reached"] = extra is not None
    way["seconds"] = round(time.time() - t0, 1)
    way["there"] = there
    return way


def measure(sizes, log=lambda *a: None):
    from playwright.sync_api import sync_playwright
    h = H.Harness(HERE / "out", log=log)
    res = {}
    with Server() as server, sync_playwright() as p:
        h.server = server; h.base = server.base
        exe = H.CHROMIUM if Path(H.CHROMIUM).exists() else None
        h.browser = p.chromium.launch(executable_path=exe, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        try:
            for size in sizes:
                ctx, pg, st = h.open(size)
                pg.wait_for_function("() => !window.mh || window.mh.ready", timeout=180000)
                pg.add_script_tag(path=str(HERE / "phone_camera.js"))
                r = res[size] = {}
                for name in ("sleeping", "sleeping_side", "music", "phone", "desk", "door", "walking"):
                    h.goto_scene(pg, name, 23 if name in ("sleeping", "sleeping_side", "music", "phone") else 14)
                    r[name] = pg.evaluate(f"__phoneCam({FRAMES}, {DT}, true)")
                    log(f"  {size} {name}: {r[name]['worst']} worst, head out {r[name]['head_miss']}/{r[name]['frames']}")
                h.goto_scene(pg, "door", 23); pg.evaluate(f"__phoneCam(30, {DT}, true)")
                r["into_bed"] = _transition(h, pg, "sleeping", 23, "() => { const p = pose(); return p.at === 'bedlie' && !p.step; }")
                log(f"  {size} into_bed: {r['into_bed']['worst']} worst, head out {r['into_bed']['head_miss']}/{r['into_bed']['frames']}")
                r["out_of_bed"] = _transition(h, pg, "desk", 14, "() => { const p = pose(); return p.at === 'desk' || !!(p.step && p.step.to === 'desk'); }")   # (sitting down: the monitor shot)
                log(f"  {size} out_of_bed: {r['out_of_bed']['worst']} worst, head out {r['out_of_bed']['head_miss']}/{r['out_of_bed']['frames']}")
                r["errors"] = list(st["errors"])
                ctx.close(); h.pages.pop(size, None)
        finally:
            h.browser.close()
    return res


@pytest.fixture(scope="module")
def numbers():
    if not H.chromium_ok():
        pytest.skip("playwright / chromium not installed")
    res = measure(PHONES)          # (1280 is only recorded, by hand: python -m tests.visual.test_phone_camera; CI's 30 min)
    out = HERE / "out"; out.mkdir(exist_ok=True)
    (out / "phone_camera.json").write_text(json.dumps(res, indent=1) + "\n")
    return res


@pytest.mark.parametrize("size", PHONES)
def test_in_bed_he_is_in_the_picture(numbers, size):
    r = numbers[size]
    assert not r["errors"], r["errors"]
    bad = [f"{m}: {r[m]['worst']:.2f} of him in frame at worst (min {MIN_IN}), head out of frame {r[m]['head_miss']}/{r[m]['frames']} frames"
           f" (worst at {r[m]['worst_at']})" for m in BED if r[m]["worst"] < MIN_IN or r[m]["head_miss"]]
    bad += [f"{m}: never got there" for m in ("into_bed", "out_of_bed") if not r[m]["reached"]]
    t = r["into_bed"]["there"]
    if t["worst"] < MIN_IN or t["head_miss"]:
        bad.append(f"into_bed, lying down: {t['worst']:.2f} in frame at worst, head out {t['head_miss']}/{t['frames']}")
    t = r["out_of_bed"]["there"]
    if t["head_miss"]:
        bad.append(f"out_of_bed, at the desk: head out {t['head_miss']}/{t['frames']} (worst at {t['worst_at']})")
    assert not bad, f"{size}: in bed he is out of the picture:\n" + "\n".join(bad)


@pytest.mark.parametrize("size", PHONES)
def test_off_the_bed_he_stays_in_the_picture(numbers, size):
    r = numbers[size]
    bad = [f"{m}: {r[m]['worst']:.2f} in frame at worst, head out {r[m]['head_miss']}/{r[m]['frames']}"
           for m in OTHER if r[m]["worst"] < MIN_IN or r[m]["head_miss"]]
    if r["desk"]["head_miss"]:
        bad.append(f"desk: head out of frame {r['desk']['head_miss']}/{r['desk']['frames']} frames (worst at {r['desk']['worst_at']})")
    assert not bad, f"{size}: standing / walking / at the desk he is out of the picture:\n" + "\n".join(bad)


if __name__ == "__main__":
    sizes = tuple(sys.argv[1:]) or PHONES + ("1280",)
    res = measure(sizes, log=print)
    (HERE / "out").mkdir(exist_ok=True)
    (HERE / "out" / "phone_camera.json").write_text(json.dumps(res, indent=1) + "\n")
    for size, r in res.items():
        print(size, {m: (r[m]["worst"], r[m]["head_miss"], r[m]["frames"]) for m in r if m != "errors"})
