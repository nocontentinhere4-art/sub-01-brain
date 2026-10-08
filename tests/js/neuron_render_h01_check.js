// Node check of the H01 close-up sets (#99): web/neuron_render/h01.js decodes web/neuron_render/h01/cortex.json +
// cortex_<lod>.bin.gz exactly as the page does (fetch + DecompressionStream, stubbed onto local files), and the
// decoded arrays are checked: kinds, path distances, monotone pulse times along the far skeletons, synapses, bytes,
// triangles. Run by tests/test_neuron_render.py. Prints one JSON line.
"use strict";
const path = require("path"), fs = require("fs");
const root = path.resolve(__dirname, "..", "..");
const dir = path.join(root, "web", "neuron_render", "h01");
globalThis.performance = globalThis.performance || require("perf_hooks").performance;
globalThis.fetch = async url => { const p = path.join(dir, path.basename(String(url))); if (!fs.existsSync(p)) return new Response(null, { status: 404 });
  return new Response(fs.readFileSync(p)); };
globalThis.NeuronRender = { K: { SOMA: 0, AXON: 1, BASAL: 2, APICAL: 3, MYELIN: 4, GLIA: 9, SYN_PRE: 10, SYN_POST: 11 } };
require(path.join(root, "web", "neuron_render", "h01.js"));
const H = globalThis.NeuronRender.h01;
(async () => {
  const out = {};
  const manifest = JSON.parse(fs.readFileSync(path.join(dir, "cortex.json"), "utf8"));
  out.manifest = { source: manifest.source, license: manifest.license, cite: manifest.cite, slowdown: manifest.slowdown, pia: manifest.frame.pia,
                   em: manifest.em, lods: Object.keys(manifest.lods) };
  for (const lod of ["desktop", "phone"]) {
    const d = await H.load("cortex", lod, dir + "/");
    const L = manifest.lods[lod], info = H.describe(d);
    const bytes = fs.statSync(path.join(dir, L.file)).size + fs.statSync(path.join(dir, manifest.em.file)).size + fs.statSync(path.join(dir, "cortex.json")).size;
    const r = { cells: d.cells.length, triangles: d.triangles, bytes_total: bytes, describe: info, roles: {}, kinds: {}, bad: [] };
    for (const c of d.cells) {
      r.roles[c.role] = (r.roles[c.role] || 0) + 1;
      if (c.mesh) {
        const m = c.mesh;
        if (m.pos.length !== 3 * m.nv || m.idx.length !== 3 * m.nf) r.bad.push(c.id + " mesh sizes");
        let imax = 0; for (let i = 0; i < m.idx.length; i++) if (m.idx[i] > imax) imax = m.idx[i];
        if (imax >= m.nv) r.bad.push(c.id + " index out of range");
        for (let i = 0; i < m.nv; i++) { const k = m.kind[i]; r.kinds[k] = (r.kinds[k] || 0) + 1;
          if (!(k === 0 || k === 1 || k === 2 || k === 4 || k === 5 || k === 9)) { r.bad.push(c.id + " kind " + k); break; } }
        if (c.role !== "glia") {
          let ax = 0, arr = 0; for (let i = 0; i < m.nv; i++) { if (m.kind[i] === 1 || m.kind[i] === 4 || m.kind[i] === 5) { ax++; if (m.arrive[i] >= 0) arr++; } }
          if (ax && arr / ax < 0.9) r.bad.push(c.id + " axon vertices without a pulse time " + (arr / ax).toFixed(2));
          let dmax = 0; for (let i = 0; i < m.nv; i++) if (m.dist[i] > dmax) dmax = m.dist[i];
          if (dmax < 50) r.bad.push(c.id + " path distances too small " + dmax);
        }
      }
      if (c.syn) {
        if (c.syn.pos.length !== 3 * (c.syn.npre + c.syn.npost)) r.bad.push(c.id + " synapse sizes");
        let ok = 0; for (let i = 0; i < c.syn.npre; i++) if (c.syn.preArrive[i] >= 0) ok++;
        if (c.syn.npre && ok / c.syn.npre < 0.6) r.bad.push(c.id + " presynaptic sites without a pulse time " + (ok / c.syn.npre).toFixed(2));
      }
      if (c.askel) { r.axonSkelNodes = (r.axonSkelNodes || 0) + c.askel.n; let ax = 0; for (let i = 0; i < c.askel.n; i++) if (c.askel.kind[i] === 1 || c.askel.kind[i] === 4 || c.askel.kind[i] === 5) ax++;
        if (ax < 0.9 * c.askel.n) r.bad.push(c.id + " axon skeleton with non-axon nodes " + (ax / c.askel.n).toFixed(2)); }
      if (c.role === "focus" && !c.askel) r.bad.push(c.id + " focus cell without an axon skeleton");
      for (const k of [c.skel, c.askel]) if (k) {
        let back = 0;
        for (let i = 0; i < k.n; i++) { const p = k.parent[i]; if (p < 0) continue;
          if (p >= k.n) { r.bad.push(c.id + " parent out of range"); break; }
          if (k.dist[i] + 1e-6 < k.dist[p]) back++;
          if (k.arrive[i] >= 0 && k.arrive[p] >= 0 && k.arrive[i] + 1e-6 < k.arrive[p]) back++; }
        if (back) r.bad.push(c.id + " skeleton not monotone " + back);
      }
    }
    out[lod] = r;
  }
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
