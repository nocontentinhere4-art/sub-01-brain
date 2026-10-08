// node kimodo/mx_convert.mjs <out dir> <clip> ... : room clips made for v5 (web/room/mh_v5/<clip>.glb) carried onto the
// Mixamo-rigged character (web/room/char_mixamo.glb), for the page's slots that have no Mixamo capture yet (walking,
// standing, the bed, eating, the door, the window). The Mixamo clips themselves are not converted: they play on their
// own skeleton (kimodo/mx_fit.py bakes them for our chair).
// Each Mixamo bone moves in the world as the v5 joint it was fitted from (rig/autorig/fit.py NEW2OLD) moves from its
// bind: both characters are the same mesh (char_mixamo bound as modelled, the same size), so a part rigid on one joint
// lands where v5 puts it, frame by frame. Out: a clip on char_mixamo's own skeleton (its nodes, names and rest; the hips
// in the skeleton's centimetres), which char_mixamo.js's fixClip plays as it is (hip height ratio 1).
import fs from "node:fs"; import path from "node:path";
globalThis.self = globalThis; globalThis.window = globalThis;
const THREE = await import("three");
const { GLTFLoader } = await import("three/examples/jsm/loaders/GLTFLoader.js");
const { MeshoptDecoder } = await import("three/examples/jsm/libs/meshopt_decoder.module.js");
const { NodeIO, Document } = await import("@gltf-transform/core"); const { ALL_EXTENSIONS } = await import("@gltf-transform/extensions");
const MO = await import("meshoptimizer"); await MO.MeshoptDecoder.ready; await MO.MeshoptEncoder.ready;
const R = path.resolve(new URL("../..", import.meta.url).pathname), WEB = path.join(R, "web/room");
const V5 = await import(path.join(WEB, "char_v5.js")), MX = await import(path.join(WEB, "char_mixamo.js"));
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({"meshopt.decoder": MO.MeshoptDecoder, "meshopt.encoder": MO.MeshoptEncoder});
async function gltf(f) {                                      // (textures dropped: Node decodes no images)
  const d = await io.readBinary(new Uint8Array(fs.readFileSync(f))), r = d.getRoot();
  for (const t of r.listTextures()) t.dispose(); for (const e of r.listExtensionsUsed()) if (/texture/.test(e.extensionName)) e.dispose();
  const b = await io.writeBinary(d); return new Promise((ok, no) => new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).parse(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength), "", ok, no));
}
const [OUT, ...CL] = process.argv.slice(2); fs.mkdirSync(OUT, {recursive: true});
const FPS = 30;
// the Mixamo bone -> the v5 joint it was fitted from (fit.py NEW2OLD), by the page's names (char_v5.js TO_MH, char_mixamo.js NAMES)
const OLD = {Hips: "Hips", Spine02: "Spine01", Spine01: "Spine01", Spine: "Spine", neck: "neck", Head: "Head"};
for (const S of ["Left", "Right"]) { for (const b of ["Shoulder", "Arm", "ForeArm", "Hand", "UpLeg", "Leg", "Foot", "ToeBase"]) OLD[S + b] = S + b;
  for (let f = 1; f <= 5; f++) for (let k = 1; k <= 3; k++) OLD[`finger${f}-${k}.${S[0]}`] = `finger${f}-${k}.${S[0]}`; }
const v5g = await gltf(path.join(WEB, "char_v5.glb")), v5c = V5.prep(THREE, v5g);
const mxg = await gltf(path.join(WEB, "char_mixamo.glb")); MX.prep(THREE, mxg);
const skinOf = sc => { let m = null; sc.traverse(o => { if (o.isSkinnedMesh && !m) m = o; }); return m; };
const m5 = skinOf(v5g.scene), mm = skinOf(mxg.scene), B5 = {}, BM = {};
v5g.scene.traverse(o => { if (o.isBone) { B5[o.name] = o; B5[o.name.replace(/\.(?=[LR]$)/, "")] = o; } });
mm.skeleton.bones.forEach((b, i) => { BM[b.name] = i; });
const i5 = n => m5.skeleton.bones.indexOf(B5[n] || B5[n.replace(/\.(?=[LR]$)/, "")]);
// S: where a v5 vertex is drawn at its bind (its mesh's world matrix on its bind-space position) -> where char_mixamo
// has the same vertex (the map fit.py wrote into the file: K, the turn to face +z, the floor)
v5g.scene.updateMatrixWorld(true); mxg.scene.updateMatrixWorld(true);
const fsb = (await io.read(path.join(WEB, "char_mixamo.glb"))).getRoot().listScenes()[0].getExtras().autorig;
if (!fsb) throw new Error("char_mixamo.glb has no autorig.fromSourceBind (re-run rig/autorig.sh)");
const S = new THREE.Matrix4().fromArray(fsb.fromSourceBind).multiply(m5.matrixWorld.clone().invert()), Si = S.clone().invert();
const W5 = m5.matrixWorld.clone().multiply(m5.bindMatrixInverse), W5i = m5.bindMatrix.clone().multiply(m5.matrixWorld.clone().invert());
const MWi = mm.matrixWorld.clone().multiply(mm.bindMatrixInverse), MWiI = MWi.clone().invert();
const pairs = mm.skeleton.bones.map((b, i) => { let n = b.name, p = b; while (!(n in OLD) && p.parent && p.parent.isBone) { p = p.parent; n = p.name; }   // (an end bone: its parent's)
  const j = i5(OLD[n]); if (j < 0) throw new Error(`v5 joint for ${b.name} (${OLD[n]}) not found`); return j; });
// the v5 joint's move from its bind (world) -> the Mixamo bone's world: A5 S^-1 (bone bind world)
const bindW = mm.skeleton.boneInverses.map(m => MWi.clone().multiply(m.clone().invert()));
const top0 = new THREE.Matrix4().makeScale(0.01, 0.01, 0.01);                   // (the hips are written under the 0.01 node, at the origin)
// the written skeleton: char_mixamo.glb's own nodes (names, hierarchy, rest)
const src = await io.read(path.join(WEB, "char_mixamo.glb")), srcRoot = src.getRoot();
const top = srcRoot.listNodes().find(n => n.getName() === "mixamo");
for (const clip of CL) {
  const g = await gltf(path.join(WEB, "mh_v5", clip + ".glb")), c = V5.fixClip(THREE, g.animations[0], v5c);
  const mx = new THREE.AnimationMixer(v5g.scene), a = mx.clipAction(c); a.play();
  const F = Math.round(c.duration * FPS) + 1, rot = mm.skeleton.bones.map(() => new Float32Array(4 * F)), pos = mm.skeleton.bones.map(() => new Float32Array(3 * F));
  const A = new THREE.Matrix4(), T = new THREE.Matrix4(), q = new THREE.Quaternion(), pq = new THREE.Quaternion(), p = new THREE.Vector3(), s = new THREE.Vector3();
  const world = mm.skeleton.bones.map(() => new THREE.Matrix4());
  for (let f = 0; f < F; f++) {
    mx.setTime(Math.min(f / FPS, c.duration)); v5g.scene.updateMatrixWorld(true);
    mm.skeleton.bones.forEach((b, i) => { const j = pairs[i], bj = m5.skeleton.bones[j];
      A.multiplyMatrices(W5, bj.matrixWorld).multiply(m5.skeleton.boneInverses[j]).multiply(W5i);   // v5 bind world -> posed world
      world[i].copy(A).premultiply(new THREE.Matrix4()).multiply(Si).multiply(bindW[i]); });
    // each bone's local transform from the targets: its rotation, and its place (the two skeletons' joints are not all in
    // the same places: v5 bends at a Waist the Mixamo spine has no joint for, so rotations alone leave the hands 5 cm off)
    mm.skeleton.bones.forEach((b, i) => {
      const par = b.parent && b.parent.isBone ? world[mm.skeleton.bones.indexOf(b.parent)] : top0;
      T.copy(par).invert().multiply(world[i]).decompose(p, q, s);
      q.normalize(); if (f && q.dot(new THREE.Quaternion().fromArray(rot[i], 4 * (f - 1))) < 0) { q.x = -q.x; q.y = -q.y; q.z = -q.z; q.w = -q.w; }
      q.toArray(rot[i], 4 * f); p.toArray(pos[i], 3 * f); });
  }
  a.stop();
  // the GLB: char_mixamo's skeleton nodes and one animation (rotations for every bone, the hips' translation)
  const doc = new Document(), buf = doc.createBuffer(), scene = doc.createScene(), map = new Map();
  const copy = (n, parent) => { const d = doc.createNode(n.getName()).setTranslation(n.getTranslation()).setRotation(n.getRotation()).setScale(n.getScale());
    map.set(n.getName(), d); parent ? parent.addChild(d) : scene.addChild(d); for (const ch of n.listChildren()) copy(ch, d); };
  copy(top, null);
  const times = doc.createAccessor().setType("SCALAR").setArray(new Float32Array(F).map((_, f) => f / FPS)).setBuffer(buf), an = doc.createAnimation(clip);
  const add = (node, pathName, arr, type) => { const o = doc.createAccessor().setType(type).setArray(arr).setBuffer(buf);
    const sm = doc.createAnimationSampler().setInput(times).setOutput(o).setInterpolation("LINEAR"); an.addSampler(sm).addChannel(doc.createAnimationChannel().setTargetNode(node).setTargetPath(pathName).setSampler(sm)); };
  const srcName = {}; srcRoot.listNodes().forEach(n => { srcName[MX.pageName(n.getName())] = n.getName(); });
  let moved = 0;
  mm.skeleton.bones.forEach((b, i) => { const nd = map.get(srcName[b.name]); if (!nd) throw new Error("no node " + b.name); add(nd, "rotation", rot[i], "VEC4");
    // a place track where the bone leaves its rest offset by more than 2 mm (always the hips)
    const r = nd.getTranslation(); let d = 0; for (let f = 0; f < F; f++) d = Math.max(d, Math.hypot(pos[i][3 * f] - r[0], pos[i][3 * f + 1] - r[1], pos[i][3 * f + 2] - r[2]));
    if (i === BM.Hips || d * (b.name === "Hips" ? 0.01 : 0.01) > 0.002) { add(nd, "translation", pos[i], "VEC3"); moved++; } });
  await io.write(path.join(OUT, clip + ".glb"), doc);
  console.log(`${clip}: ${F} frames, ${moved} bones with place tracks, ${(fs.statSync(path.join(OUT, clip + ".glb")).size / 1024).toFixed(0)} KB`);
}
