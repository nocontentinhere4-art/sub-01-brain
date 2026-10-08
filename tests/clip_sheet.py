"""Contact sheet of animation clips on the character rig (#98 G3): boy.glb alone on a floor grid, each clip's frames
side by side, so a retargeted ARDY clip (web/room/boy_m_*.glb) can be judged next to the Meshy ones. Run by hand:

    python tests/clip_sheet.py --clips boy_m_type,boy_m_walk,boy_walk --out docs/screens/motion/clips

Serves web/ statically; three.js comes from room_build/node_modules (no CDN needed); headless Chromium, software GL."""
import argparse
import http.server
import os
import socketserver
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NM = ROOT / "room_build" / "node_modules"
HTML = """<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;background:#1a1b20}</style>
<script type="importmap">{"imports":{"three":"https://cdn.jsdelivr.net/npm/three@0.169.0/build/three.module.js","three/addons/":"https://cdn.jsdelivr.net/npm/three@0.169.0/examples/jsm/"}}</script>
</head><body><script type="module">
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";
const W = innerWidth, H = innerHeight;
const renderer = new THREE.WebGLRenderer({antialias:true}); renderer.setSize(W, H); renderer.outputColorSpace = THREE.SRGBColorSpace; document.body.appendChild(renderer.domElement);
const scene = new THREE.Scene(); scene.background = new THREE.Color(0x1a1b20);
scene.add(new THREE.HemisphereLight(0xffffff, 0x404060, 1.4)); const sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.position.set(2, 4, 3); scene.add(sun);
scene.add(new THREE.GridHelper(4, 16, 0x555566, 0x33343c));
const floor = new THREE.Mesh(new THREE.PlaneGeometry(4, 4), new THREE.MeshStandardMaterial({color:0x2a2b32})); floor.rotation.x = -Math.PI / 2; floor.position.y = -0.001; scene.add(floor);
const camera = new THREE.PerspectiveCamera(32, W / H, 0.05, 50);
const loader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder);
const load = u => new Promise((ok, no) => loader.load(u, ok, undefined, no));
const g = await load("room/boy.glb"); const boy = g.scene; scene.add(boy);
boy.traverse(o => { if (o.isMesh) { o.frustumCulled = false; o.material.emissive.setRGB(0, 0, 0); } });
const bones = {}; boy.traverse(o => { if (o.isBone) bones[o.name] = o; });
const mixer = new THREE.AnimationMixer(boy);
window.clipInfo = null;
window.showClip = async (file) => {
  const a = await load("room/" + file + ".glb"); const clip = a.animations[0];
  mixer.stopAllAction(); const act = mixer.clipAction(clip); act.reset().play(); mixer.update(0);
  window.clipInfo = {name: clip.name, duration: clip.duration, tracks: clip.tracks.length};
  return window.clipInfo;
};
window.atTime = (t, view) => {
  mixer.setTime(t); boy.updateMatrixWorld(true);
  const hips = new THREE.Vector3(); bones.Hips.getWorldPosition(hips);
  const c = new THREE.Vector3(hips.x, 0.9, hips.z);
  const az = view === "side" ? Math.PI / 2 : view === "front" ? 0 : 0.6;
  camera.position.set(c.x + Math.sin(az) * 3.4, 1.55, c.z + Math.cos(az) * 3.4); camera.lookAt(c);
  renderer.render(scene, camera);
  const v = new THREE.Vector3(); let low = 9;
  for (const n of ["LeftFoot", "RightFoot", "LeftToeBase", "RightToeBase"]) { bones[n].getWorldPosition(v); low = Math.min(low, v.y - (n.endsWith("Foot") ? 0.125 : 0.037)); }
  return {hips: hips.toArray().map(x => +x.toFixed(3)), lowest_sole: +low.toFixed(3)};
};
window.ready = true;
</script></body></html>"""


def serve(port):
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(ROOT / "web"), **k)

        def log_message(self, *a):
            pass
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", port), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", required=True, help="comma-separated file stems in web/room/")
    ap.add_argument("--out", default="docs/screens/motion/clips")
    ap.add_argument("--port", type=int, default=8794)
    ap.add_argument("--n", type=int, default=8, help="frames per clip")
    ap.add_argument("--view", default="3q", help="3q | side | front")
    ap.add_argument("--chromium", default=os.environ.get("SUB01_CHROMIUM", "/opt/pw-browsers/chromium"))
    args = ap.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    srv = serve(args.port)
    from PIL import Image, ImageDraw
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=args.chromium, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
            pg = browser.new_page(viewport={"width": 300, "height": 420})
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))

            def cdn(route, request):
                url = request.url
                if "three@0.169.0/" in url:
                    path = NM / "three" / url.split("three@0.169.0/", 1)[1]
                    return route.fulfill(path=str(path), content_type="text/javascript") if path.exists() else route.abort()
                return route.abort()
            pg.route("**/cdn.jsdelivr.net/**", cdn)
            pg.route("**/__sheet.html", lambda r: r.fulfill(body=HTML, content_type="text/html"))
            pg.goto(f"http://127.0.0.1:{args.port}/__sheet.html")
            pg.wait_for_function("window.ready", timeout=120000)
            for stem in args.clips.split(","):
                info = pg.evaluate("f => showClip(f)", stem)
                frames, notes = [], []
                for k in range(args.n):
                    t = info["duration"] * k / args.n
                    r = pg.evaluate("([t, v]) => atTime(t, v)", [t, args.view])
                    f = out / f"_{Path(stem).name}_{k}.png"
                    pg.screenshot(path=str(f))
                    frames.append(Image.open(f))
                    notes.append(f"t={t:.2f} sole={r['lowest_sole']:+.3f}")
                S = Image.new("RGB", (300 * len(frames), 420 + 30), (20, 20, 24))
                d = ImageDraw.Draw(S)
                d.text((6, 6), f"{stem}: {info['name']} {info['duration']:.2f} s, {info['tracks']} tracks  (lowest sole per frame)", fill=(230, 230, 240))
                for k, im in enumerate(frames):
                    S.paste(im, (k * 300, 30))
                    d.text((k * 300 + 6, 32), notes[k], fill=(255, 154, 60))
                    (out / f"_{Path(stem).name}_{k}.png").unlink()
                S.save(out / f"{Path(stem).name}.jpg", quality=80)
                print(stem, info, " ".join(notes), errors[:2], flush=True)
            browser.close()
    finally:
        srv.shutdown()


if __name__ == "__main__":
    main()
