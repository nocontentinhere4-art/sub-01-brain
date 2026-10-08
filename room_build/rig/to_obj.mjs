// static GLB -> OBJ + MTL + PNG textures (for Mixamo's auto-rigger, which takes FBX, OBJ or a ZIP of OBJ + textures)
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import fs from 'fs'; import path from 'path'; import * as THREE from 'three';
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS);
const doc = await io.read(process.argv[2]); const out = process.argv[3]; fs.mkdirSync(out, {recursive: true});
const mats = new Map(); let mtl = '', obj = 'mtllib character.mtl\n', vo = 1;
for (const node of doc.getRoot().listNodes()) { const mesh = node.getMesh(); if (!mesh) continue;
  const M = new THREE.Matrix4().fromArray(node.getWorldMatrix()), N = new THREE.Matrix3().getNormalMatrix(M);
  for (const p of mesh.listPrimitives()) {
    const mat = p.getMaterial(); let mn = 'm' + mats.size;
    if (mat && !mats.has(mat)) { mats.set(mat, mn); const tex = mat.getBaseColorTexture(); mtl += `newmtl ${mn}\nKd 1 1 1\n`;
      if (tex) { const f = `${mn}.png`; fs.writeFileSync(path.join(out, f), Buffer.from(tex.getImage())); mtl += `map_Kd ${f}\n`; } }
    else if (mat) mn = mats.get(mat);
    const P = p.getAttribute('POSITION'), Nn = p.getAttribute('NORMAL'), T = p.getAttribute('TEXCOORD_0'), I = p.getIndices();
    const v = [0,0,0], n = [0,0,0], t = [0,0]; const lines = [];
    for (let i = 0; i < P.getCount(); i++) { P.getElement(i, v); const w = new THREE.Vector3(...v).applyMatrix4(M); lines.push(`v ${w.x.toFixed(5)} ${w.y.toFixed(5)} ${w.z.toFixed(5)}`); }
    for (let i = 0; i < P.getCount(); i++) { T.getElement(i, t); lines.push(`vt ${t[0].toFixed(5)} ${(1 - t[1]).toFixed(5)}`); }
    for (let i = 0; i < P.getCount(); i++) { Nn.getElement(i, n); const w = new THREE.Vector3(...n).applyMatrix3(N).normalize(); lines.push(`vn ${w.x.toFixed(4)} ${w.y.toFixed(4)} ${w.z.toFixed(4)}`); }
    lines.push(`usemtl ${mn}`);
    for (let i = 0; i < I.getCount(); i += 3) { const a = I.getScalar(i) + vo, b = I.getScalar(i+1) + vo, c = I.getScalar(i+2) + vo; lines.push(`f ${a}/${a}/${a} ${b}/${b}/${b} ${c}/${c}/${c}`); }
    obj += lines.join('\n') + '\n'; vo += P.getCount();
  } }
fs.writeFileSync(path.join(out, 'character.obj'), obj); fs.writeFileSync(path.join(out, 'character.mtl'), mtl);
console.log('obj written, vertices', vo - 1, 'materials', mats.size);
