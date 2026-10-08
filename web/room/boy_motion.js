// The character's motion layer (#98 G3, feature/gl-motion). Loaded by one block at the end of room.html, which hands it
// the page's internals (bones, mixer, actions, the HIPS table, the IK helpers) and calls update(dt) after the page's own
// animate(). It does two things:
//
// 1. Motion clips generated with NVIDIA ARDY (text-to-motion, Apache-2.0 code, checkpoints under the NVIDIA Open Model
//    License; see web/room/CREDITS.md) and retargeted onto this rig by room_build/ardy_to_boy.mjs: boy_m_*.glb, listed
//    in boy_m_manifest.json. Per activity (the CHOICE table below; ?motion= overrides it) a clip takes the place of the
//    page's one under the same action name (typing at the desk, eating, a standing idle, the walk, the window), with
//    the HIPS table updated so the page's planner puts the root where the hips must go. The clips go in after #76's
//    boy_moves.glb (room.html's loadMoves(), which takes the desk and the walk first). The clips the planner has no slot
//    for yet (sitting down, standing up, the door, the turn, lying on the bed) ship in the manifest and can be played
//    from the console (motion.play).
// 2. A procedural layer on top of whatever clip plays: breathing (chest, belly, shoulders, from his body model's rate),
//    weight shifts with the feet planted, foot IK on the floor (no foot below it; feet locked while they bear weight
//    in the walk), hand IK to the keyboard and the mouse (typing bursts, mouse moves) and to the bowl held in the left
//    hand while he eats from it, head and eye look-at (the page's gaze director picks the target; the eyes lead, the
//    head follows, blinks and micro-saccades on eye bones or ARKit-style morphs when the rig has them), and a pop
//    killer: any sudden jump of a bone between two frames (a clip change, a snap) is bridged by a decaying offset.
//
// Nothing here is a claim about him: it is animation. Every bone it moves is registered with the page's touch(), so the
// clip's own values come back before the next mixer update.

const BOWL_KINDS = new Set(["ramen", "curry"]);
const BOWL_RIM = 0.09;                                   // the held bowl's rim over its base (the Tripo ramen bowl, #131)
const KEYBOARD = {c: [-1.07, 1.0, -0.97], ry: 0.06, w: 0.36, d: 0.13};   // room_build/build_room.py: KB_C, KB_RY, kb_body (keys top at DTOP + 0.03)
const MOUSE = [-0.735, 0.985, -0.965];                    // G10d's mouse (room.html MOUSE_AT): its hump
const SWAP = {                                   // manifest clip -> the page's action it replaces, and the HIPS keys it owns
  type: {slot: "desk", action: "sit", hips: ["sit", "m_type"], edge: true},
  eat: {slot: "eating", action: "dine", hips: ["dine", "m_eat"], edge: true},
  idle: {slot: "standing", action: "stand", hips: ["stand", "lean", "deliver", "m_idle"]},
  walk: {slot: "walk", action: "walk", hips: ["walk", "m_walk"]},
  window: {slot: "window", action: "lean", hips: ["lean", "m_window"]},
};
// Which clip each activity plays. "ardy": the clip above (boy_m_*.glb). "ual": #76's room/boy_moves.glb (Quaternius UAL /
// keyed, loadMoves() in room.html), which has one for the desk (type) and the walk; for eating, standing and the window
// it has none wired, so "ual" there means the first clip. "old": the first (Meshy) clip the page shipped with.
// ?motion=ardy|ual|old sets every slot; ?motion=desk:ual,walk:old,... sets slots (the rest keep this table).
// Defaults picked from docs/screens/motion/sheet_1280.jpg (coordinator review of #114): #80's typing clip sits upright
// where ARDY's desk and eating hunch towards the monitor; ARDY's stance, walk and window read better than the first clips.
export const CHOICE = {desk: "ual", eating: "ual", standing: "ardy", walk: "ardy", window: "ardy"};
export function choices(search){
  const out = {...CHOICE}, q = new URLSearchParams(search || "").get("motion"); if (!q) return out;
  for (const part of q.split(",")) { const [a, b] = part.split(":"); const src = (b || a).trim(), slot = b ? a.trim() : null;
    if (!["ardy", "ual", "old"].includes(src)) continue;
    if (slot) { if (slot in out) out[slot] = src; } else for (const k in out) out[k] = src; }
  return out;
}
const UAL = {desk: "type", walk: "walk"};        // the boy_moves.glb clip names in the slots #76 takes (its MOVE table)
const OLD_FILE = {walk: "room/boy_walk.glb"};    // the first clip's file for a slot #76 takes; the desk's first clip is dine's (KEEP)

export function createMotion(env){
  const {THREE} = env;
  const V = () => new THREE.Vector3(), Q = () => new THREE.Quaternion();
  const UP = new THREE.Vector3(0, 1, 0);
  const _a = V(), _b = V(), _c = V(), _d = V(), _e = V(), _p = V(), _t = V(), _q = Q(), _q2 = Q();
  const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
  const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
  const wrap = a => Math.atan2(Math.sin(a), Math.cos(a));
  let seed = 98;
  const rnd = () => (seed = seed * 16807 % 2147483647) / 2147483647;
  const nz = (t, k) => { const i = Math.floor(t), f = t - i, u = f * f * (3 - 2 * f), h = n => { const x = Math.sin(n * 127.1 + k * 311.7) * 43758.5453; return x - Math.floor(x); }; return (h(i) + (h(i + 1) - h(i)) * u) * 2 - 1; };
  const B = env.bones, F = env.F;
  const M = {
    on: true, clips: {}, manifest: null, layers: {breathe: true, shift: true, feet: true, hands: true, eyes: true, smooth: true},
    T: 0, swapped: {}, log: [], choice: choices(env.search ?? (typeof location !== "undefined" ? location.search : "")),
  };

  // ---------- the clips
  async function loadClips(){
    let man;
    try { man = await (await fetch("room/boy_m_manifest.json", {cache: "no-cache"})).json(); } catch { M.ready = true; return; }
    M.manifest = man;
    for (const [name, info] of Object.entries(man.clips)) {
      try {
        const g = await env.load(`room/${info.file}`);
        restFromScene(g.scene);
        const clip = g.animations[0]; if (!clip || !clip.tracks.length) continue;
        clip.name = `m_${name}`;
        for (const tr of clip.tracks) if (tr.values.some(v => !Number.isFinite(v))) throw new Error("NaN in " + tr.name);
        M.clips[name] = {clip, info};
      } catch (e) { M.log.push(`clip ${name}: ${e.message}`); }
    }
    installClips();
  }
  let waited = 0;
  function installClips(){
    // after the page's own clips (they arrive one file at a time and would overwrite a swapped action) and after #76's
    // room/boy_moves.glb (loadMoves(): walk, type, lie_phone), which takes the same slots: these clips go in last and win
    // walking, the desk, standing and the sill; the phone in bed stays with lie_phone
    const ready = env.mixer && ["sit", "walk", "idle", "door", "stand", "eat", "sleep"].every(k => env.actions[k]) && (!env.movesDone || env.movesDone());
    if (!ready && (waited += 200) < 20000) { setTimeout(installClips, 200); return; }
    if (!env.mixer) { M.ready = true; return; }
    const pending = [];
    for (const [name, {clip, info}] of Object.entries(M.clips)) {
      const sw = SWAP[name]; if (!sw || !info.loop && name !== "window") continue;
      const src = M.choice[sw.slot];
      if (src === "old" && UAL[sw.slot] && clipNameOf(env.actions[sw.action]) === UAL[sw.slot]) pending.push(restoreOld(sw));
      if (src !== "ardy") continue;             // "ual" / "old": the slot keeps what the page has (#76's clip or the first one)
      const a = env.mixer.clipAction(clip);
      const old = env.actions[sw.action];
      env.actions[sw.action] = a;
      for (const k of sw.hips) env.HIPS[k] = info.hips.slice();
      if (sw.edge) env.EDGE.add(clip.name);
      if (info.stride && env.setStride) env.setStride(info.stride);   // the page's walk time scale is speed / stride
      M.swapped[sw.action] = {from: old, to: a};
      handOver(old, a);
    }
    // the page's own layers that this module replaces
    env.OFF.breathe = M.layers.breathe; env.OFF.shift = M.layers.shift; env.OFF.head = M.layers.eyes;
    Promise.all(pending).finally(() => { M.ready = true; });
  }
  const clipNameOf = a => a ? a.getClip().name : "";
  // the page is on the old action right now: hand over with a crossfade and tell the page which one it plays
  function handOver(old, a){
    const st = env.state();
    if (old && st.current === old && !st.step) { a.reset().setEffectiveWeight(1).fadeIn(0.8).play(); old.fadeOut(0.8); env.setCurrent(a); }
  }
  // ?motion=old on a slot #76's boy_moves.glb took: the first clip comes back (the desk's is kept under dine by the page's
  // KEEP; the walk's file is loaded again, from the browser's cache), with the HIPS the page started with (env.HIPS0)
  async function restoreOld(sw){
    try {
      let clip = null;
      if (sw.slot === "desk") { const d = env.actions.dine; if (d && clipNameOf(d).includes("Chair_Sit")) clip = d.getClip(); }
      else if (OLD_FILE[sw.slot]) { const g = await env.load(OLD_FILE[sw.slot]); clip = g.animations[0]; }
      if (!clip) return;
      const old = env.actions[sw.action], a = env.mixer.clipAction(clip);
      env.actions[sw.action] = a;
      if (env.HIPS0 && env.HIPS0[sw.action]) env.HIPS[sw.action] = env.HIPS0[sw.action].slice();
      if (sw.slot === "walk" && env.setStride && env.stride0) env.setStride(env.stride0);   // room.html's STRIDE_V for the first walk clip
      M.swapped[sw.action] = {from: old, to: a, old: true};
      handOver(old, a);
    } catch (e) { M.log.push(`old ${sw.slot}: ${e.message}`); }
  }
  loadClips();

  // ---------- helpers on bones (world-space, registered with the page's touch)
  function setWorld(bone, q){ env.touch(bone); env.setWorldQuat(bone, q); }
  function bendWorld(bone, axis, ang){ if (!bone || !ang) return; env.touch(bone); bone.getWorldQuaternion(_q2); _q.setFromAxisAngle(axis, ang); _q2.premultiply(_q); env.setWorldQuat(bone, _q2); }
  function ik(upper, lower, end, target, pole, w = 1, keepEnd = true){
    if (!upper || w <= 0.001) return; env.touch(upper, lower, end);
    const q0 = ik.q0 || (ik.q0 = [Q(), Q(), Q()]); q0[0].copy(upper.quaternion); q0[1].copy(lower.quaternion); end.getWorldQuaternion(q0[2]);
    env.reach(upper, lower, end, target, pole);
    if (w < 1) { blendQ(upper.quaternion, q0[0], w); blendQ(lower.quaternion, q0[1], w); upper.updateMatrixWorld(true); }
    if (keepEnd) env.setWorldQuat(end, q0[2]);
  }
  const _qb = Q();
  function blendQ(q, from, w){ _qb.copy(q); q.copy(from).slerp(_qb, w); }
  // the torso's frame: his left, up the spine, forward; and the root's facing / right
  const TL = V(), TU = V(), TF = V(), FW = V(), RT = V();
  function torso(){
    env.boy.updateMatrixWorld(true);
    B.LeftArm.getWorldPosition(TL); B.RightArm.getWorldPosition(_a); TL.sub(_a).normalize();
    (B.neck || B.Head).getWorldPosition(TU); B.Hips.getWorldPosition(_a); TU.sub(_a).normalize();
    TF.crossVectors(TL, TU).normalize();
    const r = env.boy.rotation.y; FW.set(Math.sin(r), 0, Math.cos(r)); RT.set(-Math.cos(r), 0, Math.sin(r));
  }

  // ---------- breathing: the belly first, then the chest; the shoulders ride up a little; deeper and slower asleep
  let ph = 0;
  function breathe(dt, ctx){
    const v = env.state().life && env.state().life.vitals, lying = ctx === "sleep" || ctx === "lie";
    const rate = clamp(v && v.resp_per_min || 14, 8, 30) * (lying ? 0.8 : 1);
    ph += dt * rate / 60 * Math.PI * 2;
    const b = Math.sin(ph), b2 = Math.sin(ph - 0.5), k = lying ? 1.35 : ctx === "walk" ? 0.6 : 1;
    bendWorld(B.Spine02, TL, -0.011 * k * b2);          // the belly / lower back
    bendWorld(B.Spine01, TL, -0.010 * k * b);           // the chest opens
    bendWorld(B.Spine, TL, -0.006 * k * b);
    bendWorld(B.LeftShoulder, TF, 0.014 * k * b); bendWorld(B.RightShoulder, TF, -0.014 * k * b);
    bendWorld(B.neck, TL, 0.004 * k * b);               // the head stays level: the neck counters a little
  }

  // ---------- weight shifts: the pelvis drifts a few centimetres, the feet stay where they are
  const FP = [V(), V()], FQ = [Q(), Q()];
  function shiftHips(side, fwd, down = 0){
    if (!B.Hips || (!side && !fwd && !down)) return;
    env.boy.updateMatrixWorld(true);
    ["Left", "Right"].forEach((s, i) => { B[s + "Foot"].getWorldPosition(FP[i]); B[s + "Foot"].getWorldQuaternion(FQ[i]); });
    env.touch(B.Hips); B.Hips.getWorldPosition(_p).addScaledVector(RT, side).addScaledVector(FW, fwd).addScaledVector(UP, -down);
    B.Hips.parent.worldToLocal(_p); B.Hips.position.copy(_p); B.Hips.updateMatrixWorld(true);
    // the pelvis rolls towards the loaded leg
    bendWorld(B.Hips, FW, -side * 0.6); bendWorld(B.Spine02, FW, side * 0.4);
    ["Left", "Right"].forEach((s, i) => {
      const up = B[s + "UpLeg"], lo = B[s + "Leg"], ft = B[s + "Foot"]; env.touch(up, lo, ft);
      _e.copy(FP[i]).addScaledVector(FW, 0.6).addScaledVector(UP, 0.45);
      env.reach(up, lo, ft, FP[i], _e); env.setWorldQuat(ft, FQ[i]);
    });
  }
  let shiftK = 0;
  function weightShift(dt, ctx){
    const want = ctx === "stand" || ctx === "sill" ? 1 : 0;
    shiftK += (want - shiftK) * (1 - Math.exp(-dt * 2));
    if (shiftK < 0.01) return;
    const t = M.T, side = 0.022 * nz(t * 0.09, 1) + 0.008 * nz(t * 0.31, 2), fwd = 0.006 * nz(t * 0.07, 3);
    shiftHips(side * shiftK, fwd * shiftK, 0.004 * Math.max(0, nz(t * 0.1, 4)) * shiftK);
  }

  // ---------- on the desk chair the back never reclines (its backrest is 32 cm behind the hip anchor: a reclined back sinks
  // into it): whatever the clip does, the torso is bent forward at the lower spine until it leans a touch forward of vertical
  function sitUp(ctx, st){
    if (!(ctx === "seat" || ctx === "eat") || st.at !== "desk" || !B.Spine02 || !B.Spine01) return;
    torso();
    // the lower back first: the lumbar segment (Hips -> Spine01) a touch forward of vertical, whatever the clip or an
    // idle variant (the page's "lean" reclines him) did; then the whole torso (Hips -> neck) the same
    B.Hips.getWorldPosition(_a); B.Spine01.getWorldPosition(_b); _b.sub(_a).normalize();
    let back = -_b.dot(FW);
    if (back > -0.16) { bendWorld(B.Spine02, TL, Math.asin(Math.min(1, back)) + 0.16); torso(); }
    back = -TU.dot(FW);
    if (back > -0.12) { const a = Math.asin(Math.min(1, back)) + 0.12; bendWorld(B.Spine01, TL, a * 0.6); bendWorld(B.Spine, TL, a * 0.4); torso(); }   // (+ about his left axis = forward)
  }
  // ---------- feet: no foot below the floor; in the walk a foot that bears weight stays where it landed
  // the feet's rest pose: heights above the floor and world rotations, read off a clip file's rig (the same nodes as
  // boy.glb, unanimated; the skin's bind pose is hips-centred and of no use here). Until one has loaded: boy.glb's numbers
  const TIP = 0.09, HEEL = 0.05;                         // m from the toe joint to the toe tip, and from the ankle back to the heel
  const REST = {q: {}, p: {}, ankle: 0.120, toe: 0.034, fromScene: false};
  function restFromScene(scene){
    if (REST.fromScene) return;
    scene.updateMatrixWorld(true);
    for (const name of ["LeftFoot", "RightFoot", "LeftToeBase", "RightToeBase"]) {
      const n = scene.getObjectByName(name); if (!n) return;
      REST.q[name] = n.getWorldQuaternion(Q()); REST.p[name] = n.getWorldPosition(V());
    }
    REST.ankle = Math.min(REST.p.LeftFoot.y, REST.p.RightFoot.y);          // the sole on the floor: joints at their rest heights
    REST.toe = Math.min(REST.p.LeftToeBase.y, REST.p.RightToeBase.y);
    // the sole's two ends as points in the bones' own frames: the heel's bottom (on the floor, 5 cm behind the ankle) in
    // the Foot bone's frame, the toe tip (on the floor, 9 cm past the toe joint) in the ToeBase bone's frame
    for (const side of ["Left", "Right"]) {
      const a = REST.p[side + "Foot"], t = REST.p[side + "ToeBase"];
      REST[side + "heel"] = V().set(a.x, 0, a.z - HEEL).sub(a).applyQuaternion(REST.q[side + "Foot"].clone().invert());
      REST[side + "tip"] = V().set(t.x, 0, t.z + TIP).sub(t).applyQuaternion(REST.q[side + "ToeBase"].clone().invert());
    }
    REST.fromScene = true;
  }
  function restHeights(){}
  const LOCK = {Left: null, Right: null};
  function feet(dt, ctx, st){
    restHeights();
    // a step other than the walk (onto the bed, off it, onto the chair) has the page's own keys: the floor clamp and the
    // leg IK fought them and put his legs in the bed. Nor on the bed, lying or on its edge (G3's diagnosis, #63)
    const onBed = st.goal && (st.goal.anchor === "bedlie" || st.goal.anchor === "bedside") && (st.at === st.goal.anchor || st.step);
    if ((st.step && st.step.k !== "walk") || onBed) { LOCK.Left = LOCK.Right = null; return; }
    const standing = ["stand", "sill", "walk", "move", "act"].includes(ctx);
    const seated = (ctx === "seat" || ctx === "eat") && st.at === "desk" && !(st.step);
    if (!standing && !seated) { LOCK.Left = LOCK.Right = null; return; }
    env.boy.updateMatrixWorld(true);
    if (seated) {                                      // on the desk chair: the knees level (a tilted thigh sinks into the
      // cushion: the QA budget is 0 vertices in the chair), the shins hanging; the feet reach the floor as far as his
      // legs allow and the toes point down to it where they do not (he is short for this chair)
      for (const side of ["Left", "Right"]) {
        const up = B[side + "UpLeg"], lo = B[side + "Leg"], ft = B[side + "Foot"]; if (!up || !ft) continue;
        up.getWorldPosition(_b); lo.getWorldPosition(_c); ft.getWorldPosition(_a);
        const thigh = _b.distanceTo(_c), shin = _c.distanceTo(_a);
        const kneeY = _b.y - 0.04, ankleY = Math.max(F + REST.ankle, kneeY - shin);           // the knee a touch below the hip
        _t.copy(_b).addScaledVector(FW, Math.sqrt(Math.max(0.01, thigh * thigh - 0.04 * 0.04)) + 0.02).addScaledVector(RT, side === "Left" ? -0.02 : 0.02);
        _t.lerp(_a, 0.25); _t.y = ankleY;
        _e.copy(_b).addScaledVector(FW, 0.8).addScaledVector(UP, 0.1);
        ik(up, lo, ft, _t, _e, 1, false);
        env.touch(ft); ft.getWorldQuaternion(_q);
        if (REST.q[side + "Foot"]) {
          const gap = ankleY - (F + REST.ankle), pitch = Math.min(0.9, Math.asin(Math.min(1, gap / 0.14)));   // toes down to the floor
          _q2.setFromAxisAngle(UP, env.boy.rotation.y).multiply(REST.q[side + "Foot"]);
          if (pitch > 0) _q2.premultiply(new THREE.Quaternion().setFromAxisAngle(RT, -pitch));
          _q.slerp(_q2, 0.85);
        }
        env.setWorldQuat(ft, _q);
      }
      LOCK.Left = LOCK.Right = null; return;
    }
    const walking = ctx === "walk" && st.step && st.step.turn0 == null && !(st.step.pts && st.step.pts.length === 0);
    for (const side of ["Left", "Right"]) {
      const up = B[side + "UpLeg"], lo = B[side + "Leg"], ft = B[side + "Foot"], toe = B[side + "ToeBase"];
      if (!up || !ft) continue;
      ft.getWorldPosition(_a); if (toe) toe.getWorldPosition(_b); else _b.copy(_a);
      let low = Math.min(_a.y - REST.ankle, _b.y - REST.toe);
      if (REST[side + "heel"]) {                       // the sole's ends, wherever the foot pitches: the heel's bottom and the toe tip
        ft.getWorldQuaternion(_q); low = Math.min(low, _c.copy(REST[side + "heel"]).applyQuaternion(_q).add(_a).y);
        if (toe) { toe.getWorldQuaternion(_q); low = Math.min(low, _c.copy(REST[side + "tip"]).applyQuaternion(_q).add(_b).y); }
      }
      let target = null;
      // locking: when the sole is on the floor and the foot moves slowly it is planted: keep it there (within 12 cm)
      const L = LOCK[side];
      if (walking) {
        const vel = L && L.prev ? _a.distanceTo(L.prev) / Math.max(dt, 1e-3) : 9;
        if (!L || !L.on) { if (low < F + 0.02 && vel < 0.35) LOCK[side] = {on: true, p: _a.clone(), prev: _a.clone(), w: 0}; else if (L) L.prev.copy(_a); }
        if (LOCK[side] && LOCK[side].on) {
          const K = LOCK[side]; K.prev.copy(_a);
          const lifting = low > F + 0.05 || _a.distanceTo(K.p) > 0.12;
          K.w += ((lifting ? 0 : 1) - K.w) * (1 - Math.exp(-dt * 25));
          if (lifting && K.w < 0.05) { K.on = false; }
          else { target = _t.copy(K.p).lerp(_a, 1 - K.w); target.y = Math.max(target.y, F + REST.ankle); }
        }
      } else LOCK[side] = null;
      if (!target && low < F + 0.004) { target = _t.copy(_a); target.y += F + 0.004 - low; }   // at or below the floor: lift straight up (G8 #8)
      if (!target) continue;
      lo.getWorldPosition(_e); _e.addScaledVector(FW, 0.5).addScaledVector(UP, 0.3);   // the knee forward
      ik(up, lo, ft, target, _e, 1, true);
    }
  }

  // ---------- hands at the desk: typing bursts and mouse moves on the real keyboard and mouse; the bowl in the left hand
  const HS = {mode: "type", until: 0, w: 0, k: 0};   // mode: type | mouse | rest
  const kbPoint = (u, v, out) => { const {c, ry, w, d} = KEYBOARD; return out.set(c[0] + Math.cos(ry) * u * w / 2 - Math.sin(ry) * v * d / 2, c[1], c[2] - Math.sin(ry) * u * w / 2 - Math.cos(ry) * v * d / 2); };
  function hands(dt, ctx, st){
    const life = st.life || {}, act = life.activity, iv = st.iv;
    const atDesk = ctx === "seat" && !st.holdW && !["scratch", "drink", "stretch", "phone", "lean", "mouse", "look"].includes(iv);
    const want = atDesk && ["research", "chat", "chart", "watch_video", "play_chess"].includes(act) ? 1 : 0;
    HS.w += (want - HS.w) * (1 - Math.exp(-dt * (want ? 6 : 5)));     // in within ~0.5 s of sitting down
    if (HS.w < 0.01) return;
    const t = M.T;
    if (t >= HS.until) {                              // what next: typing (research, chat), the mouse, or a rest on the desk
      const r = rnd(), typing = ["research", "chat"].includes(act);
      HS.mode = typing ? (r < 0.62 ? "type" : r < 0.88 ? "mouse" : "rest") : (r < 0.55 ? "mouse" : r < 0.8 ? "rest" : "type");
      HS.until = t + (HS.mode === "type" ? 4 + rnd() * 9 : HS.mode === "mouse" ? 2.5 + rnd() * 5 : 2 + rnd() * 4); HS.k = 0;
    }
    HS.k = Math.min(1, HS.k + dt / 0.45);
    const e = smooth(0, 1, HS.k) * HS.w, rise = (1 - HS.w) * 0.08;    // on the way in the hands come over the desk from above
    torso();
    for (const [side, sx] of [["Left", -1], ["Right", 1]]) {
      const typing = HS.mode === "type" || (HS.mode === "rest" && side === "Left");
      if (typing) {                                   // hovering over its half of the keys, a key press every ~0.15 s
        const press = HS.mode === "type" ? Math.max(0, Math.sin(t * 2 * Math.PI * (side === "Left" ? 6.3 : 5.7) + sx)) : 0;
        // the wrist 3 cm before the near edge of the keys and 7 cm up, the fingers (17 cm) angled down onto the rows (G8 #27)
        kbPoint(sx * 0.42 + 0.06 * nz(t * 0.9, 5 + sx), -1.5 + 0.3 * nz(t * 0.7, 7 + sx), _t);
        _t.y += 0.085 + rise - 0.006 * press * press + (HS.mode === "rest" ? 0.012 : 0);   // the tips land ~2 cm over the caps
      } else if (side === "Right") {                   // the mouse: small moves on the mat, the hand cupped on it
        _t.set(...MOUSE).addScaledVector(UP, 0.03 + rise).addScaledVector(FW, -0.10).add(_a.set(0.015 * nz(t * 1.1, 8), 0, 0.012 * nz(t * 0.9, 9)));   // the wrist behind the mouse, the palm cupped on its back
        if (Math.sin(t * 7.3) > 0.97) _t.y -= 0.004;                                       // a click
      } else { kbPoint(-0.5, -1.9, _t); _t.y += 0.035 + rise; }                             // the left hand rests on the mat before the keys
      B[side + "Arm"].getWorldPosition(_p).addScaledVector(UP, -0.36).addScaledVector(RT, sx * 0.28).addScaledVector(FW, -0.02);   // elbow out, forearm level with the desk
      ik(B[side + "Arm"], B[side + "ForeArm"], B[side + "Hand"], _t, _p, e, false);
      // the wrist: palm down over the keys (the hand's +z is the palm, +y along the fingers)
      env.touch(B[side + "Hand"]);
      _b.copy(FW).addScaledVector(UP, typing ? -0.4 : side === "Right" ? -0.3 : -0.06).normalize();   // fingers forward and down onto the caps / the mouse's back
      _c.copy(UP).negate();                                                                 // palm down
      _c.addScaledVector(_b, -_b.dot(_c)).normalize(); _d.crossVectors(_b, _c);
      const m = hands.m || (hands.m = new THREE.Matrix4()); m.makeBasis(_d, _b, _c); _q.setFromRotationMatrix(m);
      if (!typing && side === "Right") _q.multiply(_q2.setFromAxisAngle(new THREE.Vector3(0, 1, 0), 0.25));
      B[side + "Hand"].getWorldQuaternion(_q2); _q2.slerp(_q, e); env.setWorldQuat(B[side + "Hand"], _q2);
    }
  }
  // the desk top is solid (G8 #7): over its footprint no elbow or wrist goes below its surface; a forearm that would rest
  // on the slab is lifted onto it (the hand IK'd to the same place a little higher, the elbow raised with it)
  const DESK = {x0: -1.86, x1: -0.36, z0: -1.44, z1: -0.80, top: 0.97};
  function deskGuard(ctx, st){
    if (!(ctx === "seat" || ctx === "eat") || st.at !== "desk") return;
    env.boy.updateMatrixWorld(true);
    const over = p => p.x > DESK.x0 - 0.08 && p.x < DESK.x1 + 0.08 && p.z > DESK.z0 - 0.04 && p.z < DESK.z1 + 0.10;
    for (const [side, sx] of [["Left", -1], ["Right", 1]]) {
      if (side === "Right" && (st.holdW > 0 || st.held)) continue;
      const up = B[side + "Arm"], lo = B[side + "ForeArm"], h = B[side + "Hand"]; if (!up) continue;
      lo.getWorldPosition(_a); h.getWorldPosition(_b); h.getWorldQuaternion(_q); _c.set(0, 1, 0).applyQuaternion(_q).multiplyScalar(0.17).add(_b);   // the fingertips (the hand is ~17 cm long from the wrist)
      // the fingertips may come down onto the key caps (their tops: KEYBOARD.c[1]) and the mouse's back, not into the slab
      const onKeys = Math.abs(_c.x - KEYBOARD.c[0]) < KEYBOARD.w / 2 + 0.03 && Math.abs(_c.z - KEYBOARD.c[2]) < KEYBOARD.d / 2 + 0.03;
      const onMouse = Math.abs(_c.x - MOUSE[0]) < 0.07 && Math.abs(_c.z - MOUSE[2]) < 0.08;
      // (2 cm over the caps: the finger pads are a centimetre thick below the bone, and the QA counts skin inside the keys)
      const tipFloor = onKeys ? KEYBOARD.c[1] + 0.02 : onMouse ? MOUSE[1] + 0.045 : DESK.top + 0.06;
      const lift = Math.max(over(_a) ? DESK.top + 0.05 - _a.y : 0, over(_b) ? DESK.top + 0.06 - _b.y : 0, over(_c) ? tipFloor - _c.y : 0);
      if (lift <= 0) continue;
      _t.copy(_b); _t.y += lift;
      up.getWorldPosition(_p).addScaledVector(RT, sx * 0.3); _p.y = DESK.top + 0.12;      // the elbow out and over the slab
      ik(up, lo, h, _t, _p, 1, true);
    }
  }
  const DISH0 = V(); let dishMoved = false;
  function bowl(dt, ctx, st){
    const d = env.FOOD.dish, bowlNow = ctx === "eat" && d && BOWL_KINDS.has(d.kind) && st.at === "desk";
    if (!bowlNow) { if (dishMoved) { env.DISH_AT.copy(DISH0); if (d) d.g.position.copy(DISH0); dishMoved = false; } return; }
    if (!dishMoved) { DISH0.copy(env.DISH_AT); dishMoved = true; }
    torso();
    // the bowl in front of the chest, held in the left hand: a bit left, a hand's height off the desk. The hand is under
    // it, palm up, fingers forward and a little inwards; the bowl stands on the middle of the palm, so no finger is inside it
    B.Spine.getWorldPosition(_t).addScaledVector(FW, 0.27).addScaledVector(RT, -0.13).addScaledVector(UP, -0.20 + 0.004 * Math.sin(M.T * 0.9));
    _t.y = Math.max(_t.y, 1.03);                                                            // the wrist clear of the desk top (0.97; deskGuard lifts below 1.03)
    B.LeftArm.getWorldPosition(_p).addScaledVector(UP, -0.4).addScaledVector(RT, -0.35);
    ik(B.LeftArm, B.LeftForeArm, B.LeftHand, _t, _p, 1, false);
    env.touch(B.LeftHand); _b.copy(FW).addScaledVector(RT, 0.35).normalize();                // fingers forward, a little inwards
    _c.copy(UP); _c.addScaledVector(_b, -_b.dot(_c)).normalize(); _d.crossVectors(_b, _c);   // palm up
    const m = bowl.m || (bowl.m = new THREE.Matrix4()); m.makeBasis(_d, _b, _c); _q.setFromRotationMatrix(m); env.setWorldQuat(B.LeftHand, _q);
    env.boy.updateMatrixWorld(true);
    B.LeftHand.getWorldPosition(_a).addScaledVector(_b, 0.09).addScaledVector(UP, 0.069);    // on the middle of the palm, over the fingers (4 mm more: the palm skin stayed 3-4 mm inside the base at 0.065)
    d.g.position.copy(_a); d.g.rotation.set(0, 0.15 + env.boy.rotation.y, 0, "YXZ");
    env.DISH_AT.copy(_a).addScaledVector(UP, BOWL_RIM - 0.064 + 0.09);                              // the page's chopsticks follow the bowl (aimed for
                                                                                             // a 6.4 cm Kenney bowl: lifted by the taller one's rim)
  }

  // ---------- head and eyes: the eyes lead, the head follows late; blinks; small saccades
  const EYE = {look: V(0, 1.4, -1), head: V(0, 1.4, -1), w: 0, blink: 0, nextBlink: 2, sacc: V(), nextSacc: 0, morphs: null, bones: null};
  function findEyes(){
    if (EYE.morphs !== null) return;
    EYE.morphs = false; EYE.bones = (B.LeftEye || B.RightEye) ? {L: B.LeftEye, R: B.RightEye} : false;
    env.boy.traverse(o => { if (o.isMesh && o.morphTargetDictionary) { const d = o.morphTargetDictionary;
      const pick = (...names) => { for (const n of names) if (n in d) return n; return null; };
      const map = {blinkL: pick("eyeBlinkLeft", "eyeBlink_L", "blinkLeft", "blink"), blinkR: pick("eyeBlinkRight", "eyeBlink_R", "blinkRight"),
        upL: pick("eyeLookUpLeft", "eyeLookUp_L"), downL: pick("eyeLookDownLeft", "eyeLookDown_L"), inL: pick("eyeLookInLeft", "eyeLookIn_L"), outL: pick("eyeLookOutLeft", "eyeLookOut_L"),
        upR: pick("eyeLookUpRight", "eyeLookUp_R"), downR: pick("eyeLookDownRight", "eyeLookDown_R"), inR: pick("eyeLookInRight", "eyeLookIn_R"), outR: pick("eyeLookOutRight", "eyeLookOut_R")};
      if (map.blinkL || map.upL) EYE.morphs = {mesh: o, map}; } });
  }
  function aimHead(p, w){
    const head = B.Head, neck = B.neck; if (w <= 0.01 || !head || !neck) return; env.touch(neck, head);
    head.getWorldPosition(_a); _b.subVectors(p, _a);
    const y0 = Math.atan2(TF.x, TF.z), yaw = clamp(wrap(Math.atan2(_b.x, _b.z) - y0), -1.2, 1.2) + y0;
    const pit = clamp(Math.atan2(_b.y, Math.hypot(_b.x, _b.z)), -0.75, 0.45);
    _b.set(Math.sin(yaw) * Math.cos(pit), Math.sin(pit), Math.cos(yaw) * Math.cos(pit));
    for (const [bone, k] of [[neck, 0.35 * w], [head, w]]) {
      head.localToWorld(_c.set(0, 30, 30)); head.getWorldPosition(_a);
      _d.copy(_b).multiplyScalar(_c.distanceTo(_a)).add(_a).lerp(_c, 1 - k); env.aimBone(bone, _c, _d);
    }
  }
  function eyes(dt, ctx, st){
    findEyes();
    const GZ = env.GZ, lying = ctx === "lie" || ctx === "sleep";
    // the eyes jump to the target (with a saccade's overshoot); the head follows on a slower spring and never all the way
    const t = M.T;
    if (t >= EYE.nextSacc) { EYE.nextSacc = t + 0.4 + rnd() * 1.6; EYE.sacc.set((rnd() - 0.5) * 0.06, (rnd() - 0.5) * 0.04, 0); }
    EYE.look.lerp(_a.copy(GZ.p).add(EYE.sacc), 1 - Math.exp(-dt * 30));
    EYE.head.lerp(GZ.p, 1 - Math.exp(-dt * 4.5));
    EYE.w += (GZ.w - EYE.w) * (1 - Math.exp(-dt * 3));
    torso();
    if (!lying && M.layers.eyes) aimHead(EYE.head, EYE.w * 0.85);
    // blinks: every 2-6 s, 120 ms, a double one now and then; longer and rarer asleep (closed)
    if (t >= EYE.nextBlink) { EYE.blink = 1; EYE.nextBlink = t + (rnd() < 0.15 ? 0.35 : 2 + rnd() * 4); }
    EYE.blink = Math.max(0, EYE.blink - dt / 0.12);
    const closed = ctx === "sleep" ? 1 : Math.sin(Math.PI * Math.min(1, EYE.blink));
    // eye direction relative to the head: where the look point is, from the face's frame
    if (EYE.bones || EYE.morphs) {
      B.Head.getWorldPosition(_a); B.Head.localToWorld(_c.set(0, 30, 30)).sub(_a).normalize();    // the face direction
      _b.subVectors(EYE.look, _a).normalize();
      const right = _d.crossVectors(UP, _c).normalize(), yaw = clamp(Math.asin(clamp(_b.dot(right), -1, 1)), -0.6, 0.6), pit = clamp(Math.asin(clamp(_b.dot(UP) - _c.dot(UP), -1, 1)), -0.5, 0.5);
      if (EYE.bones) for (const e of [EYE.bones.L, EYE.bones.R]) if (e) { env.touch(e); e.getWorldQuaternion(_q); _q.premultiply(_q2.setFromAxisAngle(UP, -yaw * EYE.w)); _q.premultiply(_q2.setFromAxisAngle(right, pit * EYE.w)); env.setWorldQuat(e, _q); }
      if (EYE.morphs) { const {mesh, map} = EYE.morphs, I = mesh.morphTargetInfluences, D = mesh.morphTargetDictionary, set = (n, v) => { if (n) I[D[n]] = clamp(v, 0, 1); };
        set(map.blinkL, closed); set(map.blinkR, closed);
        const h = yaw * EYE.w / 0.6, v = pit * EYE.w / 0.5;
        set(map.upL, v); set(map.upR, v); set(map.downL, -v); set(map.downR, -v);
        set(map.outL, -h); set(map.inL, h); set(map.inR, -h); set(map.outR, h); }
    }
  }

  // ---------- the pop killer: a bone that jumps between two frames gets a decaying offset that bridges the jump. It runs
  // before the IK layers, on the clip-driven bones (the torso, the shoulders, the head, the legs' tops): a hand or a
  // foot that an IK layer places lands on its target whatever happened the frame before
  const SM = new Map();                               // bone -> {q: last output, off: offset, k: how much of it is left}
  let lastRoot = null;
  const JUMP = 0.22, DECAY = 0.28;
  function smoothBones(dt){
    const root = env.boy.position;
    const teleport = !lastRoot || lastRoot.distanceTo(root) > 0.35;   // a snap into place: nothing to bridge
    (lastRoot || (lastRoot = V())).copy(root);
    const st = env.state(), skipR = st.holdW > 0 || st.held;      // a prop hangs on the right hand: it was placed before this
    // on the bed (lying or on its edge), and getting onto or off it, the page moves him continuously itself (room.html
    // lieFit, the turn over, the sit-down keys): bridging those as jumps held his legs in the mattress as he lay back (#63)
    // and in any step but the walk (sitting down, standing up, the turn, an act) the page moves him on purpose and fast:
    // bridging that dragged his hips and spine behind it into the desk chair (G3's diagnosis, #63)
    const bed = a => a === "bedlie" || a === "bedside";
    if (bed(st.at) || (st.step && st.step.k !== "walk")) { SM.clear(); lastRoot = null; return; }
    for (const name in B) {
      const b = B[name]; if (!b || !b.isBone) continue;
      let s = SM.get(b); if (!s) SM.set(b, s = {q: b.quaternion.clone(), off: Q(), k: 0});
      const skip = teleport || dt > 0.25 || !/^(Hips|Spine02|Spine01|Spine|neck|Head|LeftShoulder|RightShoulder|LeftUpLeg|RightUpLeg)$/.test(name)
        || (skipR && /^Right(Arm|ForeArm|Hand)$/.test(name)) || (st.holdW > 0 && (name === "Head" || name === "neck"));
      if (skip) { s.q.copy(b.quaternion); s.k = 0; continue; }
      const ang = 2 * Math.acos(Math.min(1, Math.abs(b.quaternion.dot(s.q))));
      if (ang > JUMP) {                               // offset = last output * current^-1 (so offset * current = last output)
        s.off.copy(s.q).multiply(_q.copy(b.quaternion).invert()); s.k = 1;
      }
      if (s.k > 0) {
        s.k = Math.max(0, s.k - dt / DECAY); const w = s.k * s.k * (3 - 2 * s.k);
        env.touch(b); _q.copy(s.off); _q2.identity().slerp(_q, w); b.quaternion.premultiply(_q2); b.updateMatrixWorld(true);
      }
      s.q.copy(b.quaternion);
    }
  }

  // ---------- each frame, after the page's animate()
  function update(dt){
    if (!M.on || !env.boy || !env.boy.visible || !B.Hips || !B.LeftArm) return;
    M.T += dt;
    const st = env.state(), ctx = st.ctx;
    torso();
    if (M.layers.smooth) smoothBones(dt);               // first: the IK layers below then land on their targets exactly
    if (M.layers.breathe) breathe(dt, ctx);
    if (M.layers.shift && !(st.step && st.step.k !== "act")) weightShift(dt, ctx);
    if (M.layers.feet) { sitUp(ctx, st); feet(dt, ctx, st); }
    if (M.layers.hands) { hands(dt, ctx, st); bowl(dt, ctx, st); deskGuard(ctx, st); }
    if (M.layers.eyes) eyes(dt, ctx, st);
    env.boy.updateMatrixWorld(true);
  }
  // console: motion.play("sit_down") plays a shipped clip once over the current one; motion.layers.x = false switches a layer off
  function play(name, fade = 0.4){
    const c = M.clips[name]; if (!c || !env.mixer) return null;
    const a = env.mixer.clipAction(c.clip); a.reset().setLoop(THREE.LoopOnce, 1).fadeIn(fade).play(); return a;
  }
  return {update, play, layers: M.layers, clips: M.clips, rest: REST, get manifest(){ return M.manifest; }, swapped: M.swapped, log: M.log,
    get ready(){ return !!M.ready; },            // the clips are in (or given up on): tests wait for this before a scene
    choice: M.choice,                            // which clip each activity plays (CHOICE, ?motion=)
    set on(v){ M.on = v; }, get on(){ return M.on; }};
}
