// Node check of the whole-brain neuron forest in web/neurons3d.js (#88 B) with a minimal THREE stub (no WebGL): run by
// tests/test_neuron_forest.py. Prints one JSON line: what the page would draw, how the cells are turned, what a frame changes.
"use strict";
const path = require("path"), fs = require("fs");
const root = path.resolve(__dirname, "..", "..");
globalThis.performance = globalThis.performance || require("perf_hooks").performance;
require(path.join(root, "web", "neurons3d.js"));
const N = globalThis.Neurons3D;
class Attr { constructor(a, n) { this.array = a; this.itemSize = n; this.needsUpdate = false; } setUsage() { return this; } }
class Geom { constructor() { this.attributes = {}; this.instanceCount = 0; } setAttribute(k, a) { this.attributes[k] = a; return this; }
  getAttribute(k) { return this.attributes[k]; } dispose() {} }
class Obj { constructor(g, m) { this.geometry = g; this.material = m; this.children = []; this.visible = true; } add(c) { this.children.push(c); } remove() {} }
const THREE = { Group: Obj, Scene: Obj, LineSegments: Obj, Points: Obj, Mesh: Obj, InstancedBufferGeometry: Geom, BufferGeometry: Geom, BufferAttribute: Attr,
  InstancedBufferAttribute: Attr, DataTexture: class { constructor(d) { this.image = { data: d }; } dispose() {} }, RGBAFormat: 1023,
  ShaderMaterial: class { constructor(o) { Object.assign(this, o); } dispose() {} }, AdditiveBlending: 2, DynamicDrawUsage: 35048,
  Vector3: class { constructor(x, y, z) { this.x = x; this.y = y; this.z = z; } } };
const web = f => path.join(root, "web", f);
const morph = JSON.parse(fs.readFileSync(web("neurons_morph.json"), "utf8"));
const nodes = JSON.parse(fs.readFileSync(web("brain.json"), "utf8")).nodes;
const sizes = JSON.parse(fs.readFileSync(web("neurons3d.json"), "utf8")).sizes;
const buf = f => { const b = fs.readFileSync(web(f)); return b.buffer.slice(b.byteOffset, b.byteOffset + b.length); };
const cortex = new Float32Array(buf("cortex.bin")), cortexIdx = new Uint32Array(buf("cortex_idx.bin"));
const b64 = bytes => Buffer.from(Uint8Array.from(bytes)).toString("base64");
const out = { simplified: {} };
for (const [t, c] of Object.entries(morph.cells)) {
  const s = N.simplify(c, N.FOREST_SEG, 400), k = { axon: 0, dendrite: 0 };
  for (let i = 0; i < s.n; i++) k[s.kind[2 * i] === 1 ? "axon" : "dendrite"]++;
  out.simplified[t] = { segments: s.n, ...k };
}
// outward normals: the share pointing away from their hemisphere's centre
const nrm = N.cortexNormals(cortex, cortexIdx);
let outward = 0; const nv = cortex.length / 3, ctr = [[0, 0, 0, 0], [0, 0, 0, 0]];
for (let v = 0; v < nv; v++) { const h = ctr[cortex[3 * v] < 0 ? 0 : 1]; for (let a = 0; a < 3; a++) h[a] += cortex[3 * v + a]; h[3]++; }
for (const h of ctr) for (let a = 0; a < 3; a++) h[a] /= h[3];
for (let v = 0; v < nv; v++) { const h = ctr[cortex[3 * v] < 0 ? 0 : 1]; let d = 0; for (let a = 0; a < 3; a++) d += nrm[3 * v + a] * (cortex[3 * v + a] - h[a]); if (d > 0) outward++; }
out.normals_outward_frac = outward / nv;
out.normals_sample = []; for (let v = 0; v < nv; v += 25) out.normals_sample.push(v, +nrm[3 * v].toFixed(4), +nrm[3 * v + 1].toFixed(4), +nrm[3 * v + 2].toFixed(4));
for (const [tag, maxCells] of [["desktop", 600], ["phone", 300], ["mini", 240]]) {
  const scene = new Obj(), t0 = performance.now();
  const n3 = N.create({ THREE, scene, nodes, cortex, cortexIdx, morph, sizes, maxCells });
  const build = performance.now() - t0, st = n3.state();
  const draw = scene.children[0].children;
  const r = { cells: st.cells, shaped: st.shaped, segments: st.segments, drawCalls: draw.length, state_drawCalls: st.drawCalls,
              build_ms: Math.round(build), enlarge: st.enlarge, types: st.types,
              max_segments_per_cell: Math.max(...draw.filter(d => d.geometry.instanceCount).map(d => d.geometry.getAttribute("position").array.length / 6)) };
  if (tag === "desktop") {
    // orientation: pyramidal apical axis vs the surface normal at its vertex; others: spread of directions
    let pyr = 0, aligned = 0, minDot = 2; const dirs = {};
    for (let j = 0; j < st.cells; j++) { const c = n3.cell(j); if (!c.type) continue;
      if (c.type === "pyramidal" && c.normal) { pyr++; const d = c.up[0] * c.normal[0] + c.up[1] * c.normal[1] + c.up[2] * c.normal[2];
        minDot = Math.min(minDot, d); if (d > 0.999) aligned++; }
      else (dirs[c.type] = dirs[c.type] || []).push(c.up); }
    r.pyramidal_on_cortex = pyr; r.pyramidal_aligned = aligned; r.pyramidal_min_dot = minDot;
    r.spread = Object.fromEntries(Object.entries(dirs).map(([t, v]) => { const m = [0, 1, 2].map(a => v.reduce((s, u) => s + u[a], 0) / v.length);
      return [t, { n: v.length, mean_len: Math.hypot(...m) }]; }));
    // offline: nothing has a spike time, the fade comes up (static cells), uLive stays 0
    n3.setVisible(true);
    for (let i = 0; i < 80; i++) n3.update(performance.now());
    const mats = draw.map(d => d.material), uLive0 = mats[0].uniforms.uLive.value;
    const spiking = () => draw.reduce((a, d) => a + Array.from(d.geometry.getAttribute(d.geometry.attributes.iSpike ? "iSpike" : "aFlash").array).filter(x => x > -1e3).length, 0);
    r.offline = { visible: scene.children[0].visible, fade: mats[0].uniforms.uFade.value, uLive: uLive0, spiking: spiking() };
    // one live frame: 30 spikes in region 12 only
    const sq = []; for (let i = 0; i < 30; i++) sq.push(12, (i * 37) % 256, (i * 11) % 256);
    const rq = new Array(214).fill(120); rq[12] = 230;
    n3.onFrame({ type: "spiking", net: "cpu", n3: { sq: b64(sq), rq: b64(rq), span: 200, ns: 30 } });
    for (let i = 0; i < 80; i++) n3.update(performance.now());
    const regs = new Set();
    for (const d of draw) { const g = d.geometry, sp = g.getAttribute(g.attributes.iSpike ? "iSpike" : "aFlash").array, rg = g.getAttribute(g.attributes.iReg ? "iReg" : "aReg").array;
      for (let i = 0; i < sp.length; i++) if (sp[i] > -1e3) regs.add(rg[i]); }
    r.live = { uLive: mats[0].uniforms.uLive.value, spiking: spiking(), regions: [...regs], uploaded: draw.some(d => (d.geometry.attributes.iSpike || d.geometry.attributes.aFlash).needsUpdate),
               rate_byte_12: n3.rate(12), state_live: n3.state().live };
  }
  out[tag] = r; n3.dispose();
}
console.log(JSON.stringify(out));
