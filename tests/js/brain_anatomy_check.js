// Node check of web/brain_anatomy.js (#99 G9) with a minimal THREE stub (no WebGL): run by tests/test_brain_anatomy.py.
// Prints one JSON line: the assets parsed, what each view swaps and draws, the cut plane, the caption's provenance.
"use strict";
const path = require("path"), fs = require("fs");
const root = path.resolve(__dirname, "..", "..");
globalThis.performance = globalThis.performance || require("perf_hooks").performance;
require(path.join(root, "web", "brain_anatomy.js"));
const B = globalThis.BrainAnatomy;

class V3 { constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z; } set(x, y, z) { this.x = x; this.y = y; this.z = z; return this; }
  copy(v) { return this.set(v.x, v.y, v.z); } negate() { return this.set(-this.x, -this.y, -this.z); }
  addScaledVector(v, s) { this.x += v.x * s; this.y += v.y * s; this.z += v.z * s; return this; } }
class V4 extends V3 { constructor(x, y, z, w) { super(x, y, z); this.w = w; } set(x, y, z, w) { super.set(x, y, z); this.w = w; return this; } }
class Attr { constructor(a, n) { this.array = a; this.itemSize = n; this.count = a.length / n; } }
class Geom { constructor() { this.attributes = {}; this.index = null; } setAttribute(k, a) { this.attributes[k] = a; return this; } setIndex(a) { this.index = a; return this; }
  computeVertexNormals() { const p = this.attributes.position.array, idx = this.index.array, n = new Float32Array(p.length);
    for (let i = 0; i < idx.length; i += 3) { const a = idx[i] * 3, b = idx[i + 1] * 3, c = idx[i + 2] * 3;
      const ux = p[b] - p[a], uy = p[b + 1] - p[a + 1], uz = p[b + 2] - p[a + 2], vx = p[c] - p[a], vy = p[c + 1] - p[a + 1], vz = p[c + 2] - p[a + 2];
      const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
      for (const k of [a, b, c]) { n[k] += nx; n[k + 1] += ny; n[k + 2] += nz; } }
    for (let v = 0; v < n.length; v += 3) { const l = Math.hypot(n[v], n[v + 1], n[v + 2]) || 1; n[v] /= l; n[v + 1] /= l; n[v + 2] /= l; }
    this.attributes.normal = new Attr(n, 3); } dispose() {} }
class Obj { constructor(g, m) { this.geometry = g; this.material = m; this.children = []; this.visible = true; this.name = ""; this.userData = {};
  this.position = new V3(); this.quaternion = { setFromUnitVectors() {} }; } add(c) { this.children.push(c); } remove(c) { this.children = this.children.filter(x => x !== c); } }
class Mat4 { set(...a) { this.elements = a; return this; } }
const THREE = { Group: Obj, Scene: Obj, Mesh: Obj, LineSegments: Obj, BufferGeometry: Geom, PlaneGeometry: class extends Geom { constructor() { super(); this.setAttribute("position", new Attr(new Float32Array(12), 3)); this.setIndex(new Attr(new Uint16Array([0, 1, 2, 0, 2, 3]), 1)); } },
  BufferAttribute: Attr, ShaderMaterial: class { constructor(o) { Object.assign(this, o); } dispose() {} }, Vector3: V3, Vector4: V4, Vector2: class { constructor(x, y) { this.x = x; this.y = y; } },
  Matrix4: Mat4, Texture: class { constructor(img) { this.image = img; } dispose() {} }, LinearFilter: 1006, DoubleSide: 2, FrontSide: 0 };

const web = f => path.join(root, "web", f);
const buf = f => { const b = fs.readFileSync(f); return b.buffer.slice(b.byteOffset, b.byteOffset + b.length); };
const meta = JSON.parse(fs.readFileSync(web("anatomy/anatomy.json"), "utf8"));
const out = {};

// --- the pure helpers on the real assets ---
const parts = B.parseParts(buf(web("anatomy/" + meta.parts.file)), meta.parts);
const cortex = new Float32Array(buf(web("cortex.bin"))), cortexIdx = new Uint32Array(buf(web("cortex_idx.bin")));
const bb = { min: [1e9, 1e9, 1e9], max: [-1e9, -1e9, -1e9] };
for (let i = 0; i < cortex.length; i += 3) for (let k = 0; k < 3; k++) { bb.min[k] = Math.min(bb.min[k], cortex[i + k]); bb.max[k] = Math.max(bb.max[k], cortex[i + k]); }
out.parts = parts.map(p => { const e = { min: [1e9, 1e9, 1e9], max: [-1e9, -1e9, -1e9] }; let bad = 0;
  for (let i = 0; i < p.pos.length; i += 3) for (let k = 0; k < 3; k++) { e.min[k] = Math.min(e.min[k], p.pos[i + k]); e.max[k] = Math.max(e.max[k], p.pos[i + k]); }
  for (let i = 0; i < p.idx.length; i++) if (p.idx[i] >= p.pos.length / 3) bad++;
  return { label: p.label, kind: p.kind, verts: p.pos.length / 3, tris: p.idx.length / 3, bad_indices: bad, min: e.min.map(x => +x.toFixed(1)), max: e.max.map(x => +x.toFixed(1)) }; });
out.cortex_bbox = bb;
const cg = new Geom(); cg.setAttribute("position", new Attr(cortex, 3)); cg.setIndex(new Attr(cortexIdx, 1)); cg.computeVertexNormals();
const t0 = performance.now();
const depth = B.sulcalDepth(cortex, cortexIdx, cg.attributes.normal.array);
out.sulcal = { ms: Math.round(performance.now() - t0), n: depth.length, mean: +(depth.reduce((a, b) => a + b, 0) / depth.length).toFixed(3),
               frac_deep: +(depth.filter(d => d > 0.5).length / depth.length).toFixed(3), max: Math.max(...depth), min: Math.min(...depth) };
out.cut = { coronal: B.cutPlane("coronal", 0.5, bb), sagittal: B.cutPlane("sagittal", 0.25, bb), axial: B.cutPlane("axial", 1, bb), bogus: B.cutPlane("bogus", 2, bb) };
const t = meta.volume.tissue;
out.tissue = { csf: B.tissueColour(t.csf, B.PALETTE.fixed, t), grey: B.tissueColour(t.grey, B.PALETTE.fixed, t), white: B.tissueColour(t.white, B.PALETTE.fixed, t),
               mid: B.tissueColour((t.grey + t.white) / 2, B.PALETTE.fresh, t) };
out.volume = meta.volume;

// --- the scene driver: views swap materials, layers show atlas parts, captions carry the provenance ---
const scene = new Obj();
const cortexMesh = new Obj(cg, { name: "orig-cortex" }); cortexMesh.name = "cortex";
const pageFibreUniforms = { time: { value: 0 }, mixw: { value: new V3(1, 0, 0) }, pulseT: { value: -1 }, act: { value: null }, tgOn: { value: new Array(12).fill(0) },
                            burst: { value: 0 }, boost: { value: 0 }, sci: { value: 0 } };
const fibres = new Obj(new Geom(), { name: "orig-fibres", uniforms: pageFibreUniforms }); fibres.name = "fibres";
let caption = "";
const fetchMap = {
  "/anatomy/anatomy.json": () => ({ ok: true, json: async () => meta }),
};
for (const f of ["cortex_part.bin", "cerebellum.bin", "cerebellum_idx.bin", "brainstem.bin", "brainstem_idx.bin", meta.parts.file])
  fetchMap["/anatomy/" + f] = () => ({ ok: true, arrayBuffer: async () => buf(web("anatomy/" + f)) });
globalThis.fetch = async url => { const f = fetchMap[url]; if (!f) throw new Error("no " + url); return f(); };
globalThis.Image = class { set src(v) { setTimeout(() => this.onload && this.onload(), 0); } };
const renderer = { dpr: 2, getPixelRatio() { return this.dpr; }, setPixelRatio(v) { this.dpr = v; } };
const anat = B.create({ THREE, scene, renderer, cortex: cortexMesh, fibres, base: "/anatomy/", caption: h => { caption = h; } });
const tick = () => new Promise(r => setTimeout(r, 5));
(async () => {
  const views = {};
  for (const v of ["fresh", "fixed", "bundles", "glow"]) {
    anat.setView(v);
    for (let i = 0; i < 20; i++) await tick();
    const st = anat.state();
    views[v] = { cortexMat: cortexMesh.material === cortexMesh.material && cortexMesh.material.name === "orig-cortex" ? "orig" : "swapped",
                 fibresMat: fibres.material.name === "orig-fibres" ? "orig" : "swapped", drawn: st.drawn, meshes: st.meshes, cut: st.cut.on, caption,
                 winding: st.winding, fibresDrawn: st.fibresDrawn, bundleShared: st.bundleSharesPageUniforms,
                 cortexPart: cg.attributes.part ? Array.from(new Set(cg.attributes.part.array)).sort() : null };
  }
  anat.setView("fresh"); anat.setLayer("vessels", true); anat.setLayer("nerves", true);
  for (let i = 0; i < 20; i++) await tick();
  views.layers = { drawn: anat.state().drawn, caption, parts: anat.state().parts };
  anat.setView("fixed"); anat.setCut("sagittal", 0.3); for (let i = 0; i < 20; i++) await tick();
  views.fixed_cut = { cut: anat.state().cut, cap: scene.children[0].children.filter(c => c.name === "cut_cap").map(c => ({ visible: c.visible, pos: [c.position.x, c.position.y, c.position.z] })),
                      clip: [cortexMesh.material.uniforms.uClip.value.x, cortexMesh.material.uniforms.uClip.value.y, cortexMesh.material.uniforms.uClip.value.z, cortexMesh.material.uniforms.uClip.value.w, cortexMesh.material.uniforms.uClipOn.value] };
  // the frame-time tier: 20 fps for 4 s with a realistic view on -> the low tier, pixel ratio capped
  let now = 1000; for (let i = 0; i < 90; i++) { now += 50; anat.update(now); }
  views.tier = { tier: anat.state().tier, fps: anat.state().fps, dpr: renderer.dpr, caption_has_low: /low-detail/.test(caption) };
  globalThis.zoomBrain = 0.4; anat.update(now + 50);
  views.fade = { alpha: anat.state().alpha, transparent: cortexMesh.material.transparent, depthWrite: cortexMesh.material.depthWrite };
  globalThis.zoomBrain = 1; anat.update(now + 100);
  views.fade.back = { alpha: anat.state().alpha, transparent: cortexMesh.material.transparent };
  anat.setView("glow"); for (let i = 0; i < 20; i++) await tick();
  views.back = { cortexMat: cortexMesh.material.name === "orig-cortex" ? "orig" : "swapped", fibresMat: fibres.material.name === "orig-fibres" ? "orig" : "swapped", drawn: anat.state().drawn };
  anat.dispose();
  views.disposed = { dpr: renderer.dpr, inScene: scene.children.length };
  out.views = views;
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
