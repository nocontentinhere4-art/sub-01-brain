// node contact_pass.mjs <port> <activity | activity>next> <seconds> [out.json] : the room (room.html?debug) with the character doing
// <activity> (research, chart, chat, eat: seated at the desk; listen_music: on the bed), sampled every frame for <seconds> once he is in place; every
// vertex of his skin (every 2nd) tested against the furniture, split by body region:
//   chair  inside the desk chair (inside-intervals of the chair's own meshes, in its frame, as the page's chairVox, so it
//          follows the chair as it rolls); seat: his thighs / buttocks against the cushion's top (a height map of its
//          fabric): the lowest gap each frame, and any of him more than 1 cm under it
//   desk   inside the desk and the other static furniture near it (inside-intervals of the room's solid meshes, built
//          here the same way: vertical rays, every crossing counted, 1.5 cm columns), labelled desk where over the desk
//   floor  below the floor (F); soles: each foot's lowest gap to what is under it (the floor, the chair's base, furniture)
//   bed    inside the bed (the page's box: the mattress top less 2 cm of give, rounded edge)
//   legs   his hands and fingers inside his own thighs (capsules on the thigh bones, radius from his thigh skin)
//   keys   his fingertips over the room keyboard: their lowest height over its key tops each frame (touching within 5 mm)
//   mouse  his right palm (60% from the wrist to the middle knuckle) against the room mouse: across from its centre, over its top
// A penetration is a vertex more than 1 cm inside (the page's own margin); depth = how far inside, vertically.
// LIFE='{"screen": {"id": "v", "kind": "video"}}': more of the tick for live() (a video on the screen: watching).
// RARE=scared|angry|clap: once settled at the desk, start that rare event (boy_mh.js mh.rare) and sample from there.
// perFrame in the output: for every frame with something inside a solid, {"solid:region": [vertices, depth cm]} (frame = 1/30 s).
// QS: more of the page's query (QS="&char=mixamo").
// Needs a page served with ?debug (window.penetration, chairVox, live, pose, animate_). Uses playwright-core.
import {chromium} from "playwright-core"; import fs from "fs"; import {execSync} from "child_process"; import path from "path";
const [port, activity = "research", secs = "8", out] = process.argv.slice(2);
const b = await chromium.launch({executablePath: process.env.CHROME || "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
  args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]});
const p = await b.newPage({viewport: {width: 480, height: 320}});
const cdn = path.join(process.env.CDN_CACHE || "/tmp", "cdn_cache"); fs.mkdirSync(cdn, {recursive: true});
await p.route(/^https:\/\/(cdn\.jsdelivr\.net|unpkg\.com)\//, async r => { const u = r.request().url(), f = path.join(cdn, u.replace(/[^a-z0-9.]+/gi, "_"));
  if (!fs.existsSync(f)) execSync(`curl -sSfL -o ${f} '${u}'`); await r.fulfill({status: 200, contentType: u.endsWith(".css") ? "text/css" : "application/javascript", body: fs.readFileSync(f)}); });
p.on("pageerror", e => console.log("pageerror", e.message));
await p.goto(`http://localhost:${port}/room.html?debug&nolive&hour=15${process.env.QS || ""}`);   // (QS="&char=mixamo": the Mixamo-rigged character)
await p.waitForFunction(() => window.boy && window.mh && window.mh.ready && window.roomDbg, null, {timeout: 300000});
const res = await p.evaluate(([activity, secs, X, RARE]) => { let S0step = null;
  // "a>b": settle doing a, then switch to b and sample from the moment his pose step (sitting down, getting up) begins
  const [act0, act1] = activity.split(">"); activity = act0;
  window.FREEZE = true; settle(); live(activity, X);
  // in place: no step for a second
  const WANT = {research: "desk", chart: "desk", chat: "desk", eat: "desk", listen_music: "bedlie", sleep: "bedlie", phone: "bedside"}[activity];
  let t = 0, still = 0; while (t < 120 && still < 1) { animate_(1 / 30); t += 1 / 30; still = pose().step || (WANT && pose().at !== WANT) ? 0 : still + 1 / 30; }
  if (RARE) { const ok = mh.rare(RARE); if (!ok) return {error: "rare " + RARE + " did not start"}; }
  if (act1) { live(act1, X); let w = 0; while (w < 60 && !(pose().step && pose().step.k === "pose")) { animate_(1 / 30); w += 1 / 30; } }
  const at = pose().at, cur = pose().current && pose().current._clip && pose().current._clip.name;
  S0step = pose().step ? {k: pose().step.k, from: pose().step.from, to: pose().step.to} : null;
  // ---- the static furniture as inside-intervals (desk region and around), world frame
  const SOLID = /^(oak|steel|painted|white|plastic_black|book|metal_dark|rubber|alu|cable|desk_lamp_arm_01|potted_plant_02_pot|potted_plant_04)$/;
  const meshes = []; room.traverse(o => { if (o.isMesh && o.material && SOLID.test(o.material.name)) { meshes.push(o); o.material.side = THREE.DoubleSide; } });
  const R = {x0: -1.95, x1: 0.35, z0: -1.50, z1: 0.25, c: 0.015}, nx = Math.ceil((R.x1 - R.x0) / R.c), nz = Math.ceil((R.z1 - R.z0) / R.c), cols = new Array(nx * nz);
  const ray = new THREE.Raycaster(), o = new THREE.Vector3(), UP = new THREE.Vector3(0, 1, 0);
  for (let i = 0; i < nx; i++) for (let k = 0; k < nz; k++) { o.set(R.x0 + (i + 0.5) * R.c, 0.17, R.z0 + (k + 0.5) * R.c); ray.set(o, UP);
    const hits = []; for (const h of ray.intersectObjects(meshes, false)) { const y = h.point.y; if (!hits.length || y - hits[hits.length - 1] > 0.002) hits.push(y); }
    cols[i * nz + k] = hits.length >= 2 ? hits.slice(0, hits.length - (hits.length % 2)) : null; }
  meshes.forEach(m => { m.material.side = THREE.FrontSide; });
  const DESK = {x0: -1.56, x1: -0.34, z0: -1.46, z1: -0.84};          // the desk's footprint (its top and legs)
  // ---- body regions by each vertex's main bone
  const REG = n => /Foot|ToeBase|toe/i.test(n) ? "feet" : /UpLeg|Leg|thigh|calf|knee/i.test(n) ? "legs" : /Hips|pelvis|Pelvis|Hip$/.test(n) ? "hips"
    : /Hand|finger|metacarpal|thumb/i.test(n) ? "hands" : /Arm|Shoulder|clavicle/i.test(n) ? "arms" : /neck|Neck|Head|head/.test(n) ? "head" : "torso";
  const parts = []; boy.traverse(x => { if (x.isSkinnedMesh && x.visible) parts.push(x); });
  const vreg = parts.map(sm => { const I = sm.geometry.attributes.skinIndex, W = sm.geometry.attributes.skinWeight, n = sm.geometry.attributes.position.count, r = new Array(n);
    for (let i = 0; i < n; i++) { let bb = 0, bw = 0; for (let q = 0; q < 4; q++) if (W.getComponent(i, q) > bw) { bw = W.getComponent(i, q); bb = I.getComponent(i, q); } r[i] = REG(sm.skeleton.bones[bb].name); } return r; });
  // the chair the same way, in its own frame (as the page's chairVox, which is not exported)
  // what sits on a seat: the buttocks and thighs (the hips' and thighs' bones), not the calves
  const SEATV = parts.map(sm => { const I = sm.geometry.attributes.skinIndex, W = sm.geometry.attributes.skinWeight, n = sm.geometry.attributes.position.count, r = new Uint8Array(n);
    for (let i = 0; i < n; i++) { let bb = 0, bw = 0; for (let q = 0; q < 4; q++) if (W.getComponent(i, q) > bw) { bw = W.getComponent(i, q); bb = I.getComponent(i, q); } r[i] = /UpLeg|Thigh|Hips|Hip$|Pelvis|pelvis/.test(sm.skeleton.bones[bb].name) ? 1 : 0; } return r; });
  const ch = roomDbg().CHAIR && roomDbg().CHAIR.node; let CV = null;
  if (ch) { const cm = []; ch.traverse(m => { if (m.isMesh) { cm.push(m); m.material.side = THREE.DoubleSide; } }); ch.updateMatrixWorld(true);
    const bb = new THREE.Box3().setFromObject(ch), inv = new THREE.Matrix4().copy(ch.matrixWorld).invert(), lb = bb.clone().applyMatrix4(inv), c = 0.015, w = new THREE.Vector3();
    CV = {x0: lb.min.x, z0: lb.min.z, c, nx: Math.ceil((lb.max.x - lb.min.x) / c), nz: Math.ceil((lb.max.z - lb.min.z) / c), cols: []};
    const dir = new THREE.Vector3(0, 1, 0).transformDirection(ch.matrixWorld);
    for (let i = 0; i < CV.nx; i++) for (let k = 0; k < CV.nz; k++) { o.set(CV.x0 + (i + 0.5) * c, lb.min.y - 0.05, CV.z0 + (k + 0.5) * c); ch.localToWorld(o); ray.set(o, dir);
      const hits = []; for (const h of ray.intersectObjects(cm, false)) { const y = ch.worldToLocal(w.copy(h.point)).y; if (!hits.length || y - hits[hits.length - 1] > 0.002) hits.push(y); }
      CV.cols[i * CV.nz + k] = hits.length >= 2 ? hits.slice(0, hits.length - (hits.length % 2)) : null;
      let st = null; for (const h of ray.intersectObjects(cm, false)) if (/fabric/.test(h.object.material.name)) st = Math.max(st ?? -9, ch.worldToLocal(w.copy(h.point)).y);
      (CV.seat = CV.seat || [])[i * CV.nz + k] = st; }
    cm.forEach(m => { m.material.side = THREE.FrontSide; }); }
  const F = 0.16, TOP = 0.82 - 0.02, M = 0.01;
  const S = {frames: 0, at, clip: cur, step: S0step, chair: {}, desk: {}, other: {}, floor: {}, bed: {}, seat: {min: 9, max: -9}, soles: {L: {min: 9, max: -9}, R: {min: 9, max: -9}}, worst: [], perFrame: {}};
  const add = (k, reg, d, f) => { const e = S[k][reg] || (S[k][reg] = {frames: 0, maxDepth: 0, maxCount: 0, _f: -1, _n: 0});
    if (e._f !== f) { if (e._f >= 0) e.maxCount = Math.max(e.maxCount, e._n); e._f = f; e._n = 0; e.frames++; } e._n++; e.maxDepth = Math.max(e.maxDepth, d);
    const p = S.perFrame[f] || (S.perFrame[f] = {}), q = p[k + ":" + reg] || (p[k + ":" + reg] = [0, 0]); q[0]++; q[1] = Math.max(q[1], +(d * 100).toFixed(1)); };   // (frame -> "solid:region" -> [vertices, depth cm])
  // his own legs: each thigh a capsule on its bone (hip joint -> knee), its radius along the bone measured from his thigh
  // skin in the first frame (the 90th percentile of the skin's distance from the bone, 10 bands); a hand or finger vertex
  // inside it (by more than 5 mm) is a hand in the leg
  const TH = {L: ["LeftUpLeg", "LeftLeg"], R: ["RightUpLeg", "RightLeg"]}, HANDV = parts.map((sm, pi) => vreg[pi].map(r => r === "hands"));
  const THV = parts.map(sm => { const I = sm.geometry.attributes.skinIndex, W = sm.geometry.attributes.skinWeight, n = sm.geometry.attributes.position.count, r = new Array(n);
    for (let i = 0; i < n; i++) { let bb = 0, bw = 0; for (let q = 0; q < 4; q++) if (W.getComponent(i, q) > bw) { bw = W.getComponent(i, q); bb = I.getComponent(i, q); }
      const nm = sm.skeleton.bones[bb].name; r[i] = /^LeftUpLeg|^L_Thigh/.test(nm) ? "L" : /^RightUpLeg|^R_Thigh/.test(nm) ? "R" : null; } return r; });
  const segOf = s => { const a = boy.getObjectByName(TH[s][0]).getWorldPosition(new THREE.Vector3()), b = boy.getObjectByName(TH[s][1]).getWorldPosition(new THREE.Vector3()); return [a, b]; };
  const RAD = {}; { boy.updateMatrixWorld(true); const vv = new THREE.Vector3();
    for (const s of ["L", "R"]) { const [a, b] = segOf(s), ab = b.clone().sub(a), L2 = ab.lengthSq(), bands = Array.from({length: 10}, () => []);
      parts.forEach((sm, pi) => { const P = sm.geometry.attributes.position; for (let i = 0; i < P.count; i += 2) { if (THV[pi][i] !== s) continue; sm.getVertexPosition(i, vv); vv.applyMatrix4(sm.matrixWorld);
        const t = vv.clone().sub(a).dot(ab) / L2; if (t < 0 || t > 1) continue; const d = vv.distanceTo(a.clone().addScaledVector(ab, t)); bands[Math.min(9, Math.floor(t * 10))].push(d); } });
      RAD[s] = bands.map(bd => { if (!bd.length) return 0; bd.sort((x, y) => x - y); return bd[Math.floor(bd.length * 0.9)]; }); } }
  // the keyboard: his fingertips (the skin of the last finger joints) over its footprint, against its key tops
  const KB = scene.getObjectByName("keyboard"); let KBB = null; if (KB) { KB.updateMatrixWorld(true); KBB = new THREE.Box3().setFromObject(KB); }
  const TIPV = parts.map(sm => { const I = sm.geometry.attributes.skinIndex, W = sm.geometry.attributes.skinWeight, n = sm.geometry.attributes.position.count, r = new Uint8Array(n);
    for (let i = 0; i < n; i++) { let bb = 0, bw = 0; for (let q = 0; q < 4; q++) if (W.getComponent(i, q) > bw) { bw = W.getComponent(i, q); bb = I.getComponent(i, q); } r[i] = /finger[2-5]-3/.test(sm.skeleton.bones[bb].name) ? 1 : 0; } return r; });
  S.keys = KBB ? {top: +KBB.max.y.toFixed(3), framesOver: 0, framesTouch: 0, framesBelow: 0, minGap_cm: 99, maxGap_cm: -99, gaps: []} : null;
  // the mouse (a room node "mouse"): the right palm (60% from the wrist to the middle knuckle) against it each frame:
  // how far it is from the mouse's centre across the pad, and its height over the mouse's top
  const MS = scene.getObjectByName("mouse"), MB = MS ? new THREE.Box3() : null;
  S.mouse = MS ? {frames: 0, palmOff_cm: [99, -99], palmOverTop_cm: [99, -99]} : null;
  S.legs = {framesIn: 0, maxVerts: 0, maxDepth: 0, worstT: null, radius_cm: Object.fromEntries(Object.entries(RAD).map(([k, r]) => [k, r.map(x => +(x * 100).toFixed(1))]))};
  const v = new THREE.Vector3(), u = new THREE.Vector3(), N = Math.round(secs * 30);
  for (let f = 0; f < N; f++) {
    animate_(1 / 30); boy.updateMatrixWorld(true); let seatLow = 9, solL = 9, solR = 9, nPen = 0;
    parts.forEach((sm, pi) => { const P = sm.geometry.attributes.position, reg = vreg[pi];
      for (let i = 0; i < P.count; i += 2) { sm.getVertexPosition(i, v); v.applyMatrix4(sm.matrixWorld); const rg = reg[i];
        if (v.y < F - M) { add("floor", rg, F - v.y, f); nPen++; }
        if (rg === "feet") { const side = v.z; }
        const e = Math.min(v.x + 1.90, -0.20 - v.x, v.z - 0.25, 1.50 - v.z);
        if (e > 0 && v.y < TOP - (e < 0.05 ? 0.05 - Math.sqrt(0.0025 - (0.05 - e) ** 2) : 0) - M) { add("bed", rg, TOP - v.y, f); nPen++; }
        if (CV) { ch.worldToLocal(u.copy(v)); const ci = Math.floor((u.x - CV.x0) / CV.c), ck = Math.floor((u.z - CV.z0) / CV.c);
          const col = ci >= 0 && ci < CV.nx && ck >= 0 && ck < CV.nz && CV.cols[ci * CV.nz + ck];
          if (col) { for (let j = 0; j < col.length; j += 2) if (u.y > col[j] + M && u.y < col[j + 1] - M) { add("chair", rg, Math.min(u.y - col[j], col[j + 1] - u.y), f); nPen++; }
            if ((rg === "hips" || rg === "legs") && u.y > col[0] - 0.05) { const top = col[col.length - 1]; } } }
        const i2 = Math.floor((v.x - R.x0) / R.c), k2 = Math.floor((v.z - R.z0) / R.c), col2 = i2 >= 0 && i2 < nx && k2 >= 0 && k2 < nz && cols[i2 * nz + k2];
        if (col2) for (let j = 0; j < col2.length; j += 2) if (v.y > col2[j] + M && v.y < col2[j + 1] - M) {
          const desk = v.x > DESK.x0 && v.x < DESK.x1 && v.z > DESK.z0 && v.z < DESK.z1; add(desk ? "desk" : "other", rg, Math.min(v.y - col2[j], col2[j + 1] - v.y), f); nPen++; }
        if (rg === "feet") { const g = v.y - F; if (v.z === v.z) { /* per sole below */ } if (sm.skeleton) { } }
      } });
    // the seat: his thighs / buttocks over the cushion's top surface (a height map of the chair's fabric, its own frame):
    // the lowest gap each frame (contact), and how much of him is more than 1 cm under it
    if (CV) { let low = 9, under = 0, deep = 0; parts.forEach((sm, pi) => { const P = sm.geometry.attributes.position, reg = vreg[pi];
      for (let i = 0; i < P.count; i += 2) { if (!SEATV[pi][i]) continue; sm.getVertexPosition(i, v); v.applyMatrix4(sm.matrixWorld); ch.worldToLocal(u.copy(v));
        const ci = Math.floor((u.x - CV.x0) / CV.c), ck = Math.floor((u.z - CV.z0) / CV.c), top = ci >= 0 && ci < CV.nx && ck >= 0 && ck < CV.nz ? CV.seat[ci * CV.nz + ck] : null;
        // (more than the cushion's 10 cm under its top: under the seat, not in it)
        if (top == null || u.y < top - 0.10) continue; const g = u.y - top; if (g < low) low = g; if (g < -M) { under++; deep = Math.max(deep, -g); } } });
      if (low < 9) { S.seat.min = Math.min(S.seat.min, low); S.seat.max = Math.max(S.seat.max, low); }
      if (under) { S.seat.framesUnder = (S.seat.framesUnder || 0) + 1; S.seat.maxUnder = Math.max(S.seat.maxUnder || 0, under); S.seat.maxDepth = Math.max(S.seat.maxDepth || 0, deep); } }
    // the soles: each foot's lowest skin over the floor
    for (const s of ["Left", "Right"]) { const fb = boy.getObjectByName(s + "Foot"); if (!fb) continue; let lo = 9;
      parts.forEach((sm, pi) => { const P = sm.geometry.attributes.position, reg = vreg[pi], I = sm.geometry.attributes.skinIndex, W = sm.geometry.attributes.skinWeight;
        for (let i = 0; i < P.count; i += 3) { if (reg[i] !== "feet") continue; let bb = 0, bw = 0; for (let q = 0; q < 4; q++) if (W.getComponent(i, q) > bw) { bw = W.getComponent(i, q); bb = I.getComponent(i, q); }
          if (!sm.skeleton.bones[bb].name.startsWith(s) && !sm.skeleton.bones[bb].name.endsWith(s === "Left" ? ".L" : ".R")) continue;
          sm.getVertexPosition(i, v); v.applyMatrix4(sm.matrixWorld);
          let sup = F, what = "floor";                                    // the highest surface under this point: the floor, the chair (its base, a caster), furniture
          if (CV) { ch.worldToLocal(u.copy(v)); const ci = Math.floor((u.x - CV.x0) / CV.c), ck = Math.floor((u.z - CV.z0) / CV.c), col = ci >= 0 && ci < CV.nx && ck >= 0 && ck < CV.nz && CV.cols[ci * CV.nz + ck];
            if (col) for (let j = 1; j < col.length; j += 2) if (col[j] < u.y + 0.03) { const wy = ch.localToWorld(u.clone().setY(col[j])).y; if (wy > sup) { sup = wy; what = "chair"; } } }
          const i2 = Math.floor((v.x - R.x0) / R.c), k2 = Math.floor((v.z - R.z0) / R.c), col2 = i2 >= 0 && i2 < nx && k2 >= 0 && k2 < nz && cols[i2 * nz + k2];
          if (col2) for (let j = 1; j < col2.length; j += 2) if (col2[j] < v.y + 0.03 && col2[j] > sup) { sup = col2[j]; what = "furniture"; }
          if (v.y - sup < lo) { lo = v.y - sup; S.soles[s[0]].on = what; } } });
      const k = s[0], g = lo; if (lo < 9) { S.soles[k].min = Math.min(S.soles[k].min, g); S.soles[k].max = Math.max(S.soles[k].max, g); } }
    { const segs = {L: segOf("L"), R: segOf("R")}; let nIn = 0, dMax = 0;
      parts.forEach((sm, pi) => { const P = sm.geometry.attributes.position; for (let i = 0; i < P.count; i += 2) { if (!HANDV[pi][i]) continue; sm.getVertexPosition(i, v); v.applyMatrix4(sm.matrixWorld);
        for (const s of ["L", "R"]) { const [a, b] = segs[s], ab = b.clone().sub(a), t = v.clone().sub(a).dot(ab) / ab.lengthSq(); if (t < 0 || t > 1) continue;
          const d = v.distanceTo(a.clone().addScaledVector(ab, t)), r = RAD[s][Math.min(9, Math.floor(t * 10))]; if (d < r - 0.005) { nIn++; dMax = Math.max(dMax, r - d); } } } });
      if (nIn) { S.legs.framesIn++; if (nIn > S.legs.maxVerts) { S.legs.maxVerts = nIn; S.legs.worstT = +(f / 30).toFixed(2); } S.legs.maxDepth = Math.max(S.legs.maxDepth, dMax); } }
    if (KBB) { let lo = 9; parts.forEach((sm, pi) => { const P = sm.geometry.attributes.position; for (let i = 0; i < P.count; i++) { if (!TIPV[pi][i]) continue; sm.getVertexPosition(i, v); v.applyMatrix4(sm.matrixWorld);
        if (v.x > KBB.min.x && v.x < KBB.max.x && v.z > KBB.min.z && v.z < KBB.max.z) lo = Math.min(lo, v.y - KBB.max.y); } });
      if (lo < 9) { const K = S.keys; K.framesOver++; if (lo < 0.005) K.framesTouch++; if (lo < -0.005) K.framesBelow++; K.minGap_cm = Math.min(K.minGap_cm, +(lo * 100).toFixed(1)); K.maxGap_cm = Math.max(K.maxGap_cm, +(lo * 100).toFixed(1)); if (f % 15 === 0) K.gaps.push(+(lo * 100).toFixed(1)); } }
    if (MS) { MS.updateMatrixWorld(true); MB.setFromObject(MS); const c = MB.getCenter(new THREE.Vector3()), hd = boy.getObjectByName("RightHand"), kn = boy.getObjectByName("finger3-1.R") || boy.getObjectByName("finger3-1R");
      if (hd && kn) { const pm = hd.getWorldPosition(new THREE.Vector3()).lerp(kn.getWorldPosition(new THREE.Vector3()), 0.6), o = Math.hypot(pm.x - c.x, pm.z - c.z) * 100, h = (pm.y - MB.max.y) * 100, M2 = S.mouse;
        M2.frames++; M2.palmOff_cm = [Math.min(M2.palmOff_cm[0], +o.toFixed(1)), Math.max(M2.palmOff_cm[1], +o.toFixed(1))]; M2.palmOverTop_cm = [Math.min(M2.palmOverTop_cm[0], +h.toFixed(1)), Math.max(M2.palmOverTop_cm[1], +h.toFixed(1))]; } }
    if (nPen) S.worst.push([+(f / 30).toFixed(2), nPen]);
    S.frames++; }
  for (const k of ["chair", "desk", "other", "floor", "bed"]) for (const r in S[k]) { const e = S[k][r]; e.maxCount = Math.max(e.maxCount, e._n); delete e._f; delete e._n; e.maxDepth = +(e.maxDepth * 100).toFixed(1); }
  S.seat = {lowestGap_min_cm: +(S.seat.min * 100).toFixed(1), lowestGap_max_cm: +(S.seat.max * 100).toFixed(1), framesUnder: S.seat.framesUnder || 0, maxVertsUnder: S.seat.maxUnder || 0, maxDepth_cm: +((S.seat.maxDepth || 0) * 100).toFixed(1)};
  for (const k of ["L", "R"]) S.soles[k] = {min_cm: +(S.soles[k].min * 100).toFixed(1), max_cm: +(S.soles[k].max * 100).toFixed(1), on: S.soles[k].on};
  S.worst = S.worst.sort((a, b) => b[1] - a[1]).slice(0, 5); S.legs.maxDepth = +(S.legs.maxDepth * 100).toFixed(1);
  S.mode = window.mh && mh.M.mode; S.mhlog = window.mh ? mh.M.log.slice(-8) : null; return S; }, [activity, +secs, JSON.parse(process.env.LIFE || "{}"), process.env.RARE || null]);
const txt = JSON.stringify(res, null, 1); if (out) fs.writeFileSync(out, txt); console.log(txt); await b.close();
