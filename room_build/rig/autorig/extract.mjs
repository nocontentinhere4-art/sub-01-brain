// node rig/autorig/extract.mjs <in.glb> <out dir>
// The rigged character's data for fit.py, in its bind space: every skinned primitive's positions, normals, joints,
// weights and triangles (raw little-endian files), and the skin's joints (name, parent, bind matrix = inverse IBM).
import fs from "node:fs";
import { NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS } from "@gltf-transform/extensions";
import { dequantize } from "@gltf-transform/functions";
import { MeshoptDecoder } from "meshoptimizer";
import * as THREE from "three";
await MeshoptDecoder.ready;
const [IN, OUT] = process.argv.slice(2); fs.mkdirSync(OUT, {recursive: true});
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({"meshopt.decoder": MeshoptDecoder});
const doc = await io.read(IN); await doc.transform(dequantize());
const root = doc.getRoot(), skin = root.listSkins()[0], joints = skin.listJoints(), ibm = skin.getInverseBindMatrices();
const J = joints.map((j, i) => ({name: j.getName(), parent: joints.indexOf(j.getParentNode()),
  bind: new THREE.Matrix4().fromArray(ibm.getElement(i, [])).invert().toArray()}));
const prims = []; let k = 0;
for (const node of root.listNodes()) { const m = node.getMesh(); if (!m || !node.getSkin()) continue;
  const sk = node.getSkin(), js = sk.listJoints().map(j => joints.indexOf(j)), ib = sk.getInverseBindMatrices(), h = js.indexOf(1);
  // this skin's bind space -> the first skin's (the same joints, so one matrix: B0[j] * IBMk[j], at the hips)
  const toBind = new THREE.Matrix4().fromArray(J[js[h]].bind).multiply(new THREE.Matrix4().fromArray(ib.getElement(h, []))).toArray();
  for (const p of m.listPrimitives()) {
    const f = `p${k++}`, w = (a, ext, T) => { const arr = a.getArray(); fs.writeFileSync(`${OUT}/${f}.${ext}`, Buffer.from(new T(arr).buffer)); };
    w(p.getAttribute("POSITION"), "pos", Float32Array); w(p.getAttribute("NORMAL"), "nrm", Float32Array);
    const jj = p.getAttribute("JOINTS_0").getArray(), jm = new Uint16Array(jj.length); for (let i = 0; i < jj.length; i++) jm[i] = js[jj[i]];
    fs.writeFileSync(`${OUT}/${f}.jnt`, Buffer.from(jm.buffer)); w(p.getAttribute("WEIGHTS_0"), "wgt", Float32Array);
    w(p.getIndices(), "idx", Uint32Array);
    prims.push({file: f, toBind, node: node.getName(), mesh: m.getName(), material: p.getMaterial()?.getName(), count: p.getAttribute("POSITION").getCount()});
  } }
// the size the character is drawn at: its joints' spread in the world (through the armature's own scale) over their
// spread in bind space (v5: 0.8508, 1.73 m in the page with the slides), so fit.py keeps it that size
const wp = joints.map(j => new THREE.Vector3().setFromMatrixPosition(new THREE.Matrix4().fromArray(j.getWorldMatrix())));
const bp = J.map(j => new THREE.Vector3().setFromMatrixPosition(new THREE.Matrix4().fromArray(j.bind)));
const ratios = wp.slice(1).map((p, i) => [p.distanceTo(wp[0]), bp[i + 1].distanceTo(bp[0])]).filter(([, b]) => b > 1e-3).map(([a, b]) => a / b).sort((a, b) => a - b);
const worldScale = ratios[ratios.length >> 1];
fs.writeFileSync(`${OUT}/rig.json`, JSON.stringify({joints: J, prims, worldScale}));
console.log(`${prims.length} primitives, ${J.length} joints -> ${OUT}`);
