# His hands on the keys, in the page (run from the repo root): typing mode held, desk_14 scene.
#   python3 tools/motion/key_probe.py contact SECONDS [OUT.json]  each fingertip's skin over the keycap under it (mm), desk hits by bone
#   python3 tools/motion/key_probe.py shots OUT TAG               top-down over the keyboard, across the desk, from his left at key height
import sys
mode = sys.argv.pop(1)
if mode == 'contact':
    # typing mode: each fingertip's skin over the keycap top under it (mm; min over the distal phalanx's vertices), the desk hits by bone
    import json, sys
    sys.path.insert(0, ".")
    from pathlib import Path
    from tests.visual.harness import Harness, CHROMIUM
    from tests.visual.fake_server import Server
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 10; outp = sys.argv[2] if len(sys.argv) > 2 else None
    JS = """() => { boy.updateMatrixWorld(true); const V = (...a) => new THREE.Vector3(...a); const kb = scene.getObjectByName("keyboard"); kb.updateMatrixWorld(true);
      if (!window.__kbm) { const ms = []; kb.traverse(m => { if (m.isMesh) ms.push(m); }); window.__kbm = ms; }
      const ray = new THREE.Raycaster(), dn = V(0, -1, 0), bb = new THREE.Box3().setFromObject(kb);
      const top = p => { if (p.x < bb.min.x || p.x > bb.max.x || p.z < bb.min.z || p.z > bb.max.z) return null; ray.set(V(p.x, p.y + 0.2, p.z), dn); ray.far = 0.5; const h = ray.intersectObjects(window.__kbm, false)[0]; return h ? h.point.y : null; };
      const tips = {}; const v = V();
      boy.traverse(o => { if (!o.isSkinnedMesh || !o.visible || /_inside$/.test(o.name)) return; const P = o.geometry.attributes.position, I = o.geometry.attributes.skinIndex, W = o.geometry.attributes.skinWeight;
        for (let i = 0; i < P.count; i += 1) { let k0 = 0, w0 = 0; for (let k = 0; k < 4; k++) if (W.getComponent(i, k) > w0) { w0 = W.getComponent(i, k); k0 = I.getComponent(i, k); }
          const bn = o.skeleton.bones[k0].name; const m = /^finger([1-5])-3\\.?([LR])$/.exec(bn); if (!m) continue;
          o.getVertexPosition(i, v).applyMatrix4(o.matrixWorld); const t = top(v); if (t == null) continue; const key = m[2] + m[1]; const d = (v.y - t) * 1000; tips[key] = Math.min(tips[key] ?? 1e9, d); } });
      const q = __qa.body ? __qa.body(2) : null; const deskBy = {}; if (q) for (const [k, n] of Object.entries(q.by)) if (k.startsWith('desk:')) deskBy[k.slice(5)] = n;
      return {mode: mh.M.mode, tips: Object.fromEntries(Object.entries(tips).map(([k, x]) => [k, +x.toFixed(1)])), desk: q ? q.desk : null, deskBy}; }"""
    with Server() as server:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            h = Harness(Path("/tmp/mp"), log=lambda *x: None, cdn_cache=Path("tests/visual/.cdn_cache")); h.server = server; h.base = server.base
            h.browser = p.chromium.launch(executable_path=CHROMIUM, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
            ctx, pg, st = h.open("1280"); h.goto_scene(pg, "desk", 14); pg.wait_for_function("() => !window.mh || window.mh.ready", timeout=180000)
            pg.evaluate("() => { act('research', {screen: {device: 'desk', id: 'q1', kind: 'page', query: 'ramen near kichijoji and the best late night places'}}); mh.M.typeUntil = 1e9; }")
            pg.evaluate("() => { for (let i = 0; i < 60; i++) animate_(1/30); }")
            rows = []
            for s in range(int(secs * 4)):
                r = pg.evaluate(JS); r["t"] = 2 + s * 0.25; rows.append(r)
                print(json.dumps(r), flush=True)
                pg.evaluate("() => { for (let i = 0; i < 8; i++) animate_(1/30); }")
            if outp: json.dump(rows, open(outp, "w"))
else:
    # typing: a top-down over the keyboard, a low view from across the desk, one from his left at key height
    import json, sys
    sys.path.insert(0, ".")
    from pathlib import Path
    from tests.visual.harness import Harness, CHROMIUM
    from tests.visual.fake_server import Server
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True); tag = sys.argv[2]
    CAM = """(k) => { boy.updateMatrixWorld(true); const V = (...a) => new THREE.Vector3(...a); const kb = scene.getObjectByName("keyboard"), c = kb.getWorldPosition(V());
      const f = V(Math.sin(boy.rotation.y), 0, Math.cos(boy.rotation.y)), rt = V(-f.z, 0, f.x); let pos, at = c.clone().setY(c.y + 0.03);
      camera.up.set(0, 1, 0);
      if (k === "top") { pos = at.clone().addScaledVector(f, 0.06).setY(c.y + 0.55); camera.up.copy(f); }
      else if (k === "front") pos = at.clone().addScaledVector(f, 0.42).addScaledVector(rt, 0.16).setY(c.y + 0.10);
      else pos = at.clone().addScaledVector(rt, -0.42).addScaledVector(f, 0.06).setY(c.y + 0.07);
      camera.position.copy(pos); controls.target.copy(at); controls.update(); camera.fov = k === "top" ? 40 : 38; camera.updateProjectionMatrix(); __qa.render(); }"""
    with Server() as server:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            h = Harness(out, log=lambda *x: None, cdn_cache=Path("tests/visual/.cdn_cache")); h.server = server; h.base = server.base
            h.browser = p.chromium.launch(executable_path=CHROMIUM, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
            ctx, pg, st = h.open("1280"); h.goto_scene(pg, "desk", 14); pg.wait_for_function("() => !window.mh || window.mh.ready", timeout=180000)
            pg.evaluate("() => { act('research', {screen: {device: 'desk', id: 'q1', kind: 'page', query: 'ramen near kichijoji and the best late night places'}}); mh.M.typeUntil = 1e9; }")
            pg.evaluate("() => { for (let i = 0; i < 150; i++) animate_(1/30); }")
            for k in ["top", "front", "left"]:
                pg.evaluate(CAM, k); h.shoot(pg, out / f"{tag}_{k}.png", hud=False)
