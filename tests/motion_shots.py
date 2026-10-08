"""Old vs new motion sheet for the room's character (#98 G3). Run by hand (no `test_` prefix):

    python tests/motion_shots.py --out docs/screens/motion

Serves web/ statically (no live server: the page runs with ?debug&nolive and is driven through its debug API), opens
room.html in headless Chromium at 1280 and 390 px, and for each situation (at the desk, eating, standing, at the
window, walking, at the door, on the phone in bed, asleep) takes frames per clip source (--modes): `old` (the first
Meshy clips: ?moves=old&motion=old), `ual` (#76's boy_moves.glb where it has a clip, the desk and the walk: ?motion=ual)
and `ardy` (the ARDY clips, the default), the procedural layer of web/room/boy_motion.js on top of each; `before` is
the page with the layer blocked (the hook's import fails) and the first clips: as it was before #80 and #98. Each frame
is checked in the page: the lowest foot or toe sole against the floor, NaN in any bone. Writes <out>/sheet_1280.jpg,
sheet_390.jpg (one row per mode and frame, a column per situation), the single frames, and results.json. The CDN
scripts (three.js, leaflet) are served from room_build's node_modules (the sandbox may have no route to the CDNs);
Chromium renders WebGL in software.
"""
import argparse
import http.server
import json
import os
import socketserver
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NM = ROOT / "room_build" / "node_modules"
SITUATIONS = [("desk", "research", {}), ("eat", "eat", {"eating": "ramen", "food": 1}), ("stand", "idle_home", {"place": "room"}),
              ("window", "window", {}), ("walk", "research", {}),           # walk: from the door to the desk, shot mid-stride
              ("door", "idle_home", {"place": "door_in"}), ("phone_bed", "phone", {}), ("sleep", "sleep", {})]
# the page URL per clip source (see the docstring); None blocks the motion layer's module
MODES = {"before": ("moves=old", False), "old": ("moves=old&motion=old", True), "ual": ("motion=ual", True), "ardy": ("", True)}
# measured in the page: the lowest sole, NaN, the frame time of animate()
PROBE = """() => {
  const b = window.boy, bones = window.bones; if (!b) return null; b.updateMatrixWorld(true);
  const v = new THREE.Vector3(); let low = 9, nan = 0;
  for (const n of ["LeftFoot", "RightFoot", "LeftToeBase", "RightToeBase"]) { const o = bones[n]; if (!o) continue; o.getWorldPosition(v);
    low = Math.min(low, v.y - (n.endsWith("Foot") ? 0.125 : 0.037)); }
  for (const n in bones) { const q = bones[n].quaternion; if (![q.x, q.y, q.z, q.w].every(Number.isFinite)) nan++; }
  let armLow = 9; for (const n of ["LeftForeArm", "LeftHand", "RightForeArm", "RightHand"]) { const o = bones[n]; if (!o) continue; o.getWorldPosition(v);
    if (v.x > -1.9 && v.x < -0.32 && v.z > -1.44 && v.z < -0.74) armLow = Math.min(armLow, v.y - 0.97); }   // over the desk: height above its top
  const legs = {}; for (const n of ["Hips", "LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToeBase", "RightFoot", "RightToeBase"]) if (bones[n]) { bones[n].getWorldPosition(v); legs[n] = +v.y.toFixed(3); }
  const rest = window.motion && window.motion.rest ? {ankle: window.motion.rest.ankle, toe: window.motion.rest.toe, p: Object.fromEntries(Object.entries(window.motion.rest.p || {}).map(([k, v]) => [k, v.toArray().map(x => +x.toFixed(3))]))} : null;
  // which desk-zone geometry the hand and foot vertices sit inside (the visual QA's column test, re-done here)
  let deskHits = null;
  try {
    const st = window.room.getObjectByName("room_static"); const meshes = []; st.traverse(m => { if (m.isMesh) meshes.push(m); });
    const sides = meshes.map(m => m.material.side); meshes.forEach(m => { m.material.side = THREE.DoubleSide; });
    const ray = new THREE.Raycaster(); let sm; b.traverse(o => { if (o.isSkinnedMesh) sm = o; });
    const P = sm.geometry.attributes.position, I = sm.geometry.attributes.skinIndex, W = sm.geometry.attributes.skinWeight, hits = {}, lows = {};
    for (let i = 0; i < P.count; i += 2) { sm.getVertexPosition(i, v); v.applyMatrix4(sm.matrixWorld);
      let bi = 0, bw = 0; for (let k = 0; k < 4; k++) if (W.getComponent(i, k) > bw) { bw = W.getComponent(i, k); bi = I.getComponent(i, k); }
      const bn = sm.skeleton.bones[bi].name; if (!/Hand|Foot|ToeBase/.test(bn)) continue;
      if (!lows[bn] || v.y < lows[bn][1]) lows[bn] = v.toArray().map(x => +x.toFixed(3));
      if (v.x < -1.92 || v.x > -0.30 || v.z < -1.47 || v.z > -0.72) continue;
      ray.set(new THREE.Vector3(v.x, -0.5, v.z), new THREE.Vector3(0, 1, 0)); const ys = [];
      for (const h of ray.intersectObjects(meshes, false)) if (!ys.length || h.point.y - ys[ys.length - 1] > 0.002) ys.push(+h.point.y.toFixed(3));
      for (let j = 0; j + 1 < ys.length; j += 2) if (v.y > ys[j] + 0.01 && v.y < ys[j + 1] - 0.01) { const key = bn + " in " + ys[j] + ".." + ys[j + 1]; hits[key] = (hits[key] || 0) + 1; }
    }
    meshes.forEach((m, i) => { m.material.side = sides[i]; }); deskHits = {hits, lows};
  } catch (e) { deskHits = String(e); }
  const tv = {}; for (const n of ['Hips','Spine02','Spine','neck','Head','LeftArm','RightArm','LeftUpLeg','LeftLeg']) if (bones[n]) { bones[n].getWorldPosition(v); tv[n] = v.toArray().map(x => +x.toFixed(2)); }
  const torsoVec = tv; let pen = null; try { pen = window.penetration(2, true); } catch (e) { pen = String(e); }
  return {deskHits, torsoVec, ry: +b.rotation.y.toFixed(2), pen, lowest_sole: +(low - 0.16).toFixed(3), arm_over_desk: armLow === 9 ? null : +armLow.toFixed(3), nan, legs, rest, root: +b.position.y.toFixed(3), ctx: window.motion ? "on" : "off", clip: window.current && window.current.getClip().name,
    swapped: window.motion ? Object.keys(window.motion.swapped) : [], log: window.motion ? window.motion.log : []};
}"""


# the camera close to him: a three-quarter view from his front-left, the whole body in frame
FRAME = """() => { const b = window.boy; if (!b) return; const t = new THREE.Vector3(); b.getWorldPosition(t); t.y += 0.8;
  const tall = [[-0.12, 0.32, -1.45, -1.17], [0.45, 0.93, -1.45, -0.97], [-1.9, -1.84, -0.62, 0.9]];   // shelf, fridge, the window wall: never inside them
  const inTall = p => tall.some(([x0, x1, z0, z1]) => p.x > x0 - 0.15 && p.x < x1 + 0.15 && p.z > z0 - 0.15 && p.z < z1 + 0.15);
  const r = b.rotation.y, box = p => { p.x = Math.min(1.85, Math.max(-1.75, p.x)); p.z = Math.min(1.5, Math.max(-1.3, p.z)); p.y = Math.min(2.3, p.y); return p; };
  // the whole body in frame: of eight directions around him (his front half first), the one with most room inside the walls
  // and nothing solid between the camera and his head or hips (a ray against the room; his own meshes and glass ignored)
  const ray = new THREE.Raycaster(), ofBoy = o => { for (; o; o = o.parent) if (o === b) return true; return false; };
  const clear = (c, p) => { const d = p.clone().sub(c), len = d.length(); ray.set(c, d.normalize()); ray.far = len - 0.35;
    const h = ray.intersectObjects(scene.children, true).find(h => h.object.visible && !ofBoy(h.object) && !(h.object.material && h.object.material.transparent && h.object.material.opacity < 0.6));
    return h ? h.distance / len : 1; };
  // eight directions at four distances: the longest clear line of sight wins (the clear part of the way to him), his
  // front half preferred; near a wall (the door, the window) that means a closer camera rather than one behind furniture
  let best = null; const tried = [];
  for (const a of [0.7, -0.7, 1.2, -1.2, 0.2, -0.2, 1.8, -1.8, 2.5, -2.5, 3.1]) for (const s of [2.7, 2.1, 1.6, 1.2]) for (const h of [0.6, 0.1]) {   // the last three: from behind (facing a wall)
    const d = new THREE.Vector3(Math.sin(r + a), 0, Math.cos(r + a));
    const c = box(t.clone().addScaledVector(d, s).add(new THREE.Vector3(0, h * s / 2.7, 0)));
    const far = c.distanceTo(t), open = Math.min(clear(c, t), clear(c, t.clone().add(new THREE.Vector3(0, -0.6, 0))));   // head and hips (a knee ray trips on low props: the plant at the sill)
    const dist = far * open - (Math.abs(a) > 1.5 ? 0.4 : 0) - (inTall(c) ? 5 : 0);
    tried.push({a, s, h, far: +far.toFixed(2), open: +open.toFixed(2), score: +dist.toFixed(2)});
    if (!best || dist > best.dist) best = {c, dist, a}; }
  camera.fov = 46; camera.updateProjectionMatrix(); camera.position.copy(best.c); controls.target.copy(t); controls.update(); renderer.render(scene, camera);
  return {a: best.a, ry: +r.toFixed(2), at: t.toArray().map(v => +v.toFixed(2)), tried}; }"""


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
    ap.add_argument("--port", type=int, default=8793)
    ap.add_argument("--out", default="docs/screens/motion")
    ap.add_argument("--chromium", default=os.environ.get("SUB01_CHROMIUM", "/opt/pw-browsers/chromium"))
    ap.add_argument("--widths", default="1280,390")
    ap.add_argument("--frames", type=int, default=3, help="frames per situation, 1.2 s apart")
    ap.add_argument("--modes", default="old,ual,ardy", help=f"clip sources, of {', '.join(MODES)}")
    ap.add_argument("--only", default="", help="comma-separated situations")
    ap.add_argument("--prep", default="", help="JavaScript run in the page after each act() (debug)")
    ap.add_argument("--settle", type=int, default=120, help="frames (30 fps) after act() before the first shot")
    args = ap.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    srv = serve(args.port)
    base = f"http://127.0.0.1:{args.port}"
    from playwright.sync_api import sync_playwright
    results = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=args.chromium, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
            for w in [int(x) for x in args.widths.split(",")]:
                h = 720 if w > 900 else 844
                for mode in args.modes.split(","):
                    ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1, is_mobile=w < 900, has_touch=w < 900)
                    pg = ctx.new_page()
                    errors = []
                    pg.on("pageerror", lambda e: errors.append(str(e)))

                    def cdn(route, request):
                        url = request.url
                        if "three@0.169.0/" in url:
                            path = NM / "three" / url.split("three@0.169.0/", 1)[1]
                        elif "leaflet@1.9.4/dist/" in url:
                            path = NM / "leaflet" / "dist" / url.split("dist/", 1)[1]
                        else:
                            return route.abort()
                        ct = "text/javascript" if path.suffix == ".js" else "text/css" if path.suffix == ".css" else "application/octet-stream"
                        return route.fulfill(path=str(path), content_type=ct) if path.exists() else route.abort()
                    pg.route("**/cdn.jsdelivr.net/**", cdn)
                    pg.route("**/unpkg.com/**", cdn)
                    pg.route("**/api/**", lambda r: r.fulfill(status=404, body=""))
                    pg.route("**/tokyo_*.json", lambda r: r.fulfill(status=404, body=""))
                    query, layer = MODES[mode]
                    if not layer:
                        pg.route("**/room/boy_motion.js", lambda r: r.abort())
                    pg.goto(f"{base}/room.html?debug&nolive&hour=14" + (f"&{query}" if query else ""), wait_until="load")
                    pg.wait_for_function("window.boy && window.room && window.actions && window.actions.walk && window.actions.sleep", timeout=120000)
                    pg.wait_for_timeout(1500)
                    if layer:                                      # the layer's clips are in (after boy_moves.glb)
                        pg.wait_for_function("window.motion && window.motion.ready", timeout=60000)
                    print(mode, w, "clips:", pg.evaluate("Object.fromEntries(Object.entries(actions).map(([k, a]) => [k, a.getClip().name]))"), flush=True)
                    pg.evaluate("() => { window.FREEZE = true; settle(); for (const id of ['top', 'side', 'dock', 'corner', 'vignette']) document.getElementById(id).style.display = 'none'; }")
                    for key, activity, extra in SITUATIONS:
                        if args.only and key not in args.only.split(","):
                            continue
                        life = {"activity": activity, "place": "room", "vitals": {"resp_per_min": 14}, **extra}
                        if key == "walk":                          # snapped to the door; a research tick (live(), not act()) plans the walk to the desk
                            pg.evaluate("(l) => { act('idle_home', {...l, activity: 'idle_home', place: 'door_in'}); sim(1 / 30, 60); }", life)
                            pg.evaluate("(l) => { live(l.activity, l); " + args.prep + " for (let i = 0; i < 400; i++) { animate_(0.1); "   # steps without a render
                                        "const p = pose(); if (p.step && p.step.k === 'walk') break; } sim(1 / 30, 24); }", life)
                        else:
                            pg.evaluate("(l) => { act(l.activity, l); " + args.prep + f" sim(1 / 30, {args.settle}); }}", life)
                        if key == "phone_bed":
                            pg.evaluate("() => { sim(1 / 30, 1500); }")   # time to lie back
                        for k in range(args.frames):
                            if k:
                                pg.evaluate("() => { sim(1 / 30, 36); }")
                            if not pg.evaluate("() => { const b = window.boy; return b && b.visible; }"):
                                continue
                            cam = pg.evaluate(FRAME)
                            probe = pg.evaluate(PROBE)
                            if probe is not None:
                                probe["camera"] = cam
                            name = f"{key}_{mode}_{w}_{k}.jpg"
                            try:
                                pg.screenshot(path=str(out / name), type="jpeg", quality=80, timeout=90000)
                            except Exception as e:  # noqa: BLE001
                                print("screenshot failed", name, str(e)[:80], flush=True)
                            results[name] = {**(probe or {}), "errors": errors[:3]}
                            print(name, probe, flush=True)
                    ctx.close()
            browser.close()
    finally:
        srv.shutdown()
    (out / "results.json").write_text(json.dumps(results, indent=1))
    sheet(out, results, [int(x) for x in args.widths.split(",")], args.modes.split(","))


def sheet(out, results, widths, modes=("old", "ual", "ardy")):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("no PIL: no sheet")
        return
    for w in widths:
        cols = [k for k, _, _ in SITUATIONS if any((out / f"{k}_{m}_{w}_0.jpg").exists() for m in modes)]
        rows = [(m, k) for k in (0, 2) for m in modes]              # the modes side by side per frame
        tw = 320 if w > 900 else 160
        imgs = {}
        for (mode, k) in rows:
            for c in cols:
                f = out / f"{c}_{mode}_{w}_{k}.jpg"
                if f.exists():
                    im = Image.open(f)
                    imgs[(mode, k, c)] = im.resize((tw, int(im.height * tw / im.width)))
        if not imgs:
            continue
        th = max(im.height for im in imgs.values())
        S = Image.new("RGB", (tw * len(cols), (th + 18) * len(rows) + 20), (10, 10, 12))
        d = ImageDraw.Draw(S)
        for j, c in enumerate(cols):
            d.text((j * tw + 6, 4), c, fill=(220, 220, 230))
        for i, (mode, k) in enumerate(rows):
            y = 20 + i * (th + 18)
            d.text((6, y + 2), f"{mode} (frame {k})", fill=(255, 154, 60) if mode == "ardy" else (160, 160, 175))
            for j, c in enumerate(cols):
                im = imgs.get((mode, k, c))
                if im:
                    S.paste(im, (j * tw, y + 16))
        S.save(out / f"sheet_{w}.jpg", quality=82)
        print("wrote", out / f"sheet_{w}.jpg")


if __name__ == "__main__":
    main()
