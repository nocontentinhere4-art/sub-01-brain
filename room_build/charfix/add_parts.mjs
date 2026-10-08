// node add_parts.mjs <in.glb> <out.glb> <parts.json>
// Adds skinned parts to the v5 character: each a new node and mesh on the same skeleton as its "slides" part (a skin
// whose bind is the identity: positions in the rig's world at bind, metres), from raw little-endian files written by
// room_build/char_fix (P f32x3, N f32x3, UV f32x2, J u16x4, W f32x4, I u32). parts.json: [{name, dir, material:
// {name, color:[r,g,b], roughness, metalness, doubleSided, map, normalMap, ormMap, mirror, from}}], `map` & co. image files
// (`mirror`: MIRRORED_REPEAT wrapping, for a small patch tiled).
// `drop`: names of nodes to remove (their meshes go too). Writes with meshopt, like the source.
import { NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS, EXTMeshoptCompression } from "@gltf-transform/extensions";
import { prune, reorder } from "@gltf-transform/functions";
import { MeshoptEncoder, MeshoptDecoder } from "meshoptimizer";
import fs from "fs";
const [src, dst, spec] = process.argv.slice(2);
await MeshoptEncoder.ready; await MeshoptDecoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({"meshopt.encoder": MeshoptEncoder, "meshopt.decoder": MeshoptDecoder});
const doc = await io.read(src), root = doc.getRoot(), buf = root.listBuffers()[0], S = JSON.parse(fs.readFileSync(spec, "utf8"));
const old = root.listNodes().find(n => n.getName() === "slides"), skin = old.getSkin(), parent = old.getParentNode() || null;
const T0 = old.getTranslation(), R0 = old.getRotation(), S0 = old.getScale();
const scene = root.listScenes()[0];
for (const name of S.drop || []) { const n = root.listNodes().find(x => x.getName() === name); if (n) { const m = n.getMesh(); n.dispose(); if (m) m.dispose(); } }
const rd = (f, T) => { const b = fs.readFileSync(f); return new T(b.buffer, b.byteOffset, b.byteLength / T.BYTES_PER_ELEMENT); };
const tex = (f, mime) => doc.createTexture(f).setImage(fs.readFileSync(f)).setMimeType(mime || (f.endsWith(".png") ? "image/png" : f.endsWith(".webp") ? "image/webp" : "image/jpeg"));
for (const p of S.parts) {
  const d = p.dir, mt = p.material;
  // (`from`: a copy of the source's material of that name, its own textures and all, e.g. the hood's fabric for a patch
  // in it; `doubleSided` as given)
  const src0 = mt.from && root.listMaterials().find(m => m.getName() === mt.from);
  if (mt.from && !src0) throw new Error(`no material ${mt.from}`);
  const mat = src0 ? src0.clone().setName(mt.name).setDoubleSided(!!mt.doubleSided)
    : doc.createMaterial(mt.name).setBaseColorFactor([...(mt.color || [1, 1, 1]), 1]).setRoughnessFactor(mt.roughness ?? 0.9).setMetallicFactor(mt.metalness ?? 0).setDoubleSided(!!mt.doubleSided);
  if (mt.map) mat.setBaseColorTexture(tex(mt.map)); if (mt.normalMap) mat.setNormalTexture(tex(mt.normalMap)); if (mt.ormMap) mat.setMetallicRoughnessTexture(tex(mt.ormMap));
  if (mt.mirror) for (const ti of [mat.getBaseColorTextureInfo(), mat.getNormalTextureInfo(), mat.getMetallicRoughnessTextureInfo()]) if (ti) ti.setWrapS(10497 + 33648 - 10497).setWrapT(33648);   // (MIRRORED_REPEAT: a small patch tiles without seams)
  const acc = (arr, type) => doc.createAccessor().setType(type).setArray(arr).setBuffer(buf);
  const prim = doc.createPrimitive().setMaterial(mat).setIndices(acc(rd(`${d}/I.bin`, Uint32Array), "SCALAR"))
    .setAttribute("POSITION", acc(rd(`${d}/P.bin`, Float32Array), "VEC3")).setAttribute("NORMAL", acc(rd(`${d}/N.bin`, Float32Array), "VEC3"))
    .setAttribute("TEXCOORD_0", acc(rd(`${d}/UV.bin`, Float32Array), "VEC2"))
    .setAttribute("JOINTS_0", acc(rd(`${d}/J.bin`, Uint16Array), "VEC4")).setAttribute("WEIGHTS_0", acc(rd(`${d}/W.bin`, Float32Array), "VEC4"));
  const node = doc.createNode(p.name).setMesh(doc.createMesh(p.name).addPrimitive(prim)).setSkin(skin)
    .setTranslation(T0).setRotation(R0).setScale(S0);
  if (parent) parent.addChild(node); else scene.addChild(node);
  console.log("added", p.name, prim.getIndices().getCount() / 3, "triangles");
}
// keep "slides" the last skinned part (the page's skinMesh() takes the last one it finds)
const slides = root.listNodes().find(n => n.getName() === "slides" && n.getMesh());
if (slides) { const p = slides.getParentNode() || scene; p.removeChild(slides); p.addChild(slides); }
// (no re-quantizing: the source's parts are quantized already, each with its dequantization folded into its skin's inverse
// bind matrices, and a part split off the body shares the body's skin; quantizing again moved those parts against their
// skins. The new parts stay float, meshopt-compressed as they are)
await doc.transform(prune({keepAttributes: true}), reorder({encoder: MeshoptEncoder}));
doc.createExtension(EXTMeshoptCompression).setRequired(true).setEncoderOptions({method: EXTMeshoptCompression.EncoderMethod.QUANTIZE});
await io.write(dst, doc);
console.log("wrote", dst, fs.statSync(dst).size);
