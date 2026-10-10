// The camera's turn toward him while he answers viewers (preview/interactive): when a glance response starts (boy_mh.js
// counts them in M.respond: a wave, a smile, a look around, happy - desk_states.js GLANCE), the follow camera eases to a
// three-quarter front view of his face and upper body for a few seconds, then back. From behind (the default view at
// the desk) his answer was hard to see. Only while the camera follows him; the page's own camera is put back after each
// frame is drawn, so its follow keeps going underneath and the way back lands where it would have been anyway.

export const ENV = {in: 0.6, hold: 3.0, out: 0.8};          // (s)
export const VIEW = {fwd: 0.55, side: 0.85, up: 0.12, dist: 1.15, face: 0.0, near: 0.55, margin: 0.3};   // (m; near: the closest it comes when something stands in the way; margin: kept from it - at 0.1 m from the room's wall its edge showed past where the room ends)   // the view: from his front and one side (m)

// and lying on the bed with the phone (room/boy_mh.js's bed layer holds it), on a wide screen only: the follow camera keeps
// its angle and slowly comes in toward him (the phone was a speck from the overview), and goes back out when he puts it
// down; a glance answer still turns it to his face on top of that
export const BED = {dist: 2.6, in: 3.0, out: 2.0};          // (m from his chest; s to come in, to go out)

// the room's inside (room.html IN_ROOM: x -1.75..3.5, z -1.3..3.5), 0.2 m in from its walls
export const ROOM = {x0: -1.55, x1: 3.3, z0: -1.1, z1: 3.3};

export function weightAt(t) {                                // 0..1 at t s into the turn (smooth in and out); 0 outside it
  if (!(t >= 0)) return 0;
  const s = u => u * u * (3 - 2 * u);
  if (t < ENV.in) return s(t / ENV.in);
  if (t < ENV.in + ENV.hold) return 1;
  const u = (t - ENV.in - ENV.hold) / ENV.out;
  return u < 1 ? s(1 - u) : 0;
}
export const LENGTH = ENV.in + ENV.hold + ENV.out;

export function createGlanceCam(THREE) {
  let t = -1, seen = null, side = 0, dist = VIEW.dist;
  let wb = 0; const bt = new THREE.Vector3(), bd = new THREE.Vector3();
  const ray = new THREE.Raycaster();
  const P = new THREE.Vector3(), Q = new THREE.Vector3(), h = new THREE.Vector3(), c = new THREE.Vector3(), f = new THREE.Vector3(),
    r = new THREE.Vector3(), g = new THREE.Vector3(), at = new THREE.Vector3(), up = new THREE.Vector3(0, 1, 0);
  let saved = false;
  const api = {
    get active() { return t >= 0; },
    // after the page's camera, controls.update() and keepClear() (its push out of his body sent this close view through the
    // wall; the way to him is checked here instead), before the render: follows = the page follows him now
    apply(dt, follows, camera, controls, boy, bones) {
      saved = false;
      const M = globalThis.mh && globalThis.mh.M, n = M ? M.respond || 0 : 0;
      if (seen === null) seen = n;
      if (n !== seen) { seen = n; if (follows) { t = 0; side = 0; } }   // (a new answer: from the start)
      // the bed's zoom: its weight eases in and out; the page's camera brought in along its own direction to BED.dist
      const B = M && M.bed, onPhone = !!(B && B.cur && B.clips[B.cur] && B.clips[B.cur].phone);
      wb = Math.max(0, Math.min(1, wb + (follows && onPhone && camera.aspect >= 1 && boy && boy.visible ? dt / BED.in : -dt / BED.out)));
      if (wb > 0 && boy && bones.Head) { const k = wb * wb * (3 - 2 * wb);
        if (!saved) { P.copy(camera.position); Q.copy(controls.target); saved = true; }
        bones.Head.getWorldPosition(bt); (bones.Spine2 || bones.Spine02 || bones.Spine1 || bones.Spine01 || bones.Head).getWorldPosition(c); bt.lerp(c, 0.5);
        bd.copy(camera.position).sub(controls.target); const d0 = bd.length(); bd.normalize();
        controls.target.lerp(bt, k); camera.position.copy(controls.target).addScaledVector(bd, d0 + (Math.min(d0, BED.dist) - d0) * k); controls.update(); }
      if (t < 0) return;
      t += dt; if (t >= LENGTH || !follows || !boy || !boy.visible || !bones.Head) { t = -1; return; }
      const w = weightAt(t);
      boy.updateMatrixWorld(true);
      bones.Head.getWorldPosition(h); (bones.Spine2 || bones.Spine02 || bones.Spine1 || bones.Spine01 || bones.Neck || bones.Head).getWorldPosition(c);
      at.copy(h).lerp(c, VIEW.face);                         // (his face, a little towards his chest)
      boy.getWorldDirection(f).setY(0).normalize(); r.crossVectors(f, up).normalize();
      if (!side) side = camera.position.clone().sub(at).dot(r) >= 0 ? 1 : -1;   // (the side the camera is on already: the shorter way)
      g.copy(f).multiplyScalar(VIEW.fwd).addScaledVector(r, side * VIEW.side).normalize();
      if (t <= dt + 1e-6) {                                  // (once per turn: nothing between him and the camera - a shelf, the wall)
        dist = VIEW.dist; const root = boy.parent; ray.set(at, g); ray.far = VIEW.dist + VIEW.margin;
        if (root) for (const hit of ray.intersectObjects(root.children, true)) { let o = hit.object, his = false; while (o) { if (o === boy) { his = true; break; } o = o.parent; }
          if (his || !hit.object.visible || !hit.object.isMesh || hit.distance < VIEW.near) continue; dist = Math.max(VIEW.near, hit.distance - VIEW.margin); break; } }   // (nearer than VIEW.near: his own chair, the desk's edge - looked past)
      if (t <= dt + 1e-6) for (; dist > VIEW.near; dist -= 0.05) {   // (and inside the room: the window's glass is no mesh, and a ray through it
        c.copy(g).multiplyScalar(dist).add(at);                // left the camera outside, the dark beyond the wall in view)
        if (c.x > ROOM.x0 && c.x < ROOM.x1 && c.z > ROOM.z0 && c.z < ROOM.z1) break; }
      g.multiplyScalar(dist).add(at); g.y += VIEW.up;
      if (!saved) { P.copy(camera.position); Q.copy(controls.target); saved = true; }
      camera.position.lerp(g, w); controls.target.lerp(at, w); controls.update();
    },
    // after the render: the page's own camera back
    restore(camera, controls) {
      if (!saved) return; saved = false;
      camera.position.copy(P); controls.target.copy(Q); controls.update();
    },
  };
  globalThis.__glanceCam = api;                              // (the visual checks, whose frames the page's loop does not draw)
  return api;
}
