// node build_tripo2.mjs <folder with the raw Tripo GLBs> ../web/room/props_tripo2.glb [skip,these]
// The second batch of props made with Tripo's paid API (text-to-model, P1-20260311, PBR): each scaled to real size, turned,
// and put in its place in the room (world metres, the floor's top at y = 0.16), then all joined into ONE mesh with ONE
// material: base colour, metal/roughness and normal maps packed in atlases (a 512 px tile per prop, 8 px of edge padding,
// a square grid; metal/roughness and normals at half that), WebP, meshopt. Two draw calls: the lot, and the desk lamp kept
// apart (out of its own light's shadow map). The page (web/room.html, "Tripo props") adds it and hides or cuts
// out the props it replaces. The raw files are not committed; their task ids are in ../web/room/CREDITS.md.
import { NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS, EXTMeshoptCompression } from "@gltf-transform/extensions";
import { mergeDocuments, dedup, prune, unpartition, reorder, quantize, weld, flatten, join, textureCompress } from "@gltf-transform/functions";
import { MeshoptEncoder, MeshoptDecoder } from "meshoptimizer";
import sharp from "sharp";

const F = 0.16, DTOP = 0.97, FTOP = 1.27, SILL = 1.27, STOP = 2.12;
// name: file stem; size: {h: height} or {w: longest horizontal side} or {l: longest side}; turn: [rx, ry] applied to the
// raw model first (radians); at: [x, support y, z, turn about the vertical in the room]
export const PROPS2 = [
  {name:"lamp2", size:{h:0.62}, turn:[0, 0], at:[-1.575, DTOP, -1.30, 0]},             // the desk lamp's: its clamp by the window wall, the shade over the desk
  {name:"plant2", size:{h:0.66}, turn:[0, 0], at:[-1.58, F, -0.36, 0]},                 // the floor plant's: the pot inside the page's plant box
  {name:"box", size:{w:0.29}, turn:[0, 0], at:[0.10, STOP, -1.28, 0.1]},                // the carton on top of the bookshelf
  {name:"alarm", size:{h:0.12}, turn:[0, 0], at:[-1.87, SILL, 0.62, -0.35]},   // the sill (the alarm clock's); its dial (+x) to the room
  {name:"succulent", size:{h:0.17}, turn:[0, 0], at:[-0.48, DTOP, -1.13, 0.3], drop:0.1},   // the desk succulent's (its
                                                      // saucer came out floating 2 cm under the pot: dropped)
  {name:"backpack", size:{h:0.42}, turn:[0, 0], at:[0.0, F, 1.24, 0]},                // against the bed's side, as before (pocket to +x)
  {name:"fan", size:{h:0.80}, turn:[0, 0], at:[1.70, F, 0.30, 2.51]},                   // the fan's place, facing as before (it faces +x)
  {name:"bin", size:{h:0.30}, turn:[0, 0], at:[-0.55, F, -1.22, 0]},                    // under the desk
  {name:"controller", size:{w:0.15}, turn:[0, 0], flat:"up", at:[-0.80, DTOP, -1.20, -0.35]},      // on the desk, as before
  {name:"skateboard", size:{l:0.80}, turn:[0, 0], flat:"up", at:[1.58, F, -0.12, 0]},   // on the floor by the door, off his routes, wheels
                                                      // up and its graphic showing (the stray third truck Tripo put on the grip tape is underneath)
  {name:"console", size:{h:0.20}, turn:[0, 0], at:[-0.76, DTOP, -1.33, 0]},             // the desk's back, between the monitor and the speaker
  {name:"figure", size:{h:0.15}, turn:[0, 0], at:[-1.87, SILL, 0.78, -0.3]},           // the sill, past the alarm clock (she faces +x)
  {name:"cans", size:{w:0.13}, turn:[0, 0], at:[0.80, FTOP, -1.07, 0.4]},               // the fridge's top, by the tissues
  {name:"shoeboxes", size:{w:0.33}, turn:[0, 0], at:[1.82, F, -0.58, Math.PI / 2]},     // the floor by the door
  {name:"monitor", fit:"monitor"},                                                       // around the page's live screen
  {name:"speaker_l", file:"speaker", size:{h:0.20}, turn:[0, 0], at:[-1.42, DTOP, -1.30, 0.22 - Math.PI / 2]},   // the pair's turns; the left one
                                                      // 10 cm right of its old place, clear of the lamp's clamp (the page moves the sticky notes along)
  {name:"speaker_r", file:"speaker", size:{h:0.20}, turn:[0, 0], at:[-0.59, DTOP, -1.30, -0.18 - Math.PI / 2]},  // (the front faces +x; the right one 1 cm left, clear of the pen cup); 20 cm
                                                                                         // tall: the sticky notes stay on the left one
  {name:"camera", size:{w:0.12}, turn:[0, 0], at:[-1.70, DTOP + 0.068, -1.02, 0.6]},   // on the desk's book stack
];
const TILE = 512, PAD = 8;

function eachVertex(doc, fn){
  for (const mesh of doc.getRoot().listMeshes()) for (const p of mesh.listPrimitives()) fn(p);
}
function rotate(p, rx, ry, rz = 0){                    // about z, then x, then y
  const cx = Math.cos(rx), sx = Math.sin(rx), cy = Math.cos(ry), sy = Math.sin(ry), cz = Math.cos(rz), sz = Math.sin(rz), v = [0, 0, 0];
  const r = ([x0, y0, z]) => { const x = cz * x0 - sz * y0, y = sz * x0 + cz * y0;
    const y1 = cx * y - sx * z, z1 = sx * y + cx * z; return [cy * x + sy * z1, y1, -sy * x + cy * z1]; };
  for (const a of [p.getAttribute("POSITION"), p.getAttribute("NORMAL")]) if (a)
    for (let i = 0; i < a.getCount(); i++) a.setElement(i, r(a.getElement(i, v)));
}
// lay a flat thing down: its longest principal axis along x, its thinnest (the deck's normal) up, the heavier tail of
// points along that normal (the wheels) downwards
function pieces(p){                                   // the connected pieces of a primitive (by shared positions): a label per vertex
  const pos = p.getAttribute("POSITION"), n = pos.getCount(), key = new Map(), rep = new Int32Array(n), par = new Int32Array(n), v = [0, 0, 0];
  for (let i = 0; i < n; i++) { pos.getElement(i, v); const k = v.map(x => Math.round(x * 1e4)).join(","); if (!key.has(k)) key.set(k, i); rep[i] = key.get(k); par[i] = i; }
  const find = x => { while (par[x] !== x) { par[x] = par[par[x]]; x = par[x]; } return x; };
  const I = p.getIndices().getArray();
  for (let t = 0; t < I.length; t += 3) { const a = find(rep[I[t]]); par[find(rep[I[t + 1]])] = a; par[find(rep[I[t + 2]])] = a; }
  return i => find(rep[i]);
}
function layFlat(doc, tailUp = false){                // (the axes from the largest piece alone: a deck without its wheels)
  const pts = [], v = [0, 0, 0];
  eachVertex(doc, p => { const a = p.getAttribute("POSITION"), I = p.getIndices().getArray(), lab = pieces(p), count = new Map();
    for (const i of I) count.set(lab(i), (count.get(lab(i)) || 0) + 1);
    const big = [...count.entries()].sort((x, y) => y[1] - x[1])[0][0];
    for (const i of I) if (lab(i) === big) pts.push(a.getElement(i, v).slice()); });
  const m = [0, 1, 2].map(k => pts.reduce((s, q) => s + q[k], 0) / pts.length);
  const C = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
  for (const q of pts) for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) C[i][j] += (q[i] - m[i]) * (q[j] - m[j]) / pts.length;
  let V = [[1, 0, 0], [0, 1, 0], [0, 0, 1]], A = C.map(r => r.slice());              // Jacobi eigen-decomposition
  for (let it = 0; it < 50; it++) for (const [i, j] of [[0, 1], [0, 2], [1, 2]]) {
    if (Math.abs(A[i][j]) < 1e-12) continue;
    const th = 0.5 * Math.atan2(2 * A[i][j], A[j][j] - A[i][i]), c = Math.cos(th), s = Math.sin(th);
    for (let k = 0; k < 3; k++) { const aki = A[k][i], akj = A[k][j]; A[k][i] = c * aki - s * akj; A[k][j] = s * aki + c * akj; }
    for (let k = 0; k < 3; k++) { const aik = A[i][k], ajk = A[j][k]; A[i][k] = c * aik - s * ajk; A[j][k] = s * aik + c * ajk; }
    for (let k = 0; k < 3; k++) { const vki = V[k][i], vkj = V[k][j]; V[k][i] = c * vki - s * vkj; V[k][j] = s * vki + c * vkj; }
  }
  const ord = [0, 1, 2].sort((a, b) => A[b][b] - A[a][a]), col = k => [V[0][k], V[1][k], V[2][k]];
  const ex = col(ord[0]), ey = col(ord[2]), dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const all = []; eachVertex(doc, p => { const a = p.getAttribute("POSITION"); for (const i of p.getIndices().getArray()) all.push(a.getElement(i, v).slice()); });
  const along = all.map(q => dot([q[0] - m[0], q[1] - m[1], q[2] - m[2]], ey)).sort((a, b) => a - b);   // (the tail from all of it)
  const mean = along.reduce((s, x) => s + x, 0) / along.length, med = along[along.length >> 1];
  if ((mean - med > 0) !== tailUp) ey.forEach((x, k) => ey[k] = -x);                  // the tail (wheels) to -y, or up
  const ez = [ex[1] * ey[2] - ex[2] * ey[1], ex[2] * ey[0] - ex[0] * ey[2], ex[0] * ey[1] - ex[1] * ey[0]];
  eachVertex(doc, p => { for (const a of [p.getAttribute("POSITION"), p.getAttribute("NORMAL")]) if (a)
    for (let i = 0; i < a.getCount(); i++) { const q = a.getElement(i, v); a.setElement(i, [dot(q, ex), dot(q, ey), dot(q, ez)]); } });
}
// the monitor: its panel (the widest piece; Tripo's screen faces +x) fitted around the page's live screen quad SURF_monitor
// (props_hard.py MON_C, MON_RY, MON_RX, SW x SH, the quad 3 mm in front of the old glass), with bezels of BZ; tilted with
// it; the rest (neck, foot) turned along, and only the stand stretched up or down so its foot stands on the desk top
const MON = {c:[-1.06, 1.33, -1.19], ry:0.10, rx:-0.06, w:0.64, h:0.37, front:0.003, bz:0.008};
function fitMonitor(doc){
  const v = [0, 0, 0];
  eachVertex(doc, p => {
    const pos = p.getAttribute("POSITION"), nor = p.getAttribute("NORMAL"), I = p.getIndices().getArray(), lab = pieces(p);
    const ext = new Map();                                          // each piece's z extent: the panel is the widest
    for (const i of I) { pos.getElement(i, v); const l = lab(i), e = ext.get(l) || [1e9, -1e9]; e[0] = Math.min(e[0], v[2]); e[1] = Math.max(e[1], v[2]); ext.set(l, e); }
    const panel = [...ext.entries()].sort((a, b) => (b[1][1] - b[1][0]) - (a[1][1] - a[1][0]))[0][0];
    const lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9];
    for (const i of I) if (lab(i) === panel) { pos.getElement(i, v); for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], v[k]); hi[k] = Math.max(hi[k], v[k]); } }
    const k = (MON.w + 2 * MON.bz) / (hi[2] - lo[2]);
    const pc = [hi[0], hi[1] - MON.bz / k - (MON.h / 2) / k, (lo[2] + hi[2]) / 2];   // the screen's centre on the panel's front face
    const ry = MON.ry - Math.PI / 2, cy = Math.cos(ry), sy = Math.sin(ry), t = -MON.rx, ct = Math.cos(t), st = Math.sin(t);
    const n = [Math.sin(MON.ry) * Math.cos(MON.rx), -Math.sin(MON.rx), Math.cos(MON.ry) * Math.cos(MON.rx)];   // the quad's normal
    const at = MON.c.map((c, a) => c + n[a] * (0.002 - MON.front));                 // the old glass's plane, behind the quad
    const bottom = (lo[1] - pc[1]) * k, used = new Set(I);
    let minY = 1e9;
    const out = new Map();
    for (let i = 0; i < pos.getCount(); i++) {
      pos.getElement(i, v); let x = (v[0] - pc[0]) * k, y = (v[1] - pc[1]) * k, z = (v[2] - pc[2]) * k;
      if (lab(i) === panel) { const x1 = ct * x - st * y, y1 = st * x + ct * y; x = x1; y = y1; }   // tilt the panel back like the quad
      out.set(i, [x, y, z]); if (used.has(i) && lab(i) !== panel) minY = Math.min(minY, y);
    }
    const floor = 0.97 - at[1];                                                       // the desk top, in these coordinates
    for (const [i, q] of out) {
      if (lab(i) !== panel && q[1] < bottom) q[1] = floor + (q[1] - minY) * (bottom - floor) / (bottom - minY);   // stretch the stand
      pos.setElement(i, [cy * q[0] + sy * q[2] + at[0], q[1] + at[1], -sy * q[0] + cy * q[2] + at[2]]);
    }
    if (nor) for (let i = 0; i < nor.getCount(); i++) { nor.getElement(i, v); nor.setElement(i, [cy * v[0] + sy * v[2], v[1], -sy * v[0] + cy * v[2]]); }
    console.log(`  monitor: panel ${((hi[2] - lo[2]) * k).toFixed(3)} x ${((hi[1] - lo[1]) * k).toFixed(3)} m, the stand ${minY < bottom ? "stretched to the desk" : "as is"}`);
  });
}
// drop the separate pieces (connected by shared positions) lying wholly in the bottom `frac` of the model's height
function dropLow(doc, frac){
  const [lo, hi] = bounds(doc), cut = lo[1] + frac * (hi[1] - lo[1]), v = [0, 0, 0];
  eachVertex(doc, p => {
    const pos = p.getAttribute("POSITION"), idx = p.getIndices(), n = pos.getCount(), key = new Map(), rep = new Int32Array(n), par = new Int32Array(n);
    for (let i = 0; i < n; i++) { pos.getElement(i, v); const k = v.map(x => Math.round(x * 1e4)).join(","); if (!key.has(k)) key.set(k, i); rep[i] = key.get(k); par[i] = i; }
    const find = x => { while (par[x] !== x) { par[x] = par[par[x]]; x = par[x]; } return x; };
    const I = idx.getArray();
    for (let t = 0; t < I.length; t += 3) { const a = find(rep[I[t]]); par[find(rep[I[t + 1]])] = a; par[find(rep[I[t + 2]])] = a; }
    const top = new Map();
    for (let i = 0; i < n; i++) { pos.getElement(i, v); const r = find(rep[i]); top.set(r, Math.max(top.get(r) ?? -1e9, v[1])); }
    const keep = [];
    for (let t = 0; t < I.length; t += 3) if (top.get(find(rep[I[t]])) > cut) keep.push(I[t], I[t + 1], I[t + 2]);
    console.log(`  dropped ${(I.length - keep.length) / 3} of ${I.length / 3} triangles under ${(frac * 100).toFixed(0)}% of the height`);
    idx.setArray(new Uint32Array(keep));
  });
}
function bounds(doc){
  const lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9], v = [0, 0, 0];
  eachVertex(doc, p => { const a = p.getAttribute("POSITION"), I = p.getIndices().getArray();      // (used vertices only)
    for (const i of I) { a.getElement(i, v); for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], v[k]); hi[k] = Math.max(hi[k], v[k]); } } });
  return [lo, hi];
}
function scaleMove(p, k, off){
  const a = p.getAttribute("POSITION"), v = [0, 0, 0];
  for (let i = 0; i < a.getCount(); i++) { a.getElement(i, v); a.setElement(i, [(v[0] + off[0]) * k, (v[1] + off[1]) * k, (v[2] + off[2]) * k]); }
}
function translate(p, t){
  const a = p.getAttribute("POSITION"), v = [0, 0, 0];
  for (let i = 0; i < a.getCount(); i++) { a.getElement(i, v); a.setElement(i, [v[0] + t[0], v[1] + t[1], v[2] + t[2]]); }
}
async function tile(img){                              // a texture -> a 512 px tile: resized to 496 and its edges copied out 8 px
  return sharp(img).resize(TILE - 2 * PAD, TILE - 2 * PAD, {fit:"fill"}).extend({top:PAD, bottom:PAD, left:PAD, right:PAD, extendWith:"copy"}).png().toBuffer();
}

const [dir, out, skip = ""] = process.argv.slice(2);
const USE = PROPS2.filter(p => !skip.split(",").includes(p.name));
const N = Math.ceil(Math.sqrt(new Set(USE.map(p => p.file || p.name)).size)), ATLAS = N * TILE;   // a square grid of tiles
await MeshoptEncoder.ready; await MeshoptDecoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS)
  .registerDependencies({"meshopt.encoder": MeshoptEncoder, "meshopt.decoder": MeshoptDecoder});
const tiles = {base:[], mr:[], normal:[]}, slot = new Map();          // one tile per file (the two speakers share one)
let doc = null, uvOut = 0, lampLight = null;
for (const pr of USE) {
  const file = pr.file || pr.name, d = await io.read(`${dir}/${file}.glb`);
  await d.transform(flatten());
  const mat = d.getRoot().listMaterials()[0];
  if (!slot.has(file)) { slot.set(file, slot.size);
    tiles.base.push(await tile(mat.getBaseColorTexture().getImage()));
    tiles.mr.push(await tile(mat.getMetallicRoughnessTexture().getImage()));
    tiles.normal.push(await tile(mat.getNormalTexture().getImage())); }
  const at = slot.get(file), col = at % N, row = Math.floor(at / N), v2 = [0, 0];
  eachVertex(d, p => {
    if (pr.turn) rotate(p, pr.turn[0], pr.turn[1], pr.turn[2] || 0);
    const uv = p.getAttribute("TEXCOORD_0");                // into this prop's tile, inside its padding
    for (let k = 0; k < uv.getCount(); k++) { uv.getElement(k, v2);
      if (v2[0] < -0.001 || v2[0] > 1.001 || v2[1] < -0.001 || v2[1] > 1.001) uvOut++;
      const u = Math.min(1, Math.max(0, v2[0])), w = Math.min(1, Math.max(0, v2[1]));
      uv.setElement(k, [(col * TILE + PAD + u * (TILE - 2 * PAD)) / ATLAS, (row * TILE + PAD + w * (TILE - 2 * PAD)) / ATLAS]); }
  });
  if (pr.fit === "monitor") fitMonitor(d);
  if (pr.flat) layFlat(d, pr.flat === "up");
  if (pr.drop) dropLow(d, pr.drop);
  let [lo, hi] = bounds(d);
  if (!pr.fit) {
  const k = pr.size.h ? pr.size.h / (hi[1] - lo[1]) : pr.size.w ? pr.size.w / Math.max(hi[0] - lo[0], hi[2] - lo[2])
    : pr.size.l / Math.max(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]);
  eachVertex(d, p => { scaleMove(p, k, [-(lo[0] + hi[0]) / 2, -lo[1], -(lo[2] + hi[2]) / 2]); rotate(p, 0, pr.at[3]); translate(p, [pr.at[0], pr.at[1], pr.at[2]]); });
  }
  [lo, hi] = bounds(d);
  if (pr.name === "lamp2") {                                    // its light: in the middle of the shade (the top quarter)
    const top = lo[1] + 0.75 * (hi[1] - lo[1]), a = [1e9, 1e9, 1e9], b = [-1e9, -1e9, -1e9], v = [0, 0, 0];
    eachVertex(d, p => { const P = p.getAttribute("POSITION"); for (const i of p.getIndices().getArray()) { P.getElement(i, v);
      if (v[1] > top) for (let k = 0; k < 3; k++) { a[k] = Math.min(a[k], v[k]); b[k] = Math.max(b[k], v[k]); } } });
    lampLight = [(a[0] + b[0]) / 2, a[1] + 0.25 * (b[1] - a[1]), (a[2] + b[2]) / 2].map(x => +x.toFixed(3));
    console.log("  its light at", lampLight.join(", "));
  }
  console.log(pr.name.padEnd(11), "size", hi.map((h, a) => (h - lo[a]).toFixed(3)).join(" x "), "box", lo.map(x => x.toFixed(2)).join(","), "..", hi.map(x => x.toFixed(2)).join(","));
  // everything joins into one mesh except the lamp, kept apart so it can stay out of its own light's shadow map
  const own = pr.name === "lamp2" ? "T2_lamp" : "";
  for (const m of d.getRoot().listMeshes()) m.setName(own);
  for (const n of d.getRoot().listNodes()) n.setName(own);
  if (!doc) { doc = d; continue; }
  const map = mergeDocuments(doc, d), scene = doc.getRoot().listScenes()[0], other = map.get(d.getRoot().listScenes()[0]);
  for (const n of other.listChildren()) { other.removeChild(n); scene.addChild(n); } other.dispose();
}
if (uvOut) console.log(`note: ${uvOut} UVs outside 0..1 were clamped`);
// the atlases, one material for every prop
const atlas = async (list, scale = 1) => {                // (metal/roughness and normals at half size: GPU memory)
  const full = await sharp({create:{width:ATLAS, height:ATLAS, channels:3, background:{r:128, g:128, b:128}}})
    .composite(list.map((b, i) => ({input:b, left:(i % N) * TILE, top:Math.floor(i / N) * TILE}))).png().toBuffer();
  return scale === 1 ? full : sharp(full).resize(ATLAS * scale, ATLAS * scale).png().toBuffer();
};
const root = doc.getRoot(), M = doc.createMaterial("tripo_props2").setDoubleSided(true).setMetallicFactor(1).setRoughnessFactor(1);
M.setBaseColorTexture(doc.createTexture("atlas_base").setImage(await atlas(tiles.base)).setMimeType("image/png"));
M.setMetallicRoughnessTexture(doc.createTexture("atlas_mr").setImage(await atlas(tiles.mr, 0.5)).setMimeType("image/png"));
M.setNormalTexture(doc.createTexture("atlas_normal").setImage(await atlas(tiles.normal, 0.5)).setMimeType("image/png"));
for (const m of root.listMeshes()) for (const p of m.listPrimitives()) p.setMaterial(M);
for (const m of root.listMaterials()) if (m !== M) m.dispose();
root.listScenes()[0].setExtras({props: USE.map(p => p.name), lampLight});   // the page reads these (gltf.scene.userData)
await doc.transform(prune(), dedup(), flatten(), join({keepNamed:true}), weld(),
  textureCompress({encoder:sharp, targetFormat:"webp", quality:85}), unpartition(), prune(), reorder({encoder:MeshoptEncoder}), quantize());
doc.createExtension(EXTMeshoptCompression).setRequired(true).setEncoderOptions({method:EXTMeshoptCompression.EncoderMethod.QUANTIZE});
await io.write(out, doc);
const prims = root.listMeshes().flatMap(m => m.listPrimitives());
console.log(out, `${prims.length} primitive(s), ${prims.reduce((a, p) => a + p.getIndices().getCount() / 3, 0)} triangles, ${root.listTextures().length} textures`);
