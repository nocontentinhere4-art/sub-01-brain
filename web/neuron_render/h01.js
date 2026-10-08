/* NeuronRender.h01: the real H01 cells for the close-ups (#99). Loaded lazily by neuron_render.js when a close-up
   kind has an H01 set (cortex); decodes web/neuron_render/h01/<set>.json + <set>_<lod>.bin.gz (gzip, through
   DecompressionStream) into typed arrays the renderer turns into geometry.

   H01: Shapson-Coe A, Januszewski M, Berger DR et al. (2024) A petavoxel fragment of human cerebral cortex reconstructed
   at nanoscale resolution. Science 384:eadk4858. CC BY 4.0 (gs://h01-release). The build script
   (web/neuron_render/build/fetch_h01.py) says exactly what was taken and how it was decimated. */
(function (root) {
  "use strict";
  const NR = root.NeuronRender;
  if (!NR) return;
  const cache = {};
  const u16 = (buf, off, n) => new Uint16Array(buf, off, n);
  const dq = (q, lo, hi) => {                                     // uint16 x3 -> float32 x3 in the bbox
    const n = q.length / 3, out = new Float32Array(q.length);
    for (let a = 0; a < 3; a++) { const s = (hi[a] - lo[a]) / 65535, l = lo[a]; for (let i = 0; i < n; i++) out[3 * i + a] = q[3 * i + a] * s + l; }
    return out;
  };
  const secs = (u, out) => { for (let i = 0; i < u.length; i++) out[i] = u[i] === 65535 ? -1 : u[i] / 1000; return out; };

  async function fetchBlob(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(url + " " + r.status);
    if (typeof root.DecompressionStream !== "function") throw new Error("no DecompressionStream");
    return new Response(r.body.pipeThrough(new root.DecompressionStream("gzip"))).arrayBuffer();
  }
  // -> {manifest, lod, cells: [{id, role, type, layer, soma, mesh:{pos,idx,kind,dist,arrive,nv,nf}, syn:{pos,npre,npost,preArrive}, skel:{...}, askel:{...}}], em}
  async function load(set, lodName, base) {
    const key = set + "/" + lodName;
    if (cache[key]) return cache[key];
    base = base || "neuron_render/h01/";
    cache[key] = (async () => {
      const manifest = await (await fetch(base + set + ".json")).json();
      const L = manifest.lods[lodName] || manifest.lods.desktop;
      const buf = await fetchBlob(base + L.file);
      const cells = L.cells.map(c => {
        const out = { id: c.id, role: c.role, source: c.source, soma: c.soma, classes: c.classes, myelinatedUm: c.myelinated_um || 0,
                      axonUm: c.axon_um || 0, dendUm: c.dend_um || 0, facesSource: c.faces_source, lod: c.lod, tags: c.tags || [] };
        if (c.mesh) {
          const m = c.mesh, nv = m.nv, nf = m.nf;
          out.mesh = { nv, nf, pos: dq(u16(buf, m.pos, nv * 3), c.bbox[0], c.bbox[1]),
                       idx: m.idx_t === "u32" ? new Uint32Array(buf, m.idx, nf * 3) : new Uint16Array(buf, m.idx, nf * 3),
                       kind: new Uint8Array(buf, m.kind, nv), dist: Float32Array.from(u16(buf, m.dist, nv), x => x / 10),
                       arrive: secs(u16(buf, m.arrive, nv), new Float32Array(nv)) };
          out.bbox = c.bbox;
        }
        if (c.syn) {
          const s = c.syn, n = s.npre + s.npost;
          out.syn = { npre: s.npre, npost: s.npost, pos: dq(u16(buf, s.pos, n * 3), c.sbbox[0], c.sbbox[1]),
                      preArrive: secs(u16(buf, s.pre_arrive, s.npre), new Float32Array(s.npre)) };
        }
        const skel = (k, box) => { const n = k.n; return { n, pos: dq(u16(buf, k.pos, n * 3), box[0], box[1]),
          kind: new Uint8Array(buf, k.kind, n), parent: new Int32Array(buf.slice(k.parent, k.parent + 4 * n)),
          dist: Float32Array.from(u16(buf, k.dist, n), x => x / 10), arrive: secs(u16(buf, k.arrive, n), new Float32Array(n)) }; };
        if (c.skel) out.skel = skel(c.skel, c.sbbox);               // the far tier: the whole skeleton (drawn as lines)
        if (c.askel) out.askel = skel(c.askel, c.abbox);            // focus / hero cells: the axon's skeleton (a line under the mesh, lit by the pulse)
        return out;
      });
      return { manifest, lod: lodName, cells, em: Object.assign({ url: base + manifest.em.file }, manifest.em), bytes: L.bytes, triangles: L.triangles };
    })();
    try { return await cache[key]; } catch (e) { delete cache[key]; throw e; }
  }
  // what the caption says about an H01 set
  function describe(data) {
    const C = data.cells, by = {};
    for (const c of C) by[c.role] = (by[c.role] || 0) + 1;
    const pre = C.reduce((a, c) => a + (c.syn ? c.syn.npre : 0), 0), post = C.reduce((a, c) => a + (c.syn ? c.syn.npost : 0), 0);
    const my = C.reduce((a, c) => a + (c.myelinatedUm || 0), 0);
    return { cells: C.length, focus: C.filter(c => c.role === "focus").map(c => c.id), hero: by.hero || 0, mid: by.mid || 0, far: by.far || 0,
             glia: by.glia || 0, synapsesPre: pre, synapsesPost: post, myelinatedUm: Math.round(my), triangles: data.triangles, bytes: data.bytes };
  }
  NR.h01 = { load, describe, cache };
})(typeof window !== "undefined" ? window : globalThis);
