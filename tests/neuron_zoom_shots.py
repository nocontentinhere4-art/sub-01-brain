"""Frames of the zoom (#99): the whole brain -> a cortical column at true size -> the tissue block. Run by hand:

    python tests/neuron_zoom_shots.py --out docs/screens/neuron_zoom [--cdn-dir DIR]

Starts `live_server.py --demo` (no live network on the server), replays a RECORDED stream of the 20k CPU network into
the page's socket handler (tests/neurons3d_shots.py: test only), switches the neurons on, starts the dive and holds it
at points along its path (zoom.anim.at), at 1920 x 1080 and 390 x 844. For each frame: the page as seen (JPEG), the
camera distance, the stage, the scale bar's text, and the luminance of the image with text and panels hidden (% of
pixels above 0.8 among those above 0.03; the gate is <= 2 %). Writes a contact sheet and an animated GIF per width,
results.json, and the frame time (JS ms per frame, FPS) at column scale under x4 CPU throttle, which is software
WebGL here (SwiftShader), not a phone's GPU.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from neuron_forest_look import HIDE, luminance  # noqa: E402
from neurons3d_shots import INJECT, record, wait_ready  # noqa: E402

STEPS = [0.0, 0.3, 0.45, 0.55, 0.62, 0.7, 0.8, 0.9, 1.0]
STEP_JS = """u => { if (!zoom) return; zoom.anim = zoom.anim || {t0: performance.now(), dur: 11000}; zoom.anim.at = u; for (let k = 0; k < 40; k++) { const t = performance.now(); if (zoom) zoomFrame(t); n3d.update(t); }
  zoomOverlay(); neuronsText(); controls.update(); renderer.render(scene, camera); }"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8801)
    ap.add_argument("--out", default="docs/screens/neuron_zoom")
    ap.add_argument("--chromium", default=os.environ.get("SUB01_CHROMIUM", "/opt/pw-browsers/chromium"))
    ap.add_argument("--cdn-dir", default=None)
    args = ap.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    frames = record(seconds=10.0)
    tmp = tempfile.mkdtemp(prefix="n3zoom-")
    env = dict(os.environ, BROWSE="0", SUB01_SPIKING_LIVE="0", SUB01_WS_STATS_S="3600")
    proc = subprocess.Popen([sys.executable, str(ROOT / "live_server.py"), "--demo", "--port", str(args.port), "--host",
                             "127.0.0.1", "--data-dir", tmp], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{args.port}"
    res = {"steps": STEPS, "frames": {}}
    try:
        wait_ready(base, proc)
        from playwright.sync_api import sync_playwright
        from PIL import Image
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=args.chromium, args=["--use-gl=angle", "--use-angle=swiftshader",
                                                                             "--enable-unsafe-swiftshader"])
            for w, h in ((1920, 1080), (390, 844)):
                ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1, is_mobile=w < 600, has_touch=w < 600)
                pg = ctx.new_page()
                pg.add_init_script(INJECT)
                errors = []
                pg.on("pageerror", lambda e: errors.append(str(e)))
                if args.cdn_dir:
                    cdn = Path(args.cdn_dir)
                    pg.route("**/three.min.js", lambda r: r.fulfill(path=str(cdn / "three.min.js"), content_type="text/javascript"))
                    pg.route("**/OrbitControls.js", lambda r: r.fulfill(path=str(cdn / "OrbitControls.js"), content_type="text/javascript"))
                pg.goto(base + "/brain", wait_until="load")
                pg.wait_for_function("window.__brainWs && window.__brainWs.readyState === 1", timeout=60000)
                pg.wait_for_timeout(2000)
                pg.evaluate("controls.autoRotate = false")
                pg.evaluate("f => window.__replay(f)", frames)
                pg.evaluate("document.querySelector('#layers button[data-l=\"neurons\"]').click()")
                pg.wait_for_function("typeof n3d !== 'undefined' && n3d && n3morph", timeout=120000)
                pg.evaluate("zoomStart(true)")
                pg.wait_for_function("zoom && zoom.anim", timeout=60000)
                pg.evaluate("zoom.anim.at = 0")
                pg.wait_for_function("document.querySelector('#n3cap').innerText.includes('live')", timeout=120000)
                shots = []
                for u in STEPS:
                    pg.evaluate(STEP_JS, u)
                    pg.wait_for_timeout(2500 if u < 1 else 6000)
                    st = pg.evaluate("""() => ({d: camera.position.distanceTo(controls.target), brain: zoomBrain,
                      stage: n3close ? 'tissue (NeuronRender)' : zoom && zoomBrain < 0.5 ? 'column' : 'brain',
                      scale: document.querySelector('#n3scale span').textContent, caption: document.querySelector('#n3cap').innerText.slice(0, 400)})""")
                    name = f"zoom_{w}_{int(round(u * 100)):03d}"
                    pg.screenshot(path=str(out / f"{name}.jpg"), type="jpeg", quality=85, timeout=180000)
                    pg.add_style_tag(content=HIDE)
                    pg.wait_for_timeout(400)
                    raw = Path(tmp) / f"{name}.png"
                    pg.screenshot(path=str(raw), timeout=180000)
                    st["luminance"] = luminance(raw)
                    pg.evaluate("document.querySelectorAll('style').forEach(s => { if (s.textContent.includes('visibility: hidden !important')) s.remove(); })")
                    res["frames"][name] = st
                    shots.append(out / f"{name}.jpg")
                    print(name, json.dumps({k: v for k, v in st.items() if k != "caption"}), flush=True)
                # contact sheet and GIF of the frames
                ims = [Image.open(s).convert("RGB") for s in shots]
                tw = 480 if w > 600 else 195
                th = int(ims[0].height * tw / ims[0].width)
                thumbs = [im.resize((tw, th)) for im in ims]
                sheet = Image.new("RGB", (tw * len(thumbs), th), (3, 3, 5))
                for i, t in enumerate(thumbs):
                    sheet.paste(t, (i * tw, 0))
                sheet.save(out / f"zoom_{w}_sheet.jpg", quality=85)
                gw = 640 if w > 600 else 300
                gif = [im.resize((gw, int(im.height * gw / im.width))).quantize(colors=96, method=Image.Quantize.MEDIANCUT) for im in ims]
                gif[0].save(out / f"zoom_{w}.gif", save_all=True, append_images=gif[1:], duration=900, loop=0, optimize=True)
                if w == 390:                                 # frame time at column scale, CPU x4 (software WebGL here)
                    pg.evaluate("document.querySelector('#n3close button[data-k=\"\"]').click()")
                    pg.wait_for_timeout(1500)
                    pg.evaluate("if (zoom) zoomEnd(); zoomStart(true)")
                    pg.wait_for_function("zoom && zoom.anim", timeout=60000)
                    pg.evaluate(STEP_JS, 0.7)
                    cdp = ctx.new_cdp_session(pg)
                    cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
                    pg.evaluate("window.__frameMs(3000)")                 # the first window warms up; the second counts
                    m = pg.evaluate("window.__frameMs(6000)")
                    cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
                    res["column_390_x4"] = {"fps": round(m["frames"] / 6, 1), "js_ms_per_frame": m["js_ms_per_frame"],
                                            "info": pg.evaluate("zoom && zoom.col.info()")}
                res[f"errors_{w}"] = errors
                ctx.close()
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=20)
    (out / "results.json").write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in res.items() if k != "frames"}, indent=1))


if __name__ == "__main__":
    main()
