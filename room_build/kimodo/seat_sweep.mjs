// node kimodo/seat_sweep.mjs <port> <out.json> [mode ...] : the seat-point sweep (boy_mh.js SEAT_AT) in the room
// (room.html?debug, QS="&char=mixamo" for the Mixamo-rigged character): for each desk mode (desk_watch, desk_type,
// desk_mouse) and each seat point forward of the chair's pivot (-0.01 ... -0.12 m), he settles at the desk in that mode
// and the page's own penetration() counts his skin inside the chair every 0.1 s over the mode's clip (one loop, at least
// 4 s). The clear range per mode is where every sample has 0 vertices in the chair. One page load for the whole sweep.
import {chromium} from "playwright-core"; import fs from "fs"; import {execSync} from "child_process"; import path from "path";
const [port, out, ...modes] = process.argv.slice(2);
const MODES = modes.length ? modes : ["desk_watch", "desk_type", "desk_mouse"];
const ZS = Array.from({length: 12}, (_, i) => -0.01 * (i + 1));
// what puts him in each mode (boy_mh.js wanted()): a video on the screen; a search (typing for 4-8 s); a chart (the mouse)
const LIFE = {desk_watch: ["research", {screen: {id: "v", kind: "video"}}], desk_type: ["research", {screen: {id: "s", search: {query: "how do tides work exactly"}}}],
  desk_mouse: ["chart", {}]};
const b = await chromium.launch({executablePath: process.env.CHROME || "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
  args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]});
const p = await b.newPage({viewport: {width: 480, height: 320}});
const cdn = path.join(process.env.CDN_CACHE || "/tmp", "cdn_cache"); fs.mkdirSync(cdn, {recursive: true});
await p.route(/^https:\/\/(cdn\.jsdelivr\.net|unpkg\.com)\//, async r => { const u = r.request().url(), f = path.join(cdn, u.replace(/[^a-z0-9.]+/gi, "_"));
  if (!fs.existsSync(f)) execSync(`curl -sSfL -o ${f} '${u}'`); await r.fulfill({status: 200, contentType: u.endsWith(".css") ? "text/css" : "application/javascript", body: fs.readFileSync(f)}); });
p.on("pageerror", e => console.log("pageerror", e.message));
await p.goto(`http://localhost:${port}/room.html?debug&nolive&hour=15${process.env.QS || ""}`);
await p.waitForFunction(() => window.boy && window.mh && window.mh.ready, null, {timeout: 300000});
const res = {};
for (const m of MODES) { res[m] = {};
  for (const z of ZS) {
    const r = await p.evaluate(([m, z, act, X]) => {
      window.FREEZE = true; window.__seatAt = {[m]: [0, z]}; if (m === "desk_type") window.__seatAt.type_in = window.__seatAt.type_out = [0, z];
      settle(); live(act, X); let t = 0, still = 0;
      while (t < 120 && still < 1.5) { animate_(1 / 30); t += 1 / 30; still = pose().step || pose().at !== "desk" ? 0 : still + 1 / 30; }
      // (typing: a new search each time, so it types; the others: the mode itself)
      if (m === "desk_type") live(act, {screen: {id: "s" + Math.random(), search: {query: "how do tides work exactly"}}});
      let w = 0; while (w < 3 && mh.M.mode !== m) { animate_(1 / 30); w += 1 / 30; }
      for (let k = 0; k < 24; k++) animate_(1 / 30);                         // (the 0.4-0.8 s blends over)
      const a = mh.M.actions[m], dur = Math.max(4, Math.min(8, a ? a.getClip().duration : 4)), hits = [];
      for (let s = 0; s < dur; s += 0.1) { for (let k = 0; k < 3; k++) animate_(1 / 30); if (mh.M.mode !== m) break; const q = penetration(2, true); hits.push(q.chair);
        if (q.chair && !window.__by) window.__by = q.by; }
      const by = window.__by; window.__by = null;
      return {mode: mh.M.mode, samples: hits.length, maxChair: Math.max(0, ...hits), framesIn: hits.filter(x => x).length, by: by ? Object.fromEntries(Object.entries(by).filter(([k]) => k !== "pts")) : null};
    }, [m, z, ...LIFE[m]]);
    res[m][z.toFixed(2)] = r; console.log(m, z.toFixed(2), JSON.stringify(r));
  }
  const clear = Object.entries(res[m]).filter(([, r]) => r.samples && !r.maxChair).map(([z]) => +z);
  res[m].clear = clear.length ? [Math.max(...clear), Math.min(...clear)] : null; console.log(m, "clear", JSON.stringify(res[m].clear));
}
fs.writeFileSync(out, JSON.stringify(res, null, 1)); await b.close();
