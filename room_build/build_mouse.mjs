// node build_mouse.mjs <ambientCG Plastic016A 1K folder> ../web/room/mouse.glb
// A generic computer mouse on a cloth pad, modelled in code (original, CC0; no maker's shape, no logo): 12.0 cm long, 6.4 cm
// wide, 4.0 cm high (a full-size body that fills a palm: the hand at the desk grips it; the first one, 3.6 cm with a 2.2 cm
// nose, read as a low pebble a hand could not curl over), its hump in the back third, the two buttons sloping gently to the front with a seam between them, a
// small scroll wheel. Two nodes: "mouse" (origin: the middle of its base; its front, the buttons, towards -z) and
// "mousepad" (origin: the middle of its underside). PBR (desk_pbr.mjs): a satin top, a matte skirt, a glossier wheel; the
// pad a plain rough cloth; a contact shadow under the mouse (its child "mouse_contact").
import { Document, NodeIO } from "@gltf-transform/core";
import { plasticMaps, contactBlob } from "./desk_pbr.mjs";

const L = 0.120, W = 0.064, H = 0.040, BASE = 0.004;
const BODY = [0.018, 0.018, 0.019], SEAM = [0.002, 0.002, 0.002], WHEEL = [0.035, 0.035, 0.038], PAD = [0.016, 0.017, 0.02];

const parts = [];
function part(name){ const p = {name, pos: [], col: [], uv: [], idx: []}; parts.push(p); return p; }
// uv: the shell maps into the matte half of the maps, the wheel into the polished half
const vtx = (p, x, y, z, c, uv = [0.5 * (x / W + 0.5), 0.5 + z / L]) => { p.pos.push(x, y, z); p.col.push(...c, 1); p.uv.push(...uv); return p.pos.length / 3 - 1; };

// the outline: a superellipse (|x/a|^2.6 + |z/b|^2.6 = 1), a little narrower at the front and pinched at the waist where
// the thumb and the ring finger hold it (the widest part stays in the back third, 6.4 cm)
const PE = 2.6;
const narrow = z => (z < 0 ? 1 - 0.12 * (-z / (L / 2)) : 1) * (1 - 0.05 * Math.exp(-((((0.5 + z / L) - 0.42) / 0.16) ** 2)));
const halfW = z => W / 2 * narrow(z) * Math.max(0, 1 - Math.abs(2 * z / L) ** PE) ** (1 / PE);
// the height of the top at (x, z): the hump peaks a third from the back, the buttons slope to the front, rounded sideways
function top(x, z){
  const u = 0.5 + z / L;                                       // 0 at the front, 1 at the back
  const along = 0.70 + 0.30 * Math.exp(-(((u - 0.66) / 0.34) ** 2));   // (the nose at ~70% of the hump: buttons, not a blade)
  return H * along * (1 - 0.14 * (x / (W / 2)) ** 2);
}
const m = part("mouse");
const SEAM_Y = 0.012;                                          // the parting line between the top shell and the skirt
const WZ = -L / 2 + 0.34 * L, WR = 0.0058, WHW = 0.0032;       // the scroll wheel: centre z, radius, half width
const WY = top(0, WZ) + 0.002 - WR;                            // (its axle; it stands 2 mm proud of the top)
const SLOT_X = WHW + 0.0012, SLOT_Z = WR + 0.0010, SPLIT_Z = 0.004, SPLIT_X = 0.0006, SPLIT_D = 0.0012;
// rows along z: dense at the ends, plus rows on the wheel slot's and the split's edges so they come out sharp
const zs = new Set();
for (let i = 0; i <= 64; i++) zs.add(+(-L / 2 * Math.cos(Math.PI * i / 64)).toFixed(6));
for (const z of [WZ - SLOT_Z - 0.0005, WZ - SLOT_Z, WZ + SLOT_Z, WZ + SLOT_Z + 0.0005, SPLIT_Z, SPLIT_Z + 0.0005]) zs.add(+z.toFixed(6));
const rows = [...zs].sort((p, q) => p - q);
// columns across: fixed x near the middle (the split, the slot), then spread to the rim
const INNER = [0, 0.0004, SPLIT_X, SPLIT_X + 0.0002, 0.0011, SLOT_X - 0.0004, SLOT_X, SLOT_X + 0.0004, 0.006, 0.008, 0.0105], NOUT = 16;
function cols(hw){                                             // x positions for a row of half width hw, from -hw to +hw
  const s = Math.min(1, hw / 0.016), half = INNER.map(x => x * s), x0 = half[half.length - 1];
  for (let i = 1; i <= NOUT; i++) half.push(x0 + (hw - x0) * Math.sin(Math.PI / 2 * i / NOUT));
  return [...half.slice(1).reverse().map(x => -x), ...half];
}
function shellY(x, z){
  const hw = halfW(z), k = hw > 1e-6 ? Math.min(1, Math.abs(x) / hw) : 1;
  const ke = (Math.abs(x / (W / 2 * narrow(z))) ** PE + Math.abs(2 * z / L) ** PE) ** (1 / PE);
  let y = SEAM_Y + (top(x, z) - SEAM_Y) * Math.sqrt(Math.max(0, 1 - Math.min(1, Math.max(k, ke)) ** 6));
  if (Math.abs(x) <= SPLIT_X + 1e-7 && z <= SPLIT_Z + 1e-7) y = Math.max(SEAM_Y, y - SPLIT_D);          // the button split
  if (Math.abs(x) <= SLOT_X + 1e-7 && Math.abs(z - WZ) <= SLOT_Z + 1e-7) y = Math.min(y, WY);           // the wheel's slot
  return y;
}
const topUV = (x, z) => [0.5 + 0.5 * (x / W + 0.5), 0.5 + z / L];          // (the top in the polished half: a satin gloss)
const grid = rows.map(z => cols(halfW(z)).map(x => { const y = shellY(x, z), dark = Math.abs(x) <= SPLIT_X + 1e-7 && z <= SPLIT_Z + 1e-7
  || Math.abs(x) <= SLOT_X + 1e-7 && Math.abs(z - WZ) <= SLOT_Z + 1e-7; return vtx(m, x, y, z, dark ? SEAM : BODY, topUV(x, z)); }));
const want = [];                                               // per triangle: the direction its face should look
const tri = (a, b, c, w) => { m.idx.push(a, b, c); want.push(w); };
for (let r = 0; r + 1 < rows.length; r++) for (let i = 0; i + 1 < grid[r].length; i++) {
  const a = grid[r][i], b = grid[r][i + 1], c = grid[r + 1][i + 1], d = grid[r + 1][i];
  tri(a, b, c, () => [0, 1, 0]); tri(a, c, d, () => [0, 1, 0]);
}
// the rim loop (right side front to back, left side back to front), then the bands below it, each with its own vertices so
// the edges between them stay hard: the lip's underside, the groove, its floor, the skirt, a chamfer, the base
const last = rows.length - 1, loop = [];
for (let r = 0; r <= last; r++) loop.push(grid[r][grid[r].length - 1]);
for (let r = last - 1; r >= 1; r--) loop.push(grid[r][0]);
const P = i => [m.pos[3 * i], m.pos[3 * i + 1], m.pos[3 * i + 2]];
const rim = loop.map(P), n = rim.length;
const outN = rim.map((p, i) => { const a = rim[(i - 1 + n) % n], b = rim[(i + 1) % n]; let nx = b[2] - a[2], nz = -(b[0] - a[0]);
  const l = Math.hypot(nx, nz) || 1; nx /= l; nz /= l; if (nx * p[0] + nz * p[2] < 0) { nx = -nx; nz = -nz; } return [nx, nz]; });
const ringAt = (inset, y) => rim.map((p, i) => [p[0] - outN[i][0] * inset, y, p[2] - outN[i][1] * inset]);
const SIDE = [0.012, 0.012, 0.013];
function band(A, B, col, uvu, w){                              // A, B: rings of points; w(point): the wanted face direction
  const ia = A.map(p => vtx(m, ...p, col, [uvu, 0.5 + p[2] / L])), ib = B.map(p => vtx(m, ...p, col, [uvu, 0.5 + p[2] / L]));
  for (let i = 0; i < n; i++) { const j = (i + 1) % n; tri(ia[i], ib[i], ib[j], w); tri(ia[i], ib[j], ia[j], w); }
}
const outw = c => [c[0], 0, c[2]], down = () => [0, -1, 0], upw = () => [0, 1, 0];
const R0 = ringAt(0, SEAM_Y), R1 = ringAt(0.0008, SEAM_Y), R2 = ringAt(0.0008, SEAM_Y - 0.0008), R3 = ringAt(0.0003, SEAM_Y - 0.0008);
const R4 = ringAt(0.0012, 0.0016), R5 = ringAt(0.0028, 0);
band(R0, R1, SEAM, 0.25, down); band(R1, R2, SEAM, 0.25, outw); band(R2, R3, SEAM, 0.25, upw);
band(R3, R4, SIDE, 0.25, outw); band(R4, R5, SIDE, 0.25, c => [c[0], -0.02, c[2]]);
{ const c0 = vtx(m, 0, 0, 0, BODY), ib = R5.map(p => vtx(m, ...p, BODY));
  for (let i = 0; i < n; i++) tri(c0, ib[i], ib[(i + 1) % n], down); }
// the scroll wheel: a short cylinder across x, half sunk in its slot
{ const n = 18, c0 = [], c1 = [], ctr = c => [c[0], c[1] - WY, c[2] - WZ];
  for (let i = 0; i < n; i++) { const a = 2 * Math.PI * i / n, y = WY + WR * Math.sin(a), z = WZ + WR * Math.cos(a);
    c0.push(vtx(m, -WHW, y, z, WHEEL, [0.6, i / n])); c1.push(vtx(m, WHW, y, z, WHEEL, [0.9, i / n])); }
  for (let i = 0; i < n; i++) { const j = (i + 1) % n; tri(c0[i], c0[j], c1[j], c => [0, c[1] - WY, c[2] - WZ]); tri(c0[i], c1[j], c1[i], c => [0, c[1] - WY, c[2] - WZ]); }
  const e0 = vtx(m, -WHW, WY, WZ, WHEEL, [0.75, 0.5]), e1 = vtx(m, WHW, WY, WZ, WHEEL, [0.75, 0.5]);
  for (let i = 0; i < n; i++) { const j = (i + 1) % n; tri(e0, c0[j], c0[i], () => [-1, 0, 0]); tri(e1, c1[i], c1[j], () => [1, 0, 0]); } }
// turn every triangle to face the way it should
for (let t = 0; t < want.length; t++) {
  const [a, b, c] = [m.idx[3 * t], m.idx[3 * t + 1], m.idx[3 * t + 2]].map(P);
  const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], v = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
  const f = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
  const w = want[t]([(a[0] + b[0] + c[0]) / 3, (a[1] + b[1] + c[1]) / 3, (a[2] + b[2] + c[2]) / 3]);
  if (f[0] * w[0] + f[1] * w[1] + f[2] * w[2] < 0) [m.idx[3 * t + 1], m.idx[3 * t + 2]] = [m.idx[3 * t + 2], m.idx[3 * t + 1]];
}

// the pad: a cloth rectangle with rounded corners, 3 mm thick (its top and a thin edge)
const pad = part("mousepad"), PW = 0.20, PD = 0.19, PT = 0.003, RC = 0.012, pts = [];
for (const [cx, cz, a0] of [[PW / 2 - RC, PD / 2 - RC, 0], [-(PW / 2 - RC), PD / 2 - RC, Math.PI / 2], [-(PW / 2 - RC), -(PD / 2 - RC), Math.PI], [PW / 2 - RC, -(PD / 2 - RC), 1.5 * Math.PI]])
  for (let i = 0; i <= 6; i++) { const a = a0 + (Math.PI / 2) * i / 6; pts.push([cx + RC * Math.cos(a), cz + RC * Math.sin(a)]); }
const c = vtx(pad, 0, PT, 0, PAD), up = pts.map(([x, z]) => vtx(pad, x, PT, z, PAD)), dn = pts.map(([x, z]) => vtx(pad, x, 0, z, PAD));
for (let i = 0; i < pts.length; i++) { const j = (i + 1) % pts.length;
  pad.idx.push(c, up[j], up[i]); pad.idx.push(up[i], up[j], dn[j], up[i], dn[j], dn[i]); }

// smooth normals for both parts (the mouse's bands have their own vertices, so their edges stay hard)
for (const p of parts) {
  const n = new Float32Array(p.pos.length), P = p.pos;
  for (let i = 0; i < p.idx.length; i += 3) {
    const [a, b, c] = [p.idx[i] * 3, p.idx[i + 1] * 3, p.idx[i + 2] * 3];
    const u = [P[b] - P[a], P[b + 1] - P[a + 1], P[b + 2] - P[a + 2]], v = [P[c] - P[a], P[c + 1] - P[a + 1], P[c + 2] - P[a + 2]];
    const f = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
    for (const k of [a, b, c]) { n[k] += f[0]; n[k + 1] += f[1]; n[k + 2] += f[2]; }
  }
  for (let i = 0; i < n.length; i += 3) { const l = Math.hypot(n[i], n[i + 1], n[i + 2]) || 1; n[i] /= l; n[i + 1] /= l; n[i + 2] /= l; }
  p.nor = n;
}
const [folder, out] = process.argv.slice(2);
const maps = await plasticMaps(folder), blob = await contactBlob();
const doc = new Document(), buf = doc.createBuffer(), scene = doc.createScene();
const acc = (type, arr) => doc.createAccessor().setType(type).setArray(arr).setBuffer(buf);
const tex = (name, img, mime) => doc.createTexture(name).setImage(img).setMimeType(mime);
const shell = doc.createMaterial("mouse").setBaseColorFactor([1, 1, 1, 1]).setRoughnessFactor(1).setMetallicFactor(1)
  .setMetallicRoughnessTexture(tex("plastic_mr", maps.mr, "image/webp")).setNormalTexture(tex("plastic_normal", maps.normal, "image/webp")).setNormalScale(0.35);
const cloth = doc.createMaterial("mousepad").setBaseColorFactor([1, 1, 1, 1]).setRoughnessFactor(0.95).setMetallicFactor(0);
let tris = 0;
const nodes = {};
for (const p of parts) {
  if (process.env.REF && p !== m) continue;              // (REF=1: the bare mouse, the clean reference picture for the Tripo attempt)
  const prim = doc.createPrimitive().setAttribute("POSITION", acc("VEC3", new Float32Array(p.pos))).setAttribute("NORMAL", acc("VEC3", p.nor))
    .setAttribute("TEXCOORD_0", acc("VEC2", new Float32Array(p.uv))).setAttribute("COLOR_0", acc("VEC4", new Float32Array(p.col)))
    .setIndices(acc("SCALAR", new Uint32Array(p.idx))).setMaterial(p === m ? shell : cloth);
  nodes[p.name] = doc.createNode(p.name).setMesh(doc.createMesh(p.name).addPrimitive(prim)); scene.addChild(nodes[p.name]); tris += p.idx.length / 3;
}
if (!process.env.REF) { const x0 = -W / 2 - 0.012, x1 = W / 2 + 0.012, z0 = -L / 2 - 0.012, z1 = L / 2 + 0.012, y = 0.0004;   // the mouse's contact shadow
  const smat = doc.createMaterial("mouse_contact").setBaseColorFactor([0, 0, 0, 0.6]).setAlphaMode("BLEND").setRoughnessFactor(1).setMetallicFactor(0)
    .setBaseColorTexture(tex("contact_blob", blob, "image/png"));
  const sp = doc.createPrimitive().setAttribute("POSITION", acc("VEC3", new Float32Array([x0, y, z1, x1, y, z1, x1, y, z0, x0, y, z0])))
    .setAttribute("NORMAL", acc("VEC3", new Float32Array([0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0])))
    .setAttribute("TEXCOORD_0", acc("VEC2", new Float32Array([0, 1, 1, 1, 1, 0, 0, 0]))).setIndices(acc("SCALAR", new Uint32Array([0, 1, 2, 0, 2, 3]))).setMaterial(smat);
  nodes.mouse.addChild(doc.createNode("mouse_contact").setMesh(doc.createMesh("mouse_contact").addPrimitive(sp))); }
await new NodeIO().write(out, doc);
let hy = 0, hz = 0; for (let i = 0; i < m.pos.length; i += 3) if (m.pos[i + 1] > hy) { hy = m.pos[i + 1]; hz = m.pos[i + 2]; }
console.log(out, `${tris} triangles; mouse ${L} x ${W} x ${hy.toFixed(4)} m, hump top at z ${hz.toFixed(3)} (+z back)`);
