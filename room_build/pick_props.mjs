// node pick_props.mjs <props_clutter.glb from preview/props-hard e3c0376> ../web/room/props_picked.glb
// The room upgrade (preview/room-upgrade) keeps only the owner-approved pieces of preview/props-hard's clutter: the woven
// laundry basket (Poly Haven's wicker_basket_02 scan), the shallow key bowl (wooden_bowl_02) with the keys lying in it
// (their brass, leather fob and remote), and the notebook with the pen and the pencil (no logos). Everything else in
// props_clutter.glb is dropped, and so are the pieces of these materials that lie outside the boxes below (the leather of
// a wallet beside the bowl). Positions, materials and textures are kept as they are (world metres).
import { NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS } from "@gltf-transform/extensions";
import { prune, dedup, meshopt } from "@gltf-transform/functions";
import { MeshoptEncoder, MeshoptDecoder } from "meshoptimizer";

const [IN, OUT] = process.argv.slice(2);
await MeshoptEncoder.ready; await MeshoptDecoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({"meshopt.encoder": MeshoptEncoder, "meshopt.decoder": MeshoptDecoder});
const BOWL = [[1.66, 0.47, -0.66], [1.83, 0.56, -0.49]];               // the key bowl on the cabinet by the door
const KEEP = {                                                           // material -> the world box its triangles must lie in
  wicker_basket_02: [[-0.10, 0.10, -1.25], [0.40, 0.50, -0.60]],         // the laundry basket
  wooden_bowl_02: BOWL, brass: BOWL, leather: BOWL, connector: BOWL,     // the bowl and the keys in it
  binder_notebook: [[-1.90, 0.95, -1.45], [-1.60, 1.02, -1.15]],         // the notebook on the desk
  stationery_supplies: [[-1.90, 0.95, -1.45], [-1.60, 1.02, -1.15]],     // the pen and the pencil on it
};
const doc = await io.read(IN), root = doc.getRoot();
const kept = {};
for (const node of root.listNodes()) { const mesh = node.getMesh(); if (!mesh) continue; const M = node.getWorldMatrix();
  for (const p of mesh.listPrimitives()) {
    const name = p.getMaterial()?.getName(), box = KEEP[name];
    if (!box) { mesh.removePrimitive(p); p.dispose(); continue; }
    const pos = p.getAttribute("POSITION"), I = p.getIndices().getArray(), v = [0, 0, 0], keep = [];
    const inside = i => { pos.getElement(i, v); const w = [0, 1, 2].map(r => M[r] * v[0] + M[4 + r] * v[1] + M[8 + r] * v[2] + M[12 + r]);
      return w.every((x, k) => x >= box[0][k] && x <= box[1][k]); };
    for (let t = 0; t < I.length; t += 3) if (inside(I[t]) && inside(I[t + 1]) && inside(I[t + 2])) keep.push(I[t], I[t + 1], I[t + 2]);
    if (!keep.length) { mesh.removePrimitive(p); p.dispose(); continue; }
    p.getIndices().setArray(new Uint32Array(keep)); kept[name] = (kept[name] || 0) + keep.length / 3;
  }
  if (!mesh.listPrimitives().length) node.setMesh(null);
}
for (const n of root.listNodes()) if (!n.getMesh() && !n.listChildren().length) n.dispose();
await doc.transform(prune(), dedup(), meshopt({encoder: MeshoptEncoder, level: "medium"}));
await io.write(OUT, doc);
console.log(OUT, kept, "nodes:", root.listNodes().map(n => n.getName()).join(", "));
