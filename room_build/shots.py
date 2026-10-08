"""Fixed-camera screenshots of the room (#98 G5): overview and close-ups of the hard surfaces, at 1280 and 390 px, day
and night. Run by hand from the repository root (no `test_` prefix: pytest does not collect it):

    python room_build/shots.py --out docs/design/room-hard/after            # the GLB in web/room/
    python room_build/shots.py --out docs/design/room-hard/before --glb /tmp/room_before.glb --tag before

Starts `live_server.py --demo` (BROWSE=0) and opens `/?debug&nolive&hour=<h>` in headless Chromium; `--glb` serves that
file in place of web/room/room_clean.glb (the page is not changed). The camera is set through the page's debug globals
(`camera`, `controls`, `settle`, `sim`), so the same views come out of every build. Headless Chromium draws WebGL in
software (SwiftShader): a few seconds a frame, so only `--shots` (default: all) are drawn.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# name: [camera position, target]; glTF/three.js world units (floor at y 0.16)
VIEWS = {
    "overview": [[5.2, 5.0, 6.0], [0, 0.6, 0]],
    "desk": [[-0.35, 1.55, 0.25], [-1.15, 1.08, -1.05]],
    "keyboard": [[-0.72, 1.32, -0.45], [-1.05, 0.99, -0.98]],
    "chair": [[0.35, 1.25, 0.65], [-1.05, 0.55, -0.55]],
    "shelf": [[1.05, 1.45, -0.05], [0.10, 1.15, -1.30]],
    "bed": [[0.95, 1.45, 1.55], [-1.05, 0.55, 0.85]],
    "fridge_door": [[-0.25, 1.65, 0.35], [0.95, 1.05, -1.40]],
    "window": [[-0.35, 1.70, 1.05], [-1.90, 1.65, 0.15]],
    "floor": [[0.65, 1.15, 1.10], [-0.25, 0.16, -0.10]],
    "fan_ac": [[0.15, 1.75, 1.30], [1.25, 1.20, -0.80]],
    "headphones": [[0.35, 1.45, -0.45], [-0.24, 1.38, -1.42]],
    "keycaps": [[-0.98, 1.22, -0.72], [-1.09, 0.99, -0.99]],
    "door": [[1.05, 1.35, -0.55], [1.62, 1.05, -1.42]],
}
WITH_HIM = {"overview"}                                  # he sits at the desk in the overview; the close-ups show the room alone
SIZES = {"1280": (1280, 800), "390": (390, 844)}
HOURS = {"day": 13.0, "night": 21.5}


def wait_http(url, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen(url, timeout=3).read()
            return True
        except Exception:
            time.sleep(0.5)
    return False


def cdn_route(r, cdn):
    """the page's CDN scripts from a local node_modules (three@0.169.0, leaflet@1.9.4); anything else off the network"""
    u = r.request.url
    for pre, sub in (("https://cdn.jsdelivr.net/npm/three@0.169.0/", "three/"), ("https://unpkg.com/leaflet@1.9.4/", "leaflet/")):
        if u.startswith(pre):
            f = cdn / sub / u[len(pre):].split("?")[0]
            if f.exists():
                ct = "text/javascript" if f.suffix in (".js", ".mjs") else "text/css" if f.suffix == ".css" else "application/octet-stream"
                return r.fulfill(path=str(f), content_type=ct)
    return r.abort()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--glb", default=None, help="serve this GLB in place of web/room/room_clean.glb")
    ap.add_argument("--tag", default="")
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--shots", default="all", help="comma-separated view names (default all)")
    ap.add_argument("--sizes", default="1280,390")
    ap.add_argument("--hours", default="day,night")
    ap.add_argument("--chromium", default=os.environ.get("CHROMIUM", "/opt/pw-browsers/chromium"))
    ap.add_argument("--quality", type=int, default=88)
    ap.add_argument("--cdn-dir", default=os.environ.get("CDN_DIR"), help="a node_modules with three@0.169.0 and leaflet@1.9.4: served in place of the CDNs (no network)")
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    views = list(VIEWS) if args.shots == "all" else args.shots.split(",")
    data = tempfile.mkdtemp(prefix="room_shots_")
    env = dict(os.environ, BROWSE="0", SUB01_SPIKING_LIVE="0", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
    srv = subprocess.Popen([sys.executable, str(ROOT / "live_server.py"), "--demo", "--port", str(args.port), "--data-dir", data],
                           cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert wait_http(f"http://127.0.0.1:{args.port}/api/config"), "the demo server did not start"
        with sync_playwright() as pw:
            kw = {"headless": True, "args": ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--ignore-certificate-errors"]}
            exe = Path(args.chromium)
            if exe.is_dir():
                cands = sorted(exe.glob("chromium-*/chrome-linux/chrome")) + sorted(exe.glob("chrome-linux/chrome"))
                exe = cands[-1] if cands else None
            if exe and Path(exe).exists():
                kw["executable_path"] = str(exe)
            br = pw.chromium.launch(**kw)
            for sk, (w, h) in SIZES.items():
                if sk not in args.sizes.split(","):
                    continue
                for hk, hour in HOURS.items():
                    if hk not in args.hours.split(","):
                        continue
                    ctx = br.new_context(viewport={"width": w, "height": h}, device_scale_factor=1)
                    pg = ctx.new_page()
                    if args.glb:
                        pg.route("**/room/room_clean.glb", lambda r: r.fulfill(path=args.glb, content_type="model/gltf-binary"))
                    if args.cdn_dir:
                        pg.route("https://**", lambda r: cdn_route(r, Path(args.cdn_dir)))
                    pg.goto(f"http://127.0.0.1:{args.port}/?debug&nolive&hour={hour}", wait_until="load", timeout=240000)
                    pg.wait_for_function("() => window.room && window.boy && document.getElementById('boot') === null", timeout=240000)
                    pg.evaluate("() => { for (const e of document.body.children) if (e.id !== 'scene' && e.tagName !== 'SCRIPT') e.style.visibility = 'hidden'; }")
                    pg.evaluate("() => { try { act('research'); } catch (e) {} settle(); }")
                    for v in views:
                        pos, tgt = VIEWS[v]
                        pg.evaluate("(show) => boy.traverse(o => { if (o.isMesh || o.isSkinnedMesh) o.visible = show; })", v in WITH_HIM)
                        pg.evaluate("([p, t]) => { camera.position.set(p[0], p[1], p[2]); controls.target.set(t[0], t[1], t[2]); controls.update(); settle(); sim(0.05, 3); }", [pos, tgt])
                        time.sleep(0.5)
                        pg.evaluate("() => sim(0.05, 2)")
                        name = f"{v}_{sk}_{hk}{'_' + args.tag if args.tag else ''}.jpg"
                        pg.screenshot(path=str(out / name), type="jpeg", quality=args.quality, timeout=240000)
                        print("wrote", name, flush=True)
                    ctx.close()
            br.close()
    finally:
        srv.terminate()
        try:
            srv.wait(10)
        except Exception:
            srv.kill()


if __name__ == "__main__":
    main()
