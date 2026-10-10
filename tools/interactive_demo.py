"""The demo recording for preview/interactive (docs/qa/interactive/demo.mp4): the vote on what he does next and the
reactions with his glance, on the demo server, desktop then a 390 px phone.

Headless Chromium draws the room with software GL (SwiftShader): one 3D frame takes ~15 s here, so this is not a
screencast. The page runs with ?debug and FREEZE: the 3D view is rendered on keyframes (sim(), the page's own step) and
held as an image between them, the page's CSS animations (the reactions floating up) are stepped on a virtual clock,
one step per video frame, and a few bot viewers (websockets with their own cookie and user agent) vote and react.
Everything shown comes from the running server: the counts, the round's end, the result, the nudge, the glance.

    python live_server.py --demo ...            (started by this script, in a temporary data dir)
    python tools/interactive_demo.py --out docs/qa/interactive/demo.mp4
"""
import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import aiohttp
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
PORT = 8791
SNAP_JS = """() => {                      // render the 3D once and hold it as an image (screenshots stay cheap)
  renderer.render(scene, camera);
  const url = renderer.domElement.toDataURL("image/jpeg", 0.92);
  let im = document.getElementById("__snap");
  if (!im) { im = document.createElement("img"); im.id = "__snap";
    Object.assign(im.style, {position: "absolute", left: 0, top: 0, width: "100%", height: "100%", pointerEvents: "none"});
    renderer.domElement.parentNode.appendChild(im); }
  im.src = url; renderer.domElement.style.visibility = "hidden";
  return new Promise(r => { if (im.complete) r(); else im.onload = () => r(); });
}"""
FOLLOW_JS = """() => {                    // the page's own follow camera, snapped to its goal (no easing between keyframes)
  updateCameraGoal(); camera.position.copy(camGoal.pos); controls.target.copy(camGoal.target); controls.update();
}"""
FACE_JS = """() => {                      // a camera in front of him and to his side, on his face (for the glance)
  const V = THREE.Vector3; boy.updateMatrixWorld(true);
  const h = bones.Head.getWorldPosition(new V()), f = boy.getWorldDirection(new V()).setY(0).normalize(), s = new V(f.z, 0, -f.x);
  camera.position.copy(h).addScaledVector(f, 0.62).addScaledVector(s, 0.7).add(new V(0, 0.06, 0));
  controls.target.copy(h).add(new V(0, -0.12, 0)); controls.update();
}"""
STEP_CSS_JS = """dt => {                      // the page's CSS animations on a virtual clock: one step per video frame
  for (const a of document.getAnimations()) {
    if (!a.__v) { a.__v = 1; a.pause(); a.currentTime = 0; continue; }
    a.currentTime = (a.currentTime || 0) + dt * 1000;
    const end = a.effect && a.effect.getComputedTiming().endTime;
    if (isFinite(end) && a.currentTime >= end) { const el = a.effect.target; if (el && el.parentNode && el.parentNode.id === "rxfloat") el.remove(); }
  }
}"""


class Bot:
    def __init__(self, i, session):
        self.i, self.s, self.ws, self.hello = i, session, None, None

    async def connect(self):
        self.ws = await self.s.ws_connect(f"http://127.0.0.1:{PORT}/ws?rate=1&lite=1",
                                          headers={"Cookie": f"sub01v=demo-bot-{self.i}", "User-Agent": f"demo-bot/{self.i}"})
        self.hello = json.loads((await self.ws.receive()).data)
        asyncio.ensure_future(self.drain())

    async def drain(self):
        async for _ in self.ws:
            pass

    async def send(self, d):
        await self.ws.send_str(json.dumps(d))


async def api(path):
    async with aiohttp.ClientSession() as s:
        async with s.get(f"http://127.0.0.1:{PORT}{path}") as r:
            return await r.json()


class Rec:
    def __init__(self, page, outdir, tag):
        self.pg, self.dir, self.tag, self.frames, self.last_sim = page, outdir, tag, [], time.time()
        self.cam = FOLLOW_JS

    async def sim(self, step=None):
        """Advance his animation (by the real time since the last render, or `step` seconds) and render the 3D."""
        el = time.time() - self.last_sim if step is None else step
        self.last_sim = time.time()
        n = max(1, min(300, round(el / 0.1)))
        await self.pg.evaluate(f"sim({el / n:.4f}, {n})")
        if self.cam:
            await self.pg.evaluate(self.cam)
        await self.pg.evaluate(SNAP_JS)

    async def frame(self, dur, dt=0.1):
        await self.pg.evaluate(STEP_CSS_JS, dt)
        p = self.dir / f"{self.tag}_{len(self.frames):04d}.png"
        await self.pg.screenshot(path=str(p), timeout=240000)
        self.frames.append((p, dur))

    async def hold(self, seconds, fps=10, render_every=None):
        for k in range(int(seconds * fps)):
            if render_every and k % render_every == 0:
                await self.sim()
            await self.frame(1 / fps)


async def open_page(b, vp, mobile):
    ctx = await b.new_context(viewport=vp, is_mobile=mobile, has_touch=mobile, device_scale_factor=1)
    pg = await ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    await pg.goto(f"http://127.0.0.1:{PORT}/?debug", wait_until="domcontentloaded")
    await pg.wait_for_function("typeof boy !== 'undefined' && boy && typeof sim === 'function' && window.GLANCE", timeout=300000)
    await pg.wait_for_timeout(4000)
    await pg.evaluate("window.FREEZE = true")
    return ctx, pg, errs


def pick_option(vote, avoid):
    """The option bots favour: one that is not what he is doing now, the desk ones first (the glance shows best there)."""
    opts = [o["act"] for o in vote["round"]["options"]]
    for a in ("research", "watch_video", "play_chess", "window", "listen_music", "phone", "park"):
        if a in opts and a != avoid:
            return opts.index(a)
    return 0


async def main(args):
    tmp = Path(tempfile.mkdtemp(prefix="sub01-demo-"))
    frames = tmp / "frames"
    frames.mkdir()
    env = dict(os.environ, BROWSE="0", SUB01_SPIKING_LIVE="0", SUB01_MAX_WS_PER_IP="60")
    srv = subprocess.Popen([sys.executable, str(ROOT / "live_server.py"), "--demo", "--port", str(PORT), "--data-dir",
                            str(tmp / "data"), "--start", args.start, "--time-scale", "1.001", "--vote-round", str(args.round)],
                           cwd=ROOT, env=env, stdout=open(tmp / "server.log", "w"), stderr=subprocess.STDOUT)
    log = []
    try:
        for _ in range(120):
            try:
                await api("/api/vote")
                break
            except Exception:
                await asyncio.sleep(1)
        async with async_playwright() as p, aiohttp.ClientSession() as s:
            b = await p.chromium.launch(executable_path=args.chromium,
                                        args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
            bots = [Bot(i, s) for i in range(14)]
            for bot in bots:
                await bot.connect()

            # --- desktop -------------------------------------------------------------------------------------------
            ctx, pg, errs = await open_page(b, {"width": 1280, "height": 720}, False)
            r = Rec(pg, frames, "d")
            v = await api("/api/vote")
            while not v["round"] or v["round"]["ends_in"] < 45:          # a fresh round with time to vote in
                await asyncio.sleep(2)
                v = await api("/api/vote")
            life = await pg.evaluate("document.getElementById('story').textContent")
            life = next((a for a, w in (("research", "read"), ("watch_video", "video"), ("play_chess", "chess"),
                                        ("listen_music", "music"), ("window", "window"), ("phone", "phone")) if w in life), "")
            k = pick_option(v, life)
            log.append(f"round {v['round']['id']}: {[o['act'] for o in v['round']['options']]}, he is {life}; bots favour {k}")
            await r.sim()
            await r.hold(1.5)
            await pg.click(f"#v-opts .opt[data-k='{k}']")                # the page's viewer votes
            await r.hold(1.0)
            plan = [k] * 7 + [(k + 1) % 3] * 3 + [(k + 2) % 3]
            for i, choice in enumerate(plan):                            # the other viewers vote, one by one
                await bots[i].send({"type": "vote", "k": choice})
                await r.frame(0.25)
            await r.hold(1.0)
            await bots[0].send({"type": "vote", "k": (k + 1) % 3})        # a second vote from the same viewer: refused
            ends = (await api("/api/vote"))["round"]["ends_in"]
            log.append(f"votes cast; round ends in {ends} s")
            while (await api("/api/vote"))["round"]["id"] == v["round"]["id"]:   # until the round ends (real time)
                await r.frame(0.12)
                await asyncio.sleep(0.6)
            await r.hold(1.5)
            res = (await api("/api/vote"))["last"]
            log.append(f"result: {res}")
            for _ in range(24):                                          # the nudge: he gets up for it
                await r.sim()
                await r.hold(0.3)
                story = await pg.evaluate("document.getElementById('story').textContent")
                if any(w in story for w in ("reading", "at the computer", "watching", "chess")) and \
                        await pg.evaluate("roomDbg().at === 'desk'"):
                    break
            for _ in range(4):                                           # he sits down
                await r.sim()
                await r.hold(0.3)
            log.append("he is now: " + await pg.evaluate("document.getElementById('story').textContent + ' / ' + document.getElementById('why').textContent"))
            # reactions: everyone taps; a spike (>= 10 in 10 s) makes him glance at the camera once
            r.cam = None
            await pg.evaluate(FACE_JS)
            await r.sim()
            await r.hold(0.8)
            await pg.click("#rx button >> nth=1")
            for i, bot in enumerate(bots[:12]):
                await bot.send({"type": "react", "k": i % 6})
                if i % 3 == 2:
                    await r.frame(0.1)
            await pg.wait_for_function("window.GLANCE.active", timeout=10000)
            log.append("glance received (desktop)")
            for i in range(16):                                         # the glance itself, 3D every frame
                await r.sim(0.15)
                await r.frame(0.15, dt=0.15)
            await r.hold(1.0)
            log.append(f"desktop page errors: {errs[:3]}")
            await ctx.close()

            # --- phone, 390 px ------------------------------------------------------------------------------------------
            ctx, pg, errs = await open_page(b, {"width": 390, "height": 844}, True)
            r2 = Rec(pg, frames, "p")
            await r2.sim()
            await r2.hold(1.2)
            await pg.evaluate("document.getElementById('votecard').scrollIntoView({block: 'center'})")
            await r2.hold(2.0)
            vote = await api("/api/vote")
            if vote["round"]:
                await pg.click("#v-opts .opt >> nth=0")
                for i in range(5):
                    await bots[i].send({"type": "vote", "k": i % 3})
                    await r2.frame(0.2)
            await r2.hold(1.5)
            await pg.evaluate("window.scrollTo(0, 0)")
            await r2.sim()
            await r2.hold(0.8)
            for i, bot in enumerate(bots):                               # reactions on the phone (no glance: 2 min apart)
                await bot.send({"type": "react", "k": (i * 5) % 6})
                if i % 2:
                    await r2.frame(0.1)
            await pg.click("#rx button >> nth=4")
            await r2.hold(3.0)
            log.append(f"phone page errors: {errs[:3]}")
            await ctx.close()
            await b.close()
            frames_all = r.frames + r2.frames
    finally:
        srv.terminate()
        srv.wait(10)
    total = sum(d for _, d in frames_all)
    scale = args.seconds / total
    lst = tmp / "list.txt"
    with open(lst, "w") as f:
        for path, d in frames_all:
            f.write(f"file '{path}'\nduration {d * scale:.4f}\n")
        f.write(f"file '{frames_all[-1][0]}'\n")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=0x08080b,fps=25,format=yuv420p",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "24", "-movflags", "+faststart", str(out)], check=True)
    log.append(f"{len(frames_all)} frames ({total:.1f} s nominal) -> {args.seconds} s: {out} ({out.stat().st_size // 1024} KB)")
    print("\n".join(log))
    (tmp / "log.txt").write_text("\n".join(log))
    if not args.keep:
        shutil.rmtree(frames, ignore_errors=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "qa" / "interactive" / "demo.mp4"))
    ap.add_argument("--seconds", type=float, default=45.0)
    ap.add_argument("--start", default="21:00", help="Tokyo time the demo clock starts at (awake, at home: the park "
                    "closes at 20:00; the clock runs at x1.001, as --start needs a scale other than 1)")
    ap.add_argument("--round", type=float, default=150.0, help="vote round length, seconds (the demo's; default 1 h live)")
    ap.add_argument("--chromium", default="/opt/pw-browsers/chromium")
    ap.add_argument("--keep", action="store_true", help="keep the frames")
    asyncio.run(main(ap.parse_args()))
