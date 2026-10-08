// room_build/charfix/probe.py's page side (injected into /room.html?debug): his feet, frame by frame.
//   sole(): per foot, the lowest vertex of what he stands on (the slides when on, else the socks / the body's feet) - F
//   pen(): sock vertices inside the slides' closed surface (+y ray parity over a 5 mm grid of the slides' triangles),
//          and the sock-slide pairs (the same place at rest: the shared seam and the 0.4 mm tube) apart in this frame
(() => {
  const F = 0.16, V = () => new THREE.Vector3();
  const D = window;
  const boy = () => D.boy;
  const skins = () => { const out = []; boy().traverse(o => { if (o.isSkinnedMesh && !/_inside$/.test(o.name)) out.push(o); }); return out; };
  const byName = n => skins().find(o => o.name === n || o.name.startsWith(n));
  const domBone = (sm, i) => { const I = sm.geometry.attributes.skinIndex, W = sm.geometry.attributes.skinWeight; let b = 0, bw = -1;
    for (let k = 0; k < 4; k++) if (W.getComponent(i, k) > bw) { bw = W.getComponent(i, k); b = I.getComponent(i, k); } return sm.skeleton.bones[b].name; };
  const footIdx = new Map();          // mesh -> {L: [...], R: [...]} vertices whose main bone is a foot / toe
  const feetOf = sm => { let f = footIdx.get(sm); if (f) return f; f = {L: [], R: []};
    const P = sm.geometry.attributes.position;
    for (let i = 0; i < P.count; i++) { const n = domBone(sm, i); if (!/Foot|Toe|toe|Leg$|Calf/.test(n)) continue; const s = /^Left|^L_|\.L$/.test(n) ? "L" : /^Right|^R_|\.R$/.test(n) ? "R" : null; if (s) f[s].push(i); }
    footIdx.set(sm, f); return f; };
  const v = V(), u = V();
  function sole() {
    boy().updateMatrixWorld(true);
    const sl = byName("slides"), parts = sl && sl.visible ? [sl] : skins().filter(o => o.visible && !/slides/.test(o.name));
    const out = {};
    for (const s of ["L", "R"]) { let low = 9;
      for (const sm of parts) { const f = feetOf(sm)[s]; for (const i of f) { sm.getVertexPosition(i, v).applyMatrix4(sm.matrixWorld); if (v.y < low) low = v.y; } }
      out[s] = low - F; }
    out.on = !!(sl && sl.visible);
    return out;
  }
  // sock-slide: candidates (sock vertices within 1 cm of a slide vertex at rest), pairs (within 1 mm at rest)
  let PRE = null;
  function prep() {
    const so = byName("socks"), sl = byName("slides"); if (!so || !sl) return null;
    const rest = sm => { const P = sm.geometry.attributes.position, a = []; for (let i = 0; i < P.count; i++) a.push(V().fromBufferAttribute(P, i).applyMatrix4(sm.bindMatrix)); return a; };
    const A = rest(so), B = rest(sl), g = new Map(), key = (x, y, z) => x + "," + y + "," + z, C = 0.01;
    B.forEach((p, i) => { const k = key(Math.floor(p.x / C), Math.floor(p.y / C), Math.floor(p.z / C)); (g.get(k) || g.set(k, []).get(k)).push(i); });
    const cand = [], pairs = [], seam = new Set();
    A.forEach((p, i) => { let best = 9, bj = -1; const cx = Math.floor(p.x / C), cy = Math.floor(p.y / C), cz = Math.floor(p.z / C);
      for (let x = cx - 1; x <= cx + 1; x++) for (let y = cy - 1; y <= cy + 1; y++) for (let z = cz - 1; z <= cz + 1; z++) for (const j of g.get(key(x, y, z)) || []) { const d = p.distanceTo(B[j]); if (d < best) { best = d; bj = j; } }
      if (best < 0.01) cand.push(i); if (best < 0.001) pairs.push([i, bj, best]); if (best < 5e-5) seam.add(i); });
    return PRE = {so, sl, cand, pairs, seam};
  }
  function pen() {
    const P0 = PRE || prep(); if (!P0) return null;
    const {so, sl, cand, pairs, seam} = P0; boy().updateMatrixWorld(true);
    const G = sl.geometry, I = G.index.array, n = G.attributes.position.count, pos = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) { sl.getVertexPosition(i, v).applyMatrix4(sl.matrixWorld); pos[3 * i] = v.x; pos[3 * i + 1] = v.y; pos[3 * i + 2] = v.z; }
    const C = 0.005, grid = new Map();
    for (let t = 0; t < I.length; t += 3) { const a = I[t], b = I[t + 1], c = I[t + 2];
      const x0 = Math.floor(Math.min(pos[3 * a], pos[3 * b], pos[3 * c]) / C), x1 = Math.floor(Math.max(pos[3 * a], pos[3 * b], pos[3 * c]) / C);
      const z0 = Math.floor(Math.min(pos[3 * a + 2], pos[3 * b + 2], pos[3 * c + 2]) / C), z1 = Math.floor(Math.max(pos[3 * a + 2], pos[3 * b + 2], pos[3 * c + 2]) / C);
      for (let x = x0; x <= x1; x++) for (let z = z0; z <= z1; z++) { const k = x + "," + z; (grid.get(k) || grid.set(k, []).get(k)).push(t); } }
    let inside = 0, maxDepth = 0; const hist = [0, 0, 0, 0], TRI = new THREE.Triangle();
    const sp = new Float32Array(3);
    for (const i of cand) { if (seam.has(i)) continue; so.getVertexPosition(i, v).applyMatrix4(so.matrixWorld);
      const tris = grid.get(Math.floor(v.x / C) + "," + Math.floor(v.z / C)) || []; let cross = 0, nearest = 9;
      for (const t of tris) { const a = 3 * I[t], b = 3 * I[t + 1], c = 3 * I[t + 2];
        // the vertical line through v against the triangle (2D barycentric in xz), above v
        const ax = pos[a], az = pos[a + 2], bx = pos[b], bz = pos[b + 2], cx = pos[c], cz = pos[c + 2];
        const d = (bz - cz) * (ax - cx) + (cx - bx) * (az - cz); if (Math.abs(d) < 1e-14) continue;
        const w0 = ((bz - cz) * (v.x - cx) + (cx - bx) * (v.z - cz)) / d, w1 = ((cz - az) * (v.x - cx) + (ax - cx) * (v.z - cz)) / d, w2 = 1 - w0 - w1;
        if (w0 < 0 || w1 < 0 || w2 < 0) continue;
        const y = w0 * pos[a + 1] + w1 * pos[b + 1] + w2 * pos[c + 1]; if (y > v.y) cross++; nearest = Math.min(nearest, Math.abs(y - v.y)); }
      if (cross % 2 === 1) { inside++;       // its depth: the 3D distance to the slides' surface (the triangles round it)
        const cx = Math.floor(v.x / C), cz = Math.floor(v.z / C); let d3 = 9;
        for (let x = cx - 2; x <= cx + 2; x++) for (let z = cz - 2; z <= cz + 2; z++) for (const t of grid.get(x + "," + z) || []) {
          TRI.a.fromArray(pos, 3 * I[t]); TRI.b.fromArray(pos, 3 * I[t + 1]); TRI.c.fromArray(pos, 3 * I[t + 2]); d3 = Math.min(d3, TRI.closestPointToPoint(v, u).distanceTo(v)); }
        hist[d3 < 0.0005 ? 0 : d3 < 0.001 ? 1 : d3 < 0.002 ? 2 : 3]++; maxDepth = Math.max(maxDepth, d3); } }
    let gapMax = 0, gapMin = 9;
    for (const [i, j] of pairs) { so.getVertexPosition(i, v).applyMatrix4(so.matrixWorld); sl.getVertexPosition(j, u).applyMatrix4(sl.matrixWorld); const d = v.distanceTo(u); gapMax = Math.max(gapMax, d); gapMin = Math.min(gapMin, d); }
    return {inside, depth_mm: +(maxDepth * 1000).toFixed(2), by_depth: {"<0.5mm": hist[0], "0.5-1mm": hist[1], "1-2mm": hist[2], ">2mm": hist[3]}, cand: cand.length, pairs: pairs.length, seam: seam.size, gap_max_mm: +(gapMax * 1000).toFixed(3), gap_min_mm: +(gapMin * 1000).toFixed(3)};
  }
  function run(setup, seconds, stride = 3, withPen = true) {
    setup(); const n = Math.round(seconds * 30), res = {frames: 0, sole: {L: [9, -9], R: [9, -9], low: [9, -9], high_support: -9}, pen: {inside_max: 0, depth_max_mm: 0, gap_max_mm: 0}, on_frames: 0, off_frames: 0};
    for (let f = 0; f < n; f++) { animate_(1 / 30); if (f % stride) continue; res.frames++;
      const s = sole(); s.on ? res.on_frames++ : res.off_frames++;
      for (const k of ["L", "R"]) { res.sole[k][0] = Math.min(res.sole[k][0], s[k]); res.sole[k][1] = Math.max(res.sole[k][1], s[k]); }
      const lo = Math.min(s.L, s.R); res.sole.low[0] = Math.min(res.sole.low[0], lo); res.sole.low[1] = Math.max(res.sole.low[1], lo);
      if (withPen) { const p = pen(); if (p) { res.pen.inside_max = Math.max(res.pen.inside_max, p.inside); res.pen.depth_max_mm = Math.max(res.pen.depth_max_mm, p.depth_mm); res.pen.gap_max_mm = Math.max(res.pen.gap_max_mm, p.gap_max_mm);
        res.pen.by_depth_worst = res.pen.by_depth_worst || {}; for (const [k, n] of Object.entries(p.by_depth)) res.pen.by_depth_worst[k] = Math.max(res.pen.by_depth_worst[k] || 0, n); res.pen.info = {cand: p.cand, pairs: p.pairs, seam: p.seam}; } } }
    const mm = x => +(x * 1000).toFixed(1);
    return {frames: res.frames, slides_on_frames: res.on_frames, slides_off_frames: res.off_frames,
      sole_mm: {L: res.sole.L.map(mm), R: res.sole.R.map(mm), lowest_foot: res.sole.low.map(mm)}, sock_slide: res.pen};
  }
  // a camera on his feet (or on the parked slides): azimuths round them from his facing, the first ones with a clear
  // line of sight (no room mesh between) inside the room; NOCLEAR: the page's own camera clearance off for the shot
  function feetCam(az, dist = 0.6, up = 0.22, what = "feet") {
    D.NOCLEAR = true; const b = boy(); b.updateMatrixWorld(true);
    let tgt;
    if (what === "parked") { const pk = D.scene.getObjectByName("slides_parked"); tgt = new THREE.Box3().setFromObject(pk).getCenter(V()); }
    else { const L = D.bones.LeftFoot.getWorldPosition(V()), R = D.bones.RightFoot.getWorldPosition(V()); tgt = L.add(R).multiplyScalar(0.5); tgt.y = Math.max(tgt.y, F) + 0.05; }
    const f = V().set(0, 0, 1).applyQuaternion(b.getWorldQuaternion(new THREE.Quaternion())).setY(0).normalize(), a0 = Math.atan2(f.x, f.z) + az;
    const pos = tgt.clone().add(V().set(Math.sin(a0) * dist, up, Math.cos(a0) * dist));
    const meshes = []; D.scene.traverse(m => { if (!m.isMesh || !m.visible) return; let o = m; while (o) { if (o === b) return; o = o.parent; } meshes.push(m); });
    const ray = new THREE.Raycaster(), dir = V().subVectors(tgt, pos), d = dir.length(); ray.set(pos, dir.normalize()); ray.far = d - 0.12;
    const hit = ray.intersectObjects(meshes, false)[0];
    const inRoom = pos.x > -1.85 && pos.z > -1.4 && pos.x < 3.5 && pos.z < 3.5 && pos.y > F + 0.03;
    D.camera.position.copy(pos); D.controls.target.copy(tgt); D.controls.update(); D.camera.position.copy(pos); D.camera.lookAt(tgt);
    return {clear: !hit && inRoom, by: hit ? hit.object.name : null, pos: pos.toArray().map(x => +x.toFixed(3)), tgt: tgt.toArray().map(x => +x.toFixed(3))};
  }
  function state() { const sl = byName("slides"), so = byName("socks"), parked = D.scene.getObjectByName("slides_parked");
    return {slides: sl ? sl.visible : null, socks: so ? so.visible : null, parked: parked ? parked.visible : null, parked_children: parked ? parked.children.length : 0,
      meshes: skins().map(o => o.name + ":" + o.geometry.index.count / 3)}; }
  window.__feet = {sole, pen, run, feetCam, state, prep};
})();
