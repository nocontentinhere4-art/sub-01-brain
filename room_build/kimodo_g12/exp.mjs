// node exp.mjs <glb> <out.json> : nodes (parent, rest TRS), the first skin (joints, IBMs) and its mesh (positions,
// joints, weights of every vertex), and every animation's raw keyframes
import {NodeIO} from '@gltf-transform/core';
import {ALL_EXTENSIONS} from '@gltf-transform/extensions';
import {MeshoptDecoder} from 'meshoptimizer'; import fs from 'fs';
await MeshoptDecoder.ready;
const d = await new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({'meshopt.decoder': MeshoptDecoder}).read(process.argv[2]);
const r = d.getRoot(), nodes = r.listNodes(), ix = new Map(nodes.map((n, i) => [n, i]));
const parent = nodes.map(() => -1); nodes.forEach((n, i) => n.listChildren().forEach(c => parent[ix.get(c)] = i));
const out = {nodes: nodes.map((n, i) => ({name: n.getName(), parent: parent[i], t: n.getTranslation(), r: n.getRotation(), s: n.getScale()})), anims: []};
const sk = r.listSkins()[0];
if (sk) {
  out.skin = {joints: sk.listJoints().map(j => ix.get(j)), ibm: Array.from(sk.getInverseBindMatrices().getArray())};
  const mn = nodes.find(n => n.getMesh() && n.getSkin()); out.skin.meshNode = ix.get(mn);
  // (ALLMESH=1: every skinned mesh node's primitives, each tagged with its mesh's name: the slides too. They must share
  // the first skin and mesh space, as an auto-rigged character's do)
  const prims = process.env.ALLMESH ? nodes.filter(n => n.getMesh() && n.getSkin() === sk).flatMap(n => n.getMesh().listPrimitives().map(p => (p.__mesh = n.getName(), p)))
    : mn.getMesh().listPrimitives();
  out.mesh = prims.map(p => ({mesh: p.__mesh, ...(process.env.ALLMESH && p.getAttribute('NORMAL') ? {nrm: Array.from(p.getAttribute('NORMAL').getArray(), x => +x.toFixed(4))} : {}), pos: Array.from(p.getAttribute('POSITION').getArray()), j: Array.from(p.getAttribute('JOINTS_0').getArray()), w: Array.from(p.getAttribute('WEIGHTS_0').getArray()), norm: p.getAttribute('POSITION').getNormalized ? p.getAttribute('POSITION').getNormalized() : false}));
}
for (const a of r.listAnimations()) out.anims.push({name: a.getName(), ch: a.listChannels().map(c => ({node: ix.get(c.getTargetNode()), path: c.getTargetPath(),
  interp: c.getSampler().getInterpolation(), t: Array.from(c.getSampler().getInput().getArray()), v: Array.from(c.getSampler().getOutput().getArray())}))});
fs.writeFileSync(process.argv[3], JSON.stringify(out));
console.log(process.argv[2].split('/').pop(), nodes.length, 'nodes', sk ? sk.listJoints().length + ' joints' : '', out.mesh ? out.mesh.map(m => m.pos.length / 3).join('+') + ' verts' : '', out.anims.map(a => a.name).join(','));
