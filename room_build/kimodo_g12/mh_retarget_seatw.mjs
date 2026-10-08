// node mh_retarget.mjs <mh_clip.glb> <v5.glb> <out.glb> [opts.json]
// MakeHuman room clips (preview/room-mh web/room/mh/*.glb: G2's rig, world-aligned rest pose facing +Z, fingers) onto the
// v5 Tripo rig (41 bones, faces +X; plus finger bones when the GLB has them, MakeHuman names finger1-1.L ... finger5-3.R).
// 1) every mapped bone takes its MakeHuman bone's world rotation, the source turned to face +X (C = 90° about Y), with the
//    two rest poses aligned per bone (the minimal rotation from the source rest direction to the target's);
// 2) the Hip follows the midpoint of the MakeHuman hip joints: horizontally unscaled (props_g2.json and the choreography
//    are in the clip's metres), vertically by the leg-length ratio, ankle heights matched;
// 3) zero-phase smoothing (Gaussian, sigma 1 frame limbs / 1.7 spine-neck-head), then two-bone IK: the wrists onto the
//    MakeHuman wrists (so hands stay on the keyboard, mouse, book, phone, spoon, cup), the ankles onto the MakeHuman
//    ankles (feet planted where his were), soles above the floor; a last smoothing pass with the IK re-solved.
// Output: the bare v5 rig with one animation (all bones + Hip translation, 30 fps), in the rig's frame: the rig faces +X,
// so a v5 root turned by (MH heading - 90°) about Y plays it where the MakeHuman clip played.
import fs from "node:fs";
import { NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS } from "@gltf-transform/extensions";
import { MeshoptDecoder, MeshoptEncoder } from "meshoptimizer";
import { resample, prune } from "@gltf-transform/functions";
import * as THREE from "three";
const [,, SRC, CHAR, OUT, OPTF] = process.argv;
const O = OPTF ? JSON.parse(fs.readFileSync(OPTF)) : {};
await MeshoptDecoder.ready; await MeshoptEncoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({"meshopt.decoder": MeshoptDecoder, "meshopt.encoder": MeshoptEncoder});
const V = a => new THREE.Vector3(a[0], a[1], a[2]);
const FPS = O.fps || 30;

// ---------- the MakeHuman clip, sampled at FPS, world transforms per frame
const sdoc = await io.read(SRC), sroot = sdoc.getRoot();
const sNodes = new Map(sroot.listNodes().map(n => [n.getName(), n]));
const sPar = new Map(); for (const n of sroot.listNodes()) for (const c of n.listChildren()) sPar.set(c, n);
const sDepth = n => { let k = 0; while ((n = sPar.get(n))) k++; return k; };
const sTD = sroot.listNodes().slice().sort((a, b) => sDepth(a) - sDepth(b));
const anim = sroot.listAnimations()[0]; const chans = new Map();
let dur = 0; for (const c of anim.listChannels()) { const s = c.getSampler(), inp = s.getInput().getArray(), out = s.getOutput().getArray();
  chans.set(c.getTargetNode().getName() + ":" + c.getTargetPath(), {inp, out, n: c.getTargetPath() === "rotation" ? 4 : 3}); dur = Math.max(dur, inp[inp.length - 1]); }
function sample(ch, t){ const {inp, out, n} = ch; let i = 0; while (i + 1 < inp.length && inp[i + 1] <= t) i++;
  const j = Math.min(i + 1, inp.length - 1), u = inp[j] > inp[i] ? Math.min(1, Math.max(0, (t - inp[i]) / (inp[j] - inp[i]))) : 0;
  if (n === 4) { const a = new THREE.Quaternion().fromArray(out, i * 4), b = new THREE.Quaternion().fromArray(out, j * 4); return a.slerp(b, u); }
  return new THREE.Vector3().fromArray(out, i * 3).lerp(new THREE.Vector3().fromArray(out, j * 3), u); }
const T = Math.round(dur * FPS) + 1;
const C = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 2), Ci = C.clone().invert();
function sFK(t){ const W = new Map(), P = new Map();
  for (const n of sTD) { const nm = n.getName(), p = sPar.get(n);
    const q = chans.has(nm + ":rotation") ? sample(chans.get(nm + ":rotation"), t) : new THREE.Quaternion(...n.getRotation());
    const tr = chans.has(nm + ":translation") ? sample(chans.get(nm + ":translation"), t) : V(n.getTranslation());
    if (!p) { W.set(nm, q); P.set(nm, tr); continue; }
    const pw = W.get(p.getName()); W.set(nm, pw.clone().multiply(q)); P.set(nm, tr.applyQuaternion(pw).add(P.get(p.getName()))); }
  return {W, P}; }
const sRest = sFK(-1); for (const n of sTD) { /* rest = the nodes' own transforms */ }
const sRestP = new Map(); { const W = new Map(); for (const n of sTD) { const p = sPar.get(n), q = new THREE.Quaternion(...n.getRotation()), tr = V(n.getTranslation());
  if (!p) { W.set(n.getName(), q); sRestP.set(n.getName(), tr); continue; } const pw = W.get(p.getName()); W.set(n.getName(), pw.clone().multiply(q)); sRestP.set(n.getName(), tr.applyQuaternion(pw).add(sRestP.get(p.getName()))); } }
const srcP = nm => sRestP.get(nm).clone().applyQuaternion(C);

// ---------- the v5 rig
const doc = await io.read(CHAR), root = doc.getRoot();
const nodes = new Map(root.listNodes().map(n => [n.getName(), n]));
const parentOf = new Map(); for (const n of root.listNodes()) for (const c of n.listChildren()) parentOf.set(c, n);
const depth = n => { let k = 0; while ((n = parentOf.get(n))) k++; return k; };
const skinJoints = root.listSkins()[0].listJoints();
const bonesTD = root.listNodes().filter(n => skinJoints.includes(n) || n.getName() === "Armature").sort((a, b) => depth(a) - depth(b));
const restL = new Map(bonesTD.map(n => [n, new THREE.Quaternion(...n.getRotation())])), restT = new Map(bonesTD.map(n => [n, V(n.getTranslation())])), restS = new Map(bonesTD.map(n => [n, n.getScale()[0]]));
function fk(localQ, hipT){ const W = new Map(), P = new Map(), S = new Map();
  for (const n of bonesTD) { const p = parentOf.get(n), q = localQ.get(n) || restL.get(n), t = (n.getName() === "Hip" && hipT) ? hipT : restT.get(n);
    if (!p || !W.has(p)) { W.set(n, q.clone()); P.set(n, t.clone()); S.set(n, restS.get(n)); continue; }
    W.set(n, W.get(p).clone().multiply(q)); P.set(n, t.clone().multiplyScalar(S.get(p)).applyQuaternion(W.get(p)).add(P.get(p))); S.set(n, S.get(p) * restS.get(n)); }
  return {W, P, S}; }
const rest = fk(new Map()); const B = nm => nodes.get(nm); const restP = nm => rest.P.get(B(nm)).clone();
const HAS_FINGERS = !!B("finger2-1.L");

// target <- [source, source child for the direction, target child]
const MAP = {Hip: ["Hips", "spine04", "Spine01"], Waist: ["spine04", "spine02", "Spine01"], Spine01: ["spine02", "Spine", "Spine02"],
  Spine02: ["Spine", "neck", "NeckTwist01"], NeckTwist01: ["neck", "Head", "NeckTwist02"], NeckTwist02: ["neck", "Head", "Head"], Head: ["Head", "head_end", null], Pelvis: ["Hips", null, null]};
for (const [s, S, x] of [["L", "Left", "L"], ["R", "Right", "R"]]) {
  Object.assign(MAP, {[`${s}_Clavicle`]: [`${S}Shoulder`, `${S}Arm`, `${s}_Upperarm`], [`${s}_Upperarm`]: [`${S}Arm`, `${S}ForeArm`, `${s}_Forearm`],
    [`${s}_Forearm`]: [`${S}ForeArm`, `${S}Hand`, `${s}_Hand`], [`${s}_Hand`]: [`${S}Hand`, `finger3-1.${x}`, HAS_FINGERS ? `finger3-1.${x}` : null],
    [`${s}_Thigh`]: [`${S}UpLeg`, `${S}Leg`, `${s}_Calf`], [`${s}_Calf`]: [`${S}Leg`, `${S}Foot`, `${s}_Foot`],
    [`${s}_Foot`]: [`${S}Foot`, `${S}ToeBase`, `${s}_ToeBase`], [`${s}_ToeBase`]: [`${S}ToeBase`, `toe1-2.${x}`, null]});
  if (HAS_FINGERS) { for (let f = 1; f <= 5; f++) for (let j = 1; j <= 3; j++) { const nm = `finger${f}-${j}.${x}`; if (B(nm)) MAP[nm] = [nm, null, null]; }
    for (let m = 1; m <= 4; m++) { const nm = `metacarpal${m}.${x}`; if (B(nm)) MAP[nm] = [nm, null, null]; } }
}
for (const k of Object.keys(MAP)) if (!B(k) || !sNodes.has(MAP[k][0])) delete MAP[k];
const order = Object.keys(MAP).sort((a, b) => depth(B(a)) - depth(B(b)));
const ALIGN = {};
for (const b of order) { const [src, sc, tc] = MAP[b];
  let ds = sc && sNodes.has(sc) ? srcP(sc).sub(srcP(src)).normalize() : null, dt = tc ? restP(tc).sub(restP(b)).normalize() : null;
  if (b === "Head") dt = new THREE.Vector3(0, 1, 0);
  // the hand: a full basis (wrist -> middle-finger base, index base -> little-finger base), so the palm's facing and its
  // fingers' curl axis carry over, not only the hand's pointing direction (a lone direction leaves its twist free)
  const hs = (b.match(/^([LR])_Hand$/) || [])[1];
  if (hs && HAS_FINGERS) { const bas = (p, h) => { const x = p(`finger3-1.${hs}`).sub(p(h)).normalize(), y = p(`finger5-1.${hs}`).sub(p(`finger2-1.${hs}`));
      y.sub(x.clone().multiplyScalar(y.dot(x))).normalize(); return new THREE.Matrix4().makeBasis(x, y, x.clone().cross(y)); };
    const Ms = bas(srcP, src), Mt = bas(restP, b); ALIGN[b] = new THREE.Quaternion().setFromRotationMatrix(Mt.multiply(Ms.transpose())); continue; }
  // fingers and metacarpals ride the hand: its alignment, so each finger keeps its pose relative to the palm
  if (/^(finger|metacarpal)/.test(b)) { ALIGN[b] = ALIGN[`${b.slice(-1)}_Hand`].clone(); continue; }
  if (ds && dt && ds.lengthSq() > 0.5 && dt.lengthSq() > 0.5) ALIGN[b] = new THREE.Quaternion().setFromUnitVectors(ds, dt);
  else { let a = null; for (let n = parentOf.get(B(b)); n && !a; n = parentOf.get(n)) a = ALIGN[n.getName()]; ALIGN[b] = a ? a.clone() : new THREE.Quaternion(); } }

// scale and ankle offset
const srcLeg = srcP("LeftUpLeg").distanceTo(srcP("LeftLeg")) + srcP("LeftLeg").distanceTo(srcP("LeftFoot"));
const tgtLeg = restP("L_Thigh").distanceTo(restP("L_Calf")) + restP("L_Calf").distanceTo(restP("L_Foot"));
const k = tgtLeg / srcLeg, srcAnkle = sRestP.get("LeftFoot").y, tgtAnkle = (restP("L_Foot").y + restP("R_Foot").y) / 2;

// ---------- per frame
const frames = [];
const SW = [];   // seatW (G12): per-frame weight of the seated options, 1 seated -> 0 standing, from the source hips' height
for (let f = 0; f < T; f++) { const t = Math.min(f / FPS, dur), s = sFK(t), W = {};
  const sw = !O.seatW ? 1 : (() => { const y = s.P.get("Hips").y, x = Math.min(1, Math.max(0, (O.seatW.up - y) / (O.seatW.up - O.seatW.down))); return x * x * (3 - 2 * x); })();
  SW.push(sw);
  for (const b of order) W[b] = C.clone().multiply(s.W.get(MAP[b][0])).multiply(Ci).multiply(ALIGN[b].clone().invert()).multiply(rest.W.get(B(b)));
  if (O.pitch) { const SPN = ["Waist", "Spine01", "Spine02"].map(B);   // the torso tipped forward off the backrest, spread over the three spine joints
    for (const b of order) { let n = 0; for (let x = B(b); x; x = parentOf.get(x)) if (SPN.includes(x)) n++;
      if (n) W[b] = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), -O.pitch * sw * Math.PI / 180 * n / 3).multiply(W[b]); } }
  const hm = s.P.get("LeftUpLeg").clone().add(s.P.get("RightUpLeg")).multiplyScalar(0.5).applyQuaternion(C);
  const lift = (O.seatLift || 0) * sw;   // (m) the hips, hands and anything held go up by this onto a taller seat; the feet stay on the floor
  // forward (m): his hips further forward on the seat (off the backrest), with his hands (unless handForward false: they
  // stay on the keyboard / mouse / plate); baked into the clip, so the page's chair placement needs no change
  const fwd = (O.forward || 0) * sw;
  // shift [forward, left] (m): the body re-centred on the page's seat (hips + feet); handShift: the hands (and anything held
  // or world props), default = shift (type / mouse: only the forward part, the keys and mouse stay put)
  const SH = (O.shift || [0, 0]).map(v => v * sw), HS = (O.handShift || O.shift || [0, 0]).map(v => v * sw);
  const hip = new THREE.Vector3(hm.x + fwd + SH[0], (hm.y - srcAnkle) * k + tgtAnkle + lift, hm.z - SH[1]);
  const eff = {}; for (const [n, sn] of [["L_Hand", "LeftHand"], ["R_Hand", "RightHand"], ["L_Foot", "LeftFoot"], ["R_Foot", "RightFoot"]]) {
    const p = s.P.get(sn).clone().applyQuaternion(C); if (n.endsWith("Foot")) { p.y = p.y - srcAnkle + tgtAnkle; p.x += fwd + SH[0]; p.z -= SH[1]; } else { p.y += O.handLift != null ? O.handLift * sw : lift; if (O.handForward !== false) p.x += fwd; p.x += HS[0]; p.z -= HS[1]; } eff[n] = p; }
  frames.push({W, hip, eff}); }
function toLocal(Wmap, hipWorld){ const L = new Map(), Wc = new Map();
  for (const n of bonesTD) { const p = parentOf.get(n), name = n.getName(), pw = p ? Wc.get(p) : new THREE.Quaternion();
    const w = Wmap[name] ? Wmap[name] : pw.clone().multiply(restL.get(n)); Wc.set(n, w); if (Wmap[name]) L.set(n, pw.clone().invert().multiply(w)); }
  const pr = parentOf.get(B("Hip")), ht = hipWorld.clone().sub(rest.P.get(pr)).applyQuaternion(rest.W.get(pr).clone().invert()).multiplyScalar(1 / rest.S.get(pr));
  return {L, ht}; }
let seq = frames.map(f => toLocal(f.W, f.hip));

function twoBone(L, ht, a, b, c, goal, w = 1){
  const st = fk(L, ht), A = st.P.get(B(a)), Bp = st.P.get(B(b)), Cp = st.P.get(B(c));
  const la = A.distanceTo(Bp), lb = Bp.distanceTo(Cp); let d = Math.min(A.distanceTo(goal), (la + lb) * 0.999); const cur = A.distanceTo(Cp);
  const ang = x => Math.acos(THREE.MathUtils.clamp((la * la + lb * lb - x * x) / (2 * la * lb), -1, 1));
  const axis = Bp.clone().sub(A).cross(Cp.clone().sub(Bp)); if (axis.lengthSq() < 1e-10) axis.set(0, 0, 1).applyQuaternion(st.W.get(B(a))); axis.normalize();
  const qb = new THREE.Quaternion().setFromAxisAngle(axis, ang(cur) - ang(d)), Wb = qb.clone().multiply(st.W.get(B(b)));
  const Cn = Cp.clone().sub(Bp).applyQuaternion(qb).add(Bp);
  const qa = new THREE.Quaternion().setFromUnitVectors(Cn.clone().sub(A).normalize(), goal.clone().sub(A).normalize());
  const Wa = qa.clone().multiply(st.W.get(B(a))), Wb2 = qa.clone().multiply(Wb), Wc = st.W.get(B(c)).clone();
  const chainW = (from, Wtop, to) => { let w = Wtop; const path = []; for (let x = parentOf.get(B(to)); x !== B(from); x = parentOf.get(x)) path.unshift(x); for (const x of path) w = w.clone().multiply(L.get(x) || restL.get(x)); return w; };
  const La = st.W.get(parentOf.get(B(a))).clone().invert().multiply(Wa), Lb = chainW(a, Wa, b).invert().multiply(Wb2), Lc = chainW(b, Wb2, c).invert().multiply(Wc);
  for (const [n, q] of [[a, La], [b, Lb], [c, Lc]]) { const c0 = L.get(B(n)) || restL.get(B(n)); L.set(B(n), c0.clone().slerp(q, w)); } }
function smoothSeq(sigL, sigS){ const SP = new Set(["Hip", "Waist", "Spine01", "Spine02", "NeckTwist01", "NeckTwist02", "Head", "Pelvis"]);
  const kern = sg => { const r = Math.ceil(sg * 3), w = []; for (let j = -r; j <= r; j++) w.push(Math.exp(-j * j / (2 * sg * sg))); return {r, w}; };
  const KL = kern(sigL), KS = kern(sigS), out = seq.map(f => ({L: new Map(f.L), ht: f.ht.clone()}));
  for (const n of bonesTD) { if (!seq[0].L.has(n)) continue; const K = SP.has(n.getName()) ? KS : KL;
    for (let f = 0; f < T; f++) { const c = seq[f].L.get(n), acc = new THREE.Vector4(0, 0, 0, 0);
      for (let j = -K.r; j <= K.r; j++) { const q = seq[Math.min(T - 1, Math.max(0, f + j))].L.get(n), w = K.w[j + K.r], sg = (q.x * c.x + q.y * c.y + q.z * c.z + q.w * c.w) < 0 ? -1 : 1;
        acc.x += sg * w * q.x; acc.y += sg * w * q.y; acc.z += sg * w * q.z; acc.w += sg * w * q.w; }
      out[f].L.set(n, new THREE.Quaternion(acc.x, acc.y, acc.z, acc.w).normalize()); } }
  for (let f = 0; f < T; f++) { const acc = new THREE.Vector3(); let ws = 0; for (let j = -KS.r; j <= KS.r; j++) { const w = KS.w[j + KS.r]; acc.add(seq[Math.min(T - 1, Math.max(0, f + j))].ht.clone().multiplyScalar(w)); ws += w; } out[f].ht = acc.multiplyScalar(1 / ws); }
  seq = out; }
// the effector targets smoothed too (so the pins don't chatter)
for (const n of ["L_Hand", "R_Hand", "L_Foot", "R_Foot"]) { const raw = frames.map(f => f.eff[n].clone());
  frames.forEach((f, i) => { const a = new THREE.Vector3(); let ws = 0; for (let j = -3; j <= 3; j++) { const w = Math.exp(-j * j / 2); a.add(raw[Math.min(T - 1, Math.max(0, i + j))].clone().multiplyScalar(w)); ws += w; } f.eff[n] = a.multiplyScalar(1 / ws); }); }
function pins(){ const FLOOR = 0;
  for (let f = 0; f < T; f++) {
    for (const s of ["L", "R"]) { if (O.hands !== false) twoBone(seq[f].L, seq[f].ht, `${s}_Upperarm`, `${s}_Forearm`, `${s}_Hand`, frames[f].eff[`${s}_Hand`], O.handW ?? 1);
      if (O.feet !== false) { const g = frames[f].eff[`${s}_Foot`].clone(); g.y = Math.max(g.y, FLOOR + tgtAnkle * 0.95); const g0y = g.y; g.y += (O.heelLift || 0) * SW[f];
        twoBone(seq[f].L, seq[f].ht, `${s}_Thigh`, `${s}_Calf`, `${s}_Foot`, g, O.footW ?? 1);
        if (O.heelLift && SW[f] > 0.01) heelUp(seq[f].L, seq[f].ht, s, g0y); } } } }
// heel lifted off the floor, the ball of the foot stays down: the foot pitched about its ankle until the toe joint is back at
// the height a flat foot would have it (rest offset under the unlifted ankle); the toes keep their world rotation (bent flat)
const TOE_REL = restP("L_ToeBase").y - restP("L_Foot").y;
function heelUp(L, ht, s, g0y){ const st = fk(L, ht), F = B(`${s}_Foot`), Tb = B(`${s}_ToeBase`), pa = st.P.get(F), pt = st.P.get(Tb), len = pa.distanceTo(pt);
  const d0 = Math.asin(THREE.MathUtils.clamp((pt.y - pa.y) / len, -1, 1)), d1 = Math.asin(THREE.MathUtils.clamp((g0y + TOE_REL - pa.y) / len, -1, 1));
  const dirH = new THREE.Vector3(pt.x - pa.x, 0, pt.z - pa.z).normalize(), axis = dirH.clone().cross(new THREE.Vector3(0, -1, 0)).normalize();
  const Qd = new THREE.Quaternion().setFromAxisAngle(axis, d0 - d1), Wf = Qd.clone().multiply(st.W.get(F)), Wt = st.W.get(Tb);
  L.set(F, st.W.get(parentOf.get(F)).clone().invert().multiply(Wf)); L.set(Tb, Wf.clone().invert().multiply(Wt)); }
const jit = () => { const o = {}; const P = seq.map(f => fk(f.L, f.ht).P);
  for (const n of ["L_Hand", "R_Hand", "Head", "Hip"]) { const x = P.map(m => m.get(B(n)).clone()), r = x.map((_, i) => { const a = new THREE.Vector3(); let ws = 0; for (let j = -12; j <= 12; j++) { const w = Math.exp(-j * j / 32); a.add(x[Math.min(T - 1, Math.max(0, i + j))].clone().multiplyScalar(w)); ws += w; } return x[i].clone().sub(a.multiplyScalar(1 / ws)); });
    let s2 = 0; for (let i = 1; i < T - 1; i++) s2 += r[i - 1].clone().add(r[i + 1]).sub(r[i].clone().multiplyScalar(2)).multiplyScalar(FPS * FPS).lengthSq(); o[n] = +Math.sqrt(s2 / Math.max(1, T - 2)).toFixed(3); } return o; };
const jitterBefore = jit();
smoothSeq(O.sigma ?? 1.0, O.sigmaSpine ?? 1.7); pins();
smoothSeq(O.post ?? 1.0, (O.post ?? 1.0) * 1.5); pins();
if (O.book) bookGrip(O.book);
const jitterAfter = jit();
// effector error after the pins (m)
let errH = 0, errF = 0; seq.forEach((f, i) => { const P = fk(f.L, f.ht).P; for (const s of ["L", "R"]) { errH = Math.max(errH, P.get(B(`${s}_Hand`)).distanceTo(frames[i].eff[`${s}_Hand`])); errF = Math.max(errF, P.get(B(`${s}_Foot`)).distanceTo(frames[i].eff[`${s}_Foot`])); } });

// ---------- the book held as people hold one (O.book = {props, clip, tilt, out, gy}): each hand behind its half's cover near
// the outer edge, palm on the cover, fingers spread toward the top, the thumb over the outer edge on the page margin; the book
// tilted `tilt` degrees more toward his face (about its centre; the tilted props written to `out`). For each page turn the
// right hand leaves its cover, thumb and index pinch the turning page's lower outer corner, carry it over and let it down,
// then go back. Arms by two-bone IK onto the wrist that puts the palm / pinch exactly there; fingers set on the hand.
function bookGrip(OB){
  const DEG = Math.PI / 180, all = JSON.parse(fs.readFileSync(OB.props)), P = JSON.parse(JSON.stringify(all[OB.clip]));
  const qOf = r => new THREE.Quaternion().setFromEuler(new THREE.Euler(r[0] * DEG, r[1] * DEG, r[2] * DEG, "XYZ"));
  const eul = q => { const e = new THREE.Euler().setFromQuaternion(q, "XYZ"); return [e.x, e.y, e.z].map(x => +(x / DEG).toFixed(3)); };
  const items = P.world.filter(w => /page block|cover/.test(w.what)), c = items.reduce((a, w) => a.add(V(w.pos)), new THREE.Vector3()).multiplyScalar(1 / items.length);
  const Rt = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), -(OB.tilt || 0) * DEG);   // the far edge up: steeper toward his face
  const sh = V(OB.shift || [0, 0, 0]);   // the book moved (MakeHuman clip frame, m) into the v5 arms' reach
  const tp = p => V(p).sub(c).applyQuaternion(Rt).add(c).add(sh).toArray().map(x => +x.toFixed(5));
  for (const w of items) { w.pos = tp(w.pos); w.rot = eul(Rt.clone().multiply(qOf(w.rot || [0, 0, 0]))); }
  for (const pg of P.pages || []) { pg.pivot = tp(pg.pivot); pg.rot = eul(Rt.clone().multiply(qOf(pg.rot))); pg.axis = V(pg.axis).applyQuaternion(Rt).toArray().map(x => +x.toFixed(5)); }
  const HSw = O.handShift || O.shift || [0, 0], Pw = JSON.parse(JSON.stringify(P)), dd = [HSw[1], O.seatLift || 0, (O.forward || 0) + HSw[0]];
  for (const w of Pw.world) if (/page block|cover/.test(w.what)) w.pos = w.pos.map((x, i) => +(x + dd[i]).toFixed(5));
  for (const pg of Pw.pages || []) pg.pivot = pg.pivot.map((x, i) => +(x + dd[i]).toFixed(5));
  if (OB.out) { const o = fs.existsSync(OB.out) ? JSON.parse(fs.readFileSync(OB.out)) : JSON.parse(JSON.stringify(all)); o[OB.clip] = Pw; fs.writeFileSync(OB.out, JSON.stringify(o, null, 1)); }
  // the seat lift and the forward shift baked into the written props (clip frame: +y up, +z his forward)
  const HS0 = O.handShift || O.shift || [0, 0];
  const D = new THREE.Vector3(HS0[1], O.seatLift || 0, (O.forward || 0) + HS0[0]), R = p => V(p).add(D).applyQuaternion(C), Rd = v => v.clone().applyQuaternion(C);
  const cen = R(c.clone().add(sh).toArray());   // (R adds D)
  const half = side => { const pg = items.find(w => /page block/.test(w.what) && (side === "L" ? /left/.test(w.what) : /right/.test(w.what))), cv = items.find(w => /cover/.test(w.what) && (side === "L" ? /left/.test(w.what) : /right/.test(w.what)));
    const Q = C.clone().multiply(qOf(pg.rot)), ex = new THREE.Vector3(1, 0, 0).applyQuaternion(Q), ey = new THREE.Vector3(0, 1, 0).applyQuaternion(Q), ez = new THREE.Vector3(0, 0, 1).applyQuaternion(Q);
    const pc = R(pg.pos), cc = R(cv.pos), up = ez.clone().multiplyScalar(cc.clone().sub(pc).dot(ez) > 0 ? -1 : 1), out = ex.clone().multiplyScalar(pc.clone().sub(cen).dot(ex) > 0 ? 1 : -1);
    const top = ey.clone().multiplyScalar(ey.x > 0 ? 1 : -1), under = cc.clone().sub(up.clone().multiplyScalar(Math.max(cv.size[2], 0.005) / 2));
    return {pc, up, out, top, under, hw: pg.size[0] / 2, hz: pg.size[2] / 2, cw: cv.size[0] / 2}; };
  const H = {L: half("L"), R: half("R")};
  // the v5 hand's rest basis: x wrist -> middle base, y index base -> little base, z = x * y; the palm faces +-z
  const basis = (x, y) => { x = x.clone().normalize(); y = y.clone().sub(x.clone().multiplyScalar(y.dot(x))).normalize(); return new THREE.Matrix4().makeBasis(x, y, x.clone().cross(y)); };
  const RB = {}; for (const s of ["L", "R"]) RB[s] = basis(restP(`finger3-1.${s}`).sub(restP(`${s}_Hand`)), restP(`finger5-1.${s}`).sub(restP(`finger2-1.${s}`))).transpose();
  // hand world rotation from (fingers' direction x, palm normal n); thumb side t = n * x (left), x * n (right); y = -t
  const handRot = (s, x, n) => { const t = s === "L" ? n.clone().cross(x) : x.clone().cross(n); const Mt = basis(x, t.clone().negate());
    return new THREE.Quaternion().setFromRotationMatrix(Mt.multiply(RB[s].clone())).multiply(rest.W.get(B(`${s}_Hand`))); };
  const tipOf = (st, f, s) => { const a = B(`finger${f}-3.${s}`), b = B(`finger${f}-2.${s}`), off = restP(`finger${f}-3.${s}`).sub(restP(`finger${f}-2.${s}`)).multiplyScalar(0.85);
    return st.P.get(a).clone().add(off.applyQuaternion(rest.W.get(a).clone().invert()).applyQuaternion(st.W.get(a))); };
  const palmOf = (st, s) => st.P.get(B(`${s}_Hand`)).clone().lerp(st.P.get(B(`finger3-1.${s}`)), 0.55);
  // fingers 2-5: flex (deg, the three joints) toward the palm side, spread (deg) about the palm normal toward the thumb
  const SPREAD = {2: 5, 3: 0, 4: -4, 5: -9};
  function setFingers(L, ht, s, flex, n, thumbGoal){
    let st;
    for (let m = 1; m <= 4; m++) { const mb = B(`metacarpal${m}.${s}`); if (mb) L.set(mb, restL.get(mb).clone()); }
    st = fk(L, ht);
    // v5's rest fingers bend ~45 deg off the wrist-knuckle line, so each phalanx is aimed explicitly: along the hand's
    // wrist -> knuckle line (spread about the palm normal), then turned toward the palm by the summed flex of the joints so far
    const Rh = st.W.get(B(`${s}_Hand`)).clone().multiply(rest.W.get(B(`${s}_Hand`)).clone().invert());
    const xw = restP(`finger3-1.${s}`).sub(restP(`${s}_Hand`)).normalize().applyQuaternion(Rh), nn = n.clone().sub(xw.clone().multiplyScalar(n.dot(xw))).normalize();
    for (let f = 2; f <= 5; f++) { let parW = st.W.get(parentOf.get(B(`finger${f}-1.${s}`))), phi = 0;
      const df = xw.clone().applyAxisAngle(nn, (s === "L" ? 1 : -1) * (SPREAD[f] || 0) * DEG), ax = df.clone().cross(nn).normalize();
      for (let j = 1; j <= 3; j++) { const b = B(`finger${f}-${j}.${s}`);
        let W = parW.clone().multiply(restL.get(b)); const dir = (j < 3 ? restP(`finger${f}-${j + 1}.${s}`).sub(restP(`finger${f}-${j}.${s}`)) : restP(`finger${f}-3.${s}`).sub(restP(`finger${f}-2.${s}`))).normalize().applyQuaternion(rest.W.get(b).clone().invert()).applyQuaternion(W);
        phi += flex[f][j - 1] * DEG; const want = df.clone().applyAxisAngle(ax, phi);
        W = new THREE.Quaternion().setFromUnitVectors(dir, want).multiply(W); L.set(b, parW.clone().invert().multiply(W)); parW = W; } }
    // the thumb: CCD on its three joints, its tip onto thumbGoal
    const TB = [1, 2, 3].map(j => B(`finger1-${j}.${s}`));
    for (const b of TB) L.set(b, restL.get(b).clone());
    for (let it = 0; it < 12; it++) for (let j = 2; j >= 0; j--) { st = fk(L, ht); const tip = tipOf(st, 1, s), pj = st.P.get(TB[j]);
      const a = tip.clone().sub(pj).normalize(), g = thumbGoal.clone().sub(pj).normalize(); let q = new THREE.Quaternion().setFromUnitVectors(a, g);
      const ang = 2 * Math.acos(Math.min(1, Math.abs(q.w))); if (ang > 0.35) q = new THREE.Quaternion().slerp(q, 0.35 / ang);
      const Wj = q.multiply(st.W.get(TB[j])), pw = st.W.get(parentOf.get(TB[j])); L.set(TB[j], pw.clone().invert().multiply(Wj)); }
  }
  // the page turns: angle curves, start (first motion) and release (80 % of the way over)
  const turns = (P.pages || []).map(pg => { const ks = pg.keys, amin = Math.min(...ks.map(k => k[1])); const ts = ks.find(k => k[1] < -0.5)[0], te = ks.find(k => k[1] <= amin * 0.8)[0];
    return {pg, ts, te, ang: t => keyAt(ks, t), piv: R(pg.pivot), axis: Rd(V(pg.axis)).normalize(), Qp: C.clone().multiply(qOf(pg.rot))}; });
  function keyAt(ks, t){ let i = 0; while (i + 1 < ks.length && ks[i + 1][0] <= t) i++; const a = ks[i], b = ks[Math.min(i + 1, ks.length - 1)]; if (t <= a[0] || b[0] <= a[0]) return a[1]; return a[1] + (b[1] - a[1]) * Math.min(1, (t - a[0]) / (b[0] - a[0])); }
  const sstep = u => { u = THREE.MathUtils.clamp(u, 0, 1); return u * u * (3 - 2 * u); };
  const HOLDF = {2: [4, 4, 3], 3: [4, 4, 3], 4: [5, 5, 4], 5: [6, 6, 5]}, PINCHF = {2: [28, 38, 22], 3: [45, 55, 30], 4: [55, 60, 35], 5: [58, 62, 38]};
  const gy = OB.gy ?? -0.03;
  const hold = s => { const h = H[s], x = h.top.clone().multiplyScalar(Math.cos(25 * DEG)).sub(h.out.clone().multiplyScalar(Math.sin(25 * DEG))).normalize();
    const E = h.under.clone().add(h.out.clone().multiplyScalar(h.cw)).add(h.top.clone().multiplyScalar(gy));
    return {rot: handRot(s, x, h.up), n: h.up.clone(), palm: E.clone().sub(h.out.clone().multiplyScalar(0.04)).sub(h.up.clone().multiplyScalar(0.015)),
      thumb: h.pc.clone().add(h.out.clone().multiplyScalar(h.hw - 0.022)).add(h.top.clone().multiplyScalar(gy + 0.03)).add(h.up.clone().multiplyScalar(h.hz + 0.008)), flex: HOLDF}; };
  const HOLD = {L: hold("L"), R: hold("R")};
  function pinchAt(tr, t){ const a = tr.ang(t) * DEG, Qa = new THREE.Quaternion().setFromAxisAngle(tr.axis, a), h = H.R;
    // the page's lower outer corner (local x 0..size0 from the spine, y +-size1/2; the one nearer him), a little in
    const Qw = Qa.clone().multiply(tr.Qp), lx = new THREE.Vector3(1, 0, 0).applyQuaternion(tr.Qp), ly = new THREE.Vector3(0, 1, 0).applyQuaternion(tr.Qp), sy = ly.dot(h.top) > 0 ? -1 : 1;
    const loc = new THREE.Vector3(tr.pg.size[0] - 0.012, sy * (tr.pg.size[1] / 2 - 0.018), 0).applyQuaternion(tr.Qp);
    const corner = loc.applyQuaternion(Qa).add(tr.piv);
    const fol = Math.abs(a) <= 90 * DEG ? a : Math.sign(a) * (90 * DEG + 0.5 * (Math.abs(a) - 90 * DEG)), Qf = new THREE.Quaternion().setFromAxisAngle(tr.axis, fol);
    const x0 = h.out.clone().multiplyScalar(-Math.cos(40 * DEG)).add(h.top.clone().multiplyScalar(Math.sin(40 * DEG))).normalize(), n0 = h.up.clone().negate();
    const x = x0.applyQuaternion(Qf), n = n0.applyQuaternion(Qf); return {rot: handRot("R", x, n), n, corner, flex: PINCHF}; }
  const lerpFlex = (A, Bf, w) => { const o = {}; for (const f in A) o[f] = A[f].map((v, i) => v + (Bf[f][i] - v) * w); return o; };
  const solveHand = (L, ht, s, rot, n, flex, contact, thumbGoal, isPinch) => {
    let wt = contact.clone();
    for (let it = 0; it < 3; it++) { twoBone(L, ht, `${s}_Upperarm`, `${s}_Forearm`, `${s}_Hand`, wt, 1);
      let st = fk(L, ht); L.set(B(`${s}_Hand`), st.W.get(B(`${s}_Forearm`)).clone().invert().multiply(rot));
      if (isPinch !== undefined) { st = fk(L, ht); const tg = isPinch > 0 ? tipOf(st, 2, s).add(n.clone().multiplyScalar(-0.012)) : thumbGoal; setFingers(L, ht, s, flex, n, tg); }
      else setFingers(L, ht, s, flex, n, thumbGoal);
      st = fk(L, ht); const cp = isPinch > 0 ? tipOf(st, 2, s).lerp(tipOf(st, 1, s), 0.5) : (isPinch === 0 ? palmOf(st, s) : palmOf(st, s)); wt.add(contact.clone().sub(cp)); } };
  for (let f = 0; f < T; f++) { const t = f / FPS, L = seq[f].L, ht = seq[f].ht;
    const hl = HOLD.L; solveHand(L, ht, "L", hl.rot, hl.n, hl.flex, hl.palm, hl.thumb);
    let w = 0, tr = null; for (const x of turns) { const ww = t < x.ts ? sstep((t - (x.ts - 0.45)) / 0.45) : t <= x.te ? 1 : 1 - sstep((t - x.te) / 0.5); if (ww > w) { w = ww; tr = x; } }
    const hr = HOLD.R;
    if (OB.debug && f === 90) { const st = fk(L, ht), f3 = v => v.toArray().map(x => +x.toFixed(3)); const s = "L", h = H[s];
      console.error(JSON.stringify({top: f3(h.top), out: f3(h.out), up: f3(h.up), under: f3(h.under), pc: f3(h.pc), palmT: f3(hl.palm), palm: f3(palmOf(st, s)), wrist: f3(st.P.get(B("L_Hand"))), mid: f3(st.P.get(B("finger3-1.L"))), tip3: f3(tipOf(st, 3, s)), thumbT: f3(hl.thumb), thumb: f3(tipOf(st, 1, s)),
        dirMid: f3(st.P.get(B("finger3-1.L")).sub(st.P.get(B("L_Hand"))).normalize()), idx2pky: f3(st.P.get(B("finger5-1.L")).sub(st.P.get(B("finger2-1.L"))).normalize()), thumbBase: f3(st.P.get(B("finger1-1.L")))})); }
    if (w <= 0.001) { solveHand(L, ht, "R", hr.rot, hr.n, hr.flex, hr.palm, hr.thumb); continue; }
    const pc = pinchAt(tr, Math.min(Math.max(t, tr.ts), tr.te));
    // blend: the contact point moves from the palm spot to the corner along an arc out and up (round the cover's edge / over the pages)
    const arc = H.R.up.clone().add(H.R.out.clone().multiplyScalar(t < tr.ts ? 0.8 : 0.0)).multiplyScalar(0.05 * Math.sin(Math.PI * w) * (w < 1 ? 1 : 0));
    if (w >= 0.999) { solveHand(L, ht, "R", pc.rot, pc.n, pc.flex, pc.corner, null, 1); continue; }
    // in between: hand rotation slerped, contact on a mixed point, fingers blended; the thumb follows the index (pinch) as w grows
    const rot = hr.rot.clone().slerp(pc.rot, w), n = hr.n.clone().lerp(pc.n, w).normalize(), flex = lerpFlex(hr.flex, pc.flex, w);
    const contact = hr.palm.clone().lerp(pc.corner, w).add(arc);
    let wt = contact.clone();
    for (let it = 0; it < 3; it++) { twoBone(L, ht, "R_Upperarm", "R_Forearm", "R_Hand", wt, 1); let st = fk(L, ht); L.set(B("R_Hand"), st.W.get(B("R_Forearm")).clone().invert().multiply(rot));
      st = fk(L, ht); const tg = hr.thumb.clone().lerp(tipOf(st, 2, "R").add(n.clone().multiplyScalar(-0.012)), w); setFingers(L, ht, "R", flex, n, tg);
      st = fk(L, ht); const cp = palmOf(st, "R").lerp(tipOf(st, 2, "R").lerp(tipOf(st, 1, "R"), 0.5), w); wt.add(contact.clone().sub(cp)); } }
}

// ---------- write
for (const a of root.listAnimations()) a.dispose();
for (const n of root.listNodes()) if (n.getMesh()) { n.setMesh(null); n.setSkin(null); n.dispose(); }
for (const m of root.listMeshes()) m.dispose(); for (const s of root.listSkins()) s.dispose(); for (const m of root.listMaterials()) m.dispose(); for (const t of root.listTextures()) t.dispose();
for (const e of root.listExtensionsUsed()) e.dispose();
const buf = root.listBuffers()[0], name = O.name || anim.getName();
const an = doc.createAnimation(name), tin = doc.createAccessor().setArray(new Float32Array(seq.map((_, i) => i / FPS))).setType("SCALAR").setBuffer(buf);
const add = (node, pth, arr, type) => { const s = doc.createAnimationSampler().setInput(tin).setInterpolation("LINEAR").setOutput(doc.createAccessor().setArray(arr).setType(type).setBuffer(buf)); an.addSampler(s).addChannel(doc.createAnimationChannel().setTargetNode(node).setTargetPath(pth).setSampler(s)); };
for (const n of bonesTD) { if (n.getName() === "Armature") continue; const arr = new Float32Array(T * 4); let prev = null;
  seq.forEach((f, i) => { const q = (f.L.get(n) || restL.get(n)).clone().normalize(); if (prev && q.dot(prev) < 0) { q.x = -q.x; q.y = -q.y; q.z = -q.z; q.w = -q.w; } q.toArray(arr, i * 4); prev = q; }); add(n, "rotation", arr, "VEC4"); }
const hip = new Float32Array(T * 3); seq.forEach((f, i) => f.ht.toArray(hip, i * 3)); add(B("Hip"), "translation", hip, "VEC3");
await doc.transform(resample({tolerance: 2e-4}), prune({keepLeaves: true}));
await io.write(OUT, doc);
const rep = {clip: name, frames: T, fps: FPS, fingers: HAS_FINGERS, legScale: +k.toFixed(3), mapped: order.length, maxWristErr: +errH.toFixed(3), maxAnkleErr: +errF.toFixed(3), jitterBefore, jitterAfter};
if (O.report) fs.writeFileSync(O.report, JSON.stringify(rep, null, 1));
console.log(JSON.stringify(rep));
