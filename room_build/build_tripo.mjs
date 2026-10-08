// node build_tripo.mjs <folder with the raw Tripo GLBs> ../web/room/props_tripo.glb
// Packs the four props generated with Tripo's paid API (text-to-model, P1-20260311, PBR) into one small GLB: one scene node
// per prop, named T_<name>, at real size in metres with its origin at the centre of its base, the textures cut to
// 1024 px WebP, meshopt-compressed. The page (web/room.html, "Tripo props") puts them in place. The raw files are not
// committed; their task ids are in ../web/room/CREDITS.md.
import { NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS, EXTMeshoptCompression } from "@gltf-transform/extensions";
import { mergeDocuments, dedup, prune, unpartition, reorder, quantize, weld, textureCompress, flatten } from "@gltf-transform/functions";
import { MeshoptEncoder, MeshoptDecoder } from "meshoptimizer";
import sharp from "sharp";

// file, the size it gets (its longest horizontal side, or its height), the turn about the vertical (radians, applied first)
const PROPS = [
  {name:"ramen", file:"ramen2.glb", horiz:0.18, ry:Math.PI},          // the bowl ~15 cm like the Kenney one; its chopsticks to -x
  {name:"mug", file:"mug_b.glb", height:0.097, ry:-Math.PI / 2},      // the desk mug's height; its handle turned to +x as before
  {name:"headphones", file:"headphones_b.glb", height:0.20, ry:Math.PI / 2},   // cups left and right (x), band on top
  {name:"sneakers", file:"sneakers_b.glb", horiz:0.29, ry:0},         // a pair side by side, toes to +z
];
const [dir, out] = process.argv.slice(2);
await MeshoptEncoder.ready; await MeshoptDecoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS)
  .registerDependencies({"meshopt.encoder": MeshoptEncoder, "meshopt.decoder": MeshoptDecoder});

// bake a turn, a scale and an offset into every position (and the turn into the normals) of a document's meshes
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

let doc = null;
for (const pr of PROPS) {
  const d = await io.read(`${dir}/${pr.file}`);
  await d.transform(flatten());                          // (Tripo's files hold one node with no transform; make sure)
  bake(d, pr.ry, 1, [0, 0, 0]);
  const [lo, hi] = bounds(d);
  const k = pr.height ? pr.height / (hi[1] - lo[1]) : pr.horiz / Math.max(hi[0] - lo[0], hi[2] - lo[2]);
  bake(d, 0, k, [-(lo[0] + hi[0]) / 2, -lo[1], -(lo[2] + hi[2]) / 2]);
  for (const m of d.getRoot().listMaterials()) m.setName(`tripo_${pr.name}`);
  const sc = d.getRoot().listScenes()[0], g = d.createNode("T_" + pr.name);
  for (const n of sc.listChildren()) { sc.removeChild(n); g.addChild(n); } sc.addChild(g);
  const [lo2, hi2] = bounds(d);
  console.log(pr.name, "size (m)", hi2.map((h, a) => (h - lo2[a]).toFixed(3)).join(" x "));
  if (!doc) { doc = d; continue; }
  const map = mergeDocuments(doc, d), scene = doc.getRoot().listScenes()[0];
  const other = map.get(sc); for (const n of other.listChildren()) { other.removeChild(n); scene.addChild(n); } other.dispose();
}
await doc.transform(
  textureCompress({encoder:sharp, targetFormat:"webp", resize:[1024, 1024], quality:85}),
  dedup(), unpartition(), weld(), prune(), reorder({encoder:MeshoptEncoder}), quantize());
doc.createExtension(EXTMeshoptCompression).setRequired(true).setEncoderOptions({method:EXTMeshoptCompression.EncoderMethod.QUANTIZE});
await io.write(out, doc);
const tris = doc.getRoot().listMeshes().map(m => m.getName() + " " + m.listPrimitives().reduce((a, p) => a + p.getIndices().getCount() / 3, 0));
console.log(out, doc.getRoot().listScenes()[0].listChildren().map(n => n.getName()).join(" "), "|", tris.join(", "));
