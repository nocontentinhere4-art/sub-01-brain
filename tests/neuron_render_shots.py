"""Screenshots, counts and timings of the microscopy-grade neuron close-ups on /brain (#88 A). Run by hand:

    python tests/neuron_render_shots.py --out docs/screens/neuron_render [--cdn-dir <dir with three.min.js, OrbitControls.js>]

Same harness as tests/neurons3d_shots.py: live_server.py --demo with no live spiking network, and a RECORDED stream of
the real 20k CPU network's frames (recorded in this process, put through frames.Budget as a viewer gets them) replayed
by this script into the page's own websocket handler; the server never serves it. It takes:
  - the offline close-up (no stream): static cells, the caption says so (1280 and 390 px);
  - every close-up region (cortex, striatum, thalamus, hippocampus, amygdala) in both styles (fluorescence, 3D render)
    at 1280 and 390 px, with the recorded stream live;
  - a strip of an action potential leaving a soma and running down the axon (cortex, fluorescence, 1280 px);
  - a side-by-side with the reference look (a GFP-labelled pyramidal neuron, Wikimedia Commons, CC BY 2.5);
  - the renderer's own numbers: triangles, spines, boutons, nodes of Ranvier, draw calls, and under a mid-phone profile
    (CPU x4) the JS ms per frame and the FPS. Headless Chromium here draws WebGL in software (SwiftShader): FPS numbers
    are those of a CPU rasteriser, not of a phone GPU, and are reported as such.
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

KINDS = ["cortex", "striatum", "thalamus", "hippocampus", "amygdala"]
REGION = {"cortex": None, "striatum": 202, "thalamus": 200, "hippocampus": 204, "amygdala": 212}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8795)
    ap.add_argument("--out", default="docs/screens/neuron_render")
    ap.add_argument("--chromium", default=os.environ.get("SUB01_CHROMIUM", "/opt/pw-browsers/chromium"))
    ap.add_argument("--cdn-dir", default=None)
    ap.add_argument("--reference", default="docs/screens/neuron_render/reference_gfp_pyramidal.jpg")
    ap.add_argument("--quick", action="store_true", help="cortex only")
    ap.add_argument("--only-strip", action="store_true", help="only the action-potential strip (results.json keeps the rest)")
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
    REGION["cortex"] = region
    print(f"recorded {len(frames)} frames; cortical region with most sampled spikes: {region} ({count[region]} spikes)")

    tmp = tempfile.mkdtemp(prefix="nrshots-")
    env = dict(os.environ, BROWSE="0", SUB01_SPIKING_LIVE="0", SUB01_WS_STATS_S="3600")
    proc = subprocess.Popen([sys.executable, str(ROOT / "live_server.py"), "--demo", "--port", str(args.port), "--host",
                             "127.0.0.1", "--data-dir", tmp], cwd=ROOT, env=env, stdout=open(Path(tmp) / "log", "w"),
                            stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{args.port}"
    res = {"region": region, "software_webgl": True,
           "note": "headless Chromium with SwiftShader (software WebGL): FPS here is a CPU rasteriser's, not a phone GPU's"}
    if args.only_strip and (out / "results.json").exists():
        res = json.loads((out / "results.json").read_text())
    kinds = ["cortex"] if args.quick else KINDS
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
                pg.on("console", lambda m: errors.append("console." + m.type + ": " + m.text) if m.type in ("error",) else None)
                pg.goto(base + "/brain", wait_until="load")
                pg.wait_for_function("window.__brainWs && window.__brainWs.readyState === 1", timeout=60000)
                pg.wait_for_timeout(1500)
                pg.evaluate("document.querySelector('#layers button[data-l=\"neurons\"]').click()")
                pg.wait_for_timeout(800)
                return ctx, pg, errors

            def shot(pg, name):
                pg.screenshot(path=str(out / name), timeout=240000)

            def closeup(pg, kind, reg, style):
                pg.evaluate(f"closeupOpen({json.dumps(kind)}, {json.dumps(reg)})")
                pg.wait_for_function("n3close && n3close.info().cells > 0", timeout=180000)
                pg.evaluate(f"n3close.setStyle({json.dumps(style)})")
                pg.wait_for_timeout(2500)                      # a few frames rendered (software GL: slow)
                return pg.evaluate("n3close.info()")

            widths = ((1920, 1080, False, "1920"), (1280, 800, False, "1280"), (390, 844, True, "390"))
            for w, h, mobile, tag in () if args.only_strip else widths:
                ctx, pg, errors = page(w, h, mobile)
                info = closeup(pg, "cortex", region, "fluorescence")
                shot(pg, f"cortex_{tag}_offline.png")
                res[f"offline_{tag}"] = {"caption": pg.inner_text("#n3cap"), "live": info["live"], "spikes": info["spikes"], "source": info.get("source")}
                pg.evaluate("f => window.__replay(f)", frames)
                pg.wait_for_function("n3close.info().live", timeout=120000)
                for kind in kinds:
                    # #99: cortex draws the real H01 cells ("after"); the NeuroMorpho procedural cells are the "before"
                    variants = [("h01", ("fluorescence", "em"))] if kind == "cortex" else [("", ("fluorescence", "render"))]
                    if kind == "cortex" and not args.quick:
                        variants.append(("before", ("fluorescence", "render")))
                    for variant, styles in variants:
                        pg.evaluate("v => { NeuronRender.H01_SETS.cortex = v === 'before' ? null : 'cortex'; }", variant)
                        for style in styles:
                            info = closeup(pg, kind, REGION[kind], style)
                            name = f"{kind}_{tag}_{style}" + ("_before" if variant == "before" else "")
                            shot(pg, name + ".png")
                            keep = ("source", "cells", "heroCells", "triangles", "triangleCap", "spines", "spineUm", "dendUm", "boutons", "nodesOfRanvier",
                                    "drawCalls", "lineSegments", "live", "spikes", "lod", "halfFloat", "webgl2", "synapsesPre", "synapsesPost", "myelinatedUm",
                                    "glia", "far", "bytes", "focusId", "ids")
                            res[name] = {k: info[k] for k in keep if k in info}
                            res[name]["caption"] = pg.inner_text("#n3cap")
                        pg.evaluate("NeuronRender.H01_SETS.cortex = 'cortex'")
                res[f"errors_{tag}"] = errors
                ctx.close()

            # the action potential: the focus cell (drawn cell 0) spikes; frames after it (software GL: the times are recorded)
            ctx, pg, errors = page(1280, 800)
            pg.evaluate("f => window.__replay(f)", frames)
            closeup(pg, "cortex", region, "fluorescence")
            # software WebGL takes seconds per screenshot, so the renderer's clock is frozen at fixed times after the spike
            # (nr.debugTime, a test hook): what a viewer sees at those moments on a device that keeps up
            pg.evaluate("n3close.spike(0, 0)")                  # slot 0 -> drawn cell 0, the cell in focus
            h01 = pg.evaluate("n3close.info().source") == "H01"
            # #99, H01: the real axon is ~0.5 um thick and 4 mm long, so each frame is cropped around the front, projected to the screen
            # from the vertices whose arrival time is just before the frozen clock (the cell's own aArrive), and enlarged 2.5x
            FRONT = """t => { const c = n3close.cells[0], m = c.h01.mesh, cam = n3close.camera; let n = 0, x = 0, y = 0, d = 0;
              for (let i = 0; i < m.nv; i++) { const a = m.arrive[i], k = m.kind[i]; if (a < 0 || a > t || a < t - 0.12 || !(k === 1 || k === 4 || k === 5)) continue;
                const v = new THREE.Vector3(m.pos[3 * i], m.pos[3 * i + 1], m.pos[3 * i + 2]).applyQuaternion(n3close.scene.quaternion).project(cam);
                x += (v.x + 1) / 2 * innerWidth; y += (1 - v.y) / 2 * innerHeight; d += m.dist[i]; n++; }
              return n ? {x: x / n, y: y / n, dist: d / n, n} : null; }"""
            pg.mouse.click(640, 300)                            # stops the slow auto-rotation, so the frames line up
            pg.evaluate("document.getElementById('dock').style.visibility = 'hidden'")   # the page's panel would cover the axon's path
            strip, fronts = [], []
            times = [0.3, 1.0, 2.0, 4.0, 8.0] if h01 else [0.1, 1.5, 1.7, 1.9, 2.1]   # procedural: the initial segment (48 um) at the unmyelinated speed ~1.6 s, then ~0.6 mm/s
            for i, t in enumerate(times):
                pg.evaluate(f"n3close.debugTime({t})")
                pg.wait_for_timeout(1200)
                name = f"ap_{i + 1}.png"
                shot(pg, name)
                strip.append(name)
                fronts.append(pg.evaluate(FRONT, t) if h01 else None)
            pg.evaluate("n3close.debugTime(null); document.getElementById('dock').style.visibility = ''")
            res["ap_strip_clock_s"] = times
            res["ap_front_um"] = [round(f["dist"], 1) if f else None for f in fronts]
            from PIL import Image
            ims = []
            for n, f in zip(strip, fronts):
                im = Image.open(out / n)
                if f: x, y = int(f["x"]), int(f["y"]); im = im.crop((x - 100, y - 100, x + 100, y + 100)).resize((500, 500), Image.LANCZOS)
                else: im = im.crop((390, 230, 890, 730))                             # 1280 px frames
                ims.append(im)
            W = sum(i.width for i in ims) + 10 * (len(ims) - 1)
            im = Image.new("RGB", (W, ims[0].height))
            x = 0
            for i in ims:
                im.paste(i, (x, 0))
                x += i.width + 10
            im.save(out / "ap_strip.png")
            for n in strip:
                (out / n).unlink()
            res["ap_errors"] = errors
            # side by side with the reference look
            ref = ROOT / args.reference
            if ref.exists():
                a = Image.open(ref).convert("RGB")
                b = Image.open(out / "cortex_1920_fluorescence.png").convert("RGB").crop((300, 120, 1620, 1000))
                hh = 520
                a = a.resize((round(a.width * hh / a.height), hh))
                b = b.resize((round(b.width * hh / b.height), hh))
                sb = Image.new("RGB", (a.width + b.width + 12, hh))
                sb.paste(a, (0, 0))
                sb.paste(b, (a.width + 12, 0))
                sb.save(out / "side_by_side.png")
            ctx.close()

            if args.only_strip:
                browser.close()
                proc.terminate()
                proc.wait(timeout=20)
                (out / "results.json").write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n")
                print("strip at", times)
                return
            # a mid phone profile (CPU x4): the renderer's own JS per frame and FPS (software WebGL: CPU rasteriser)
            ctx, pg, errors = page(390, 844, True)
            cdp = ctx.new_cdp_session(pg)
            res["build_ms_x4"] = {}
            cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
            pg.evaluate("f => window.__replay(f)", frames)
            for kind in kinds:
                t = time.time()
                info = closeup(pg, kind, REGION[kind], "fluorescence")
                res["build_ms_x4"][kind] = round((time.time() - t) * 1000)
                pg.wait_for_timeout(6500)
                info = pg.evaluate("n3close.info()")
                res[f"phone_x4_{kind}"] = {"fps_software_gl": round(info["fps"], 1), "js_ms_per_frame": round(info["jsMs"], 2),
                                           "triangles": info["triangles"], "cells": info["cells"], "lod": info["lod"]}
            cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
            pg.wait_for_timeout(4000)
            info = pg.evaluate("n3close.info()")
            res["phone_x1_last"] = {"fps_software_gl": round(info["fps"], 1), "js_ms_per_frame": round(info["jsMs"], 2)}
            # the geometry build alone (pure JS, no GPU), x4
            cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
            res["geometry_ms_x4"] = pg.evaluate("""() => { const out = {}; const C = NeuronRender.CELLS;
              for (const t of Object.keys(C.cells)) { const s = performance.now(); const g = NeuronRender.cellGeometry(THREE, C.cells[t], NeuronRender.TYPES[t], 'hero', NeuronRender.LOD.phone, 1);
                out[t] = {ms: +(performance.now() - s).toFixed(0), triangles: g.tri, spines: g.spines}; g.geom.dispose(); } return out; }""")
            cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
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
