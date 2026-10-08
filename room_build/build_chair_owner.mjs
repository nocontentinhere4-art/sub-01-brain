// node build_chair_owner.mjs <parts.ply> <ambientCG folder> ../web/room/chair_owner.glb
// The office chair the owner made on Tripo (docs/design/chair-tripo/chair_owner_raw.fbx; AI-generated under Tripo's terms):
// its letter-shaped holes repaired by chair_owner_repair.py, split into a real mesh chair's parts by chair_owner_parts.py
// (with box-projected UVs in metres), then put into the frame of the room's "chair" node (web/room.html CHAIR: the pivot on
// the floor, y up, the sitter facing -z): scaled so the seat cushion's top under him is 0.52 m (the model's 0.407 -> x 1.278:
// 1.25 m tall with the headrest), turned half round (Tripo's faces +z), its gas lift on the pivot and then moved 5 cm back
// (his reclined back and head in the seated clips clear the backrest that way), welded and simplified a little.
// Tripo's texture atlas is not used. The materials are made here, matched to a real chair (docs/design/chair-tripo):
//   chair_mesh    black woven mesh (backrest, headrest): a knit drawn here, its strands and the darker gaps between them
//   chair_fabric  black upholstery (seat, lumbar pad): ambientCG Fabric 030 (CC0) for its weave, darkened
//   chair_plastic black matte plastic (frame, spine, arms, seat pan): a moulded grain drawn here, ambientCG Plastic 006 (CC0)
//                 for the mottling of its roughness
//   chair_armpad  the armrests' soft tops, the same plastic, a little rougher
//   chair_lift    the gas lift: black, a little glossy
//   chair_base    the five-star base: polished aluminium
//   chair_caster  the casters' black nylon
// <ambientCG folder> holds Fabric030/ and Plastic006/ (their 1K JPG sets).
import fs from "node:fs";
import { Document, NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS, EXTMeshoptCompression, KHRTextureTransform } from "@gltf-transform/extensions";
import { weld, simplify, dedup, prune, reorder, quantize } from "@gltf-transform/functions";
import { MeshoptEncoder, MeshoptSimplifier } from "meshoptimizer";
import sharp from "sharp";

// SEAT: the seat cushion's top under him; the live character sits on the room's old seat height, 0.505 m (SEAT=0.505;
// preview/chair-tripo's character sits at 0.52)
const SEAT = +(process.env.SEAT || 0.52);
export const OWNER = {scale: SEAT / 0.407, lift: [0.0, -0.013], back: 0.05};
const PARTS = ["mesh", "lumbar", "seat", "plastic", "armpad", "lift", "base", "caster"];   // (chair_owner_parts.py's order)
const MAT_OF = {mesh: "chair_mesh", lumbar: "chair_fabric", seat: "chair_fabric", plastic: "chair_plastic", armpad: "chair_armpad",
  lift: "chair_lift", base: "chair_base", caster: "chair_caster"};
const TILE = {chair_mesh: 0.04, chair_fabric: 0.12, chair_plastic: 0.05, chair_armpad: 0.05, chair_lift: 0.05, chair_base: 0.05, chair_caster: 0.05};
const [src, acg, out] = process.argv.slice(2);
await MeshoptEncoder.ready; await MeshoptSimplifier.ready;

// the parts PLY: per corner x y z nx ny nz u v part (float32), faces of three
const buf = fs.readFileSync(src), hEnd = buf.indexOf("end_header\n") + 11, head = buf.subarray(0, hEnd).toString();
const nv = +head.match(/element vertex (\d+)/)[1];
const V = new Float32Array(buf.buffer.slice(buf.byteOffset + hEnd, buf.byteOffset + hEnd + nv * 36)), S = OWNER.scale;
const groups = {};
for (let i = 0; i < nv; i += 3) {
  const mat = MAT_OF[PARTS[V[9 * i + 8]]], g = groups[mat] = groups[mat] || {pos: [], nor: [], uv: []};
  for (let k = i; k < i + 3; k++) {
    const x = V[9 * k], y = V[9 * k + 1], z = V[9 * k + 2];
    g.pos.push(-(x - OWNER.lift[0]) * S, y * S, -(z - OWNER.lift[1]) * S + OWNER.back);      // (half a turn about y)
    g.nor.push(-V[9 * k + 3], V[9 * k + 4], -V[9 * k + 5]);
    g.uv.push(V[9 * k + 6] * S / TILE[mat], V[9 * k + 7] * S / TILE[mat]);                    // (metres in the room / the tile)
  }
}

// --- the maps (tiles that repeat; linear values are written as sRGB for the colour maps)
const N = 512, srgb = l => Math.round(255 * (l <= 0.0031308 ? 12.92 * l : 1.055 * l ** (1 / 2.4) - 0.055));
const webp = (px, ch = 3) => sharp(px, {raw: {width: N, height: N, channels: ch}}).webp({quality: 80}).toBuffer();
function normalFromHeight(h, strength) {                 // tangent space, OpenGL green up
  const px = Buffer.alloc(N * N * 3), H = (x, y) => h[((y + N) % N) * N + ((x + N) % N)];
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
    const dx = (H(x + 1, y) - H(x - 1, y)) * strength, dy = (H(x, y + 1) - H(x, y - 1)) * strength, l = Math.hypot(dx, dy, 1), i = 3 * (y * N + x);
    px[i] = Math.round(127.5 * (1 - dx / l)); px[i + 1] = Math.round(127.5 * (1 + dy / l)); px[i + 2] = Math.round(127.5 * (1 + 1 / l)); }
  return px;
}
// the mesh: a fine knit, 14 cells across a 4 cm tile (2.9 mm), its strands running diagonally both ways round small
// gaps; the gaps darker (the dark inside of the panel seen through them), the strands with a slight fibre sheen
const knit = new Float32Array(N * N), knitCol = Buffer.alloc(N * N * 3), knitMR = Buffer.alloc(N * N * 3);
for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
  const u = (x / N) * 14, v = (y / N) * 14, a = Math.abs(((u + v) % 1) - 0.5), b = Math.abs(((u - v + 14) % 1) - 0.5);
  const s = Math.min(a, b), strand = Math.max(0, 1 - s / 0.16), row = 0.5 + 0.5 * Math.cos(2 * Math.PI * (u + v) * 2);
  const h = strand ** 0.6 * (0.85 + 0.15 * row), i = y * N + x; knit[i] = h;
  const lin = 0.006 + 0.03 * Math.min(1, h * 1.3); knitCol[3 * i] = knitCol[3 * i + 1] = knitCol[3 * i + 2] = srgb(lin);
  knitMR[3 * i] = 255; knitMR[3 * i + 1] = Math.round(255 * (0.88 - 0.26 * h)); knitMR[3 * i + 2] = 0;
}
// ambientCG Fabric 030: its colour's light and shade around a black upholstery, its normal and roughness
const fab = `${acg}/Fabric030/Fabric030_1K-JPG_`;
const fabL = await sharp(fab + "Color.jpg").resize(N, N).greyscale().raw().toBuffer();
let fm = 0; for (const v of fabL) fm += v; fm /= fabL.length;
const fabCol = Buffer.alloc(N * N * 3);
for (let i = 0; i < N * N; i++) { const lin = Math.max(0.003, 0.02 * (1 + 1.2 * (fabL[i] - fm) / fm)); fabCol[3 * i] = srgb(lin * 0.97); fabCol[3 * i + 1] = srgb(lin * 0.97); fabCol[3 * i + 2] = srgb(lin); }
const fabR = await sharp(fab + "Roughness.jpg").resize(N, N).greyscale().raw().toBuffer(), fabMR = Buffer.alloc(N * N * 3);
for (let i = 0; i < N * N; i++) { fabMR[3 * i] = 255; fabMR[3 * i + 1] = Math.min(255, Math.round(0.35 * fabR[i] + 165)); fabMR[3 * i + 2] = 0; }
const fabN = await sharp(fab + "NormalGL.jpg").resize(N, N).removeAlpha().raw().toBuffer();
// black matte plastic: a fine moulded grain (smoothed noise, about 0.3 mm, on a 5 cm tile) as its normal, ambientCG
// Plastic 006's mottled roughness around 0.66
let seed = 7; const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 2 ** 32; };
const grainRaw = Buffer.alloc(N * N); for (let i = 0; i < N * N; i++) grainRaw[i] = Math.round(255 * rnd());
const grainB = await sharp(grainRaw, {raw: {width: N, height: N, channels: 1}}).blur(1.4).raw().toBuffer();
const grain = new Float32Array(N * N); for (let i = 0; i < N * N; i++) grain[i] = grainB[i] / 255;
const pl = `${acg}/Plastic006/Plastic006_1K-JPG_`;
const plR = await sharp(pl + "Roughness.jpg").resize(N, N).greyscale().raw().toBuffer(); let pm = 0; for (const v of plR) pm += v; pm /= plR.length;
const plMR = Buffer.alloc(N * N * 3);
for (let i = 0; i < N * N; i++) { plMR[3 * i] = 255; plMR[3 * i + 1] = Math.max(0, Math.min(255, Math.round(255 * (0.66 + 0.30 * (plR[i] - pm) / 128)))); plMR[3 * i + 2] = 0; }
const plN = normalFromHeight(grain, 6);

const doc = new Document(), b = doc.createBuffer(), sc = doc.createScene();
const acc = (t, a) => doc.createAccessor().setType(t).setArray(a).setBuffer(b);
const tex = async (name, px) => doc.createTexture(name).setImage(await webp(px)).setMimeType("image/webp");
const T = {knitN: await tex("mesh_knit_normal", normalFromHeight(knit, 1.8)), knitC: await tex("mesh_knit_color", knitCol), knitMR: await tex("mesh_knit_mr", knitMR),
  fabC: await tex("fabric_color", fabCol), fabMR: await tex("fabric_mr", fabMR), fabN: await tex("fabric_normal", fabN),
  plMR: await tex("plastic_mr", plMR), plN: await tex("plastic_normal", plN)};
const M = (name, col) => doc.createMaterial(name).setBaseColorFactor([...col, 1]).setMetallicFactor(0);
const MAT = {
  chair_mesh: M("chair_mesh", [1, 1, 1]).setBaseColorTexture(T.knitC).setMetallicRoughnessTexture(T.knitMR).setRoughnessFactor(1).setNormalTexture(T.knitN).setNormalScale(1.0),
  chair_fabric: M("chair_fabric", [1, 1, 1]).setBaseColorTexture(T.fabC).setMetallicRoughnessTexture(T.fabMR).setRoughnessFactor(1).setNormalTexture(T.fabN).setNormalScale(1.6),
  chair_plastic: M("chair_plastic", [0.011, 0.011, 0.012]).setMetallicRoughnessTexture(T.plMR).setRoughnessFactor(1.1).setNormalTexture(T.plN).setNormalScale(0.3),
  chair_armpad: M("chair_armpad", [0.014, 0.014, 0.015]).setMetallicRoughnessTexture(T.plMR).setRoughnessFactor(1.3).setNormalTexture(T.plN).setNormalScale(0.5),
  chair_lift: M("chair_lift", [0.012, 0.012, 0.013]).setRoughnessFactor(0.38),
  chair_base: M("chair_base", [0.91, 0.92, 0.93]).setMetallicFactor(1).setRoughnessFactor(0.18).setNormalTexture(T.plN).setNormalScale(0.08),
  chair_caster: M("chair_caster", [0.012, 0.012, 0.013]).setMetallicRoughnessTexture(T.plMR).setRoughnessFactor(0.95).setNormalTexture(T.plN).setNormalScale(0.25),
};
// (Tripo's surface has small openings, its inner faces facing away: the mesh and the plastic are drawn from both sides,
// so an opening shows the dark inside and not the room behind it)
MAT.chair_mesh.setDoubleSided(true); MAT.chair_plastic.setDoubleSided(true);
const mesh = doc.createMesh("chair_owner"), KTT = doc.createExtension(KHRTextureTransform);
for (const [mat, g] of Object.entries(groups)) {
  // the UVs (in tiles) squeezed into [0, 1] so they quantise; KHR_texture_transform puts the tiling back
  const lo = [Infinity, Infinity], hi = [-Infinity, -Infinity];
  for (let i = 0; i < g.uv.length; i++) { lo[i % 2] = Math.min(lo[i % 2], g.uv[i]); hi[i % 2] = Math.max(hi[i % 2], g.uv[i]); }
  const span = [hi[0] - lo[0] || 1, hi[1] - lo[1] || 1], uv = Float32Array.from(g.uv, (v, i) => (v - lo[i % 2]) / span[i % 2]);
  const m = MAT[mat];
  for (const info of [m.getBaseColorTextureInfo(), m.getMetallicRoughnessTextureInfo(), m.getNormalTextureInfo()])
    if (info && (m.getBaseColorTextureInfo() === info ? m.getBaseColorTexture() : m.getMetallicRoughnessTextureInfo() === info ? m.getMetallicRoughnessTexture() : m.getNormalTexture()))
      info.setExtension("KHR_texture_transform", KTT.createTransform().setOffset(lo).setScale(span));
  mesh.addPrimitive(doc.createPrimitive().setAttribute("POSITION", acc("VEC3", new Float32Array(g.pos))).setAttribute("NORMAL", acc("VEC3", new Float32Array(g.nor)))
    .setAttribute("TEXCOORD_0", acc("VEC2", uv)).setMaterial(m));
}
const node = doc.createNode("chair_owner").setMesh(mesh);
node.setExtras({seatTop: SEAT, scale: +S.toFixed(4), back: OWNER.back, source: "Tripo (owner), repaired, own materials"}); sc.addChild(node);
await doc.transform(weld({tolerance: 1e-5}), simplify({simplifier: MeshoptSimplifier, ratio: +(process.env.RATIO || 0.55), error: 0.0006}),
  dedup(), prune(), reorder({encoder: MeshoptEncoder}), quantize());
doc.createExtension(EXTMeshoptCompression).setRequired(true).setEncoderOptions({method: EXTMeshoptCompression.EncoderMethod.QUANTIZE});
await new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({"meshopt.encoder": MeshoptEncoder}).write(out, doc);
let tris = 0; for (const p of mesh.listPrimitives()) tris += p.getIndices().getCount() / 3;
console.log(out, tris, "triangles,", mesh.listPrimitives().length, "materials,", (fs.statSync(out).size / 1024).toFixed(0), "KB");
