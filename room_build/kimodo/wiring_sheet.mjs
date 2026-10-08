// node kimodo/wiring_sheet.mjs <out.jpg> <before port> <after port> [after query]
// The ?char=mixamo wiring sheet: seated watching and typing at the desk, each from the page's own camera and from his
// right side (a camera 3.1 m off his right), before (main, served on <before port>) and after (this branch with
// room.html?char=mixamo, on <after port>). Each still is taken once he has settled in that mode, 3 s in.
import {chromium} from "playwright-core"; import fs from "fs"; import {execSync} from "child_process"; import path from "path";
import sharp from "sharp";
const [OUT, PB, PA, QA = "&char=mixamo"] = process.argv.slice(2);
const MODES = [["watching", "desk_watch", "research", {screen: {id: "v", kind: "video"}}], ["typing", "desk_type", "research", {screen: {id: "s", search: {query: "how do tides work exactly"}}}]];
const W = 480, H = 400;
const b = await chromium.launch({executablePath: process.env.CHROME || "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
  args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]});
const cdn = path.join(process.env.CDN_CACHE || "/tmp", "cdn_cache"); fs.mkdirSync(cdn, {recursive: true});
async function shots(port, qs) {
  const p = await b.newPage({viewport: {width: 1280, height: 860}});
  await p.route(/^https:\/\/(cdn\.jsdelivr\.net|unpkg\.com)\//, async r => { const u = r.request().url(), f = path.join(cdn, u.replace(/[^a-z0-9.]+/gi, "_"));
    if (!fs.existsSync(f)) execSync(`curl -sSfL -o ${f} '${u}'`); await r.fulfill({status: 200, contentType: u.endsWith(".css") ? "text/css" : "application/javascript", body: fs.readFileSync(f)}); });
  await p.goto(`http://localhost:${port}/room.html?debug&nolive&hour=15${qs}`);
  await p.waitForFunction(() => window.boy && window.mh && window.mh.ready, null, {timeout: 300000});
  // (the page's panels over the room hidden: only the view)
  await p.evaluate(() => { const cv = document.querySelector("canvas"); for (const el of document.body.querySelectorAll("*")) if (el !== cv && !el.contains(cv)) el.style.visibility = "hidden"; });
  const out = [];
  for (const [label, mode, act, X] of MODES) {
    const info = await p.evaluate(([mode, act, X]) => { window.FREEZE = true; settle(); live(act, X); let t = 0;
      while (t < 60 && !(pose().at === "desk" && !pose().step && mh.M.mode === mode)) { animate_(1 / 30); t += 1 / 30; }
      if (mode === "desk_type") live(act, {screen: {id: "s" + t, search: X.screen.search}});        // (a fresh search: it types on)
      for (let k = 0; k < 90; k++) animate_(1 / 30);
      sim(1 / 30, 1); return {mode: mh.M.mode, t: +t.toFixed(1)}; }, [mode, act, X]);
    const cv = await p.$("canvas"); const bb = await cv.boundingBox();
    // the page's camera: the middle of the view, where the camera holds him
    const page = await p.screenshot({clip: {x: bb.x + bb.width * 0.1, y: bb.y + bb.height * 0.08, width: bb.width * 0.5, height: bb.height * 0.6}});
    // his right side: a camera 3.1 m off his right at his hips' height, looking a little under them (the feet in view)
    await p.evaluate(() => { window.__cam = [camera.position.clone(), camera.quaternion.clone()];
      const h = boy.getObjectByName("Hips").getWorldPosition(new THREE.Vector3()), ry = boy.rotation.y;
      const right = new THREE.Vector3(-Math.cos(ry), 0, Math.sin(ry)); camera.position.copy(h).addScaledVector(right, 3.1).add(new THREE.Vector3(0, 0.1, 0));
      camera.lookAt(h.clone().add(new THREE.Vector3(0, -0.12, 0))); camera.updateProjectionMatrix(); renderer.render(scene, camera); });
    const side = await p.screenshot({clip: {x: bb.x, y: bb.y, width: bb.width, height: bb.height}});
    await p.evaluate(() => { camera.position.copy(window.__cam[0]); camera.quaternion.copy(window.__cam[1]); camera.updateProjectionMatrix(); });   // (the page's camera back)
    out.push({label, info, page, side});
  }
  await p.close(); return out;
}
const before = await shots(PB, ""), after = await shots(PA, QA);
const tile = async (buf, txt, crop) => { let im = sharp(buf); if (crop) { const m = await im.metadata(); im = sharp(buf).extract({left: Math.round(m.width * 0.2), top: Math.round(m.height * 0.02), width: Math.round(m.width * 0.6), height: Math.round(m.height * 0.96)}); }
  const body = await im.resize(W, H, {fit: "cover"}).toBuffer();
  const lab = Buffer.from(`<svg width="${W}" height="28"><rect width="100%" height="100%" fill="#1d1d1d"/><text x="8" y="19" font-family="sans-serif" font-size="15" fill="#eee">${txt}</text></svg>`);
  return sharp({create: {width: W, height: H + 28, channels: 3, background: "#1d1d1d"}}).composite([{input: lab, top: 0, left: 0}, {input: body, top: 28, left: 0}]).jpeg().toBuffer(); };
const rows = [];
for (const [name, S] of [["before: main (v5)", before], ["after: ?char=mixamo", after]]) {
  const r = [];
  for (const s of S) { r.push(await tile(s.page, `${name}, ${s.label}: page camera (${s.info.mode})`)); r.push(await tile(s.side, `${name}, ${s.label}: his right side`, true)); }
  rows.push(r);
}
const sheet = await sharp({create: {width: W * 4, height: (H + 28) * rows.length, channels: 3, background: "#1d1d1d"}})
  .composite(rows.flatMap((r, i) => r.map((buf, j) => ({input: buf, top: i * (H + 28), left: j * W})))).jpeg({quality: 84}).toBuffer();
fs.writeFileSync(OUT, sheet); console.log(OUT, JSON.stringify([...before, ...after].map(s => [s.label, s.info])));
await b.close();
