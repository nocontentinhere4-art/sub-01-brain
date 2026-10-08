// v5 -> a static bind-pose GLB for an auto-rigger: no skin, no animations, no meshopt/quantization, PNG textures,
// turned to face +Z (glTF front). Prints the bind pose of the arms so we know if it is a T- or A-pose.
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { dequantize, prune } from '@gltf-transform/functions';
import { MeshoptDecoder } from 'meshoptimizer';
import sharp from 'sharp';
import * as THREE from 'three';
await MeshoptDecoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({'meshopt.decoder': MeshoptDecoder});
const doc = await io.read(process.argv[2]);
const root = doc.getRoot();
// the arms in bind pose, from the inverse bind matrices
const skin = root.listSkins()[0], ibm = skin.getInverseBindMatrices();
const pos = {}; skin.listJoints().forEach((j, i) => { const m = new THREE.Matrix4().fromArray(ibm.getElement(i, [])).invert(); pos[j.getName()] = new THREE.Vector3().setFromMatrixPosition(m); });
for (const n of ['L_Upperarm','L_UpperArm','L_Forearm','L_Hand','R_Upperarm','R_Hand','Head','Hip']) if (pos[n]) console.log('bind', n, pos[n].toArray().map(v=>v.toFixed(3)).join(' '));
console.log('joints', Object.keys(pos).join(' '));
await doc.transform(dequantize());
for (const a of root.listAnimations()) a.dispose();
for (const n of root.listNodes()) if (n.getSkin()) n.setSkin(null);
for (const s of root.listSkins()) s.dispose();
for (const m of root.listMeshes()) for (const p of m.listPrimitives()) for (const k of ['JOINTS_0','WEIGHTS_0']) { const a = p.getAttribute(k); if (a) { p.setAttribute(k, null); } }
// skinned meshes ignore their node transforms in glTF: the vertices already sit in the bind pose. So take the
// positions as they are (no parent scale baked in) and only turn him -90 deg about Y so he faces +Z.
const scene = root.listScenes()[0];
const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0), -Math.PI/2).toArray();
const meshNodes = root.listNodes().filter(n => n.getMesh());
// feet on y = 0 and 1.75 m tall (the bind space is 2.0 m tall about its middle; the page scales it at runtime)
const K = 1.75 / 2.0;
for (const n of meshNodes) { for (const par of n.listParents()) if (par.propertyType === 'Node' || par.propertyType === 'Scene') par.removeChild(n); scene.addChild(n); n.setTranslation([0, 1.0 * K, 0]).setRotation(q).setScale([K,K,K]); }
for (const n of root.listNodes()) if (!n.getMesh()) n.dispose();
for (const ext of root.listExtensionsUsed()) if (['EXT_meshopt_compression','KHR_mesh_quantization'].includes(ext.extensionName)) ext.dispose();
for (const tex of root.listTextures()) { if (tex.getMimeType() !== 'image/png') { tex.setImage(await sharp(Buffer.from(tex.getImage())).png().toBuffer()); tex.setMimeType('image/png'); } }
for (const ext of root.listExtensionsUsed()) if (ext.extensionName === 'EXT_texture_webp') ext.dispose();
await doc.transform(prune());
await io.write(process.argv[3], doc);
let tris = 0; for (const m of root.listMeshes()) for (const p of m.listPrimitives()) tris += p.getIndices().getCount()/3;
console.log('written', process.argv[3], 'tris', tris, 'meshes', root.listMeshes().length);
