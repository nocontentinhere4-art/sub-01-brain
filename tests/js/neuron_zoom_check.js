// Node check of the cortical column of the zoom (#99) in web/neurons3d.js, with a minimal THREE stub (no WebGL):
// run by tests/test_neuron_zoom.py. Prints one JSON line.
"use strict";
const path = require("path"), fs = require("fs");
const root = path.resolve(__dirname, "..", "..");
globalThis.performance = globalThis.performance || require("perf_hooks").performance;
require(path.join(root, "web", "neurons3d.js"));
const N = globalThis.Neurons3D;
class V3 { constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z; }
  set(x, y, z) { this.x = x; this.y = y; this.z = z; return this; } clone() { return new V3(this.x, this.y, this.z); }
  normalize() { const l = Math.hypot(this.x, this.y, this.z) || 1; this.x /= l; this.y /= l; this.z /= l; return this; }
  toArray() { return [this.x, this.y, this.z]; } setScalar(s) { this.x = this.y = this.z = s; return this; } }
class Q { constructor() { this.x = 0; this.y = 0; this.z = 0; this.w = 1; }
  setFromUnitVectors(a, b) { const d = a.x * b.x + a.y * b.y + a.z * b.z;
    if (d < -0.999999) { this.x = 1; this.y = 0; this.z = 0; this.w = 0; return this; }
    const c = [a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x], w = 1 + d, l = Math.hypot(...c, w);
    this.x = c[0] / l; this.y = c[1] / l; this.z = c[2] / l; this.w = w / l; return this; } }
const rot = (q, v) => { const c = [q.y * v[2] - q.z * v[1] + q.w * v[0], q.z * v[0] - q.x * v[2] + q.w * v[1], q.x * v[1] - q.y * v[0] + q.w * v[2]];
  return [v[0] + 2 * (q.y * c[2] - q.z * c[1]), v[1] + 2 * (q.z * c[0] - q.x * c[2]), v[2] + 2 * (q.x * c[1] - q.y * c[0])]; };
class Attr { constructor(a, n) { this.array = a; this.itemSize = n; this.needsUpdate = false; } setUsage() { return this; } }
class Geom { constructor() { this.attributes = {}; this.instanceCount = 0; } setAttribute(k, a) { this.attributes[k] = a; return this; }
  getAttribute(k) { return this.attributes[k]; } dispose() {} }
class Obj { constructor(g, m) { this.geometry = g; this.material = m; this.children = []; this.visible = true;
    this.position = new V3(); this.quaternion = new Q(); this.scale = new V3(1, 1, 1); }
  add(c) { this.children.push(c); } remove() {} updateMatrixWorld() {}
  localToWorld(v) { const p = rot(this.quaternion, [v.x * this.scale.x, v.y * this.scale.y, v.z * this.scale.z]);
    return v.set(p[0] + this.position.x, p[1] + this.position.y, p[2] + this.position.z); } }
const THREE = { Group: Obj, Scene: Obj, LineSegments: Obj, Points: Obj, Mesh: Obj, InstancedBufferGeometry: Geom, BufferGeometry: Geom,
  BufferAttribute: Attr, InstancedBufferAttribute: Attr, Vector3: V3,
  ShaderMaterial: class { constructor(o) { Object.assign(this, o); } dispose() {} }, AdditiveBlending: 2, DynamicDrawUsage: 35048 };
const web = f => JSON.parse(fs.readFileSync(path.join(root, "web", f), "utf8"));
const morph = { cells: Object.assign({}, web("neurons_morph.json").cells, web("column_morph.json").cells) };
const b64 = bytes => Buffer.from(Uint8Array.from(bytes)).toString("base64");
const pos = [-40.2, 10.5, 30.1], normal = [-0.6, 0.48, 0.64], region = 12;
const scene = new Obj();
const col = N.column({ THREE, scene, morph, pos, normal, region, block: { um: [2210, 846, 175], depthUm: [400, 1250] } });
const info = col.info(), group = col.group;
// every drawn cell: its soma depth, and for pyramids the depth its apical tuft reaches (soma depth - reach x scale)
const cells = [];
for (const c of col.cells) {
  const lines = group.children.find(l => l.name === "column-" + c.t), g = lines.geometry;
  const off = g.getAttribute("iOff").array, sc = Math.abs(g.getAttribute("iScale").array[c.i]), depth = -off[3 * c.i + 1];
  const reach = morph.cells[c.t].box[4] * sc;
  cells.push({ t: c.t, layer: c.layer, depth, tip: depth - reach, quat: Array.from(g.getAttribute("iQuat").array.slice(4 * c.i, 4 * c.i + 4)) });
}
const up = rot(group.quaternion, [0, 1, 0]);
const at0 = col.at(0), at1 = col.at(1000);
const before = col.info().spiking;
const frame = (r, n) => { const sq = []; for (let i = 0; i < n; i++) sq.push(r, (i * 37) % 256, (i * 11) % 256);
  const rq = new Array(214).fill(120); rq[r] = 220; return { type: "spiking", net: "cpu", n3: { sq: b64(sq), rq: b64(rq), span: 200, ns: n } }; };
col.onFrame(frame(region + 1, 40)); const other = col.info().spiking;
col.onFrame(frame(region, 40)); const own = col.info().spiking;
console.log(JSON.stringify({ plan: N.columnPlan(morph), layersUm: N.H01_LAYERS_UM, neuronsMm3: N.H01_NEURONS_MM3, info,
  cells, up, normal, pos, at0, at1, spiking_offline: before, spiking_other: other, spiking_own: own,
  children: group.children.map(c => c.name), segmentsPerCell: Math.max(...group.children.filter(c => c.geometry.getAttribute("aKind"))
    .map(c => c.geometry.getAttribute("position").array.length / 6)) }));
