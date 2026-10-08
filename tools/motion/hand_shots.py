# page shots of the hands from over his left shoulder (the owner's angle) + from his right side, per desk mode
import json, sys, time
sys.path.insert(0, ".")
from pathlib import Path
from tests.visual.harness import Harness, CHROMIUM
from tests.visual.fake_server import Server
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True); tag = sys.argv[2]
SC0 = {"type": "act('research', {screen: {device: 'desk', id: 'q1', kind: 'page', query: 'ramen near kichijoji'}})",
      "mouse": "act('chart', {screen: {device: 'desk', id: 'c1', kind: 'page'}})",
      "watch": "act('research', {screen: {device: 'desk', id: 'v1', kind: 'video'}})"}
SC = {k: v for k, v in SC0.items() if len(sys.argv) < 4 or k in sys.argv[3].split(",")}
CAM = """(k) => { boy.updateMatrixWorld(true); const V = () => new THREE.Vector3(), wp = n => boy.getObjectByName(n).getWorldPosition(V());
  const f = V().set(Math.sin(boy.rotation.y), 0, Math.cos(boy.rotation.y)), right = V().set(f.z, 0, -f.x), up = V().set(0, 1, 0);
  const m = wp("LeftHand").add(wp("RightHand")).multiplyScalar(0.5), sh = wp("LeftArm");
  if (k === "left") { const lh = wp("LeftHand"); const pos = lh.clone().addScaledVector(f, -0.12).addScaledVector(right, 0.42).addScaledVector(up, 0.36);
    camera.position.copy(pos); controls.target.copy(lh); controls.update(); __qa.render(); return [pos.toArray(), lh.toArray()]; }
  let pos; if (k === "over") pos = sh.clone().addScaledVector(f, -0.45).addScaledVector(right, 0.30).addScaledVector(up, 0.45);
  else pos = m.clone().addScaledVector(right, -0.55).addScaledVector(f, 0.22).addScaledVector(up, 0.36);
  camera.position.copy(pos); controls.target.copy(m); controls.update(); __qa.render(); return [pos.toArray(), m.toArray()]; }"""
with Server() as server:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        h = Harness(out, log=lambda *x: None, cdn_cache=Path("tests/visual/.cdn_cache")); h.server = server; h.base = server.base
        h.browser = p.chromium.launch(executable_path=CHROMIUM, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        for mode, setup in SC.items():
            ctx, pg, st = h.open("1280"); h.goto_scene(pg, "desk", 14); pg.wait_for_function("() => !window.mh || window.mh.ready", timeout=180000)
            pg.evaluate(f"() => {{ {setup}; for (let i = 0; i < 150; i++) animate_(1/30); }}")
            for k in ["over", "side", "left"]:
                pg.evaluate(CAM, k); h.shoot(pg, out / f"{tag}_{mode}_{k}.png", hud=False)
            print(mode, pg.evaluate("() => [mh.M.mode, pose().clip]"), flush=True); h.pages.clear(); ctx.close()
