"""v5's feet in the room (room_build/charfix/feet.mjs): in the page's own states (tests/visual's harness, /room.html?debug),
frame by frame: each sole's height over the floor (standing, walking, seated), sock vertices inside the slides and the
sock-slide pairs apart (the seam and the tube under the strap), and in bed whether the slides are off (parked by the
bed) with his socks on. Close-ups of his feet standing, seated and in bed.

    python room_build/charfix/probe.py --tag after --out docs/design/char-fix-feet/probe     # web/room/char_v5.glb as it is
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.visual.harness import Harness, CHROMIUM          # noqa: E402
from tests.visual.fake_server import Server                 # noqa: E402

MH_DESK = "act('research', {screen: {device: 'desk', id: 'p1', kind: 'page'}})"
SCENARIOS = [  # label, start scene (hour), setup JS, seconds
    ("standing at the door (mh_stand)", ("door", 14), "", 6),
    ("getting up, walking to the window, standing there", ("desk", 14), MH_DESK + "; for (let i = 0; i < 60; i++) animate_(1/30); live('window', {activity: 'window'})", 14),
    ("seated: desk typing (desk_type_ik)", ("desk", 14), "act('research', {screen: {device: 'desk', id: 'q1', kind: 'page', search: {query: 'ramen near kichijoji'}}})", 10),
    ("seated: desk mouse (desk_mouse_ik)", ("desk", 14), "act('chart', {screen: {device: 'desk', id: 'c1', kind: 'page'}})", 8),
    ("seated: desk watch (desk_watch)", ("desk", 14), "act('watch_video', {screen: {device: 'desk', id: 'v1', kind: 'video'}})", 6),
    ("sitting down at the desk (room_sit_down)", ("window", 14), "live('research', {screen: {device: 'desk', id: 'p2', kind: 'page'}})", 16),
    ("bedtime: to bed (slides come off)", ("desk", 23), MH_DESK + "; for (let i = 0; i < 60; i++) animate_(1/30); live('sleep', {activity: 'sleep'})", 22),
    ("in bed, asleep", ("sleeping", 23), "", 6),
    ("waking, out of bed (slides go back on)", ("sleeping", 23), "live('window', {activity: 'window'})", 12),
]
SHOTS = [  # name, scene (hour), camera distance, height, what
    ("standing", ("door", 14), 0.6, 0.22, "feet"),
    ("seated", ("desk", 14), 0.7, 0.25, "feet"),
    ("on_the_bed", ("phone", 14), 0.7, 0.35, "feet"),      # lying on top of the duvet with the phone: slides off, socks on
    ("asleep", ("sleeping", 23), 0.9, 0.6, "feet"),          # under the duvet at night
    ("parked", ("sleeping", 23), 0.55, 0.30, "parked"),      # the slides by the bed
]
AZ = [("front", 0), ("front-right", -0.8), ("front-left", 0.8), ("right", -1.57), ("left", 1.57), ("back-right", -2.4), ("back-left", 2.4), ("back", 3.14)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--no-shots", action="store_true")
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    h = Harness(out, log=lambda *x: print(*x, flush=True), cdn_cache=ROOT / "tests" / "visual" / ".cdn_cache")
    rep = {"tag": a.tag, "scenarios": [], "states": {}}
    with Server() as server, sync_playwright() as p:
        h.server = server; h.base = server.base; h.query = ""
        h.browser = p.chromium.launch(executable_path=CHROMIUM, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        ctx, pg, st = h.open("1280")
        h.goto_scene(pg, "door", 14)
        pg.wait_for_function("() => !window.mh || window.mh.ready", timeout=120000)
        pg.add_script_tag(path=str(Path(__file__).with_name("feet_probe.js")))
        rep["states"]["load"] = pg.evaluate("__feet.state()")
        print("state", rep["states"]["load"], flush=True)
        if not a.no_shots:
            for name, (scene, hour), dist, up, what in SHOTS:
                h.goto_scene(pg, scene, hour)
                pg.evaluate("for (let i = 0; i < 20; i++) animate_(1/30)")
                rep["states"][name] = pg.evaluate("__feet.state()")
                got = 0
                for vname, az in AZ:                 # the first three clear views, in this order
                    c = pg.evaluate(f"__feet.feetCam({az}, {dist}, {up}, {json.dumps(what)})")
                    if not c["clear"]:
                        continue
                    pg.evaluate("__qa.render()")
                    h.shoot(pg, out / f"{a.tag}_{name}_{vname}.png", hud=False)
                    rep["states"].setdefault("cams", {})[f"{name}_{vname}"] = c
                    got += 1
                    if got == 3:
                        break
                pg.evaluate("window.NOCLEAR = false; __qa.followCam()")
        for label, (scene, hour), setup, secs in SCENARIOS:
            if a.only and a.only not in label:
                continue
            h.goto_scene(pg, scene, hour)
            t0 = time.time()
            r = pg.evaluate(f"__feet.run(() => {{ {setup}; }}, {secs}, 3)")
            r["label"] = label; r["seconds"] = secs; r["state_end"] = pg.evaluate("__feet.state()"); r["wall_s"] = round(time.time() - t0, 1)
            pg.evaluate("if (window.mh && mh.show) mh.show(null)")
            rep["scenarios"].append(r)
            print(json.dumps(r), flush=True)
        rep["errors"] = st["errors"]
        h.browser.close()
    (out / f"probe_{a.tag}.json").write_text(json.dumps(rep, indent=1))
    print("errors", rep["errors"])


if __name__ == "__main__":
    main()
