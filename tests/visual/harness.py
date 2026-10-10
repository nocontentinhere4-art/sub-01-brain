"""The visual QA harness for /room (issue #98, G8): fixed-camera screenshots of the character in each activity, at
several Tokyo hours and two viewport sizes, plus automated checks. Run by hand:

    python -m tests.visual.harness --out tests/visual/out            # the core set (what CI runs; ~15 renders)
    python -m tests.visual.harness --full --out tests/visual/out     # every scene x hour x size, plus more flicker tests

It starts tests/visual/fake_server.py (web/ with a fake /ws), opens /room.html?debug in headless Chromium drawing
WebGL in software (SwiftShader: a CPU rasteriser, so FPS numbers are not a GPU's), freezes the page's own loop
(window.FREEZE) and steps the simulation itself (animate_), so every shot is deterministic: same pose, same light.

Checks, per shot or once per run (hard = fails CI; the rest is reported in results.json and report.md):
  hard   the page loads (boot screen gone, room + character + all clips), no JS errors, no failed own-origin request,
         the character reaches each scene's place and clip, the 3D canvas is not blank,
         bed/chair penetration within budgets.json (0 on main);
  soft   skinned vertices below the floor or inside the desk, feet off the floor when standing, props floating or
         sunk (vertical rays from each separate object), texture texels per metre, pure-black and blown-out pixel
         fractions of the 3D canvas, z-fighting (frame-to-frame flicker under a sub-millimetre camera move), FPS under
         a 4x CPU throttle and the character logic's ms per frame, draw calls and triangles.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from tests.visual import scenes as S                      # noqa: E402
from tests.visual import image_checks as IC               # noqa: E402
from tests.visual.fake_server import Server               # noqa: E402
from tests.visual.cdn_cache import CdnCache                # noqa: E402

CHROMIUM = os.environ.get("SUB01_CHROMIUM", "/opt/pw-browsers/chromium")
# the waits below poll on a timer (polling=100), not on requestAnimationFrame: the 390 page is a second, background page
# whose frames Chromium may not schedule, so a rAF-polled predicate could stay unevaluated though already true
GLB_FILES = 19                                              # room_clean, boy, 6 clips, hand_phone, food, props_tripo(2), mouse, controller, monitor, props_picked, sneakers_door, chair_owner, boy_moves
PIP_URL = "/mini-brain?mini"                                # the room's embed (#116), served as web/index.html; "&neurons=1" is the regression
BUDGETS = json.loads((HERE / "budgets.json").read_text())


def chromium_ok():
    """Playwright importable and a Chromium present: /opt/pw-browsers/chromium (SUB01_CHROMIUM) or Playwright's own."""
    try:
        import playwright.sync_api  # noqa: F401
    except Exception:
        return False
    if Path(CHROMIUM).exists():
        return True
    exe = _pw_chromium()
    return bool(exe) and Path(exe).exists()


def _pw_chromium():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            return p.chromium.executable_path
    except Exception:
        return None


def wait_js(pg, predicate, timeout=15000, every=100):
    """Poll a page predicate from here (pg.evaluate every `every` ms) until it is true or `timeout` ms pass.

    Playwright's wait_for_function polls inside the page (requestAnimationFrame, or a setTimeout chain with polling=N);
    on the second, background page Chromium may schedule neither for seconds at a time, so a true predicate went
    unseen (CI, desk@14 on the 390 page: the diagnostic evaluate right after the timeout showed the scene taken). An
    evaluate from here runs as soon as the page's main thread is free, whatever its timer throttling."""
    t0 = time.time()
    while True:
        if pg.evaluate(predicate):
            return True
        if (time.time() - t0) * 1000 > timeout:
            raise TimeoutError(f"wait_js: {timeout} ms exceeded")
        pg.wait_for_timeout(every)


class Harness:
    def __init__(self, out, full=False, log=print, cdn_cache=HERE / ".cdn_cache", only=None):
        self.out = Path(out); self.out.mkdir(parents=True, exist_ok=True)
        self.full = full; self.log = log; self.only = set(only or [])
        self.cdn = CdnCache(cdn_cache) if cdn_cache else None
        self.res = {"software_webgl": True, "full": full, "shots": {}, "closeups": {}, "flicker": {}, "props": {}, "hard_failures": [],
                    "note": "headless Chromium with SwiftShader: FPS is a CPU rasteriser's, not a phone GPU's; DPR 1"}
        if self.only and (self.out / "results.json").exists():      # an incremental run: the other scenes' results stay
            self.res = json.loads((self.out / "results.json").read_text())
            self.res["hard_failures"] = [h for h in self.res["hard_failures"] if not any(h.startswith((f"{sc}_", f"{sc}:")) for sc in self.only)]
            self.res["partial_rerun"] = sorted(self.only)
        self.pages = {}
        self.query = ""                                            # extra query for room.html (e.g. "&props=old")
        self.t0 = time.time()

    # ---- pages
    def open(self, size):
        if size in self.pages:
            return self.pages[size]
        w, h, mobile = S.SIZES[size]
        ctx = self.browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1, is_mobile=mobile, has_touch=mobile)
        pg = ctx.new_page()
        st = {"errors": [], "failed": [], "glb": 0, "console": []}
        pg.on("pageerror", lambda e: st["errors"].append(str(e)))
        pg.on("console", lambda m: st["console"].append(m.type + ": " + m.text) if m.type in ("error", "warning") else None)
        pg.on("requestfailed", lambda r: st["failed"].append(f"{r.url} ({r.failure})"))

        def on_resp(r):
            if r.url.endswith(".glb") and r.ok:
                st["glb"] += 1
            if r.status >= 400 and r.url.startswith(self.base) and not r.url.endswith("/favicon.ico"):
                st["failed"].append(f"{r.url} -> {r.status}")
        pg.on("response", on_resp)
        if self.cdn:
            self.cdn.install(pg)
        tb = time.time()
        pg.goto(self.base + "/room.html?debug&hour=14" + self.query, wait_until="load")
        # 300 s: the page boots with its loop drawing live (software GL), which on CI's 2 vCPUs took up to ~180 s (main
        # 448a0b8). Freezing the loop through the boot made it 15 s but changed what two scenes measured (7f2bf6e: walking_8
        # and eating_19 into the desk), so it is not done until that is understood.
        wait_js(pg, "() => !!(window.boy && window.room && !document.getElementById('boot') && Object.keys(window.actions).length >= 9)", timeout=300000)
        print(f"[visual] page {size} booted in {time.time() - tb:.0f} s", file=sys.stderr, flush=True)   # (CI: how close to the 180 s)
        t0 = time.time()
        while st["glb"] < GLB_FILES and time.time() - t0 < 60:
            pg.wait_for_timeout(200)
        # #98 G3's motion layer (room/boy_motion.js) swaps its clips in after boy_moves.glb: wait for it too (a no-op without it)
        wait_js(pg, "() => !window.motion || !!window.motion.ready", timeout=60000)
        pg.evaluate("window.FREEZE = true")
        pg.add_script_tag(content=(HERE / "page_checks.js").read_text())
        pg.wait_for_timeout(300)                                   # the last tick's UI timer
        st["markers_hidden"] = pg.evaluate("__qa.hideMarkers()")   # ?debug's magenta marker spheres: not what viewers see
        st["ready"] = pg.evaluate("__qa.ready()")
        st["glb_loaded"] = st["glb"]
        self.pages[size] = (ctx, pg, st)
        self.log(f"  page {size}: {st['ready']}, {st['glb']} GLBs, {time.time() - t0:.1f}s wait")
        return self.pages[size]

    # ---- scenes
    def snap(self, pg, name, hour):
        """The fake server sends this scene; once the page has its tick, snap him into it the way the page's first
        tick does (the debug act()), so the ticks that follow find him where they want him and plan nothing."""
        lf, stage, before, settle_s, at, clip, prep = S.scene(name)
        self.server.set_scene(name, hour)
        # (the side-pose scene leaves the page's ROLL state turned: put it back, or the next lie-down pose restarts)
        pg.evaluate(f"setHour({hour}); if (window.ROLL) {{ ROLL.force = null; ROLL.a = 0; ROLL.goal = 0; }}")
        try:
            wait_js(pg, f"() => {{ const p = pose(); return !!(p.goal && p.goal.anchor === {json.dumps(at or 'desk')} "
                        f"&& document.getElementById('clock').textContent.includes({json.dumps(S.clock(hour))})); }}", timeout=15000)
        except Exception as e:                                     # say where he was and what the page threw, not just "timeout"
            st = next((v[2] for v in self.pages.values() if v[1] is pg), {})
            state = pg.evaluate("JSON.stringify({pose: pose(), clock: document.getElementById('clock').textContent})")
            raise AssertionError(f"scene {name}@{hour}: page never took the scene ({e.__class__.__name__}); {state}; "
                                 f"page errors {st.get('errors', [])[:5]}") from e
        pg.evaluate(f"act({json.dumps(lf['activity'])}, {json.dumps(lf)}); __qa.clearFood()")
        pg.wait_for_timeout(250)                                   # a tick and the UI timer (screens(): monitor, phone, stage)

    def goto_scene(self, pg, name, hour):
        """Put him into a scene. Most scenes snap straight in; the phone in bed starts lying asleep and the fake
        server's phone tick brings the phone up; walking starts at the door and the research tick sends him off."""
        lf, stage, before, settle_s, at, clip, prep = S.scene(name)
        self.snap(pg, before or name, hour)
        if prep:
            pg.evaluate(prep)
        if before:                                                 # the next tick must change his goal (anchor or clip)
            was = pg.evaluate("JSON.stringify(pose().goal)")
            self.server.set_scene(name, hour)
            wait_js(pg, f"() => {{ const p = pose(); return !!(p.goal && JSON.stringify(p.goal) !== {json.dumps(was)} "
                        f"&& p.goal.anchor === {json.dumps(at or 'desk')}); }}", timeout=15000)
            pg.wait_for_timeout(250)
        if name == "walking":
            pose = self.walk_until(pg)
        else:
            pose = pg.evaluate(f"__qa.step(1/30, {int(round(settle_s * 30))})")
        pg.evaluate(f"settle(); __qa.settleWindow({hour})")
        pg.evaluate("__qa.followCam()")
        return pose

    def walk_until(self, pg):
        for _ in range(400):                                       # up to 40 simulated seconds to stand up and set off
            p = pg.evaluate("__qa.step(0.1, 1)")
            if p["step"] and p["step"]["k"] == "walk":
                break
        p = pg.evaluate("__qa.step(1/30, 24)")                     # 0.8 s into the walk: mid-stride, well off the door
        return p

    def shoot(self, pg, path, hud=True):
        pg.evaluate(f"__qa.hud({str(hud).lower()})")
        pg.screenshot(path=str(path), timeout=240000, animations="disabled")
        if not hud:
            pg.evaluate("__qa.hud(true)")

    def check_pose(self, key, name, pose):
        _, _, _, _, at, clip, _ = S.scene(name)
        if S.makehuman_rig():
            clip = S.MH_CLIP.get(name, clip)
        ok_at = at is None or pose.get("at") == at
        got = pose.get("clip") or ""
        # (the bed layer, room/boy_mh.js bedStep: with the mixamo character's Sova clips the bed plays its own takes over the
        # lie and sleep clips - bed_sleep_side, bed_bed_phone_watch_portrait, ...)
        ok_clip = clip is None or clip in got or (clip in ("mh_sleep", "mh_lie") and got.startswith("bed_"))
        if name == "walking":
            ok_at = bool(pose.get("step")) and pose["step"]["k"] == "walk"
        if not (ok_at and ok_clip):
            self.res["hard_failures"].append(f"{key}: expected at={at} clip~{clip}, got at={pose.get('at')} clip={pose.get('clip')} step={pose.get('step')}")
        return ok_at and ok_clip

    def shot(self, name, hour, size):
        ctx, pg, st = self.open(size)
        key = f"{name}_{hour}_{size}"
        t0 = time.time()
        pose = self.goto_scene(pg, name, hour)
        pg.evaluate("__qa.render()")
        r = {"scene": name, "hour": hour, "size": size, "pose": pose, "ok_pose": self.check_pose(key, name, pose)}
        self.shoot(pg, self.out / f"{key}.png", hud=True)
        self.shoot(pg, self.out / f"{key}_clean.png", hud=False)
        rect = pg.evaluate("__qa.canvasRect()")
        r["canvas"] = rect
        r["exposure"] = IC.exposure(self.out / f"{key}_clean.png", crop=rect)
        if r["exposure"]["black_frac"] > 0.97:
            self.res["hard_failures"].append(f"{key}: the 3D canvas is blank ({r['exposure']['black_frac']:.0%} black)")
        r["lights"] = pg.evaluate("__qa.lights()")
        r["screen"] = pg.evaluate("__qa.screenState()")               # the monitor and the follow camera: on only at the desk
        r["render"] = pg.evaluate("__qa.info()")
        if size == "1280":                                        # a medium shot of him too, from his front-right
            r["character_cam"] = pg.evaluate("__qa.characterCam()")
            pg.evaluate("__qa.render()")
            self.shoot(pg, self.out / f"{key}_char.png", hud=False)
            pg.evaluate("__qa.followCam()")
            if name in ("desk", "eating", "sleeping", "window") and hour in (14, 23):
                self.res["props"][key] = pg.evaluate("__qa.props()")    # (before the sweep below moves the clip on)
            # the worst frame over 8 s of the clip, not the one frame the scene stopped on (docs/qa/contact.md): a
            # single frame read 6 or 14 on the same code depending on how long the page took to load
            r["body"] = pg.evaluate("__qa.bodySweep(2, 8, 0.25)")
            b = r["body"]
            for what, field in (("bed", "bed"), ("chair", "chair"), ("desk", "desk"), ("desk_things", "things"), ("below_floor", "below_floor")):
                lim = BUDGETS.get(f"{what}_vertices")                   # null: reported, not failed
                if lim is not None and b[field] > lim:
                    self.res["hard_failures"].append(f"{key}: {what} penetration {b[field]} sampled vertices at {b['sweep']['worst_at_s'][field]} s of 8 (budget {lim})")
        r["seconds"] = round(time.time() - t0, 1)
        self.res["shots"][key] = r
        self.log(f"  {key}: pose {pose.get('at')}/{pose.get('clip')} monitor {'on' if r['screen']['monitor_on'] else 'off'} cam {r['screen']['camera']} black {r['exposure']['black_frac']:.1%} "
                 f"body bed {r.get('body', {}).get('bed', '-')} chair {r.get('body', {}).get('chair', '-')} {r['seconds']}s")
        return r

    def closeup(self, cname, scene, hour, recipe=None, size="1280"):
        ctx, pg, st = self.open(size)
        t0 = time.time()
        self.goto_scene(pg, scene, hour)
        cam = pg.evaluate(f"__qa.closeup({json.dumps(recipe or cname)})")
        pg.evaluate("__qa.render()")
        path = self.out / f"closeup_{cname}_{hour}.png"
        self.shoot(pg, path, hud=False)
        rect = pg.evaluate("__qa.canvasRect()")
        r = {"scene": scene, "hour": hour, "camera": cam, "exposure": IC.exposure(path, crop=rect), "seconds": round(time.time() - t0, 1)}
        self.res["closeups"][cname] = r
        self.log(f"  close-up {cname} ({scene}@{hour}): {r['seconds']}s")
        pg.evaluate("__qa.followCam()")

    def flicker(self, scene, hour, size="1280", frames=5):
        ctx, pg, st = self.open(size)
        self.goto_scene(pg, scene, hour)
        pg.evaluate("__qa.hud(false)")
        paths = []
        for i in range(frames):                                   # the camera creeps sideways 0.7 mm a frame, one direction
            pg.evaluate(f"__qa.jitter({0 if i == 0 else 1})")
            p = self.out / f"flicker_{scene}_{hour}_{i}.png"
            pg.screenshot(path=str(p), timeout=240000, animations="disabled")
            paths.append(p)
        pg.evaluate("__qa.hud(true)")
        rect = pg.evaluate("__qa.canvasRect()")
        f = IC.flicker(paths, crop=rect)
        mask = f.pop("mask", None)
        if mask is not None and f["flagged_pixels"]:
            IC.save_mask(mask, paths[0], self.out / f"flicker_{scene}_{hour}_mask.png", crop=rect)
            f["mask_image"] = f"flicker_{scene}_{hour}_mask.png"
        for p in paths[1:]:
            p.unlink()
        paths[0].rename(self.out / f"flicker_{scene}_{hour}.png")
        self.res["flicker"][f"{scene}_{hour}"] = f
        self.log(f"  flicker {scene}@{hour}: {f['flicker_frac']:.3%} of the canvas, {len(f['regions'])} regions")

    def perf(self):
        ctx, pg, st = self.open("1280")
        self.goto_scene(pg, "desk", 14)
        self.res["animate_ms_per_frame_1280"] = pg.evaluate("__qa.animateMs(120)")
        self.res["textures"] = pg.evaluate("__qa.textures()")
        ctx2, pg2, st2 = self.open("390")
        self.goto_scene(pg2, "desk", 14)
        cdp = ctx2.new_cdp_session(pg2)
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
        fps = pg2.evaluate("__qa.fps(4000)")
        ams = pg2.evaluate("__qa.animateMs(60)")
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
        self.res["fps_390_cpu_x4_software_gl"] = fps
        self.res["animate_ms_per_frame_390_cpu_x4"] = ams
        self.log(f"  perf: animate {self.res['animate_ms_per_frame_1280']} ms/frame (1280), {ams} ms/frame (390, CPU x4); "
                 f"software-GL fps {fps['fps']} at 390 CPU x4")

    # ---- the room's mini brain (the PiP iframe loads /brain?mini since #116): a rendered no-dots check
    def pip(self):
        ctx = self.browser.new_context(viewport={"width": 300, "height": 225}, device_scale_factor=1)
        pg = ctx.new_page()
        errors, failed = [], []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("requestfailed", lambda r: failed.append(f"{r.url} ({r.failure})"))
        pg.on("response", lambda r: failed.append(f"{r.url} -> {r.status}") if r.status >= 400 and r.url.startswith(self.base) and not r.url.endswith("/favicon.ico") else None)
        if self.cdn:
            self.cdn.install(pg)
        t0 = time.time()
        # the room's own embed: what URL it loads (#116: /brain?mini, without neurons=1)
        with urllib.request.urlopen(self.base + "/room.html", timeout=30) as resp:
            room_html = resp.read().decode("utf-8", "replace")
        m = re.search(r'<a id="brainpip"[^>]*>\s*<iframe[^>]*\s(?:data-)?src="([^"]*)"', room_html)
        embed_src = m.group(1) if m else None
        pg.goto(self.base + PIP_URL, wait_until="load")
        try:
            pg.wait_for_function("renderer.info.render.calls > 0 && renderer.info.render.lines + renderer.info.render.triangles > 1000", timeout=120000)
        except Exception as e:                                      # noqa: BLE001  (also a ReferenceError: the page's script died before its renderer)
            self.res["pip"] = {"url": "/brain?mini", "embed_src": embed_src, "errors": errors, "failed": failed, "started": False}
            self.res["hard_failures"].append(f"pip: the mini brain did not start rendering ({type(e).__name__}; errors {errors[:3]}; failed {failed[:3]})")
            ctx.close()
            return
        pg.wait_for_timeout(6000)                                   # a few more frames: the fibres and the live feed
        pg.add_style_tag(content="#n3mini{display:none!important}")
        pg.wait_for_timeout(1500)
        path = self.out / "pip_mini_brain.png"
        pg.screenshot(path=str(path), timeout=240000, animations="disabled")
        info = pg.evaluate("""({calls: renderer.info.render.calls, points: renderer.info.render.points, lines: renderer.info.render.lines,
            triangles: renderer.info.render.triangles, neurons_wanted: typeof n3want !== 'undefined' ? !!n3want : null,
            forest: typeof n3d !== 'undefined' ? !!n3d : null, n3_class: document.body.classList.contains('n3'),
            text: (document.getElementById('n3mini') || {}).innerText || ''})""")
        sp = IC.specks(path)
        mask = sp.pop("mask")
        if sp["specks"]:
            IC.save_mask(mask, path, self.out / "pip_mini_brain_specks.png")
        exp = IC.exposure(path)
        r = {"url": "/brain?mini (served as web/index.html)", "embed_src": embed_src, "size": [300, 225], "render": info, "exposure": exp,
             "specks": sp["specks"], "largest": sp["largest"], "bright_frac": sp["bright_frac"], "errors": errors, "failed": failed,
             "started": True, "seconds": round(time.time() - t0, 1)}
        self.res["pip"] = r
        for e in errors:
            self.res["hard_failures"].append(f"pip: JS error: {e}")
        for f in failed:
            self.res["hard_failures"].append(f"pip: request failed: {f}")
        if embed_src is None or not embed_src.startswith("/brain?mini") or "neurons=1" in embed_src:
            self.res["hard_failures"].append(f"pip: the room embeds {embed_src!r}; expected /brain?mini without neurons=1 (#116)")
        if exp["black_frac"] > 0.97:
            self.res["hard_failures"].append("pip: the mini brain rendered blank")
        if info["points"] > 0:
            self.res["hard_failures"].append(f"pip: {info['points']} points drawn (a THREE.Points layer: dots)")
        if info["neurons_wanted"] or info["forest"] or info["n3_class"]:
            self.res["hard_failures"].append("pip: the neuron forest is on in the mini brain (its cells read as dots at 300 px; #116)")
        if sp["bright_frac"] < 0.05:
            self.res["hard_failures"].append(f"pip: the fibres are dim or missing ({sp['bright_frac']:.1%} of the frame bright; 20% on main; "
                                             "they step back to <1% when the forest is on)")
        lim = BUDGETS.get("pip_draw_calls")
        if lim is not None and info["calls"] > lim:
            self.res["hard_failures"].append(f"pip: {info['calls']} draw calls in the mini brain (budget {lim}; 2 on main, 9 with the forest)")
        lim = BUDGETS.get("pip_specks")
        if lim is not None and sp["specks"] > lim:
            self.res["hard_failures"].append(f"pip: {sp['specks']} bright specks in the mini brain (budget {lim})")
        self.log(f"  pip /brain?mini: embed {embed_src}, forest {info['forest']}, calls {info['calls']}, points {info['points']}, lines {info['lines']}, "
                 f"tris {info['triangles']}, specks {sp['specks']}, bright {sp['bright_frac']:.1%}, black {exp['black_frac']:.1%}, {r['seconds']}s")
        ctx.close()

    # ---- the run
    def run(self):
        from playwright.sync_api import sync_playwright
        with Server() as server, sync_playwright() as p:
            self.server = server; self.base = server.base
            exe = CHROMIUM if Path(CHROMIUM).exists() else None
            self.browser = p.chromium.launch(executable_path=exe, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
            try:
                shots = S.FULL_SHOTS if self.full else S.CORE_SHOTS
                pick = lambda sc: not self.only or sc in self.only            # noqa: E731  (--only: a subset of scenes)
                # one page per size; scenes in a stable order so the before-scenes (sleeping before phone) cost little
                for name, hour, size in sorted(shots, key=lambda t: (t[2], t[1], list(S.SCENES).index(t[0]))):
                    if pick(name):
                        self.shot(name, hour, size)
                for cname, (scene, hour, recipe) in S.CLOSEUPS.items():
                    if pick(scene):
                        self.closeup(cname, scene, hour, recipe)
                for scene, hour in ([("desk", 14), ("window", 19), ("sleeping", 23), ("door", 8)] if self.full else [("desk", 14)]):
                    if pick(scene):
                        self.flicker(scene, hour)
                if pick("pip"):
                    self.pip()
                if not self.only:
                    self.perf()
            finally:
                for size, (ctx, pg, st) in self.pages.items():
                    self.res[f"page_{size}"] = {k: st[k] for k in ("errors", "failed", "glb_loaded", "ready")}
                    self.res[f"page_{size}"]["console"] = st["console"][:40]
                    for e in st["errors"]:
                        self.res["hard_failures"].append(f"page {size}: JS error: {e}")
                    for f in st["failed"]:
                        self.res["hard_failures"].append(f"page {size}: request failed: {f}")
                    if st["glb_loaded"] < GLB_FILES:
                        self.res["hard_failures"].append(f"page {size}: only {st['glb_loaded']}/{GLB_FILES} GLB files loaded")
                    ctx.close()
                self.browser.close()
        self.res["seconds"] = round(time.time() - self.t0, 1)
        if self.cdn:
            self.res["cdn_cache"] = {"hits": self.cdn.hits, "misses": self.cdn.misses, "failed": self.cdn.failed}
            for f in self.cdn.failed:
                self.res["hard_failures"].append(f"CDN fetch failed: {f}")
        (self.out / "results.json").write_text(json.dumps(self.res, indent=1, ensure_ascii=False) + "\n")
        self.report()
        self.log(f"done in {self.res['seconds']}s: {len(self.res['hard_failures'])} hard failures -> {self.out / 'report.md'}")
        return self.res

    # ---- the report
    def report(self):
        R = self.res
        L = [f"# Visual QA run ({'full' if R['full'] else 'core'} set)", "",
             f"{R['seconds']} s, software WebGL (SwiftShader), DPR 1. Hard failures: **{len(R['hard_failures'])}**.", ""]
        for h in R["hard_failures"]:
            L.append(f"- HARD: {h}")
        L += ["", "## Shots", "", "| shot | place / clip | black | blown | mean lum | bed | chair | desk | below floor | feet y (L/R) | draw calls | tris | s |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for k, r in R["shots"].items():
            b = r.get("body", {}); e = r["exposure"]; fy = b.get("foot_min_y", {})
            him = f", [him]({k}_char.png)" if "character_cam" in r else ""
            L.append(f"| [{k}]({k}.png) ([clean]({k}_clean.png){him}) | {r['pose'].get('at')} / {r['pose'].get('clip')} | {e['black_frac']:.1%} | {e['blown_frac']:.2%} | {e['mean_lum']} | "
                     f"{b.get('bed', '')} | {b.get('chair', '')} | {b.get('desk', '')} | {b.get('below_floor', '')} | {fy.get('Left', '')}/{fy.get('Right', '')} | "
                     f"{r['render']['calls']} | {r['render']['triangles']} | {r['seconds']} |")
        L += ["", "## Close-ups", ""]
        for k, r in R["closeups"].items():
            L.append(f"- **{k}** ({r['scene']} @ {r['hour']}): [closeup_{k}_{r['hour']}.png](closeup_{k}_{r['hour']}.png), mean lum {r['exposure']['mean_lum']}")
        L += ["", "## Z-fighting (flicker under a sub-mm camera move)", ""]
        for k, f in R["flicker"].items():
            L.append(f"- {k}: {f['flicker_frac']:.3%} of the canvas flagged ({f.get('flagged_pixels', 0)} px), regions {f['regions']}"
                     + (f" — [mask]({f['mask_image']})" if f.get("mask_image") else ""))
        L += ["", "## Props (rays down from each separate object)", ""]
        for k, props in R["props"].items():
            bad = [p for p in props if p["verdict"] not in ("ok", "hangs")]
            L.append(f"- {k}: {len(props)} objects, {len(bad)} not resting: " + "; ".join(f"{p['name']} {p['verdict']} ({p['gap_mm']} mm)" for p in bad))
        L += ["", "## Textures (texels per metre of the object's longest side)", ""]
        for t in sorted(R.get("textures", []), key=lambda t: (t["texels_per_m"] is None, t["texels_per_m"] or 0))[:16]:
            L.append(f"- {t['material'] or '?'} {t['kind']} {t['size'][0]}x{t['size'][1]} on {', '.join(t['objects'])} ({t['max_dim_m']} m): {t['texels_per_m']} texels/m, anisotropy {t['aniso']}")
        if R.get("pip"):
            p = R["pip"]
            L += ["", "## The room's mini brain (/brain?mini, 300x225)", "", f"- the room embeds `{p.get('embed_src')}` (#116: /brain?mini without neurons=1)"]
            if p.get("started"):
                L.append(f"- [pip_mini_brain.png](pip_mini_brain.png): neuron forest {p['render']['forest']}, draw calls {p['render']['calls']}, THREE.Points drawn "
                         f"{p['render']['points']}, lines {p['render']['lines']}, triangles {p['render']['triangles']}, bright {p['bright_frac']:.1%} of the frame, "
                         f"black {p['exposure']['black_frac']:.1%}, errors {len(p['errors'])}; {p['specks']} small bright blobs (the fibres' beads count too: "
                         f"140 on main, 189 with the forest, so a texture figure, not the dots test)"
                         + (f" — [blobs]({'pip_mini_brain_specks.png'})" if p['specks'] else ""))
            else:
                L.append(f"- the mini brain did not start rendering: errors {p['errors'][:3]}, failed requests {p['failed'][:3]}")
        L += ["", "## Performance", "",
              f"- character logic (animate) at 1280: {R.get('animate_ms_per_frame_1280')} ms/frame; at 390 under CPU x4: {R.get('animate_ms_per_frame_390_cpu_x4')} ms/frame",
              f"- software-GL frames at 390, CPU x4, 4 s: {R.get('fps_390_cpu_x4_software_gl')} (a CPU rasteriser: not a phone number)"]
        for size in ("1280", "390"):
            pgr = R.get(f"page_{size}", {})
            L.append(f"- page {size}: {pgr.get('glb_loaded')} GLBs, errors {len(pgr.get('errors', []))}, failed requests {len(pgr.get('failed', []))}, console {len(pgr.get('console', []))}")
        (self.out / "report.md").write_text("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tests/visual/out")
    ap.add_argument("--full", action="store_true", help="every scene x hour x size (the heavy set); default: the core set CI runs")
    ap.add_argument("--no-cdn-cache", action="store_true", help="let the browser fetch three.js and leaflet itself (default: cached through Python)")
    ap.add_argument("--only", default=None, help="comma-separated scenes to (re)run; with an existing results.json in --out the rest is kept")
    args = ap.parse_args()
    res = Harness(ROOT / args.out, full=args.full, cdn_cache=None if args.no_cdn_cache else HERE / ".cdn_cache",
                  only=[x for x in (args.only or "").split(",") if x]).run()
    sys.exit(1 if res["hard_failures"] else 0)


if __name__ == "__main__":
    main()
