// A Mixamo-rigged character in the room: the character (room_build/kimodo/mixamo_glb.mjs: Mixamo's FBX as a GLB, its
// mixamorig:* skeleton of 65 bones with the fingers, the whole under one node scaled 0.01) and Mixamo clips played on it
// by bone name - the clips were recorded on this skeleton, so nothing is retargeted. Only the hips' travel is scaled,
// by the character's hip height over the clip skeleton's (a taller or shorter body covers the same steps in proportion).
//
// boy_mh.js and the page name the bones as the MakeHuman / v5 body did; the Mixamo bones get those names (NAMES), in the
// rig and in every clip's tracks alike, and the hips hang straight under the body so a Hips.position is in the body's
// frame (feet at y = 0, metres, facing +z: Mixamo's own frame), as char_v5.js does for v5.

const strip = n => n.replace(/^mixamorig\d*:?/, "");
// Mixamo -> the page's names (char_v5.js TO_MH's targets; the spine chain Hips > Spine02 > Spine01 > Spine > neck)
export const NAMES = {Hips: "Hips", Spine: "Spine02", Spine1: "Spine01", Spine2: "Spine", Neck: "neck", Head: "Head", HeadTop_End: "head_end"};
for (const [S, x] of [["Left", "L"], ["Right", "R"]]) {
  for (const b of ["Shoulder", "Arm", "ForeArm", "Hand", "UpLeg", "Leg", "Foot", "ToeBase"]) NAMES[S + b] = S + b;
  NAMES[S + "Toe_End"] = `toe1-2.${x}`;
  ["Thumb", "Index", "Middle", "Ring", "Pinky"].forEach((f, i) => { for (let j = 1; j <= 4; j++) NAMES[`${S}Hand${f}${j}`] = `finger${i + 1}-${j}.${x}`; });
}
export const pageName = n => NAMES[strip(n)] || strip(n);
export const isMixamo = root => { let y = false; root.traverse(o => { if (o.isBone && /^mixamorig\d*:?Hips$/.test(o.name)) y = true; }); return y; };

// the hips' height over the lowest foot joint, at rest (metres, world)
function hipHeight(THREE, root) {
  root.updateMatrixWorld(true); let hips = null, low = Infinity; const v = new THREE.Vector3();
  root.traverse(o => { const n = NAMES[strip(o.name)] || o.name;
    if (n === "Hips") hips = o.getWorldPosition(new THREE.Vector3()).y;
    if (/^(Left|Right)(Foot|ToeBase)$/.test(n)) low = Math.min(low, o.getWorldPosition(v).y); });
  return hips == null || low === Infinity ? null : hips - low;
}

// the loaded character glTF (g.scene) made into the body boy_mh.js expects; returns the conversion for its clips
export function prep(THREE, g) {
  const sc = g.scene; sc.updateMatrixWorld(true);
  let hip = null; sc.traverse(o => { if (o.isBone && strip(o.name) === "Hips") hip = o; });
  if (!hip) throw new Error("char_mixamo: no mixamorig Hips");
  const par = hip.parent;
  // a Hips value in its parent's frame (the clips') -> in the body's: M = body^-1 * parent (world, at rest)
  const M = new THREE.Matrix4().copy(sc.matrixWorld).invert().multiply(par.matrixWorld);
  const mp = new THREE.Vector3(), mq = new THREE.Quaternion(), ms = new THREE.Vector3(); M.decompose(mp, mq, ms);
  const H = hipHeight(THREE, sc);
  sc.attach(hip);                                      // (world transform kept: the skin is unchanged)
  sc.traverse(o => { if (o.isBone) o.name = pageName(o.name); });
  const conv = {M, q: mq, hipH: H};
  g.animations = g.animations.map(c => fixClip(THREE, c, conv));
  return conv;
}

// a clip's skeleton (the clip's own glTF, g.scene) for its hip height; without it the clip is taken to be recorded on a
// skeleton of the character's height (Mixamo's clips for this character are)
export const clipHipHeight = (THREE, g) => g && g.scene ? hipHeight(THREE, g.scene) : null;

// a Mixamo clip for the prepared character: the tracks renamed as the bones are, the hips' translation carried into the
// body's frame and scaled by hip height (conv.hipH / srcHipH), the hips' rotation turned with it; nothing else changes
export function fixClip(THREE, clip, conv, srcHipH) {
  const k = srcHipH && conv.hipH ? conv.hipH / srcHipH : 1, M = conv.M, q = conv.q, v = new THREE.Vector3(), r = new THREE.Quaternion();
  const tracks = clip.tracks.map(t => {
    const dot = t.name.lastIndexOf("."), node = t.name.slice(0, dot), prop = t.name.slice(dot + 1), name = pageName(node) + "." + prop;
    if (pageName(node) !== "Hips" || (prop !== "position" && prop !== "quaternion")) { const c = t.clone(); c.name = name; return c; }
    const vals = t.values.slice();
    if (prop === "position") {
      // in the body's frame, then the travel about the first frame's hips scaled (its height above the floor too)
      for (let i = 0; i < vals.length; i += 3) { v.fromArray(vals, i).applyMatrix4(M); v.toArray(vals, i); }
      for (let i = 0; i < vals.length; i++) vals[i] *= k;
    } else for (let i = 0; i < vals.length; i += 4) { r.fromArray(vals, i); r.premultiply(q); r.toArray(vals, i); }
    return new t.constructor(name, t.times.slice(), vals);
  });
  return new THREE.AnimationClip(clip.name, clip.duration, tracks);
}

// a hips position in the body's frame -> as the page's HIPS table reads it (char_v5.js legacyHips: G14 tuned the seat
// placement while v5's Hip hung under a group turned -90 deg; this body is the same mesh at the same size, so it is
// placed the same way)
export function legacyHips(THREE, h) {
  const v = new THREE.Vector3(h[0], h[1], h[2]).applyAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 2);
  return [v.x, v.y, v.z];
}

// room.html?char=mixamo: what boy_mh.js plays in each slot (room/mh_mx/). The desk is Mixamo's own captures on this
// skeleton, baked for our chair (kimodo/mx_build.sh, rows in kimodo/mx_clips.json): watching room_seated_idle (Seated_Idle),
// typing room_mx_typing (Typing) with Sit_To_Type / Type_To_Sit on the way in and out (kimodo/mixamo_chains.json's
// "working" chain and its 0.8 s links), sitting down and standing up room_mx_stand_to_sit / room_mx_sit_to_stand. The
// mouse plays watching's body (Seated_Idle, as on main), its right hand carried onto the mouse by the page; walking,
// standing, the bed, eating, the door and the window are v5's room clips carried onto this skeleton (kimodo/mx_convert.mjs: each bone moves as the v5 joint it was fitted from).
// kb / home: where the baked Typing has his fingertips over the keys (the mean of both hands' last finger joints over
// the clip, the body's frame), for the page's keyboard (boy_mh.js rolls him and the chair so it lands on the room's)
export const ROOM = {
  clips: {desk_type: "room_mx_typing", type_in: "room_mx_sit_to_type", type_out: "room_mx_type_to_sit"},
  links: {in: 0.3, out: 0.2, fromWatch: 0.8, toWatch: 0.8},
  // (kimodo/mx_build.sh Typing's report, fingertips_mean: x across, y up, z forward of his feet; the keys lie under it)
  clipFrame: {kb: [0.039, 0.862, 0.617], home: [0.039, 0.862, 0.617]},
  // for G14's keyboard resolver (boy_mh.js CLIP_MX): this bake's index fingers, F (left) and J (right): the last joints'
  // means over the clip, 1.5 cm on along the finger and 1 cm down, as G14 measured them on v5's bake
  clipMX: {F: [0.17, 0.829, 0.599], J: [-0.095, 0.859, 0.639], clip: "room_mx_typing"},
  // the seat points (boy_mh.js SEAT_AT: [across, forward of the chair's pivot]), swept in the room for this character
  // (kimodo/seat_sweep.mjs: the page's penetration() every 0.1 s over each mode's clip): clear of the chair from -0.06 m
  // (watching, typing and the mouse, which plays watching's body as on main) to past -0.12 m; each set 1.5 cm inside that
  seatAt: {desk_watch: [0, -0.075], desk_type: [0, -0.075], desk_mouse: [0, -0.075]},
  // eating at the desk: how much further back he sits than for watching (boy_mh.js EAT_BACK, v5 0.05): room_eat on this
  // skeleton leans his chest 52 sampled vertices into the desk's edge at 0.05 m, none at 0.10 m (eating_19, 8 s sweep)
  eatBack: 0.10,
  // sitting down at the desk (room_mx_stand_to_sit): the right thigh brushed the seat's front edge (1-7 sampled vertices
  // for a few frames, walking_8); lifted by up to this much mid-way, 0 at both ends (boy_mh.js seatLift())
  sitBump: 0.015,
};
