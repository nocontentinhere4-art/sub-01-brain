"""Screenshots of the view out of the room's window (#98 G7). Run by hand (no `test_` prefix, pytest does not collect it):

    python tests/room_window_shots.py --before <checkout of main> --out docs/design/room-window

Serves `web/` of this checkout (after) and of --before (main, before) statically, opens /room.html?debug&nolive&hour=H
(&weather=W) in headless Chromium at 1280x800 and 390x844, from the page's overview camera and from his standing place at
the window, at hours 7, 12, 18, 21 and 2, clear and in the rain, and writes one contact sheet per hour and width:
before | after (clear) | after (rain), overview above, the window close-up below. Also the relative cost of the window's
shader under software WebGL (frames with the window plane hidden vs shown, 390 px), which is a relative figure only:
SwiftShader is not a phone's GPU. three.js comes from its CDN; the proxy settings of the environment are passed on.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOURS = (7, 12, 18, 21, 2)
SIZES = ((1280, 800, False), (390, 844, True))
# cameras: the page's overview (what the room opens on) and from where he stands at the window (ANCHOR.window, eyes 1.75 m)
CAMS = {"overview": None, "window": ((0.6, 1.75, 0.0), (-2.0, 1.69, 0.14))}


def serve(web_dir, port):
    p = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(web_dir)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/room.html", timeout=2).read()
            return p
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("static server did not start")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", default=None, help="a checkout of main (its web/ is served as the before)")
    ap.add_argument("--out", default="docs/design/room-window")
    ap.add_argument("--chromium", default=os.environ.get("SUB01_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"))
    ap.add_argument("--port", type=int, default=8811)
    ap.add_argument("--only-after", action="store_true")
    ap.add_argument("--quick", action="store_true", help="one size")
    ap.add_argument("--hours", default=None, help="comma-separated hours (default 7,12,18,21,2)")
    args = ap.parse_args()
    out = Path(args.out) if Path(args.out).is_absolute() else ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="room-window-shots-"))     # the raw PNGs; only the contact sheets are kept
    from PIL import Image, ImageDraw
    from playwright.sync_api import sync_playwright

    servers = [serve(ROOT / "web", args.port)]
    bases = {"after": f"http://127.0.0.1:{args.port}"}
    if args.before and not args.only_after:
        servers.append(serve(Path(args.before) / "web", args.port + 1))
        bases["before"] = f"http://127.0.0.1:{args.port + 1}"
    hours = tuple(int(h) for h in args.hours.split(",")) if args.hours else HOURS
    sizes = SIZES[:1] if args.quick else SIZES
    results = {"errors": {}}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=args.chromium, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
            # the CDNs (three.js, leaflet): fetched by Python (which honours the environment's HTTPS proxy) and cached
            cache = {}
            def cdn(route):
                url = route.request.url
                if url not in cache:
                    try:
                        with urllib.request.urlopen(url, timeout=60) as r:
                            cache[url] = (r.status, r.headers.get("content-type", "application/javascript"), r.read())
                    except Exception as e:                        # noqa: BLE001
                        cache[url] = (502, "text/plain", str(e).encode())
                st, ct, body = cache[url]
                route.fulfill(status=st, content_type=ct, body=body)

            def shot(base, hour, weather, w, h, mobile, cam, path):
                ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1, is_mobile=mobile, has_touch=mobile, ignore_https_errors=True)
                pg = ctx.new_page(); errors = []
                pg.route(re.compile(r"^https://(cdn\.jsdelivr\.net|unpkg\.com)/"), cdn)
                pg.on("pageerror", lambda e: errors.append(str(e)))
                url = f"{base}/room.html?debug&nolive&hour={hour}" + (f"&weather={weather}" if weather else "")
                pg.goto(url, wait_until="load")
                pg.wait_for_function("typeof sky !== 'undefined' && sky && typeof boy !== 'undefined' && boy", timeout=120000)
                pg.wait_for_timeout(3500)                           # textures, clips, the settle of the lights
                pg.evaluate("() => { settle(); if (typeof windowView !== 'undefined') { for (let i = 0; i < 200; i++) windowView.update(0.1, %s); } }" % hour)
                if CAMS[cam]:
                    (px, py, pz), (tx, ty, tz) = CAMS[cam]
                    pg.evaluate(f"() => {{ document.getElementById('cam').click(); camera.position.set({px}, {py}, {pz}); controls.target.set({tx}, {ty}, {tz}); controls.update(); }}")
                pg.evaluate("() => { document.getElementById('corner').style.visibility = 'hidden'; document.getElementById('dock').style.visibility = 'hidden'; document.getElementById('side').style.visibility = 'hidden'; document.getElementById('top').style.visibility = 'hidden'; }")
                pg.wait_for_timeout(600)
                pg.screenshot(path=str(path), timeout=240000)
                st = pg.evaluate("() => typeof windowView !== 'undefined' ? windowView.state() : null")
                ctx.close()
                return errors, st

            sheets = []
            for w, h, mobile in sizes:
                for hour in hours:
                    cols = []                                       # (label, {cam: image})
                    variants = ([("before", bases["before"], None)] if "before" in bases else []) + [("after · clear", bases["after"], "clear"), ("after · rain", bases["after"], "rain")]
                    for label, base, weather in variants:
                        imgs = {}
                        for cam in CAMS:
                            f = tmp / f"{label.split()[0]}_{weather or 'x'}_{hour:02d}_{w}_{cam}.png"
                            errors, st = shot(base, hour, weather, w, h, mobile, cam, f)
                            if errors: results["errors"][f.name] = errors[:3]
                            if st: results[f"{weather}_{hour:02d}"] = {k: st[k] for k in ("kind", "cloud", "rain") if k in st} | {"weather": st.get("weather")}
                            imgs[cam] = Image.open(f).convert("RGB")
                        cols.append((label, imgs))
                    # the contact sheet: one column per variant, overview above the window view
                    cw, ch = w, h
                    scale = 0.5 if w > 1000 else 1.0
                    cw, ch = int(cw * scale), int(ch * scale)
                    pad, head = 10, 28
                    sheet = Image.new("RGB", (len(cols) * (cw + pad) + pad, head + 2 * (ch + pad) + pad), (18, 18, 22))
                    d = ImageDraw.Draw(sheet)
                    for i, (label, imgs) in enumerate(cols):
                        x = pad + i * (cw + pad)
                        d.text((x, 8), f"{label} · {hour:02d}:00 Tokyo · {w} px", fill=(235, 235, 235))
                        for j, cam in enumerate(CAMS):
                            im = imgs[cam].resize((cw, ch), Image.LANCZOS)
                            sheet.paste(im, (x, head + j * (ch + pad)))
                    name = f"h{hour:02d}_{w}.jpg"
                    sheet.save(out / name, "JPEG", quality=82, optimize=True)
                    sheets.append(name)
                    print("wrote", name, flush=True)

            # the shader's relative cost under software GL: frame time with the window plane hidden vs shown (390 px, window view)
            ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True, has_touch=True, ignore_https_errors=True)
            pg = ctx.new_page()
            pg.route(re.compile(r"^https://(cdn\.jsdelivr\.net|unpkg\.com)/"), cdn)
            pg.goto(f"{bases['after']}/room.html?debug&nolive&hour=21&weather=rain", wait_until="load")
            pg.wait_for_function("typeof sky !== 'undefined' && sky && typeof boy !== 'undefined' && boy", timeout=120000)
            pg.wait_for_timeout(3000)
            (px, py, pz), (tx, ty, tz) = CAMS["window"]
            pg.evaluate(f"() => {{ document.getElementById('cam').click(); camera.position.set({px}, {py}, {pz}); controls.target.set({tx}, {ty}, {tz}); controls.update(); }}")
            cost = pg.evaluate("""() => { const t = (n) => { const a = performance.now(); for (let i = 0; i < n; i++) { renderer.render(scene, camera); renderer.getContext().finish(); } return (performance.now() - a) / n; };
              t(3); sky.visible = false; const off = t(12); sky.visible = true; const on = t(12);
              const u = (n) => { const a = performance.now(); for (let i = 0; i < n; i++) windowView.update(0.016, 21.3); return (performance.now() - a) / n; };
              return {software_gl_ms_window_hidden: +off.toFixed(1), software_gl_ms_window_shown: +on.toFixed(1), window_update_js_ms: +u(2000).toFixed(4),
                      fragment_px: Math.round(390 * 844)}; }""")
            results["cost_390px_window_view_swiftshader"] = cost
            ctx.close()
            browser.close()
    finally:
        for s in servers:
            s.terminate()
    results["sheets"] = sheets
    print(json.dumps(results, indent=1))
    (out / "results.json").write_text(json.dumps(results, indent=1) + "\n")


if __name__ == "__main__":
    main()
