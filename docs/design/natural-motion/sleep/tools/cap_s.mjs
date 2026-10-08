// node cap.mjs <port> <outdir> <case,case...> [w h]
// Headless Chromium (SwiftShader WebGL); the page runs ?debug&nolive with its rAF loop frozen and is stepped with sim()
import { chromium } from "playwright";
import fs from "fs";
import { execSync } from "child_process";

const [port, out, which = "all", W = "640", H = "400"] = process.argv.slice(2);
fs.mkdirSync(out, {recursive:true});
const browser = await chromium.launch({executablePath:"/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
  args:["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]});
const page = await browser.newPage({viewport:{width:+W, height:+H}, ignoreHTTPSErrors:true});
// CDN files (three.js, leaflet) through curl and the agent proxy, cached on disk
fs.mkdirSync("cdn", {recursive:true});
await page.route(/^https:\/\/(cdn\.jsdelivr\.net|unpkg\.com)\//, async r => {
  const u = r.request().url(), f = "cdn/" + u.replace(/[^a-z0-9.]+/gi, "_");
  if (!fs.existsSync(f)) execSync(`curl -sSfL -o ${f} '${u}'`);
  const ct = u.endsWith(".css") ? "text/css" : "application/javascript";
  await r.fulfill({status:200, contentType:ct, body:fs.readFileSync(f)});
});
page.on("pageerror", e => console.log("pageerror", e.message));
page.on("console", m => { if (m.type() === "error") console.log("console", m.text().slice(0, 200)); });
await page.goto(`http://localhost:${port}/room.html?debug&nolive&hour=14`);
await page.waitForFunction(() => window.boy && window.room && window.actions && ["walk", "idle", "door", "eat", "sleep", "phone_sit", "phone_stand", "phone_lie"].concat((location.port === "8802" || location.port === "8803") ? ["stand"] : []).every(k => window.actions[k]), null, {timeout:120000});
await page.evaluate(() => { window.FREEZE = true; document.querySelectorAll("#top,#side,#corner,#dock,#vignette,#away").forEach(e => e.style.display = "none"); settle();
  scene.traverse(o => { if (o.isMesh && o.geometry.type === "SphereGeometry" && o.material.color && o.material.color.getHex() === 0xff00ff) o.visible = false; }); });

const C = {   // camera presets
  room:  {pos:[3.3, 2.9, 3.5], target:[-0.35, 0.65, -0.15]},
  bed:   {pos:[0.35, 1.55, -0.55], target:[-0.55, 0.95, 0.55]},
  desk:  {pos:[0.45, 1.55, 0.8], target:[-1.1, 0.9, -0.75]},
  win:   {pos:[-0.35, 1.7, 1.65], target:[-1.6, 1.15, -0.05]},
  door:  {pos:[-0.2, 1.75, 1.3], target:[1.35, 1.05, -1.1]},
  eat:   {pos:[0.2, 1.75, -1.0], target:[-1.15, 1.15, -0.6]},
  def:   null,                                                  // the page's default camera
  bedc:  {pos:[0.5, 2.0, 0.2], target:[-1.1, 0.85, 0.9]},
};
// each case: setup (in the page), then `secs` of simulation, a frame every `every` s
const CASES = {
  sleep_in:    {setup:`act("research"); live("sleep")`, cam:"def", secs:40},
  sleep_in_c:  {setup:`act("research"); live("sleep"); sim(0.05, 330)`, cam:"bedc", secs:10},
  breathing:   {setup:`act("sleep"); sim(0.05, 80)`, cam:"bedc", secs:10},
  roll:        {setup:`act("sleep"); sim(0.05, 80); ROLL.force = ROLL.ang`, cam:"def", secs:16, at:{8:"ROLL.force = 0"}},
  roll_c:      {setup:`act("sleep"); sim(0.05, 80); ROLL.force = -ROLL.ang`, cam:"bedc", secs:16, at:{8:"ROLL.force = 0"}},
  wake:        {setup:`act("sleep"); sim(0.05, 80); ROLL.force = ROLL.ang; sim(0.05, 100); ROLL.force = null; live("research")`, cam:"def", secs:24},
};
const list = which === "all" ? Object.keys(CASES) : which.split(",");
const FINE = +(process.env.FINE || 0.5);   // seconds between frames (the WebM); strips keep one frame every 0.5 s
for (const name of list) {
  const c = CASES[name], cam = C[c.cam], every = c.every || FINE, dt = 0.05, dir = `${out}/${name}`;
  fs.rmSync(dir, {recursive:true, force:true}); fs.mkdirSync(dir, {recursive:true});
  await page.evaluate(([s, cam]) => { window.CAM0 = window.CAM0 || [camera.position.clone(), controls.target.clone()]; eval(s);
    if (!cam) { camera.position.copy(CAM0[0]); controls.target.copy(CAM0[1]); controls.update(); }
    if (cam) { camera.position.set(...cam.pos); controls.target.set(...cam.target); controls.update(); } sim(0.0001); }, [c.setup, cam]);
  const n = Math.round(c.secs / every), pen = [];
  for (let i = 0; i <= n; i++) {
    if (i) await page.evaluate(([dt, k]) => sim(dt, k), [dt, Math.round(every / dt)]);
    if (c.at && c.at[(i * every).toFixed(1).replace(/\.0$/, "")]) await page.evaluate(c.at[(i * every).toFixed(1).replace(/\.0$/, "")]);
    const p = await page.evaluate(() => { const q = penetration(4); const s = pose(); return {...q, at:s.at, step:s.step && s.step.k, clip:s.clip}; });
    pen.push(`${(i * every).toFixed(1)} bed ${p.bed} chair ${p.chair} ${p.at || "-"} ${p.step || ""} ${p.clip}`);
    await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
    await page.locator("#scene canvas").screenshot({path:`${dir}/f${String(i).padStart(4, "0")}.png`});
  }
  fs.writeFileSync(`${dir}/trace.txt`, pen.join("\n") + "\n");
  console.log(name, "frames", n + 1, "max pen", Math.max(...pen.map(l => +l.split(" ")[2] + +l.split(" ")[4])));
}
await browser.close();
// strips (one frame every 0.5 s, or every frame for the long ones, rows of 8) and a WebM per case
for (const name of list) { const dir = `${out}/${name}`, c = CASES[name], k = c.every ? 1 : Math.round(0.5 / FINE);
  const fr = fs.readdirSync(dir).filter(f => f.endsWith(".png")).sort().filter((f, i) => i % k === 0).map(f => `${dir}/${f}`);
  execSync(`montage ${fr.join(" ")} -tile 8x -geometry 320x200+2+2 -background '#111' ${out}/strip_${name}.jpg`);
  if (!c.every) execSync(`ffmpeg -y -loglevel error -framerate ${Math.round(1 / FINE)} -i ${dir}/f%04d.png -c:v libvpx-vp9 -b:v 0 -crf 40 -pix_fmt yuv420p ${out}/${name}.webm`); }
