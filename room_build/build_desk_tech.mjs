// node build_desk_tech.mjs <ambientCG Plastic016A 1K folder> ../web/room     (writes controller.glb and monitor.glb)
// The game controller and the monitor on the desk, modelled in code for this project (original, CC0; no maker's shape, no
// logo), replacing the Tripo ones of props_tripo2.glb. PBR from desk_pbr.mjs (ambientCG Plastic 016 A's speckle; u < 0.5 the
// matte half of the maps, u >= 0.5 the polished half), colours per vertex (linear).
//  controller.glb: node "controller", origin the middle of its footprint on the desk, the grips towards +z (the player), 15.5 x
//    10.5 x 6 cm: a body with two grips (a signed distance field, meshed by surface nets and simplified), two analogue sticks
//    with knurled concave caps in wells, a D-pad, four plain face buttons, two small menu buttons and a round centre button,
//    bumpers and triggers; it rests on its grips. A soft contact shadow under it (its child "controller_contact").
//  monitor.glb: node "monitor", in world metres (like props_tripo2.glb): a panel fitted around the page's live screen
//    (SURF_monitor in room_clean.glb: MON below) with 6 mm bezels and a 14 mm chin, a glossy rim, a tapered rear housing with
//    vent slots, a port bay and a VESA plate, a hinge; a flat dark-metal neck and a flat rounded foot; the cable from the port
//    bay down behind the neck, over the desk's back edge and down the gap to the wall.
import { Document, NodeIO } from "@gltf-transform/core";
import { MeshoptSimplifier, MeshoptEncoder } from "meshoptimizer";
import { EXTMeshoptCompression, ALL_EXTENSIONS } from "@gltf-transform/extensions";
import { dedup, prune, reorder, quantize } from "@gltf-transform/functions";
import { plasticMaps, contactBlob } from "./desk_pbr.mjs";

const [folder, outDir] = process.argv.slice(2);
await MeshoptSimplifier.ready; await MeshoptEncoder.ready;

// ---------- a part: positions, colours, uvs, normals (optional, else smooth from faces), indices
function part(name){ return {name, pos: [], col: [], uv: [], nor: null, idx: []}; }
const add = (p, q, c, uv) => { p.pos.push(...q); p.col.push(...c, 1); p.uv.push(...uv); return p.pos.length / 3 - 1; };
function smoothNormals(p){
  const n = new Float32Array(p.pos.length), P = p.pos;
  for (let i = 0; i < p.idx.length; i += 3) {
    const [a, b, c] = [p.idx[i] * 3, p.idx[i + 1] * 3, p.idx[i + 2] * 3];
    const u = [P[b] - P[a], P[b + 1] - P[a + 1], P[b + 2] - P[a + 2]], v = [P[c] - P[a], P[c + 1] - P[a + 1], P[c + 2] - P[a + 2]];
    const f = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
    for (const k of [a, b, c]) { n[k] += f[0]; n[k + 1] += f[1]; n[k + 2] += f[2]; }
  }
  for (let i = 0; i < n.length; i += 3) { const l = Math.hypot(n[i], n[i + 1], n[i + 2]) || 1; n[i] /= l; n[i + 1] /= l; n[i + 2] /= l; }
  return n;
}
function merge(into, p){                                       // append part p to part `into`
  const base = into.pos.length / 3;
  into.pos.push(...p.pos); into.col.push(...p.col); into.uv.push(...p.uv);
  into.nor.push(...(p.nor || smoothNormals(p))); into.idx.push(...p.idx.map(i => i + base));
}
// a closed ring of points -> a band to the next ring; rings are arrays of [x, y, z]. Faces wound so their normal looks
// along `out(centre)` (a function of the face's centre)
function bands(p, rings, c, uvu, out, capStart = false, capEnd = false){
  const ids = rings.map(r => r.map(q => add(p, q, c, [uvu, 0.5])));
  const tri = (a, b, d) => p.idx.push(a, b, d);
  for (let k = 0; k + 1 < ids.length; k++) { const A = ids[k], B = ids[k + 1], n = A.length;
    for (let i = 0; i < n; i++) { const j = (i + 1) % n; tri(A[i], B[i], B[j]); tri(A[i], B[j], A[j]); } }
  for (const [on, ring] of [[capStart, ids[0]], [capEnd, ids[ids.length - 1]]]) if (on) {
    const r = ring.map(i => p.pos.slice(3 * i, 3 * i + 3)), m = [0, 1, 2].map(a => r.reduce((s, q) => s + q[a], 0) / r.length);
    const ci = add(p, m, c, [uvu, 0.5]); const cr = ring.map(i => add(p, p.pos.slice(3 * i, 3 * i + 3), c, [uvu, 0.5]));
    for (let i = 0; i < cr.length; i++) p.idx.push(ci, cr[i], cr[(i + 1) % cr.length]);
  }
  orient(p, out);
}
// turn every triangle of p (from index `from`) so its face normal looks along out(centre)
function orient(p, out, from = 0){ orientRange(p, from, p.idx.length, out); }
function orientRange(p, from, to, out){
  const P = i => [p.pos[3 * i], p.pos[3 * i + 1], p.pos[3 * i + 2]];
  for (let t = from; t < to; t += 3) {
    const [a, b, c] = [P(p.idx[t]), P(p.idx[t + 1]), P(p.idx[t + 2])];
    const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], v = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
    const f = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
    const w = out([(a[0] + b[0] + c[0]) / 3, (a[1] + b[1] + c[1]) / 3, (a[2] + b[2] + c[2]) / 3]);
    if (f[0] * w[0] + f[1] * w[1] + f[2] * w[2] < 0) [p.idx[t + 1], p.idx[t + 2]] = [p.idx[t + 2], p.idx[t + 1]];
  }
}
// a lathe about the vertical through (cx, cz): profile [[r, y], ...] from the axis outwards; rmod(angle, k) scales radii
function lathe(name, prof, cx, y0, cz, c, uvu, n = 32, rmod = null){
  const p = part(name);
  const rings = prof.map(([r, y], k) => Array.from({length: n}, (_, i) => { const a = 2 * Math.PI * i / n, rr = r * (rmod ? rmod(a, k) : 1);
    return [cx + rr * Math.cos(a), y0 + y, cz + rr * Math.sin(a)]; }));
  const ids = rings.map(r => r.map(q => add(p, q, c, [uvu, 0.5])));
  for (let k = 0; k + 1 < ids.length; k++) for (let i = 0; i < n; i++) { const j = (i + 1) % n;
    p.idx.push(ids[k][i], ids[k + 1][i], ids[k + 1][j], ids[k][i], ids[k + 1][j], ids[k][j]); }
  // each band faces along the profile's outward normal (-dy, dr): up on caps that run outwards, out on walls going down
  for (let k = 0; k + 1 < prof.length; k++) { const nr = -(prof[k + 1][1] - prof[k][1]), ny = prof[k + 1][0] - prof[k][0];
    const t0 = k * n * 6; orientRange(p, t0, t0 + n * 6, q => { const dx = q[0] - cx, dz = q[2] - cz, l = Math.hypot(dx, dz) || 1; return [nr * dx / l, ny, nr * dz / l]; }); }
  return p;
}

// ---------- signed distance fields and surface nets
const len3 = (x, y, z) => Math.hypot(x, y, z);
const sdRoundBox = (x, y, z, hx, hy, hz, r) => { const qx = Math.abs(x) - hx + r, qy = Math.abs(y) - hy + r, qz = Math.abs(z) - hz + r;
  return len3(Math.max(qx, 0), Math.max(qy, 0), Math.max(qz, 0)) + Math.min(Math.max(qx, qy, qz), 0) - r; };
const sdEllipsoid = (x, y, z, a, b, c) => { const k0 = len3(x / a, y / b, z / c), k1 = len3(x / (a * a), y / (b * b), z / (c * c)); return k0 * (k0 - 1) / k1; };
function sdRoundCone(p, a, b, r1, r2){                      // a capsule whose radius goes from r1 at a to r2 at b
  const ba = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], pa = [p[0] - a[0], p[1] - a[1], p[2] - a[2]];
  const l2 = ba[0] ** 2 + ba[1] ** 2 + ba[2] ** 2, t = Math.max(0, Math.min(1, (pa[0] * ba[0] + pa[1] * ba[1] + pa[2] * ba[2]) / l2));
  return len3(pa[0] - ba[0] * t, pa[1] - ba[1] * t, pa[2] - ba[2] * t) - (r1 + (r2 - r1) * t);
}
const smin = (a, b, k) => { const h = Math.max(k - Math.abs(a - b), 0) / k; return Math.min(a, b) - h * h * k * 0.25; };
const smax = (a, b, k) => -smin(-a, -b, k);
// surface nets over [lo, hi] at `step`: a vertex per cell the surface crosses (the mean of its edge crossings), a quad per
// crossed grid edge; normals from the field's gradient
function surfaceNets(name, f, lo, hi, step, c, uvOf){
  const nx = Math.ceil((hi[0] - lo[0]) / step) + 1, ny = Math.ceil((hi[1] - lo[1]) / step) + 1, nz = Math.ceil((hi[2] - lo[2]) / step) + 1;
  const F = new Float32Array(nx * ny * nz), at = (i, j, k) => (k * ny + j) * nx + i;
  for (let k = 0; k < nz; k++) for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++)
    F[at(i, j, k)] = f(lo[0] + i * step, lo[1] + j * step, lo[2] + k * step);
  const p = part(name), cellV = new Int32Array(nx * ny * nz).fill(-1);
  const E = [[0, 1], [2, 3], [4, 5], [6, 7], [0, 2], [1, 3], [4, 6], [5, 7], [0, 4], [1, 5], [2, 6], [3, 7]];
  for (let k = 0; k + 1 < nz; k++) for (let j = 0; j + 1 < ny; j++) for (let i = 0; i + 1 < nx; i++) {
    const v = [], cs = [];
    for (let m = 0; m < 8; m++) { const di = m & 1, dj = (m >> 1) & 1, dk = (m >> 2) & 1; v.push(F[at(i + di, j + dj, k + dk)]); cs.push([di, dj, dk]); }
    if (v.every(x => x > 0) || v.every(x => x <= 0)) continue;
    let sx = 0, sy = 0, sz = 0, n = 0;
    for (const [a, b] of E) if ((v[a] > 0) !== (v[b] > 0)) { const t = v[a] / (v[a] - v[b]);
      sx += cs[a][0] + t * (cs[b][0] - cs[a][0]); sy += cs[a][1] + t * (cs[b][1] - cs[a][1]); sz += cs[a][2] + t * (cs[b][2] - cs[a][2]); n++; }
    const q = [lo[0] + (i + sx / n) * step, lo[1] + (j + sy / n) * step, lo[2] + (k + sz / n) * step];
    cellV[at(i, j, k)] = add(p, q, c, uvOf(q));
  }
  for (let k = 1; k + 1 < nz; k++) for (let j = 1; j + 1 < ny; j++) for (let i = 1; i + 1 < nx; i++) {
    const s0 = F[at(i, j, k)] > 0;
    for (const [di, dj, dk, A, B] of [[1, 0, 0, [0, 1, 0], [0, 0, 1]], [0, 1, 0, [0, 0, 1], [1, 0, 0]], [0, 0, 1, [1, 0, 0], [0, 1, 0]]]) {
      if (i + di >= nx || j + dj >= ny || k + dk >= nz) continue;
      if (s0 === (F[at(i + di, j + dj, k + dk)] > 0)) continue;
      const c0 = at(i, j, k), c1 = at(i - A[0], j - A[1], k - A[2]), c2 = at(i - A[0] - B[0], j - A[1] - B[1], k - A[2] - B[2]), c3 = at(i - B[0], j - B[1], k - B[2]);
      const q = [cellV[c0], cellV[c1], cellV[c2], cellV[c3]];
      if (q.some(x => x < 0)) continue;
      if (s0) p.idx.push(q[0], q[1], q[2], q[0], q[2], q[3]); else p.idx.push(q[0], q[2], q[1], q[0], q[3], q[2]);
    }
  }
  return p;
}
function gradNormals(p, f){
  const e = 1e-4, n = [];
  for (let i = 0; i < p.pos.length; i += 3) { const [x, y, z] = p.pos.slice(i, i + 3);
    const g = [f(x + e, y, z) - f(x - e, y, z), f(x, y + e, z) - f(x, y - e, z), f(x, y, z + e) - f(x, y, z - e)], l = Math.hypot(...g) || 1;
    n.push(g[0] / l, g[1] / l, g[2] / l); }
  return n;
}
function simplify(p, f, ratio, err){                       // fewer triangles (meshoptimizer), then compact and SDF normals
  const idx = new Uint32Array(p.idx), pos = new Float32Array(p.pos);
  const [out] = MeshoptSimplifier.simplify(idx, pos, 3, Math.floor(idx.length * ratio / 3) * 3, err);
  orientFix(p, out, f);
  const map = new Map(), q = part(p.name);
  for (const i of out) if (!map.has(i)) { map.set(i, q.pos.length / 3); q.pos.push(...p.pos.slice(3 * i, 3 * i + 3)); q.col.push(...p.col.slice(4 * i, 4 * i + 4)); q.uv.push(...p.uv.slice(2 * i, 2 * i + 2)); }
  q.idx = [...out].map(i => map.get(i)); q.nor = gradNormals(q, f); return q;
}
function orientFix(p, idx, f){                              // (the triangles' winding against the field's gradient)
  for (let t = 0; t < idx.length; t += 3) {
    const P = i => p.pos.slice(3 * i, 3 * i + 3), a = P(idx[t]), b = P(idx[t + 1]), c = P(idx[t + 2]);
    const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], v = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
    const fn = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
    const m = [0, 1, 2].map(k => (a[k] + b[k] + c[k]) / 3), e = 1e-4;
    const g = [f(m[0] + e, m[1], m[2]) - f(m[0] - e, m[1], m[2]), f(m[0], m[1] + e, m[2]) - f(m[0], m[1] - e, m[2]), f(m[0], m[1], m[2] + e) - f(m[0], m[1], m[2] - e)];
    if (fn[0] * g[0] + fn[1] * g[1] + fn[2] * g[2] < 0) { const s = idx[t + 1]; idx[t + 1] = idx[t + 2]; idx[t + 2] = s; }
  }
}

// ---------- write a GLB: parts grouped by material
async function writeGLB(out, nodeName, groups, extra = null){
  const maps = await plasticMaps(folder), doc = new Document(), buf = doc.createBuffer(), scene = doc.createScene();
  const acc = (type, arr) => doc.createAccessor().setType(type).setArray(arr).setBuffer(buf);
  const tex = (name, img, mime) => doc.createTexture(name).setImage(img).setMimeType(mime);
  const mr = tex("plastic_mr", maps.mr, "image/webp"), nm = tex("plastic_normal", maps.normal, "image/webp");
  const mats = {
    plastic: doc.createMaterial(nodeName).setBaseColorFactor([1, 1, 1, 1]).setRoughnessFactor(1).setMetallicFactor(1).setMetallicRoughnessTexture(mr).setNormalTexture(nm).setNormalScale(0.35),
    metal: doc.createMaterial(nodeName + "_metal").setBaseColorFactor([1, 1, 1, 1]).setRoughnessFactor(0.42).setMetallicFactor(0.85),
    glass: doc.createMaterial(nodeName + "_glass").setBaseColorFactor([1, 1, 1, 1]).setRoughnessFactor(0.3).setMetallicFactor(0),
  };
  const mesh = doc.createMesh(nodeName); let tris = 0;
  for (const [m, p] of Object.entries(groups)) { if (!p.idx.length) continue;
    const nor = p.nor && p.nor.length === p.pos.length ? new Float32Array(p.nor) : smoothNormals(p);
    mesh.addPrimitive(doc.createPrimitive().setAttribute("POSITION", acc("VEC3", new Float32Array(p.pos))).setAttribute("NORMAL", acc("VEC3", nor))
      .setAttribute("TEXCOORD_0", acc("VEC2", new Float32Array(p.uv))).setAttribute("COLOR_0", acc("VEC4", new Float32Array(p.col)))
      .setIndices(acc("SCALAR", new Uint32Array(p.idx))).setMaterial(mats[m])); tris += p.idx.length / 3; }
  const node = doc.createNode(nodeName).setMesh(mesh); scene.addChild(node);
  if (extra) await extra(doc, node, acc, tex);
  for (const m of Object.values(mats)) if (!m.listParents().some(x => x.propertyType === "Primitive")) m.dispose();
  await doc.transform(dedup(), prune(), reorder({encoder: MeshoptEncoder}), quantize());
  doc.createExtension(EXTMeshoptCompression).setRequired(true).setEncoderOptions({method: EXTMeshoptCompression.EncoderMethod.QUANTIZE});
  await new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({"meshopt.encoder": MeshoptEncoder}).write(out, doc);
  return tris;
}
const lo3 = p => { const l = [1e9, 1e9, 1e9], h = [-1e9, -1e9, -1e9]; for (let i = 0; i < p.pos.length; i += 3) for (let a = 0; a < 3; a++) { l[a] = Math.min(l[a], p.pos[i + a]); h[a] = Math.max(h[a], p.pos[i + a]); } return [l, h]; };

// =====================================================================================================================
// the controller (local: x across, y up, z towards the player; the grips' ends rest on y = 0)
// =====================================================================================================================
{
  const BODY = [0.020, 0.020, 0.023], KEY = [0.008, 0.008, 0.009], CAP = [0.013, 0.013, 0.014], WELL = [0.006, 0.006, 0.007];
  const LS = [-0.033, -0.012], RS = [0.017, 0.011], DP = [-0.017, 0.011], FB = [0.033, -0.012];   // sticks, D-pad, face buttons
  const TOPY = 0.0475;
  function shell(x, y, z){
    let d = sdRoundBox(x, y - 0.034, z + 0.008, 0.047, 0.0135, 0.030, 0.012);
    for (const s of [-1, 1]) {
      d = smin(d, sdEllipsoid(x - s * 0.046, y - 0.035, z + 0.010, 0.031, 0.0135, 0.029), 0.012);
      d = smin(d, sdRoundCone([x, y, z], [s * 0.043, 0.034, 0.004], [s * 0.054, 0.0145, 0.044], 0.019, 0.0145), 0.014);
    }
    d = smax(d, y - TOPY, 0.008);                                          // the face plate: nearly flat
    for (const [cx, cz, r, deep] of [[...LS, 0.0125, 0.0035], [...RS, 0.0125, 0.0035], [...DP, 0.0140, 0.0022]])
      d = smax(d, -(Math.max(Math.hypot(x - cx, z - cz) - r, TOPY - deep - y)), 0.0015);   // the wells
    for (let b = 0; b < 4; b++) { const a = Math.PI / 2 * b, cx = FB[0] + 0.0105 * Math.cos(a), cz = FB[1] + 0.0105 * Math.sin(a);
      d = smax(d, -(Math.max(Math.hypot(x - cx, z - cz) - 0.0056, TOPY - 0.0015 - y)), 0.0008); }
    return d;
  }
  const surf = (x, z) => { let y = 0.07; while (y > 0 && shell(x, y, z) > 0) y -= 0.0002; return y; };
  const body = simplify(surfaceNets("controller", shell, [-0.086, -0.004, -0.060], [0.086, 0.064, 0.070], 0.0013, BODY,
    q => [0.25 + 0.25 * q[0] / 0.09, 0.5 + q[2] / 0.14]), shell, 0.14, 0.0015);
  const keys = part("keys"); keys.nor = [];
  // the sticks: a shaft in the well, a concave cap with a knurled rim
  for (const [cx, cz] of [LS, RS]) {
    const floor = TOPY - 0.0035, top = TOPY + 0.0085;
    merge(keys, lathe("boot", [[0.0062, top - 0.0042], [0.0068, floor + 0.0034], [0.0092, floor + 0.0016], [0.0114, floor + 0.0004], [0.0118, floor - 0.0008]], cx, 0, cz, WELL, 0.25, 32));
    merge(keys, lathe("cap", [[0, top - 0.0014], [0.0040, top - 0.0010], [0.0072, top - 0.0001], [0.0094, top - 0.0006], [0.0098, top - 0.0020], [0.0096, top - 0.0036],
      [0.0060, top - 0.0045], [0.0047, top - 0.0045]], cx, 0, cz, CAP, 0.25, 48, (a, k) => k >= 3 && k <= 5 ? 1 + 0.035 * (Math.cos(24 * a) > 0 ? 1 : -1) : 1));
  }
  // the D-pad: a cross, bevelled, its middle a little lower
  { const y0 = TOPY - 0.0028, y1 = TOPY + 0.0016, L = 0.0118, w = 0.0042, ol = [];
    for (const [sx, sz] of [[1, 0], [0, 1], [-1, 0], [0, -1]]) { const px = -sz, pz = sx;          // each arm: its two corners
      ol.push([sx * w - px * w, sz * w - pz * w], [sx * L - px * w, sz * L - pz * w], [sx * L + px * w, sz * L + pz * w]); }
    const ring = (s, y) => ol.map(([x, z]) => [DP[0] + x * s, y, DP[1] + z * s]);
    const p = part("dpad"), rings = [ring(1, y0), ring(1, y1 - 0.0008), ring(0.93, y1)];
    const ids = rings.map(r => r.map(q => add(p, q, KEY, [0.75, 0.5])));
    for (let k = 0; k < 2; k++) for (let i = 0; i < ol.length; i++) { const j = (i + 1) % ol.length; p.idx.push(ids[k][i], ids[k + 1][i], ids[k + 1][j], ids[k][i], ids[k + 1][j], ids[k][j]); }
    const mid = add(p, [DP[0], y1 - 0.0006, DP[1]], KEY, [0.75, 0.5]), top = rings[2].map(q => add(p, q, KEY, [0.75, 0.5]));
    for (let i = 0; i < top.length; i++) p.idx.push(mid, top[i], top[(i + 1) % top.length]);
    orient(p, q => q[1] > y1 - 0.0009 ? [0, 1, 0] : [q[0] - DP[0], 0, q[2] - DP[1]]);
    p.nor = null; merge(keys, p); }
  // the face buttons: four domes; the menu buttons: two pills; the centre button: a round one
  for (let b = 0; b < 4; b++) { const a = Math.PI / 2 * b, cx = FB[0] + 0.0105 * Math.cos(a), cz = FB[1] + 0.0105 * Math.sin(a);
    merge(keys, lathe("btn", [[0, TOPY + 0.0042], [0.0028, TOPY + 0.0038], [0.0044, TOPY + 0.0026], [0.0047, TOPY + 0.0010], [0.0047, TOPY - 0.0016]], cx, 0, cz, KEY, 0.75, 28)); }
  for (const [cx, cz, r] of [[-0.0105, -0.016, 0.0026], [0.0105, -0.016, 0.0026], [0, -0.030, 0.0052]]) {
    const y = surf(cx, cz);
    merge(keys, lathe("menu", [[0, y + 0.0013], [r * 0.7, y + 0.0011], [r, y + 0.0005], [r, y - 0.0015]], cx, 0, cz, KEY, 0.75, 24, null)); }
  // the bumpers along the front shoulders, the triggers behind and above them
  const sh = part("shoulders"); sh.nor = [];
  for (const s of [-1, 1]) {
    // a skin on the shell (from 1.2 mm inside to 2.8 mm proud of it) clipped to a box: they follow the body's curve
    const skin = (x, y, z, box, out) => smax(Math.abs(shell(x, y, z) - out / 2 + 0.0006) - out / 2 - 0.0006, box, 0.0012);
    const bump = (x, y, z) => skin(x, y, z, sdRoundBox(x - s * 0.043, y - 0.0425, z + 0.040, 0.021, 0.0042, 0.010, 0.002), 0.0028);
    const bp = simplify(surfaceNets("bumper", bump, [s * 0.043 - 0.026, 0.034, -0.056], [s * 0.043 + 0.026, 0.052, -0.022], 0.0008, KEY, q => [0.75, 0.5]), bump, 0.15, 0.002);
    merge(sh, bp);
    const trig = (x, y, z) => skin(x, y, z, sdRoundBox(x - s * 0.045, y - 0.031, z + 0.042, 0.013, 0.0068, 0.010, 0.003), 0.0042);
    const tp = simplify(surfaceNets("trigger", trig, [s * 0.045 - 0.018, 0.018, -0.058], [s * 0.045 + 0.018, 0.044, -0.024], 0.0008, BODY, q => [0.25, 0.5]), trig, 0.15, 0.002);
    merge(sh, tp);
  }
  const all = part("controller"); all.nor = []; merge(all, body); merge(all, keys); merge(all, sh);
  const [l, h] = lo3(all), cx = (l[0] + h[0]) / 2, cz = (l[2] + h[2]) / 2;      // origin: the footprint's middle on the desk
  for (let i = 0; i < all.pos.length; i += 3) { all.pos[i] -= cx; all.pos[i + 1] -= l[1]; all.pos[i + 2] -= cz; }
  const [l2, h2] = lo3(all);
  const tris = await writeGLB(`${outDir}/controller.glb`, "controller", {plastic: all}, async (doc, node, acc, tex) => {
    const blob = await contactBlob(), x0 = l2[0] - 0.01, x1 = h2[0] + 0.01, z0 = l2[2] - 0.004, z1 = h2[2] + 0.012, y = 0.0004;
    const smat = doc.createMaterial("controller_contact").setBaseColorFactor([0, 0, 0, 0.5]).setAlphaMode("BLEND").setRoughnessFactor(1).setMetallicFactor(0)
      .setBaseColorTexture(tex("contact_blob", blob, "image/png"));
    const sp = doc.createPrimitive().setAttribute("POSITION", acc("VEC3", new Float32Array([x0, y, z1, x1, y, z1, x1, y, z0, x0, y, z0])))
      .setAttribute("NORMAL", acc("VEC3", new Float32Array([0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0])))
      .setAttribute("TEXCOORD_0", acc("VEC2", new Float32Array([0, 1, 1, 1, 1, 0, 0, 0]))).setIndices(acc("SCALAR", new Uint32Array([0, 1, 2, 0, 2, 3]))).setMaterial(smat);
    node.addChild(doc.createNode("controller_contact").setMesh(doc.createMesh("controller_contact").addPrimitive(sp))); });
  console.log(`controller.glb ${tris} triangles; ${h2.map((x, a) => (x - l2[a]).toFixed(3)).join(" x ")} m`);
}

// =====================================================================================================================
// the monitor (world metres)
// =====================================================================================================================
{
  const MON = {c: [-1.0598, 1.33, -1.18801], ry: 0.10, rx: -0.06, w: 0.64, h: 0.37};      // SURF_monitor (room_clean.glb)
  const DTOP = 0.97, DZ0 = -1.44;
  const BLACK = [0.010, 0.010, 0.011], RIM = [0.030, 0.030, 0.033], HOUSE = [0.014, 0.014, 0.016], SLOT = [0.002, 0.002, 0.002],
    PORT = [0.06, 0.06, 0.065], METAL = [0.11, 0.11, 0.12], GLASS = [0.004, 0.004, 0.005], CABLE = [0.010, 0.010, 0.011];
  const cy = Math.cos(MON.ry), sy = Math.sin(MON.ry), cx = Math.cos(MON.rx), sx = Math.sin(MON.rx);
  const W = ([x, y, z]) => { const y1 = cx * y - sx * z, z1 = sx * y + cx * z;                    // panel -> world (Ry(ry) Rx(rx), YXZ)
    return [MON.c[0] + cy * x + sy * z1, MON.c[1] + y1, MON.c[2] - sy * x + cy * z1]; };
  const Wn = ([x, y, z]) => { const y1 = cx * y - sx * z, z1 = sx * y + cx * z; return [cy * x + sy * z1, y1, -sy * x + cy * z1]; };
  const Ry = ([x, y, z], o) => [o[0] + cy * x + sy * z, o[1] + y, o[2] - sy * x + cy * z];          // stand frame (turned, not tilted)
  // a rounded rectangle, w x h, corner radius r, centred at (0, yc): n points, the same parameter for every size
  const rr = (w, h, r, yc, n = 64) => { const pts = [], per = n / 4;
    for (let q = 0; q < 4; q++) { const [sx2, sy2] = [[1, 1], [-1, 1], [-1, -1], [1, -1]][q];
      for (let i = 0; i < per; i++) { const a = Math.PI / 2 * (q + i / (per - 1));
        pts.push([sx2 * (w / 2 - r) + r * Math.cos(a), yc + sy2 * (h / 2 - r) + r * Math.sin(a)]); } }
    return pts; };
  const plastic = part("monitor"), metal = part("monitor_metal"), glass = part("monitor_glass"); plastic.nor = []; metal.nor = [];
  const L = ([x, y, z]) => { const d = [x - MON.c[0], y - MON.c[1], z - MON.c[2]], x1 = cy * d[0] - sy * d[2], z1 = sy * d[0] + cy * d[2];   // world -> panel
    return [x1, cx * d[1] + sx * z1, -sx * d[1] + cx * z1]; };
  const BZ = 0.006, CHIN = 0.014, OW = MON.w + 2 * BZ, OH = MON.h + BZ + CHIN, OY = (BZ - CHIN) / 2;
  const pc = W([0, 0, -0.02]);                                   // a point inside the panel, for "outward"
  const awayFrom = c0 => q => [q[0] - c0[0], q[1] - c0[1], q[2] - c0[2]];
  // the front slab: the bezel ring (1 mm proud of the glass), the glossy rim, a chamfer to the back
  { const n = 96, lift = (pts, z) => pts.map(([x, y]) => W([x, y, z]));
    const inner = rr(MON.w + 0.0006, MON.h + 0.0006, 0.002, 0, n), front = rr(OW - 0.0016, OH - 0.0016, 0.0062, OY, n), edge = rr(OW, OH, 0.007, OY, n);
    const p = part("bezel"), ring = (pts, z, c, u) => lift(pts, z).map(q => add(p, q, c, [u, 0.5]));
    const a = ring(inner, -0.0010, BLACK, 0.25), b = ring(inner, 0, BLACK, 0.25), cR = ring(front, 0, BLACK, 0.25);
    const d = ring(front, 0, RIM, 0.75), e = ring(edge, -0.0010, RIM, 0.75), f = ring(edge, -0.0105, RIM, 0.75), g = ring(rr(OW - 0.004, OH - 0.004, 0.006, OY, n), -0.0125, HOUSE, 0.25);
    const st = (A, B) => { for (let i = 0; i < n; i++) { const j = (i + 1) % n; p.idx.push(A[i], B[i], B[j], A[i], B[j], A[j]); } };
    st(a, b); st(b, cR); st(d, e); st(e, f);
    const bc = ring(rr(OW - 0.004, OH - 0.004, 0.006, OY, n), -0.0125, HOUSE, 0.25); st(f.map((x, i) => x), g);
    const mid = add(p, W([0, OY, -0.0125]), HOUSE, [0.25, 0.5]); for (let i = 0; i < n; i++) p.idx.push(mid, bc[i], bc[(i + 1) % n]);
    orient(p, q => { const [x, y, z] = L(q);
      if (Math.abs(x) < MON.w / 2 + 0.0006 && Math.abs(y) < MON.h / 2 + 0.0006) return Wn([-x, -y, 0]);   // the opening's wall
      if (z > -0.0004) return Wn([0, 0, 1]);                     // the bezel's face
      if (z < -0.012) return Wn([0, 0, -1]);                     // the back
      return Wn([x, y - OY, 0]); });                             // the rim
    p.nor = null; merge(plastic, p); }
  // the glass behind the live screen quad
  { const p = glass, q = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([a, b]) => add(p, W([a * (MON.w / 2 + 0.0003), b * (MON.h / 2 + 0.0003), -0.0010]), GLASS, [0.75, 0.5]));
    p.idx.push(q[0], q[1], q[2], q[0], q[2], q[3]); orient(p, () => Wn([0, 0, 1])); }
  // the rear housing: tapered, its back a little smaller; vent slots near its top, a port bay low down, the VESA plate
  const HY = -0.035, back = -0.044;
  { const p = part("housing"), n = 64, rings = [[0.47, 0.28, 0.030, -0.0120], [0.455, 0.265, 0.034, -0.030], [0.42, 0.235, 0.040, back]]
      .map(([w, h, r, z]) => rr(w, h, r, HY, n).map(([x, y]) => W([x, y, z])));
    bands(p, rings, HOUSE, 0.25, awayFrom(W([0, HY, -0.02])), false, true);
    p.nor = null; merge(plastic, p); }
  const quad = (p, x0, x1, y0, y1, z, c, u, want) => { const q = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]].map(([x, y]) => add(p, W([x, y, z]), c, [u, 0.5]));
    const s = p.idx.length; p.idx.push(q[0], q[1], q[2], q[0], q[2], q[3]); orient(p, () => want, s); };
  const nb = Wn([0, 0, -1]);
  { const p = part("details");
    for (let row = 0; row < 3; row++) for (let i = 0; i < 16; i++) { const x = -0.165 + i * 0.022, y = HY + 0.085 - row * 0.009;
      quad(p, x, x + 0.015, y, y + 0.0028, back - 0.0004, SLOT, 0.25, nb); }
    quad(p, -0.09, 0.07, HY - 0.103, HY - 0.080, back - 0.0004, SLOT, 0.25, nb);                               // the port bay
    for (let i = 0; i < 5; i++) { const x = -0.08 + i * 0.03; quad(p, x, x + 0.016, HY - 0.096, HY - 0.088, back - 0.0008, PORT, 0.75, nb); }
    const vesa = rr(0.10, 0.10, 0.008, -0.02, 32), r0 = vesa.map(([x, y]) => W([x, y, back])), r1 = vesa.map(([x, y]) => W([x, y, back - 0.004]));
    const s = p.idx.length; bands(p, [r0, r1], RIM, 0.75, awayFrom(W([0, -0.02, back])), false, true);
    p.nor = null; merge(plastic, p); }
  // the stand: hinge, neck, foot (in the stand's turned frame; the neck rises to the hinge behind the VESA plate)
  const hinge = W([0, -0.02, back - 0.012]);
  const SX = hinge[0], SZ = hinge[2], ST = [SX, 0, SZ];            // the stand's origin: under the hinge, on the floor plane
  const toS = ([x, y, z]) => Ry([x, y, z], ST);
  { const p = part("hinge"), n = 20, rings = [-0.036, 0.036].map(x => Array.from({length: n}, (_, i) => { const a = 2 * Math.PI * i / n;
      return toS([x, hinge[1] + 0.012 * Math.sin(a), 0.012 * Math.cos(a)]); }));
    bands(p, rings, METAL, 0.25, q => { const l = [q[0] - SX, q[1] - hinge[1], q[2] - SZ]; const ax = [cy, 0, -sy], d = l[0] * ax[0] + l[2] * ax[2];
      return Math.abs(d) > 0.0355 ? ax.map(v => v * Math.sign(d)) : [l[0] - ax[0] * d, l[1], l[2] - ax[2] * d]; }, true, true);
    p.nor = null; merge(metal, p); }
  { const p = part("neck"), sec = rr(0.066, 0.024, 0.007, 0, 32), nz = -0.014;               // (behind the hinge's axis)
    const at = (y, s = 1, lean = 0) => sec.map(([x, z]) => toS([x * s, y, z * s + nz - lean]));
    const rings = [at(DTOP + 0.009, 1.06, 0.004), at(DTOP + 0.016, 1, 0.002), at(hinge[1] - 0.06), at(hinge[1] + 0.02), at(hinge[1] + 0.030, 0.9)];
    bands(p, rings, METAL, 0.25, q => { const c0 = toS([0, q[1], nz]); return [q[0] - c0[0], q[1] > hinge[1] + 0.029 ? 1 : 0, q[2] - c0[2]]; }, false, true);
    p.nor = null; merge(metal, p);
    // a cable hole through the neck (a dark slot on its back) and the cable's run
    const d = part("hole"), q0 = [[-0.012, hinge[1] - 0.20], [0.012, hinge[1] - 0.20], [0.012, hinge[1] - 0.15], [-0.012, hinge[1] - 0.15]].map(([x, y]) => add(d, toS([x, y, nz - 0.0125]), SLOT, [0.25, 0.5]));
    d.idx.push(q0[0], q0[1], q0[2], q0[0], q0[2], q0[3]); orient(d, () => Ry([0, 0, -1], [0, 0, 0])); d.nor = null; merge(plastic, d); }
  { const p = part("foot"), n = 64, ft = rr(0.25, 0.19, 0.05, 0, n), fz0 = 0.062;            // its middle 6.2 cm in front of the neck
    const at = (s, y) => ft.map(([x, z]) => toS([x * s, y, z * s + fz0]));
    const rings = [at(0.985, DTOP), at(1, DTOP + 0.0015), at(1, DTOP + 0.0068), at(0.985, DTOP + 0.009)];
    bands(p, rings, METAL, 0.25, q => q[1] > DTOP + 0.0085 ? [0, 1, 0] : q[1] < DTOP + 0.0005 ? [0, -1, 0] : [q[0] - toS([0, 0, fz0])[0], 0, q[2] - toS([0, 0, fz0])[2]], true, true);
    p.nor = null; merge(metal, p); }
  // the cable: from the port bay down behind the neck, along the desk to its back edge, over it and down the gap
  { const P0 = W([0.01, HY - 0.095, back - 0.004]), x0 = P0[0] + 0.004;
    const ctrl = [P0, [P0[0], P0[1] - 0.015, P0[2] - 0.020], [x0, hinge[1] - 0.18, SZ - 0.055], [x0, DTOP + 0.005, SZ - 0.075], [x0 - 0.01, DTOP + 0.0034, -1.37],
      [x0 - 0.02, DTOP + 0.0034, -1.425], [x0 - 0.02, DTOP - 0.012, -1.4445], [x0 - 0.02, DTOP - 0.25, -1.4455]];
    const cr = (a, b, c, d, t) => [0, 1, 2].map(k => 0.5 * (2 * b[k] + (-a[k] + c[k]) * t + (2 * a[k] - 5 * b[k] + 4 * c[k] - d[k]) * t * t + (-a[k] + 3 * b[k] - 3 * c[k] + d[k]) * t ** 3));
    const pts = []; for (let s = 0; s + 1 < ctrl.length; s++) for (let t = 0; t < 12; t++)
      pts.push(cr(ctrl[Math.max(0, s - 1)], ctrl[s], ctrl[s + 1], ctrl[Math.min(ctrl.length - 1, s + 2)], t / 12));
    pts.push(ctrl[ctrl.length - 1]);
    const p = part("cable"), R = 0.0032, n = 10, rings = [];
    let prevN = [1, 0, 0];
    for (let i = 0; i < pts.length; i++) { const a = pts[Math.max(0, i - 1)], b = pts[Math.min(pts.length - 1, i + 1)];
      let t = [b[0] - a[0], b[1] - a[1], b[2] - a[2]]; const lt = Math.hypot(...t); t = t.map(v => v / lt);
      let u = [prevN[1] * t[2] - prevN[2] * t[1], prevN[2] * t[0] - prevN[0] * t[2], prevN[0] * t[1] - prevN[1] * t[0]]; const lu = Math.hypot(...u) || 1; u = u.map(v => v / lu);
      const v = [t[1] * u[2] - t[2] * u[1], t[2] * u[0] - t[0] * u[2], t[0] * u[1] - t[1] * u[0]]; prevN = v;
      rings.push(Array.from({length: n}, (_, k) => { const a2 = 2 * Math.PI * k / n; return [0, 1, 2].map(m => pts[i][m] + R * (Math.cos(a2) * u[m] + Math.sin(a2) * v[m])); })); }
    const ids = rings.map(r => r.map(q => add(p, q, CABLE, [0.25, 0.5])));
    for (let k = 0; k + 1 < ids.length; k++) for (let i = 0; i < n; i++) { const j = (i + 1) % n; p.idx.push(ids[k][i], ids[k + 1][i], ids[k + 1][j], ids[k][i], ids[k + 1][j], ids[k][j]); }
    orient(p, q => { let best = 0, bd = 1e9; for (let i = 0; i < pts.length; i++) { const d = Math.hypot(q[0] - pts[i][0], q[1] - pts[i][1], q[2] - pts[i][2]); if (d < bd) { bd = d; best = i; } }
      return [q[0] - pts[best][0], q[1] - pts[best][1], q[2] - pts[best][2]]; });
    p.nor = null; merge(plastic, p); }
  const tris = await writeGLB(`${outDir}/monitor.glb`, "monitor", {plastic, metal, glass});
  const [l, h] = lo3({pos: [...plastic.pos, ...metal.pos]});
  console.log(`monitor.glb ${tris} triangles; box ${l.map(x => x.toFixed(3)).join(",")} .. ${h.map(x => x.toFixed(3)).join(",")}`);
}
