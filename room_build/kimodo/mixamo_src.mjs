// node mixamo_src.mjs <clip.fbx> <out.glb> [--in-place] [--fps 30] [--trim from,to (s)]
// A Mixamo clip (FBX Binary, "Without Skin", mixamorig:* skeleton) as a source for mh_retarget.mjs: the same conventions
// as the MakeHuman room clips it was written for, so the retarget (its bone map, rest alignment, leg-length scale, IK
// pins) runs unchanged on it:
//   - bone names: mixamorig:Spine/Spine1/Spine2 -> spine04/spine02/Spine, Neck -> neck, HeadTop_End -> head_end,
//     ToeBase / Toe_End -> ToeBase / toe1-2.L|R, the finger chains Thumb/Index/Middle/Ring/Pinky 1-3 -> finger1..5-1..3.L|R
//     (MakeHuman's names, which v5's 38 finger joints already carry); arms, legs, hips and head keep their names;
//   - the rest pose world-aligned (MakeHuman's is; Mixamo's bones have their own axes): every frame's world rotation is
//     taken relative to the bone's rest world rotation, and the rest pose becomes the bones' rest positions with no turn;
//   - metres (Mixamo's FBX is in centimetres), Y up, facing +Z (both as MakeHuman's);
//   - --in-place: the hips' horizontal travel removed (for clips Mixamo has no "In Place" variant of and that do not
//     travel); the hips' height is kept;
//   - --trim: only that stretch of the capture (a take that runs on past the act, e.g. sitting back down after standing).
// Mixamo's terms allow its animations in a game or app but not the raw files redistributed: the FBX files stay out of the
// repository; only the clips retargeted onto v5 and baked are committed.
import fs from "node:fs";
import { Document, NodeIO } from "@gltf-transform/core";
globalThis.self = globalThis; globalThis.window = globalThis;          // (FBXLoader looks for a browser global)
const THREE = await import("three");
const { FBXLoader } = await import("three/examples/jsm/loaders/FBXLoader.js");

const args = process.argv.slice(2), SRC = args[0], OUT = args[1];
const IN_PLACE = args.includes("--in-place"), FPS = args.includes("--fps") ? +args[args.indexOf("--fps") + 1] : 30;
const TRIM = args.includes("--trim") ? args[args.indexOf("--trim") + 1].split(",").map(Number) : null;

// Mixamo -> MakeHuman (the names mh_retarget.mjs maps onto v5)
const NAME = {Hips: "Hips", Spine: "spine04", Spine1: "spine02", Spine2: "Spine", Neck: "neck", Head: "Head", HeadTop_End: "head_end"};
for (const [S, x] of [["Left", "L"], ["Right", "R"]]) {
  for (const b of ["Shoulder", "Arm", "ForeArm", "Hand", "UpLeg", "Leg", "Foot", "ToeBase"]) NAME[S + b] = S + b;
  NAME[S + "Toe_End"] = `toe1-2.${x}`;
  ["Thumb", "Index", "Middle", "Ring", "Pinky"].forEach((f, i) => { for (let j = 1; j <= 3; j++) NAME[`${S}Hand${f}${j}`] = `finger${i + 1}-${j}.${x}`; });
}

const buf = fs.readFileSync(SRC);
const g = new FBXLoader().parse(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength), "");
const clip = g.animations.find(a => a.tracks.length) || g.animations[0];
if (!clip) throw new Error(`${SRC}: no animation`);
// the skeleton: the first object of each Mixamo name (FBXLoader can list a bone twice); "mixamorig:" or "mixamorig" prefixes
const strip = n => n.replace(/^mixamorig\d*:?/, "");
const bone = {}; g.traverse(o => { const s = strip(o.name); if (NAME[s] && !bone[s] && (o.isBone || o.type === "Object3D")) bone[s] = o; });
const names = Object.keys(NAME).filter(s => bone[s]);
if (!bone.Hips) throw new Error(`${SRC}: no mixamorig:Hips`);
const parentOf = s => { for (let o = bone[s].parent; o; o = o.parent) { const p = strip(o.name); if (bone[p] === o) return p; } return null; };

// rest: the bones' own transforms before the clip plays
g.updateMatrixWorld(true);
const restQ = {}, restP = {};
for (const s of names) { restQ[s] = bone[s].getWorldQuaternion(new THREE.Quaternion()); restP[s] = bone[s].getWorldPosition(new THREE.Vector3()); }
const unit = restP.Hips.y > 10 ? 0.01 : 1;                              // centimetres -> metres

// per frame: world rotation relative to rest (the rest pose made world-aligned), world position
const mixer = new THREE.AnimationMixer(g), act = mixer.clipAction(clip); act.play();
const t0 = TRIM ? Math.max(0, TRIM[0]) : 0, t1 = TRIM ? Math.min(clip.duration, TRIM[1]) : clip.duration;
const T = Math.round((t1 - t0) * FPS) + 1, Wq = {}, Wp = {};
for (const s of names) { Wq[s] = []; Wp[s] = []; }
for (let f = 0; f < T; f++) {
  mixer.setTime(Math.min(t0 + f / FPS, t1)); g.updateMatrixWorld(true);
  for (const s of names) { Wq[s].push(bone[s].getWorldQuaternion(new THREE.Quaternion()).multiply(restQ[s].clone().invert()));
    Wp[s].push(bone[s].getWorldPosition(new THREE.Vector3()).multiplyScalar(unit)); }
}
if (IN_PLACE) { const x0 = Wp.Hips[0].x, z0 = Wp.Hips[0].z; for (const p of Wp.Hips) { p.x = x0; p.z = z0; } }

// the source GLB: rest positions relative to the parent (no rest turn), local rotations per frame, the hips' translation
const doc = new Document(), buffer = doc.createBuffer(), scene = doc.createScene("mixamo"), nodes = {};
for (const s of names) { const p = parentOf(s), rp = restP[s].clone().multiplyScalar(unit), pp = p ? restP[p].clone().multiplyScalar(unit) : new THREE.Vector3();
  nodes[s] = doc.createNode(NAME[s]).setTranslation(rp.sub(pp).toArray()); }
for (const s of names) { const p = parentOf(s); if (p) nodes[p].addChild(nodes[s]); else scene.addChild(nodes[s]); }
const times = doc.createAccessor().setArray(new Float32Array(Array.from({length: T}, (_, f) => f / FPS))).setType("SCALAR").setBuffer(buffer);
const anim = doc.createAnimation(clip.name || "mixamo");
for (const s of names) {
  const p = parentOf(s), q = new Float32Array(T * 4);
  for (let f = 0; f < T; f++) { const l = p ? Wq[p][f].clone().invert().multiply(Wq[s][f]) : Wq[s][f].clone(); q.set([l.x, l.y, l.z, l.w], f * 4); }
  const out = doc.createAccessor().setArray(q).setType("VEC4").setBuffer(buffer), smp = doc.createAnimationSampler().setInput(times).setOutput(out).setInterpolation("LINEAR");
  anim.addSampler(smp).addChannel(doc.createAnimationChannel().setTargetNode(nodes[s]).setTargetPath("rotation").setSampler(smp));
}
{ const t = new Float32Array(T * 3); for (let f = 0; f < T; f++) t.set(Wp.Hips[f].toArray(), f * 3);
  const out = doc.createAccessor().setArray(t).setType("VEC3").setBuffer(buffer), smp = doc.createAnimationSampler().setInput(times).setOutput(out).setInterpolation("LINEAR");
  anim.addSampler(smp).addChannel(doc.createAnimationChannel().setTargetNode(nodes.Hips).setTargetPath("translation").setSampler(smp)); }
await new NodeIO().write(OUT, doc);
const leg = restP.LeftUpLeg.distanceTo(restP.LeftLeg) + restP.LeftLeg.distanceTo(restP.LeftFoot);
console.log(`${SRC.split("/").pop()} -> ${OUT.split("/").pop()}: ${names.length} bones (${names.filter(s => /Hand(Thumb|Index|Middle|Ring|Pinky)/.test(s)).length} finger), ${T} frames ${(t1 - t0).toFixed(2)} s${TRIM ? ` (of ${clip.duration.toFixed(2)})` : ""}, ` +
  `hips ${(restP.Hips.y * unit).toFixed(3)} m up, leg ${(leg * unit).toFixed(3)} m${IN_PLACE ? ", in place" : ""}`);
