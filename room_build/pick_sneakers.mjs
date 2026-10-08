// node pick_sneakers.mjs <room_clean.glb from preview/props-soft 0cbc9ce> <room_clean.glb of this branch> ../web/room/sneakers_door.glb
// The room upgrade (preview/room-upgrade) takes ONLY the upright pair of worn canvas sneakers by the door from
// preview/props-soft (room_build/props_soft.py sneakers(): between the fridge and the door's hinge-side casing, toes to the
// wall). That branch baked them into its room_clean.glb's joined static mesh; this lifts their triangles out of it: the
// "painted" (soles, laces, eyelets) and "jersey" (canvas) triangles inside the box below that are not in this branch's own
// room (a few painted triangles there belong to the room). Positions, vertex colours, UVs and the two materials as they are.
import { NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS } from "@gltf-transform/extensions";
import { prune, dedup, meshopt } from "@gltf-transform/functions";
import { MeshoptEncoder, MeshoptDecoder } from "meshoptimizer";

const [SOFT, OURS, OUT] = process.argv.slice(2);
await MeshoptEncoder.ready; await MeshoptDecoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({"meshopt.encoder": MeshoptEncoder, "meshopt.decoder": MeshoptDecoder});
const BOX = [[0.90, 0.155, -1.445], [1.15, 0.33, -1.08]], MATS = ["painted", "jersey"];
const world = (M, v) => [0, 1, 2].map(r => M[r] * v[0] + M[4 + r] * v[1] + M[8 + r] * v[2] + M[12 + r]);
const key = (a, b, c) => [a, b, c].map(w => w.map(x => Math.round(x * 1e4)).join(",")).sort().join("|");
// the triangles this branch's room already has in the box (by their corners)
const own = new Set(), ours = await io.read(OURS);
for (const node of ours.getRoot().listNodes()) { const mesh = node.getMesh(); if (!mesh) continue; const M = node.getWorldMatrix();
  for (const p of mesh.listPrimitives()) { const pos = p.getAttribute("POSITION"), I = p.getIndices().getArray(), v = [0, 0, 0];
    const W = i => world(M, pos.getElement(i, v));
    for (let t = 0; t < I.length; t += 3) own.add(key(W(I[t]), W(I[t + 1]), W(I[t + 2]))); } }
const doc = await io.read(SOFT), root = doc.getRoot(); const kept = {};
for (const node of root.listNodes()) { const mesh = node.getMesh(); if (!mesh) continue; const M = node.getWorldMatrix();
  for (const p of mesh.listPrimitives()) {
    const name = p.getMaterial()?.getName();
    if (node.getName() !== "room_static" || !MATS.includes(name)) { mesh.removePrimitive(p); continue; }
    const pos = p.getAttribute("POSITION"), I = p.getIndices().getArray(), v = [0, 0, 0], keep = [];
    const W = i => world(M, pos.getElement(i, v)), inside = w => w.every((x, k) => x >= BOX[0][k] && x <= BOX[1][k]);
    for (let t = 0; t < I.length; t += 3) { const a = W(I[t]), b = W(I[t + 1]), c = W(I[t + 2]);
      if (inside(a) && inside(b) && inside(c) && !own.has(key(a, b, c))) keep.push(I[t], I[t + 1], I[t + 2]); }
    if (!keep.length) { mesh.removePrimitive(p); continue; }
    p.getIndices().setArray(new Uint32Array(keep)); kept[name] = keep.length / 3;
  }
  if (!mesh.listPrimitives().length) node.setMesh(null);
}
for (const n of root.listNodes()) if (n.getName() !== "room_static") n.dispose();
root.listNodes().find(n => n.getName() === "room_static")?.setName("sneakers_door");
for (const m of root.listMeshes()) m.setName("sneakers_door");
await doc.transform(prune(), dedup(), meshopt({encoder: MeshoptEncoder, level: "medium"}));
await io.write(OUT, doc);
console.log(OUT, kept);
