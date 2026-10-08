"""Screenshots and FPS of the neurons layer on /brain (#62; the forest of real cells, #88 B). Run by hand (no `test_` prefix: pytest does not collect it):

    python tests/neurons3d_shots.py --out docs/screens/neuron_forest

Starts `live_server.py --demo` (BROWSE=0, SUB01_SPIKING_LIVE=0: no live spiking network on the server), then in headless
Chromium:
  1. /brain with the neurons toggle on and no live network: the offline state, static cells (1920, 1280, 390 px), and
     the right panel's layout (bounding boxes: the cards must end above the dock);
  2. a RECORDED stream: real frames of the 20k CPU network (spiking/live.py) recorded in this process while it decides,
     put through frames.Budget exactly as a viewer gets them, and replayed by this script into the page's own websocket
     handler. The server never serves it; it exists for screenshots and the FPS check only. Screenshots at 1920, 1280
     and 390 px (the page as it opens, and the forest alone, zoomed in, fibres and cortex hidden), and the room's mini
     brain (/brain?mini&neurons=1 at the PiP's 300 x 225);
  3. FPS with the CPU throttled x4 (devtools Emulation.setCPUThrottlingRate), neurons off vs on, over --fps-s seconds,
     and the layer's own main-thread cost under the same throttle. Headless Chromium draws WebGL in software
     (SwiftShader): the fibres alone fall below 1 frame/s there, so FPS is measured with fibres and cortex hidden.

Chromium: --chromium (default /opt/pw-browsers/chromium). The page's three.js comes from a CDN; --cdn-dir serves
three.min.js and OrbitControls.js from local copies when the sandbox has no route to the CDNs.
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
sys.path.insert(0, str(ROOT))

INJECT = """
(() => {
  const Real = window.WebSocket;
  function Wrapped(url, protocols) {
    const ws = protocols === undefined ? new Real(url) : new Real(url, protocols);
    if (/\\/ws\\?/.test(String(url))) window.__brainWs = ws;
    return ws;
  }
  Wrapped.prototype = Real.prototype;
  for (const k of ["CONNECTING", "OPEN", "CLOSING", "CLOSED"]) Wrapped[k] = Real[k];
  window.WebSocket = Wrapped;
  // replay a recorded stream into the page's own handler (test only), looping, at the recorded times
  window.__replay = (frames) => {
    let i = 0, t0 = performance.now(), base = frames[0][0];
    const step = () => {
      const now = (performance.now() - t0) / 1000;
      while (i < frames.length && frames[i][0] - base <= now) {
        const ws = window.__brainWs;
        if (ws && ws.onmessage) ws.onmessage({data: JSON.stringify(frames[i][1])});
        i++;
      }
      if (i >= frames.length) { i = 0; t0 = performance.now(); }
      setTimeout(step, 20);
    };
    step();
  };
  // main-thread ms of the page's own frame() (a global function: rAF(frame) inside it picks up this wrapper)
  window.__frameMs = (ms) => new Promise(res => { const f0 = window.frame; let n = 0, acc = 0;
    window.frame = now => { const a = performance.now(); f0(now); acc += performance.now() - a; n++; };
    setTimeout(() => { window.frame = f0; res({frames: n, js_ms_per_frame: n ? +(acc / n).toFixed(2) : null}); }, ms); });
  window.__fps = (ms) => new Promise(res => { let n = 0; const t0 = performance.now();
    const f = () => { n++; if (performance.now() - t0 < ms) requestAnimationFrame(f); else res(n * 1000 / (performance.now() - t0)); };
    requestAnimationFrame(f); });
})();
"""


def record(seconds=20.0, every_s=1.2):
    """Frames of the real 20k CPU network deciding every `every_s` (wall time simulated), as each viewer gets them."""
    from spiking import frames as F
    from spiking import live as L
    brain = L.LiveBrain(L.N_NEURONS, twin=False, log=lambda *a: None)
    clock = [0.0]
    budget = F.Budget(clock=lambda: clock[0])
    raw = []
    brain.emit = raw.append
    out, i = [], 0
    labels = [["a video about trains", "tokyo parks at night", "bread recipes"], ["the news", "a chess puzzle", "music"],
              ["anime clips", "football scores", "a museum page", "cats"]]
    while clock[0] < seconds:
        raw.clear()
        brain.decide(labels[i % len(labels)], did=f"r{i}")
        brain.idle(50)
        for f in raw:
            g = budget.fit(f)
            if g is not None:
                out.append([round(clock[0], 3), g])
            clock[0] += 0.2
        clock[0] += max(0.0, every_s - 0.2 * len(raw))
        i += 1
    return out


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
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--out", default="docs/screens/neuron_forest")
    ap.add_argument("--chromium", default=os.environ.get("SUB01_CHROMIUM", "/opt/pw-browsers/chromium"))
    ap.add_argument("--cdn-dir", default=None)
    ap.add_argument("--fps-s", type=float, default=6.0)
    args = ap.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)

    print("recording the 20k CPU network's frames ...", flush=True)
    frames = record()
    sizes = [len(json.dumps(f)) for _, f in frames]
    print(f"  {len(frames)} frames over {frames[-1][0]:.1f} s, {sum(sizes) / frames[-1][0]:.0f} B/s per viewer")

    tmp = tempfile.mkdtemp(prefix="n3shots-")
    env = dict(os.environ, BROWSE="0", SUB01_SPIKING_LIVE="0", SUB01_WS_STATS_S="3600")
    log = open(Path(tmp) / "server.log", "w")
    proc = subprocess.Popen([sys.executable, str(ROOT / "live_server.py"), "--demo", "--port", str(args.port),
                             "--host", "127.0.0.1", "--data-dir", tmp], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{args.port}"
    results = {}
    try:
        wait_ready(base, proc)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=args.chromium, args=["--use-gl=angle", "--use-angle=swiftshader",
                                                                             "--enable-unsafe-swiftshader"])

            def page_for(w, h, url, mobile=False):
                ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1,     # software GL: DPR 2 starves the page
                                          is_mobile=mobile, has_touch=mobile)
                pg = ctx.new_page()
                pg.add_init_script(INJECT)
                if args.cdn_dir:
                    cdn = Path(args.cdn_dir)
                    pg.route("**/three.min.js", lambda r: r.fulfill(path=str(cdn / "three.min.js"), content_type="text/javascript"))
                    pg.route("**/OrbitControls.js", lambda r: r.fulfill(path=str(cdn / "OrbitControls.js"), content_type="text/javascript"))
                errors = []
                pg.on("pageerror", lambda e: errors.append(str(e)))
                pg.goto(base + url, wait_until="load")
                pg.wait_for_function("window.__brainWs && window.__brainWs.readyState === 1", timeout=60000)
                pg.wait_for_timeout(2500)
                return ctx, pg, errors

            def toggle(pg):
                pg.evaluate("document.querySelector('#layers button[data-l=\"neurons\"]').click()")

            rects = """() => { const r = s => { const e = document.querySelector(s); if (!e || !e.offsetParent && getComputedStyle(e).position !== 'fixed') return null;
                const b = e.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.top), Math.round(b.right), Math.round(b.bottom)]; };
              const o = {cards: r('#cards'), dock: r('#dock'), layers: r('#layers'), caption: r('#n3cap')};
              o.cards_end_above_dock = !o.cards || !o.dock || getComputedStyle(document.querySelector('#cards')).position !== 'fixed' || o.cards[3] <= o.dock[1];
              o.buttons_fit = [...document.querySelectorAll('#layers button')].filter(b => b.offsetParent).every(b => b.scrollWidth <= b.clientWidth + 1);
              return o; }"""
            for w, h, mobile, tag in ((1920, 1080, False, "1920"), (1280, 800, False, "1280"), (390, 844, True, "390")):
                ctx, pg, errors = page_for(w, h, "/brain", mobile)
                pg.evaluate("controls.autoRotate = false")
                toggle(pg)
                pg.wait_for_function("typeof n3d !== 'undefined' && n3d && n3d.state().cells > 0", timeout=120000)
                pg.wait_for_timeout(2500)
                cap = pg.inner_text("#n3cap")
                btn = pg.inner_text('#layers button[data-l="neurons"]')
                pg.screenshot(timeout=180000, path=str(out / f"brain_{tag}_offline.jpg"), type="jpeg", quality=85)
                results[f"offline_{tag}"] = {"button": btn, "caption": cap, "panel": pg.evaluate(rects),
                                             "forest": pg.evaluate("n3d.state()")}
                pg.evaluate("f => window.__replay(f)", frames)
                pg.wait_for_function("document.querySelector('#n3cap').innerText.includes('live')", timeout=120000)
                pg.wait_for_timeout(2500)
                pg.screenshot(timeout=180000, path=str(out / f"brain_{tag}_neurons.jpg"), type="jpeg", quality=85)
                results[f"live_{tag}"] = {"caption": pg.inner_text("#n3cap"), "panel": pg.evaluate(rects), "errors": errors}
                # the forest alone, closer (the close-up switch held off): fibres and cortex hidden
                for layer in ("fibres", "cortex"):
                    pg.evaluate(f"document.querySelector('#layers button[data-l=\"{layer}\"]').click()")
                pg.evaluate("""() => { n3lodAt = 1e12; camera.position.sub(controls.target).multiplyScalar(0.5).add(controls.target); }""")
                pg.wait_for_timeout(2500)
                pg.screenshot(timeout=180000, path=str(out / f"forest_{tag}_live_zoom.jpg"), type="jpeg", quality=85)
                ctx.close()

            ctx, pg, errors = page_for(300, 225, "/brain?mini&neurons=1")
            pg.screenshot(timeout=180000, path=str(out / "mini_offline.jpg"), type="jpeg", quality=85)
            pg.evaluate("f => window.__replay(f)", frames)
            pg.wait_for_timeout(3000)
            pg.screenshot(timeout=180000, path=str(out / "mini_neurons.jpg"), type="jpeg", quality=85)
            results["mini"] = {"text": pg.inner_text("#n3mini"), "errors": errors}
            ctx.close()

            # FPS on a mid phone profile (CPU x4, 390 px, stream playing). Software WebGL draws the fibres at < 1 frame/s
            # here with or without this layer, so the layer is measured with fibres and cortex hidden: neurons off vs
            # on. Then its main-thread cost alone: a second Neurons3D instance timed on the same stream.
            ctx, pg, errors = page_for(390, 844, "/brain", True)
            cdp = ctx.new_cdp_session(pg)
            for layer in ("fibres", "cortex"):
                pg.evaluate(f"document.querySelector('#layers button[data-l=\"{layer}\"]').click()")
            pg.evaluate("f => window.__replay(f)", frames)
            pg.wait_for_timeout(1500)
            cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
            # FPS from the page's own frame() count (window.__fps' first reading is unreliable under throttle in software GL)
            def fps_js():
                m = pg.evaluate(f"window.__frameMs({int(args.fps_s * 1000)})")
                return {"fps": round(m["frames"] / args.fps_s, 1), "js_ms_per_frame": m["js_ms_per_frame"]}
            off = fps_js()
            toggle(pg)
            pg.wait_for_function("typeof n3d !== 'undefined' && n3d && n3d.state().cells > 0", timeout=120000)
            pg.wait_for_timeout(2000)
            on = fps_js()
            # off screen: the page draws nothing (IntersectionObserver): move the scene out of view, count renders
            hidden = pg.evaluate("""() => new Promise(res => { document.getElementById('scene').style.transform = 'translateY(-3000px)';
              setTimeout(() => { const r = renderer.render.bind(renderer); let k = 0; renderer.render = (...a) => { k++; r(...a); };
                setTimeout(() => { renderer.render = r; document.getElementById('scene').style.transform = '';
                  res({on_screen: onScreen, renders_in_2s: k}); }, 2000); }, 1000); })""")
            js = pg.evaluate("""async f => {
              const nodes = (await (await fetch('brain.json')).json()).nodes;
              const cortex = new Float32Array(await (await fetch('cortex.bin')).arrayBuffer());
              const cortexIdx = new Uint32Array(await (await fetch('cortex_idx.bin')).arrayBuffer());
              const sizes = (await (await fetch('neurons3d.json')).json()).sizes;
              const morph = await (await fetch('neurons_morph.json')).json();
              const t0 = performance.now();
              const n = Neurons3D.create({THREE, scene: new THREE.Scene(), nodes, cortex, cortexIdx, morph, sizes, maxCells: 1500});
              const build = performance.now() - t0;
              n.setVisible(true);
              let tf = 0, tu = 0, k = 0;
              for (let rep = 0; rep < 3; rep++) for (const [, m] of f) {
                let a = performance.now(); n.onFrame(m); tf += performance.now() - a;
                for (let i = 0; i < 12; i++) { a = performance.now(); n.update(performance.now()); tu += performance.now() - a; k++; }
              }
              n.dispose();
              const st = n.state();
              return {cells: st.cells, segments: st.segments, draw_calls: st.drawCalls, build_ms: Math.round(build), per_frame_msg_ms: +(tf / (3 * f.length)).toFixed(3),
                      per_render_ms: +(tu / k).toFixed(4)};
            }""", frames)
            cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
            results["fps_x4_390px_fibres_cortex_hidden"] = {"neurons_off": off, "neurons_on": on}
            results["off_screen_390px"] = hidden
            results["neurons_layer_js_cost_x4"] = js
            results["fps_errors"] = errors
            ctx.close()
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=20)
    print(json.dumps(results, indent=1, ensure_ascii=False))
    (out / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
