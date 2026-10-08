# usage (repo root): python3 tools/motion/key_contact_mesh.py OUT.json SECONDS
# typing contact on the keyboard's MESH (not a height map): DoubleSide faces; inside = odd number of crossings of a ray
# straight up (hits closer than 0.05 mm merged: shared edges); depth inside = nearest surface over 6 axis rays; outside, the
# fingertip's gap = the first face straight below. Plus the image-checkable geometry: reach, spread, hand turn, F/J.
import json, sys
sys.path.insert(0, ".")
from pathlib import Path
from tests.visual.harness import Harness, CHROMIUM
from tests.visual.fake_server import Server
JS = """() => { boy.updateMatrixWorld(true); const V=(...a)=>new THREE.Vector3(...a); const kb = scene.getObjectByName('keyboard'); kb.updateMatrixWorld(true);
  if (!window.__kbm) { const ms = []; kb.traverse(m => { if (m.isMesh) ms.push(m); }); window.__kbm = ms; }
  const ms = window.__kbm, saved = ms.map(m => m.material.side); ms.forEach(m => { m.material.side = THREE.DoubleSide; });
  const ray = new THREE.Raycaster(), bb = new THREE.Box3().setFromObject(kb).expandByScalar(0.01);
  const hits = (o, d, far) => { ray.set(o, d); ray.far = far; const hs = ray.intersectObjects(ms, false); const out = []; for (const h of hs) if (!out.length || h.distance - out[out.length - 1] > 5e-5) out.push(h.distance); return out; };
  const DIRS = [V(1,0,0), V(-1,0,0), V(0,1,0), V(0,-1,0), V(0,0,1), V(0,0,-1)];
  const signed = v => { if (!bb.containsPoint(v)) return null; const up = hits(v, V(0,1,0), 0.3); if (up.length % 2 === 1) { let d = 1; for (const dd of DIRS) { const h = hits(v, dd, 0.05)[0]; if (h != null) d = Math.min(d, h); } return -d; }
    const dn = hits(v, V(0,-1,0), 0.2)[0]; return dn == null ? null : dn; };
  const tips = {}, inside = {}; const v = V();
  boy.traverse(o => { if (!o.isSkinnedMesh || !o.visible || /_inside$/.test(o.name)) return; const P = o.geometry.attributes.position, I = o.geometry.attributes.skinIndex, W = o.geometry.attributes.skinWeight;
    for (let i = 0; i < P.count; i++) { let k0 = 0, w0 = 0; for (let k = 0; k < 4; k++) if (W.getComponent(i, k) > w0) { w0 = W.getComponent(i, k); k0 = I.getComponent(i, k); }
      const bn = o.skeleton.bones[k0].name; if (!/^(LeftHand|RightHand|finger\\d-\\d[LR])$/.test(bn)) continue;
      o.getVertexPosition(i, v).applyMatrix4(o.matrixWorld); const s = signed(v); if (s == null) continue;
      if (s < 0) inside[bn] = Math.min(inside[bn] ?? 0, s);
      const m = /^finger([1-5])-3([LR])$/.exec(bn); if (m) { const key = m[2] + m[1]; tips[key] = Math.min(tips[key] ?? 1e9, s); } } });
  // self-check: a point 2 mm under the cap top at F must read inside, 3 mm over it outside
  const fw = kb.localToWorld(V(-0.0285, 0, 0)), topF = hits(fw.clone().setY(fw.y + 0.2), V(0, -1, 0), 0.4)[0], ty = fw.y + 0.2 - topF;
  const check = [signed(fw.clone().setY(ty - 0.002)), signed(fw.clone().setY(ty + 0.003))].map(x => x == null ? null : +(x * 1000).toFixed(1));
  ms.forEach((m, k) => { m.material.side = saved[k]; });
  const r = x => +(x * 1000).toFixed(1);
  // geometry, in the keyboard's frame (x along the keys, his right +; z toward him +)
  const g = n => boy.getObjectByName(n).getWorldPosition(V()), kl = p => kb.worldToLocal(p.clone());
  const tipP = (s, i) => { const b3 = boy.getObjectByName('finger' + i + '-3' + s); return b3.getWorldPosition(V()).add(V(0, -1, 0).applyQuaternion(b3.getWorldQuaternion(new THREE.Quaternion())).multiplyScalar(0.02)); };
  const geo = {};
  for (const s of ['L', 'R']) { const H = s === 'L' ? 'LeftHand' : 'RightHand', w = kl(g(H)), k3 = kl(g('finger3-1' + s)); const h = k3.clone().sub(w).setY(0), palm = k3.clone().sub(w).length();
    const yaw = Math.atan2(h.x, -h.z) * 57.3;   // (+ = toward his right, from his forward line = the keys' -z)
    const ang = (a, b) => { const u = kl(b).sub(kl(a)).setY(0); return Math.atan2(u.x, -u.z) * 57.3; };
    const mid = ang(g('finger3-1' + s), g('finger3-2' + s)), sideL = s === 'L' ? 1 : -1;   // (index lies to the right of the middle on the left hand)
    const spread = {2: (ang(g('finger2-1' + s), g('finger2-2' + s)) - mid) * sideL, 4: (mid - ang(g('finger4-1' + s), g('finger4-2' + s))) * sideL, 5: (mid - ang(g('finger5-1' + s), g('finger5-2' + s))) * sideL};
    const reach = [2, 3, 4, 5].map(i => +(kl(tipP(s, i)).sub(w).setY(0).length() / h.length()).toFixed(2));
    geo[s] = {yaw: +yaw.toFixed(1), spread: Object.fromEntries(Object.entries(spread).map(([k, x]) => [k, +x.toFixed(1)])), reach, tip2: kl(tipP(s, 2)).toArray().map(x => +x.toFixed(3))}; }
  return {tips: Object.fromEntries(Object.entries(tips).map(([k, x]) => [k, r(x)])), inside: Object.fromEntries(Object.entries(inside).map(([k, x]) => [k, r(x)])), check, lifted: mh.M.lifted ? JSON.parse(JSON.stringify(mh.M.lifted)) : null, geo, F: [-0.0285, 0.0285]}; }"""
with Server() as server:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        h = Harness(Path("/tmp/mp"), log=lambda *x: None, cdn_cache=Path("tests/visual/.cdn_cache")); h.server = server; h.base = server.base
        h.browser = p.chromium.launch(executable_path=CHROMIUM, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        ctx, pg, st = h.open("1280"); h.goto_scene(pg, "desk", 14); pg.wait_for_function("() => !window.mh || window.mh.ready", timeout=180000)
        pg.evaluate("() => { act('research', {screen: {device: 'desk', id: 'q1', kind: 'page', query: 'ramen near kichijoji and the best late night places'}}); mh.M.typeUntil = 1e9; for (let i = 0; i < 90; i++) animate_(1/30); }")
        rows = []
        for s in range(int(float(sys.argv[2]) * 4)):
            r = pg.evaluate(JS); r["t"] = 3 + s * 0.25; rows.append(r)
            if s < 2: print(json.dumps(r)[:600], flush=True)
            pg.evaluate("() => { for (let i = 0; i < 7; i++) animate_(1/30); animate_(1/60); }")
        json.dump(rows, open(sys.argv[1], "w")); print("samples", len(rows))
