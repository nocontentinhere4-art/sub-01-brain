// node rig/autorig/refskel.mjs <any Mixamo FBX on the Standard Skeleton> <out.json>
// The Mixamo Standard Skeleton's rest (T-pose) as FBXLoader reads it: per bone the name (mixamorig:*), the parent, the
// world position (cm) and world rotation. fit.py copies the rotations and keeps the directions; it places the joints.
import fs from "node:fs";
globalThis.self = globalThis; globalThis.window = globalThis;
const THREE = await import("three");
const { FBXLoader } = await import("three/examples/jsm/loaders/FBXLoader.js");
const [IN, OUT] = process.argv.slice(2), b = fs.readFileSync(IN);
const g = new FBXLoader().parse(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength), ""); g.updateMatrixWorld(true);
const bones = []; g.traverse(o => { if (o.isBone) bones.push(o); });
const fix = n => n.replace(/^mixamorig\d*:?/, "mixamorig:");
const out = bones.map(o => ({name: fix(o.name), parent: o.parent && o.parent.isBone ? fix(o.parent.name) : null,
  p: o.getWorldPosition(new THREE.Vector3()).toArray(), q: o.getWorldQuaternion(new THREE.Quaternion()).toArray()}));
fs.writeFileSync(OUT, JSON.stringify(out));
console.log(`${out.length} bones -> ${OUT}`);
