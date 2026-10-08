// node mixamo_check.mjs <character.glb> <clip.glb> <clip.fbx> [--scale 0.9]
// Proves web/room/char_mixamo.js: the clip (mixamo_glb.mjs's GLB) played on the character by bone name, against the
// same FBX played by three's FBXLoader on its own skeleton. Every joint's world position compared every 0.1 s:
//   - as given: the largest gap (should be ~0: no retarget layer, the same skeleton);
//   - --scale k: the character's skeleton scaled by k (its bones' offsets), the reference scaled by k too: the gap shows
//     whether the hips' travel scales with the body (the feet stay where a k-sized performer's would).
// Also every bone's world rotation against the reference's (worstRot_deg): a character with its own proportions (the
// auto-rig's, rig/autorig.sh) cannot match the positions, but its bones must turn exactly as the performer's did.
import fs from "node:fs";
globalThis.self = globalThis; globalThis.window = globalThis;
const THREE = await import("three");
const { GLTFLoader } = await import("three/examples/jsm/loaders/GLTFLoader.js");
const { FBXLoader } = await import("three/examples/jsm/loaders/FBXLoader.js");
const { MeshoptDecoder } = await import("three/examples/jsm/libs/meshopt_decoder.module.js");   // (the auto-rig's character is meshopt-compressed)
const M = await import(new URL("../../web/room/char_mixamo.js", import.meta.url));
const args = process.argv.slice(2), [CH, CL, FBX] = args, K = args.includes("--scale") ? +args[args.indexOf("--scale") + 1] : 1;
const ab = f => { const b = fs.readFileSync(f); return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength); };
// (a textured character: its textures dropped first - Node has no image decoder, and the check needs only the skeleton)
const { NodeIO } = await import("@gltf-transform/core"); const { ALL_EXTENSIONS } = await import("@gltf-transform/extensions");
const MO = await import("meshoptimizer"); await MO.MeshoptDecoder.ready; await MO.MeshoptEncoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({"meshopt.decoder": MO.MeshoptDecoder, "meshopt.encoder": MO.MeshoptEncoder});
async function bare(f) { const d = await io.readBinary(new Uint8Array(fs.readFileSync(f))); const r = d.getRoot();
  if (!r.listTextures().length) return ab(f);
  for (const t of r.listTextures()) t.dispose(); for (const e of r.listExtensionsUsed()) if (/texture/.test(e.extensionName)) e.dispose();
  const b = await io.writeBinary(d); return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength); }
const gltf = async f => { const a = await bare(f); return new Promise((ok, no) => new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).parse(a, "", ok, no)); };

const ch = await gltf(CH), cl = await gltf(CL);
if (K !== 1) ch.scene.traverse(o => { if (o.isBone && !/Hips$/.test(o.name)) o.position.multiplyScalar(K); });   // (a k-sized body: every bone's offset; the hips' rest height with it)
if (K !== 1) { let h = null; ch.scene.traverse(o => { if (o.isBone && /Hips$/.test(o.name)) h = o; }); h.position.multiplyScalar(K); }
const conv = M.prep(THREE, ch), src = M.clipHipHeight(THREE, cl), clip = M.fixClip(THREE, cl.animations[0], conv, src);
const ref = new FBXLoader().parse(ab(FBX), ""), rg = new THREE.Group(); rg.scale.setScalar(0.01 * K); rg.add(ref);
const mA = new THREE.AnimationMixer(ch.scene); mA.clipAction(clip).play();
const mB = new THREE.AnimationMixer(ref); mB.clipAction(ref.animations.find(a => a.tracks.length)).play();
const bonesA = {}; ch.scene.traverse(o => { if (o.isBone) bonesA[o.name] = o; });
const bonesB = {}; ref.traverse(o => { if (o.isBone) bonesB[M.pageName(o.name)] = o; });
const names = Object.keys(bonesA).filter(n => bonesB[n]);
let worst = 0, wn = null, wt = 0, footA = 9, footB = 9, rot = 0, rn = null; const a = new THREE.Vector3(), b = new THREE.Vector3();
const qa = new THREE.Quaternion(), qb = new THREE.Quaternion(), q0 = new THREE.Quaternion(), q1 = new THREE.Quaternion(), off = {};
// (the two bodies' rest frames differ by a fixed turn per bone, if at all: measured at rest, then every frame against it)
ch.scene.updateMatrixWorld(true); rg.updateMatrixWorld(true); let rest = 0;
for (const n of names) off[n] = bonesA[n].getWorldQuaternion(q0).clone().invert().multiply(bonesB[n].getWorldQuaternion(q1));
for (const n of names) rest = Math.max(rest, THREE.MathUtils.radToDeg(off[n].angleTo(new THREE.Quaternion())));
for (let t = 0; t <= clip.duration + 1e-6; t += 0.1) {
  mA.setTime(t); mB.setTime(t); ch.scene.updateMatrixWorld(true); rg.updateMatrixWorld(true);
  for (const n of names) { bonesA[n].getWorldPosition(a); bonesB[n].getWorldPosition(b); const d = a.distanceTo(b); if (d > worst) { worst = d; wn = n; wt = t; }
    const g = THREE.MathUtils.radToDeg(bonesA[n].getWorldQuaternion(qa).multiply(off[n]).angleTo(bonesB[n].getWorldQuaternion(qb))); if (g > rot) { rot = g; rn = n; }
    if (/Foot|ToeBase/.test(n)) { footA = Math.min(footA, a.y); footB = Math.min(footB, b.y); } }
}
console.log(JSON.stringify({character: CH.split("/").pop(), clip: CL.split("/").pop(), scale: K, bonesMatched: names.length, of: Object.keys(bonesA).length,
  hipH: {character: +conv.hipH.toFixed(3), clip: +src.toFixed(3)}, worstGap_cm: +(worst * 100).toFixed(2), at: [wn, +wt.toFixed(1)], worstRot_deg: +rot.toFixed(2), rotAt: rn, restRot_deg: +rest.toFixed(2),
  lowestFoot_m: {played: +footA.toFixed(3), reference: +footB.toFixed(3)}}));
