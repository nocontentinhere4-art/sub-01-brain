# Game look: a catalogue for the #98 workers (G2–G8)

Research only (G1, 2026-10-02). Every licence below was read at the linked page on that date; "unverified" means the
page could not be read. Grouped by the stream that would use it. **Top 3** per stream are marked ★. Nothing here is
merged code: it is what the other streams can act on today.

Rules that apply to everything listed (issue #98): shipped assets must be CC0 or explicitly free for commercial
redistribution and go in `web/room/CREDITS.md`; the room page stays ≥ 30 FPS on a mid-range phone; total room assets
≤ 12 MB (today 7.4 MB in `web/room/`); no Mixamo; the character keeps his identity and resembles no real person.

## 0. Where we start (measured on `main`, 2026-10-02)

| thing | today | why it matters |
|---|---|---|
| `boy.glb` | 982 KB, 31,088 triangles, 35,483 vertices, 24 bones, no morph targets | enough triangles for a game character; no fingers, no face rig |
| its material | **one** material, one 2048² WebP (462 KB) used as base colour **and** emissive at factor 1 (Meshy export); `roughnessFactor` 0.41; `KHR_materials_specular` `specularColorFactor` = [2,2,2]; no normal, roughness, metalness or AO map; double-sided | `room.html` zeroes the emissive and forces roughness 0.78 / `envMapIntensity` 0.5, so he is a baked-light albedo with a flat uniform roughness: no skin, eye, hair or cloth response. This is the single biggest lever for G2 |
| room | `room_clean.glb` 4.17 MB, 135k triangles, 42 primitives, 48 WebP textures (1k, floor 2k), AO baked to `room_ao` (UV2, 247 KB) | AO only: no bounced colour, no baked direct/indirect light |
| renderer | r169, `antialias:true`, DPR ≤ 1.5 adaptive, ACESFilmic, `PCFSoftShadowMap`, sun 2048² (manual update), lamp point-light shadow 512², `RoomEnvironment` PMREM, RectAreaLight window, no `EffectComposer` | no AO/SSAO, no bloom, no grade, no contact shadows; `RoomEnvironment` is a studio box, not this room |
| motion | 7 Meshy clips (sit idle, sleep, eat, text, idle, door, walk) + procedural layers in `room.html` (breathing, weight shift, gaze, arm IK by hand) | few clips, no finger motion, no blink |

## 1. Photorealism first: the levers, in order of payoff per millisecond

The owner's steer (2026-10-02): "as real as possible". What reads as "real" at this scale is lighting and material
response, not triangle count. The order below comes from the Digital Foundry breakdowns of the GTA 6 trailers (cited
through [PureXbox](https://www.purexbox.com/news/2023/12/digital-foundry-breaks-down-grand-theft-auto-6-trailer-1),
[PureXbox 2025](https://www.purexbox.com/news/2025/05/gta-6-tech-is-seriously-impressive-but-its-looking-like-a-30fps-game-on-console),
[TweakTown](https://www.tweaktown.com/news/113346/gta-6s-pristine-14gb-gameplay-file-exposes-in-game-image-quality-problems/index.html),
[Push Square](https://www.pushsquare.com/news/2026/06/gta-6-screenshots-unlikely-to-be-running-real-time-on-ps5-tech-experts-warn)),
the Lofi Girl room ([Wikipedia](https://en.wikipedia.org/wiki/Lofi_Girl), [80.lv cozy bedroom](https://80.lv/articles/how-to-create-a-cozy-bedroom-with-rich-details-storytelling-in-blender/)),
the Unrecord developer notes ([Tubers Digest](https://tubersdigest.substack.com/p/devs-explain-why-a-bodycam-fps-looks)) and
interior-render critiques ([SketchUp forum](https://forums.sketchup.com/t/interior-rendering-looks-fake/160568)).

| # | lever | what the references do | on a mid-range phone in WebGL2 | cheapest way for us | stream |
|---|---|---|---|---|---|
| 1 | **Soft bounced light** | DF: GTA 6's RT GI "drives the soft, bounced light … on interiors, skin" | real-time no; **baked yes** | Cycles `DIFFUSE` indirect bake into the existing UV1 (`lightMap`), keep one real-time sun | G6 |
| 2 | **Window ≫ room exposure** | Unrecord's blown highlights; interior critiques: "higher contrast from the window" | yes | window emissive ≫ 1, exposure by hour, AgX/ACES | G6, G7 |
| 3 | **Real material response** | DF: reflections on sunglasses, half-lowered glass; roughness breakup, smudges | yes | load-time room cubemap as `envMap`, roughness maps with fingerprints/dust, bevels + weighted normals | G5, G6 |
| 4 | **Skin that is smooth, not uncanny** | DF: GTA 6 skin is "noticeably smoother" than Matrix Awakens; Fresnel rim on hair | yes (< 1 ms) | pre-integrated skin LUT + sheen + cornea layer, no SSS pass | G2 |
| 5 | **Shadow maps, one real sun** | DF: GTA 6 uses "traditional shadowmapping" | yes | 1024² PCF sun through the window, only the character casts | G6 |
| 6 | **Cloth that hangs** | socks/towels/duvets with weight and folds | yes (build-time) | Blender cloth sim baked to ≤ 2k tris + knit/terry normals | G4 |
| 7 | **Warm key / cool fill, then a grade** | Lofi room: warm lamp vs cool window; 80.lv: "pull the yellow back in post" | yes (1 pass) | lamp PointLight + sky RectAreaLight, one final pass: LUT + vignette + grain + dither | G6 |
| 8 | **A real city in the window** | Lofi: a real Lyon skyline whose sky changes with the hour | yes (~0.1 ms) | 2.5D cut-out city, CC0 Tokyo plates, two-plate day/night fade | G7 |
| 9 | **Consistent light on the character** | DF called out "inconsistent lighting on foreground characters" as the tell | yes | `LightProbe` (9 SH) from the same room cubemap | G6, G2 |
| 10 | **Motion weight, follow-through, blinking** | DF: hair follow-through; nothing frozen | yes | spring bones, blink/saccade/breath rates, foot IK | G3 |
| 11 | **Pristine image: no shimmer** | DF: aliasing fizzle is what gives away "game" | yes | keep MSAA ×4, DPR ≤ 1.5, avoid thin geometry | G6, G8 |
| 12 | **Lens response** | Unrecord: mild barrel, chromatic aberration at edges, grain, handheld sway | yes (same pass as 7) | 1–2 % distortion/CA in the final pass, faint camera sway | G6 |

Not realistic on the phone tier and not worth building: screen-space GI/SSR, screen-space SSS, strand hair, volumetrics,
motion blur, DOF passes, `transmission` glass (see § 6 "never on phones").

## 2. G2: the character asset (face, skin, eyes, hair, clothes, rig)

### 2.1 Fix the mesh and the maps first (build-time, zero runtime cost)

| item | link | licence | cost | how we'd use it |
|---|---|---|---|---|
| ★ **Normals**: Blender 4.2 `shade_smooth_by_angle` + Weighted Normal modifier | [4.1 release notes](https://developer.blender.org/docs/release_notes/4.1/modeling/) | GPL (tool only; output ours) | build-time | clear Meshy's custom split normals, `bpy.ops.object.shade_smooth_by_angle(angle=radians(30))`, then Weighted Normal (Face Area & Angle, Keep Sharp). Fixes the lumpy shading on long thin AI triangles |
| gltf-transform `weld`, `simplify`, `quantize`, `meshopt` | [gltf-transform](https://gltf-transform.dev/) | MIT | build-time | `weld` merges only identical vertices since 2024 (cannot smooth): fix normals in Blender first. `simplify` (meshopt) can re-facet the face: keep ratio ≥ 0.5 there. Normals quantise to 10 bit by default; use 12 if the forehead bands |
| Quadriflow (built in) / Instant Meshes | [QuadriFlow](https://github.com/hjwdzh/QuadriFlow), [Instant Meshes](https://github.com/wjakob/instant-meshes) | BSD-3-Clause (both) | minutes; kills UVs and skinning | only if the face is triangle soup; shrink-wrap to the original and re-bake the albedo to keep identity |
| Quad Remesher (Exoside) | [buy page](https://exoside.com/quadremesher/quadremesher-buy/) | commercial, Pro $109.90 (Indie "NOT usable for commercial purpose") | build-time | not needed if normals are fixed |
| three.js side | r169 | MIT | runtime, free | `flatShading=false`; `mergeVertices` + `computeVertexNormals` only as a last resort; `normalScale` 0.6–0.8 on a noisy AI normal map |
| ★ **Texture super-resolution**: Real-ESRGAN (`realesr-general-x4v3 -dn 0.3`) | [repo + LICENSE](https://github.com/xinntao/Real-ESRGAN/blob/master/LICENSE) | BSD-3-Clause (code and weights in the same repo); output ours | seconds on GPU, ~1 min CPU | upscale the 2048² albedo ×2, re-sample to 2048 for crisp pores and cloth weave |
| Upscayl / chaiNNer | [Upscayl LICENSE](https://github.com/upscayl/upscayl/blob/main/LICENSE), [chaiNNer LICENSE](https://github.com/chaiNNer-org/chaiNNer/blob/main/LICENSE) | AGPL-3.0 / GPL-3.0 (apps; images unrestricted). Upscayl's bundled third-party models: licences unverified | build-time | use only the Real-ESRGAN models to keep provenance clean |
| De-lighting the baked albedo | (no tool needed) | — | build-time | divide the albedo by a blurred copy, re-multiply by the mean skin tone (removes the baked light gradients); then bake a real AO and add it back at 0.3–0.5 via `aoMap`. Agisoft De-Lighter is free but GUI-only, licence unverified |
| Texture formats | [Khronos KTX guide](https://github.com/KhronosGroup/3D-Formats-Guidelines/blob/main/KTXDeveloperGuide.md) | — | 2048² RGBA8 = 16 MB VRAM (+33 % mips) whatever the file format; ETC1S ≈ 2 MB, UASTC ≈ 4 MB | character set: albedo 2048 ETC1S (~0.7 MB), normal 1024 UASTC (~1.3 MB), ORM 1024 ETC1S. Under 3 MB on the wire, under 8 MB VRAM. `KTX2Loader` needs the Basis transcoder from the CDN |

### 2.2 Skin shading in r169 (one `onBeforeCompile` patch on `MeshPhysicalMaterial`)

| item | link | licence | cost | how we'd use it |
|---|---|---|---|---|
| ★ **Pre-integrated skin shading** (Penner 2011) | [slides](https://advances.realtimerendering.com/s2011/Penner%20-%20Pre-Integrated%20Skin%20Rendering%20%28Siggraph%202011%20Advances%20in%20Real-Time%20Rendering%20Course%29.pptx) | public talk; no three.js port exists, write ours | one 256² LUT (64 KB) + curvature term, ~0.1 ms | replace the diffuse term: `texture2D(skinLUT, vec2(NdotL*0.5+0.5, curvature))`, curvature from `fwidth(N)/fwidth(P)` clamped 0.2–0.8 on the face. The cheapest convincing SSS on a phone |
| three.js `SubsurfaceScatteringShader` | [source](https://github.com/mrdoob/three.js/blob/dev/examples/jsm/shaders/SubsurfaceScatteringShader.js) | MIT | ≈ MeshPhong | Phong-based: do not use as is. Port its 5-line translucency term (GDC 2011) into the patch, fed by a baked thickness map (512², ~20 KB) for ears and nostrils |
| `MeshPhysicalMaterial` knobs | [docs](https://threejs.org/docs/#api/en/materials/MeshPhysicalMaterial) | MIT | sheen +5–10 %, clearcoat +10–15 % of fragment cost | skin: roughness map 0.35 lips / 0.4 T-zone / 0.55 cheeks, `specularIntensity` 0.4–0.6 (skin F0 ≈ 0.028; today's `specularColorFactor` [2,2,2] is wrong and must go), `sheen` 0.15–0.3 with warm `sheenColor` #d8b4a0, `sheenRoughness` 0.6 for peach fuzz; clearcoat only on lips and nose tip. **Never `transmission`** on skin |
| Wrap lighting | — | — | 3 lines | fallback if the LUT is late: `NdotL = saturate((dot(N,L)+0.3)/1.3)` with a red tint in the wrapped zone |
| Micro-detail | — | — | one 512² tiled normal, 100–300 KB | tiled ×20–40 and blended in `normal_fragment_maps` (UDN blend); cavity map into specular |
| Screen-space SSS | — | — | 2–4 ms on a phone | skip |

### 2.3 Eyes

| item | link | licence | cost | how we'd use it |
|---|---|---|---|---|
| ★ **Cornea as a second mesh** | r169 `MeshPhysicalMaterial` | MIT | ~200 tris, 2 draw calls | `ior` 1.376, `clearcoat` 1, `roughness` 0.05, `transparent`, `opacity` ≈ 0.1, `envMap` = the room probe. **No `transmission`** (renders the scene again per object) |
| **Iris parallax by view vector** | [zulubo/EyeShader](https://github.com/zulubo/EyeShader) (Unity, README states MIT) | MIT (port the maths, not the Unity code) | ~10 ALU | in `map_fragment`: offset the iris UV by the tangent-space view vector × depth, masked to the iris disc, darken the limbus |
| Eye occlusion wedge + tear line | [CC/iC Blender Tools eye docs](https://soupday.github.io/cc_blender_tools/eyes.html) (GPL add-on: read, do not ship) | — | 4 small draw calls | a dark gradient mesh under the upper lid (`transparent`, `depthWrite` off) + a thin high-clearcoat strip for wetness |
| Catchlights | — | — | free | a small white "window" rectangle in the room probe, or one camera-relative `PointLight`; never painted highlights |
| Whole eye setup | — | — | ≈ 8 draw calls, < 2k tris, < 0.3 ms | — |

### 2.4 Hair

| item | link | licence | cost | how we'd use it |
|---|---|---|---|---|
| Hair cards with `alphaTest` 0.5 + `alphaToCoverage` | r169 | MIT | overdraw is the phone killer: ≤ 300–500 cards, ≤ 6k tris, ≤ 2 layers of coverage | default. `alphaHash` (r154+) only with a TAA pass, which we do not run |
| `anisotropy` (r160+) | [example](https://threejs.org/examples/#webgl_loader_gltf_anisotropy) | MIT | +~10 % on the hair material | 0.6–0.8, rotation along the card's V; gives the Kajiya highlight streak; add a cheap Fresnel rim (DF's hair tell) |
| Mesh (sculpted) hair | — | — | 1 draw call, 2–4k tris | cheapest and fine for a "modern game" look: keep Meshy's hair chunk, anisotropy + tiled strand normal + root darkening |
| Shell/fin fur | — | — | 8–16× overdraw | no |
| ★ **CC0 hair alphas: "Hair Alphas For Days"** (OwlishMedia) | [OpenGameArt](https://opengameart.org/content/hair-alphas-for-days-hair38png) | CC0 (stated on the page); 85 alphas, 2048², 1.1 MB zip | pack 4–8 into a 1024² atlas, 100–200 KB | the only verified-CC0 card alphas found; Gumroad freebies are unverified |
| Card tools in Blender | [GBH Tool](https://superhivemarket.com/products/gbhtool) GPL-2.0+, $15, Blender 4.2; Bystedt "hair cards from curves" (free, licence unverified); Hair Tool (unverified) | — | build-time | GBH makes cards and bakes their textures in 4.2 |

### 2.5 Fingers and blendshapes on the 24-bone rig

| item | link | licence | cost | how we'd use it |
|---|---|---|---|---|
| ★ **Our own bpy script**: +30 finger bones (3 per finger), auto-weights on the hand only | Blender 4.2 | GPL tool; output ours | build-time; skinning cost negligible (three.js uses a bone texture) | `edit_bones` from mesh landmarks (fingertips = farthest verts along the hand axis, k = 5 clusters); `parent_set(type='ARMATURE_AUTO')` on a duplicate restricted to the `hand` vertex group; Data Transfer the finger groups back; normalise. Same rig names elsewhere, so every existing clip keeps working |
| Auto-Rig Pro (Smart) | [FAQ](https://superhivemarket.com/products/auto-rig-pro/faq) | add-on GPL, $50; output ours | build-time | the fastest paid path: 7 markers, fingers detected, glTF "Humanoid" export |
| AccuRig (Reallusion) | [EULA](https://cdn-www.reallusion.com/Content/EULA/AP/EULA_AP.htm), [staff answer](https://discussions.reallusion.com/t/question-about-accurig-2s-eula/15034) | free; EULA § 2.1 allows exporting own characters into "games, applications, web services"; no Reallusion content may be used | GUI only (Win/mac), FBX | valid if someone has a desktop; not scriptable |
| Mixamo auto-rigger | [community FAQ](https://community.adobe.com/t5/mixamo-discussions/mixamo-faq-licensing-royalties-ownership-eula-and-tos/m-p/13234775) | Adobe terms: own character in an app OK, "free distribution of character or animation raw files" not | — | avoid: our GLB is a downloadable file (see § 3) |
| Meshy / Tripo rigging | [Meshy docs](https://docs.meshy.ai/en/api/rigging-and-animation), [Tripo docs](https://developers.tripo3d.com/en/docs/animations-rig.md) | — | credits | neither adds finger bones or a face rig: re-rigging there changes nothing |
| UniRig | [repo](https://github.com/VAST-AI-Research/UniRig), [weights](https://huggingface.co/VAST-AI/UniRig) | MIT (code and weights) | needs a CUDA GPU ≥ 8 GB | possible on a RunPod; hand quality undocumented. The bpy script is more controllable |
| RigNet / Anything World / BlenRig | — | GPL-3 (2020, coarse) / forced on-screen disclosure / GPL-3 (Blender 5 builds) | — | skip |
| ★ **Blendshapes: 8–12 ARKit-named shapes on a split head mesh** | [ARKit names](https://developer.apple.com/documentation/arkit/arfaceanchor/blendshapelocation) | names free to use; three.js morph textures since r133 | 10 shapes × 5k verts ≈ 600 KB raw, ~150 KB meshopt; drop morph normals to halve | eyeBlink L/R, jawOpen, mouthSmile L/R, browInnerUp, mouthFunnel, mouthPucker, eyeWide L/R, cheekPuff. Sculpt by script (proportional edit + `shape_key_add`) |
| Faceit | [listing](https://superhivemarket.com/products/faceit) | add-on GPL, $78; output ours | build-time | the full 52 ARKit shapes automatically, if ever needed |
| KeenTools FaceBuilder | — | needs photos of a real person | — | not applicable (no real likeness) |

### 2.6 Reference assets (study the shading setup only; never ship, never copy a likeness)

| asset | licence | note |
|---|---|---|
| three.js LeePerrySmith head | [CC BY 3.0](https://github.com/mrdoob/three.js/blob/dev/examples/models/gltf/LeePerrySmith/LeePerrySmith_License.txt) | a real person's scan: study its COL/SPEC/normal ranges only |
| three.js Soldier / Xbot | Mixamo terms | study only |
| Khronos glTF Sample Assets | per model ([list](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/main/Models/Models.md)): Fox CC0, CesiumMan CC BY 4.0, BrainStem "Poser EULA" | no realistic skin/eye sample exists; sheen/clearcoat/anisotropy examples |
| Mozilla Hubs avatars | CC BY-SA 4.0 assets, MPL-2.0 code | clean ORM-packed GLB setup |
| VRoid Studio | [guidelines](https://vroid.com/en/studio/guidelines): commercial export allowed | its cheap hair-card and eye setups are instructive |
| Ready Player Me | CC BY-NC-SA 4.0 (reported; site unreachable, unverified) | study only |

**Top 3 for G2:** ★ fix normals and maps offline + KTX2 (§ 2.1); ★ one `onBeforeCompile` skin + eye patch, < 1 ms (§ 2.2, 2.3);
★ fingers and 8–12 blendshapes from our own bpy script (§ 2.5). The scan-based texture route is in § 10.

## 3. G3: motion (clip sources, retargeting, IK, procedural layers)

### 3.1 Clip sources: what we may ship as retargeted GLBs in a public web app

Every clip we ship is a file a visitor can download. That is the test applied below.

| source | link | licence (verified at) | format / content | verdict |
|---|---|---|---|---|
| ★ **CMU Graphics Lab mocap** | [mocap.cs.cmu.edu](http://mocap.cs.cmu.edu/) (server often 503) | "This dataset of motions is free for all uses … You may include this data in commercially-sold products, but you may not resell this data directly, even in converted form." Acknowledgement requested: "The data used in this project was obtained from mocap.cs.cmu.edu. The database was created with funding from NSF EIA-0196217." | 2605 trials: walk, sit down / stand up, idle, "common behaviours"; fingers are placeholders. BVH conversions by cgspeed ([Daz-friendly release](https://www.sites.google.com/a/cgspeed.com/cgspeed/motion-capture/the-daz-friendly-bvh-release-of-cmus-motion-capture-database), 2,548 motions, ~1.5 GB; MotionBuilder-friendly naming is the cleanest for a bone map). The [4TU FBX conversion](https://data.4tu.nl/datasets/0448aab2-3332-449f-a8e2-d208cb58c7df) is CC BY-NC: do not use that one | **USE**: in-app clips are "included in a product"; never offer them as a pack; add the acknowledgement to CREDITS.md |
| ★ **100STYLE** | [Zenodo](https://zenodo.org/record/8127870) | CC BY 4.0 (on Zenodo) | BVH, Xsens, 60 fps, 100 styles of walk / run / **idle** (tired, cheerful, old …); 14.8 GB processed | **USE**: credit Ian Mason / 100STYLE |
| ★ **Meshy animation presets / paid-plan output** (our rig is a Meshy rig) | [Meshy terms](https://www.meshy.ai/terms-of-use) (re-read by G1) | paid plan: "customers on a paid Meshy plan own their Customer Output". Free plan: Meshy owns the output and licenses it CC BY 4.0 "as long as the free plan customer provides appropriate credit to Meshy" | 500+ presets incl. sit, type, phone, sleep on our own skeleton | **USE** (via Higgsfield credits as today). Check which plan the Higgsfield path maps to; if it is the free plan, add "Character animations: Meshy" to CREDITS.md |
| **Quaternius Universal Animation Library** | [pack page](https://quaternius.com/packs/universalanimationlibrary.html), [site licence](https://quaternius.com/license.html) | **Conflict (G1 re-read both pages):** the pack page says "CC0 License"; the site-wide "Quaternius Asset License (QAL) v1.0, last updated 8/28/2026" allows "incorporate the Assets (in original or modified form) into a Product … distribute … that Product … no attribution" but forbids redistribution "as a standalone asset, asset pack, stock file"; § 7: "the version in effect at the time you obtained the Assets governs" | 120+ clips, own humanoid rig, FBX/glTF/blend; sitting, 8-way locomotion | **USE WITH CARE**: in-app use is allowed under both readings. Record it in CREDITS.md as "CC0 per the pack page on <date> (screenshot kept), otherwise QAL v1.0"; never as a pack. **#80 should know this today** |
| Kenney Character Assets | [itch](https://kenney.itch.io/kenney-character-assets) | CC0 | 17 blocky clips (idle, walk, interact …) | USE, low value (cartoon timing) |
| Rokoko "10 free everyday idle animations" | [page](https://www.rokoko.com/resources/rokoko-mocap-10-free-everyday-idle-animations) | "commercial use" stated; redistribution not addressed; Motion Library terms unverified | 10 FBX idles, Mixamo skeleton with fingers | USE WITH CARE: ask Rokoko in writing before shipping |
| Khronos Fox / CesiumMan | [Fox](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/main/Models/Fox/README.md), [CesiumMan](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/main/Models/CesiumMan/README.md) | CC BY 4.0 (Fox rig and animation; model CC0) | pipeline test fixtures only | USE as test data |
| Bandai-Namco Research Motiondataset | [LICENSE](https://raw.githubusercontent.com/BandaiNamcoResearchInc/Bandai-Namco-Research-Motiondataset/master/dataset/Bandai-Namco-Research-Motiondataset-1/LICENSE) | **CC BY-NC 4.0** (not ND, as often reported) | 3,077 BVH clips of daily activities in styles | **DO NOT USE** (non-commercial) |
| Ubisoft LAFAN1 | [license.txt](https://raw.githubusercontent.com/ubisoft/ubisoft-laforge-animation-dataset/master/license.txt) | CC BY-NC-ND 4.0 | — | DO NOT USE |
| AMASS / HumanML3D / Motion-X | [AMASS licence](https://amass.is.tue.mpg.de/license.html) | non-commercial, no redistribution / inherits AMASS / CC BY-NC-SA 4.0 | — | DO NOT USE |
| SFU mocap, KIT Motion-Language | [SFU](https://mocap.cs.sfu.ca/) | SFU: "cannot be used for commercial products"; KIT: no licence stated | — | DO NOT USE |
| Ready Player Me animation library | [LICENSE.md](https://raw.githubusercontent.com/readyplayerme/animation-library/master/LICENSE.md) | RPM avatars only; no redistribution | — | DO NOT USE |
| ActorCore / Reallusion free motions | [EULA](https://actorcore.reallusion.com/static/includes/content/EULA.htm) (updated 2025-08-01) | § 2.1.C: not "as embedded content within applications or online services"; § 2.1.F: may not "make available … distribute" to third parties | — | **DO NOT USE** (a GLB served to browsers is exactly that) |
| **Mixamo** | [Adobe General Terms § 3.6](https://www.adobe.com/legal/terms.html), [Mixamo additional terms](https://wwwimages2.adobe.com/content/dam/cc/en/legal/servicetou/Mixamo-Addl-Terms-en_US-20210623.pdf) | "cannot distribute the Content Files on a stand-alone basis, outside of the End Use"; free access terminable "in its sole discretion" (§ 3.7) | — | **DO NOT USE.** Why: (1) our clips are discrete downloadable `.glb` files, which Adobe's wording leaves open to being "stand-alone"; (2) the only Mixamo-specific document is a one-page addendum, the real licence is the general terms Adobe may change; (3) the June 2025 multi-day outage with support calling it unsupported ([thread](https://community.adobe.com/t5/mixamo-discussions/mixamo-down/m-p/15377556)); (4) an account-bound licence gives no provenance for a public repo |
| VRoid VRMA, Mocap Online, Truebones, MotionBuilder samples | — | no extractable distribution / "binary-only" / no raw-file redistribution / unverified | — | DO NOT USE |
| Hubs avatar pipelines | [README](https://raw.githubusercontent.com/MozillaReality/hubs-avatar-pipelines/master/README.md) | CC BY-SA 4.0 | one idle | not worth the SA obligation |

There is no CC0 BVH of typing, phone-scrolling or sleeping anywhere: those stay Meshy presets or procedural.

### 3.2 Capture or generate our own clips (output ownership)

| tool | link | terms | redistributable? |
|---|---|---|---|
| BlendArMocap (MediaPipe in Blender) | [repo](https://github.com/cgtinker/BlendArMocap) | GPL-3.0+ tool, unmaintained, 4.2 compatibility uncertain | yes, our own capture (rough; good for upper-body typing/phone reference) |
| Rokoko Vision (free 30 s/month) | [pricing](https://www.rokoko.com/pricing) | ownership of recordings not stated anywhere G1 could read | probably, unverified: ask support |
| Cascadeur | [plans](https://cascadeur.com/plans) | Free: non-commercial, `.casc` export only; Indie $8/mo (revenue < $100k) commercial | Indie/Pro yes |
| Plask / DeepMotion / Move One | [Plask ToS](https://plask.ai/docs/100002), [DeepMotion](https://www.deepmotion.com/pricing-animate3d), [Move](https://docs.move.ai/knowledge/move-one-pricing) | free tiers non-commercial | paid tiers yes |

### 3.3 Retargeting

| tool | link | licence | note |
|---|---|---|---|
| three.js `SkeletonUtils.retarget` / `retargetClip` | [r169 source](https://raw.githubusercontent.com/mrdoob/three.js/r169/examples/jsm/utils/SkeletonUtils.js) | MIT | options `names`, `getBoneName`, `hip`, `hipInfluence`, `scale`, `preserveBoneMatrix`, `preserveBonePositions`, `useTargetMatrix`; `retargetClip` adds `fps`, `useFirstFramePosition`, `trim`. Assumes matching rest poses (A vs T pose shows as twisted limbs), no IK, no foot lock. Our `retarget_meshy.mjs` already does this: add a one-time rest-pose alignment (per-bone offset quaternion) |
| Rokoko Studio Live Blender plugin | [repo](https://github.com/Rokoko/rokoko-studio-live-blender) | MIT (README badge) | free retarget panel with auto bone lists |
| Expy Kit | [repo](https://github.com/pKrime/Expy-Kit) | GPL-3.0 | presets for Mixamo/Unreal/Rigify/VRoid/Daz, batch retarget. The "Retarget" fork on extensions.blender.org is Blender 5.0+ only |
| Rig Bridge, Bone Animation Copy Tool | [extensions](https://extensions.blender.org/add-ons/humanoid-remap-studio/), [extensions](https://extensions.blender.org/add-ons/bone-animation-copy-tool/) | GPL-3.0+ | Blender 4.2+, constraint-based |
| BVH Retargeter (Larsson) / KeeMap | [bitbucket](https://bitbucket.org/Diffeomorphic/retarget_bvh/) / [repo](https://github.com/nkeeline/Keemap-Blender-Rig-ReTargeting-Addon) | unverified (historically GPL) / GPL-3.0, tested on 3.3 | with care |
| Auto-Rig Pro Remap | [listing](https://superhivemarket.com/products/auto-rig-pro) | GPL, $50 | best remap with IK and root motion |

### 3.4 IK, look-at, procedural layers, secondary motion (runtime)

| item | link | licence | cost | how we'd use it |
|---|---|---|---|---|
| ★ **`CCDIKSolver`** (r169) | [source](https://raw.githubusercontent.com/mrdoob/three.js/r169/examples/jsm/animation/CCDIKSolver.js) | MIT | 2 legs + 2 arms × 2 links × 5 iterations = 40 CCD steps ≈ tens of µs | feet on the floor, hands on keyboard / phone / bowl; use `rotationMin/Max` per joint (the `limitation` axis is crude). Solve after `mixer.update()`, before render |
| closed-chain-ik (gkjohnson) | [repo](https://github.com/gkjohnson/closed-chain-ik-js) | Apache-2.0 (0.0.3, 2023) | heavier (Jacobian) | only for a true closed loop (two hands on one object) |
| three-ik / fullik | [THREE.IK](https://github.com/jsantell/THREE.IK), [fullik](https://github.com/lo-th/fullik) | MIT / MIT | — | abandoned (2022) / vendor the file if FABRIK is wanted |
| ★ **`@pixiv/three-vrm-springbone`** 3.5.5 | [repo](https://github.com/pixiv/three-vrm/tree/dev/packages/three-vrm-springbone) | MIT, published 2026-07, peer three ≥ 0.137 | O(joints × colliders), negligible | `VRMSpringBoneJoint(bone, child, {stiffness, gravityPower, dragForce 0.4})` works on any three.js bone, no VRM file: hood string, hoodie hem, hair chunk. A hand-rolled 80-line Verlet rope does the headphone cable |
| Look-at weighting | [VRMLookAt.ts](https://raw.githubusercontent.com/pixiv/three-vrm/dev/packages/three-vrm-core/src/lookAt/VRMLookAt.ts) (MIT), [Unity SetLookAtWeight](https://docs.unity3d.com/2022.2/Documentation/ScriptReference/Animator.SetLookAtWeight.html) | — | trivial | split the target angle chest 0.1–0.2 / neck 0.3 / head 0.5–0.6 with clamps (head ±60° yaw ±35° pitch, neck ±25°, chest ±15°); eyes via UV offset until blendshapes exist |
| Additive layers | [AnimationUtils docs](https://threejs.org/docs/#api/en/animation/AnimationUtils) | MIT | free | `makeClipAdditive` + `AdditiveAnimationBlendMode` for breathing, weight shift, gaze; `crossFadeTo` with warp between states; `subclip` to cut idles |
| ★ **Rates from data** | [blink](https://pmc.ncbi.nlm.nih.gov/articles/PMC8646095/table/T5), [saccades](https://pmc.ncbi.nlm.nih.gov/articles/PMC4322726/table/T1), [breathing](https://ouraring.com/blog/breathing-rate-while-sleeping/), [Perlin idle](https://gamedev.net/forums/topic/672158-using-perlin-noise-for-subtle-random-animationmotion/) | — | free | blink 15–20/min (5–10 while reading), 100–150 ms; saccades 2–3/s, ~5°, fixations 200–400 ms; breathing 12–20/min awake, 13–18 asleep (we already drive it from `vitals.resp_per_min`); weight shift every 8–20 s, hips ±2–4 cm; 2–3 octaves of noise at 0.05–0.5 Hz, 0.2–1° on hips/spine/head; fidgets on a Poisson timer |
| Foot IK recipe | [Vulkan tutorial](https://docs.vulkan.org/tutorial/latest/Advanced_glTF/Procedural_Animation_IK/04_foot_placement.html) | — | — | raycast under each ankle, lower the pelvis by the smaller delta, low-pass the targets |
| Motion matching in JS | — | — | — | nothing maintained exists; keep the state machine + crossfades |

**Top 3 for G3:** ★ three.js built-ins only (`makeClipAdditive` layers + `CCDIKSolver`, 2 links, 3–5 iterations);
★ `@pixiv/three-vrm-springbone` on hood/hem/hair + the look-at range-map idea; ★ procedural rates from the data above.
**Top 3 clip sources:** ★ CMU via cgspeed BVH, ★ 100STYLE, ★ Meshy presets on our own rig (then Quaternius with the licence note).

## 4. G4: soft goods (socks, towel, duvet, pillow, curtains, hoodie)

Finding that changes the plan: **there are no CC0 socks, towels, hoodies or duvets on Sketchfab** (20 CC0 queries by G1's
researcher: every CC0 hit is a museum photogrammetry scan at 100k–1.9M faces). Soft goods are made, not downloaded: a
Blender cloth sim baked to a static mesh, dressed with CC0 fabric textures.

### 4.1 Fabric textures (ship as 1k KTX2 / WebP; one 512² tiled detail normal replaces megabytes of unique maps)

| source | link | licence (verified at) | assets that fit | size |
|---|---|---|---|---|
| ★ **Poly Haven textures** | [fabric category](https://polyhaven.com/textures/fabric) | CC0 ([licence](https://polyhaven.com/license): "any purpose, including commercial … redistribute them … no credit required") | `terry_cloth` (towel), `cotton_jersey` / `jersey_melange` / `knitted_fleece` / `polar_fleece` (socks, hoodie), `ribbed_corduroy` (sock cuff, tiled 1:4), `denim_fabric`…`_06`, `waffle_pique_cotton` / `rough_linen` / `stretch_poplin` (duvet, pillowcase, curtain), `wool_boucle` (rug), `brown_leather` / `leather_white` (chair, slippers) | 2k JPG per map 3.6–4.7 MB on download; ship at 1k ≈ 150–400 KB per set |
| ambientCG | [licence](https://docs.ambientcg.com/license/) | CC0 1.0 ("include the raw files in your project, for example a video game"; suggested credit string optional) | `Fabric020`/`021` (towel weave), `Fabric019`/`031`/`032` (wool, duvet), `Fabric080` (plaid cotton), `Fabric083`/`082A`/`036` (sheet, curtain), `Carpet016`, `Leather026`–`039` | 1k JPG zip 7 MB, 2k 22 MB (all maps); no knit or denim there |
| 3DTextures.me, TextureCan, cgbookcase | [3dtextures](https://3dtextures.me/about/), [texturecan](https://www.texturecan.com/terms/), [cgbookcase fabric-04](https://www.cgbookcase.com/textures/fabric-04) | CC0 / "CC0 1.0 Universe" / CC0 (per page; cgbookcase's licence page was 404) | knit, terry, fabric sets 1–4k; cgbookcase normals are DirectX (flip G) | — |
| ShareTextures | [licence](https://sharetextures.com/p/license) | CC0-based, but no redistribution "as part of collections": inside the GLB is fine, raw packs in the repo are not | — | — |
| BlenderKit | [licences](https://www.blendkit.com/docs/licenses/) | filter CC0 only; its "Royalty Free" tier forbids the asset "in the same form" (a downloadable GLB is a grey zone) | — | — |

### 4.2 Making cloth in headless Blender 4.2 (output is ours)

Pattern (bpy, headless-safe): Cloth modifier → `temp_override` + `bpy.ops.ptcache.bake(bake=True)` → `frame_set(settle)` →
`modifier_apply` → Decimate (collapse, triangulate) → Weighted Normal (Keep Sharp) → bake the high-poly sim to a 1024²
normal map on the low-poly, shared by all soft goods. Blender's manual pages for cloth could not be fetched; the
settings below are the 4.x defaults from memory and should be checked in-app.

| prop | approach | key settings | budget / texture |
|---|---|---|---|
| ★ **socks on the pinch hanger** | tube 24×48 segments, top ring in a `pin` vertex group, a small box collider for the clip, gravity, self-collision, settle 60–80 frames. Fallback: modelled tube + heel bend + Shrinkwrap to a hidden foot blob | mass 0.15, bending 0.2, quality 8, self-collision distance 3 mm | ≤ 1.5k tris; `cotton_jersey`/`knitted_fleece` normal + roughness tiled ~4 cm; cuff UV island with `ribbed_corduroy` |
| towel on the bar | plane 40×60 draped over a cylinder collider, no pins, 60 frames; folded towel = rounded stack (bevel 1 cm) with a slight sag | bending 3–8, mass 0.4 | ≤ 1.5k tris; `terry_cloth`, roughness ~0.9 |
| duvet | plane 60×90, pressure on (2–4) + Solidify after apply, dropped on bed + pillow colliders | bending 10–20, mass 0.8 | 3–4k tris; `waffle_pique_cotton` |
| pillow | quad cube, pressure 4–6, 30 frames | bending 2 | ≤ 1k tris; or Poly Haven `throw_pillows_01` (CC0) decimated |
| hoodie on the hook | two panels sewn (Shape → Sewing) on a sphere collider at the neck, or a closed low-poly tube pinned at the hood seam | mass 0.5, bending 1–2 | ≤ 2.5k tris; `polar_fleece` |
| curtains | Wave modifier (height 0.03, width 0.12) applied is enough; sim only for a bottom gather; bake folds to a 512×1024 normal on a 200-tri plane | — | `rough_linen` |

Paid tools (all output yours, none required): Simply Cloth Studio $36 (Blender 4.0–5.2), Cloth Weaver $39+ (3.3–4.0 only),
Garment Tool $54 (4.5+), Marvelous Designer (exports are yours per its EULA summary; legal page returned 403). Free: Rich
Colburn's Modeling Cloth add-on, the built-in Cloth Filter sculpt brush (needs a sculpt context, awkward headless).

Mobile budgets ([Tripo polycount guide](https://www.tripo3d.ai/blog/explore/polycount-budgeting-for-realtime-assets), [Epic Fortnite-ready assets](https://dev.epicgames.com/documentation/fortnite/fortniteready-assets-best-practices-in-fortnite)): soft goods ≤ 1.5–4k tris each, hard props ≤ 1–3k, hero furniture ≤ 5k, whole room ≤ 200k tris and ≤ ~80 draw calls (today: 135k, 42 primitives).

If a CC BY credit is acceptable to the owner, Sketchfab has CC BY socks to use as a base: "Sock hung" by RubaQewar (632 faces, uid `2fdf44f9e3024c8fac2c9c7383bcde79`), "Sock" by Espen Lindahl (576 faces, `b6b61685e34347b5afd69cefe593f942`). Re-check the badge on the page before download.

**Top 3 for G4:** ★ Poly Haven fabric set as 1k KTX2 + one tiled detail normal; ★ the headless cloth pipeline above
(pin groups, pressure, bake, decimate, normal bake into a shared 1024² atlas); ★ `throw_pillows_01` (CC0) as the cushion
and pillow base. See § 10 for scanning the owner's own socks and towel.

## 5. G5: hard surfaces (furniture, desk items)

### 5.1 CC0 model sources (glTF ready; decimate each to ≤ 3k tris, textures to 1k)

| source | link | licence | what fits a Tokyo bedroom | note |
|---|---|---|---|---|
| ★ **Poly Haven models** (521 checked by category) | [models](https://polyhaven.com/models) | CC0 | `classic_laptop`, `gaming_console`, `television_02`, `boombox`, `ceiling_fan`, `wall_clock`, `alarm_clock_01`, `decorative_book_set_01`, `book_encyclopedia_set_01`, `binder_notebook`, `cardboard_box_01`, `plastic_container`, `metal_trash_can`, `wicker_basket_01`, `vintage_suitcase`, `potted_plant_01/02/04`, `hanging_picture_frame_01`, `standing_picture_frame_01`, `steel_frame_shelves_03`, `wooden_display_shelves_01`, `drawer_cabinet`, `side_table_01`, `modern_arm_chair_01`, `folding_wooden_stool`, `old_bed_frame`, `office_notepads`, `stationery_supplies`, `clipboard`, `vintage_electric_kettle`, `vintage_microwave`, `long_life_food`, `wine_bottles_01`, `throw_pillows_01` | blend/FBX/glTF/USD at 1k/2k/4k; 1k package ≈ 2.7 MB, 2k ≈ 7.4 MB. **Not on Poly Haven:** shoes, backpack, towel, duvet, hoodie, socks, mug, speaker, headphones, controller, monitor, keyboard, fridge, rug, curtains, hanger, slippers, futon |
| Kenney Furniture Kit | [kit](https://kenney.nl/assets/furniture-kit), [licence](https://kenney.nl/support) | CC0 | 120 flat-shaded pieces | blockout/collision only; the style fights realism |
| KayKit Furniture Bits | [itch](https://kaylousberg.itch.io/furniture-bits) | CC0 (page) | 50+ stylised pieces, one gradient atlas | blockout only |
| Quaternius furniture packs | [licence](https://quaternius.com/license.html) | QAL v1.0 (not CC0 any more; in-product use allowed, no standalone redistribution) | low-poly | record as QAL if used; low value here |
| OpenGameArt (CC0 filter) | [search](https://opengameart.org/art-search-advanced) | per item | e.g. "Bed" by Colorado Stark (CC0, 8,189 tris, 2048 TGA) | check each page |
| Sketchfab CC0 filter | `https://sketchfab.com/search?type=models&features=downloadable&licenses=7c23a1ba438d4306920229c12afcb5f9&q=…` (API: `license=cc0`, returns `faceCount`, `archives.glb.size`) | per model | zero usable bedroom props at CC0; only museum scans | CC BY (`322a749bcfa841b29dff1e8a1bb74b0b`) has them, with a credit line |
| **Do not ship:** Dimensiva ([licence](https://dimensiva.com/license/): "can not be … distributed, redistributed in original format or other format"), Scan the World (CC BY-SA / BY-NC-SA), ThreeDScans (no licence statement), Poly Pizza / Polycam (unverified), KitBash3D (paid, no redistribution) | | | | |

Japanese-specific CC0 props (futon, zabuton, rice cooker, konbini items): none found anywhere. Model them from primitives
with CC0 fabric/paper textures and author the label decals in-house (as `tex_prep.py` already does for the posters).

### 5.2 What makes hard surfaces read as "game"

| lever | source | how we'd use it |
|---|---|---|
| ★ **1–2 mm bevels on every visible edge + Weighted Normal** | Polycount threads ([1](https://polycount.com/discussion/comment/2629643), [2](https://polycount.com/discussion/comment/2425413)): "most AAA games use bevelling edges at the lowest setting combined with weighted normals" (Alien: Isolation); chamfer + WN "looks identical to baking in many situations" | Bevel modifier (1 segment) on desk, shelf, bed, fridge, monitor, door; bevel only silhouette edges |
| Roughness breakup | ambientCG `Plastic0xx`/`Metal0xx` roughness maps, fingerprint/smudge masks; grime multiplied by the baked AO at floor and wall contacts | monitor bezel, fridge door, desk top, phone glass |
| Decals | authored in-house (sticker on the laptop, label on the bottle, tape, a receipt) | `tex_prep.py` already draws posters and the pinboard |
| Cables | bevelled curves, ~100 tris each | monitor, console, fan, lamp cords to the power strip (the strip exists since #75) |
| Mixed scale clutter | [80.lv living room breakdown](https://80.lv/articles/creating-a-living-room-scene-in-unreal-engine-5-1): character-driven clutter, emissive screens + a rect light, IES-like lamp pools | coins, cables, receipts next to big furniture; slight rotation on every prop |
| Emissive screens | monitor and console LED as emissive + a small RectAreaLight, no bloom pass on phones | already partly there (`screen` material) |

### 5.3 GLB optimisation (gltf-transform, MIT; needs KTX-Software `toktx` for KTX2)

```
gltf-transform optimize in.glb out.glb --compress meshopt --texture-compress auto --texture-size 2048 --simplify true --simplify-error 0.01 --instance true --instance-min 2 --palette true --palette-min 4 --flatten --join --weld --prune
gltf-transform etc1s in.glb out.glb --slots "{baseColorTexture,emissiveTexture}" --quality 128
gltf-transform uastc in.glb out.glb --slots "{normalTexture,occlusionTexture,metallicRoughnessTexture}" --level 2 --rdo --zstd 18
gltf-transform webp  in.glb out.glb --slots "*" --quality 80      # today's path, smallest on the wire, worst in VRAM
```

| 2048² texture | on the wire | GPU memory with mips |
|---|---|---|
| PNG / WebP q80 | 3–8 MB / 0.3–0.8 MB | **22.4 MB** (decoded RGBA8 either way) |
| KTX2 ETC1S q128 | 0.25–0.6 MB | **5.6 MB** |
| KTX2 UASTC + zstd | 2–3.5 MB | **5.6 MB** |

`KTX2Loader` (r169): `setTranscoderPath()` to a CDN copy of `basis_transcoder.{js,wasm}`, `detectSupport(renderer)` picks
ASTC → BPTC → S3TC → ETC2 → ETC1 → PVRTC → RGBA32; any WebGL2 phone gets ASTC or ETC2. Expected effect on the room:
VRAM ~150 MB → ~40 MB, file within ±20 %. `palette` turns the flat plastic/metal materials into one tiny atlas; `join`
cuts draw calls. Detail normals in three.js: blend a tiled 512² map into `normal_fragment_maps` via `onBeforeCompile`
([discourse pattern](https://discourse.threejs.org/t/how-to-blend-normal-texture-and-detailnormal-texture/26922)).

**Top 3 for G5:** ★ the Poly Haven prop set above, decimated; ★ the gltf-transform KTX2 pipeline with `KTX2Loader`;
★ bevels + weighted normals + ambientCG roughness masks, cables and decals.

## 6. G6: rendering (lights, shadows, environment, post, colour, mobile budget)

All three.js items are MIT and load as ES modules from the CDN with the existing importmap unless stated.

### 6.1 Baked lighting and probes

| item | link | licence | cost | how we'd use it |
|---|---|---|---|---|
| ★ **GI lightmap on the existing UV1** | [migration guide](https://github.com/mrdoob/three.js/wiki/Migration-Guide) (r151: `lightMap.channel = 1`; r152: `uv2` → `uv1`) | MIT | one texture fetch per fragment | Cycles `bpy.ops.object.bake(type='DIFFUSE', pass_filter={'INDIRECT'})` (add `'DIRECT'` for the static props' shadows; no `'COLOR'` so the albedo stays live) from a scene with the window area light + sun; denoise off at bake, OIDN after ([bake bugs #97808](https://projects.blender.org/blender/blender/issues/97808)); 16 px margin; 2048² 8-bit PNG → WebP/ETC1S ≈ 1–2 MB. Keep the AO bake as `aoMap` on the same channel; set `flipY=false` |
| HDR lightmap: `RGBMLoader` | [r169 source](https://cdn.jsdelivr.net/npm/three@0.169.0/examples/jsm/loaders/RGBMLoader.js) | MIT | PNG bytes on the wire, half-float in VRAM | only if 8-bit bands; `maxRange` 7. A raw `.hdr` 2k lightmap is ~6 MB (no); half-float KTX2 is 32 MB (no) |
| The Lightmapper (Blender add-on) | [repo](https://github.com/Naxela/The_Lightmapper) (commits Sep 2026) | GPL-3.0 (tool only) | build-time | one-click bake, OIDN, RGBM/RGBD export, xatlas packing |
| xatlas | [repo](https://github.com/jpcy/xatlas) | MIT | build-time | UV1 atlas offline (xatlas-python or the Blender add-on); Blender's Pack Islands is adequate for one room |
| ★ **`LightProbe` + `LightProbeGenerator.fromCubeRenderTarget`** | [example](https://threejs.org/examples/#webgl_lightprobe_cubecamera) | MIT | one 6-face render + readback at load; 9 vec3 uniforms per frame | a `CubeCamera` at chest height at load (and on lamp/time changes, throttled) gives the character room-coloured bounce for free; 2–4 probes along the walking graph, lerp `sh.coefficients` on the CPU. Fixes DF's "inconsistent foreground lighting" tell |
| ★ **Reflection probe: `CubeCamera` once + `PMREMGenerator.fromCubemap`** | [PMREMGenerator docs](https://threejs.org/docs/pages/PMREMGenerator.html) | MIT | 6 renders at 128–256² + prefilter at load; nothing per frame (per-frame is "very poor performance" per [discourse 48043](https://discourse.threejs.org/t/bad-performances-when-animating-a-pmremgenerator-environment/48043)) | replaces `RoomEnvironment`: monitor, floor varnish, window glass and the character's eyes reflect this room. Re-bake only on day/night switch |
| Box-projected cubemap (parallax-corrected) | [discourse 32692](https://discourse.threejs.org/t/parallax-correction-from-environment-maps/32692), [drei `useBoxProjectedEnv`](https://drei.docs.pmnd.rs/misc/use-box-projected-env) | MIT (drei; port ~40 lines of `onBeforeCompile`) | a few ALU, no pass | floor only; moderate maintenance risk across three versions |
| Poly Haven interior HDRIs | [cabin](https://polyhaven.com/a/cabin), `combination_room`, `anniversary_lounge`, `blinds` | CC0 | 1k `.hdr` 1.66 MB, 2k 6.5 MB; as UltraHDR ~150 KB | fallback only: the in-scene cube bake matches this room better than any stock HDRI |
| `UltraHDRLoader` (r165+) | [docs](https://threejs.org/docs/pages/UltraHDRLoader.html), [thread](https://discourse.threejs.org/t/ultrahdr-three/60548) | MIT | JPEG + gain map: 1.5 MB `.hdr` → 122 KB `.jpg` | if any HDRI ships, ship it as UltraHDR (convert at gainmap-creator.monogrid.com). `HDRJPGLoader` and `HDRLoader` do not exist in r169 |

### 6.2 Shadows

| item | link | licence | cost | how we'd use it |
|---|---|---|---|---|
| ★ **Static shadows baked, only the character casts** | lightmap above | MIT | sun map rasterises a few k tris | `castShadow=false` on all static props; `receiveShadow` on floor/walls/bed |
| `PCFSoftShadowMap` vs PCF vs VSM | [shadowmap chunk](https://cdn.jsdelivr.net/npm/three@0.169.0/src/renderers/shaders/ShaderChunk/shadowmap_pars_fragment.glsl.js) | MIT | PCF 17 taps, PCFSoft 9 taps + bilinear, VSM 1 tap but 2 blur passes per map update and light bleeding (an iPhone 12 crash report, [discourse 71094](https://discourse.threejs.org/t/dynamic-shadows-with-vsmshadowmap/71094)) | keep PCFSoft; plain PCF + `radius` if fill-bound |
| Map size | [LightShadow docs](https://threejs.org/docs/pages/LightShadow.html) | — | the scene re-render dominates, not the map size ([discourse 64681](https://discourse.threejs.org/t/how-to-optimize-shadow-rendering-in-three-js-for-better-performance/64681)) | 1024² on phones, frustum tight on the walking area; 2048² desktop. `normalBias` 0.02–0.05, `bias` 0 |
| ★ **Lamp: `PointLight` shadow → `SpotLight`** | same chunk | — | point shadows render 6 viewports into an atlas; a spot renders 1 | one 256–512² spot pointing at the desk, or bake the lamp's shadow into the lightmap and let it cast none |
| Contact shadow under the character | [example](https://threejs.org/examples/#webgl_shadow_contact) | MIT | two 512² RTs, 3 blur passes; cheap at 256², update only when he moves | the soft blob that grounds him on the floor and the bed |
| PCSS | [example](https://threejs.org/examples/#webgl_shadowmap_pcss) | MIT | ~34 taps per fragment | desktop tier: real penumbra on the sun patch |
| CSM | [CSM.js](https://cdn.jsdelivr.net/npm/three@0.169.0/examples/jsm/csm/CSM.js) | MIT | 3 shadow lights | overkill for 4×4 m: skip |

### 6.3 Post-processing

| item | link | licence | cost | how we'd use it | CDN |
|---|---|---|---|---|---|
| ★ **`EffectComposer` with MSAA kept** | [source](https://cdn.jsdelivr.net/npm/three@0.169.0/examples/jsm/postprocessing/EffectComposer.js) | MIT | default RT is `HalfFloatType` with **no `samples`** | pass your own `WebGLRenderTarget(w, h, {type: HalfFloatType, samples: 4})`; call `composer.setPixelRatio()` from the adaptive loop ([discourse 55813](https://discourse.threejs.org/t/postprocessing-adds-a-lot-of-pixelation/55813)). MSAA resolves in tile memory on Mali/Adreno: the cheapest AA by far ([ranking](https://discourse.threejs.org/t/performance-of-different-antialiasing-techniques/56740)) | yes |
| `OutputPass` | [source](https://cdn.jsdelivr.net/npm/three@0.169.0/examples/jsm/postprocessing/OutputPass.js) | MIT | 1 pass | tone mapping (ACES/AgX/Neutral from `renderer.toneMapping`) + sRGB; no dithering; must be before a LUT authored in sRGB (the [3D LUT example](https://threejs.org/examples/#webgl_postprocessing_3dlut) orders RenderPass → OutputPass → LUTPass) | yes |
| ★ **One final grade pass**: `LUTPass` logic + vignette + grain + 1/255 dither in one `ShaderPass` | r169 `LUTPass`, `LUTCubeLoader`, `VignetteShader`, `FilmShader` | MIT | 1 pass, one 3D-texture fetch; a 16³–32³ `.cube` LUT is a few KB | the whole "GTA grade" (filmic curve, slight teal/orange, lifted blacks) for ~1–2 ms on a phone. **LUT sources:** the three.js example's LUTs (RocketStock) are not verifiably redistributable; Q-DDL's 800 free `.cube` LUTs are [CC BY 4.0](https://www.cgchannel.com/2020/01/download-800-free-3d-luts/); no CC0 `.cube` pack found. Safest: author our own LUT (Blender/DaVinci) | yes |
| `SMAAPass` / `FXAAShader` | r169 (`FXAAPass.js` does not exist) | MIT | 1 pass each | fallback only if an MSAA RT fails on a device | yes |
| `GTAOPass` (r160+), `SAOPass`, `SSAOPass` | [GTAOPass](https://cdn.jsdelivr.net/npm/three@0.169.0/examples/jsm/postprocessing/GTAOPass.js) | MIT | GTAO: 4 passes, two full-res half-float RTs, no half-res option | desktop tier only; AO is baked | yes |
| `UnrealBloomPass` | [docs](https://threejs.org/docs/pages/UnrealBloomPass.html) | MIT | 5-level mip chain; 20–40 fps reports on laptop iGPUs ([1](https://discourse.threejs.org/t/unrealbloompass-poor-performance-on-macos-safari-with-intel/42606), [2](https://discourse.threejs.org/t/unreal-bloom-optimize/35476)) | desktop tier at quarter resolution for the lamp/monitor; on phones keep the additive halo sprite | yes |
| `postprocessing` (pmndrs) 6.39.5 | [npm](https://www.npmjs.com/package/postprocessing) | Zlib | merges effects into one über-shader per `EffectPass` | peer `three >= 0.168 < 0.187`: **r169 is supported**; ESM build imports bare `"three"`, so the importmap works (`https://cdn.jsdelivr.net/npm/postprocessing@6.39.5/build/index.js`). Only needed for N8AO or the merged-pass convenience | yes |
| N8AO 2.0.1 | [repo](https://github.com/N8python/n8ao) | **CC0 1.0** (LICENSE file; package.json says ISC, the LICENSE governs) | README: `halfRes` 2–4× faster, upsampling ~1 ms fixed; presets Performance (8/4 samples, "Mobile") … Ultra | desktop tier: `N8AOPostPass`, `halfRes:true`, `setQualityMode("Performance")`. Importmap gotcha: it also imports `three/examples/jsm/postprocessing/Pass.js`, so add a `three/examples/jsm/` entry | yes (unpkg) |
| realism-effects (SSGI/SSR/TRAA) | [repo](https://github.com/0beqz/realism-effects) | MIT | multi-pass full-res with history buffers; last commit Feb 2024 | do not use | — |
| three-good-godrays | [repo](https://github.com/Ameobea/three-good-godrays) | zlib | 60-step raymarch + a depth copy per frame | desktop-only sun shaft; phones keep the additive sun-patch quad | yes |
| `SSRPass`, `BokehPass`, `SSAARenderPass`, `TAARenderPass` | r169 | MIT | 6–7 passes / depth + bokeh / N scene renders | never on phones | yes |

### 6.4 Materials and reflections

| item | note |
|---|---|
| `envMapIntensity` per object | floor 0.6–0.8, monitor 1.0, matte fabric 0.2–0.3; drive by time of day |
| `clearcoat` | floor varnish only (one more env fetch) |
| `anisotropy` | only if brushed metal is in view |
| **`transmission`** | renders the whole scene again into a 1024² target per transmissive object; `transmissionResolutionScale` only arrives in r172; also [fails on some Android devices](https://discourse.threejs.org/t/transmission-of-meshphysicalmaterial-doesnt-work-on-some-android-devices/28836). Window glass = `transparent`, `opacity` ≈ 0.08, `roughness` 0, `envMap` = the room probe |
| planar reflections (`MeshReflectorMaterial`-style) | doubles the scene cost: desktop tier at 256–512² for the floor at most; the box-projected cube is the budget answer |

### 6.5 Colour and tone

| item | note |
|---|---|
| ACES vs **AgX** (r160+) vs **Neutral** (r163+, [Khronos](https://khronos.org/news/press/khronos-pbr-neutral-tone-mapper-released-for-true-to-life-color-rendering-of-3d-products)) | all inline, zero cost. AgX desaturates highlights filmically and avoids ACES's orange skew on the lamp: the better default for a "game" bedroom; Neutral if the art direction wants Blender-matched albedo. With AgX keep exposure in ≈ 0.6–1.4 |
| light units | `useLegacyLights` was removed in r165: r169 is always physical (candela / lux / nits) |
| composer + colour space | everything stays linear half-float until `OutputPass`; sRGB LUTs go after it |
| banding on phones | `EXT_color_buffer_float` is at 99.9 % on Android ([web3dsurvey](https://web3dsurvey.com/webgl2/extensions/EXT_color_buffer_float)): half-float RTs are safe. `OutputPass` has no dither: add `+ (rand(gl_FragCoord.xy) - 0.5) / 255.0` in the final pass; without a composer, `material.dithering = true` on walls and floor works |

### 6.6 Mobile budget (Mali-G57/G68, Snapdragon 6xx/7xx)

No published per-pass millisecond numbers exist for three.js on this class; the estimates are from pixel counts and
Arm's bandwidth guidance ([Arm blog](https://developer.arm.com/community/arm-community-blogs/b/mobile-graphics-and-gaming-blog/posts/deferred-shading-on-mobile)) and must be validated on a real device.

| item | fact | rule |
|---|---|---|
| full-screen passes | at DPR 1.5 on 412×915 CSS ≈ 0.85 Mpx; each half-float pass reads ≥ 7 MB and writes 7 MB | ~1–2 ms per simple pass, 4–8 ms for GTAO's four: **≤ 1 post pass on phones** |
| MSAA ×4 | resolved in tile memory | keep it |
| DPR | iOS: full DPR 40 fps → 60 fps without ([discourse 4963](https://discourse.threejs.org/t/low-fps-on-ios-mobile-with-pixel-ration-set-as-window-devicepixelratio/4963)); "1.1–1.5 is the balance" ([34563](https://discourse.threejs.org/t/changing-pixelratio-based-on-fps-good-or-bad-idea/34563)) | the existing 1.5 cap + adaptive scaler is right; let it fall to 0.75–1.0 first, and make the composer follow |
| shadow map | the re-render dominates | 1024², character only |
| textures | `MAX_TEXTURE_SIZE` ≥ 4096 on 100 % of Android, ≥ 8192 on 77 % ([web3dsurvey](https://web3dsurvey.com/webgl2/parameters/MAX_TEXTURE_SIZE)) | ≤ 2048 everywhere, KTX2 for the big ones |
| GPU timing | `EXT_disjoint_timer_query_webgl2`: **0.2 % of Android, 0.09 % of iOS** ([web3dsurvey](https://web3dsurvey.com/webgl2/extensions/EXT_disjoint_timer_query_webgl2)) | measure only frame time on phones; GPU ms on desktop with `stats-gl` (MIT); real traces via `chrome://inspect` + Perfetto |
| tiers | `detect-gpu` 5.x (MIT) + first-second frame time | choose `postFX`, `aoPass`, `shadowSize` once per session |

**Top 3 for G6:** ★ bake GI into UV1 + `LightProbe` for the character, only the character casts a 1024² sun shadow;
★ a load-time `CubeCamera` reflection probe replacing `RoomEnvironment` (+ box projection on the floor, lamp spot instead
of point shadow); ★ composer with MSAA → `OutputPass` (AgX) → one grade pass; desktop tier adds N8AO (CC0) half-res and
quarter-res bloom.

**Never on phones:** realism-effects, `SSRPass`, `SSAARenderPass`/`TAARenderPass`, `BokehPass`, full-res GTAO/SAO/SSAO,
`transmission`, per-frame planar reflections or PMREM/CubeCamera updates, `VSMShadowMap` with large blur, CSM, point-light
shadows, DPR 2, full-res bloom, godrays.

## 7. G7: the window and the outside

### 7.1 Plates and panoramas we may ship

| item | link | licence (verified at) | size | how we'd use it |
|---|---|---|---|---|
| ★ **Wikimedia Commons CC0 Tokyo plates** (per-file licence read via the API `extmetadata`) | [Minato-ku twilight from Rainbow Bridge (xegxef, Pixabay 2016)](https://commons.wikimedia.org/wiki/File:Illuminated_buildings_at_twilight_in_Minato-ku,_Tokyo,_view_from_Rainbow_Bridge_%282016-12-10_by_xegxef_@Pixabay_2086645%29.jpg) 10000×2500, 10.7 MB; [Roppongi at night from Shibuya Stream (Syced)](https://commons.wikimedia.org/wiki/File:Roppongi_at_night_seen_from_Shibuya_Stream.jpg) 6383×3759; [Shinjuku south exit at night (calvision, Pixabay)](https://commons.wikimedia.org/wiki/File:Shinjuku_Station_South_Entrance_area_at_night_%282015-09-01_by_calvision_@Pixabay_617590%29.jpg) 7346×4896; [Blue illuminated buildings in Tokyo (Syced)](https://commons.wikimedia.org/wiki/File:Blue_illuminated_buildings_in_Tokyo.jpg); [Buildings seen from the platform of Kichijoji Station (Kirin7739)](https://commons.wikimedia.org/wiki/File:Buildings_seen_from_the_platform_of_Kichijoji_Station.jpg) 1920×1080 | CC0 on every row (the Pixabay-sourced ones predate 2019-01-09, when Pixabay was still CC0: [Pixabay terms](https://pixabay.com/service/terms/)) | crop the window slice to ≤ 1024×512 WebP ≈ 100–200 KB per plate | the Rainbow Bridge twilight as the dusk plate, Roppongi/Shinjuku as the night plate; the Kichijoji shot is the only Kichijoji-specific reference (low-res: for painting the cut-out silhouettes). No CC0 360° Tokyo panorama exists on Commons |
| Poly Haven night/urban HDRIs | [shanghai_bund](https://polyhaven.com/a/shanghai_bund) (the only dense Asian neon skyline), `rooftop_night`, `modern_buildings_night`, `golden_bay`, `hansaplatz` (low-rise shops, Kichijoji scale), `sunset_jhbcentral` (best dusk skyline), `shanghai_riverside` (day) | CC0 | 1k `.hdr` 1.6 MB, 2k 6.5 MB, 4k 25 MB; tonemapped JPG 4.8 MB; crop the 90° slice | far-layer glow behind the cut-outs; none is Tokyo |
| ambientCG sky HDRIs | `EveningSkyHDRI046B`, `NightSkyHDRI003` | CC0 | — | pure skies for the sky band |
| Unsplash / Pexels | [Unsplash licence](https://unsplash.com/license), [Pexels licence](https://www.pexels.com/license/) | free commercial use but **not CC0**; a single photo baked into a texture is permitted | — | avoid if CC0 is the bar |
| Flickr | [API licences](https://www.flickr.com/services/api/flickr.photos.licenses.getInfo.html) | `license=9` = CC0 | — | search with that id |

### 7.2 Techniques (three.js, costs on a mid-range phone)

| # | technique | example / library (licence) | cost | how we'd use it |
|---|---|---|---|---|
| ★ 1 | **2.5D cut-out city**: 3–4 alpha-cutout quads at different depths, emissive window mask, moved by parallax per fixed camera | plain three.js | ~0.1 ms, 3–4 draw calls, 300–600 KB | the right answer for a low-rise Kichijoji view: silhouettes painted from the CC0 references, far layer = pre-blurred `shanghai_bund` or the Rainbow Bridge plate (bokeh baked in, no DOF pass) |
| 2 | flat photo plate behind the glass with UV parallax | — | ≈ 0 ms | the minimum; pre-blur the plate |
| 3 | inverse interior mapping (a parallax cubemap behind the glass) | [three-fenestra](https://www.npmjs.com/package/three-fenestra) (MIT, three ≥ 0.150), [three-interior-mapping](https://github.com/mohsenheydari/three-interior-mapping) (MIT) | a few taps per window pixel | true parallax of a street without geometry |
| 4 | instanced emissive boxes (night layer, flickering windows) | `InstancedMesh` | 1 draw call for 300–500 boxes; fragment cost only on window pixels | optional mid layer |
| ★ 5 | **two-plate day/night cross-fade + sky-coupled lights** | tiny `ShaderMaterial` `mix(texA, texB, t)`; [`suncalc`](https://github.com/mourner/suncalc) 2.1.0 | negligible; suncalc is **BSD-2-Clause** (not MIT), v2 is a breaking rewrite | `getPosition(date, 35.703, 139.580)` (Kichijoji, JST) → `DirectionalLight` direction + colour by altitude; sample the same sky gradient on the CPU for the RectAreaLight colour and the hemisphere; the sun patch as a `SpotLight.map` cookie (since r144, [PR #21944](https://github.com/mrdoob/three.js/pull/21944)) of the sash pattern instead of frame shadows |
| ★ 6 | **non-transmissive glass + rain/condensation** | `MeshStandardMaterial` `transparent`, `opacity` ≈ 0.08, `roughness` 0, `envMap` = the room probe; rain drops as procedural UV distortion ([rain-shader write-up](https://github.com/NordicBeaver/rain-shader), licence unverified: reimplement) | ~10 drop evaluations per window pixel | lamp reflections in the glass, weather without a transmission pass ([transmission fails on some Android devices](https://discourse.threejs.org/t/transmission-of-meshphysicalmaterial-doesnt-work-on-some-android-devices/28836)) |
| 7 | trains and cars as additive sprites on a path; two scrolling cloud layers; lightning = 2-frame emissive spike | — | negligible | the Chuo line every few minutes |
| 8 | fake god rays | additive translucent cone from the window (the [Lofi tribute](https://blenderartists.org/t/just-a-lofigirl-tribute-attempt-to-reproduce-an-image-by-juan-pablo-machado-youtube/1625177) did the same) | 1 mesh | only when the sun is low |

**Top 3 for G7:** ★ the 2.5D cut-out city with CC0 Tokyo plates; ★ the two-plate day/night fade with `suncalc`-driven sun and
sky-coupled lights (BSD-2-Clause, not MIT); ★ non-transmissive glass with reflections and a procedural rain layer.

## 8. G8: visual QA (screenshot suite, scorecard, FPS)

| item | link | licence (verified) | how we'd use it |
|---|---|---|---|
| ★ **Playwright `toHaveScreenshot`** | [docs](https://playwright.dev/docs/api/class-pageassertions) | Apache-2.0 | `threshold` (YIQ, default 0.2), `maxDiffPixelRatio`, `mask`, `clip`, `animations: 'disabled'`; baselines are per browser + platform; `comparator: 'ssim-cie94'` exists ([PR #19166](https://github.com/microsoft/playwright/pull/19166)) but is lightly documented |
| `odiff-bin` | [repo](https://github.com/dmtrKovalenko/odiff) | MIT | native, ~5–7× faster than pixelmatch, AA detection, **ignore regions** for the stochastic window area |
| `pixelmatch` / `ssim.js` / `jest-image-snapshot` | [pixelmatch](https://github.com/mapbox/pixelmatch), [ssim.js](https://github.com/obartra/ssim), [jest-image-snapshot](https://github.com/americanexpress/jest-image-snapshot) | ISC / MIT (archived 2023) / Apache-2.0 | baseline diff; SSIM trend per camera; `comparisonMethod: 'ssim'` if Jest |
| LPIPS / DISTS (offline, Python) | [PerceptualSimilarity](https://github.com/richzhang/PerceptualSimilarity), [DISTS](https://github.com/dingkeyan93/DISTS) | BSD-2-Clause / MIT | perceptual distance to the approved "hero" frames |
| **`pyiqa`** (BRISQUE/NIQE/NIMA/MUSIQ) | [repo](https://github.com/chaofengc/IQA-PyTorch) | **PolyForm Noncommercial 1.0.0**: do not use | OpenCV's `quality` module (Apache-2.0) has BRISQUE/NIQE instead |
| ★ **Headless WebGL determinism** | [Chromium SwiftShader doc](https://chromium.googlesource.com/chromium/src/+/main/docs/gpu/swiftshader.md), [Playwright clock](https://playwright.dev/docs/clock) | — | flags `--use-gl=angle --use-angle=swiftshader-webgl --enable-unsafe-swiftshader` (auto-fallback removed in Chrome 135); SwiftShader and GPU output differ: **one backend per baseline set**, named by backend; `--use-angle=gl` without a display silently renders a flat 2D fallback (use xvfb for a real GPU). In the page: `page.clock.setFixedTime()` freezes `Date`, timers and `requestAnimationFrame`; add `?qa=1` → DPR 1, adaptive DPR off, `?seed=` for weather/trains, a `window.__ready` promise after textures + PMREM, N warm-up frames |
| ★ **Game-look scorecard** (no ML) | colourfulness ([Hasler & Süsstrunk](https://pyimagesearch.com/2017/06/05/computing-image-colorfulness-with-opencv-and-python/)), luminance p1–p99 and clipped %, window-ROI / room-ROI luminance ratio, Canny edge density or Laplacian variance, RMS contrast per 32-px tile, warm-key / cool-fill hue split, SSIM vs hero | OpenCV Apache-2.0 | a JSON next to each PNG; flags flat-ambient, washed-out, shimmering and over-yellow frames; thresholds per camera and hour |
| FPS on a real phone | [Chrome remote debugging](https://developer.chrome.com/docs/devtools/remote-debugging), [LoAF](https://developer.chrome.com/docs/web-platform/long-animation-frames) | — | `requestAnimationFrame` deltas (p50/p95) + `renderer.info.render.calls` behind `?perf=1`; `PerformanceObserver({type:'long-animation-frame'})` counts > 50 ms frames; GPU timer queries are unavailable on Android (0.2 %) |

**Top 3 for G8:** ★ Playwright screenshots with `ssim-cie94` or odiff, baselines keyed by backend; ★ the determinism contract
in the page (`?qa=1`, `?seed=`, fixed clock, `__ready`); ★ the cheap scorecard JSON per camera, LPIPS offline.

## 9. Real neuron data for the neuron workers (issue #99)

For the close-up renderer and the forest: EM-reconstructed meshes, skeletons and synapse positions, redistributed as
simplified GLBs. The test is the same as above: derivatives in a public web app, with the required credit visible.

| dataset | species | licence (verified at) | access / auth | formats | sizes | verdict |
|---|---|---|---|---|---|---|
| ★ **H01** (Google + Lichtman lab, human temporal cortex) | human | **CC BY 4.0**: "All released datasets are licensed under a Creative Commons Attribution 4.0 License" ([data page](https://h01-release.storage.googleapis.com/data.html)); cite Shapson-Coe et al., Science 384, eadk4858 (2024) | anonymous GCS: `gs://h01-release/data/20210601/proofread_104/{mesh,skeletons,subcompartments,segment_properties}`, `synapse_locations.csv` (18.9 MB), `skeletons/104_proofread_neurons_swc.zip` (57 MB); full c3 segmentation under `…/c3/`; synapse exports under `…/20210729/c3/synapses/` (~24 GB). No public BigQuery | `neuroglancer_multilod_draco`, sharded, 16-bit quantisation, transform 16×16×33 nm; precomputed skeletons with radius; SWC; CSV | the 104 proofread cells: **1.07 GB of meshes, ~10 MB per cell all LODs**; ~350 KB per skeleton; per-cell tags (layer, type, spine/myelin/AIS counts) in `segment_properties/info`. LOD 2–3 per cell ≈ 0.5–5 MB (estimate by analogy with MICrONS) | **USE**: human, no auth, small proofread set |
| ★ **MICrONS minnie65** (mouse V1, 1 mm³) | mouse | **CC BY 4.0** ([terms](https://www.microns-explorer.org/terms-and-conditions)); [citation policy](https://www.microns-explorer.org/citation-policy): cite The MICrONS Consortium, Nature 640, 435–447 (2025), link www.microns-explorer.org, and "be sure that our Content is never displayed in the absence of such citation" (credit on the same screen as the neuron) | static meshes anonymous: `precomputed://https://storage.googleapis.com/iarpa_microns/minnie/minnie65/seg_m1300/` (its `info` answers anonymously); v661 SWC skeletons on AWS Open Data `s3://bossdb-open-data/iarpa_microns/minnie/minnie65/skeletons/v661/`; tables (`synapses_pni_2`, 337,312,429 rows; `proofreading_status_and_strategy`: 547 fully-extended axons; `coregistration_manual_v4`: 19,181 functionally matched cells) via `caveclient` with a one-time token (Google account, [TOS accept](https://global.daf-apis.com/sticky_auth/api/v1/tos/2/accept)) | multi-LOD draco (4 LODs), SWC/h5, CAVE tables | one cell: LOD 0 5.2 M v / 10.3 M f; LOD 2 254k v / 475k f; **LOD 3 57k v / 100k f** (≈ 0.5–1 MB draco); ~4.6k input + 1.5k output synapses per cell | **USE**: best documented; the visible-credit clause and the token are the only frictions |
| ★ **Janelia MouseLight** | mouse | **CC BY 4.0** on the figshare records (e.g. [AA1628](https://api.figshare.com/v2/articles/27766479), 226 articles in collection 3924067); the project site returned 503 (its own wording unverified) | figshare API / [NeuronBrowser](https://ml-neuronbrowser.janelia.org) | SWC + JSON, ~90 KB per cell | whole-brain long-range axons, no synapses | **USE** for the far view |
| **NeuroMorpho.Org** (in use) | all | CC BY 4.0 ([terms](https://neuromorpho.org/useterm.jsp)); three mandatory citations: the original paper, "NeuroMorpho.Org (RRID:SCR_002145)", Tecuatl, Ljungquist & Ascoli 2024 | [REST API](https://neuromorpho.org/apiReference.html) `/api/neuron/select?q=species:human&fq=cell_type:pyramidal&size=500`; SWC at `https://neuromorpho.org/dableFiles/<archive>/CNG%20version/<name>.CNG.swc` | SWC 50–500 KB | 299,708 cells | USE (check `docs/spiking/morphology_credits.md` carries all three citations) |
| Janelia hemibrain | fly | CC BY 4.0 ([project page](https://www.janelia.org/project-team/flyem/hemibrain)) | `precomputed://gs://neuroglancer-janelia-flyem-hemibrain/v1.2/segmentation` anonymous; neuPrint token for synapses | multi-LOD draco | — | USE only if a fly cell is ever wanted |
| **Allen Cell Types Database** | mouse + human | **non-commercial** ([terms of use](https://alleninstitute.org/terms-of-use/): "must be for research or other noncommercial purposes … may not redistribute the Content or Improvements for commercial purposes without our written permission"); same-page citation required | `allensdk` `CellTypesCache`, no auth | SWC (axons often truncated) | 2,333 cells, 667 reconstructions | **DO NOT USE** (the coin makes the site commercial-adjacent) |
| FlyWire | fly | mixed: ToS says annotations CC BY-NC 4.0, the Zenodo connectivity release CC BY 4.0, mesh licence unverified | token | — | — | avoid |
| EBRAINS human morphologies, CATMAID/VFB, BossDB projects | human / fly / varies | per dataset (often CC BY-NC-SA) / unstated / "CC BY 4.0; CC0 1.0; CC BY-NC-SA 4.0" per project ([registry](https://registry.opendata.aws/bossdb/)) | — | — | — | read each dataset card first |

Tooling (licences verified): `cloud-volume` BSD-3 (sharded multi-LOD reads), `meshparty` Apache-2.0, `navis` GPL-3 and
`skeletor` GPL-3 (build-time only), `trimesh` MIT, `fast-simplification` MIT, `pymeshlab` GPL-3, `open3d` MIT,
`gltf-transform` MIT, neuroglancer Apache-2.0 ([precomputed mesh format](https://github.com/google/neuroglancer/blob/master/src/datasource/precomputed/meshes.md)).

```python
from cloudvolume import CloudVolume
import trimesh, fast_simplification as fs, numpy as np
cv  = CloudVolume("precomputed://gs://h01-release/data/20210601/proofread_104", use_https=True)
sid = 546925828                                   # a Layer-1 pyramidal cell from segment_properties
m   = cv.mesh.get(sid, lod=2)[sid]                # vertices in nm
tm  = trimesh.Trimesh(m.vertices / 1000.0, m.faces, process=True)
v, f = fs.simplify(tm.vertices.astype(np.float32), tm.faces.astype(np.int32), target_count=50_000)
trimesh.Trimesh(v, f).export(f"{sid}_50k.glb")    # then: gltf-transform optimize --compress meshopt  (≈ 0.3–0.6 MB)
sk = cv.skeleton.get(sid)                         # radius per node, for the tube renderer
```

Streaming raw precomputed fragments to three.js is possible (they are plain Draco buffers for `DRACOLoader.parse`,
positions quantised in fragment-local space, 3–4 range requests per cell through the shard index) but not worth it:
convert at build time and ship GLBs.

**Top 3 for #99:** ★ H01 `proofread_104` (human, CC BY 4.0, no auth); ★ MICrONS minnie65 LOD 2–3 meshes + v661 SWC +
synapse table (credit on screen); ★ MouseLight SWCs for the far view, NeuroMorpho kept.

## 10. Photorealism sources: scans, generated props, textures, and what is off limits

### 10.1 Scan the real thing (we own the result; the most "real" route by far)

| tool | link | terms (verified at) | our own scans | others' public scans |
|---|---|---|---|---|
| ★ **RealityScan** (Epic; mobile + desktop) | [EULA](https://www.realityscan.com/en-US/eula) | "does not grant to Licensor any right, title, or interest in any of the content that you produce"; free under $1 M revenue; only the sample datasets are non-commercial | **yes** | — |
| ★ **KIRI Engine** (free: 150 photos, unlimited exports) | [FAQ](https://www.kiriengine.app/faq), user agreement | "The 3D scans created and exported … completely belong to each individual user"; KIRI keeps a broad licence to anything you upload (privacy note, not an IP problem) | **yes** | — |
| Scaniverse (Niantic; LiDAR iPhones) | [terms](https://www.nianticspatial.com/terms) | "you own all right, title and interest … in all Output"; Niantic gets a perpetual licence incl. AI training | yes | unclear |
| Polycam | [usage rights](https://learn.poly.cam/) | public Explore captures are **CC BY 4.0**; your own are yours; free plan exports `.gltf` only, 150 photos | yes | with a credit line |
| Meshroom / COLMAP + OpenMVS | — | MPL-2.0 (site JS-only, unverified) / BSD / AGPL-3.0 (tools only) | yes, headless on Linux | — |

Recipe for the owner (no secrets, nothing personal in frame): socks, towel, hoodie, sneakers, mug, backpack. 80–150 photos,
three orbits at ~20°/45°/70° elevation plus a few top-down, ≤ 15° between shots, the object filling ≥ 50 % of the frame,
overcast window light or a white-sheet softbox, no flash, on a newspaper or textured mat; flip shoes and re-scan the sole.
Export the highest mesh → Blender 4.2 headless: Decimate to 3–5k tris, Smart UV, bake albedo + normal from the high-poly +
a roughness guess at 2048 → 1024 KTX2 ≈ 0.3–0.6 MB per prop; ten props fit the budget. Cloth scans are the one place where
reality beats every generator, and they drape onto the Meshy body with a Data Transfer of weights.

### 10.2 Scanned and photo-sourced models we may ship

| source | link | licence (verified at) | note |
|---|---|---|---|
| ★ Poly Haven (photo-sourced 8k PBR; polycounts on the pages) | [models](https://polyhaven.com/models) | CC0 | `throw_pillows_01` 6.4k, `stationery_supplies` 4.4k, `binder_notebook` 18k, `classic_laptop` 14k, `gamepad` 9.5k, `wall_clock` 3.7k, `alarm_clock_01` 13k, `wicker_basket_02` 18k, `vintage_suitcase` 16k, `rubber_boots` 35k (the only shoe), `wooden_bookshelf_worn` 10k, `metal_office_desk` 6.9k, `painted_wooden_nightstand` 470, `tea_set_01` 40k (mugs), `book_encyclopedia_set_01` 67k, `decorative_book_set_01` 113k (split the row); decimate to ≤ 5k |
| Smithsonian Open Access 3D (CC0-marked items only) | [3d.si.edu](https://3d.si.edu), [FAQ](https://www.si.edu/openaccess/faq) | CC0: "for commercial purposes without any attribution, permission, or fee" | Feedsack Dress (99,999 tris: real garment folds to study/retopo), 1750s chair, costume boots, ski boots |
| Sketchfab "CC0 Public Domain" scans (API label) | e.g. [sports shoes](https://sketchfab.com/3d-models/none-678f96cfadc741a3b260548eeb75954a) 118k, [knobby mug](https://sketchfab.com/3d-models/none-b1367a8e263c41ac8690b20c98315bc3) 98k, [scanned book](https://sketchfab.com/3d-models/none-39a5280efdcd4427ab3bd5209aead8d9) 21k, [clothes peg](https://sketchfab.com/3d-models/none-496a93eaeebb458ba675a3060292b444) 80k, Japanese curios: [netsuke](https://sketchfab.com/3d-models/none-4c379e58642c471fad32406fe90c7cc4) 6.4k, [Musashi Plains screen](https://sketchfab.com/3d-models/none-0dd3488b9a8040ecb3cab9d80e120628) 100k | CC0 (verify the badge on the page at download) | museum pieces; heavy retopo; no sneakers, hoodies, socks or towels at CC0 |
| Scan the World / MyMiniFactory, Three D Scans | — | CC BY-NC-SA ([Lincoln 3D Scans FAQ](https://lincoln3dscans.co.uk/faq)) / no licence text | do not ship |

### 10.3 Generated props (image-to-3D): whose output is it?

| tool | link | terms (verified at) | ship outputs? |
|---|---|---|---|
| ★ **Meshy** (our existing path via Higgsfield) | [terms](https://www.meshy.ai/terms-of-use), [image-to-3D API](https://docs.meshy.ai/en/api/image-to-3d) | paid plan: "customers on a paid Meshy plan own their Customer Output"; free plan: Meshy owns it, licensed CC BY 4.0 with credit to Meshy. `enable_pbr` gives metallic/roughness/normal maps | yes (credit Meshy if the free plan). Check which plan the Higgsfield route maps to for `boy.glb` itself and add the credit if needed |
| Hunyuan3D 2.0 / 2.1 (open weights) | [LICENSE](https://github.com/Tencent-Hunyuan/Hunyuan3D-2) | "Tencent claims no rights in Outputs You generate"; licence territory excludes the EU, UK and South Korea; > 1 million MAU needs a licence | outputs yes; do not self-host from the EU; a hosted API is fine |
| TRELLIS (Microsoft) / InstantMesh | [TRELLIS](https://github.com/microsoft/TRELLIS), [InstantMesh](https://github.com/TencentARC/InstantMesh) | MIT (main code and models) / Apache-2.0 | yes (no PBR) |
| Tripo | [terms](https://www.tripo3d.ai/terms) § 5.2 | free: "Tripo retains all rights … the Inputs and Outputs"; paid: full rights | paid only |
| Rodin / Hyper3D | [terms](https://hyper3d.ai/legal/terms) | Rodin paid: "we will not limit your use of such Output"; ChatAvatar free: personal use only | Rodin paid yes; ChatAvatar no |
| Sloyd | [terms](https://www.sloyd.ai/terms-of-use) | free/Plus: no redistribution; Pro allows it | Pro only; stylised anyway |
| FLUX.1 (the eye's image model on Replicate) | [FLUX repo](https://github.com/black-forest-labs/flux) | schnell Apache-2.0; dev: non-commercial to self-host, but "We claim no ownership rights in and to the Outputs … You may use Output for any purpose (including for commercial purposes)" | generated albedos are ours either way |

### 10.4 Skin, eye and hair textures

| item | link | licence (verified at) | verdict |
|---|---|---|---|
| ★ **CC0 iris photos on Wikimedia Commons** | [A human male brown eye](https://commons.wikimedia.org/wiki/File:A_human_male_brown_eye.jpg) 4080×3060, [GreenEye3](https://commons.wikimedia.org/wiki/File:GreenEye3.jpg) 1920×1149 | CC0 (API) | crop the iris → 1k iris albedo, paint the sclera; an iris is not a likeness |
| ★ **CC0 hair alphas** "Hair Alphas For Days" | [OpenGameArt](https://opengameart.org/content/hair-alphas-for-days-hair38png) | CC0; 85 alphas at 2048² (download size reported both as 1.1 MB and 138 MB by the two readers; expect the larger) | yes |
| Sketchfab "Human materials 1 CC0" | — | the page actually says **CC Attribution** | with a credit only; 2k seamless skin tiles for the body |
| ★ **Make our own PBR from generated albedo** | [DeepBump](https://github.com/HugoTini/DeepBump) GPL-3.0, [Materialize](https://github.com/BoundingBoxSoftware/Materialize) **GPL-3.0 (not MIT)**, [NormalMap-Online](https://github.com/cpetry/NormalMap-Online) MIT | tool licences do not touch the output | FLUX/Higgsfield skin and cloth albedo → de-light (§ 2.1) → DeepBump normal → painted roughness |
| Texturing.xyz, 3D Scan Store | [terms](https://texturing.xyz/pages/terms-of-service), [terms](https://3dscanstore.com/terms-and-conditions-licensing) | paid; no distribution of the textures/scans in an extractable form ("online/offline … viewer") | **no** (a downloadable GLB is a viewer) |
| Digital Emily 2, Unity Digital Human (Enemies/Heretic) | [USC ICT](https://vgl.ict.usc.edu/Data/DigitalEmily2/), Unity Companion License | research only / Unity-only | no |
| **MetaHuman** | UE EULA § 6(e); [CG Channel 2025-06](https://www.cgchannel.com/2025/06/you-can-now-sell-metahumans-or-use-them-in-unity-or-godot/) | since UE 5.6 usable outside Unreal under the UE EULA, but Epic retains the IP and the MetaHuman Creator clause on extractable distribution could not be read | **do not use**: not CC0, not extractable-safe, and a MetaHuman face is not his face anyway |
| **Quixel Megascans / Fab** | [Fab EULA](https://www.fab.com/eula), [legacy Quixel terms](https://quixel.com/terms) | "restrict end users from extracting or otherwise using Content outside of the Project"; legacy: distribute "in object code format only as an inseparable part of a Project" | **no**: a web page serving `.glb`/`.ktx2` is extraction by definition |

### 10.5 Photoreal three.js interiors to learn from (technique transfers to plain r169; copy code only where licensed)

| link | what they did | note |
|---|---|---|
| [discourse 89753: realistic ambience in architectural scenes](https://discourse.threejs.org/t/achieving-realistic-ambience-in-architectural-scenes/89753) | consensus: bake everything, display with lightmaps and no real-time shadows; GTAO/progressive shadows as the non-baked alternative | matches § 6 |
| [techinz/blender-batch-lightmap-baker](https://github.com/techinz/blender-batch-lightmap-baker) (MIT) + [discourse 82346](https://discourse.threejs.org/t/made-a-blender-script-for-batch-baking-lightmaps-to-optimize-models-for-threejs/82346) | a Blender script that batch-bakes Combined/Diffuse lightmaps with auto UVs; "crazy bigger fps on mobile" | our Blender 4.2 headless path, code reusable |
| [discourse 16351: Whitewood interior](https://discourse.threejs.org/t/whitewood-realistic-interior/16351) | baked shadows + real-time floor reflections; lesson: bake AO too, corners went weak | — |
| three.js `ProgressiveLightMap` (`examples/jsm/misc/ProgressiveLightMap.js`, r169, MIT) + `webgl_shadowmap_progressive` | accumulates soft shadows into a lightmap at runtime | an alternative to the Blender bake for the character's own static poses; WebGLRenderer only |
| Bruno Simon's "my room in 3D" | Blender-baked single-texture room | repo has **no licence file**: technique only |
| Needle Engine lightmapping docs | auto lightmap UVs, 1024–4096, denoise, embeds the lightmap in the GLB | Hobby tier is non-commercial with branding: replicate the pipeline, do not use the product |

## 11. One-page licence verdicts

| USE (verified) | USE WITH CARE | DO NOT USE |
|---|---|---|
| Poly Haven (CC0), ambientCG (CC0), Kenney (CC0), KayKit (CC0), 3DTextures.me / TextureCan / cgbookcase (CC0), Smithsonian CC0 items, Sketchfab items labelled CC0, Wikimedia Commons CC0 files, "Hair Alphas For Days" (CC0), CMU mocap (free for all uses, acknowledgement), 100STYLE (CC BY 4.0), Meshy outputs (paid: ours; free: CC BY 4.0 + credit), TRELLIS (MIT), InstantMesh (Apache-2.0), Hunyuan3D outputs, FLUX outputs, our own scans (RealityScan / KIRI / Scaniverse), H01 (CC BY 4.0), MICrONS (CC BY 4.0, credit on screen), MouseLight (CC BY 4.0), NeuroMorpho (CC BY 4.0, three citations), hemibrain (CC BY 4.0); code: three.js (MIT), `postprocessing` (Zlib), N8AO (CC0), three-vrm (MIT), closed-chain-ik (Apache-2.0), gltf-transform (MIT), suncalc (BSD-2), odiff (MIT), pixelmatch (ISC), LPIPS (BSD-2), cloud-volume (BSD-3), trimesh (MIT) | Quaternius (pack page CC0 vs site QAL v1.0: in-product use OK under both, never as a pack, keep a dated screenshot), Rokoko free idles (commercial use stated, redistribution silent: ask), Sketchfab CC BY items (credit line), Polycam public captures (CC BY 4.0), ShareTextures (inside the GLB only), BlenderKit CC0 tier only, GPL build tools (Blender add-ons, navis, Materialize, DeepBump: output is ours, never ship the tool), Q-DDL LUTs (CC BY 4.0), BVH Retargeter / Three D Scans / Meshroom (licence text not readable today) | Mixamo (stand-alone distribution clause, terminable terms), ActorCore/Reallusion content (no embedding in online services), Bandai-Namco (CC BY-NC), LAFAN1 (BY-NC-ND), AMASS / HumanML3D / Motion-X / SFU / KIT, Ready Player Me library, VRoid VRMA, Mocap Online, Truebones, Quixel Megascans / Fab (no extraction), Texturing.xyz, 3D Scan Store, MetaHuman, Unity Digital Human, Digital Emily, Dimensiva, Scan the World (NC-SA), BlenderKit "Royalty Free", Tripo free, ChatAvatar, Sloyd free, Allen Cell Types (non-commercial), FlyWire (NC ambiguity), `pyiqa` (PolyForm Noncommercial), 4TU's CMU FBX conversion (CC BY-NC), Anything World (forced disclosure), realism-effects on phones (technical, not legal) |

Two facts other streams should act on today: **Quaternius is no longer CC0 site-wide** (QAL v1.0, 2026-08-28; the
Universal Animation Library page still says CC0), and **a Meshy free-plan output is owned by Meshy and licensed CC BY 4.0**,
so CREDITS.md may need a "Meshy" line for `boy.glb` and its clips depending on the plan behind the Higgsfield route.

## 12. Method and gaps

Seven research passes on 2026-10-02 (web search + fetching every licence page named above). Pages that could not be
read and are therefore marked unverified: the Blender manual's cloth pages (defaults quoted from memory), mocap.cs.cmu.edu
(503 at the time; the wording is from the researcher's earlier fetch of the same page), Rokoko's Motion Library terms,
Three D Scans, Meshroom's site, the MetaHuman Creator EULA, mouselight.janelia.org, Ready Player Me. No published
per-pass millisecond numbers exist for three.js on Mali-G57/G68: every phone estimate here is derived from pixel counts and
must be measured by G8 on a real device.
