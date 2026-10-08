"""Screenshots and FPS of the brain as a real specimen on /brain (#99 G9, web/brain_anatomy.js). Run by hand (no `test_`
prefix: pytest does not collect it):

    python tests/brain_anatomy_shots.py --out docs/screens/brain_anatomy

Starts `live_server.py --demo` (BROWSE=0, no live spiking network), then in headless Chromium takes, at 1920 and 390 px:
  before (the page's own glow look) awake with a stimulus travelling and asleep (NREM), the bundles view in the same two
  states, fresh brain, dissected (coronal cut through the middle), fresh brain with vessels and nerves; plus the sagittal
  and axial cuts and a view from below at 1920. The sleep stage is pinned in the page (the server's ticks would reset it). Writes results.json with each view's caption, the
  anatomy module's state (meshes, parts, atlas loaded; tier) and page errors, and an FPS reading per view at 390 px with
  the CPU throttled x4. Headless Chromium draws WebGL in software (SwiftShader): the FPS numbers here are a floor and
  the >= 30 FPS phone check needs a real device (docs/HANDOFF.md says the same for the neuron forest).
--cdn-dir serves three.min.js and OrbitControls.js from local copies when the sandbox has no route to the CDNs.
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

FPS = """(ms) => new Promise(res => { let n = 0; const t0 = performance.now();
  const f = () => { n++; if (performance.now() - t0 < ms) requestAnimationFrame(f); else res(+(n * 1000 / (performance.now() - t0)).toFixed(1)); };
  requestAnimationFrame(f); })"""


def wait_ready(base, proc, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            raise RuntimeError("server exited")
        try:
            urllib.request.urlopen(base + "/api/config", timeout=2).read()
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("server not ready")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8793)
    ap.add_argument("--out", default="docs/screens/brain_anatomy")
    ap.add_argument("--chromium", default=os.environ.get("SUB01_CHROMIUM", "/opt/pw-browsers/chromium"))
    ap.add_argument("--fps-s", type=float, default=5.0)
    ap.add_argument("--sizes", default="1920,390")
    ap.add_argument("--cdn-dir", default=None, help="serve three.min.js and OrbitControls.js from local copies (no route to the CDNs)")
    args = ap.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="anatshots-")
    env = dict(os.environ, BROWSE="0", SUB01_SPIKING_LIVE="0", SUB01_WS_STATS_S="3600")
    log = open(Path(tmp) / "server.log", "w")
    proc = subprocess.Popen([sys.executable, str(ROOT / "live_server.py"), "--demo", "--port", str(args.port), "--host", "127.0.0.1",
                             "--data-dir", tmp], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{args.port}"
    results = {}
    try:
        wait_ready(base, proc)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=args.chromium, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])

            def page_for(w, h, mobile):
                ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1, is_mobile=mobile, has_touch=mobile)
                pg = ctx.new_page()
                errors = []
                pg.on("pageerror", lambda e: errors.append(str(e)))
                if args.cdn_dir:
                    cdn = Path(args.cdn_dir)
                    pg.route("**/three.min.js", lambda r: r.fulfill(path=str(cdn / "three.min.js"), content_type="text/javascript"))
                    pg.route("**/OrbitControls.js", lambda r: r.fulfill(path=str(cdn / "OrbitControls.js"), content_type="text/javascript"))
                pg.goto(base + "/brain", wait_until="load")
                try:
                    pg.wait_for_function("typeof scene !== 'undefined' && scene.getObjectByName('cortex') && scene.getObjectByName('fibres')", timeout=120000)
                except Exception:
                    print("page errors:", errors, file=sys.stderr)
                    raise
                pg.evaluate("controls.autoRotate = false")
                pg.wait_for_timeout(1500)
                return ctx, pg, errors

            def hold(pg, stage):                      # pin the sleep stage (the server's ticks would reset it) and send a stimulus
                pg.evaluate(f"""() => {{ if (!window.__setStage) window.__setStage = setStage; window.__setStage({json.dumps(stage)});
                    setStage = () => {{}}; mix = [...target]; if ({json.dumps(stage)} === 'AWAKE') fire('a stimulus travelling', ['default', 'attention']); }}""")
                pg.wait_for_timeout(900 if stage == "AWAKE" else 2500)

            def view(pg, v, layers=(), cut=None, settle=3000, stage=None):
                pg.evaluate(f"anatView({json.dumps(v)})")
                for a in ("vessels", "nerves"):
                    pg.evaluate(f"""() => {{ const b = document.querySelector('#anat button[data-a="{a}"]'); if (b.classList.contains('on') !== {json.dumps(a in layers)}) b.click(); }}""")
                if v != "glow":
                    pg.wait_for_function("anat && anat.state().loading === 0 && (anat.state().view !== 'fresh' && anat.state().view !== 'fixed' || anat.state().meshes)", timeout=120000)
                    if layers:
                        pg.wait_for_function("anat.state().parts", timeout=120000)
                    if cut:
                        pg.evaluate(f"() => {{ const b = document.getElementById('anat-axis'); b.textContent = {json.dumps(cut[0])}; const r = document.getElementById('anat-cut'); r.value = {cut[1]}; anat.setCut({json.dumps(cut[0])}, {cut[1]}); }}")
                        pg.wait_for_function("anat.state().atlas", timeout=120000)
                if stage:
                    hold(pg, stage)
                    settle = 600
                pg.wait_for_timeout(settle)
                st = pg.evaluate("anat ? anat.state() : null") if v != "glow" else None
                return {"caption": pg.inner_text("#anatcap") if v != "glow" else "", "state": st}

            shots = [("before_awake", "glow", (), None, "AWAKE"), ("before_asleep", "glow", (), None, "NREM"),
                     ("bundles_awake", "bundles", (), None, "AWAKE"), ("bundles_asleep", "bundles", (), None, "NREM"),
                     ("fresh", "fresh", (), None, "AWAKE"), ("dissected", "fixed", (), ("coronal", 0.5), None),
                     ("nerves", "fresh", ("vessels", "nerves"), None, None)]
            for size in [int(x) for x in args.sizes.split(",")]:
                w, h, mobile = (size, 844, True) if size < 600 else (size, 1080, False)
                ctx, pg, errors = page_for(w, h, mobile)
                for tag, v, layers, cut, stage in shots:
                    r = view(pg, v, layers, cut, stage=stage)
                    pg.screenshot(timeout=180000, path=str(out / f"{tag}_{size}.jpg"), type="jpeg", quality=88)
                    results[f"{tag}_{size}"] = r
                if size >= 600:
                    for axis, t in (("sagittal", 0.35), ("axial", 0.55)):
                        r = view(pg, "fixed", (), (axis, t))
                        pg.screenshot(timeout=180000, path=str(out / f"dissected_{axis}_{size}.jpg"), type="jpeg", quality=88)
                        results[f"dissected_{axis}_{size}"] = r
                    # from below: the circle of Willis, chiasm and nerves
                    view(pg, "fresh", ("vessels", "nerves"), None)
                    pg.evaluate("() => { camera.position.set(-60, 40, -330); controls.update(); }")
                    pg.wait_for_timeout(2500)
                    pg.screenshot(timeout=180000, path=str(out / f"nerves_below_{size}.jpg"), type="jpeg", quality=88)
                results[f"errors_{size}"] = errors
                if size < 600:
                    cdp = ctx.new_cdp_session(pg)
                    cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
                    fps = {}
                    for tag, v, layers, cut, stage in shots:
                        view(pg, v, layers, cut, settle=1500)
                        fps[tag] = pg.evaluate(f"({FPS})({int(args.fps_s * 1000)})")
                    results["fps_390_cpu_x4_software_gl"] = fps
                ctx.close()
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=20)
        log.close()
    (out / "results.json").write_text(json.dumps(results, indent=1))
    print(json.dumps({k: v for k, v in results.items() if k.startswith("fps") or k.startswith("errors")}, indent=1))
    for k, v in results.items():
        if isinstance(v, dict) and v.get("caption"):
            print(f"{k}: {v['caption'][:160]}")


if __name__ == "__main__":
    main()
