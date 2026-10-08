// The view out of SUB-01's window (#98 G7): a Tokyo neighbourhood seen from a third-floor room in Kichijōji, from photographs.
//
// One plane sits on the glass (the GLB's SURF_window marker). Its fragment shader casts the view ray from the real camera
// through each pixel of the glass and intersects it with photographic plates behind the window: the low houses of the
// Musashino suburbs by day and the same kind of view at night (mid), the far skyline (far), a utility pole and its cables
// (near), and a real sky at infinity (an atlas of six CC0
// sky photographs: clear, partly cloudy, overcast, sunset, dusk, night, cross-faded by the sun's elevation and the cloud
// cover). So the outside has true parallax from every camera in the room, and nothing of it exists outside the glass.
// The plates are cut out and prepared by room_build/window_cards.py from CC0 sources (Wikimedia Commons, Poly Haven);
// every source is listed in web/room/CREDITS.md and web/room/window/plates.json.
//
//   import { createWindowView } from "./room/window_view.js";
//   const view = createWindowView(THREE, {base:"room/window/", hdr:() => post.hdr});
//   view.build(SURF.window, scene, renderer);   // the plane at the marker (c, w, h, ry); renderer: for the glass's reflection probe
//   view.update(dt, hour);                      // every frame: Tokyo hour (0..24), the clock moves everything
//   view.setWeather("rain" | "overcast" | "clear" | null);   // null: back to the daily pattern
//   view.setEmission(day, night);               // how bright the window is in the room's light units (G6's HDR: 5 / 0.05)
//   view.light.sun                              // 0..1: how much direct sun the weather lets through (for the room's lights)
//
// By the hour: the photographs are relit (daylight as shot; dusk warm and dark; night a city-glow ambient with the homes'
// windows switching on and off from a lights mask, each pane with its own id), the far skyline is a hazy silhouette by
// day and the twilight photograph itself at dusk and night; the sun and the moon cross the window; birds by day; a train's
// lit windows glide past at night. Weather: there is no weather feed in the server (nothing in live_server.py or life.py
// fetches one), so the weather is a deterministic daily pattern (weatherAt: smooth noise over Tokyo time with autumn-Tokyo
// shares, about a fifth of the hours wet), never presented as real. Rain streaks and drops on the glass refract the view;
// rain falls outside; the layers haze over. The glass reflects the room: a 64 px cube probe rendered from just inside
// the glass every 20 s, blended with a Fresnel term.
//
// Budget: one draw call, ≤ ~14 texture reads per glass pixel at most, no per-frame JS beyond a few uniforms.

export const GROUND = -8.2;                  // the street, metres below the window's centre line (a third-floor room)
// the diorama: depth behind the glass (m), the plate's width (m), its y range (m) and the x of its centre (m); a plate's
// metres come from its pixels (room_build/window_cards.py writes them to plates.json; tests compare)
export const LAYERS = {
  near: {d: 14.0,  xm: 16.0,  y0: -9.0,  y1: 7.0,  cx: 0.0, wrap: true},     // the pole and its cables (drawn, silhouettes)
  mid:  {d: 40.0,  xm: 56.0,  y0: -18.0, y1: 13.0, cx: 4.0, wrap: false},     // the neighbourhood (two photographs: day, night)
  far:  {d: 200.0, xm: 48.0,  y0: -1.0,  y1: 11.8, cx: 8.0, wrap: false},     // the skyline at twilight (a photograph), small and far
};
export const SKY = {rows: 6, az: 70.0, el0: -2.0, el1: 50.0};   // the atlas: 6 skies, each ±70° of azimuth and -2..50° of elevation
// perspective gains: 1 = the geometry above. The vertical gain flattens steep views, and the view rays are lifted by a
// slope `pitch` plus `pitchK` per metre the camera stands above the window's centre (up to `pitchMax`): the room's high
// overview camera looks down through the window at ~25°, and would only ever see the street; with the lift the horizon
// follows the camera up and the sky still shows from there. Standing at the window little is lifted. A diorama cheat,
// like a parallax-interior shader's depth setting: the parallax itself stays true.
export const GAIN = {h: 0.7, v: 0.5, pitch: 0.10, pitchK: 0.045, pitchMax: 0.35};
export const TRAIN = {d: 27.0, y: GROUND + 7.0, h: 3.3, len: 72.0, every: 150.0, speed: 17.0};   // lit windows gliding past at night
export const PROBE = {size: 64, every: 20.0, first: 1.5};

export function sunElevation(hour){            // Tokyo, autumn: up ~05:35, down ~17:45 (the room's lighting uses the same curve)
  return Math.sin(Math.PI * (hour - 5.6) / 12.2);
}

// how many homes have their lights on, by Tokyo hour (the shader shows them only once the sky is dark enough)
const LIT = [[0, 0.42], [1, 0.30], [2, 0.14], [4, 0.10], [5, 0.22], [6, 0.36], [7, 0.30], [9, 0.20], [16, 0.25], [17.5, 0.55], [19, 0.78], [22, 0.74], [23, 0.55], [24, 0.42]];
export function litProbability(hour){
  const h = ((hour % 24) + 24) % 24;
  for (let i = 1; i < LIT.length; i++) if (h <= LIT[i][0]) { const [a, pa] = LIT[i - 1], [b, pb] = LIT[i]; return pa + (pb - pa) * (h - a) / (b - a); }
  return LIT[LIT.length - 1][1];
}

// ---- the weather pattern: deterministic, smooth in time, the same for every viewer (no feed exists; see the header)
const fract = x => x - Math.floor(x);
const hash1 = x => fract(Math.sin(x * 127.1 + 311.7) * 43758.5453);
function vnoise1(x){ const i = Math.floor(x), f = x - i, t = f * f * (3 - 2 * f); return hash1(i) + (hash1(i + 1) - hash1(i)) * t; }
const sstep = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
export function weatherAt(dayKey, hour){
  const t = dayKey * 24 + hour;                                  // Tokyo hours since the epoch
  const n = 0.62 * vnoise1(t / 20.0 + 3.1) + 0.38 * vnoise1(t / 6.0 + 71.7);  // fronts over days, showers over hours
  const rain = sstep(0.42, 0.28, n);                             // shares calibrated in tests/js/window_view_check.js
  const cloud = Math.max(sstep(0.60, 0.42, n), rain);
  return {kind: rain > 0.5 ? "rain" : cloud > 0.5 ? "overcast" : "clear", cloud, rain, n};
}
export function tokyoDayKey(date = new Date()){ return Math.floor((date.getTime() / 1000 + 9 * 3600) / 86400); }

// ---- the shader
const VERT = /* glsl */`
  uniform vec3 uLift;                                             // pitch, per metre of camera height, max
  varying vec2 vUv; varying vec3 vWorld; varying vec3 vRight; varying vec3 vUp; varying vec3 vOut; varying float vPitch;
  void main(){
    vUv = uv; vec4 w = modelMatrix * vec4(position, 1.0); vWorld = w.xyz;
    vRight = normalize(modelMatrix[0].xyz); vUp = normalize(modelMatrix[1].xyz); vOut = -normalize(modelMatrix[2].xyz);
    vPitch = uLift.x + clamp(uLift.y * (cameraPosition.y - modelMatrix[3].y), 0.0, uLift.z);
    gl_Position = projectionMatrix * viewMatrix * w;
  }`;

const FRAG = /* glsl */`
  varying vec2 vUv; varying vec3 vWorld; varying vec3 vRight; varying vec3 vUp; varying vec3 vOut; varying float vPitch;
  uniform vec2 uSize; uniform vec2 uGain; uniform float uTime; uniform float uSun; uniform float uRain; uniform float uCloud; uniform float uLitP;
  uniform vec3 uSunDir; uniform vec3 uMoonDir; uniform float uTrain; uniform float uTrainDir; uniform float uEmit; uniform float uReflect;
  uniform sampler2D tNear; uniform sampler2D tMid; uniform sampler2D tMidN; uniform sampler2D tMidL; uniform sampler2D tFar; uniform sampler2D tSky; uniform sampler2D tNoise;
  uniform samplerCube tEnv;
  uniform vec4 uNear; uniform vec4 uMid; uniform vec4 uFar;     // depth, width, y0, y1
  uniform vec3 uCentres;                                        // the x of each plate's centre: near, mid, far
  uniform vec4 uSky;                                            // rows, half azimuth (rad), el0 (rad), el1 (rad)
  uniform vec4 uTrainP;                                         // depth, y, height, length

  float h1(float x){ return fract(sin(x * 127.1 + 311.7) * 43758.5453); }

  // the plate at depth D: metres on its plane -> its texture (wrapping plates repeat; the photographs clamp to a clear edge)
  vec4 plate(sampler2D t, vec4 L, float cx, vec2 g, vec2 slope){
    vec2 p = g + slope * L.x;
    vec2 uv = vec2((p.x - cx) / L.y + 0.5, (p.y - L.z) / (L.w - L.z));
    if (uv.y <= 0.0 || uv.y >= 1.0) return vec4(0.0);
    return texture2D(t, uv);
  }
  // the night photograph's lit windows: each pane has an id in the mask; a hash of id and a 2-minute slot switches some
  // of them off (and on again) with a probability that follows the evening. Returns 0..1 = how much of the pane is dark.
  float lightsOff(sampler2D t, vec4 L, float cx, vec2 g, vec2 slope){
    vec4 m = plate(t, L, cx, g, slope);
    if (m.r < 0.12) return 0.0;
    float id = floor(m.b / m.r * 255.0 + 0.5);                     // premultiplied by the pane coverage
    float slot = floor(uTime / 120.0 + h1(id) * 9.0);
    float on = step(h1(id * 3.17 + slot * 17.7), clamp(uLitP / 0.78, 0.0, 1.0));
    return m.r * (1.0 - on);
  }
  // one sky of the atlas, in a direction
  vec3 skyRow(float row, vec2 ae){
    float u = clamp(ae.x / (2.0 * uSky.y) + 0.5, 0.002, 0.998);
    float vr = clamp((ae.y - uSky.z) / (uSky.w - uSky.z), 0.004, 0.996);
    return texture2D(tSky, vec2(u, 1.0 - (row + 1.0 - vr) / uSky.x)).rgb;
  }
  // the sky in a direction: the photographs cross-faded by the phase of the day and the cloud cover (rows: clear, partly
  // cloudy, overcast, sunset, dusk, night), the city's glow at night
  vec3 skyColor(vec3 dir, float day, float golden, float blue, float night){
    vec2 ae = vec2(atan(dir.x, dir.z) + uTime * 0.00003, asin(clamp(dir.y, -1.0, 1.0)));   // a very slow drift (6° an hour)
    float ov = smoothstep(0.45, 0.9, uCloud), partly = smoothstep(0.05, 0.45, uCloud);
    vec3 s = vec3(0.0);
    if (day > 0.005) s += day * mix(skyRow(0.0, ae), skyRow(1.0, ae), partly);
    if (golden > 0.005) s += golden * skyRow(3.0, ae);
    if (blue > 0.005) s += blue * skyRow(4.0, ae);
    if (night > 0.005) s += night * skyRow(5.0, ae) * 0.45;              // the photograph is a moonlit sky: Tokyo's is darker
    if (ov > 0.005) {
      vec3 o = skyRow(2.0, ae) * (0.025 + 0.975 * smoothstep(-0.22, 0.12, uSun));            // the overcast sky, dimmed at night
      o += vec3(0.30, 0.16, 0.07) * night * 0.6 * exp(-max(dir.y, 0.0) * 5.0);               // Tokyo's clouds glow orange
      s = mix(s, o, ov);
    }
    s += vec3(0.34, 0.17, 0.07) * night * (1.0 - ov) * 0.5 * exp(-max(dir.y, 0.0) * 8.0);    // the city's glow on the horizon
    return s;
  }

  void main(){
    vec3 d = normalize(vWorld - cameraPosition);
    float dz = max(dot(d, vOut), 0.03);
    float dx = dot(d, vRight) * uGain.x, dy = dot(d, vUp) * uGain.y + vPitch * dz;
    vec2 g = (vUv - 0.5) * uSize;                                  // where on the glass, metres from its centre

    // --- phases of the day from the sun's elevation (-1..1), normalised
    float day = smoothstep(0.02, 0.35, uSun);
    float golden = exp(-pow((uSun - 0.04) / 0.11, 2.0));
    float blue = exp(-pow((uSun + 0.12) / 0.07, 2.0));
    float night = 1.0 - smoothstep(-0.24, -0.06, uSun);
    float w = day + golden + blue + night + 1e-4; day /= w; golden /= w; blue /= w; night /= w;
    float dark = 1.0 - smoothstep(-0.02, 0.22, uSun);              // lit windows show from sunset on

    // --- rain on the glass: drops refract the view (sliding down slowly), streaks run
    float dropA = 0.0;
    if (uRain > 0.002) {
      vec4 n1 = texture2D(tNoise, vUv * vec2(1.9, 1.0) + vec2(0.0, uTime * 0.010));
      vec2 off = (n1.ba - 0.5) * 2.0;
      dropA = length(off);
      dx += off.x * 0.010 * uRain; dy += off.y * 0.010 * uRain;
    }
    // metres sideways and up per metre of depth. Seen along the glass the true slope explodes (30 m sideways per metre
    // of depth at 88°) and the finite plates run out, leaving only sky: the slope is soft-clamped (an asymptote of
    // 0.55 m/m sideways, 0.9 m/m up), so a grazing look still lands on the neighbourhood, compressed, as the eye expects
    vec2 slope = vec2(dx, dy) / dz;
    slope = slope / (1.0 + abs(slope) / vec2(0.55, 0.9));
    vec3 dir = normalize(vec3(dx, dy, dz));                        // the sky direction (x right, y up, z out)

    // --- the sky (a photograph), the sun and the moon on it
    vec3 sky = skyColor(dir, day, golden, blue, night);
    float cs = dot(dir, uSunDir);
    float sunVis = smoothstep(-0.08, 0.04, uSun) * (1.0 - 0.95 * smoothstep(0.3, 0.9, uCloud));
    vec3 sunCol = mix(vec3(1.0, 0.45, 0.15), vec3(1.0, 0.96, 0.88), smoothstep(0.0, 0.3, uSun));
    sky += sunCol * sunVis * (0.12 * pow(max(cs, 0.0), 6.0) * (0.5 + golden) + 0.5 * pow(max(cs, 0.0), 120.0) + 2.5 * smoothstep(0.99935, 0.99965, cs));
    float cm = dot(dir, uMoonDir);
    float moon = smoothstep(0.99955, 0.99975, cm) * (1.0 - 0.9 * smoothstep(0.99955, 0.99975, dot(dir, normalize(uMoonDir + vec3(0.012, 0.004, 0.0)))));
    sky += vec3(0.95, 0.97, 1.0) * night * moon * (1.0 - 0.9 * uCloud) + vec3(0.25, 0.30, 0.45) * night * 0.04 * pow(max(cm, 0.0), 40.0) * (1.0 - uCloud);
    // birds, by day: four of them crossing, flapping
    if (day > 0.3 && dir.y > 0.05 && uRain < 0.3) {
      float az = atan(dir.x, dir.z), el = asin(clamp(dir.y, -1.0, 1.0));
      for (int i = 0; i < 4; i++) {
        float fi = float(i);
        float ph = fract(uTime * 0.011 + fi * 0.26);
        vec2 q = vec2(az - (ph * 1.7 - 0.85), el - (0.16 + 0.08 * sin(fi * 2.1 + uTime * 0.21) + 0.04 * fi));
        float flap = sin(uTime * (9.0 + fi) + fi * 1.7);
        float b = smoothstep(0.0022, 0.0009, abs(q.y - flap * 0.6 * abs(q.x))) * step(abs(q.x), 0.0075);
        sky = mix(sky, vec3(0.02, 0.02, 0.03), b * smoothstep(0.0, 0.1, ph) * smoothstep(1.0, 0.9, ph));
      }
    }
    // the haze's colour: the sky just above the horizon in this direction
    vec3 horizonCol = skyColor(normalize(vec3(dir.x, 0.03, dir.z)), day, golden, blue, night);

    // --- light on the photographs by time of day: daylight as shot, dusk warm and dark, night a city-glow ambient
    vec3 tint = mix(vec3(0.030, 0.034, 0.060), vec3(1.0), day);
    tint = mix(tint, vec3(0.30, 0.22, 0.20), golden * 0.75);
    tint = mix(tint, vec3(0.09, 0.10, 0.17), blue * 0.8);
    tint *= 1.0 - 0.38 * smoothstep(0.3, 0.9, uCloud) - 0.12 * uRain;
    float haze = 0.30 + 0.30 * uCloud + 0.15 * uRain;

    vec3 col = sky;
    // far: the skyline. By day a silhouette in the haze (the photograph's luminance, greyed); at dusk and night the
    // twilight photograph itself, with its real lights
    vec4 f = plate(tFar, uFar, uCentres.z, g, slope);
    if (f.a > 0.002) {
      float lum = dot(f.rgb, vec3(0.3, 0.5, 0.2));
      vec3 dayFar = horizonCol * (0.80 + 0.12 * smoothstep(0.0, 0.5, lum)) * (1.0 - 0.1 * haze);   // a faint grey-blue silhouette in the haze
      vec3 duskFar = mix(f.rgb * (0.55 + 0.45 * (1.0 - night)) + f.rgb * night * 0.25, horizonCol, haze * 0.5);
      col = mix(col, mix(duskFar, dayFar, day), f.a);
    }
    // the train, between the far and the mid plates: lit windows gliding past at night (nothing by day)
    if (uTrain > -uTrainP.w && dark > 0.05) {
      vec2 tp = g + slope * uTrainP.x;
      float tx = tp.x * uTrainDir - uTrain;
      if (tp.y > uTrainP.y && tp.y < uTrainP.y + uTrainP.z && tx > 0.0 && tx < uTrainP.w) {
        float ry = (tp.y - uTrainP.y) / uTrainP.z;
        float win = step(0.50, ry) * step(ry, 0.80) * step(0.22, fract(tx / 1.5)) * step(0.15, fract(tx / 20.0)) * step(fract(tx / 20.0), 0.97);
        col = mix(col, vec3(0.05, 0.05, 0.07) * dark + col * (1.0 - dark), 0.85 * dark);
        col += vec3(1.0, 0.92, 0.7) * win * dark * 0.9;
      }
    }
    // mid: the neighbourhood. By day the daylight photograph, relit by the hour; the night photograph fades in through
    // the blue hour, with some of its real lit windows switching off and on
    float nightW = smoothstep(-0.02, -0.14, uSun);
    vec4 md = nightW < 0.999 ? plate(tMid, uMid, uCentres.y, g, slope) : vec4(0.0);
    vec4 mn = nightW > 0.001 ? plate(tMidN, uMid, uCentres.y, g, slope) : vec4(0.0);
    float ma = mix(md.a, mn.a, nightW);
    if (ma > 0.002) {
      vec3 dayCol = mix(md.rgb * tint, horizonCol, haze * 0.25);
      vec3 nightCol = mn.rgb * (0.62 + 0.28 * night);
      if (nightW > 0.001) nightCol = mix(nightCol, nightCol * 0.12, lightsOff(tMidL, uMid, uCentres.y, g, slope));
      nightCol *= 1.0 - 0.3 * smoothstep(0.3, 0.9, uCloud);
      col = mix(col, mix(dayCol, nightCol, nightW), ma);
    }
    // rain falling, in front of the buildings
    if (uRain > 0.002) {
      vec2 rp = g + slope * (uNear.x + 4.0);
      float r = texture2D(tNoise, vec2(rp.x * 0.33, rp.y * 0.045 + uTime * 0.85)).g;
      col = mix(col, horizonCol * 1.2 + vec3(0.08), smoothstep(0.35, 0.9, r) * uRain * 0.2);
    }
    // near: the utility pole and its cables, silhouettes
    vec4 nr = plate(tNear, uNear, uCentres.x, g, slope);
    col = mix(col, mix(nr.rgb * tint, horizonCol, haze * 0.05), nr.a);

    // --- the glass: transmission, the room's reflection (a cube probe) by Fresnel, the rain's highlights
    // Fresnel, capped: a real pane at 80° reflects ~35 %, never the whole room; by day the view outside is far brighter
    // than the room, so its reflection barely shows (uReflect follows the hour); the view itself keeps ≥ 70 %
    float fres = min(0.04 + 0.96 * pow(1.0 - dz, 5.0), 0.25);
    vec3 env = textureCube(tEnv, reflect(d, -vOut)).rgb;
    env = min(mix(env, vec3(0.0), vec3(isnan(env))), vec3(1.0));   // a probe not yet rendered is black, a lit wall never blows out
    col = col * vec3(0.93, 0.96, 0.95) * (1.0 - 0.85 * fres) + env * fres * uReflect;
    if (uRain > 0.002) {
      float s = texture2D(tNoise, vec2(vUv.x * 2.2, vUv.y * 0.5 + uTime * 0.22)).g;
      col += (smoothstep(0.6, 0.95, s) * 0.10 + dropA * dropA * 0.09) * uRain * (0.15 + 0.85 * day) * (sky * 0.5 + 0.2);
    }
    col = max(mix(col, vec3(0.0), vec3(isnan(col))), vec3(0.0));   // never a NaN or a negative texel (an environment capture reads this pane)
    gl_FragColor = vec4(col * uEmit, 1.0);
    #include <colorspace_fragment>
  }`;

export function createWindowView(THREE, opts = {}){
  const base = opts.base ?? "room/window/";
  const loader = new THREE.TextureLoader();
  const tex = (name, srgb, aniso = 4, wrap = true) => {
    const t = loader.load(base + name + ".webp");
    t.wrapS = wrap ? THREE.RepeatWrapping : THREE.ClampToEdgeWrapping; t.wrapT = THREE.ClampToEdgeWrapping;
    t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
    t.anisotropy = aniso; t.flipY = true;
    return t;
  };
  const tNear = tex("near", true), tMid = tex("mid", true, 8, false), tMidN = tex("mid_n", true, 8, false), tMidL = tex("mid_l", false, 4, false);
  const tFar = tex("far", true, 8, false), tSky = tex("sky", true, 4, false), tNoise = tex("noise", false, 1);
  tNoise.wrapT = THREE.RepeatWrapping;
  const envRT = new THREE.WebGLCubeRenderTarget(PROBE.size, {generateMipmaps: true, minFilter: THREE.LinearMipmapLinearFilter});
  const L = l => new THREE.Vector4(l.d, l.xm, l.y0, l.y1);
  const rad = x => x * Math.PI / 180;
  const material = new THREE.ShaderMaterial({
    uniforms: {
      uSize: {value: new THREE.Vector2(1.5, 0.8)}, uGain: {value: new THREE.Vector2(GAIN.h, GAIN.v)}, uLift: {value: new THREE.Vector3(GAIN.pitch, GAIN.pitchK, GAIN.pitchMax)},
      uTime: {value: 0}, uSun: {value: 0.5}, uRain: {value: 0}, uCloud: {value: 0}, uLitP: {value: 0}, uEmit: {value: 1}, uReflect: {value: 0.6},
      uSunDir: {value: new THREE.Vector3(0, 0.3, 1)}, uMoonDir: {value: new THREE.Vector3(0, 0.3, 1)}, uTrain: {value: -1e3}, uTrainDir: {value: 1},
      tNear: {value: tNear}, tMid: {value: tMid}, tMidN: {value: tMidN}, tMidL: {value: tMidL}, tFar: {value: tFar}, tSky: {value: tSky}, tNoise: {value: tNoise}, tEnv: {value: envRT.texture},
      uNear: {value: L(LAYERS.near)}, uMid: {value: L(LAYERS.mid)}, uFar: {value: L(LAYERS.far)},
      uCentres: {value: new THREE.Vector3(LAYERS.near.cx, LAYERS.mid.cx, LAYERS.far.cx)},
      uSky: {value: new THREE.Vector4(SKY.rows, rad(SKY.az), rad(SKY.el0), rad(SKY.el1))},
      uTrainP: {value: new THREE.Vector4(TRAIN.d, TRAIN.y, TRAIN.h, TRAIN.len)},
    },
    vertexShader: VERT, fragmentShader: FRAG, toneMapped: false,
  });
  const U = material.uniforms;
  const state = {hour: 12, sun: 0.5, weather: {kind: "clear", cloud: 0, rain: 0}, override: opts.weather ?? null, litP: 0, train: null, time: 0, probes: 0, emit: {day: 1, night: 1}, hdr: false};
  const light = {sun: 1, cloud: 0, rain: 0};
  let mesh = null, cloud = 0, rain = 0, probeCam = null, renderer = null, scene = null, probeAt = -1e9, emitSet = false;

  function build(surf, sc, rend){
    mesh = new THREE.Mesh(new THREE.PlaneGeometry(surf.w, surf.h), material);
    mesh.position.set(...surf.c); mesh.rotation.y = surf.ry; mesh.name = "window_view";
    U.uSize.value.set(surf.w, surf.h);
    scene = sc || null; renderer = rend || null;
    if (scene) scene.add(mesh);
    if (renderer && THREE.CubeCamera) {                          // the reflection probe, just inside the glass
      probeCam = new THREE.CubeCamera(0.05, 30, envRT);
      probeCam.position.set(...surf.c).add(new THREE.Vector3(0, 0, 0.25).applyAxisAngle(new THREE.Vector3(0, 1, 0), surf.ry));
      scene.add(probeCam);
      // a render target starts with undefined texels (NaN under software GL, and a frozen loop never updates): clear the
      // six faces to black now and take the first probe right away, so the glass never samples garbage
      const was = renderer.getRenderTarget ? renderer.getRenderTarget() : null;
      for (let face = 0; face < 6; face++) { renderer.setRenderTarget(envRT, face); renderer.clear(); }
      renderer.setRenderTarget(was);
      probe(); probeAt = state.time;
    }
    return mesh;
  }
  function probe(){                                              // the room as the glass sees it (the view plane hidden)
    if (!probeCam || !renderer || !scene) return;
    mesh.visible = false; probeCam.update(renderer, scene); mesh.visible = true;
    state.probes++;
  }
  function target(){
    if (state.override) return state.override === "rain" ? {kind: "rain", cloud: 1, rain: 1} : state.override === "overcast" ? {kind: "overcast", cloud: 1, rain: 0} : {kind: "clear", cloud: 0, rain: 0};
    return weatherAt(tokyoDayKey(), state.hour);
  }
  function setEmission(day, night){ state.emit = {day, night}; emitSet = true; }
  function update(dt, hour){
    // a NaN hour or dt (a clock not yet read, a bad tick) would poison every uniform and light.sun: keep the last good ones
    if (!Number.isFinite(hour)) hour = state.hour;
    if (!Number.isFinite(dt) || dt < 0) dt = 0;
    state.time += dt; state.hour = hour;
    const sunEl = sunElevation(hour); state.sun = sunEl;
    U.uTime.value = state.time; U.uSun.value = sunEl;
    // the sun crosses the window from the viewer's left to the right over the day, low in the morning and the evening
    const td = Math.min(1, Math.max(0, (hour - 5.6) / 12.2));
    const az = (-48 + 96 * td) * Math.PI / 180, el = (7 + 34 * Math.max(0, sunEl)) * Math.PI / 180;
    U.uSunDir.value.set(Math.sin(az) * Math.cos(el), Math.sin(el), Math.cos(az) * Math.cos(el));
    const tn = (((hour - 17.8) / 12.2) % 1 + 1) % 1;
    const maz = (-40 + 80 * tn) * Math.PI / 180, mel = (10 + 28 * Math.sin(Math.PI * tn)) * Math.PI / 180;
    U.uMoonDir.value.set(Math.sin(maz) * Math.cos(mel), Math.sin(mel), Math.cos(maz) * Math.cos(mel));
    // weather eases towards its target (a front takes minutes to arrive, a debug switch about two seconds)
    const w = target(); state.weather = w;
    const k = 1 - Math.exp(-dt * (state.override ? 1.5 : 0.05));
    cloud += (w.cloud - cloud) * k; rain += (w.rain - rain) * k;
    U.uCloud.value = cloud; U.uRain.value = rain;
    light.cloud = cloud; light.rain = rain; light.sun = 1 - 0.85 * cloud;
    state.litP = U.uLitP.value = litProbability(hour);
    // the window's brightness in the room's units: G6's HDR scale when the page says so (unless set explicitly)
    if (opts.hdr && !emitSet) { const h = !!opts.hdr(); if (h !== state.hdr) { state.hdr = h; state.emit = h ? {day: 5, night: 0.05} : {day: 1, night: 1}; } }
    const dayK = sstep(-0.12, 0.2, sunEl);
    U.uEmit.value = state.emit.night + (state.emit.day - state.emit.night) * dayK;
    U.uReflect.value = 0.32 - 0.22 * dayK;                      // the room shows faintly in the glass at night, hardly by day
    // the train: every TRAIN.every s one passes, alternating direction
    const cyc = Math.floor(state.time / TRAIN.every), ph = state.time - cyc * TRAIN.every, dir = cyc % 2 ? -1 : 1;
    const x = ph * TRAIN.speed - TRAIN.len - 40;                // its tail, from well off one side to well off the other
    const on = x < 40;
    U.uTrain.value = on ? x : -1e3; U.uTrainDir.value = dir;
    state.train = on ? {x, dir} : null;
    // the glass's reflection of the room: refreshed every PROBE.every seconds (the first one once the room has loaded)
    if (probeCam && state.time - probeAt > (state.probes ? PROBE.every : PROBE.first) && !(typeof document !== "undefined" && document.hidden)) { probeAt = state.time; probe(); }
  }
  function setWeather(kind){ state.override = kind || null; }
  return {material, get mesh(){ return mesh; }, build, update, setWeather, setEmission, probe, light, state: () => ({...state, cloud, rain}), LAYERS, GAIN, SKY};
}
