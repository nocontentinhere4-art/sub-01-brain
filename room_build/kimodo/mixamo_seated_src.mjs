// node mixamo_seated_src.mjs <dir of Mixamo FBX> : the seated captures on their OWN skeleton (no retarget): hips height, head
// ahead of the hips, each hand over / from its thigh and to the side, and the worst joint jump into and out of the desk set.
import fs from "node:fs"; globalThis.self = globalThis; globalThis.window = globalThis;
const THREE = await import("three"); const { FBXLoader } = await import("three/examples/jsm/loaders/FBXLoader.js");
const load = f => { const b = fs.readFileSync(f), g = new FBXLoader().parse(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength), ""), rg = new THREE.Group(); rg.scale.setScalar(0.01); rg.add(g);
  const clip = g.animations.find(a => a.tracks.length), m = new THREE.AnimationMixer(g); m.clipAction(clip).play(); return {g, rg, m, clip}; };
const pose = (L, t) => { L.m.setTime(Math.min(t, L.clip.duration - 1e-3)); L.rg.updateMatrixWorld(true); const P = {}, Q = {}; L.g.traverse(o => { if (o.isBone) { const n = o.name.replace(/^mixamorig\d*:?/, ""); P[n] = o.getWorldPosition(new THREE.Vector3()); Q[n] = o.quaternion.clone(); } }); return {P, Q}; };
const S = process.argv[2], CL = ["Seated_Idle", "Sitting", "Sitting_1", "Sitting_Rubbing_Arm", "Sitting_Talking", "Stand_To_Sit", "Sit_To_Type", "Type_To_Sit"], L = {};
for (const c of CL) L[c] = load(`${S}/${c}.fbx`);
const desc = (c, t) => { const {P} = pose(L[c], t), h = P.Hips, f = v => +v.toFixed(2);
  const hand = s => { const p = P[s + "Hand"], th = P[s + "UpLeg"].clone().lerp(P[s + "Leg"], 0.6); return {overThigh_cm: f((p.y - th.y) * 100), fromThigh_cm: f(p.distanceTo(th) * 100), side_cm: f(Math.abs(p.x - h.x) * 100)}; };
  return {hipsY: f(h.y), headFwd_cm: f((P.Head.z - h.z) * 100), L: hand("Left"), R: hand("Right")}; };
const ang = (a, ta, b, tb) => { const A = pose(L[a], ta).Q, B = pose(L[b], tb).Q; let w = 0, wn = ""; for (const n in A) if (B[n] && !/Hand(Thumb|Index|Middle|Ring|Pinky)/.test(n)) { const d = 2 * Math.acos(Math.min(1, Math.abs(A[n].dot(B[n])))) * 180 / Math.PI; if (d > w) { w = d; wn = n; } } return [+w.toFixed(1), wn]; };
for (const c of CL.slice(0, 5)) { const D = L[c].clip.duration;
  console.log(c, D.toFixed(1) + " s", JSON.stringify(desc(c, Math.min(D, 0.5))), "wrap", JSON.stringify(ang(c, D, c, 0)),
    "| StandToSit.end->", JSON.stringify(ang("Stand_To_Sit", L.Stand_To_Sit.clip.duration, c, 0)), "->SitToType", JSON.stringify(ang(c, 0, "Sit_To_Type", 0)), "TypeToSit.end->", JSON.stringify(ang("Type_To_Sit", L.Type_To_Sit.clip.duration, c, 0))); }
console.log("Stand_To_Sit end", JSON.stringify(desc("Stand_To_Sit", L.Stand_To_Sit.clip.duration)));
