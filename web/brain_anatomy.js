/* BrainAnatomy: the brain on /brain drawn as a real specimen (issue #99, worker G9).

   What is HIS (one person's public MRI, the same data as the fibres): the cortex surface with its gyri and sulci
   (cortex.bin), his cerebellum and brainstem as separate surfaces (web/anatomy/cerebellum.bin, brainstem.bin: his own
   tissue, folia at 1 mm), and the cut plane, which shows HIS T1 scan (web/anatomy/t1_atlas.png) coloured as grey and
   white matter. What is an ATLAS (BodyParts3D, © The Database Center for Life Science, CC BY 4.0; another adult's body,
   fitted to his brain with one similarity transform): the cerebral arteries (circle of Willis and trunks), the optic
   nerves / chiasm / tracts (II), the trochlear (IV) and ophthalmic (V1) nerves, the pituitary gland and a spinal cord
   stub; the dural sinuses and large veins come from the VENAT atlas (Huck 2019, CC BY 4.0, 20 adults, affinely fitted).
   Cranial nerves I, VI-XII and the trunks of III and V, and the small bridging veins, are NOT drawn: no licensed
   source has them and nothing is invented. The caption says all of this on every view. A model, not a mind.

   Views: "glow" (the page's own look, nothing changed), "fresh" (pinkish-grey cortex, glistening pia, red arteries),
   "fixed" (formalin-grey, matte, cut open on a plane: his T1 as grey / white matter), "bundles" (the cortex a ghost, the
   real fibres as muted white-matter bundles coloured by direction, not glowing). Layers: vessels, nerves.

   No dots, sprites or point markers anywhere (owner's rule): every part is a lit mesh. `window.zoomBrain` (the page's
   zoom into a cortical column, 1 = whole brain) fades every material of ours like the page's own.

   Usage (classic script; THREE r128 or r169):
     const anat = BrainAnatomy.create({THREE, scene, renderer, camera, cortex, fibres, base: "/anatomy/", caption});
       cortex  : the page's cortex THREE.Mesh (cortex.bin geometry with normals); its material is swapped while a
                 realistic view is on and restored on "glow" (the page's own uniform updates keep pointing at it)
       fibres  : the page's fibres THREE.LineSegments (attribute dcol); same swap
       caption : (html) => void, called whenever the provenance line changes
     anat.setView("fresh"|"fixed"|"bundles"|"glow"); anat.setLayer("vessels"|"nerves", on); anat.setCut(axis, t)
     anat.update(nowMs) once a rendered frame (frame-time tier); anat.state() for tests and captions; anat.dispose()
   Pure helpers (tested in node with a THREE stub, tests/js/brain_anatomy_check.js): parseParts, sulcalDepth, cutPlane,
   tissueColour, captionFor, PALETTE. */
(function (root) {
  "use strict";

  // ---------- colours (display sRGB 0-1; approximate values read off open-licence photographs of fresh and fixed
  // human brains, see docs/research/real_brain_sources.md § colour) ----------
  const PALETTE = {
    fresh: { cerebrum: [0.74, 0.60, 0.56], cerebellum: [0.66, 0.50, 0.47], brainstem: [0.80, 0.70, 0.66],
             grey: [0.68, 0.56, 0.54], white: [0.92, 0.88, 0.85], csf: [0.30, 0.17, 0.17],
             artery: [0.72, 0.10, 0.10], vein: [0.36, 0.12, 0.20], nerve: [0.93, 0.88, 0.75], gland: [0.72, 0.42, 0.42], cord: [0.80, 0.70, 0.66],
             spec: 0.55, shine: 56, wrap: 0.32, scatter: 0.22, vessel: 1.0, wet: 1.0 },
    fixed: { cerebrum: [0.62, 0.57, 0.53], cerebellum: [0.57, 0.52, 0.48], brainstem: [0.70, 0.65, 0.60],
             grey: [0.60, 0.56, 0.52], white: [0.90, 0.87, 0.82], csf: [0.16, 0.15, 0.14],
             artery: [0.42, 0.20, 0.17], vein: [0.30, 0.20, 0.24], nerve: [0.86, 0.82, 0.72], gland: [0.60, 0.50, 0.45], cord: [0.70, 0.65, 0.60],
             spec: 0.10, shine: 12, wrap: 0.22, scatter: 0.0, vessel: 0.35, wet: 0.3 },
  };
  PALETTE.bundles = PALETTE.fixed;
  const PART = { cerebrum: 1, cerebellum: 2, brainstem: 3 };
  const AXES = { coronal: [0, 1, 0], sagittal: [-1, 0, 0], axial: [0, 0, 1] };   // the side the camera starts on is removed
  const VIEWS = ["glow", "fresh", "fixed", "bundles"];
  const LIVE_FPS = 28;                                                            // below it for 3 s: the low tier

  // ---------- pure helpers ----------
  // parts.bin -> [{label, kind, pos: Float32Array(mm), idx}] (int16 positions in `unit_mm`, 4-byte aligned blocks)
  function parseParts(buf, meta) {
    const u = meta.unit_mm, out = [];
    for (const r of meta.parts) {
      const q = new Int16Array(buf, r.pos, r.verts * 3), pos = new Float32Array(q.length);
      for (let i = 0; i < q.length; i++) pos[i] = q[i] * u;
      const idx = r.idx_type === "uint16" ? new Uint16Array(buf, r.idx, r.n_idx) : new Uint32Array(buf, r.idx, r.n_idx);
      out.push({ label: r.label, kind: r.kind, pos, idx, faces: r.faces, source: r.source });
    }
    return out;
  }
  // signed volume (cm3) of an indexed triangle mesh: negative when the winding is clockwise seen from outside
  // (marching-cubes meshes often are); the shaders and the sulcal depth follow the sign instead of trusting it
  function signedVolume(pos, idx) {
    let v = 0;
    for (let i = 0; i < idx.length; i += 3) {
      const a = idx[i] * 3, b = idx[i + 1] * 3, c = idx[i + 2] * 3;
      v += pos[a] * (pos[b + 1] * pos[c + 2] - pos[b + 2] * pos[c + 1]) - pos[a + 1] * (pos[b] * pos[c + 2] - pos[b + 2] * pos[c])
         + pos[a + 2] * (pos[b] * pos[c + 1] - pos[b + 1] * pos[c]);
    }
    return v / 6000;
  }
  // connected components of an indexed mesh (union-find): vertex -> component size, so crumbs can be left out
  function componentSizes(nVerts, idx) {
    const parent = new Int32Array(nVerts); for (let i = 0; i < nVerts; i++) parent[i] = i;
    const find = i => { while (parent[i] !== i) { parent[i] = parent[parent[i]]; i = parent[i]; } return i; };
    for (let i = 0; i < idx.length; i += 3) { const a = find(idx[i]), b = find(idx[i + 1]), c = find(idx[i + 2]); parent[b] = a; parent[c] = a; }
    const count = new Int32Array(nVerts); for (let i = 0; i < nVerts; i++) count[find(i)]++;
    const size = new Int32Array(nVerts); for (let i = 0; i < nVerts; i++) size[i] = count[find(i)];
    return size;
  }
  // how deep each vertex sits below a smoothed copy of its own surface (0 crown of a gyrus .. 1 bottom of a sulcus):
  // Laplacian smoothing over the index buffer, then the signed distance along the normal, normalised by its 98th centile
  function sulcalDepth(pos, idx, normals, iters, sign) {
    const n = pos.length / 3, deg = new Float32Array(n), sg = sign || 1;
    let s = Float32Array.from(pos);
    for (let i = 0; i < idx.length; i += 3) for (let k = 0; k < 3; k++) deg[idx[i + k]] += 2;
    for (let it = 0; it < (iters || 12); it++) {
      const acc = new Float32Array(n * 3);
      for (let i = 0; i < idx.length; i += 3) {
        const a = idx[i], b = idx[i + 1], c = idx[i + 2];
        for (let k = 0; k < 3; k++) {
          acc[3 * a + k] += s[3 * b + k] + s[3 * c + k];
          acc[3 * b + k] += s[3 * a + k] + s[3 * c + k];
          acc[3 * c + k] += s[3 * a + k] + s[3 * b + k];
        }
      }
      const t = new Float32Array(n * 3);
      for (let v = 0; v < n; v++) { const d = deg[v] || 1; for (let k = 0; k < 3; k++) t[3 * v + k] = 0.5 * s[3 * v + k] + 0.5 * acc[3 * v + k] / d; }
      s = t;
    }
    const depth = new Float32Array(n);
    for (let v = 0; v < n; v++) {
      let d = 0; for (let k = 0; k < 3; k++) d += (s[3 * v + k] - pos[3 * v + k]) * normals[3 * v + k] * sg;
      depth[v] = Math.max(0, d);                                                   // the smooth surface lies above a sulcus
    }
    const sorted = Float32Array.from(depth).sort(), hi = sorted[Math.floor(0.98 * (n - 1))] || 1;
    for (let v = 0; v < n; v++) depth[v] = Math.min(1, depth[v] / hi);
    return depth;
  }
  // the cut: axis name + t in 0..1 across the brain's bounding box -> {n:[3], d} with "discard where dot(p, n) > d"
  function cutPlane(axis, t, bbox) {
    const n = AXES[axis] || AXES.coronal, a = n.indexOf(1) >= 0 ? n.indexOf(1) : n.indexOf(-1);
    const lo = bbox.min[a], hi = bbox.max[a], x = lo + (hi - lo) * Math.min(1, Math.max(0, t));
    return { n, d: n[a] * x, axis: AXES[axis] ? axis : "coronal", value_mm: x };
  }
  // one T1 intensity (0..1, the atlas byte) -> tissue colour by the landmarks of HIS histogram (csf / grey / white)
  function tissueColour(v, pal, tissue) {
    const sm = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
    const g = sm(tissue.csf, tissue.grey, v), w = sm(tissue.grey, tissue.white, v);
    return [0, 1, 2].map(k => { const c1 = pal.csf[k] + (pal.grey[k] - pal.csf[k]) * g; return c1 + (pal.white[k] - c1) * w; });
  }
  function captionFor(meta, st) {
    const fit = meta && meta.parts && meta.parts.fit, rms = fit ? ` (fitted to his brain, surface error ~${fit.rms_mm} mm)` : "";
    const atlas = (meta && meta.parts && meta.parts.parts) || [];
    const names = kinds => atlas.filter(p => kinds.includes(p.kind)).map(p => p.label);
    const specimen = st.view === "fresh" || st.view === "fixed";                     // the views that draw his cerebellum and brainstem
    const his = ["cortex (gyri and sulci)"].concat(st.meshes && specimen ? ["cerebellum (folia)", "brainstem"] : []);
    const lines = [];
    if (st.view === "fresh") lines.push("<b>fresh specimen</b>: pinkish-grey cortex under a glistening pia; colours are approximate, from open photographs; the reddish runs in the sulci are a shading cue for pial vessels, not drawn vessels");
    else if (st.view === "fixed") lines.push(`<b>fixed and dissected</b>: formalin-grey; the ${st.cut.axis} cut shows HIS T1 scan as grey and white matter (ventricles dark)`);
    else if (st.view === "bundles") lines.push("<b>white-matter bundles</b>: his real diffusion fibres, muted colours by direction (red left-right, green front-back, blue up-down), no glow; a stimulus still travels along its route and sleep cools the tint; the cortex a ghost");
    lines.push(`from HIS MRI: ${his.join(", ")}${st.view === "fixed" ? ", the cut (his T1, 2 mm)" : ""}; the fibres are his real tractography.`);
    const shown = [].concat(st.layers.vessels ? names(["artery"]) : [], st.layers.nerves ? names(["nerve", "gland"]) : [], st.parts && specimen ? names(["cord"]) : []);
    if (shown.length) lines.push(`from an ATLAS (BodyParts3D, another adult; © DBCLS, CC BY 4.0${rms}): ${shown.join(", ")}.`);
    if (st.layers.vessels && names(["vein"]).length) lines.push(`from an ATLAS (VENAT, 20 adults' veins at 7 T, Huck 2019, CC BY 4.0; affinely fitted): ${names(["vein"]).join(", ")}; the small bridging veins are below its threshold.`);
    const missing = meta && meta.parts && meta.parts.not_in_atlas;
    if ((st.layers.nerves || st.layers.vessels) && missing) lines.push(`not drawn (no licensed source; nothing is invented): ${missing.join(", ")}.`);
    if (st.tier === "low") lines.push("low-detail tier (frame rate)");
    lines.push("A model, not a mind.");
    return lines.join(" · ");
  }

  // ---------- shaders (GLSL 1, WebGL1 and 2) ----------
  const LIGHT = `
    uniform vec3 uBase; uniform float uSpec; uniform float uShine; uniform float uWrap; uniform float uScatter;
    float h3(vec3 p) { return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453); }
    float vnoise(vec3 p) {                                           // value noise: wet patches, roughness, vessel runs
      vec3 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
      float a = h3(i), b = h3(i + vec3(1.0, 0.0, 0.0)), c = h3(i + vec3(0.0, 1.0, 0.0)), d = h3(i + vec3(1.0, 1.0, 0.0));
      float e = h3(i + vec3(0.0, 0.0, 1.0)), g = h3(i + vec3(1.0, 0.0, 1.0)), hh = h3(i + vec3(0.0, 1.0, 1.0)), k = h3(i + vec3(1.0, 1.0, 1.0));
      return mix(mix(mix(a, b, f.x), mix(c, d, f.x), f.y), mix(mix(e, g, f.x), mix(hh, k, f.x), f.y), f.z);
    }
    vec3 lit(vec3 albedo, vec3 N, vec3 V, float ao, float specMul, float shineMul) {
      vec3 L = normalize(vec3(-0.45, 0.55, 0.70)), L2 = normalize(vec3(0.6, -0.2, 0.4));
      vec3 a = pow(albedo, vec3(2.2));
      float nl = dot(N, L), wrap = clamp((nl + uWrap) / (1.0 + uWrap), 0.0, 1.0);
      float fill = 0.14 * clamp(dot(N, L2), 0.0, 1.0), sky = 0.08 + 0.07 * N.y;
      vec3 H = normalize(L + V), spec = vec3(1.0) * uSpec * specMul * pow(max(dot(N, H), 0.0), uShine * shineMul);
      float fres = pow(1.0 - max(dot(N, V), 0.0), 4.0) * specMul;
      vec3 scat = a * vec3(1.0, 0.72, 0.68) * uScatter * pow(clamp((nl + 0.7) / 1.7, 0.0, 1.0), 1.5);
      float cav = 1.0 - 0.75 * pow(ao, 0.7);
      vec3 c = a * (wrap * 1.15 + fill + sky) * cav + scat * cav + (spec + fres * 0.10) * (1.0 - 0.9 * ao);
      return pow(max(c, 0.0), vec3(1.0 / 2.2));
    }`;
  const CLIP = `uniform vec4 uClip; uniform float uClipOn; uniform float uFlip; uniform float uAlpha; varying vec3 vW;
    void clipIt() { if (uClipOn > 0.5 && dot(vW, uClip.xyz) > uClip.w) discard; }`;
  const TISSUE_V = `
    attribute float part; attribute float depth;
    varying vec3 vN; varying vec3 vV; varying vec3 vW; varying float vPart; varying float vDepth;
    void main() {
      vec4 mv = modelViewMatrix * vec4(position, 1.0);
      vN = normalize(normalMatrix * normal); vV = normalize(-mv.xyz); vW = (modelMatrix * vec4(position, 1.0)).xyz;
      vPart = part; vDepth = depth;
      gl_Position = projectionMatrix * mv;
    }`;
  const TISSUE_F = `
    precision highp float;
    uniform vec3 uCerebrum; uniform vec3 uCerebellum; uniform vec3 uBrainstem; uniform vec3 uWhite; uniform float uHide; uniform float uVessel; uniform float uWet;
    varying vec3 vN; varying vec3 vV; varying float vPart; varying float vDepth;
    ${CLIP}
    ${LIGHT}
    void main() {
      clipIt();
      if (vPart < 0.5) discard;                                // a crumb of the mesh (a disconnected fragment)
      if (uHide > 0.5 && vPart > 1.5) discard;                 // (off) his cerebellum / brainstem come as their own finer meshes
      vec3 N = normalize(vN) * uFlip;                           // computed normals follow the winding; uFlip makes them outward
      bool outside = gl_FrontFacing == (uFlip > 0.0);
      if (!outside) { gl_FragColor = vec4(pow(pow(uWhite, vec3(2.2)) * 0.55, vec3(1.0 / 2.2)), uAlpha); return; }   // the inside of the shell at a cut
      vec3 base = vPart < 1.5 ? uCerebrum : (vPart < 2.5 ? uCerebellum : uBrainstem);
      // the pia: wet patches (a translucent film, wetter here and there) and finer roughness; pial vessels run along the
      // sulci: a reddish tint where the surface dips, broken up along its length (a shading cue, not drawn vessels)
      float wet = mix(0.45, 1.6, vnoise(vW * 0.11)), rough = mix(0.55, 1.4, vnoise(vW * 0.45 + 3.0));
      float ves = smoothstep(0.30, 0.85, vDepth) * smoothstep(0.42, 0.72, vnoise(vW * 0.9 + 7.0));
      base = mix(base, vec3(0.50, 0.14, 0.16), uVessel * 0.55 * ves);
      gl_FragColor = vec4(lit(base, N, normalize(vV), vDepth, mix(1.0, wet, uWet), rough), uAlpha);
    }`;
  const PART_V = `
    varying vec3 vN; varying vec3 vV; varying vec3 vW;
    void main() {
      vec4 mv = modelViewMatrix * vec4(position, 1.0);
      vN = normalize(normalMatrix * normal); vV = normalize(-mv.xyz); vW = (modelMatrix * vec4(position, 1.0)).xyz;
      gl_Position = projectionMatrix * mv;
    }`;
  const PART_F = `
    precision highp float;
    varying vec3 vN; varying vec3 vV;
    ${CLIP}
    ${LIGHT}
    void main() { clipIt(); vec3 N = normalize(vN); if (!gl_FrontFacing) N = -N; gl_FragColor = vec4(lit(uBase, N, normalize(vV), 0.0, 1.0, 1.0), uAlpha); }`;
  const CAP_V = `
    varying vec3 vW; varying vec3 vV;
    void main() { vec4 mv = modelViewMatrix * vec4(position, 1.0); vW = (modelMatrix * vec4(position, 1.0)).xyz; vV = normalize(-mv.xyz);
      gl_Position = projectionMatrix * mv; }`;
  const CAP_F = `
    precision highp float;
    uniform sampler2D uAtlas; uniform mat4 uWebToVox; uniform vec3 uShape; uniform vec2 uGrid; uniform vec2 uAtlasPx;
    uniform vec3 uCsf; uniform vec3 uGrey; uniform vec3 uWhite; uniform vec3 uTissue; uniform vec3 uN; uniform float uQuality; uniform float uAlpha;
    varying vec3 vW; varying vec3 vV;
    vec2 slice(vec3 v, float k) {                                  // one tile of the atlas, bilinear inside the tile: (T1, soft mask)
      float c = mod(k, uGrid.x), r = floor(k / uGrid.x);
      vec2 ij = clamp(v.xy, vec2(0.5), uShape.xy - 0.5);
      vec2 uv = (vec2(c, r) * uShape.xy + ij) / uAtlasPx;
      vec4 s = texture2D(uAtlas, uv);
      return vec2(s.r, s.a);
    }
    void main() {
      vec3 v = (uWebToVox * vec4(vW, 1.0)).xyz;                     // continuous voxel coordinates (i, j, k)
      if (any(lessThan(v, vec3(0.0))) || any(greaterThan(v, uShape - 1.0))) discard;
      float k0 = floor(v.z), f = v.z - k0; vec2 s;
      if (uQuality > 0.5) s = mix(slice(v, k0), slice(v, min(k0 + 1.0, uShape.z - 1.0)), f); else s = slice(v, floor(v.z + 0.5));
      if (s.y < 0.5) discard;                                      // outside his brain: the soft mask's half-way contour, no voxel steps
      float t = s.x;
      float g = smoothstep(uTissue.x, uTissue.y, t), w = smoothstep(uTissue.y, uTissue.z, t);
      vec3 col = mix(mix(uCsf, uGrey, g), uWhite, w);
      col *= 0.92 + 0.16 * (t - uTissue.y);                       // a little of the scan's own texture
      vec3 N = gl_FrontFacing ? uN : -uN; vec3 L = normalize(vec3(-0.45, 0.55, 0.70));
      float sh = 0.55 + 0.55 * clamp(dot(N, L), 0.0, 1.0);
      gl_FragColor = vec4(pow(pow(col, vec3(2.2)) * sh, vec3(1.0 / 2.2)), uAlpha);
    }`;
  // the fibres as white-matter bundles: the page's own uniforms drive it (the sleep-stage mix, each region's activity,
  // a stimulus travelling along its route), but the look is a tractography figure: cream fibres tinted by direction,
  // normal blending, no additive glow; a pulse brightens the fibre to white where it travels, sleep cools the tint
  const BUNDLE_V = `
    attribute vec3 dcol; attribute vec4 info; attribute vec2 nodes;
    uniform float time; uniform vec3 mixw; uniform float pulseT; uniform sampler2D act; uniform float tgOn[12];
    uniform float burst; uniform float boost; uniform float sci; uniform float uMute;
    varying vec3 vCol; varying float vA; varying vec3 vW;
    float actAt(float i){ return i < 0.0 ? 1.0 : texture2D(act, vec2((i + 0.5) / 256.0, 0.5)).r * 3.0; }
    void main() {
      float tp = info.x, tgt = info.y, raw = info.w;
      float drive = clamp((max(actAt(nodes.x), actAt(nodes.y)) - 1.1) / 0.9, 0.0, 1.0);        // above its own baseline
      vec3 dir = mix(vec3(0.84, 0.80, 0.74), dcol, uMute);                                      // cream, tinted by direction
      vec3 stage = mixw.x * vec3(1.0, 0.97, 0.94) + mixw.y * vec3(0.86, 0.91, 1.0) + mixw.z * vec3(0.96, 0.90, 1.0);
      float slow = mixw.y * 0.25 * pow(0.5 + 0.5 * sin(position.y * 0.045 - time * 1.1), 6.0);  // a slow wave, front to back, in deep sleep
      float rem = mixw.z * 0.15 * burst;
      vec3 col = dir * stage * (0.80 + 0.30 * drive + slow + rem) * (1.0 + 0.25 * boost);
      col = mix(col, dcol * (0.75 + 0.5 * drive), sci);                                          // standard tractography colours
      float route = 0.0;
      for (int i = 0; i < 12; i++) { if (abs(tgt - float(i)) < 0.5) route = tgOn[i]; }
      float pk = route * exp(-pow((tp - pulseT) * 3.5, 2.0)) * step(-0.5, pulseT);
      float trail = route * step(0.0, pulseT) * step(tp, pulseT) * exp(-(pulseT - tp) * 1.5);
      float busy = step(0.0, pulseT) * (1.0 - smoothstep(1.2, 1.6, pulseT));
      col *= 1.0 - 0.35 * busy * (1.0 - route);
      col = mix(col, vec3(1.0, 0.98, 0.95), clamp(0.9 * pk + 0.45 * trail, 0.0, 1.0));            // the fibre itself brightens where the stimulus travels
      vCol = col; vA = (1.0 + 0.8 * pk + 0.4 * trail) * (1.0 - 0.3 * busy * (1.0 - route));
      vW = (modelMatrix * vec4(position, 1.0)).xyz;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }`;
  const BUNDLE_F = `
    precision highp float;
    uniform float uOpacity; uniform float uAlpha; varying vec3 vCol; varying float vA; varying vec3 vW;
    uniform vec4 uClip; uniform float uClipOn;
    void main() { if (uClipOn > 0.5 && dot(vW, uClip.xyz) > uClip.w) discard;
      gl_FragColor = vec4(clamp(vCol, 0.0, 1.0), clamp(uOpacity * vA, 0.0, 1.0) * uAlpha); }`;
  const GHOST_V = `varying vec3 vN; varying vec3 vV;
    void main() { vec4 mv = modelViewMatrix * vec4(position, 1.0); vN = normalize(normalMatrix * normal); vV = normalize(-mv.xyz); gl_Position = projectionMatrix * mv; }`;
  const GHOST_F = `precision highp float; varying vec3 vN; varying vec3 vV; uniform float uAlpha;
    void main() { float f = pow(1.0 - abs(dot(normalize(vN), normalize(vV))), 2.5); gl_FragColor = vec4(vec3(0.75, 0.72, 0.70) * f, f * 0.55 * uAlpha); }`;

  function create(o) {
    const THREE = o.THREE, scene = o.scene, renderer = o.renderer, base = o.base || "/anatomy/";
    const cortex = o.cortex, fibres = o.fibres, caption = o.caption || (() => {});
    const group = new THREE.Group(); group.name = "anatomy"; scene.add(group);
    const st = { view: "glow", layers: { vessels: false, nerves: false }, cut: { on: false, axis: "coronal", t: 0.5 },
                 meshes: false, parts: false, atlas: false, tier: o.tier || "high", fps: 0, loading: 0 };
    let meta = null, metaP = null, parts = null, partsP = null, atlasTex = null, atlasP = null, meshesP = null;
    const origCortexMat = cortex ? cortex.material : null, origFibreMat = fibres ? fibres.material : null;
    const origDpr = renderer && renderer.getPixelRatio ? renderer.getPixelRatio() : 1;
    const v3 = a => new THREE.Vector3(a[0], a[1], a[2]);
    const uClip = { value: new THREE.Vector4(0, 1, 0, 0) }, uClipOn = { value: 0 }, uFlip = { value: 1 }, uAlpha = { value: 1 };
    let winding = 0;                                                              // +1 CCW / -1 CW of the cortex mesh, from its signed volume
    const palU = pal => ({ uSpec: { value: pal.spec }, uShine: { value: pal.shine }, uWrap: { value: pal.wrap }, uScatter: { value: pal.scatter } });
    const bbox = { min: [1e9, 1e9, 1e9], max: [-1e9, -1e9, -1e9] };
    if (cortex && cortex.geometry && cortex.geometry.attributes.position) {
      const p = cortex.geometry.attributes.position.array;
      for (let i = 0; i < p.length; i += 3) for (let k = 0; k < 3; k++) { bbox.min[k] = Math.min(bbox.min[k], p[i + k]); bbox.max[k] = Math.max(bbox.max[k], p[i + k]); }
    }

    // --- materials ---
    const tissueMat = pal => new THREE.ShaderMaterial({
      uniforms: Object.assign({ uCerebrum: { value: v3(pal.cerebrum) }, uCerebellum: { value: v3(pal.cerebellum) }, uBrainstem: { value: v3(pal.brainstem) },
        uWhite: { value: v3(pal.white) }, uHide: { value: 0 }, uVessel: { value: pal.vessel }, uWet: { value: pal.wet }, uClip, uClipOn, uFlip, uAlpha,
        uBase: { value: v3(pal.cerebrum) } }, palU(pal)),
      vertexShader: TISSUE_V, fragmentShader: TISSUE_F, side: THREE.DoubleSide });
    const partMat = (pal, kind) => new THREE.ShaderMaterial({
      uniforms: Object.assign({ uBase: { value: v3(pal[kind]) }, uClip, uClipOn, uFlip, uAlpha }, palU(pal), { uSpec: { value: kind === "artery" ? pal.spec * 1.3 : pal.spec * 0.6 } }),
      vertexShader: PART_V, fragmentShader: PART_F, side: THREE.DoubleSide });
    // the page's fibre uniforms (stage mix, activity texture, the travelling stimulus) are shared by reference, so the
    // page keeps driving them; a page without them (tests) gets quiet defaults
    const fu = (origFibreMat && origFibreMat.uniforms) || {};
    const shared = (k, v) => fu[k] || { value: v };
    const bundleMat = new THREE.ShaderMaterial({ uniforms: { uOpacity: { value: 0.55 }, uMute: { value: 0.45 }, uClip, uClipOn, uAlpha,
        time: shared("time", 0), mixw: shared("mixw", new THREE.Vector3(1, 0, 0)), pulseT: shared("pulseT", -1), act: shared("act", null),
        tgOn: shared("tgOn", new Array(12).fill(0)), burst: shared("burst", 0), boost: shared("boost", 0), sci: shared("sci", 0) },
      vertexShader: BUNDLE_V, fragmentShader: BUNDLE_F, transparent: true, depthWrite: false });
    const ghostMat = new THREE.ShaderMaterial({ uniforms: { uAlpha }, vertexShader: GHOST_V, fragmentShader: GHOST_F, transparent: true, depthWrite: false, side: THREE.FrontSide });
    const mats = { fresh: tissueMat(PALETTE.fresh), fixed: tissueMat(PALETTE.fixed) };
    let capMat = null, cap = null;
    const partMeshes = [], hisMeshes = [];

    // --- the cortex gets its part labels and sulcal depth (his gyri shade themselves) ---
    function prepCortex(partBytes) {
      if (!cortex || !cortex.geometry) return;
      const g = cortex.geometry, pos = g.attributes.position.array, idx = g.index.array;
      if (!g.attributes.normal) g.computeVertexNormals();
      if (!winding) { winding = signedVolume(pos, idx) < 0 ? -1 : 1; uFlip.value = winding; }
      const part = new Float32Array(pos.length / 3), size = componentSizes(part.length, idx);
      for (let i = 0; i < part.length; i++) part[i] = size[i] < part.length * 0.01 ? 0 : (partBytes ? partBytes[i] || 1 : 1);   // crumbs: 0, not drawn
      g.setAttribute("part", new THREE.BufferAttribute(part, 1));
      g.setAttribute("depth", new THREE.BufferAttribute(sulcalDepth(pos, idx, g.attributes.normal.array, 12, winding), 1));
    }
    function addHisMesh(name, pos, idx, part) {
      if (!winding) prepCortex(null);
      if ((signedVolume(pos, idx) < 0 ? -1 : 1) !== winding)                         // the same winding as the cortex: one uFlip for all
        for (let i = 0; i < idx.length; i += 3) { const t = idx[i + 1]; idx[i + 1] = idx[i + 2]; idx[i + 2] = t; }
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      g.setIndex(new THREE.BufferAttribute(idx, 1));
      g.computeVertexNormals();
      g.setAttribute("part", new THREE.BufferAttribute(new Float32Array(pos.length / 3).fill(part), 1));
      g.setAttribute("depth", new THREE.BufferAttribute(sulcalDepth(pos, idx, g.attributes.normal.array, name === "cerebellum" ? 8 : 12, winding), 1));
      const m = new THREE.Mesh(g, mats[st.view === "fixed" ? "fixed" : "fresh"]); m.name = "his_" + name; m.frustumCulled = false;
      group.add(m); hisMeshes.push(m);
      return m;
    }
    function addPart(p) {
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(p.pos, 3));
      g.setIndex(new THREE.BufferAttribute(p.idx, 1));
      g.computeVertexNormals();
      const m = new THREE.Mesh(g, partMat(PALETTE[st.view === "glow" ? "fresh" : st.view], p.kind)); m.name = "atlas_" + p.kind; m.userData = { kind: p.kind, label: p.label };
      m.frustumCulled = false; m.visible = false;
      group.add(m); partMeshes.push(m);
    }

    // --- loading (lazy, each asset once) ---
    const fetchBuf = f => fetch(base + f).then(r => { if (!r.ok) throw new Error(f); return r.arrayBuffer(); });
    function loadMeta() {
      return metaP || (metaP = fetch(base + "anatomy.json").then(r => r.json()).then(m => { meta = m; return m; }));
    }
    function loadMeshes() {
      if (meshesP) return meshesP;
      st.loading++;
      return meshesP = loadMeta().then(() => Promise.all([fetchBuf("cortex_part.bin"), fetchBuf("cerebellum.bin"), fetchBuf("cerebellum_idx.bin"),
                                                           fetchBuf("brainstem.bin"), fetchBuf("brainstem_idx.bin")]))
        .then(([cp, cb, cbi, bs, bsi]) => {
          const idx = (name, b) => meta.meshes[name].idx_type === "uint16" ? new Uint16Array(b) : new Uint32Array(b);
          prepCortex(new Uint8Array(cp));
          addHisMesh("cerebellum", new Float32Array(cb), idx("cerebellum", cbi), PART.cerebellum);
          addHisMesh("brainstem", new Float32Array(bs), idx("brainstem", bsi), PART.brainstem);
          for (const k in mats) mats[k].uniforms.uHide.value = 0;        // the coarse parts stay under the fine meshes: no holes
          st.meshes = true; st.loading--; apply();
        }).catch(e => { st.loading--; prepCortex(null); apply(); console.warn("anatomy meshes", e); });
    }
    function loadParts() {
      if (partsP) return partsP;
      st.loading++;
      return partsP = loadMeta().then(m => fetchBuf(m.parts.file)).then(buf => {
        parts = parseParts(buf, meta.parts); parts.forEach(addPart); st.parts = true; st.loading--; apply();
      }).catch(e => { st.loading--; console.warn("anatomy parts", e); });
    }
    function loadAtlas() {
      if (atlasP) return atlasP;
      st.loading++;
      return atlasP = loadMeta().then(() => new Promise((res, rej) => {
        const img = new Image(); img.onload = () => res(img); img.onerror = rej; img.src = base + "t1_atlas.png";
      })).then(img => {
        atlasTex = new THREE.Texture(img); atlasTex.flipY = false; atlasTex.minFilter = THREE.LinearFilter; atlasTex.magFilter = THREE.LinearFilter;
        atlasTex.generateMipmaps = false; atlasTex.needsUpdate = true;
        const vol = meta.volume, M = new THREE.Matrix4(); M.set(...vol.web_to_vox);
        capMat = new THREE.ShaderMaterial({ uniforms: { uAtlas: { value: atlasTex }, uWebToVox: { value: M }, uShape: { value: v3(vol.shape) },
          uGrid: { value: new THREE.Vector2(vol.cols, vol.rows) }, uAtlasPx: { value: new THREE.Vector2(vol.cols * vol.shape[0], vol.rows * vol.shape[1]) },
          uCsf: { value: v3(PALETTE.fixed.csf) }, uGrey: { value: v3(PALETTE.fixed.grey) }, uWhite: { value: v3(PALETTE.fixed.white) },
          uTissue: { value: v3([vol.tissue.csf, vol.tissue.grey, vol.tissue.white]) }, uN: { value: new THREE.Vector3(0, 1, 0) }, uQuality: { value: st.tier === "low" ? 0 : 1 }, uAlpha },
          vertexShader: CAP_V, fragmentShader: CAP_F, side: THREE.DoubleSide });
        cap = new THREE.Mesh(new THREE.PlaneGeometry(420, 420), capMat); cap.name = "cut_cap"; cap.frustumCulled = false; cap.visible = false;
        group.add(cap); st.atlas = true; st.loading--; apply();
      }).catch(e => { st.loading--; console.warn("anatomy atlas", e); });
    }

    // --- state -> scene ---
    function placeCut() {
      const c = cutPlane(st.cut.axis, st.cut.t, bbox);
      uClip.value.set(c.n[0], c.n[1], c.n[2], c.d);
      uClipOn.value = st.cut.on ? 1 : 0;
      if (cap) {
        cap.visible = st.cut.on && st.view === "fixed";
        const n = v3(c.n), ctr = [0, 1, 2].map(k => (bbox.min[k] + bbox.max[k]) / 2);
        const a = c.n.indexOf(1) >= 0 ? c.n.indexOf(1) : c.n.indexOf(-1);
        ctr[a] = c.value_mm;
        cap.position.set(ctr[0], ctr[1], ctr[2]);
        cap.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), n);
        cap.position.addScaledVector(n, -0.05);                                 // a hair behind the cut: no z-fight with the shell
        capMat.uniforms.uN.value.copy(n).negate();                              // the cap faces the viewer on the kept side
        const pal = PALETTE[st.view === "glow" ? "fixed" : st.view];
        capMat.uniforms.uCsf.value.set(...pal.csf); capMat.uniforms.uGrey.value.set(...pal.grey); capMat.uniforms.uWhite.value.set(...pal.white);
      }
      return c;
    }
    function apply() {
      const real = st.view !== "glow", pal = real ? PALETTE[st.view] : null;
      if (cortex) {
        if (st.view === "fresh" || st.view === "fixed") { if (!cortex.geometry.attributes.part) prepCortex(null); cortex.material = mats[st.view]; }
        else if (st.view === "bundles") cortex.material = ghostMat;
        else cortex.material = origCortexMat;
      }
      if (fibres) fibres.material = real ? bundleMat : origFibreMat;
      bundleMat.visible = st.view === "bundles";                                    // under an opaque specimen the fibres are not drawn at all
      for (const m of hisMeshes) { m.visible = st.view === "fresh" || st.view === "fixed"; m.material = mats[st.view === "fixed" ? "fixed" : "fresh"]; }
      for (const m of partMeshes) {
        const k = m.userData.kind;
        m.visible = ((k === "artery" || k === "vein") && st.layers.vessels) || ((k === "nerve" || k === "gland") && st.layers.nerves) || (k === "cord" && (st.view === "fresh" || st.view === "fixed"));
        const p = PALETTE[real ? st.view : "fresh"];
        m.material.uniforms.uBase.value.set(...p[k]); m.material.uniforms.uSpec.value = k === "artery" ? p.spec * 1.3 : p.spec * 0.6;
        m.material.uniforms.uShine.value = p.shine; m.material.uniforms.uWrap.value = p.wrap; m.material.uniforms.uScatter.value = p.scatter;
      }
      st.cut.on = st.view === "fixed";
      placeCut();
      caption(captionFor(meta, st));
    }

    // --- API ---
    function setView(v) {
      if (!VIEWS.includes(v)) return;
      st.view = v;
      if (v === "fresh" || v === "fixed") loadMeshes();
      if (v === "fixed") loadAtlas();
      if (v !== "glow") loadMeta().then(apply);
      apply();
    }
    function setLayer(name, on) {
      if (!(name in st.layers)) return;
      st.layers[name] = !!on;
      if (on) loadParts();
      apply();
    }
    function setCut(axis, t) {
      if (axis && AXES[axis]) st.cut.axis = axis;
      if (typeof t === "number" && !Number.isNaN(t)) st.cut.t = Math.min(1, Math.max(0, t));
      placeCut();
      caption(captionFor(meta, st));
    }
    // frame-time tier: below LIVE_FPS for 3 s with a realistic view on -> pixel ratio 1.25 and nearest-slice cuts (once; no flapping)
    let lastT = 0, acc = 0, n = 0, lowSince = 0;
    function update(now) {
      const z = typeof root.zoomBrain === "number" ? Math.min(1, Math.max(0, root.zoomBrain)) : 1;   // the page's zoom into a column fades the brain
      if (z !== uAlpha.value) {
        uAlpha.value = z;
        const fading = z < 1;                                                    // opaque materials turn transparent only while fading
        for (const m of [mats.fresh, mats.fixed, capMat].concat(partMeshes.map(p => p.material))) if (m) { m.transparent = fading; m.depthWrite = !fading; }
      }
      if (lastT) { const dt = now - lastT; if (dt < 500) { acc += dt; n++; } }
      lastT = now;
      if (acc >= 1000 && n) {
        st.fps = Math.round(1000 * n / acc); acc = 0; n = 0;
        if (st.view !== "glow" && st.fps < LIVE_FPS) { lowSince = lowSince || now; if (now - lowSince >= 3000 && st.tier !== "low") setTier("low"); }
        else lowSince = 0;
      }
    }
    function setTier(t) {
      st.tier = t;
      if (renderer && renderer.setPixelRatio) renderer.setPixelRatio(t === "low" ? Math.min(origDpr, 1.25) : origDpr);
      if (capMat) capMat.uniforms.uQuality.value = t === "low" ? 0 : 1;
      caption(captionFor(meta, st));
    }
    function state() {
      return { view: st.view, layers: Object.assign({}, st.layers), cut: Object.assign({}, st.cut, cutPlane(st.cut.axis, st.cut.t, bbox)), meshes: st.meshes, parts: st.parts,
               atlas: st.atlas, tier: st.tier, fps: st.fps, loading: st.loading, drawn: group.children.filter(c => c.visible).map(c => c.name),
               bbox, winding, alpha: uAlpha.value, fibresDrawn: !fibres || fibres.material !== bundleMat || bundleMat.visible,
               bundleSharesPageUniforms: !!(fu.time && bundleMat.uniforms.time === fu.time),
               cortexSwapped: !!cortex && cortex.material !== origCortexMat, fibresSwapped: !!fibres && fibres.material !== origFibreMat };
    }
    function dispose() {
      st.view = "glow"; apply(); setTier("high");
      scene.remove(group);
      for (const m of group.children) { m.geometry.dispose(); m.material.dispose(); }
      if (atlasTex) atlasTex.dispose();
    }
    return { setView, setLayer, setCut, setTier, update, state, dispose, meta: () => meta, VIEWS, group };
  }

  root.BrainAnatomy = { create, parseParts, sulcalDepth, signedVolume, componentSizes, cutPlane, tissueColour, captionFor, PALETTE, PART, AXES, VIEWS, LIVE_FPS };
})(typeof window !== "undefined" ? window : globalThis);
