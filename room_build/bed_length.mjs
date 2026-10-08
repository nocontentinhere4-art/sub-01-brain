// The bed at a standard single's length (UK/EU 90 x 190, US twin 75"): web/room/room_clean.glb's mattress was 1.65 m,
// shorter than him (1.75 m). Its head stays against the window wall; the foot grows DL into the room. Run from
// room_build/ (its node_modules):
//   node bed_length.mjs <room_clean.glb> <out.glb>             the bed
//   node bed_length.mjs <props_tripo2.glb> <out.glb> --props   the backpack the page shows (room.html T2_OLD cuts the
//                                                              static room's own out), moved with the foot end
// How the bed grows:
//  - along the bed, x moves by DL * ramp(x): 0 up to XA, 1 from XB, linear in between. XA..XB is exactly the drawer at the
//    foot end (its front, x -1.00..-0.25): that drawer widens; the head end (the headboard, the pillow, the other drawer)
//    stays and the foot end (its board, the corner) moves rigidly;
//  - small parts (a connected piece under SMALL across: a handle, a lock, the backpack, the jeans) move whole, by the
//    shift at their centre, so nothing small is stretched or skewed;
//  - the folded quilt also comes QS toward the pillow at its head end (its turned-back fold, x <= QA), so no strip of bare
//    sheet is left between them for a body to bridge (he lay across 12 cm of it, 4 cm over the sheet, G10d);
//  - the texture keeps its density: each UV island is planar (a linear fit of uv on the island's own positions is off by
//    under 0.001), so a vertex that moves by dx gets uv += (du/dx, dv/dx) * (dx - dx0), its island's rate times how much further
//    it moved than the island's head-most point (an island moved whole keeps its UVs): the stretched span gets
//    more weave and grain at the same scale, not the same weave drawn longer; islands sharing a seam share the rate;
//  - the normals follow the stretch: in the stretched span n -> (nx / k, ny, nz), normalised (k: how much x is stretched
//    there), so the duvet's folds keep their shading; parts moved whole keep theirs.
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { MeshoptDecoder, MeshoptEncoder } from 'meshoptimizer';
await MeshoptDecoder.ready; await MeshoptEncoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({'meshopt.decoder': MeshoptDecoder, 'meshopt.encoder': MeshoptEncoder});
export const DL = 0.25, XA = -1.00, XB = -0.25, QA = -1.05, QS = 0.15, SMALL = 0.20;
const BOX = {x0: -2.0, x1: 0.12, y0: 0.10, y1: 1.32, z0: 0.15, z1: 1.598};   // (the duvet hangs to z 1.59; the wall behind is at 1.6)
const SKIP = new Set(['floor', 'wall', 'rug', 'curtain', 'posters', 'door', 'pinboard']);   // (the room around the bed)
const ramp = x => x <= XA ? 0 : x >= XB ? 1 : (x - XA) / (XB - XA);
const shift = (mat, x) => mat === 'duvet' ? (x <= QA ? -QS : x >= XB ? DL : -QS + (DL + QS) * (x - QA) / (XB - QA)) : DL * ramp(x);
const slope = (mat, x) => mat === 'duvet' ? (x > QA && x < XB ? (DL + QS) / (XB - QA) : 0) : (x > XA && x < XB ? DL / (XB - XA) : 0);
const inBox = (w, B) => w[0] > B.x0 && w[0] < B.x1 && w[1] > B.y0 && w[1] < B.y1 && w[2] > B.z0 && w[2] < B.z1;
// connected pieces of a primitive, its vertices welded by position (a UV or normal seam does not split a piece)
function pieces(prim, n, key) {
  const par = new Int32Array(n).map((_, i) => i), f = i => { while (par[i] !== i) i = par[i] = par[par[i]]; return i; }, u = (a, b) => { a = f(a); b = f(b); if (a !== b) par[a] = b; };
  const first = new Map(); for (let i = 0; i < n; i++) { const k = key(i); if (first.has(k)) u(i, first.get(k)); else first.set(k, i); }
  const I = prim.getIndices(); if (I) for (let t = 0; t < I.getCount(); t += 3) { u(I.getScalar(t), I.getScalar(t + 1)); u(I.getScalar(t), I.getScalar(t + 2)); }
  return Array.from({length: n}, (_, i) => f(i));
}
function moveDoc(doc, sel, d, report, B = BOX, sl = null) {
  for (const node of doc.getRoot().listNodes()) { const m = node.getMesh(); if (!m) continue; const T = node.getTranslation(), S = node.getScale();
    for (const prim of m.listPrimitives()) {
      const mat = prim.getMaterial()?.getName() || '', P = prim.getAttribute('POSITION'), n = P.getCount(), p = [0, 0, 0];
      if (!sel(node, mat)) continue;
      const W = new Float32Array(3 * n); for (let i = 0; i < n; i++) { P.getElement(i, p); W[3 * i] = T[0] + S[0] * p[0]; W[3 * i + 1] = T[1] + S[1] * p[1]; W[3 * i + 2] = T[2] + S[2] * p[2]; }
      const w = i => [W[3 * i], W[3 * i + 1], W[3 * i + 2]];
      const root = pieces(prim, n, i => `${Math.round(W[3 * i] * 2e4)},${Math.round(W[3 * i + 1] * 2e4)},${Math.round(W[3 * i + 2] * 2e4)}`);
      const box = new Map(); for (let i = 0; i < n; i++) { const r = root[i]; let b = box.get(r); if (!b) box.set(r, b = [9, 9, 9, -9, -9, -9]);
        for (let a = 0; a < 3; a++) { b[a] = Math.min(b[a], W[3 * i + a]); b[a + 3] = Math.max(b[a + 3], W[3 * i + a]); } }
      // (each UV island's rate along x: uv ~ a x + b y + c z + e on the island's own vertices, kept only where it fits)
      const UV = sl && prim.getAttribute('TEXCOORD_0'), NOR = sl && prim.getAttribute('NORMAL'), rate = new Map();
      if (UV) { const I = prim.getIndices(), par = new Int32Array(n).map((_, i) => i), f = i => { while (par[i] !== i) i = par[i] = par[par[i]]; return i; };
        for (let t = 0; t < I.getCount(); t += 3) { const a = f(I.getScalar(t)), b = f(I.getScalar(t + 1)), c = f(I.getScalar(t + 2)); par[a] = c; par[b] = c; }
        const isl = new Map(); for (let i = 0; i < n; i++) { const r = f(i); (isl.get(r) || isl.set(r, []).get(r)).push(i); }
        const u = [0, 0];
        for (const [r, ids] of isl) { if (ids.length < 4) continue;
          const coef = [], A = Array.from({length: 4}, () => [0, 0, 0, 0]), y = [[0, 0, 0, 0], [0, 0, 0, 0]];
          for (const i of ids) { const v = [W[3 * i], W[3 * i + 1], W[3 * i + 2], 1]; UV.getElement(i, u); for (let a = 0; a < 4; a++) { y[0][a] += v[a] * u[0]; y[1][a] += v[a] * u[1]; for (let b = 0; b < 4; b++) A[a][b] += v[a] * v[b]; } }
          for (let a = 0; a < 4; a++) A[a][a] += 1e-9;
          for (const yy of y) { const m = A.map((row, i) => [...row, yy[i]]);
            for (let c = 0; c < 4; c++) { let pv = c; for (let r2 = c + 1; r2 < 4; r2++) if (Math.abs(m[r2][c]) > Math.abs(m[pv][c])) pv = r2; [m[c], m[pv]] = [m[pv], m[c]];
              for (let r2 = 0; r2 < 4; r2++) if (r2 !== c) { const q = m[r2][c] / m[c][c]; for (let k = c; k < 5; k++) m[r2][k] -= q * m[c][k]; } }
            coef.push(m.map((row, i) => row[4] / row[i])); }
          let e = 0; for (const i of ids) { UV.getElement(i, u); const w0 = [W[3 * i], W[3 * i + 1], W[3 * i + 2]];
            e += (u[0] - (coef[0][0] * w0[0] + coef[0][1] * w0[1] + coef[0][2] * w0[2] + coef[0][3])) ** 2 + (u[1] - (coef[1][0] * w0[0] + coef[1][1] * w0[1] + coef[1][2] * w0[2] + coef[1][3])) ** 2; }
          // (relative to the island's own head-most point: an island moved rigidly keeps its UVs; one from the fixed head end
          // gets exactly the stretch; the shift grows along x, so the smallest is at the island's smallest x)
          let x0 = 9; for (const i of ids) x0 = Math.min(x0, W[3 * i]);
          if (Math.sqrt(e / ids.length) < 0.002) for (const i of ids) rate.set(i, [coef[0][0], coef[1][0], d(mat, x0)]); } }
      let moved = 0, whole = 0, uvs = 0, nors = 0; const seen = new Set();
      for (let i = 0; i < n; i++) { const b = box.get(root[i]), c = [(b[0] + b[3]) / 2, (b[1] + b[4]) / 2, (b[2] + b[5]) / 2];
        const small = Math.max(b[3] - b[0], b[4] - b[1], b[5] - b[2]) < SMALL;
        const at = small ? c : w(i); if (!inBox(at, B)) continue;
        const dx = d(mat, at[0]); if (Math.abs(dx) < 1e-7) continue;
        P.getElement(i, p); p[0] = (W[3 * i] + dx - T[0]) / S[0];
        if (Math.abs(p[0]) > 1) throw new Error(`${mat} vertex ${i} leaves the quantized range`);
        P.setElement(i, p); moved++; if (small && !seen.has(root[i])) { seen.add(root[i]); whole++; }
        if (small) continue;                                   // (moved whole: its texture and shading as they were)
        const r = rate.get(i); if (r && Math.abs(dx - r[2]) > 1e-7) { const u = [0, 0]; UV.getElement(i, u); u[0] += r[0] * (dx - r[2]); u[1] += r[1] * (dx - r[2]); UV.setElement(i, u); uvs++; }
        const k = 1 + sl(mat, at[0]); if (NOR && k !== 1) { const q = [0, 0, 0]; NOR.getElement(i, q); q[0] /= k; const L = Math.hypot(q[0], q[1], q[2]) || 1; NOR.setElement(i, [q[0] / L, q[1] / L, q[2] / L]); nors++; } }
      if (moved) { const r = report[mat] = report[mat] || {moved: 0, small_parts_moved_whole: 0, uv_kept_density: 0, normals_restretched: 0}; r.moved += moved; r.small_parts_moved_whole += whole; r.uv_kept_density += uvs; r.normals_restretched += nors; } } }
}
const [inp, outp, mode] = process.argv.slice(2);
const doc = await io.read(inp), report = {};
if (mode === '--props') {                                    // (one merged mesh: only the backpack's piece is in this box)
  const PACK = {x0: -0.21, x1: 0.20, y0: 0.15, y1: 0.72, z0: 1.00, z1: 1.48};
  moveDoc(doc, () => true, () => DL, report, PACK);
} else {
  moveDoc(doc, (node, mat) => node.getName() === 'room_static' && !SKIP.has(mat), shift, report, BOX, slope);
  // (the decals on the bed: the drawers' lock rings; not the scuffs on the floor round it, y under 0.17)
  moveDoc(doc, node => node.getName() === 'decals', shift, report, {...BOX, y0: 0.17});
}
await io.write(outp, doc);
console.log(JSON.stringify(report));
