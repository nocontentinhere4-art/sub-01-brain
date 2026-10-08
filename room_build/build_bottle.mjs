// node build_bottle.mjs <raw bottle.glb from Tripo> ../web/room/bottle.glb
// Fits the bottle of green tea made with Tripo's paid API (image-to-model, v3.1, PBR) to the place room.html already
// keeps for it: one node T_bottle, in metres, its long axis +y and the cap up, its origin where the page puts the prop
// (PROP.bottle sits at BOTTLE_AT + (0, 0.08, 0)), so the base lands exactly on the desk top. Scaled by its width, not
// its height: room.html's collision box reserves a 8 cm square for it and his right hand is solved against a 3.2 cm
// radius, so the radius is what has to hold. Tripo bakes a metal look into the ORM map; a PET bottle is not metal, so
// the metallic factor goes to 0. Textures: colour 1024 px, the metal/roughness and normal maps 512, WebP, meshopt.
// The raw download is not committed; its task id is in ../web/room/CREDITS.md.
import { NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS, EXTMeshoptCompression } from "@gltf-transform/extensions";
import { dedup, prune, unpartition, reorder, quantize, weld, textureCompress, flatten } from "@gltf-transform/functions";
import { MeshoptEncoder, MeshoptDecoder } from "meshoptimizer";
import sharp from "sharp";

const WIDTH = 0.064;        // across the body: radius 3.2 cm, as the procedural bottle it replaces
const BASE_BELOW = 0.08;    // the base sits this far under the origin (room.html: BOTTLE_AT + (0, 0.08, 0))
const RY = 0.7;             // turned so the label's front faces the overview camera
const MAPS = {baseColour: 1024, other: 512};

const [src, out] = process.argv.slice(2);
await MeshoptEncoder.ready; await MeshoptDecoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS)
  .registerDependencies({"meshopt.encoder": MeshoptEncoder, "meshopt.decoder": MeshoptDecoder});

// bake a turn about the vertical, a scale and an offset into every position (and the turn into the normals)
function bake(doc, ry, k, off){
  const c = Math.cos(ry), s = Math.sin(ry);
  for (const mesh of doc.getRoot().listMeshes()) for (const p of mesh.listPrimitives()) {
    const pos = p.getAttribute("POSITION"), nor = p.getAttribute("NORMAL"), v = [0, 0, 0];
    for (let i = 0; i < pos.getCount(); i++) { pos.getElement(i, v);
      const x = c * v[0] + s * v[2], z = -s * v[0] + c * v[2];
      pos.setElement(i, [(x + off[0]) * k, (v[1] + off[1]) * k, (z + off[2]) * k]); }
    if (nor) for (let i = 0; i < nor.getCount(); i++) { nor.getElement(i, v); nor.setElement(i, [c * v[0] + s * v[2], v[1], -s * v[0] + c * v[2]]); }
  }
}
function bounds(doc){
  const lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9], v = [0, 0, 0];
  for (const mesh of doc.getRoot().listMeshes()) for (const p of mesh.listPrimitives()) {
    const pos = p.getAttribute("POSITION"); for (let i = 0; i < pos.getCount(); i++) { pos.getElement(i, v);
      for (let a = 0; a < 3; a++) { lo[a] = Math.min(lo[a], v[a]); hi[a] = Math.max(hi[a], v[a]); } } }
  return [lo, hi];
}

const doc = await io.read(src);
await doc.transform(flatten());
bake(doc, RY, 1, [0, 0, 0]);
const [lo, hi] = bounds(doc);
const k = WIDTH / Math.max(hi[0] - lo[0], hi[2] - lo[2]);
bake(doc, 0, k, [-(lo[0] + hi[0]) / 2, -lo[1] - BASE_BELOW / k, -(lo[2] + hi[2]) / 2]);

for (const m of doc.getRoot().listMaterials()) { m.setName("tripo_bottle"); m.setMetallicFactor(0); }
// resize each map with sharp before the WebP pass: the colour carries the label, the rest can be half that
for (const t of doc.getRoot().listTextures()) {
  const px = doc.getRoot().listMaterials().some(m => m.getBaseColorTexture() === t) ? MAPS.baseColour : MAPS.other;
  t.setImage(await sharp(Buffer.from(t.getImage())).resize(px, px, {fit: "fill"}).png().toBuffer()).setMimeType("image/png");
}
const sc = doc.getRoot().listScenes()[0], g = doc.createNode("T_bottle");
for (const n of sc.listChildren()) { sc.removeChild(n); g.addChild(n); } sc.addChild(g);

await doc.transform(
  textureCompress({encoder: sharp, targetFormat: "webp", quality: 88}),
  dedup(), unpartition(), weld(), prune(), reorder({encoder: MeshoptEncoder}), quantize());
doc.createExtension(EXTMeshoptCompression).setRequired(true).setEncoderOptions({method: EXTMeshoptCompression.EncoderMethod.QUANTIZE});
await io.write(out, doc);

const [lo2, hi2] = bounds(doc);
const tris = doc.getRoot().listMeshes().reduce((a, m) => a + m.listPrimitives().reduce((b, p) => b + p.getIndices().getCount() / 3, 0), 0);
console.log(out, "| triangles", tris, "| size (m)", hi2.map((h, a) => (h - lo2[a]).toFixed(4)).join(" x "),
            "| base y", lo2[1].toFixed(4), "| top y", hi2[1].toFixed(4));
