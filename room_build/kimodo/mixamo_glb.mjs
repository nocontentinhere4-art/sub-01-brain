// node mixamo_glb.mjs <in.fbx> <out.glb> [--test-skin] [--no-anim]
// A Mixamo FBX as a GLB the room page loads as it is: the skeleton (mixamorig:* bones, 65 with the fingers), any skinned
// meshes on it, and its animation, with nothing renamed or retargeted (three.js keeps the bone names as "mixamorigHips"
// etc., the colon dropped, in the character and in its clips alike, so a clip plays on the character by bone name).
// Mixamo's FBX is in centimetres: the whole scene sits under one node scaled 0.01 (the bones and the animation keep
// Mixamo's own numbers).
//   --test-skin: bind a plain body (a box along each bone) to the skeleton, for testing the skinned path with a clip
//                downloaded "Without Skin"
//   --no-anim:   the character only
//   --no-textures: skip the FBX's textures (Node cannot decode them; rig/mixamo_import.sh puts our own back)
// Mixamo's terms allow its characters and animations in a game or app but not the raw files redistributed: the FBX stays
// out of the repository.
import fs from "node:fs";
globalThis.self = globalThis; globalThis.window = globalThis;
globalThis.FileReader = class {                              // (GLTFExporter's binary path, in Node)
  readAsArrayBuffer(b) { b.arrayBuffer().then(r => { this.result = r; this.onloadend && this.onloadend(); }); }
  readAsDataURL(b) { b.arrayBuffer().then(r => { this.result = "data:application/octet-stream;base64," + Buffer.from(r).toString("base64"); this.onloadend && this.onloadend(); }); }
};
const THREE = await import("three");
const { FBXLoader } = await import("three/examples/jsm/loaders/FBXLoader.js");
const { GLTFExporter } = await import("three/examples/jsm/exporters/GLTFExporter.js");

const args = process.argv.slice(2), SRC = args[0], OUT = args[1];
if (args.includes("--no-textures")) THREE.TextureLoader.prototype.load = () => new THREE.Texture();
const buf = fs.readFileSync(SRC);
const g = new FBXLoader().parse(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength), "");
const bones = []; g.traverse(o => { if (o.isBone) bones.push(o); });
if (!bones.find(b => /Hips$/.test(b.name))) throw new Error(`${SRC}: no mixamorig Hips`);

if (args.includes("--test-skin")) {                          // a box from each bone to each child bone, all weight on the bone
  g.updateMatrixWorld(true);
  const pos = [], idx = [], wts = [], ix = new Map(bones.map((b, i) => [b, i]));
  const add = (a, b, i) => {
    const d = b.clone().sub(a), L = d.length(); if (L < 1e-3) return;
    const w = Math.max(1.5, Math.min(6, L * 0.25)), q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), d.clone().normalize());
    const box = new THREE.BoxGeometry(w, L, w).translate(0, L / 2, 0); box.applyQuaternion(q); box.translate(a.x, a.y, a.z);
    const P = box.toNonIndexed().attributes.position;
    for (let k = 0; k < P.count; k++) { pos.push(P.getX(k), P.getY(k), P.getZ(k)); idx.push(i, 0, 0, 0); wts.push(1, 0, 0, 0); }
  };
  const inv = new THREE.Matrix4().copy(g.matrixWorld).invert();
  for (const b of bones) for (const c of b.children) if (c.isBone)
    add(b.getWorldPosition(new THREE.Vector3()).applyMatrix4(inv), c.getWorldPosition(new THREE.Vector3()).applyMatrix4(inv), ix.get(b));
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  geo.setAttribute("skinIndex", new THREE.Uint16BufferAttribute(idx, 4));
  geo.setAttribute("skinWeight", new THREE.Float32BufferAttribute(wts, 4));
  geo.computeVertexNormals();
  const mesh = new THREE.SkinnedMesh(geo, new THREE.MeshStandardMaterial({color: 0x888888}));
  mesh.name = "test_body"; g.add(mesh);
  mesh.bind(new THREE.Skeleton(bones), mesh.matrixWorld);
}

if (args.includes("--no-textures")) g.traverse(o => { if (o.material) for (const m of [].concat(o.material))
  for (const k of ["map", "normalMap", "specularMap", "bumpMap", "emissiveMap", "aoMap", "alphaMap"]) m[k] = null; });
const root = new THREE.Group(); root.name = "mixamo"; root.scale.setScalar(0.01); root.add(g);   // centimetres -> metres
const anims = args.includes("--no-anim") ? [] : g.animations.filter(a => a.tracks.length);
const glb = await new GLTFExporter().parseAsync(root, {binary: true, animations: anims, onlyVisible: false});
fs.writeFileSync(OUT, Buffer.from(glb));
const hips = bones.find(b => /Hips$/.test(b.name));
console.log(`${SRC.split("/").pop()} -> ${OUT.split("/").pop()}: ${bones.length} bones (${bones.filter(b => /Hand(Thumb|Index|Middle|Ring|Pinky)/.test(b.name)).length} finger), ` +
  `${anims.length} clip(s)${anims[0] ? ` ${anims[0].duration.toFixed(2)} s` : ""}, hips ${hips.getWorldPosition(new THREE.Vector3()).y.toFixed(3)} m up` +
  `${args.includes("--test-skin") ? ", test body bound" : ""}, ${(fs.statSync(OUT).size / 1024).toFixed(0)} KB`);
