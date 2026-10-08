// node build_food.mjs <Kenney "Food Kit" GLB folder> ../web/room/food.glb
// Packs the food models the room uses (#63) into one small GLB: one scene node per model, named after its Kenney file,
// the shared palette texture once, meshopt-compressed. Kenney's Food Kit is CC0 (https://kenney.nl/assets/food-kit).
import { NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS, EXTMeshoptCompression } from "@gltf-transform/extensions";
import { mergeDocuments, dedup, prune, unpartition, reorder, quantize, weld } from "@gltf-transform/functions";
import { MeshoptEncoder, MeshoptDecoder } from "meshoptimizer";

const MODELS = ["bowl-broth", "bowl", "bowl-soup", "plate-rectangle", "sushi-salmon", "sushi-egg", "maki-salmon", "bag-flat",
  "pizza-box", "pizza", "rice-ball", "croissant", "bag", "chopstick"];
const [dir, out] = process.argv.slice(2);
await MeshoptEncoder.ready; await MeshoptDecoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS)
  .registerDependencies({"meshopt.encoder": MeshoptEncoder, "meshopt.decoder": MeshoptDecoder});
const doc = await io.read(`${dir}/${MODELS[0]}.glb`);
const root = doc.getRoot(), scene = root.listScenes()[0];
const wrap = (sc, name) => {                          // the model's top nodes under one node "F_<name>"
  const g = doc.createNode("F_" + name); for (const n of sc.listChildren()) { sc.removeChild(n); g.addChild(n); } return g;
};
const first = wrap(scene, MODELS[0]); scene.addChild(first);
for (const m of MODELS.slice(1)) {
  const map = mergeDocuments(doc, await io.read(`${dir}/${m}.glb`));
  const sc = root.listScenes().find(s => map.get(s) === s || [...map.values()].includes(s) && s !== scene) || root.listScenes()[root.listScenes().length - 1];
  scene.addChild(wrap(sc, m)); sc.dispose();
}
await doc.transform(dedup(), unpartition(), weld(), prune(), reorder({encoder:MeshoptEncoder}), quantize());
doc.createExtension(EXTMeshoptCompression).setRequired(true).setEncoderOptions({method:EXTMeshoptCompression.EncoderMethod.QUANTIZE});
await io.write(out, doc);
console.log(out, scene.listChildren().map(n => n.getName()).join(" "));
