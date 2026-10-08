"""Fixed-camera renders of a room GLB for before/after comparisons (#98 G4, the soft goods). Run by hand:

    python shots_soft.py --glb ../web/room/room_clean.glb --tag after --out ../docs/design/room-soft/raw
    python shots_soft.py --glb /tmp/before.glb --tag before --out ../docs/design/room-soft/raw
    python shots_soft.py --compose ../docs/design/room-soft/raw --out ../docs/design/room-soft    # before | after pairs

A small three.js viewer (the same three.js r169 as web/room.html, served from room_build/node_modules/three by a
Playwright route, so no CDN is needed) loads the GLB with the page's lights: the hemisphere light, the sun through the
window with its shadow map, the sky's area light at the window, the ceiling light in the evening, the room environment
map and ACES tone mapping, with the page's values for 13:00 (day) and 21:00 (night, the room light on). Headless
Chromium draws WebGL in software here (SwiftShader): the look is the page's, the speed is not.
"""
import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
THREE = HERE / "node_modules" / "three"

# name: camera position, target, fov, mode (day / night), viewport
SHOTS = [
    ("overview_1280_day", (5.2, 5.0, 6.0), (0, 0.6, 0), 30, "day", (1280, 720)),
    ("overview_1280_night", (5.2, 5.0, 6.0), (0, 0.6, 0), 30, "night", (1280, 720)),
    ("overview_390_day", (5.2, 5.0, 6.0), (0, 0.6, 0), 30, "day", (390, 844)),
    ("overview_390_night", (5.2, 5.0, 6.0), (0, 0.6, 0), 30, "night", (390, 844)),
    ("hanger_day", (-0.95, 1.95, 1.25), (-1.76, 1.78, 0.46), 26, "day", (1280, 720)),
    ("socks_day", (-1.25, 1.86, 0.95), (-1.70, 1.76, 0.52), 24, "day", (1280, 720)),
    ("socks_night", (-1.25, 1.86, 0.95), (-1.70, 1.76, 0.52), 24, "night", (1280, 720)),
    ("towel_day", (-1.35, 1.86, 0.98), (-1.86, 1.76, 0.46), 24, "day", (1280, 720)),
    ("bed_day", (0.7, 1.9, 2.3), (-1.0, 0.85, 0.85), 32, "day", (1280, 720)),
    ("bed_night", (0.7, 1.9, 2.3), (-1.0, 0.85, 0.85), 32, "night", (1280, 720)),
    ("pillow_day", (-0.8, 1.45, 1.55), (-1.58, 0.9, 0.9), 28, "day", (1280, 720)),
    ("duvet_fold_day", (-0.6, 1.5, 1.45), (-1.35, 0.9, 0.55), 28, "day", (1280, 720)),
    ("mattress_day", (-0.2, 0.95, 1.1), (-0.9, 0.7, 0.28), 28, "day", (1280, 720)),
    ("curtain_day", (-0.8, 1.75, 1.45), (-1.85, 1.65, 1.0), 30, "day", (1280, 720)),
    ("curtain_night", (-0.8, 1.75, 1.45), (-1.85, 1.65, 1.0), 30, "night", (1280, 720)),
    ("curtain_a_day", (-0.9, 1.8, -0.2), (-1.85, 1.7, -0.75), 30, "day", (1280, 720)),
    ("rug_day", (1.4, 1.5, 1.3), (0.2, 0.2, 0.1), 32, "day", (1280, 720)),
    ("cushion_day", (2.0, 1.0, 1.75), (1.32, 0.2, 0.98), 26, "day", (1280, 720)),
    ("door_day", (1.3, 1.6, 0.25), (1.45, 1.38, -1.35), 30, "day", (1280, 720)),
    ("door_night", (1.3, 1.6, 0.25), (1.45, 1.38, -1.35), 30, "night", (1280, 720)),
    ("hoodie_day", (1.15, 1.5, -0.35), (1.33, 1.40, -1.33), 28, "day", (1280, 720)),
    ("tote_day", (1.7, 1.55, -0.45), (1.57, 1.42, -1.33), 26, "day", (1280, 720)),
    ("backpack_day", (0.7, 0.75, 1.95), (-0.07, 0.22, 1.24), 26, "day", (1280, 720)),
    ("jeans_day", (1.1, 0.9, 1.95), (0.45, 0.2, 1.38), 26, "day", (1280, 720)),
    ("tee_day", (0.1, 1.5, 2.1), (-0.58, 0.9, 1.3), 26, "day", (1280, 720)),
]

VIEWER = r"""<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;background:#000;overflow:hidden}canvas{display:block}</style>
<script type="importmap">{"imports":{"three":"https://cdn.jsdelivr.net/npm/three@0.169.0/build/three.module.js","three/addons/":"https://cdn.jsdelivr.net/npm/three@0.169.0/examples/jsm/"}}</script>
</head><body><script type="module">
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { RectAreaLightUniformsLib } from "three/addons/lights/RectAreaLightUniformsLib.js";
const W = innerWidth, H = innerHeight;
const renderer = new THREE.WebGLRenderer({antialias:true, preserveDrawingBuffer:true});
renderer.setSize(W, H); renderer.setPixelRatio(1); renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace; renderer.toneMapping = THREE.ACESFilmicToneMapping; document.body.appendChild(renderer.domElement);
const scene = new THREE.Scene(); scene.background = new THREE.Color(0x0b0b10);
const pmrem = new THREE.PMREMGenerator(renderer); scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture; scene.environmentIntensity = 0.35;
const camera = new THREE.PerspectiveCamera(30, W / H, 0.02, 200);
const hemi = new THREE.HemisphereLight(0xfff1dd, 0x1a1a24, 0.6); scene.add(hemi);
const sun = new THREE.DirectionalLight(0xffe2c0, 1.0); sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048); sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.02;
Object.assign(sun.shadow.camera, {left:-3, right:3, top:3, bottom:-3, near:0.5, far:20}); scene.add(sun, sun.target);
const ceiling = new THREE.PointLight(0xffd9a8, 0, 7, 1.6); ceiling.position.set(0.1, 2.3, 0.1); scene.add(ceiling);
RectAreaLightUniformsLib.init(); const skyLight = new THREE.RectAreaLight(0xdfe8ff, 0, 1.5, 0.8); scene.add(skyLight);
const cSunDay = new THREE.Color(0xfff0dc), cMoon = new THREE.Color(0x7d93d8), cNight = new THREE.Color(0.22, 0.27, 0.50), cSkyDay = new THREE.Color(0xe4ecff);
const mats = []; let win = null, sky = null;
function mergeBoxes(list){ const pos = [], idx = [];
  for (const [[x0, x1], [y0, y1], [z0, z1]] of list) { const g = new THREE.BoxGeometry(x1 - x0, y1 - y0, z1 - z0).translate((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2);
    const base = pos.length / 3; pos.push(...g.attributes.position.array); idx.push(...g.index.array.map(i => i + base)); }
  const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3)); g.setIndex(idx); return g; }
const shell = new THREE.Mesh(mergeBoxes([[[-2.05, 2.05], [2.39, 2.47], [-1.65, 1.65]], [[-2.05, 2.05], [0, 2.47], [1.6, 1.66]], [[2.0, 2.06], [0, 2.47], [-1.65, 1.65]]]),
  new THREE.MeshBasicMaterial({colorWrite:false, depthWrite:false})); shell.castShadow = true; scene.add(shell);
const loader = new GLTFLoader(); loader.setMeshoptDecoder(MeshoptDecoder);
window.ready = false;
loader.load(new URLSearchParams(location.search).get("glb"), g => {
  scene.add(g.scene); g.scene.updateMatrixWorld(true);
  g.scene.traverse(o => { if (!o.isMesh) return; const lampPart = /desk_lamp/i.test(o.name) || /desk_lamp/i.test(o.parent && o.parent.name || "");
    o.receiveShadow = true; o.castShadow = !lampPart; if (!mats.includes(o.material)) mats.push(o.material); o.material.envMap = scene.environment;
    if (new URLSearchParams(location.search).has("noao")) { o.material.aoMap = null; o.material.needsUpdate = true; } });
  const w = g.scene.getObjectByName("SURF_window"); const p = new THREE.Vector3(); w.getWorldPosition(p);
  win = {c:p.toArray(), w:w.userData.w, h:w.userData.h};
  skyLight.width = win.w; skyLight.height = win.h; skyLight.position.set(p.x + 0.12, p.y, p.z); skyLight.lookAt(p.x + 1, p.y, p.z);
  sky = new THREE.Mesh(new THREE.PlaneGeometry(win.w + 0.4, win.h + 0.4), new THREE.MeshBasicMaterial({color:0xbfd4ff}));
  sky.position.set(p.x - 0.03, p.y, p.z); sky.rotation.y = Math.PI / 2; scene.add(sky);
  window.ready = true;
});
window.shoot = (mode, pos, target, fov) => {
  const day = mode === "day" ? 1 : 0, roomOn = 1 - day, sunEl = day ? 0.95 : -0.7;
  sun.color.copy(cMoon).lerp(cSunDay, day); sun.intensity = 0.15 + 3.2 * day;
  sun.position.set(win.c[0] - 3.5, win.c[1] + 1.2 + 2.5 * Math.max(0, sunEl), win.c[2] + 1.0); sun.target.position.set(0.2, 0.3, 0.1);
  skyLight.color.copy(cMoon).lerp(cSkyDay, day); skyLight.intensity = 0.3 + 7.0 * day;
  hemi.intensity = 0.08 + 0.7 * day + 0.22 * roomOn; hemi.color.setHSL(0.085, 0.45, 0.58 + 0.22 * day); hemi.color.lerp(cNight, 1 - Math.max(day, roomOn));
  hemi.groundColor.setRGB(0.20, 0.13, 0.08).lerp(cNight, 1 - Math.max(day, roomOn));
  ceiling.intensity = 4.2 * roomOn; renderer.toneMappingExposure = 0.74 + 0.28 * day + 0.1 * roomOn;
  const env = 0.04 + 0.5 * day + 0.12 * roomOn; for (const m of mats) m.envMapIntensity = env;
  sky.material.color.set(day ? 0xbfd4ff : 0x151a33);
  camera.position.set(...pos); camera.lookAt(...target); camera.fov = fov; camera.updateProjectionMatrix();
  renderer.render(scene, camera); renderer.render(scene, camera); return true;
};
</script></body></html>"""


def route_three(page):
    import mimetypes
    def handler(route):
        url = route.request.url
        if "three@0.169.0/build/" in url: f = THREE / "build" / url.split("/build/")[1]
        elif "three@0.169.0/examples/jsm/" in url: f = THREE / "examples" / "jsm" / url.split("/examples/jsm/")[1]
        else: return route.abort()
        route.fulfill(path=str(f), content_type=mimetypes.guess_type(str(f))[0] or "text/javascript")
    page.route("https://cdn.jsdelivr.net/**", handler)


def render(glb, tag, out, chromium, only=None):
    from playwright.sync_api import sync_playwright
    glb = Path(glb).resolve(); out = Path(out); out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        by_size = {}
        for s in SHOTS:
            if only and not any(k in s[0] for k in only): continue
            by_size.setdefault(s[5], []).append(s)
        for (w, h), shots in by_size.items():
            ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1)
            pg = ctx.new_page(); route_three(pg)
            pg.route("**/view.html*", lambda r: r.fulfill(body=VIEWER, content_type="text/html"))
            pg.route("**/model.glb", lambda r: r.fulfill(path=str(glb), content_type="model/gltf-binary"))
            pg.goto("http://room.local/view.html?glb=model.glb" + ("&noao" if os.environ.get("SHOTS_NOAO") else "")); pg.wait_for_function("window.ready === true", timeout=120000)
            for name, pos, target, fov, mode, _ in shots:
                pg.evaluate(f"shoot({json.dumps(mode)}, {json.dumps(pos)}, {json.dumps(target)}, {fov})")
                pg.wait_for_timeout(300)
                pg.screenshot(path=str(out / f"{name}_{tag}.jpg"), type="jpeg", quality=86)
                print("shot", name, tag)
            ctx.close()
        browser.close()


def compose(raw, out):
    """before | after side by side, labelled, one JPEG per shot"""
    from PIL import Image, ImageDraw
    raw, out = Path(raw), Path(out); out.mkdir(parents=True, exist_ok=True)
    for s in SHOTS:
        name = s[0]; a, b = raw / f"{name}_before.jpg", raw / f"{name}_after.jpg"
        if not (a.exists() and b.exists()): continue
        A, Bm = Image.open(a), Image.open(b); gap = 8
        im = Image.new("RGB", (A.width + Bm.width + gap, max(A.height, Bm.height) + 22), "#111")
        im.paste(A, (0, 22)); im.paste(Bm, (A.width + gap, 22)); d = ImageDraw.Draw(im)
        d.text((6, 5), f"{name}  before", fill="#ddd"); d.text((A.width + gap + 6, 5), "after", fill="#ddd")
        im.save(out / f"{name}.jpg", quality=86); print("composed", name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glb"); ap.add_argument("--tag", default="after"); ap.add_argument("--out", default=str(HERE.parent / "docs" / "design" / "room-soft" / "raw"))
    ap.add_argument("--compose", help="raw dir with *_before.jpg and *_after.jpg: write the pairs into --out")
    ap.add_argument("--only", nargs="*", help="shot name substrings")
    ap.add_argument("--chromium", default=os.environ.get("SUB01_CHROMIUM", "/opt/pw-browsers/chromium"))
    a = ap.parse_args()
    if a.compose: compose(a.compose, a.out); return
    if not a.glb: sys.exit("--glb or --compose")
    render(a.glb, a.tag, a.out, a.chromium, a.only)


if __name__ == "__main__":
    main()
