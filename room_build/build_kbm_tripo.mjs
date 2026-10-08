// node build_kbm_tripo.mjs <folder with kbtripo.glb, mstripo.glb> ../web/room/mouse.glb ../web/room   (writes keyboard_tripo.glb, mouse_tripo.glb)
// The keyboard and the mouse made with Tripo (paid API, image-to-model, P1-20260311, from renders of the ones modelled in
// code), turned and scaled to the same real sizes and origins as those, for comparison (the page: ?debug&kb=tripo). The
// keyboard's origin is where the modelled one has the middle of F and J, so the page places either by the same numbers;
// the mouse's is the middle of its base, its front towards -z. The mouse file carries the code-made pad too.
import { NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS, EXTMeshoptCompression } from "@gltf-transform/extensions";
import { mergeDocuments, dedup, prune, flatten, weld, quantize, reorder, textureCompress, unpartition } from "@gltf-transform/functions";
import { MeshoptEncoder, MeshoptDecoder } from "meshoptimizer";
import sharp from "sharp";

const [dir, procMouse, outDir] = process.argv.slice(2);
await MeshoptEncoder.ready; await MeshoptDecoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({"meshopt.encoder": MeshoptEncoder, "meshopt.decoder": MeshoptDecoder});

function transformAll(doc, fn){
  const v = [0, 0, 0];
  for (const mesh of doc.getRoot().listMeshes()) for (const p of mesh.listPrimitives()) {
    const P = p.getAttribute("POSITION"), N = p.getAttribute("NORMAL");
    for (let i = 0; i < P.getCount(); i++) P.setElement(i, fn(P.getElement(i, v), false));
    if (N) for (let i = 0; i < N.getCount(); i++) N.setElement(i, fn(N.getElement(i, v), true));
  }
}
function bounds(doc){
  const lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9], v = [0, 0, 0];
  for (const mesh of doc.getRoot().listMeshes()) for (const p of mesh.listPrimitives()) { const P = p.getAttribute("POSITION");
    for (let i = 0; i < P.getCount(); i++) { P.getElement(i, v); for (let a = 0; a < 3; a++) { lo[a] = Math.min(lo[a], v[a]); hi[a] = Math.max(hi[a], v[a]); } } }
  return [lo, hi];
}
// turn about y by ry, then scale by k so the longest horizontal side is `len`, and put [lo..hi] x/z at the given box, y from 0
async function fit(file, ry, len, cx, cz, name){
  const doc = await io.read(file); await doc.transform(flatten());
  const c = Math.cos(ry), s = Math.sin(ry);
  transformAll(doc, ([x, y, z]) => [c * x + s * z, y, -s * x + c * z]);
  const [lo, hi] = bounds(doc), k = len / Math.max(hi[0] - lo[0], hi[2] - lo[2]);
  const ox = (lo[0] + hi[0]) / 2, oz = (lo[2] + hi[2]) / 2;
  transformAll(doc, ([x, y, z], n) => n ? [x, y, z] : [(x - ox) * k + cx, (y - lo[1]) * k, (z - oz) * k + cz]);
  const sc = doc.getRoot().listScenes()[0], node = doc.createNode(name);
  for (const n of sc.listChildren()) { sc.removeChild(n); node.addChild(n); } sc.addChild(node);
  for (const m of doc.getRoot().listMeshes()) m.setName(name);
  const [l2, h2] = bounds(doc);
  console.log(name, "size", h2.map((h, a) => (h - l2[a]).toFixed(3)).join(" x "), "m");
  return doc;
}
async function write(doc, out){
  await doc.transform(textureCompress({encoder: sharp, targetFormat: "webp", resize: [1024, 1024], quality: 85}), dedup(), unpartition(), weld(), prune(), reorder({encoder: MeshoptEncoder}), quantize());
  doc.createExtension(EXTMeshoptCompression).setRequired(true).setEncoderOptions({method: EXTMeshoptCompression.EncoderMethod.QUANTIZE});
  await io.write(out, doc);
  const tris = doc.getRoot().listMeshes().flatMap(m => m.listPrimitives()).reduce((a, p) => a + p.getIndices().getCount() / 3, 0);
  console.log(out, tris, "triangles");
}
// the keyboard: Tripo's lies along z with Esc at +z/-x: turned -pi/2 it reads left to right with its back to -z. Its footprint
// goes where the code-made one's case is around its F/J origin (x -0.140..+0.301, z -0.110..+0.052: 0.441 m long)
await write(await fit(`${dir}/kbtripo.glb`, -Math.PI / 2, 0.441, 0.0805, -0.029, "keyboard"), `${outDir}/keyboard_tripo.glb`);
// the mouse: along z already, its front (the wheel) at -z; 11.8 cm long, its origin the middle of its base; plus the pad
const md = await fit(`${dir}/mstripo.glb`, 0, 0.118, 0, 0, "mouse");
const pd = await io.read(procMouse), padNode = pd.getRoot().listNodes().find(n => n.getName() === "mousepad");
for (const n of pd.getRoot().listNodes()) if (n !== padNode && !n.listParents().includes(padNode)) n.dispose();
for (const s of pd.getRoot().listScenes()) for (const n of s.listChildren()) if (n !== padNode) s.removeChild(n);
const map = mergeDocuments(md, pd), other = map.get(pd.getRoot().listScenes()[0]);
for (const n of other.listChildren()) { other.removeChild(n); md.getRoot().listScenes()[0].addChild(n); } other.dispose();
await write(md, `${outDir}/mouse_tripo.glb`);
