// A GLB's contents at a glance: meshes (triangles, vertices, skinned or not), materials and their textures' sizes,
// skins and joint counts, animations, and the scene's bounds (after node transforms). Usage: node rig/inspect.mjs in.glb
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { getBounds } from '@gltf-transform/functions';
import { MeshoptDecoder } from 'meshoptimizer';

await MeshoptDecoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({ 'meshopt.decoder': MeshoptDecoder });
const doc = await io.read(process.argv[2]);
const root = doc.getRoot();
let tris = 0, verts = 0;
for (const m of root.listMeshes()) {
  for (const p of m.listPrimitives()) {
    const n = p.getAttribute('POSITION').getCount(), ix = p.getIndices();
    const t = ix ? ix.getCount() / 3 : n / 3;
    tris += t; verts += n;
    console.log(`mesh ${m.getName() || '-'}: ${t} tris, ${n} verts, skinned ${!!p.getAttribute('JOINTS_0')}, material ${p.getMaterial()?.getName() || '-'}`);
  }
}
console.log(`total ${tris} tris, ${verts} verts`);
for (const mat of root.listMaterials()) {
  const tex = ['getBaseColorTexture', 'getNormalTexture', 'getMetallicRoughnessTexture', 'getOcclusionTexture', 'getEmissiveTexture']
    .map(f => mat[f]()).filter(Boolean).map(t => `${t.getMimeType()} ${t.getSize()?.join('x')}`);
  console.log(`material ${mat.getName() || '-'}: ${tex.join(', ') || 'no textures'}`);
}
for (const s of root.listSkins()) console.log(`skin ${s.getName() || '-'}: ${s.listJoints().length} joints`);
for (const a of root.listAnimations()) console.log(`animation ${a.getName() || '-'}: ${a.listChannels().length} channels`);
const b = getBounds(root.listScenes()[0]);
console.log('bounds min', b.min.map(v => v.toFixed(3)).join(' '), 'max', b.max.map(v => v.toFixed(3)).join(' '),
  'size', b.max.map((v, i) => (v - b.min[i]).toFixed(3)).join(' '));
