"""Screenshots, segment counts and timings of the neuron close-ups on /brain (#78). Run by hand (not collected):

    python tests/neurons_morph_shots.py --out docs/screens/neurons_morph --cdn-dir <dir with three.min.js, OrbitControls.js>

Same harness as tests/neurons3d_shots.py: live_server.py --demo with no live spiking network, and a RECORDED stream of
the real 20k CPU network's frames (recorded in this process, put through frames.Budget as a viewer gets them) replayed
by this script into the page's own websocket handler; the server never serves it. At 1280 and 390 px:
  - the whole brain with the neurons layer (points);
  - a close-up of cortex (the recorded stream's most active cortical region), with live spikes from the stream;
  - a close-up of the hippocampus (CA1 pyramidal cells), with live spikes from the stream;
  - a 3-frame strip of a spike pulse leaving a soma along its axon (cortex close-up, 1280 px);
  - the offline close-up (no stream): shapes only, no activity.
Also: the layer's JS time per rendered frame and per message (CPU x4), and FPS in the close-up (software WebGL here).
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import neurons3d_shots as N3  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8793)
    ap.add_argument("--out", default="docs/screens/neurons_morph")
    ap.add_argument("--chromium", default=os.environ.get("SUB01_CHROMIUM", "/opt/pw-browsers/chromium"))
    ap.add_argument("--cdn-dir", default=None)
    args = ap.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    frames = N3.record(seconds=24.0, every_s=0.8)
    from spiking import frames as F
    count = {}
    for _, f in frames:
        for reg, _, _ in F.unpack_spikes(f["n3"]["sq"], f["n3"]["span"]).astype(int):
            if reg < 200:
                count[reg] = count.get(reg, 0) + 1
    region = int(max(count, key=count.get))
    print(f"recorded {len(frames)} frames; cortical region with most sampled spikes: {region} ({count[region]} spikes)")

    tmp = tempfile.mkdtemp(prefix="morphshots-")
    env = dict(os.environ, BROWSE="0", SUB01_SPIKING_LIVE="0", SUB01_WS_STATS_S="3600")
    proc = subprocess.Popen([sys.executable, str(ROOT / "live_server.py"), "--demo", "--port", str(args.port), "--host",
                             "127.0.0.1", "--data-dir", tmp], cwd=ROOT, env=env, stdout=open(Path(tmp) / "log", "w"),
                            stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{args.port}"
    res = {"region": region}
    try:
        N3.wait_ready(base, proc)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=args.chromium,
                                        args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])

            def page(w, h, mobile=False):
                ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1, is_mobile=mobile,
                                          has_touch=mobile)
                pg = ctx.new_page()
                pg.add_init_script(N3.INJECT)
                if args.cdn_dir:
                    cdn = Path(args.cdn_dir)
                    pg.route("**/three.min.js", lambda r: r.fulfill(path=str(cdn / "three.min.js"), content_type="text/javascript"))
                    pg.route("**/OrbitControls.js", lambda r: r.fulfill(path=str(cdn / "OrbitControls.js"), content_type="text/javascript"))
                errors = []
                pg.on("pageerror", lambda e: errors.append(str(e)))
                pg.goto(base + "/brain", wait_until="load")
                pg.wait_for_function("window.__brainWs && window.__brainWs.readyState === 1", timeout=60000)
                pg.wait_for_timeout(2500)
                return ctx, pg, errors

            def shot(pg, name):
                pg.screenshot(path=str(out / name), timeout=180000)

            def closeup(pg, kind, reg=None):
                pg.evaluate(f"closeupOpen({json.dumps(kind)}, {json.dumps(reg)})")
                pg.wait_for_function("document.body.classList.contains('closeup')", timeout=60000)
                pg.wait_for_timeout(2500)

            for w, h, mobile, tag in ((1280, 800, False, "1280"), (390, 844, True, "390")):
                ctx, pg, errors = page(w, h, mobile)
                pg.evaluate("document.querySelector('#layers button[data-l=\"neurons\"]').click()")
                pg.wait_for_timeout(1500)
                closeup(pg, "cortex", region)
                shot(pg, f"cortex_{tag}_offline.png")
                res[f"offline_{tag}"] = pg.inner_text("#n3cap")
                pg.evaluate("f => window.__replay(f)", frames)
                pg.evaluate("closeupExit()")
                pg.wait_for_function("document.querySelector('#n3cap').innerText.includes('live')", timeout=120000)
                pg.wait_for_timeout(2000)
                shot(pg, f"brain_{tag}_points.png")
                closeup(pg, "cortex", region)
                pg.wait_for_timeout(3000)
                shot(pg, f"cortex_{tag}_closeup.png")
                res[f"cortex_{tag}"] = pg.inner_text("#n3cap")
                closeup(pg, "hippocampus")
                pg.wait_for_timeout(3000)
                shot(pg, f"hippocampus_{tag}_closeup.png")
                res[f"hippocampus_{tag}"] = pg.inner_text("#n3cap")
                res[f"errors_{tag}"] = errors
                ctx.close()

            # 3-frame strip: the cortex close-up, a recorded frame with spikes in that region, three shots after it
            ctx, pg, errors = page(1280, 800)
            pg.evaluate("document.querySelector('#layers button[data-l=\"neurons\"]').click()")
            pg.wait_for_timeout(1000)
            with_spikes = [f for _, f in frames if (F.unpack_spikes(f["n3"]["sq"], f["n3"]["span"])[:, 0] == region).any()]
            for f in frames[:3]:
                pg.evaluate("m => window.__brainWs.onmessage({data: JSON.stringify(m)})", f[1])
            closeup(pg, "cortex", region)
            pg.evaluate("controls.autoRotate = false")
            for f in with_spikes[:6]:                               # several sampled spikes of this region at once
                pg.evaluate("m => window.__brainWs.onmessage({data: JSON.stringify(m)})", f)
            t0 = time.time()
            for i in range(3):
                shot(pg, f"spike_strip_{i + 1}.png")
                res[f"strip_{i + 1}_s"] = round(time.time() - t0, 2)
            from PIL import Image                                   # one image: the three frames side by side
            ims = [Image.open(out / f"spike_strip_{i + 1}.png").crop((120, 180, 900, 720)) for i in range(3)]
            strip = Image.new("RGB", (3 * ims[0].width + 20, ims[0].height))
            for i, im in enumerate(ims):
                strip.paste(im, (i * (im.width + 10), 0))
            strip.save(out / "spike_strip.png")
            for i in range(3):
                (out / f"spike_strip_{i + 1}.png").unlink()
            res["strip_errors"] = errors
            ctx.close()

            # timings under a mid phone profile (CPU x4): the close-up's own JS per message and per rendered frame
            ctx, pg, errors = page(390, 844, True)
            cdp = ctx.new_cdp_session(pg)
            cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
            res["js_x4"] = pg.evaluate("""async f => {
              const morph = await (await fetch('neurons_morph.json')).json(), out = {};
              for (const kind of ['cortex', 'striatum', 'thalamus', 'hippocampus', 'amygdala']) {
                let t = performance.now();
                const c = Neurons3D.closeup({THREE, morph, kind, region: {cortex: 12, striatum: 202, thalamus: 200, hippocampus: 204, amygdala: 212}[kind]});
                const build = performance.now() - t;
                let tm = 0, tu = 0, k = 0;
                for (const [, m] of f) { t = performance.now(); c.onFrame(m); tm += performance.now() - t;
                  for (let i = 0; i < 12; i++) { t = performance.now(); c.update(performance.now()); tu += performance.now() - t; k++; } }
                const i = c.info(); c.dispose();
                out[kind] = {cells: i.cells, segments: i.segments, draw_calls: i.drawCalls, build_ms: +build.toFixed(1),
                             per_message_ms: +(tm / f.length).toFixed(3), per_frame_ms: +(tu / k).toFixed(4)};
              }
              return out; }""", frames)
            pg.evaluate("document.querySelector('#layers button[data-l=\"neurons\"]').click()")
            pg.evaluate("f => window.__replay(f)", frames)
            closeup(pg, "cortex", region)
            res["fps_x4_closeup_cortex_390"] = round(pg.evaluate("window.__fps(6000)"), 1)
            cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
            res["fps_x1_closeup_cortex_390"] = round(pg.evaluate("window.__fps(6000)"), 1)
            res["timing_errors"] = errors
            ctx.close()
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=20)
    print(json.dumps(res, indent=1, ensure_ascii=False))
    (out / "results.json").write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
