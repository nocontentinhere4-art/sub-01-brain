// node sweep.mjs <port> [scale] : chain every activity, sample penetration every 0.25 s (all vertices)
import { chromium } from "playwright";
import fs from "fs";
import { execSync } from "child_process";
const [port, scale = "1", seedArg = "63"] = process.argv.slice(2);
const browser = await chromium.launch({executablePath:"/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
  args:["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]});
const page = await browser.newPage({viewport:{width:320, height:200}, ignoreHTTPSErrors:true});
await page.route(/^https:\/\/(cdn\.jsdelivr\.net|unpkg\.com)\//, async r => {
  const u = r.request().url(), f = "cdn/" + u.replace(/[^a-z0-9.]+/gi, "_");
  if (!fs.existsSync(f)) execSync(`curl -sSfL -o ${f} '${u}'`);
  await r.fulfill({status:200, contentType:u.endsWith(".css") ? "text/css" : "application/javascript", body:fs.readFileSync(f)});
});
page.on("pageerror", e => console.log("pageerror", e.message));
await page.goto(`http://localhost:${port}/room.html?debug&nolive&hour=14`);
await page.waitForFunction(() => window.boy && window.room && window.actions && ["walk", "idle", "door", "eat", "sleep", "phone_sit", "phone_lie", "stand"].every(k => window.actions[k]), null, {timeout:120000});
await page.evaluate(s => { window.FREEZE = true; settle(); setSeed(s); }, +seedArg);
const k = +scale;
const SEQ = [["act", "research", 20], ["live", "sleep", 50], ["js", "ROLL.force = ROLL.ang", 15], ["js", "ROLL.force = 0", 15], ["js", "ROLL.force = -ROLL.ang", 15],
  ["js", "ROLL.force = null; ROLL.goal = 0", 15], ["live", "phone", 40], ["live", "listen_music", 40], ["live", "sleep", 40], ["js", "ROLL.force = ROLL.ang * 0.9", 12],
  ["live", "research", 40], ["live", "sleep", 40], ["js", "ROLL.force = -ROLL.ang", 12], ["live", "window", 40], ["live", "order_food", 30], ["live", "sleep", 30], ["live", "get_delivery", 40]];
let worst = 0;
for (const [how, a, secs, x] of SEQ) {
  await page.evaluate(([how, a, x]) => { if (how === "js") eval(a); else { ROLL.force = null; (how === "act" ? act : live)(a, x || {}); } }, [how, a, x]);
  const res = await page.evaluate(([n]) => { const out = {max:0, bad:[]}; for (let i = 0; i < n; i++) { for (let j = 0; j < 5; j++) animate_(0.05);
      const p = penetration(1, true); const c = (i % 4 === 0) ? contacts(4) : null; const inbed = pose().at === "bedlie"; const s = p.bed + p.chair + (c && inbed ? c.wall.n : 0);
      if (s) out.bad.push([+(i * 0.25).toFixed(2), s, pose().step && pose().step.k, gz().iv, JSON.stringify(p.by) + (c && inbed && c.wall.n ? " wall " + c.wall.n : "")]);
      out.max = Math.max(out.max, s); if (c) { out.pill = Math.max(out.pill || 0, inbed ? c.pillow.d : 0); } }
    return out; }, [Math.round(secs * k / 0.25)]);
  worst = Math.max(worst, res.max);
  console.log(a.slice(0, 22).padEnd(23), "worst", res.max, "head-pillow", (res.pill || 0).toFixed(3), "|", "max", res.max, res.bad.slice(0, 4).map(b => b.join(" ")).join(" | "));
}
console.log("WORST", worst);
await browser.close();
