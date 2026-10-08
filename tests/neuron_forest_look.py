"""How bright the whole-brain neuron forest is (#88 B follow-up: "it looks like a Christmas tree"). Run by hand (no
`test_` prefix):

    python tests/neuron_forest_look.py --out docs/screens/neuron_forest_look --tag after

Starts `live_server.py --demo` (no live spiking network), opens /brain at 1920 x 1080 and 390 x 844 with the neurons
toggle on and the page's default layers (fibres and cortex on, as a viewer sees it), first offline, then with a RECORDED
stream of the 20k CPU network replayed into the page's socket handler (tests/neurons3d_shots.py: test only, the
server never serves it). For each shot the page's text and panels are hidden for a second copy, and the luminance of
the brain's pixels is measured on it (Rec. 709 luma of the sRGB pixel, 0-1): "brain pixels" are those above 0.03,
and the target is <= 2 % of them above 0.8 at rest. Also the same with fibres and cortex hidden (the forest alone).
Writes <tag>_<w>_<offline|live>.jpg (as seen) and <tag>_luminance.json.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from neurons3d_shots import INJECT, record, wait_ready  # noqa: E402

HIDE = "#top, #cards, #dock, #ticker, #honest, #n3mini, #vignette { visibility: hidden !important; }"


def luminance(path):
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float64) / 255.0
    y = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    brain = y > 0.03
    n = int(brain.sum())
    return {"brain_px": n, "above_0_8_pct": round(100.0 * float((y[brain] > 0.8).sum()) / max(1, n), 2),
            "above_0_5_pct": round(100.0 * float((y[brain] > 0.5).sum()) / max(1, n), 2),
            "mean": round(float(y[brain].mean()) if n else 0.0, 3), "p99": round(float(np.percentile(y[brain], 99)) if n else 0.0, 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8792)
    ap.add_argument("--out", default="docs/screens/neuron_forest_look")
    ap.add_argument("--tag", default="after")
    ap.add_argument("--chromium", default=os.environ.get("SUB01_CHROMIUM", "/opt/pw-browsers/chromium"))
    ap.add_argument("--cdn-dir", default=None)
    args = ap.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    frames = record(seconds=12.0)
    tmp = tempfile.mkdtemp(prefix="n3look-")
    env = dict(os.environ, BROWSE="0", SUB01_SPIKING_LIVE="0", SUB01_WS_STATS_S="3600")
    proc = subprocess.Popen([sys.executable, str(ROOT / "live_server.py"), "--demo", "--port", str(args.port), "--host",
                             "127.0.0.1", "--data-dir", tmp], cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{args.port}"
    res = {}
    try:
        wait_ready(base, proc)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=args.chromium, args=["--use-gl=angle", "--use-angle=swiftshader",
                                                                             "--enable-unsafe-swiftshader"])
            for w, h, mobile in ((1920, 1080, False), (390, 844, True)):
                ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1, is_mobile=mobile,
                                          has_touch=mobile)
                pg = ctx.new_page()
                pg.add_init_script(INJECT)
                if args.cdn_dir:
                    cdn = Path(args.cdn_dir)
                    pg.route("**/three.min.js", lambda r: r.fulfill(path=str(cdn / "three.min.js"), content_type="text/javascript"))
                    pg.route("**/OrbitControls.js", lambda r: r.fulfill(path=str(cdn / "OrbitControls.js"), content_type="text/javascript"))
                pg.goto(base + "/brain", wait_until="load")
                pg.wait_for_function("window.__brainWs && window.__brainWs.readyState === 1", timeout=60000)
                pg.wait_for_timeout(2500)
                pg.evaluate("controls.autoRotate = false")
                pg.evaluate("document.querySelector('#layers button[data-l=\"neurons\"]').click()")
                pg.wait_for_function("typeof n3d !== 'undefined' && n3d && n3d.state().cells > 0", timeout=120000)
                pg.wait_for_timeout(3000)
                st = pg.evaluate("n3d.state()")
                res[f"state_{w}"] = {k: st[k] for k in ("cells", "segments", "drawCalls", "enlarge") if k in st}

                def shoot(name):
                    pg.screenshot(timeout=180000, path=str(out / f"{args.tag}_{name}.jpg"), type="jpeg", quality=85)
                    pg.add_style_tag(content=HIDE)
                    pg.wait_for_timeout(600)
                    raw = Path(tmp) / f"{name}.png"
                    pg.screenshot(timeout=180000, path=str(raw))
                    res[name] = luminance(raw)
                    pg.evaluate("document.querySelectorAll('style').forEach(s => { if (s.textContent.includes('visibility: hidden !important')) s.remove(); })")
                    pg.wait_for_timeout(400)

                shoot(f"{w}_offline")
                pg.evaluate("f => window.__replay(f)", frames)
                pg.wait_for_function("document.querySelector('#n3cap').innerText.includes('live')", timeout=120000)
                pg.wait_for_timeout(2500)
                shoot(f"{w}_live")
                for layer in ("fibres", "cortex"):
                    pg.evaluate(f"document.querySelector('#layers button[data-l=\"{layer}\"]').click()")
                pg.wait_for_timeout(1500)
                shoot(f"{w}_live_forest_only")
                ctx.close()
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=20)
    print(json.dumps(res, indent=1))
    (out / f"{args.tag}_luminance.json").write_text(json.dumps(res, indent=1) + "\n")


if __name__ == "__main__":
    main()
