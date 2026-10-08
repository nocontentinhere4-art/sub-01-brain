// The pure parts of web/room/window_view.js, run in node by tests/test_window_view.py (no WebGL here): the weather
// pattern's shares over a year of Tokyo hours, its smoothness, the lit-window probability by hour, the sun's elevation,
// the shader's contract (every sampler has a texture, every uniform is declared, the layers match plates.json), the
// reflection probe's cadence, the HDR emission hook, and that nothing names a brand. Prints one JSON line.
import { readFileSync } from "fs";
import { weatherAt, litProbability, sunElevation, tokyoDayKey, createWindowView, LAYERS, GAIN, TRAIN, GROUND, SKY, PROBE } from "../../web/room/window_view.js";

const out = {};
// a year of hours, every 10 minutes
let n = 0, rain = 0, overcast = 0, clear = 0, maxStep = 0, prev = null, switches = 0, prevKind = null;
const day0 = tokyoDayKey(new Date("2026-10-01T00:00:00Z"));
for (let d = 0; d < 365; d++) for (let h = 0; h < 24; h += 1 / 6) {
  const w = weatherAt(day0 + d, h);
  n++; if (w.kind === "rain") rain++; else if (w.kind === "overcast") overcast++; else clear++;
  if (prev) maxStep = Math.max(maxStep, Math.abs(w.cloud - prev.cloud), Math.abs(w.rain - prev.rain));
  if (prevKind && w.kind !== prevKind) switches++;
  prev = w; prevKind = w.kind;
}
out.weather = {rain: +(rain / n).toFixed(3), overcast: +(overcast / n).toFixed(3), clear: +(clear / n).toFixed(3),
  max_step_per_10min: +maxStep.toFixed(3), changes_per_day: +(switches / 365).toFixed(2)};
const a = weatherAt(20000, 13.5), b = weatherAt(20000, 13.5);
out.deterministic = a.kind === b.kind && a.cloud === b.cloud && a.rain === b.rain;
out.range_ok = [0, 3, 7.9, 12, 18.25, 23.9].every(h => { const w = weatherAt(20001, h); return w.cloud >= 0 && w.cloud <= 1 && w.rain >= 0 && w.rain <= 1 && w.cloud >= w.rain; });
out.lit = {h20: +litProbability(20).toFixed(2), h3: +litProbability(3).toFixed(2), h12: +litProbability(12).toFixed(2), h24_eq_h0: Math.abs(litProbability(24) - litProbability(0)) < 1e-9};
let litJump = 0; for (let h = 0; h < 24; h += 0.05) litJump = Math.max(litJump, Math.abs(litProbability(h + 0.05) - litProbability(h)));
out.lit.max_jump_per_3min = +litJump.toFixed(3);
out.sun = {noon: +sunElevation(11.7).toFixed(3), midnight: +sunElevation(23.7).toFixed(3), rise: +sunElevation(5.6).toFixed(3)};

// the module builds its material with a THREE stub
class V2 { constructor(x = 0, y = 0){ this.x = x; this.y = y; } set(x, y){ this.x = x; this.y = y; return this; } }
class V3 extends V2 { constructor(x = 0, y = 0, z = 0){ super(x, y); this.z = z; } set(x, y, z){ this.x = x; this.y = y; this.z = z; return this; }
  add(v){ this.x += v.x; this.y += v.y; this.z += v.z; return this; } applyAxisAngle(){ return this; } }
class V4 extends V3 { constructor(x, y, z, w){ super(x, y, z); this.w = w; } }
const loads = [], probes = [];
const THREE = {Vector2: V2, Vector3: V3, Vector4: V4, RepeatWrapping: 1, ClampToEdgeWrapping: 2, SRGBColorSpace: "srgb", NoColorSpace: "", LinearMipmapLinearFilter: 3,
  TextureLoader: class { load(u){ loads.push(u); return {}; } },
  ShaderMaterial: class { constructor(o){ Object.assign(this, o); } },
  WebGLCubeRenderTarget: class { constructor(size, o){ this.size = size; this.texture = {cube: size, ...o}; } },
  CubeCamera: class { constructor(near, far, rt){ this.near = near; this.far = far; this.rt = rt; this.position = new V3(); } update(r, s){ probes.push([r, s]); } },
  Mesh: class { constructor(g, m){ this.geometry = g; this.material = m; this.position = new V3(); this.rotation = new V3(); this.visible = true; } },
  PlaneGeometry: class { constructor(w, h){ this.w = w; this.h = h; } }};
let hdr = false;
const view = createWindowView(THREE, {base: "room/window/", hdr: () => hdr});
const frag = view.material.fragmentShader, vert = view.material.vertexShader, U = view.material.uniforms;
const samplers = [...frag.matchAll(/uniform sampler(?:2D|Cube) (t\w+)/g)].map(m => m[1]);
out.textures = {declared: samplers, loaded: loads.map(u => u.split("/").pop()), every_sampler_has_a_uniform: samplers.every(s => s in U && U[s].value)};
out.uniforms_declared = Object.keys(U).every(k => frag.includes(k) || vert.includes(k));
// the layers the shader uses are the ones the plates were cut for
const plates = JSON.parse(readFileSync(new URL("../../web/room/window/plates.json", import.meta.url), "utf8"));
const same = (a, b) => ["d", "xm", "y0", "y1", "cx"].every(k => Math.abs(a[k] - b[k]) < 1e-6);
out.layers = {near: same(LAYERS.near, plates.layers.near), mid: same(LAYERS.mid, plates.layers.mid), far: same(LAYERS.far, plates.layers.far),
  uniforms: U.uNear.value.x === LAYERS.near.d && U.uMid.value.x === LAYERS.mid.d && U.uFar.value.x === LAYERS.far.d,
  order_ok: LAYERS.near.d < TRAIN.d && TRAIN.d < LAYERS.mid.d && LAYERS.mid.d < LAYERS.far.d,
  sky: plates.sky.rows.length === SKY.rows && plates.sky.az === SKY.az && plates.sky.el0 === SKY.el0 && plates.sky.el1 === SKY.el1, ground: GROUND};
out.gain = GAIN;
out.colorspace_included = frag.includes("#include <colorspace_fragment>");
// a simulated day of updates. The renderer stub records what build() does to the probe's render target: the six faces
// must be cleared and the first probe taken right away (a frozen loop never updates; undefined texels are NaN, #G6)
const added = []; const scene = {add: m => added.push(m)};
const rt = {sets: [], clears: 0, current: "screen"};
const renderer = {getRenderTarget: () => rt.current, setRenderTarget: (t, face) => { rt.current = t; if (t) rt.sets.push(face); }, clear: () => { rt.clears++; }};
const p0 = probes.length;
view.build({c: [-2.012, 1.685, 0.14], w: 1.58, h: 0.89, ry: Math.PI / 2}, scene, renderer);
out.built = added.length === 2 && Math.abs(U.uSize.value.x - 1.58) < 1e-9;      // the plane and the probe camera
out.probe_init = {faces_cleared: rt.sets.filter(f => f !== undefined).length, clears: rt.clears, target_restored: rt.current === "screen", probed_at_build: probes.length - p0};
// NaN never reaches the uniforms or light.sun: a NaN hour or dt keeps the last good values
view.update(0.016, 12); view.update(NaN, NaN); view.update(Number.NaN, 12); view.update(0.016, undefined);
const finite = v => Number.isFinite(v);
out.nan_guard = {light_sun: finite(view.light.sun), uSun: finite(U.uSun.value), uCloud: finite(U.uCloud.value), uEmit: finite(U.uEmit.value), uReflect: finite(U.uReflect.value),
  sunDir: [U.uSunDir.value.x, U.uSunDir.value.y, U.uSunDir.value.z].every(finite), time: finite(view.state().time), hour: view.state().hour};
out.shader_scrubs_nan = /isnan\(env\)/.test(frag) && /isnan\(col\)/.test(frag) && frag.indexOf("isnan(col)") > frag.indexOf("uReflect;");
out.light_sun_initial = Number.isFinite(createWindowView(THREE, {}).light.sun);
view.update(0.016, 8); const sx8 = U.uSunDir.value.x; view.update(0.016, 16); const sx16 = U.uSunDir.value.x;
out.sun_crosses = sx8 < 0 && sx16 > 0;
view.update(0.016, 21); out.lit_uniform_follows_hour = Math.abs(U.uLitP.value - litProbability(21)) < 1e-9;
view.setWeather("rain"); for (let i = 0; i < 400; i++) view.update(0.05, 21);
out.rain_override = {rain: +U.uRain.value.toFixed(3), cloud: +U.uCloud.value.toFixed(3), sun_factor: +view.light.sun.toFixed(3)};
view.setWeather(null); out.state_kind_after_reset = view.state().weather.kind;
// the probe: once at build, then every PROBE.every s; the plane hidden while it renders
const p1 = probes.length; for (let t = 0; t < PROBE.every * 2.5; t += 0.5) view.update(0.5, 12);
out.probe = {renders: probes.length - p1, expected_about: Math.round(2.5), plane_visible_after: view.mesh.visible};
// the HDR hook: emission follows post.hdr (5 by day, 0.05 at night) until setEmission says otherwise
view.update(0.016, 12); const e1 = U.uEmit.value; hdr = true; view.update(0.016, 12); const e2 = U.uEmit.value; view.update(0.016, 1); const e3 = U.uEmit.value;
view.setEmission(2, 0.5); view.update(0.016, 12); const e4 = U.uEmit.value;
out.emission = {plain_day: +e1.toFixed(3), hdr_day: +e2.toFixed(3), hdr_night: +e3.toFixed(3), explicit_day: +e4.toFixed(3)};
// a train passes at night: within one cycle uTrain is in range for a while and the direction alternates between cycles
let seen = 0; const dirs = new Set(); for (let t = 0; t < TRAIN.every * 2; t += 0.5) { view.update(0.5, 21); if (U.uTrain.value > -TRAIN.len) { seen++; dirs.add(U.uTrainDir.value); } }
out.train = {steps_visible: seen, directions: [...dirs].sort()};
const src = readFileSync(new URL("../../web/room/window_view.js", import.meta.url), "utf8");
out.brand_free = !/\b(Sony|Toshiba|Hitachi|Coca|Suntory|Asahi|Kirin|7-?Eleven|Lawson|FamilyMart|Skytree|Tokyo Tower|JR\b|Chuo|Chūō)/i.test(src);
out.honest_weather = /no weather feed/.test(src.replace(/\n\/\/ /g, " ")) && /never presented as real/.test(src.replace(/\n\/\/ /g, " "));
console.log(JSON.stringify(out));
