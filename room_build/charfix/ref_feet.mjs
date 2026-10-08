// The owner's Tripo reference (preview/char-owner-tripo: docs/design/char-owner-tripo/char_owner_tripo.glb) cut down to
// its feet: every triangle under 16 cm (scaled to 1.75 m tall, as room_build/rig/normalize.mjs does), with the texture
// charts those triangles use packed into one 2048² atlas (base colour and normal), so room_build/charfix/feet.mjs has a
// small, committed input. Deterministic.
//
//   node room_build/charfix/ref_feet.mjs <char_owner_tripo.glb> room_build/charfix/ref_feet.glb
import {NodeIO, Document} from "@gltf-transform/core";
import {ALL_EXTENSIONS, EXTTextureWebP} from "@gltf-transform/extensions";
import sharp from "sharp";

const [src, dst] = process.argv.slice(2);
if (!src || !dst) { console.error("usage: ref_feet.mjs <char_owner_tripo.glb> <ref_feet.glb>"); process.exit(1); }
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS);
const doc = await io.read(src);
const prim = doc.getRoot().listMeshes()[0].listPrimitives()[0];
const P = prim.getAttribute("POSITION").getArray(), UV = prim.getAttribute("TEXCOORD_0").getArray(), I = prim.getIndices().getArray();
let ymin = Infinity, ymax = -Infinity;
for (let i = 1; i < P.length; i += 3) { ymin = Math.min(ymin, P[i]); ymax = Math.max(ymax, P[i]); }
const S = 1.75 / (ymax - ymin), TOP = 0.16;

// the triangles under TOP, and their charts (vertices shared through the index: Tripo splits its vertices at UV seams)
const tris = [];
for (let t = 0; t < I.length; t += 3)
  if (Math.max(P[3 * I[t] + 1], P[3 * I[t + 1] + 1], P[3 * I[t + 2] + 1]) * S - ymin * S < TOP) tris.push(I[t], I[t + 1], I[t + 2]);
const par = new Map(), find = x => { while (par.get(x) !== x) { par.set(x, par.get(par.get(x))); x = par.get(x); } return x; };
for (const i of tris) if (!par.has(i)) par.set(i, i);
for (let t = 0; t < tris.length; t += 3) { const a = find(tris[t]); par.set(find(tris[t + 1]), a); par.set(find(tris[t + 2]), find(tris[t])); }
const charts = new Map();
for (const i of par.keys()) { const r = find(i); let c = charts.get(r);
  if (!c) charts.set(r, c = {b: [Infinity, Infinity, -Infinity, -Infinity]});
  c.b[0] = Math.min(c.b[0], UV[2 * i]); c.b[1] = Math.min(c.b[1], UV[2 * i + 1]); c.b[2] = Math.max(c.b[2], UV[2 * i]); c.b[3] = Math.max(c.b[3], UV[2 * i + 1]); }

// shelf packing, tallest first, 8 px of padding (the source's own pixels around each chart come along: no bleeding)
const SRC = prim.getMaterial().getBaseColorTexture().getSize()[0], A = 2048, PAD = 8;
const list = [...charts.entries()].map(([r, c]) => {
  const x0 = Math.max(0, Math.floor(c.b[0] * SRC) - PAD), y0 = Math.max(0, Math.floor(c.b[1] * SRC) - PAD);
  const x1 = Math.min(SRC, Math.ceil(c.b[2] * SRC) + PAD), y1 = Math.min(SRC, Math.ceil(c.b[3] * SRC) + PAD);
  return {r, x0, y0, w: x1 - x0, h: y1 - y0};
}).sort((a, b) => b.h - a.h || b.w - a.w || a.x0 - b.x0 || a.y0 - b.y0);
let cx = 0, cy = 0, rowH = 0;
for (const c of list) {
  if (cx + c.w > A) { cx = 0; cy += rowH; rowH = 0; }
  c.ax = cx; c.ay = cy; cx += c.w; rowH = Math.max(rowH, c.h);
}
if (cy + rowH > A) throw new Error(`charts do not fit ${A}²: ${cy + rowH}`);
const byRoot = new Map(list.map(c => [c.r, c]));

// the sub-mesh: positions in metres (feet on y = 0, 1.75 m tall, facing +z as in the source), UVs into the atlas
const map = new Map(), pos = [], uv = [], idx = [];
for (const i of tris) {
  if (!map.has(i)) { const c = byRoot.get(find(i)); map.set(i, pos.length / 3);
    pos.push(P[3 * i] * S, (P[3 * i + 1] - ymin) * S, P[3 * i + 2] * S);
    uv.push((UV[2 * i] * SRC - c.x0 + c.ax) / A, (UV[2 * i + 1] * SRC - c.y0 + c.ay) / A); }
  idx.push(map.get(i));
}

async function atlas(tex) {
  const img = sharp(Buffer.from(tex.getImage()));
  const parts = await Promise.all(list.map(async c => ({input: await img.clone().extract({left: c.x0, top: c.y0, width: c.w, height: c.h}).toBuffer(), left: c.ax, top: c.ay})));
  return sharp({create: {width: A, height: A, channels: 3, background: {r: 128, g: 128, b: 128}}}).composite(parts).webp({quality: 95}).toBuffer();
}
const mat = prim.getMaterial();
const out = new Document(), buf = out.createBuffer(); out.createExtension(EXTTextureWebP).setRequired(true);
const color = out.createTexture("feet_color").setImage(await atlas(mat.getBaseColorTexture())).setMimeType("image/webp");
const normal = out.createTexture("feet_normal").setImage(await atlas(mat.getNormalTexture())).setMimeType("image/webp");
const m = out.createMaterial("ref_feet").setBaseColorTexture(color).setNormalTexture(normal).setMetallicFactor(0).setRoughnessFactor(0.85);
const p = out.createPrimitive().setMaterial(m)
  .setAttribute("POSITION", out.createAccessor().setType("VEC3").setArray(new Float32Array(pos)).setBuffer(buf))
  .setAttribute("TEXCOORD_0", out.createAccessor().setType("VEC2").setArray(new Float32Array(uv)).setBuffer(buf))
  .setIndices(out.createAccessor().setType("SCALAR").setArray(new Uint32Array(idx)).setBuffer(buf));
out.createScene().addChild(out.createNode("ref_feet").setMesh(out.createMesh("ref_feet").addPrimitive(p)));
await io.write(dst, out);
console.log(`ref_feet: ${idx.length / 3} triangles, ${pos.length / 3} vertices, ${list.length} charts in ${A}² (to y ${cy + rowH})`);
