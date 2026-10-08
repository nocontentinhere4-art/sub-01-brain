// node boy_post.mjs [out/boy2_raw.glb] [../web/room] : better motion for the first character (#76).
//
// Ships: web/room/boy_moves.glb, the first character's 24-bone rig (boy.glb's) playing the new clips, and
// docs/motion/deform_check.json, the skin check of every clip on boy.glb (see deformCheck at the end).
//
// How: the clips are made on an authoring body, boy2 (build_boy.py: MakeHuman CC0, a skeleton with the first rig's
// bone names and rest frames plus fingers and eyes; kept in out/, not shipped): Quaternius' Universal Animation
// Library (CC0) retargeted onto it, and keyed poses (the bed, the desk, eating, ...) posed on it by IK against its own
// skin. Then toOld() carries each clip onto the first rig: every bone turns in the world as on boy2 from its rest, the
// hips scaled by the leg ratio and set from his own lowest skin (the floor, or the mattress lying), seated frames
// raised to his seat height with the legs reaching back down by IK.
//
// Input: build_boy.py's skinned mesh in its bind pose (out/boy2_raw.glb, MPFB bone names) and joints (out/boy2_bind.json),
// boy_ref.mjs's old skeleton (out/boy_ref.json), the first character (web/room/boy.glb, boy_*.glb) and UAL (env UAL).
// Also written to out/: boy2.glb, boy2_<clip>.glb, boy2_hands.glb, boy2_motion.glb (the authoring body and its clips).
import fs from "node:fs";
import path from "node:path";
import { NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS } from "@gltf-transform/extensions";
import { prune, weld, meshopt, dedup, resample } from "@gltf-transform/functions";
import { MeshoptEncoder, MeshoptDecoder } from "meshoptimizer";
import sharp from "sharp";
import * as THREE from "three";
import { palmOf } from "./palm.mjs";

const [,, RAW = "out/boy2_raw.glb", WEB = "../web/room"] = process.argv;
// what ships is web/room/boy_moves.glb (the motion on the first character's rig) and docs/motion/deform_check.json;
// the authoring character (boy2*: the MakeHuman body the clips are keyed and retargeted on) stays in out/
const OUT = "out", OLD_FILES = ["boy_door.glb", "boy_eat.glb", "boy_idle.glb", "boy_sleep.glb", "boy_text.glb", "boy_walk.glb"];
await MeshoptEncoder.ready; await MeshoptDecoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({"meshopt.encoder": MeshoptEncoder, "meshopt.decoder": MeshoptDecoder});
const REF = JSON.parse(fs.readFileSync("out/boy_ref.json", "utf8")).bones;
const BIND = JSON.parse(fs.readFileSync("out/boy2_bind.json", "utf8"));
const V = a => new THREE.Vector3(...a), Q = a => new THREE.Quaternion(...a);
const CM = 100;                                  // bones are in cm under a 0.01 "Armature" node, like the old rig

// ------------------------------------------------------------------ the skeleton: name -> {parent, pos (m, world), quat (world)}
const mpfbOf = {}; for (const [m, n] of Object.entries(BIND.map)) if (m !== "Root") mpfbOf[n] = m;
const SK = {}, order = [];
function addBone(name, parent, pos, quat) { SK[name] = {name, parent, pos: pos.clone(), quat: quat.clone().normalize()}; order.push(name); }
// the old 24 in their old order (parents before children)
for (const [name, b] of Object.entries(REF)) {
  let pos;
  if (mpfbOf[name]) pos = V(BIND.bones[mpfbOf[name]].head);
  else {                                         // head_end / headfront: helpers at the same offset from the head joint as before
    pos = V(BIND.bones[mpfbOf.Head].head).add(V(b.pos).sub(V(REF.Head.pos)));
  }
  addBone(name, b.parent, pos, Q(b.quat));
}
const frameQuat = b => new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(V(b.x).normalize(), V(b.y).normalize(), V(b.z).normalize()));
for (const S of ["Left", "Right"]) for (const F of ["Thumb", "Index", "Middle", "Ring", "Pinky"]) for (const k of [1, 2, 3]) {
  const n = `${S}Hand${F}${k}`, b = BIND.bones[mpfbOf[n]];
  addBone(n, k === 1 ? `${S}Hand` : `${S}Hand${F}${k - 1}`, V(b.head), frameQuat(b));
}
for (const S of ["Left", "Right"]) addBone(`${S}Eye`, "Head", V(BIND.bones[mpfbOf[`${S}Eye`]].head), new THREE.Quaternion());
// the spine: MPFB's chest bone starts low (its spine_03 spans 1.15-1.44 m), the old rig's three spine joints are evenly
// spread between the hips and the neck, and the old clips bend them as such. So the new spine joints go where the old
// ones were along the torso (scaled), and the torso's weights are spread over them again (SPINE below)
const SPINE = ["Hips", "Spine02", "Spine01", "Spine", "neck"];
{
  const k = SK.neck.pos.clone().sub(SK.Hips.pos).length() / V(REF.neck.pos).sub(V(REF.Hips.pos)).length();
  for (const n of ["Spine02", "Spine01", "Spine"]) SK[n].pos.copy(SK.Hips.pos).add(V(REF[n].pos).sub(V(REF.Hips.pos)).multiplyScalar(k));
}
const world = n => new THREE.Matrix4().compose(SK[n].pos, SK[n].quat, new THREE.Vector3(0.01, 0.01, 0.01));
const ARM = new THREE.Matrix4().makeScale(0.01, 0.01, 0.01);
function localOf(n) {                            // local transform under the parent (cm)
  const pw = SK[n].parent ? world(SK[n].parent) : ARM, m = new THREE.Matrix4().copy(pw).invert().multiply(world(n));
  const p = new THREE.Vector3(), q = new THREE.Quaternion(), s = new THREE.Vector3(); m.decompose(p, q, s); return {p, q};
}

let SOCKETS = {};                                // filled in once the palms are measured (below)
function buildSkeleton(doc, scene) {
  const nodes = {}, arm = doc.createNode("Armature").setScale([0.01, 0.01, 0.01]); scene.addChild(arm);
  for (const n of order) {
    const {p, q} = localOf(n);
    nodes[n] = doc.createNode(n).setTranslation(p.toArray()).setRotation(q.toArray());
    (SK[n].parent ? nodes[SK[n].parent] : arm).addChild(nodes[n]);
  }
  for (const [n, s] of Object.entries(SOCKETS)) { nodes[n] = doc.createNode(n).setTranslation(s.p).setRotation(s.q); nodes[s.parent].addChild(nodes[n]); }
  return {arm, nodes};
}

// ------------------------------------------------------------------ the mesh
const doc = await io.read(RAW), root = doc.getRoot();
const rawSkin = root.listSkins()[0], rawJoints = rawSkin.listJoints().map(j => j.getName());
const meshNode = root.listNodes().find(n => n.getMesh()), mesh = meshNode.getMesh();
for (const n of root.listNodes()) if (n !== meshNode) n.dispose();
for (const s of root.listSkins()) s.dispose();
const scene = root.listScenes()[0]; meshNode.setName("boy2").setTranslation([0, 0, 0]).setRotation([0, 0, 0, 1]).setScale([1, 1, 1]);
scene.addChild(meshNode);
const joints = order.filter(n => !/head_end/.test(n));   // every bone is a joint (sockets are not)
const jIndex = Object.fromEntries(joints.map((n, i) => [n, i]));
// weights: MPFB bone -> new bone (the root's few go to the hips), merged, top 4, normalised
const remap = rawJoints.map(n => jIndex[BIND.map[n]]);
// the torso's share (its weights on the hips and the three spine bones) spread again by height: each spine bone's
// influence peaks in the middle of its segment and fades into its neighbours' (below the hips joint: all hips)
const spineIds = SPINE.slice(0, 4).map(n => jIndex[n]);
const centres = [SK.Hips.pos.y, ...[1, 2, 3].map(i => (SK[SPINE[i]].pos.y + SK[SPINE[i + 1]].pos.y) / 2)];
function spineShare(y) {
  const w = [0, 0, 0, 0];
  if (y <= centres[0]) w[0] = 1; else if (y >= centres[3]) w[3] = 1;
  else for (let i = 0; i < 3; i++) if (y >= centres[i] && y <= centres[i + 1]) { const t = (y - centres[i]) / (centres[i + 1] - centres[i]); w[i] = 1 - t; w[i + 1] = t; }
  return w;
}
if (remap.some(i => i === undefined)) throw new Error("unmapped joints: " + rawJoints.filter((n, i) => remap[i] === undefined));
for (const prim of mesh.listPrimitives()) {
  const J = prim.getAttribute("JOINTS_0"), W = prim.getAttribute("WEIGHTS_0"), POS = prim.getAttribute("POSITION"), n = J.getCount();
  const jo = new Uint8Array(n * 4), wo = new Float32Array(n * 4), j = [], w = [], p = [];
  for (let i = 0; i < n; i++) {
    J.getElement(i, j); W.getElement(i, w); const acc = new Map();
    for (let k = 0; k < 4; k++) if (w[k] > 0) acc.set(remap[j[k]], (acc.get(remap[j[k]]) || 0) + w[k]);
    const torso = spineIds.reduce((t, id) => t + (acc.get(id) || 0), 0);
    if (torso > 0) { const sh = spineShare(POS.getElement(i, p)[1]); spineIds.forEach((id, k) => { if (sh[k] > 0) acc.set(id, torso * sh[k]); else acc.delete(id); }); }
    const top = [...acc].sort((a, b) => b[1] - a[1]).slice(0, 4), sum = top.reduce((s, x) => s + x[1], 0) || 1;
    top.forEach(([jj, ww], k) => { jo[i * 4 + k] = jj; wo[i * 4 + k] = ww / sum; });
  }
  if (joints.length > 255) throw new Error("too many joints");
  J.setArray(jo).setType("VEC4"); W.setArray(wo);
}

// the palms, measured on the skin (palm.mjs), as a frame in each hand bone's space (cm): Y along the fingers, Z the palm's
// normal, T across the knuckles towards the thumb; `surf` how far the palm's skin stands out along Z
const HANDF = {};
for (const side of ["Left", "Right"]) {
  const ids = new Set(joints.map((n, i) => n.startsWith(side + "Hand") ? i : -1).filter(i => i >= 0)), inv = world(side + "Hand").invert(), pts = [];
  for (const prim of mesh.listPrimitives()) { const P = prim.getAttribute("POSITION"), J = prim.getAttribute("JOINTS_0"), W = prim.getAttribute("WEIGHTS_0"), j = [], w = [], q = [];
    for (let i = 0; i < P.getCount(); i++) { J.getElement(i, j); W.getElement(i, w); let sum = 0; for (let k = 0; k < 4; k++) if (ids.has(j[k])) sum += w[k];
      if (sum > 0.9) pts.push(new THREE.Vector3(...P.getElement(i, q)).applyMatrix4(inv)); } }
  const Z = palmOf(pts), Y = new THREE.Vector3(0, 1, 0), X = new THREE.Vector3().crossVectors(Y, Z);
  const thumb = SK[side + "HandThumb1"].pos.clone().applyMatrix4(inv), T = X.clone().multiplyScalar(Math.sign(thumb.dot(X)) || 1);
  const surf = Math.max(...pts.filter(p => p.y > 3 && p.y < 9 && Math.abs(p.dot(T)) < 3).map(p => p.dot(Z)));
  HANDF[side] = {T, Y, Z, surf, right: T.dot(X) > 0};
}
// a socket placed in the palm frame: p = [along T, along Y, off the palm (from its skin)] cm; y, z = the socket's own
// y and z axes as combinations of T, Y, Z (x follows)
function socket(side, [pt, py, pz], yk, zk) {
  const F = HANDF[side], v = k => F.T.clone().multiplyScalar(k[0]).addScaledVector(F.Y, k[1]).addScaledVector(F.Z, k[2]).normalize();
  const y = v(yk), x = new THREE.Vector3().crossVectors(y, v(zk)).normalize(), z = new THREE.Vector3().crossVectors(x, y);
  const q = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(x, y, z));
  return {parent: side + "Hand", p: F.T.clone().multiplyScalar(pt).addScaledVector(F.Y, py).addScaledVector(F.Z, F.surf + pz).toArray(), q: q.toArray()};
}
// the phone: its back on the palm and fingers, screen facing the palm's way, its top towards the thumb, the fingers
// wrapped round its far long edge and the thumb over the screen. Chopsticks: in the thumb's web, along the index finger,
// tips past the fingertips. Spoon: held like a pencil, its bowl past the fingertips. Tuned on boy_test.html (T.hand(...))
SOCKETS = {
  socket_phone: socket("Right", [-1.0, 9.5, 0.45], [1, 0, 0], [0, 0, 1]),
  socket_chopsticks: socket("Right", [1.5, 7.5, 1.0], [0.25, 1, 0.15], [0, -0.15, 1]),
  socket_spoon: socket("Right", [1.0, 4.0, 1.0], [0.2, 1, 0.3], [0, -0.3, 1]),
};
console.log("palms:", Object.entries(HANDF).map(([k, f]) => `${k} Z ${f.Z.toArray().map(x => x.toFixed(2))} T ${f.T.toArray().map(x => x.toFixed(2))} surf ${f.surf.toFixed(1)}`).join(" | "));

const {nodes} = buildSkeleton(doc, scene);
const skin = doc.createSkin("boy2"); joints.forEach(n => skin.addJoint(nodes[n]));
skin.setSkeleton(nodes.Hips);
const ibm = doc.createAccessor("ibm").setType("MAT4").setArray(new Float32Array(joints.flatMap(n => world(n).invert().toArray())));
skin.setInverseBindMatrices(ibm); meshNode.setSkin(skin);

// ------------------------------------------------------------------ materials: one opaque atlas, one alpha-tested
const [primBody, primHair] = mesh.listPrimitives();
const mainPng = await sharp("out/boy2_color.png").removeAlpha().webp({quality: 90}).toBuffer();
const normalPng = await sharp("out/boy2_normal.png").removeAlpha().webp({quality: 92}).toBuffer();
// occlusion, roughness, metalness (glTF's R, G, B): the AO softened (it is baked in the bind pose), no metal
const ao = await sharp("out/boy2_ao.png").greyscale().raw().toBuffer({resolveWithObject: true}), rg = await sharp("out/boy2_rough.png").greyscale().raw().toBuffer();
const orm = Buffer.alloc(ao.info.width * ao.info.height * 3);
for (let i = 0; i < ao.info.width * ao.info.height; i++) { orm[i * 3] = 255 - Math.round((255 - ao.data[i]) * 0.45); orm[i * 3 + 1] = rg[i]; orm[i * 3 + 2] = 0; }
const ormPng = await sharp(orm, {raw: {width: ao.info.width, height: ao.info.height, channels: 3}}).webp({quality: 90}).toBuffer();
const hairRgb = await sharp("out/boy2_hair_color.png").removeAlpha().raw().toBuffer({resolveWithObject: true});
const hairA = await sharp("out/boy2_hair_alpha.png").greyscale().raw().toBuffer();
const rgba = Buffer.alloc(hairRgb.info.width * hairRgb.info.height * 4);
for (let i = 0; i < hairRgb.info.width * hairRgb.info.height; i++) {
  for (let c = 0; c < 3; c++) rgba[i * 4 + c] = hairRgb.data[i * 3 + c]; rgba[i * 4 + 3] = hairA[i];
}
const hairWebp = await sharp(rgba, {raw: {width: hairRgb.info.width, height: hairRgb.info.height, channels: 4}}).webp({quality: 88, alphaQuality: 90}).toBuffer();
const texMain = doc.createTexture("boy2_body").setImage(mainPng).setMimeType("image/webp");
const texNormal = doc.createTexture("boy2_body_normal").setImage(normalPng).setMimeType("image/webp");
const texOrm = doc.createTexture("boy2_body_orm").setImage(ormPng).setMimeType("image/webp");
const texHair = doc.createTexture("boy2_hair").setImage(hairWebp).setMimeType("image/webp");
doc.createExtension(ALL_EXTENSIONS.find(e => e.EXTENSION_NAME === "EXT_texture_webp")).setRequired(true);
const matBody = doc.createMaterial("boy2_body").setBaseColorTexture(texMain).setNormalTexture(texNormal)
  .setOcclusionTexture(texOrm).setMetallicRoughnessTexture(texOrm).setRoughnessFactor(1).setMetallicFactor(1);
const matHair = doc.createMaterial("boy2_hair").setBaseColorTexture(texHair).setRoughnessFactor(0.85).setMetallicFactor(0)
  .setAlphaMode("MASK").setAlphaCutoff(0.3).setDoubleSided(true);
// hair: a weak specular, so direct sun does not turn its top grey
const specExt = doc.createExtension(ALL_EXTENSIONS.find(e => e.EXTENSION_NAME === "KHR_materials_specular"));
matHair.setExtension("KHR_materials_specular", specExt.createSpecular().setSpecularFactor(0.25));
primBody.setMaterial(matBody); primHair.setMaterial(matHair);
for (const m of root.listMaterials()) if (m !== matBody && m !== matHair) m.dispose();

// ------------------------------------------------------------------ clips
// the motion clips leave the fingers to the finger poses (boy2_hands.glb), layered on top in the room
const FINGER = /Hand(Thumb|Index|Middle|Ring|Pinky)\d$/, bodyOnly = channels => channels.filter(c => !FINGER.test(c.node));
function addClip(target, nodesOf, name, channels) {  // channels: [{node, path, times, values}]
  const a = target.createAnimation(name), buf = target.getRoot().listBuffers()[0];
  for (const c of channels) {
    const node = nodesOf[c.node]; if (!node) continue;
    const s = target.createAnimationSampler().setInput(target.createAccessor().setType("SCALAR").setArray(new Float32Array(c.times)).setBuffer(buf))
      .setOutput(target.createAccessor().setType(c.path === "rotation" ? "VEC4" : c.path === "weights" ? "SCALAR" : "VEC3").setArray(new Float32Array(c.values)).setBuffer(buf))
      .setInterpolation(c.interp || "LINEAR");
    a.addSampler(s).addChannel(target.createAnimationChannel().setTargetNode(node).setTargetPath(c.path).setSampler(s));
  }
  return a;
}
async function readClip(file) {                  // the old clip, decoded, as plain channels
  const d = await io.read(file), out = [];
  for (const a of d.getRoot().listAnimations()) {
    const ch = [];
    for (const c of a.listChannels()) {
      const s = c.getSampler();
      // getElement() decodes normalised integers (the old clips' rotations are int16)
      const acc = x => { const out = [], e = []; for (let i = 0; i < x.getCount(); i++) out.push(...x.getElement(i, e)); return out; };
      ch.push({node: c.getTargetNode().getName(), path: c.getTargetPath(), times: acc(s.getInput()), values: acc(s.getOutput()), interp: s.getInterpolation()});
    }
    out.push({name: a.getName(), channels: ch});
  }
  return out;
}

// forward kinematics (three.js, no rendering) of a skeleton playing a clip
const OLD = {};                                 // the old rig's rest (local TRS, cm)
for (const n of (await io.read(path.join(WEB, "boy.glb"))).getRoot().listNodes())
  if (REF[n.getName()]) OLD[n.getName()] = {parent: REF[n.getName()].parent, p: V(n.getTranslation()), q: Q(n.getRotation()), s: V(n.getScale())};
const NEW = Object.fromEntries(order.map(n => { const {p, q} = localOf(n); return [n, {parent: SK[n].parent, p, q, s: new THREE.Vector3(1, 1, 1)}]; }));
function fk(locals, channels, name, scale = 0.01) {
  const root = new THREE.Object3D(), b = {}; root.scale.setScalar(scale);
  for (const [n, L] of Object.entries(locals)) { const o = b[n] = new THREE.Object3D(); o.name = n; o.position.copy(L.p); o.quaternion.copy(L.q); o.scale.copy(L.s); }
  for (const [n, L] of Object.entries(locals)) (L.parent ? b[L.parent] : root).add(b[n]);
  const tracks = channels.filter(c => b[c.node] && c.path !== "weights").map(c => {
    const T = c.path === "rotation" ? THREE.QuaternionKeyframeTrack : THREE.VectorKeyframeTrack;
    return new T(`${c.node}.${c.path === "rotation" ? "quaternion" : c.path === "translation" ? "position" : "scale"}`, c.times, c.values); });
  const mixer = new THREE.AnimationMixer(root); mixer.clipAction(new THREE.AnimationClip(name, -1, tracks)).play();
  return {at(t) { mixer.setTime(t); root.updateMatrixWorld(true); return b; }};
}
const ankle = b => Math.min(b.LeftFoot.getWorldPosition(new THREE.Vector3()).y, b.RightFoot.getWorldPosition(new THREE.Vector3()).y);
const oldRestAnkle = Math.min(REF.LeftFoot.pos[1], REF.RightFoot.pos[1]), newRestAnkle = Math.min(SK.LeftFoot.pos.y, SK.RightFoot.pos.y);

// the old clip on the new skeleton: rotations as they are; the bones' translations and scales of the old skeleton are
// dropped (the old idle even scales the hips by 1.18), except the hips' path, whose height is set at every key so that
// the lower foot is as far above its rest height as the old one's (the feet stay on the floor, the seat stays a seat)
function retarget(clip) {
  const ch = clip.channels, hips = ch.find(c => c.node === "Hips" && c.path === "translation");
  const out = ch.filter(c => c.path === "rotation" && SK[c.node]).map(c => ({...c}));
  if (hips) {
    const o = fk(OLD, ch, clip.name), values = hips.values.slice();
    const n = fk(NEW, [...out, {...hips, values}], clip.name);
    for (let i = 0; i < hips.times.length; i++) {
      const t = hips.times[i], dOld = ankle(o.at(t)) - oldRestAnkle, dNew = ankle(n.at(t)) - newRestAnkle;
      values[i * 3 + 1] += (dOld - dNew) * CM;
    }
    out.push({...hips, values});
  }
  const dropped = ch.filter(c => c.path === "scale" && c.values.some(v => Math.abs(v - 1) > 1e-3)).map(c => c.node);
  if (dropped.length) console.log(`  ${clip.name}: animated scale dropped (${dropped.join(", ")})`);
  return {name: clip.name, channels: out};
}

// our clip on the first character's rig (boy.glb): each of its bones turns in the world as ours does from our rest pose,
// starting from its own rest pose; the hips move like ours scaled by the leg-length ratio, their height set so that the
// lower ankle is as far above its rest height as ours (feet on the floor, the seat a seat, the back on the mattress)
const OLD_CLIPS = [];
const SEAT_DY = 0.235 - 0.139, KNEE_DROP = 0.12, FOOT_FWD = 0.08;   // FOOT_FWD: seated, the feet a little forward so the
                                                // calves clear the seat's front edge                  // hip joint over the seat: his (room.html's chair anchor, 0.735 m over the
                                                // pivot, the seat top at 0.505) less ours (0.639 over a 0.50 m seat)
// the first character's skin (every 4th vertex), to set his height from his own lowest point
const OLD_SKIN = await (async () => { const d = await io.read(path.join(WEB, "boy.glb")), sk = d.getRoot().listSkins()[0], out = [];
  const js = sk.listJoints().map(j => j.getName()), ibm = sk.getInverseBindMatrices(), e = [];
  const IB = js.map((_, i) => new THREE.Matrix4().fromArray(ibm.getElement(i, e)));
  for (const prim of d.getRoot().listMeshes()[0].listPrimitives()) { const P = prim.getAttribute("POSITION"), J = prim.getAttribute("JOINTS_0"), W = prim.getAttribute("WEIGHTS_0");
    for (let i = 0; i < P.getCount(); i += 4) out.push([new THREE.Vector3(...P.getElement(i, [])), J.getElement(i, []), W.getElement(i, [])]); }
  return {js, IB, verts: out}; })();
const TRUNK = /^(Hips|Spine\d*|neck|Head)$/;
function lowestOld(o, trunk = false) {           // his lowest skin (of the trunk and head only, with `trunk`)
  const M = OLD_SKIN.js.map((n, i) => (o[n] ? o[n].matrixWorld : new THREE.Matrix4()).clone().multiply(OLD_SKIN.IB[i])), v = _v(), acc = _v(); let lo = Infinity;
  for (const [p, j, w] of OLD_SKIN.verts) { if (trunk && !TRUNK.test(OLD_SKIN.js[j[w.indexOf(Math.max(...w))]])) continue;
    acc.set(0, 0, 0); for (let k = 0; k < 4; k++) if (w[k] > 0) acc.addScaledVector(v.copy(p).applyMatrix4(M[j[k]]), w[k]); if (acc.y < lo) lo = acc.y; }
  return lo;
}
const lowestOurs = (b, trunk) => skinLowest(b, () => true, trunk ? j => TRUNK.test(joints[j]) : null);
// a bone's direction in each rest pose (to its child down the chain): the two rests differ a little (our arms rest 12
// degrees closer in), so each bone also gets the turn that lines its rest direction up with the first character's
const CHAIN = {Hips: "Spine02", Spine02: "Spine01", Spine01: "Spine", Spine: "neck", neck: "Head"};
for (const S_ of ["Left", "Right"]) Object.assign(CHAIN, {[S_ + "Shoulder"]: S_ + "Arm", [S_ + "Arm"]: S_ + "ForeArm", [S_ + "ForeArm"]: S_ + "Hand",
  [S_ + "UpLeg"]: S_ + "Leg", [S_ + "Leg"]: S_ + "Foot", [S_ + "Foot"]: S_ + "ToeBase"});
function toOld(channels, dur) {
  const nb = fk(NEW, channels, "to-old"), ob = fk(OLD, [], "old"), r0n = fk(NEW, [], "rest-n").at(0), r0o = fk(OLD, [], "rest-o").at(0);
  const bones = Object.keys(OLD).filter(n => n !== "Armature"), wq = o => o.getWorldQuaternion(new THREE.Quaternion()), wp = o => o.getWorldPosition(_v());
  const align = n => CHAIN[n] && r0n[CHAIN[n]] ? new THREE.Quaternion().setFromUnitVectors(wp(r0o[CHAIN[n]]).sub(wp(r0o[n])).normalize(), wp(r0n[CHAIN[n]]).sub(wp(r0n[n])).normalize()) : new THREE.Quaternion();
  // old world = our world x our rest^-1 x (old rest direction turned onto ours) x old rest
  const restN = Object.fromEntries(bones.filter(n => r0n[n]).map(n => [n, wq(r0n[n]).invert().multiply(align(n)).multiply(wq(r0o[n]))]));
  const legN = SK.Hips.pos.y - newRestAnkle, legO = REF.Hips.pos[1] - oldRestAnkle, k = legO / legN;
  const n = Math.max(2, Math.round(dur * 30) + 1), times = [...Array(n)].map((_, i) => i * dur / (n - 1));
  const out = Object.fromEntries(bones.map(b => [b, []])), hips = [];
  for (const t of times) {
    const b = nb.at(t), o = ob.at(0), W = {};
    for (const name of bones) if (restN[name]) W[name] = wq(b[name]).multiply(restN[name]);
    for (const name of bones) if (W[name]) {
      const par = OLD[name].parent; o[name].quaternion.copy((W[par] ? W[par].clone() : wq(o[name].parent)).invert().multiply(W[name])); }
    // the hips: ours scaled by the leg ratio, then raised or lowered so his lowest point is where ours is (soles on
    // the floor); lying (the trunk more level than upright), the lowest point of his trunk (his back on the mattress)
    const h = wp(b.Hips).multiplyScalar(k);
    o.Hips.position.set(h.x / 0.01, h.y / 0.01, h.z / 0.01); o.Hips.parent.updateMatrixWorld(true);
    const trunkUp = wp(b.neck).sub(wp(b.Hips)).normalize().y, lying = Math.abs(trunkUp) < 0.6;
    h.y += (lying ? lowestOurs(b, true) : Math.max(0, lowestOurs(b, false))) - lowestOld(o, lying);   // (never under the floor)
    o.Hips.position.y = h.y / 0.01; o.Hips.parent.updateMatrixWorld(true);
    // seated (thighs level, back upright): his hip joint sits SEAT_DY higher over the seat than ours, so his hips go up
    // by that much and the legs reach back down by IK to where his feet were (flat, as they were)
    const thigh = Math.max(...["Left", "Right"].map(S_ => Math.abs(wp(b[S_ + "Leg"]).sub(wp(b[S_ + "UpLeg"])).normalize().y)));
    const sitW = trunkUp > 0.7 ? Math.min(1, Math.max(0, (0.75 - thigh) / 0.35)) : 0;
    if (sitW > 0) {
      const ft = ["Left", "Right"].map(S_ => wp(o[S_ + "Foot"]));
      h.y = Math.max(h.y, wp(b.Hips).y + SEAT_DY * sitW + (h.y - wp(b.Hips).y) * (1 - sitW));
      o.Hips.position.y = h.y / 0.01; o.Hips.parent.updateMatrixWorld(true);
      // his shins are long for the room's chair: with his feet on the floor his knees would drop below the seat's front
      // edge, so a foot rises (hovers, as with the first clips) until its knee is at most KNEE_DROP under the hip joint;
      // it also goes FOOT_FWD forward (he faces +z), so the calf clears the seat's front edge
      ["Left", "Right"].forEach((S_, i) => { const knee = wp(o[S_ + "Leg"]), fwd = knee.clone().sub(wp(o[S_ + "UpLeg"])); fwd.y = 0;
        const pole = knee.clone().add(fwd.normalize().multiplyScalar(0.3)).add(new THREE.Vector3(0, 0.1, 0));
        for (let lift = 0; lift <= 0.12; lift += 0.005) {
          reach(o[S_ + "UpLeg"], o[S_ + "Leg"], o[S_ + "Foot"], ft[i].clone().add(new THREE.Vector3(0, lift * sitW, FOOT_FWD * sitW)), pole);
          if (wp(o[S_ + "Leg"]).y >= h.y - KNEE_DROP) break; }
        o[S_ + "Foot"].quaternion.copy(wq(o[S_ + "Leg"]).invert().multiply(W[S_ + "Foot"])); o[S_ + "Foot"].updateMatrixWorld(true); });
    }
    for (const name of bones) if (W[name]) out[name].push(...o[name].quaternion.toArray());
    hips.push(h.x / 0.01, h.y / 0.01, h.z / 0.01);
  }
  return [...bones.filter(b => restN[b]).map(b => ({node: b, path: "rotation", times, values: out[b]})), {node: "Hips", path: "translation", times, values: hips}];
}


// ------------------------------------------------------------------ Quaternius' Universal Animation Library (CC0)
// Its rig (UE-mannequin style, T-pose, facing +z, every bone bending about its local +x) is mapped onto ours: our skeleton
// is posed into its T-pose bone by bone (limb directions, then the elbow and knee hinges and the palms, like
// build_boy.py does with the old rig), which gives each bone a fixed offset; a UAL frame's world rotations times the
// offsets are ours. The hips follow the UAL pelvis (scaled by leg length) with the feet held at the same height above
// their rest. In place: the Standard pack has no root motion.
const UAL_FILE = process.env.UAL || "/opt/ual/Universal Animation Library[Standard]/Unreal-Godot/UAL1_Standard.glb";
const UMAP = {pelvis: "Hips", spine_01: "Spine02", spine_02: "Spine01", spine_03: "Spine", neck_01: "neck", Head: "Head"};
for (const [s_, S_] of [["l", "Left"], ["r", "Right"]]) {
  Object.assign(UMAP, {[`clavicle_${s_}`]: `${S_}Shoulder`, [`upperarm_${s_}`]: `${S_}Arm`, [`lowerarm_${s_}`]: `${S_}ForeArm`, [`hand_${s_}`]: `${S_}Hand`,
    [`thigh_${s_}`]: `${S_}UpLeg`, [`calf_${s_}`]: `${S_}Leg`, [`foot_${s_}`]: `${S_}Foot`, [`ball_${s_}`]: `${S_}ToeBase`});
  for (const [f, F] of [["thumb", "Thumb"], ["index", "Index"], ["middle", "Middle"], ["ring", "Ring"], ["pinky", "Pinky"]])
    for (const k of [1, 2, 3]) UMAP[`${f}_0${k}_${s_}`] = `${S_}Hand${F}${k}`;
}
const MINE = Object.fromEntries(Object.entries(UMAP).map(([u, m]) => [m, u]));
// the child joint that gives each bone its direction (ours, UAL's)
const CHILD = {Spine02: "Spine01", Spine01: "Spine", Spine: "neck", neck: "Head"};
for (const S_ of ["Left", "Right"]) {
  Object.assign(CHILD, {[`${S_}Shoulder`]: `${S_}Arm`, [`${S_}Arm`]: `${S_}ForeArm`, [`${S_}ForeArm`]: `${S_}Hand`, [`${S_}Hand`]: `${S_}HandMiddle1`,
    [`${S_}UpLeg`]: `${S_}Leg`, [`${S_}Leg`]: `${S_}Foot`, [`${S_}Foot`]: `${S_}ToeBase`});
  for (const F of ["Thumb", "Index", "Middle", "Ring", "Pinky"]) { CHILD[`${S_}Hand${F}1`] = `${S_}Hand${F}2`; CHILD[`${S_}Hand${F}2`] = `${S_}Hand${F}3`; }
}
let UAL = null;
async function loadUAL() {
  if (!fs.existsSync(UAL_FILE)) { console.warn("  no UAL file:", UAL_FILE); return null; }
  const ud = await io.read(UAL_FILE), ur = ud.getRoot(), skin = ur.listSkins()[0], joints = skin.listJoints(), jn = new Set(joints.map(j => j.getName()));
  const U = {};
  for (const j of joints) U[j.getName()] = {parent: jn.has(j.getParentNode()?.getName()) ? j.getParentNode().getName() : null,
    p: V(j.getTranslation()), q: Q(j.getRotation()), s: V(j.getScale())};
  const rest = fk(U, [], "rest", 1).at(0), W = {};
  for (const n of Object.keys(U)) W[n] = {p: rest[n].getWorldPosition(new THREE.Vector3()), q: rest[n].getWorldQuaternion(new THREE.Quaternion())};
  // UAL's palms, measured on its mannequin's skin like ours
  const palms = {};
  for (const [s_, S_] of [["l", "Left"], ["r", "Right"]]) {
    const ids = new Set(joints.map((j, i) => /^(hand|index|middle|ring|pinky|thumb)_/.test(j.getName()) && j.getName().endsWith("_" + s_) ? i : -1).filter(i => i >= 0));
    const inv = new THREE.Matrix4().fromArray(skin.getInverseBindMatrices().getElement(joints.findIndex(j => j.getName() === "hand_" + s_), [])), pts = [];
    for (const m of ur.listMeshes()) for (const prim of m.listPrimitives()) {
      const P = prim.getAttribute("POSITION"), J = prim.getAttribute("JOINTS_0"), Wt = prim.getAttribute("WEIGHTS_0"); if (!J) continue;
      for (let i = 0, j = [], w = [], q = []; i < P.getCount(); i++) { J.getElement(i, j); Wt.getElement(i, w); let sum = 0; for (let k = 0; k < 4; k++) if (ids.has(j[k])) sum += w[k];
        if (sum > 0.9) pts.push(new THREE.Vector3(...P.getElement(i, q)).applyMatrix4(inv)); }
    }
    palms[S_] = palmOf(pts).applyQuaternion(W["hand_" + s_].q);
  }
  const anims = Object.fromEntries(ur.listAnimations().map(a => [a.getName(), a]));
  return {U, W, palms, anims};
}
// our skeleton in UAL's T-pose: world rotations per bone
function canonical(ual) {
  const b = fk(NEW, [], "canon").at(0), W = ual.W, wp = n => b[n].getWorldPosition(new THREE.Vector3()), wq = n => b[n].getWorldQuaternion(new THREE.Quaternion());
  const turn = (n, R) => { const pq = b[n].parent.getWorldQuaternion(new THREE.Quaternion()); b[n].quaternion.copy(pq.invert().multiply(R.clone().multiply(wq(n)))); b[n].updateMatrixWorld(true); };
  const aim = n => { const c = CHILD[n]; if (!c || !MINE[n] || !MINE[c]) return;
    const mine = wp(c).sub(wp(n)).normalize(), theirs = W[MINE[c]].p.clone().sub(W[MINE[n]].p).normalize();
    turn(n, new THREE.Quaternion().setFromUnitVectors(mine, theirs)); };
  const twist = (n, have, want) => { const a = wp(CHILD[n]).sub(wp(n)).normalize();
    const h = have.clone().addScaledVector(a, -have.dot(a)).normalize(), w = want.clone().addScaledVector(a, -want.dot(a)).normalize();
    turn(n, new THREE.Quaternion().setFromAxisAngle(a, Math.atan2(a.dot(new THREE.Vector3().crossVectors(h, w)), h.dot(w)))); };
  const xOf = n => new THREE.Vector3(1, 0, 0).applyQuaternion(W[n].q);       // UAL's hinge (flex about +x)
  const HINGE_LOCAL = {ForeArm: {Left: [-0.8, 0, 0.6], Right: [-0.8, 0, -0.6]}, Leg: {Left: [1, 0, 0], Right: [1, 0, 0]}};
  const hingeOf = (n, side, kind) => new THREE.Vector3(...HINGE_LOCAL[kind][side]).normalize().applyQuaternion(wq(n));
  for (const n of ["Spine02", "Spine01", "Spine", "neck"]) aim(n);
  for (const S_ of ["Left", "Right"]) {
    const s_ = S_[0].toLowerCase();
    aim(`${S_}Shoulder`); aim(`${S_}Arm`); aim(`${S_}ForeArm`);
    twist(`${S_}Arm`, hingeOf(`${S_}ForeArm`, S_, "ForeArm"), xOf(`lowerarm_${s_}`)); aim(`${S_}ForeArm`);
    aim(`${S_}Hand`);
    twist(`${S_}Hand`, HANDF[S_].Z.clone().applyQuaternion(wq(`${S_}Hand`)), ual.palms[S_]);
    for (const F of ["Thumb", "Index", "Middle", "Ring", "Pinky"]) { aim(`${S_}Hand${F}1`); aim(`${S_}Hand${F}2`); }
    aim(`${S_}UpLeg`); aim(`${S_}Leg`);
    twist(`${S_}UpLeg`, hingeOf(`${S_}Leg`, S_, "Leg"), xOf(`calf_${s_}`)); aim(`${S_}Leg`);
    aim(`${S_}Foot`);
  }
  const off = {};
  for (const [m, u] of Object.entries(MINE)) off[m] = W[u].q.clone().invert().multiply(wq(m));
  return off;
}
// two-bone IK (as room.html's reach()): turn `upper` and `lower` so that `end` reaches `target`, the knee towards `pole`
const _v = () => new THREE.Vector3();
function aimBone(bone, from, to) {
  const a = bone.getWorldPosition(_v()), q = new THREE.Quaternion().setFromUnitVectors(from.clone().sub(a).normalize(), to.clone().sub(a).normalize());
  const wq = bone.getWorldQuaternion(new THREE.Quaternion()).premultiply(q), pq = bone.parent.getWorldQuaternion(new THREE.Quaternion());
  bone.quaternion.copy(pq.invert().multiply(wq)); bone.updateMatrixWorld(true);
}
function reach(upper, lower, end, target, pole) {
  const S = upper.getWorldPosition(_v()), E = lower.getWorldPosition(_v()), H = end.getWorldPosition(_v());
  const a = S.distanceTo(E), b = E.distanceTo(H), D = target.clone().sub(S), d = Math.min(Math.max(D.length(), Math.abs(a - b) + 1e-4), a + b - 1e-4);
  D.normalize(); const x = (a * a - b * b + d * d) / (2 * d), h = Math.sqrt(Math.max(0, a * a - x * x));
  const N = pole.clone().sub(S); N.addScaledVector(D, -N.dot(D)).normalize();
  aimBone(upper, E, S.clone().addScaledVector(D, x).addScaledVector(N, h));
  aimBone(lower, end.getWorldPosition(_v()), target);
}
// a UAL clip on our skeleton, resampled at 30 fps, every bone keyed. Feet: where a foot rests (near its floor height
// and nearly still) it is pinned and the leg reaches it by IK, so nothing slides; `seat` lifts the hips by up to that much
// as he sits (UAL's chair is lower than the room's), the feet staying where they were
function fromUAL(ual, off, name, as, {seat = 0} = {}) {
  const a = ual.anims[name], ch = [];
  for (const c of a.listChannels()) { const sm = c.getSampler(), acc = x => { const o = [], e = []; for (let i = 0; i < x.getCount(); i++) o.push(...x.getElement(i, e)); return o; };
    ch.push({node: c.getTargetNode().getName(), path: c.getTargetPath(), times: acc(sm.getInput()), values: acc(sm.getOutput())}); }
  const dur = Math.max(...ch.map(c => c.times[c.times.length - 1])), n = Math.max(2, Math.round(dur * 30) + 1), times = [...Array(n)].map((_, i) => i * dur / (n - 1));
  const u = fk(ual.U, ch, name, 1), mine = fk(NEW, [], as);
  const uRestAnkle = Math.min(ual.W.foot_l.p.y, ual.W.foot_r.p.y), uRestPelvis = ual.W.pelvis.p;
  const k = (SK.Hips.pos.y - newRestAnkle) / (uRestPelvis.y - uRestAnkle);   // leg-length ratio
  const armInv = new THREE.Matrix4().makeScale(100, 100, 100), sides = ["Left", "Right"];
  // pose frame i: rotations from UAL, hips from its pelvis with the feet at UAL's height; returns the bones
  const pose = i => {
    const ub = u.at(times[i]), mb = mine.at(0);
    for (const b of order) {
      const o = mb[b];
      if (MINE[b]) { const uq = ub[MINE[b]].getWorldQuaternion(new THREE.Quaternion()).multiply(off[b]);
        o.quaternion.copy(o.parent.getWorldQuaternion(new THREE.Quaternion()).invert().multiply(uq)); }
      else o.quaternion.copy(NEW[b].q);
      o.updateMatrixWorld(true);
    }
    const hipsW = SK.Hips.pos.clone().add(ub.pelvis.getWorldPosition(_v()).sub(uRestPelvis).multiplyScalar(k));
    mb.Hips.position.copy(hipsW.clone().applyMatrix4(armInv)); mb.Hips.updateMatrixWorld(true);
    const dU = Math.min(ub.foot_l.getWorldPosition(_v()).y, ub.foot_r.getWorldPosition(_v()).y) - uRestAnkle;
    hipsW.y += dU * k - (ankle(mb) - newRestAnkle);
    mb.Hips.position.copy(hipsW.clone().applyMatrix4(armInv)); mb.Hips.updateMatrixWorld(true);
    return mb;
  };
  // pass 1: the feet's paths, and how far down he sits (0 standing .. 1 at the clip's lowest hips)
  const feet = {Left: [], Right: []}, hipsY = [];
  for (let i = 0; i < n; i++) { const mb = pose(i); for (const S_ of sides) feet[S_].push(mb[S_ + "Foot"].getWorldPosition(_v())); hipsY.push(mb.Hips.getWorldPosition(_v()).y); }
  // how far he is down in a seat: 0 standing (hips at rest height) .. 1 from 25 cm lower
  const sitK = i => seat ? Math.min(1, Math.max(0, (SK.Hips.pos.y - hipsY[i]) / 0.25)) : 0;
  // contacts: low and slow; each run of contact frames pinned at its mean
  const pin = {Left: [], Right: []};
  for (const S_ of sides) {
    const P = feet[S_], floor = Math.min(...P.map(p => p.y)), on = P.map((p, i) => p.y < floor + 0.025 &&
      P[Math.min(n - 1, i + 1)].clone().sub(P[Math.max(0, i - 1)]).setY(0).length() / (2 / 30) < 0.25);
    for (let i = 0; i < n;) { if (!on[i]) { pin[S_][i++] = null; continue; }
      let j = i; while (j < n && on[j]) j++;
      const m = P.slice(i, j).reduce((s, p) => s.add(p), _v()).divideScalar(j - i);
      for (let t = i; t < j; t++) pin[S_][t] = m.clone(); i = j; }
  }
  // pass 2: seat lift, then the legs reach their pinned (or pass-1) foot positions
  const outQ = Object.fromEntries(order.map(b => [b, []])), outT = [];
  for (let i = 0; i < n; i++) {
    const mb = pose(i), lift = seat * sitK(i);
    if (lift) { mb.Hips.position.y += lift * CM; mb.Hips.updateMatrixWorld(true); }
    for (const S_ of sides) {
      const target = pin[S_][i] || feet[S_][i], knee = mb[S_ + "Leg"].getWorldPosition(_v()), fwd = new THREE.Vector3(0, 0, 0.3);
      if (pin[S_][i] || lift) reach(mb[S_ + "UpLeg"], mb[S_ + "Leg"], mb[S_ + "Foot"], target, knee.add(fwd));
    }
    for (const b of order) outQ[b].push(...mb[b].quaternion.toArray());
    outT.push(...mb.Hips.position.toArray());
  }
  const channels = order.map(b => ({node: b, path: "rotation", times, values: outQ[b]}));
  channels.push({node: "Hips", path: "translation", times, values: outT});
  const contacts = Object.fromEntries(sides.map(S_ => [S_, pin[S_].map((p, i) => p ? i : -1).filter(i => i >= 0)]));
  // in place, a walking foot slides back on the floor at the walking speed: the room moves him forward at that speed
  let speed = 0, nS = 0;
  for (const S_ of sides) { const P = feet[S_], floor = Math.min(...P.map(p => p.y));
    for (let i = 1; i < n; i++) if (P[i].y < floor + 0.02) { speed += Math.abs(P[i].z - P[i - 1].z) * 30; nS++; } }
  return {name: as, channels, duration: dur, hips0: outT.slice(0, 3).map(v => v / CM), contacts, stanceSpeed: nS ? speed / nS : 0};
}
// the room's names (#63's list) for what UAL Standard has
// (the room's chair seat is at 0.50 m: the seated clips' hips go up to sit on it)
const SEAT_LIFT = 0.12;                           // measured: the buttocks then rest at 0.49 m (1 cm into the cushion)
const UAL_CLIPS = {stand_idle: ["Idle_Loop"], walk: ["Walk_Loop"], sit_down_chair: ["Sitting_Enter", {seat: SEAT_LIFT}],
  stand_up_chair: ["Sitting_Exit", {seat: SEAT_LIFT}], sit_idle_upright: ["Sitting_Idle_Loop", {seat: SEAT_LIFT}],
  take_item: ["PickUp_Table"], door_open_pull: ["Interact"]};

// ------------------------------------------------------------------ authored clips (original work, CC0)
// What UAL Standard lacks (the bed set first) is keyed here from its poses: the whole body turned about the hips,
// hands and feet placed by IK, a few bones turned in world axes, then keys eased into each other at 30 fps. Heights are
// the room's (floor 0, mattress top MATTRESS); the lowest skin is put exactly on the surface it lies on.
const MATTRESS = 0.70;
const ease = t => t * t * (3 - 2 * t);
// a pose: local rotations of every bone + the hips' world position (m)
function poseOfChannels(channels, t) {
  const b = fk(NEW, channels, "pose").at(t);
  return {q: Object.fromEntries(order.map(n => [n, b[n].quaternion.clone()])), hips: b.Hips.getWorldPosition(_v())};
}
function bonesOf(pose) {                        // FK bones of a pose, to edit with IK / world turns
  const b = fk(NEW, [], "edit").at(0);
  for (const n of order) b[n].quaternion.copy(pose.q[n]);
  b.Hips.position.copy(pose.hips.clone().multiplyScalar(CM)); b.Hips.parent.updateMatrixWorld(true); b.Hips.updateMatrixWorld(true);
  return b;
}
function poseOfBones(b) { b.Hips.updateMatrixWorld(true); return {q: Object.fromEntries(order.map(n => [n, b[n].quaternion.clone()])), hips: b.Hips.getWorldPosition(_v())}; }
function turnWorld(b, n, axis, deg) {           // turn bone n (and what hangs on it) about a world axis through its joint
  const R = new THREE.Quaternion().setFromAxisAngle(axis.clone().normalize(), deg * Math.PI / 180);
  const wq = b[n].getWorldQuaternion(new THREE.Quaternion()).premultiply(R), pq = b[n].parent.getWorldQuaternion(new THREE.Quaternion());
  b[n].quaternion.copy(pq.invert().multiply(wq)); b[n].updateMatrixWorld(true);
}
function turnWorldQ(b, n, R) {                  // turn bone n by a world rotation R about its joint
  const wq = b[n].getWorldQuaternion(new THREE.Quaternion()).premultiply(R), pq = b[n].parent.getWorldQuaternion(new THREE.Quaternion());
  b[n].quaternion.copy(pq.invert().multiply(wq)); b[n].updateMatrixWorld(true);
}
// the gaze: his face turned to a point, `neck` of the turn in the neck and the rest in the head. In the bind pose he
// looks along +z; the gaze is that direction carried by the head's turn from its bind pose
let HEAD0 = null;
function headTurn(b) {                          // the head's world turn from its bind pose
  HEAD0 ??= fk(NEW, [], "rest").at(0).Head.getWorldQuaternion(new THREE.Quaternion()).invert();
  return b.Head.getWorldQuaternion(new THREE.Quaternion()).multiply(HEAD0);
}
function lookAt(b, target, neck = 0.4) {
  for (const [n, share] of [["neck", neck], ["Head", 1]]) {
    const eyes = wpos(b, "LeftEye").lerp(wpos(b, "RightEye"), 0.5);
    const gaze = new THREE.Vector3(0, 0, 1).applyQuaternion(headTurn(b));
    const R = new THREE.Quaternion().setFromUnitVectors(gaze, target.clone().sub(eyes).normalize());
    turnWorldQ(b, n, new THREE.Quaternion().slerp(R, share));
  }
}
function turnBody(b, axis, deg) {               // the whole body about the hips
  turnWorld(b, "Hips", axis, deg);
}
function placeHips(b, p) { b.Hips.position.copy(p.clone().multiplyScalar(CM)); b.Hips.updateMatrixWorld(true); }
function armTo(b, side, target, pole) { reach(b[side + "Arm"], b[side + "ForeArm"], b[side + "Hand"], target, pole); }
function legTo(b, side, target, pole) { reach(b[side + "UpLeg"], b[side + "Leg"], b[side + "Foot"], target, pole); }
const wpos = (b, n) => b[n].getWorldPosition(_v());
// the skin in a pose (bind positions skinned by the bones): for contact with the mattress / floor
const SKIN_V = [];
for (const prim of mesh.listPrimitives()) { const P = prim.getAttribute("POSITION"), J = prim.getAttribute("JOINTS_0"), W = prim.getAttribute("WEIGHTS_0");
  for (let i = 0; i < P.getCount(); i += 4) SKIN_V.push([V(P.getElement(i, [])), J.getElement(i, []), W.getElement(i, [])]); }
const IBM = joints.map(n => world(n).invert());
const ALL_V = [];                               // every vertex, for the deformation check at the end
for (const prim of mesh.listPrimitives()) { const P = prim.getAttribute("POSITION"), J = prim.getAttribute("JOINTS_0"), W = prim.getAttribute("WEIGHTS_0");
  for (let i = 0; i < P.getCount(); i++) ALL_V.push([P.getElement(i, []), J.getElement(i, []), W.getElement(i, [])]); }
const CHECKS = [];                              // [file, clip name, channels, duration]: every clip, for the deformation check
function skinLowest(b, filter = () => true, byJoint = null) {   // byJoint(dominant joint index): which vertices count
  const M = joints.map((n, i) => b[n].matrixWorld.clone().multiply(IBM[i])), v = _v(), acc = _v();
  let lo = Infinity;
  for (const [p, j, w] of SKIN_V) { if (byJoint && !byJoint(j[w.indexOf(Math.max(...w))])) continue; acc.set(0, 0, 0); for (let k = 0; k < 4; k++) if (w[k] > 0) acc.addScaledVector(v.copy(p).applyMatrix4(M[j[k]]), w[k]);
    if (filter(acc) && acc.y < lo) lo = acc.y; }
  return lo;
}
function onSurface(b, y) {                      // lower or raise him so his lowest skin rests on height y
  const lo = skinLowest(b); placeHips(b, wpos(b, "Hips").add(new THREE.Vector3(0, y - lo, 0)));
}
// keys [[t, pose], ...] -> channels at 30 fps (eased slerp between keys); `breathe` adds a breath every `period` s
function keyed(keys, {loop = false, breathe = 0, period = 4} = {}) {
  const dur = keys[keys.length - 1][0], n = Math.max(2, Math.round(dur * 30) + 1), times = [...Array(n)].map((_, i) => i * dur / (n - 1));
  const outQ = Object.fromEntries(order.map(b => [b, []])), outT = [];
  for (const t of times) {
    let i = 0; while (i < keys.length - 2 && t > keys[i + 1][0]) i++;
    const [t0, A] = keys[i], [t1, B] = keys[Math.min(i + 1, keys.length - 1)], u = t1 > t0 ? ease(Math.min(1, Math.max(0, (t - t0) / (t1 - t0)))) : 0;
    const br = breathe ? breathe * Math.sin(2 * Math.PI * t / period) : 0;
    for (const bn of order) {
      const q = A.q[bn].clone().slerp(B.q[bn], u);
      if (br && (bn === "Spine01" || bn === "Spine")) q.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), br * Math.PI / 180));
      outQ[bn].push(...q.toArray());
    }
    outT.push(...A.hips.clone().lerp(B.hips, u).multiplyScalar(CM).toArray());
  }
  const channels = order.map(b => ({node: b, path: "rotation", times, values: outQ[b]}));
  channels.push({node: "Hips", path: "translation", times, values: outT});
  return {channels, duration: dur, hips0: outT.slice(0, 3).map(v => v / CM)};
}
const X = new THREE.Vector3(1, 0, 0), Y = new THREE.Vector3(0, 1, 0), Z = new THREE.Vector3(0, 0, 1);
const halfway = (a, b) => ({q: Object.fromEntries(order.map(n => [n, a.q[n].clone().slerp(b.q[n], 0.5)])), hips: a.hips.clone().lerp(b.hips, 0.5)});
// the bed set. In each clip's own frame he lies with his head towards -z and his feet towards +z (like the old sleep
// clip), on a mattress whose top is at MATTRESS; root under his hips
function bodyFrame(b) {                         // L: towards the head, Lat: his left, F: the way his front faces
  const hips = wpos(b, "Hips"), L = wpos(b, "neck").sub(hips).normalize();
  const Lat = wpos(b, "LeftUpLeg").sub(wpos(b, "RightUpLeg")); Lat.addScaledVector(L, -Lat.dot(L)).normalize();
  return {hips, L, Lat, F: new THREE.Vector3().crossVectors(Lat, L)};
}
const at = (o, ...terms) => { const p = o.clone(); for (const [v, k] of terms) p.addScaledVector(v, k); return p; };
function torsoOn(b, y) {                        // his back (or side) on the surface: the lowest skin near the trunk
  const hips = wpos(b, "Hips"), neck = wpos(b, "neck"), mid = hips.clone().lerp(neck, 0.5);
  const lo = skinLowest(b, p => p.distanceTo(mid) < 0.42);
  placeHips(b, hips.add(new THREE.Vector3(0, y - lo, 0)));
}
const PILLOW = 0.09;                            // the pillow lifts the back of his head this much above the mattress
function headOnPillow(b, up) {                  // tip the neck and head until the head's lowest skin is PILLOW above
  for (let i = 0; i < 12; i++) {
    const head = wpos(b, "Head"), lo = skinLowest(b, p => p.distanceTo(head) < 0.16);
    if (lo >= MATTRESS + PILLOW - 0.005) break;
    turnWorld(b, "neck", up, 3); turnWorld(b, "Head", up, 1.5);
  }
}
function bedPoses(stand, sit) {
  // on his back: the standing idle laid down, legs straightened side by side (knees a touch bent, heels on the mattress),
  // one hand resting on the belly and the other beside the hip, the head raised a little by the pillow
  const back = bonesOf(stand);
  placeHips(back, new THREE.Vector3(0, 1, 0)); turnBody(back, X, -90);
  turnWorld(back, "neck", X, 6); turnWorld(back, "Head", X, 3);         // the head raised by the pillow (+x tips the chin to the chest)
  torsoOn(back, MATTRESS);
  { const {hips, L, Lat, F} = bodyFrame(back);
    for (const [S_, k] of [["Left", 1], ["Right", -1]]) {
      legTo(back, S_, at(hips, [L, -0.79], [Lat, k * 0.12], [F, -0.03]), at(hips, [L, -0.4], [F, 0.5], [Lat, k * 0.1]));
      turnWorld(back, S_ + "Foot", Lat, -15);
    }
    // hands resting on the mattress beside the hips, palms down, elbows a little out (nothing crosses the body)
    for (const [S_, k] of [["Left", 1], ["Right", -1]])
      armTo(back, S_, at(hips, [Lat, k * 0.27], [F, -0.05], [L, 0.02]), at(wpos(back, S_ + "Arm"), [Lat, k * 0.35], [L, -0.15], [F, 0.05]));
    torsoOn(back, MATTRESS); headOnPillow(back, X); }
  // on a side: the seated pose (hips and knees bent) eased towards standing, rolled onto that side; the lower arm under
  // the pillow (hand by the face), the upper hand on the mattress in front of the chest, the knees one over the other
  const side = S_ => {
    const blend = {q: Object.fromEntries(order.map(n => [n, sit.q[n].clone().slerp(stand.q[n], 0.5)])), hips: sit.hips.clone()};
    const b = bonesOf(blend); placeHips(b, new THREE.Vector3(0, 1, 0));
    turnBody(b, X, -90); turnBody(b, Z, S_ === "Left" ? 90 : -90);
    torsoOn(b, MATTRESS);
    const {hips, L, Lat, F} = bodyFrame(b), down = S_, up = S_ === "Left" ? "Right" : "Left", k = S_ === "Left" ? 1 : -1;  // k: Lat points down
    legTo(b, down, at(hips, [L, -0.52], [F, 0.42], [Lat, k * 0.10]), at(hips, [L, -0.15], [F, 0.8]));
    legTo(b, up, at(hips, [L, -0.48], [F, 0.50], [Lat, -k * 0.02]), at(hips, [L, -0.12], [F, 0.85], [Lat, -k * 0.05]));
    armTo(b, down, at(wpos(b, "Head"), [F, 0.10], [L, 0.06], [Lat, k * 0.06]), at(wpos(b, down + "Arm"), [F, 0.3], [L, -0.15]));
    armTo(b, up, at(wpos(b, "Spine"), [F, 0.22], [Lat, k * 0.2], [L, -0.10]), at(wpos(b, up + "Arm"), [F, 0.25], [Lat, -k * 0.15]));
    turnWorld(b, "neck", F, k * 6);
    torsoOn(b, MATTRESS);
    return poseOfBones(b);
  };
  return {back: poseOfBones(back), left: side("Left"), right: side("Right")};
}

// where a held thing's far end is: `len` m along the socket's +y (the chopsticks' tips; sockets are in the hand's cm)
function toolTip(b, socket, len) {
  const S = SOCKETS[socket], hq = b[S.parent].getWorldQuaternion(new THREE.Quaternion());
  return new THREE.Vector3(...S.p).multiplyScalar(0.01).applyQuaternion(hq).add(wpos(b, S.parent))
    .addScaledVector(new THREE.Vector3(0, 1, 0).applyQuaternion(new THREE.Quaternion(...S.q)).applyQuaternion(hq), len);
}
// put a held thing's far end on `target`: place(wrist) poses the arm and hand; the wrist moves by the miss, a few times
function toolTo(b, socket, len, target, wrist, place) {
  for (let i = 0; i < 4; i++) { place(wrist); wrist = wrist.clone().add(target.clone().sub(toolTip(b, socket, len))); }
  place(wrist);
}
// the hand turned so its fingers run along `fingers` and its palm faces `palm` (world directions)
function handFacing(b, side, fingers, palm) {
  const F = HANDF[side], Yw = fingers.clone().normalize(), Zw = palm.clone().addScaledVector(Yw, -palm.dot(Yw)).normalize();
  const Xw = new THREE.Vector3().crossVectors(Yw, Zw);
  const local = new THREE.Matrix4().makeBasis(new THREE.Vector3().crossVectors(F.Y, F.Z), F.Y, F.Z);   // hand-local palm frame
  const worldM = new THREE.Matrix4().makeBasis(Xw, Yw, Zw).multiply(local.clone().invert());
  const wq = new THREE.Quaternion().setFromRotationMatrix(worldM), pq = b[side + "Hand"].parent.getWorldQuaternion(new THREE.Quaternion());
  b[side + "Hand"].quaternion.copy(pq.invert().multiply(wq)); b[side + "Hand"].updateMatrixWorld(true);
}
// seated work at the desk (room heights: desk top DESK; keyboard 0.30 m in front of his chest, 5 cm above the desk,
// i.e. z = +0.03 in the clip's frame; mouse 0.35 m to his right of it): the upright seated idle, the hands on the keys by IK, palms down, the
// back upright and the gaze on the screen (its centre 0.61 m in front of his hips, 1.16 m up); `work(t)` gives each hand's small motion
const DESK = 0.97, KEYS = new THREE.Vector3(0, DESK + 0.05, 0.03), SCREEN = new THREE.Vector3(0, 1.16, 0.33);
function deskClip(sitClip, dur, work) {
  const keys = [], step = 1 / 6;
  for (let t = 0; t <= dur + 1e-6; t += step) {
    const tt = t >= dur - 1e-6 ? 0 : t;                 // the loop closes on its first key
    const b = bonesOf(poseOfChannels(sitClip.channels, tt % sitClip.duration));
    turnWorld(b, "Spine02", X, 2);
    for (const S_ of ["Left", "Right"]) {
      const w = work(S_, tt), sh = wpos(b, S_ + "Arm"), k = S_ === "Left" ? 1 : -1;
      armTo(b, S_, w.at, at(sh, [X, k * 0.22], [Y, -0.45], [Z, -0.1]));
      handFacing(b, S_, w.fingers || new THREE.Vector3(-k * 0.15, -0.25, 1), new THREE.Vector3(0, -1, 0));
    }
    lookAt(b, at(SCREEN, [X, 0.08 * Math.sin(tt * 0.7)], [Y, 0.03 * Math.sin(tt * 1.1)]));   // reading across the screen
    keys.push([t, poseOfBones(b)]);
  }
  return keyed(keys);
}
// small, uneven key presses: each hand bobs a few millimetres at its own rhythm and drifts a little along the row
const press = (S_, t, seed) => { const a = Math.sin(t * 7.3 + seed) * Math.sin(t * 2.1 + seed * 3); return Math.max(0, a) * 0.008; };

// a pose blended between two (per bone slerp, hips lerp)
const mixPose = (a, b, w) => ({q: Object.fromEntries(order.map(n => [n, a.q[n].clone().slerp(b.q[n], w)])), hips: a.hips.clone().lerp(b.hips, w)});
// a clip from a function of time: f(t) -> pose, sampled every `step` s (the keys are eased into each other)
function fromFn(dur, f, step = 1 / 10, opt = {}) { const keys = []; for (let t = 0; t <= dur + 1e-6; t += step) keys.push([Math.min(t, dur), f(Math.min(t, dur))]); return keyed(keys, opt); }
const clipPose = (r, t) => poseOfChannels(r.channels, ((t % r.duration) + r.duration) % r.duration);
// edit a pose: f(bones) changes it, the pose comes back
const edit = (pose, f) => { const b = bonesOf(pose); f(b); return poseOfBones(b); };

// finger poses. A pose: per finger the flex of its three joints (deg, + curls towards the palm) and its spread at the
// knuckle (deg, + away from the middle finger); the thumb: its base turned about the hand's own axes (x across the
// knuckles, y along the fingers, z the palm side), then its two joints' flex.
const FINGERS = ["Index", "Middle", "Ring", "Pinky"];
const POSES = {
  hand_relaxed: {L: {curl: [[14, 20, 10], [18, 24, 12], [22, 26, 14], [26, 28, 14]], spread: [-2, 0, -2, -4], thumb: {base: [10, 6, 0], flex: [8, 10]}}},
  hand_phone: {R: {curl: [[22, 78, 30], [24, 80, 30], [26, 80, 30], [34, 70, 25]], spread: [-1, 0, -1, -3], thumb: {base: [48, 24, 25], flex: [6, 10]}}},
  hand_chopsticks: {R: {curl: [[22, 18, 8], [36, 30, 14], [62, 60, 40], [70, 64, 40]], spread: [2, 0, -2, -4], thumb: {base: [30, 20, 20], flex: [10, 14]}}},
  hand_spoon: {R: {curl: [[30, 26, 12], [42, 40, 20], [64, 62, 40], [72, 66, 42]], spread: [1, 0, -2, -4], thumb: {base: [30, 22, 20], flex: [12, 16]}}},
  hand_type: {L: {curl: [[22, 30, 12], [24, 32, 14], [24, 32, 14], [24, 30, 12]], spread: [0, 0, -2, -4], thumb: {base: [14, 4, 0], flex: [6, 8]}}},
  hand_mouse: {R: {curl: [[10, 14, 8], [10, 14, 8], [24, 28, 14], [30, 34, 18]], spread: [0, 0, -3, -6], thumb: {base: [18, 10, 10], flex: [6, 6]}}},
};
for (const p of Object.values(POSES)) for (const [a, b] of [["L", "R"], ["R", "L"]]) if (!p[a]) p[a] = p[b] === POSES.hand_relaxed.L ? p[b] : null;
for (const [k, p] of Object.entries(POSES)) { if (!p.L) p.L = POSES.hand_relaxed.L; if (!p.R) p.R = k === "hand_type" ? p.L : POSES.hand_relaxed.L; }
const deg = Math.PI / 180;
function poseChannels(spec) {
  const ch = [];
  for (const [S, side] of [["L", "Left"], ["R", "Right"]]) {
    const P = spec[S], hand = SK[`${side}Hand`], hq = hand.quat;
    const F = HANDF[side], hx = F.T.clone().applyQuaternion(hq), hy = F.Y.clone().applyQuaternion(hq), palm = F.Z.clone().applyQuaternion(hq);
    const mid = SK[`${side}HandMiddle1`].pos;
    const posed = {};                            // world rotation of each finger bone once posed
    const put = (n, worldQ) => { posed[n] = worldQ; const pw = posed[SK[n].parent] || SK[SK[n].parent].quat;
      const lq = pw.clone().invert().multiply(worldQ); ch.push({node: n, path: "rotation", times: [0, 1], values: [...lq.toArray(), ...lq.toArray()]}); };
    FINGERS.forEach((F, fi) => {
      for (let k = 1; k <= 3; k++) {
        const n = `${side}Hand${F}${k}`, b = SK[n];
        // the parent's turn so far (world), then this joint's own: about the knuckle line (+ towards the palm), and at the
        // knuckle a spread about the palm's normal (+ away from the middle finger)
        const parentTurn = posed[b.parent] ? posed[b.parent].clone().multiply(SK[b.parent].quat.clone().invert()) : new THREE.Quaternion();
        const d = new THREE.Vector3(0, 1, 0).applyQuaternion(b.quat).applyQuaternion(parentTurn), pn = palm.clone().applyQuaternion(parentTurn);
        let turn = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3().crossVectors(d, pn).normalize(), P.curl[fi][k - 1] * deg);
        if (k === 1) { const away = Math.sign(new THREE.Vector3().crossVectors(pn, d).dot(b.pos.clone().sub(mid))) || 0;
          turn = turn.multiply(new THREE.Quaternion().setFromAxisAngle(pn, away * P.spread[fi] * deg)); }
        put(n, turn.multiply(parentTurn).multiply(b.quat).normalize());
      }
    });
    // thumb: its base swung towards the palm (base[0]) and towards the fingers (base[1]), turned about itself (base[2],
    // + rolls its pad towards the fingers); then its joints flex towards the palm
    const t1 = SK[`${side}HandThumb1`], d1 = new THREE.Vector3(0, 1, 0).applyQuaternion(t1.quat), roll = S === "R" ? -1 : 1;
    const base = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3().crossVectors(d1, hy).normalize(), P.thumb.base[1] * deg)
      .multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3().crossVectors(d1, palm).normalize(), P.thumb.base[0] * deg))
      .multiply(new THREE.Quaternion().setFromAxisAngle(d1, roll * P.thumb.base[2] * deg));
    put(`${side}HandThumb1`, base.clone().multiply(t1.quat));
    for (const k of [2, 3]) {
      const n = `${side}HandThumb${k}`, b = SK[n], parentTurn = posed[b.parent].clone().multiply(SK[b.parent].quat.clone().invert());
      const d = new THREE.Vector3(0, 1, 0).applyQuaternion(b.quat).applyQuaternion(parentTurn);
      const axis = new THREE.Vector3().crossVectors(d, palm).normalize();
      put(n, new THREE.Quaternion().setFromAxisAngle(axis, P.thumb.flex[k - 2] * deg).multiply(parentTurn).multiply(b.quat).normalize());
    }
  }
  return ch;
}

// ------------------------------------------------------------------ write
const report = [];
async function finish(d, file) {
  await d.transform(dedup(), resample({tolerance: 1e-4}), prune({keepLeaves: true, keepAttributes: true}), meshopt({encoder: MeshoptEncoder, level: "medium"}));
  await io.write(file, d); const kb = fs.statSync(file).size / 1024; report.push(`${path.basename(file)} ${kb.toFixed(0)} KB`); return kb;
}
const sit = await readClip(path.join(WEB, "boy.glb"));
const buf = root.listBuffers()[0] || doc.createBuffer();
for (const c of sit) { const r = retarget(c); addClip(doc, nodes, r.name, r.channels); }
// a blink: 0.22 s, closing fast and opening a little slower (room.html fires it every few seconds)
addClip(doc, {boy2: meshNode}, "blink", [{node: "boy2", path: "weights", times: [0, 0.07, 0.1, 0.22], values: [0, 1, 1, 0]}]);
await doc.transform(weld());
const kbMain = await finish(doc, path.join(OUT, "boy2.glb"));
// every other clip file: the same skeleton (no mesh), the retargeted clip
for (const f of OLD_FILES) {
  const d = new (await import("@gltf-transform/core")).Document(); d.createBuffer(); const sc = d.createScene();
  const {nodes: ns} = buildSkeleton(d, sc);
  for (const c of await readClip(path.join(WEB, f))) { const r = retarget(c); addClip(d, ns, r.name, r.channels);
    CHECKS.push([f.replace(/^boy_/, "boy2_"), r.name, r.channels, Math.max(...r.channels.map(ch => ch.times[ch.times.length - 1]))]); }
  await finish(d, path.join(OUT, f.replace(/^boy_/, "boy2_")));
}
{
  const d = new (await import("@gltf-transform/core")).Document(); d.createBuffer(); const sc = d.createScene();
  const {nodes: ns} = buildSkeleton(d, sc);
  for (const [name, spec] of Object.entries(POSES)) addClip(d, ns, name, poseChannels(spec));
  await finish(d, path.join(OUT, "boy2_hands.glb"));
}
if (process.env.ORIENT) {
  for (const f of ["boy_sleep.glb", "boy.glb", "boy_eat.glb"]) { const c = (await readClip(path.join(WEB, f)))[0], b = fk(OLD, c.channels, "x").at(0);
    const w = n => b[n].getWorldPosition(_v()).toArray().map(v => +v.toFixed(2));
    console.log(f, "hips", w("Hips"), "head", w("Head"), "Lfoot", w("LeftFoot"), "Rfoot", w("RightFoot"), "Lhand", w("LeftHand")); }
  process.exit(0);
}
UAL = await loadUAL();
if (UAL) {
  // all the new motion in one file, one animation per name of the room's list
  const off = canonical(UAL), rows = [];
  const d = new (await import("@gltf-transform/core")).Document(); d.createBuffer(); const sc = d.createScene();
  const {nodes: ns} = buildSkeleton(d, sc);
  for (const [as, [name, opt]] of Object.entries(UAL_CLIPS)) {
    if (!UAL.anims[name]) { console.warn("  UAL has no", name); continue; }
    const r = fromUAL(UAL, off, name, as, opt); addClip(d, ns, r.name, bodyOnly(r.channels));
    CHECKS.push(["boy2_motion.glb", r.name, bodyOnly(r.channels), r.duration]);
    rows.push(`  ${as} <- UAL ${name}: ${r.duration.toFixed(2)} s, hips at frame 0 [${r.hips0.map(v => v.toFixed(3)).join(", ")}] m, ` +
      `foot contact frames L ${r.contacts.Left.length}/R ${r.contacts.Right.length}` + (as === "walk" ? `, stance foot speed ${r.stanceSpeed.toFixed(2)} m/s` : ""));
  }
  // the bed set, keyed from UAL's standing idle and seated poses
  const stand = poseOfChannels(fromUAL(UAL, off, "Idle_Loop", "stand").channels, 0);
  const sit = poseOfChannels(fromUAL(UAL, off, "Sitting_Idle_Loop", "sit").channels, 0);
  const bed = bedPoses(stand, sit);
  const lift = (p, dy) => ({q: p.q, hips: p.hips.clone().add(new THREE.Vector3(0, dy, 0))});
  // half-way through a roll: the body half turned, the arms held clear of it (beside the chest, a little in front),
  // so neither forearm sweeps through the hips on the way
  const midRoll = (a, c) => edit(lift(halfway(a, c), 0.04), b => { const {hips, L, Lat, F} = bodyFrame(b);
    for (const [S_, k] of [["Left", 1], ["Right", -1]])
      armTo(b, S_, at(hips, [Lat, k * 0.30], [F, 0.12], [L, 0.22]), at(wpos(b, S_ + "Arm"), [Lat, k * 0.4], [L, -0.1], [F, 0.1])); });
  const BED = {
    lie_back_idle: keyed([[0, bed.back], [8, bed.back]], {breathe: 1.2, period: 4}),
    lie_side_left: keyed([[0, bed.left], [8, bed.left]], {breathe: 1.0, period: 4}),
    lie_side_right: keyed([[0, bed.right], [8, bed.right]], {breathe: 1.0, period: 4}),
    sleep_breathing: keyed([[0, bed.back], [5, bed.back]], {breathe: 1.6, period: 5}),
    sleep_breathing_left: keyed([[0, bed.left], [5, bed.left]], {breathe: 1.4, period: 5}),
    sleep_breathing_right: keyed([[0, bed.right], [5, bed.right]], {breathe: 1.4, period: 5}),
    roll_back_to_side_L: keyed([[0, bed.back], [1.4, midRoll(bed.back, bed.left)], [3, bed.left]]),
    roll_back_to_side_R: keyed([[0, bed.back], [1.4, midRoll(bed.back, bed.right)], [3, bed.right]]),
    roll_side_to_back_L: keyed([[0, bed.left], [1.6, midRoll(bed.left, bed.back)], [3, bed.back]]),
    roll_side_to_back_R: keyed([[0, bed.right], [1.6, midRoll(bed.right, bed.back)], [3, bed.back]]),
  };
  // at the desk
  const sitUp = fromUAL(UAL, off, "Sitting_Idle_Loop", "sit", {seat: SEAT_LIFT});
  BED.type = deskClip(sitUp, 5, (S_, t) => { const k = S_ === "Left" ? 1 : -1;
    return {at: at(KEYS, [X, k * 0.11 + 0.02 * Math.sin(t * 0.9 + k)], [Y, -press(S_, t, k)], [Z, -0.02])}; });
  BED.mouse = deskClip(sitUp, 4, (S_, t) => S_ === "Left"
    ? {at: at(KEYS, [X, 0.14], [Y, -0.02], [Z, -0.06])}
    : {at: at(KEYS, [X, -0.35 + 0.03 * Math.sin(t * 1.6)], [Z, 0.02 * Math.sin(t * 2.3 + 1)], [Y, -0.01]), fingers: new THREE.Vector3(0.05, -0.3, 1)});
  // ---- standing and walking
  const idle = fromUAL(UAL, off, "Idle_Loop", "idle"), walkR = fromUAL(UAL, off, "Walk_Loop", "walk");
  const crouch = fromUAL(UAL, off, "Crouch_Idle_Loop", "crouch");
  // start / stop: the stance eases into the gait (and back) over 0.7 s
  BED.walk_start = fromFn(0.7, t => mixPose(clipPose(idle, t), clipPose(walkR, t), ease(t / 0.7)));
  BED.walk_stop = fromFn(0.7, t => mixPose(clipPose(walkR, t), clipPose(idle, t), ease(t / 0.7)));
  // turns in place: the hips yaw by 90 deg while the legs take two small steps (half the walk's stride)
  for (const [as, deg] of [["turn_in_place_L90", 90], ["turn_in_place_R90", -90], ["turn_in_place_180", 180]]) {
    const dur = Math.abs(deg) > 90 ? 1.4 : 1.0;
    BED[as] = fromFn(dur, t => edit(mixPose(clipPose(idle, t), clipPose(walkR, t * 1.2), 0.5 * Math.sin(Math.PI * t / dur)),
      b => turnBody(b, Y, deg * ease(t / dur))));
  }
  // hands on the window sill (1.10 m, 0.35 m in front), leaning a little; a slow breath
  BED.lean_on_sill = fromFn(8, t => edit(clipPose(idle, t), b => {
    turnWorld(b, "Spine02", X, 8); turnWorld(b, "Spine01", X, 4);
    for (const [S_, k] of [["Left", 1], ["Right", -1]]) { armTo(b, S_, new THREE.Vector3(k * 0.2, 1.10, 0.38), at(wpos(b, S_ + "Arm"), [X, k * 0.4], [Y, -0.3]));
      handFacing(b, S_, new THREE.Vector3(-k * 0.2, 0, 1), new THREE.Vector3(0, -1, 0)); } }), 0.5, {breathe: 1.0, period: 4});
  // arms up and down again; a hand to the side of the head, scratching; looking around with the feet planted
  BED.stretch_arms_up = fromFn(3, t => { const u = t < 1.1 ? ease(t / 1.1) : t < 1.9 ? 1 : 1 - ease((t - 1.9) / 1.1);
    return edit(clipPose(idle, t), b => { turnWorld(b, "Spine01", X, -6 * u); turnWorld(b, "neck", X, -10 * u);
      for (const [S_, k] of [["Left", 1], ["Right", -1]]) { const rest = wpos(b, S_ + "Hand"), up = new THREE.Vector3(k * 0.16, 2.02, -0.02);
        const arc = Math.sin(Math.PI * u);         // the hands go up round the outside of the shoulders, a little forward
        armTo(b, S_, at(rest.clone().lerp(up, u), [X, k * 0.18 * arc], [Z, 0.10 * arc]), at(wpos(b, S_ + "Arm"), [X, k * 0.5], [Y, -0.1 + 0.4 * u])); } }); }, 1 / 10);
  BED.scratch_head = fromFn(2.5, t => { const u = t < 0.6 ? ease(t / 0.6) : t < 1.9 ? 1 : 1 - ease((t - 1.9) / 0.6);
    return edit(clipPose(idle, t), b => { const head = wpos(b, "Head"), rest = wpos(b, "RightHand");
      // the wrist by the right temple, the fingers over the crown, the palm on the head (scratching: small strokes)
      const spot = at(head, [X, -0.12], [Y, 0.09 + 0.012 * Math.sin(t * 25)], [Z, -0.01]), crown = at(head, [Y, 0.13], [Z, -0.02]);
      const arc = Math.sin(Math.PI * u);           // up and down round the outside of the shoulder, a little forward
      armTo(b, "Right", at(rest.clone().lerp(spot, u), [X, -0.16 * arc], [Z, 0.12 * arc]), at(wpos(b, "RightArm"), [X, -0.4], [Y, 0.1 * u], [Z, 0.1]));
      if (u > 0) { const hand = wpos(b, "RightHand"), q0 = b.RightHand.quaternion.clone();
        handFacing(b, "Right", crown.clone().sub(hand).normalize(), at(head, [Y, 0.07]).sub(hand).normalize());
        b.RightHand.quaternion.copy(q0.slerp(b.RightHand.quaternion, u)); b.RightHand.updateMatrixWorld(true); }
      turnWorld(b, "neck", Z, 6 * u); }); }, 1 / 15);
  BED.look_around = fromFn(4, t => edit(clipPose(idle, t), b => { const yaw = 35 * Math.sin(2 * Math.PI * t / 4) * Math.min(1, t, 4 - t);
    turnWorld(b, "Spine", Y, yaw * 0.25); turnWorld(b, "neck", Y, yaw * 0.35); turnWorld(b, "Head", Y, yaw * 0.4); }), 1 / 8);
  // down to the floor (a hand reaches 0.45 m forward, low) and up; a bag put on the desk (0.97 m)
  BED.crouch_drop = fromFn(2.5, t => { const u = t < 0.9 ? ease(t / 0.9) : t < 1.6 ? 1 : 1 - ease((t - 1.6) / 0.9);
    return edit(mixPose(clipPose(idle, t), clipPose(crouch, t), u), b => {
      armTo(b, "Right", wpos(b, "RightHand").lerp(new THREE.Vector3(-0.12, 0.08, 0.45), u * 0.9), at(wpos(b, "RightArm"), [X, -0.3], [Z, 0.2])); }); }, 1 / 10);
  BED.put_down = fromFn(1.5, t => { const u = t < 0.6 ? ease(t / 0.6) : t < 0.9 ? 1 : 1 - ease((t - 0.9) / 0.6);
    return edit(clipPose(idle, t), b => { turnWorld(b, "Spine01", X, 10 * u);
      armTo(b, "Right", wpos(b, "RightHand").lerp(new THREE.Vector3(-0.15, DESK + 0.12, 0.42), u), at(wpos(b, "RightArm"), [X, -0.4], [Y, -0.2])); }); }, 1 / 10);
  // ---- seated: lean back, eat with chopsticks (bowl in the left hand), drink
  const chestOf = b => wpos(b, "Spine"), mouthOf = b => {   // the lips: below and in front of the eyes, the way his face points
    const eyes = wpos(b, "LeftEye").lerp(wpos(b, "RightEye"), 0.5);
    return eyes.add(new THREE.Vector3(0, -0.065, 0.025).applyQuaternion(headTurn(b))); };
  BED.sit_lean_back = fromFn(6, t => edit(clipPose(sitUp, t), b => { turnWorld(b, "Spine02", X, -10); turnWorld(b, "Spine01", X, -4); turnWorld(b, "neck", X, 8); }), 1 / 6, {breathe: 1.0, period: 4});
  BED.sit_eat_chopsticks = fromFn(5, t => edit(clipPose(sitUp, t), b => {
    turnWorld(b, "Spine01", X, 4);
    const bowl = at(chestOf(b), [Z, 0.30], [Y, -0.20], [X, 0.04]);
    armTo(b, "Left", bowl, at(wpos(b, "LeftArm"), [X, 0.35], [Y, -0.35]));
    handFacing(b, "Left", new THREE.Vector3(-0.6, 0, 1), new THREE.Vector3(0, 1, 0));
    const ph = (t % 2.5) / 2.5, up = ph < 0.4 ? 0 : ph < 0.6 ? ease((ph - 0.4) / 0.2) : ph < 0.75 ? 1 : 1 - ease((ph - 0.75) / 0.25);   // pick, bite, back
    // the chopsticks' tips (0.28 m on from the wrist: the grip, then the sticks) go to the food in the bowl, then to the
    // lips, coming in from in front, below and his right; the eyes go down towards the bowl to pick, up to the screen to eat
    lookAt(b, at(bowl, [Y, 0.05]).lerp(SCREEN, 0.5 + 0.4 * up), 0.5);
    const mouth = mouthOf(b), REACH = 0.28;
    const dPick = new THREE.Vector3(0.75, -0.55, 0.35).normalize(), dBite = new THREE.Vector3(0.3, 0.4, -1).normalize();
    const aim = dPick.clone().lerp(dBite, up).normalize(), tip = at(bowl, [Y, 0.03]).lerp(mouth, up);
    toolTo(b, "socket_chopsticks", 0.195, tip, at(tip, [aim, -REACH]), wrist => {
      armTo(b, "Right", wrist, at(wpos(b, "RightArm"), [X, -0.4], [Y, -0.3]));
      handFacing(b, "Right", aim, new THREE.Vector3(-0.4, -0.3, 0).addScaledVector(Y, 0.5 * up)); });
  }), 1 / 10);
  BED.sit_drink = fromFn(4, t => { const u = t < 1.0 ? ease(t / 1.0) : t < 2.8 ? 1 : 1 - ease((t - 2.8) / 1.0), tip = t > 1.2 && t < 2.6 ? 1 : 0;
    return edit(clipPose(sitUp, t), b => { const rest = at(chestOf(b), [Z, 0.25], [Y, -0.3], [X, -0.12]), lips = at(mouthOf(b), [Z, 0.07], [Y, -0.10], [X, -0.03]);
      armTo(b, "Right", rest.lerp(lips, u), at(wpos(b, "RightArm"), [X, -0.4], [Y, -0.35]));
      handFacing(b, "Right", new THREE.Vector3(0.2, 1, 0.2), new THREE.Vector3(1, 0, 0));
      turnWorld(b, "Head", X, -12 * tip * u); }); }, 1 / 10);
  // ---- the bed's edge (mattress top MATTRESS): sitting (UAL's seated clips, raised to it), lying down and getting up
  const EDGE_LIFT = SEAT_LIFT + (MATTRESS - 0.50);
  const edgeSit = fromUAL(UAL, off, "Sitting_Idle_Loop", "edge", {seat: EDGE_LIFT});
  BED.sit_edge_idle = fromFn(8, t => clipPose(edgeSit, t), 1 / 6, {breathe: 0.8, period: 4});
  for (const [as, name] of [["sit_down_bed_edge", "Sitting_Enter"], ["stand_up_bed_edge", "Sitting_Exit"]]) {
    const r = fromUAL(UAL, off, name, as, {seat: EDGE_LIFT}); BED[as] = {channels: r.channels, duration: r.duration, hips0: r.hips0}; }
  // lying down from the edge, head towards his left (+x): sitting, leaning onto the left elbow, legs up, on the back
  const sitEdge = clipPose(edgeSit, 0);
  const lieX = edit(bed.back, b => { placeHips(b, new THREE.Vector3(0, 1, 0)); turnBody(b, Y, -90); torsoOn(b, MATTRESS);
    placeHips(b, at(wpos(b, "Hips"), [X, -0.35], [Z, -0.55])); });
  const leanL = edit(sitEdge, b => { turnBody(b, Z, 38); turnWorld(b, "neck", Z, -15);
    armTo(b, "Left", at(wpos(b, "Hips"), [X, 0.30], [Y, -0.05], [Z, -0.1]), at(wpos(b, "LeftArm"), [Z, -0.3], [Y, -0.2])); placeHips(b, at(wpos(b, "Hips"), [Y, -0.03])); });
  const legsUp = mixPose(leanL, lieX, 0.6);
  BED.lie_down_from_edge = keyed([[0, sitEdge], [0.9, leanL], [1.7, legsUp], [2.5, lieX]]);
  BED.get_up_to_edge = keyed([[0, lieX], [0.8, legsUp], [1.6, leanL], [2.5, sitEdge]]);
  // the phone held up over his chest in the right hand, on his back, the head raised by the pillow: the elbow resting
  // on the mattress beside his ribs, the forearm up, the wrist straight, the screen turned to his eyes
  BED.lie_phone = fromFn(6, t => edit(bed.back, b => { turnWorld(b, "neck", X, 4);
    const eyes = wpos(b, "LeftEye").lerp(wpos(b, "RightEye"), 0.5), sh = wpos(b, "RightArm"), wob = 0.006 * Math.sin(t);
    const elbow = at(sh, [X, -0.10], [Y, -0.04], [Z, 0.27]), wrist = at(elbow, [X, 0.08], [Y, 0.25], [Z, -0.03 + wob]);
    armTo(b, "Right", wrist, at(elbow, [X, -0.1], [Y, -0.05]));
    const fore = wpos(b, "RightHand").sub(wpos(b, "RightForeArm")).normalize();
    handFacing(b, "Right", fore, eyes.clone().sub(at(wpos(b, "RightHand"), [fore, 0.09])).normalize());
  }),
    1 / 6, {breathe: 1.0, period: 4});
  for (const [as, r] of Object.entries(BED)) { addClip(d, ns, as, bodyOnly(r.channels)); CHECKS.push(["boy2_motion.glb", as, bodyOnly(r.channels), r.duration]);
    rows.push(`  ${as} <- keyed: ${r.duration.toFixed(2)} s, hips at frame 0 [${r.hips0.map(v => v.toFixed(3)).join(", ")}] m (mattress top ${MATTRESS} m)`); }
  await finish(d, path.join(OUT, "boy2_motion.glb"));
  console.log("boy2_motion.glb:\n" + rows.join("\n"));
  // the same motion on the first character's rig (boy.glb, 24 bones): web/room/boy_moves.glb
  console.log(`first character at rest: lowest point ${lowestOld(fk(OLD, [], "rest-o").at(0)).toFixed(3)} m`);
  const o = await io.read(path.join(WEB, "boy_door.glb"));
  for (const a of o.getRoot().listAnimations()) a.dispose();
  const ons = Object.fromEntries(o.getRoot().listNodes().map(n => [n.getName(), n]));
  for (const [file, name, channels, dur] of CHECKS) if (file === "boy2_motion.glb") { const r = toOld(channels, dur); addClip(o, ons, name, r); OLD_CLIPS.push([name, r, dur]); }
  for (const [name, ch] of OLD_CLIPS) if (["walk", "type", "sleep_breathing", "lie_phone", "sit_idle_upright", "stand_idle"].includes(name)) {
    const h = ch.find(c => c.node === "Hips" && c.path === "translation").values;
    console.log(`  boy_moves ${name}: hips at frame 0 [${h.slice(0, 3).map(v => (v / 100).toFixed(3)).join(", ")}] m`); }
  await finish(o, path.join(WEB, "boy_moves.glb"));
}
// the check on the first character (boy.glb's skin): the clips he plays today and the new ones (boy_moves.glb)
{ const old = [];
  for (const f of ["boy.glb", ...OLD_FILES]) for (const c of await readClip(path.join(WEB, f)))
    old.push([f, c.name, c.channels, Math.max(...c.channels.map(ch => ch.times[ch.times.length - 1]))]);
  deformCheck({locals: OLD, joints: OLD_SKIN.js, IB: OLD_SKIN.IB, verts: OLD_SKIN.verts, file: path.join(WEB, "..", "..", "docs", "motion", "deform_check.json"),
    clips: [...old, ...OLD_CLIPS.map(([name, ch, dur]) => ["boy_moves.glb", name, ch, dur])]}); }
const tris = mesh.listPrimitives().reduce((s, p) => s + p.getIndices().getCount() / 3, 0);
console.log(`boy2: ${tris} triangles, ${mesh.listPrimitives().length} materials, ${joints.length} joints`);
console.log(report.join(", "));
if (kbMain > 3 * 1024) throw new Error("boy2.glb is over 3 MB");
if (tris > 25000) throw new Error("over 25k triangles");

// ---------------------------------------------------------------- deformation check (docs/character/deform_check.json)
// Every clip, sampled at 5 fps, skinned on the CPU like the GPU does it. Two measures, in cm:
//  bulge: how much further a vertex (skin or cloth) stands off its bones than in the bind pose: for each bone that
//         mainly moves it (weight >= 0.25), its distance to that bone's segment posed minus bind; the least of these.
//         A swelling at a bent joint (the "bloated joggers") moves vertices off every bone they hang on.
//  torso: how deep a forearm or hand vertex sinks into the torso's core: capsules along the spine (hips -> chest ->
//         neck) a little thinner than the torso's front-to-back half-depth there (in the bind pose), so a hand resting
//         on the belly is outside, through is in.
function deformCheck({locals, joints, IB, verts, clips, file: outFile}) {
  const SEG = {Hips: "Spine02", Spine02: "Spine01", Spine01: "Spine", Spine: "neck", neck: "Head", Head: "headfront"};
  for (const S_ of ["Left", "Right"])
    Object.assign(SEG, {[S_ + "UpLeg"]: S_ + "Leg", [S_ + "Leg"]: S_ + "Foot", [S_ + "Foot"]: S_ + "ToeBase",
      [S_ + "Shoulder"]: S_ + "Arm", [S_ + "Arm"]: S_ + "ForeArm", [S_ + "ForeArm"]: S_ + "Hand"});
  const TORSO = ["Hips", "Spine02", "Spine01", "Spine"], LIMB = /(ForeArm|Hand)/;
  const jIndex = Object.fromEntries(joints.map((n, i) => [n, i]));
  // a segment per joint: to SEG's end, else on from the joint along its parent's direction (half the parent's length)
  const ends = b => joints.map(n => { if (!b[n]) return [_v(), _v()]; const p = b[n].getWorldPosition(_v());
    if (SEG[n] && b[SEG[n]]) return [p, b[SEG[n]].getWorldPosition(_v())];
    const par = locals[n].parent && b[locals[n].parent] ? b[locals[n].parent].getWorldPosition(_v()) : p.clone();
    return [p, p.clone().add(p.clone().sub(par).multiplyScalar(0.5))]; });
  const segDist = (p, [a, c]) => { const ab = _v().subVectors(c, a), t = Math.max(0, Math.min(1, _v().subVectors(p, a).dot(ab) / Math.max(ab.lengthSq(), 1e-12)));
    return p.distanceTo(a.clone().addScaledVector(ab, t)); };
  const skinAll = b => { const M = joints.map((n, i) => (b[n] ? b[n].matrixWorld : new THREE.Matrix4()).clone().multiply(IB[i])), v = _v();
    return verts.map(([p, j, w]) => { const acc = _v(); for (let k = 0; k < 4; k++) if (w[k] > 0) acc.addScaledVector(v.set(p.x ?? p[0], p.y ?? p[1], p.z ?? p[2]).applyMatrix4(M[j[k]]), w[k]); return acc; }); };
  const infl = verts.map(([, j, w]) => [0, 1, 2, 3].filter(k => w[k] >= 0.25).map(k => j[k]));
  const dom = verts.map(([, j, w]) => joints[j[w.indexOf(Math.max(...w))]]);
  const rest = fk(locals, [], "rest").at(0), E0 = ends(rest), P0 = skinAll(rest);
  const r0 = P0.map((p, i) => infl[i].map(j => segDist(p, E0[j])));
  // the bulge: the least a vertex moved off any of its main bones (moving off one bone towards another is no bulge)
  const off = (p, i, E) => Math.min(...infl[i].map((j, k) => segDist(p, E[j]) - r0[i][k]));
  // the torso core: per spine segment, 0.7 of the 10th percentile of the trunk's distance to it (his hoodie is loose and
  // one mesh with his body, so the outer 30% is cloth a resting forearm may press)
  const core = TORSO.map(n => { const ji = jIndex[n], d = P0.filter((p, i) => dom[i] === n).map(p => segDist(p, E0[ji])).sort((a, b) => a - b);
    return d.length ? 0.7 * d[Math.floor(d.length * 0.1)] : 0; });
  const limbs = verts.map((_, i) => i).filter(i => LIMB.test(dom[i]));
  // bulges by region: the hips and legs (the joggers), the shoulders and arms (the hoodie's sleeves), the trunk and head
  const region = dom.map(n => /^Hips$|UpLeg|Leg|Foot|Toe/.test(n) ? "legs" : /Shoulder|Arm|Hand/.test(n) ? "arms" : "trunk");
  const out = [];
  for (const [file, name, channels, dur] of clips) {
    const f = fk(locals, channels, name), bulge = {legs: [0, "", 0], arms: [0, "", 0], trunk: [0, "", 0]};
    let torso = 0, tWhere = "", tAt = 0;
    for (let t = 0; t <= dur + 1e-6; t += 0.2) {
      const b = f.at(Math.min(t, dur)), E = ends(b), P = skinAll(b);
      for (let i = 0; i < P.length; i++) { const d = off(P[i], i, E), r = bulge[region[i]]; if (d > r[0]) { r[0] = d; r[1] = dom[i]; r[2] = t; } }
      for (const i of limbs) TORSO.forEach((n, k) => { const d = core[k] - segDist(P[i], E[jIndex[n]]); if (d > torso) { torso = d; tWhere = `${dom[i]} in ${n}`; tAt = t; } });
    }
    out.push({file, clip: name, ...Object.fromEntries(Object.entries(bulge).map(([k, [d, w, t]]) => [`bulge_${k}_cm`, +(d * 100).toFixed(1)])),
      bulge_at: Object.entries(bulge).map(([k, [d, w, t]]) => `${k}: ${w || "-"} ${t.toFixed(1)} s`).join("; "),
      torso_cm: +(torso * 100).toFixed(1), torso_at: tWhere ? `${tWhere} ${tAt.toFixed(1)} s` : ""});
  }
  const report = {about: "boy_post.mjs deformCheck() on boy.glb's own skin: per clip (sampled at 5 fps), the worst bulge of skin or cloth off its bones by region (cm, posed minus bind) and the deepest forearm/hand vertex inside the torso core (cm)",
    torso_core_cm: Object.fromEntries(TORSO.map((n, k) => [n, +(core[k] * 100).toFixed(1)])), clips: out};
  fs.mkdirSync(path.dirname(outFile), {recursive: true}); fs.writeFileSync(outFile, JSON.stringify(report, null, 1) + "\n");
  const worst = k => out.reduce((a, c) => c[k] > a[k] ? c : a), w = k => `${worst(k)[k]} cm (${worst(k).clip})`;
  console.log(`deform check: ${out.length} clips; worst bulge: legs ${w("bulge_legs_cm")}, arms ${w("bulge_arms_cm")}, trunk ${w("bulge_trunk_cm")}; ` +
    `deepest hand in the torso ${w("torso_cm")}`);
}
