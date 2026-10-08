import { NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS } from "@gltf-transform/extensions";
import { MeshoptDecoder } from "meshoptimizer";
import fs from "fs";
await MeshoptDecoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({"meshopt.decoder": MeshoptDecoder});
const doc = await io.read(process.argv[2]), out = process.argv[3]; fs.mkdirSync(out, {recursive: true});
let k = 0; const meta = [];
for (const n of doc.getRoot().listNodes()) { const m = n.getMesh(); if (!m) continue;
  for (const p of m.listPrimitives()) { const name = `${n.getName().slice(0, 20)}_${k++}`, A = {};
    for (const s of p.listSemantics()) { const a = p.getAttribute(s), N = a.getCount(), E = a.getElementSize(), f = new Float32Array(N * E), e = [];
      for (let i = 0; i < N; i++) { a.getElement(i, e); f.set(e, i * E); } fs.writeFileSync(`${out}/${name}.${s}.f32`, Buffer.from(f.buffer)); A[s] = [N, E]; }
    if (p.getIndices()) fs.writeFileSync(`${out}/${name}.idx.u32`, Buffer.from(new Uint32Array(p.getIndices().getArray()).buffer));
    meta.push({name, node: n.getName(), mesh: m.getName(), mat: p.getMaterial() && p.getMaterial().getName(), attrs: A}); } }
const sk = doc.getRoot().listSkins()[0];
if (sk) { const ib = sk.getInverseBindMatrices(), joints = sk.listJoints().map(j => j.getName()), M = [];
  for (let i = 0; i < joints.length; i++) M.push(ib.getElement(i, []));
  const wm = sk.listJoints().map(j => j.getWorldMatrix());
  fs.writeFileSync(`${out}/skin.json`, JSON.stringify({joints, ibm: M, world: wm, parents: sk.listJoints().map(j => j.getParentNode() ? j.getParentNode().getName() : null)})); }
fs.writeFileSync(`${out}/meta.json`, JSON.stringify(meta, null, 1));
console.log(JSON.stringify(meta));
