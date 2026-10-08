// node rig/autorig/qa.mjs <character.glb> <clips dir> <out dir> [Clip ...]
// The auto-rigged character in a browser (qa.html, through web/room/char_mixamo.js), playing each Mixamo clip
// (<clips dir>/<Clip>.glb, mixamo_glb.mjs's): a render sheet (rest pose, then each clip at four moments, front and
// side, and close-ups of the shoulders, elbows, hips and hands) and qa.json with the deformation and contact numbers.
import fs from "node:fs"; import http from "node:http"; import path from "node:path";
import { chromium } from "playwright-core";
import sharp from "sharp";
const [CHAR, CLIPS, OUT, ...names] = process.argv.slice(2);
const CL = names.length ? names : ["Seated_Idle", "Laying_Sleeping", "Typing"];
const ROOT = path.resolve(new URL("../../..", import.meta.url).pathname);
fs.mkdirSync(OUT, {recursive: true});
const files = {"/char.glb": path.resolve(CHAR)}; for (const c of CL) files[`/clips/${c}.glb`] = path.resolve(CLIPS, `${c}.glb`);
const TYPES = {".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".glb": "model/gltf-binary", ".wasm": "application/wasm", ".json": "application/json"};
const srv = http.createServer((q, r) => { const u = decodeURIComponent(q.url.split("?")[0]); const f = files[u] || path.join(ROOT, u);
  if (!f.startsWith(ROOT) && !files[u]) { r.writeHead(403); return r.end(); }
  fs.readFile(f, (e, b) => { if (e) { r.writeHead(404); return r.end(); } r.writeHead(200, {"content-type": TYPES[path.extname(f)] || "application/octet-stream"}); r.end(b); }); });
await new Promise(ok => srv.listen(0, ok)); const port = srv.address().port;
const b = await chromium.launch({executablePath: process.env.CHROME || "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
  args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]});
const p = await b.newPage(); p.on("console", m => { if (m.type() === "error") console.log("page:", m.text()); });
await p.goto(`http://localhost:${port}/room_build/rig/autorig/qa.html`); await p.waitForFunction(() => window.QA_READY, null, {timeout: 60000});
const info = await p.evaluate(c => QA.load("/char.glb", Object.fromEntries(c.map(k => [k, `/clips/${k}.glb`]))), CL);
console.log(`loaded: ${info.bones} bones, hip height ${info.hipH.toFixed(3)} m, clips ${JSON.stringify(info.clips)}`);
const img = async (k, t, view, w, h) => { await p.evaluate(([k, t]) => QA.pose(k, t), [k, t]);
  const d = await p.evaluate(([v, w, h]) => QA.shot(v, w, h), [view, w, h]); return Buffer.from(d.split(",")[1], "base64"); };
const label = (txt, w) => Buffer.from(`<svg width="${w}" height="26"><rect width="100%" height="100%" fill="#222"/><text x="8" y="18" font-family="sans-serif" font-size="15" fill="#eee">${txt}</text></svg>`);
const tile = async (buf, txt, w, h) => sharp({create: {width: w, height: h + 26, channels: 3, background: "#222"}})
  .composite([{input: label(txt, w), top: 0, left: 0}, {input: buf, top: 26, left: 0}]).jpeg().toBuffer();
const W = 300, H = 400, rows = [];
// rest pose
rows.push(await Promise.all([["front", "rest, front"], ["side", "rest, side"], ["back", "rest, back"], [{dir: "front", focus: "LeftHand", r: 0.12}, "rest, left hand"],
  [{dir: "top", focus: "RightHand", r: 0.12}, "rest, right hand (top)"]].map(async ([v, t]) => tile(await img(null, 0, v, W, H), t, W, H))));
for (const c of CL) { const D = info.clips[c], ts = [0, D * 0.33, D * 0.66, D * 0.99].map(t => +t.toFixed(2)), r = [];
  const vs = /Lay|Sleep/.test(c) ? ["top", "side"] : ["front", "side"];   // (lying: from above and beside)
  for (const t of ts.slice(0, 2)) for (const v of vs) r.push(await tile(await img(c, t, v, W, H), `${c} ${t}s ${v}`, W, H));
  r.push(await tile(await img(c, ts[2], "three", W, H), `${c} ${ts[2]}s 3/4`, W, H));
  rows.push(r);
  const z = [];
  for (const [f, nm] of [["LeftArm", "L shoulder"], ["RightForeArm", "R elbow"], ["Hips", "hips"], ["LeftHand", "L hand"], ["RightHand", "R hand"]])
    z.push(await tile(await img(c, ts[1], {dir: [0.6, 0.4, 0.7], focus: f, r: f === "Hips" ? 0.3 : 0.14}, W, H), `${c} ${ts[1]}s ${nm}`, W, H));
  rows.push(z); }
const sheet = await sharp({create: {width: W * 5, height: (H + 26) * rows.length, channels: 3, background: "#222"}})
  .composite(rows.flatMap((r, i) => r.map((buf, j) => ({input: buf, top: i * (H + 26), left: j * W})))).jpeg({quality: 82}).toBuffer();
fs.writeFileSync(`${OUT}/sheet.jpg`, sheet);
const qa = {character: path.basename(CHAR), bones: info.bones, hipH_m: +info.hipH.toFixed(3), clips: {}};
for (const c of CL) { const t0 = Date.now(); qa.clips[c] = await p.evaluate(k => QA.measure(k, 0.1), c); console.log(c, `${((Date.now() - t0) / 1000).toFixed(0)} s`, JSON.stringify(qa.clips[c])); }
if (CL.includes("Seated_Idle") && CL.includes("Typing")) {                 // (the README's 0.8 s hands-to-thighs blend, both ways)
  qa.blends = [await p.evaluate(() => QA.blend("Seated_Idle", "Typing")), await p.evaluate(() => QA.blend("Typing", "Seated_Idle"))];
  console.log("blends", JSON.stringify(qa.blends)); }
fs.writeFileSync(`${OUT}/qa.json`, JSON.stringify(qa, null, 1));
await b.close(); srv.close();
console.log(`${OUT}/sheet.jpg, ${OUT}/qa.json`);
