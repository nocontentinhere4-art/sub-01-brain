"""Contact checks for the room upgrade (preview/room-upgrade): his skinned vertices against the desk chair (all of him)
and against the keyboard, the mouse and the game controller (his hands and fingers), frame by frame through every
seated scenario, and (v5) in bed against the mattress (a plane) and the page's duvet over him (poking through it), in the
page's own states (?debug act() / live() / variant()). Prints a JSON report.

    python -m tests.visual.contacts [--out DIR] [--stride 2] [--every 1]

A hit is a vertex inside a closed mesh (tests/visual/contacts.js: inside-intervals on 5 mm columns), with its depth."""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.visual.harness import Harness, CHROMIUM          # noqa: E402
from tests.visual.fake_server import Server                  # noqa: E402

DESK = "act('research', {screen: {device: 'desk', id: 'p1', kind: 'page'}}); for (let i = 0; i < 60; i++) animate_(1/30)"
SEAT = DESK + "; variant('%s', 7)"                         # an idle variant in the chair, forced (it is picked at random)
SCENARIOS = [  # label, setup (JS), seconds: the live character's seated clips and the ways in and out of the chair
    ("desk typing", "act('research', {screen: {device: 'desk', id: 'q1', kind: 'page', query: 'ramen near kichijoji'}})", 10),
    ("desk mouse", "act('research', {screen: {device: 'desk', id: 'c1', kind: 'page'}})", 8),
    ("desk watch", "act('watch_video', {screen: {device: 'desk', id: 'v1', kind: 'video'}})", 6),
    ("desk chess", "act('play_chess', {screen: {device: 'desk', id: 'k1', kind: 'chess'}})", 6),
    ("eating at the desk", "act('eat', {eating: 'ramen', food: 1})", 8),
    ("seated: leaning back", SEAT % "lean", 8),
    ("seated: legs", SEAT % "legs", 8),
    ("seated: drinking", SEAT % "drink", 8),
    ("seated: phone", SEAT % "phone", 8),
    ("seated: stretch / scratch / look", DESK + "; variant('scratch', 3)", 4),
    ("getting up to the window", DESK + "; live('window', {activity: 'window'})", 12),
    ("bedtime: get up, to bed", DESK + "; live('sleep', {activity: 'sleep'})", 22),
    ("sitting down at the desk", "act('window'); for (let i = 0; i < 30; i++) animate_(1/30); live('research', {screen: {device: 'desk', id: 'p2', kind: 'page'}})", 16),
]

MH_DESK = "act('research', {screen: {device: 'desk', id: 'p1', kind: 'page'}})"
SCENARIOS_MH = [  # the room clips under room/boy_mh.js (preview/room-mh; v5 on preview/room-v5): label, setup (JS), seconds or an act clip
    ("desk typing", "act('research', {screen: {device: 'desk', id: 'q1', kind: 'page', search: {query: 'ramen near kichijoji'}}})", 10),
    ("desk mouse", "act('research', {screen: {device: 'desk', id: 'c1', kind: 'page'}})", 8),
    ("desk watch", "act('watch_video', {screen: {device: 'desk', id: 'v1', kind: 'video'}})", 6),
    ("room_read", MH_DESK + "; for (let i = 0; i < 30; i++) animate_(1/30); mh.show('read')", "read"),
    ("room_phone", MH_DESK + "; for (let i = 0; i < 30; i++) animate_(1/30); mh.show('phone')", "phone"),
    ("room_phone_scroll", MH_DESK + "; for (let i = 0; i < 30; i++) animate_(1/30); mh.show('phone_scroll')", "phone_scroll"),
    ("eating at the desk", "act('eat', {eating: 'ramen', food: 1})", 8),
    ("bedtime: stretch, get up, to bed", MH_DESK + "; for (let i = 0; i < 60; i++) animate_(1/30); live('sleep', {activity: 'sleep'})", 22),
    ("getting up to the window", MH_DESK + "; for (let i = 0; i < 60; i++) animate_(1/30); live('window', {activity: 'window'})", 12),
    ("sitting down at the desk", "act('window'); for (let i = 0; i < 30; i++) animate_(1/30); live('research', {screen: {device: 'desk', id: 'p2', kind: 'page'}})", 16),
    # in bed (from the harness's sleeping scene, 23:00, under the duvet): the mattress and the duvet, and how far over it he lies
    ("in bed, asleep (mh_sleep: room_bedtime's end)", "", 8, "sleeping"),
    ("waking, out of bed (room_bed_wake)", "live('window', {activity: 'window'})", 10, "sleeping"),
]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "tests" / "visual" / "out"))
    ap.add_argument("--stride", type=int, default=2)
    ap.add_argument("--every", type=int, default=1)
    ap.add_argument("--only", default="")
    ap.add_argument("--chair-sdf", default="", help="a signed distance grid of the chair (tests/visual/chair_sdf.py) for its test, in place of ray parity")
    ap.add_argument("--chair-tol-mm", type=int, default=2)
    ap.add_argument("--chair-regions", action="store_true", help="split the chair's hits by where on it (chair@arm / front / seat / back / base)")
    ap.add_argument("--occupancy", default="", help="instead of the checks: write where his skin goes in the chair's frame (JSON)")
    ap.add_argument("--query", default="", help="extra query for the page, e.g. '&bottle=old' to probe the prop it replaced")
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    h = Harness(out, log=lambda *x: None, cdn_cache=ROOT / "tests" / "visual" / ".cdn_cache")
    report = {"objects": None, "scenarios": []}
    with Server() as server, sync_playwright() as p:
        h.server = server; h.base = server.base; h.query = a.query
        h.browser = p.chromium.launch(executable_path=CHROMIUM, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        ctx, pg, st = h.open("1280"); h.goto_scene(pg, "desk", 14)
        pg.wait_for_function("() => !window.mh || window.mh.ready", timeout=120000)
        if a.chair_sdf:                                    # (a generated chair is not closed: its grid instead)
            import base64
            import numpy as np
            z = np.load(a.chair_sdf)
            pg.evaluate(f"window.__chairRegions = {'true' if a.chair_regions else 'false'}")
            pg.evaluate("(g) => { window.__chairSDF = g; }", {"b64": base64.b64encode(z["sd"].astype(np.int8).tobytes()).decode(), "lo": z["lo"].tolist(),
                                                              "step": float(z["step"]), "dims": list(z["sd"].shape), "tol": a.chair_tol_mm,
                                                              "part": base64.b64encode(z["part"].tobytes()).decode() if "part" in z else None})
        pg.add_script_tag(path=str(Path(__file__).with_name("contacts.js")))
        report["objects"] = pg.evaluate("__contacts.build()")
        mh = pg.evaluate("() => !!window.mh")                       # (boy_mh.js drives him: its clips' scenarios)
        for label, setup, secs, *start in (SCENARIOS_MH if mh else SCENARIOS):
            if a.only and a.only not in label:
                continue
            if start:                                      # (a scenario that starts in one of the harness's scenes)
                h.goto_scene(pg, start[0], 23)
            if isinstance(secs, str):                      # a showcase clip: one loop of it
                secs = pg.evaluate(f"(() => {{ const c = mh.M.actions['act_{secs}']; return c ? c.getClip().duration : 0; }})()")
            t0 = time.time()
            if a.occupancy:
                occ = pg.evaluate(f"__contacts.occupy(() => {{ {setup}; }}, {secs}, {a.stride}, {a.every})")
                pg.evaluate("if (window.mh && mh.show) mh.show(null)")
                report.setdefault("occupancy", {})[label] = occ
                print(label, len(occ), "voxels", round(time.time() - t0, 1), "s", flush=True)
                continue
            r = pg.evaluate(f"__contacts.run({json.dumps(label)}, () => {{ {setup}; }}, {secs}, {a.stride}, {a.every})")
            pg.evaluate("if (window.mh && mh.show) mh.show(null)")
            r["seconds"] = round(secs, 2); r["wall_s"] = round(time.time() - t0, 1)
            report["scenarios"].append(r)
            print(json.dumps(r), flush=True)
        report["errors"] = st["errors"]
        h.browser.close()
    if a.occupancy:
        Path(a.occupancy).write_text(json.dumps(report["occupancy"]))
        return
    (out / "contacts.json").write_text(json.dumps(report, indent=1))
    print("objects", report["objects"])
    print("errors", report["errors"])


if __name__ == "__main__":
    main()
