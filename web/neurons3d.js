/* Neurons3D: his live spiking neurons inside the 3D brain (#62), each drawn as a small real neuron (#88: the forest).
   Reusable: /brain draws it today, and the room's mini brain can import it with a few lines (it needs only THREE, a
   scene, the region centroids, the cortex and neurons_morph.json).

   Simulated spiking neurons (1M on GPU / 20k on CPU) inside the real wiring of one person's brain; each drawn cell
   stands for a sampled model neuron; a model, not a mind.

   Usage:
     const n3 = Neurons3D.create({THREE, scene, nodes, cortex, cortexIdx, morph, sizes, maxCells});
       nodes     : brain.json nodes (214, in the spiking networks' region order): {q:[x,y,z], group, name}
       cortex    : Float32Array of cortex.bin vertex positions (optional; without it every region is a small cloud)
       cortexIdx : Uint32Array of cortex_idx.bin (optional): the surface normals pyramidal cells point along
       morph     : neurons_morph.json (real NeuroMorpho.Org cells); without it every cell is a soma only
       sizes     : neurons3d.json "sizes": cells a region (the 20k network's populations; scaled to maxCells)
     n3.resize(bufferHeightPx, fovDeg) on resize
     n3.onFrame(msg)       every {"type":"spiking"} websocket frame (spiking/frames.py: n3.rq rates, n3.sq spikes)
     n3.update(nowMs)      once per rendered frame (cheap: a few uniforms)
     n3.setVisible(on)     the toggle; n3.state() -> {live, net, tint, cells, segments, drawCalls, enlarge, types} for the caption
   Data: one byte a region of spike rate (log scale 0.1-100 Hz, byte 0 = below), 3 bytes a spike (region, slot 0-255,
   time 0-255 of the frame's span). Every glow is a recorded spike of a model neuron; with no frames the cells stand
   still (offline). Drawing: one instanced LineSegments per cell type (<= 6) + one instanced soma mesh (no points); <= 40
   segments a cell, maxCells cells (600 desktop, 300 phone, 240 mini); nothing is uploaded while it is hidden. */
(function (root) {
  "use strict";
  const LIVE_MS = 10000, RATE_LO = 0.1, RATE_HI = 100, FLASH_S = 0.35;

  function unb64(s) {
    if (!s) return new Uint8Array(0);
    const b = atob(s), out = new Uint8Array(b.length);
    for (let i = 0; i < b.length; i++) out[i] = b.charCodeAt(i);
    return out;
  }
  // rate (Hz) -> the byte quantise_rates sends (for group-rate tinting when a network sends no per-region rates)
  const rateByte = hz => !(hz >= RATE_LO) ? 0 : Math.max(1, Math.min(255, Math.round(1 + 254 * Math.log(Math.min(hz, RATE_HI) / RATE_LO) / Math.log(RATE_HI / RATE_LO))));
  function mulberry(seed) { let a = seed >>> 0; return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
  function rng(seed) { let s = seed >>> 0 || 1; return () => { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; }; }

  // ---------- where the cells go: inside each region, from its centroid and the cortex mesh ----------
  // vert[j]: the cortex vertex cell j sits under (-1: a nucleus cell), for the local surface normal
  function layout(nodes, cortex, sizes, maxCells) {
    const R = nodes.length, total = sizes.reduce((a, b) => a + b, 0), k = Math.min(1, maxCells / total);
    const count = sizes.map(s => Math.max(1, Math.floor(s * k)));     // >= 1 a region (every region keeps its spikes)
    for (let tot = count.reduce((a, b) => a + b, 0); tot > Math.max(R, maxCells); tot--) {
      let m = 0; for (let r = 1; r < R; r++) if (count[r] > count[m]) m = r;   // over the cap: trim the largest regions
      count[m]--;
    }
    const start = new Int32Array(R + 1);
    for (let r = 0; r < R; r++) start[r + 1] = start[r] + count[r];
    const N = start[R], pos = new Float32Array(N * 3), reg = new Float32Array(N), vert = new Int32Array(N).fill(-1), rand = rng(62);
    // cortex vertices -> nearest cortical centroid (the Schaefer parcels sit on the cortex; nuclei are inside)
    const cort = [], cells = nodes.map(() => []);
    nodes.forEach((n, i) => { if (/^(LH|RH)_/.test(n.name || "")) cort.push(i); });
    if (cortex && cortex.length) {
      const step = cortex.length / 3 > 40000 ? 2 : 1;                // half the vertices are plenty to find the cells
      for (let v = 0; v < cortex.length / 3; v += step) {
        const x = cortex[3 * v], y = cortex[3 * v + 1], z = cortex[3 * v + 2];
        let best = -1, bd = 1e30;
        for (const i of cort) { const q = nodes[i].q, d = (x - q[0]) ** 2 + (y - q[1]) ** 2 + (z - q[2]) ** 2; if (d < bd) { bd = d; best = i; } }
        if (best >= 0 && bd < 30 * 30) cells[best].push(v);
      }
    }
    for (let r = 0; r < R; r++) {
      const q = nodes[r].q, cell = cells[r], rad = 2.5 + 1.1 * Math.cbrt(count[r]);
      for (let j = start[r]; j < start[r + 1]; j++) {
        let x, y, z;
        if (cell.length > 8) {                                     // just under the cortical surface of its parcel
          const v = cell[Math.floor(rand() * cell.length)], u = 0.04 + 0.2 * rand();
          x = cortex[3 * v] + (q[0] - cortex[3 * v]) * u; y = cortex[3 * v + 1] + (q[1] - cortex[3 * v + 1]) * u;
          z = cortex[3 * v + 2] + (q[2] - cortex[3 * v + 2]) * u; vert[j] = v;
        } else {                                                    // a nucleus: a small cloud around its centroid
          const a = rand() * 6.2832, c = 2 * rand() - 1, s = Math.sqrt(1 - c * c), rr = rad * Math.cbrt(rand());
          x = q[0] + rr * s * Math.cos(a); y = q[1] + rr * s * Math.sin(a); z = q[2] + rr * c;
        }
        pos[3 * j] = x + (rand() - 0.5) * 0.8; pos[3 * j + 1] = y + (rand() - 0.5) * 0.8; pos[3 * j + 2] = z + (rand() - 0.5) * 0.8;
        reg[j] = r;
      }
    }
    return { N, pos, reg, start, count, vert };
  }

  // outward unit normals of the cortex mesh (face normals summed per vertex; the winding's sign checked against each
  // hemisphere's centre). Without the index buffer: the direction from the parcel centroid to the vertex.
  function cortexNormals(cortex, idx) {
    const nv = cortex.length / 3, n = new Float32Array(cortex.length);
    for (let f = 0; f + 2 < idx.length; f += 3) {
      const a = 3 * idx[f], b = 3 * idx[f + 1], c = 3 * idx[f + 2];
      const ux = cortex[b] - cortex[a], uy = cortex[b + 1] - cortex[a + 1], uz = cortex[b + 2] - cortex[a + 2];
      const vx = cortex[c] - cortex[a], vy = cortex[c + 1] - cortex[a + 1], vz = cortex[c + 2] - cortex[a + 2];
      const x = uy * vz - uz * vy, y = uz * vx - ux * vz, z = ux * vy - uy * vx;
      for (const o of [a, b, c]) { n[o] += x; n[o + 1] += y; n[o + 2] += z; }
    }
    const ctr = [[0, 0, 0, 0], [0, 0, 0, 0]];                        // hemisphere centres (x < 0: left)
    for (let v = 0; v < nv; v++) { const h = ctr[cortex[3 * v] < 0 ? 0 : 1]; h[0] += cortex[3 * v]; h[1] += cortex[3 * v + 1]; h[2] += cortex[3 * v + 2]; h[3]++; }
    for (const h of ctr) for (let a = 0; a < 3; a++) h[a] /= Math.max(1, h[3]);
    let out = 0;
    for (let v = 0; v < nv; v++) {
      const h = ctr[cortex[3 * v] < 0 ? 0 : 1], l = Math.hypot(n[3 * v], n[3 * v + 1], n[3 * v + 2]) || 1;
      n[3 * v] /= l; n[3 * v + 1] /= l; n[3 * v + 2] /= l;
      out += Math.sign(n[3 * v] * (cortex[3 * v] - h[0]) + n[3 * v + 1] * (cortex[3 * v + 1] - h[1]) + n[3 * v + 2] * (cortex[3 * v + 2] - h[2]));
    }
    if (out < 0) for (let i = 0; i < n.length; i++) n[i] = -n[i];   // the mesh is wound inwards: flip it once
    return n;
  }

  // ---------- one real cell, simplified to <= maxSeg straight segments ----------
  // The reconstruction (neurons_morph.json: <= 300 segments, soma at the origin, apical dendrite up +y) is rebuilt as a
  // tree; unbranched runs between branch points are straightened (Ramer-Douglas-Peucker, tolerance 4 % of the cell),
  // and the shortest terminal branches are pruned first until it fits. The last branch of a kind (axon, basal,
  // apical) is never pruned, so every cell keeps its axon for the spike to run along; the axon gets <= 35 % of them.
  // axonUm: draw the axon only to that path length from the soma (whole-brain view: its long straight runs are clutter).
  const AXON_SHARE = 0.35;
  function simplify(cell, maxSeg, axonUm) {
    const P = cell.pos, K = cell.kind, D = cell.dist, key = (x, y, z) => `${Math.round(x * 100)},${Math.round(y * 100)},${Math.round(z * 100)}`;
    const ids = new Map([[key(0, 0, 0), 0]]), xyz = [[0, 0, 0]], parent = [-1], kind = [0], dist = [0];
    const id = (x, y, z, k, d) => { const s = key(x, y, z); let i = ids.get(s);
      if (i === undefined) { i = xyz.length; ids.set(s, i); xyz.push([x, y, z]); parent.push(-1); kind.push(k); dist.push(d); } return i; };
    for (let i = 0; i < cell.n_seg; i++) {
      if (axonUm && K[i] === 1 && D[2 * i] >= axonUm) continue;        // the axon only to its first axonUm (path length)
      const a = id(P[6 * i], P[6 * i + 1], P[6 * i + 2], K[i], D[2 * i]), b = id(P[6 * i + 3], P[6 * i + 4], P[6 * i + 5], K[i], D[2 * i + 1]);
      if (b !== 0 && parent[b] < 0) { parent[b] = a; kind[b] = K[i]; dist[b] = D[2 * i + 1]; }
    }
    const M = xyz.length, kept = new Uint8Array(M).fill(1), ext = Math.max(...[0, 1, 2].map(a => cell.box[3 + a] - cell.box[a]));
    const len = (a, b) => Math.hypot(xyz[a][0] - xyz[b][0], xyz[a][1] - xyz[b][1], xyz[a][2] - xyz[b][2]);
    function rdp(pts, tol) {                                           // indices into xyz, endpoints kept
      if (pts.length < 3) return pts;
      const a = xyz[pts[0]], b = xyz[pts[pts.length - 1]], ab = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], L = Math.hypot(...ab) || 1e-9;
      let wi = -1, wd = -1;
      for (let i = 1; i < pts.length - 1; i++) { const p = xyz[pts[i]], ap = [p[0] - a[0], p[1] - a[1], p[2] - a[2]];
        const c = [ap[1] * ab[2] - ap[2] * ab[1], ap[2] * ab[0] - ap[0] * ab[2], ap[0] * ab[1] - ap[1] * ab[0]], d = Math.hypot(...c) / L;
        if (d > wd) { wd = d; wi = i; } }
      if (wd <= tol) return [pts[0], pts[pts.length - 1]];
      return rdp(pts.slice(0, wi + 1), tol).concat(rdp(pts.slice(wi), tol).slice(1));
    }
    function chains() {                                                // runs from a key node up to the next key node
      const kids = new Int32Array(M);
      for (let i = 1; i < M; i++) if (kept[i] && parent[i] >= 0) kids[parent[i]]++;
      const isKey = i => i === 0 || kids[i] !== 1 || kind[i] !== kind[parent[i]];
      const out = [];
      for (let i = 1; i < M; i++) {
        if (!kept[i] || parent[i] < 0 || !isKey(i)) continue;
        const pts = [i]; let j = i, L = 0;
        while (j !== 0 && parent[j] >= 0 && (j === i || !isKey(j))) { L += len(j, parent[j]); j = parent[j]; pts.push(j); }
        out.push({ pts: pts.reverse(), leaf: kids[i] === 0, kind: kind[i], L });
      }
      return out;
    }
    let tol = 0.04 * ext, ch = chains();
    const segs = (c, axon) => c.reduce((a, x) => a + (axon == null || (x.kind === 1) === axon ? rdp(x.pts, tol).length - 1 : 0), 0);
    for (let guard = 0; segs(ch) > maxSeg && guard < 2000; guard++) {
      const leaves = ch.filter(c => c.leaf), perKind = {};
      for (const c of leaves) perKind[c.kind] = (perKind[c.kind] || 0) + 1;
      const ok = leaves.filter(c => perKind[c.kind] > 1).sort((a, b) => a.L - b.L);
      const axonFirst = segs(ch, true) > AXON_SHARE * maxSeg;           // the axon gets at most its share
      const cand = ok.find(c => (c.kind === 1) === axonFirst) || ok[0];
      if (!cand) { tol *= 1.5; continue; }                             // only trunks left: straighten them more
      for (let i = 1; i < cand.pts.length; i++) kept[cand.pts[i]] = 0;
      ch = chains();
    }
    const out = [];
    for (const c of ch) { const p = rdp(c.pts, tol); for (let i = 1; i < p.length; i++) out.push([p[i - 1], p[i], c.kind]); }
    const n = out.length, pos = new Float32Array(n * 6), dst = new Float32Array(n * 2), kd = new Float32Array(n * 2);
    let axon = 0;
    out.forEach(([a, b, k], i) => { pos.set(xyz[a], 6 * i); pos.set(xyz[b], 6 * i + 3); dst[2 * i] = dist[a]; dst[2 * i + 1] = dist[b];
      kd[2 * i] = kd[2 * i + 1] = k; if (k === 1) axon = Math.max(axon, dist[b]); });
    return { n, pos, dist: dst, kind: kd, axon };
  }

  // a unit icosahedron, flat-shaded (non-indexed): positions and normals for a soma body
  function somaGeometry(THREE) {
    const t = (1 + Math.sqrt(5)) / 2, V = [[-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0], [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t],
      [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]].map(v => { const l = Math.hypot(...v); return v.map(x => x / l); });
    const F = [[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11], [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
      [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9], [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]];
    const pos = new Float32Array(F.length * 9), nrm = new Float32Array(F.length * 9);
    F.forEach((f, k) => f.forEach((vi, m) => { pos.set(V[vi], 9 * k + 3 * m); nrm.set(V[vi], 9 * k + 3 * m); }));
    return { position: new THREE.BufferAttribute(pos, 3), normal: new THREE.BufferAttribute(nrm, 3) };
  }

  // ---------- the whole-brain forest (#88): every sampled model neuron drawn as a small real cell ----------
  // Cell types by region: what the close-ups use. The pallidum has no reconstruction in the set: its cells are somata.
  const FOREST_SEG = 40, ENLARGE = 6, FOREST_AXON_UM = 400;         // <= 40 segments a cell, drawn 6x their size; axon to 400 um
  const FOREST_SPEED = 2000, FOREST_TRAIL = 250;                    // a spike lights the axon soma -> front (2 mm/s), fading behind
  const FOREST_SLOWDOWN = Math.round(0.5e6 / FOREST_SPEED);         // ~250x slower than a thin unmyelinated axon
  // The look (#88 follow-up: the first version saturated to white). Like a sparse stain under a dark-field microscope:
  // one muted hue a cell type, a dim base (<= FOREST_BASE before additive blending, so a few overlapping cells stay
  // grey), the region's rate only warms the hue a little; only a recorded spike brightens a cell, briefly, from the
  // soma along its axon.
  const FOREST_BASE = 0.12, FOREST_SPIKE = 0.7;
  // Microscope optics (#99), in the vertex shader (no post-processing pass, so it costs a phone nothing): a light
  // sheet / shallow depth of field keeps cells near the focal plane (the depth of what the camera looks at) at full
  // strength and dims the rest to 35 %, and the out-of-focus light drifts toward the slight blue-green of a
  // fluorescence image (scatter). It only ever dims or re-tints: never brighter than the cell itself.
  const LIGHT_SHEET = `
    vec3 lightSheet(vec3 c, float depth, float focus){
      float dz = (depth - focus) / max(1e-4, 0.35 * focus);
      float inFocus = 1.0 / (1.0 + dz * dz);
      vec3 tint = vec3(dot(c, vec3(0.3, 0.45, 0.25))) * vec3(0.72, 1.0, 0.95);   // grey -> faint cyan-green
      return mix(tint, c, 0.55 + 0.45 * inFocus) * (0.35 + 0.65 * inFocus);
    }`;
  const FOREST_HUE = { pyramidal: [0.62, 0.8, 0.66], basket: [0.85, 0.7, 0.55], medium_spiny: [0.78, 0.66, 0.84],
                       relay: [0.62, 0.74, 0.9], ca1_pyramidal: [0.62, 0.82, 0.72], amygdala_principal: [0.88, 0.68, 0.62] };
  const SOMA_HUE = [0.75, 0.75, 0.78];                              // a soma of no shaped type (pallidum)
  const FOREST_TYPES = { cortex: [["pyramidal", 0.8], ["basket", 0.2]], striatum: [["medium_spiny", 1]], thalamus: [["relay", 1]],
                         hippocampus: [["ca1_pyramidal", 1]], amygdala: [["amygdala_principal", 1]] };
  // per cell: which way it points. Pyramidal cells in the cortex: apical dendrite (+y) along the local surface normal,
  // any turn about it. CA1 pyramids: within 30 degrees of one axis per region (a layered structure). The rest
  // (multipolar): any orientation. Half of all cells mirrored (x).
  function quatFromTo(u, v) {                                       // unit vectors -> [x, y, z, w]
    const d = u[0] * v[0] + u[1] * v[1] + u[2] * v[2];
    if (d < -0.999999) return [1, 0, 0, 0];
    const c = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]], w = 1 + d, l = Math.hypot(c[0], c[1], c[2], w);
    return [c[0] / l, c[1] / l, c[2] / l, w / l];
  }
  function quatMul(a, b) {
    return [a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1], a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
            a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3], a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2]];
  }
  const yawQ = a => [0, Math.sin(a / 2), 0, Math.cos(a / 2)];      // a turn about the cell's own +y
  function randDir(rnd) { const c = 2 * rnd() - 1, s = Math.sqrt(1 - c * c), a = 6.2832 * rnd(); return [s * Math.cos(a), s * Math.sin(a), c]; }
  function coneDir(axis, deg, rnd) {                                // a direction within deg of axis
    const c = 1 - (1 - Math.cos(deg * Math.PI / 180)) * rnd(), s = Math.sqrt(1 - c * c), a = 6.2832 * rnd();
    const q = quatFromTo([0, 0, 1], axis), v = [s * Math.cos(a), s * Math.sin(a), c];
    const t = [2 * (q[1] * v[2] - q[2] * v[1]), 2 * (q[2] * v[0] - q[0] * v[2]), 2 * (q[0] * v[1] - q[1] * v[0])];
    return [v[0] + q[3] * t[0] + q[1] * t[2] - q[2] * t[1], v[1] + q[3] * t[1] + q[2] * t[0] - q[0] * t[2], v[2] + q[3] * t[2] + q[0] * t[1] - q[1] * t[0]];
  }

  function create(o) {
    const THREE = o.THREE, nodes = o.nodes, R = nodes.length, morph = o.morph;
    const sizes = o.sizes && o.sizes.length === R ? o.sizes : nodes.map(() => 90);
    const L = layout(nodes, o.cortex, sizes, o.maxCells || 600);
    const normals = o.cortex && o.cortexIdx ? cortexNormals(o.cortex, o.cortexIdx) : null;
    const rnd = mulberry(880), group = new THREE.Group(); group.name = "neurons"; group.visible = false;
    // per region: R = rate byte (smoothed), G = decision race highlight (striatum while a race runs)
    const texData = new Uint8Array(256 * 4), tex = new THREE.DataTexture(texData, 256, 1, THREE.RGBAFormat);
    tex.needsUpdate = true;
    const striatum = nodes.map(n => n.group === "reward");
    const uniforms = { uTime: { value: 0 }, uRates: { value: tex }, uFade: { value: 0 }, uLive: { value: 0 },
                       uUnit: { value: ENLARGE / 1000 }, uSpeed: { value: FOREST_SPEED }, uTrail: { value: FOREST_TRAIL },
                       uSize: { value: o.somaSize || 1.0 }, uScale: { value: 1000 },
                       uBase: { value: FOREST_BASE }, uSpikeI: { value: FOREST_SPIKE },
                       uFocus: { value: 350 }, uZoom: { value: 1 } };
    // which cell type each sampled neuron is drawn as
    const shapes = {}, cellType = new Int16Array(L.N).fill(-1), cellInst = new Int32Array(L.N), types = [];
    const regAxis = nodes.map(() => randDir(rnd));
    const cellQ = new Float32Array(4 * L.N), cellS = new Float32Array(L.N).fill(1);   // each cell's turn and size (its soma follows)
    for (let r = 0; r < R; r++) {
      const tt = morph && morph.cells ? (FOREST_TYPES[kindOf(nodes[r])] || []).filter(([t]) => morph.cells[t]) : [];
      for (let j = L.start[r]; j < L.start[r + 1]; j++) {
        if (!tt.length) continue;                                   // pallidum (or no shapes): a soma only
        let u = rnd(), t = tt[0][0];
        for (const [name, f] of tt) { if (u < f) { t = name; break; } u -= f; }
        if (!shapes[t]) { shapes[t] = { type: t, shape: simplify(morph.cells[t], FOREST_SEG, FOREST_AXON_UM), cells: [] }; shapes[t].ti = types.length; types.push(shapes[t]); }
        cellType[j] = shapes[t].ti; cellInst[j] = shapes[t].cells.length; shapes[t].cells.push(j);
      }
    }
    for (const T of types) {
      const s = T.shape, n = T.cells.length, g = new THREE.InstancedBufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(s.pos, 3));
      g.setAttribute("aDist", new THREE.BufferAttribute(s.dist, 1));
      g.setAttribute("aKind", new THREE.BufferAttribute(s.kind, 1));
      const off = new Float32Array(n * 3), quat = new Float32Array(n * 4), sc = new Float32Array(n), reg = new Float32Array(n),
            spk = new Float32Array(n).fill(-1e4);
      T.cells.forEach((j, i) => {
        off.set(L.pos.subarray(3 * j, 3 * j + 3), 3 * i); reg[i] = L.reg[j];
        let up;
        if (T.type === "pyramidal" && L.vert[j] >= 0) {
          const v = L.vert[j];
          up = normals ? [normals[3 * v], normals[3 * v + 1], normals[3 * v + 2]]
                       : (q => { const d = [o.cortex[3 * v] - q[0], o.cortex[3 * v + 1] - q[1], o.cortex[3 * v + 2] - q[2]], l = Math.hypot(...d) || 1; return d.map(x => x / l); })(nodes[L.reg[j]].q);
        } else if (T.type === "ca1_pyramidal") up = coneDir(regAxis[L.reg[j]], 30, rnd);
        else up = randDir(rnd);
        quat.set(quatMul(quatFromTo([0, 1, 0], up), yawQ(rnd() * 6.2832)), 4 * i);
        sc[i] = (0.85 + 0.3 * rnd()) * (rnd() < 0.5 ? -1 : 1);       // +-15 % size; half mirrored
        cellQ.set(quat.subarray(4 * i, 4 * i + 4), 4 * j); cellS[j] = Math.abs(sc[i]);
      });
      g.setAttribute("iOff", new THREE.InstancedBufferAttribute(off, 3));
      g.setAttribute("iQuat", new THREE.InstancedBufferAttribute(quat, 4));
      g.setAttribute("iScale", new THREE.InstancedBufferAttribute(sc, 1));
      g.setAttribute("iReg", new THREE.InstancedBufferAttribute(reg, 1));
      const sa = new THREE.InstancedBufferAttribute(spk, 1); if (sa.setUsage) sa.setUsage(THREE.DynamicDrawUsage);
      g.setAttribute("iSpike", sa);
      g.instanceCount = n;
      const hue = FOREST_HUE[T.type] || SOMA_HUE;
      const mat = new THREE.ShaderMaterial({ uniforms: Object.assign({ uHue: { value: new THREE.Vector3(...hue) } }, uniforms),
        transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
        vertexShader: `
          attribute float aDist; attribute float aKind; attribute vec3 iOff; attribute vec4 iQuat; attribute float iScale;
          attribute float iReg; attribute float iSpike;
          uniform float uTime; uniform sampler2D uRates; uniform float uLive; uniform float uUnit; uniform float uSpeed; uniform float uTrail;
          uniform vec3 uHue; uniform float uBase; uniform float uSpikeI; uniform float uFocus; uniform float uZoom;
          ${LIGHT_SHEET}
          varying vec3 vCol;
          void main(){
            vec3 p = position * abs(iScale); p.x *= sign(iScale);
            p += 2.0 * cross(iQuat.xyz, cross(iQuat.xyz, p) + iQuat.w * p);
            vec4 t = texture2D(uRates, vec2((iReg + 0.5) / 256.0, 0.5));
            float rate = uLive * smoothstep(0.42, 0.86, t.r);              // ~2-40 Hz on the log byte scale
            float dt = uTime - iSpike, on = dt >= 0.0 ? 1.0 : 0.0;
            float soma = on * exp(-dt / 0.3) * exp(-aDist / 60.0);
            float front = dt * uSpeed;                      // the axon lights from the soma up to the front, then fades
            float pulse = on * step(aDist, front) * exp(-(front - aDist) / uTrail) * exp(-dt / 0.5);
            vec3 tint = mix(uHue, vec3(0.95, 0.72, 0.55), 0.25 * rate + 0.3 * t.g * uLive);   // rate: a little warmer
            vec3 col = aKind < 1.5 ? uHue * uBase * 0.6 : tint * uBase * (1.0 + 0.5 * rate);     // axon dimmer than dendrites
            col += uHue * uSpikeI * (pulse * (aKind < 1.5 ? 1.0 : 0.0) + soma);       // only a spike brightens
            vec4 mv = modelViewMatrix * vec4(iOff + p * uUnit, 1.0);
            vCol = lightSheet(col, -mv.z, uFocus) * uZoom;
            gl_Position = projectionMatrix * mv;
          }`,
        fragmentShader: `uniform float uFade; varying vec3 vCol; void main(){ gl_FragColor = vec4(vCol * uFade, 1.0); }` });
      const lines = new THREE.LineSegments(g, mat);
      lines.frustumCulled = false; lines.name = "forest-" + T.type;
      group.add(lines);
      Object.assign(T, { spk, sa, geom: g, mat });
    }
    // the somata (#88 follow-up: "no dots"): every cell's body is a small solid at the base of its own tree, turned with
    // it and sized from the reconstruction's soma radius: an ellipsoid for multipolar cells, a pyramid-like teardrop
    // (apex up the apical dendrite) for pyramidal ones; the pallidum's cells, which have no reconstruction here, are
    // the ellipsoid alone. At whole-brain scale a soma is below a pixel; it flashes with its cell's spikes.
    const flash = new Float32Array(L.N).fill(-1e4);
    const sgeo = somaGeometry(THREE), sg = new THREE.InstancedBufferGeometry();
    sg.setAttribute("position", sgeo.position); sg.setAttribute("normal", sgeo.normal);
    const somaR = new Float32Array(L.N), somaHue = new Float32Array(3 * L.N), somaShape = new Float32Array(L.N);
    for (let j = 0; j < L.N; j++) {
      const t = cellType[j] >= 0 ? types[cellType[j]].type : null;
      somaR[j] = (t ? morph.cells[t].soma_r : 8) * cellS[j];
      somaHue.set(t ? FOREST_HUE[t] || SOMA_HUE : SOMA_HUE, 3 * j);
      somaShape[j] = t && /pyramidal/.test(t) ? 1 : 0;
      if (!t) cellQ.set(quatFromTo([0, 1, 0], randDir(rnd)), 4 * j);
    }
    sg.setAttribute("iOff", new THREE.InstancedBufferAttribute(L.pos, 3));
    sg.setAttribute("iQuat", new THREE.InstancedBufferAttribute(cellQ, 4));
    sg.setAttribute("iR", new THREE.InstancedBufferAttribute(somaR, 1));
    sg.setAttribute("iShape", new THREE.InstancedBufferAttribute(somaShape, 1));
    sg.setAttribute("iHue", new THREE.InstancedBufferAttribute(somaHue, 3));
    sg.setAttribute("iReg", new THREE.InstancedBufferAttribute(L.reg, 1));
    const fa = new THREE.InstancedBufferAttribute(flash, 1); if (fa.setUsage) fa.setUsage(THREE.DynamicDrawUsage);
    sg.setAttribute("iSpike", fa);
    sg.instanceCount = L.N;
    const smat = new THREE.ShaderMaterial({ uniforms, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
      vertexShader: `
        attribute vec3 iOff; attribute vec4 iQuat; attribute float iR; attribute float iShape; attribute vec3 iHue;
        attribute float iReg; attribute float iSpike;
        uniform float uTime; uniform sampler2D uRates; uniform float uLive; uniform float uUnit; uniform float uBase; uniform float uSpikeI;
        uniform float uFocus; uniform float uZoom;
        varying vec3 vCol;
        vec3 turn(vec3 v){ return v + 2.0 * cross(iQuat.xyz, cross(iQuat.xyz, v) + iQuat.w * v); }
        ${LIGHT_SHEET}
        void main(){
          vec3 p = position, nn = normal;
          if (iShape > 0.5) { float up = max(p.y, 0.0); p.y *= 1.0 + 0.9 * up; p.xz *= 1.0 - 0.5 * up; }   // a pyramid's soma
          vec4 t = texture2D(uRates, vec2((iReg + 0.5) / 256.0, 0.5));
          float rate = uLive * smoothstep(0.42, 0.86, t.r);
          float dt = uTime - iSpike, f = dt < 0.0 ? 0.0 : exp(-dt / 0.35);
          vec3 n = normalize(normalMatrix * turn(nn));
          float rim = 0.55 + 0.45 * (1.0 - abs(n.z));                 // a solid body: brighter at its rim, like a stained soma
          vec4 mv = modelViewMatrix * vec4(iOff + turn(p * iR) * uUnit, 1.0);
          vCol = lightSheet(iHue * (1.6 * uBase * (1.0 + 0.4 * rate) * rim + 1.3 * uSpikeI * f), -mv.z, uFocus) * uZoom;
          gl_Position = projectionMatrix * mv;
        }`,
      fragmentShader: `uniform float uFade; varying vec3 vCol; void main(){ gl_FragColor = vec4(vCol * uFade, 1.0); }` });
    const somata = new THREE.Mesh(sg, smat);
    somata.name = "forest-somata"; somata.frustumCulled = false;
    group.add(somata);
    o.scene.add(group);
    const segments = types.reduce((a, T) => a + T.shape.n * T.cells.length, 0);

    const S = { on: false, fade: 0, net: null, lastWall: -1e9, gpuWall: -1e9, tint: null, rates: new Float32Array(R),
                race: new Float32Array(R), raceOn: false, groups: null, prevArrive: 0, gap: 200, t0: performance.now(), dirty: false,
                ns: 0, shown: 0, spikes: 0 };
    const clockS = now => (now - S.t0) / 1000;

    function onFrame(m) {
      if (!m || m.type !== "spiking") return;
      if (m.live === false) { S.lastWall = -1e9; return; }
      const n3 = m.n3; if (!n3) return;
      const now = performance.now();
      if (m.net === "cpu") { if (now - S.gpuWall < LIVE_MS) return; } else S.gpuWall = now;
      if (S.net !== m.net) { S.net = m.net; S.rates.fill(0); }
      if (m.groups) S.groups = m.groups;
      const gap = now - S.prevArrive; S.prevArrive = now;
      if (gap > 30 && gap < 2000) S.gap = 0.7 * S.gap + 0.3 * gap;   // wall time between frames: spikes play over it
      S.lastWall = now; S.raceOn = !!n3.race; S.ns = n3.ns || 0;
      // rates: measured per region (rq), else the region's network group rate (say so in the caption)
      let tint = null;
      if (n3.rq) { const q = unb64(n3.rq); if (q.length === R) { tint = "regions"; for (let r = 0; r < R; r++) S.rates[r] = S.rates[r] ? 0.55 * S.rates[r] + 0.45 * q[r] : q[r]; } }
      if (!tint && S.groups) { tint = "groups"; for (let r = 0; r < R; r++) { const hz = S.groups[nodes[r].group]; S.rates[r] = hz == null ? S.rates[r] * 0.9 : rateByte(hz); } }
      S.tint = tint; S.dirty = true;
      // spikes: flash their cells, spread over the time until the next frame as they were spread over the frame
      const b = unb64(n3.sq), play = Math.min(600, S.gap) / 1000, t = clockS(now);
      for (let i = 0; i + 2 < b.length; i += 3) {
        const r = b[i]; if (r >= R) continue;
        const j = L.start[r] + Math.min(L.count[r] - 1, Math.floor(b[i + 1] * L.count[r] / 256)), at = t + (b[i + 2] / 255) * play;
        flash[j] = at; S.spikes++;
        if (cellType[j] >= 0) { const T = types[cellType[j]]; T.spk[cellInst[j]] = at; T.dirty = true; }
      }
      S.shown = b.length / 3;
      if (b.length >= 3) S.pending = true;                            // uploaded on the next drawn frame, if shown
    }

    function update(now) {
      const isLive = now - S.lastWall < LIVE_MS;
      const target = S.on ? 1 : 0;                                    // offline: the cells stand still, never flash
      S.fade += (target - S.fade) * 0.08; if (Math.abs(S.fade - target) < 0.004) S.fade = target;
      group.visible = S.fade > 0 && uniforms.uZoom.value > 0.003;    // faded out by the zoom (#99): not drawn at all
      if (!group.visible) return;
      uniforms.uTime.value = clockS(now); uniforms.uFade.value = S.fade;
      uniforms.uLive.value += ((isLive ? 1 : 0) - uniforms.uLive.value) * 0.05;
      let raceDirty = false;
      for (let r = 0; r < R; r++) { if (!striatum[r]) continue;
        const v = S.race[r] + ((S.raceOn && isLive ? 1 : 0) - S.race[r]) * 0.06; if (Math.abs(v - S.race[r]) > 1e-3) { S.race[r] = v; raceDirty = true; } }
      if (S.dirty || raceDirty) {
        for (let r = 0; r < R; r++) { texData[4 * r] = Math.round(S.rates[r]); texData[4 * r + 1] = Math.round(255 * S.race[r]); }
        tex.needsUpdate = true; S.dirty = false;
      }
      if (S.pending) { fa.needsUpdate = true; for (const T of types) if (T.dirty) { T.sa.needsUpdate = true; T.dirty = false; } S.pending = false; }
    }
    // drawing-buffer height (px) and vertical fov: a soma of r um is drawn ENLARGE x r at its depth
    function resize(h, fov) { uniforms.uScale.value = h / (2 * Math.tan((fov || 32) * Math.PI / 360)); }
    function setVisible(on) { S.on = !!on; }
    // the zoom (#99): focal distance (mm, the camera's distance to what it looks at) and the forest's fade as the
    // view dives into a cortical column
    function setFocus(mm) { uniforms.uFocus.value = Math.max(1e-3, mm); }
    function setZoomFade(f) { uniforms.uZoom.value = Math.max(0, Math.min(1, f)); }
    function state() { return { live: performance.now() - S.lastWall < LIVE_MS, net: S.net, tint: S.tint, race: S.raceOn, recorded: S.ns,
      shown: S.shown, points: L.N, cells: L.N, shaped: types.reduce((a, T) => a + T.cells.length, 0), segments,
      drawCalls: types.length + 1, enlarge: ENLARGE, spikes: S.spikes,
      types: types.map(T => ({ type: T.type, n: T.cells.length, segs: T.shape.n, id: morph.cells[T.type].nmo_id, species: morph.cells[T.type].species })) }; }
    function dispose() { o.scene.remove(group); for (const T of types) { T.geom.dispose(); T.mat.dispose(); } sg.dispose(); smat.dispose(); tex.dispose(); }
    function rate(r) { return S.rates[r] || 0; }                    // smoothed rate byte of region r (0 = none yet)
    // for checks: cell j's type, its turned apical axis (+y) and where its soma is
    function cell(j) { const t = cellType[j]; if (t < 0) return { type: null, pos: [...L.pos.subarray(3 * j, 3 * j + 3)], vert: L.vert[j] };
      const T = types[t], i = cellInst[j], q = T.geom.getAttribute("iQuat").array.slice(4 * i, 4 * i + 4), v = [0, 1, 0];
      const c = [q[1] * v[2] - q[2] * v[1] + q[3] * v[0], q[2] * v[0] - q[0] * v[2] + q[3] * v[1], q[0] * v[1] - q[1] * v[0] + q[3] * v[2]];
      const up = [v[0] + 2 * (q[1] * c[2] - q[2] * c[1]), v[1] + 2 * (q[2] * c[0] - q[0] * c[2]), v[2] + 2 * (q[0] * c[1] - q[1] * c[0])];
      return { type: T.type, up, pos: [...L.pos.subarray(3 * j, 3 * j + 3)], vert: L.vert[j], normal: normals && L.vert[j] >= 0 ? [...normals.subarray(3 * L.vert[j], 3 * L.vert[j] + 3)] : null,
               spike: T.spk[i] }; }
    return { object: group, onFrame, update, resize, setVisible, setFocus, setZoomFade, state, dispose, rate, cell, points: L.N,
             cells: L.N, normals, vert: L.vert, pos: L.pos, start: L.start };
  }

  // ---------- the cortical column (#99): the zoom from the whole brain down to tissue ----------
  // A 0.5 mm-wide column of cortex under one point of the real cortex mesh, at TRUE size, its local +y along the
  // outward surface normal (pia at y = 0, white matter below). Layers L1-L6: thicknesses measured from the H01 layer
  // annotation (Shapson-Coe et al. 2024, human temporal cortex, CC BY 4.0; tests/../analysis/h01_layers.py: median
  // boundary-to-boundary distance in 3 sections of the 8 um segmentation). Neurons: H01's ~16 000 per mm3 (the
  // paper's count over its sample), L1 assumed 10 % of that (it is cell-sparse). Like a Golgi stain, only a few
  // percent are drawn ("sparse label"), each a real NeuroMorpho.Org reconstruction of its layer's type: human L2/3
  // pyramids in L2-L4 and L6, the human L5 pyramid (NMO_159993, apical tuft ~1.5 mm) in L5, human basket cells as the
  // interneurons. Every drawn cell stands for a sampled model neuron of the column's region (its spikes, its rate).
  const H01_LAYERS_UM = [["L1", 413], ["L2", 303], ["L3", 447], ["L4", 272], ["L5", 449], ["L6", 261]];
  const H01_NEURONS_MM3 = 16000, L1_REL_DENSITY = 0.1, COL_W_UM = 500, COL_LABEL = 0.03, COL_SEG = 90, COL_AXON_UM = 600;
  const COL_TYPES = { L1: [["basket", 1]], L2: [["pyramidal", 0.8], ["basket", 0.2]], L3: [["pyramidal", 0.8], ["basket", 0.2]],
                      L4: [["pyramidal", 0.7], ["basket", 0.3]], L5: [["l5_pyramidal", 0.8], ["basket", 0.2]],
                      L6: [["pyramidal", 0.8], ["basket", 0.2]] };
  const COL_HUE = Object.assign({ l5_pyramidal: [0.6, 0.8, 0.68] }, FOREST_HUE);
  function columnPlan(morph, label) {
    label = label || COL_LABEL;
    let top = 0, neurons = 0, drawn = 0;
    const area = (COL_W_UM / 1000) ** 2;
    const layers = H01_LAYERS_UM.map(([name, um]) => {
      const n = Math.round(H01_NEURONS_MM3 * (name === "L1" ? L1_REL_DENSITY : 1) * area * um / 1000);
      const types = COL_TYPES[name].filter(([t]) => morph && morph.cells && morph.cells[t]);
      const d = Math.max(name === "L1" ? 1 : 3, Math.round(n * label));
      const L = { name, top, bottom: top + um, neurons: n, drawn: types.length ? d : 0, types };
      top += um; neurons += n; drawn += L.drawn;
      return L;
    });
    return { layers, thickness: top, neurons, drawn, widthUm: COL_W_UM, label };
  }
  function column(o) {
    const THREE = o.THREE, morph = o.morph, plan = columnPlan(morph, o.label);
    const rnd = mulberry(990 + (o.region || 0)), group = new THREE.Group(); group.name = "column";
    // local frame: +y = outward normal, origin at the pia point, 1 unit = 1 um
    const n = new THREE.Vector3(...o.normal).normalize();
    group.position.set(...o.pos);
    group.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), n);
    group.scale.setScalar(0.001);
    group.updateMatrixWorld(true);                                   // at() / anchors() are asked before the first render
    const uniforms = { uTime: { value: 0 }, uFade: { value: 0 }, uLive: { value: 0 }, uRate: { value: 0 },
                       uBase: { value: FOREST_BASE }, uSpikeI: { value: FOREST_SPIKE }, uFocus: { value: 5 },
                       uSpeed: { value: FOREST_SPEED }, uTrail: { value: FOREST_TRAIL }, uScale: { value: 1000 } };
    const shapes = {}, cells = [];
    for (const L of plan.layers) {
      for (let i = 0; i < L.drawn; i++) {
        let u = rnd(), t = L.types[0][0];
        for (const [name, f] of L.types) { if (u < f) { t = name; break; } u -= f; }
        if (!shapes[t]) shapes[t] = { type: t, shape: simplify(morph.cells[t], COL_SEG, COL_AXON_UM), list: [] };
        const depth = L.top + (0.08 + 0.84 * rnd()) * (L.bottom - L.top);
        const c = morph.cells[t], reach = Math.max(1, c.box[4]);          // apical / upward reach (um)
        let sc = 0.88 + 0.24 * rnd();
        // a deep pyramid's tuft ends in L1, as real tufts do: scale (0.8-1.15) so its top lands 40-300 um below the pia
        if (t === "l5_pyramidal") sc = Math.max(0.8, Math.min(1.15, (depth - (40 + 260 * rnd())) / reach));
        // nothing pokes out of the brain: shallow cells whose tree would cross the pia sit a little deeper
        const y = -Math.max(depth, reach * sc + 15);
        const x = (rnd() - 0.5) * COL_W_UM, z = (rnd() - 0.5) * COL_W_UM;
        const lean = 8 * Math.PI / 180, a = rnd() * 6.2832;
        let q = quatMul(quatFromTo([0, 1, 0], [Math.sin(lean * (rnd() - 0.5) * 2), 1, Math.sin(lean * (rnd() - 0.5) * 2)].map((v, k, arr) => v / Math.hypot(...arr))), yawQ(a));
        if (t === "basket") q = quatFromTo([0, 1, 0], randDir(rnd));         // interneurons: any orientation
        shapes[t].list.push({ x, y, z, q, sc: sc * (rnd() < 0.5 ? -1 : 1), layer: L.name });
        cells.push({ t, i: shapes[t].list.length - 1, layer: L.name, depth: -y });
      }
    }
    const types = [];
    for (const T of Object.values(shapes)) {
      const s = T.shape, m = T.list.length, g = new THREE.InstancedBufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(s.pos, 3));
      g.setAttribute("aDist", new THREE.BufferAttribute(s.dist, 1));
      g.setAttribute("aKind", new THREE.BufferAttribute(s.kind, 1));
      const off = new Float32Array(3 * m), quat = new Float32Array(4 * m), sc = new Float32Array(m), spk = new Float32Array(m).fill(-1e4);
      T.list.forEach((c, i) => { off.set([c.x, c.y, c.z], 3 * i); quat.set(c.q, 4 * i); sc[i] = c.sc; });
      g.setAttribute("iOff", new THREE.InstancedBufferAttribute(off, 3));
      g.setAttribute("iQuat", new THREE.InstancedBufferAttribute(quat, 4));
      g.setAttribute("iScale", new THREE.InstancedBufferAttribute(sc, 1));
      const sa = new THREE.InstancedBufferAttribute(spk, 1); if (sa.setUsage) sa.setUsage(THREE.DynamicDrawUsage);
      g.setAttribute("iSpike", sa);
      g.instanceCount = m;
      const hue = COL_HUE[T.type] || SOMA_HUE;
      const mat = new THREE.ShaderMaterial({ uniforms: Object.assign({ uHue: { value: new THREE.Vector3(...hue) } }, uniforms),
        transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
        vertexShader: `
          attribute float aDist; attribute float aKind; attribute vec3 iOff; attribute vec4 iQuat; attribute float iScale; attribute float iSpike;
          uniform float uTime; uniform float uLive; uniform float uRate; uniform float uBase; uniform float uSpikeI; uniform float uFocus;
          uniform float uSpeed; uniform float uTrail; uniform vec3 uHue;
          varying vec3 vCol;
          ${LIGHT_SHEET}
          void main(){
            vec3 p = position * abs(iScale); p.x *= sign(iScale);
            p += 2.0 * cross(iQuat.xyz, cross(iQuat.xyz, p) + iQuat.w * p);
            float rate = uLive * uRate;
            float dt = uTime - iSpike, on = dt >= 0.0 ? 1.0 : 0.0;
            float soma = on * exp(-dt / 0.3) * exp(-aDist / 60.0);
            float front = dt * uSpeed;
            float pulse = on * step(aDist, front) * exp(-(front - aDist) / uTrail) * exp(-dt / 0.5);   // lit soma -> front
            vec3 tint = mix(uHue, vec3(0.95, 0.72, 0.55), 0.25 * rate);
            vec3 col = aKind < 1.5 ? uHue * uBase * 0.6 : tint * uBase * (1.0 + 0.5 * rate);
            col += uHue * uSpikeI * (pulse * (aKind < 1.5 ? 1.0 : 0.0) + soma);
            vec4 mv = modelViewMatrix * vec4(iOff + p, 1.0);
            vCol = lightSheet(col, -mv.z, uFocus);
            gl_Position = projectionMatrix * mv;
          }`,
        fragmentShader: `uniform float uFade; varying vec3 vCol; void main(){ gl_FragColor = vec4(vCol * uFade, 1.0); }` });
      const lines = new THREE.LineSegments(g, mat); lines.frustumCulled = false; lines.name = "column-" + T.type;
      group.add(lines);
      types.push(Object.assign(T, { spk, sa, geom: g, mat }));
    }
    // somata: a solid body each (as the forest's, #88 follow-up: no dots), turned with its cell, at its real size
    const N = cells.length, sgeo = somaGeometry(THREE), sg = new THREE.InstancedBufferGeometry();
    sg.setAttribute("position", sgeo.position); sg.setAttribute("normal", sgeo.normal);
    const so = new Float32Array(3 * N), sq = new Float32Array(4 * N), sr = new Float32Array(N), ss = new Float32Array(N), sh = new Float32Array(3 * N),
          sf = new Float32Array(N).fill(-1e4);
    cells.forEach((c, k) => { const L = shapes[c.t].list[c.i]; so.set([L.x, L.y, L.z], 3 * k); sq.set(L.q, 4 * k);
      sr[k] = morph.cells[c.t].soma_r * Math.abs(L.sc); ss[k] = /pyramidal/.test(c.t) ? 1 : 0; sh.set(COL_HUE[c.t] || SOMA_HUE, 3 * k); });
    sg.setAttribute("iOff", new THREE.InstancedBufferAttribute(so, 3)); sg.setAttribute("iQuat", new THREE.InstancedBufferAttribute(sq, 4));
    sg.setAttribute("iR", new THREE.InstancedBufferAttribute(sr, 1)); sg.setAttribute("iShape", new THREE.InstancedBufferAttribute(ss, 1));
    sg.setAttribute("iHue", new THREE.InstancedBufferAttribute(sh, 3));
    const sfa = new THREE.InstancedBufferAttribute(sf, 1); if (sfa.setUsage) sfa.setUsage(THREE.DynamicDrawUsage);
    sg.setAttribute("iSpike", sfa); sg.instanceCount = N;
    const smat = new THREE.ShaderMaterial({ uniforms, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
      vertexShader: `
        attribute vec3 iOff; attribute vec4 iQuat; attribute float iR; attribute float iShape; attribute vec3 iHue; attribute float iSpike;
        uniform float uTime; uniform float uLive; uniform float uRate; uniform float uBase; uniform float uSpikeI; uniform float uFocus;
        varying vec3 vCol;
        vec3 turn(vec3 v){ return v + 2.0 * cross(iQuat.xyz, cross(iQuat.xyz, v) + iQuat.w * v); }
        ${LIGHT_SHEET}
        void main(){
          vec3 p = position, nn = normal;
          if (iShape > 0.5) { float up = max(p.y, 0.0); p.y *= 1.0 + 0.9 * up; p.xz *= 1.0 - 0.5 * up; }
          float dt = uTime - iSpike, f = dt < 0.0 ? 0.0 : exp(-dt / 0.35);
          vec3 n = normalize(normalMatrix * turn(nn));
          float rim = 0.55 + 0.45 * (1.0 - abs(n.z));
          vec4 mv = modelViewMatrix * vec4(iOff + turn(p * iR), 1.0);
          vCol = lightSheet(iHue * (1.6 * uBase * (1.0 + 0.4 * uLive * uRate) * rim + 1.3 * uSpikeI * f), -mv.z, uFocus);
          gl_Position = projectionMatrix * mv;
        }`,
      fragmentShader: `uniform float uFade; varying vec3 vCol; void main(){ gl_FragColor = vec4(vCol * uFade, 1.0); }` });
    const somata = new THREE.Mesh(sg, smat); somata.frustumCulled = false; somata.name = "column-somata";
    group.add(somata);
    // the layer boundaries: a faint square outline of the column at the pia, at each boundary, and at the white matter
    const W = COL_W_UM / 2, edges = [];
    const ring = y => [[-W, y, -W], [W, y, -W], [W, y, -W], [W, y, W], [W, y, W], [-W, y, W], [-W, y, W], [-W, y, -W]];
    edges.push(...ring(0));
    for (const L of plan.layers) edges.push(...ring(-L.bottom));
    for (const [x, z] of [[-W, -W], [W, -W], [W, W], [-W, W]]) edges.push([x, 0, z], [x, -plan.thickness, z]);   // the column's corners
    const block = o.block;                                            // NeuronRender's tissue block, outlined where it sits
    if (block && block.um && block.depthUm) {
      // its depth band, within the column's width (H01's block is wider than this 0.5 mm column)
      const bw = Math.min(block.um[0], COL_W_UM), bd = Math.min(block.um[2], COL_W_UM), y0 = -block.depthUm[0], y1 = -block.depthUm[1], bx = bw / 2, bz = bd / 2;
      for (const y of [y0, y1]) edges.push([-bx, y, -bz], [bx, y, -bz], [bx, y, -bz], [bx, y, bz], [bx, y, bz], [-bx, y, bz], [-bx, y, bz], [-bx, y, -bz]);
      for (const [x, z] of [[-bx, -bz], [bx, -bz], [bx, bz], [-bx, bz]]) edges.push([x, y0, z], [x, y1, z]);
    }
    const eg = new THREE.BufferGeometry(); eg.setAttribute("position", new THREE.BufferAttribute(new Float32Array(edges.flat()), 3));
    const emat = new THREE.ShaderMaterial({ uniforms, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
      vertexShader: `uniform float uFocus; varying vec3 vCol; ${LIGHT_SHEET}
        void main(){ vec4 mv = modelViewMatrix * vec4(position, 1.0); vCol = lightSheet(vec3(0.07, 0.085, 0.09), -mv.z, uFocus);
          gl_Position = projectionMatrix * mv; }`,
      fragmentShader: `uniform float uFade; varying vec3 vCol; void main(){ gl_FragColor = vec4(vCol * uFade, 1.0); }` });
    const outline = new THREE.LineSegments(eg, emat); outline.frustumCulled = false; outline.name = "column-layers";
    group.add(outline);
    o.scene.add(group);

    const segments = types.reduce((a, T) => a + T.shape.n * T.list.length, 0);
    const S = { t0: performance.now(), lastWall: -1e9, gap: 200, prev: 0, rate: 0, spikes: 0, fade: 0, target: 0 };
    const clock = now => (now - S.t0) / 1000;
    function onFrame(m) {                                            // only the column's region's spikes and rate
      if (!m || m.type !== "spiking" || !m.n3 || m.live === false) return;
      const now = performance.now(), gap = now - S.prev; S.prev = now;
      if (gap > 30 && gap < 2000) S.gap = 0.7 * S.gap + 0.3 * gap;
      S.lastWall = now;
      if (m.n3.rq) { const q = unb64(m.n3.rq); if (q.length > o.region) S.rate = q[o.region]; }
      const b = unb64(m.n3.sq), play = Math.min(600, S.gap) / 1000, t = clock(now), dirty = new Set();
      for (let i = 0; i + 2 < b.length; i += 3) {
        if (b[i] !== o.region || !cells.length) continue;
        const k = Math.min(cells.length - 1, Math.floor(b[i + 1] * cells.length / 256)), c = cells[k], T = shapes[c.t], at = t + (b[i + 2] / 255) * play;
        T.spk[c.i] = at; sf[k] = at; dirty.add(T); S.spikes++;
      }
      for (const T of dirty) T.sa.needsUpdate = true;
      if (dirty.size) sfa.needsUpdate = true;
    }
    function update(now, focusMm, scalePx) {
      const live = now - S.lastWall < LIVE_MS;
      uniforms.uTime.value = clock(now); uniforms.uLive.value = live ? 1 : 0;
      const r = S.rate ? Math.max(0, Math.min(1, (S.rate / 255 - 0.42) / 0.44)) : 0;
      uniforms.uRate.value += (r - uniforms.uRate.value) * 0.05;
      if (focusMm) uniforms.uFocus.value = focusMm;
      if (scalePx) uniforms.uScale.value = scalePx;
      S.fade += (S.target - S.fade) * 0.15; if (Math.abs(S.fade - S.target) < 0.003) S.fade = S.target;
      uniforms.uFade.value = S.fade; group.visible = S.fade > 0.003;
    }
    function setOpacity(f) { S.target = Math.max(0, Math.min(1, f)); }
    // world positions (mm) for the page's labels: each layer's middle, on one vertical edge of the column
    function anchors() {
      const out = [], v = new THREE.Vector3();
      for (const L of plan.layers) { v.set(-W * 1.08, -(L.top + L.bottom) / 2, -W); group.localToWorld(v); out.push({ name: L.name, pos: v.toArray() }); }
      v.set(-W * 1.08, -plan.thickness - 60, -W); group.localToWorld(v); out.push({ name: "white matter", pos: v.toArray() });
      return out;
    }
    // the world point (mm) at a depth below the pia, on the column's axis
    function at(depthUm) { const v = new THREE.Vector3(0, -depthUm, 0); group.localToWorld(v); return v.toArray(); }
    function info() {
      const byType = {};
      for (const c of cells) byType[c.t] = (byType[c.t] || 0) + 1;
      return { region: o.region, widthUm: COL_W_UM, thicknessUm: plan.thickness, neurons: plan.neurons, drawn: cells.length,
        label: plan.label, segments, drawCalls: types.length + 2, layers: plan.layers.map(L => ({ name: L.name, top: L.top, bottom: L.bottom, neurons: L.neurons, drawn: L.drawn })),
        types: Object.entries(byType).map(([t, k]) => ({ type: t, n: k, id: morph.cells[t].nmo_id, species: morph.cells[t].species })),
        live: performance.now() - S.lastWall < LIVE_MS, spikes: S.spikes,
        spiking: types.reduce((a, T) => a + T.spk.filter(x => x > -1e3).length, 0) };
    }
    function dispose() { o.scene.remove(group); for (const T of types) { T.geom.dispose(); T.mat.dispose(); } sg.dispose(); smat.dispose(); eg.dispose(); emat.dispose(); }
    return { group, onFrame, update, setOpacity, anchors, at, info, dispose, plan, cells };
  }

  // ---------- close-up: real neuron shapes (#78) ----------
  // A block of tissue with 100-300 reconstructed neurons (web/neurons_morph.json: NeuroMorpho.Org, CC BY 4.0,
  // simplified), drawn as instanced line segments: one draw call per cell type, <= SEG_BUDGET segments in all. Each
  // drawn cell stands for a sampled model neuron of the region: when that neuron's spike arrives (n3.sq), its soma
  // flashes and a pulse runs from the soma along its axon at PULSE_UM_S (visibly slowed); its dendrites glow with the
  // region's rate. Only regions the network simulates get a close-up (no cerebellum: it is not one of the 214).
  // Illustrative shapes: the simulated network uses point neurons.
  const SEG_BUDGET = 60000, MAX_CELLS = 300, SOMA_SEGS = 3;
  const TILT = 2 * 10 * Math.PI / 180, SCALE_JITTER = 0.15;       // per cell: lean +-10 degrees, size +-15 %
  const PULSE_UM_S = 1000, PULSE_W_UM = 70;                        // 1 mm/s on screen vs ~0.5 m/s in thin axons
  const SLOWDOWN = Math.round(0.5e6 / PULSE_UM_S);                 // ~500x slower than a thin unmyelinated axon
  const KINDS = {                                                  // close-up kind -> cell types, shares, cells drawn
    cortex: { types: [["pyramidal", 0.8], ["basket", 0.2]], cells: 120 },
    striatum: { types: [["medium_spiny", 1]], cells: 220 },
    thalamus: { types: [["relay", 1]], cells: 160 },
    hippocampus: { types: [["ca1_pyramidal", 1]], cells: 150 },
    amygdala: { types: [["amygdala_principal", 1]], cells: 150 },
  };
  // which close-up a region gets (by its brain.json group / name); null: none
  function kindOf(node) {
    if (!node) return null;
    const nm = node.name || "";
    if (/^(LH|RH)_/.test(nm)) return "cortex";
    if (/Caudate|Putamen|Accumbens/.test(nm)) return "striatum";
    if (/Thalamus/.test(nm)) return "thalamus";
    if (/Hippocampus/.test(nm)) return "hippocampus";
    if (/Amygdala/.test(nm)) return "amygdala";
    return null;
  }
  // how many cells of each type fit: <= MAX_CELLS cells and <= budget segments (soma marks included)
  function closeupPlan(kind, morph, budget) {
    const k = KINDS[kind]; if (!k || !morph || !morph.cells) return null;
    budget = Math.min(budget || SEG_BUDGET, SEG_BUDGET);
    const per = k.types.reduce((a, [t, f]) => a + f * ((morph.cells[t] ? morph.cells[t].n_seg : 0) + SOMA_SEGS), 0);
    const n = Math.max(0, Math.min(MAX_CELLS, k.cells, Math.floor(budget / Math.max(1, per))));
    const plan = k.types.filter(([t]) => morph.cells[t]).map(([t, f]) => ({ type: t, n: Math.round(n * f) }));
    let segs = plan.reduce((a, p) => a + p.n * (morph.cells[p.type].n_seg + SOMA_SEGS), 0);
    while (segs > budget) { const p = plan[0]; p.n--; segs -= morph.cells[p.type].n_seg + SOMA_SEGS; }   // rounding
    return { kind, cells: plan.reduce((a, p) => a + p.n, 0), segments: segs, drawCalls: plan.length, plan };
  }
  // soma position of cell i of n in the block (micrometres; y up, pia at the top for cortex). x is stratified: cell i
  // lies anywhere in the i-th of n slices, so the block is evenly covered without clumps (which additive blending
  // shows as bright columns) and without a visible grid.
  function placeCell(kind, type, i, n, rnd) {
    const sx = ((i + rnd()) / n - 0.5);
    if (kind === "hippocampus")                                    // CA1: somata packed in stratum pyramidale
      return [sx * 2000, (rnd() - 0.5) * 120, (rnd() - 0.5) * 600];
    if (kind === "cortex") {                                       // L2/3 pyramids under the pia, basket cells around
      const y = type === "pyramidal" ? -150 - 650 * rnd() : -100 - 900 * rnd();
      return [sx * 2200, y, (rnd() - 0.5) * 700];
    }
    const s = kind === "striatum" ? 520 : 760;                      // a cube of nucleus
    return [sx * s, (rnd() - 0.5) * s, (rnd() - 0.5) * s];
  }
  function closeup(o) {
    const THREE = o.THREE, morph = o.morph, kind = o.kind, plan = closeupPlan(kind, morph, o.budget);
    if (!plan || !plan.cells) return null;
    const group = new THREE.Group(), rnd = mulberry(780 + Object.keys(KINDS).indexOf(kind));
    const UM = o.unit || 0.12;                                      // scene units per micrometre
    const uniforms = { uTime: { value: 0 }, uRate: { value: 0 }, uFade: { value: 0 }, uLive: { value: 0 },
                       uSpeed: { value: PULSE_UM_S }, uWidth: { value: PULSE_W_UM }, uUnit: { value: UM } };
    const cells = [], types = [];                                   // cells[k] -> {t: types index, j: instance}
    for (const p of plan.plan) {
      const c = morph.cells[p.type], ns = c.n_seg + SOMA_SEGS, pos = new Float32Array(ns * 6), dist = new Float32Array(ns * 2),
            kd = new Float32Array(ns * 2), r = Math.max(4, c.soma_r);
      pos.set(c.pos.slice(0, c.n_seg * 6));
      for (let i = 0; i < c.n_seg; i++) { dist[2 * i] = c.dist[2 * i]; dist[2 * i + 1] = c.dist[2 * i + 1]; kd[2 * i] = kd[2 * i + 1] = c.kind[i]; }
      for (let a = 0; a < SOMA_SEGS; a++) {                          // the soma: three crossed strokes of its diameter
        const i = c.n_seg + a, o6 = 6 * i, ax = [0, 0, 0]; ax[a] = r;
        pos.set([-ax[0], -ax[1], -ax[2], ax[0], ax[1], ax[2]], o6);
        dist[2 * i] = dist[2 * i + 1] = 0; kd[2 * i] = kd[2 * i + 1] = 0;
      }
      const g = new THREE.InstancedBufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      g.setAttribute("aDist", new THREE.BufferAttribute(dist, 1));
      g.setAttribute("aKind", new THREE.BufferAttribute(kd, 1));
      const off = new Float32Array(p.n * 3), rot = new Float32Array(p.n * 2), tilt = new Float32Array(p.n * 2),
            sc = new Float32Array(p.n), spk = new Float32Array(p.n).fill(-1e4);
      for (let j = 0; j < p.n; j++) {
        off.set(placeCell(kind, p.type, j, p.n, rnd).map(v => v * UM), 3 * j);
        const a = rnd() * 6.2832;
        rot[2 * j] = Math.cos(a); rot[2 * j + 1] = Math.sin(a);       // any turn about the cell's main (vertical) axis
        tilt[2 * j] = (rnd() - 0.5) * TILT; tilt[2 * j + 1] = (rnd() - 0.5) * TILT;   // leaning up to +-10 degrees
        sc[j] = (1 - SCALE_JITTER + 2 * SCALE_JITTER * rnd()) * (rnd() < 0.5 ? -1 : 1);   // +-15 %; half mirrored (x)
        cells.push({ t: types.length, j });
      }
      g.setAttribute("iOff", new THREE.InstancedBufferAttribute(off, 3));
      g.setAttribute("iRot", new THREE.InstancedBufferAttribute(rot, 2));
      g.setAttribute("iTilt", new THREE.InstancedBufferAttribute(tilt, 2));
      g.setAttribute("iScale", new THREE.InstancedBufferAttribute(sc, 1));
      const sa = new THREE.InstancedBufferAttribute(spk, 1); if (sa.setUsage) sa.setUsage(THREE.DynamicDrawUsage);
      g.setAttribute("iSpike", sa);
      g.instanceCount = p.n;
      const mat = new THREE.ShaderMaterial({ uniforms, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
        vertexShader: `
          attribute float aDist; attribute float aKind; attribute vec3 iOff; attribute vec2 iRot; attribute vec2 iTilt;
          attribute float iScale; attribute float iSpike;
          uniform float uTime; uniform float uRate; uniform float uLive; uniform float uSpeed; uniform float uWidth; uniform float uUnit;
          varying vec3 vCol;
          void main(){
            vec3 p = position * abs(iScale);
            p.x *= sign(iScale);                                          // a mirrored copy: x only, never upside down
            float cx = cos(iTilt.x), sx = sin(iTilt.x), cz = cos(iTilt.y), sz = sin(iTilt.y);
            p = vec3(p.x, cx * p.y - sx * p.z, sx * p.y + cx * p.z);      // lean about x...
            p = vec3(cz * p.x - sz * p.y, sz * p.x + cz * p.y, p.z);      // ...and about z
            p = vec3(iRot.x * p.x + iRot.y * p.z, p.y, -iRot.y * p.x + iRot.x * p.z);
            vec3 w = p * uUnit + iOff;
            float dt = uTime - iSpike;
            float on = dt >= 0.0 ? 1.0 : 0.0;
            float soma = on * exp(-dt / 0.25);
            float front = dt * uSpeed;
            float pulse = on * exp(-pow((aDist - front) / uWidth, 2.0)) * step(front, aDist + 3.0 * uWidth);
            vec3 col;
            if (aKind < 0.5) col = vec3(0.9, 0.85, 0.75) * (0.45 + 2.6 * soma);                       // soma
            else if (aKind < 1.5) col = vec3(0.55, 0.32, 0.12) * 0.22 + vec3(1.0, 0.9, 0.6) * 4.0 * pulse; // axon
            else {                                                                                   // dendrites
              float glow = uLive * uRate;
              col = mix(vec3(0.22, 0.32, 0.6), vec3(1.0, 0.5, 0.18), glow) * (0.9 + 0.9 * glow)
                    + vec3(1.0, 0.8, 0.5) * 0.9 * soma * exp(-aDist / 40.0);
            }
            vCol = col;
            gl_Position = projectionMatrix * modelViewMatrix * vec4(w, 1.0);
          }`,
        fragmentShader: `uniform float uFade; varying vec3 vCol; void main(){ gl_FragColor = vec4(vCol * 0.42 * uFade, 1.0); }` });
      const lines = new THREE.LineSegments(g, mat);
      lines.frustumCulled = false; lines.name = "closeup-" + p.type;
      group.add(lines);
      types.push({ type: p.type, n: p.n, spk, sa, geom: g, mat });
    }
    // block extent for framing (scene units)
    const box = { min: [1e9, 1e9, 1e9], max: [-1e9, -1e9, -1e9] };
    for (const T of types) { const off = T.geom.getAttribute("iOff").array, c = morph.cells[T.type];
      for (let j = 0; j < T.n; j++) for (let a = 0; a < 3; a++) {
        box.min[a] = Math.min(box.min[a], off[3 * j + a] + c.box[a] * UM); box.max[a] = Math.max(box.max[a], off[3 * j + a] + c.box[3 + a] * UM); } }
    const S = { t0: performance.now(), lastWall: -1e9, gap: 200, prev: 0, rate: 0, region: o.region, fade: 0, on: true, spikes: 0 };
    const clock = now => (now - S.t0) / 1000;
    function onFrame(m) {                                           // a spiking frame: only the close-up region's spikes
      if (!m || m.type !== "spiking" || !m.n3 || m.live === false) return;
      const now = performance.now(), gap = now - S.prev; S.prev = now;
      if (gap > 30 && gap < 2000) S.gap = 0.7 * S.gap + 0.3 * gap;
      S.lastWall = now;
      if (m.n3.rq) { const q = unb64(m.n3.rq); if (q.length > S.region) S.rate = q[S.region]; }
      else if (o.groupRate) S.rate = rateByte(o.groupRate(m)) || S.rate;
      const b = unb64(m.n3.sq), play = Math.min(600, S.gap) / 1000, t = clock(now), dirty = new Set();
      for (let i = 0; i + 2 < b.length; i += 3) {
        if (b[i] !== S.region) continue;
        const c = cells[Math.min(cells.length - 1, Math.floor(b[i + 1] * cells.length / 256))], T = types[c.t];
        T.spk[c.j] = t + (b[i + 2] / 255) * play; dirty.add(T); S.spikes++;
      }
      for (const T of dirty) T.sa.needsUpdate = true;
    }
    function update(now) {
      const live = now - S.lastWall < LIVE_MS;
      uniforms.uTime.value = clock(now); uniforms.uLive.value = live ? 1 : 0;
      const r = S.rate ? Math.max(0, Math.min(1, (S.rate / 255 - 0.42) / 0.44)) : 0;
      uniforms.uRate.value += (r - uniforms.uRate.value) * 0.05;
      S.fade += ((S.on ? 1 : 0) - S.fade) * 0.1; uniforms.uFade.value = S.fade;
    }
    function dispose() { for (const T of types) { T.geom.dispose(); T.mat.dispose(); } }
    function info() { return { kind, region: S.region, cells: plan.cells, segments: plan.segments,
      drawCalls: plan.drawCalls, types: plan.plan.map(p => ({ type: p.type, n: p.n, species: morph.cells[p.type].species,
      id: morph.cells[p.type].nmo_id })), live: performance.now() - S.lastWall < LIVE_MS, spikes: S.spikes,
      spiking: types.reduce((a, T) => a + T.spk.filter(x => x > -1e3).length, 0) }; }
    return { group, onFrame, update, dispose, info, box, plan };
  }

  // level of detail: "brain" (points) or "closeup" (shapes), from the camera distance. Zooming in close on the brain
  // (dist < brainIn) opens a close-up; zooming out of one (dist > its fit distance x OUT) returns to the whole brain.
  const LOD_IN = 95, LOD_OUT = 2.6;
  function lod(mode, dist, fit) {
    if (mode === "closeup") return dist > (fit || 1) * LOD_OUT ? "brain" : "closeup";
    return dist < LOD_IN ? "closeup" : "brain";
  }

  // the caption's spike clause (plain text) for state() -> {recorded, shown}. A frame can arrive with its rates but no
  // spikes when the server's per-viewer budget (3 KB/s, spiking/frames.py) was used up: say so, never "0 of N".
  function spikeLine(st) {
    const rec = st && st.recorded > 0 ? Math.round(st.recorded) : 0, shown = st && st.shown > 0 ? Math.round(st.shown) : 0;
    if (!rec) return "";
    const n = rec.toLocaleString("en-US");
    return shown ? `showing ${shown.toLocaleString("en-US")} of ${n} recorded spikes in the last frame`
                 : `last frame: ${n} spikes recorded, none sent (the stream's 3 KB/s budget was used up)`;
  }

  root.Neurons3D = { create, simplify, cortexNormals, column, columnPlan, H01_LAYERS_UM, H01_NEURONS_MM3, COL_W_UM, COL_LABEL, FOREST_SEG, ENLARGE, FOREST_SLOWDOWN, unb64, rateByte, spikeLine, closeup, closeupPlan, kindOf, lod, SEG_BUDGET, SLOWDOWN, PULSE_UM_S,
                     LOD_IN, LOD_OUT };
})(typeof window !== "undefined" ? window : globalThis);
