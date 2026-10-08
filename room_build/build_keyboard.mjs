// node build_keyboard.mjs <ambientCG Plastic016A 1K folder> ../web/room/keyboard.glb
// A full-size keyboard modelled in code (original, CC0; no maker's design, no legends), from real ones' measures: the ANSI
// 104-key layout on a 19.05 mm pitch, separate keycaps (tapered sides, a 0.7 mm bevel round the top, 1 mm gaps, clean flat
// tops for his fingertips) on a black case with a slight typing tilt, a soft cable out of the back, and a contact shadow.
// PBR: matte ABS with a fine micro-texture, the keys pressed most (the home row, WASD, space, Enter, Backspace) polished by
// use (desk_pbr.mjs). One node "keyboard" (origin: the middle of F and J at desk level; the page places it by its home row,
// whose key tops stand HOME_TOP above the desk) with a child "keyboard_contact".
import { Document, NodeIO } from "@gltf-transform/core";
import { plasticMaps, contactBlob } from "./desk_pbr.mjs";

const U = 0.01905, GAP = 0.001, TAPER = 0.0016, BEVEL = 0.0007, MARGIN = 0.006;
const CASE_H = 0.016, TILT = 0.06;                             // the case's height (m) and the tilt (rad, back up)
const CAP_BASE = 0.004, CAP_H = 0.0085;                        // the caps stand over the case top, this tall
const HOME_TOP = 0.032;                                        // the home row's key tops above the desk (the modelled one: 0.031)
const CASE_COL = [0.006, 0.0065, 0.0075], CAP_COL = [0.018, 0.019, 0.022], ESC_COL = [0.70, 0.11, 0.015], CABLE_COL = [0.008, 0.008, 0.009];

// keys: [x from the left edge (u), depth from the back edge (u), width (u), depth (u)]
const K = [];
const row = (d, list, x = 0) => { for (const w of list) { if (w > 0) K.push([x, d, w, 1]); x += Math.abs(w); } };   // (a negative width: a gap)
row(0, [1, -1, 1, 1, 1, 1, -0.5, 1, 1, 1, 1, -0.5, 1, 1, 1, 1, -0.25, 1, 1, 1]);                 // Esc, F1-F12, PrtSc ScrLk Pause
row(1.5, [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, -0.25, 1, 1, 1, -0.25, 1, 1, 1, 1]);         // numbers, Backspace, Ins Home PgUp, numpad
row(2.5, [1.5, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1.5, -0.25, 1, 1, 1, -0.25, 1, 1, 1]);        // Tab .. \, Del End PgDn, 7 8 9
row(3.5, [1.75, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2.25, -3.5, 1, 1, 1]);                          // Caps .. Enter, 4 5 6
row(4.5, [2.25, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2.75, -1.25, 1, -1.25, 1, 1, 1]);                  // Shift .. Shift, Up, 1 2 3
row(5.5, [1.25, 1.25, 1.25, 6.25, 1.25, 1.25, 1.25, 1.25, -0.25, 1, 1, 1, -0.25, 2, 1]);         // the bottom row, arrows, 0 .
K.push([21.5, 2.5, 1, 2], [21.5, 4.5, 1, 2]);                                                    // numpad + and Enter (2u tall)
const WIDTH_U = 22.5, DEPTH_U = 6.5;
const HOME = [(1.75 + 3 + 0.5 + 1.75 + 6 + 0.5) / 2, 4.0];      // the middle of F and J (u from the left and back edges)
const worn = ([x, d, w]) => (d === 3.5 && x >= 1.75 && x < 10.75) || (d === 2.5 && (x === 2.5 || x === 3.5))   // A..L, W E
  || (d === 5.5 && w === 6.25) || (d === 3.5 && x === 12.75) || (d === 1.5 && w === 2);                     // space, Enter, Backspace

const pos = [], col = [], uv = [], idx = [];
// a quad (corners counter-clockwise seen from outside), its uv from a mapping of each corner
function quad(ps, rgb, map) { const i = pos.length / 3; for (const p of ps) { pos.push(...p); col.push(...rgb, 1); uv.push(...map(p)); } idx.push(i, i + 1, i + 2, i, i + 2, i + 3); }
// a frustum from the rectangle (x0..x1, z0..z1) at y0 up to y1, inset by `inset` (and, with a bevel, a last chamfer of `bev`)
function frustum(x0, x1, z0, z1, y0, y1, inset, rgb, map, bev = 0) {
  const ring = (k, y) => [[x0 + k, y, z1 - k], [x1 - k, y, z1 - k], [x1 - k, y, z0 + k], [x0 + k, y, z0 + k]];   // front-left, front-right, back-right, back-left
  const levels = bev ? [ring(0, y0), ring(inset, y1 - bev), ring(inset + bev, y1)] : [ring(0, y0), ring(inset, y1)];
  for (let l = 0; l + 1 < levels.length; l++) { const a = levels[l], b = levels[l + 1];
    for (let s = 0; s < 4; s++) { const t = (s + 1) % 4; quad([a[s], a[t], b[t], b[s]], rgb, map); } }
  const top = levels[levels.length - 1]; quad([top[0], top[1], top[2], top[3]], rgb, map);
}
// in the keyboard's own frame: x right from the keys' left edge, z forward from their back edge, y up from the desk (untilted)
const W = WIDTH_U * U, D = DEPTH_U * U;
const caseMap = p => [0.5 * (p[0] + MARGIN) / (W + 2 * MARGIN) + 0.0 * p[1], (p[2] + MARGIN + p[1]) / (D + 2 * MARGIN)];
frustum(-MARGIN, W + MARGIN, -MARGIN, D + MARGIN, 0, CASE_H, 0.002, CASE_COL, caseMap, 0.0015);
for (const k of K) {
  const [x, d, w, h] = k, x0 = x * U + GAP / 2, x1 = (x + w) * U - GAP / 2, z0 = d * U + GAP / 2, z1 = (d + h) * U - GAP / 2;
  const u0 = worn(k) ? 0.5 : 0, map = p => [u0 + 0.5 * (p[0] - x0) / (x1 - x0) * 0.98 + 0.005, (p[2] - z0) / (z1 - z0)];
  frustum(x0, x1, z0, z1, CASE_H + CAP_BASE - 0.004, CASE_H + CAP_BASE + CAP_H, TAPER, x === 0 && d === 0 ? ESC_COL : CAP_COL, map, BEVEL);
}
// tilt about the front edge (back up), then move the origin to F/J at desk level and lift so the home row's tops sit at HOME_TOP
const zf = D + MARGIN, c = Math.cos(TILT), s = Math.sin(TILT), hx = HOME[0] * U, hz = (HOME[1] + 0.5) * U;
const tilt = ([x, y, z]) => { const dz = z - zf; return [x, y * c - dz * s, zf + dz * c + y * s]; };
const homeTop = tilt([hx, CASE_H + CAP_BASE + CAP_H, hz])[1], homeZ = tilt([hx, 0, hz])[2], lift = HOME_TOP - homeTop;
const place = p => { const [x, y, z] = tilt(p); return [x - hx, y + lift, z - homeZ]; };
for (let i = 0; i < pos.length; i += 3) { const q = place([pos[i], pos[i + 1], pos[i + 2]]); pos[i] = q[0]; pos[i + 1] = q[1]; pos[i + 2] = q[2]; }
// the cable: out of the back a third from the left, down onto the desk and away behind the monitor, a soft curve
// (REF=1: a bare keyboard, no cable or contact shadow: the clean reference picture for the Tripo attempt)
if (!process.env.REF) { const R = 0.0022, N = 8, back = place([W * 0.62, CASE_H * 0.55, -MARGIN]);
  const pts = []; for (let i = 0; i <= 40; i++) { const t = i / 40;
    const z = back[2] - 0.34 * t, x = back[0] + 0.07 * Math.sin(t * 2.2) - 0.03 * t, y = R + (back[1] - R) * Math.max(0, 1 - t * 8) ** 2;
    pts.push([x, y, z]); }
  const rings = pts.map((p, i) => { const q = pts[Math.min(i + 1, pts.length - 1)], o = pts[Math.max(i - 1, 0)];
    const t = [q[0] - o[0], q[1] - o[1], q[2] - o[2]], l = Math.hypot(...t), T = t.map(v => v / l);
    let side = [T[2], 0, -T[0]]; const ls = Math.hypot(...side) || 1; side = side.map(v => v / ls);
    const upv = [T[1] * side[2] - T[2] * side[1], T[2] * side[0] - T[0] * side[2], T[0] * side[1] - T[1] * side[0]];
    return Array.from({length: N}, (_, k) => { const a = 2 * Math.PI * k / N; return p.map((v, j) => v + R * (Math.cos(a) * side[j] + Math.sin(a) * upv[j])); }); });
  for (let i = 0; i + 1 < rings.length; i++) for (let k = 0; k < N; k++) { const j = (k + 1) % N;
    quad([rings[i][k], rings[i + 1][k], rings[i + 1][j], rings[i][j]], CABLE_COL, () => [0.25, 0.5]); } }
// normals: flat per quad (each quad has its own four corners)
const nor = new Float32Array(pos.length);
for (let i = 0; i < idx.length; i += 6) {
  const [a, b, d] = [idx[i] * 3, idx[i + 1] * 3, idx[i + 2] * 3];
  const u = [pos[b] - pos[a], pos[b + 1] - pos[a + 1], pos[b + 2] - pos[a + 2]], v = [pos[d] - pos[a], pos[d + 1] - pos[a + 1], pos[d + 2] - pos[a + 2]];
  let n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]; const l = Math.hypot(...n) || 1; n = n.map(x => x / l);
  for (let k = 0; k < 4; k++) nor.set(n, (idx[i] + k) * 3);
}
let lo = [9, 9, 9], hi = [-9, -9, -9]; for (let i = 0; i < pos.length; i += 3) for (let a = 0; a < 3; a++) { lo[a] = Math.min(lo[a], pos[i + a]); hi[a] = Math.max(hi[a], pos[i + a]); }

const [folder, out] = process.argv.slice(2);
const maps = await plasticMaps(folder), blob = await contactBlob();
const doc = new Document(), buf = doc.createBuffer(), scene = doc.createScene();
const acc = (type, arr) => doc.createAccessor().setType(type).setArray(arr).setBuffer(buf);
const tex = (name, img, mime) => doc.createTexture(name).setImage(img).setMimeType(mime);
const mat = doc.createMaterial("keyboard").setBaseColorFactor([1, 1, 1, 1]).setRoughnessFactor(1).setMetallicFactor(1)
  .setMetallicRoughnessTexture(tex("plastic_mr", maps.mr, "image/webp")).setNormalTexture(tex("plastic_normal", maps.normal, "image/webp")).setNormalScale(0.6);
const prim = doc.createPrimitive().setAttribute("POSITION", acc("VEC3", new Float32Array(pos))).setAttribute("NORMAL", acc("VEC3", nor))
  .setAttribute("TEXCOORD_0", acc("VEC2", new Float32Array(uv))).setAttribute("COLOR_0", acc("VEC4", new Float32Array(col)))
  .setIndices(acc("SCALAR", new Uint32Array(idx))).setMaterial(mat);
const kb = doc.createNode("keyboard").setMesh(doc.createMesh("keyboard").addPrimitive(prim));
// the contact shadow: the case's footprint grown 1.5 cm, a hair over the desk
if (!process.env.REF) { const m = 0.015, x0 = lo[0] - m, x1 = hi[0] + m, z0 = lo[2] - m, z1 = hi[2] + m, y = 0.0004;
  const smat = doc.createMaterial("keyboard_contact").setBaseColorFactor([0, 0, 0, 0.55]).setAlphaMode("BLEND").setRoughnessFactor(1).setMetallicFactor(0)
    .setBaseColorTexture(tex("contact_blob", blob, "image/png"));
  const sp = doc.createPrimitive().setAttribute("POSITION", acc("VEC3", new Float32Array([x0, y, z1, x1, y, z1, x1, y, z0, x0, y, z0])))
    .setAttribute("NORMAL", acc("VEC3", new Float32Array([0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0])))
    .setAttribute("TEXCOORD_0", acc("VEC2", new Float32Array([0, 1, 1, 1, 1, 0, 0, 0]))).setIndices(acc("SCALAR", new Uint32Array([0, 1, 2, 0, 2, 3]))).setMaterial(smat);
  kb.addChild(doc.createNode("keyboard_contact").setMesh(doc.createMesh("keyboard_contact").addPrimitive(sp))); }
scene.addChild(kb);
await new NodeIO().write(out, doc);
console.log(out, `${K.length} keys, ${idx.length / 3 + 2} triangles, ${hi.map((h, a) => (h - lo[a]).toFixed(3)).join(" x ")} m, home tops ${(HOME_TOP * 1000).toFixed(1)} mm`);
