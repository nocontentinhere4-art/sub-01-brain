// The MakeHuman rig with real mocap (preview/room-mh, a crude first integration; #98). When room/boy.glb is the MakeHuman
// body (163 bones with fingers, metres, feet at y = 0, bones world-aligned at rest; on this branch G2's boy_g2.glb with
// preview/mh-motion's clips_g2 in room/mh/, which go together), the old rig's clips and procedural layers do not fit it:
// this module takes over.
//
// The desk follows the owner's rule ("deve scrivere sulla tastiera quando cerca qualcosa, usare il mouse per cliccare e
// selezionare cose, e quando guarda video sta semplicemente sulla sedia"):
//   research: a new screen that carries a search query -> desk_type_ik for about the time to type it (4-8 s), else the mouse
//   watch_video, and any screen of kind video / short -> desk_watch (relaxed in the chair)
//   chart, play_chess -> desk_mouse_ik
// with 0.4 s crossfades between the modes. desk_type_ik and desk_mouse_ik (the owner approved both) already carry the
// arms, the wrists and the fingers against a keyboard and a mouse placed in the clip's own frame; here the wrists are only
// re-pinned to the room's real keyboard and mouse: the recorded wrist (with its drift) moves by the offset between the
// clip's reference point and the room's, and no fingertip goes below the keycaps (+3 mm) or into the pad (+1.1 cm).
//
// Swappable parts: a room node named "keyboard" (G10d's Tripo keyboard) replaces the keycap numbers below by its bounds,
// and a node named "mouse" follows the right palm while he uses it (within 6 cm of where it lies on the pad). In the
// room on main both are part of the merged static mesh, so the numbers below are used and the mouse stays put.
//
// The room's moves: the recorded walk loop (the page moves him along his path), sit down / stand up on the chair, lie
// down / get up on the bed, each pose step lasting its clip's stretch and placed by the clip's own pose (the seat, the
// bed's edge, lying on the duvet). Still frames stand in for standing (room_window's first) and for sitting on the bed's
// edge and lying; the old rig's interludes, breathing, look-at, foot IK and phone hold are off.
//
// At the desk the seated pose, the sit-down and the stand-up are real captures (Mixamo, retargeted onto v5 and fitted to
// this chair: docs/design/mixamo): room_seated_idle (watching, and every seated slot), room_mx_stand_to_sit,
// room_mx_sit_to_stand. Leaving the desk he rides the chair back out, stands up with room_mx_sit_to_stand and walks off;
// where the sit-down starts and the stand-up ends come from the clips (env.setSpots). (room_bedtime's one-take get-up,
// flow(), is no longer used for leaving the desk: it put his torso 9 cm into the chair.) The walk plays as recorded.

const CLIPS = {desk_type: "room_mx_typing", desk_mouse: "room_seated_idle", desk_watch: "room_seated_idle", stand: "room_window",
  walk: "room_walk", sit_down: "room_mx_stand_to_sit", stand_up: "room_mx_sit_to_stand", bed_lie: "room_bed_lie", bed_wake: "room_bed_wake",
  eat: "room_eat", read: "room_read", phone: "room_phone", phone_scroll: "room_phone_scroll", drink: "room_drink", door: "room_door", window: "room_window",
  bedtime: "room_bedtime"};
// the room (main): keycaps (G10d) centre, top y, turn about y, size; the mouse centre on the pad; the desk / pad top
const ROOM = {keys: {c: [-1.070, 1.001, -0.976], ry: 0.06, w: 0.356, d: 0.134}, mouse: [-0.755, 0.973, -0.950], pad: 0.973};
// the clips' frame (root at the feet, facing +z; measured in the page: the recorded wrists sit on the README's pins in
// it): the keyboard the typing was pinned to (keycaps' centre at KEYTOP; the wrists' pins (0.03 / -0.13, 0.878, 0.32)
// lie over its near half) and the mouse dome's hump (on DESK_Y), from preview/mh-motion's README. G2's clips (clips_g2)
// sit the typing and the mouse higher (DY 0.032 at 4f1f995, on the 0.52 m seat); measured in the page, raising the clip's
// keyboard and mouse by 2.6 cm puts the pressing fingertips 2-5 mm over the keycaps
const DY = 0.026;
const CLIP0 = {kb: [-0.05, 0.83 + DY, 0.33], mouse: [-0.36, 0.807 + DY, 0.39], desk: 0.809 + DY,
  home: [-0.003, 0.83 + DY, 0.317]};                         // the same keyboard's home row (F/J, KB_HOME): 4.7 cm left, 1.3 cm nearer
// the room clips (preview/mh-motion README): sit_down ends facing +z with the chair's seat centre at (-0.26, -0.13) (boy_mh;
// measured from the clips at load: G2's is at (-0.28, -0.15));
// stand_up starts seated with it at (0, 0); the bed clips are lifted to the 0.66 m mattress (the room's: 0.82 - 0.16)
const SEAT = {down: [-0.26, -0.13], up: [0, 0]};
const BED = {hips: [-0.90, 0.89], head: -1,               // where his hips lie on the duvet (x, z), the head toward -x (the headboard;
  // 10 cm from it since the 1.90 m bed: the back of his head was 5 cm into its oak),
  edge: [-0.40, 0.36], face: Math.PI,                        // where he sits on its edge (ANCHOR.bedside's seat), facing the desk (-z),
  box: [-1.90, 0.05, 0.25, 1.50], top: 0.805};                // and the mattress (x0, x1, z0, z1) with its top less 1.5 cm of give
const WALK_V = 0.67;                                         // room_walk's travel speed (m/s)
// the Mixamo typing capture (room_mx_typing, G12): where the performer's index fingers were, in the clip's frame as the page
// has it (fixClip: body = (-z, y + 0.02, x) of the GLB's): G12's measured F (left index) and J (right index) last joints,
// means over the clip, 1.5 cm on to the fingertips and 1 cm down to the key tops under them. Each hand is carried by its
// own mean onto our F / J (the performer's keyboard was wider: his hands sat 18 cm apart, which put the left little finger
// off ours), and keeps its own motion about it (the right hand travels 13.6 cm: kept, not pinned)
const CLIP_MX = {F: [0.118, 0.695, 0.541], J: [-0.063, 0.717, 0.569], clip: "room_mx_typing"};
const MX_SHIFT = 0.045;   // (m along the keys, + = his right: the capture's hands centred so its left little finger is on the keys; its hands sit 18 cm apart, wider than F-J)
const HUMP = 0.02;                                           // a room mouse's hump: 2 cm behind its centre (the back third)
const FADE = 0.4;
const REACH_S = 0.8;                                         // (s: a mode switch at the desk; the right wrist's ~32 cm keys <-> mouse then peaks ~0.75 m/s)

export const isMH = bones => !!(bones && (bones["metacarpal1L"] || bones["metacarpal1.L"]));   // (three.js drops the dot)

export function createMH(env) {
  const {THREE} = env;
  // (a character with its own desk clips, room.html?char=mixamo: env.clips names the clip per slot, type_in / type_out
  // the way into and out of typing, env.links their cross-fades; env.clipFrame its typing keyboard; env.seatAt its seat
  // points. Without them, the clips and numbers above)
  const CL = {...CLIPS, ...(env.clips || {})}, CLIP = {...CLIP0, ...(env.clipFrame || {})};
  const MXK = env.clipMX || CLIP_MX;                          // (the typing capture's F / J points: env.clipMX for its own bake)
  const M = {ready: false, mode: null, typeUntil: 0, lastScreen: null, actions: {}, w: {type: 0, mouse: 0}, ph: {type: 0, mouse: 0}, log: [], noIK: false, zoff: 0,
    handsHz: 15};                                            // (the hands' contact solve, times a second; 0: every frame. ?debug: mh.M.handsHz)
  const V = (...a) => new THREE.Vector3(...a);

  // ---------- clips: two approved desk loops, the relaxed one, and two still poses, under the page's slot names ----------
  function stillClip(name, clip, at) {                       // one frame of a clip as a 1 s still
    const tracks = clip.tracks.map(tr => { const v = tr.createInterpolant().evaluate(at).slice(); return new tr.constructor(tr.name, [0, 1], [...v, ...v]); });
    return new THREE.AnimationClip(name, 1, tracks);
  }
  function hipsAt(clip, at) {                               // where the clip has the hips at a time (metres, from the root)
    const tr = clip.tracks.find(t => t.name === "Hips.position");
    return tr ? Array.from(tr.createInterpolant().evaluate(at)) : [0, 0.87, -0.076];
  }
  // the hips for the page's own table (HIPS: where it puts his root so the hips land on a seat, the bed, a spot). G14
  // tuned v5's seat placement (env.seatIn, the chair rolled in, the hips centred) while char_v5.js still hung the Hip
  // under its turned group, i.e. against these values turned back into that group's frame; env.pageHips does that turn,
  // so the page places him exactly as tuned. boy_mh.js's own sums (the segments, the re-rooted get-up, the bed's
  // placements) use hipsAt, in the body's frame like its sampler
  const pageHips = (clip, at) => env.pageHips ? env.pageHips(hipsAt(clip, at)) : hipsAt(clip, at);
  // a clip's pose at a time, in its own frame (the root at the feet): the hips' and the head's positions
  function sampler(clip) {
    const mx = new THREE.AnimationMixer(env.boy), a = mx.clipAction(clip); a.play();
    const B = env.bones, out = t => { a.time = t; mx.update(0); env.boy.updateMatrixWorld(true);
      const loc = n => env.boy.worldToLocal(B[n].getWorldPosition(V()));
      return {t, hips: loc("Hips"), head: loc("Head"), knee: loc("LeftLeg").add(loc("RightLeg")).multiplyScalar(0.5),
        foot: Math.max(loc("LeftFoot").y, loc("RightFoot").y), fl: loc("LeftFoot").y, fr: loc("RightFoot").y, hand: Math.max(loc("LeftHand").y, loc("RightHand").y),
        feet: loc("LeftFoot").add(loc("RightFoot")).add(loc("LeftToeBase")).add(loc("RightToeBase")).multiplyScalar(0.25)}; };
    out.done = () => { a.stop(); mx.uncacheRoot(env.boy); };
    return out;
  }
  function segments(got) {
    const scan = (clip, dt = 0.05) => { const s = sampler(clip), r = []; for (let t = 0; t <= clip.duration + 1e-6; t += dt) r.push(s(Math.min(t, clip.duration))); s.done(); return r; };
    const S = {};
    // sit_down: the last moment the hips are still high (standing) before they drop onto the seat
    const sd = scan(got.sit_down); let i = sd.length - 1; while (i > 0 && sd[i].hips.y < 0.80 * M.k) i--;
    S.sit = {from: Math.max(0, sd[i].t - 0.3), to: got.sit_down.duration};
    // the chair's seat centre in sit_down's frame: where it leaves the hips, less where stand_up starts them (its seat at 0, 0)
    const su = sampler(got.stand_up), h0 = su(0).hips; su.done();
    S.seatDown = [sd[sd.length - 1].hips.x - h0.x, sd[sd.length - 1].hips.z - h0.z];
    // bed_lie: on the edge = hips low with the head up; lying = the head low
    const bl = scan(got.bed_lie);
    const e0 = bl.find(p => p.hips.y < 0.80 * M.k && p.head.y > 1.05 * M.k) || bl[Math.floor(bl.length / 3)];
    const l0 = bl.find(p => p.t > e0.t && p.head.y < 1.0 * M.k) || bl[Math.floor(bl.length * 2 / 3)];
    // sitting on the edge: the middle of the stretch where he sits upright with his feet down (before they swing up to lie)
    const up = bl.filter(p => p.t >= e0.t && p.t <= l0.t && p.hips.y < 0.76 * M.k && p.head.y > 1.3 * M.k && p.foot < 0.3), sat = up.length ? up[up.length >> 1] : e0;
    S.lie = {stand: Math.max(0, e0.t - 1.6), edge: sat.t, end: got.bed_lie.duration, endPose: bl[bl.length - 1]};
    // bed_wake: lying -> sitting up (head high again) -> standing (hips high)
    const bw = scan(got.bed_wake);
    const s0 = bw.find(p => p.head.y > 1.05 * M.k && p.hips.y < 0.80 * M.k) || bw[Math.floor(bw.length / 3)];
    S.wake = {sat: Math.min(s0.t + 0.6, got.bed_wake.duration), end: got.bed_wake.duration, startPose: bw[0]};
    // the bed's placement: the lying pose turned so the head points toward the headboard, the hips on the duvet
    S.bedLie = bedPlace(S.lie.endPose); S.bedWake = bedPlace(S.wake.startPose);
    // on the edge: the clip's bed is not laid out like the room's, so the sitting moments get their own placement
    const atT = (r, t) => r.reduce((b, q) => Math.abs(q.t - t) < Math.abs(b.t - t) ? q : b);
    S.lieEdge = edgePlace(atT(bl, S.lie.edge)); S.wakeEdge = edgePlace(atT(bw, S.wake.sat));
    // room_bedtime (the late "go to sleep"): seated stretch -> up at the chair; walk in -> on the edge; -> lying. Its chair
    // and bed are not this room's (2.4 m apart, here 1.6 m): the first part plays at the room's chair, the page walks him
    // across, and the rest plays at the bed's edge and on the duvet, placed like room_bed_lie's
    if (got.bedtime) {
      const bt = scan(got.bedtime), up = bt.find(p => p.hips.y > 0.9 * M.k) || bt[Math.floor(bt.length / 4)];
      const e1 = bt.find(p => p.t > up.t + 2 && p.hips.y < 0.80 * M.k && p.head.y > 1.05 * M.k) || bt[Math.floor(bt.length / 2)];
      const l1 = bt.find(p => p.t > e1.t && p.head.y < 1.0 * M.k) || bt[Math.floor(bt.length * 3 / 4)];
      const sit = bt.filter(p => p.t >= e1.t && p.t <= l1.t && p.head.y > 1.3 * M.k && p.foot < 0.3), on = sit.length ? sit[sit.length >> 1] : e1;
      const s0 = bt[0], face = Math.atan2(s0.knee.z - s0.hips.z, s0.knee.x - s0.hips.x);
      const su0 = sampler(got.stand_up), h0 = su0(0).hips; su0.done();
      S.bt = {up: up.t, walk: Math.max(up.t + 0.5, e1.t - 1.6), edge: on.t, end: got.bedtime.duration,
        seat: [s0.hips.x - h0.x, s0.hips.z - h0.z], face, edgePl: edgePlace(on), lie: bedPlace(bt[bt.length - 1])};
    }
    // the get-up (room_bedtime, re-rooted as seated at the desk: see getupClips): seated (the stretch first after a long
    // sit) -> up (the hips over 0.9 m, times M.k) -> turning while he walks off over about three steps -> walking straight. Its
    // moments from the clip's own poses: the chair rolls back under him from 2.0 to 1.0 s before the hips are up (they
    // start rising at 1.1 s), his legs push it on until 0.2 s after, he turns from 0.9 s to 3.1 s after, walks by 3.7 s.
    // Two of them: as recorded (he turns to his left) and mirrored (to his right)
    if (got.getupL) {
      const W = (() => { const w = sampler(got.walk), r = []; for (let t = 0; t < got.walk.duration; t += 1 / 30) r.push(w(t)); w.done(); return r; })();
      for (const side of ["L", "R"]) {
        const s = sampler(got["getup" + side]), R = [], dt = 1 / 30; let up = null;
        for (let t = 0; t <= got.bedtime.duration; t += dt) { const p = s(t); R.push(p); if (!up && p.hips.y > 0.9 * M.k) up = t; if (up && t > up + 4.2) break; }
        s.done();
        const at = t => R[Math.min(R.length - 1, Math.round(t / dt))], d = p => p.fl - p.fr;
        // where the walk loop may take over (after two, three or four steps), each with the loop's moment whose feet match
        // the get-up's as it takes over (the foot heights and their change)
        const ends = [2.2, 2.9, 3.7].map(k => { const end = up + k, e = at(end - 0.4), slope = d(at(end - 0.4 + dt)) - d(e);
          let best = 0, bc = 1e9; W.forEach((p, i) => { const q = W[(i + 1) % W.length], c = (d(p) - d(e)) ** 2 + 9 * ((d(q) - d(p)) - slope) ** 2; if (c < bc) { bc = c; best = i; } });
          return {end, phase: best * dt}; });
        // (from the desk it starts once the seated stretch is over: 0.4 s after his hands were last over his head; the chair
        // rolls back from then on)
        let st0 = 0; R.forEach((p, k) => { if (k * dt < up && p.hand > p.head.y) st0 = k * dt + 0.4; });
        const start = Math.max(up - 2.1, Math.min(st0, up - 1.2));
        S["gu" + side] = {side, rows: R, dt, up, start, stand: up + 0.8, ride: [Math.max(up - 2.0, start), up - 1.0], push: [up - 0.9, up + 0.2],
          turn: [up + 0.9, up + 3.1], ends, end: ends[ends.length - 1].end};
      }
    }
    return S;
  }
  // a clip mirrored left <-> right (the rig is symmetric with every bone world-aligned at rest: a local turn (x, y, z, w)
  // mirrors to (x, -y, -z, w) on the other side's bone, a position's x flips)
  function mirrorClip(clip, name) {
    const B = env.bones, mir = n => { const m = /Left/.test(n) ? n.replace("Left", "Right") : /Right/.test(n) ? n.replace("Right", "Left")
      : /L$/.test(n) ? n.slice(0, -1) + "R" : /R$/.test(n) ? n.slice(0, -1) + "L" : n; return B[m] ? m : n; };
    const tracks = clip.tracks.map(tr => { const i = tr.name.lastIndexOf("."), bone = tr.name.slice(0, i), prop = tr.name.slice(i + 1), v = tr.values.slice();
      if (prop === "quaternion") for (let k = 0; k < v.length; k += 4) { v[k + 1] = -v[k + 1]; v[k + 2] = -v[k + 2]; }
      else if (prop === "position") for (let k = 0; k < v.length; k += 3) v[k] = -v[k];
      return new tr.constructor(mir(bone) + "." + prop, tr.times.slice(), v); });
    return new THREE.AnimationClip(name, clip.duration, tracks);
  }
  // a clip turned about y by r and moved by (dx, dz) in his frame (the hips carry the whole body: rest-aligned, a root bone)
  function rerootClip(clip, r, dx, dz) {
    const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), r), p = new THREE.Quaternion();
    for (const tr of clip.tracks) { const v = tr.values;
      if (tr.name === "Hips.position") for (let k = 0; k < v.length; k += 3) { const x = v[k], z = v[k + 2]; v[k] = x * Math.cos(r) + z * Math.sin(r) + dx; v[k + 2] = -x * Math.sin(r) + z * Math.cos(r) + dz; }
      else if (tr.name === "Hips.quaternion") for (let k = 0; k < v.length; k += 4) { p.fromArray(v, k).premultiply(q); p.toArray(v, k); } }
    return clip;
  }
  // the get-ups: room_bedtime as recorded and mirrored, each re-rooted so its seated pose sits where the desk clips' does
  // (facing +z, the hips over the same spot): from the desk he goes straight into it, no root jump, no turn of the frame
  const GETUP_FWD = 0.05;                                      // (its recorded chair's back was further back: his clears this one's in the stretch)
  function getupClips(got) {
    const hd = hipsAt(got.desk_watch, 0);
    for (const [side, c] of [["L", got.bedtime.clone()], ["R", mirrorClip(got.bedtime, "room_getup_R")]]) {
      c.name = "room_getup_" + side;
      const s = sampler(c); let t = 0; while (t < c.duration && s(t).hips.y <= 0.9 * M.k) t += 0.1; const p = s(Math.max(0, t - 2.1)); s.done();
      const face = Math.atan2(p.knee.z - p.hips.z, p.knee.x - p.hips.x), r = face - Math.PI / 2;
      const hx = p.hips.x * Math.cos(r) + p.hips.z * Math.sin(r), hz = -p.hips.x * Math.sin(r) + p.hips.z * Math.cos(r);
      got["getup" + side] = rerootClip(c, r, hd[0] - hx, hd[2] - hz + GETUP_FWD);
    }
  }
  function edgePlace(p) {                                    // the root that seats this pose on the room's bed edge, facing out
    const a = Math.atan2(p.knee.z - p.hips.z, p.knee.x - p.hips.x);                 // the way his knees point (local)
    const want = Math.atan2(Math.cos(BED.face), Math.sin(BED.face)), ry = a - want;
    const c = Math.cos(ry), s = Math.sin(ry), hx = p.hips.x * c + p.hips.z * s, hz = -p.hips.x * s + p.hips.z * c;
    return {ry, x: BED.edge[0] - hx, z: BED.edge[1] - hz};
  }
  // two placements blended about his hips (not the root, which sits a metre away when he lies and would swing him
  // through the bed): h is the clip's hips at this moment, in its own frame
  function mixPlace(A, B, k, h) {
    const rot = ry => { const c = Math.cos(ry), s = Math.sin(ry); return [h[0] * c + h[2] * s, -h[0] * s + h[2] * c]; };
    const ha = rot(A.ry), hb = rot(B.ry), ry = angLerp(A.ry, B.ry, k), hr = rot(ry);
    const wx = A.x + ha[0] + (B.x + hb[0] - A.x - ha[0]) * k, wz = A.z + ha[1] + (B.z + hb[1] - A.z - ha[1]) * k;
    return {ry, x: wx - hr[0], z: wz - hr[1]};
  }
  function bedPlace(p) {                                     // the root's turn and position that lay this pose on the room's bed
    const vx = p.head.x - p.hips.x, vz = p.head.z - p.hips.z, a = Math.atan2(vz, vx);
    const ry = a - (BED.head < 0 ? Math.PI : 0);             // (a local direction at angle a ends at angle a - ry in the room)
    const c = Math.cos(ry), s = Math.sin(ry), hx = p.hips.x * c + p.hips.z * s, hz = -p.hips.x * s + p.hips.z * c;
    return {ry, x: BED.hips[0] - hx, z: BED.hips[1] - hz};
  }
  async function load() {
    const got = {};
    // (the clips' folder and their fit to the body come from the page: room/mh as recorded, room/mh_v5 for v5 through char_v5.js)
    await Promise.all(Object.entries(CL).filter(([k]) => !/^type_(in|out)$/.test(k)).map(([k, f]) => env.load(`${env.clipDir || "room/mh"}/${f}.glb`).then(g => { got[k] = env.fixClip ? env.fixClip(g.animations[0]) : g.animations[0]; },
      e => { throw new Error(`${env.clipDir || "room/mh"}/${f}.glb: ${e && e.message || e}`); })));   // (which clip is missing: all are needed)
    // each desk mode its own copy of its clip, named for the mode (two modes now play one capture, room_seated_idle, and
    // the page and its tests know a desk clip by its "desk_" name, not the capture's "mixamo.com")
    for (const k of ["desk_type", "desk_mouse", "desk_watch"]) if (got[k] && !got[k].name.startsWith("desk_")) { got[k] = got[k].clone(); got[k].name = k; }
    const mixer = env.mixer, A = env.actions, H = env.HIPS;
    // the way into and out of typing (optional)
    await Promise.all(["type_in", "type_out"].filter(k => CL[k]).map(k => env.load(`${env.clipDir || "room/mh"}/${CL[k]}.glb`).then(g => { got[k] = env.fixClip ? env.fixClip(g.animations[0]) : g.animations[0]; }, () => {})));
    // the rare events at the desk (optional: the room plays on without them)
    await Promise.all(Object.entries(RARE).map(([k, f]) => env.load(`${env.clipDir || "room/mh"}/${f}.glb`).then(g => { got["rare_" + k] = env.fixClip ? env.fixClip(g.animations[0]) : g.animations[0]; }, () => {})));
    // watching "simply sits in the chair": room_seated_idle plays as recorded, feet on the floor (the old watch clip
    // propped its feet up and took the mouse clip's legs and pelvis; that swap is gone with it)
    const make = c => mixer.clipAction(c);
    M.clips = got;
    // the heights in segments() and getupClips() ("the hips over 0.9 m", the head over 1.05 m, ...) are the MakeHuman
    // body's (its hips 0.977 m up, walking): scaled to this body's by its own walking hips (v5's are about 0.87 m up, so they
    // never passed 0.9 m and the get-up from the desk started at room_bedtime's seated stretch, the arms up)
    M.k = hipsAt(got.walk, 0)[1] / 0.977;
    if (got.bedtime) getupClips(got);
    // the transitions' moments, from the clips' own poses: on the bed edge (hips low, head up), lying (head low)
    const seg = segments(got);
    M.seg = seg; M.sampler = sampler;                          // (?debug: a clip's hips, head, knees and feet at a time)
    const stand = stillClip("mh_stand", got.stand, 0), lie = stillClip("mh_lie", got.bed_lie, got.bed_lie.duration),
      edge = stillClip("mh_edge", got.bed_lie, seg.lie.edge);
    // the desk modes sit on the seat by their hips as the body has them (its own frame, as the page's rootOf turns them):
    // the legacy turn (pageHips) put a clip's forward offset on the seat sideways (room_seated_idle's 1.9 cm: its right
    // thigh against the armrest)
    const bodyHips = c => { const s = sampler(c), h = s(0).hips; s.done(); return [h.x, h.y, h.z]; };
    for (const k of ["desk_type", "desk_mouse", "desk_watch"]) { M.actions[k] = make(got[k]); H[k] = bodyHips(got[k]); }
    for (const k of ["type_in", "type_out"]) if (got[k]) { const a = M.actions[k] = make(got[k]); a.setLoop(THREE.LoopOnce, 1); a.clampWhenFinished = true; H[k] = bodyHips(got[k]); }
    M.mouseHips = H.desk_mouse;                              // (the mouse-mode body's hips at its first frame, its own frame)
    // the thumbs' hinges from the typing clip's own first frame (not from whatever pose the first ownerKeys call meets: a
    // session that starts mousing took the left thumb's plane from the mouse clip's resting hand, or mid-crossfade)
    { const s = sampler(got.desk_type); s(0); for (const sd of ["Left", "Right"]) if (S(sd, 1, 3) && env.bones[sd + "Hand"]) OT.hinge[sd] = otHinges(sd); s.done(); }
    // each rare event: its action (once, held at its end), its hips (placed on the seated loop's seat point) and how much
    // further back he and the chair go for it: how much further forward than the seated loop any part of him reaches
    // under the desk's top, plus 3 cm (reach())
    for (const k of Object.keys(RARE)) { const c = got["rare_" + k]; if (!c) continue;
      const a = M.actions["rare_" + k] = make(c); a.setLoop(THREE.LoopOnce, 1); a.clampWhenFinished = true;
      H["rare_" + k] = bodyHips(c); M.rare[k] = {pts: parts(c), dur: c.duration}; }
    M.actions.stand = make(stand); H.mh_stand = pageHips(stand, 0);
    // the walk as recorded: knees and elbows bend and the arms swing (the owner: "più liberi"); the paths keep him clear
    M.actions.walk = make(got.walk); H.room_walk = pageHips(got.walk, 0);
    M.actions.lie = make(lie); H.mh_lie = pageHips(lie, 0);
    M.actions.edge = make(edge); H.mh_edge = pageHips(edge, 0);
    for (const k of ["sit_down", "stand_up", "bed_lie", "bed_wake", "bedtime", "getupL", "getupR"]) { if (!got[k]) continue; const a = M.actions[k] = make(got[k]); a.setLoop(THREE.LoopOnce, 1); a.clampWhenFinished = true; }
    // every slot the page plays: seated at the desk -> relaxed in the chair, on the bed's edge -> the edge, standing ->
    // the stand, walking -> the walk loop (the page scales it to his speed), lying -> the lie
    const seated = ["sit", "dine", "eat", "type"], onEdge = ["edge", "phone_sit"], upright = ["idle", "stand", "lean", "deliver", "phone_stand", "door"],
      lying = ["sleep", "phone_lie", "listen", "lie_phone"];
    for (const k of seated) { A[k] = M.actions.desk_watch; H[k] = H.desk_watch.slice(); }
    // eating at the desk: room_eat (the food to his lips); the other activity clips play in the preview showcase (show())
    for (const k of ["eat", "read", "phone", "phone_scroll", "drink", "door", "window"]) { M.actions["act_" + k] = make(got[k]); H["act_" + k] = pageHips(got[k], 0); }
    for (const k of ["dine", "eat"]) { A[k] = M.actions.act_eat; H[k] = H.act_eat.slice(); }
    for (const k of onEdge) { A[k] = M.actions.edge; H[k] = H.mh_edge.slice(); }
    for (const k of upright) { A[k] = M.actions.stand; H[k] = H.mh_stand.slice(); }
    A.walk = M.actions.walk; H.walk = H.room_walk.slice(); if (env.setStride) env.setStride(WALK_V);
    for (const k of lying) { A[k] = M.actions.lie; H[k] = H.mh_lie.slice(); }
    if (seg.bt) {                                             // asleep: lying as room_bedtime ends (it is how he got there)
      const sl = stillClip("mh_sleep", got.bedtime, got.bedtime.duration); M.actions.sleep = make(sl); H.mh_sleep = pageHips(sl, 0);
      A.sleep = M.actions.sleep; H.sleep = H.mh_sleep.slice(); }
    for (let i = 0; i < 600 && !(env.chairNode && env.chairNode()); i++) await new Promise(r => setTimeout(r, 100));   // (the room may still be loading)
    { const sp = sampler(stand); M.standFeet = sp(0).feet; sp.done(); }     // (he turns on the spot about his feet, not the root)
    raiseChair(); seatHeight(); props();
    for (const a of Object.values(M.actions)) a.stop();
    mixer.stopAllAction();
    const first = A[env.state().want] || M.actions.stand; first.reset().setEffectiveWeight(1).play(); env.setCurrent(first);
    env.resnap();                                            // placed for the old clips: again, with these hips
    // where he stands to sit down and where the stand-up leaves him, from the clips: the root that puts the walk's hips on
    // the sit-down's as it starts, and the standing pose's hips on the stand-up's as it ends ([right, forward] of the seat)
    if (env.setSpots) { const sd = sampler(got.sit_down), a = sd(seg.sit.from).hips; sd.done();
      const su = sampler(got.stand_up), e = su(got.stand_up.duration).hips; su.done();
      const wk = sampler(got.walk), w0 = wk(0).hips; wk.done(); const sp = sampler(stand), s0 = sp(0).hips; sp.done();
      const sdn = seg.seatDown || SEAT.down;
      const sa = SEAT_AT.desk_watch, sx = -sa[0], sz = -sa[1];   // (the seat point, [right, forward] of the turned seat: the chair's front is its -z)
      // (he turns on the spot there before he sits: the walk loop's turning steps swing his feet, and turning closer than
      // TURN_CLEAR to the turned seat they caught its front edge; the rest of the way he goes as he sits back: transition())
      const sitF = Math.max(sz + a.z - sdn[1] - w0.z, TURN_CLEAR);
      M.spots = {sit: [sx + a.x - sdn[0] - w0.x, sitF], up: [sx + e.x - SEAT.up[0] - s0.x, sz + e.z - SEAT.up[1] - s0.z], seat: sa.slice()};
      env.setSpots(M.spots); }
    M.ready = true;
    // the desk states (by default with the mixamo character): loaded after he is ready, so they never hold him back; until
    // they are in, and if they fail, the Mixamo clips play (a clip that fails is left out)
    if (env.anim === "sova") svLoad(make, bodyHips).then(() => seatHeight(), e => { SV = null; M.sv = null; console.warn("desk states not loaded, Mixamo clips only", e); });
    if (env.anim === "sova") bedLoad(make).catch(e => { M.bed = null; console.warn("bed clips not loaded, Mixamo clips only", e); }).finally(() => { M.bedTried = true; });   // (the bed layer: bedStep())
    else M.bedTried = true;
  }
  // the page puts the root at the seat anchor less the clip's hips; the MakeHuman clips have the feet at y = 0, so the
  // seated slots' hip height is the seat anchor's height over the floor: the root (his feet) stays on the floor
  // G2's seated clips all sit on a 0.52 m seat (preview/mh-motion 4f1f995): the room's chair (seat top 0.504 m) is raised
  // 1.6 cm at the gas lift: every vertex above 0.30 m (the seat, the back, the armrests) moves up, the lift's column stretches
  // (v5 on the live room keeps the live chair: env.seatUp 0)
  const SEAT_UP = env.seatUp ?? 0.016, LIFT_CUT = 0.30;
  function raiseChair() {
    const n = env.chairNode && env.chairNode(); if (!n || n.userData.raised || !SEAT_UP) return;
    n.updateMatrixWorld(true); const v = V(), floor = env.F;
    n.traverse(o => { if (!o.isMesh) return;
      const g = o.geometry.clone(), A = g.attributes.position, f = new Float32Array(A.count * 3), inv = o.matrixWorld.clone().invert();
      for (let i = 0; i < A.count; i++) { v.fromBufferAttribute(A, i).applyMatrix4(o.matrixWorld);
        if (v.y > floor + LIFT_CUT) v.y += SEAT_UP; v.applyMatrix4(inv); f.set([v.x, v.y, v.z], 3 * i); }
      g.setAttribute("position", new THREE.BufferAttribute(f, 3)); g.computeBoundingBox(); g.computeBoundingSphere(); o.geometry = g; });
    n.userData.raised = true; if (env.chairChanged) env.chairChanged();
  }
  function seatHeight() {
    const n = env.chairNode && env.chairNode(); if (!n) return;
    const p = n.localToWorld(V(0, 0.735, 0.02)), hy = p.y - env.F, H = env.HIPS;
    for (const k of ["desk_type", "desk_mouse", "desk_watch", "type_in", "type_out", "sit", "dine", "eat", "edge", "phone_sit", "type"]) if (H[k]) H[k][1] = hy;
    if (SV) for (const k of [...SV.loops, ...Object.keys(M.rare).filter(k => M.rare[k].sv).map(k => "rare_" + k)]) H[k][1] = hy;   // (the desk states: seated as desk_watch)
  }
  // the room's keyboard and mouse: separate nodes when the room has them (G10d's), else the numbers above
  // (G10d's are top-level scene nodes: "keyboard" with its origin on the home row (the middle of F and J) on the desk
  // top, and "mouse" with its origin at its base centre on the pad, already placed next to the keyboard's right end)
  const P = {keys: ROOM.keys, ref: CLIP.kb, mouse: ROOM.mouse, pad: ROOM.pad, mouseNode: null, mouseHome: null, kbNode: null, seen: 0};
  function props(force) {
    const sc = env.scene; if (!sc || (!force && P.kbNode && P.mouseNode)) return;
    if (!P.kbNode) { const kb = sc.getObjectByName("keyboard");
      if (kb && kb.children.length) {                        // the keycaps' top from its meshes; the home row is its origin
        kb.updateMatrixWorld(true); const bb = new THREE.Box3().setFromObject(kb);
        const ry = new THREE.Euler().setFromQuaternion(kb.getWorldQuaternion(new THREE.Quaternion()), "YXZ").y;
        P.keys = {c: [kb.position.x, Math.min(bb.max.y, kb.position.y + 0.045), kb.position.z], ry, w: ROOM.keys.w, d: ROOM.keys.d};
        P.ref = CLIP.home; P.kbNode = kb; } }
    if (!P.mouseNode) { const ms = sc.getObjectByName("mouse");
      if (ms && ms.parent === sc) {                          // where G10d put it; it follows the palm while he holds it
        P.mouseNode = ms; P.mouseHome = ms.position.clone(); P.pad = ms.position.y; P.mouse = [ms.position.x, ms.position.y, ms.position.z]; } }
  }

  // ---------- the desk modes ----------
  function wanted(st) {
    const life = st.life || {}, act = life.activity;
    const seatedAtDesk = st.at === "desk" && !st.step && ["research", "chat", "chart", "watch_video", "play_chess"].includes(act);
    if (!seatedAtDesk) return null;
    const sc = life.screen || {}, kind = sc.kind || (sc.info && sc.info.kind);
    const query = (sc.search && sc.search.query) || (sc.info && sc.info.search && sc.info.search.query) || "";
    if (sc.id && sc.id !== M.lastScreen) {                  // a new screen: a search on it means he typed its query
      M.lastScreen = sc.id;
      if (act === "research" && query) M.typeUntil = st.T + Math.min(8, Math.max(4, 2.5 + 0.18 * query.length));
    }
    if (act === "watch_video" || kind === "video" || kind === "short") return "desk_watch";
    const sv = M.sv;                                         // (the desk states: he waits in the chair while the opponent thinks,
    if (sv && act === "play_chess") {                        // and looks at the board a moment before he takes the mouse)
      const c = sv.pick.chess;
      if (c && (c.done || c.turn === "opponent" || st.T - (sv.turnAt ?? -1e9) < sv.look)) return "desk_watch";   // (the game over: he sits back)
    }
    if (act === "research" && st.T < M.typeUntil) return "desk_type";
    return "desk_mouse";
  }
  function setMode(m) {
    if (m === M.mode) return;
    const a = M.actions[m], cur = env.state().current, L = env.links || {};
    // into or out of typing by its own clips when the character has them (Sit_To_Type, Type_To_Sit): the link plays once,
    // then hands over to the mode's loop (link())
    const via = m === "desk_type" ? M.actions.type_in : M.mode === "desk_type" ? M.actions.type_out : null;
    if (via && cur !== via) {
      const fin = via === M.actions.type_in ? (M.mode === "desk_watch" ? L.fromWatch : L.in) : L.out, fout = via === M.actions.type_in ? L.out : (m === "desk_watch" ? L.toWatch : FADE);
      via.reset(); via.setEffectiveWeight(1); via.fadeIn(fin || FADE).play(); if (cur) cur.fadeOut(fin || FADE); env.setCurrent(via);
      M.link = {a: via, to: a, fade: fout || FADE};
    } else if (a !== cur) { M.link = null; a.reset(); a.setEffectiveWeight(1); a.fadeIn(FADE).play(); if (cur) cur.fadeOut(FADE); env.setCurrent(a); }
    for (const k of ["sit", "type"]) env.actions[k] = a;   // the page's own play("sit") then keeps this mode
    M.mode = m; M.log.push([+env.state().T.toFixed(2), m]); if (M.log.length > 50) M.log.shift();
  }

  function link() {                                           // a link's end: on into the mode's loop
    const L = M.link; if (!L) return;
    if (L.a.time >= L.a.getClip().duration - L.fade) { L.to.reset(); L.to.setEffectiveWeight(1); L.to.fadeIn(L.fade).play(); L.a.fadeOut(L.fade); env.setCurrent(L.to); M.link = null; }
  }
  // ---------- re-pinning the wrists (the arm's two bones turn; the wrist and the fingers keep the clip) ----------
  const _a = V(), _b = V(), _u = V(), _v = V(), _q = new THREE.Quaternion(), _pq = new THREE.Quaternion(), _wq = new THREE.Quaternion();
  const toWorld = (p, out) => env.boy.localToWorld(out.set(p[0], p[1], p[2] + M.zoff));   // the clip's frame -> the room
  function ccd(side, target, weight) {                       // move the wrist to target: forearm, then upper arm
    const B = env.bones, hand = B[side + "Hand"], chain = [B[side + "ForeArm"], B[side + "Arm"]];
    if (!hand || !chain[0] || !chain[1] || weight <= 0) return;
    for (let it = 0; it < 6; it++) for (const bone of chain) {
      bone.getWorldPosition(_a); hand.getWorldPosition(_b);
      _u.subVectors(_b, _a).normalize(); _v.subVectors(target, _a).normalize();
      if (_u.dot(_v) > 0.99999) continue;
      _q.setFromUnitVectors(_u, _v); _q.slerp(_ID, 1 - weight);
      bone.parent.getWorldQuaternion(_pq);
      bone.quaternion.copy(_pq.invert().multiply(bone.getWorldQuaternion(_wq).premultiply(_q)));
      bone.updateMatrixWorld(true);
    }
  }
  // the elbow swung about the shoulder-wrist line onto the side of that line where e (world) is: the wrist stays put.
  // After ccd() the elbow is wherever six passes left it, ill-conditioned with the arm near straight: in steady typing it
  // leapt up to 22 cm in a frame while the wrist moved 5 mm. Its reference (elbowRef) is last frame's elbow drawn over
  // 0.5 s toward the clip's: the clip's alone is no reference, its typing arm is near straight (the elbow 8 mm off the
  // shoulder-wrist line), so the side it lies on turned round from frame to frame.
  const ELB = {Left: null, Right: null}, ELB_REF = {Left: null, Right: null}; let elbFrame = 0, elbSeen = {Left: -9, Right: -9};
  const _elb = {Left: V(), Right: V()}, _elbRef = {Left: V(), Right: V()};   // (their own vectors, written in place: a frame's elbow and its reference)
  function elbowRef(dt) {                                    // once a frame, before any arm is placed
    elbFrame++;
    for (const side of ["Left", "Right"]) { const fa = env.bones[side + "ForeArm"]; if (!fa) continue; const c = fa.getWorldPosition(_a);
      ELB_REF[side] = ELB[side] && elbSeen[side] === elbFrame - 1 ? _elbRef[side].copy(ELB[side]).lerp(c, 1 - Math.exp(-dt / 0.5)) : _elbRef[side].copy(c); }
  }
  function elbowKeep() {                                     // once a frame, after the arms are placed
    for (const side of ["Left", "Right"]) { const fa = env.bones[side + "ForeArm"]; if (fa) { ELB[side] = fa.getWorldPosition(_elb[side]); elbSeen[side] = elbFrame; } }
  }
  const _vsh = V(), _vax = V(), _ve0 = V(), _ve1 = V(), _vx = V(), _vpq = new THREE.Quaternion(), _vw0 = new THREE.Quaternion(), _vr = new THREE.Quaternion();
  function swivelTo(side, e, weight = 1) {
    const B = env.bones, ua = B[side + "Arm"], fa = B[side + "ForeArm"], hand = B[side + "Hand"]; if (!ua || !fa || !hand) return;
    const sh = ua.getWorldPosition(_vsh), ax = hand.getWorldPosition(_vax).sub(sh); if (ax.lengthSq() < 1e-8) return; ax.normalize();
    const e0 = fa.getWorldPosition(_ve0).sub(sh), e1 = _ve1.copy(e).sub(sh); e0.addScaledVector(ax, -e0.dot(ax)); e1.addScaledVector(ax, -e1.dot(ax));
    if (e0.lengthSq() < 1e-8 || e1.lengthSq() < 1e-8) return;
    const a = Math.atan2(_vx.copy(e0).cross(e1).dot(ax), e0.dot(e1)) * weight;
    const pq = ua.parent.getWorldQuaternion(_vpq).invert(), w0 = ua.getWorldQuaternion(_vw0);
    ua.quaternion.copy(pq.multiply(_vr.setFromAxisAngle(ax, a).multiply(w0))); ua.updateMatrixWorld(true);
  }
  const tipNames = side => [1, 2, 3, 4, 5].map(f => env.bones[`finger${f}-3${side === "Left" ? "L" : "R"}`] || env.bones[`finger${f}-3.${side === "Left" ? "L" : "R"}`]).filter(Boolean);
  function lowestTip(side) {                                // the lowest fingertip: the end bone's head, a finger's half thickness lower
    let low = 1e9; for (const b of tipNames(side)) { b.getWorldPosition(_a); low = Math.min(low, _a.y - 0.008); } return low;
  }
  // ---------- contact: his hand settled ONTO a named surface, not kept clear of it ----------
  // The owner: "the right hand must hold the mouse"; then (G12) on the keys his fingertips hovered 0.5-1.1 cm over the caps
  // for the whole clip: the old rules only ever lifted the hand out of things. One resolver, two callers:
  //   mouse: the palm on the shell's hump, the fingers along it, the thumb on its left flank (references mouse1, mouse2);
  //   keys:  the index fingertips over F and J, the knuckles 3 cm over the caps, every finger laid onto the keycaps (kb1, kb2).
  // For both, per frame: the hand is placed by a point of the hand itself (never a clip reference: that put the palm 5 cm
  // short of the mouse and the fingertips past the keyboard's far edge); the whole arm turns to get the wrist there (the
  // upper arm at the shoulder, the forearm at the elbow; the wrist keeps the clip's turn); the elbow swings about the
  // shoulder-wrist line until forearm and upper arm are out of the desk (the room's own solid, as the page QA tests it);
  // then each finger is bent down joint by joint until it touches what is under it: contact, the surface the hard limit.
  // Half thicknesses (measured off his skin): palm 16 mm below the bones' line, knuckles 11, fingers 10; the arm and the
  // last two phalanges are tested by their own skin.
  const PALM_R = 0.016, KN_R = 0.011, FING_R = 0.010;
  const GRIP_BACK = 0.022;                       // mouse: the palm 2.2 cm behind the hump's top; across, where his thumb lies on the
                                                 // left flank (mouseFit)
  const KEY_KNUCKLE = 0.030, FJ = 0.0285;        // keys: knuckles 3 cm over the caps; F and J 1.5 keys either side of the
                                                 // keyboard's origin (G10d's: the middle of F and J)
  // (a finger bone by side, finger, joint, looked up once: S() built two names a call, thousands of times a frame)
  const SB = new Map();
  const S = (side, i, j) => { const k = (side[0] === "L" ? 0 : 100) + i * 10 + j; let b = SB.get(k);
    if (b === undefined) { b = env.bones[`finger${i}-${j}${side[0]}`] || env.bones[`finger${i}-${j}.${side[0]}`] || null; SB.set(k, b); } return b || undefined; };
  // his forward in the room: one vector, kept while his turn is the same; read-only to its callers (deskV copies it)
  const _fw = V(); let _fwRy = null;
  const fwdV = () => { const ry = env.boy.rotation.y; if (ry !== _fwRy) { _fwRy = ry; _fw.set(Math.sin(ry), 0, Math.cos(ry)); } return _fw; };
  const _l = V(), _p = V(), _n = V(), _s = V(), _e = V(), _g = V(), _sd = V(), _ax = V(), _up1 = V(0, 1, 0), _dn2 = V(0, -1, 0), _zero = V();
  const _q0 = new THREE.Quaternion(), _rq = new THREE.Quaternion(), _rq2 = new THREE.Quaternion(), _ID = new THREE.Quaternion();   // (_ID: the identity, slerp's far end; never written)

  // a surface's top as a height map in the node's own frame (2.5 mm): the highest hit of a vertical ray (keycaps, the shell)
  const MAPS = new Map();
  function topMap(node) {
    if (MAPS.has(node)) return MAPS.get(node);
    node.updateMatrixWorld(true); const meshes = []; node.traverse(m => { if (m.isMesh && !/_contact$/.test(m.name)) meshes.push(m); });
    const inv = node.matrixWorld.clone().invert(), bb = new THREE.Box3(), v = V();
    for (const m of meshes) { const P = m.geometry.attributes.position; m.updateMatrixWorld(true); for (let i = 0; i < P.count; i++) bb.expandByPoint(v.fromBufferAttribute(P, i).applyMatrix4(m.matrixWorld).applyMatrix4(inv)); }
    const s = 0.0025, nx = Math.ceil((bb.max.x - bb.min.x) / s) + 1, nz = Math.ceil((bb.max.z - bb.min.z) / s) + 1, h = new Float32Array(nx * nz).fill(NaN);
    const ray = new THREE.Raycaster(), o = V(), dn = V(0, -1, 0); let peak = -1e9; const pk = V();
    for (let i = 0; i < nx; i++) for (let k = 0; k < nz; k++) {
      const lx = bb.min.x + i * s, lz = bb.min.z + k * s; node.localToWorld(o.set(lx, bb.max.y + 0.1, lz)); ray.set(o, dn);
      const x = ray.intersectObjects(meshes, false)[0]; if (!x) continue;
      const ly = x.point.clone().applyMatrix4(inv).y; h[i * nz + k] = ly; if (ly > peak) { peak = ly; pk.set(lx, ly, lz); } }
    const m = {node, x0: bb.min.x, z0: bb.min.z, s, nx, nz, h, peak: pk}; MAPS.set(node, m); return m;
  }
  function topAt(m, p) {                                     // the surface's top under p (world y), null off it
    // (the highest of the cell and its 8 neighbours: next to a step, a keycap's side, the nearest cell alone could read the
    // lower level and let a fingertip 5 mm into the cap's edge)
    m.node.worldToLocal(_l.copy(p)); const i0 = Math.round((_l.x - m.x0) / m.s), k0 = Math.round((_l.z - m.z0) / m.s);
    let y = -Infinity;
    for (let i = i0 - 1; i <= i0 + 1; i++) for (let k = k0 - 1; k <= k0 + 1; k++) { if (i < 0 || k < 0 || i >= m.nx || k >= m.nz) continue; const h = m.h[i * m.nz + k]; if (!Number.isNaN(h) && h > y) y = h; }
    if (y === -Infinity) return null;
    return m.node.localToWorld(_l.set(_l.x, y, _l.z)).y;
  }
  const SURF = {mouse: () => P.mouseNode, keys: () => P.kbNode};
  function under(name, p) { const n = SURF[name](); const y = n ? topAt(topMap(n), p) : null; return y == null ? P.pad : y; }   // the surface, else the pad / desk top

  // the desk: the room's static mesh over the desk's zone, its top (the highest face between 0.90 and 1.00 m, 1 cm cells)
  // taken as a 3 cm slab: the room draws the desk as a 3 mm skin, which no inside-test can see a forearm in
  let DESK = null;
  function deskCols() {
    if (DESK !== null) return DESK;
    const st = env.scene && env.scene.getObjectByName("room_static"); if (!st) return (DESK = false);
    const meshes = []; st.traverse(m => { if (m.isMesh) meshes.push(m); });
    for (const m of meshes) if (m.geometry.computeBoundsTree && !m.geometry.boundsTree) m.geometry.computeBoundsTree();   // (a cut drops a mesh's tree: 12 000 rays without one took seconds)
    const sides = meshes.map(m => m.material.side); meshes.forEach(m => { m.material.side = THREE.DoubleSide; });
    const x0 = -1.92, x1 = -0.30, z0 = -1.47, z1 = -0.72, c = 0.01, nx = Math.ceil((x1 - x0) / c), nz = Math.ceil((z1 - z0) / c), tops = new Float32Array(nx * nz).fill(NaN);
    const ray = new THREE.Raycaster(), o = V(), up = V(0, 1, 0);
    for (let i = 0; i < nx; i++) for (let k = 0; k < nz; k++) {
      ray.set(o.set(x0 + (i + 0.5) * c, 0.5, z0 + (k + 0.5) * c), up); ray.far = 0.7; let t = NaN;
      for (const h of ray.intersectObjects(meshes, false)) if (h.point.y > 0.90 && h.point.y < 1.00) t = Number.isNaN(t) ? h.point.y : Math.max(t, h.point.y);
      tops[i * nz + k] = t; }
    meshes.forEach((m, i) => { m.material.side = sides[i]; });
    return (DESK = {x0, z0, c, nx, nz, tops});
  }
  const DESK_SLAB = 0.03;
  function inDesk(p) {                                       // how deep a world point is inside the desk's slab (m), 0 outside
    const D = deskCols(); if (!D) return 0; const i = Math.floor((p.x - D.x0) / D.c), k = Math.floor((p.z - D.z0) / D.c);
    if (i < 0 || k < 0 || i >= D.nx || k >= D.nz) return 0; let t = D.tops[i * D.nz + k]; if (Number.isNaN(t)) return 0; t += M.deskTest || 0;   // (?debug: the slab raised, to see the swing work)
    return p.y < t && p.y > t - DESK_SLAB ? Math.min(t - p.y, p.y - (t - DESK_SLAB)) : 0;
  }
  const ARM = {};
  function armIn(side) {                                     // the deepest point of his arm's skin (sleeve included, up to 120 vertices) in the desk
    if (!ARM[side]) { const bs = new Set(), hand = env.bones[side + "Hand"];   // (every bone of the arm but the hand's: the skin hangs on its twist bones)
      env.bones[side + "Arm"].traverse(b => { if (!b.isBone) return; let n = b; while (n && n !== hand) n = n.parent; if (!n) bs.add(b); }); const all = [];
      env.boy.traverse(o => { if (!o.isSkinnedMesh || /_inside$/.test(o.name)) return; const I = o.geometry.attributes.skinIndex, W = o.geometry.attributes.skinWeight;
        for (let n = 0; n < I.count; n++) { let k0 = 0, w0 = 0; for (let c = 0; c < 4; c++) if (W.getComponent(n, c) > w0) { w0 = W.getComponent(n, c); k0 = I.getComponent(n, c); } if (bs.has(o.skeleton.bones[k0])) all.push([o, n]); } });
      const st = Math.max(1, Math.ceil(all.length / 120)); ARM[side] = all.filter((_, n) => n % st === 0); }
    let d = 0; for (const [o, n] of ARM[side]) { o.getVertexPosition(n, _g).applyMatrix4(o.matrixWorld); d = Math.max(d, inDesk(_g)); }
    return d;
  }
  // seated at the desk and not on the keys or the mouse (riding the chair in, watching, eating): an arm whose skin (or its
  // hand's) is in the desk's slab is swung about the shoulder by the least angle that takes it out (3 mm of slack).
  // The clips put a forearm on the desk 1.2-1.8 cm too low (walking_8: riding in, 100 sampled vertices up to 18 mm under
  // its top) - unseen until the room's raycasts saw the whole desk again
  M.clear = {frames: 0, maxIn: 0, maxA: 0};                 // (?debug)
  const HANDSKIN = {};
  function handIn(side) {                                    // the deepest point of his hand's skin (palm and fingers, up to 120 vertices) in the desk
    if (!HANDSKIN[side]) { const bs = new Set(); env.bones[side + "Hand"].traverse(b => { if (b.isBone) bs.add(b); }); const all = [];
      env.boy.traverse(o => { if (!o.isSkinnedMesh || /_inside$/.test(o.name)) return; const I = o.geometry.attributes.skinIndex, W = o.geometry.attributes.skinWeight;
        for (let n = 0; n < I.count; n++) { let k0 = 0, w0 = 0; for (let c = 0; c < 4; c++) if (W.getComponent(n, c) > w0) { w0 = W.getComponent(n, c); k0 = I.getComponent(n, c); } if (bs.has(o.skeleton.bones[k0])) all.push([o, n]); } });
      const st = Math.max(1, Math.ceil(all.length / 120)); HANDSKIN[side] = all.filter((_, n) => n % st === 0); }
    let d = 0; for (const [o, n] of HANDSKIN[side]) { o.getVertexPosition(n, _g).applyMatrix4(o.matrixWorld); d = Math.max(d, inDesk(_g)); }
    return d;
  }
  // (eased, preview/freeze-why-ease: the swing keeps last frame's way while that way still clears - the least angle
  // over all four flipped from 6 deg back to 7 deg forward in one frame mid-crossfade, a fingertip 147 mm - and it lets
  // go over ~0.25 s instead of at once; it still comes in at once, so no skin stays in the desk)
  const CLR = {Left: null, Right: null}, CLR_OUT = 0.09, CLR_SLACK = 0.008, CLR_TURN = 0.12;   // (s: the release's time constant, ~0.25 s to nothing; m: in the slab while letting go; s: a change of way)
  const WLIFT = {}, WLIFT_STEP = 0.04;                        // (weighted(): the wrist's lift over the desk, m, and its most per frame)
  const _dpq = new THREE.Quaternion(), _dw0 = new THREE.Quaternion(), _dlat = V(), _daxes = {lat: _dlat, fwd: null};
  function deskClear(side, dt = 1 / 30) {
    const ua = env.bones[side + "Arm"]; if (!ua || !env.bones[side + "Hand"] || M.noClear) return;   // (?debug: M.noClear)
    const inn = () => Math.max(armIn(side), handIn(side)), d0 = inn();
    const pq = ua.parent.getWorldQuaternion(_dpq).invert(), w0 = ua.getWorldQuaternion(_dw0);
    const f = fwdV(), lat = _dlat.crossVectors(f, _up1).normalize(), MAX = 25 * Math.PI / 180;
    const axes = _daxes; axes.fwd = f;
    const set = (ax, a) => { ua.quaternion.copy(pq).multiply(_rq.setFromAxisAngle(ax, a).multiply(w0)); ua.updateMatrixWorld(true); };
    const least = (k, sg) => { const ax = axes[k]; set(ax, sg * MAX); if (inn() > 0.003) return null;   // (the least angle that way that clears; none within 25 deg)
      let lo = 0, hi = MAX; for (let it = 0; it < 8; it++) { const m = (lo + hi) / 2; set(ax, sg * m); if (inn() > 0.003) lo = m; else hi = m; } return hi; };
    const prev = CLR[side], fade = prev ? prev.a * Math.exp(-dt / CLR_OUT) : 0;
    let best = null;
    if (d0 > 0.003) {
      M.clear.frames++; M.clear.maxIn = Math.max(M.clear.maxIn, d0);
      // the whole arm swung about the shoulder - back or forward (his left-right axis), out or in (his forward axis) - by
      // the least angle that takes its skin and the hand's out: last frame's way if it still can, else the least of all four
      if (prev) { const a = least(prev.k, prev.sg); if (a != null) best = {k: prev.k, sg: prev.sg, a}; }
      if (!best) for (const k of ["lat", "fwd"]) for (const sg of [1, -1]) { const a = least(k, sg); if (a != null && (!best || a < best.a)) best = {k, sg, a}; }
      if (best && prev && best.k === prev.k && best.sg === prev.sg) best.a = Math.max(best.a, fade);   // (never less than the release allows)
    } else if (prev && fade > 0.003) {                       // out of the desk: the swing lets go gradually - as much of it as keeps him out
      set(axes[prev.k], prev.sg * fade);                     // (the clip's arm has moved on: the old way may now push it in. Letting go,
      // up to 8 mm of the slab is allowed - the desk's check counts skin more than 1 cm in - for the way back to the clip's
      // arm can pass the desk's edge: held to 3 mm, an 18 deg swing dropped at once, a fingertip 175-195 mm in a frame)
      let a = fade; if (inn() > CLR_SLACK) { let lo = 0, hi = fade; for (let it = 0; it < 6; it++) { const m = (lo + hi) / 2; set(axes[prev.k], prev.sg * m); if (inn() > CLR_SLACK) hi = m; else lo = m; } a = lo; }
      if (a > 0.003) best = {k: prev.k, sg: prev.sg, a};
    }
    // a change of way (the last way no longer clears): the old swing hands over to the new one over CLR_TURN instead of
    // at once (walking_8, riding in: back 21 deg to forward 22 deg in a frame, the left fingertip 378 mm); a little skin
    // may stay in the slab for those frames
    if (best && prev && (best.k !== prev.k || best.sg !== prev.sg)) { best.from = prev.from && prev.r < 1 ? prev.from : {k: prev.k, sg: prev.sg, a: prev.a}; best.r = 0; }
    else if (best && prev && prev.from) { best.from = prev.from; best.r = prev.r; }
    if (best && best.from) { best.r = Math.min(1, best.r + dt / CLR_TURN); const r = best.r * best.r * (3 - 2 * best.r);
      ua.quaternion.copy(pq).multiply(_rq.setFromAxisAngle(axes[best.k], best.sg * best.a * r).multiply(_rq2.setFromAxisAngle(axes[best.from.k], best.from.sg * best.from.a * (1 - r))).multiply(w0));
      ua.updateMatrixWorld(true); if (best.r >= 1) best.from = null; }
    else if (best) set(axes[best.k], best.sg * best.a);
    else set(lat, 0);
    if (best) M.clear.maxA = Math.max(M.clear.maxA || 0, best.a);
    CLR[side] = best;
    if (M.clearLog) M.clearLog.push([side, +d0.toFixed(4), best ? best.k + (best.sg > 0 ? "+" : "-") : "none", best ? +(best.a * 57.3).toFixed(1) : 0]);   // (?debug)
  }
  // eating at the desk (room_eat): the clip's reach for a bite goes 0.44 m out from the shoulder, 30 cm past the dish
  // and up into the monitor (eating_19: 774 sampled vertices of the right hand inside it). While the clip's hand is out
  // ahead of him (0.26 -> 0.40 m), it is taken to just over the dish instead; to the mouth and back the clip is as it was
  // ... the share follows the clip at most 1 / 0.5 s, and the hand goes to a point between the clip's and the dish's,
  // pinned at full weight (pin() is not linear in its weight: weighted, it leapt 20 cm in a frame as the share fell)
  // the keys or the mouse taking over (their weight past 0.01) while an arm was swung out of the desk: the swing fades
  // (~0.4 s) on top of the hands' solve instead of going at once (walking_8: sitting down, then the mouse - the left
  // fingertip moved 188 mm in a frame as the swing went)
  function clearRelease(side, dt) {
    const p = CLR[side], ua = env.bones[side + "Arm"]; if (!p || !ua) return;
    const a = p.a * Math.exp(-dt / 0.15); if (a < 0.003) { CLR[side] = null; return; }
    const f = fwdV(), ax = p.k === "lat" ? _dlat.crossVectors(f, _up1).normalize() : f;
    const pq = ua.parent.getWorldQuaternion(_dpq).invert(), w0 = ua.getWorldQuaternion(_dw0);
    ua.quaternion.copy(pq).multiply(_rq.setFromAxisAngle(ax, p.sg * a).multiply(w0)); ua.updateMatrixWorld(true);
    CLR[side] = {k: p.k, sg: p.sg, a};
  }
  M.eatReach = 0;                                            // (?debug: the share)
  function eatReach(st, dt) {
    const B = env.bones, eating = !!env.DISH_AT && st.at === "desk" && st.current === M.actions.act_eat;
    const sh = B.RightArm && B.RightArm.getWorldPosition(V()), hand = B.RightHand && B.RightHand.getWorldPosition(V()); if (!sh || !hand) return;
    const f = fwdV(), ext = hand.clone().sub(sh).dot(f), u = Math.min(1, Math.max(0, (ext - 0.26) / 0.14)), want = eating ? u * u * (3 - 2 * u) : 0;
    M.eatReach += Math.max(-dt / 0.5, Math.min(dt / 0.5, want - M.eatReach)); if (M.eatReach < 1e-3) { M.eatReach = 0; return; }
    const tgt = V().copy(env.DISH_AT).add(V(0, 0.10, 0)).addScaledVector(f, -0.05);   // (10 cm over the dish, its near side)
    pin("Right", tgt.sub(hand).multiplyScalar(M.eatReach), 1, null, {iters: 4});
  }
  const FORE = {};
  function foreIn(side) {                                    // armIn() on the forearm's skin alone (120 vertices there, not spread over the upper arm,
    if (!FORE[side]) { const bs = new Set(), hand = env.bones[side + "Hand"];   // whose samples missed forearm skin 1 cm in the desk's edge over the mouse)
      env.bones[side + "ForeArm"].traverse(b => { if (!b.isBone) return; let n = b; while (n && n !== hand) n = n.parent; if (!n) bs.add(b); }); const all = [];
      env.boy.traverse(o => { if (!o.isSkinnedMesh || /_inside$/.test(o.name)) return; const I = o.geometry.attributes.skinIndex, W = o.geometry.attributes.skinWeight;
        for (let n = 0; n < I.count; n++) { let k0 = 0, w0 = 0; for (let c = 0; c < 4; c++) if (W.getComponent(n, c) > w0) { w0 = W.getComponent(n, c); k0 = I.getComponent(n, c); } if (bs.has(o.skeleton.bones[k0])) all.push([o, n]); } });
      const st = Math.max(1, Math.ceil(all.length / 120)); FORE[side] = all.filter((_, n) => n % st === 0); }
    let d = 0; for (const [o, n] of FORE[side]) { o.getVertexPosition(n, _g).applyMatrix4(o.matrixWorld); d = Math.max(d, inDesk(_g)); }
    return d;
  }
  M.swing = {frames: 0, maxIn: 0, maxA: 0};                 // (?debug: how often and how far the elbow had to swing)
  const _ssh = V(), _sax = V(), _spq = new THREE.Quaternion(), _sw0 = new THREE.Quaternion();
  function swingElbow(side, weight) {                        // the elbow up about the shoulder-wrist line until the arm is out of the desk
    M.swingNow = M.swingNow || {}; M.swingNow[side] = 0;   // (?debug: this frame's swing, rad)
    const d0 = armIn(side); if (d0 <= 0.003) return; M.swing.frames++; M.swing.maxIn = Math.max(M.swing.maxIn, d0);
    const B = env.bones, ua = B[side + "Arm"], sh = ua.getWorldPosition(_ssh), axis = B[side + "Hand"].getWorldPosition(_sax).sub(sh).normalize();
    const pq = ua.parent.getWorldQuaternion(_spq).invert(), w0 = ua.getWorldQuaternion(_sw0);
    const set = a => { ua.quaternion.copy(pq).multiply(_rq.setFromAxisAngle(axis, a).multiply(w0)); ua.updateMatrixWorld(true); };
    const elbowY = a => { set(a); return B[side + "ForeArm"].getWorldPosition(_g).y; };
    const sgn = elbowY(0.1) > elbowY(-0.1) ? 1 : -1;        // (the way that lifts the elbow)
    let lo = 0, hi = 0.26 * sgn; set(hi);                  // (at most 15 deg: past that the shoulder reads as hunched)
    if (armIn(side) > 0.003) { set(hi * weight); M.swingNow[side] = Math.abs(hi); return; }
    for (let it = 0; it < 10; it++) { const m = (lo + hi) / 2; set(m); if (armIn(side) > 0.003) lo = m; else hi = m; }
    set(hi * weight); M.swing.maxA = Math.max(M.swing.maxA, Math.abs(hi)); M.swingNow[side] = Math.max(M.swingNow[side], Math.abs(hi));
  }

  // (pin's own vectors and turns, written in place - it ran ~20 allocations an iteration, 5-6 iterations a hand a solve; pin
  // never nests: fit(), aim() and post() place fingers and read the hand, they do not pin)
  const _pw0 = V(), _pt = V(), _pe0 = V(), _kwr = V(), _kh = V(), _kl = V(), _kax = V(), _klt = V(), _bx = V(), _by = V(), _bz = V(), _bm = new THREE.Matrix4();
  const _pq0 = new THREE.Quaternion(), _kpq = new THREE.Quaternion(), _kq = new THREE.Quaternion(), _kq2 = new THREE.Quaternion(), _kr = new THREE.Quaternion(), _kR = new THREE.Quaternion(), _kR2 = new THREE.Quaternion(), _puq = new THREE.Quaternion();
  function pin(side, delta, weight, fit, o = {}) {           // the recorded wrist + delta, the arm turned to it, then fit()'s corrections
    const hand = env.bones[side + "Hand"]; if (!hand || weight <= 0) return;
    const w0 = hand.getWorldPosition(_pw0), t = _pt.copy(w0).add(delta), q0 = hand.getWorldQuaternion(_pq0);   // (the clip's hand turn)
    const fa = env.bones[side + "ForeArm"], e0 = ELB_REF[side] || (fa ? fa.getWorldPosition(_pe0) : null);   // (see swivelTo)
    const basis = (a, b, out) => { const x = _bx.copy(a).normalize(), z = _bz.copy(x).cross(b).normalize(), y = _by.copy(z).cross(x); return out.setFromRotationMatrix(_bm.makeBasis(x, y, z)); };
    const keepTurn = () => { const pq = hand.parent.getWorldQuaternion(_kpq).invert(), q = _kq.copy(q0);
      if (o.pitch && !o.aim) { const h = S(side, 3, 1).getWorldPosition(_kh).sub(hand.getWorldPosition(_kwr)), ax = _kax.copy(h).cross(_dn2).normalize(); q.premultiply(_kr.setFromAxisAngle(ax, o.pitch())); }   // (o.pitch(): + = fingers down, about the wrist)
      if (o.roll && !o.aim) { const h = S(side, 3, 1).getWorldPosition(_kh).sub(hand.getWorldPosition(_kwr)).normalize(), f = fwdV(), lt = _klt.set(f.z, 0, -f.x), sg = _kax.copy(h).cross(lt).y > 0 ? 1 : -1;
        q.premultiply(_kr.setFromAxisAngle(h, sg * o.roll * Math.PI / 180)); }   // (o.roll: deg, his left side of the hand up)
      hand.quaternion.slerp(pq.multiply(q), weight); hand.updateMatrixWorld(true);
      if (o.aim) {                                         // (o.aim(): [forward, right] the hand should point: wrist->middle knuckle, index->little knuckle)
        const [hw, lw] = o.aim(), wr = hand.getWorldPosition(_kwr), h = S(side, 3, 1).getWorldPosition(_kh).sub(wr).normalize(), l = S(side, 5, 1).getWorldPosition(_kl).sub(S(side, 2, 1).getWorldPosition(_kax));
        const R = basis(hw, lw, _kR).multiply(basis(h, l, _kR2).invert()), pq2 = hand.parent.getWorldQuaternion(_kpq).invert();
        hand.quaternion.copy(pq2.multiply(hand.getWorldQuaternion(_kq).premultiply(R.slerp(_ID, 1 - weight)))); hand.updateMatrixWorld(true);
        if (o.pitch || o.roll) { const q2 = hand.getWorldQuaternion(_kq2);   // (the tilt and the roll on top of the aim)
          if (o.pitch) { const h2 = S(side, 3, 1).getWorldPosition(_kh).sub(hand.getWorldPosition(_kwr)), ax = _kax.copy(h2).cross(_dn2).normalize(); q2.premultiply(_kr.setFromAxisAngle(ax, o.pitch() * weight)); }
          if (o.roll) { const h2 = S(side, 3, 1).getWorldPosition(_kh).sub(hand.getWorldPosition(_kwr)).normalize(), f = fwdV(), lt = _klt.set(f.z, 0, -f.x), sg = _kax.copy(h2).cross(lt).y > 0 ? 1 : -1; q2.premultiply(_kr.setFromAxisAngle(h2, sg * o.roll * Math.PI / 180 * weight)); }
          hand.quaternion.copy(hand.parent.getWorldQuaternion(_kpq).invert().multiply(q2)); hand.updateMatrixWorld(true); }
      }
      if (o.post) o.post(); };
    for (let it = 0; it < (o.iters || 5); it++) {
      ccd(side, t, weight); swingElbow(side, weight); keepTurn();
      const d = fit ? fit() : _zero; if (d.length() <= 0.001 && !o.iters) break; t.addScaledVector(d, weight);
    }
    if (e0) {                                                // (once the wrist is placed)
      // the elbow towards its reference, as far as the desk allows: on the mouse, where the full swing left the forearm in
      // the desk's edge (the 15 deg elbow lift could not clear it), only the share that keeps it out
      const ua = env.bones[side + "Arm"], q = _puq.copy(ua.quaternion), go = k => { ua.quaternion.copy(q); ua.updateMatrixWorld(true); if (k > 0) swivelTo(side, e0, weight * k); swingElbow(side, weight); };
      swivelTo(side, e0, weight); swingElbow(side, weight);   // (the whole swing, as before)
      // (on the mouse only: typing, both forearms rest on the desk's edge and capping there moved the left hand's fit, 80%
      // of resting tips on their caps against 81%)
      if (M.w.mouse > 0.5 && foreIn(side) > 0.003) { let lo = 0, hi = 1; for (let it = 0; it < 6; it++) { const m = (lo + hi) / 2; go(m); if (foreIn(side) > 0.003) hi = m; else lo = m; } go(lo); }
      keepTurn();
    }
  }
  const palmAt = (side, out) => env.bones[side + "Hand"].getWorldPosition(out).lerp(S(side, 3, 1).getWorldPosition(_e), 0.6);
  function knuckleNeed(side, name) { let dy = -1; for (let i = 2; i <= 5; i++) { const k = S(side, i, 1); if (!k) continue; k.getWorldPosition(_s); dy = Math.max(dy, under(name, _s) + KN_R - _s.y); } return dy; }
  const tipSkin = (side, name, i) => { let low = 1e9; for (const [o, n] of skinOf(side, i, 3)) { o.getVertexPosition(n, _p).applyMatrix4(o.matrixWorld); low = Math.min(low, _p.y - under(name, _p)); } return low; };
  const _cwr = V(), _ck2 = V(), _ck3 = V(), _ck5 = V(), _ch = V(), _cl = V(), _cn = V(), _cd0 = V(), _cax = V(), _cw = V();   // (curl's: it runs inside every finger search, ~20 allocations a call before)
  function curl(side, G, weight) {                           // each finger set to G's bends in the hand's own frame (absolute: they never add up)
    if (!env.bones[side + "Hand"] || !S(side, 2, 1) || !S(side, 3, 1) || !S(side, 5, 1)) return;   // (another rig: degrade, never throw)
    const hand = env.bones[side + "Hand"], wr = hand.getWorldPosition(_cwr), k2 = S(side, 2, 1).getWorldPosition(_ck2), k3 = S(side, 3, 1).getWorldPosition(_ck3), k5 = S(side, 5, 1).getWorldPosition(_ck5);
    const h = _ch.copy(k3).sub(wr).normalize(), l = _cl.copy(k5).sub(k2); l.addScaledVector(h, -l.dot(h)).normalize();
    let n = _cn.copy(h).cross(l).normalize(); if (n.y > 0) n.negate();   // (the palm's side: down)
    for (const i of [2, 3, 4, 5]) { const g = G[i]; if (!g || !S(side, i, 1)) continue;
      const a = g[3] * Math.PI / 180, out = i === 2 ? -1 : 1;   // (the index lies on the -l side of the middle finger, ring and little on +l)
      const d0 = _cd0.copy(h).multiplyScalar(Math.cos(a)).addScaledVector(l, out * Math.sin(a));
      const ax = _cax.copy(d0).cross(n).normalize(); let acc = 0;
      for (let j = 1; j <= 3; j++) { acc += g[j - 1] * Math.PI / 180; const want = _cw.copy(d0).applyAxisAngle(ax, acc), b = S(side, i, j);
        b.getWorldPosition(_a); (j < 3 ? S(side, i, j + 1).getWorldPosition(_b) : tipOf(side, i, _b)); _u.subVectors(_b, _a).normalize();
        if (_u.dot(want) > 0.99999) continue; _q.setFromUnitVectors(_u, want); _q.slerp(_ID, 1 - weight);
        b.parent.getWorldQuaternion(_pq); b.quaternion.copy(_pq.invert().multiply(b.getWorldQuaternion(_wq).premultiply(_q))); b.updateMatrixWorld(true); }
    }
  }  M.mPitch = 0; M.mSide = 0;
  function mouseFit() {                                      // palm over the hump, resting on it; no knuckle in the shell
    const pm = palmAt("Right", V()), m = topMap(P.mouseNode), hump = P.mouseNode.localToWorld(_n.copy(m.peak)), f = fwdV();
    const d = V(hump.x - GRIP_BACK * f.x - M.mSide * f.z - pm.x, 0, hump.z - GRIP_BACK * f.z + M.mSide * f.x - pm.z);   // (M.mSide: + = his right)
    return d.setY(Math.max(under("mouse", pm) + PALM_R - pm.y, knuckleNeed("Right", "mouse"), shellLift()));
  }
  // the palm, the knuckles and the thumb's root on the shell's own mesh: the hand up by its skin's deepest point in it
  // (straight up to the shell's top over that point)
  const PALMSKIN = {};
  function palmSkin() {
    if (PALMSKIN.v) return PALMSKIN.v; const hand = env.bones.RightHand, all = [];
    env.boy.traverse(o => { if (!o.isSkinnedMesh || /_inside$/.test(o.name)) return; const I = o.geometry.attributes.skinIndex, W = o.geometry.attributes.skinWeight;
      for (let n = 0; n < I.count; n++) { let k0 = 0, w0 = 0; for (let c = 0; c < 4; c++) if (W.getComponent(n, c) > w0) { w0 = W.getComponent(n, c); k0 = I.getComponent(n, c); } if (o.skeleton.bones[k0] === hand) all.push([o, n]); } });
    const st = Math.max(1, Math.ceil(all.length / 160)); PALMSKIN.v = all.filter((_, n) => n % st === 0).concat(...[1, 2, 3, 4, 5].map(i => skinOf("Right", i, 1)));
    return PALMSKIN.v;
  }
  const _bb = new THREE.Box3();
  function shellLift() {
    _bb.setFromObject(P.mouseNode); let up = 0;
    for (const [o, n] of palmSkin()) { o.getVertexPosition(n, _p).applyMatrix4(o.matrixWorld); if (!_bb.containsPoint(_p)) continue;
      _ray.set(_p, _up1); _ray.far = 0.2; const hs = _ray.intersectObjects(shell(), false); let k = 0, last = -1, first = null;
      for (const h of hs) { if (h.distance - last > 1e-5) { k++; if (first === null) first = h.distance; } last = h.distance; }
      if (k % 2 === 1) up = Math.max(up, first); }
    return up;
  }
  // once the hand is placed, each frame: the tilt that brings the index and middle fingertips onto the buttons (a tip 1 mm
  // up: the hand ~0.5 deg down about the wrist), and the hand across until the thumb's pad is THUMB_IN / 2 into the left
  // flank (left by as much as it is deeper, right by its clearance); followed at most 1.5 deg and 2 mm a frame
  function mouseSettle() {
    // (a finger omOpen had to open is on the shell, held off it by its own curl: both opened, the hand up; one, held)
    const op = M.omOpen || {}, nOp = [2, 3].filter(i => op[i] != null).length;
    const tip = nOp === 2 ? -0.001 : nOp === 1 ? 0 : Math.min(tipSkin("Right", "mouse", 2), tipSkin("Right", "mouse", 3));
    const c = thumbSide(), lim = (x, a) => Math.max(-a, Math.min(a, x));
    M.mPitch = Math.max(-0.5, Math.min(0.6, M.mPitch + lim(tip / 0.11, 0.026)));
    const r = thumbSide([1]), e = r !== null && -r > THUMB_IN ? r + THUMB_IN / 2 : c !== null ? c + THUMB_IN / 2 : 0;
    M.mSide = lim(M.mSide + lim(e, 0.002), 0.04);           // (the thumb's root out of the flank first, then its pad onto it)
    M.thumbSide = c;                                         // (?debug)
    // the roll (omAim): the front take's, less what keeps the ring and little fingers out of the shell and the pad at their
    // curl, inside the front take's band only: 0.5 deg a frame little side up while either had to open, back towards the
    // take's while both are clear
    const opened = [4, 5].some(i => op[i] != null && op[i] < 0.95), j = OM.j;
    const clear = !opened && Math.min(gap("Right", "mouse", 4, 1), gap("Right", "mouse", 5, 1)) > 0.003, atBand = M.mRoll <= j.roll_band[0] - j.roll_base + 1e-6;
    M.mRoll = Math.max(j.roll_band[0] - j.roll_base, Math.min(0, M.mRoll + (opened ? -0.5 : clear ? 0.5 : 0)));
    // the mouse across (it is ours: its width is free to match his hand): narrower while the ring and little fingers still
    // had to open with the roll at its band's end, wider again (to its own) while they are clear; 0.3% a frame
    M.mWidth = Math.max(0.6, Math.min(1, M.mWidth + (opened && atBand ? -0.003 : clear ? 0.003 : 0)));
    mouseWidth(M.mWidth);
    // the mouse turned under his thumb (his thumb lies along its flank in the take, so the flank runs where his thumb
    // does): its long axis towards the thumb's line seen from above, 0.3 deg a frame, within 15 deg of where it was put
    const n = P.mouseNode, ta = S("Right", 1, 3).getWorldPosition(V()).sub(S("Right", 1, 2).getWorldPosition(_g)).setY(0).normalize();
    const la = (MW.axis === "x" ? V(0, 0, 1) : V(1, 0, 0)).transformDirection(n.matrixWorld).setY(0).normalize();
    let dy = Math.atan2(la.x * ta.z - la.z * ta.x, la.dot(ta)); if (dy > Math.PI / 2) dy -= Math.PI; if (dy < -Math.PI / 2) dy += Math.PI;   // (an axis: either way along it)
    if (MW.y0 == null) MW.y0 = n.rotation.y;
    M.mYaw = Math.max(-0.26, Math.min(0.26, (M.mYaw || 0) - Math.max(-0.005, Math.min(0.005, dy))));
    n.rotation.y = MW.y0 + M.mYaw; n.updateMatrixWorld(true);
  }
  // the mouse's width: its shorter horizontal extent in its own frame, scaled from its own (M.mWidth: the share kept)
  const MW = {axis: null, s0: 1}; M.mWidth = 1;
  function mouseWidth(k) {
    const n = P.mouseNode; if (!n) return;
    if (!MW.axis) { const m = topMap(n); MW.axis = m.nx * m.s < m.nz * m.s ? "x" : "z"; MW.s0 = n.scale[MW.axis]; }
    n.scale[MW.axis] = MW.s0 * k; n.updateMatrixWorld(true);
  }
  M.mRoll = 0;
  const keyFit = side => () => {                              // the knuckles 3 cm over the caps under them (never closer than their skin)
    // (the highest surface under any knuckle: a hand half off the keyboard is held over the caps, not lowered to the pad's average)
    let y = 0, n = 0, top = -1e9; for (let i = 2; i <= 5; i++) { const k = S(side, i, 1); if (!k) continue; k.getWorldPosition(_s); y += _s.y; top = Math.max(top, under("keys", _s)); n++; }
    return V(0, Math.max(top + (MX() && M.w.type >= M.w.mouse ? M.kk[side] : KEY_KNUCKLE) + M.kUp[side] - y / n, knuckleNeed(side, "keys")), 0);
  };
  function keyTarget(side) { return P.kbNode ? P.kbNode.localToWorld(V(side === "Left" ? -FJ : FJ, 0, 0)) : V(...P.keys.c); }

  // the fingertip, measured once off his skin (the end bone's farthest vertex, less a finger's half thickness), carried in
  // the end bone's own frame so it follows that joint
  const TIP = {};
  function tipOf(side, i, out) {
    const b3 = S(side, i, 3), key = side + i;
    if (!TIP[key]) {
      const p3 = b3.getWorldPosition(V()), d = p3.clone().sub(S(side, i, 2).getWorldPosition(V())).normalize(), v = V(); let best = null, far = -1;
      env.boy.traverse(o => { if (!o.isSkinnedMesh || /_inside$/.test(o.name)) return; const P_ = o.geometry.attributes.position, I = o.geometry.attributes.skinIndex, W = o.geometry.attributes.skinWeight;
        for (let n = 0; n < P_.count; n++) { let k0 = 0, w0 = 0; for (let k = 0; k < 4; k++) if (W.getComponent(n, k) > w0) { w0 = W.getComponent(n, k); k0 = I.getComponent(n, k); }
          if (o.skeleton.bones[k0] !== b3) continue; o.getVertexPosition(n, v).applyMatrix4(o.matrixWorld); const a = v.clone().sub(p3).dot(d); if (a > far) { far = a; best = p3.clone().addScaledVector(d, a); } } });
      if (!best) { best = p3.clone().addScaledVector(d, 0.015); far = 0.015; }
      best.sub(p3).multiplyScalar(Math.max(0, 1 - FING_R / Math.max(far, 1e-3))).add(p3);   // (the pad's centre, a half thickness back from the end)
      TIP[key] = b3.worldToLocal(best);
    }
    return b3.localToWorld(out.copy(TIP[key]));
  }
  // the middle and end phalanges are tested by their own skin (~48 of each one's vertices, skinned as drawn): a bone
  // line with a radius missed the pad under the tip by up to 8 mm on the keys
  const SKIN = {};
  function skinOf(side, i, k) {
    const key = side + i + k; if (SKIN[key]) return SKIN[key];
    const b = S(side, i, k), all = [];
    env.boy.traverse(o => { if (!o.isSkinnedMesh || /_inside$/.test(o.name)) return; const I = o.geometry.attributes.skinIndex, W = o.geometry.attributes.skinWeight;
      for (let n = 0; n < I.count; n++) { let k0 = 0, w0 = 0; for (let c = 0; c < 4; c++) if (W.getComponent(n, c) > w0) { w0 = W.getComponent(n, c); k0 = I.getComponent(n, c); } if (o.skeleton.bones[k0] === b) all.push([o, n]); } });
    // (the pad and the tip's end first: the vertices furthest towards the palm and the tip, then an even spread of the rest)
    const p0 = b.getWorldPosition(V()), c = k < 3 ? S(side, i, k + 1).getWorldPosition(V()) : tipOf(side, i, V()), dir = c.clone().sub(p0).normalize();
    const hand = env.bones[side + "Hand"], wr = hand.getWorldPosition(V()), h = S(side, 3, 1).getWorldPosition(V()).sub(wr).normalize(), l = S(side, 5, 1).getWorldPosition(V()).sub(S(side, 2, 1).getWorldPosition(V()));
    let palm = h.clone().cross(l).normalize(); if (palm.y > 0) palm.negate();
    const v = V(), score = all.map(([o, n]) => { o.getVertexPosition(n, v).applyMatrix4(o.matrixWorld); const d = v.sub(p0); return d.dot(palm) + 0.5 * d.dot(dir); });
    const order = all.map((_, n) => n).sort((a, b2) => score[b2] - score[a]), pick = new Set(order.slice(0, 32));
    const st = Math.max(1, Math.ceil(all.length / 16)); all.forEach((_, n) => { if (n % st === 0) pick.add(n); });
    return (SKIN[key] = [...pick].map(n => all[n]));
  }
  // on the keys only the pad matters (the caps are below it, tested straight down): the 12 pad-most of skinOf's vertices,
  // pad-first already (G24 F9: each skin test re-skins its vertices on the CPU, dozens of times a frame)
  const PAD = {};
  const padOf = (side, i, k) => PAD[side + i + k] || (PAD[side + i + k] = skinOf(side, i, k).slice(0, 12));
  const SKALL = {};
  function skinAll(side, i, k) {                             // every vertex skinned mostly to finger i's bone k
    const key = side + i + k; if (SKALL[key]) return SKALL[key]; const b = S(side, i, k), all = [];
    env.boy.traverse(o => { if (!o.isSkinnedMesh || /_inside$/.test(o.name)) return; const I = o.geometry.attributes.skinIndex, W = o.geometry.attributes.skinWeight;
      for (let n = 0; n < I.count; n++) { let k0 = 0, w0 = 0; for (let c = 0; c < 4; c++) if (W.getComponent(n, c) > w0) { w0 = W.getComponent(n, c); k0 = I.getComponent(n, c); } if (o.skeleton.bones[k0] === b) all.push([o, n]); } });
    return (SKALL[key] = all);
  }
  function gap(side, name, i, j) {                           // finger i from its joint j to the tip: the least clearance over what is under it
    let low = 1e9;
    if (j === 1) {                                           // the first phalanx: its bone line, a finger's half thickness round it
      S(side, i, 1).getWorldPosition(_s); S(side, i, 2).getWorldPosition(_e);
      _sd.subVectors(_e, _s).cross(_up1).setY(0).normalize().multiplyScalar(0.7 * FING_R);   // (across the finger: on a slope its uphill side is lower)
      for (let u = 0.25; u <= 1.0001; u += 0.25) { _p.lerpVectors(_s, _e, u);
        const top = Math.max(under(name, _p), under(name, _g.copy(_p).add(_sd)), under(name, _g.copy(_p).sub(_sd))); low = Math.min(low, _p.y - FING_R - top); }
    }
    for (let k = Math.max(2, j); k <= 3; k++) for (const [o, n] of (name === "keys" && i > 1 ? padOf(side, i, k) : skinOf(side, i, k))) { o.getVertexPosition(n, _p).applyMatrix4(o.matrixWorld); low = Math.min(low, _p.y - under(name, _p)); }
    // the mouse: every vertex of the finger's skin on the shell's own mesh (under its bulge the height map reads clear, and
    // a finger down a flank touches it with its side, which the subset above leaves out)
    if (name === "mouse" && low >= 0) { _bb.setFromObject(P.mouseNode);
      for (let k = j; k <= 3 && low >= 0; k++) for (const [o, n] of skinAll(side, i, k)) { o.getVertexPosition(n, _p).applyMatrix4(o.matrixWorld); if (_bb.containsPoint(_p) && inShell(_p)) { low = -0.001; break; } } }
    return low;
  }
  // the page's own turns of the fingers are undone at the start of the next step (they never add up)
  const GR = new Map();
  // (before the mixer's update: a clip that holds a bone still is not written again by the mixer, three.js skipping an
  // unchanged value, so a test of "did the clip write it" missed: one missed frame and the page's turn stayed for good)
  function contactRestore() { for (const [b, r] of GR) { b.quaternion.copy(r.pre); b.updateMatrixWorld(true); } GR.clear(); }
  // (a record per bone, reused: the clip's turn is copied in, not cloned - 30 fresh quaternions a solve before)
  const GRP = new Map();
  function grKeep(b) { if (!b || GR.has(b)) return; let r = GRP.get(b); if (!r) GRP.set(b, r = {pre: new THREE.Quaternion()}); r.pre.copy(b.quaternion); GR.set(b, r); }
  function grKeepHand(side) { for (let i = 1; i <= 5; i++) for (let j = 1; j <= 3; j++) grKeep(S(side, i, j)); }
  // keys (slow > 0): the bend that brings a finger down to the caps is followed over `slow` seconds, so the clip's own
  // quick strokes (a finger lifted for a key) stay; never into a key, though: the bend is never more than the touch's
  const FA = new Map();
  const _lpq = new THREE.Quaternion();
  function layFingers(side, name, weight, first = 2, slow = 0, dt = 1 / 30, lifted = null) {   // each joint bends (down) or straightens (up) until its part of the finger touches
    grKeepHand(side);
    for (let i = first; i <= 5; i++) for (let j = 1; j <= 3; j++) {
      const b = S(side, i, j), c = j < 3 ? S(side, i, j + 1) : null; if (!b) continue;
      b.getWorldPosition(_s); (c ? c.getWorldPosition(_e) : _e.copy(_s).sub(S(side, i, j - 1).getWorldPosition(_n)).add(_s));
      _ax.subVectors(_e, _s).normalize().cross(_dn2); if (_ax.lengthSq() < 1e-8) continue; _ax.normalize();
      b.getWorldQuaternion(_q0); const pq = b.parent.getWorldQuaternion(_lpq).invert();
      const set = a => { _rq.setFromAxisAngle(_ax, a); b.quaternion.copy(pq).multiply(_rq.multiply(_q0)); b.updateMatrixWorld(true); };
      // from straightest down in steps to the first touch, then halved in between (bent past the vertical a finger
      // comes up again, so the first touch, not the last)
      const lo0 = j === 1 ? -0.6 : -0.15, HI = 1.2;          // (the middle and end joints barely over-straighten)
      set(lo0); if (gap(side, name, i, j) < 0) { set(lo0 * weight); if (slow > 0) FA.set(b, lo0); continue; }   // (in it even straightened: as far out as it goes)
      let lo = lo0, hi = null, best = lo0, bestG = 1e9;
      for (let a = lo0 + 0.15; a <= HI + 1e-6; a += 0.15) { set(a); const g = gap(side, name, i, j); if (g <= 0) { hi = a; break; } if (g < bestG) { bestG = g; best = a; } lo = a; }
      let a = best;                                          // (no touch within reach: as near as it comes)
      if (hi !== null) { for (let it = 0; it < 8; it++) { const m = (lo + hi) / 2; set(m); if (gap(side, name, i, j) > 0) lo = m; else hi = m; } a = lo; }
      if (lifted && lifted.has(i)) { const f = FA.has(b) ? FA.get(b) : 0; FA.set(b, f * Math.exp(-dt / 0.1)); a = Math.min(0, a); }   // (a stroke: the clip's finger, only opened out of a key)
      else if (slow > 0) { const f = FA.has(b) ? FA.get(b) : a, nf = f + (a - f) * (1 - Math.exp(-dt / slow)); FA.set(b, nf); a = Math.min(nf, a); }
      set(a * weight);
    }
    let worst = 0; for (let i = first; i <= 5; i++) if (S(side, i, 1)) worst = Math.min(worst, gap(side, name, i, 1)); return worst;
  }

  const _k = V(), _c = V(), _m = V(), dK = V(), _hp = V();
  // the solve at M.handsHz (15 a second): the contact solves skin vertices inside bisection searches for 15 joints x 2 hands,
  // 13-16 ms a frame under software GL and the hottest thing on the owner's Mac (its fans). The frames between re-apply
  // the last solve's local turns of the bones it touches (both arms: upper arm, forearm, hand, every finger bone - chainOf)
  // over the clip the mixer just wrote, so nothing snaps back to the clip pose, and the clip's turns go in GR so the next
  // frame starts from the clip again (contactRestore); the solve's clocks (the takes, the phases, the follows) run on the
  // time accumulated since. Every frame still while a reach is in progress (a mode switch: the weights move each frame,
  // minimum-jerk), on a mode or a clip change, until a first solve is held, and while nothing is placed (the modes' weights
  // gone: nothing to hold, and the body is cheap)
  const HZ = {acc: 0, held: false, mode: null, cur: null, q: {Left: [], Right: []}};
  function hands(dt) {
    const t0 = performance.now(), typing = M.mode === "desk_type", mousing = M.mode === "desk_mouse", cur = env.state().current;
    const reaching = (typing ? M.ph.type < 1 : M.ph.type > 0) || (mousing ? M.ph.mouse < 1 : M.ph.mouse > 0);
    HZ.acc += dt;
    const full = !(M.handsHz > 0) || !HZ.held || reaching || M.noIK || M.mode !== HZ.mode || cur !== HZ.cur || HZ.acc >= 1 / M.handsHz - 1e-6;
    HZ.mode = M.mode; HZ.cur = cur;
    if (full) { const dta = HZ.acc; HZ.acc = 0; handsSolve(dta); HZ.held = M.w.type > 0.01 || M.w.mouse > 0.01; if (HZ.held) handsHold(true); }
    else handsHold(false);
    const ms = performance.now() - t0;
    M.handsMs = ms; M.handsMsAvg = M.handsMsAvg == null ? ms : M.handsMsAvg + (ms - M.handsMsAvg) * 0.05;   // (?debug: the hands' cost per frame)
  }
  function handsSolve(dt) {                                  // the whole solve, as every frame before the throttle
    for (const sd of ["Left", "Right"]) forearmTwistKeep(sd);
    handsBody(dt);
    for (const sd of ["Left", "Right"]) forearmTwistBack(sd);
    if (ELB_REF.Left || ELB_REF.Right) { elbowKeep(); ELB_REF.Left = ELB_REF.Right = null; }   // (other placements keep the clip's elbow)
  }
  function handsHold(save) {                                 // save: the solved pose kept; else put back over the clip's (between solves)
    for (const side of ["Left", "Right"]) { const C = chainOf(side), Q = HZ.q[side];
      C.forEach((b, i) => { if (save) { (Q[i] || (Q[i] = new THREE.Quaternion())).copy(b.quaternion); return; }
        grKeep(b); b.quaternion.copy(Q[i]); }); }               // (the clip's turn kept: back before the next mixer update)
  }
  // a rig with no forearm twist bones (the Mixamo character): the arm's solve leaves the upper arm's and the forearm's own
  // twist (about their length) free, and frame to frame they jumped - the upper arm 145 deg in one frame while he typed,
  // the hand's turn on the forearm 151-165 deg, the sleeve wrung round. Handing the twist to the wrist or the forearm only
  // moved the flip (the elbow then 121-179 deg a frame). So the upper arm and the forearm keep the clip's own twist, each
  // child turned back by as much: the hand's pose in the room, the fingertips and the contacts unchanged, the elbow where
  // it was. The default page's v5 has twist bones
  const FTW = {};
  const twistOf = (q, a) => { const v = V(q.x, q.y, q.z), p = a.clone().multiplyScalar(v.dot(a)), t = new THREE.Quaternion(p.x, p.y, p.z, q.w);
    if (t.lengthSq() < 1e-12) return 0; t.normalize(); if (t.w < 0) t.set(-t.x, -t.y, -t.z, -t.w); return 2 * Math.acos(Math.min(1, t.w)) * Math.sign(V(t.x, t.y, t.z).dot(a) || 1); };
  function noTwistBones(side) { return !env.bones[(side === "Left" ? "L" : "R") + "_ForearmTwist01"]; }
  const TWIST_CHAIN = side => [[side + "Arm", side + "ForeArm"], [side + "ForeArm", side + "Hand"]];   // (each bone, the child on its length)
  function forearmTwistKeep(side) {                          // before the hands are placed: the clip's twist of the upper arm and the forearm
    FTW[side] = noTwistBones(side) ? TWIST_CHAIN(side).map(([b, c]) => { const B = env.bones[b], C = env.bones[c];
      return B && C && C.parent === B ? twistOf(B.quaternion, C.position.clone().normalize()) : null; }) : null;
  }
  function forearmTwistBack(side) {                          // after: back to it (the upper arm first), each child turned back by as much
    if (!FTW[side]) return; const out = [];
    TWIST_CHAIN(side).forEach(([b, c], k) => { const t0 = FTW[side][k], B = env.bones[b], C = env.bones[c]; if (t0 == null) return;
      const a = C.position.clone().normalize(); let d = t0 - twistOf(B.quaternion, a); d = Math.atan2(Math.sin(d), Math.cos(d)); out.push(+(d * 57.3).toFixed(1)); if (Math.abs(d) < 1e-4) return;
      const R = new THREE.Quaternion().setFromAxisAngle(a, d); B.quaternion.multiply(R); C.quaternion.premultiply(R.invert()); B.updateMatrixWorld(true); });
    M.wrist = M.wrist || {}; M.wrist[side] = out;            // (?debug: how far the solve had turned the upper arm and the forearm)
  }
  function handsBody(dt) {
    const typing = M.mode === "desk_type", mousing = M.mode === "desk_mouse";
    // each mode's weight: a phase moving at a constant rate, shaped minimum-jerk (10p^3 - 15p^4 + 6p^5): a reach from the
    // keys to the mouse starts and ends at rest and peaks mid-way, like a real one (~1 m/s). (An exponential approach
    // peaked at its start and mid-switch moved the right hand 72 mm in a frame, 2+ m/s.)
    const step = dt / REACH_S, mj = p => p * p * p * (10 - 15 * p + 6 * p * p);
    const c01 = x => Math.min(1, Math.max(0, x));
    M.ph.type = c01(M.ph.type + (typing ? step : -step)); M.ph.mouse = c01(M.ph.mouse + (mousing ? step : -step));
    M.w.type = mj(M.ph.type); M.w.mouse = mj(M.ph.mouse);
    if (M.noIK) { ELB_REF.Left = ELB_REF.Right = null; return; }
    env.boy.updateMatrixWorld(true); elbowRef(dt);
    // the clip's keyboard to the room's (its home row, the caps' top): the recorded motion's carrier; keyOn() then centres the
    // index fingertips over F and J (a slow correction, so the typing itself stays the clip's)
    _k.set(...P.keys.c); dK.subVectors(_k, toWorld(kbRef(), _c));
    const wk = Math.max(M.w.type, M.w.mouse);                // (the left hand stays on the keys while he mouses)
    // typing: the owner's own hands; mousing: his left hand at rest on the keys, drifting slowly through his take. Across a
    // mode switch the left hand blends the two by their weights (its rest share: w.mouse over both), each clock running
    // while its mode has weight; the right hand stays on his typing take until w.type is gone (never the old capture path:
    // a switch snapped the left index ~5 cm in a frame and put the right hand through keyOn's placement for ~15 frames)
    const ot = OT.json && P.kbNode;
    if (ot && M.w.type > 0.01) OT.t += dt * OT.json.speed;
    if (ot && M.w.mouse > 0.01) OT.tr += dt * OT.json.speed * OT_REST;
    const mix = wk > 0 ? M.w.mouse / (M.w.type + M.w.mouse) : 0;
    // (the left hand stays on the keys between the keys and the mouse, its weight then never low: as before. Into and out of
    // the desk modes it fades from or to the clip's pose: blended from its pose at full weight)
    const inSwitch = M.w.type > 0.01 && M.w.mouse > 0.01;
    if (wk > 0.01) { if (ot) { if (inSwitch) ownerKeys("Left", wk, dt, {mix}); else weighted("Left", wk, w => ownerKeys("Left", w, dt, {mix})); } else keyOn("Left", wk, dt); }
    const both = ot && M.w.type > 0.01 && M.w.mouse > 0.01, qc = both ? rightChain().map(b => b.quaternion.clone()) : null;   // (the clip's right arm, before the mouse moves it)
    if (M.w.mouse > 0.01 && P.mouseNode) {
      const ry = env.boy.rotation.y, home = V(P.mouse[0] - Math.sin(ry) * HUMP, P.mouse[1], P.mouse[2] - Math.cos(ry) * HUMP);
      omStep(dt); const F = omNow(), f = fwdV(), k2 = S("Right", 2, 1), k5 = S("Right", 5, 1), pw = k2 && k5 ? k2.getWorldPosition(V()).distanceTo(k5.getWorldPosition(_a)) : 0;   // (his palm width, 5 -> 17: the character's)
      if (F) home.addScaledVector(f, F.move[0] * pw).addScaledVector(V(-f.z, 0, f.x), F.move[1] * pw);   // (his wrist's travel over the pad)
      // (mid-switch the mouse's pose at full weight: the crossfade below then runs between two whole poses; fading alone,
      // the pose at full weight blended from the clip's by the weight)
      const off = home.sub(toWorld(CLIP.mouse, _c));
      weighted("Right", both ? 1 : M.w.mouse, () => {
        pin("Right", off, 1);                                // the recorded hand carried to the room's mouse: where it goes, the mouse goes
        follow(); mouseHold(1); });                          // then the hand onto the mouse
    } else M.grab = null;
    // (after the mouse: its pin carries the clip's own hand by an offset, so it must see the clip's hand, not one already
    // placed on the keys - mid-switch that sent the right hand 22 cm in one frame; the typing placement is absolute.) While
    // both modes have weight the right arm crossfades exactly: the mouse's pose and the typing's (placed at full weight),
    // slerped bone by bone by w.type - pin() is not linear in its weight (at w.type 0.01 it still landed the hand on the
    // keys, then let go: 28 cm in a frame)
    if (M.w.type > 0.01) {
      if (!ot) keyOn("Right", M.w.type, dt);
      else if (both) {
        // between the two whole poses in the task's own terms: the wrist along the straight line between them (so its speed
        // is the weight's, minimum-jerk), the arm solved to it from the clip's pose, the hand's turn slerped in the world,
        // the fingers in their own frames. (Slerping the arm bone by bone, its forearm turned ~160 deg apart between the
        // poses: the shortest way round swapped mid-switch and the fingertip leapt 12 cm in a frame.)
        const chain = rightChain(), hand = env.bones.RightHand, fa = env.bones.RightForeArm, wq = () => hand.getWorldQuaternion(new THREE.Quaternion());
        const qm = chain.map(b => b.quaternion.clone()), pm = hand.getWorldPosition(V()), hm = wq(), em = fa.getWorldPosition(V());
        const reset = () => { chain.forEach((b, i) => b.quaternion.copy(qc[i])); env.boy.updateMatrixWorld(true); };
        reset(); ownerKeys("Right", 1, dt);                  // (the typing solved from the clip's hand, as in steady typing)
        const qt = chain.map(b => b.quaternion.clone()), pt = hand.getWorldPosition(V()), ht = wq(), et = fa.getWorldPosition(V());
        const wt = M.w.type / (M.w.type + M.w.mouse), at = pm.clone().lerp(pt, wt), hq = hm.slerp(ht, wt), ew = em.lerp(et, wt);
        reset(); pin("Right", at.sub(hand.getWorldPosition(V())), 1, null, {iters: 5});
        swivelTo("Right", ew);                             // (the elbow to the two poses' elbow, blended)
        hand.quaternion.copy(hand.parent.getWorldQuaternion(new THREE.Quaternion()).invert().multiply(hq));
        chain.forEach((b, i) => { if (i >= 3) b.quaternion.copy(qm[i].slerp(qt[i], wt)); }); env.boy.updateMatrixWorld(true); }
      else weighted("Right", M.w.type, w => ownerKeys("Right", w, dt));
    }
  }
  const CHAINS = {Left: [], Right: []};
  function chainOf(side) {                                   // the bones a hand's placement turns: the arm, the hand, the fingers
    const C = CHAINS[side];
    if (!C.length) { for (const n of ["Arm", "ForeArm", "Hand"]) if (env.bones[side + n]) C.push(env.bones[side + n]);
      for (let i = 1; i <= 5; i++) for (let j = 1; j <= 3; j++) { const b = S(side, i, j); if (b) C.push(b); } }
    return C;
  }
  const rightChain = () => chainOf("Right");
  // a hand placed at a fading weight (preview/freeze-why-ease): solved at full weight, then the arm blended bone by bone
  // from the clip's pose by the weight. pin() is not linear in its weight: at a weight of 0.02 the mouse hold still had his
  // hand on the mouse, then at 0.01 let go - the fingers 295 mm in one frame. At full weight (steady typing, mousing)
  // nothing changes
  function weighted(side, w, solve) {
    if (w >= 0.999) return solve(1);
    const C = chainOf(side), q0 = C.map(b => b.quaternion.clone());
    solve(1);
    C.forEach((b, i) => b.quaternion.copy(q0[i].slerp(b.quaternion, w))); env.boy.updateMatrixWorld(true);
    // the blend's way from the clip's hand to the solved one went through the desk (sitting down, then the mouse: both
    // hands 13 frames in it, 500-940 sampled vertices): the wrist goes up over the desk's top on the way (the solve's own
    // ends are out of it: at either end nothing is lifted)
    if (M.noLift) return;                                    // (?debug)
    // (the lift grows at most WLIFT_STEP a frame: all at once it popped the hand 8 cm up on the blend's first frame)
    WLIFT[side] = WLIFT[side] || 0; let up = 0;
    for (let k = 0; k < 2; k++) { const need = underTop(side); if (need <= 0.003) break; const d = Math.min(need + 0.01, WLIFT[side] + WLIFT_STEP - up); if (d <= 0) break; up += d; pin(side, V(0, d, 0), 1, null, {iters: 3}); }
    WLIFT[side] = up; M.lifted = M.lifted || {}; M.lifted[side] = +up.toFixed(3);
  }
  function underTop(side) {                                  // how far the lowest of his hand's and forearm's skin in the desk is under its top (m)
    handIn(side); foreIn(side); const D = deskCols(); if (!D) return 0; let need = 0;
    for (const [o, n] of [...HANDSKIN[side], ...FORE[side]]) { o.getVertexPosition(n, _g).applyMatrix4(o.matrixWorld);
      const i = Math.floor((_g.x - D.x0) / D.c), k = Math.floor((_g.z - D.z0) / D.c); if (i < 0 || k < 0 || i >= D.nx || k >= D.nz) continue;
      const t = D.tops[i * D.nz + k] + (M.deskTest || 0); if (Number.isNaN(t) || _g.y >= t || _g.y < t - 0.15) continue;   // (anywhere in the desk's top 15 cm: deeper than its 3 cm slab too)
      need = Math.max(need, t - _g.y); }
    return need;
  }
  function mouseHold(w) {                                    // his hand from the take, placed so palm and fingertips meet the shell
    const F = omNow(); if (!F || !S("Right", 2, 1) || !S("Right", 3, 1) || !S("Right", 5, 1)) return; shellSync();   // (palmFrame needs the knuckles)
    grKeepHand("Right");
    pin("Right", V(), w, mouseFit, {iters: 6, pitch: () => M.mPitch, aim: () => omAim(F), post: () => omFingers(F, w)});
    omOpen(F, w); if (w > 0.97) mouseSettle();
  }
  // ---------- the owner's own hand on his mouse (room/mh/owner_mouse.json: room_build/kimodo_g12/owner_mouse.py) ----------
  // per frame of his overhead take: each finger segment's direction in his palm's frame (wrist -> middle knuckle, index ->
  // little knuckle), the palm's long axis over the desk, the hand's roll from his front take and the wrist's travel over
  // the pad in palm widths;
  // played at its own `speed` of his, looped (the file's tail is already crossfaded into its head)
  const OM = {j: null, t: 0, d: [], hand: [0, 0, 0, 0, 0, 0], move: [0, 0]};
  fetch("room/mh/owner_mouse.json").then(r => r.json()).then(j => { OM.j = j; }).catch(() => {});
  function omStep(dt) { if (OM.j) OM.t = (OM.t + dt * OM.j.speed) % (OM.j.frames / OM.j.fps); }
  function omNow() {                                         // the take at OM.t, between its two frames
    const j = OM.j; if (!j) return null;
    const x = OM.t * j.fps, f0 = Math.floor(x) % j.frames, f1 = (f0 + 1) % j.frames, a = x - Math.floor(x);
    const mix = (arr, n, out) => { for (let k = 0; k < n; k++) out[k] = arr[f0 * n + k] * (1 - a) + arr[f1 * n + k] * a; return out; };
    mix(j.d, 45, OM.d); mix(j.hand, 6, OM.hand); mix(j.move, 2, OM.move); M.omFrame = x;   // (?debug)
    return OM;
  }
  // the hand's aim: the take's long axis (wrist -> middle knuckle) over the desk, rolled about it little side down by the
  // front take's roll (owner_mouse.py: the overhead take's depth is its weak axis), plus M.mRoll: contact's correction,
  // inside the front take's band only
  const _oahw = V(), _oart = V(), _oal1 = V(), _oal2 = V(), _oay = V();   // (the aims' vectors, read by pin's keepTurn at once)
  function omAim(F) {
    const hw = deskV(F.hand, 0, _oahw), f = fwdV(), rt = _oart.set(-f.z, 0, f.x); rt.addScaledVector(hw, -rt.dot(hw)).normalize();
    const j = OM.j, deg = Math.max(j.roll_band[0], Math.min(j.roll_band[1], j.roll_base + M.mRoll)), a = deg * Math.PI / 180;
    const l1 = _oal1.copy(rt).applyAxisAngle(hw, a), l2 = _oal2.copy(rt).applyAxisAngle(hw, -a);
    M.rollDeg = deg; return [hw, l1.y < l2.y ? l1 : l2];   // (the little side down)
  }
  const deskV = (a, k, out) => { const f = fwdV(), rt = _oart.set(-f.z, 0, f.x); return out.copy(f).multiplyScalar(a[k]).addScaledVector(rt, a[k + 1]).add(_oay.set(0, a[k + 2], 0)).normalize(); };
  function palmFrame(side) {                                 // the character's palm, as the take's: h wrist -> middle knuckle, l index -> little, n = h x l
    const wr = env.bones[side + "Hand"].getWorldPosition(V()), h = S(side, 3, 1).getWorldPosition(V()).sub(wr).normalize();
    const l = S(side, 5, 1).getWorldPosition(V()).sub(S(side, 2, 1).getWorldPosition(V())); l.addScaledVector(h, -l.dot(h)).normalize();
    return [h, l, h.clone().cross(l)];
  }
  // the end of a finger as seen: the middle of its end bone's farthest skin (beyond 80% of the farthest vertex), carried
  // in that bone's frame. (tipOf is the pad's centre for contact, which lies off the line the eye follows: aimed by it,
  // the thumb's last joint read 19 deg bent where his is 9)
  const SEEN = {};
  function seenTip(side, i, out) {
    const b3 = S(side, i, 3), key = side + i;
    if (!SEEN[key]) { const h3 = b3.getWorldPosition(V()), vs = skinAll(side, i, 3).map(([o, n]) => o.getVertexPosition(n, V()).applyMatrix4(o.matrixWorld));
      const far = Math.max(...vs.map(q => q.distanceTo(h3))), c = V(); let k = 0; for (const q of vs) if (q.distanceTo(h3) > 0.8 * far) { c.add(q); k++; }
      SEEN[key] = b3.worldToLocal(k ? c.multiplyScalar(1 / k) : tipOf(side, i, V())); }
    return b3.localToWorld(out.copy(SEEN[key]));
  }
  function aimBone(i, j, want, weight, seen = false) {       // finger i's joint j turned so its segment points along want
    const b = S("Right", i, j); b.getWorldPosition(_a); (j < 3 ? S("Right", i, j + 1).getWorldPosition(_b) : seen ? seenTip("Right", i, _b) : tipOf("Right", i, _b)); _u.subVectors(_b, _a).normalize();
    if (_u.dot(want) > 0.99999) return; _q.setFromUnitVectors(_u, want); _q.slerp(_ID, 1 - weight);
    b.parent.getWorldQuaternion(_pq); b.quaternion.copy(_pq.invert().multiply(b.getWorldQuaternion(_wq).premultiply(_q))); b.updateMatrixWorld(true);
  }
  // each segment along the take's, in the character's palm; open (finger -> share): that finger's bends taken by that share
  // towards straight (its first segment laid into the palm's plane, the splay kept)
  function omFingers(F, weight, open = null) {
    const [h, l, n] = palmFrame("Right");
    // the thumb: straight, its MCP and IP bones on along its root's line (finger1-1, as recorded). The owner: "the thumb
    // is STRAIGHT, not curved"; his take agrees (bends of 14 and 9 deg from above, the weak axis). The character's thumb
    // root lies inside its index knuckle's line and his outside it, so his segments' directions taken as they are bent
    // ours 22 / 18 deg; any turn of that root tears the skin at the thumb's base (its triangles to 5x their bind length;
    // as recorded, 2.3x). The hand is placed across the mouse, and the mouse turned under the thumb, so that this
    // straight thumb meets the left flank (mouseSettle)
    if (S("Right", 1, 3)) { const d = S("Right", 1, 2).getWorldPosition(V()).sub(S("Right", 1, 1).getWorldPosition(_g)).normalize();
      aimBone(1, 2, d, weight); aimBone(1, 3, d, weight, true); }
    for (let i = 2; i <= 5; i++) { if (!S("Right", i, 1)) continue;
      const ds = [0, 1, 2].map(k => { const o = ((i - 1) * 3 + k) * 3; return V(F.d[o], F.d[o + 1], F.d[o + 2]); });
      if (open && open[i] != null) { const m = open[i], d0 = ds[0].clone().setZ(0).normalize(), out = [d0];
        for (let k = 0; k < 3; k++) { const q = _rq2.setFromUnitVectors(k ? ds[k - 1] : d0, ds[k]).slerp(_ID, 1 - m); out.push(out[k].clone().applyQuaternion(q)); }
        ds.splice(0, 3, out[1], out[2], out[3]); }
      for (let j = 1; j <= 3; j++) { const d = ds[j - 1]; aimBone(i, j, h.clone().multiplyScalar(d.x).addScaledVector(l, d.y).addScaledVector(n, d.z).normalize(), weight); }
    }
  }
  const OMO = {};                                            // (each opened finger's share last frame: the next one's warm start)
  function omOpen(F, weight) {                               // a finger that would be in the shell is opened until it only touches
    const open = {};
    for (const i of [2, 3, 4, 5]) { if (!S("Right", i, 1) || gap("Right", "mouse", i, 1) >= 0) continue;
      const try_ = m => { omFingers(F, weight, {...open, [i]: m}); return gap("Right", "mouse", i, 1); };
      // warm start: last frame's share first, kept while the finger only touches (0..0.5 mm clear); else a bracket of
      // +-0.06 round it; else the whole range (8 halvings: each a skin test on the shell, ~0.3 ms)
      const c = OMO[i]; let lo = 0, hi = 1, done = false;
      if (c != null) { const g0 = try_(c); if (g0 >= 0 && g0 <= 0.0005) { lo = c; done = true; }
        else { const a = Math.max(0, c - 0.06), b = Math.min(1, c + 0.06); if (try_(a) >= 0 && try_(b) < 0) { lo = a; hi = b;
          for (let it = 0; it < 4; it++) { const m = (lo + hi) / 2; if (try_(m) >= 0) lo = m; else hi = m; } done = true; } } }
      if (!done) { lo = 0; hi = 1; for (let it = 0; it < 8; it++) { const m = (lo + hi) / 2; if (try_(m) >= 0) lo = m; else hi = m; } }
      open[i] = OMO[i] = lo; omFingers(F, weight, open); }
    for (const i of [2, 3, 4, 5]) if (open[i] == null) OMO[i] = null;
    M.omOpen = open;                                         // (?debug: the share of its bends each opened finger kept)
  }
  // the shell itself (the mouse's meshes, both faces, on their BVH): what its height map cannot see - a finger under its
  // bulge, the thumb against its steep flank
  let SHELL = null; const _ray = new THREE.Raycaster();
  function shell() {
    if (SHELL && SHELL.node === P.mouseNode) return SHELL.ms;
    const ms = [], mat = new THREE.MeshBasicMaterial({side: THREE.DoubleSide});
    P.mouseNode.traverse(o => { if (!o.isMesh || /_contact$/.test(o.name)) return; if (o.geometry.computeBoundsTree && !o.geometry.boundsTree) o.geometry.computeBoundsTree();
      const m = new THREE.Mesh(o.geometry, mat); m.matrixAutoUpdate = false; m.src = o; ms.push(m); });
    SHELL = {node: P.mouseNode, ms}; return ms;
  }
  function shellSync() { P.mouseNode.updateMatrixWorld(true); for (const m of shell()) m.matrixWorld.copy(m.src.matrixWorld); }
  function inShell(p) {                                      // inside: an odd number of faces above (a ray through an edge counted once)
    _ray.set(p, _up1); _ray.far = 0.2; let n = 0, last = -1;
    for (const h of _ray.intersectObjects(shell(), false)) { if (h.distance - last > 1e-5) n++; last = h.distance; } return n % 2 === 1;
  }
  // the thumb on the shell's left flank (his thumb lies along it in the take): its skin's least clearance to the shell
  // towards his right (- = in it; null: no shell beside it); mouseSettle moves the hand across until it is THUMB_IN / 2 in
  const THUMB_IN = 0.002, THS = {};
  const thumbSkin = k => THS[k] || (THS[k] = (() => { const a = skinAll("Right", 1, k), st = Math.max(1, Math.ceil(a.length / 60)); return a.filter((_, n) => n % st === 0); })());   // (at most ~60 vertices a bone: one ray each)
  function thumbSide(ks = [2, 3]) {                          // (ks: the thumb's pad, its last two bones; [1]: its root)
    const f = fwdV(), rt = V(-f.z, 0, f.x), ms = shell(); let c = null;
    for (const k of ks) for (const [o, n] of thumbSkin(k)) { o.getVertexPosition(n, _p).applyMatrix4(o.matrixWorld);
      _ray.set(_g.copy(_p).addScaledVector(rt, -0.03), rt); _ray.far = 0.06; const h = _ray.intersectObjects(ms, false)[0];
      if (h && (c === null || h.distance - 0.03 < c)) c = h.distance - 0.03; }
    return c;
  }

  const MX = () => CL.desk_type === MXK.clip;
  const kbRef = () => MX() ? MXK.F.map((v, i) => (v + MXK.J[i]) / 2) : P.ref;   // (the clip's keyboard point: for the roll)
  const dKs = {Left: V(), Right: V()};
  function keyDelta(side) {                                  // the carry for one hand onto the keys
    if (!MX() || !P.kbNode || M.w.type < M.w.mouse) return dK;   // (mousing: the left hand on a seated body, placed by the correction below)
    // one carry for both hands (the capture's hands keep their own spacing; carrying each onto F / J on its own took 12 cm
    // out of it and laid the hands over each other): the middle of its index fingertips onto our keyboard's home row,
    // MX_SHIFT along the keys
    const mid = MXK.F.map((v, i) => (v + MXK.J[i]) / 2);
    return dKs[side].subVectors(P.kbNode.localToWorld(V(window.__mxShift ?? MX_SHIFT, 0, 0)), toWorld(mid, _c));
  }
  // a finger in a stroke: the clip's own fingertip raised more than 8 mm above its lowest over the last 1.5 s, measured
  // towards the back of the hand (G12's measure of the capture's lifts: median 0.4 s, the longest 1.6 s); while it is
  // up the resolver leaves it as recorded, and settles it onto the key again over 0.15 s once it is down
  const LIFT = {Left: {}, Right: {}};
  function liftedFingers(side, dt) {
    const hand = env.bones[side + "Hand"], wr = hand.getWorldPosition(V()), k2 = S(side, 2, 1).getWorldPosition(V()), k3 = S(side, 3, 1).getWorldPosition(V()), k5 = S(side, 5, 1).getWorldPosition(V());
    const h = k3.clone().sub(wr).normalize(), l = k5.clone().sub(k2); l.addScaledVector(h, -l.dot(h)).normalize();
    let up = h.clone().cross(l).normalize(); if (up.y < 0) up.negate();   // (the back of the hand)
    const out = new Set(), L = LIFT[side], now = (L.t = (L.t || 0) + dt);
    for (let i = 1; i <= 5; i++) { if (!S(side, i, 3)) continue; const d = tipOf(side, i, V()).sub(wr).dot(up), H = L[i] || (L[i] = []);
      H.push([now, d]); while (H.length && H[0][0] < now - 1.5) H.shift(); let lo = 1e9; for (const x of H) lo = Math.min(lo, x[1]);
      if (d - lo > 0.008) out.add(i); }
    // the clip's own drop from the knuckles to the resting fingertips' skin (fingers 2-5 not in a stroke): the hand is held
    // at that height over the caps, so a resting finger touches as recorded and a stroke stays up (followed over ~1 s)
    let ky = 0, kn = 0; for (let i = 2; i <= 5; i++) { const k = S(side, i, 1); if (k) { ky += k.getWorldPosition(_s).y; kn++; } }
    let drop = 0, dn = 0; for (let i = 2; i <= 5; i++) if (S(side, i, 3) && !out.has(i)) { drop += ky / kn - (tipOf(side, i, _e).y - FING_R); dn++; }
    // (the drop's bounds: a finger's length; the capture's own drop is 5.4-6.8 cm, steady)
    if (dn) { M.kkRaw = M.kkRaw || {}; M.kkRaw[side] = drop / dn; const want = Math.max(0.015, Math.min(0.09, drop / dn)); M.kk[side] += (want - M.kk[side]) * (1 - Math.exp(-dt / 1.0)); }   // (?debug: kkRaw, unclamped)
    M.lifted = M.lifted || {}; M.lifted[side] = [...out];   // (?debug)
    return out;
  }
  M.kk = {Left: KEY_KNUCKLE, Right: KEY_KNUCKLE};
  // the slow F / J correction, one per context: mousing (the left hand on a seated body) and typing kept apart, so one's
  // never carries into the other (it did: mousing's +10 cm on the left hand pushed the typing hands across each other)
  M.kOff = {type: {Left: V(), Right: V()}, mouse: {Left: V(), Right: V()}};
  const kCtx = () => M.w.type >= M.w.mouse ? "type" : "mouse";
  M.kUp = {Left: 0, Right: 0};   // (kUp: the hand raised where a finger could not clear the caps even straightened)
  function keyOn(side, w, dt) {                              // a hand onto the keys: placed, the arm out of the desk, every finger on the caps
    const ko = M.kOff[kCtx()][side];
    pin(side, keyDelta(side).clone().add(MX() && kCtx() === "type" ? V() : ko), w, keyFit(side));   // (a capture's typing: carried by its own measured means only)
    if (P.kbNode && w > 0.9 && !(MX() && M.w.type >= M.w.mouse)) {   // the index fingertip's drift from F / J, taken out over ~1 s (not for a capture: its hands travel)
      const e = keyTarget(side).sub(tipOf(side, 2, V())).setY(0); ko.addScaledVector(e, Math.min(1, dt / 0.8));
      const L = ko.length(); if (L > 0.15) ko.multiplyScalar(0.15 / L);
    }
    const lifted = liftedFingers(side, dt);
    let left = layFingers(side, "keys", w, 1, 0.15, dt, lifted);
    // a finger still in a key even straightened: the hand up by as much and the fingers solved again in this frame (twice
    // at most: next frame was too late while the hand travelled, a fingertip stayed 5 mm in a cap); else back down slowly
    for (let pass = 0; pass < 2 && left < -0.0005; pass++) {
      M.kUp[side] = Math.min(0.03, M.kUp[side] - left);
      for (let i = 1; i <= 5; i++) for (let j = 1; j <= 3; j++) { const b = S(side, i, j), r = b && GR.get(b); if (r) { b.quaternion.copy(r.pre); b.updateMatrixWorld(true); GR.delete(b); } }
      pin(side, V(), w, keyFit(side)); left = layFingers(side, "keys", w, 1, 0.15, dt, lifted);
    }
    if (left >= -0.0005) M.kUp[side] = Math.max(0, M.kUp[side] - 0.002 * dt * 30 * 0.25);
  }
  // ---------- typing: the owner's own hands (room/mh/owner_typing.json, tools/motion/owner_typing.py: MediaPipe landmarks
  // from his overhead video). Per frame, at 0.75x his speed, looped with a crossfade: every finger joint's bend and spread,
  // the thumb's, each hand's turn over the keys and its travel. The capture's body stays; the arms reach his wrists.
  const OT_REST = 0.2, OT_DRIFT = 0.35;   // (mousing: the resting left hand runs through his take at a fifth of the typing's pace)
  const OT = {json: null, t: 0, tr: 0, kk: {Left: 0.02, Right: 0.02}, hinge: {}, mean2: {}, acc: {}, thumbIn: {Left: 0, Right: 0}, roll: {Left: 0, Right: 0}};
  fetch("room/mh/owner_typing.json").then(r => r.json()).then(j => { OT.json = j; }).catch(() => {});
  function otFrame(side, t = OT.t) {                         // the take at t, linear between its frames
    const J = OT.json, H = J.hands[side], n = J.frames, x = ((t * J.fps) % n + n) % n, i0 = Math.floor(x), i1 = (i0 + 1) % n, u = x - i0;
    const mix = (a, b) => Array.isArray(a) ? a.map((v, k) => v + (b[k] - v) * u) : a + (b - a) * u;
    const o = {}; for (const k of ["G", "reach", "thumb", "yaw", "roll", "pitch", "wrist", "tip2"]) o[k] = mix(H[k][i0], H[k][i1]); return o;
  }
  function aimSeg(b, cur, want, weight) {                    // a bone turned (in the world) so its segment's line goes from cur to want
    if (cur.dot(want) > 0.99999) return; _q.setFromUnitVectors(cur, want); _q.slerp(_ID, 1 - weight);
    b.parent.getWorldQuaternion(_pq); b.quaternion.copy(_pq.invert().multiply(b.getWorldQuaternion(_wq).premultiply(_q))); b.updateMatrixWorld(true);
  }
  // the thumb: its metacarpal turned in the palm plane to the take's angle from the index metacarpal's line (its lift out
  // of the plane kept), then its MCP and IP bends toward the palm (absolute: they never add up)
  const _twr = V(), _tk2 = V(), _th = V(), _tl = V(), _tn = V(), _tim = V(), _td = V(), _tin = V(), _tp = V(), _ts = V(), _tax = V(), _tw = V(), _thq = new THREE.Quaternion();   // (otThumb's, once a pin iteration)
  function otThumb(side, T, weight) {
    const hand = env.bones[side + "Hand"], b1 = S(side, 1, 1), b2 = S(side, 1, 2), b3 = S(side, 1, 3); if (!b1 || !b2 || !b3) return;
    const wr = hand.getWorldPosition(_twr), k2 = S(side, 2, 1).getWorldPosition(_tk2), h = S(side, 3, 1).getWorldPosition(_th).sub(wr).normalize();
    const l = S(side, 5, 1).getWorldPosition(_tl).sub(k2); l.addScaledVector(h, -l.dot(h)).normalize();
    const n = _tn.copy(h).cross(l).normalize(); if (n.y > 0) n.negate();   // (the palm's side: down)
    const im = _tim.copy(k2).sub(wr); im.addScaledVector(n, -im.dot(n)).normalize();   // (the index metacarpal's line, in the palm plane)
    const seg = (b, c, out) => (c ? c.getWorldPosition(out) : tipOf(side, 1, out)).sub(b.getWorldPosition(_a)).normalize();
    const d = seg(b1, b2, _td), up = d.dot(n), inPl = _tin.copy(d).addScaledVector(n, -up), L = inPl.length(); if (L < 1e-6) return;
    const sg = Math.sign(_tw.copy(im).cross(inPl).dot(n)) || 1;   // (the side the thumb lies on, from the index line)
    aimSeg(b1, d, _tw.copy(im).applyAxisAngle(n, sg * T[0] * Math.PI / 180).multiplyScalar(L).addScaledVector(n, up).normalize(), weight);
    // the bends about the thumb's own hinge: the plane its joints bend in as the capture holds it (kept in the hand's frame;
    // a thumb bends across the palm, not down like the fingers)
    const hq = hand.getWorldQuaternion(_thq);
    [[b1, b2, b2, b3, T[1], 0], [b2, b3, b3, null, T[2], 1]].forEach(([p0, p1, b, c, a, k]) => {
      const prev = seg(p0, p1, _tp), hinge = OT.hinge[side] && OT.hinge[side][k];
      const ax = hinge ? _tax.copy(hinge).applyQuaternion(hq) : _tax.copy(prev).cross(n).normalize(); ax.addScaledVector(prev, -ax.dot(prev)); if (ax.lengthSq() < 1e-8) return; ax.normalize();
      aimSeg(b, seg(b, c, _ts), _tw.copy(prev).applyAxisAngle(ax, a * Math.PI / 180), weight);
    });
  }
  function otHinges(side) {                                  // (from the clip's pose, before the page turns anything: per joint, in the hand's frame)
    const hand = env.bones[side + "Hand"], hqi = hand.getWorldQuaternion(new THREE.Quaternion()).invert(), p = [1, 2, 3].map(j => S(side, 1, j).getWorldPosition(V()));
    p.push(tipOf(side, 1, V())); const d = [0, 1, 2].map(k => p[k + 1].clone().sub(p[k]).normalize());
    return [0, 1].map(k => { const ax = d[k].clone().cross(d[k + 1]); return ax.length() > 0.05 ? ax.normalize().applyQuaternion(hqi) : null; });   // (null: too straight to tell)
  }
  // the hand's turn: wrist->middle knuckle along his forward line turned by the take's yaw (+ = toward his right) and
  // pitch (knuckles up); rolled thumb side up only as far as its thumb needs to stay out of the space bar (at most 30 deg,
  // followed over frames). (The take's roll, read off the palm's foreshortening, said 42 deg for his right hand: on a
  // flat keyboard that hung its index 4.5 cm over the keys with the little finger in them, while both type. The
  // foreshortening is not only roll.)
  function otAim(side, f0) {
    const f = fwdV(), rt = _oart.set(-f.z, 0, f.x), y = f0.yaw * Math.PI / 180, p = f0.pitch * Math.PI / 180, r = OT.roll[side];   // (roll: by contact, see below)
    const hw = _oahw.copy(f).multiplyScalar(Math.cos(y)).addScaledVector(rt, Math.sin(y));
    const lw = _oal1.copy(rt).multiplyScalar(Math.cos(y)).addScaledVector(f, -Math.sin(y)); if (side === "Left") lw.negate();
    lw.multiplyScalar(Math.cos(r)).addScaledVector(_up1, -Math.sin(r));
    hw.multiplyScalar(Math.cos(p)).addScaledVector(_up1, Math.sin(p));
    return [hw, lw];
  }
  // a resting finger onto the cap under it by its knuckle bend alone (at most 12 deg either way; the take's middle and end
  // joints kept); a finger in a stroke only opened out of a key
  const OTS = {Left: {}, Right: {}};   // (each resting finger's last knuckle bend: the next frame's warm start)
  function otSettle(side, G, lifted, weight, T0, thumbGap = 0) {   // thumbGap: the thumb's margin over the height map (m)
    let worst = 0;
    for (const i of [2, 3, 4, 5]) { if (!S(side, i, 1)) continue; const g = G[i];
      const gp = () => Math.min(gap(side, "keys", i, 2), gap(side, "keys", i, 1));
      if (lifted.has(i)) { if (gp() >= 0) continue; let lo = 0, hi = 1;
        for (let it = 0; it < 8; it++) { const m = (lo + hi) / 2; curl(side, {[i]: g.map((x, k) => k < 3 ? x * m : x)}, weight); if (gp() >= 0) lo = m; else hi = m; }
        curl(side, {[i]: g.map((x, k) => k < 3 ? x * lo : x)}, weight); worst = Math.min(worst, gp()); continue; }
      const set = dm => curl(side, {[i]: [Math.max(-5, g[0] + dm), g[1], g[2], g[3]]}, weight), TGT = 0.001;   // (never bent back past 5 deg at the knuckle)
      const memo = OTS[side], c = memo[i];
      // warm start (G24 F9: each finger's search cost ~12 skin tests a frame): last frame's bend first, kept while the
      // fingertip still touches (0.5-2 mm over its cap); else a narrow bracket round it; else the full search
      if (c != null) { set(c); const g0 = gp();
        if (g0 >= TGT - 0.0005 && g0 <= TGT + 0.001) { worst = Math.min(worst, g0); continue; }
        const lo2 = Math.max(-12, c - 3), hi2 = Math.min(12, c + 3); set(lo2); const a = gp() > TGT; set(hi2); const b = gp() <= TGT;
        if (a && b) { let lo = lo2, hi = hi2; for (let it = 0; it < 5; it++) { const m = (lo + hi) / 2; set(m); if (gp() > TGT) lo = m; else hi = m; }
          set(lo); memo[i] = lo; worst = Math.min(worst, gp()); continue; } }
      set(-12); if (gp() < TGT) { memo[i] = -12; worst = Math.min(worst, gp()); continue; }   // (down on the cap even opened: as open as it goes)
      set(12); if (gp() > TGT) { memo[i] = 12; continue; }                                  // (out of reach: the most it bends)
      let lo = -12, hi = 12; for (let it = 0; it < 9; it++) { const m = (lo + hi) / 2; set(m); if (gp() > TGT) lo = m; else hi = m; }
      set(lo); memo[i] = lo; worst = Math.min(worst, gp());
    }
    // the thumb, if it would be in the space bar: its metacarpal lifted toward the back of the hand by the least angle that
    // clears it (at most 25 deg), its bends kept. It never raises the hand.
    const b1 = S(side, 1, 1), tg = () => Math.min(gap(side, "keys", 1, 2), gap(side, "keys", 1, 1)) - thumbGap;
    if (b1 && tg() < 0) { const q0 = [1, 2, 3].map(j => S(side, 1, j).quaternion.clone());
      const n = (() => { const hand = env.bones[side + "Hand"], wr = hand.getWorldPosition(V()), h = S(side, 3, 1).getWorldPosition(V()).sub(wr).normalize(), l = S(side, 5, 1).getWorldPosition(V()).sub(S(side, 2, 1).getWorldPosition(V())); const nn = h.cross(l).normalize(); return nn.y > 0 ? nn.negate() : nn; })();
      const lift = a => { [1, 2, 3].forEach((j, k) => { const b = S(side, 1, j); b.quaternion.copy(q0[k]); b.updateMatrixWorld(true); });
        const d = S(side, 1, 2).getWorldPosition(V()).sub(b1.getWorldPosition(V())).normalize(), ax = d.clone().cross(n).normalize();
        aimSeg(b1, d, d.clone().applyAxisAngle(ax, -a), weight); };
      const MAX = 25 * Math.PI / 180;
      lift(MAX); OTS[side].th = MAX;
      if (tg() >= 0) { let lo = 0, hi = MAX; for (let it = 0; it < 8; it++) { const m = (lo + hi) / 2; lift(m); if (tg() < 0) lo = m; else hi = m; } lift(hi); OTS[side].th = hi; }
      void T0; } else OTS[side].th = 0;
    OT.thumbIn[side] = b1 ? Math.min(0, tg()) : 0;   // (still in at the most: the hand rolls thumb side up next frame)
    return worst;
  }
  // each finger's curl scaled (its bends kept in proportion) until its wrist->fingertip, seen square to the palm, is the
  // take's share of the palm's length (the take's bends are right in their timing, not in their depth: see the builder)
  const OTK = {Left: [1, 1, 1, 1], Right: [1, 1, 1, 1]};
  function otReach(side, G, reach, weight) {
    if (!S(side, 2, 1) || !S(side, 3, 1) || !S(side, 5, 1)) return;
    const hand = env.bones[side + "Hand"], wr = hand.getWorldPosition(V()), k3 = S(side, 3, 1).getWorldPosition(V()), h = k3.clone().sub(wr).normalize();
    const l = S(side, 5, 1).getWorldPosition(V()).sub(S(side, 2, 1).getWorldPosition(V())); l.addScaledVector(h, -l.dot(h)).normalize();
    const n = h.clone().cross(l).normalize(), palm = k3.distanceTo(wr);
    const flat = v => v.addScaledVector(n, -v.dot(n)).length();
    [2, 3, 4, 5].forEach((i, k) => { if (!S(side, i, 1)) return; const g = G[i];
      const at = m => { curl(side, {[i]: [g[0] * m, g[1] * m, g[2] * m, g[3]]}, weight); return flat(tipOf(side, i, V()).sub(wr)) / palm; };
      let lo = 0, hi = 1.3; if (at(lo) <= reach[k]) hi = 0; else if (at(hi) >= reach[k]) lo = hi;
      else for (let it = 0; it < 10; it++) { const m = (lo + hi) / 2; if (at(m) > reach[k]) lo = m; else hi = m; }
      OTK[side][k] = Math.max(OT_KMIN, (lo + hi) / 2); at(OTK[side][k]); });
  }
  // (a floor on the curl, half the take's bends: our fingers are shorter against the palm than his, so his reach alone
  // straightened ours into planks - the right hand's PIP read 0 - and the skin at the knuckles, modelled curled, stretched:
  // triangles over 2.5x bind on the right hand per frame 16 at 0.35, 12 at 0.6, 4 at 0.85, the capture's claw 3)
  const OT_KMIN = 0.5;


  const otScaled = (side, G) => { const o = {}; [2, 3, 4, 5].forEach((i, k) => { const m = OTK[side][k]; o[i] = [G[i][0] * m, G[i][1] * m, G[i][2] * m, G[i][3]]; }); return o; };
  // at rest (mousing): his take on its own slow clock, his index fingertip's track centred on F and a third of its travel
  // kept round it (his own place, 3.5 cm left of the middle, and his full 8 cm travel put our little finger off the
  // keyboard's left edge)
  function otRestFrame(side) {
    const fr = otFrame(side, OT.tr);
    if (!OT.mean2[side]) { const T2 = OT.json.hands[side].tip2; OT.mean2[side] = [0, 1].map(k => T2.reduce((a, v) => a + v[k], 0) / T2.length); }
    const m = OT.mean2[side]; fr.tip2 = [(fr.tip2[0] - m[0]) * OT_DRIFT - FJ, (fr.tip2[1] - m[1]) * OT_DRIFT]; return fr;
  }
  const otBlend = (a, b, u) => { const o = {}; for (const k in a) o[k] = Array.isArray(a[k]) ? a[k].map((v, i) => v + (b[k][i] - v) * u) : a[k] + (b[k] - a[k]) * u; return o; };
  function ownerKeys(side, w, dt, o = {}) {                  // o.mix: the share at rest (mousing: slow, every finger settled on its cap)
    if (!S(side, 2, 1) || !S(side, 3, 1) || !S(side, 5, 1) || !env.bones[side + "Hand"]) return;   // (another rig: degrade, never throw every frame)
    grKeepHand(side);
    if (!OT.hinge[side]) OT.hinge[side] = otHinges(side);   // (normally set at load from the typing clip: otHingesAtLoad)
    const mix = Math.max(0, Math.min(1, o.mix || 0)), rest = mix >= 0.5;
    const f0 = mix <= 0 ? otFrame(side, OT.t) : mix >= 1 ? otRestFrame(side) : otBlend(otFrame(side, OT.t), otRestFrame(side), mix);
    const G = {2: f0.G.slice(0, 4), 3: f0.G.slice(4, 8), 4: f0.G.slice(8, 12), 5: f0.G.slice(12, 16)};
    // placed by the index fingertip (his sit 7 cm apart, about F-J); the wrist where the arm and the hand's turn put it
    const f = fwdV(), rt = V(-f.z, 0, f.x), home = P.kbNode.localToWorld(V(0, 0, 0)), at = p => home.clone().addScaledVector(rt, p[0]).addScaledVector(f, p[1]);
    const want = at(f0.wrist), tipWant = at(f0.tip2), hand = env.bones[side + "Hand"];
    const fit = () => { let y = 0, n = 0, top = -1e9; for (let i = 2; i <= 5; i++) { const k = S(side, i, 1); if (!k) continue; k.getWorldPosition(_s); y += _s.y; top = Math.max(top, under("keys", _s)); n++; }
      return tipWant.clone().sub(tipOf(side, 2, _g)).setY(Math.max(top + OT.kk[side] + M.kUp[side] - y / n, knuckleNeed(side, "keys"))); };
    // the searches (each finger's reach and its bend onto the cap, the thumb's lift) at 15 Hz; the frames between reuse
    // their results (G24 F9: the hands cost ~26 ms a frame here under software GL, most of it in these searches)
    OT.acc[side] = (OT.acc[side] || 0) + dt; const full = OT.acc[side] >= 1 / 15 - 1e-6 || !OTS[side].done; if (full) { OT.acc[side] = 0; OTS[side].done = true; }
    const solve = () => { pin(side, want.clone().sub(hand.getWorldPosition(V())).setY(0), w, fit, {iters: 5, aim: () => otAim(side, f0), post: () => { curl(side, otScaled(side, G), w); otThumb(side, f0.thumb, w); }});
      if (full) otReach(side, G, f0.reach, w); return otScaled(side, G); };
    let Gs = solve();
    let lifted = liftedFingers(side, dt);
    if (rest) { lifted = new Set(); M.lifted[side] = []; }   // (at rest: no strokes)
    // the hand's height: its own knuckle->fingertip drop (resting fingers; all four if every one is up), followed over 0.3 s
    let ky = 0, kn = 0, drop = 0, dn = 0; for (let i = 2; i <= 5; i++) { const k = S(side, i, 1); if (k) { ky += k.getWorldPosition(_s).y; kn++; } }
    for (const all of [false, true]) { if (dn) break; for (let i = 2; i <= 5; i++) if (S(side, i, 3) && (all || !lifted.has(i))) { drop += ky / kn - (tipOf(side, i, _e).y - FING_R); dn++; } }
    if (dn && kn) OT.kk[side] += (Math.max(0.005, Math.min(0.09, drop / dn)) - OT.kk[side]) * (1 - Math.exp(-dt / 0.3));   // (no end bones: kept, never NaN)
    // (the thumb's margin over the height map: 1 mm typing, 1.5 at rest; the map misses the caps' steep sides, and with none
    // the thumb read 2.1 mm into the space bar on the mesh)
    let left = otSettle(side, Gs, lifted, w, f0.thumb, 0.001 + 0.0005 * mix);
    if (left < -0.0005) { M.kUp[side] = Math.min(0.03, M.kUp[side] - left); Gs = solve(); left = otSettle(side, Gs, lifted, w, f0.thumb, 0.001 + 0.0005 * mix); }   // (one retry pass: G24 F9)
    if (left >= -0.0005) M.kUp[side] = Math.max(0, M.kUp[side] - 0.002 * dt * 30 * 0.25);
    OT.roll[side] = OT.thumbIn[side] < -0.0005 ? Math.min(0.52, OT.roll[side] + 0.05 * dt * 30) : Math.max(0, OT.roll[side] - 0.004 * dt * 30);
    M.ot = M.ot || {}; M.ot[side] = {t: +OT.t.toFixed(3), lifted: [...lifted], k: OTK[side].map(x => +x.toFixed(2)), kk: +OT.kk[side].toFixed(3), roll: +(OT.roll[side] * 57.3).toFixed(1), thumbIn: +(OT.thumbIn[side] * 1000).toFixed(1)};   // (?debug)
  }
  // a separate room mouse follows the recorded right palm (60% from the wrist to the middle knuckle) while he holds it
  function follow() {
    const hand = env.bones.RightHand, kn = S("Right", 3, 1);
    if (!hand || !kn || M.w.mouse <= 0.97) { M.grab = null; return; }   // (once the hand is on it)
    hand.getWorldPosition(_hp).lerp(kn.getWorldPosition(_a), 0.6);
    if (!M.grab) M.grab = P.mouseHome.clone().sub(_hp).setY(0);
    const H0 = P.mouseHome, cl = v => Math.max(-0.06, Math.min(0.06, v));   // (it stays on the pad: within 6 cm of home)
    P.mouseNode.position.set(H0.x + cl(_hp.x + M.grab.x - H0.x), H0.y, H0.z + cl(_hp.z + M.grab.z - H0.z)); P.mouseNode.updateMatrixWorld(true);
  }
  // seated at the desk: each mode's clip has its hips (at its first frame) on a seat point in the chair's own frame
  // (SEAT_AT: across, forward; the chair's front is its -z), and he and the chair roll to where that capture puts his hands:
  // the clip's keyboard (typing) or mouse (mousing) onto the room's, along the way he faces. Watching (room_seated_idle:
  // hands on the armrests and knees) needs nothing on the desk, so he stays where the last mode left him (snapped in:
  // where the mouse would put him). A book or a phone on his lap: 0.45 m back, clear of the desk.
  // SEAT_AT, swept in the room (the page's penetration() every 0.25 s over 10 s, and contact_pass.mjs): how far forward
  // of the chair's pivot each clip's hips sit with nothing of him in the chair. room_seated_idle: clear from 2 to 6.5 cm
  // (closer, its calves catch the cushion's front edge); 5.5 cm also clears the sit-down, whose hips land 2.7 cm further
  // back than they rest. The mouse clip: clear from 3.5 cm (main's 0.6 cm puts its left calf on the front edge); the
  // typing clip, the same family, with it (docs/design/mixamo)
  // The rare events, swept the same way over the whole event (the page's penetration() every 0.1 s): Scared clear from
  // 9.5 cm to at least 13.5 cm (closer, his left calf catches the cushion's front edge as he springs up), Angry_Gesture
  // from 7.5 cm (closer, his left thigh presses into the cushion as he leans in); Standing_Clap is clear where he sits to
  // watch
  // (mousing here plays room_seated_idle's body: its seat point, as desk_watch's; main's -0.045 was for desk_mouse_ik)
  const SEAT_AT = {desk_type: [0, -0.045], desk_mouse: [0, -0.055], desk_watch: [0, -0.055], rare_scared: [0, -0.115], rare_angry: [0, -0.085], ...(env.seatAt || {})};
  SEAT_AT.type_in = SEAT_AT.type_in || SEAT_AT.desk_type; SEAT_AT.type_out = SEAT_AT.type_out || SEAT_AT.desk_type;
  const MOUSE_HIPS_BACK = 0.389;                              // (the old mouse clip's hips behind the mouse, measured in the page)
  // the nearest the turn on the spot before the sit-down clears the turned seat (the walking scene swept: 0.45 m caught
  // his right foot, 0.52 m his toes, 0.60 m clear)
  const TURN_CLEAR = 0.60;
  const _f = V(), _st = V();
  // ---------- rare events at the desk (room_build/kimodo/mixamo_chains.json "rare"): the whole capture, seated -> up -> seated
  // (Scared, Standing_Clap) or seated throughout (Angry_Gesture). The chair moves, not the performance: before it he rides the
  // chair back as far as the capture needs (M.rare[k].back), the capture plays whole, and after it he rides back in.
  // mh.rare("scared" | "angry" | "clap") starts one (the page's scheduler: rare, never twice close together) ----------
  const RARE = {scared: "room_mx_scared", angry: "room_mx_angry_gesture", clap: "room_mx_standing_clap"};
  M.rare = {};
  // how far he and the chair ride back for a capture: its parts (hands, forearms, knees, feet, chest, head; sampled every
  // 0.1 s, in the body's frame from its first frame's hips) against the room in front of the seat (free(): rays toward
  // the desk across his width at each height, once), the deepest any part would go past it, plus 3 cm
  const PARTS = [["LeftHand", 0.05], ["RightHand", 0.05], ["LeftForeArm", 0.05], ["RightForeArm", 0.05], ["LeftLeg", 0.08], ["RightLeg", 0.08],
    ["LeftFoot", 0.05], ["RightFoot", 0.05], ["LeftToeBase", 0.05], ["RightToeBase", 0.05], ["Spine", 0.16], ["Head", 0.12]];
  function parts(clip) {
    const s = sampler(clip), h0 = s(0).hips, B = env.boy, out = [];
    for (let t = 0; t <= clip.duration + 1e-6; t += 0.1) { s(Math.min(t, clip.duration));
      for (const [n, r] of PARTS) { const b = env.bones[n]; if (!b) continue; const p = B.worldToLocal(b.getWorldPosition(V())); out.push([p.x - h0.x, p.y, p.z - h0.z, r]); } }
    s.done(); return out;
  }
  const FREE = {lat: [-0.35, -0.25, -0.15, -0.05, 0.05, 0.15, 0.25, 0.35], ys: Array.from({length: 20}, (_, i) => 0.03 + 0.05 * i)};
  function free(S, f, l) {                                   // [lateral][height] -> the free depth (m) in front of S along f
    const room = env.room && env.room(); if (!room) return null;
    const ch = env.chairNode && env.chairNode(), solid = [];                // (the room's furniture, not the chair he sits on)
    room.traverse(o => { if (!o.isMesh || !o.visible) return; for (let p = o; p; p = p.parent) if (p === ch) return; solid.push(o); });
    if (SV) {                                                // (the desk states: the things on the desk too (the monitor, the lamp), and the
      const mine = o => { for (let p = o; p; p = p.parent) if (p === env.boy || p === ch || p === room) return true; return false; };   // room's trees built
      env.scene.traverse(o => { if (!o.isMesh || !o.visible || o.isSkinnedMesh || mine(o)) return;                                      // anew where the
        const bb = new THREE.Box3().setFromObject(o), sz = bb.getSize(V()); if (Math.max(sz.x, sz.y, sz.z) < 2 && bb.max.y < 2.5) solid.push(o); });   // the
      for (const m of solid) if (m.geometry.computeBoundsTree && !m.geometry.boundsTree) m.geometry.computeBoundsTree();             // keyboard's cut, if dropped)
    }
    const ray = new THREE.Raycaster(), o = V(), d = V(f.x, 0, f.z), side = solid.map(m => m.material.side);
    solid.forEach(m => { m.material.side = THREE.DoubleSide; });          // (a face seen from behind is still the desk)
    const D = FREE.lat.map(x => FREE.ys.map(y => { o.set(S.x + l.x * x, env.F + y, S.z + l.z * x); ray.set(o, d); ray.far = 1.5;
      const h = ray.intersectObjects(solid, false)[0]; return h ? h.distance : 1.5; }));
    // the desk's top is a thin plate (3 mm): where it starts in front of him, and its height, by rays down every 2 cm
    const dn = V(0, -1, 0); D.top = FREE.lat.map(x => { for (let t = 0; t <= 1.2; t += 0.02) {
      o.set(S.x + l.x * x + f.x * t, env.F + 1.2, S.z + l.z * x + f.z * t); ray.set(o, dn); ray.far = 0.65;
      const h = ray.intersectObjects(solid, false)[0]; if (h && h.point.y > env.F + 0.6) return [t, h.point.y - env.F]; } return [1.5, 0]; });
    solid.forEach((m, i) => { m.material.side = side[i]; }); return D;
  }
  function backFor(R, k) {                                   // the ride back (m) this capture needs, from where he sits now
    const ch = env.chairNode && env.chairNode(); if (!ch) return 0;
    const ry = env.boy.rotation.y, f = V(Math.sin(ry), 0, Math.cos(ry)), l = V(Math.cos(ry), 0, -Math.sin(ry));
    const at = (window.__seatAt && window.__seatAt["rare_" + k]) || SEAT_AT["rare_" + k] || SEAT_AT.desk_watch;
    ch.updateMatrixWorld(true); const S = ch.localToWorld(V(at[0], 0, at[1]));
    const D = free(S, f, l); if (!D) return 0.3;
    let need = 0;
    for (const [x, y, z, r] of R.pts) {
      const i = FREE.lat.reduce((b, v, j) => Math.abs(v - x) < Math.abs(FREE.lat[b] - x) ? j : b, 0), [te, ty] = D.top[i];
      if (Math.abs(ty - y) <= r) need = Math.max(need, z + r - te);              // (crossing the desk's top: its front edge)
      for (let j = 0; j < FREE.ys.length; j++) if (Math.abs(FREE.ys[j] - y) <= r + 0.025) need = Math.max(need, z + r - D[i][j]); }
    return need > 0 ? need + 0.03 : 0;
  }
  const RIDE = 1.0;                                           // (s) riding the chair back before, and in after
  const EV_FADE = 0.8;                                        // (s) into and out of the capture: the hands go from the armrests to the thighs (42-49 deg, chain_joins.py)
  function rare(k) {
    const R = M.rare[k], a = M.actions["rare_" + k], st = env.state(); if (!R || !a || M.ev || st.at !== "desk" || st.step) return false;
    M.ev = {k, a, t: 0, R: {...R, back: backFor(R, k)}}; M.log.push([+st.T.toFixed(2), "rare:" + k + " back " + M.ev.R.back.toFixed(3)]); return true;
  }
  function rareStep(dt) {                                     // its phases: ride back, the capture, ride in
    const E = M.ev; if (!E) { M.evOff = 0; return; }
    // (the desk states' events, desk_states.js: no ride when the take needs no room (ride 0), a window of a long take
    // (from, R.dur), and on out of it into the slot the picker chose (then()); the page's rare() as before)
    const RD = E.ride ?? RIDE;
    E.t += dt; const t = E.t, D = E.R.dur, end = RD + D;
    M.evOff = E.R.back * (t < RD ? sstep(0, RD, t) : t < end ? 1 : 1 - sstep(end, end + RD, t));
    const EF = E.fade || EV_FADE;                             // (the desk states' takes fade slower: their poses lie far apart)
    if (t >= RD && !E.on) { E.on = true; E.a.reset(); E.a.time = E.from || 0; E.a.setEffectiveWeight(1); E.a.fadeIn(EF).play(); const cur = env.state().current; if (cur && cur !== E.a) cur.fadeOut(EF); env.setCurrent(E.a); }
    if (E.on && !E.off && t >= end - EF) { E.off = true; const n = E.then && E.then(), w = n ? n.a : M.actions.desk_watch;
      w.reset(); if (n) w.time = n.from; w.setEffectiveWeight(1); w.fadeIn(EF).play(); E.a.fadeOut(EF); env.setCurrent(w);
      for (const k of ["sit", "type"]) env.actions[k] = w; }
    if (t >= end + RD) { E.a.stop(); M.ev = null; }
  }
  // ---------- the desk states (room.html?char=mixamo&anim=sova; desk_states.js decides, this plays) ----------
  // In desk_watch (a video, a page, the opponent's turn at chess) the seated loop is one of several: idle variants, his
  // attention on the monitor, a small gesture, now and then a reaction to what the page received. Loops crossfade
  // (SV_FADE) each from a random phase of its clip, for a random hold; a gesture or a reaction plays once through the
  // rare events' path (rareStep): the chair rides back first by what the take needs (backFor; no ride if it needs none),
  // and out of it he crossfades into the next loop the picker chose. Off desk_watch (typing, the mouse) the page's modes
  // play as before; the default page never loads any of this.
  const SV_FADE = 0.8, SV_LOOK = 2.5, SV_MIN = 1.5, SV_EV_FADE = 1.3, SV_REACT_BACK = 0.12;   // (s; SV_EV_FADE: into and out of a gesture or a reaction - 0.8 s from the hands on his thighs to his arms crossed moved a fingertip 107-187 mm in a frame)          // (s) a loop's crossfade; a look at the board; the least a loop holds before an event
  let SV = null;
  async function svLoad(make, bodyHips) {
    const D = await import("./desk_states.js"), dir = env.clipDir || "room/mh";
    let named = {}, seats = {}, once = [];                   // (slot -> its own clip's file; a list: <slot>.glb)
    try { const r = await fetch(`${D.DIR}/index.json`); if (r.ok) { const j = await r.json(); const c = j.clips || [];
      named = Array.isArray(c) ? Object.fromEntries(c.map(n => [n, n + ".glb"])) : c; seats = j.seat || {}; once = j.once || []; } } catch (e) { /* stand-ins */ }
    for (const n of ["finger1-4", "finger3-4", "finger5-4"]) for (const sd of ["L", "R"]) if (env.bones[`${n}.${sd}`]) PARTS.push([`${n}.${sd}`, 0.02]);   // (the fingertips too: up, a hand reaches 18 cm past the wrist)
    const files = {}, have = [], clipOf = {}, durOf = {}, loops = [];
    for (const [k, f] of [...Object.entries(CL), ...Object.entries(RARE).map(([k, f]) => ["rare_" + k, f])])   // (the clips already loaded: not again)
      if (M.clips[k]) files[`${dir}/${f}.glb`] = Promise.resolve(M.clips[k]);
    const get = f => files[f] || (files[f] = env.load(f).then(g => env.fixClip ? env.fixClip(g.animations[0]) : g.animations[0], () => null));
    for (const [n, sl0] of Object.entries(D.SLOTS)) {
      const own = n in named, sl = own ? {...sl0, span: null, once: sl0.once || once.includes(n), seat: seats[n]} : sl0;   // (its own clip: whole, at its own seat point)
      if (own) D.SLOTS[n] = sl;
      const f = own ? `${D.DIR}/${named[n]}` : sl.standIn ? `${dir}/${sl.standIn}.glb` : null, c0 = f && await get(f); if (!c0) continue;
      const c = c0.clone(); c.name = "sv_" + n; have.push(n); clipOf[n] = f; durOf[n] = c.duration;
      const z = sl.seat; if (z != null) SEAT_AT[(sl.once || sl.span ? "rare_sv_" : "sv_") + n] = [0, z];
      if (sl.once || sl.span) { const k = "sv_" + n, a = M.actions["rare_" + k] = make(c); a.setLoop(THREE.LoopOnce, 1); a.clampWhenFinished = true;
        env.HIPS["rare_" + k] = bodyHips(c); M.rare[k] = {pts: parts(c), dur: c.duration, sv: n}; }
      else { const a = M.actions["sv_" + n] = make(c); a.setLoop(THREE.LoopRepeat, Infinity); env.HIPS["sv_" + n] = bodyHips(c); loops.push("sv_" + n); }
    }
    SV = {D, loops, cur: null, until: 0, since: 0, turnAt: null, look: SV_LOOK, waveUntil: null,   // (waveUntil: a viewers' wave asked for, until when)
      pick: D.createPicker({have, clipOf: n => clipOf[n], durOf: n => durOf[n], rng: env.rng || Math.random})};
    FREE.ys = Array.from({length: 30}, (_, i) => 0.03 + 0.05 * i);   // (the desk states: up to 1.48 m, the monitor's height too)
    SV.pick.S.lastClip = `${dir}/${CL.desk_watch}.glb`;      // (desk_watch's own clip counts as the one just played)
    M.sv = SV;                                                // (?debug; svForce(name): that slot next, as if an event called for it)
    M.svBack = k => { const R = M.rare[k], ch = env.chairNode(), ry = env.boy.rotation.y, f = V(Math.sin(ry), 0, Math.cos(ry)), l = V(Math.cos(ry), 0, -Math.sin(ry));
      const at = (window.__seatAt && window.__seatAt["rare_" + k]) || SEAT_AT["rare_" + k] || SEAT_AT.desk_watch; ch.updateMatrixWorld(true); const S = ch.localToWorld(V(at[0], 0, at[1]));
      const D = free(S, f, l); let need = 0, w = null;
      for (const [x, y, z, r] of R.pts) { const i = FREE.lat.reduce((b, v, j) => Math.abs(v - x) < Math.abs(FREE.lat[b] - x) ? j : b, 0), [te, ty] = D.top[i];
        if (Math.abs(ty - y) <= r && z + r - te > need) { need = z + r - te; w = ["top", x, y, z, te, ty]; }
        for (let j = 0; j < FREE.ys.length; j++) if (Math.abs(FREE.ys[j] - y) <= r + 0.025 && z + r - D[i][j] > need) { need = z + r - D[i][j]; w = ["wall", x, y, z, D[i][j], FREE.ys[j]]; } }
      const ymax = Math.max(...R.pts.map(p => p[1])), zmax = Math.max(...R.pts.map(p => p[2]));
      return {need, w, ymax, zmax, ys: FREE.ys.length, S: S.toArray(), D: D.map(c => c.map(x => +x.toFixed(2))), top: D.top}; };   // (?debug)
    M.svForce = n => { const T = env.state().T; SV.pick.S.at = {gesture: -1e9, react: -1e9}; SV.pick.S.last = SV.pick.S.lastClip = null; SV.pick.S.queue.push({slot: n, T, src: "force"}); SV.until = 0; SV.since = -1e9; };
  }
  function svLoop(p) {                                        // a loop slot: its action, crossfaded in from its phase
    const a = M.actions["sv_" + p.name]; if (!a) return null; return {a, from: p.from};
  }
  function svEvents(st) {                                     // what the page received since the last frame (wherever he is)
    for (const m of env.deskEvents ? env.deskEvents() : []) { const was = SV.pick.chess, r = SV.pick.event(m, st.T);
      if (r && r.wave) SV.waveUntil = st.T + SV.D.KEEP;       // (viewers' waves: a request with a deadline; svWave() starts it the first frame he sits watching)
      const c = SV.pick.chess; if (m && m.type === "chess" && c && c.turn === "his" && (!was || was.turn !== "his")) SV.turnAt = st.T; }
    svWave(st);
  }
  function svWave(st) {                                       // the wave viewers asked for: on top of whatever loop plays, as soon as he sits
    if (SV.waveUntil == null) return;                         // watching (wave() lets it be only then); not by its deadline: it lapses
    if (st.T > SV.waveUntil) { SV.waveUntil = null; return; }
    if (M.wave || M.mode !== "desk_watch" || st.at !== "desk" || st.step || M.ev) return;
    SV.waveUntil = null; M.wave = {t: 0}; M.respond = (M.respond || 0) + 1; M.log.push([+st.T.toFixed(2), "wave <glance"]);
  }
  function svStep(st) {
    const T = st.T;
    if (M.link || M.ev || M.sc) return;
    const life = st.life || {}, mode = life.activity === "play_chess" ? "wait" : "watch";
    if (!SV.cur) { SV.cur = {name: "desk_watch"}; SV.since = T; SV.until = T + 3 + 3 * (env.rng || Math.random)(); return; }   // (the mode's own loop first)
    if (T < SV.until && !(SV.pick.pending(T) && T - SV.since >= SV_MIN)) return;
    const p = SV.pick.next(T, mode); if (!p) { SV.until = T + 2; return; }
    if (p.wave && !M.wave && SV.waveUntil == null) SV.waveUntil = T + 1;   // (the answer to a wave is a wave: asked again, in case the request lapsed while he typed)
    if (p.why === "glance" && !p.wave) M.respond = (M.respond || 0) + 1;   // (an answer to viewers: room/glance_cam.js turns the camera to him; a wave counts itself)
    if (p.once) {                                             // a gesture or a reaction: once, through rareStep, then the next loop
      const k = "sv_" + p.name, R = M.rare[k], a = M.actions["rare_" + k]; if (!R || !a) return;
      // (a reaction rides at least SV_REACT_BACK back: its take's own frames clear the desk, but the crossfade from his hands
      // on his thighs to his arms crossed swept them through the desk's edge, where the desk clearing then swung and flipped)
      const back = Math.max(backFor(R, k), p.kind === "react" ? SV_REACT_BACK : 0), dur = Math.min(R.dur - p.from, p.hold);
      M.ev = {k, a, t: 0, from: p.from, ride: back > 0 ? RIDE : 0, fade: SV_EV_FADE, R: {...R, dur, back}, then: () => { const T2 = env.state().T, q = SV.pick.loop(T2, mode), n = q && svLoop(q);
        SV.cur = n ? {name: q.name} : {name: "desk_watch"}; SV.since = T2; SV.until = T2 + (n ? q.hold : 4); return n; }};
      M.log.push([+T.toFixed(2), "sv:" + p.name + (p.why ? " <" + p.why : "") + " back " + back.toFixed(3)]);
      return;
    }
    const n = svLoop(p), cur = st.current; if (!n || n.a === cur) { SV.until = T + p.hold; return; }   // (already playing: no restart)
    n.a.reset(); n.a.time = n.from; n.a.setEffectiveWeight(1); n.a.fadeIn(SV_FADE).play();
    if (cur && cur !== n.a) cur.fadeOut(SV_FADE); env.setCurrent(n.a);
    for (const k of ["sit", "type"]) env.actions[k] = n.a;   // (the page's play("sit") keeps it)
    SV.cur = {name: p.name}; SV.since = T; SV.until = T + p.hold;
    M.log.push([+T.toFixed(2), "sv:" + p.name + (p.why ? " <" + p.why : "")]); if (M.log.length > 50) M.log.shift();
  }
  function handRoll(m) {                                     // the roll back (m) that puts the clip's keyboard / mouse on the room's
    const ry = env.boy.rotation.y; _f.set(Math.sin(ry), 0, Math.cos(ry)); env.boy.updateMatrixWorld(true);
    if (m === "desk_type") return (M.off || 0) - _k.set(...P.keys.c).sub(toWorld(kbRef(), _c)).dot(_f);
    // mousing: the body is a seated capture with no mouse in it (Mixamo has none) and the contact resolver takes the right
    // arm to the mouse, so he sits where the old mouse clip had his hips: 0.389 m behind the mouse along the way he faces
    if (m === "desk_mouse") { _m.set(P.mouse[0], P.mouse[1], P.mouse[2]);
      return (M.off || 0) - (_m.sub(toWorld(M.mouseHips, _c)).dot(_f) - MOUSE_HIPS_BACK); }
    return null;
  }
  // eating at the desk (room_eat) he leans in over the dish: from the seat the desk modes use, his belly went 3.1 cm into
  // the desk's front edge and the right forearm 2.6 cm (eating_19, once the room's raycasts saw the whole desk)
  const EAT_BACK = env.eatBack ?? 0.05;                       // (per character: room/char_mixamo.js ROOM.eatBack)
  function roll(dt) {
    const lap = M.sc && ["read", "phone", "phone_scroll"].includes(M.sc.k);
    const p = env.boy.position, H = env.HIPS, k = 1 - Math.exp(-dt / 0.35);
    if (M.rollAt && (Math.abs(p.x - M.rollAt[0]) > 1e-6 || Math.abs(p.z - M.rollAt[1]) > 1e-6)) { M.off = 0; M.held = null; }   // (the page placed him anew)
    const ry = env.boy.rotation.y, c = Math.cos(ry), s = Math.sin(ry), ch = env.chairNode && env.chairNode();
    // a desk mode (or watching after one) is placed by its clip; anything else seated (eating: room_eat with the dish) as before
    const desk = !lap && (M.mode || M.held != null);
    let want;
    if (desk) { const hr = handRoll(M.mode) ?? (M.held ?? handRoll("desk_mouse")); if (M.mode && M.mode !== "desk_watch") M.held = hr; want = (hr ?? 0) + (M.evOff || 0); }
    else want = lap ? 0.45 : 0.12 - (env.seatIn || 0);
    if (env.state().current === M.actions.act_eat) want += window.__eatBack ?? EAT_BACK;   // (?debug: __eatBack)   // (eating leans in: 5 cm further from the desk, see EAT_BACK)
    const off = M.off || 0, nxt = off + (want - off) * k, d = nxt - off; M.off = nxt;
    if (ch && Math.abs(d) > 1e-6) { ch.position.x += -s * d; ch.position.z += -c * d; ch.updateMatrixWorld(true); }   // (back: against the way he faces)
    if (ch && desk) {                                        // his root: each mode's hips on its seat point, blended as the clips are
      ch.updateMatrixWorld(true); let tx = 0, tz = 0, W = 0;
      for (const m of ["desk_type", "desk_mouse", "desk_watch", "type_in", "type_out", ...Object.keys(M.rare).map(k => "rare_" + k), ...(SV ? SV.loops : [])]) {
        const a = M.actions[m], w = a && a.isRunning() ? a.getEffectiveWeight() : 0; if (w < 1e-3) continue;   // (an action never played reports weight 1)
        const hm = H[m], at = (window.__seatAt && window.__seatAt[m]) || SEAT_AT[m] || SEAT_AT.desk_watch; ch.localToWorld(_st.set(at[0], 0, at[1]));
        tx += w * (_st.x - (hm[0] * c + hm[2] * s)); tz += w * (_st.z - (-hm[0] * s + hm[2] * c)); W += w; }
      if (W > 0.5) { p.x = tx / W; p.z = tz / W; } else if (Math.abs(d) > 1e-6) { p.x += -s * d; p.z += -c * d; }   // (no desk clip: he goes with the chair)
    } else if (Math.abs(d) > 1e-6) { p.x += -s * d; p.z += -c * d; }
    M.rollAt = [p.x, p.z];
  }

  // ---------- getting on and off the chair and the bed: the room clips, inside the page's own pose steps ----------
  // The page moves his hips along keyed paths between two poses (posePose); here the matching stretch of a room clip
  // plays instead, its time following the step's progress, placed rigidly on the chair or the bed (its root on the
  // floor), and it hands back to the page's poses at both ends (the first and last 15 % blend).
  const sstep = (a, b, x) => { const u = Math.min(1, Math.max(0, (x - a) / (b - a))); return u * u * (3 - 2 * u); };
  const angLerp = (a, b, k) => a + Math.atan2(Math.sin(b - a), Math.cos(b - a)) * k;
  function chairPlace(off, face, at) {                       // the root for a clip whose seat centre is at off (x, z), on the room's chair
    const ch = env.chairNode && env.chairNode(); if (!ch) return null;   // (face: the way the seated clip faces, in its frame; +z if not given;
    ch.updateMatrixWorld(true); const p = at ? ch.localToWorld(V(at[0], 0, at[1])) : ch.getWorldPosition(V()), cry = ch.rotation.y;   // at: the seat point in the chair's frame, else its pivot)
    let r = Math.atan2(-Math.sin(cry), -Math.cos(cry));                 // the way a person on it faces
    if (face != null) r = face - Math.atan2(Math.cos(r), Math.sin(r));   // (a local direction at angle a ends at a - ry in the room)
    const c = Math.cos(r), s = Math.sin(r);
    return {ry: r, x: p.x - (off[0] * c + off[1] * s), z: p.z - (-off[0] * s + off[1] * c)};
  }
  function transitionFor(S) {
    if (!S || S.k !== "pose" || S.t == null) return null;
    const G = M.seg, to = S.to, from = S.from, g = env.state().goal, B = G.bt;
    if (S.flow && G.guL && !to && from === "desk") {            // up from the desk and away: one take (see flow())
      const sleepy = g && g.clip === "sleep", U = G.guL;          // (both sides share the clip's timing)
      return {k: "getup", flow: true, a: S.stiff || sleepy ? 0 : U.start, b: S.next ? U.end : U.stand}; }
    if (B && g && g.clip === "sleep" && g.anchor === "bedlie") {          // going to sleep: room_bedtime
      // (up from the desk he stands up as always, room_mx_sit_to_stand below: room_bedtime's own get-up at its chair put
      // his legs and hips through ours, up to 3300 vertices on main)
      if (to === "bedside" && from !== "bedlie") return {k: "bedtime", a: B.walk, b: B.edge, at: () => B.edgePl};
      if (to === "bedlie" && from === "bedside") { const h = u => hipsAt(M.clips.bedtime, B.edge + (B.end - B.edge) * u);
        return {k: "bedtime", a: B.edge, b: B.end, at: u => mixPlace(B.edgePl, B.lie, sstep(0.1, 0.7, u), h(u))}; }
    }
    if (to === "desk" && from !== "desk") return {k: "sit_down", a: G.sit.from, b: G.sit.to, at: () => chairPlace(G.seatDown || SEAT.down, null, SEAT_AT.desk_watch), back: true};   // (onto the seated loop's seat point)
    if (!to && from === "desk") return {k: "stand_up", a: 0, b: M.clips.stand_up.duration, at: () => chairPlace(SEAT.up, null, SEAT_AT.desk_watch), back: true};
    if (to === "bedside" && from !== "bedlie") return {k: "bed_lie", a: G.lie.stand, b: G.lie.edge, at: () => G.lieEdge};
    const hips = (clip, a, b) => u => hipsAt(M.clips[clip], a + (b - a) * u);
    if (to === "bedlie" && from !== "bedlie") { const h = hips("bed_lie", G.lie.edge, G.lie.end);   // (lying already: no lie-down)
      return {k: "bed_lie", a: G.lie.edge, b: G.lie.end, at: u => mixPlace(G.lieEdge, G.bedLie, sstep(0.1, 0.7, u), h(u))}; }
    if (to === "bedside" && from === "bedlie") { const h = hips("bed_wake", 0, G.wake.sat);
      return {k: "bed_wake", a: 0, b: G.wake.sat, at: u => mixPlace(G.bedWake, G.wakeEdge, sstep(0.3, 0.9, u), h(u))}; }
    if (!to && from === "bedside") return {k: "bed_wake", a: G.wake.sat, b: G.wake.end, at: () => G.wakeEdge, back: true};
    return null;
  }
  // Up from the desk and away in one take (the owner: no standing still to turn round, no chair put back by itself).
  // Seated, he and the chair roll back and swivel toward the side he leaves by; his legs push the chair on as he rises
  // (back, and to the other side) and it stays there; his hips then follow the clip's own travel, its heading turned a
  // little more or less while he turns and walks (W, spread over those steps) so he leaves toward the page's next
  // waypoint; over the last 0.4 s the walk loop takes over at the moment whose feet match, the root moving under his
  // hips, and the page walks on from there. The room is tight (the bed 30-60 cm behind the chair, the plant on its left,
  // the desk in front): of the two get-ups (turning left, turning right) and a few swivels and pushes, the one needing
  // the smallest W whose hips keep off the desk and the furniture, whose walk-off passes the pushed chair, and from
  // whose end the page's path to the next waypoint is clear with the chair where he left it. Where no push leaves a way
  // (the window sill: its only way is the 30 cm gap behind the chair), the path is planned with the chair parked under
  // the desk and he shoves it there in passing (shove(): a hand on it for 0.35 s, it rolls on by itself; he never stops)
  const rotXZ = (h, r) => [h[0] * Math.cos(r) + h[1] * Math.sin(r), -h[0] * Math.sin(r) + h[1] * Math.cos(r)];
  const CHAIR_R = 0.33, BODY_R = 0.17, LEG_PUSH = 0.05;       // the chair's footprint (a circle), half his width, his legs' last push
  function flowPlan(S, T0, G, swivel, back, side, after, end) {
    const T = {a: T0.a, b: end ? end.end : T0.b}, turn = [G.turn[0], Math.min(G.turn[1], T.b - 0.3)];
    const R = G.rows, n = Math.max(1, Math.ceil((T.b - T.a) / G.dt)), b = env.boy, ch = env.chairNode();
    const hAt = t => { const f = Math.min(R.length - 1, Math.max(0, t / G.dt)), i = Math.floor(f), j = Math.min(R.length - 1, i + 1), k = f - i;
      return [R[i].hips.x + (R[j].hips.x - R[i].hips.x) * k, R[i].hips.z + (R[j].hips.z - R[i].hips.z) * k]; };
    const hw = [env.HIPS.walk[0], env.HIPS.walk[2]], r0 = b.rotation.y, x0 = b.position.x, z0 = b.position.z;
    const c0 = [ch.position.x, ch.position.z, ch.rotation.y], bk = [-Math.sin(r0), -Math.cos(r0)], rt = [-Math.cos(r0), Math.sin(r0)], v = [x0 - c0[0], z0 - c0[1]];
    const ride = back, sw = Math.sign(swivel);                     // (rt: his right as he sits; side > 0 pushes it to his right)
    const legs = t => { const e = sstep(G.ride[0], G.ride[1], t), e2 = sstep(G.push[0], G.push[1], t), d = ride * e + LEG_PUSH * e2;
      return [c0[0] + bk[0] * d + rt[0] * side * e2, c0[1] + bk[1] * d + rt[1] * side * e2, c0[2] + swivel * e + sw * 0.15 * e2]; };
    const chairAt = legs, cEnd = chairAt(T.b), home = after && env.chairHome ? env.chairHome() : null, cWay = home || cEnd;
    const why = {desk: 0, room: 0, chair: 0, bed: 0};
    { const into = c => Math.max(0, ...env.boxes().map(([x0, x1, z0, z1], i) => i === 1 || i === 2 ? 0     // (how deep its footprint is in the bed,
        : CHAIR_R - Math.hypot(Math.max(x0 - c[0], 0, c[0] - x1), Math.max(z0 - c[1], 0, c[1] - z1))));        //  the shelf, the fridge, the plant)
      if (into(chairAt(T.b)) > into(c0) + 0.02) why.bed = 50; }                                                  // (pushed no deeper than it was)
    const build = W => { const out = []; let hx = 0, hz = 0, hp = null, bad = why.bed; for (const k of ["desk", "room", "chair"]) why[k] = 0;
      for (let i = 0; i <= n; i++) { const t = T.a + (T.b - T.a) * i / n, h = hAt(t);
        let ry, rx, rz;
        if (t <= G.ride[1]) {                                   // riding the chair: his root turns and moves with it
          const e = sstep(G.ride[0], G.ride[1], t), dr = swivel * e, rv = rotXZ(v, dr);
          ry = r0 + dr; rx = c0[0] + bk[0] * ride * e + rv[0]; rz = c0[1] + bk[1] * ride * e + rv[1];
          const r = rotXZ(h, ry); hx = rx + r[0]; hz = rz + r[1];
        } else {                                                // on his feet: the hips' own travel, its heading turned by W
          ry = r0 + swivel + W * sstep(turn[0], turn[1], t);
          if (!hp) { hp = h; const r = rotXZ(h, ry); hx = x0 + r[0]; hz = z0 + r[1]; }   // (a clip whose ride ends before the take starts: on his feet from where he is)
          const d = rotXZ([h[0] - hp[0], h[1] - hp[1]], ry); hx += d[0]; hz += d[1];
          const r = rotXZ(h, ry); rx = hx - r[0]; rz = hz - r[1];
          if (t > G.up - 1.1 && env.blocked(hx, hz, t < G.up + 0.5 ? 0.14 : BODY_R)) { bad++; why[t < G.up + 0.5 ? "desk" : "room"]++; }  // (rising: the belly clear of the desk)
          if (t > G.up + 1.0) { const c = chairAt(t); if (Math.hypot(hx - c[0], hz - c[1]) < CHAIR_R + BODY_R - 0.08) { bad++; why.chair++; } } }   // (his hips past the seat's edge)
        hp = h; const rw = rotXZ(hw, ry); out.push([rx, rz, ry, hx - rw[0], hz - rw[1]]); }
      return {out, bad}; };
    let W = 0, P = build(0), way = true, be = 0, left = 9;
    if (S.next && env.chairRoute) {                            // the turn W that leaves him walking toward the next waypoint
      const e0 = hAt(T.b - 0.4), e1 = hAt(T.b), ac = Math.atan2(e1[0] - e0[0], e1[1] - e0[1]);
      const err = W => { const B = build(W), L = B.out[n], q = env.chairRoute([L[3], L[4]], S.next, cWay).pts[0], want = Math.atan2(q[0] - L[3], q[1] - L[4]);
        return Math.abs(Math.atan2(Math.sin(want - r0 - swivel - W - ac), Math.cos(want - r0 - swivel - W - ac))); };
      be = 1e9; for (let w = -1.2; w <= 1.2001; w += 0.1) { const e = err(w); if (e < be) { be = e; W = w; } }
      for (const d of [-0.05, -0.025, 0.025, 0.05]) { const e = err(W + d); if (e < be) { be = e; W += d; } }
      P = build(W); const L = P.out[n], rt = env.chairRoute([L[3], L[4]], S.next, cWay); way = rt.ok;
      left = 0; let p = [L[3], L[4]]; for (const q of rt.pts) { left += Math.hypot(q[0] - p[0], q[1] - p[1]); p = q; } }   // (the walk left after it)
    return {G, n, W, a: T.a, b: T.b, phase: end ? end.phase : 0, arr: P.out, bad: P.bad, why: {...why}, way, chairAt, swivel, back, side, shove: home, err: be, left,
      cost: Math.abs(W) + 2 * be + P.bad * 0.1 + (way ? 0 : 20) - 0.3 * (back + Math.abs(side)) + (home ? 1 : 0) + (left < 0.5 ? 3 * (0.5 - left) : 0)};
  }
  // the chair shoved in in passing: once his near hand can reach its backrest or an armrest (from the shoulder, 0.65 m),
  // the hand goes to it (0.15 s), pushes for 0.35 s while the chair speeds up, lets go, and the chair rolls on to its
  // place under the desk, slowing over 0.9 s (a constant push, then rolling friction); he walks on all the while
  const GRIPS = [[0.15, 1.26, 0.36], [-0.15, 1.26, 0.36], [0.26, 0.92, 0.0], [-0.26, 0.92, 0.0]];   // (chair's frame: the backrest's top, the armrests)
  const SHOVE = {reach: 0.65, hand: 0.15, push: 0.35, roll: 0.9};
  function shove(st, dt) {
    const H = M.shove, S = st.step; if (!H) return;
    const going = S ? S.k === "walk" || (S.k === "pose" && S.flow) : !st.at;          // (between two steps: still going)
    if (!going && H.tau == null) { M.shove = null; return; }                         // (the plan changed before he got there)
    const ch = env.chairNode(); if (!ch) return; env.boy.updateMatrixWorld(true); ch.updateMatrixWorld(true);
    if (H.tau == null) {                                       // not yet: within reach?
      let bd = 1e9, pick = null;
      for (const side of ["Right", "Left"]) { const sh = env.bones[side + "Arm"].getWorldPosition(V());
        for (const g of GRIPS) { const d = sh.distanceTo(ch.localToWorld(V(...g))); if (d < bd) { bd = d; pick = [side, g]; } } }
      if (bd > SHOVE.reach || !S || (S.k === "pose" && S.t < 0.6)) return;
      H.tau = 0; H.grip = pick; H.from = [ch.position.x, ch.position.z, ch.rotation.y];
    }
    H.tau += dt;
    const s = H.tau - SHOVE.hand, ta = SHOVE.push, td = SHOVE.roll, v = 2 / (ta + td);
    const p = s <= 0 ? 0 : s < ta ? v * s * s / (2 * ta) : s < ta + td ? v * ta / 2 + v * (s - ta) - v * (s - ta) ** 2 / (2 * td) : 1;
    const f = H.from, h = H.home;
    env.chairPose(f[0] + (h[0] - f[0]) * p, f[1] + (h[1] - f[1]) * p, f[2] + Math.atan2(Math.sin(h[2] - f[2]), Math.cos(h[2] - f[2])) * p);
    const w = sstep(0, SHOVE.hand, H.tau) * (1 - sstep(SHOVE.hand + ta, SHOVE.hand + ta + 0.2, H.tau));
    if (w > 0.01) { ch.updateMatrixWorld(true); ccd(H.grip[0], ch.localToWorld(V(...H.grip[1])), w); }
    if (p >= 1 && w <= 0.01) M.shove = null;
  }
  function flow(S, T) {
    if (!S.fl) {
      if (!env.chairNode()) return false;
      let best = null;                                         // (left: swivel +, the chair pushed to his right; right: the mirror)
      const all = [];
      for (const G of [M.seg.guL, M.seg.guR]) for (const sv of [0.3, 0.6, 0.9]) {
        const sg = G.side === "L" ? 1 : -1;
        for (const E of S.next ? G.ends : [null]) for (const after of [false, true])
          for (const bk of [0.15, 0.25, 0.32]) for (const sd of [0, 0.1, 0.2]) { const P = flowPlan(S, T, G, sg * sv, bk, sg * sd, after, E); all.push(P); if (!best || P.cost < best.cost) best = P; } }
      S.fl = best; S.mhd = S.d; S.d = best.b - best.a;
      M.flowLog = {side: best.G.side, W: +best.W.toFixed(2), bad: best.bad, way: best.way, swivel: best.swivel, back: best.back, push: best.side, shove: !!best.shove,
        end: +(best.b - best.G.up).toFixed(1), err: +best.err.toFixed(2), left: +best.left.toFixed(2),
        top: all.sort((a, b) => a.cost - b.cost).slice(0, 5).map(P => [P.G.side, P.swivel, P.back, P.side, !!P.shove, +(P.b - P.G.up).toFixed(1), +P.W.toFixed(2), P.why, P.way, +P.cost.toFixed(2)])};
    }
    const F = S.fl, G = F.G, n = F.n, u = Math.min(1, Math.max(0, S.t)), f = u * n, i = Math.min(n - 1, Math.floor(f)), k = f - i, A0 = F.arr[i], A1 = F.arr[i + 1];
    const L = j => A0[j] + (A1[j] - A0[j]) * k, t = F.a + (F.b - F.a) * u;
    const win = sstep(F.a, F.a + 0.5, t), kout = sstep(F.b - 0.4, F.b, t);
    const a = M.actions["getup" + G.side]; if (!a.isRunning()) { a.reset(); a.play(); }
    a.paused = true; a.time = t; a.setEffectiveWeight(win * (1 - kout));
    if (S.A && S.A !== S.B && S.A !== a) S.A.setEffectiveWeight(1 - win);
    if (S.B) { S.B.setEffectiveWeight(kout);
      if (S.next && S.B === M.actions.walk) { S.B.timeScale = 1; S.B.time = (F.phase + Math.max(0, t - (F.b - 0.4))) % M.clips.walk.duration; } }
    const c = F.chairAt(t); env.chairPose(c[0], c[1], c[2]);
    env.mixer.update(0);
    const b = env.boy, ry = A0[2] + Math.atan2(Math.sin(A1[2] - A0[2]), Math.cos(A1[2] - A0[2])) * k;
    b.position.set(L(0) + (L(3) - L(0)) * kout, env.F, L(1) + (L(4) - L(1)) * kout); b.rotation.y = ry;
    if (F.shove && !M.shove) M.shove = {home: F.shove, from: null, tau: null};   // (the shove in passing: shove())
    if (F.shove && kout > 0.5) env.chairBlock(F.shove[0], F.shove[1]);         // (the page walks on as if it were in)
    return true;
  }
  function transition(st) {
    const S = st.step, T = transitionFor(S);
    const on = !T ? null : T.flow ? (S.fl ? "getup" + S.fl.G.side : null) : T.k;
    for (const k of ["sit_down", "stand_up", "bed_lie", "bed_wake", "bedtime", "getupL", "getupR"]) if (k !== on) { const a = M.actions[k]; if (a && (a.isRunning() || a.getEffectiveWeight() > 0)) { a.setEffectiveWeight(0); a.stop(); } }
    if (!T) return false;
    if (T.flow) return flow(S, T);
    const place = T.at(Math.min(1, Math.max(0, S.t))); if (!place) return false;
    if (S.mhd === undefined) { S.mhd = S.d; S.d = Math.max(S.d, T.b - T.a); }   // the step lasts as long as the clip's stretch (the page's ~1 s is too quick)
    const u = Math.min(1, Math.max(0, S.t)), w = sstep(0, 0.15, u) * (1 - sstep(0.85, 1, u));
    const a = M.actions[T.k]; if (!a.isRunning()) { a.reset(); a.play(); }
    a.paused = true; a.time = T.a + (T.b - T.a) * u; a.setEffectiveWeight(w);
    if (S.A && S.A !== a) S.A.setEffectiveWeight(u < 0.5 ? 1 - w : 0);          // the page's poses only at the two ends
    if (S.B && S.B !== a) S.B.setEffectiveWeight(u < 0.5 ? 0 : 1 - w);
    env.mixer.update(0);
    // the root: from the page's toward the clip's placement (onto the bed: kept); sitting down from further out than the
    // clip starts (TURN_CLEAR), over the first 35 % while he already sits back, so it adds to his own travel
    const b = env.boy, wr = T.k === "sit_down" && u < 0.5 ? sstep(0, 0.35, u) : T.back ? w : sstep(0, 0.15, u);
    b.position.set(b.position.x + (place.x - b.position.x) * wr, b.position.y + (env.F - b.position.y) * wr, b.position.z + (place.z - b.position.z) * wr);
    b.rotation.y = angLerp(b.rotation.y, place.ry, wr);
    return true;
  }
  // the clips were recorded on another bed: while he sits on, lies down on or gets up from this one, any of his skin
  // that dips into the mattress lifts him by as much (eased back down when clear)
  let skin = null;
  function baseY() {                                         // his height as the page has it, without the lifts below
    const y = env.boy.position.y; if (M.lastY === undefined || Math.abs(y - M.lastY) > 1e-7) M.baseY = y;
    env.boy.position.y = M.baseY; return M.baseY;
  }
  // a body thicker than the clips' (v5: the hoodie, the thighs) sits higher on the seat: env.seatLift (m), seated at the
  // desk; it eases in and out over the sit-down and the stand-up (?debug: window.__seatLift overrides it)
  function seatLift(st) {
    const s = st.step, t = s ? Math.min(1, Math.max(0, s.t || 0)) : 0;     // (a step's t runs 0 -> 1)
    // sitting down onto the desk chair: a lift that peaks mid-way and is 0 at both ends (the seated pose is unchanged), for
    // a character whose thighs brush the seat's front on the way down (env.sitBump, m; ?debug: window.__sitBump)
    const SB = window.__sitBump ?? env.sitBump ?? 0; if (SB && s && s.k === "pose" && s.to === "desk") env.boy.position.y += SB * Math.sin(Math.PI * t);
    const L = window.__seatLift ?? env.seatLift ?? 0; if (!L) return;
    const k = st.at === "desk" && (!s || s.k === "chair") ? 1 : s && s.k === "pose" && s.to === "desk" ? t : s && s.k === "pose" && st.at === "desk" ? 1 - t : 0;
    env.boy.position.y += L * k;
  }
  function bedLift(st, dt) {
    const on = st.at === "bedlie" || st.at === "bedside" || (st.step && (st.step.to === "bedlie" || st.step.to === "bedside" || st.step.from === "bedlie" || st.step.from === "bedside"));
    if (!on && !M.lift) return;
    const b = env.boy; let need = 0, every = 3;
    if (on && !st.step) {                                      // still on the bed: every other vertex, once a second (cheap on a phone)
      M.liftT = (M.liftT || 0) - dt; if (M.liftT > 0) { b.position.y += M.lift; return; }
      M.liftT = 1; every = 2; M.lift = 0;
    }
    if (on) {
      if (!skin) { skin = []; b.traverse(o => { if (o.isSkinnedMesh && !/_inside$/.test(o.name)) skin.push(o); }); }     // every part (dressed: his clothes too; not the page's drawn inside)
      b.updateMatrixWorld(true); const v = V();
      // (lying awake on top of it, he rests on the folded quilt pressed flat under him, env.quiltTop, not on the bare
      // mattress: there his back and soles went 1 to 3 cm into the dented quilt)
      const top = env.quiltTop ? BED.top + (M.dentW || 0) * (env.quiltTop - BED.top) : BED.top;
      for (const o of skin) { if (!o.visible) continue; const P = o.geometry.attributes.position;
      for (let i = 0; i < P.count; i += every) { o.getVertexPosition(i, v).applyMatrix4(o.matrixWorld);
        const e = Math.min(v.x - BED.box[0], BED.box[1] - v.x, v.z - BED.box[2], BED.box[3] - v.z);
        if (e > 0) need = Math.max(need, top - (e < 0.05 ? 0.05 - Math.sqrt(0.0025 - (0.05 - e) ** 2) : 0) - v.y); } }   // (its edge is rounded, r 5 cm)
    }
    M.lift = Math.max(need, (M.lift || 0) - 0.1 * dt);
    if (M.lift < 1e-4) M.lift = 0;
    b.position.y += M.lift;
  }
  // the soles: no vertex of his feet (or of the slides on them) under the floor; a step that dips lifts him by as much,
  // eased back down. The vertices whose main bone is a foot or a toe, gathered once over every skinned part - only the
  // sole's extreme points of each bone's skin, though: the lowest under a fan of directions about down in the bind pose
  // (tilted up to 80 deg every 10, 24 ways round: a heel strike, a toe off, a foot swung sideways), so whichever way the
  // bone turns its lowest vertex is among them within ~1 mm. Skinned as drawn each frame: ~400 vertices against half of
  // all ~14 000 foot vertices before, which cost 3-4 ms a frame under software GL (the owner's Mac ran its fans)
  let feet = null; const _lv = V();
  function feetPick() {
    const dirs = [V(0, -1, 0)]; for (let t = 10; t <= 80; t += 10) for (let a = 0; a < 360; a += 15) { const r = t * Math.PI / 180, p = a * Math.PI / 180; dirs.push(V(Math.sin(r) * Math.cos(p), -Math.cos(r), Math.sin(r) * Math.sin(p))); }
    const out = [], v = V();
    env.boy.traverse(o => { if (!o.isSkinnedMesh || /_inside$/.test(o.name)) return; const g = o.geometry, I = g.attributes.skinIndex, W = g.attributes.skinWeight, P = g.attributes.position, by = new Map();
      for (let i = 0; i < P.count; i++) { let k0 = 0, w0 = 0; for (let k = 0; k < 4; k++) if (W.getComponent(i, k) > w0) { w0 = W.getComponent(i, k); k0 = I.getComponent(i, k); }
        if (/Foot|ToeBase|toe/.test(o.skeleton.bones[k0].name)) { if (!by.has(k0)) by.set(k0, []); by.get(k0).push(i); } }
      const pick = new Set();
      for (const ids of by.values()) { const pos = ids.map(i => v.fromBufferAttribute(P, i).applyMatrix4(o.bindMatrix).clone());   // (the bind pose, upright)
        for (const d of dirs) { let best = 0, bd = -Infinity; for (let n = 0; n < pos.length; n++) { const s = pos[n].dot(d); if (s > bd) { bd = s; best = n; } } pick.add(ids[best]); } }   // (the farthest along d: the lowest were d down)
      if (pick.size) out.push([o, [...pick]]); });
    return out;
  }
  function floorLift(dt) {
    const b = env.boy, t0 = performance.now();
    if (!feet) feet = feetPick();
    b.updateMatrixWorld(true); let low = 9; const v = _lv;
    for (const [o, ids] of feet) for (const i of ids) { o.getVertexPosition(i, v).applyMatrix4(o.matrixWorld); if (v.y < low) low = v.y; }
    const need = Math.max(0, env.F - 0.002 - low); M.floorLow = low;   // (?debug: the soles' lowest point, to check against every vertex)
    M.flift = Math.max(need, (M.flift || 0) - 0.1 * dt); if (M.flift < 1e-4) M.flift = 0;
    b.position.y += M.flift;
    const ms = performance.now() - t0; M.floorMs = ms; M.floorMsAvg = M.floorMsAvg == null ? ms : M.floorMsAvg + (ms - M.floorMsAvg) * 0.05;   // (?debug: the floor check's cost per frame)
  }
  // in bed: the slides come off before he sits on the bed's edge (a pair parked on the floor by it, toes toward the bed,
  // their own geometry as in his bind pose: standing, feet flat) and go back on as he stands up; asleep at night the
  // page's duvet is drawn up over him to his chest (a daytime rest stays on top of it)
  const SL = {on: [], pair: null, off: false, duv: 0};
  function slidesInit() {
    env.boy.traverse(o => { if (o.isSkinnedMesh && /slide/i.test(o.name) && !/_inside$/.test(o.name)) SL.on.push(o); });
    if (!SL.on.length) return;
    const pair = new THREE.Group(), box = new THREE.Box3(), c = V();
    for (const o of SL.on) { const g = o.geometry.clone(); g.applyMatrix4(o.bindMatrix); for (const k of ["skinIndex", "skinWeight"]) g.deleteAttribute(k);
      const m = new THREE.Mesh(g, o.material); m.castShadow = m.receiveShadow = true; pair.add(m); g.computeBoundingBox(); box.union(g.boundingBox); }
    box.getCenter(c); for (const m of pair.children) m.geometry.translate(-c.x, -box.min.y, -c.z);
    pair.position.set(-0.66, env.F + 0.002, 0.08); pair.rotation.y = 0.25; pair.visible = false; pair.name = "slides_parked";
    env.scene.add(pair); SL.pair = pair;
  }
  function bedThings(st, dt) {
    if (!SL.pair && !SL.tried) { SL.tried = true; slidesInit(); }
    const S = st.step, u = S && S.t != null ? S.t : 1;
    const off = st.at === "bedlie" || st.at === "bedside" || !!(S && S.k === "pose" && (S.to === "bedlie" || S.from === "bedlie" ||
      (S.to === "bedside" && u > 0.6) || (S.from === "bedside" && !S.to && u < 0.25)));
    if (SL.pair && off !== SL.off) { SL.off = off; SL.pair.visible = off; for (const o of SL.on) o.visible = !off; }
    if (!env.cover) return;
    const asleep = !!(st.goal && st.goal.clip === "sleep") && (st.at === "bedlie" || !!(S && S.k === "pose" && S.to === "bedlie" && u > 0.8));
    SL.duv = SL.duv === 0 && asleep && st.at === "bedlie" && !S ? 1 : Math.min(1, Math.max(0, SL.duv + (asleep ? dt / 2.2 : -dt / 1.2)));
    env.cover(SL.duv, dt);
  }
  // turning on the spot (a walk or turn step before he moves off): the walk loop's full stride would swing a foot 30 cm
  // out (into the bed at the sill), so the stride shrinks with his speed: the walk blends toward the stand
  const _lp = V();
  function pivot(st, dt) {
    const S = st.step, W = M.actions.walk, St = M.actions.stand, b = env.boy;
    const speed = M.lpOk ? Math.hypot(b.position.x - _lp.x, b.position.z - _lp.z) / Math.max(dt, 1e-3) : 1;
    _lp.copy(b.position); M.lpOk = true;
    const walking = !!(S && (S.k === "walk" || S.k === "turn") && st.current === W);
    const want = walking ? Math.min(1, Math.max(0.15, speed / 0.35)) : 1;
    if (walking && !M.wasWalking) M.ww = S.flow ? 1 : 0.15;     // (from standing: the first steps are short ones; after the get-up he is mid-stride)
    M.wasWalking = walking;
    M.ww = (M.ww == null ? 1 : M.ww) + (want - (M.ww == null ? 1 : M.ww)) * (1 - Math.exp(-dt / 0.15));
    if (!walking) { M.ry0 = null; if (M.pivoting) { M.pivoting = false; if (St !== st.current) { St.setEffectiveWeight(0); St.stop(); } } M.ww = 1; return; }
    if (M.ry0 == null || M.ww > 0.99) M.ry0 = b.rotation.y;    // (where this turn on the spot started)
    if (M.ww > 0.995 && !M.pivoting) return;
    M.pivoting = M.ww <= 0.995;
    if (!St.isRunning()) { St.reset(); St.play(); }
    W.setEffectiveWeight(M.ww); St.setEffectiveWeight(1 - M.ww); env.mixer.update(0);
    // and he turns about his feet, not the root (the stand's feet are ahead of it: at the sill his toes would reach the
    // bed): his hips move by the turn of that offset (the mixer sets them anew each frame), fading out as he walks off
    const H = env.bones.Hips, f = M.standFeet; if (!H || !f) return;
    const rot = r => [f.x * Math.cos(r) + f.z * Math.sin(r), -f.x * Math.sin(r) + f.z * Math.cos(r)];
    // (halfway to the feet: the hips' swing stays clear of the chair, the toes of the bed)
    const a0 = rot(M.ry0), a1 = rot(b.rotation.y), k = 0.5 * Math.min(1, Math.max(0, (1 - M.ww) / 0.85));
    b.updateMatrixWorld(true); const w0 = H.getWorldPosition(V()), w1 = w0.clone().add(V((a0[0] - a1[0]) * k, 0, (a0[1] - a1[1]) * k));
    H.position.add(H.parent.worldToLocal(w1).sub(H.parent.worldToLocal(w0)));
  }
  // the clothes' corrective shapes (G4's morph targets on the hoodie and the trousers: seated, elbow_L/R, lying), weighted
  // each frame after the animation from the joints, by the drivers the file carries (extras.correctives). The file is
  // read for its header only when this body has shapes to drive (v5 and the Mixamo character have none: 983 KB saved)
  const CORR = {drivers: null, meshes: []};
  env.boy.traverse(o => { if (o.isMesh && o.morphTargetDictionary && o.morphTargetInfluences) CORR.meshes.push(o); });
  if (CORR.meshes.length) fetch("room/boy.glb").then(r => r.arrayBuffer()).then(buf => {
    const dv = new DataView(buf), n = dv.getUint32(12, true);
    const js = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 20, n)));
    CORR.drivers = ((js.extras || {}).correctives || {}).drivers || null;
  }).catch(() => {});
  const smooth = (a, b, x) => sstep(a, b, x), _cdn = V(), _c1 = V(), _c2 = V(), _c3 = V(), _c4 = V();
  function correctives() {
    if (!CORR.drivers || !CORR.meshes.length) return;
    const B = env.bones, p = (n, o) => B[n].getWorldPosition(o);   // (into a scratch vector: a dozen joints a frame)
    const down = p("Hips", _cdn).sub(p("neck", _c1)).normalize(), deg = (a, b) => THREE.MathUtils.radToDeg(a.angleTo(b)), w = {};
    for (const [name, d] of Object.entries(CORR.drivers)) {
      let v = 0;
      if (d.type === "hip_bend") v = (deg(p("LeftLeg", _c1).sub(p("LeftUpLeg", _c2)), down) + deg(p("RightLeg", _c1).sub(p("RightUpLeg", _c2)), down)) / 2;
      else if (d.type === "elbow_bend") v = deg(p(d.side + "ForeArm", _c1).sub(p(d.side + "Arm", _c2)), p(d.side + "Hand", _c3).sub(p(d.side + "ForeArm", _c4)));
      else if (d.type === "chest_up") v = _c3.crossVectors(p("LeftArm", _c1).sub(p("RightArm", _c2)), _c4.copy(down).negate()).normalize().y;
      w[name] = smooth(d.from, d.to, v);
    }
    for (const o of CORR.meshes) for (const [nm, i] of Object.entries(o.morphTargetDictionary)) o.morphTargetInfluences[i] = w[nm] || 0;
    M.corr = w;
  }
  // ---------- the activity clips' props (room/mh/props_g2.json: placeholder boxes and cylinders, real models later) ----------
  // held ones ride a hand bone (offset and turn in its frame), the others stand in the clip's own frame (a child of him:
  // his root is that frame); each set shows while its clip plays. The door's swing and the window's sash follow the
  // clip's keys [t, rotY, dx, dy, dz].
  const PR = {json: null, sets: {}, sash: null};
  fetch("room/mh/props_g2.json").then(r => r.json()).then(j => { PR.json = j; }).catch(() => {});
  const COLOR = w => /screen/.test(w) ? 0x6aa0ff : /phone/.test(w) ? 0x111214 : /plate/.test(w) ? 0xf2f0ea : /glass/.test(w) ? 0xcfe8f5
    : /bottle/.test(w) ? 0x6fb37a : /cover/.test(w) ? 0x9a3b30 : /page|paperback|half/.test(w) ? 0xf5f1e6 : /counter/.test(w) ? 0xb79c7e : 0xd9a35b;
  function propMesh(p) {
    const z = p.size, geo = p.shape === "cyl" ? new THREE.CylinderGeometry(z[0], z[2] != null ? z[2] : z[0], z[1], 20) : new THREE.BoxGeometry(z[0], z[1], z[2]);
    const mat = new THREE.MeshStandardMaterial({color: p.color ? Number(p.color) : COLOR(p.what || ""), roughness: p.rough != null ? p.rough : 0.6,
      transparent: p.opacity != null || /glass/.test(p.what || ""), opacity: p.opacity != null ? p.opacity : /glass/.test(p.what || "") ? 0.45 : 1,
      emissive: /screen/.test(p.what || "") ? 0x335599 : 0x000000});
    const m = new THREE.Mesh(geo, mat); m.castShadow = m.receiveShadow = true;
    if (p.rot) m.rotation.set(...p.rot.map(d => THREE.MathUtils.degToRad(d)));
    return m;
  }
  function propSet(k) {                                      // built once per clip
    if (PR.sets[k] !== undefined || !PR.json) return PR.sets[k] || null;
    const spec = PR.json["room_" + k]; if (!spec) return PR.sets[k] = null;
    const set = {held: [], world: new THREE.Group()};
    const MHB = {"wrist.L": "LeftHand", "wrist.R": "RightHand"};          // (MakeHuman's names for the room rig's)
    for (const p of spec.held || []) { const nm = MHB[p.bone] || p.bone, bone = env.bones[nm.replace(".", "")] || env.bones[nm]; if (!bone) { console.warn("prop bone", p.bone); continue; }
      const m = propMesh(p); m.position.set(...p.off); m.visible = false; bone.add(m); set.held.push(m); }
    for (const p of spec.world || []) { const m = propMesh(p); m.position.set(...p.pos); set.world.add(m); }
    set.pages = [];                                           // turning pages: hinged on the spine (a group at the pivot), turned
    for (const p of spec.pages || []) {                       // about the axis by the keys [t, deg] (0 on the right half, -160 on the left)
      const m = propMesh({...p, rot: null}); m.geometry.translate(p.size[0] / 2, 0, 0); m.rotation.set(...p.rot.map(d => THREE.MathUtils.degToRad(d)));
      const g = new THREE.Group(); g.position.set(...p.pivot); g.add(m); set.world.add(g);
      set.pages.push({g, axis: V(...p.axis).normalize(), keys: p.keys}); }
    set.world.visible = false; env.boy.add(set.world);
    return PR.sets[k] = set;
  }
  function showProps(k, on) { const set = propSet(k); if (!set) return; set.world.visible = on; for (const m of set.held) m.visible = on; }
  const keyAt = (keys, t) => { if (!keys || !keys.length) return [0, 0, 0, 0]; let i = 0; while (i < keys.length - 2 && keys[i + 1][0] <= t) i++;
    const a = keys[i], b = keys[Math.min(i + 1, keys.length - 1)], u = b[0] > a[0] ? Math.min(1, Math.max(0, (t - a[0]) / (b[0] - a[0]))) : 0;
    return [1, 2, 3, 4].map(j => a[j] + (b[j] - a[j]) * u); };
  function props_(st) {                                      // which clip's props are out, and the door / the sash
    if (!PR.json) return;
    for (const k of ["eat", "read", "phone", "phone_scroll", "drink"]) { const a = M.actions["act_" + k]; showProps(k, !!a && a.isRunning() && a.getEffectiveWeight() > 0.5); }
    const rd = PR.sets.read, ra = M.actions.act_read;
    if (rd && rd.pages && ra && rd.world.visible) for (const pg of rd.pages) {
      const K = pg.keys, t = ra.time; let i = 0; while (i < K.length - 2 && K[i + 1][0] <= t) i++;
      const a = K[i], b = K[Math.min(i + 1, K.length - 1)], u = b[0] > a[0] ? Math.min(1, Math.max(0, (t - a[0]) / (b[0] - a[0]))) : 0;
      const deg = t <= K[0][0] ? K[0][1] : t >= K[K.length - 1][0] ? K[K.length - 1][1] : a[1] + (b[1] - a[1]) * u;
      pg.g.quaternion.setFromAxisAngle(pg.axis, THREE.MathUtils.degToRad(deg)); }
    const sc = M.sc;
    // (the clip pulls the door toward him, rotY < 0: in this room that is a negative setDoor, the leaf's free edge to +z)
    if (sc && sc.k === "door" && env.setDoor) { const [ry] = keyAt(PR.json.room_door.anim[0].keys, sc.a.time); env.setDoor(THREE.MathUtils.degToRad(ry)); }
    if (sc && sc.k === "window") {
      const W = PR.json.room_window, an = W.anim[0];
      if (!PR.sash) { PR.sash = new THREE.Group(); for (const p of W.anim) { const m = propMesh(p); PR.sash.add(m); } env.scene.add(PR.sash); }
      const [, dx] = keyAt(an.keys, sc.a.time), b = env.boy;
      // the room's window is higher than the clip's (sill 1.11 m above the floor, the clip's 0.825): the sash sits in
      // the real opening, just inside the glass, and slides as keyed
      const loc = V(an.pivot[0] + dx, an.pivot[1] + 0.24, 1.05); b.updateMatrixWorld(true); PR.sash.position.copy(b.localToWorld(loc));
      PR.sash.rotation.y = b.rotation.y; PR.sash.visible = true;
    } else if (PR.sash) PR.sash.visible = false;
  }
  // ---------- the preview showcase (?debug: mh.show("read" | "phone" | "drink" | "door" | "window"), mh.show(null) ends it):
  // the activity clips awaiting the owner's word, played where they belong in the room ----------
  const SHOW = {read: null, phone: null, phone_scroll: null,  // at the desk, seated: where the page has him
    drink: [0.50, 0.05, 0],                                  // standing, a counter in front (the clip's own placeholder)
    door: [1.73, -0.48, Math.PI],                            // facing the door: its handle where the clip's hand reaches
    window: [-0.90, -0.06, -Math.PI / 2]};                   // facing the window between the chair and the bed
  function show(k) {
    if (M.sc) { M.sc.a.setEffectiveWeight(0); M.sc.a.stop(); if (M.sc.k === "door" && env.setDoor) env.setDoor(0); M.sc = null;
      if (!k) env.resnap(); }                                // (back where the page has him, its clip at full weight)
    if (!k || !M.actions["act_" + k]) return;
    const a = M.actions["act_" + k]; a.reset(); a.setLoop(THREE.LoopRepeat, Infinity); a.play(); M.sc = {k, a, root: SHOW[k]};
  }
  function showStep() {
    const sc = M.sc; if (!sc) return;
    const b = env.boy; if (sc.root) { b.position.set(sc.root[0], env.F, sc.root[1]); b.rotation.y = sc.root[2]; }
    for (const a of env.mixer._actions) if (a !== sc.a && a.getEffectiveWeight() > 0) a.setEffectiveWeight(0);
    sc.a.setEffectiveWeight(1); env.mixer.update(0);
  }
  // ---------- G11's hair (room/hair: ~60,000 strands grown on G2's head; preview/hair-mh): on the Head bone (its frame is
  // the bone's rest frame), the half-density LOD at room distance, lit from the room's own lights; preview/hair-mh 875d61c ----------
  const HAIR = {mesh: null, t: 9};
  function hairInit() {
    if (HAIR.tried || env.noHair) return; HAIR.tried = true;      // (v5 has its own hair)
    Promise.all([env.load("room/hair/hair_mh.glb"), import("./hair/hair_strands.js")]).then(([g, mod]) => {
      const hair = g.scene.getObjectByName("hair_mh") || g.scene, head = env.bones.Head; if (!head) return;
      hair.position.set(0, 0, 0); head.add(hair); HAIR.root = hair;
      // (half the hairs at room distance; the spine turns on the collar collider: the nape hair stays on the hood)
      HAIR.mesh = mod.useStrands(THREE, hair, {lod: 0.5, spine: env.boy.getObjectByName("Spine")});
      hair.traverse(o => { if (o.isMesh) o.castShadow = false; });
    }).catch(e => console.warn("hair:", e));
  }
  const _ld = V(), _lt = V();
  function hairLights(dt) {                                  // twice a second: the strongest directional light is the key, the next
    const m = HAIR.mesh; if (!m || !m.material || !m.material.uniforms) return;   // the rim; the hemisphere / ambient the sky and ground
    HAIR.t += dt; if (HAIR.t < 0.5) return; HAIR.t = 0;
    const U = m.material.uniforms, dirs = [], amb = new THREE.Color(0, 0, 0); let hemi = null;
    env.scene.traverse(o => { if (!o.visible) return; if (o.isDirectionalLight || o.isSpotLight) dirs.push(o); else if (o.isHemisphereLight) hemi = o;
      else if (o.isAmbientLight) amb.add(o.color.clone().multiplyScalar(o.intensity)); });
    dirs.sort((a, b) => b.intensity - a.intensity);
    const set = (L, dirU, colU) => { if (!L) { U[colU].value.setRGB(0, 0, 0); return; }
      L.getWorldPosition(_ld); (L.target ? L.target.getWorldPosition(_lt) : _lt.set(0, 0, 0)); U[dirU].value.copy(_ld.sub(_lt).normalize());
      U[colU].value.copy(L.color).multiplyScalar(Math.min(3, L.intensity * 0.6)); };
    set(dirs[0], "keyDir", "keyCol"); set(dirs[1], "rimDir", "rimCol");
    if (hemi) { U.sky.value.copy(hemi.color).multiplyScalar(hemi.intensity * 0.5).add(amb); U.ground.value.copy(hemi.groundColor).multiplyScalar(hemi.intensity * 0.5).add(amb); }
    else { U.sky.value.copy(amb); U.ground.value.copy(amb).multiplyScalar(0.6); }
  }
  function onBed(st) {                                       // lying on, or sitting on the edge of, the bed: placed by the lie clip's pose
    if (st.step || (st.at !== "bedlie" && st.at !== "bedside")) return;
    const sleep = M.seg.bt && st.goal && st.goal.clip === "sleep";
    const p = st.at === "bedlie" ? (sleep ? M.seg.bt.lie : M.seg.bedLie) : (sleep ? M.seg.bt.edgePl : M.seg.lieEdge), b = env.boy;
    b.position.set(p.x, env.F, p.z); b.rotation.y = p.ry;
  }

  // ---------- the bed layer (room/desk_states/bed: G23's Sova bed clips, fitted to the room's bed) ----------
  // Lying on the bed with the phone, the phone clips by what is on it: a portrait short (or anything else) -> watching it
  // held upright, a video -> held sideways, a chat -> typing (the lift over his face, bed_phone_lift, is left out: see
  // BED_SKIP). Asleep: on his side, after a while he rolls onto his back (once), then on his back with small
  // shifts now and then. Crossfaded like the desk states; the page's lie and sleep clips stay underneath (a clip that does
  // not load is left out; none loaded: the page's clips as before). The phone clips hold the phone in his left hand
  // themselves: the page's holdPhone() stands aside (phone.userData.byClip) and the phone hangs on the hand by the clip's grip
  const BED_DIR = "room/desk_states/bed", BED_FADE = 0.8;
  // (bed_phone_lift is left out: its source lies across a bed with the feet on the floor, and laid along this mattress its
  // legs went 7122 sampled vertices into it - G23's extents_m say as much; the other seven: 0 in the bed over each clip)
  const BED_SKIP = ["bed_phone_lift"];
  // the page's phone (x its width, y its length, z out of its screen) in the clips' phone box (x its thickness = the screen's
  // normal, y its length, z its width)
  const BED_AXES = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(V(0, 0, -1), V(0, 1, 0), V(1, 0, 0)));
  async function bedLoad(make) {
    const r = await fetch(`${BED_DIR}/index.json`); if (!r.ok) throw new Error(`${BED_DIR}/index.json: ${r.status}`);
    const ix = (await r.json()).clips || {}, clips = {};
    await Promise.all(Object.entries(ix).filter(([name]) => !BED_SKIP.includes(name)).map(([name, e]) => env.load(`${BED_DIR}/${e.file}`).then(g => {
      const c0 = env.fixClip ? env.fixClip(g.animations[0]) : g.animations[0]; if (!c0) return; const c = c0.clone(); c.name = "bed_" + name;
      const a = make(c); if (e.loop) a.setLoop(THREE.LoopRepeat, Infinity); else { a.setLoop(THREE.LoopOnce, 1); a.clampWhenFinished = true; }
      const sp = sampler(c), p0 = sp(0); sp.done();
      clips[name] = {a, dur: c.duration, loop: !!e.loop, place: bedPlace(p0), phone: e.phone ? {t: V(...e.phone.node_translation), q: new THREE.Quaternion(...e.phone.node_rotation_xyzw)} : null};
    }, () => null)));
    if (!Object.keys(clips).length) throw new Error("no bed clip loaded");
    const A = env.actions; M.bed = {clips, cur: null, slot: null, until: 0, def: {phone_lie: A.phone_lie, lie_phone: A.lie_phone, sleep: A.sleep}, from: null, k: 1};
  }
  function bedPhoneClip(life) {                              // which phone clip, by what is on the phone
    const sc = life && life.screen, app = life && life.phone, has = n => M.bed.clips[n] ? n : null;
    if (app === "chat") return has("bed_phone_typing") || has("bed_phone_watch_portrait");
    if ((sc && sc.device === "phone" && sc.kind === "video") || app === "video" || app === "youtube") return has("bed_phone_watch_landscape") || has("bed_phone_watch_portrait");
    return has("bed_phone_watch_portrait") || has("bed_phone_watch_landscape");
  }
  function bedPlay(name, st) {
    const B = M.bed, C = B.clips[name], a = C.a, cur = st.current;
    a.reset(); a.setEffectiveWeight(1); a.fadeIn(BED_FADE).play(); if (cur && cur !== a) cur.fadeOut(BED_FADE); env.setCurrent(a);
    for (const k of B.slot === "phone" ? ["phone_lie", "lie_phone"] : ["sleep"]) env.actions[k] = a;   // (the page's play() keeps it)
    const b = env.boy; B.from = {x: b.position.x, z: b.position.z, ry: b.rotation.y}; B.k = 0; B.cur = name;
    M.log.push([+st.T.toFixed(2), "bed:" + name]); if (M.log.length > 50) M.log.shift();
  }
  function bedOff() {
    const B = M.bed; for (const [k, a] of Object.entries(B.def)) if (a) env.actions[k] = a;
    B.cur = B.slot = null; const ph = env.phone && env.phone(); if (ph && ph.userData.byClip) { ph.userData.byClip = false; ph.visible = false; if (env.propHand) env.propHand(true); }
  }
  function bedStep(st, dt) {
    const B = M.bed; if (!B) return;
    const g = st.goal, slot = !st.step && st.at === "bedlie" && g ? (g.clip === "phone_lie" ? "phone" : g.clip === "sleep" ? "sleep" : null) : null;
    if (!slot) { if (B.cur) bedOff(); return; }
    const T = st.T, rng = env.rng || Math.random, has = n => !!B.clips[n], fresh = B.slot !== slot || !B.cur; let want = B.cur;
    B.slot = slot;
    if (slot === "phone") {
      const base = bedPhoneClip(st.life);
      if (fresh) { want = base; B.until = T + 25 + 35 * rng(); }
      else if (B.cur === "bed_phone_lift") { if (T >= B.until) { want = base; B.until = T + 30 + 40 * rng(); } }
      else if (B.cur !== base) want = base;
      else if (T >= B.until && has("bed_phone_lift")) { want = "bed_phone_lift"; B.until = T + B.clips.bed_phone_lift.dur - BED_FADE; }
    } else {
      const back = () => (has("sleep_back") ? "sleep_back" : "sleep_back_idle");
      if (fresh) { want = has("sleep_side") ? "sleep_side" : back(); B.until = T + 40 + 50 * rng(); }
      else if (B.cur === "sleep_side" && T >= B.until && has("sleep_roll_to_back")) { want = "sleep_roll_to_back"; B.until = T + B.clips.sleep_roll_to_back.dur - BED_FADE; }
      else if (B.cur === "sleep_roll_to_back" && T >= B.until) { want = back(); B.until = T + 30 + 30 * rng(); }
      else if ((B.cur === "sleep_back" || B.cur === "sleep_back_idle") && T >= B.until) { want = B.cur === "sleep_back" && has("sleep_back_idle") ? "sleep_back_idle" : back(); B.until = T + 20 + 30 * rng(); }
    }
    if (M.bedForce && has(M.bedForce)) want = M.bedForce;      // (?debug: that clip, now)
    if (want && want !== B.cur && has(want)) bedPlay(want, st);
    const C = B.clips[B.cur]; if (!C) return;
    // the root: each clip's own placement on the bed (the page's is the lie clip's), eased over the crossfade
    if ((window.__bedPlace ?? "own") === "own") { B.k = Math.min(1, B.k + dt / BED_FADE); const k = B.k * B.k * (3 - 2 * B.k), F0 = B.from || C.place, b = env.boy;
      b.position.set(F0.x + (C.place.x - F0.x) * k, env.F, F0.z + (C.place.z - F0.z) * k); b.rotation.y = angLerp(F0.ry, C.place.ry, k); b.updateMatrixWorld(true); }
    // the phone: in his left hand by the clip's grip (else the page holds it as before)
    // (this body's step - the page's step0 - has no phone of its own: shown here while a clip holds it, hidden after)
    const ph = env.phone && env.phone(); if (!ph) return;
    if (!C.phone) { if (ph.userData.byClip) { ph.userData.byClip = false; ph.visible = false; if (env.propHand) env.propHand(true); } return; }
    ph.userData.byClip = true; ph.visible = true;
    if (env.propHand) env.propHand(false);                   // his own hand grips it: the page's prop hand goes, the phone body shows
    const hb = env.bones.LeftHand; if (!hb) return; hb.updateWorldMatrix(true, false);
    ph.position.copy(hb.localToWorld(C.phone.t.clone())); ph.quaternion.copy(hb.getWorldQuaternion(new THREE.Quaternion()).multiply(C.phone.q).multiply(BED_AXES)); ph.updateMatrixWorld(true);
  }

  // ---------- one step (instead of the page's animate: the mixer, his plan and walk, the desk modes, the wrists) ----------
  function animate(dt) {
    contactRestore();                                          // (the page's finger turns undone before the mixer runs)
    if (M.ready && SV) { const s0 = env.state(); svEvents(s0); if (M.mode === "desk_watch" && s0.at === "desk" && !s0.step) svStep(s0); }   // (the desk states: likewise)
    if (M.ready) rareStep(dt);                                 // (before the mixer: a crossfade it starts is in this frame's pose)
    const moving = env.step0(dt);
    if (!M.ready) return moving;
    if (!P.kbNode || !P.mouseNode) { P.seen += dt; if (P.seen > 1) { P.seen = 0; props(); } }   // (G10d's nodes may arrive late)
    const st = env.state();
    // (a desk mode only once he has settled: between the sit-down and the chair's ride in the page has no step for a
    // frame, and a mode switched in then rode the turned chair in, its legs through it)
    M.still = st.at === "desk" && !st.step ? (M.still || 0) + dt : 0;
    if (M.ev && (st.at !== "desk" || st.step)) { M.ev.a.stop(); M.ev = null; }   // (the page moved him on: the event ends)
    const m = M.sc || M.still < 0.3 ? null : M.ev ? "desk_watch" : wanted(st);   // (the showcase plays its own clip; an event sits him back)
    if (m) { setMode(m); link(); } else if (M.mode) {        // off the desk modes (eating, leaving): seated he just sits back
      M.mode = null; M.link = null; M.w.type = M.w.mouse = M.ph.type = M.ph.mouse = 0; const a = st.goal && st.goal.clip === "dine" ? M.actions.act_eat : M.actions.desk_watch, cur = st.current;
      for (const k of ["sit", "type"]) env.actions[k] = M.actions.desk_watch;
      // (riding the chair out to leave too: he sits back first, so the page rides it with the seated loop on its seat point)
      if (st.at === "desk" && (!st.step || st.step.k === "chair") && cur !== a) { a.reset(); a.setEffectiveWeight(1); a.fadeIn(FADE).play(); if (cur) cur.fadeOut(FADE); env.setCurrent(a); }
    }
    if (SV && M.mode !== "desk_watch") SV.cur = null;        // (the desk states start over with the mode's own loop)
    if (!transition(st)) onBed(st);
    bedStep(st, dt);                                           // (the Sova bed clips over the page's lie and sleep, and the phone they hold)
    // the quilt and the pillow give under him lying awake on the bed: in as he lies down (the lift follows it frame by
    // frame through the step, no pop once he is down), out as he gets up or falls asleep under the duvet
    const lying = st.at === "bedlie" && !st.step, asleep = !!(st.goal && st.goal.clip === "sleep");
    const lyingTo = lying || !!(st.step && st.step.to === "bedlie");
    M.dentW = Math.max(0, Math.min(1, (M.dentW || 0) + (lyingTo && !asleep ? dt : -dt) / 0.6));
    pivot(st, dt);
    showStep();                                                // (the showcase's clip, before the guards measure him)
    baseY(); seatLift(st); bedLift(st, dt); floorLift(dt); M.lastY = env.boy.position.y;
    // (after the lifts: the dents are shaped from where he is drawn, not from his clip's height before bedLift raises him)
    if (env.quiltDent) env.quiltDent(M.dentW, dt); if (env.pillowDent && lying) env.pillowDent(1); else if (env.pillowDent && M.pil) env.pillowDent(0);
    M.pil = lying;
    shove(st, dt);                                             // (after the root is final: the hand reaches the chair where it is)
    bedThings(st, dt);
    if (st.at === "desk" && !st.step) roll(dt); else { M.off = 0; M.held = null; M.rollAt = null; }   // (off the desk the page places him and the chair)
    if (M.mode) hands(dt);
    if ((st.at === "desk" || (st.step && st.step.to === "desk")) && !(M.mode && M.w.type + M.w.mouse > 0.01)) { env.boy.updateMatrixWorld(true); eatReach(st, dt); deskClear("Left", dt); deskClear("Right", dt); }
    else if (CLR.Left || CLR.Right) { env.boy.updateMatrixWorld(true); clearRelease("Left", dt); clearRelease("Right", dt); }   // (the keys or the mouse take over: the swing lets go gently)
    wave(st, dt);
    props_(st); hairInit(); hairLights(dt);
    env.boy.updateMatrixWorld(true); correctives();           // (last: on the final pose)
    return moving;
  }
  // a short wave of his right hand toward the viewers (viewers' reactions spiked, mostly waves: desk_states.js GLANCE),
  // seated and watching only, drawn on top of the seated loop: the upper arm out and forward, the forearm up, the hand
  // swung side to side a few times, then back down. Anything else (typing, the mouse, a reaction, getting up) fades it out
  const WAVE = {in: 0.45, hold: 1.8, out: 0.55, hz: 2.2, amp: 0.35};
  function wave(st, dt) {
    const W = M.wave; if (!W) return;
    const B = env.bones, ua = B.RightArm, fa = B.RightForeArm, hd = B.RightHand, k3 = S("Right", 3, 1); if (!ua || !fa || !hd || !B.LeftArm) { M.wave = null; return; }
    const ok = st.at === "desk" && !st.step && M.mode === "desk_watch" && !M.ev && !M.sc;
    if (!ok && W.t < WAVE.in + WAVE.hold) W.t = WAVE.in + WAVE.hold + WAVE.out * (1 - Math.min(1, W.t / WAVE.in));   // (stopped early: straight to the way down, from where it is)
    W.t += dt; const t = W.t, sm = u => u * u * (3 - 2 * u), L = WAVE.in + WAVE.hold + WAVE.out;
    if (t >= L) { M.wave = null; return; }
    const w = t < WAVE.in ? sm(t / WAVE.in) : t < WAVE.in + WAVE.hold ? 1 : sm(1 - (t - WAVE.in - WAVE.hold) / WAVE.out);
    env.boy.updateMatrixWorld(true);
    const f = fwdV(), up = V(0, 1, 0), r = ua.getWorldPosition(V()).sub(B.LeftArm.getWorldPosition(V())).setY(0).normalize();   // (his right, from his shoulders)
    const sway = Math.sin(2 * Math.PI * WAVE.hz * Math.max(0, t - WAVE.in * 0.5)) * WAVE.amp * w;
    const aim = (b, c, dir) => { const cur = c.getWorldPosition(V()).sub(b.getWorldPosition(V())).normalize();
      const q = new THREE.Quaternion().slerp(new THREE.Quaternion().setFromUnitVectors(cur, dir.clone().normalize()), w);
      b.quaternion.copy(b.parent.getWorldQuaternion(new THREE.Quaternion()).invert().multiply(q.multiply(b.getWorldQuaternion(new THREE.Quaternion())))); b.updateMatrixWorld(true); };
    aim(ua, fa, V().addScaledVector(r, 0.6).addScaledVector(f, 0.55).addScaledVector(up, 0.1));   // (the elbow out and forward, about shoulder height)
    aim(fa, hd, V().addScaledVector(up, 1).addScaledVector(f, 0.15).addScaledVector(r, sway));     // (the forearm up, swaying)
    if (k3) aim(hd, k3, V().addScaledVector(up, 1).addScaledVector(f, 0.1).addScaledVector(r, sway * 1.4));   // (the hand along it, a little more)
  }
  // ?debug: where the wrists are in the clip's frame (to check the pins), and the tips' clearance
  function dbg() {
    env.boy.updateMatrixWorld(true);
    const loc = b => { const p = env.bones[b].getWorldPosition(V()); return env.boy.worldToLocal(p).toArray().map(v => +v.toFixed(3)); };
    return {mode: M.mode, L: loc("LeftHand"), R: loc("RightHand"), tipsL: +lowestTip("Left").toFixed(3), tipsR: +lowestTip("Right").toFixed(3),
      root: env.boy.position.toArray().map(v => +v.toFixed(3)), keys: P.keys, mouse: P.mouse,
      mouseAt: P.mouseNode ? P.mouseNode.position.toArray().map(v => +v.toFixed(3)) : null, grab: M.grab ? M.grab.toArray().map(v => +v.toFixed(3)) : null};
  }
  load().catch(e => console.warn("MakeHuman clips:", e));
  M.armIn = side => +(armIn(side) * 1000).toFixed(1); M.inDesk = (x, y, z) => +(inDesk(V(x, y, z)) * 1000).toFixed(1);
  M.contactGap = (side, name, i) => [1, 2, 3].map(j => +(gap(side, name, i, j) * 1000).toFixed(1));   // (?debug: a finger's clearance, mm)
  return {animate, dbg, show, rare, M, get ready() { return M.ready; }, get mode() { return M.mode; }};
}
