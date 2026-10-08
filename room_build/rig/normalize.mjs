// A static character GLB (no skin) -> the same character standing at the origin, feet on y = 0, HEIGHT m tall,
// facing +Z (glTF front), with node transforms baked into the vertices and textures re-encoded as PNG for the
// auto-rigger. For a model that already faces +Z, as Tripo's image-to-model output does.
// Usage: node rig/normalize.mjs in.glb out.glb [HEIGHT=1.75]
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { getBounds, flatten, transformMesh, prune } from '@gltf-transform/functions';
import { MeshoptDecoder } from 'meshoptimizer';

const [inp, out, h = '1.75'] = process.argv.slice(2);
await MeshoptDecoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({ 'meshopt.decoder': MeshoptDecoder });
const doc = await io.read(inp);
const root = doc.getRoot(), scene = root.listScenes()[0];
if (root.listSkins().length) throw new Error('skinned input: use static.mjs');
await doc.transform(flatten());
// bake each mesh node's world matrix into its vertices, then reset the node
for (const node of root.listNodes()) {
  const mesh = node.getMesh(); if (!mesh) continue;
  transformMesh(mesh, node.getWorldMatrix());
  node.setTranslation([0, 0, 0]).setRotation([0, 0, 0, 1]).setScale([1, 1, 1]);
}
const b = getBounds(scene), k = Number(h) / (b.max[1] - b.min[1]);
const cx = (b.min[0] + b.max[0]) / 2, cz = (b.min[2] + b.max[2]) / 2;
const M = [k, 0, 0, 0, 0, k, 0, 0, 0, 0, k, 0, -cx * k, -b.min[1] * k, -cz * k, 1];
for (const mesh of root.listMeshes()) transformMesh(mesh, M);
for (const a of root.listAnimations()) a.dispose();
for (const ext of root.listExtensionsUsed()) if (/meshopt|quantiz|draco/i.test(ext.extensionName)) ext.dispose();
await doc.transform(prune());
const nb = getBounds(scene);
console.log('scale', k.toFixed(4), 'bounds', nb.min.map(v => v.toFixed(3)).join(' '), '|', nb.max.map(v => v.toFixed(3)).join(' '));
await io.write(out, doc);
