# posture in the page: spine angle from vertical (Hips->neck, Hips->Head, in the chair's side plane), the back skin's gap to
# the backrest along the chair's +z (lumbar 0.55-0.80 m, mid-back 0.80-1.05 m above the floor), elbows; per desk mode
import json, sys, math
sys.path.insert(0, ".")
from pathlib import Path
from tests.visual.harness import Harness, CHROMIUM
from tests.visual.fake_server import Server
MH_DESK = "act('research', {screen: {device: 'desk', id: 'p1', kind: 'page'}})"
SC = {"type": "act('research', {screen: {device: 'desk', id: 'q1', kind: 'page', query: 'ramen near kichijoji'}})",
      "mouse": "act('chart', {screen: {device: 'desk', id: 'c1', kind: 'page'}})",
      "watch": "act('research', {screen: {device: 'desk', id: 'v1', kind: 'video'}})"}
JS = """([n, every]) => { const D = roomDbg(), ch = D.chairNode(), ray = new THREE.Raycaster(), v = new THREE.Vector3(), out = [];
  const parts = []; boy.traverse(o => { if (o.isSkinnedMesh && o.visible) parts.push(o); }); const cm = []; ch.traverse(m => { if (m.isMesh) cm.push(m); });
  const W = nm => boy.getObjectByName(nm).getWorldPosition(new THREE.Vector3());
  for (let f = 0; f < n; f++) { animate_(1/30); if (f < 60 || f % every) continue; ch.updateMatrixWorld(true); boy.updateMatrixWorld(true);
    const inv = ch.matrixWorld.clone().invert(), L = p => p.clone().applyMatrix4(inv), dirZ = new THREE.Vector3(0, 0, 1).transformDirection(ch.matrixWorld);
    const h = L(W("Hips")), nk = L(W("neck")), hd = L(W("Head")), F = env => env;
    const ang = (a, b) => +(Math.atan2(b.z - a.z, b.y - a.y) * 180 / Math.PI).toFixed(1);   // + = leaning back (toward the backrest, +z)
    let gL = 9, gM = 9;
    for (const sm of parts) { const P = sm.geometry.attributes.position, I = sm.geometry.attributes.skinIndex, Wt = sm.geometry.attributes.skinWeight;
      for (let i = 0; i < P.count; i += 4) { let b = 0, bw = 0; for (let k = 0; k < 4; k++) if (Wt.getComponent(i, k) > bw) { bw = Wt.getComponent(i, k); b = I.getComponent(i, k); }
        if (!/^(Hips|Pelvis|Spine02|Spine01|Spine)$/.test(sm.skeleton.bones[b].name)) continue;
        sm.getVertexPosition(i, v); v.applyMatrix4(sm.matrixWorld); const l = L(v); if (Math.abs(l.x) > 0.12 || l.z < h.z) continue;
        const y = l.y; if (y < 0.55 || y > 1.05) continue;
        ray.set(v, dirZ); ray.far = 0.4; const hit = ray.intersectObjects(cm, false)[0]; if (!hit) continue;
        if (y < 0.80) gL = Math.min(gL, hit.distance); else gM = Math.min(gM, hit.distance); } }
    const el = s => { const a = W(s + "Arm"), e = W(s + "ForeArm"), w = W(s + "Hand"); const u = a.sub(e), q = w.sub(e); return +(u.angleTo(q) * 180 / Math.PI).toFixed(0); };
    out.push({f, mode: mh.M.mode, clip: pose().clip, spineNeck: ang(h, nk), spineHead: ang(h, hd), headOverHips_cm: +((hd.z - h.z) * 100).toFixed(1), lumbarGap_cm: +(gL * 100).toFixed(1), midGap_cm: +(gM * 100).toFixed(1), elbowL: el("Left"), elbowR: el("Right"), hips: [h.x, h.y, h.z].map(x => +x.toFixed(3))}); }
  return out; }"""
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True); R = {}
with Server() as server:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        h = Harness(out, log=lambda *x: None, cdn_cache=Path("tests/visual/.cdn_cache")); h.server = server; h.base = server.base
        h.browser = p.chromium.launch(executable_path=CHROMIUM, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        ctx, pg, st = h.open("1280"); h.goto_scene(pg, "desk", 14); pg.wait_for_function("() => !window.mh || window.mh.ready", timeout=180000)
        for k, setup in SC.items():
            if len(sys.argv) > 2 and k not in sys.argv[2].split(","): continue
            pg.evaluate(f"() => {{ {setup}; }}"); R[k] = pg.evaluate(JS, [420, 30]); pg.evaluate("if (window.mh && mh.show) mh.show(null)")
            rows = [r for r in R[k] if r["mode"] and r["mode"].startswith("desk")]
            med = lambda key: sorted(r[key] for r in rows)[len(rows) // 2] if rows else None
            print(k, len(rows), {key: med(key) for key in ["spineNeck", "spineHead", "headOverHips_cm", "lumbarGap_cm", "midGap_cm", "elbowL", "elbowR"]}, rows and rows[0]["clip"], flush=True)
        (out / "posture.json").write_text(json.dumps(R))
