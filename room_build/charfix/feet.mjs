// v5's feet: white socks in black slides, transplanted from the owner's Tripo reference (preview/char-owner-tripo,
// cut down to its feet by room_build/charfix/ref_feet.mjs -> room_build/charfix/ref_feet.glb).
//
//   node room_build/charfix/feet.mjs <in.glb> <out.glb> [--ref room_build/charfix/ref_feet.glb] [--debug dir] [--report out.json]
//
// Input: v5 as web/room/char_v5.glb has it (or after another charfix script: only the feet and ankles are touched).
//   - the body mesh (the biggest skinned mesh) loses every triangle of its old socked feet under the trouser hem;
//   - the mesh "slides" is rebuilt from the reference's slides (strap and sole, closed: a footbed and the strap's
//     underside), and a new mesh "socks" is the reference's socks (heel tube and toe cap, closed under the strap and
//     the foot). The page's mechanism is unchanged: boy_mh.js hides the meshes named /slide/ in bed and parks a copy
//     of them by the bed; the socks stay on him (barefoot in bed = in his socks).
// How the parts are made, per foot, in the reference's own space:
//   1. a darkness field (the base colour at each vertex, smoothed over the surface) splits the surface along its 0.5
//      contour: sock (white) and slide (dark), with one shared boundary (no gap, no overlap where they meet); the
//      trouser cuff (dark, not reaching the floor) is dropped;
//   2. the sock's two lower boundaries (round the heel and the back edge of the strap; round the toes and the strap's
//      front edge) are bridged by a tube (cylindrical coordinates round the foot's long axis, each ring between the two
//      loops), kept 2.5 mm under the strap and on the footbed: the sock's hidden part. The slide's footbed and strap
//      underside are the same tube 0.4 mm further out (so the sock never enters the slide);
//   3. each foot is placed on v5's (the old slides' footprint: direction, length, centre; soles on y = 0), and the
//      sock's top is drawn into v5's trouser cuff (2 mm inside the hem, extended 2.5 cm up inside the leg);
//   4. skin weights: a smooth field over v5's vertices of the old feet, slides and hem (gaussian, sigma 1.2 cm, top 4
//      bones), one set per position, so the sock and the slide over it move together.
// The reference's texture charts come in one 2048² atlas (base colour and normal), shared by both new meshes.
import {NodeIO, Document} from "@gltf-transform/core";
import {ALL_EXTENSIONS} from "@gltf-transform/extensions";
import {MeshoptDecoder, MeshoptEncoder} from "meshoptimizer";
import sharp from "sharp";
import {writeFileSync, mkdirSync} from "node:fs";
import {fileURLToPath} from "node:url";
import path from "node:path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2), opt = k => { const i = args.indexOf(k); return i >= 0 ? args.splice(i, 2)[1] : null; };
const REF = opt("--ref") || path.join(HERE, "ref_feet.glb"), DEBUG = opt("--debug"), REPORT = opt("--report");
const [SRC, DST] = args;
if (!SRC || !DST) { console.error("usage: feet.mjs <in.glb> <out.glb> [--ref ref_feet.glb] [--debug dir] [--report out.json]"); process.exit(1); }

const T_STRAP = 0.0025, GAP = 0.0004, NTH = 72, NRING = 14, HEM_IN = 0.002, SOCK_UP = 0.025;

await MeshoptDecoder.ready; await MeshoptEncoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({"meshopt.decoder": MeshoptDecoder, "meshopt.encoder": MeshoptEncoder});

// ---------------------------------------------------------------- small vector helpers
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]], add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const mul = (a, s) => [a[0] * s, a[1] * s, a[2] * s], dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const len = a => Math.hypot(a[0], a[1], a[2]), norm = a => mul(a, 1 / (len(a) || 1)), lerp = (a, b, t) => add(a, mul(sub(b, a), t));
const smooth = (e0, e1, x) => { const t = Math.min(1, Math.max(0, (x - e0) / (e1 - e0))); return t * t * (3 - 2 * t); };

// a triangle soup with per-corner attributes: {pos: [[x,y,z]...], uv: [[u,v]...], tri: [[a,b,c]...]}
const mesh = () => ({pos: [], uv: [], tri: []});
const addV = (m, p, u) => (m.pos.push(p), m.uv.push(u), m.pos.length - 1);
// vertices welded by position (ids per vertex), for topology
function weld(m, eps = 1e-6) {
  const key = new Map(), id = new Int32Array(m.pos.length); let n = 0;
  m.pos.forEach((p, i) => { const k = p.map(x => Math.round(x / eps)).join(","); let w = key.get(k); if (w === undefined) key.set(k, w = n++); id[i] = w; });
  return {id, n};
}
// boundary edges (welded): Map "a,b" directed as in its one triangle
function openEdges(m, W = weld(m)) {
  const E = new Map();
  for (const t of m.tri) for (let e = 0; e < 3; e++) { const a = W.id[t[e]], b = W.id[t[(e + 1) % 3]]; if (a === b) continue;
    const k = a < b ? a + "," + b : b + "," + a; const c = E.get(k); if (c) c.n++; else E.set(k, {n: 1, a, b, va: t[e], vb: t[(e + 1) % 3]}); }
  return [...E.values()].filter(e => e.n === 1);
}
// boundary loops: arrays of vertex indices (one representative per welded vertex), in the triangles' direction
function loops(m, W = weld(m)) {
  const next = new Map(), rep = new Map();
  for (const e of openEdges(m, W)) { next.set(e.a, e.b); rep.set(e.a, e.va); rep.set(e.b, e.vb); }
  const seen = new Set(), out = [];
  for (const s of next.keys()) { if (seen.has(s)) continue; const L = []; let c = s;
    while (c !== undefined && !seen.has(c)) { seen.add(c); L.push(rep.get(c)); c = next.get(c); }
    out.push(L); }
  return out;
}
function components(m, W = weld(m)) {          // triangle components (through welded vertices)
  const par = new Int32Array(W.n).map((_, i) => i), f = x => { while (par[x] !== x) x = par[x] = par[par[x]]; return x; };
  for (const t of m.tri) { const a = f(W.id[t[0]]); par[f(W.id[t[1]])] = a; par[f(W.id[t[2]])] = a; }
  const comp = new Map(); m.tri.forEach((t, i) => { const r = f(W.id[t[0]]); if (!comp.has(r)) comp.set(r, []); comp.get(r).push(i); });
  return [...comp.values()];
}
const subset = (m, tris) => { const o = mesh(), map = new Map();
  for (const ti of tris) o.tri.push(m.tri[ti].map(i => { let j = map.get(i); if (j === undefined) { map.set(i, j = addV(o, m.pos[i], m.uv[i])); } return j; }));
  return o; };
const merge = (...ms) => { const o = mesh(); for (const m of ms) { const b = o.pos.length; o.pos.push(...m.pos); o.uv.push(...m.uv); for (const t of m.tri) o.tri.push(t.map(i => i + b)); } return o; };
const triNormal = (m, t) => cross(sub(m.pos[t[1]], m.pos[t[0]]), sub(m.pos[t[2]], m.pos[t[0]]));

// cut a mesh along the 0.5 contour of a per-vertex field: returns [below, above] (field < 0.5, >= 0.5), sharing the
// contour's vertices (positions identical: the cut point on an edge depends only on the edge)
function isoCut(m, f, lv = 0.5) {
  const lo = mesh(), hi = mesh(), mapL = new Map(), mapH = new Map(), cut = new Map();
  const take = (o, map, i) => { let j = map.get(i); if (j === undefined) map.set(i, j = addV(o, m.pos[i], m.uv[i])); return j; };
  const cutPt = (a, b) => { const k = a < b ? a + "," + b : b + "," + a; let c = cut.get(k);
    if (!c) { const t = (lv - f[a]) / (f[b] - f[a]); c = {p: lerp(m.pos[a], m.pos[b], t), u: [m.uv[a][0] + (m.uv[b][0] - m.uv[a][0]) * t, m.uv[a][1] + (m.uv[b][1] - m.uv[a][1]) * t]}; cut.set(k, c); }
    return c; };
  const cutV = (o, cmap, a, b) => { const k = (a < b ? a + "," + b : b + "," + a); let j = cmap.get("c" + k); if (j === undefined) { const c = cutPt(a, b); cmap.set("c" + k, j = addV(o, c.p, c.u)); } return j; };
  for (const t of m.tri) {
    const s = t.map(i => f[i] >= lv);
    const nh = s.filter(Boolean).length;
    if (nh === 0) { lo.tri.push(t.map(i => take(lo, mapL, i))); continue; }
    if (nh === 3) { hi.tri.push(t.map(i => take(hi, mapH, i))); continue; }
    // rotate so that t[0] is the odd one out
    let r = 0;                                   // the single vertex on its own side
    for (let k = 0; k < 3; k++) { const odd = nh === 1 ? s[k] : !s[k]; if (odd) r = k; }
    const a = t[r], b = t[(r + 1) % 3], c = t[(r + 2) % 3];
    const [A, Am] = s[r] ? [hi, mapH] : [lo, mapL], [Bo, Bm] = s[r] ? [lo, mapL] : [hi, mapH];
    const ab1 = cutV(A, Am, a, b), ac1 = cutV(A, Am, a, c);
    A.tri.push([take(A, Am, a), ab1, ac1]);
    const ab2 = cutV(Bo, Bm, a, b), ac2 = cutV(Bo, Bm, a, c), bb = take(Bo, Bm, b), cc = take(Bo, Bm, c);
    Bo.tri.push([ab2, bb, cc], [ab2, cc, ac2]);
  }
  return [lo, hi];
}

// ray (o, d unit) against a triangle list: nearest positive t
function rayHit(m, tris, o, d) {
  let best = Infinity;
  for (const t of tris) {
    const p0 = m.pos[t[0]], e1 = sub(m.pos[t[1]], p0), e2 = sub(m.pos[t[2]], p0), h = cross(d, e2), a = dot(e1, h);
    if (Math.abs(a) < 1e-12) continue;
    const fI = 1 / a, s = sub(o, p0), u = fI * dot(s, h); if (u < 0 || u > 1) continue;
    const q = cross(s, e1), v = fI * dot(d, q); if (v < 0 || u + v > 1) continue;
    const tt = fI * dot(e2, q); if (tt > 1e-7 && tt < best) best = tt;
  }
  return best;
}

function ptTri(p, a, b, c) {             // distance from p to the triangle abc
  const ab = sub(b, a), ac = sub(c, a), ap = sub(p, a), d1 = dot(ab, ap), d2 = dot(ac, ap);
  if (d1 <= 0 && d2 <= 0) return len(ap);
  const bp = sub(p, b), d3 = dot(ab, bp), d4 = dot(ac, bp); if (d3 >= 0 && d4 <= d3) return len(bp);
  const vc = d1 * d4 - d3 * d2; if (vc <= 0 && d1 >= 0 && d3 <= 0) return len(sub(p, add(a, mul(ab, d1 / (d1 - d3)))));
  const cp = sub(p, c), d5 = dot(ab, cp), d6 = dot(ac, cp); if (d6 >= 0 && d5 <= d6) return len(cp);
  const vb = d5 * d2 - d1 * d6; if (vb <= 0 && d2 >= 0 && d6 <= 0) return len(sub(p, add(a, mul(ac, d2 / (d2 - d6)))));
  const va = d3 * d6 - d5 * d4; if (va <= 0 && d4 - d3 >= 0 && d5 - d6 >= 0) return len(sub(p, add(b, mul(sub(c, b), (d4 - d3) / ((d4 - d3) + (d5 - d6))))));
  const dn = 1 / (va + vb + vc); return len(sub(p, add(a, add(mul(ab, vb * dn), mul(ac, vc * dn)))));
}
// the nearest distance from p to mesh b (triangles within 2 cm)
function nearDist(b, p, R = 0.02) { let best = Infinity;
  for (const t of b.tri) { const A = b.pos[t[0]]; if (Math.abs(A[0] - p[0]) > R || Math.abs(A[1] - p[1]) > R || Math.abs(A[2] - p[2]) > R) continue;
    best = Math.min(best, ptTri(p, A, b.pos[t[1]], b.pos[t[2]])); } return best; }

// the vertices of a inside the closed mesh b (a +y ray crosses b an odd number of times); a's vertices on b's surface
// (the shared seam) do not count
function insideOf(a, b) {
  const C = 0.005, G = new Map(), keys = new Set(b.pos.map(p => p.map(x => Math.round(x * 1e6)).join(",")));
  b.tri.forEach((t, i) => { const P = t.map(j => b.pos[j]);
    for (let x = Math.floor(Math.min(P[0][0], P[1][0], P[2][0]) / C); x <= Math.floor(Math.max(P[0][0], P[1][0], P[2][0]) / C); x++)
      for (let z = Math.floor(Math.min(P[0][2], P[1][2], P[2][2]) / C); z <= Math.floor(Math.max(P[0][2], P[1][2], P[2][2]) / C); z++) { const k = x + "," + z; (G.get(k) || G.set(k, []).get(k)).push(i); } });
  const out = [];
  for (const p of a.pos) { if (keys.has(p.map(x => Math.round(x * 1e6)).join(","))) continue;
    let n = 0; for (const ti of G.get(Math.floor(p[0] / C) + "," + Math.floor(p[2] / C)) || []) if (rayHit(b, [b.tri[ti]], p, [0, 1, 0]) < Infinity) n++;
    if (n % 2) out.push(p); }
  return out;
}

// ---------------------------------------------------------------- the reference's feet
async function loadRef() {
  const doc = await io.read(REF), p = doc.getRoot().listMeshes()[0].listPrimitives()[0], mat = p.getMaterial();
  const P = p.getAttribute("POSITION").getArray(), U = p.getAttribute("TEXCOORD_0").getArray(), I = p.getIndices().getArray();
  const m = mesh(); for (let i = 0; i < P.length / 3; i++) addV(m, [P[3 * i], P[3 * i + 1], P[3 * i + 2]], [U[2 * i], U[2 * i + 1]]);
  for (let t = 0; t < I.length; t += 3) m.tri.push([I[t], I[t + 1], I[t + 2]]);
  const col = await sharp(Buffer.from(mat.getBaseColorTexture().getImage())).removeAlpha().raw().toBuffer({resolveWithObject: true});
  return {m, color: mat.getBaseColorTexture().getImage(), normal: mat.getNormalTexture().getImage(), px: col};
}
const lum = (px, u, v) => { const {data, info} = px, W = info.width, H = info.height; let s = 0, n = 0;
  for (let dy = -2; dy <= 2; dy += 2) for (let dx = -2; dx <= 2; dx += 2) {
    const x = Math.min(W - 1, Math.max(0, Math.floor(u * W) + dx)), y = Math.min(H - 1, Math.max(0, Math.floor(v * H) + dy)), k = (y * W + x) * info.channels;
    s += (data[k] + data[k + 1] + data[k + 2]) / 765; n++; }
  return s / n; };

// one foot of the reference (its triangles) -> {sock, slide, loops, frame}
function refFoot(m, px) {
  const W = weld(m), nW = W.n;
  // darkness per welded vertex, smoothed over the surface
  let d = new Float32Array(nW), cnt = new Float32Array(nW);
  m.pos.forEach((p, i) => { d[W.id[i]] += 1 - lum(px, m.uv[i][0], m.uv[i][1]); cnt[W.id[i]]++; });
  for (let i = 0; i < nW; i++) d[i] /= cnt[i];
  const nb = Array.from({length: nW}, () => new Set());
  for (const t of m.tri) for (let e = 0; e < 3; e++) { const a = W.id[t[e]], b = W.id[t[(e + 1) % 3]]; nb[a].add(b); nb[b].add(a); }
  const nbA = nb.map(s => [...s]);
  for (let it = 0; it < 12; it++) { const n = new Float32Array(nW); for (let i = 0; i < nW; i++) { let s = d[i]; for (const j of nbA[i]) s += d[j]; n[i] = s / (nbA[i].length + 1); } d = n; }
  // dark (>= 0.5) / white; small islands of either take the other side's value (0.2 / 0.8)
  for (let pass = 0; pass < 2; pass++) {
    const cls = i => d[i] >= 0.5, seen = new Uint8Array(nW);
    for (let s = 0; s < nW; s++) { if (seen[s]) continue; const c = cls(s), q = [s], comp = []; seen[s] = 1;
      while (q.length) { const i = q.pop(); comp.push(i); for (const j of nbA[i]) if (!seen[j] && cls(j) === c) { seen[j] = 1; q.push(j); } }
      if (comp.length < 400) for (const i of comp) d[i] = c ? 0.2 : 0.8; }
  }
  const f = new Float32Array(m.pos.length); m.pos.forEach((_, i) => { f[i] = d[W.id[i]]; });
  let [sock, dark] = isoCut(m, f);
  // the dark parts that do not reach the floor are the trouser cuff: dropped
  dark = subset(dark, components(dark).filter(c => Math.min(...c.flatMap(t => dark.tri[t].map(i => dark.pos[i][1]))) < 0.03).flat());
  // the sock: its parts that reach under the cuff's lowest point (the cuff's own white piping and such go)
  sock = subset(sock, components(sock).filter(c => c.length > 50 && Math.min(...c.flatMap(t => sock.tri[t].map(i => sock.pos[i][1]))) < 0.06).flat());
  return {sock, dark};
}

// the foot's frame from its sole (the slide's vertices under 1 cm): long axis (toward +fwd), centre, length
function soleFrame(pts, fwd) {
  let cx = 0, cz = 0; for (const p of pts) { cx += p[0]; cz += p[2]; } cx /= pts.length; cz /= pts.length;
  let xx = 0, xz = 0, zz = 0; for (const p of pts) { const x = p[0] - cx, z = p[2] - cz; xx += x * x; xz += x * z; zz += z * z; }
  const th = 0.5 * Math.atan2(2 * xz, xx - zz); let a = [Math.cos(th), 0, Math.sin(th)];
  if (dot(a, fwd) < 0) a = mul(a, -1);
  const l = [-a[2], 0, a[0]];                 // a rotated +90 deg about y... (x,z) -> (-z, x)
  let lo = Infinity, hi = -Infinity, wlo = Infinity, whi = -Infinity;
  for (const p of pts) { const r = [p[0] - cx, 0, p[2] - cz], s = dot(r, a), w = dot(r, l); lo = Math.min(lo, s); hi = Math.max(hi, s); wlo = Math.min(wlo, w); whi = Math.max(whi, w); }
  const c = add([cx, 0, cz], add(mul(a, (lo + hi) / 2), mul(l, (wlo + whi) / 2)));
  return {a, l, c, L: hi - lo, Wd: whi - wlo};
}

// the hidden part of the foot: a tube from the heel loop to the toe loop. The two loops are matched by arc length
// between four anchors each (the lowest point at the heel / the toes, the two sides at the axis' height, the top), so
// that the ring at s (0 at the heel loop, 1 at the toe loop) is the straight blend of the two, then pushed up under the
// strap (2.5 mm under it) and kept on the footbed
function bridge(sock, dark, heel, toe, fr) {
  const yc = [...heel, ...toe].map(i => sock.pos[i][1]).sort((a, b) => a - b), yFb = yc[Math.floor(yc.length * 0.1)];
  const yTop = Math.max(...dark.pos.map(p => p[1])), y0 = yFb + 0.4 * (yTop - yFb);
  const up = [0, 1, 0], o = add(fr.c, [0, y0, 0]);
  const cyl = p => { const r = sub(p, o), x = dot(r, fr.a), w = dot(r, fr.l), h = r[1]; return {x, w, h, th: Math.atan2(h, w), r: Math.hypot(h, w)}; };
  const at = (x, th, r) => add(add(o, mul(fr.a, x)), add(mul(fr.l, r * Math.cos(th)), mul(up, r * Math.sin(th))));
  const unwrap = L => { const th = L.map(i => cyl(sock.pos[i]).th);
    for (let i = 1; i < th.length; i++) { while (th[i] - th[i - 1] > Math.PI) th[i] -= 2 * Math.PI; while (th[i] - th[i - 1] < -Math.PI) th[i] += 2 * Math.PI; }
    return th; };
  // a loop, turned to run the way the angle grows (+w -> up -> -w -> down), started at its bottom anchor; with its
  // four anchors and a sampler by the parameter u in [0, 4) (anchor k at u = k: bottom, +w side, top, -w side)
  const prep = (L0, isHeel) => {
    let L = L0.slice(), th = unwrap(L); if (th[th.length - 1] < th[0]) L.reverse();
    const C = L.map(i => cyl(sock.pos[i])), n = L.length;
    // bottom: the end of the foot (lowest x at the heel, highest at the toes) among the points under the axis
    let b = 0; for (let i = 0; i < n; i++) if (C[i].h < 0 && (isHeel ? C[i].x < C[b].x : C[i].x > C[b].x)) b = i;
    L = [...L.slice(b), ...L.slice(0, b)]; const P = L.map(i => sock.pos[i]), Cc = L.map(i => cyl(sock.pos[i]));
    // the sides: the first crossing of the axis' height after the bottom (+w side), the last one before it (-w side)
    let s1 = -1, s3 = -1; for (let i = 1; i < n; i++) { if (Cc[i - 1].h < 0 && Cc[i].h >= 0 && s1 < 0) s1 = i; if (Cc[i - 1].h >= 0 && Cc[i].h < 0) s3 = i; }
    let s2 = s1; for (let i = s1; i < s3; i++) if (Cc[i].h > Cc[s2].h) s2 = i;   // the top
    const anchors = [0, s1, s2, s3, n];
    const cum = [0]; for (let i = 1; i <= n; i++) cum.push(cum[i - 1] + len(sub(P[i % n], P[i - 1])));
    const uOf = new Float64Array(n);
    for (let k = 0; k < 4; k++) { const i0 = anchors[k], i1 = anchors[k + 1];
      for (let i = i0; i < i1; i++) uOf[i] = k + (cum[i] - cum[i0]) / Math.max(1e-9, cum[i1] - cum[i0]); }
    const sample = u => { u = ((u % 4) + 4) % 4; let i = 0; while (i + 1 < n && uOf[i + 1] <= u) i++;
      const u0 = uOf[i], u1 = i + 1 < n ? uOf[i + 1] : 4; return lerp(P[i], P[(i + 1) % n], u1 > u0 ? (u - u0) / (u1 - u0) : 0); };
    return {L, uOf, sample, ok: s1 > 0 && s3 > s1};
  };
  const H = prep(heel, true), Tt = prep(toe, false);
  if (process.env.LOOPDUMP) for (const [nm, Lp] of [["heel", H], ["toe", Tt]]) { const rows = [];
    for (let q = 0; q < Lp.L.length; q += 6) { const c = cyl(sock.pos[Lp.L[q]]); rows.push(`u ${Lp.uOf[q].toFixed(2)} x ${(c.x * 100).toFixed(1)} w ${(c.w * 100).toFixed(1)} h ${(c.h * 100).toFixed(1)}`); }
    console.log(nm, "y0", y0.toFixed(3), "yFb", yFb.toFixed(3), "\n" + rows.join("\n")); }
  if (!H.ok || !Tt.ok) throw new Error("bridge: a loop without its anchors");
  const allD = dark.tri;
  const NU = NTH, grid = [];
  for (let j = 1; j < NRING; j++) { const s = j / NRING, ring = [];
    for (let k = 0; k < NU; k++) { const u = 4 * k / NU; let p = lerp(H.sample(u), Tt.sample(u), s);
      const c = cyl(p), dir = norm(sub(at(c.x, c.th, 1), at(c.x, c.th, 0)));
      const hit = rayHit(dark, allD, at(c.x, c.th, 0), dir);
      let r = c.r;
      if (hit < Infinity && c.h > 0) r = hit - T_STRAP;             // over the axis: snug under the strap
      else if (hit < Infinity) r = Math.min(r, hit - T_STRAP);       // (under it: inside the sole's rim)
      p = at(c.x, c.th, r); if (p[1] < yFb) p[1] = yFb;
      ring.push(p); }
    grid.push(ring); }
  // smooth the inner rings (the clamps leave steps), the loops' neighbours stay
  for (let it = 0; it < 6; it++) { const g2 = grid.map(r => r.map(p => p.slice()));
    for (let j = 1; j < grid.length - 1; j++) for (let k = 0; k < NU; k++) {
      const q = [grid[j][(k + 1) % NU], grid[j][(k + NU - 1) % NU], grid[j - 1][k], grid[j + 1][k]];
      g2[j][k] = lerp(grid[j][k], mul(q.reduce(add, [0, 0, 0]), 1 / 4), 0.5); if (g2[j][k][1] < yFb) g2[j][k][1] = yFb; }
    grid.splice(0, grid.length, ...g2); }
  // a point back inside the slide's opening (from the axis toward it, short of the slide's surface: 2.5 mm under the
  // strap, 1.5 mm elsewhere)
  const clamp = p => { const c = cyl(p); if (c.r < 1e-6) return p; const dir = norm(sub(at(c.x, c.th, 1), at(c.x, c.th, 0)));
    const hit = rayHit(dark, allD, at(c.x, c.th, 0), dir), m = c.h > 0 ? T_STRAP : 0.0015;
    return hit < Infinity && c.r > hit - m ? at(c.x, c.th, Math.max(0.002, hit - m)) : p; };
  for (const row of grid) for (let k = 0; k < NU; k++) row[k] = clamp(row[k]);
  return {grid, at, cyl, H, T: Tt, yFb, o, fr, NU, clamp};
}

// the tube's triangles: ring rows plus a zip to each loop (the loop's own vertices: shared with the sock and the slide);
// dr pushes the rows out by that much (the slide's side of it)
function tubeMesh(src, B, dr, uvOf) {
  const m = mesh(), G = B.grid, NU = B.NU, rows = [];
  // the slide's side (dr > 0): each ring vertex pushed out along the sock's own normal there (the grid's), so the two
  // stay dr apart everywhere, the sole's flat bottom included
  let off = null;
  if (dr) { off = G.map(r => r.map(() => [0, 0, 0]));
    const P = (j, k) => G[Math.max(0, Math.min(G.length - 1, j))][((k % NU) + NU) % NU];
    for (let j = 0; j < G.length; j++) for (let k = 0; k < NU; k++) {
      let n = cross(sub(P(j, k + 1), P(j, k - 1)), sub(P(j + 1, k), P(j - 1, k)));
      const c = B.cyl(G[j][k]), radial = sub(G[j][k], add(B.o, mul(B.fr.a, c.x)));
      if (dot(n, radial) < 0) n = mul(n, -1);
      off[j][k] = mul(norm(n), dr); } }
  const push = (j, k, p) => off ? add(p, off[j][k]) : p;
  for (let j = 0; j < G.length; j++) rows.push(G[j].map((p, k) => addV(m, push(j, k, p), uvOf((j + 1) / NRING, k / NU))));
  for (let j = 0; j + 1 < rows.length; j++) for (let k = 0; k < NU; k++) { const a = rows[j][k], b = rows[j][(k + 1) % NU], c = rows[j + 1][(k + 1) % NU], d = rows[j + 1][k];
    m.tri.push([a, b, c], [a, c, d]); }
  const zip = (Lp, row, s, flip) => {           // the loop (by its u) against a ring (ring vertex k at u = 4k/NU)
    const n = Lp.L.length, lv = Lp.L.map((i, q) => addV(m, src.pos[i], uvOf(s, Lp.uOf[q] / 4)));
    let i = 0, k = 0;
    while (i < n || k < NU) {
      const ui = i < n ? (i + 1 < n ? Lp.uOf[i + 1] : 4) : Infinity, uk = k < NU ? 4 * (k + 1) / NU : Infinity;
      const t = ui <= uk ? [lv[i % n], lv[(i + 1) % n], row[k % NU]] : [lv[i % n], row[(k + 1) % NU], row[k % NU]];
      if (ui <= uk) i++; else k++;
      m.tri.push(flip ? [t[0], t[2], t[1]] : t);
    }
  };
  zip(B.H, rows[0], 0, false); zip(B.T, rows[rows.length - 1], 1, true);
  return m;
}
// orient a mesh's triangles so that its normals point away from (out = true) / toward the axis
function orientRadial(m, B, out) {          // (the whole tube at once: its winding is consistent)
  let vote = 0;
  for (const t of m.tri) { const n = triNormal(m, t), c = mul(add(add(m.pos[t[0]], m.pos[t[1]]), m.pos[t[2]]), 1 / 3);
    const r = sub(c, B.o), radial = sub(r, mul(B.fr.a, dot(r, B.fr.a))); vote += dot(n, norm(radial)); }
  if ((vote > 0) !== out) for (const t of m.tri) { const s = t[1]; t[1] = t[2]; t[2] = s; }
}

// ---------------------------------------------------------------- debug output (positions + uv + one texture)
async function debugGlb(file, parts, tex) {
  const d = new Document(), buf = d.createBuffer(), sc = d.createScene();
  const t = d.createTexture("c").setImage(tex).setMimeType("image/png"), mt = d.createMaterial("m").setBaseColorTexture(t).setMetallicFactor(0).setRoughnessFactor(0.8);
  for (const [name, m] of Object.entries(parts)) { if (!m.tri.length) continue;
    const pr = d.createPrimitive().setMaterial(mt)
      .setAttribute("POSITION", d.createAccessor().setType("VEC3").setArray(new Float32Array(m.pos.flat())).setBuffer(buf))
      .setAttribute("TEXCOORD_0", d.createAccessor().setType("VEC2").setArray(new Float32Array(m.uv.flat())).setBuffer(buf))
      .setIndices(d.createAccessor().setType("SCALAR").setArray(new Uint32Array(m.tri.flat())).setBuffer(buf));
    sc.addChild(d.createNode(name).setMesh(d.createMesh(name).addPrimitive(pr))); }
  await new NodeIO().write(file, d);
}

// ================================================================ main
const ref = await loadRef();
const feetRef = {}, B_ref = {};
// two swatches of the atlas for the hidden parts: the flattest bright patch (the sock's knit) and the flattest dark one
function swatch(px, bright, S = 96) {
  const {data, info} = px, Wd = info.width, Ch = info.channels; let best = null;
  for (let y = 0; y + S < info.height; y += 16) for (let x = 0; x + S < Wd; x += 16) {
    let s = 0, q = 0, n = 0;
    for (let dy = 0; dy < S; dy += 8) for (let dx = 0; dx < S; dx += 8) { const k = ((y + dy) * Wd + x + dx) * Ch, l = (data[k] + data[k + 1] + data[k + 2]) / 765; s += l; q += l * l; n++; }
    const m = s / n, sd = Math.sqrt(Math.max(0, q / n - m * m)), score = bright ? m - 3 * sd : (1 - m) - 3 * sd;
    if ((bright ? m > 0.7 : m < 0.15) && (!best || score > best.score)) best = {x, y, score}; }
  const A = info.width, f = (s, t) => [(best.x + 4 + t * (S - 8)) / A, (best.y + 4 + s * (S - 8)) / A];
  f.rect = [best.x, best.y, S]; return f;
}
const uvSock = swatch(ref.px, true), uvSlide = swatch(ref.px, false);
for (const side of ["L", "R"]) {           // the reference faces +z: his left foot is on +x
  const sgn = side === "L" ? 1 : -1;
  const part = subset(ref.m, ref.m.tri.map((t, i) => i).filter(i => ref.m.tri[i].every(v => ref.m.pos[v][0] * sgn > 0)));
  const {sock, dark} = refFoot(part, ref.px);
  const Ls = loops(sock).map(L => ({L, y: L.reduce((s, i) => s + sock.pos[i][1], 0) / L.length, n: L.length}));
  console.log(side, "sock", sock.tri.length, "dark", dark.tri.length, "sock loops", Ls.map(l => [l.n, l.y.toFixed(3)]), "dark loops", loops(dark).map(L => L.length));
  const fr = soleFrame(dark.pos.filter(p => p[1] < 0.01), [0, 0, 1]);
  Ls.sort((a, b) => b.y - a.y);
  const top = Ls[0].L, [heel, toe] = Ls.slice(1).map(l => l.L).sort((A, Bq) => dot(sub(sock.pos[A[0]], fr.c), fr.a) - dot(sub(sock.pos[Bq[0]], fr.c), fr.a));
  const B = bridge(sock, dark, heel, toe, fr);
  // the sole of the bridge: lowered wherever the sock's own surface would be under it (inside the slide): the foot
  // rests on the footbed at the arch's height, not on a line from the heel cup's rim to the toes
  for (let it = 0; it < 8; it++) {
    const t2 = tubeMesh(sock, B, GAP, uvSlide), bad = insideOf(sock, merge(dark, t2));
    if (!bad.length) break;
    let moved = 0;
    for (const row of B.grid) for (const p of row) { const c = B.cyl(p); if (c.h >= 0) continue;
      let lo = Infinity; for (const q of bad) if (Math.hypot(q[0] - p[0], q[2] - p[2]) < 0.015 && q[1] < p[1] + 0.002) lo = Math.min(lo, q[1]);
      if (lo < Infinity) { const y = Math.max(0.004, lo - 0.002 - GAP); if (y < p[1]) { p[1] = y; const q = B.clamp(p); p[0] = q[0]; p[1] = q[1]; p[2] = q[2]; moved++; } } }
    console.log(side, "bridge: sock inside the slide", bad.length, "-> lowered", moved);
    if (!moved) break;
  }
  const tube = tubeMesh(sock, B, 0, uvSock), tube2 = tubeMesh(sock, B, GAP, uvSlide);
  orientRadial(tube, B, true); orientRadial(tube2, B, false);
  console.log(side, "frame", fr.a.map(x => x.toFixed(3)), "L", fr.L.toFixed(3), "W", fr.Wd.toFixed(3), "yFb", B.yFb.toFixed(3), "tube", tube.tri.length,
    "sock+tube open edges", openEdges(merge(sock, tube)).length, "slide+tube2 open", openEdges(merge(dark, tube2)).length);
  feetRef[side] = {sock, dark, Ls, fr, B, tube, tube2, top, heel, toe}; B_ref[side] = B;
  if (DEBUG) writeFileSync(path.join(DEBUG, `parts_${side}.json`), JSON.stringify({fr, o: B.o, S: {p: sock.pos, t: sock.tri}, D: {p: dark.pos, t: dark.tri}, I: {p: tube.pos, t: tube.tri}, I2: {p: tube2.pos, t: tube2.tri}}));
  if (DEBUG) await debugGlb(path.join(DEBUG, `bridge_${side}.glb`), {sock, dark, tube, tube2}, ref.color);
  if (DEBUG) { mkdirSync(DEBUG, {recursive: true}); await debugGlb(path.join(DEBUG, `ref_${side}.glb`), {sock, dark}, ref.color); }
}

// ---------------------------------------------------------------- v5
const doc = await io.read(SRC), root = doc.getRoot();
const skinned = root.listNodes().filter(n => n.getSkin() && n.getMesh());
const slideNode = skinned.find(n => /slide/i.test(n.getName()) || /slide/i.test(n.getMesh().getName()));
const bodyNode = skinned.filter(n => n !== slideNode).sort((a, b) => b.getMesh().listPrimitives()[0].getAttribute("POSITION").getCount() - a.getMesh().listPrimitives()[0].getAttribute("POSITION").getCount())[0];
const mat4 = (a, b) => { const o = new Array(16).fill(0); for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) for (let k = 0; k < 4; k++) o[j * 4 + i] += a[k * 4 + i] * b[j * 4 + k]; return o; };
const xf = (m, p) => [m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12], m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13], m[2] * p[0] + m[6] * p[1] + m[10] * p[2] + m[14]];
const inv4 = m => { // affine inverse (3x3 + translation)
  const a = m[0], b = m[4], c = m[8], d = m[1], e = m[5], f = m[9], g = m[2], h = m[6], i = m[10];
  const A = e * i - f * h, B = -(d * i - f * g), C = d * h - e * g, det = a * A + b * B + c * C;
  const r = [A / det, B / det, C / det, 0, -(b * i - c * h) / det, (a * i - c * g) / det, -(a * h - b * g) / det, 0, (b * f - c * e) / det, -(a * f - c * d) / det, (a * e - b * d) / det, 0, 0, 0, 0, 1];
  const t = xf(r, [m[12], m[13], m[14]]); r[12] = -t[0]; r[13] = -t[1]; r[14] = -t[2]; return r; };
// a skinned node's mesh space -> the rest pose (joint world x inverse bind: the same for every joint at rest, checked)
function restMatrix(node) {
  const sk = node.getSkin(), J = sk.listJoints(), IBM = sk.getInverseBindMatrices();
  const Ms = J.map((j, k) => mat4(j.getWorldMatrix(), IBM.getElement(k, [])));
  const dev = Math.max(...Ms.map(M => Math.max(...M.map((x, q) => Math.abs(x - Ms[0][q])))));
  if (dev > 1e-3) throw new Error(`${node.getName()}: the rest pose is not the bind pose (${dev})`);
  return Ms[0];
}
const readPrim = (node) => {
  const p = node.getMesh().listPrimitives()[0], M = restMatrix(node), PA = p.getAttribute("POSITION"), n = PA.getCount(), e = [];
  const pos = []; for (let i = 0; i < n; i++) pos.push(xf(M, PA.getElement(i, e)));
  const J = p.getAttribute("JOINTS_0"), Wt = p.getAttribute("WEIGHTS_0"), joints = node.getSkin().listJoints();
  const skin = []; for (let i = 0; i < n; i++) { const j = J.getElement(i, []), w = Wt.getElement(i, []); skin.push(j.map((x, k) => [joints[x], w[k]]).filter(q => q[1] > 0)); }
  return {p, M, pos, skin, n};
};
const body = readPrim(bodyNode), oldSl = slideNode ? readPrim(slideNode) : null;
// the body's colour at a vertex
const bodyTex = await sharp(Buffer.from(body.p.getMaterial().getBaseColorTexture().getImage())).removeAlpha().raw().toBuffer({resolveWithObject: true});
const bUV = body.p.getAttribute("TEXCOORD_0"), bIdx = body.p.getIndices().getArray();
// v5's old feet: under 10.5 cm everything, up to 16 cm the white (the sock under the cuff)
const isFoot = new Uint8Array(body.n);
for (let i = 0; i < body.n; i++) { const y = body.pos[i][1]; if (y < 0.105) isFoot[i] = 1; else if (y < 0.16) { const u = bUV.getElement(i, []); if (lum(bodyTex, u[0], u[1]) > 0.5) isFoot[i] = 1; } }
const delTri = [];
for (let t = 0; t < bIdx.length; t += 3) { const tr = [bIdx[t], bIdx[t + 1], bIdx[t + 2]], nf = tr.filter(i => isFoot[i]).length;
  if (nf === 3) { delTri.push(t / 3); continue; }
  if (nf === 0) continue;                       // (a triangle on the hem's edge goes when its middle is the sock's white)
  const u = [0, 1].map(k => tr.reduce((s, i) => s + bUV.getElement(i, [])[k], 0) / 3);
  if (lum(bodyTex, u[0], u[1]) > 0.5) delTri.push(t / 3); }
console.log("v5 body: delete", delTri.length, "triangles of", bIdx.length / 3);
if (DEBUG) {
  const bm = mesh(); for (let i = 0; i < body.n; i++) addV(bm, body.pos[i], bUV.getElement(i, []));
  const del = new Set(delTri), keepNear = [], gone = [];
  for (let t = 0; t < bIdx.length / 3; t++) { const tr = [bIdx[3 * t], bIdx[3 * t + 1], bIdx[3 * t + 2]]; if (Math.max(...tr.map(i => body.pos[i][1])) > 0.3) continue; (del.has(t) ? gone : keepNear).push(t); }
  bm.tri = []; for (let t = 0; t < bIdx.length; t += 3) bm.tri.push([bIdx[t], bIdx[t + 1], bIdx[t + 2]]);
  const png = await sharp(Buffer.from(body.p.getMaterial().getBaseColorTexture().getImage())).png().toBuffer();
  await debugGlb(path.join(DEBUG, "v5_feet.glb"), {kept: subset(bm, keepNear), gone: subset(bm, gone)}, png);
}

// ---------------------------------------------------------------- per foot: placed on v5's, the sock's top into the cuff
const gone = new Set(delTri), keptV = new Uint8Array(body.n);
for (let t = 0; t < bIdx.length / 3; t++) if (!gone.has(t)) { keptV[bIdx[3 * t]] = keptV[bIdx[3 * t + 1]] = keptV[bIdx[3 * t + 2]] = 1; }
const NPHI = 48, phiBin = (c, p) => { const a = Math.atan2(p[2] - c[2], p[0] - c[0]); return Math.min(NPHI - 1, Math.floor((a + Math.PI) / (2 * Math.PI) * NPHI)); };
const phiDir = k => { const a = -Math.PI + (k + 0.5) * 2 * Math.PI / NPHI; return [Math.cos(a), 0, Math.sin(a)]; };
const fillBins = A => { for (let it = 0; it < NPHI; it++) for (let k = 0; k < NPHI; k++) if (!isFinite(A[k])) { const a = A[(k + 1) % NPHI], b = A[(k + NPHI - 1) % NPHI]; if (isFinite(a) && isFinite(b)) A[k] = (a + b) / 2; else if (isFinite(a)) A[k] = a; else if (isFinite(b)) A[k] = b; } return A; };
const binAt = (A, c, p) => { const a = Math.atan2(p[2] - c[2], p[0] - c[0]), f = (a + Math.PI) / (2 * Math.PI) * NPHI - 0.5, k = Math.floor(f), t = f - k;
  return A[((k % NPHI) + NPHI) % NPHI] * (1 - t) + A[(((k + 1) % NPHI) + NPHI) % NPHI] * t; };
const placed = {}, report = {sides: {}};
for (const side of ["L", "R"]) {
  const zs = side === "L" ? -1 : 1, R = feetRef[side];
  const solePts = (oldSl ? oldSl.pos : body.pos.filter((p, i) => isFoot[i])).filter(p => p[1] < 0.01 && p[2] * zs > 0);
  const frV = soleFrame(solePts, [1, 0, 0]);
  // the cuff: the trousers' dark vertices just over its lowest point; its radius round its centre, per direction
  const trs = []; for (let i = 0; i < body.n; i++) { const p = body.pos[i]; if (!keptV[i] || p[2] * zs <= 0 || p[1] < 0.06 || p[1] > 0.22) continue;
    const u = bUV.getElement(i, []); if (lum(bodyTex, u[0], u[1]) < 0.35) trs.push(p); }
  const ys = trs.map(p => p[1]).sort((a, b) => a - b), yHem = ys[Math.floor(ys.length * 0.01)];
  const band = trs.filter(p => p[1] < yHem + 0.015), cH = [0, 0, 0]; for (const p of band) { cH[0] += p[0] / band.length; cH[2] += p[2] / band.length; }
  const RH = fillBins(new Array(NPHI).fill(Infinity)), YH = fillBins(new Array(NPHI).fill(Infinity));
  for (const p of band) { const k = phiBin(cH, p); RH[k] = Math.min(RH[k], Math.hypot(p[0] - cH[0], p[2] - cH[2])); YH[k] = Math.min(YH[k], p[1]); }
  fillBins(RH); fillBins(YH);
  // the reference's foot onto v5's: same long axis, centre and length; soles on y = 0
  const s = frV.L / R.fr.L;
  const T = p => { const r = sub(p, R.fr.c), x = dot(r, R.fr.a) * s, w = dot(r, R.fr.l) * s;
    return [frV.c[0] + frV.a[0] * x + frV.l[0] * w, p[1] * s, frV.c[2] + frV.a[2] * x + frV.l[2] * w]; };
  const sock = merge(R.sock, R.tube), slide = merge(R.dark, R.tube2);
  sock.pos = sock.pos.map(T); slide.pos = slide.pos.map(T);
  const yMin = Math.min(...slide.pos.map(p => p[1])); for (const m of [sock, slide]) for (const p of m.pos) p[1] -= yMin;
  // the sock's top: drawn to 2 mm inside the cuff over the last 2.5 cm under it (over the strap only)
  const yS = Math.max(...slide.pos.map(p => p[1]));
  const cs = []; for (let b = 0; b < 40; b++) { const y0 = yS + b * 0.003; const pts = sock.pos.filter(p => Math.abs(p[1] - y0) < 0.003);
    cs.push(pts.length ? [pts.reduce((a, p) => a + p[0], 0) / pts.length, 0, pts.reduce((a, p) => a + p[2], 0) / pts.length] : cs[b - 1] || cH); }
  const cAt = y => cs[Math.min(cs.length - 1, Math.max(0, Math.round((y - yS) / 0.003)))];
  for (const p of sock.pos) { if (p[1] <= yS) continue;
    const c0 = cAt(p[1]), yh = binAt(YH, cH, p), w = smooth(Math.max(yS + 0.003, yh - 0.025), yh - 0.002, p[1]); if (w <= 0) continue;
    const c = lerp(c0, cH, w), d = norm([p[0] - c0[0], 0, p[2] - c0[2]]), r = Math.hypot(p[0] - c0[0], p[2] - c0[2]);
    const rT = binAt(RH, cH, add(cH, d)) - HEM_IN, rr = r + (rT - r) * w;
    p[0] = c[0] + d[0] * rr; p[2] = c[2] + d[2] * rr; }
  // ... and on up inside the leg (rings over the top loop, the cuff's radius)
  const topL = R.top, yTop = Math.max(...YH) + SOCK_UP, NR = 5, rings = [topL];
  for (let k = 1; k <= NR; k++) rings.push(topL.map(i => { const p = sock.pos[i], d = norm([p[0] - cH[0], 0, p[2] - cH[2]]), rT = binAt(RH, cH, add(cH, d)) - HEM_IN;
    const y = p[1] + (yTop - p[1]) * k / NR, q = [cH[0] + d[0] * rT, y, cH[2] + d[2] * rT]; return addV(sock, k === 1 ? lerp(p, q, 0.5) : q, sock.uv[i]); }));
  const ext = [];
  for (let k = 0; k < NR; k++) for (let i = 0; i < topL.length; i++) { const a = rings[k][i], b = rings[k][(i + 1) % topL.length], c = rings[k + 1][(i + 1) % topL.length], d = rings[k + 1][i]; ext.push([a, c, b], [a, d, c]); }
  // (the loop runs the way its triangles do; the new band must continue them: test one against the sock's own outward)
  const e0 = openEdges(sock).find(e => topL.includes(e.va) && topL.includes(e.vb));
  const flip = e0 && topL[(topL.indexOf(e0.va) + 1) % topL.length] === e0.vb;   // the sock's triangle has a->b: the band must have b->a
  for (const t of ext) sock.tri.push(flip ? t : [t[0], t[2], t[1]]);
  placed[side] = {sock, slide, frV, s, yHem, cH, R};
  report.sides[side] = {scale: +s.toFixed(4), v5_sole_length_m: +frV.L.toFixed(4), ref_sole_length_m: +R.fr.L.toFixed(4), hem_y_m: +yHem.toFixed(4), strap_top_y_m: +yS.toFixed(4), sock_top_y_m: +yTop.toFixed(4)};
  console.log(side, report.sides[side]);
}
if (DEBUG) {
  const bm = mesh(); for (let i = 0; i < body.n; i++) addV(bm, body.pos[i], bUV.getElement(i, []));
  for (let t = 0; t < bIdx.length; t += 3) if (!gone.has(t / 3) && Math.max(body.pos[bIdx[t]][1], body.pos[bIdx[t + 1]][1], body.pos[bIdx[t + 2]][1]) < 0.4) bm.tri.push([bIdx[t], bIdx[t + 1], bIdx[t + 2]]);
  const png = await sharp(Buffer.from(body.p.getMaterial().getBaseColorTexture().getImage())).png().toBuffer();
  await debugGlb(path.join(DEBUG, "placed_body.glb"), {legs: subset(bm, bm.tri.map((_, i) => i))}, png);
  await debugGlb(path.join(DEBUG, "placed_feet.glb"), {sockL: placed.L.sock, slidesL: placed.L.slide, sockR: placed.R.sock, slidesR: placed.R.slide}, ref.color);
}

// ---------------------------------------------------------------- the atlas: the sock's own charts made all sock
// (the colour split does not follow the triangles exactly: under the sock's triangles the strap's black, the toe's
// dark spot and the seam lines are filled from the sock's white round them; under the slides', the white fringe from
// the slides' black)
async function cleanAtlas(src, sockMeshes, isBad, grow = 0, val = null) {
  const {data, info} = src.raw ? src : await sharp(Buffer.from(src)).removeAlpha().raw().toBuffer({resolveWithObject: true});
  const W = info.width, H = info.height, mask = new Uint8Array(W * H);
  for (const m of sockMeshes) for (const t of m.tri) {          // rasterise each triangle's UVs (+1 px)
    const P = t.map(i => [m.uv[i][0] * W, m.uv[i][1] * H]);
    const x0 = Math.max(0, Math.floor(Math.min(...P.map(p => p[0])) - 1)), x1 = Math.min(W - 1, Math.ceil(Math.max(...P.map(p => p[0])) + 1));
    const y0 = Math.max(0, Math.floor(Math.min(...P.map(p => p[1])) - 1)), y1 = Math.min(H - 1, Math.ceil(Math.max(...P.map(p => p[1])) + 1));
    if ((x1 - x0) * (y1 - y0) > 40000) continue;                // (the swatch-mapped tube: not a chart)
    const ar = (P[1][0] - P[0][0]) * (P[2][1] - P[0][1]) - (P[2][0] - P[0][0]) * (P[1][1] - P[0][1]); if (Math.abs(ar) < 1e-9) continue;
    for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
      const px = x + 0.5, py = y + 0.5;
      const w0 = ((P[1][0] - px) * (P[2][1] - py) - (P[2][0] - px) * (P[1][1] - py)) / ar, w1 = ((P[2][0] - px) * (P[0][1] - py) - (P[0][0] - px) * (P[2][1] - py)) / ar, w2 = 1 - w0 - w1;
      const e = 1.5 / Math.sqrt(Math.abs(ar));
      if (w0 > -e && w1 > -e && w2 > -e) mask[y * W + x] = 1; } }
  const L = val ? k => val(data, k) : k => (data[3 * k] + data[3 * k + 1] + data[3 * k + 2]) / 765;
  const bad = new Uint8Array(W * H); let nBad = 0;
  for (let k = 0; k < W * H; k++) if (mask[k] && isBad(L(k))) { bad[k] = 1; nBad++; }
  // (grown by `grow` px inside the charts: a bad line's own anti-aliased rim, too light to count as bad, is what still
  // showed as a dark seam across the sock in bed, and as the grey nick on the big toe; G23's review)
  for (let g = 0; g < grow; g++) { const add = [];
    for (let k = 0; k < W * H; k++) if (mask[k] && !bad[k]) { const x = k % W, y = (k - x) / W;
      if ((x > 0 && bad[k - 1]) || (x < W - 1 && bad[k + 1]) || (y > 0 && bad[k - W]) || (y < H - 1 && bad[k + W])) add.push(k); }
    for (const k of add) { bad[k] = 1; nBad++; } }
  // fill the bad pixels from their good neighbours, ring by ring
  for (let it = 0; it < 64 && nBad; it++) { const fix = [];
    for (let k = 0; k < W * H; k++) if (bad[k]) { let r = 0, g = 0, b = 0, n = 0; const x = k % W, y = (k - x) / W;
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) { const xx = x + dx, yy = y + dy; if (xx < 0 || yy < 0 || xx >= W || yy >= H) continue; const q = yy * W + xx;
        if (!bad[q] && mask[q] && !isBad(L(q))) { r += data[3 * q]; g += data[3 * q + 1]; b += data[3 * q + 2]; n++; } }
      if (n) fix.push([k, r / n, g / n, b / n]); }
    for (const [k, r, g, b] of fix) { data[3 * k] = r; data[3 * k + 1] = g; data[3 * k + 2] = b; bad[k] = 0; nBad--; } }
  return {data, info, raw: true, mask};
}
// the texels round a mesh's charts (and its swatch) taken from the charts' own edge, `n` rings out: the socks and the
// slides each get their own copy of the atlas, so that no texture filtering (bilinear, the mip levels) brings the
// other's colour over a chart's edge. That bleed was the dark line along the sock's edges, under the strap and round
// the toes, once the slides are hidden (G23's review: the seam across the sock in bed, the grey nick on the big toe)
function bleed(img, mask, rect, n = 16) {
  const {info} = img, W = info.width, H = info.height, data = Buffer.from(img.data), keep = Uint8Array.from(mask);
  const [rx, ry, rs] = rect; for (let y = ry; y < ry + rs; y++) for (let x = rx; x < rx + rs; x++) keep[y * W + x] = 1;
  for (let it = 0; it < n; it++) { const fix = [];
    for (let k = 0; k < W * H; k++) if (!keep[k]) { let r = 0, g = 0, b = 0, c = 0; const x = k % W, y = (k - x) / W;
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) { const xx = x + dx, yy = y + dy; if (xx < 0 || yy < 0 || xx >= W || yy >= H) continue; const q = yy * W + xx;
        if (keep[q]) { r += data[3 * q]; g += data[3 * q + 1]; b += data[3 * q + 2]; c++; } }
      if (c) fix.push([k, r / c, g / c, b / c]); }
    for (const [k, r, g, b] of fix) { data[3 * k] = r; data[3 * k + 1] = g; data[3 * k + 2] = b; keep[k] = 1; } }
  return sharp(data, {raw: {width: W, height: H, channels: 3}}).webp({quality: 90}).toBuffer();
}
const sockClean = await cleanAtlas(ref.color, [feetRef.L.sock, feetRef.R.sock], l => l < 0.6, 4);
const sockColorWebp = await bleed(sockClean, sockClean.mask, uvSock.rect);
const cleaned = await cleanAtlas({...sockClean, data: Buffer.from(sockClean.data)},
  [feetRef.L.dark, feetRef.R.dark], l => l > 0.4, 1);                  // (and the slides' own charts all black)
const colorWebp = await bleed(cleaned, cleaned.mask, uvSlide.rect);
// the normal map too: the strap's edge is baked into it as a relief rim along the sock's charts (lit as a dark line
// across the sock in bed, with the slides hidden; G23's review): inside the sock's charts every texel tilted more than
// ~30 degrees (the knit's own relief stays under it) is filled from the flat knit round it
const nz = (d, k) => d[3 * k + 2] / 127.5 - 1;
const normalClean = await cleanAtlas(ref.normal, [feetRef.L.sock, feetRef.R.sock], z => z < 0.87, 3, nz);
const sockNormalWebp = await bleed(normalClean, normalClean.mask, uvSock.rect);
const normalWebp = await sharp(Buffer.from(ref.normal)).webp({quality: 90}).toBuffer();
console.log("atlas: slides colour", colorWebp.length, "normal", normalWebp.length, "/ socks colour", sockColorWebp.length, "normal", sockNormalWebp.length, "bytes");
if (DEBUG) await sharp(cleaned.data, {raw: {width: cleaned.info.width, height: cleaned.info.height, channels: 3}}).png().toFile(path.join(DEBUG, "atlas_clean.png"));

// ---------------------------------------------------------------- skin weights: from v5's nearest (old feet, slides, hem)
const srcPts = [], srcSkin = [];
for (let i = 0; i < body.n; i++) if (body.pos[i][1] < 0.25) { srcPts.push(body.pos[i]); srcSkin.push(body.skin[i]); }
if (oldSl) for (let i = 0; i < oldSl.n; i++) { srcPts.push(oldSl.pos[i]); srcSkin.push(oldSl.skin[i]); }
const CELL = 0.01, grid = new Map(), gk = (x, y, z) => x + "," + y + "," + z;
srcPts.forEach((p, i) => { const k = gk(Math.floor(p[0] / CELL), Math.floor(p[1] / CELL), Math.floor(p[2] / CELL)); if (!grid.has(k)) grid.set(k, []); grid.get(k).push(i); });
function nearest(p, K = 6) {
  const cx = Math.floor(p[0] / CELL), cy = Math.floor(p[1] / CELL), cz = Math.floor(p[2] / CELL);
  for (let R = 1; R < 8; R++) { const found = [];
    for (let x = cx - R; x <= cx + R; x++) for (let y = cy - R; y <= cy + R; y++) for (let z = cz - R; z <= cz + R; z++) for (const i of grid.get(gk(x, y, z)) || []) found.push([len(sub(srcPts[i], p)), i]);
    if (found.length >= K) { found.sort((a, b) => a[0] - b[0] || a[1] - b[1]); if (found[K - 1][0] <= R * CELL) return found.slice(0, K); } }
  throw new Error("no v5 vertex near " + p);
}
const slideJoints = slideNode.getSkin().listJoints(), jIndex = new Map(slideJoints.map((j, k) => [j, k]));
const weightCache = new Map();
function weightsAt(p) {
  const key = p.map(x => Math.round(x * 1e6)).join(","); let w = weightCache.get(key); if (w) return w;
  const acc = new Map();
  // a smooth field (gaussian, sigma 1.2 cm, over v5's vertices within 3 cm; the nearest ones if none): the sock and
  // the slide over it, a few mm apart, get the same weights to within a hair, so they move together
  const SIG = 0.012, cx = Math.floor(p[0] / CELL), cy = Math.floor(p[1] / CELL), cz = Math.floor(p[2] / CELL); let tot = 0;
  for (let x = cx - 3; x <= cx + 3; x++) for (let y = cy - 3; y <= cy + 3; y++) for (let z = cz - 3; z <= cz + 3; z++) for (const i of grid.get(gk(x, y, z)) || []) {
    const d = len(sub(srcPts[i], p)); if (d > 0.03) continue; const f = Math.exp(-d * d / (2 * SIG * SIG)); tot += f;
    for (const [j, x2] of srcSkin[i]) acc.set(j, (acc.get(j) || 0) + f * x2); }
  if (tot < 1e-6) for (const [d, i] of nearest(p)) { const f = 1 / (d + 1e-4) ** 2; for (const [j, x] of srcSkin[i]) acc.set(j, (acc.get(j) || 0) + f * x); }
  const top = [...acc.entries()].sort((a, b) => b[1] - a[1] || jIndex.get(a[0]) - jIndex.get(b[0])).slice(0, 4), sum = top.reduce((s, q) => s + q[1], 0);
  w = {j: [0, 1, 2, 3].map(k => top[k] ? jIndex.get(top[k][0]) : 0), w: [0, 1, 2, 3].map(k => top[k] ? top[k][1] / sum : 0)};
  if (w.j.some(x => x === undefined)) throw new Error("a v5 bone missing from the slides' skin");
  weightCache.set(key, w); return w;
}

// ---------------------------------------------------------------- the new meshes
function normals(m) {
  const W = weld(m), acc = Array.from({length: W.n}, () => [0, 0, 0]);
  for (const t of m.tri) { const n = triNormal(m, t); for (const i of t) { const a = acc[W.id[i]]; a[0] += n[0]; a[1] += n[1]; a[2] += n[2]; } }
  return m.pos.map((_, i) => norm(acc[W.id[i]]));
}
const sockAll = merge(placed.L.sock, placed.R.sock);
// the slide's tube vertices take the weights of the sock's tube vertices under them (the same rows, the same order)
const slideParts = [], sockTubeW = [];
for (const side of ["L", "R"]) { const P = placed[side], nS = P.R.sock.pos.length, nD = P.R.dark.pos.length;
  for (let i = 0; i < P.R.tube.pos.length; i++) sockTubeW.push(weightsAt(P.sock.pos[nS + i]));
  slideParts.push({m: P.slide, nD, tubeW: sockTubeW.splice(0)}); }
const slideAll = merge(...slideParts.map(q => q.m));
const sockW = sockAll.pos.map(p => weightsAt(p));
const slideW = []; for (const q of slideParts) { for (let i = 0; i < q.m.pos.length; i++) slideW.push(i < q.nD ? weightsAt(q.m.pos[i]) : q.tubeW[i - q.nD]); }

const buf = root.listBuffers()[0];
const acc = (type, arr) => doc.createAccessor().setType(type).setArray(arr).setBuffer(buf);
const color = doc.createTexture("feet_color").setImage(new Uint8Array(colorWebp)).setMimeType("image/webp");
const normalT = doc.createTexture("feet_normal").setImage(new Uint8Array(normalWebp)).setMimeType("image/webp");
const feetMat = doc.createMaterial("feet").setBaseColorTexture(color).setNormalTexture(normalT).setMetallicFactor(0).setRoughnessFactor(0.8);
const sockMat = doc.createMaterial("socks").setBaseColorTexture(doc.createTexture("socks_color").setImage(new Uint8Array(sockColorWebp)).setMimeType("image/webp"))
  .setNormalTexture(doc.createTexture("socks_normal").setImage(new Uint8Array(sockNormalWebp)).setMimeType("image/webp")).setMetallicFactor(0).setRoughnessFactor(0.8);
function primOf(m, W, Minv, mat = feetMat) {
  const nrm = normals(m), n = m.pos.length;
  const P = new Float32Array(n * 3), N = new Float32Array(n * 3), U = new Float32Array(n * 2), J = new Uint8Array(n * 4), Wt = new Float32Array(n * 4);
  const R3 = [Minv[0], Minv[1], Minv[2], Minv[4], Minv[5], Minv[6], Minv[8], Minv[9], Minv[10]];
  for (let i = 0; i < n; i++) { P.set(xf(Minv, m.pos[i]), 3 * i);
    const q = nrm[i], v = norm([R3[0] * q[0] + R3[3] * q[1] + R3[6] * q[2], R3[1] * q[0] + R3[4] * q[1] + R3[7] * q[2], R3[2] * q[0] + R3[5] * q[1] + R3[8] * q[2]]);
    N.set(v, 3 * i); U.set(m.uv[i], 2 * i); J.set(W[i].j, 4 * i); Wt.set(W[i].w, 4 * i); }
  return doc.createPrimitive().setMaterial(mat)
    .setAttribute("POSITION", acc("VEC3", P)).setAttribute("NORMAL", acc("VEC3", N)).setAttribute("TEXCOORD_0", acc("VEC2", U))
    .setAttribute("JOINTS_0", acc("VEC4", J)).setAttribute("WEIGHTS_0", acc("VEC4", Wt)).setIndices(acc("SCALAR", new Uint32Array(m.tri.flat())));
}
const slideInv = inv4(restMatrix(slideNode));
const oldSlideTris = oldSl ? oldSl.p.getIndices().getCount() / 3 : 0;
const slideMesh = slideNode.getMesh(); for (const p of slideMesh.listPrimitives()) { slideMesh.removePrimitive(p); p.dispose(); }
slideMesh.addPrimitive(primOf(slideAll, slideW, slideInv));
const sockMesh = doc.createMesh("socks").addPrimitive(primOf(sockAll, sockW, slideInv, sockMat));
const sockNode = doc.createNode("socks").setMesh(sockMesh).setSkin(slideNode.getSkin());
const parent = slideNode.getParentNode(), scene = root.listScenes().find(s => s.listChildren().includes(slideNode));
if (parent) { parent.removeChild(slideNode); parent.addChild(sockNode).addChild(slideNode); }   // (the slides stay last: the page's skinMesh())
else { scene.removeChild(slideNode); scene.addChild(sockNode).addChild(slideNode); }

// the body without its old feet (its vertices compacted: nothing of the old feet is left to measure)
{
  const p = body.p, keep = new Int32Array(body.n).fill(-1); let n = 0;
  for (let i = 0; i < body.n; i++) if (keptV[i]) keep[i] = n++;
  for (const sem of p.listSemantics()) { const a = p.getAttribute(sem), src = a.getArray(), k = a.getElementSize(), dst = new src.constructor(n * k);
    for (let i = 0; i < body.n; i++) if (keep[i] >= 0) for (let c = 0; c < k; c++) dst[keep[i] * k + c] = src[i * k + c];
    a.setArray(dst); }
  const idx = []; for (let t = 0; t < bIdx.length / 3; t++) if (!gone.has(t)) idx.push(keep[bIdx[3 * t]], keep[bIdx[3 * t + 1]], keep[bIdx[3 * t + 2]]);
  const I = p.getIndices(); I.setArray(new (I.getArray().constructor)(idx));
}
for (const m of root.listMaterials()) if (!m.listParents().some(x => x.propertyType === "Primitive")) m.dispose();
await io.write(DST, doc);
// ---------------------------------------------------------------- checks (rest pose)
// orientation: edges two triangles run the same way; inward faces: a ray from a triangle's middle along its normal
// that leaves through the mesh an odd number of times (3D grid walk); open edges (welded by position)
function checks(m, closeTop) {
  const W = weld(m), E = new Map(); let conflicts = 0;
  for (const t of m.tri) for (let e = 0; e < 3; e++) { const a = W.id[t[e]], b = W.id[t[(e + 1) % 3]], k = a + "," + b; E.set(k, (E.get(k) || 0) + 1); }
  for (const [k, n] of E) if (n > 1) conflicts += n - 1;
  const where = []; for (const [k, n] of E) if (n > 1) { const [a, b] = k.split(",").map(Number); const i = W.id.indexOf(a); where.push(+m.pos[i][1].toFixed(3)); }
  // signed volume (positive: the faces point out), an open top closed by a fan to its loop's centre
  let vol = 0; const tv = (a, b, c) => dot(a, cross(b, c)) / 6;
  for (const t of m.tri) vol += tv(m.pos[t[0]], m.pos[t[1]], m.pos[t[2]]);
  if (closeTop) for (const L of loops(m, W)) { const c = mul(L.reduce((s, i) => add(s, m.pos[i]), [0, 0, 0]), 1 / L.length);
    for (let i = 0; i < L.length; i++) vol += tv(m.pos[L[(i + 1) % L.length]], m.pos[L[i]], c); }
  return {triangles: m.tri.length, open_edges: openEdges(m, W).length, orientation_conflicts: conflicts, conflict_heights_m: where, signed_volume_cm3: +(vol * 1e6).toFixed(1)};
}
report.checks = {socks: checks(sockAll, true), slides: checks(slideAll, false)};
// the socks inside the slides (rest): +y ray parity against the slides, every sock vertex not on the shared seam
{
  const C = 0.005, G = new Map();
  slideAll.tri.forEach((t, i) => { const P = t.map(j => slideAll.pos[j]);
    for (let x = Math.floor(Math.min(P[0][0], P[1][0], P[2][0]) / C); x <= Math.floor(Math.max(P[0][0], P[1][0], P[2][0]) / C); x++)
      for (let z = Math.floor(Math.min(P[0][2], P[1][2], P[2][2]) / C); z <= Math.floor(Math.max(P[0][2], P[1][2], P[2][2]) / C); z++) { const k = x + "," + z; (G.get(k) || G.set(k, []).get(k)).push(i); } });
  const slideKeys = new Set(slideAll.pos.map(p => p.map(x => Math.round(x * 1e6)).join(",")));
  let inside = 0, depth = 0, seam = 0; const insideAt = [], dbgCat = {}, depthHist = {"<0.5mm": 0, "0.5-1mm": 0, "1-2mm": 0, ">2mm": 0};
  for (const p of sockAll.pos) { if (slideKeys.has(p.map(x => Math.round(x * 1e6)).join(","))) { seam++; continue; }
    let n = 0, near = 9;
    for (const ti of G.get(Math.floor(p[0] / C) + "," + Math.floor(p[2] / C)) || []) { const h = rayHit(slideAll, [slideAll.tri[ti]], p, [0, 1, 0]); if (h < Infinity) n++;
      const h2 = rayHit(slideAll, [slideAll.tri[ti]], p, [0, -1, 0]); near = Math.min(near, h, h2); }
    if (n % 2) { inside++; const d3 = nearDist(slideAll, p); depth = Math.max(depth, d3); depthHist[d3 < 0.0005 ? "<0.5mm" : d3 < 0.001 ? "0.5-1mm" : d3 < 0.002 ? "1-2mm" : ">2mm"]++; if (DEBUG) { insideAt.push(p);
      const hits = (G.get(Math.floor(p[0] / C) + "," + Math.floor(p[2] / C)) || []).filter(ti => rayHit(slideAll, [slideAll.tri[ti]], p, [0, 1, 0]) < Infinity);
      const nDl = placed.L.R.dark.tri.length, nL = placed.L.slide.tri.length, nDr = placed.R.R.dark.tri.length;
      const cat = ti => ti < nL ? (ti < nDl ? "L.dark" : "L.tube2") : (ti - nL < nDr ? "R.dark" : "R.tube2");
      const si = sockAll.pos.indexOf(p), nSl = placed.L.R.sock.pos.length, nTl = placed.L.R.tube.pos.length, nAll = placed.L.sock.pos.length;
      const scat = si < nAll ? (si < nSl ? "L.S" : si < nSl + nTl ? "L.tube" : "L.band") : (si - nAll < placed.R.R.sock.pos.length ? "R.S" : si - nAll < placed.R.R.sock.pos.length + placed.R.R.tube.pos.length ? "R.tube" : "R.band");
      let ring = ""; if (/tube/.test(scat)) { const base = scat[0] === "L" ? nSl : nAll + placed.R.R.sock.pos.length; const ti = si - base; ring = ti < (NRING - 1) * NTH ? " ring" + Math.floor(ti / NTH) + " h" + (B_ref[scat[0]].cyl(placed[scat[0]].R.tube.pos[ti]).h > 0 ? "+" : "-") : " zip"; }
      const key = scat + ring + " under " + hits.map(cat).join("+"); dbgCat[key] = (dbgCat[key] || 0) + 1; } } }
  if (DEBUG) { console.log("inside by part", dbgCat);
    const P = placed.L, nS = P.R.sock.tri.length, nT = P.R.tube.tri.length, nD = P.R.dark.tri.length;
    const part = (m, a, b) => subset(m, m.tri.map((_, i) => i).filter(i => i >= a && i < b));
    await debugGlb(path.join(DEBUG, "partsL.glb"), {S: part(P.sock, 0, nS), tube: part(P.sock, nS, nS + nT), dark: part(P.slide, 0, nD), tube2: part(P.slide, nD, 1e9)}, ref.color); }
  // the tube under the strap: each sock vertex and the slide's over it
  let gmin = 9, gmax = 0; for (const side of ["L", "R"]) { const P = placed[side], nS = P.R.sock.pos.length, nD = P.R.dark.pos.length;
    for (let i = 0; i < P.R.tube.pos.length; i++) { const d = len(sub(P.sock.pos[nS + i], P.slide.pos[nD + i])); gmin = Math.min(gmin, d); gmax = Math.max(gmax, d); } }
  // the soles: the slides' vertices within 1 mm of y = 0 (and the lowest), per foot
  const soles = {}; for (const side of ["L", "R"]) { const ys = placed[side].slide.pos.map(p => p[1]); soles[side] = {lowest_mm: +(Math.min(...ys) * 1000).toFixed(2), within_1mm_of_floor: ys.filter(y => y < 0.001).length}; }
  report.sock_slide_rest = {sock_vertices_inside_slides: inside, deepest_mm: +(depth * 1000).toFixed(2), inside_by_depth: depthHist, shared_seam_vertices: seam,
    tube_gap_mm: [+(gmin * 1000).toFixed(3), +(gmax * 1000).toFixed(3)]};
  report.soles_rest = soles;
  if (DEBUG) { const mk = mesh(); for (const p of insideAt) { const a = addV(mk, add(p, [0.002, 0, 0]), [0, 0]), b = addV(mk, add(p, [-0.001, 0, 0.0017]), [0, 0]), c = addV(mk, add(p, [-0.001, 0, -0.0017]), [0, 0]), d = addV(mk, add(p, [0, 0.003, 0]), [0, 0]);
    mk.tri.push([a, b, c], [a, d, b], [b, d, c], [c, d, a]); }
    await debugGlb(path.join(DEBUG, "inside.glb"), {marks: mk, slides: slideAll}, ref.color); }
}
console.log(JSON.stringify({checks: report.checks, sock_slide_rest: report.sock_slide_rest, soles_rest: report.soles_rest}));
report.output = DST;
report.triangles = {body_removed: delTri.length, old_slides: oldSlideTris, socks: sockAll.tri.length, slides: slideAll.tri.length,
  added: sockAll.tri.length + slideAll.tri.length - delTri.length - oldSlideTris};
console.log("wrote", DST, report.triangles);
if (REPORT) writeFileSync(REPORT, JSON.stringify(report, null, 1));
