# The right hand on the room mouse, in the page (run from the repo root): mouse mode, desk_14 scene.
#   python3 tools/motion/grip_probe.py points            hand joints in the mouse's frame (cm), height over the shell under each
#   python3 tools/motion/grip_probe.py shots OUT TAG     top-down over the mouse, low from his right, from his left; plus skin vs shell/pad
#   python3 tools/motion/grip_probe.py contact OUT.json  hand skin inside the shell / below the pad, every 0.25 s for 15 s
import sys
mode = sys.argv.pop(1)
if mode == 'points':
    # the right hand vs the room mouse in mouse mode: points in the mouse's frame (fwd = his forward, lat = his right, cm), height over the shell top under each
    import json, sys
    sys.path.insert(0, ".")
    from pathlib import Path
    from tests.visual.harness import Harness, CHROMIUM
    from tests.visual.fake_server import Server
    JS = """() => { for (let i = 0; i < 150; i++) animate_(1/30); boy.updateMatrixWorld(true);
      const V = (...a) => new THREE.Vector3(...a), wp = n => { const o = boy.getObjectByName(n); return o ? o.getWorldPosition(V()) : null; };
      const ms = scene.getObjectByName("mouse"); ms.updateMatrixWorld(true); const bb = new THREE.Box3().setFromObject(ms), c = bb.getCenter(V());
      const f = V().set(Math.sin(boy.rotation.y), 0, Math.cos(boy.rotation.y)), rt = V().set(-f.z, 0, f.x);
      const ray = new THREE.Raycaster(); const surf = p => { ray.set(V().set(p.x, p.y + 0.3, p.z), V(0, -1, 0)); ray.far = 0.6; const x = ray.intersectObject(ms, true)[0]; return x ? x.point.y : null; };
      const rel = p => { const d = p.clone().sub(c); const s = surf(p); return {fwd: +(d.dot(f) * 100).toFixed(1), lat: +(d.dot(rt) * 100).toFixed(1), up: +((p.y - bb.min.y) * 100).toFixed(1), overShell: s == null ? null : +((p.y - s) * 100).toFixed(1)}; };
      const o = {mode: mh.M.mode, mouse: {len: +(bb.getSize(V()).dot(V(Math.abs(f.x), 0, Math.abs(f.z))) * 100).toFixed(1), size: bb.getSize(V()).toArray().map(x => +(x * 100).toFixed(1)), top: +((bb.max.y - bb.min.y) * 100).toFixed(1)}};
      const hand = wp("RightHand"), kn = wp("finger3-1R"); o.wrist = rel(hand); o.palm = rel(hand.clone().lerp(kn, 0.6));
      for (let fi = 1; fi <= 5; fi++) for (let j = 1; j <= 3; j++) { const p = wp(`finger${fi}-${j}R`); if (p) o[`f${fi}${j}`] = rel(p); }
      return o; }"""
    with Server() as server:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            h = Harness(Path("/tmp/mp"), log=lambda *x: None, cdn_cache=Path("tests/visual/.cdn_cache")); h.server = server; h.base = server.base
            h.browser = p.chromium.launch(executable_path=CHROMIUM, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
            ctx, pg, st = h.open("1280"); h.goto_scene(pg, "desk", 14); pg.wait_for_function("() => !window.mh || window.mh.ready", timeout=180000)
            pg.evaluate("() => act('chart', {screen: {device: 'desk', id: 'c1', kind: 'page'}})")
            o = pg.evaluate(JS); print(json.dumps({k: o[k] for k in ("mode", "mouse")}))
            for k, v in o.items():
                if k not in ("mode", "mouse"): print(k, v)
elif mode == 'shots':
    # the right hand on the room mouse: a top-down over the mouse and a low view from his right, plus the hand's skin vs the shell and the pad
    import json, sys
    sys.path.insert(0, ".")
    from pathlib import Path
    from tests.visual.harness import Harness, CHROMIUM
    from tests.visual.fake_server import Server
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True); tag = sys.argv[2]; frames = int(sys.argv[3]) if len(sys.argv) > 3 else 150
    CAM = """(k) => { boy.updateMatrixWorld(true); const V = (...a) => new THREE.Vector3(...a); const ms = scene.getObjectByName("mouse"), c = ms.getWorldPosition(V());
      const f = V(Math.sin(boy.rotation.y), 0, Math.cos(boy.rotation.y)), rt = V(-f.z, 0, f.x);
      let pos, at = c.clone().addScaledVector(f, -0.02).setY(c.y + 0.02);
      if (k === "top") pos = at.clone().addScaledVector(f, 0.10).setY(c.y + 0.36);
      else if (k === "low") pos = at.clone().addScaledVector(rt, 0.30).addScaledVector(f, 0.06).setY(c.y + 0.07);
      else pos = at.clone().addScaledVector(rt, -0.28).addScaledVector(f, 0.10).setY(c.y + 0.09);
      camera.position.copy(pos); camera.up.set(0, 1, 0); if (k === "top") camera.up.copy(f); controls.target.copy(at); controls.update(); __qa.render(); return pos.toArray(); }"""
    PEN = """() => { boy.updateMatrixWorld(true); const V = (...a) => new THREE.Vector3(...a); const ms = scene.getObjectByName("mouse"); ms.updateMatrixWorld(true);
      const ray = new THREE.Raycaster(), dn = V(0, -1, 0), up = V(0, 1, 0); const pad = ms.getWorldPosition(V()).y; const bb = new THREE.Box3().setFromObject(ms); bb.expandByScalar(0.01);
      let n = 0, inShell = 0, maxIn = 0, belowPad = 0, maxPad = 0, worst = '', worstPad = ''; const v = V();
      boy.traverse(o => { if (!o.isSkinnedMesh || !o.visible || /_inside$/.test(o.name)) return; const P = o.geometry.attributes.position, I = o.geometry.attributes.skinIndex, W = o.geometry.attributes.skinWeight;
        for (let i = 0; i < P.count; i++) { let k0 = 0, w0 = 0; for (let k = 0; k < 4; k++) if (W.getComponent(i, k) > w0) { w0 = W.getComponent(i, k); k0 = I.getComponent(i, k); }
          const bn = o.skeleton.bones[k0].name; if (!/R$|\\.R$/.test(bn) || !/finger|metacarpal|Hand/.test(bn)) continue;
          o.getVertexPosition(i, v).applyMatrix4(o.matrixWorld); n++;
          if (v.y < pad) { belowPad++; if (pad - v.y > maxPad) { maxPad = pad - v.y; worstPad = bn; } }
          if (!bb.containsPoint(v)) continue;
          ray.set(V(v.x, v.y + 0.3, v.z), dn); ray.far = 0.3 - 1e-4; const hits = ray.intersectObject(ms, false).filter(h => h.object.name === "mouse");
          // inside: an odd number of shell crossings above it
          const odd = hits.length % 2 === 1; if (odd) { inShell++; const d = hits[hits.length - 1].point.y - v.y; ray.set(v.clone(), up); ray.far = 0.2; const h2 = ray.intersectObject(ms, false)[0]; const dd = h2 ? h2.distance : 0; if (dd > maxIn) { maxIn = dd; worst = bn; } } } });
      const ms2 = ms.position.toArray().map(x => +x.toFixed(4));
      return {handVerts: n, inShell, maxIn_mm: +(maxIn * 1000).toFixed(1), belowPad, maxBelowPad_mm: +(maxPad * 1000).toFixed(1), mouse: ms2, mode: mh.M.mode, worst, worstPad}; }"""
    with Server() as server:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            h = Harness(out, log=lambda *x: None, cdn_cache=Path("tests/visual/.cdn_cache")); h.server = server; h.base = server.base
            h.browser = p.chromium.launch(executable_path=CHROMIUM, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
            ctx, pg, st = h.open("1280"); h.goto_scene(pg, "desk", 14); pg.wait_for_function("() => !window.mh || window.mh.ready", timeout=180000)
            pg.evaluate("() => act('chart', {screen: {device: 'desk', id: 'c1', kind: 'page'}})")
            pg.evaluate(f"() => {{ for (let i = 0; i < {frames}; i++) animate_(1/30); }}")
            print(json.dumps(pg.evaluate(PEN)))
            for k in ["top", "low", "left"]:
                pg.evaluate(CAM, k); h.shoot(pg, out / f"{tag}_{k}.png", hud=False)
else:
    import json, sys, re
    sys.path.insert(0, ".")
    src = open(__file__).read(); PEN = re.search(r'PEN = """(.*?)"""', src, re.S).group(1)
    from pathlib import Path
    from tests.visual.harness import Harness, CHROMIUM
    from tests.visual.fake_server import Server
    with Server() as server:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            h = Harness(Path("/tmp/mp"), log=lambda *x: None, cdn_cache=Path("tests/visual/.cdn_cache")); h.server = server; h.base = server.base
            h.browser = p.chromium.launch(executable_path=CHROMIUM, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
            ctx, pg, st = h.open("1280"); h.goto_scene(pg, "desk", 14); pg.wait_for_function("() => !window.mh || window.mh.ready", timeout=180000)
            pg.evaluate("() => act('chart', {screen: {device: 'desk', id: 'c1', kind: 'page'}})")
            pg.evaluate("() => { for (let i = 0; i < 90; i++) animate_(1/30); }")
            rows = []; worst = {}
            for s in range(60):
                r = pg.evaluate(PEN); rows.append((r["maxIn_mm"], r["maxBelowPad_mm"]))
                if r["maxIn_mm"] > 2 or r["belowPad"]: worst[round(3 + s * 0.25, 2)] = (r["maxIn_mm"], r["worst"], r["belowPad"])
                pg.evaluate("() => { for (let i = 0; i < 8; i++) animate_(1/30); }")
            ins = sorted(x[0] for x in rows)
            res = {"window_s": [3, 18], "samples": 60, "hand_into_shell_mm": {"max": ins[-1], "median": ins[30], "p90": ins[54]}, "hand_below_pad_mm_max": max(x[1] for x in rows), "over_2mm": worst}
            print(json.dumps(res)); json.dump(res, open(sys.argv[1], "w"), indent=1)
