"""Frame-stepped preview renderer of the room page: one side (old or new), one size, one or more segments, on whatever
WebGL the browser has (the real GPU on a RunPod pod through tools/gpu_preview.py, SwiftShader in a sandbox for a check).

    python tools/gpu_preview_render.py --web <checkout>/web --side new --size 1280x800 --fps 30 --segments 14:60,23:30 \
        --frames /tmp/pf [--gpu-args "--use-angle=vulkan,..."] [--require-gpu]
    python tools/gpu_preview_render.py --probe --gpu-args "..."            # print the WebGL renderer string and exit
    python tools/gpu_preview_render.py --encode --frames /tmp/pf --out preview.mp4 [--max-mb 25]

Each frame is one step of the page's own clock (1/fps s: his animation, the window view, the lights, the camera's cuts
and dollies as the page's loop does them), then one render; the canvas's pixels are read back as JPEG. The page runs
with ?debug&nolive&hour=H (its loop frozen, driven from here) and the scene is set with the debug act(): the window
sill at 14:00, the phone in bed at 23:00 (the page's own choices for those hours). The new side adds ?post=high when
the page has the post-processing tiers (#103). --encode stacks old | new (labelled) with /usr/bin/ffmpeg, H.264 at
the given fps, raising the CRF until the file is under --max-mb. The CDN scripts (three.js, leaflet) are fetched by the
browser; room_build/node_modules is used instead when the CDNs are unreachable (a sandbox).
"""
import argparse
import base64
import http.server
import json
import os
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NM = Path(os.environ.get("SUB01_NODE_MODULES", ROOT / "room_build" / "node_modules"))   # three.js and leaflet for --local-cdn
SCENE = {14: "act('window', {activity:'window', place:'room'})", 23: "act('phone', {activity:'phone', place:'bed', phone:'shorts'})",
         8: "act('idle_home', {activity:'idle_home', place:'door_in'})", 19: "act('eat', {activity:'eat', place:'table', eating:'ramen', food:1})"}
# one frame of the page's loop, as tests/room_preview_video.py (#103) steps it: his step, the window, the camera goal
# (a cut or a dolly), then the lights + shadows + render (sim(0, 1)) every `full` frame, a plain render otherwise
STEP_JS = """([dt, hour, full]) => {
  animate_(dt); if (window.windowView && windowView.update) windowView.update(dt, hour);
  if (typeof updateCameraGoal === 'function') updateCameraGoal();
  if (window.CAM && CAM.cut) { camera.position.copy(camGoal.pos); controls.target.copy(camGoal.target); CAM.cut = false; }
  else if (typeof camGoal !== 'undefined') { const k = 1 - Math.exp(-dt * 1.2); camera.position.lerp(camGoal.pos, k); controls.target.lerp(camGoal.target, k); }
  if (full) { scene.traverse(o => { if (o.isLight && o.shadow) o.shadow.needsUpdate = true; }); if (typeof lighting === 'function') lighting(dt); }
  controls.update(); if (window.post && post.render) post.render(dt); else renderer.render(scene, camera);
  return renderer.domElement.toDataURL('image/jpeg', 0.92); }"""
RENDERER_JS = """() => { const c = document.createElement('canvas'); const gl = c.getContext('webgl2') || c.getContext('webgl');
  if (!gl) return 'no webgl'; const d = gl.getExtension('WEBGL_debug_renderer_info');
  return d ? gl.getParameter(d.UNMASKED_RENDERER_WEBGL) + ' | ' + gl.getParameter(d.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.RENDERER); }"""
HUD_OFF = "#top,#side,#corner,#dock,#vignette,#away,#boot{display:none!important}"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"


def serve(web, port):
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(web), **k)

        def log_message(self, *a):
            pass
    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def launch(p, gpu_args, chromium):
    """Chromium with the given flags; a 'channel=chromium' entry picks Playwright's full Chromium build (new headless)
    instead of the headless shell, which may have no GPU path."""
    flags = [a for a in gpu_args.split(",") if a]
    args = ["--ignore-gpu-blocklist", "--enable-gpu-rasterization", "--enable-zero-copy", "--disable-gpu-vsync"] + [a for a in flags if not a.startswith("channel=")]
    kw = {"args": args, "headless": True}
    ch = [a.split("=", 1)[1] for a in flags if a.startswith("channel=")]
    if ch:
        kw["channel"] = ch[0]
    elif chromium:
        kw["executable_path"] = chromium
    return p.chromium.launch(**kw)


def route_cdn(pg, local_only):
    def cdn(route, request):
        url = request.url
        path = None
        if "three@0.169.0/" in url:
            path = NM / "three" / url.split("three@0.169.0/", 1)[1]
        elif "leaflet@1.9.4/dist/" in url:
            path = NM / "leaflet" / "dist" / url.split("dist/", 1)[1]
        if path and path.exists():
            return route.fulfill(path=str(path), content_type="text/javascript" if path.suffix == ".js" else "text/css")
        return route.abort() if local_only else route.continue_()
    pg.route("**/cdn.jsdelivr.net/**", cdn)
    pg.route("**/unpkg.com/**", cdn)
    pg.route("**/api/**", lambda r: r.fulfill(status=404, body=""))
    pg.route("**/tokyo_*.json", lambda r: r.fulfill(status=404, body=""))


def probe(a):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = launch(p, a.gpu_args, a.chromium)
        pg = b.new_page()
        pg.set_content("<html><body></body></html>")
        r = pg.evaluate(RENDERER_JS)
        b.close()
    print(r)
    return r


CAM_JS = "([p, t, fov]) => { if (fov) { camera.fov = fov; camera.updateProjectionMatrix(); } camera.position.set(...p); controls.target.set(...t); controls.update(); }"
STEP_ONLY_JS = "([dt, hour]) => { animate_(dt); if (window.windowView && windowView.update) windowView.update(dt, hour); }"
# one frame: lights and shadows refreshed every `full` frame, then rendered twice and the second kept: on the GPU a
# material seen for the first time (a sheen fabric, a poster) could come out black or missing for one frame while its
# program links or its texture uploads (#138: the mattress gone at 8 s, the cushion black at 4 s)
RENDER_ONLY_JS = """([dt, full]) => { if (full) { scene.traverse(o => { if (o.isLight && o.shadow) o.shadow.needsUpdate = true; }); if (typeof lighting === 'function') lighting(dt); }
  controls.update(); const draw = d => { if (window.post && post.render) post.render(d); else renderer.render(scene, camera); };
  draw(dt); draw(0); renderer.getContext().finish(); return renderer.domElement.toDataURL('image/jpeg', 0.92); }"""
# before a shot: every program compiled for this camera and every texture in the scene uploaded
WARM_JS = """() => { let n = 0; try { renderer.compile(scene, camera); } catch (e) { console.warn('compile', e); }
  const seen = new Set(); scene.traverse(o => { const ms = o.material ? (Array.isArray(o.material) ? o.material : [o.material]) : [];
    for (const m of ms) for (const k in m) { const t = m[k]; if (t && t.isTexture && !seen.has(t)) { seen.add(t); try { renderer.initTexture(t); n++; } catch (e) {} } } });
  return n; }"""


def screen_stub_jpeg(w=1280, h=800):
    """A neutral desk-monitor picture for the preview page's stubbed screens feed: a plain dark code editor drawn here
    (bars for lines of code, a side bar, a tab strip), no text, no brand, no real site."""
    import io
    from PIL import Image, ImageDraw
    import random
    rnd = random.Random(7)
    im = Image.new("RGB", (w, h), (30, 32, 38))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, w, 34), fill=(22, 24, 29))
    for i, x in enumerate(range(12, 520, 170)):
        d.rounded_rectangle((x, 6, x + 150, 34), 6, fill=(30, 32, 38) if i == 0 else (26, 28, 33))
        d.rectangle((x + 16, 16, x + 16 + 70 + 30 * (i % 2), 22), fill=(120, 126, 140))
    d.rectangle((0, 34, 210, h), fill=(25, 27, 32))
    for y in range(56, h - 30, 26):
        ind = rnd.choice((0, 0, 14, 28))
        d.rectangle((20 + ind, y, 20 + ind + rnd.randint(60, 140), y + 7), fill=(92, 98, 112))
    cols = [(198, 120, 221), (97, 175, 239), (152, 195, 121), (229, 192, 123), (171, 178, 191), (224, 108, 117)]
    y, indent = 52, 0
    while y < h - 40:
        d.rectangle((222, y, 252, y + 9), fill=(70, 75, 88))           # the line number
        if rnd.random() < 0.12:
            y += 22; continue
        indent = max(0, min(4, indent + rnd.choice((-1, 0, 0, 0, 1))))
        x = 276 + indent * 34
        for _ in range(rnd.randint(1, 5)):
            ln = rnd.randint(24, 120)
            if x + ln > w - 40:
                break
            d.rectangle((x, y, x + ln, y + 9), fill=rnd.choice(cols))
            x += ln + 12
        y += 22
    d.rectangle((0, h - 22, w, h), fill=(40, 90, 160))
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


SCREEN_STATUS = {"device": "desk", "id": "preview-stub"}     # (the life state's `screen`: the page then loads /api/screen/desk.jpg)


def textures_ready(pg):
    """On a GPU the page is ready seconds before the window's photographs (room/window/*.webp) have arrived, and the frozen
    page never recomposes them later: wait for those responses, then a few warm-up renders upload every texture."""
    try:
        pg.wait_for_function("performance.getEntriesByType('resource').filter(e => /room\\/window\\/[^/]+\\.webp/.test(e.name) && e.responseEnd > 0).length >= 6", timeout=120000)
    except Exception as e:                            # (a page without the window view: carry on)
        print("window textures: not all seen,", str(e)[:80], flush=True)
    pg.wait_for_timeout(1500)
    # the page's adapt() may have lowered its pixel ratio during the load (slow frames while textures decode), leaving a
    # smaller canvas: back to the full viewport at ratio 1 (the frozen page's adapt() never runs again)
    pg.evaluate("() => { try { renderer.setPixelRatio(1); renderer.setSize(window.innerWidth, window.innerHeight, false); camera.aspect = window.innerWidth / window.innerHeight; camera.updateProjectionMatrix(); } catch (e) { console.warn('resize', e); } }")
    for _ in range(3):
        pg.evaluate(RENDER_ONLY_JS, [1 / 30, True])


def shots_file(path):
    """A shot list: {"hour": 14, "scene": "<js>" | {"life": {...}}, "query_old": "", "query_new": "", "shots": [
    {"label", "seconds", "cam": {"pos", "target", "to"?: dolly end, "fov"?} | "closeup": "<page_checks recipe>" | "follow"}]}"""
    return json.loads(Path(path).read_text())


def render(a):
    from playwright.sync_api import sync_playwright
    w, h = [int(x) for x in a.size.split("x")]
    web = Path(a.web).resolve()
    frames = Path(a.frames); frames.mkdir(parents=True, exist_ok=True)
    srv = serve(web, a.port)
    meta = {"side": a.side, "size": a.size, "fps": a.fps, "segments": [], "renderer": None, "seconds_render": None}
    t0 = time.time()
    try:
        with sync_playwright() as p:
            b = launch(p, a.gpu_args, a.chromium)
            mobile = w < 600
            pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=1, is_mobile=mobile, has_touch=mobile)
            route_cdn(pg, a.local_cdn)
            pg.on("pageerror", lambda e: print("pageerror", str(e)[:160], flush=True))
            k = 0
            if a.shots:
                sh = shots_file(a.shots); hour = None
                query = sh.get("query_" + a.side, "") or a.query
                if sh.get("screen_stub"):                    # a lit desk monitor: the screens feed answered with a neutral picture
                    stub = screen_stub_jpeg()
                    pg.route("**/api/screen/desk.jpg*", lambda r: r.fulfill(status=200, body=stub, content_type="image/jpeg"))

                def load(h, sc, settle_s=1.0):
                    """The page at hour h (reloaded when it changes), the scene sc applied (a life state or JS), settle_s seconds run."""
                    nonlocal hour
                    if h != hour:
                        pg.goto(f"http://127.0.0.1:{a.port}/room.html?debug&nolive&hour={h}" + (f"&{query}" if query else ""), wait_until="load")
                        pg.wait_for_function("window.boy && window.room && window.actions && ['walk','idle','door','eat','sleep','stand'].every(k => window.actions[k]) && (!window.motion || window.motion.ready)", timeout=600000)
                        if meta["renderer"] is None:
                            meta["renderer"] = pg.evaluate(RENDERER_JS)
                            print("WebGL:", meta["renderer"], flush=True)
                            if a.require_gpu and "NVIDIA" not in meta["renderer"]:
                                raise SystemExit(f"not on the GPU: {meta['renderer']}")
                        pg.add_style_tag(content=HUD_OFF)
                        pg.add_script_tag(content=(ROOT / "tests" / "visual" / "page_checks.js").read_text())
                        pg.evaluate("s => { window.FREEZE = true; settle(); if (window.setSeed) setSeed(s); __qa.hideMarkers(); }", a.seed)
                        # (preview/room-mh: the MakeHuman rig loads its clips, its props and G11's hair after the page; wait for them)
                        if pg.evaluate("() => !!window.boy.getObjectByName('metacarpal1L')"):
                            pg.wait_for_function("() => window.mh && window.mh.ready", timeout=600000)
                            pg.evaluate("() => animate_(1/30)")      # (his first step asks for the hair)
                            pg.wait_for_function("() => !!window.boy.getObjectByName('hair_mh')", timeout=600000)
                        textures_ready(pg)
                        hour = h
                    if isinstance(sc, dict):
                        life = dict(sc["life"])
                        if sh.get("screen_stub"):
                            life["screen"] = SCREEN_STATUS
                        pg.evaluate("(l) => { act(l.activity, l); }", life)
                        if sh.get("screen_stub"):            # the picture arrives asynchronously; then act() again switches the monitor on
                            try:
                                pg.wait_for_function("() => window.monitor && monitor.id === 'preview-stub' && !!monitor.tex", timeout=30000)
                                pg.evaluate("(l) => { act(l.activity, l); }", life)
                            except Exception as e:
                                print("screen stub: not shown,", str(e)[:80], flush=True)
                    elif sc:
                        pg.evaluate(sc)
                    pg.evaluate("(n) => { for (let i = 0; i < n; i++) animate_(1/30); }", int(round(settle_s * 30)))
                    print("  window view:", pg.evaluate("() => window.windowView && windowView.state ? JSON.stringify(windowView.state()) : 'n/a'")[:200], flush=True)
                meta["clean"] = bool(sh.get("clean"))           # (the owner's format: the shot's own label, no hour, timer or renderer)
                load(int(sh.get("hour", 14)), sh.get("scene", ""))
                for shot in sh["shots"]:
                    if "hour" in shot or "scene" in shot:                   # a shot with its own hour and/or scene (life state or JS), settled for shot.settle seconds
                        load(int(shot.get("hour", hour)), shot.get("scene", ""), float(shot.get("settle", 1.0)))
                    n = int(round(float(shot["seconds"]) * a.fps)); seg0 = k
                    cam = shot.get("cam")
                    if cam:                                    # every program and texture ready from this shot's camera before the first frame
                        pg.evaluate(CAM_JS, [cam["pos"], cam["target"], cam.get("fov")])
                    print(f"  warm-up: {pg.evaluate(WARM_JS)} textures", flush=True)
                    for _ in range(2):
                        pg.evaluate(RENDER_ONLY_JS, [0, True])
                    for f in range(n):
                        pg.evaluate(STEP_ONLY_JS, [1 / a.fps, hour])
                        if shot.get("closeup"):
                            pg.evaluate("n => __qa.closeup(n)", shot["closeup"])
                        elif cam:
                            u = f / max(1, n - 1)
                            pos = [cam["pos"][i] + (cam["to"][i] - cam["pos"][i]) * u for i in range(3)] if cam.get("to") else cam["pos"]
                            pg.evaluate(CAM_JS, [pos, cam["target"], cam.get("fov")])
                        else:
                            pg.evaluate("() => { if (typeof updateCameraGoal === 'function') { updateCameraGoal(); camera.position.copy(camGoal.pos); controls.target.copy(camGoal.target); } }")
                        data = pg.evaluate(RENDER_ONLY_JS, [1 / a.fps, f % a.shadow_every == 0])
                        (frames / f"{a.side}_{k:05d}.jpg").write_bytes(base64.b64decode(data.split(",", 1)[1]))
                        k += 1
                        if f % (a.fps * 5) == 0:
                            print(f"  {a.side} {a.size} {shot.get('label', '')} frame {f}/{n} ({time.time() - t0:.0f} s)", flush=True)
                    meta["segments"].append({"hour": hour, "label": shot.get("label", ""), "seconds": float(shot["seconds"]), "first": seg0, "frames": n})
                b.close()
                raise StopIteration
            for seg in a.segments.split(","):
                hour, secs = seg.split(":"); hour = int(hour); secs = float(secs)
                q = f"?debug&nolive&hour={hour}" + ("&post=high" if a.side == "new" else "") + (f"&{a.query}" if a.query else "")
                pg.goto(f"http://127.0.0.1:{a.port}/room.html{q}", wait_until="load")
                pg.wait_for_function("window.boy && window.room && window.actions && ['walk','idle','door','eat','sleep','stand'].every(k => window.actions[k]) && (!window.motion || window.motion.ready)", timeout=600000)   # (software WebGL loads the high tier in minutes)
                if meta["renderer"] is None:
                    meta["renderer"] = pg.evaluate(RENDERER_JS)
                    print("WebGL:", meta["renderer"], flush=True)
                    if a.require_gpu and "SwiftShader" in meta["renderer"] or a.require_gpu and "NVIDIA" not in meta["renderer"]:
                        raise SystemExit(f"not on the GPU: {meta['renderer']}")
                pg.add_style_tag(content=HUD_OFF)
                pg.add_script_tag(content=(ROOT / "tests" / "visual" / "page_checks.js").read_text())
                pg.evaluate("s => { window.FREEZE = true; settle(); if (window.setSeed) setSeed(s); __qa.hideMarkers(); }", a.seed)   # (?debug's magenta markers off)
                textures_ready(pg)
                pg.evaluate(SCENE.get(hour, SCENE[14]))
                pg.evaluate("() => { for (let i = 0; i < 30; i++) animate_(1/30); if (typeof updateCameraGoal === 'function') { updateCameraGoal(); camera.position.copy(camGoal.pos); controls.target.copy(camGoal.target); controls.update(); } }")
                print(f"  warm-up: {pg.evaluate(WARM_JS)} textures", flush=True)
                for _ in range(2):
                    pg.evaluate(RENDER_ONLY_JS, [0, True])
                n = int(round(secs * a.fps)); seg0 = k
                for f in range(n):
                    data = pg.evaluate(STEP_JS, [1 / a.fps, hour, f % a.shadow_every == 0])
                    (frames / f"{a.side}_{k:05d}.jpg").write_bytes(base64.b64decode(data.split(",", 1)[1]))
                    k += 1
                    if f % (a.fps * 5) == 0:
                        print(f"  {a.side} {a.size} {hour}:00 frame {f}/{n} ({time.time() - t0:.0f} s)", flush=True)
                meta["segments"].append({"hour": hour, "seconds": secs, "first": seg0, "frames": n})
            b.close()
    except StopIteration:
        pass
    finally:
        srv.shutdown()
    meta["seconds_render"] = round(time.time() - t0, 1)
    (frames / f"{a.side}_meta.json").write_text(json.dumps(meta, indent=1))
    print(f"{a.side}: {k} frames in {meta['seconds_render']} s on {meta['renderer']}", flush=True)


def dropouts(frames, side, segments, grid=8, jump=0.30, spread=0.10, floor=18.0, reach=3, min_cells=2):
    """Short dropouts (a material black or missing for a frame or two): each frame is cut into grid x grid cells and a
    cell is compared with the median of the same cell in the `reach` frames on either side (within the segment). A
    cell more than `jump` away from that median, while the neighbours' middle half stays within `spread` of it (a still
    region, not motion) and the median is brighter than `floor`, is a hit; `min_cells` hits flag the frame.
    Returns {frame index: [cells]}."""
    from PIL import Image
    from statistics import median
    lum = {}

    def cells(k):
        if k not in lum:
            im = Image.open(frames / f"{side}_{k:05d}.jpg").convert("L").resize((grid, grid), Image.BOX)
            lum[k] = list(im.getdata())
        return lum[k]
    bad = {}
    for sg in segments:
        a, z = sg["first"], sg["first"] + sg["frames"]
        for k in range(a, z):
            nb = [j for j in range(k - reach, k + reach + 1) if j != k and a <= j < z]
            if len(nb) < reach:
                continue
            c, ns = cells(k), [cells(j) for j in nb]
            hit = []
            for i in range(grid * grid):
                v = sorted(n[i] for n in ns); m = median(v)
                q1, q3 = v[len(v) // 4], v[(3 * len(v)) // 4]
                if m > floor and (q3 - q1) <= spread * m and abs(c[i] - m) > jump * m:
                    hit.append(i)
            if len(hit) >= min_cells:
                bad[k] = hit
    return bad


def encode(a):
    """old | new side by side with labels (PIL), then ffmpeg H.264; the CRF rises until the file fits. Single-frame
    dropouts (dropouts()) are logged and the frame replaced by the one before it; the list goes into the JSON."""
    from PIL import Image, ImageDraw, ImageFont
    import shutil as _sh
    frames = Path(a.frames)
    metas = {s: json.loads((frames / f"{s}_meta.json").read_text()) for s in ("old", "new") if (frames / f"{s}_meta.json").exists()}
    sides = list(metas)
    n = min(sum(sg["frames"] for sg in metas[s]["segments"]) for s in sides)
    repaired = {}
    for s in sides:
        bad = dropouts(frames, s, metas[s]["segments"])
        for k in sorted(bad):
            seg = next(sg for sg in metas[s]["segments"] if sg["first"] <= k < sg["first"] + sg["frames"])
            near = sorted((j for j in range(seg["first"], seg["first"] + seg["frames"]) if j not in bad), key=lambda j: (abs(j - k), j))
            if not near:
                continue
            print(f"dropout: {s} frame {k} ({k / metas[s]['fps']:.2f} s), {len(bad[k])} cells: replaced by frame {near[0]}", flush=True)
            _sh.copy(frames / f"{s}_{near[0]:05d}.jpg", frames / f"{s}_{k:05d}.jpg")
        repaired[s] = [{"frame": k, "t": round(k / metas[s]["fps"], 2), "cells": bad[k]} for k in sorted(bad)]
    comp = frames / "composed"; comp.mkdir(exist_ok=True)
    font = ImageFont.truetype(FONT, 20) if Path(FONT).exists() else ImageFont.load_default()
    first = Image.open(frames / f"{sides[0]}_00000.jpg")
    w, h = first.size
    labels = {"old": a.label_old, "new": a.label_new}
    narrow = w * len(sides) < 1100                      # (the phone pair: the caption goes on a second line under the side labels)
    clean = bool(metas[sides[0]].get("clean"))
    bar = 64 if clean else 52 if narrow else 28           # (clean: the side labels, then the shot's own label on a line of its own)
    for k in range(n):
        S = Image.new("RGB", (w * len(sides), h + bar), (8, 8, 10))
        d = ImageDraw.Draw(S)
        for i, s in enumerate(sides):
            im = Image.open(frames / f"{s}_{k:05d}.jpg")
            if im.size != (w, h):                      # (a side whose canvas came out smaller: scaled to the pane)
                im = im.resize((w, h), Image.LANCZOS)
            S.paste(im, (i * w, bar))
            d.text((i * w + 8, 5), labels[s], font=font, fill=(255, 220, 120) if s == "new" else (210, 210, 220))
        seg = next((sg for sg in metas[sides[0]]["segments"] if sg["first"] <= k < sg["first"] + sg["frames"]), None)
        if seg and clean:
            d.text((w * len(sides) // 2 - d.textlength(seg.get("label", ""), font=font) // 2, 34), seg.get("label", ""), font=font, fill=(240, 240, 240))
        elif seg:
            cap = f"{seg.get('label', '')} {seg['hour']:02d}:00  {(k - seg['first']) / metas[sides[0]]['fps']:5.1f} s  {metas[sides[0]]['renderer'].split('|')[0].strip()[:28]}"
            d.text((8, 29) if narrow else (w * len(sides) - 420, 5), cap, font=font, fill=(200, 200, 210))
        S.save(comp / f"c_{k:05d}.jpg", quality=92)
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    fps = metas[sides[0]]["fps"]
    for crf in (20, 23, 26, 29, 32, 36):
        subprocess.run([a.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-framerate", str(fps), "-i", str(comp / "c_%05d.jpg"),
                        "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",            # (libx264 needs even sizes; the phone canvas is 390 x 523)
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", str(crf), "-preset", "medium", "-movflags", "+faststart", str(out)], check=True)
        if out.stat().st_size <= a.max_mb * 1e6:
            break
    info = {"frames": n, "fps": fps, "seconds": n / fps, "bytes": out.stat().st_size, "crf": crf, "sides": {s: metas[s] for s in sides},
            "dropouts_replaced": repaired}
    out.with_suffix(".json").write_text(json.dumps(info, indent=1))
    print(f"wrote {out}: {n} frames, {n / fps:.1f} s, {out.stat().st_size / 1e6:.1f} MB (crf {crf})", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--web"); ap.add_argument("--side", choices=["old", "new"], default="new")
    ap.add_argument("--size", default="1280x800"); ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--segments", default="14:60,23:30", help="hour:seconds, comma-separated")
    ap.add_argument("--frames", default="/tmp/preview_frames"); ap.add_argument("--port", type=int, default=8870)
    ap.add_argument("--seed", type=int, default=63); ap.add_argument("--shadow-every", type=int, default=1, help="full lighting + shadow update every n frames (1 on a GPU)")
    ap.add_argument("--gpu-args", default="", help="extra Chromium flags, comma-separated")
    ap.add_argument("--chromium", default=os.environ.get("SUB01_CHROMIUM", ""))
    ap.add_argument("--require-gpu", action="store_true"); ap.add_argument("--local-cdn", action="store_true", help="three.js and leaflet from room_build/node_modules only")
    ap.add_argument("--probe", action="store_true"); ap.add_argument("--encode", action="store_true")
    ap.add_argument("--out", default="preview.mp4"); ap.add_argument("--max-mb", type=float, default=25)
    ap.add_argument("--label-old", default="main (old)"); ap.add_argument("--label-new", default="this PR (new)")
    ap.add_argument("--ffmpeg", default="/usr/bin/ffmpeg")
    ap.add_argument("--query", default="", help="extra URL query for this side (e.g. props=old)")
    ap.add_argument("--shots", default="", help="a shot list JSON (custom cameras) instead of --segments")
    a = ap.parse_args()
    if a.probe:
        return probe(a)
    if a.encode:
        return encode(a)
    if not a.web:
        ap.error("--web is required to render")
    return render(a)


if __name__ == "__main__":
    main()
