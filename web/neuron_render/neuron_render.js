/* NeuronRender: one region's neurons at microscopy scale (#88, part A). API: docs/spiking/neuron_render_api.md.

   Shapes are real reconstructed neurons (public databases); thickness, spines and myelin are drawn from published
   typical values. The simulated network uses point neurons (no dendrites are simulated); cells are enlarged and
   pulses slowed to be visible. A model, not a mind.

   What it draws (web/neuron_render/cells.json, built by analysis/build_neuron_render.py from the same six
   NeuroMorpho.Org cells as #78, CC BY 4.0, now as branched polylines with their SWC radii):
     - tapered tubes along every dendrite and axon path (ring per node; a minimum on-screen width of ~1 px stands in
       for the microscope's point-spread function, so thin processes do not sparkle);
     - a soma as a deformed sphere (hillocks toward each primary process, a cone toward the apical dendrite) with a
       translucent nucleus and nucleolus;
     - dendritic spines (stem + head) at the type's published density, nearest the soma first, within a triangle budget;
     - on myelinated types, myelin internodes (g-ratio ~0.7) and nodes of Ranvier along the axon beyond the initial
       segment; en passant and terminal boutons on the unmyelinated axon;
     - a tissue background: out-of-focus neurite streaks and counterstain-like somata (sprites), cells of the far tier
       as thin lines;
     - bloom and a mild depth of field (depth is carried in the alpha channel of the scene target), two styles.
   Activity, never faked: a recorded spike of a sampled model neuron flashes its cell's soma and sends an action
   potential down the axon at the real conduction speed / SLOWDOWN (hopping node to node where myelinated); boutons
   glow on arrival; dendrites glow with the region's measured rate. No frames -> nothing moves (caption: offline; no demo mode).
   Works with the page's THREE (r128 global on /brain, r169 in the room); nothing newer than r128 is used. */
(function (root) {
  "use strict";
  const ASSET = "neuron_render/cells.json", LIVE_MS = 10000;
  const SLOWDOWN = 10000;                                        // pulses: real conduction speed / SLOWDOWN
  const CAPTION = "Shapes are real reconstructed neurons from public datasets (H01 human cortex electron microscopy, " +
    "Shapson-Coe et al. 2024; NeuroMorpho.Org), CC BY 4.0. The activity is simulated by a point-neuron network and " +
    "slowed down to be visible. A model, not a mind.";
  const CAPTION_PROCEDURAL = "Shapes are real reconstructed neurons (public databases); thickness, spines and myelin are drawn " +
    "from published typical values. The simulated network uses point neurons (no dendrites are simulated); cells " +
    "are enlarged and pulses slowed to be visible. A model, not a mind.";
  const H01_SETS = { cortex: "cortex" };                          // close-up kinds with a real H01 set (web/neuron_render/h01/)
  const H01_CITE = "Shapson-Coe A, Januszewski M, Berger DR et al. (2024) A petavoxel fragment of human cerebral cortex reconstructed at nanoscale resolution. Science 384:eadk4858";
  // published typical values per cell type (sources: docs/spiking/neuron_render.md). spines: per um of dendrite beyond
  // spineFree um from the soma; myelin: ais = premyelin axon initial segment (um), internode length (um), g-ratio,
  // node gap as drawn (um; real ~1 um), maxOrder = axon branch orders that are myelinated; boutonEvery (um) on the
  // unmyelinated axon beyond the AIS; vU = unmyelinated conduction speed (m/s); myelinated: ~6 m/s per um of outer
  // diameter (Hursh 1939).
  const TYPES = {
    pyramidal:          { spines: 1.3, spineFree: 30, myelin: { ais: 48, internode: 50, g: 0.7, gap: 2, maxOrder: 2, minR: 0.1 }, boutonEvery: 4.5, vU: 0.3, col: 0 },
    basket:             { spines: 0.05, spineFree: 20, myelin: { ais: 25, internode: 27, g: 0.7, gap: 2, maxOrder: 3, minR: 0.1 }, boutonEvery: 4, vU: 0.4, col: 1 },
    medium_spiny:       { spines: 1.5, spineFree: 30, myelin: null, boutonEvery: 6, vU: 0.3, col: 0 },
    relay:              { spines: 0.1, spineFree: 30, myelin: { ais: 30, internode: 100, g: 0.7, gap: 2, maxOrder: 1, minR: 0.2 }, boutonEvery: 6, vU: 0.3, col: 0 },
    ca1_pyramidal:      { spines: 2.5, spineFree: 40, myelin: { ais: 35, internode: 80, g: 0.7, gap: 2, maxOrder: 2, minR: 0.15 }, boutonEvery: 6, vU: 0.3, col: 0 },
    amygdala_principal: { spines: 1.2, spineFree: 30, myelin: { ais: 35, internode: 80, g: 0.7, gap: 2, maxOrder: 2, minR: 0.15 }, boutonEvery: 6, vU: 0.3, col: 0 },
  };
  const KINDS = {                                                 // close-up kind -> cell types and shares
    cortex: { types: [["pyramidal", 0.8], ["basket", 0.2]] },
    striatum: { types: [["medium_spiny", 1]] },
    thalamus: { types: [["relay", 1]] },
    hippocampus: { types: [["ca1_pyramidal", 1]] },
    amygdala: { types: [["amygdala_principal", 1]] },
  };
  // levels of detail: cells per tier (hero: full tubes, spines, myelin, boutons, nucleus; mid: tubes, nucleus; far:
  // lines), tube sides, node stride of the mid tier, background sprites, the field of view (um, vertical) and the
  // triangle cap the planner trims to (mid cells first, then spines).
  const LOD = {
    phone:   { cap: 250000, hero: 3, mid: 12, far: 60, sides: 5, sidesMid: 4, strideMid: 3, bg: 1800, field: 340, floorPx: 1.0, spineTri: 36000, dpr: 1.5 },
    desktop: { cap: 1000000, hero: 5, mid: 30, far: 90, sides: 7, sidesMid: 5, strideMid: 1, bg: 3200, field: 400, floorPx: 0.9, spineTri: 110000, dpr: 1.5 },
  };
  const K = { SOMA: 0, AXON: 1, BASAL: 2, APICAL: 3, MYELIN: 4, SPINE: 5, BOUTON: 6, NUCLEUS: 7, NUCLEOLUS: 8, GLIA: 9, SYN_PRE: 10, SYN_POST: 11 };

  // rate (Hz) -> the byte quantise_rates sends (a pod without per-region rates: its network group's rate, labelled by the page)
  const rateByte = hz => !(hz >= 0.1) ? 0 : Math.max(1, Math.min(255, Math.round(1 + 254 * Math.log(Math.min(hz, 100) / 0.1) / Math.log(1000))));
  function unb64(s) { if (!s) return new Uint8Array(0); const b = atob(s), o = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) o[i] = b.charCodeAt(i); return o; }
  function mulberry(seed) { let a = seed >>> 0; return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
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
  const v3 = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
  const len3 = (a, b) => Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
  const norm3 = v => { const l = Math.hypot(v[0], v[1], v[2]) || 1; return [v[0] / l, v[1] / l, v[2] / l]; };
  const cross3 = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const dot3 = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const key3 = p => (Math.round(p[0] * 10) + "," + Math.round(p[1] * 10) + "," + Math.round(p[2] * 10));

  // ---------- the plan of one cell type: nodes with path distance, arrival time of the action potential, myelin ----------
  // Returns {paths: [{k, o, nodes: [{p, r, d, t, my}], tip}], gaps, boutons: [{p, r, t}], somaDirs: [{dir, r}]}.
  // t: seconds after the spike at which the pulse reaches the node (-1 on dendrites); my: the stretch after the node is
  // myelinated. Inside an internode every node carries the time the pulse reached the node before it, so the whole
  // internode lights at once and the next one after the internode's conduction time (saltatory).
  function plan(cell, T) {
    const vU = T.vU * 1e6 / SLOWDOWN, M = T.myelin;                // um/s on screen
    const paths = cell.paths.map(P => ({ k: P.k, o: P.o, d0: P.d0, raw: P.p })).sort((a, b) => a.d0 - b.d0);
    const starts = new Set(), endT = new Map();
    for (const P of paths) starts.add(key3(P.raw.slice(0, 3)));
    // the axon's main trunk: at every branch point the child whose subtree reaches farthest (collaterals branch off it)
    const trunk = new Set();
    { const ax = paths.filter(P => P.k === K.AXON), byStart = new Map(), reach = new Map();
      for (const P of ax) { const k = key3(P.raw.slice(0, 3)); if (!byStart.has(k)) byStart.set(k, []); byStart.get(k).push(P); }
      const pathLen = P => { let l = 0; for (let i = 4; i < P.raw.length; i += 4) l += Math.hypot(P.raw[i] - P.raw[i - 4], P.raw[i + 1] - P.raw[i - 3], P.raw[i + 2] - P.raw[i - 2]); return l; };
      const endKey = P => key3(P.raw.slice(P.raw.length - 4, P.raw.length - 1));
      const deep = P => { if (reach.has(P)) return reach.get(P); let best = 0; for (const C of byStart.get(endKey(P)) || []) best = Math.max(best, deep(C)); reach.set(P, pathLen(P) + best); return reach.get(P); };
      for (const P of ax) deep(P);
      let cur = ax.filter(P => !ax.some(Q => endKey(Q) === key3(P.raw.slice(0, 3)))).sort((a, b) => reach.get(b) - reach.get(a))[0];
      while (cur) { trunk.add(cur); const kids = byStart.get(endKey(cur)) || []; cur = kids.sort((a, b) => reach.get(b) - reach.get(a))[0]; } }
    const out = [], boutons = [], somaDirs = [];
    let gaps = 0, nodesOfRanvier = 0;
    for (const P of paths) {
      const n = P.raw.length / 4, src = [];
      for (let i = 0; i < n; i++) {
        const p = [P.raw[4 * i], P.raw[4 * i + 1], P.raw[4 * i + 2]], r = P.raw[4 * i + 3];
        if (src.length && len3(src[src.length - 1].p, p) < 0.05) continue;
        src.push({ p, r });
      }
      if (src.length < 2) continue;
      const tip = !starts.has(key3(src[src.length - 1].p));
      if (P.d0 === 0) somaDirs.push({ dir: norm3([src[1].p[0] - src[0].p[0], src[1].p[1] - src[0].p[1], src[1].p[2] - src[0].p[2]]), r: src[1].r });
      const nodes = [];
      if (P.k !== K.AXON) {
        let d = P.d0;
        for (let i = 0; i < src.length; i++) { if (i) d += len3(src[i - 1].p, src[i].p); nodes.push({ p: src[i].p, r: src[i].r, d, t: -1, my: false }); }
        out.push({ k: P.k, o: P.o, nodes, tip });
        continue;
      }
      const rMean = src.reduce((a, s) => a + s.r, 0) / src.length;
      const elig = !!M && (P.o <= M.maxOrder || trunk.has(P)) && rMean >= M.minR;
      let t = endT.has(key3(src[0].p)) ? endT.get(key3(src[0].p)) : P.d0 / vU, d = P.d0, tInter = t;
      const vM = s => 6e6 * (2 * s.r / (M ? M.g : 0.7)) / SLOWDOWN;   // um/s on screen: 6 m/s per um outer diameter
      const period = M ? M.internode + M.gap : 1e9;
      const state = dd => !elig || dd < M.ais ? 0 : ((dd - M.ais) % period) < M.internode ? 1 : 2;   // 0 ais/unmyelinated, 1 internode, 2 node
      let lastBout = M ? M.ais : 0;
      nodes.push({ p: src[0].p, r: src[0].r, d, t, my: state(d) === 1 });
      for (let i = 1; i < src.length; i++) {
        const a = src[i - 1], b = src[i], L = len3(a.p, b.p);
        let cur = 0;
        while (cur < L - 1e-6) {
          const st = state(d), rel = elig && d >= M.ais ? (d - M.ais) % period : 0;
          let bound = L - cur;                                  // distance to the next pattern change
          if (elig) {
            if (d < M.ais) bound = Math.min(bound, M.ais - d);
            else if (st === 1) bound = Math.min(bound, M.internode - rel);
            else bound = Math.min(bound, period - rel);
          }
          const step = Math.max(1e-3, Math.min(bound, L - cur));
          const u = (cur + step) / L, p = v3(a.p, b.p, u), r = a.r + (b.r - a.r) * u;
          if (st === 1) { t += step / vM({ r }); }              // the pulse crosses the internode...
          else { t += step / vU; }
          cur += step; d += step;
          const stNext = state(d);
          if (st === 1 && stNext !== 1) { nodesOfRanvier++; tInter = t; }   // ...and lights the next node
          const tNode = stNext === 1 ? (st === 1 ? tInter : (tInter = t)) : t;
          nodes.push({ p, r, d, t: tNode, my: stNext === 1 });
          if (st !== 1 && d >= lastBout + T.boutonEvery * (0.7 + 0.6 * ((i * 7919 + Math.round(d)) % 13) / 13)) {   // en passant bouton
            lastBout = d; if (d > (M ? M.ais : 10)) boutons.push({ p, r: 0.5, t, d });
          }
        }
      }
      // the whole internode shows the time the pulse reached its start node
      for (let i = nodes.length - 1; i > 0; i--) if (nodes[i - 1].my) nodes[i - 1].t = Math.min(nodes[i - 1].t, nodes[i].t);
      const last = nodes[nodes.length - 1];
      endT.set(key3(last.p), last.t);
      if (tip) boutons.push({ p: last.p, r: 0.9, t: last.t, d: last.d });
      out.push({ k: P.k, o: P.o, nodes, tip });
    }
    gaps = nodesOfRanvier;
    return { paths: out, gaps, boutons, somaDirs };
  }

  // ---------- geometry builder: centreline + offset direction + radius, so the shader can apply a pixel floor ----------
  class Builder {
    constructor() { this.pos = []; this.off = []; this.nrm = []; this.r = []; this.kind = []; this.dist = []; this.arr = []; this.idx = []; }
    get n() { return this.r.length; }
    vert(p, off, nrm, r, kind, d, t) { this.pos.push(p[0], p[1], p[2]); this.off.push(off[0], off[1], off[2]); this.nrm.push(nrm[0], nrm[1], nrm[2]);
      this.r.push(r); this.kind.push(kind); this.dist.push(d); this.arr.push(t); return this.n - 1; }
    tri(a, b, c) { this.idx.push(a, b, c); }
    // a tube along nodes [{p, r, d, t}] with `sides` sides, radius x rScale, tapered to a point at the end if `cap`
    tube(nodes, sides, kind, rScale, cap) {
      if (nodes.length < 2) return;
      let nrm = null, first = -1, prev = -1;
      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[Math.max(0, i - 1)].p, b = nodes[Math.min(nodes.length - 1, i + 1)].p;
        let tg = norm3([b[0] - a[0], b[1] - a[1], b[2] - a[2]]);
        if (!nrm) { const h = Math.abs(tg[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0]; nrm = norm3(cross3(tg, h)); }
        else { const dn = dot3(nrm, tg); let v = [nrm[0] - tg[0] * dn, nrm[1] - tg[1] * dn, nrm[2] - tg[2] * dn];
          if (Math.hypot(v[0], v[1], v[2]) < 1e-4) { const h = Math.abs(tg[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0]; v = cross3(tg, h); } nrm = norm3(v); }
        const bn = cross3(tg, nrm), nd = nodes[i], base = this.n;
        for (let s = 0; s < sides; s++) {
          const an = s / sides * 6.2831853, c = Math.cos(an), sn = Math.sin(an);
          const off = [nrm[0] * c + bn[0] * sn, nrm[1] * c + bn[1] * sn, nrm[2] * c + bn[2] * sn];
          this.vert(nd.p, off, off, nd.r * rScale, kind, nd.d, nd.t);
        }
        if (prev >= 0) for (let s = 0; s < sides; s++) { const s1 = (s + 1) % sides;
          this.tri(prev + s, base + s, base + s1); this.tri(prev + s, base + s1, prev + s1); }
        if (first < 0) first = base;
        prev = base;
      }
      if (cap) { const nd = nodes[nodes.length - 1], tipV = this.vert(nd.p, [0, 0, 0], [0, 1, 0], 0, kind, nd.d, nd.t);
        for (let s = 0; s < sides; s++) this.tri(prev + s, tipV, prev + (s + 1) % sides); }
    }
    // an icosphere (subdiv 0..2) of radius radiusFn(dir) around c
    sphere(c, radiusFn, subdiv, kind, d, t) {
      const ph = (1 + Math.sqrt(5)) / 2;
      let V = [[-1, ph, 0], [1, ph, 0], [-1, -ph, 0], [1, -ph, 0], [0, -1, ph], [0, 1, ph], [0, -1, -ph], [0, 1, -ph], [ph, 0, -1], [ph, 0, 1], [-ph, 0, -1], [-ph, 0, 1]].map(norm3);
      let F = [[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11], [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8], [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9], [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]];
      for (let s = 0; s < subdiv; s++) {
        const mid = new Map(), F2 = [];
        const m = (a, b) => { const k = a < b ? a + "_" + b : b + "_" + a; if (mid.has(k)) return mid.get(k);
          V.push(norm3([V[a][0] + V[b][0], V[a][1] + V[b][1], V[a][2] + V[b][2]])); mid.set(k, V.length - 1); return V.length - 1; };
        for (const [a, b, c] of F) { const ab = m(a, b), bc = m(b, c), ca = m(c, a); F2.push([a, ab, ca], [b, bc, ab], [c, ca, bc], [ab, bc, ca]); }
        F = F2;
      }
      const base = this.n;
      for (const v of V) this.vert(c, v, v, radiusFn(v), kind, d, t);
      for (const [a, b, cc] of F) this.tri(base + a, base + b, base + cc);
    }
    octa(c, r, kind, d, t) {
      const base = this.n, D = [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]];
      for (const v of D) this.vert(c, v, v, r, kind, d, t);
      for (const [a, b, cc] of [[0, 2, 4], [2, 1, 4], [1, 3, 4], [3, 0, 4], [2, 0, 5], [1, 2, 5], [3, 1, 5], [0, 3, 5]]) this.tri(base + a, base + b, base + cc);
    }
    quad(a, b, side, r, kind, d) {                                // a thin ribbon a -> b (stems): the pixel floor gives it width
      const base = this.n, m = [-side[0], -side[1], -side[2]];
      this.vert(a, side, side, r, kind, d, -1); this.vert(a, m, side, r, kind, d, -1); this.vert(b, side, side, r, kind, d, -1); this.vert(b, m, side, r, kind, d, -1);
      this.tri(base, base + 1, base + 2); this.tri(base + 1, base + 3, base + 2);
    }
    geometry(THREE) {
      const g = new THREE.InstancedBufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(this.pos), 3));
      g.setAttribute("aOff", new THREE.BufferAttribute(new Float32Array(this.off), 3));
      g.setAttribute("aNrm", new THREE.BufferAttribute(new Float32Array(this.nrm), 3));
      g.setAttribute("aR", new THREE.BufferAttribute(new Float32Array(this.r), 1));
      g.setAttribute("aKind", new THREE.BufferAttribute(new Float32Array(this.kind), 1));
      g.setAttribute("aDist", new THREE.BufferAttribute(new Float32Array(this.dist), 1));
      g.setAttribute("aArrive", new THREE.BufferAttribute(new Float32Array(this.arr), 1));
      g.setIndex(new THREE.BufferAttribute(this.n > 65535 ? new Uint32Array(this.idx) : new Uint16Array(this.idx), 1));
      return g;
    }
  }
  const strided = (nodes, k) => k <= 1 ? nodes : nodes.filter((_, i) => i % k === 0 || i === nodes.length - 1);
  function somaRadius(cell, T, dirs) {                             // deformed sphere: a cone toward the apical side, hillocks
    const R = cell.soma_r, apical = cell.paths.some(P => P.k === K.APICAL);
    return v => {
      let r = R * (1 + (apical ? 0.35 * v[1] * Math.abs(v[1]) : 0.1 * v[1]) + 0.05 * Math.sin(7.3 * v[0] + 5.1 * v[2]) * Math.cos(6.1 * v[1]));
      for (const h of dirs) { const c = Math.max(0, dot3(v, h.dir)); r += Math.min(0.5 * R, 2.5 * h.r) * Math.pow(c, 14); }
      return r;
    };
  }
  // the geometry of one cell type at a tier. Returns {geom, tri, spines, boutons, nodes, spineUm, dendUm}
  function cellGeometry(THREE, cell, T, tier, L, seed) {
    const P = plan(cell, T), B = new Builder(), hero = tier === "hero", sides = hero ? L.sides : L.sidesMid, stride = hero ? 1 : L.strideMid;
    const rnd = mulberry(seed);
    let dendUm = 0;
    for (const path of P.paths) {
      B.tube(strided(path.nodes, stride), sides, path.k, 1, path.tip);
      if (path.k !== K.AXON) dendUm += path.nodes[path.nodes.length - 1].d - path.nodes[0].d;
    }
    B.sphere([0, 0, 0], somaRadius(cell, T, P.somaDirs), hero ? 2 : 1, K.SOMA, 0, -1);
    let myelinTri = 0, boutons = 0;
    if (hero) {
      // myelin sheath: tubes over the myelinated runs, radius / g-ratio
      const M = T.myelin;
      if (M) for (const path of P.paths) { if (path.k !== K.AXON) continue;
        let run = [];
        for (let i = 0; i < path.nodes.length; i++) { const nd = path.nodes[i];
          if (nd.my) run.push(nd);
          else { if (run.length) { run.push(nd); B.tube(run.map(x => ({ p: x.p, r: Math.max(0.25, x.r), d: x.d, t: x.t })), Math.max(4, sides - 1), K.MYELIN, 1 / M.g, false); } run = []; } }
        if (run.length > 1) B.tube(run.map(x => ({ p: x.p, r: Math.max(0.25, x.r), d: x.d, t: x.t })), Math.max(4, sides - 1), K.MYELIN, 1 / M.g, false);
      }
      for (const b of P.boutons) { B.octa(b.p, b.r, K.BOUTON, b.d, b.t); boutons++; }
    }
    const triBase = B.idx.length / 3;
    // spines: stem (ribbon) + head (octahedron), nearest the soma first, within the triangle budget
    let spines = 0, spineUm = 0;
    if (hero && T.spines > 0) {
      const S = new Builder(), budget = L.spineTri, paths = P.paths.filter(p => p.k !== K.AXON).sort((a, b) => a.nodes[0].d - b.nodes[0].d);
      for (const path of paths) {
        if (S.idx.length / 3 + 10 > budget) break;
        const nodes = path.nodes, covered = nodes[nodes.length - 1].d - Math.max(nodes[0].d, T.spineFree);
        if (covered <= 0) continue;                                 // inside the spine-free zone
        let next = Math.max(nodes[0].d, T.spineFree) + rnd() / T.spines;
        for (let i = 1; i < nodes.length && S.idx.length / 3 + 10 <= budget; i++) {
          const a = nodes[i - 1], b = nodes[i];
          while (next <= b.d && S.idx.length / 3 + 10 <= budget) {
            const u = (next - a.d) / Math.max(1e-6, b.d - a.d), p = v3(a.p, b.p, u), r = a.r + (b.r - a.r) * u;
            const tg = norm3([b.p[0] - a.p[0], b.p[1] - a.p[1], b.p[2] - a.p[2]]);
            let dir = norm3([rnd() - 0.5, rnd() - 0.5, rnd() - 0.5]); const dn = dot3(dir, tg);
            dir = norm3([dir[0] - tg[0] * dn, dir[1] - tg[1] * dn, dir[2] - tg[2] * dn]);
            const len = 0.7 + 1.1 * rnd(), head = 0.22 + 0.2 * rnd();
            const base = [p[0] + dir[0] * r * 0.8, p[1] + dir[1] * r * 0.8, p[2] + dir[2] * r * 0.8];
            const tip = [p[0] + dir[0] * (r + len), p[1] + dir[1] * (r + len), p[2] + dir[2] * (r + len)];
            S.quad(base, tip, norm3(cross3(dir, tg)), 0.08, K.SPINE, next);
            S.octa(tip, head, K.SPINE, next, -1);
            spines++; next += (0.6 + 0.8 * rnd()) / T.spines;
          }
        }
        spineUm += covered;
      }
      // merge the spines into the cell's geometry (one draw call per hero cell)
      const o = B.n;
      for (const k of ["pos", "off", "nrm", "r", "kind", "dist", "arr"]) { const a = B[k], b = S[k]; for (let i = 0; i < b.length; i++) a.push(b[i]); }
      for (let i = 0; i < S.idx.length; i++) B.idx.push(S.idx[i] + o);
    }
    const geom = B.geometry(THREE);
    return { geom, tri: B.idx.length / 3, triNoSpines: triBase, spines, spineUm: Math.max(0, spineUm), dendUm, boutons, nodes: P.gaps, myelinTri };
  }
  // the far tier: line segments along the strided paths (one instanced draw call per type)
  function lineGeometry(THREE, cell, T, stride) {
    const P = plan(cell, T), pos = [], kind = [], dist = [], arr = [];
    for (const path of P.paths) { const nodes = strided(path.nodes, stride);
      for (let i = 1; i < nodes.length; i++) { const a = nodes[i - 1], b = nodes[i];
        pos.push(a.p[0], a.p[1], a.p[2], b.p[0], b.p[1], b.p[2]); kind.push(path.k, path.k); dist.push(a.d, b.d); arr.push(a.t, b.t); } }
    const r = cell.soma_r;                                       // the soma: three crossed strokes
    for (let a = 0; a < 3; a++) { const ax = [0, 0, 0]; ax[a] = r; pos.push(-ax[0], -ax[1], -ax[2], ax[0], ax[1], ax[2]); kind.push(0, 0); dist.push(0, 0); arr.push(-1, -1); }
    const g = new THREE.InstancedBufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(pos), 3));
    g.setAttribute("aKind", new THREE.BufferAttribute(new Float32Array(kind), 1));
    g.setAttribute("aDist", new THREE.BufferAttribute(new Float32Array(dist), 1));
    g.setAttribute("aArrive", new THREE.BufferAttribute(new Float32Array(arr), 1));
    return { geom: g, segments: pos.length / 6 };
  }

  // ---------- shaders ----------
  const ROT = `vec3 rotq(vec4 q, vec3 v){ return v + 2.0 * cross(q.xyz, cross(q.xyz, v) + q.w * v); }`;
  const INST = `attribute vec3 iOff; attribute vec4 iQuat; attribute float iScale; attribute float iSpike; attribute float iCol; attribute float iBright;`;
  const VS_CELL = `
    attribute vec3 aOff; attribute vec3 aNrm; attribute float aR; attribute float aKind; attribute float aDist; attribute float aArrive;
    ${INST}
    uniform float uTime, uPixK, uFloorPx, uDepthK, uPulseW, uPulseTail, uPulseFade, uPulseSwell;
    varying vec3 vN, vV; varying float vDepth, vKind, vCol, vSoma, vPulse, vR, vDist, vBright;
    ${ROT}
    void main(){
      vec3 c = rotq(iQuat, position * iScale) + iOff;
      vec3 off = rotq(iQuat, aOff);
      vec4 cv = modelViewMatrix * vec4(c, 1.0);
      float fl = uFloorPx * (abs(aKind - 4.0) < 0.5 ? 2.4 : (abs(aKind - 5.0) < 0.5 ? 0.8 : 1.0));
      float rr = max(aR * iScale, fl * uPixK * -cv.z);
      float dt = uTime - iSpike, on = step(0.0, dt);
      vSoma = on * exp(-dt / 0.3);
      float pulse = 0.0;
      if (aArrive >= 0.0) {
        if (abs(aKind - 6.0) < 0.5) pulse = on * step(aArrive, dt) * exp(-(dt - aArrive) / 0.9);                 // bouton: glows after arrival
        else { float x = dt - aArrive;                             // the travelling front; on the real axons the tube stays lit behind it, fading
          pulse = on * (exp(-pow(x / uPulseW, 2.0)) + uPulseTail * step(0.0, x) * exp(-x / 1.5)) * exp(-aArrive / uPulseFade); }
      }
      vec3 nrm = rotq(iQuat, aNrm);
      vec3 w = c + off * rr + nrm * (uPulseSwell * min(1.0, pulse));                                             // the lit stretch of a real (thin) axon swells a little
      vec4 mv = modelViewMatrix * vec4(w, 1.0);
      gl_Position = projectionMatrix * mv;
      vN = normalize(normalMatrix * nrm); vV = -mv.xyz;
      vDepth = clamp(-mv.z * uDepthK, 0.0, 1.0);
      vPulse = pulse; vKind = aKind; vCol = iCol; vR = rr; vDist = aDist; vBright = iBright;
    }`;
  const FS_CELL = `
    precision highp float;
    uniform float uStyle, uRate, uLive, uNucAlpha;
    uniform vec3 uColA, uColB, uColG, uColMy, uColAct;
    varying vec3 vN, vV; varying float vDepth, vKind, vCol, vSoma, vPulse, vR, vDist, vBright;
    void main(){
      vec3 n = normalize(vN), v = normalize(vV); float ndv = max(0.0, dot(n, v));
      float kSoma = step(abs(vKind - 0.0), 0.5), kAxon = step(abs(vKind - 1.0), 0.5), kMy = step(abs(vKind - 4.0), 0.5);
      float kSpine = step(abs(vKind - 5.0), 0.5), kBout = step(abs(vKind - 6.0), 0.5), kNuc = step(abs(vKind - 7.0), 0.5), kNucl = step(abs(vKind - 8.0), 0.5);
      float kDend = step(1.5, vKind) * step(vKind, 3.5) + kSpine, kGlia = step(abs(vKind - 9.0), 0.5);
      float glow = uLive * uRate;
      vec3 col; float alpha = vDepth;
      if (uStyle > 1.5) {
        // EM-like: a scanning-electron look on the reconstructed surface: mid-grey facing surfaces, bright grazing edges
        // (the secondary-electron edge effect), myelin paler, glia darker
        float I = 0.42 + 0.5 * pow(ndv, 0.8) + 1.1 * pow(1.0 - ndv, 2.5);
        vec3 alb = vec3(0.62, 0.62, 0.6);
        alb = mix(alb, vec3(0.8, 0.8, 0.77), kMy); alb = mix(alb, vec3(0.42, 0.43, 0.46), kGlia);
        alb = mix(alb, vec3(0.42, 0.40, 0.44), kNuc); alb = mix(alb, vec3(0.22, 0.2, 0.24), kNucl);
        col = alb * I * (0.6 + 0.4 * vBright);
        col += uColAct * (0.5 * glow * kDend * 0.3 + 1.4 * vSoma * kSoma + 0.8 * vSoma * exp(-vDist / 40.0) * kDend + 2.0 * vPulse * (kAxon + kBout + 0.5 * kMy));
        alpha = mix(alpha, uNucAlpha, kNuc); alpha = mix(alpha, 0.85, kNucl);
      } else if (uStyle < 0.5) {
        vec3 base = vCol < 0.5 ? uColA : (vCol < 1.5 ? uColB : uColG);
        float thick = clamp(vR / 1.2, 0.55, 1.0);
        float I = (0.35 + 0.75 * pow(ndv, 0.6)) * thick;
        I = mix(I, 0.7 + 0.3 * ndv, kSoma);
        I = mix(I, 0.2 + 0.18 * ndv, kSpine);
        I = mix(I, 0.5 + 0.3 * ndv, kBout);
        col = base * I;
        col = mix(col, uColMy * (0.08 + 0.22 * ndv), kMy);
        col = mix(col, base * 0.55 * (0.7 + 0.3 * ndv), kNuc);
        col = mix(col, base * 0.35, kNucl);
        col *= vBright * (1.0 + 0.6 * glow * kDend + 0.25 * glow * kSoma);
        col += base * 2.2 * vSoma * kSoma + base * 1.4 * vSoma * exp(-vDist / 40.0) * kDend;
        col += uColAct * 3.0 * vPulse * (kAxon + kBout + kMy * 0.4);
        alpha = mix(alpha, uNucAlpha, kNuc) ; alpha = mix(alpha, 0.9, kNucl);
      } else {
        vec3 L = normalize(vec3(0.5, 0.7, 0.55));
        float diff = max(0.0, (dot(n, L) + 0.3) / 1.3);
        float spec = pow(max(0.0, dot(reflect(-L, n), v)), 32.0) * 0.25;
        float rim = pow(1.0 - ndv, 3.0);
        vec3 alb = mix(vec3(0.90, 0.72, 0.66), vec3(0.72, 0.62, 0.82), vCol);
        alb = mix(alb, vec3(0.16, 0.15, 0.2), 1.0 - vBright);                 // cells out of the spotlight: darker, cooler
        alb = mix(alb, vec3(0.96, 0.93, 0.85), kMy);
        alb = mix(alb, vec3(0.62, 0.58, 0.80), kNuc); alb = mix(alb, vec3(0.30, 0.22, 0.40), kNucl);
        vec3 sss = vec3(0.9, 0.38, 0.3) * pow(1.0 - ndv, 2.0) * 0.25 * (1.0 - kMy) * vBright;
        col = alb * (0.07 + 0.93 * diff) * (0.55 + 0.45 * vBright) + spec * vBright + sss + rim * vec3(0.25, 0.35, 0.5) * 0.25;
        col += uColAct * (0.9 * glow * kDend * 0.5 + 1.8 * vSoma * kSoma + 1.0 * vSoma * exp(-vDist / 40.0) * kDend + 2.5 * vPulse * (kAxon + kBout));
        alpha = mix(alpha, uNucAlpha, kNuc); alpha = mix(alpha, 0.85, kNucl);
      }
      gl_FragColor = vec4(col, alpha);
    }`;
  const VS_LINE = `
    attribute float aKind; attribute float aDist; attribute float aArrive;
    ${INST}
    uniform float uTime, uDepthK, uPulseW, uPulseTail, uPulseFade;
    varying float vKind, vCol, vSoma, vPulse, vDist, vDepth;
    ${ROT}
    void main(){
      vec3 w = rotq(iQuat, position * iScale) + iOff;
      vec4 mv = modelViewMatrix * vec4(w, 1.0);
      gl_Position = projectionMatrix * mv;
      vDepth = clamp(-mv.z * uDepthK, 0.0, 1.0);
      float dt = uTime - iSpike, on = step(0.0, dt), x = dt - aArrive;
      vSoma = on * exp(-dt / 0.3);
      vPulse = aArrive >= 0.0 ? on * (exp(-pow(x / uPulseW, 2.0)) + uPulseTail * step(0.0, x) * exp(-x / 1.5)) * exp(-aArrive / uPulseFade) : 0.0;
      vKind = aKind; vCol = iCol; vDist = aDist;
    }`;
  const FS_LINE = `
    precision highp float;
    uniform float uStyle, uRate, uLive, uDim; uniform vec3 uColA, uColB, uColAct;
    varying float vKind, vCol, vSoma, vPulse, vDist, vDepth;
    void main(){
      float kSoma = step(abs(vKind), 0.5), kAxon = step(abs(vKind - 1.0), 0.5) + step(abs(vKind - 4.0), 0.5) + step(abs(vKind - 5.0), 0.5);
      float kDend = step(1.5, vKind) * (1.0 - step(abs(vKind - 4.0), 0.5)) * (1.0 - step(abs(vKind - 5.0), 0.5));
      vec3 base = uStyle < 0.5 ? mix(uColA, uColB, vCol) : (uStyle > 1.5 ? vec3(0.62, 0.62, 0.6) : vec3(0.5, 0.48, 0.55));
      float glow = uLive * uRate;
      vec3 col = base * uDim * (0.5 + 0.5 * kSoma + 0.5 * glow * kDend) * mix(1.0, 1.5, vDepth);
      col += base * 1.2 * vSoma * (kSoma + kDend * exp(-vDist / 40.0)) + uColAct * 3.0 * vPulse * kAxon;
      gl_FragColor = vec4(col, 1.0);
    }`;
  const VS_BG = `
    attribute float aSize; attribute float aAngle; attribute float aKind;
    uniform float uScale; varying float vAngle, vKind;
    void main(){ vec4 mv = modelViewMatrix * vec4(position, 1.0); gl_Position = projectionMatrix * mv;
      gl_PointSize = max(2.0, aSize * uScale / -mv.z); vAngle = aAngle; vKind = aKind; }`;
  const FS_BG = `
    precision highp float;
    uniform float uStyle, uDim; uniform vec3 uColA, uColRed; varying float vAngle, vKind;
    void main(){
      vec2 c = gl_PointCoord - 0.5; float cs = cos(vAngle), sn = sin(vAngle);
      vec2 q = vec2(cs * c.x - sn * c.y, sn * c.x + cs * c.y);
      float streak = exp(-q.x * q.x * 14.0 - q.y * q.y * 260.0);
      float d = length(c) * 2.0, blob = exp(-pow((d - 0.55) / 0.2, 2.0)) * 0.7 + exp(-d * d * 8.0) * 0.3;
      vec3 col = uStyle < 0.5 ? mix(uColA * 0.05 * streak, uColRed * 0.25 * blob, vKind) : mix(vec3(0.5, 0.45, 0.48) * 0.04 * streak, vec3(0.5, 0.36, 0.38) * blob * 0.12, vKind);
      gl_FragColor = vec4(col * uDim, 1.0);
    }`;
  const VS_SYN = `
    attribute float aArrive; attribute float aKind;
    uniform float uTime, uSpike, uPixK, uDepthK, uScale;
    varying float vFlash, vKind, vDepth;
    void main(){ vec4 mv = modelViewMatrix * vec4(position, 1.0); gl_Position = projectionMatrix * mv;
      vDepth = clamp(-mv.z * uDepthK, 0.0, 1.0);
      float dt = uTime - uSpike, on = step(0.0, dt);
      vFlash = aArrive >= 0.0 ? on * step(aArrive, dt) * exp(-(dt - aArrive) / 0.9) : 0.0;
      vKind = aKind;
      float um = aKind < 10.5 ? 0.9 : 0.6;                          // a bouton ~0.9 um, a PSD ~0.6 um
      gl_PointSize = max(2.0, um * uScale / -mv.z + 1.5 * vFlash * uScale / -mv.z); }`;
  const FS_SYN = `
    precision highp float;
    uniform float uStyle, uLive, uRate; uniform vec3 uColAct;
    varying float vFlash, vKind, vDepth;
    void main(){
      vec2 c = gl_PointCoord - 0.5; float d2 = dot(c, c); if (d2 > 0.25) discard;
      float soft = exp(-d2 * 9.0);
      float pre = step(vKind, 10.5);
      vec3 col = uStyle > 1.5 ? mix(vec3(0.3, 0.32, 0.34), vec3(0.45, 0.4, 0.3), pre) * 0.5 : mix(vec3(0.55, 0.15, 0.6) * 0.5, vec3(1.0, 0.55, 0.2) * 0.45, pre);
      col = col * (0.6 + 0.6 * uLive * uRate * (1.0 - pre)) + uColAct * 2.5 * vFlash;
      gl_FragColor = vec4(col * soft, 1.0);
    }`;
  const VS_EM = `varying vec2 vUv; varying float vDepth; uniform float uDepthK;
    void main(){ vUv = uv; vec4 mv = modelViewMatrix * vec4(position, 1.0); vDepth = clamp(-mv.z * uDepthK, 0.0, 1.0); gl_Position = projectionMatrix * mv; }`;
  const FS_EM = `precision highp float; uniform sampler2D tEm; uniform float uStyle; varying vec2 vUv; varying float vDepth;
    void main(){ float g = texture2D(tEm, vUv).r; vec2 d = vUv / 9.0 - 0.5; float edge = smoothstep(0.5, 0.3, max(abs(d.x), abs(d.y)));
      g = pow(g, 1.4); gl_FragColor = vec4(vec3(0.015 + 0.2 * g) * (0.5 + 0.5 * edge), vDepth); }`;
  const VS_QUAD = `varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`;
  const FS_DOWN = `precision highp float; uniform sampler2D tSrc; uniform vec2 uTexel; varying vec2 vUv;
    void main(){ vec4 s = texture2D(tSrc, vUv + uTexel * vec2(-0.5, -0.5)) + texture2D(tSrc, vUv + uTexel * vec2(0.5, -0.5))
      + texture2D(tSrc, vUv + uTexel * vec2(-0.5, 0.5)) + texture2D(tSrc, vUv + uTexel * vec2(0.5, 0.5)); gl_FragColor = s * 0.25; }`;
  const FS_BRIGHT = `precision highp float; uniform sampler2D tSrc; uniform float uTh; varying vec2 vUv;
    void main(){ vec4 s = texture2D(tSrc, vUv); float l = dot(s.rgb, vec3(0.3, 0.59, 0.11));
      gl_FragColor = vec4(s.rgb * smoothstep(uTh, uTh * 2.2, l), 1.0); }`;
  const FS_BLUR = `precision highp float; uniform sampler2D tSrc; uniform vec2 uDir; varying vec2 vUv;
    void main(){ vec4 s = texture2D(tSrc, vUv) * 0.2270270270;
      s += (texture2D(tSrc, vUv + uDir * 1.3846153846) + texture2D(tSrc, vUv - uDir * 1.3846153846)) * 0.3162162162;
      s += (texture2D(tSrc, vUv + uDir * 3.2307692308) + texture2D(tSrc, vUv - uDir * 3.2307692308)) * 0.0702702703;
      gl_FragColor = s; }`;
  const FS_COMP = `precision highp float; uniform sampler2D tScene, tBlur, tBloom; uniform float uFocus, uDofRange, uDofMax, uBloom, uExposure, uStyle;
    uniform vec3 uBg; varying vec2 vUv;
    void main(){
      vec4 s = texture2D(tScene, vUv); vec3 b = texture2D(tBlur, vUv).rgb, g = texture2D(tBloom, vUv).rgb;
      float coc = smoothstep(0.08, uDofRange, abs(s.a - uFocus)) * uDofMax;
      vec3 c = mix(s.rgb, b, coc) + g * uBloom;
      vec2 d = vUv - 0.5; float vig = 1.0 - 0.4 * dot(d, d) * 2.0;
      c = (c * uExposure + uBg) * vig;
      c = c / (1.0 + c * 0.6);
      c = pow(max(c, 0.0), vec3(1.0 / 2.0));
      gl_FragColor = vec4(c, 1.0);
    }`;

  // ---------- the asset ----------
  let CELLS = null, loading = null;
  function load(url) {
    if (CELLS) return Promise.resolve(CELLS);
    if (!loading) loading = fetch(url || ASSET).then(r => { if (!r.ok) throw new Error("cells.json " + r.status); return r.json(); }).then(j => (CELLS = j, NR.CELLS = j, j));
    return loading;
  }

  // the triangle cap: hero [{tri, triNoSpines}], mids [{tri, n}] -> instance counts of the mid tier, triangles kept per hero cell
  function budget(L, hero, mids, nucTri) {
    let total = hero.reduce((a, h) => a + h.tri, 0) + mids.reduce((a, m) => a + m.tri * m.n, 0) + (nucTri || 0);
    const midN = mids.map(m => m.n), keep = hero.map(h => h.tri);
    for (let i = midN.length - 1; i >= 0; i--) while (total > L.cap && midN[i] > 2) { midN[i]--; total -= mids[i].tri; }
    for (let i = hero.length - 1; i >= 0 && total > L.cap; i--) { const drop = Math.min(hero[i].tri - hero[i].triNoSpines, total - L.cap); keep[i] -= drop; total -= drop; }
    return { midN, keep, total };
  }

  // ---------- placement of the cells in a block of tissue (um; y up, pia at the top for cortex) ----------
  function place(kind, type, tier, i, n, rnd) {
    const sx = ((i + rnd()) / n - 0.5);
    let y = (rnd() - 0.5) * 500;
    if (kind === "hippocampus") y = (rnd() - 0.5) * 90;                  // CA1 somata packed in stratum pyramidale
    if (kind === "cortex") y = type === "pyramidal" ? -140 - 600 * rnd() : -100 - 800 * rnd();
    if (tier === "hero") return [i === 0 ? 0 : (i % 2 ? 1 : -1) * (120 + 110 * Math.ceil(i / 2)) + (rnd() - 0.5) * 60, kind === "cortex" ? -380 + (rnd() - 0.5) * 120 : kind === "hippocampus" ? y : (rnd() - 0.5) * 120, -130 * i + (rnd() - 0.5) * 40];
    if (tier === "mid") return [sx * 1500, y, -320 - 520 * rnd()];
    return [sx * 2400, y, -200 - 900 * rnd() + 300 * rnd()];
  }

  // ---------- open ----------
  function open(container, o) {
    const THREE = (o && o.THREE) || root.THREE;
    if (!THREE) throw new Error("NeuronRender.open: no THREE");
    const kind = o.kind, Kd = KINDS[kind];
    if (!Kd) throw new Error("NeuronRender.open: unknown kind " + kind);
    const isPhone = () => (root.innerWidth || 1000) < 700;
    const DEBUG = o.debug != null ? !!o.debug : /[?&]debug\b/.test(root.location ? root.location.search : "");   // fps in the overlay only then
    const styleOf = s => s === "em" ? "em" : (s === "render" ? "render" : "fluorescence");
    const S = { kind, region: o.region, label: o.label || "", style: styleOf(o.style), lodName: o.lod || "auto",
                trimTri: 0, h01: null, entry: o.entry ? { ms: o.entry.ms || 1200, from: o.entry.from || 6, t0: 0, on: false } : null,
                worldPos: o.worldPos || null, normal: o.normal && o.normal.length === 3 ? o.normal.slice() : null, readyResolve: null, opacity: 1, entryFade: 1,
                live: !!o.live, lastWall: o.live ? performance.now() : -1e9, forcedOffline: false, rate: 0, rateT: 0, spikes: 0, gap: 200, prev: 0,
                onScreen: true, closed: false, fps: 0, jsMs: 0, frames: 0, jsSum: 0, fpsAt: performance.now(), focus: 0, t0: performance.now(),
                userTouched: false, zoomedOut: false };
    const lodOf = () => S.lodName === "phone" || S.lodName === "desktop" ? S.lodName : (isPhone() ? "phone" : "desktop");
    let L = LOD[lodOf()];
    // DOM
    if (!root.document.getElementById("nr-style")) {
      const st = root.document.createElement("style"); st.id = "nr-style";
      st.textContent = ".nr-canvas{position:absolute;inset:0;width:100%;height:100%;display:block;touch-action:none;z-index:3}" +
        ".nr-hud{position:absolute;top:8px;right:8px;display:flex;gap:6px;font:12px ui-monospace,SFMono-Regular,Menlo,monospace;z-index:4}" +
        ".nr-hud button{background:rgba(0,0,0,.55);color:#ddd;border:1px solid #555;border-radius:4px;padding:3px 8px;cursor:pointer}" +
        ".nr-hud button.on{color:#ffb070;border-color:#ffb070}.nr-hud .nr-x{margin-left:4px}" +
        ".nr-stat{position:absolute;left:50%;transform:translateX(-50%);bottom:6px;font:11px ui-monospace,SFMono-Regular,Menlo,monospace;color:#9a9a9a;z-index:4;pointer-events:none;text-shadow:0 0 4px #000;white-space:nowrap}" +
        ".nr-bar{position:absolute;left:50%;transform:translateX(-50%);bottom:24px;font:11px ui-monospace,SFMono-Regular,Menlo,monospace;color:#ddd;z-index:4;pointer-events:none;text-shadow:0 0 4px #000;text-align:center}" +
        ".nr-bar i{display:block;height:3px;background:#eee;margin:0 auto 3px auto;box-shadow:0 0 3px #000}";
      root.document.head.appendChild(st);
    }
    const canvas = root.document.createElement("canvas"); canvas.className = "nr-canvas";
    const hud = root.document.createElement("div"); hud.className = "nr-hud";
    hud.innerHTML = '<button data-s="fluorescence">fluorescence</button><button data-s="render">3D render</button><button data-s="em">EM</button><button class="nr-x" title="back to the whole brain">✕</button>';
    const bar = root.document.createElement("div"); bar.className = "nr-bar"; bar.innerHTML = '<i></i><span></span>';
    const stat = root.document.createElement("div"); stat.className = "nr-stat";
    function applyOpacity() {                                      // nr.setOpacity() x the entry fade-in, on the canvas and the HUD alike
      const a = Math.max(0, Math.min(1, S.opacity * S.entryFade)); for (const el of [canvas, hud, stat, bar]) el.style.opacity = String(a); }
    S.entryFade = S.entry ? 0 : 1; applyOpacity();
    if (root.getComputedStyle && root.getComputedStyle(container).position === "static") container.style.position = "relative";
    container.appendChild(canvas); container.appendChild(hud); container.appendChild(stat); container.appendChild(bar);
    hud.querySelectorAll("button[data-s]").forEach(b => b.onclick = () => setStyle(b.dataset.s));
    hud.querySelector(".nr-x").onclick = () => { if (o.onClose) o.onClose("button"); };
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: false, powerPreference: "high-performance" });
    renderer.autoClear = true;
    const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(32, 1, 2, 9000);
    // B's zoom: the block's +y is "toward the pia"; o.normal (the outward cortical normal where B zoomed in, in B's world) turns the
    // whole block so the two coincide, and o.cameraDir / o.cameraUp are then taken in that same world (see the API doc, openAt)
    const frameQ = new THREE.Quaternion();
    if (S.normal) { const n = new THREE.Vector3(S.normal[0], S.normal[1], S.normal[2]);
      if (n.lengthSq() > 1e-12) { frameQ.setFromUnitVectors(new THREE.Vector3(0, 1, 0), n.normalize()); scene.quaternion.copy(frameQ); } }
    if (o.cameraUp && o.cameraUp.length === 3) camera.up.set(o.cameraUp[0], o.cameraUp[1], o.cameraUp[2]).normalize();
    const toWorld = p => { const v = new THREE.Vector3(p[0], p[1], p[2]).applyQuaternion(frameQ); return [v.x, v.y, v.z]; };
    const isGL2 = !!(renderer.capabilities && renderer.capabilities.isWebGL2);
    const halfOk = isGL2 ? !!renderer.extensions.get("EXT_color_buffer_float") : !!(renderer.extensions.get("OES_texture_half_float") && renderer.extensions.get("EXT_color_buffer_half_float"));
    const rtType = halfOk ? THREE.HalfFloatType : THREE.UnsignedByteType;
    const rtOpts = { minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter, format: THREE.RGBAFormat, type: rtType, depthBuffer: false, stencilBuffer: false };
    let rtScene = null, rtHalf = null, rtQ1 = null, rtQ2 = null, rtQ3 = null, rtQ4 = null, W = 0, H = 0;
    const quadScene = new THREE.Scene(), quadCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    const matDown = new THREE.ShaderMaterial({ uniforms: { tSrc: { value: null }, uTexel: { value: new THREE.Vector2() } }, vertexShader: VS_QUAD, fragmentShader: FS_DOWN, depthTest: false, depthWrite: false });
    const matBlur = new THREE.ShaderMaterial({ uniforms: { tSrc: { value: null }, uDir: { value: new THREE.Vector2() } }, vertexShader: VS_QUAD, fragmentShader: FS_BLUR, depthTest: false, depthWrite: false });
    const matBright = new THREE.ShaderMaterial({ uniforms: { tSrc: { value: null }, uTh: { value: 0.5 } }, vertexShader: VS_QUAD, fragmentShader: FS_BRIGHT, depthTest: false, depthWrite: false });
    const matComp = new THREE.ShaderMaterial({ uniforms: { tScene: { value: null }, tBlur: { value: null }, tBloom: { value: null }, uFocus: { value: 0.4 }, uDofRange: { value: 0.25 },
      uDofMax: { value: 0.7 }, uBloom: { value: 0.9 }, uExposure: { value: 1.0 }, uStyle: { value: 0 }, uBg: { value: new THREE.Vector3() } },
      vertexShader: VS_QUAD, fragmentShader: FS_COMP, depthTest: false, depthWrite: false });
    const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), matDown); quad.frustumCulled = false; quadScene.add(quad);
    const uni = { uTime: { value: 0 }, uPixK: { value: 0.001 }, uFloorPx: { value: L.floorPx }, uDepthK: { value: 1 / 2000 }, uPulseW: { value: 0.09 }, uPulseTail: { value: 0 }, uPulseFade: { value: 8 }, uPulseSwell: { value: 0 },
                  uStyle: { value: 0 }, uRate: { value: 0 }, uLive: { value: 0 }, uNucAlpha: { value: 0.45 }, uDim: { value: 0.3 },
                  uColA: { value: new THREE.Vector3(0.25, 1.0, 0.35) }, uColB: { value: new THREE.Vector3(1.0, 0.42, 0.15) },
                  uColMy: { value: new THREE.Vector3(0.6, 0.75, 1.0) }, uColAct: { value: new THREE.Vector3(1.0, 0.95, 0.7) },
                  uColG: { value: new THREE.Vector3(0.55, 0.7, 1.0) }, uSpike: { value: -1e4 }, tEm: { value: null },
                  uColRed: { value: new THREE.Vector3(0.8, 0.1, 0.05) }, uScale: { value: 1000 } };
    function cellMaterial(nucleus) {
      const m = new THREE.ShaderMaterial({ uniforms: uni, vertexShader: VS_CELL, fragmentShader: FS_CELL, side: THREE.FrontSide });
      if (nucleus) { m.transparent = true; m.depthWrite = false; m.blending = THREE.CustomBlending; m.blendSrc = THREE.SrcAlphaFactor; m.blendDst = THREE.OneMinusSrcAlphaFactor;
        m.blendSrcAlpha = THREE.ZeroFactor; m.blendDstAlpha = THREE.OneFactor; }
      else m.blending = THREE.NoBlending;
      return m;
    }
    const matCell = cellMaterial(false), matNuc = cellMaterial(true);
    const additive = m => { m.transparent = true; m.depthWrite = false; m.blending = THREE.CustomBlending; m.blendSrc = THREE.OneFactor; m.blendDst = THREE.OneFactor;
      m.blendSrcAlpha = THREE.ZeroFactor; m.blendDstAlpha = THREE.OneFactor; return m; };
    const matLine = additive(new THREE.ShaderMaterial({ uniforms: uni, vertexShader: VS_LINE, fragmentShader: FS_LINE }));
    const matBg = additive(new THREE.ShaderMaterial({ uniforms: uni, vertexShader: VS_BG, fragmentShader: FS_BG }));
    const matEm = new THREE.ShaderMaterial({ uniforms: uni, vertexShader: VS_EM, fragmentShader: FS_EM, blending: THREE.NoBlending });
    let emPlane = null, synMeshes = [];
    // the cells
    const cells = [];                                            // drawn cell k -> {tier, type, mesh | (geomSet, j)}
    const meshes = [], sets = [], counts = { triangles: 0, spines: 0, boutons: 0, nodes: 0, drawCalls: 0, lines: 0, heroCells: 0, spineUm: 0, dendUm: 0, cap: L.cap };
    let focusPos = [0, 0, 0], built = false, nucSet = null, bgPoints = null;
    function instAttrs(g, n, rnd, kind, type, tier) {
      const off = new Float32Array(n * 3), quat = new Float32Array(n * 4), sc = new Float32Array(n), spk = new Float32Array(n).fill(-1e4), col = new Float32Array(n);
      const q = new THREE.Quaternion(), e = new THREE.Euler();
      for (let j = 0; j < n; j++) {
        off.set(place(kind, type, tier, j, n, rnd), 3 * j);
        e.set((rnd() - 0.5) * 0.35, rnd() * 6.2832, (rnd() - 0.5) * 0.35); q.setFromEuler(e);
        quat.set([q.x, q.y, q.z, q.w], 4 * j);
        sc[j] = 0.85 + 0.3 * rnd();
        col[j] = TYPES[type].col || (tier !== "hero" && rnd() < 0.15 ? 1 : 0);   // a second fluorophore on a few cells
      }
      g.setAttribute("iOff", new THREE.InstancedBufferAttribute(off, 3));
      g.setAttribute("iQuat", new THREE.InstancedBufferAttribute(quat, 4));
      g.setAttribute("iScale", new THREE.InstancedBufferAttribute(sc, 1));
      const sa = new THREE.InstancedBufferAttribute(spk, 1); if (sa.setUsage) sa.setUsage(THREE.DynamicDrawUsage);
      g.setAttribute("iSpike", sa);
      g.setAttribute("iCol", new THREE.InstancedBufferAttribute(col, 1));
      const br = new Float32Array(n); for (let j = 0; j < n; j++) br[j] = tier === "hero" ? 1 : 0.35 + 0.3 * rnd();   // hero: set per cell in build()
      g.setAttribute("iBright", new THREE.InstancedBufferAttribute(br, 1));
      g.instanceCount = n;
      return { off, quat, sc, spk, sa, col, br };
    }
    function finish() {
      focusPos = cells[S.focus] ? cells[S.focus].pos : [0, 0, 0];
      built = true;
      applyStyle(); fit(); if (o.onInfo) o.onInfo(info());
    }
    // the H01 path: real cells, lazily loaded (web/neuron_render/h01.js + h01/<set>_<lod>.bin.gz)
    function build() {
      const set = H01_SETS[kind];
      if (set && typeof root.DecompressionStream === "function" && o.h01 !== false) {
        loadH01Module(o.base).then(h => h.load(set, lodOf(), o.base ? o.base + "h01/" : undefined)).then(data => { if (!S.closed) buildH01(data); })
          .catch(e => { console.warn("NeuronRender: H01 set unavailable, drawing the NeuroMorpho cells:", e); if (!S.closed) buildProcedural(); });
      } else buildProcedural();
    }
    function synPoints(c, kindOffset) {                            // this cell's real synapses: boutons (pre) flash on arrival, inputs (post) glow dimly
      const s = c.syn, n = s.npre + s.npost, kd = new Float32Array(n), ar = new Float32Array(n).fill(-1);
      for (let i = 0; i < n; i++) { kd[i] = i < s.npre ? K.SYN_PRE : K.SYN_POST; if (i < s.npre) ar[i] = s.preArrive[i]; }
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(s.pos, 3)); g.setAttribute("aKind", new THREE.BufferAttribute(kd, 1)); g.setAttribute("aArrive", new THREE.BufferAttribute(ar, 1));
      const m = additive(new THREE.ShaderMaterial({ uniforms: Object.assign({}, uni, { uSpike: { value: -1e4 } }), vertexShader: VS_SYN, fragmentShader: FS_SYN }));
      // dot-ok: this cell's real synapse positions from H01 (presynaptic sites flash when the pulse arrives; incoming ones are dim)
      const pts = new THREE.Points(g, m); pts.frustumCulled = false; pts.renderOrder = 1; pts.name = "nr-syn-" + c.id;
      return pts;
    }
    const ident = new Float32Array([0, 0, 0, 1]);
    const oneInstance = (g, bright, col) => {
      g.setAttribute("iOff", new THREE.InstancedBufferAttribute(new Float32Array(3), 3));
      g.setAttribute("iQuat", new THREE.InstancedBufferAttribute(ident.slice(), 4));
      g.setAttribute("iScale", new THREE.InstancedBufferAttribute(new Float32Array([1]), 1));
      const spk = new Float32Array([-1e4]), sa = new THREE.InstancedBufferAttribute(spk, 1); if (sa.setUsage) sa.setUsage(THREE.DynamicDrawUsage);
      g.setAttribute("iSpike", sa);
      g.setAttribute("iCol", new THREE.InstancedBufferAttribute(new Float32Array([col]), 1));
      g.setAttribute("iBright", new THREE.InstancedBufferAttribute(new Float32Array([bright]), 1));
      g.instanceCount = 1;
      return { off: new Float32Array(3), quat: ident, sc: new Float32Array([1]), spk, sa, col: new Float32Array([col]), br: new Float32Array([bright]) };
    };
    function skelLines(k, bright, col, name) {                    // a skeleton (parent links) as one LineSegments draw, with its own spike slot
      const pos = [], kd = [], di = [], ar = [];
      for (let i = 0; i < k.n; i++) { const p = k.parent[i]; if (p < 0) continue;
        pos.push(k.pos[3 * p], k.pos[3 * p + 1], k.pos[3 * p + 2], k.pos[3 * i], k.pos[3 * i + 1], k.pos[3 * i + 2]);
        kd.push(k.kind[p], k.kind[i]); di.push(k.dist[p], k.dist[i]); ar.push(k.arrive[p], k.arrive[i]); }
      const g = new THREE.InstancedBufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(pos), 3));
      g.setAttribute("aKind", new THREE.BufferAttribute(new Float32Array(kd), 1));
      g.setAttribute("aDist", new THREE.BufferAttribute(new Float32Array(di), 1));
      g.setAttribute("aArrive", new THREE.BufferAttribute(new Float32Array(ar), 1));
      const A = oneInstance(g, bright, col);
      const lines = new THREE.LineSegments(g, matLine); lines.frustumCulled = false; lines.renderOrder = 1; lines.name = name;
      scene.add(lines); meshes.push(lines); counts.lines += pos.length / 6; counts.drawCalls++;
      return { A, geom: g };
    }
    function skelTubes(k, bright, col, name, rUm) {               // a skeleton as thin 3-sided tubes through the cell shader: the pixel floor keeps
      const children = Array.from({ length: k.n }, () => []);      // them a pixel wide at least, and the pulse lights them node to node (no sprites)
      for (let i = 0; i < k.n; i++) if (k.parent[i] >= 0) children[k.parent[i]].push(i);
      const B = new Builder(), node = i => ({ p: [k.pos[3 * i], k.pos[3 * i + 1], k.pos[3 * i + 2]], r: rUm, d: k.dist[i], t: k.arrive[i] });
      for (let s = 0; s < k.n; s++) {                                // a chain starts at a root, after a branch point or where the class changes
        const p = k.parent[s];
        if (!(p < 0 || children[p].length > 1 || k.kind[s] !== k.kind[p])) continue;
        const chain = p >= 0 ? [p] : []; let i = s;
        for (;;) { chain.push(i); if (children[i].length !== 1 || k.kind[children[i][0]] !== k.kind[i]) break; i = children[i][0]; }
        if (chain.length >= 2) B.tube(chain.map(node), 3, k.kind[s], 1, false);
      }
      if (!B.n) return null;
      const g = B.geometry(THREE), A = oneInstance(g, bright, col);
      const mesh = new THREE.Mesh(g, matCell); mesh.frustumCulled = false; mesh.name = name;
      scene.add(mesh); meshes.push(mesh); counts.triangles += B.idx.length / 3; counts.drawCalls++;
      return { A, geom: g, tri: B.idx.length / 3 };
    }
    function buildH01(data) {
      S.h01 = data;
      // the real axons are thin (~0.5 µm, a pixel) and long (the focus cell's 4 mm take ~34 s at the slowed clock): the axon (the mesh's
      // tube and the thin tube along the cell's own axon skeleton) lights from the front back toward the soma (~45 µm, fading), swells by
      // ~0.6 µm where lit, and the pulse fades over 20 s instead of 8: a visual convention, said in the docs. Nothing separate travels.
      uni.uPulseW.value = 0.3; uni.uPulseTail.value = 1.0; uni.uPulseFade.value = 20; uni.uPulseSwell.value = 0.6;
      const tags = c => (c.tags || []);
      for (const c of data.cells) {
        const tg = tags(c).join(" "), isGlia = c.role === "glia", isInter = /interneuron/.test(tg);
        const layer = (tags(c).find(t => /^L\d$|^WM$|^Layer/.test(t)) || "").replace("Layer ", "L");
        const type = isGlia ? (/astro/i.test(tg) ? "astrocyte" : (/oligo/i.test(tg) ? "oligodendrocyte" : "glia")) : (isInter ? (layer + " interneuron").trim() : (layer + " pyramidal").trim());
        if (c.mesh) {
          const m = c.mesh, g = new THREE.InstancedBufferGeometry();
          g.setAttribute("position", new THREE.BufferAttribute(m.pos, 3));
          g.setIndex(new THREE.BufferAttribute(m.idx, 1));
          g.computeVertexNormals();
          g.setAttribute("aNrm", g.getAttribute("normal")); g.deleteAttribute("normal");
          g.setAttribute("aOff", new THREE.BufferAttribute(new Float32Array(m.nv * 3), 3));
          g.setAttribute("aR", new THREE.BufferAttribute(new Float32Array(m.nv), 1));
          g.setAttribute("aKind", new THREE.BufferAttribute(Float32Array.from(m.kind), 1));
          g.setAttribute("aDist", new THREE.BufferAttribute(m.dist, 1));
          g.setAttribute("aArrive", new THREE.BufferAttribute(m.arrive, 1));
          const tier = c.role === "focus" || c.role === "hero" ? "hero" : (isGlia ? "glia" : "mid");
          const A = oneInstance(g, c.role === "focus" ? 1 : (tier === "hero" ? 0.8 : (isGlia ? 0.5 : 0.55)), isGlia ? 2 : (isInter ? 1 : 0));
          const mesh = new THREE.Mesh(g, matCell); mesh.frustumCulled = false; mesh.name = "nr-h01-" + c.role + "-" + c.id;
          scene.add(mesh); meshes.push(mesh);
          cells.push({ tier, type, A, j: 0, geom: g, pos: c.soma.slice(), tri: m.nf, triNoSpines: m.nf, spines: 0, h01: c, glia: isGlia });
          counts.triangles += m.nf; counts.drawCalls++; if (tier === "hero") counts.heroCells++;
          if (c.syn && !isGlia) { const pts = synPoints(c); scene.add(pts); meshes.push(pts); synMeshes.push({ pts, cell: cells[cells.length - 1] }); counts.boutons += c.syn.npre; counts.drawCalls++; }
        } else if (c.skel) {                                       // the far tier: the real skeleton as lines
          const Lk = skelLines(c.skel, 0.4, isInter ? 1 : 0, "nr-h01-far-" + c.id);
          cells.push({ tier: "far", type, A: Lk.A, j: 0, geom: Lk.geom, pos: c.soma.slice(), h01: c });
        }
        if (c.mesh && c.askel && !isGlia) {                        // focus / hero: the axon's own skeleton as a thin tube along the mesh's axon (which is a
          const Tk = skelTubes(c.askel, c.role === "focus" ? 0.9 : 0.7, isInter ? 1 : 0, "nr-h01-axon-" + c.id, 0.35);   // pixel wide and decimated):
          if (Tk) { const rec = cells[cells.length - 1]; rec.extra = (rec.extra || []).concat([Tk.A]); rec.tri += Tk.tri; }   // the pulse lights it node to node
        }
        counts.dendUm += c.dendUm || 0;
      }
      counts.myelinUm = data.cells.reduce((a, c) => a + (c.myelinatedUm || 0), 0);
      // the real EM image behind the block (a slice through the focus soma, drawn at the slab's back face)
      const em = data.em, zBack = Math.min(...data.cells.filter(c => c.bbox).map(c => c.bbox[0][2])) - 8;
      const tex = new THREE.TextureLoader().load(em.url); tex.minFilter = THREE.LinearMipmapLinearFilter; tex.generateMipmaps = true;
      tex.wrapS = tex.wrapT = THREE.MirroredRepeatWrapping;        // the crop (~200 um) is mirrored 3x3 to fill the field behind the block
      uni.tEm.value = tex;
      const pg = new THREE.PlaneGeometry(em.um * 9, em.um * 9); const uv = pg.getAttribute("uv"); for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i) * 9, uv.getY(i) * 9);
      emPlane = new THREE.Mesh(pg, matEm); emPlane.position.set(em.centre[0], em.centre[1], zBack);
      emPlane.frustumCulled = false; emPlane.name = "nr-em"; scene.add(emPlane); meshes.push(emPlane); counts.drawCalls++;
      // the focus cell first in the slot mapping; glia never spike
      cells.sort((a, b) => (a.h01.role === "focus" ? -1 : 0) - (b.h01.role === "focus" ? -1 : 0));
      S.focus = 0;
      finish();
    }
    function buildProcedural() {
      uni.uPulseW.value = 0.09; uni.uPulseTail.value = 0; uni.uPulseFade.value = 8; uni.uPulseSwell.value = 0;
      const rnd = mulberry(880 + Object.keys(KINDS).indexOf(kind) + (L === LOD.phone ? 7 : 0));
      const split = n => Kd.types.map(([t, f]) => [t, Math.max(0, Math.round(n * f))]);
      const want = { hero: split(L.hero), mid: split(L.mid), far: split(L.far) };
      // the hero tier: one mesh per cell (its own spines and boutons), the focus cell first
      let seed = 1;
      for (const [type, n] of want.hero) for (let j = 0; j < n; j++) {
        const G = cellGeometry(THREE, CELLS.cells[type], TYPES[type], "hero", L, seed++);
        const A = instAttrs(G.geom, 1, rnd, kind, type, "hero");
        const idx = cells.length;
        A.off.set(place(kind, type, "hero", idx, L.hero, rnd), 0); G.geom.getAttribute("iOff").needsUpdate = true;
        A.col[0] = TYPES[type].col; G.geom.getAttribute("iCol").needsUpdate = true;
        A.br[0] = idx === 0 ? 1 : 0.72; G.geom.getAttribute("iBright").needsUpdate = true;        // the focus cell brightest
        const mesh = new THREE.Mesh(G.geom, matCell); mesh.frustumCulled = false; mesh.name = "nr-hero-" + type;
        scene.add(mesh); meshes.push(mesh);
        cells.push({ tier: "hero", type, A, j: 0, geom: G.geom, pos: Array.from(A.off), spines: G.spines, tri: G.tri, triNoSpines: G.triNoSpines });
        counts.triangles += G.tri; counts.spines += G.spines; counts.boutons += G.boutons; counts.nodes += G.nodes; counts.drawCalls++;
        counts.spineUm += G.spineUm; counts.dendUm += G.dendUm; counts.heroCells++;
      }
      // the mid tier: one instanced mesh per type
      for (const [type, n] of want.mid) { if (!n) continue;
        const G = cellGeometry(THREE, CELLS.cells[type], TYPES[type], "mid", L, seed++);
        const A = instAttrs(G.geom, n, rnd, kind, type, "mid");
        const mesh = new THREE.Mesh(G.geom, matCell); mesh.frustumCulled = false; mesh.name = "nr-mid-" + type;
        scene.add(mesh); meshes.push(mesh); sets.push({ geom: G.geom, A, n, tri: G.tri, type, tier: "mid" });
        for (let j = 0; j < n; j++) cells.push({ tier: "mid", type, A, j, geom: G.geom, pos: Array.from(A.off.slice(3 * j, 3 * j + 3)) });
        counts.triangles += G.tri * n; counts.drawCalls++;
      }
      // nuclei of hero + mid cells: one instanced icosphere
      { const B = new Builder();
        B.sphere([0, 0, 0], () => 1, 1, K.NUCLEUS, 0, -1); B.sphere([0.25, 0.1, 0.15], () => 0.28, 0, K.NUCLEOLUS, 0, -1);
        const g = B.geometry(THREE), n = cells.length;
        const off = new Float32Array(n * 3), quat = new Float32Array(n * 4), sc = new Float32Array(n), spk = new Float32Array(n).fill(-1e4), col = new Float32Array(n);
        cells.forEach((c, i) => { off.set(c.pos, 3 * i); quat.set(c.A.quat.slice(4 * c.j, 4 * c.j + 4), 4 * i); sc[i] = CELLS.cells[c.type].soma_r * 0.6 * c.A.sc[c.j]; col[i] = c.A.col[c.j]; });
        g.setAttribute("iOff", new THREE.InstancedBufferAttribute(off, 3)); g.setAttribute("iQuat", new THREE.InstancedBufferAttribute(quat, 4));
        g.setAttribute("iScale", new THREE.InstancedBufferAttribute(sc, 1)); g.setAttribute("iSpike", new THREE.InstancedBufferAttribute(spk, 1));
        g.setAttribute("iCol", new THREE.InstancedBufferAttribute(col, 1)); g.instanceCount = n;
        const br = new Float32Array(n); cells.forEach((c, i) => { br[i] = c.A.br[c.j]; }); g.setAttribute("iBright", new THREE.InstancedBufferAttribute(br, 1));
        const mesh = new THREE.Mesh(g, matNuc); mesh.frustumCulled = false; mesh.renderOrder = 2; mesh.name = "nr-nuclei";
        scene.add(mesh); meshes.push(mesh); nucSet = { geom: g, n };
        counts.triangles += (B.idx.length / 3) * n; counts.nucTri = (B.idx.length / 3) * n; counts.drawCalls++; }
      // the far tier: thin lines, one instanced draw call per type
      for (const [type, n] of want.far) { if (!n) continue;
        const G = lineGeometry(THREE, CELLS.cells[type], TYPES[type], 2);
        const A = instAttrs(G.geom, n, rnd, kind, type, "far");
        const lines = new THREE.LineSegments(G.geom, matLine); lines.frustumCulled = false; lines.renderOrder = 1; lines.name = "nr-far-" + type;
        scene.add(lines); meshes.push(lines); sets.push({ geom: G.geom, A, n, tri: 0, type, tier: "far" });
        for (let j = 0; j < n; j++) cells.push({ tier: "far", type, A, j, geom: G.geom, pos: Array.from(A.off.slice(3 * j, 3 * j + 3)) });
        counts.lines += G.segments * n; counts.drawCalls++;
      }
      // the out-of-focus tissue: faint neurite streaks far behind and around (no counterstain blobs since #99: they read as dots)
      { const n = L.bg, pos = new Float32Array(n * 3), size = new Float32Array(n), ang = new Float32Array(n), kd = new Float32Array(n);
        for (let i = 0; i < n; i++) {
          pos[3 * i] = (rnd() - 0.5) * 2600; pos[3 * i + 1] = kind === "cortex" ? -1000 + 1100 * rnd() : (rnd() - 0.5) * 1200; pos[3 * i + 2] = -150 - 1100 * rnd();
          size[i] = 30 + 70 * rnd(); ang[i] = rnd() * 3.1416; kd[i] = 0; }
        const g = new THREE.BufferGeometry();
        g.setAttribute("position", new THREE.BufferAttribute(pos, 3)); g.setAttribute("aSize", new THREE.BufferAttribute(size, 1));
        g.setAttribute("aAngle", new THREE.BufferAttribute(ang, 1)); g.setAttribute("aKind", new THREE.BufferAttribute(kd, 1));
        // dot-ok: elongated out-of-focus neurite streaks (an oriented sprite each, never a round dot), the blurred tissue behind the cells
        bgPoints = new THREE.Points(g, matBg); bgPoints.frustumCulled = false; bgPoints.renderOrder = 0; bgPoints.name = "nr-tissue";
        scene.add(bgPoints); meshes.push(bgPoints); counts.drawCalls++; }
      // the triangle cap: fewer mid cells, then fewer spines on the last hero cells (the focus cell keeps its own)
      { const heroes = cells.filter(c => c.tier === "hero"), mids = sets.filter(T => T.tier === "mid");
        const bud = budget(L, heroes.map(c => ({ tri: c.tri, triNoSpines: c.triNoSpines })), mids.map(T => ({ tri: T.tri, n: T.geom.instanceCount })), counts.nucTri);
        mids.forEach((T, i) => { T.geom.instanceCount = bud.midN[i]; });
        heroes.forEach((c, i) => { if (bud.keep[i] < c.tri) { c.geom.setDrawRange(0, bud.keep[i] * 3); const dropped = Math.round((c.tri - bud.keep[i]) / 10); counts.spines -= dropped; c.spines -= dropped; } });
        counts.triangles = bud.total; }
      finish();
    }
    // camera: orbit around the focus cell; drag turns, wheel / pinch zooms; zooming out past the block closes
    const cam = { theta: 0.35, phi: 1.25, dist: 1000, dist0: 1000, target: [0, 0, 0] };
    function fit() {
      cam.target = toWorld(focusPos);
      cam.dist = cam.dist0 = (L.field / 2) / Math.tan(camera.fov * Math.PI / 360);
      if (S.entry && !S.entry.on) { S.entry.on = true; S.entry.t0 = performance.now(); cam.dist = cam.dist0 * S.entry.from; }
      if (o.cameraDir && o.cameraDir.length === 3) { const d = o.cameraDir; cam.theta = Math.atan2(-d[0], -d[2]); cam.phi = Math.acos(Math.max(-1, Math.min(1, -d[1]))); }
      camera.near = Math.max(1, cam.dist * 0.02); camera.far = cam.dist * 12; camera.updateProjectionMatrix();
    }
    function placeCamera() {
      const t = cam.target, sp = Math.sin(cam.phi), x = t[0] + cam.dist * sp * Math.sin(cam.theta), y = t[1] + cam.dist * Math.cos(cam.phi), z = t[2] + cam.dist * sp * Math.cos(cam.theta);
      camera.position.set(x, y, z); camera.lookAt(t[0], t[1], t[2]);
      uni.uDepthK.value = 1 / (cam.dist * 2.5);
      matComp.uniforms.uFocus.value = 1 / 2.5;
      matComp.uniforms.uDofRange.value = 0.45;
    }
    const ptr = new Map(); let pinch0 = 0, dist0 = 0;
    canvas.addEventListener("pointerdown", e => { ptr.set(e.pointerId, [e.clientX, e.clientY]); canvas.setPointerCapture(e.pointerId); S.userTouched = true;
      if (ptr.size === 2) { const a = [...ptr.values()]; pinch0 = Math.hypot(a[0][0] - a[1][0], a[0][1] - a[1][1]); dist0 = cam.dist; } });
    canvas.addEventListener("pointermove", e => { if (!ptr.has(e.pointerId)) return; const p = ptr.get(e.pointerId);
      if (ptr.size === 1) { cam.theta -= (e.clientX - p[0]) * 0.006; cam.phi = Math.max(0.15, Math.min(3.0, cam.phi - (e.clientY - p[1]) * 0.006)); }
      ptr.set(e.pointerId, [e.clientX, e.clientY]);
      if (ptr.size === 2) { const a = [...ptr.values()], d = Math.hypot(a[0][0] - a[1][0], a[0][1] - a[1][1]); if (pinch0 > 0) zoomTo(dist0 * pinch0 / Math.max(1, d)); } });
    const up = e => { ptr.delete(e.pointerId); };
    canvas.addEventListener("pointerup", up); canvas.addEventListener("pointercancel", up);
    canvas.addEventListener("wheel", e => { e.preventDefault(); S.userTouched = true; zoomTo(cam.dist * Math.exp(e.deltaY * 0.0012)); }, { passive: false });
    function zoomTo(d) {
      cam.dist = Math.max(cam.dist0 * 0.12, Math.min(cam.dist0 * 4, d));
      if (cam.dist > cam.dist0 * 3.2 && !S.zoomedOut) { S.zoomedOut = true; if (o.onClose) o.onClose("zoomout"); }
    }
    // style
    function applyStyle() {
      const fl = S.style === "fluorescence", em = S.style === "em", sv = em ? 2 : (fl ? 0 : 1);
      uni.uStyle.value = sv; matComp.uniforms.uStyle.value = sv;
      uni.uNucAlpha.value = fl ? 0.4 : 0.55; uni.uDim.value = fl ? 0.09 : (em ? 0.05 : 0.015);
      matComp.uniforms.uBloom.value = fl ? 0.9 : (em ? 0.15 : 0.4); matBright.uniforms.uTh.value = fl ? 0.45 : 0.7;
      matComp.uniforms.uExposure.value = fl ? 1.25 : 1.0; matComp.uniforms.uDofMax.value = fl ? 0.75 : (em ? 0.3 : 0.6);
      matComp.uniforms.uBg.value.set(em ? 0.012 : (fl ? 0.002 : 0.015), em ? 0.012 : (fl ? 0.006 : 0.018), em ? 0.014 : (fl ? 0.003 : 0.028));
      if (emPlane) emPlane.visible = em;
      if (bgPoints) bgPoints.visible = !em;
      hud.querySelectorAll("button[data-s]").forEach(b => { b.classList.toggle("on", b.dataset.s === S.style); if (b.dataset.s === "render") b.style.display = S.h01 ? "none" : ""; });
      // the 3D-render style of cortex is dense (five full arbors overlap): there, only 3 hero cells and half the mid tier
      if (built && kind === "cortex") {
        const lighter = !fl;
        S.trimTri = 0;
        for (const c of cells) if (c.tier === "hero") { const mesh = meshes.find(m => m.geometry === c.geom); const hide = lighter && cells.indexOf(c) >= 3;
          if (mesh) mesh.visible = !hide; if (hide) S.trimTri += c.tri; }
        for (const T of sets) if (T.tier === "mid") { const full = T.full != null ? T.full : (T.full = T.geom.instanceCount);
          T.geom.instanceCount = lighter ? Math.max(2, Math.round(full * 0.5)) : full; S.trimTri += (full - T.geom.instanceCount) * T.tri; }
      }
    }
    function setStyle(s) { if (s !== "render" && s !== "fluorescence" && s !== "em") return; if (S.style === s) return; S.style = s; applyStyle(); if (o.onInfo) o.onInfo(info()); }
    // size and render targets
    function resize() {
      const w = Math.max(2, container.clientWidth || 300), h = Math.max(2, container.clientHeight || 200), dpr = Math.min(root.devicePixelRatio || 1, L.dpr);
      renderer.setPixelRatio(dpr); renderer.setSize(w, h, false);
      camera.aspect = w / h; camera.updateProjectionMatrix();
      const pw = Math.round(w * dpr), ph = Math.round(h * dpr);
      if (pw === W && ph === H) return;
      W = pw; H = ph;
      for (const rt of [rtScene, rtHalf, rtQ1, rtQ2, rtQ3, rtQ4]) if (rt) rt.dispose();
      rtScene = new THREE.WebGLRenderTarget(W, H, Object.assign({}, rtOpts, { depthBuffer: true }));
      rtHalf = new THREE.WebGLRenderTarget(Math.max(1, W >> 1), Math.max(1, H >> 1), rtOpts);
      rtQ1 = new THREE.WebGLRenderTarget(Math.max(1, W >> 2), Math.max(1, H >> 2), rtOpts);
      rtQ2 = new THREE.WebGLRenderTarget(Math.max(1, W >> 2), Math.max(1, H >> 2), rtOpts);
      rtQ3 = new THREE.WebGLRenderTarget(Math.max(1, W >> 2), Math.max(1, H >> 2), rtOpts);
      rtQ4 = new THREE.WebGLRenderTarget(Math.max(1, W >> 2), Math.max(1, H >> 2), rtOpts);
      uni.uPixK.value = 2 * Math.tan(camera.fov * Math.PI / 360) / H;      // world units per pixel per unit of depth
      uni.uScale.value = H / (2 * Math.tan(camera.fov * Math.PI / 360));
    }
    const pass = (mat, src, dst, setup) => { quad.material = mat; mat.uniforms.tSrc.value = src.texture; if (setup) setup(); renderer.setRenderTarget(dst); renderer.render(quadScene, quadCam); };
    function render(now) {
      resize();
      if (S.entry && S.entry.on) {                                 // the fly-in from B's zoom: ease out, the canvas fades in
        const u = Math.min(1, (now - S.entry.t0) / S.entry.ms), e = 1 - Math.pow(1 - u, 3);
        cam.dist = cam.dist0 * (S.entry.from + (1 - S.entry.from) * e); S.entryFade = Math.min(1, u * 2.5); applyOpacity();
        if (u >= 1) { S.entry.on = false; cam.dist = cam.dist0; S.entryFade = 1; applyOpacity(); if (o.onEntryEnd) o.onEntryEnd(); }
      }
      if (!S.userTouched && !(S.entry && S.entry.on)) cam.theta += 0.00004 * Math.min(50, now - (render.at || now));
      render.at = now;
      placeCamera();
      if (now - (render.barAt || 0) > 400) {                        // the scale bar: a round length that spans 60-160 px at the focus depth
        render.barAt = now; const umPerPx = cam.dist * uni.uPixK.value * (root.devicePixelRatio ? Math.min(root.devicePixelRatio, L.dpr) : 1) / (renderer.getPixelRatio ? renderer.getPixelRatio() : 1);
        let len = 10; for (const Lb of [1, 2, 5, 10, 20, 50, 100, 200, 500]) { len = Lb; if (Lb / umPerPx >= 60) break; }
        const px = len / umPerPx; bar.firstChild.style.width = Math.round(px) + "px"; bar.lastChild.textContent = len + " µm";
      }
      uni.uTime.value = S.clock != null ? S.clock : (now - S.t0) / 1000;
      const live = isLive(now);
      uni.uLive.value += ((live ? 1 : 0) - uni.uLive.value) * 0.08;
      const r = S.rate ? Math.max(0, Math.min(1, (S.rate / 255 - 0.42) / 0.44)) : 0;
      uni.uRate.value += (r - uni.uRate.value) * 0.05;
      renderer.setClearColor(0x000000, 1.0);
      renderer.setRenderTarget(rtScene); renderer.render(scene, camera);
      pass(matDown, rtScene, rtHalf, () => matDown.uniforms.uTexel.value.set(1 / W, 1 / H));
      pass(matDown, rtHalf, rtQ1, () => matDown.uniforms.uTexel.value.set(2 / W, 2 / H));
      const qw = rtQ1.width, qh = rtQ1.height;
      pass(matBlur, rtQ1, rtQ2, () => matBlur.uniforms.uDir.value.set(1 / qw, 0));
      pass(matBlur, rtQ2, rtQ3, () => matBlur.uniforms.uDir.value.set(0, 1 / qh));      // rtQ3: the out-of-focus image
      pass(matBright, rtQ1, rtQ2);                                                       // bloom: bright pass, then two wide blurs
      pass(matBlur, rtQ2, rtQ4, () => matBlur.uniforms.uDir.value.set(1.5 / qw, 0));
      pass(matBlur, rtQ4, rtQ2, () => matBlur.uniforms.uDir.value.set(0, 1.5 / qh));
      pass(matBlur, rtQ2, rtQ4, () => matBlur.uniforms.uDir.value.set(3.5 / qw, 0));
      pass(matBlur, rtQ4, rtQ2, () => matBlur.uniforms.uDir.value.set(0, 3.5 / qh));    // rtQ2: the bloom
      quad.material = matComp; matComp.uniforms.tScene.value = rtScene.texture; matComp.uniforms.tBlur.value = rtQ3.texture; matComp.uniforms.tBloom.value = rtQ2.texture;
      renderer.setRenderTarget(null); renderer.render(quadScene, quadCam);
      if (S.readyResolve) { S.readyResolve(nr); S.readyResolve = null; }
    }
    // loop: nothing drawn while off screen, hidden or closed
    let io = null;
    if ("IntersectionObserver" in root) { io = new root.IntersectionObserver(es => { S.onScreen = es[es.length - 1].isIntersecting; }); io.observe(container); }
    function frame(now) {
      if (S.closed) return;
      root.requestAnimationFrame(frame);
      if (!built || !S.onScreen || root.document.hidden) return;
      const t = performance.now();
      render(now);
      S.jsSum += performance.now() - t; S.frames++;
      if (now - S.fpsAt >= 1000) { S.fps = S.frames * 1000 / (now - S.fpsAt); S.jsMs = S.frames ? S.jsSum / S.frames : 0; S.frames = 0; S.jsSum = 0; S.fpsAt = now;
        const i = info(); const txt = `${i.cells} cells · ${(i.triangles / 1000).toFixed(0)}k triangles · ${i.live ? "live" : "offline: static"}` + (DEBUG ? ` · ${i.fps.toFixed(0)} fps` : "");
        if (stat.textContent !== txt) stat.textContent = txt; }
    }
    root.requestAnimationFrame(frame);
    // activity
    const clock = now => (now - S.t0) / 1000;
    const isLive = now => !S.forcedOffline && (now || performance.now()) - S.lastWall < LIVE_MS;
    const spikable = () => cells.filter(c => !c.glia);
    function spikeCell(k, t) {
      const c = spikable()[k]; if (!c) return;
      c.A.spk[c.j] = t; c.A.sa.needsUpdate = true; S.spikes++;
      for (const a of c.extra || []) { a.spk[0] = t; a.sa.needsUpdate = true; }   // the cell's axon skeleton line (H01 focus / hero cells)
      for (const sm of synMeshes) if (sm.cell === c) sm.pts.material.uniforms.uSpike.value = t;
    }
    function spike(slot, delayMs) { const n = spikable().length; if (!n) return; const k = Math.min(n - 1, Math.floor((slot || 0) * n / 256)); S.spikeAt = clock(performance.now()) + (delayMs || 0) / 1000; spikeCell(k, S.spikeAt); }
    function rates(rq) { if (typeof rq === "number") S.rate = rq; else if (rq && rq.length > S.region) S.rate = rq[S.region]; }
    function onFrame(m) {
      if (!m || m.type !== "spiking" || !m.n3 || m.live === false) return;
      const now = performance.now(), gap = now - S.prev; S.prev = now;
      if (gap > 30 && gap < 2000) S.gap = 0.7 * S.gap + 0.3 * gap;
      S.lastWall = now; S.forcedOffline = false;
      if (m.n3.rq) { const q = unb64(m.n3.rq); if (q.length > S.region) S.rate = q[S.region]; }
      else if (o.groupRate) { const hz = o.groupRate(m); if (hz != null) S.rate = rateByte(hz) || S.rate; }
      if (S.clock != null) return;                                 // the clock is held by the test hook (debugTime): no new spikes
      const b = unb64(m.n3.sq), play = Math.min(600, S.gap) / 1000, t = clock(now);
      const n = spikable().length;
      for (let i = 0; i + 2 < b.length; i += 3) { if (b[i] !== S.region || !n) continue;
        spikeCell(Math.min(n - 1, Math.floor(b[i + 1] * n / 256)), t + (b[i + 2] / 255) * play); }
    }
    function setLive(on) { if (on) { S.lastWall = performance.now(); S.forcedOffline = false; } else S.forcedOffline = true; }
    // test hook: freeze the renderer's clock at `seconds` after the last spike() (null: wall clock). Screenshots under
    // software WebGL take seconds each; the action-potential strip is taken at fixed clock times with it.
    function debugTime(seconds) { S.clock = seconds == null ? null : S.spikeAt + seconds; }
    const nf = x => (x || 0).toLocaleString("en-US");
    function info() {
      const types = {}; for (const c of cells) types[c.type] = (types[c.type] || 0) + 1;
      if (S.h01) {
        const d = NR.h01.describe(S.h01), f = S.h01.cells.find(c => c.role === "focus");
        return { kind, region: S.region, label: S.label, style: S.style, lod: lodOf(), source: "H01", cells: cells.length, heroCells: counts.heroCells,
          triangles: counts.triangles, triangleCap: L.cap, lineSegments: counts.lines, spines: "real (in the meshes)", boutons: counts.boutons,
          synapsesPre: d.synapsesPre, synapsesPost: d.synapsesPost, myelinatedUm: d.myelinatedUm, glia: d.glia, far: d.far, bytes: d.bytes,
          ids: S.h01.cells.map(c => c.id), focusId: f ? f.id : null, focusClasses: f ? f.classes : null, em: { um: S.h01.em.um, nmPerPx: S.h01.em.nm_per_px },
          drawCalls: counts.drawCalls, live: isLive(), spikes: S.spikes, fps: S.fps, jsMs: S.jsMs, offScreen: !S.onScreen, slowdown: SLOWDOWN,
          halfFloat: halfOk, webgl2: isGL2, worldPos: S.worldPos, normal: S.normal, cite: H01_CITE, license: "CC BY 4.0",
          dendUm: Math.round(S.h01.cells.reduce((a, c) => a + (c.dendUm || 0), 0)),
          // two ready-made lines for the page's panel (index.html prints them as they are): what is drawn, and where it comes from
          detailLine: `${cells.length} real cells, ${counts.heroCells} proofread in full detail` + (d.glia ? ` and ${d.glia} glia` : "") +
            `: spines as reconstructed, ${nf(d.synapsesPre)} presynaptic and ${nf(d.synapsesPost)} incoming synapses at their real positions, ` +
            `${nf(d.myelinatedUm)} µm of axon H01 labels as myelinated · ${nf(Math.round(counts.triangles / 1000))}k of ${nf(Math.round(L.cap / 1000))}k triangles (${lodOf()}) · ${S.style}`,
          sourceLine: `H01 electron-microscopy reconstructions of human temporal cortex (Shapson-Coe et al. 2024; cells ${S.h01.cells.slice(0, 3).map(c => c.id).join(", ")}` +
            (S.h01.cells.length > 3 ? ` + ${S.h01.cells.length - 3} more` : "") + `), CC BY 4.0, decimated and moved closer together; glia from the automated segmentation, not proofread · credits on /about`,
          types: Object.keys(types).map(t => ({ type: t, n: types[t], species: "human", id: "H01", dataset: /astro|oligo|glia/.test(t) ? "H01 c3 segmentation (automated)" : "H01 proofread cells" })) };
      }
      return { kind, region: S.region, label: S.label, style: S.style, lod: lodOf(), source: "NeuroMorpho", cells: cells.length, heroCells: counts.heroCells,
        triangles: counts.triangles - S.trimTri, triangleCap: L.cap, lineSegments: counts.lines, spines: counts.spines, spineUm: Math.round(counts.spineUm), dendUm: Math.round(counts.dendUm),
        boutons: counts.boutons, nodesOfRanvier: counts.nodes, drawCalls: counts.drawCalls, live: isLive(), spikes: S.spikes, fps: S.fps, jsMs: S.jsMs,
        offScreen: !S.onScreen, slowdown: SLOWDOWN, halfFloat: halfOk, webgl2: isGL2, worldPos: S.worldPos, normal: S.normal,
        detailLine: `${cells.length} cells, ${counts.heroCells} in full detail: ${nf(counts.spines)} spines on ${nf(Math.round(counts.spineUm))} of ${nf(Math.round(counts.dendUm))} µm of dendrite, ` +
          `${nf(counts.boutons)} boutons, ${nf(counts.nodes)} nodes of Ranvier · ${nf(Math.round((counts.triangles - S.trimTri) / 1000))}k of ${nf(Math.round(L.cap / 1000))}k triangles (${lodOf()}) · ${S.style}`,
        sourceLine: `NeuroMorpho.Org reconstructions (${Object.keys(types).map(t => CELLS.cells[t].nmo_id).join(", ")}), CC BY 4.0, simplified; thickness from their radii, spines, myelin and boutons from published values · credits on /about`,
        types: Object.keys(types).map(t => ({ type: t, n: types[t], species: CELLS.cells[t].species, id: CELLS.cells[t].nmo_id, radii: CELLS.cells[t].radii, myelinated: !!TYPES[t].myelin, spines: TYPES[t].spines })) };
    }
    function caption() {
      const i = info();
      if (S.h01) return CAPTION + ` This close-up: ${i.cells} real cells of human temporal cortex from H01 (${i.heroCells} proofread cells in full detail` +
        (i.glia ? `, ${i.glia} glia from the automated segmentation` : "") + `), with their own spines, ${i.synapsesPre.toLocaleString("en-US")} presynaptic and ` +
        `${i.synapsesPost.toLocaleString("en-US")} incoming synapses at their real positions, and ${i.myelinatedUm} µm of axon H01 labels as myelinated; a real EM slice behind. ` +
        `Pulses slowed ${SLOWDOWN}× along the real axons.` + (i.live ? " Each cell stands for a sampled model neuron of this region; every flash is a recorded spike." : " No live network: static cells, no activity.");
      const my = i.types.filter(t => t.myelinated).map(t => t.type);
      return CAPTION_PROCEDURAL + ` Pulses slowed ${SLOWDOWN}×` + (my.length ? ", hopping node to node on myelinated axons" : "") + "." +
        (i.live ? " Each cell stands for a sampled model neuron of this region; every flash is a recorded spike." : " No live network: static cells, no activity.");
    }
    function close() {
      if (S.closed) return; S.closed = true;
      if (io) io.disconnect();
      for (const m of meshes) { scene.remove(m); m.geometry.dispose(); }
      for (const m of [matCell, matNuc, matLine, matBg, matEm, matDown, matBlur, matBright, matComp]) m.dispose();
      for (const sm of synMeshes) sm.pts.material.dispose();
      if (uni.tEm.value) uni.tEm.value.dispose();
      quad.geometry.dispose();
      for (const rt of [rtScene, rtHalf, rtQ1, rtQ2, rtQ3, rtQ4]) if (rt) rt.dispose();
      renderer.dispose();
      for (const el of [canvas, hud, stat, bar]) if (el.parentNode) el.parentNode.removeChild(el);
    }
    const ready = new Promise(res => { S.readyResolve = res; });
    const nr = { onFrame, spike, rates, setLive, debugTime, setStyle, style: () => S.style, setLod: l => { if (LOD[l] || l === "auto") { S.lodName = l; } }, lod: lodOf, ready,
                 setOpacity: a => { S.opacity = Math.max(0, Math.min(1, Number(a) || 0)); applyOpacity(); }, opacity: () => S.opacity,
                 focus: i => { if (cells[i]) { S.focus = i; focusPos = cells[i].pos; fit(); } }, resize, info, caption, close, scene, camera, renderer, cells };
    load(o.assetUrl).then(() => { if (!S.closed) build(); }).catch(e => { console.error("NeuronRender:", e); });
    return nr;
  }

  // the H01 module (web/neuron_render/h01.js), loaded once, on demand
  function loadH01Module(base) {
    if (NR.h01) return Promise.resolve(NR.h01);
    if (!loadH01Module.p) loadH01Module.p = new Promise((res, rej) => { const sc = root.document.createElement("script"); sc.src = (base || "neuron_render/") + "h01.js";
        sc.onload = () => NR.h01 ? res(NR.h01) : rej(new Error("h01.js")); sc.onerror = () => rej(new Error("h01.js")); root.document.head.appendChild(sc); })
      .catch(e => { loadH01Module.p = null; throw e; });
    return loadH01Module.p;
  }
  // B's zoom: start fetching a region set (h01.js, the cells, the EM slice) while B's camera is still flying; the later open() finds it
  // in the cache. Resolves to the decoded set, or null where there is no H01 set / no DecompressionStream (then open() draws NeuroMorpho).
  function prefetch(o) {
    o = o || {}; const set = H01_SETS[o.kind || "cortex"];
    if (!set || typeof root.DecompressionStream !== "function") return Promise.resolve(null);
    const lodName = o.lod === "phone" || o.lod === "desktop" ? o.lod : ((root.innerWidth || 1000) < 700 ? "phone" : "desktop");
    return loadH01Module(o.base).then(h => h.load(set, lodName, o.base ? o.base + "h01/" : undefined))
      .then(d => { if (root.Image) { const im = new root.Image(); im.src = d.em.url; } return d; });
  }
  // open() + B's zoom end: worldPos (bookkeeping), normal (the outward cortical normal: the block's +y, toward the pia, is turned onto it),
  // cameraDir / cameraUp (B's camera at the cut, in B's world), entry {ms, from} (the fly-in). See the API doc.
  function openAt(container, o) { return open(container, o); }
  // the cortex block's extent, readable before open(): the union of the H01 cells' bounding boxes in the block frame (h01/cortex.json),
  // µm; +y toward the pia; the focus soma (L2 pyramidal 1874244336) at the origin. depthUm: how deep below the pia the block's top and
  // bottom lie, estimated from H01's soma table (the highest layer-1 somata of this column sit ~780 µm above the focus soma): ± ~100 µm.
  const BLOCK = { set: "cortex", dataset: "H01", um: [2202, 827, 174], min: [-1084, -431, -145], max: [1118, 396, 29], pia: "+y", focusUm: [0, 0, 0],
                  focusDepthUm: 800, depthUm: [400, 1230], depthApprox: true };
  const NR = { open, openAt, prefetch, load, kindOf, plan, cellGeometry, lineGeometry, budget, rateByte, Builder, TYPES, KINDS, LOD, SLOWDOWN, CAPTION, CAPTION_PROCEDURAL,
               H01_SETS, H01_CITE, BLOCK, K, CELLS: null, h01: null };
  root.NeuronRender = NR;
})(typeof window !== "undefined" ? window : globalThis);
