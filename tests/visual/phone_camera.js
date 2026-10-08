// Is he in the picture? (preview/phone-camera) The page's follow camera, frame by frame as the page's own frame() moves
// it (updateCameraGoal, the 1.2/s lerp, controls.update, keepClear), and each frame his projected bounding box: every
// visible skinned mesh of him (not his drawn inside), every k-th vertex skinned on the CPU, projected with the page's
// camera (its view offset included). The frame is the 3D canvas less what covers it: on a phone (the canvas at most 900
// px wide) the header block (#top: the name, the clock, what he does, the camera button) lies over the canvas's top, so
// the frame starts under it. Reported: the share of the box inside the frame, and whether his whole head (a 12 cm
// sphere round the head bone) is inside it.
// Run by tests/visual/test_phone_camera.py; only uses what ?debug exposes.
(() => {
  const V = new THREE.Vector3(), H = new THREE.Vector3();
  function parts() {
    const out = []; boy.traverse(o => { if (o.isSkinnedMesh && o.visible && !/_inside$/.test(o.name)) out.push(o); }); return out;
  }
  function frameTop() {                     // the frame's top in NDC y: 1, or the bottom of the header over the canvas
    const c = renderer.domElement.getBoundingClientRect(); if (c.width > 900) return 1;
    const t = document.getElementById("top").getBoundingClientRect();
    return Math.min(1, 1 - 2 * Math.max(0, t.bottom - c.top) / c.height);
  }
  const R = new THREE.Vector3(), E = new THREE.Vector3();
  function measure() {
    boy.updateMatrixWorld(true); camera.updateMatrixWorld(true);
    const top = frameTop();
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const m of parts()) {
      const pos = m.geometry.attributes.position, k = Math.max(1, Math.floor(pos.count / 1500));
      for (let i = 0; i < pos.count; i += k) {
        V.fromBufferAttribute(pos, i); m.applyBoneTransform(i, V); V.applyMatrix4(m.matrixWorld).project(camera);
        if (V.z > 1) continue;
        x0 = Math.min(x0, V.x); x1 = Math.max(x1, V.x); y0 = Math.min(y0, V.y); y1 = Math.max(y1, V.y);
      }
    }
    if (!(x1 > x0)) return {frac: 0, head: false, box: null};
    const ix = Math.max(0, Math.min(1, x1) - Math.max(-1, x0)), iy = Math.max(0, Math.min(top, y1) - Math.max(-1, y0));
    const frac = ix * iy / ((x1 - x0) * (y1 - y0));
    (bones.headfront || head).getWorldPosition(H);
    R.setFromMatrixColumn(camera.matrixWorld, 0).multiplyScalar(0.12).add(H).project(camera);   // the sphere's radius on screen
    E.setFromMatrixColumn(camera.matrixWorld, 1).multiplyScalar(0.12).add(H).project(camera);
    H.project(camera); const rx = Math.abs(R.x - H.x), ry = Math.abs(E.y - H.y);
    const headIn = H.z < 1 && H.x - rx >= -1 && H.x + rx <= 1 && H.y - ry >= -1 && H.y + ry <= top;
    return {frac, head: headIn, top: +top.toFixed(3), box: [x0, y0, x1, y1].map(v => +v.toFixed(3)), hd: [+H.x.toFixed(3), +H.y.toFixed(3), +rx.toFixed(3)]};
  }
  // the page's frame() camera step, as it runs when the visitor has not touched the camera
  function camStep(dt, snap) {
    updateCameraGoal();
    const k = snap ? 1 : 1 - Math.exp(-dt * 1.2);
    camera.position.lerp(camGoal.pos, k); controls.target.lerp(camGoal.target, k);
    controls.update(); __keepClear();
  }
  // n frames of dt: the simulation and the camera; worst share and head misses; snap the camera first if asked
  // (until: a predicate checked after each step; the run stops there, that frame unmeasured, and says so: done)
  window.__phoneCam = (n, dt, snap, until) => {
    window.FREEZE = true; if (snap) { animate_(dt); camStep(dt, true); }
    let worst = 1, worstAt = null, headMiss = 0, frames = 0, sum = 0, maxJump = 0; const P = camera.position.clone();
    let done = false;
    for (let i = 0; i < n; i++) {
      animate_(dt); camStep(dt, false);
      if (until && until()) { done = true; break; }     // (this frame is the next phase's)
      frames++;
      maxJump = Math.max(maxJump, camera.position.distanceTo(P)); P.copy(camera.position);
      const r = measure(); sum += r.frac;
      if (!r.head) headMiss++;
      if (r.frac < worst) { worst = r.frac; worstAt = {i, ...r, pose: pose().at, step: pose().step}; }
    }
    return {frames, done, worst: +worst.toFixed(3), mean: +(sum / Math.max(1, frames)).toFixed(3), head_miss: headMiss, worst_at: worstAt,
            max_cam_step_m: +maxJump.toFixed(3), cam: camera.position.toArray().map(v => +v.toFixed(2)), tgt: controls.target.toArray().map(v => +v.toFixed(2))};
  };
  window.__phoneCamNow = measure;
})();
