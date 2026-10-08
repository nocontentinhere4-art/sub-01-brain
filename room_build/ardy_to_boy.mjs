// node ardy_to_boy.mjs <ardy_out_dir> <boy.glb> <out_dir> [clip ...]
// ARDY Core-skeleton motions (room_build/ardy/gen.py -> <name>.json, skeleton.json) retargeted onto the room's character
// rig (web/room/boy.glb, Meshy auto-rig, 24 bones): world-space rotations of each mapped joint, with the two rest poses
// aligned per bone (the minimal rotation taking the source's neutral bone direction to the target's rest direction), put
// on the target's rest pose; Hips translation scaled by the hip-height ratio. Then, per clip: a seamless loop (the best
// matching pose pair is cropped out and the seam blended), the walk made in-place and timed so its feet move at the page's
// stride speed, the turn de-yawed (the page turns the root), the feet kept on the floor (the root is lifted by any
// penetration), and a manifest with each clip's hips offset. Output: <out_dir>/boy_m_<clip>.glb, rotation tracks + Hips
// translation only, rotations quantised to int16.
import fs from "node:fs";
import path from "node:path";
import { NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS } from "@gltf-transform/extensions";
import { prune, resample, quantize } from "@gltf-transform/functions";
import { MeshoptEncoder, MeshoptDecoder } from "meshoptimizer";
import * as THREE from "three";

const [,, ARDY, BOY, OUT, ...ONLY] = process.argv;
await MeshoptEncoder.ready; await MeshoptDecoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({"meshopt.encoder": MeshoptEncoder, "meshopt.decoder": MeshoptDecoder});

const STRIDE_V = 0.65;                      // m/s: room.html plays the walk clip at timeScale = speed / STRIDE_V
const BOY_HIP = 0.919;                      // m: boy.glb's hips at rest (Armature scale 0.01, Hips y 91.9 cm)
// target bone <- source joint, and the child that gives the target bone's direction (null: use the parent's alignment)
const MAP = {
  Hips: ["Hips", null], Spine02: ["Spine", "Spine01"], Spine01: ["Spine1", "Spine"], Spine: ["Spine3", "neck"],
  neck: ["Neck", "Head"], Head: ["Head", null],
  LeftShoulder: ["LeftShoulder", "LeftArm"], LeftArm: ["LeftArm", "LeftForeArm"], LeftForeArm: ["LeftForeArm", "LeftHand"], LeftHand: ["LeftHand", null],
  RightShoulder: ["RightShoulder", "RightArm"], RightArm: ["RightArm", "RightForeArm"], RightForeArm: ["RightForeArm", "RightHand"], RightHand: ["RightHand", null],
  LeftUpLeg: ["LeftUpLeg", "LeftLeg"], LeftLeg: ["LeftLeg", "LeftFoot"], LeftFoot: ["LeftFoot", "LeftToeBase"], LeftToeBase: ["LeftToeBase", null],
  RightUpLeg: ["RightUpLeg", "RightLeg"], RightLeg: ["RightLeg", "RightFoot"], RightFoot: ["RightFoot", "RightToeBase"], RightToeBase: ["RightToeBase", null],
};
// the source joint whose child gives the source bone direction (ARDY cskel27 names)
const SRC_CHILD = {Hips: "Spine", Spine: "Spine1", Spine1: "Spine2", Spine3: "Neck", Neck: "Head", Head: null,
  LeftShoulder: "LeftArm", LeftArm: "LeftForeArm", LeftForeArm: "LeftHand", LeftHand: "LeftHandEnd",
  RightShoulder: "RightArm", RightArm: "RightForeArm", RightForeArm: "RightHand", RightHand: "RightHandEnd",
  LeftUpLeg: "LeftLeg", LeftLeg: "LeftFoot", LeftFoot: "LeftToeBase", LeftToeBase: null,
  RightUpLeg: "RightLeg", RightLeg: "RightFoot", RightFoot: "RightToeBase", RightToeBase: null};
// per clip: loop (cyclic, seam blended), inplace (root xz removed, timed to STRIDE_V), deyaw (root yaw removed), minLoop/maxLoop (s)
const OPTS = {
  // lean: a constant forward bend of the torso (rad) for the seated clips: ARDY sits reclined as in a lounge chair, and the
  // room's desk chair has its backrest 32 cm behind the hip anchor, so a reclined back sinks into it (the visual QA's chair
  // budget is 0 vertices)
  type: {loop: true, minLoop: 3, maxLoop: 7.5, lean: 0.36}, stretch: {loop: true, minLoop: 4, maxLoop: 6.8, lean: 0.36}, eat: {loop: true, minLoop: 3, maxLoop: 7.5, lean: 0.36},
  idle: {loop: true, minLoop: 3, maxLoop: 7.5}, walk: {loop: true, inplace: true, minLoop: 0.8, maxLoop: 1.7},
  turn: {deyaw: true, inplace: true}, window: {loop: true, minLoop: 3, maxLoop: 7.5}, door: {},
  lie_back: {loop: true, minLoop: 3, maxLoop: 7.5}, lie_side: {loop: true, minLoop: 3, maxLoop: 7.5}, turn_over: {}, sleep: {loop: true, minLoop: 3, maxLoop: 7.5},
  sit_down: {}, stand_up: {},
};

// ---------- the target rig: rest pose in world space (rotation and position per bone; scale ignored for rotations)
const boyDoc = await io.read(BOY), boyRoot = boyDoc.getRoot();
const nodes = new Map(boyRoot.listNodes().map(n => [n.getName(), n]));
const parentOf = new Map(); for (const n of boyRoot.listNodes()) for (const c of n.listChildren()) parentOf.set(c, n);
const restW = new Map(), restP = new Map();            // world rotation (quaternion), world position (m)
function restOf(n){                                   // restScale: the node's world scale (the Armature is 0.01: cm)
  if (restW.has(n)) return;
  const p = parentOf.get(n); let pq = new THREE.Quaternion(), pp = new THREE.Vector3(), ps = 1;
  if (p) { restOf(p); pq = restW.get(p); pp = restP.get(p); ps = restScale.get(p); }
  restScale.set(n, ps * n.getScale()[0]);
  const q = new THREE.Quaternion(...n.getRotation()), t = new THREE.Vector3(...n.getTranslation());
  restW.set(n, pq.clone().multiply(q)); restP.set(n, t.multiplyScalar(ps).applyQuaternion(pq).add(pp));
}
const restScale = new Map();
for (const n of boyRoot.listNodes()) restOf(n);
const nodesTopDown = boyRoot.listNodes().slice().sort((a, b) => depth(a) - depth(b));
const bone = name => nodes.get(name);
const dirT = name => { const [, child] = MAP[name]; if (!child) return null; return restP.get(bone(child)).clone().sub(restP.get(bone(name))).normalize(); };

// ---------- the source skeleton
const SK = JSON.parse(fs.readFileSync(path.join(ARDY, "skeleton.json")));
const J = SK.joints, JI = Object.fromEntries(J.map((n, i) => [n, i])), PAR = SK.parents;
const neutral = SK.neutral.map(p => new THREE.Vector3(...p));
const hipRatio = BOY_HIP / SK.hip_height;
const dirS = name => { const c = SRC_CHILD[name]; if (!c) return null; return neutral[JI[c]].clone().sub(neutral[JI[name]]).normalize(); };
// per target bone: the alignment Q (source neutral direction -> target rest direction), inherited by end bones
const ALIGN = {};
const order = Object.keys(MAP).sort((a, b) => depth(bone(a)) - depth(bone(b)));
function depth(n){ let k = 0; while ((n = parentOf.get(n))) k++; return k; }
for (const b of order) {
  const [src] = MAP[b], dt = dirT(b), ds = dirS(src);
  if (dt && ds) ALIGN[b] = new THREE.Quaternion().setFromUnitVectors(ds, dt);
  else { const p = parentOf.get(bone(b)); ALIGN[b] = p && ALIGN[p.getName()] ? ALIGN[p.getName()].clone() : new THREE.Quaternion(); }
}
console.log("hip ratio", hipRatio.toFixed(3), "alignments (deg):", order.map(b => `${b} ${(2 * Math.acos(Math.min(1, Math.abs(ALIGN[b].w))) * 180 / Math.PI).toFixed(0)}`).join(" "));

// ---------- helpers
const qFrom = a => new THREE.Quaternion(a[0], a[1], a[2], a[3]);
function fkSource(localQ, root){                       // world rotations and positions of the source joints, one frame
  const G = [], P = [];
  for (let j = 0; j < J.length; j++) {
    const p = PAR[j], lq = qFrom(localQ[j]);
    if (p < 0) { G[j] = lq; P[j] = new THREE.Vector3(...root); }
    else { G[j] = G[p].clone().multiply(lq); P[j] = neutral[j].clone().sub(neutral[p]).applyQuaternion(G[p]).add(P[p]); }
  }
  return {G, P};
}
const headingOf = P => { const d = P[JI.RightUpLeg].clone().sub(P[JI.LeftUpLeg]); return Math.atan2(d.z, -d.x); };
const wrap = a => Math.atan2(Math.sin(a), Math.cos(a));
const yaw = a => new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), a);
function fkTarget(localQ, hipsT){                      // world positions of the target bones (m) for one frame of output
  const W = new Map(), Pw = new Map();
  for (const n of nodesTopDown) {
    const p = parentOf.get(n), name = n.getName();
    const q = localQ[name] || new THREE.Quaternion(...n.getRotation());
    const t = name === "Hips" ? hipsT.clone() : new THREE.Vector3(...n.getTranslation());
    if (!p) { W.set(n, q); Pw.set(n, t); continue; }
    W.set(n, W.get(p).clone().multiply(q)); Pw.set(n, t.multiplyScalar(restScale.get(p)).applyQuaternion(W.get(p)).add(Pw.get(p)));
  }
  return Pw;
}
function qdist(a, b){ return 2 * Math.acos(Math.min(1, Math.abs(a.dot(b)))); }

// ---------- one clip
async function convert(name){
  const file = path.join(ARDY, name + ".json");
  if (!fs.existsSync(file)) { console.log("skip", name, "(no file)"); return null; }
  const C = JSON.parse(fs.readFileSync(file)), O = OPTS[name] || {}, fps = C.fps, T = C.T;
  // source world rotations per frame, de-yawed if asked (the heading at frame 0 is kept)
  const frames = [];
  let h0 = null;
  for (let t = 0; t < T; t++) {
    const {G, P} = fkSource(C.local_quat[t], C.root[t]);
    const h = headingOf(P); if (h0 === null) h0 = h;
    let fix = new THREE.Quaternion();
    if (O.deyaw) fix = yaw(-wrap(h - h0));
    frames.push({G: G.map(g => fix.clone().multiply(g)), root: new THREE.Vector3(...C.root[t]).applyQuaternion(fix), P});
  }
  // walk: in place (the root's xz goes), its forward speed sets the time scale
  let timeScale = 1;
  if (O.inplace) {
    const d = frames[T - 1].root.clone().sub(frames[0].root).setY(0).length() * hipRatio, v = d / ((T - 1) / fps);
    if (name === "walk" && v > 0.05) timeScale = v / STRIDE_V;
    const r0 = frames[0].root.clone();
    for (const f of frames) { f.root.x = r0.x; f.root.z = r0.z; }
    console.log(`${name}: root speed ${v.toFixed(2)} m/s -> time x${timeScale.toFixed(2)}`);
  }
  // target local rotations per frame
  const TORSO = new Set(order.filter(b => { let n = bone(b); while (n) { if (n.getName() === "Spine02") return true; n = parentOf.get(n); } return false; }));
  const out = frames.map(f => {
    const W = {}, L = {};
    const leanQ = O.lean ? new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0).applyQuaternion(yaw(headingOf(f.P))), O.lean) : null;
    for (const b of order) {
      const [src] = MAP[b], n = bone(b), p = parentOf.get(n);
      W[b] = f.G[JI[src]].clone().multiply(ALIGN[b].clone().invert()).multiply(restW.get(n));
      if (leanQ && TORSO.has(b)) W[b].premultiply(leanQ);      // the torso and everything on it bent forward about his hips
      const pw = p && W[p.getName()] ? W[p.getName()] : (p ? restW.get(p) : new THREE.Quaternion());
      L[b] = pw.clone().invert().multiply(W[b]);
    }
    const hipsRest = new THREE.Vector3(...bone("Hips").getTranslation());
    const hips = new THREE.Vector3(hipsRest.x + (f.root.x - frames[0].root.x) * hipRatio * 100, f.root.y * hipRatio * 100, hipsRest.z + (f.root.z - frames[0].root.z) * hipRatio * 100);
    return {L, hips};
  });
  // loop: crop to the best matching pair (i, j), blend the seam into frame i over `seam` frames
  let times = out.map((_, t) => t / fps * timeScale), seq = out;
  if (O.loop) {
    const legs = ["Hips", "LeftUpLeg", "LeftLeg", "RightUpLeg", "RightLeg", "Spine02", "LeftArm", "RightArm", "LeftForeArm", "RightForeArm"];
    let best = null;
    const minF = Math.round(O.minLoop * fps), maxF = Math.round(O.maxLoop * fps);   // in the source's seconds (a gait cycle ~1.1 s)
    for (let i = 0; i < T - minF; i++) for (let j = i + minF; j < Math.min(T, i + maxF + 1); j++) {
      let d = 0; for (const b of legs) { d += qdist(out[i].L[b], out[j].L[b]); if (i + 1 < T && j + 1 < T) d += 0.5 * Math.abs(qdist(out[i].L[b], out[i + 1].L[b]) - qdist(out[j].L[b], out[j + 1].L[b])); }
      d += 2 * Math.abs(out[i].hips.y - out[j].hips.y) / 100;
      if (!best || d < best.d) best = {i, j, d};
    }
    if (!best) best = {i: 0, j: T, d: -1};              // too short to search: the whole clip, seam blended
    const {i, j} = best, seam = Math.min(8, Math.floor((j - i) / 4));
    seq = out.slice(i, j).map(f => ({L: {...f.L}, hips: f.hips.clone()}));
    for (let k = 0; k < seam; k++) {                   // the last `seam` frames ease into frame i (= the next loop's first)
      const w = (k + 1) / (seam + 1), f = seq[seq.length - seam + k];
      for (const b of order) f.L[b] = f.L[b].clone().slerp(seq[0].L[b], w);
      f.hips.lerp(seq[0].hips, w);
    }
    times = seq.map((_, t) => t / fps * timeScale);
    console.log(`${name}: loop ${i}..${j} (${((j - i) / fps * timeScale).toFixed(2)} s, pose distance ${best.d.toFixed(2)})`);
  }
  // the floor: no foot or toe under its rest height (the rest pose stands on y = 0); the root is lifted by the deepest
  // penetration of each frame, smoothed over 5 frames
  const restH = {LeftFoot: restP.get(bone("LeftFoot")).y, RightFoot: restP.get(bone("RightFoot")).y, LeftToeBase: restP.get(bone("LeftToeBase")).y, RightToeBase: restP.get(bone("RightToeBase")).y};
  const pen = seq.map(f => { const P = fkTarget(f.L, f.hips); let m = 0; for (const b in restH) m = Math.max(m, restH[b] - 0.01 - P.get(bone(b)).y); return m; });
  const lift = pen.map((_, t) => { let s = 0, n = 0; for (let k = -2; k <= 2; k++) if (pen[t + k] != null) { s += pen[t + k]; n++; } return s / n; });
  seq.forEach((f, t) => { f.hips.y += lift[t] * 100; });
  const maxPen = Math.max(...pen);
  // measure: hips offset from the root (m, the page's HIPS table), lowest foot after the lift, stride speed
  const P0 = fkTarget(seq[0].L, seq[0].hips), hipsAvg = seq.reduce((a, f) => a.add(f.hips), new THREE.Vector3()).multiplyScalar(1 / seq.length / 100);
  let lowest = 9; for (const f of seq) { const P = fkTarget(f.L, f.hips); for (const b in restH) lowest = Math.min(lowest, P.get(bone(b)).y - restH[b]); }
  // write: a copy of the rig without its mesh, one animation
  const doc = await io.read(BOY), root = doc.getRoot();
  for (const a of root.listAnimations()) { for (const c of a.listChannels()) c.dispose(); for (const sm of a.listSamplers()) sm.dispose(); a.dispose(); }
  for (const n of root.listNodes()) if (n.getMesh()) { n.setMesh(null); n.setSkin(null); n.dispose(); }
  for (const m of root.listMeshes()) m.dispose(); for (const s of root.listSkins()) s.dispose();
  for (const m of root.listMaterials()) m.dispose(); for (const t of root.listTextures()) t.dispose();
  for (const e of root.listExtensionsUsed()) e.dispose();   // a bare rig needs none of boy.glb's extensions
  const byName = new Map(root.listNodes().map(n => [n.getName(), n])), buf = root.listBuffers()[0];
  const anim = doc.createAnimation(`m_${name}`), tin = doc.createAccessor().setArray(new Float32Array(times)).setType("SCALAR").setBuffer(buf);
  const add = (node, pth, arr, type) => { const s = doc.createAnimationSampler().setInput(tin).setInterpolation("LINEAR")
    .setOutput(doc.createAccessor().setArray(arr).setType(type).setBuffer(buf)); anim.addSampler(s).addChannel(doc.createAnimationChannel().setTargetNode(node).setTargetPath(pth).setSampler(s)); };
  for (const b of order) { const arr = new Float32Array(seq.length * 4);
    let prev = null; seq.forEach((f, t) => { const q = f.L[b].clone(); if (prev && q.dot(prev) < 0) { q.x = -q.x; q.y = -q.y; q.z = -q.z; q.w = -q.w; } q.toArray(arr, t * 4); prev = q; });
    add(byName.get(b), "rotation", arr, "VEC4"); }
  const hip = new Float32Array(seq.length * 3); seq.forEach((f, t) => f.hips.toArray(hip, t * 3)); add(byName.get("Hips"), "translation", hip, "VEC3");
  // rotations as normalised int16 (core glTF for animation outputs), no meshopt: the tests read the clips without a decoder
  await doc.transform(prune({keepLeaves: true}), resample({tolerance: 1e-4}), quantize({quantizePosition: 14, quantizeNormal: 8, quantizeTexcoord: 10, quantizeColor: 8, quantizeWeight: 8, quantizeGeneric: 12}));
  const outFile = path.join(OUT, `boy_m_${name}.glb`); await io.write(outFile, doc);
  const size = fs.statSync(outFile).size;
  const info = {file: path.basename(outFile), frames: seq.length, duration: +((seq.length - 1) / fps * timeScale).toFixed(3), fps, loop: !!O.loop,
    hips: hipsAvg.toArray().map(v => +v.toFixed(3)), hips0: seq[0].hips.clone().multiplyScalar(0.01).toArray().map(v => +v.toFixed(3)),
    floorFix: +maxPen.toFixed(3), lowestFoot: +lowest.toFixed(3), bytes: size, prompt: C.prompt, seed: C.seed, score: C.score};
  if (O.inplace && name === "walk") info.stride = STRIDE_V;      // the page's STRIDE_V while this walk plays (its feet move back at this speed)
  console.log(`${name}: ${seq.length} frames, ${info.duration} s, hips ${info.hips}, floor fix ${info.floorFix} m, lowest ${info.lowestFoot} m, ${(size / 1024).toFixed(0)} KB`);
  return info;
}

fs.mkdirSync(OUT, {recursive: true});
const names = ONLY.length ? ONLY : Object.keys(OPTS);
const manifest = {source: "NVIDIA ARDY (ARDY-Core-RP-20FPS-Horizon40), retargeted by room_build/ardy_to_boy.mjs", hipRatio: +hipRatio.toFixed(4), clips: {}};
for (const n of names) { const info = await convert(n); if (info) manifest.clips[n] = info; }
fs.writeFileSync(path.join(OUT, "boy_m_manifest.json"), JSON.stringify(manifest, null, 1));
console.log("manifest:", Object.keys(manifest.clips).join(" "));
