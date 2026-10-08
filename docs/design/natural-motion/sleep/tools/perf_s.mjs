// node perf.mjs <port> : mid phone profile (390x844, DPR 2, CPU x4 via CDP). Per state: the JS cost of animating him
// (200 steps of the page's own sim(), one render), and the real rAF frame rate over 8 s with the loop running
import { chromium } from "playwright";
import fs from "fs";
import { execSync } from "child_process";
const [port] = process.argv.slice(2);
const browser = await chromium.launch({executablePath:"/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
  args:["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]});
const ctx = await browser.newContext({viewport:{width:390, height:844}, deviceScaleFactor:2, isMobile:true, hasTouch:true, ignoreHTTPSErrors:true});
const page = await ctx.newPage();
await page.route(/^https:\/\/(cdn\.jsdelivr\.net|unpkg\.com)\//, async r => {
  const u = r.request().url(), f = "cdn/" + u.replace(/[^a-z0-9.]+/gi, "_");
  if (!fs.existsSync(f)) execSync(`curl -sSfL -o ${f} '${u}'`);
  await r.fulfill({status:200, contentType:u.endsWith(".css") ? "text/css" : "application/javascript", body:fs.readFileSync(f)});
});
await page.goto(`http://localhost:${port}/room.html?debug&nolive&hour=14`);
await page.waitForFunction(() => window.boy && window.room && window.actions && ["walk", "idle", "door", "eat", "sleep", "phone_sit", "phone_lie"].every(k => window.actions[k]), null, {timeout:120000});
const cdp = await ctx.newCDPSession(page);
await cdp.send("Emulation.setCPUThrottlingRate", {rate:4});
for (const [a, prep] of [["research", ""], ["sleep", ""], ["sleep", "window.ROLL && (ROLL.force = ROLL.ang)"]]) {
  const r = await page.evaluate(async ([a, prep]) => {
    window.FREEZE = true; act(a === "walk" ? "research" : a, {food:1}); if (prep) eval(prep); sim(1 / 60, 300);
    const t0 = performance.now(); for (let i = 0; i < 10; i++) sim(1 / 60, 20); const anim = (performance.now() - t0) / 200;   // ms per step (+1/20 of a render)
    const t1 = performance.now(); for (let i = 0; i < 10; i++) sim(1e-6, 1); const rend = (performance.now() - t1) / 10;
    window.FREEZE = false; let n = 0; const ts = []; await new Promise(ok => { const s = performance.now(); (function f(t){ ts.push(t); if (t - s < 8000) requestAnimationFrame(f); else ok(); })(s); });
    const d = ts.slice(1).map((t, i) => t - ts[i]).sort((x, y) => x - y);
    return {anim:+(anim - rend / 20).toFixed(2), render:+rend.toFixed(1), fps:+((ts.length - 1) / ((ts[ts.length - 1] - ts[0]) / 1000)).toFixed(1), p95ms:+d[Math.floor(d.length * 0.95)].toFixed(1), dpr:window.dpr};
  }, [a, prep]);
  console.log(a.padEnd(9), JSON.stringify(r));
}
await browser.close();
