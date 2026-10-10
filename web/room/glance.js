// A glance toward the camera (preview/interactive): when viewers' reactions spike, the server sends {type: "glance"}
// (live_server.py, audience.py: 10 reactions within 10 s, at most once every 2 minutes) and he turns his head toward
// the viewer's camera once, then back. Drawn on top of whatever clip plays (after the mixer, each frame): the neck and
// the head share the turn, capped so it stays a glance, never a twist. The desk states (room/desk_states.js) get the
// same message through the page's deskEv hook and answer it with a look up (attend).

export const ENV = {in: 0.35, hold: 1.3, out: 0.6};          // (s) turn toward, hold, turn back
export const MAX_DEG = 55;                                   // the most the head + neck turn away from where they face
export const SHARE = {Neck: 0.4, Head: 0.6};                 // of the turn

// the turn's weight 0..1 at t seconds into the glance (smooth in and out); 0 outside it
export function weightAt(t) {
  if (!(t >= 0)) return 0;
  const s = u => u * u * (3 - 2 * u);
  if (t < ENV.in) return s(t / ENV.in);
  if (t < ENV.in + ENV.hold) return 1;
  const u = (t - ENV.in - ENV.hold) / ENV.out;
  return u < 1 ? s(1 - u) : 0;
}
export const LENGTH = ENV.in + ENV.hold + ENV.out;

export function createGlance(THREE) {
  let t = -1;                                                // seconds into the current glance; < 0: none
  const _h = new THREE.Vector3(), _f = new THREE.Vector3(), _c = new THREE.Vector3(), _q = new THREE.Quaternion(),
    _p = new THREE.Quaternion(), _w = new THREE.Quaternion(), _id = new THREE.Quaternion(), _e = new THREE.Euler();
  return {
    trigger(upright = true) { if (t < 0 && upright) t = 0; },   // (one at a time; lying down: none, the server checks it too)
    get active() { return t >= 0; },
    // after the clips: turn bones.Neck / bones.Head toward camera.position by the envelope's weight
    apply(dt, boy, bones, camera) {
      if (t < 0 || !boy || !camera) return;
      t += dt; const w = weightAt(t); if (t >= LENGTH) { t = -1; return; }
      const head = bones.Head; if (!head || !boy.visible) return;
      boy.updateMatrixWorld(true);
      head.getWorldPosition(_h);
      boy.getWorldDirection(_f).setY(0).normalize();         // where his body faces (+z of the root)
      _c.copy(camera.position).sub(_h).normalize();
      _q.setFromUnitVectors(_f, _c);
      _e.setFromQuaternion(_q, "YXZ");                       // a turn (yaw) and a nod (pitch), no roll; capped
      const lim = MAX_DEG * Math.PI / 180;
      _e.y = Math.max(-lim, Math.min(lim, _e.y)); _e.x = Math.max(-lim / 2, Math.min(lim / 2, _e.x)); _e.z = 0;
      _q.setFromEuler(_e);
      for (const [name, share] of Object.entries(SHARE)) {
        const b = bones[name]; if (!b || !b.parent) continue;
        const qq = _id.clone().slerp(_q, w * share);         // this bone's part of the turn, in world space
        b.parent.getWorldQuaternion(_p).invert();
        b.quaternion.copy(_p.multiply(b.getWorldQuaternion(_w).premultiply(qq)));
        b.updateMatrixWorld(true);
      }
    },
  };
}
