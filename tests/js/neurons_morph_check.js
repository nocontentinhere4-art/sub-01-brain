// Node check of web/neurons3d.js close-ups (#78) with a minimal THREE stub (no WebGL): run by tests/test_neurons_morph.py.
// Prints one JSON line with what the page would draw and what each frame changes.
"use strict";
const path = require("path"), fs = require("fs");
const root = path.resolve(__dirname, "..", "..");
globalThis.performance = globalThis.performance || require("perf_hooks").performance;
require(path.join(root, "web", "neurons3d.js"));
const N = globalThis.Neurons3D;
class Attr { constructor(a, n) { this.array = a; this.itemSize = n; this.needsUpdate = false; } setUsage() { return this; } }
class Geom { constructor() { this.attributes = {}; this.instanceCount = 0; } setAttribute(k, a) { this.attributes[k] = a; return this; }
  getAttribute(k) { return this.attributes[k]; } dispose() {} }
class Obj { constructor(g, m) { this.geometry = g; this.material = m; this.children = []; this.rotation = { x: 0 }; } add(c) { this.children.push(c); } }
const THREE = { Group: Obj, LineSegments: Obj, InstancedBufferGeometry: Geom, BufferAttribute: Attr, InstancedBufferAttribute: Attr,
  ShaderMaterial: class { constructor(o) { Object.assign(this, o); } dispose() {} }, AdditiveBlending: 2, DynamicDrawUsage: 35048 };
const morph = JSON.parse(fs.readFileSync(path.join(root, "web", "neurons_morph.json"), "utf8"));
const b64 = bytes => Buffer.from(Uint8Array.from(bytes)).toString("base64");
const frame = (region, n) => { const sq = []; for (let i = 0; i < n; i++) sq.push(region, (i * 37) % 256, (i * 11) % 256);
  const rq = new Array(214).fill(120); rq[region] = 220; return { type: "spiking", net: "cpu", n3: { sq: b64(sq), rq: b64(rq), span: 200, ns: n } }; };
const out = {};
for (const [kind, region] of [["cortex", 12], ["striatum", 202], ["thalamus", 200], ["hippocampus", 204], ["amygdala", 212]]) {
  const c = N.closeup({ THREE, morph, kind, region });
  const segs = c.group.children.reduce((a, l) => a + l.geometry.getAttribute("position").array.length / 6 * l.geometry.instanceCount, 0);
  const before = c.info();
  const v = { tilt: 0, scaleMin: 9, scaleMax: 0, mirrored: 0, n: 0, yawBins: new Set() };   // per-instance variety
  for (const l of c.group.children) {
    const g = l.geometry, t = g.getAttribute("iTilt").array, sc = g.getAttribute("iScale").array, r = g.getAttribute("iRot").array;
    for (let j = 0; j < g.instanceCount; j++) {
      v.tilt = Math.max(v.tilt, Math.abs(t[2 * j]), Math.abs(t[2 * j + 1]));
      v.scaleMin = Math.min(v.scaleMin, Math.abs(sc[j])); v.scaleMax = Math.max(v.scaleMax, Math.abs(sc[j]));
      v.mirrored += sc[j] < 0 ? 1 : 0; v.n++;
      v.yawBins.add(Math.floor((Math.atan2(r[2 * j + 1], r[2 * j]) + Math.PI) / (Math.PI / 4)));
    }
  }
  c.update(performance.now());
  const rateBefore = c.group.children[0].material.uniforms.uRate.value;
  c.onFrame(frame(region + 1, 50));                              // another region's spikes: nothing here changes
  const other = c.info().spiking;
  c.onFrame(frame(region, 50));
  for (let i = 0; i < 40; i++) c.update(performance.now());
  const after = c.info();
  out[kind] = { cells: before.cells, segments: before.segments, drawn_segments: segs, drawCalls: c.group.children.length,
    spiking_offline: before.spiking, live_offline: before.live, rate_offline: rateBefore,
    spiking_other_region: other, spiking_after: after.spiking, live_after: after.live,
    rate_after: c.group.children[0].material.uniforms.uRate.value, types: before.types,
    variety: { tilt_deg: v.tilt * 180 / Math.PI, scale_min: v.scaleMin, scale_max: v.scaleMax,
               mirrored_frac: v.mirrored / v.n, yaw_octants: v.yawBins.size } };
  c.dispose();
}
out.lod = [N.lod("brain", 300), N.lod("brain", N.LOD_IN - 1), N.lod("closeup", 100, 100), N.lod("closeup", 100 * N.LOD_OUT + 1, 100)];
out.slowdown = N.SLOWDOWN;
out.kinds = ["LH_Vis_1", "Left Putamen", "Right Thalamus", "Left Pallidum", "Left Hippocampus", "Right Amygdala"].map(name => N.kindOf({ name }));
console.log(JSON.stringify(out));
