// node post.mjs in.glb ao.png out.glb [ao_chair.png] : AO lightmaps as occlusion (texCoord 1), WebP textures, meshopt; prints a report
import fs from "node:fs";
import { NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS } from "@gltf-transform/extensions";
import { dedup, prune, flatten, join, weld, meshopt, textureCompress, resample } from "@gltf-transform/functions";
import { MeshoptEncoder, MeshoptDecoder } from "meshoptimizer";
import sharp from "sharp";
const [,, IN, AO, OUT, AO_CHAIR] = process.argv;
await MeshoptEncoder.ready; await MeshoptDecoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({"meshopt.encoder": MeshoptEncoder, "meshopt.decoder": MeshoptDecoder});
const doc = await io.read(IN);
const root = doc.getRoot();

// --- the baked AO goes on every material of the static room mesh, read through the second UV set
const staticMesh = root.listNodes().find(n => n.getName() === "room_static").getMesh();
staticMesh.setName("room_static");
// marker nodes (SURF_*) are empty: flatten/prune would drop them, so keep their world transforms and re-add them at the end
const markers = root.listNodes().filter(n => n.getName().startsWith("SURF_")).map(n => ({name: n.getName(), m: n.getWorldMatrix(), extras: n.getExtras()}));
if (AO && fs.existsSync(AO)) {
  const {width: W} = await sharp(AO).metadata(), c = Math.ceil(W * 0.014);   // the tiny parts read a white corner
  const flat = await sharp(AO).composite([{input: {create: {width: c, height: c, channels: 3, background: "#ffffff"}}, left: W - c, top: 0}]).png().toBuffer();
  const png = await sharp(flat).greyscale().blur(0.9).toColourspace("b-w").png().toBuffer();
  const tex = doc.createTexture("room_ao").setImage(png).setMimeType("image/png").setURI("room_ao.png");
  for (const p of staticMesh.listPrimitives()) {
    const m = p.getMaterial(); if (!m) continue;
    m.setOcclusionTexture(tex); m.getOcclusionTextureInfo().setTexCoord(1); m.setOcclusionStrength(1.0);
  }
}
// the chair is its own node (it moves) with its own materials and its own AO (self-occlusion)
const chairNode = root.listNodes().find(n => n.getName() === "chair");
// (an extra marks its materials, so dedup/join can never fold the chair back into the static room)
if (chairNode) for (const p of chairNode.getMesh().listPrimitives()) p.getMaterial().setExtras({movable: "chair"});
// the headphones on the wall hook are their own node too (#75; a later change puts them on his head), with no AO
// and so are the things hanging on the door ("hangers", origin at the hinge: the page swings them with the leaf, #82)
for (const name of ["headphones", "hangers"]) {
  const n = root.listNodes().find(n => n.getName() === name);
  if (n) for (const p of n.getMesh().listPrimitives()) p.getMaterial().setExtras({movable: name});
}
if (chairNode && AO_CHAIR && fs.existsSync(AO_CHAIR)) {
  const png = await sharp(AO_CHAIR).greyscale().blur(0.6).toColourspace("b-w").png().toBuffer();
  const tex = doc.createTexture("chair_ao").setImage(png).setMimeType("image/png").setURI("chair_ao.png");
  for (const p of chairNode.getMesh().listPrimitives()) {
    const m = p.getMaterial(); m.setOcclusionTexture(tex); m.getOcclusionTextureInfo().setTexCoord(1); m.setOcclusionStrength(1.0);
  }
}
// the clocks' glass uses transmission, which costs three.js a whole extra render pass: plain alpha-blended glass instead
for (const m of root.listMaterials()) {
  const t = m.getExtension("KHR_materials_transmission");
  if (t) { m.setExtension("KHR_materials_transmission", null); t.dispose();
    const c = m.getBaseColorFactor(); m.setBaseColorFactor([c[0], c[1], c[2], 0.12]).setAlphaMode("BLEND").setRoughnessFactor(0.05).setMetallicFactor(0); }
}
for (const e of root.listExtensionsUsed()) if (e.extensionName === "KHR_materials_transmission") e.dispose();
// name textures after their first material slot, so that the resize rules below can target them
for (const t of root.listTextures()) if (!t.getName()) t.setName((t.getURI() || "tex").replace(/\.[a-z]+$/, ""));
const isProp = t => /desk_lamp|potted|wall_clock|alarm|cardboard|notepad/i.test(t.getName() + t.getURI());
console.log("textures:", root.listTextures().map(t => `${t.getName()} ${t.getImage().byteLength >> 10}K`).join(", "));
// vertex colours carry the edge wear (#98 G5); a primitive whose colours are all white has none: drop the attribute
for (const m of root.listMeshes()) for (const p of m.listPrimitives()) {
  const c = p.getAttribute("COLOR_0"); if (!c) continue;
  const v = []; let white = true;
  for (let i = 0; i < c.getCount() && white; i++) { c.getElement(i, v); for (let k = 0; k < 3; k++) if (v[k] < 0.998) { white = false; break; } }
  if (white) p.setAttribute("COLOR_0", null);
}

await doc.transform(
  dedup(), flatten(), join({keepNamed: false}), weld(), resample(),
  // big room surfaces keep detail, props and fabrics are small on screen
  // normal maps keep more quality (their relief is subtle); each texture is encoded once (later passes skip WebP)
  textureCompress({encoder: sharp, targetFormat: "webp", formats: /png|jpeg/, slots: /normalTexture/, resize: [1024, 1024], quality: 92}),
  textureCompress({encoder: sharp, targetFormat: "webp", formats: /png|jpeg/, pattern: /floor_diff/, resize: [2048, 2048], quality: 84}),
  textureCompress({encoder: sharp, targetFormat: "webp", formats: /png|jpeg/, pattern: /room_ao|chair_ao/, quality: 88}),
  textureCompress({encoder: sharp, targetFormat: "webp", formats: /png|jpeg/, resize: [1024, 1024], quality: 84}),
  prune({keepLeaves: true, keepAttributes: false}),
);
// quantisation (in meshopt) folds a dequantising scale and offset into each mesh node's transform; so that "chair" keeps
// its pivot (on the floor under the gas lift), its mesh goes into a child node and "chair" stays a plain transform node
for (const name of ["chair", "headphones", "hangers"]) {
  const ch = root.listNodes().find(n => n.getName() === name);
  if (ch && ch.getMesh()) { const mesh = ch.getMesh(); ch.setMesh(null); ch.addChild(doc.createNode(name + "_mesh").setMesh(mesh)); }
}
await doc.transform(meshopt({encoder: MeshoptEncoder, level: "medium"}));
// props: shrink their textures further
for (const t of root.listTextures()) {
  if (isProp(t)) {
    const im = await sharp(t.getImage()).resize(512, 512, {fit: "inside"}).webp({quality: 80}).toBuffer();
    t.setImage(im).setMimeType("image/webp");
  }
}
const scene = root.listScenes()[0];
for (const k of markers) { const n = doc.createNode(k.name).setMatrix(k.m).setExtras(k.extras); scene.addChild(n); }
await io.write(OUT, doc);
const sz = fs.statSync(OUT).size;
let prims = 0, tris = 0;
for (const n of root.listNodes()) { const m = n.getMesh(); if (!m) continue; for (const p of m.listPrimitives()) { prims++; const i = p.getIndices(); tris += (i ? i.getCount() : p.getAttribute("POSITION").getCount()) / 3; } }
console.log(`out ${OUT}: ${(sz / 1048576).toFixed(2)} MB, ${prims} primitives (draw calls), ${Math.round(tris)} triangles`);
console.log("textures:", root.listTextures().map(t => `${t.getName()} ${t.getImage().byteLength >> 10}K`).join(", "));
console.log("nodes:", root.listNodes().filter(n => !n.getMesh()).map(n => n.getName()).join(", "));
const ch = root.listNodes().find(n => n.getName() === "chair");
if (ch) console.log("chair:", JSON.stringify({t: ch.getTranslation(), r: ch.getRotation(), s: ch.getScale(), children: ch.listChildren().map(c => c.getName())}));
for (const name of ["headphones", "hangers"]) { const n = root.listNodes().find(n => n.getName() === name);
  if (n) console.log(name + ":", JSON.stringify({t: n.getTranslation(), children: n.listChildren().map(c => c.getName())})); }
