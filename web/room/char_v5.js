// Character v5 in the room (preview/room-v5): room/char_v5.glb (the Tripo v5 character, 41 bones, faces +X; fingers
// later) driven by room/boy_mh.js with the room clips retargeted onto it (room/mh_v5/, the same names as room/mh/;
// G14's room_build/kimodo/mh_retarget.mjs on preview/anim-kimodo).
//
// boy_mh.js was written for the MakeHuman rig: its bones' names (Hips, LeftUpLeg, ...), its clips in the body's own frame
// (feet at y = 0, facing +z, metres; Hips.position the hips' place in it). v5 is made to look the same to it:
//   - the rig is turned to face +z (a group turned -90 deg about y: G14's "v5 root at MH heading - 90 deg");
//   - its Hip is hung straight under the body itself (the glTF scene, the page's boy), keeping its world transform (the
//     skin follows the bones themselves, so nothing moves), so a Hip.position is in the body's frame, like the MakeHuman
//     Hips'; each clip's Hip tracks are carried into that frame (through the Armature's scale, the Z-up Root's turn and
//     the group's) and the Root's dropped. (Under the turned group, as at first, a clip's Hips.position values were turned
//     90 deg from where boy_mh.js samples the hips: its re-rooted get-up put him 2 m off, through the wall);
//   - the bones G3's code names get the MakeHuman names (G14's map, the other way), in the rig and in the clips' tracks.
// Bones without a MakeHuman counterpart (the twist bones, Pelvis, Spine01, NeckTwist02) keep their v5 names.

// (Waist -> Spine02 lines the spine up with the page's own chain, Hips > Spine02 > Spine01 > Spine > neck, in BODY_SEGS)
export const TO_MH = {Hip: "Hips", Waist: "Spine02", Spine02: "Spine", NeckTwist01: "neck", Head: "Head"};
for (const [s, S] of [["L", "Left"], ["R", "Right"]])
  Object.assign(TO_MH, {[`${s}_Clavicle`]: `${S}Shoulder`, [`${s}_Upperarm`]: `${S}Arm`, [`${s}_Forearm`]: `${S}ForeArm`, [`${s}_Hand`]: `${S}Hand`,
    [`${s}_Thigh`]: `${S}UpLeg`, [`${s}_Calf`]: `${S}Leg`, [`${s}_Foot`]: `${S}Foot`, [`${s}_ToeBase`]: `${S}ToeBase`});

// the loaded glTF (g.scene: the v5 rig) made into the body boy_mh.js expects; returns the conversion for its clips
export function prep(THREE, g) {
  const sc = g.scene, turn = new THREE.Group(); turn.name = "v5_turn"; turn.rotation.y = -Math.PI / 2;
  for (const c of [...sc.children]) turn.add(c);
  sc.add(turn); sc.updateMatrixWorld(true);
  const hip = sc.getObjectByName("Hip"), root = hip && hip.parent;
  if (!hip) throw new Error("char_v5: no Hip bone");
  // a Hip value in the Root's frame -> in the body's: M = body^-1 * Root (world matrices, the scene at rest)
  const M = new THREE.Matrix4().copy(sc.matrixWorld).invert().multiply(root.matrixWorld);
  const mp = new THREE.Vector3(), mq = new THREE.Quaternion(), ms = new THREE.Vector3(); M.decompose(mp, mq, ms);
  sc.attach(hip);                                      // (world transform kept: the skin is unchanged)
  const bones = []; sc.traverse(o => { if (o.isBone) bones.push(o); });   // (renamed together: Spine02 becomes Spine, Waist Spine02)
  for (const o of bones) if (TO_MH[o.name]) o.name = TO_MH[o.name];
  // the head's end (the page's duvet and pillow measure the head as Head -> head_end): 20 cm over the head at rest
  const head = sc.getObjectByName("Head");
  if (head && !sc.getObjectByName("head_end")) { const e = new THREE.Object3D(); e.name = "head_end"; sc.updateMatrixWorld(true);
    e.position.copy(head.worldToLocal(head.getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(0, 0.2, 0)))); head.add(e); }
  const conv = {M, q: mq, s: ms.x, turnInv: turn.quaternion.clone().invert()};
  g.animations = g.animations.map(c => fixClip(THREE, c, conv));
  sc.userData.v5 = conv;
  return conv;
}

// a clip on the bare v5 rig (G14's) -> on the prepared body: the Hip's tracks in the turned frame, MakeHuman names
export function fixClip(THREE, clip, conv) {
  const v = new THREE.Vector3(), q = new THREE.Quaternion(), tracks = [];
  for (const tr of clip.tracks) {
    const i = tr.name.lastIndexOf("."), bone = tr.name.slice(0, i), prop = tr.name.slice(i + 1);
    if (bone === "Root" || bone === "Armature") continue;          // (the Root no longer carries the body)
    let values = tr.values;
    if (bone === "Hip") {
      values = tr.values.slice();
      if (prop === "position") for (let k = 0; k < values.length; k += 3) v.fromArray(values, k).applyMatrix4(conv.M).toArray(values, k);
      else if (prop === "quaternion") for (let k = 0; k < values.length; k += 4) q.fromArray(values, k).premultiply(conv.q).toArray(values, k);
      else if (prop === "scale") for (let k = 0; k < values.length; k++) values[k] *= conv.s;
    }
    tracks.push(new tr.constructor(`${TO_MH[bone] || bone}.${prop}`, tr.times, values));
  }
  return new THREE.AnimationClip(clip.name, clip.duration, tracks);
}

// a hips position in the body's frame -> as it read while the Hip hung under the turned group (the page's HIPS table:
// G14's seat placement was tuned against those values; see boy_mh.js's pageHips)
export function legacyHips(THREE, h, conv) {
  const v = new THREE.Vector3(h[0], h[1], h[2]).applyQuaternion(conv.turnInv);
  return [v.x, v.y, v.z];
}
