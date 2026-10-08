// node ui.mjs <port> <outdir> : the whole page at 1280 and 390 px, with a fake tick (so the cards read like the live page)
import { chromium } from "playwright";
import fs from "fs";
import { execSync } from "child_process";
const [port, out] = process.argv.slice(2);
fs.mkdirSync(out, {recursive:true});
const browser = await chromium.launch({executablePath:"/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
  args:["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]});
const CASES = [["window", {}, 6], ["eat", {food:1}, 7], ["phone", {}, 5], ["listen_music", {music:{title:"a track", artist:"an artist"}}, 5]];
for (const [w, h, mob] of [[1280, 800, false], [390, 844, true]]) {
  const ctx = await browser.newContext({viewport:{width:w, height:h}, isMobile:mob, hasTouch:mob, ignoreHTTPSErrors:true});
  const page = await ctx.newPage();
  await page.route(/^https:\/\/(cdn\.jsdelivr\.net|unpkg\.com)\//, async r => {
    const u = r.request().url(), f = "cdn/" + u.replace(/[^a-z0-9.]+/gi, "_");
    if (!fs.existsSync(f)) execSync(`curl -sSfL -o ${f} '${u}'`);
    await r.fulfill({status:200, contentType:u.endsWith(".css") ? "text/css" : "application/javascript", body:fs.readFileSync(f)});
  });
  await page.goto(`http://localhost:${port}/room.html?debug&nolive&hour=14`);
  await page.waitForFunction(() => window.boy && window.room && window.actions && window.actions.stand && window.actions.phone_lie, null, {timeout:120000});
  for (const [a, x, secs] of CASES) {
    await page.evaluate(([a, x]) => {
      scene.traverse(o => { if (o.isMesh && o.geometry.type === "SphereGeometry" && o.material.color && o.material.color.getHex() === 0xff00ff) o.visible = false; });
      const LABEL = {window:"looking out of the window", eat:"eating at the desk", phone:"in bed scrolling the phone", listen_music:"lying on the bed listening to music"};
      const life = {activity:a, place:a === "window" ? "window" : a === "eat" ? "table" : "bed", doing:LABEL[a], say:"", hunger:0.3, boredom:0.4, bread:1,
        vitals:{hr_bpm:64, resp_per_min:14, glucose_mg_dl:96}, ...x};
      act(a, x); applyTick({type:"tick", life, sleep:{stage:"AWAKE", clock:"14:05"}, neuro:{DA:1.1, "5HT":1, NE:0.9, ACh:1}});
      window.FREEZE = false;
    }, [a, x]);
    await page.waitForTimeout(secs * 1000);          // the real loop runs: the camera eases in, he moves
    await page.evaluate(() => { window.FREEZE = true; renderer.render(scene, camera); return new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); });
    await page.screenshot({path:`${out}/${a}_${w}.png`, fullPage:false});
  }
  await ctx.close();
}
await browser.close();
