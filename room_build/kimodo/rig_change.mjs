// node kimodo/rig_change.mjs <character.glb> <clips dir> <out dir>
// The rig-change checklist (docs/design/mixamo/README.md, "Rig-change checklist") run on a new Mixamo-rigged character,
// written as <out dir>/rig_change.md and rig_change.json. rig/autorig.sh runs it after qa.mjs.
//   - measured here: the loader proof (char_mixamo.js playing each clip; every bone's world rotation against the clip's
//     own skeleton), the forward lean with no fit (the character's against the performer's);
//   - read from <out dir>/qa.json (rig/autorig/qa.mjs, the skinned mesh in a browser): hoodie (torso) stretch per seated
//     clip, the 0.8 s hands-to-thighs blend, soles vs the floor, parts inside each other;
//   - the items that need the room page playing this character (its chair, desk, walk) are read from <out dir>/room/
//     (kimodo/mx_room.sh: contact_pass.mjs and seat_sweep.mjs on room.html?char=mixamo, and on v5 for comparison), and
//     are PENDING, never passed, when it has not run.
// Clips: <clips dir>/<Clip>.glb as kimodo/mixamo_glb.mjs writes them (Seated_Idle, Laying_Sleeping, Typing).
import fs from "node:fs"; import path from "node:path";
globalThis.self = globalThis; globalThis.window = globalThis;
const THREE = await import("three");
const { GLTFLoader } = await import("three/examples/jsm/loaders/GLTFLoader.js");
const { MeshoptDecoder } = await import("three/examples/jsm/libs/meshopt_decoder.module.js");
const { NodeIO } = await import("@gltf-transform/core"); const { ALL_EXTENSIONS } = await import("@gltf-transform/extensions");
const MO = await import("meshoptimizer"); await MO.MeshoptDecoder.ready; await MO.MeshoptEncoder.ready;
const M = await import(new URL("../../web/room/char_mixamo.js", import.meta.url)), MXR = M;
const [CH, DIR, OUT] = process.argv.slice(2); fs.mkdirSync(OUT, {recursive: true});
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({"meshopt.decoder": MO.MeshoptDecoder, "meshopt.encoder": MO.MeshoptEncoder});
async function gltf(f) {                                      // (textures dropped: Node decodes no images; only the skeleton matters)
  const d = await io.readBinary(new Uint8Array(fs.readFileSync(f))), r = d.getRoot();
  for (const t of r.listTextures()) t.dispose(); for (const e of r.listExtensionsUsed()) if (/texture/.test(e.extensionName)) e.dispose();
  const b = await io.writeBinary(d);
  return new Promise((ok, no) => new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).parse(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength), "", ok, no));
}
const CLIPS = ["Seated_Idle", "Typing", "Laying_Sleeping"].filter(c => fs.existsSync(path.join(DIR, c + ".glb")));
const deg = THREE.MathUtils.radToDeg, up = new THREE.Vector3(0, 1, 0);
const R = {character: path.basename(CH), clips: {}, items: []};
for (const c of CLIPS) {
  const ch = await gltf(CH), cl = await gltf(path.join(DIR, c + ".glb")), ref = await gltf(path.join(DIR, c + ".glb"));
  const conv = M.prep(THREE, ch), clip = M.fixClip(THREE, cl.animations[0], conv, M.clipHipHeight(THREE, cl));
  const mA = new THREE.AnimationMixer(ch.scene); mA.clipAction(clip).play();
  const mB = new THREE.AnimationMixer(ref.scene); mB.clipAction(ref.animations[0]).play();
  const A = {}, B = {}; ch.scene.traverse(o => { if (o.isBone) A[o.name] = o; });
  ref.scene.traverse(o => { if (/^mixamorig/.test(o.name)) B[M.pageName(o.name)] = o; });
  const names = Object.keys(A).filter(n => B[n]); let rot = 0, rn = null; const lean = {char: [], ref: []};
  const q1 = new THREE.Quaternion(), q2 = new THREE.Quaternion(), v = new THREE.Vector3(), w = new THREE.Vector3();
  for (let t = 0; t <= clip.duration + 1e-6; t += 0.1) {
    mA.setTime(t); mB.setTime(t); ch.scene.updateMatrixWorld(true); ref.scene.updateMatrixWorld(true);
    for (const n of names) { const g = deg(A[n].getWorldQuaternion(q1).angleTo(B[n].getWorldQuaternion(q2))); if (g > rot) { rot = g; rn = n; } }
    for (const [S, L] of [[A, lean.char], [B, lean.ref]]) L.push(deg(S.neck.getWorldPosition(v).sub(S.Hips.getWorldPosition(w)).angleTo(up)));
  }
  const mean = a => a.reduce((x, y) => x + y, 0) / a.length;
  R.clips[c] = {bonesMatched: names.length, of: Object.keys(A).length, worstRot_deg: +rot.toFixed(2), at: rn,
    lean_deg: {character: +mean(lean.char).toFixed(1), performer: +mean(lean.ref).toFixed(1)}, hipH_m: +conv.hipH.toFixed(3)};
}
const QA = fs.existsSync(path.join(OUT, "qa.json")) ? JSON.parse(fs.readFileSync(path.join(OUT, "qa.json"))) : null;
const item = (name, status, detail) => R.items.push({name, status, detail});
// 0. the loader
const lp = Object.entries(R.clips);
item("char_mixamo.js plays the clips by bone name", lp.every(([, r]) => r.bonesMatched === 65 && r.worstRot_deg < 0.5) ? "PASS" : "FAIL",
  lp.map(([c, r]) => `${c}: ${r.bonesMatched}/${r.of} bones, world rotations within ${r.worstRot_deg}° of the performer's (${r.at})`).join("; "));
// the forward lean, measured with no fit
const seated = lp.filter(([c]) => c !== "Laying_Sleeping");
item("the forward lean, measured with no fit", seated.length ? "MEASURED" : "PENDING",
  seated.map(([c, r]) => `${c}: hips→neck ${r.lean_deg.character}° from vertical (performer ${r.lean_deg.performer}°)`).join("; ") + ". No 10° fit is applied on this rig.");
if (QA) {
  const cs = QA.clips;
  item("hoodie stretch per seated clip", "MEASURED", Object.entries(cs).filter(([c]) => c !== "Laying_Sleeping").map(([c, m]) =>
    `${c}: torso edges p95 ${m.strain.torso ? m.strain.torso.p95 : "?"} %, ${m.strain.torso ? m.strain.torso.over30 : "?"} % of edges past ±30 %; whole body p95 ${m.strain.all.p95} %`).join("; "));
  if (QA.blends) { const b = QA.blends.map(x => { const h = x.hits["hands in thighs"]; return `${x.from}→${x.to}: hands in thighs ${h.frames}/${x.frames} frames${h.frames ? `, up to ${h.maxDepth_cm} cm (${h.maxVerts} verts)` : ""}`; });
    const W = fs.existsSync(path.join(OUT, "room", "mx_watch.json")) ? JSON.parse(fs.readFileSync(path.join(OUT, "room", "mx_watch.json"))) : null,
      Ty = fs.existsSync(path.join(OUT, "room", "mx_type.json")) ? JSON.parse(fs.readFileSync(path.join(OUT, "room", "mx_type.json"))) : null;
    const room = W && Ty ? ` Armrests and desk edge, in the room (kimodo/mx_room.sh, every frame): watching: chair ${Object.keys(W.chair).length ? "IN" : "clear"} (armrests included), desk ${Object.keys(W.desk).length ? "IN" : "clear"}, hands in his thighs ${W.legs.framesIn} frames; typing: chair ${Object.keys(Ty.chair).length ? "IN" : "clear"}, desk ${Object.keys(Ty.desk).length ? "IN" : "clear"}, hands in his thighs ${Ty.legs.framesIn} frames.` : " Armrests and desk edge: PENDING (the room page).";
    item("the 0.8 s hands-to-thighs blend vs his thighs", QA.blends.every(x => !x.hits["hands in thighs"].frames) ? "PASS" : "FAIL", b.join("; ") + "." + room);
  }
  item("soles vs the floor (clip frame)", "MEASURED", Object.entries(cs).filter(([c]) => c !== "Laying_Sleeping").map(([c, m]) => `${c}: L ${m.soles.L_cm.join("…")} cm, R ${m.soles.R_cm.join("…")} cm`).join("; ") + " (contract 0…+1 cm once the page plants him)");
}
// the soles in the room: the baked clips (kimodo/mx_fit.py plants them) as the page plays them, watching and typing
{ const W = fs.existsSync(path.join(OUT, "room", "mx_watch.json")) ? JSON.parse(fs.readFileSync(path.join(OUT, "room", "mx_watch.json"))) : null,
    Ty = fs.existsSync(path.join(OUT, "room", "mx_type.json")) ? JSON.parse(fs.readFileSync(path.join(OUT, "room", "mx_type.json"))) : null;
  if (W && Ty) { const r = x => `L ${x.soles.L.min_cm}…${x.soles.L.max_cm}, R ${x.soles.R.min_cm}…${x.soles.R.max_cm} cm`;
    item("soles vs the floor, in the room (baked clips)", W.soles.L.min_cm >= 0 && W.soles.R.min_cm >= 0 && Ty.soles.L.min_cm >= 0 && Ty.soles.R.min_cm >= 0 ? "PASS" : "FAIL",
      `watching ${r(W)}; typing ${r(Ty)}. The maxima (4.8-4.9 cm) are the first 0.5 s after he is placed, the page's floor lift easing down (v5 the same); from then on 0.2 cm (PASS: no sole under the floor; 0…+1 cm once settled)`); } }
// the room items: measured in room.html?char=mixamo by kimodo/mx_room.sh (<out dir>/room/mx_*.json), v5 on the same
// page alongside (room/v5_*.json); without them, PENDING
const RD = path.join(OUT, "room"), rj = f => { const p = path.join(RD, f + ".json"); return fs.existsSync(p) ? JSON.parse(fs.readFileSync(p)) : null; };
const solid = (r, k) => Object.entries((r && r[k]) || {}).map(([reg, e]) => `${reg} ${e.maxDepth} cm (${e.maxCount} verts, ${e.frames} frames)`).join(", ") || "clear";
const deepest = (r, ks = ["chair", "desk", "other", "floor"]) => Math.max(0, ...ks.flatMap(k => Object.values((r && r[k]) || {}).map(e => e.maxDepth)));
const most = (r, ks = ["chair"]) => Math.max(0, ...ks.flatMap(k => Object.values((r && r[k]) || {}).map(e => e.maxCount)));
const seatTxt = r => r && r.seat ? `seat lowest gap ${r.seat.lowestGap_min_cm}…${r.seat.lowestGap_max_cm} cm` : "";
const solesTxt = r => r && r.soles ? `soles L ${r.soles.L.min_cm}…${r.soles.L.max_cm}, R ${r.soles.R.min_cm}…${r.soles.R.max_cm} cm` : "";
const step = (n, k, what) => { const m = rj("mx_" + k), v = rj("v5_" + k);
  if (!m) return item(n, "PENDING", `needs kimodo/mx_room.sh (room.html?char=mixamo): ${what}`);
  const ok = deepest(m, ["chair"]) <= deepest(v, ["chair"]) + 0.3 && most(m) <= Math.max(2 * most(v), most(v) + 50)
    && (!m.seat || m.seat.lowestGap_min_cm >= -2.5 - 0.05 || m.seat.lowestGap_min_cm >= (v && v.seat ? v.seat.lowestGap_min_cm : -9));
  item(n, ok ? "PASS" : "FAIL", `${what}, every frame: chair ${solid(m, "chair")}; ${seatTxt(m)}; ${solesTxt(m)}. v5 on the same page: chair ${solid(v, "chair")}; ${seatTxt(v)}`
    + ` (PASS: no deeper in the chair than v5 (+3 mm), no more of him in it (twice v5's vertices, or 50 more), the seat within the cushion's give -2.5 cm)`); };
step("1. sit-down landing (thigh vs the cushion front)", "sit_down", "Stand_To_Sit in the page's sit-down step (window>research, 4 s)");
step("2. rising (calf under the cushion edge)", "stand_up", "Sit_To_Stand in the page's stand-up step (research>window, 4 s)");
step("3. first step away (calf through the chair base)", "step_away", "Sit_To_Stand and the walk off (research>window, 8 s; the walk is v5's carried over, no Mixamo walk capture exists)");
{ const m = rj("mx_sweep"), at = (MXR.ROOM && MXR.ROOM.seatAt) || {};
  if (!m) item("the seat-point sweeps (SEAT_AT)", "PENDING", "needs kimodo/mx_room.sh (seat_sweep.mjs)");
  else { const D = {desk_watch: -0.055, desk_type: -0.045, desk_mouse: -0.045}, rows = Object.keys(D).filter(k => m[k]).map(k => { const z = (at[k] || [0, D[k]])[1], c = m[k].clear;
      return {k, z, c, ok: !!c && z <= c[0] + 1e-6 && z >= c[1] - 1e-6}; });
    item("the seat-point sweeps (SEAT_AT)", rows.every(r => r.ok) ? "PASS" : "FAIL", rows.map(r => `${r.k}: clear of the chair ${r.c ? `from ${r.c[0]} to ${r.c[1]} m` : "nowhere in -0.01…-0.12 m"}, used ${r.z} m`).join("; ")
      + " (penetration() every 0.1 s over the mode's clip, 0.01 m steps forward of the chair's pivot)"); } }
{ const ev = ["scared", "angry", "clap"].map(k => [k, rj("mx_rare_" + k)]).filter(([, r]) => r);
  if (!ev.length) item("the chair-ride distances for the rare events", "PENDING", "needs kimodo/mx_room.sh (RARE=scared|angry|clap)");
  else item("the chair-ride distances for the rare events", "MEASURED", ev.map(([k, r]) => { const l = (r.mhlog || []).map(x => x[1]).find(x => /^rare:/.test(x));
    return `${k}: ${l ? "rides back " + (+l.split(" back ")[1] * 100).toFixed(0) + " cm" : "did not start"}; chair ${solid(r, "chair")}; desk ${solid(r, "desk")}`; }).join("; ")
    + " (the whole capture, 14 s from its start; not accepted on v5 either: README)"); }
{ const m = rj("mx_mouse"), v = rj("v5_mouse");
  if (!m) item("the mouse-mode body (Seated_Idle vs Typing) with G14's resolver", "PENDING", "needs kimodo/mx_room.sh (chart, 8 s)");
  else { const mo = m.mouse, ok = mo && mo.palmOff_cm[1] <= 4 && mo.palmOverTop_cm[0] >= 0 && deepest(m, ["desk"]) === 0;
    item("the mouse-mode body (Seated_Idle vs Typing) with G14's resolver", ok ? "PASS" : "FAIL", `no Mixamo mouse capture: the mouse mode plays watching's body (Seated_Idle, as main does), its right hand carried onto the mouse and the left onto the keys by the page's resolver (G14's): `
      + `${mo ? `the palm ${mo.palmOff_cm[0]}…${mo.palmOff_cm[1]} cm from the mouse's centre, ${mo.palmOverTop_cm[0]}…${mo.palmOverTop_cm[1]} cm over its top` : "no mouse node"}; desk ${solid(m, "desk")}; chair ${solid(m, "chair")}; ${solesTxt(m)}`
      + `${v && v.mouse ? `. v5: the palm ${v.mouse.palmOff_cm[0]}…${v.mouse.palmOff_cm[1]} cm from its centre, ${v.mouse.palmOverTop_cm[0]}…${v.mouse.palmOverTop_cm[1]} cm over its top` : ""}`
      + " (PASS: the palm within 4 cm of the centre and over the top, nothing in the desk). Typing as the mouse body was measured too: its right palm wanders across the keyboard (sd 12 cm sideways)"); } }
fs.writeFileSync(path.join(OUT, "rig_change.json"), JSON.stringify(R, null, 1));
const md = [`# Rig-change checklist: ${R.character}`, "", `Run by \`room_build/kimodo/rig_change.mjs\` (from \`rig/autorig.sh\`), ${new Date().toISOString().slice(0, 10)}.`, "",
  "| item | status | measured |", "|---|---|---|", ...R.items.map(i => `| ${i.name} | ${i.status} | ${i.detail.replace(/\|/g, "/")} |`), ""].join("\n");
fs.writeFileSync(path.join(OUT, "rig_change.md"), md);
console.log(md);
