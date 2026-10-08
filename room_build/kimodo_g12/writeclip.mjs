// node writeclip.mjs <in.json> <out.glb> : an animation-only GLB on the v5 skeleton (node names, hierarchy and rest as
// char_tripo_v5.glb), one clip sampled at the given rate, linear
import {Document, NodeIO} from '@gltf-transform/core';
import fs from 'fs';
const J = JSON.parse(fs.readFileSync(process.argv[2]));
const doc = new Document(); const buf = doc.createBuffer(); const scene = doc.createScene();
const nodes = J.nodes.map(n => doc.createNode(n.name).setTranslation(n.t).setRotation(n.r).setScale(n.s));
J.nodes.forEach((n, i) => { if (n.parent >= 0) nodes[n.parent].addChild(nodes[i]); else scene.addChild(nodes[i]); });
const F = J.F, times = new Float32Array(F).map((_, f) => f / J.fps);
const input = doc.createAccessor().setType('SCALAR').setArray(times).setBuffer(buf);
const anim = doc.createAnimation(J.name);
const add = (i, path, arr, type) => {
  const out = doc.createAccessor().setType(type).setArray(new Float32Array(arr)).setBuffer(buf);
  const s = doc.createAnimationSampler().setInput(input).setOutput(out).setInterpolation('LINEAR');
  anim.addSampler(s).addChannel(doc.createAnimationChannel().setTargetNode(nodes[i]).setTargetPath(path).setSampler(s));
};
for (const [i, arr] of Object.entries(J.rot)) add(+i, 'rotation', arr, 'VEC4');
for (const [i, arr] of Object.entries(J.trans)) add(+i, 'translation', arr, 'VEC3');
await new NodeIO().write(process.argv[3], doc);
console.log(process.argv[3].split('/').pop(), F, 'frames', Object.keys(J.rot).length, 'rot', Object.keys(J.trans).length, 'trans');
