// node probe.mjs <port> <out.png|-> <js> : load the room, run js (an async function body), print its result, screenshot
import { chromium } from "playwright";
import fs from "fs";
import { execSync } from "child_process";
const [port, png, js, W = "640", H = "400"] = process.argv.slice(2);
const browser = await chromium.launch({executablePath:"/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
  args:["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]});
const page = await browser.newPage({viewport:{width:+W, height:+H}, ignoreHTTPSErrors:true});
fs.mkdirSync("cdn", {recursive:true});
await page.route(/^https:\/\/(cdn\.jsdelivr\.net|unpkg\.com)\//, async r => {
  const u = r.request().url(), f = "cdn/" + u.replace(/[^a-z0-9.]+/gi, "_");
  if (!fs.existsSync(f)) execSync(`curl -sSfL -o ${f} '${u}'`);
  await r.fulfill({status:200, contentType:u.endsWith(".css") ? "text/css" : "application/javascript", body:fs.readFileSync(f)});
});
page.on("pageerror", e => console.log("pageerror", e.message));
page.on("console", m => { if (m.type() !== "error") console.log("log", m.text().slice(0, 400)); });
await page.goto(`http://localhost:${port}/room.html?debug&nolive&hour=${process.env.HOUR || 14}`);
await page.waitForFunction(() => window.boy && window.room && window.actions && ["walk", "idle", "door", "eat", "sleep", "phone_sit", "phone_stand", "phone_lie"].concat((location.port === "8802" || location.port === "8803") ? ["stand"] : []).every(k => window.actions[k]), null, {timeout:120000});
await page.evaluate(() => { window.FREEZE = true; document.querySelectorAll("#top,#side,#corner,#dock,#vignette,#away").forEach(e => e.style.display = "none"); settle(); });
const r = await page.evaluate(`(async () => { ${js} })()`);
console.log(JSON.stringify(r, null, 0));
await page.evaluate(() => { renderer.render(scene, camera); return new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); });
if (png !== "-") await page.locator("#scene canvas").screenshot({path:png});
await browser.close();
