// node rig/autorig/write.mjs <in.glb> <fit dir> <out.glb>
// fit.py's result written over the character's own file: the same meshes, materials and textures, with the positions
// and normals as modelled (the bind pose; fit.py's bindmap per bone; AUTORIG_BIND=tpose: T-posed), the Mixamo Standard Skeleton (65 bones, "mixamorig:*", Mixamo's hierarchy and T-pose rest)
// and the new weights. The skeleton hangs under one node scaled 0.01 and its numbers are centimetres, as Mixamo's FBX
// is (mixamo_glb.mjs's convention), so a clip's hips translation means the same on both. The meshes sit at the scene's
// root in metres (feet on y = 0, facing +z, 1.78 m with the slides). Meshopt-compressed like v5, but the positions stay
// float: quantizing a skinned mesh's positions moves the dequantization into the inverse bind matrices, and then
// skeleton.pose() (three) puts the bones in the wrong place. No animations.
import fs from "node:fs";
import { NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS } from "@gltf-transform/extensions";
import { dequantize, prune, quantize, reorder } from "@gltf-transform/functions";
import { EXTMeshoptCompression } from "@gltf-transform/extensions";
import { MeshoptDecoder, MeshoptEncoder } from "meshoptimizer";
import * as THREE from "three";
await MeshoptDecoder.ready; await MeshoptEncoder.ready;
const [IN, FIT, OUT] = process.argv.slice(2);
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({"meshopt.decoder": MeshoptDecoder, "meshopt.encoder": MeshoptEncoder});
const doc = await io.read(IN); await doc.transform(dequantize());
const root = doc.getRoot(), scene = root.listScenes()[0], buf = root.listBuffers()[0];
const S = JSON.parse(fs.readFileSync(`${FIT}/skel.json`)), B = S.bones, cnt = S.counts;
const raw = (f, T) => { const b = fs.readFileSync(`${FIT}/${f}.bin`); return new T(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength)); };
const POS = raw("pos", Float32Array), NRM = raw("nrm", Float32Array), JNT = raw("jnt", Uint16Array), WGT = raw("wgt", Float32Array);

// the skinned primitives, in extract.mjs's order
const meshNodes = root.listNodes().filter(n => n.getMesh() && n.getSkin());
const prims = meshNodes.flatMap(n => n.getMesh().listPrimitives());
if (prims.length !== cnt.length) throw new Error(`primitives ${prims.length} != ${cnt.length}`);
let o = 0;
prims.forEach((p, k) => {
  const n = cnt[k]; if (p.getAttribute("POSITION").getCount() !== n) throw new Error(`primitive ${k}: ${n} vertices expected`);
  const acc = (type, arr) => doc.createAccessor().setType(type).setArray(arr).setBuffer(buf);
  const j8 = new Uint8Array(4 * n); for (let i = 0; i < 4 * n; i++) j8[i] = JNT[4 * o + i];
  p.setAttribute("POSITION", acc("VEC3", POS.slice(3 * o, 3 * (o + n))));
  p.setAttribute("NORMAL", acc("VEC3", NRM.slice(3 * o, 3 * (o + n))));
  p.setAttribute("JOINTS_0", acc("VEC4", j8));
  p.setAttribute("WEIGHTS_0", acc("VEC4", WGT.slice(4 * o, 4 * (o + n))));
  for (const t of p.listTargets()) p.removeTarget(t);
  o += n;
});

// the old rig out: animations, skins, every node that is not one of the meshes
for (const a of root.listAnimations()) a.dispose();
for (const n of meshNodes) { n.setSkin(null); for (const par of n.listParents()) if (par.propertyType === "Node" || par.propertyType === "Scene") par.removeChild(n); }
for (const s of root.listSkins()) s.dispose();
for (const n of root.listNodes()) if (!meshNodes.includes(n)) n.dispose();
for (const n of meshNodes) { scene.addChild(n); n.setTranslation([0, 0, 0]).setRotation([0, 0, 0, 1]).setScale([1, 1, 1]); }

// the skeleton: world (metres) -> local (cm under the 0.01 node), rotations as Mixamo's T-pose
const top = doc.createNode("mixamo").setScale([0.01, 0.01, 0.01]); scene.addChild(top);
const W = {}, nodes = {};
for (const b of B) W[b.name] = {p: new THREE.Vector3(...b.p).multiplyScalar(100), q: new THREE.Quaternion(...b.q)};
for (const b of B) {
  const w = W[b.name], pw = b.parent ? W[b.parent] : {p: new THREE.Vector3(), q: new THREE.Quaternion()};
  const qi = pw.q.clone().invert(), lp = w.p.clone().sub(pw.p).applyQuaternion(qi), lq = qi.multiply(w.q);
  const nd = doc.createNode(b.name).setTranslation(lp.toArray()).setRotation(lq.normalize().toArray());
  nodes[b.name] = nd; (b.parent ? nodes[b.parent] : top).addChild(nd);
}
const skin = doc.createSkin("mixamorig").setSkeleton(nodes[B[0].name]);
const ibm = new Float32Array(16 * B.length);
B.forEach((b, i) => {
  // (bound as modelled: the T-pose placement's inverse after the bone's rigid map from the modelled mesh, fit.py's bindmap)
  const m = new THREE.Matrix4().compose(new THREE.Vector3(...b.p), new THREE.Quaternion(...b.q), new THREE.Vector3(1, 1, 1).multiplyScalar(0.01)).invert();
  if (b.bindmap) m.multiply(new THREE.Matrix4().fromArray(b.bindmap));
  ibm.set(m.elements, 16 * i); skin.addJoint(nodes[b.name]);
});
skin.setInverseBindMatrices(doc.createAccessor().setType("MAT4").setArray(ibm).setBuffer(buf));
for (const n of meshNodes) n.setSkin(skin);
// (provenance: the source's bind space -> these meshes' space, column-major; kimodo/mx_convert.mjs reads it)
scene.setExtras({...scene.getExtras(), autorig: {fromSourceBind: S.report.from_source_bind}});
await doc.transform(prune({keepLeaves: true}), reorder({encoder: MeshoptEncoder, target: "size"}),
  quantize({pattern: /^(NORMAL|TEXCOORD_\d+|JOINTS_\d+|WEIGHTS_\d+)$/}));      // (meshopt() itself would quantize POSITION too)
doc.createExtension(EXTMeshoptCompression).setRequired(true).setEncoderOptions({method: EXTMeshoptCompression.EncoderMethod.QUANTIZE});
await io.write(OUT, doc);
console.log(`${OUT}: ${B.length} bones, ${prims.length} primitives, ${o} vertices, ${(fs.statSync(OUT).size / 1048576).toFixed(2)} MB`);
