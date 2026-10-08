// Node check of web/neuron_render/neuron_render.js (#88 A) with a minimal THREE stub (no WebGL): run by
// tests/test_neuron_render.py. Prints one JSON line: per cell type the plan (arrival times, myelin, boutons, spines)
// and the geometry counts per tier, the triangle budget at both levels of detail, the constants and the caption.
"use strict";
const path = require("path"), fs = require("fs");
const root = path.resolve(__dirname, "..", "..");
globalThis.performance = globalThis.performance || require("perf_hooks").performance;
require(path.join(root, "web", "neuron_render", "neuron_render.js"));
const NR = globalThis.NeuronRender;
class Attr { constructor(a, n) { this.array = a; this.itemSize = n; this.count = a.length / n; this.needsUpdate = false; } setUsage() { return this; } }
class Geom { constructor() { this.attributes = {}; this.instanceCount = 0; } setAttribute(k, a) { this.attributes[k] = a; } getAttribute(k) { return this.attributes[k]; }
  setIndex(a) { this.index = a; } setDrawRange(a, b) { this.drawRange = [a, b]; } dispose() {} }
const THREE = { InstancedBufferGeometry: Geom, BufferGeometry: Geom, BufferAttribute: Attr, InstancedBufferAttribute: Attr };
const cells = JSON.parse(fs.readFileSync(path.join(root, "web", "neuron_render", "cells.json"), "utf8"));
const out = { types: {}, lod: {}, constants: { slowdown: NR.SLOWDOWN, caption: NR.CAPTION, caption_procedural: NR.CAPTION_PROCEDURAL, kinds: Object.keys(NR.KINDS), lods: Object.keys(NR.LOD) },
  kindOf: ["LH_Vis_1", "Left Putamen", "Right Thalamus", "Left Pallidum", "Left Hippocampus", "Right Amygdala"].map(n => NR.kindOf({ name: n })) };
for (const [t, c] of Object.entries(cells.cells)) {
  const T = NR.TYPES[t], P = NR.plan(c, T);
  const ax = P.paths.filter(p => p.k === 1), de = P.paths.filter(p => p.k !== 1);
  let monotone = true, myBeforeAis = 0, myUm = 0, axonUm = 0, tMax = 0, nodes = 0;
  for (const p of ax) for (let i = 1; i < p.nodes.length; i++) { const a = p.nodes[i - 1], b = p.nodes[i];
    if (b.t < a.t - 1e-9 || b.d < a.d - 1e-9) monotone = false;
    if (a.my) { myUm += b.d - a.d; if (a.d < T.myelin.ais - 1e-6) myBeforeAis++; }
    axonUm += b.d - a.d; tMax = Math.max(tMax, b.t); nodes++; }
  const dendT = de.every(p => p.nodes.every(n => n.t === -1 && !n.my));
  const boutonsOk = P.boutons.every(b => b.d >= (T.myelin ? T.myelin.ais : 10) - 1e-6 && b.t >= 0);
  const geo = {};
  for (const lod of ["phone", "desktop"]) {
    const H = NR.cellGeometry(THREE, c, T, "hero", NR.LOD[lod], 1), M = NR.cellGeometry(THREE, c, T, "mid", NR.LOD[lod], 2), Ln = NR.lineGeometry(THREE, c, T, 2);
    const kinds = Array.from(H.geom.getAttribute("aKind").array), uniq = [...new Set(kinds)].sort();
    let idxMax = 0; for (const i of H.geom.index.array) if (i > idxMax) idxMax = i;
    const nVert = H.geom.getAttribute("position").count;
    geo[lod] = { hero_tri: H.tri, hero_tri_no_spines: H.triNoSpines, spines: H.spines, spine_um: Math.round(H.spineUm), dend_um: Math.round(H.dendUm),
      spine_density: H.spineUm > 0 ? +(H.spines / H.spineUm).toFixed(2) : 0, boutons: H.boutons, ranvier: H.nodes, kinds: uniq, index_ok: idxMax < nVert,
      mid_tri: M.tri, mid_spines: M.spines, line_segments: Ln.segments, spine_tri_cap: NR.LOD[lod].spineTri };
  }
  out.types[t] = { nmo_id: c.nmo_id, radii: c.radii, myelinated_type: !!T.myelin, n_nodes: c.n_nodes, paths: P.paths.length, axon_paths: ax.length,
    monotone, dendrites_passive: dendT, myelin_before_ais: myBeforeAis, myelin_um: Math.round(myUm), axon_um: Math.round(axonUm), ranvier: P.gaps,
    boutons: P.boutons.length, boutons_ok: boutonsOk, t_max_s: +tMax.toFixed(2), spines_per_um: T.spines, geo };
}
// the planner's triangle budget per kind and LOD (as build() applies it: cells per tier from the LOD table)
for (const lod of ["phone", "desktop"]) {
  const L = NR.LOD[lod]; out.lod[lod] = { cap: L.cap };
  for (const [kind, Kd] of Object.entries(NR.KINDS)) {
    const split = n => Kd.types.map(([t, f]) => [t, Math.max(0, Math.round(n * f))]);
    const hero = [], mids = [];
    for (const [t, n] of split(L.hero)) for (let j = 0; j < n; j++) { const G = out.types[t].geo[lod]; hero.push({ tri: G.hero_tri, triNoSpines: G.hero_tri_no_spines }); }
    for (const [t, n] of split(L.mid)) if (n) mids.push({ tri: out.types[t].geo[lod].mid_tri, n });
    const nucTri = (80 + 20) * (hero.length + mids.reduce((a, m) => a + m.n, 0));
    const before = hero.reduce((a, h) => a + h.tri, 0) + mids.reduce((a, m) => a + m.tri * m.n, 0) + nucTri;
    const b = NR.budget(L, hero, mids, nucTri);
    out.lod[lod][kind] = { triangles_before: before, triangles: b.total, mid_cells: b.midN, hero_keep: b.keep, focus_keeps_spines: b.keep[0] === hero[0].tri,
      cells: hero.length + b.midN.reduce((a, x) => a + x, 0) + split(L.far).reduce((a, [, n]) => a + n, 0) };
  }
}
console.log(JSON.stringify(out));
