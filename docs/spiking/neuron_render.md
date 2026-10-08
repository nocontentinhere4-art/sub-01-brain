# Neurons at microscopy scale: the close-up renderer (#88 A)

> Shapes are real reconstructed neurons (public databases); thickness, spines and myelin are drawn from published
> typical values. The simulated network uses point neurons (no dendrites are simulated); cells are enlarged and pulses
> slowed to be visible. A model, not a mind.

`web/neuron_render/neuron_render.js` replaces the thin-line close-ups of #78 on `/brain` (zoom in with the neurons
layer on, or a close-up button). API for the whole-brain view (part B): `docs/spiking/neuron_render_api.md`.
Screenshots and numbers: `python tests/neuron_render_shots.py` → `docs/screens/neuron_render/`.

## #99: real H01 cells in the cortex close-up

Since #99 the cortex close-up no longer draws procedural tubes: it draws **real electron-microscopy reconstructions**
from **H01** (Shapson-Coe et al. 2024, Science 384:eadk4858; ~1 mm³ of human temporal cortex; CC BY 4.0), built once
by `web/neuron_render/build/fetch_h01.py` into `web/neuron_render/h01/` and lazy-loaded by `neuron_render.js` through
`h01.js` (gzip blobs decoded with `DecompressionStream`; browsers without it, or a failed fetch, fall back to the
NeuroMorpho procedural cells below, and `info().source` says which). The other regions (striatum, thalamus,
hippocampus, amygdala) keep the procedural NeuroMorpho cells: H01 is cortex only, and MICrONS (mouse) was not needed.

| part | H01 close-up |
|---|---|
| shapes, spines, boutons | the proofread cells' own meshes (multi-LOD Draco from `proofread_104/mesh`, decimated with quadric simplification to the tier's triangle target; the thin axon is decimated on its own share of the budget (`decimate_split`, ≤ 30 %) so it stays a continuous tube instead of collapsing first: the spines are in the mesh, not drawn) |
| axon / dendrite / soma / AIS / **myelin** | H01's subcompartment classes on the cells' SWC skeletons (sparse labels, propagated along the tree); the pulse runs on the nodes H01 labels axon / AIS, saltatory on the stretches it labels **myelinated axon** (an internode every ~100 µm inside a stretch, Rushton 1951: the labels say where myelin is, not where each node of Ranvier is) |
| synapses | `synapse_locations.csv`: the cell's **presynaptic sites** (its boutons; they flash when the pulse arrives, timed along the real axon) and its **incoming synapses** (dots; the mid tier keeps a sample of 1 500) |
| glia | astrocytes and oligodendrocytes from the automated c3 segmentation, chosen from the soma table, **not proofread** (said in the caption and the credits) |
| tissue behind | a crop of the real SEM image through the focus cell's soma (64 nm mip, stored at 128 nm per pixel), drawn at the back of the slab in the EM look |
| positions | the focus cell at its true place; every other cell keeps its orientation, cortical depth (y) and slab depth (z) and is moved sideways into the field (`shift_um` in the manifest): the 104 proofread cells lie over ~12 mm² |
| scale | a real **scale bar** (µm) in the HUD, from the camera distance at the focus depth |
| looks | **EM**: grey membrane-like shading, the SEM slice behind, no bloom; **fluorescence**: as before (sparse-label colours, a second fluorophore on interneurons, glia in a blue-white), depth of field, bloom |
| budget | ≤ 3 MB per set (desktop and phone sets; sizes in `cortex.json`), phone set ≤ 250k triangles, desktop ≤ 1M; nothing loaded until the close-up opens |

Sources and changes to the data: `docs/spiking/morphology_credits.md` (H01 section) and the build script's header.
Honesty: the caption (`NeuronRender.CAPTION`) names the datasets and says the activity is simulated; `nr.caption()`
adds the counts of this close-up (cells, synapses, myelinated µm) and that the glia are not proofread.

## What is real, what is typical, what is drawn (the procedural cells: every region but cortex)

| part | where it comes from |
|---|---|
| the shape of every cell (branching, lengths, soma size) | six real reconstructions from NeuroMorpho.Org (CC BY 4.0), the same cells as #78, credited in `docs/spiking/morphology_credits.md` and on `/about`; `analysis/build_neuron_render.py` keeps them as branched polylines with their SWC radii in `web/neuron_render/cells.json` (≤ 1 500 nodes a cell; the axon cut to its local arbor, 400–900 µm of path from the soma) |
| the thickness of dendrites and axons | the reconstruction's own radii for five cells (`radii: "measured"`); the CA1 cell cd2351 (1995) has one constant radius in its file, so its taper is drawn from typical values (`radii: "typical"`): apical trunk ~3 µm proximally tapering to ~1 µm, oblique and basal dendrites 0.5–1 µm (Megías et al. 2001). Every process has a minimum on-screen width of ~1 px (the point-spread function of a microscope does the same to thin processes) |
| soma, nucleus | the soma radius from the file; the soma is deformed with hillocks toward each primary process and a cone toward the apical dendrite; the nucleus is drawn at 60 % of the soma radius with a nucleolus, translucent — illustrative |
| **spines** | procedural, at a published density per µm of dendrite beyond a spine-free proximal zone, on the cells in full detail (the "hero" tier), nearest the soma first within a triangle budget; the caption says on how many µm of dendrite they are drawn |
| **myelin, nodes of Ranvier** | procedural, on the types whose axons are myelinated: internodes start after the axon initial segment, on the axon's main trunk and its first branch orders; sheath outer radius = axon radius / g-ratio; node gaps drawn 2 µm wide (real ~1 µm) so they stay visible |
| **boutons** | procedural: en passant boutons every few µm on the unmyelinated axon beyond the initial segment, a terminal bouton at every axon tip |
| the tissue around | the far tier of cells as thin lines, and oriented sprites of out-of-focus neurite streaks (no counterstain blobs since #99: they read as meaningless dots): decoration, not data |
| activity | only recorded spikes of sampled model neurons and measured region rates (`n3.sq`, `n3.rq`); no frames → nothing moves |

None of the cells is from the person whose MRI the brain model is built from (not from the scanned person): no data of that person exist at this
scale. The simulated network uses point neurons: the dendrites, spines, myelin and boutons drawn here are not simulated.

## The published values used (`TYPES` in `neuron_render.js`)

| type | spines/µm (beyond … µm) | axon initial segment (µm) | internode (µm) | boutons every (µm) | unmyelinated speed (m/s) |
|---|---|---|---|---|---|
| pyramidal (human L2/3) | 1.3 (30) | 48 | 50 | 4.5 | 0.3 |
| basket (human L2/3, PV-like) | 0.05 (20) | 25 | 27 | 4 | 0.4 |
| medium spiny (rat accumbens) | 1.5 (30) | — (unmyelinated local axon) | — | 6 | 0.3 |
| relay (rat VPM) | 0.1 (30) | 30 | 100 | 6 | 0.3 |
| CA1 pyramidal (rat) | 2.5 (40) | 35 | 80 | 6 | 0.3 |
| amygdala principal (mouse BLA) | 1.2 (30) | 35 | 80 | 6 | 0.3 |

Common: g-ratio 0.7; myelinated conduction speed 6 m/s per µm of outer fibre diameter; node of Ranvier ~1 µm (drawn 2 µm).

Sources:
- **Spines, human pyramidal cells:** Benavides-Piccione R, Ballesteros-Yáñez I, DeFelipe J, Yuste R (2002) Cortical area and
  species differences in dendritic spine morphology. J Neurocytol 31:337–346 (human spines denser, larger and longer than
  mouse); Benavides-Piccione R, Fernaud-Espinosa I, Robles V, Yuste R, DeFelipe J (2013) Age-based comparison of human
  dendritic spine structure using complete three-dimensional reconstructions. Cereb Cortex 23:1798–1810
  (doi:10.1093/cercor/bhs154; layer III, ~1–1.5 spines/µm along the dendrite, lower in the proximal segment). 1.3/µm is a
  round value inside that range.
- **Spines, CA1:** Megías M, Emri Z, Freund TF, Gulyás AI (2001) Total number and distribution of inhibitory and excitatory
  synapses on hippocampal CA1 pyramidal cells. Neuroscience 102:527–540 (2.9 spines/µm on thin stratum radiatum
  dendrites, fewer on the proximal trunk; dendrite diameters as above). 2.5/µm is a mean over the tree.
- **Spines, medium spiny neurons:** Wilson CJ, Groves PM, Kitai ST, Linder JC (1983) Three-dimensional structure of
  dendritic spines in the rat neostriatum. J Neurosci 3:383–398 (spiny beyond the proximal ~30 µm; classic counts
  ~1–2/µm, three-dimensional counts in the accumbens reach ~2.7/µm). 1.5/µm.
- **Spines, basolateral amygdala principal cells:** spiny pyramidal-like cells; densities reported around 1–2/µm in Golgi
  and filled material (e.g. the Golgi–Cox vs Neurobiotin comparison, Front Neuroanat 2017, PMC5742768). 1.2/µm.
- **Basket and relay cells** are sparsely spiny (fast-spiking PV cells and thalamocortical relay cells carry few spines):
  0.05 and 0.1/µm, nominal.
- **Myelin on cortical pyramidal axons:** Tomassy GS et al. (2014) Distinct profiles of myelin distribution along single
  axons of pyramidal neurons in the neocortex. Science 344:319–324 (the premyelin axon segment of layer III–IV cells
  48.4 ± 3.5 µm; intermittent myelin with unmyelinated stretches up to 55 µm in L2/3). Internode 50 µm, AIS 48 µm.
- **Myelin on basket (PV) cells:** Stedehouder J et al. (2017) Fast-spiking parvalbumin interneurons are frequently
  myelinated in the cerebral cortex of mice and humans. Cereb Cortex 27:5001–5013 (proximal axon, short internodes
  ~27 µm interspersed with branch points). Internode 27 µm, AIS 25 µm.
- **Internode length and g-ratio:** Rushton WAH (1951) A theory of the effects of fibre size in medullated nerve.
  J Physiol 115:101–122 (internode ≈ 100 × fibre diameter: 100 µm for ~1 µm thalamocortical fibres); Chomiak T, Hu B
  (2009) What is the optimal value of the g-ratio for myelinated fibers in the rat CNS? A theoretical approach. PLoS ONE
  4:e7754 (CNS g-ratio ~0.7–0.77). g = 0.7.
- **Boutons:** Hellwig B, Schüz A, Aertsen A (1994) Synapses on axon collaterals of pyramidal cells are spaced at random
  intervals: a Golgi study in the mouse cerebral cortex. Biol Cybern 71:1–12 (mean interval 4.5 µm, Poisson spacing).
- **Conduction speed:** myelinated fibres ≈ 6 m/s per µm of outer diameter (Hursh JB (1939) Conduction velocity and
  diameter of nerve fibers. Am J Physiol 127:131–139); thin unmyelinated cortical axons 0.3–0.5 m/s (Swadlow HA (1994)
  Efferent neurons and suspected interneurons in motor cortex of the awake rabbit: axonal properties, sensory receptive
  fields, and subthreshold synaptic inputs. J Neurophysiol 71:437–453, and the local-axon measurements in PV cells).
- **Reference look:** a GFP-expressing pyramidal neuron with a red counterstain (Lee WCA, Huang H, Feng G, Sanes JR,
  Brown EN, So PT, Nedivi E (2006) Dynamic remodeling of dendritic arbors in GABAergic interneurons of adult visual
  cortex. PLoS Biol 4(2):e29, figure 6f; Wikimedia Commons `PLoSBiol4.e126.Fig6fNeuron.jpg`, CC BY 2.5). Used only for
  the side-by-side in `docs/screens/neuron_render/side_by_side.png`; nothing of it is in the renderer.

## Activity, honest
- `nr.onFrame(msg)` gets every spiking frame; the module keeps this region's sampled spikes (frame slot 0–255 → a drawn
  cell, uniformly) and its rate byte. A spike flashes the soma and sends an **action potential** down the axon: the
  arrival time of every axon vertex is precomputed (`plan()`): along the initial segment and unmyelinated collaterals
  at the unmyelinated speed; along a myelinated internode the whole internode lights at the moment the pulse reaches
  the node before it, and the next node after the internode's conduction time (saltatory). **Boutons** glow when the
  pulse arrives. **Dendrites** glow with the region's measured rate; the soma flash leaks ~40 µm into the proximal
  dendrites. Speeds are the real ones divided by `SLOWDOWN` = 10000: ~0.6 mm/s on screen in a myelinated trunk (a ~50 µm
  internode every ~80 ms), ~30 µm/s in thin collaterals (a 300 µm collateral takes ~10 s; the pulse fades along the way).
- No frames for 10 s (or `setLive(false)`) → nothing moves; the caption says "no live network: static cells, no
  activity". There is no demo mode and no recorded stream on the server.
- A real action potential is ~1 ms long: at 0.3 m/s that is ~300 µm of axon, longer than most of these arbors. It is
  drawn as a short bright front (~90 ms at the slowed clock): a visual convention, said in the caption's "pulses slowed".
- On the H01 cells (#99) the axon is its real ~0.5 µm (a pixel) and the focus cell's 4.1 mm of axon take ~34 s at the
  slowed clock, so the **axon tube itself lights** from the front back toward the soma (~45 µm, fading), swells by
  ~0.6 µm where lit, and the cell's **axon skeleton** (H01's own nodes, ~2 000 for the focus and hero cells, drawn as
  a thin 3-sided tube along the decimated mesh's axon, never thinner than a pixel, so the axon stays continuous) lights
  node to node with it. H01's SWC skeletons come in fragments (the focus cell's axon in ~20, the first starting ~28 µm
  from the soma, unlabelled pieces in between): the build adopts an unlabelled piece into the axon when it touches
  axon-labelled nodes (`adopt_axon_fragments`), roots the soma's fragment at the soma, and links each axon piece's
  root to the nearest soma or axon node of another piece within 32 µm, taken from the soma outward
  (`bridge_axon_fragments`, `BRIDGE_UM`), so path distance and pulse time run continuously from the soma along the
  whole axon (the focus cell keeps 4 unlinked pieces). The links are straight chords, not H01 geometry; the front is ~3× wider (~9 µm) and the pulse fades over 20 s instead of 8 (`uPulseW`, `uPulseTail`,
  `uPulseFade`, `uPulseSwell`, set in `buildH01`): the same visual convention, so a viewer can follow the pulse along
  the real axon. Nothing separate travels along it (no sprites, no dots). The timing is the real conduction speed /
  10 000 along the real path (`ap_front_um` in `results.json`: the front's path distance from the soma at each strip
  frame).

## Look
- **Fluorescence:** GFP-like green (a few cells tdTomato-like orange: the basket cells in cortex, ~15 % of the mid tier
  elsewhere) on black; intensity grows with the thickness traversed (thick processes and somata brightest), a faint
  bluish myelin channel; bloom. **3D render:** soft wrap lighting, a reddish translucent edge, pale cream myelin, a
  lavender nucleus; dim cooler tissue around. Toggle in the HUD (top right of the brain) or `nr.setStyle()`. In cortex the
  render style draws 3 hero cells and half the mid tier (five full arbors overlapped into a ball of yarn); `info().triangles`
  follows. The bottom-centre overlay (with the µm scale bar above it) shows cells, triangles and live/offline; fps only with `?debug` in the page's URL (or
  `debug: true`). While a close-up is open the page's right-hand panel gets a dark translucent scrim (`body.closeup #dock`).
- **Depth of field:** every material writes linear depth into the alpha channel of the scene target; the composite
  mixes the sharp image with a quarter-resolution blur by the distance from the focus cell's depth (sharp within ±8 %
  of 2.5 × the camera distance). **Bloom:** bright pass of the quarter-resolution image, two wide blurs, added.
- **Tiers and budget** (`LOD`): phone (< 700 px wide) — 3 hero cells (full tubes, spines, myelin, boutons, nucleus),
  12 mid cells (tubes, every third node, 4 sides, nucleus), 60 far cells (lines), 1 800 tissue sprites, cap
  **250 000 triangles**; desktop — 5 / 30 / 90, 7-sided tubes, cap **1 000 000**. `budget()` drops mid cells first,
  then the spines of the last hero cells (the focus cell keeps its own). `info()` reports the count drawn.
- Nothing is drawn while the brain is off screen (IntersectionObserver) or the tab is hidden; `close()` frees the
  canvas, every geometry, material and render target.

## Measured (this sandbox: headless Chromium, WebGL in software via SwiftShader, no GPU)
`docs/screens/neuron_render/results.json`, by `tests/neuron_render_shots.py` (2026-10-02). No page errors at 1280 or
390 px in any region or style.

**Cortex since #99 (the real H01 cells):** desktop set 20 cells (1 focus L2 pyramidal, 1 L5 pyramidal and 1 L2
interneuron as heroes, 7 mid, 6 far as skeleton lines, 2 astrocytes + 2 oligodendrocytes), **317 760 triangles** of
1 000 000 (280 452 in the meshes + the three axon tubes), 34 draw calls, 1 442 presynaptic and 13 268 incoming
synapses, 1 108 µm of myelinated axon, 2.53 MB of cells + 0.43 MB EM slice (2.99 MB); phone set 17 cells,
**185 501 triangles** of 250 000, 29 draw calls, 1.54 MB + EM (2.00 MB). Under the mid-phone profile (CPU ×4, 390 px)
the main-thread time is **3.1 ms a frame** (2.8 fps in the software rasteriser; 1.7 ms unthrottled); the set decodes
in ~0.2 s from the local server and `nr.ready` resolves ~350 ms after `openAt()` when `prefetch()` ran first. The
action-potential strip (`ap_strip.png`, frames at 0.3 / 1 / 2 / 4 / 8 s after the spike, each cropped around the
front) has the front at 28 / 58 / 118 / 238 µm of real axon path (`ap_front_um`). The NeuroMorpho numbers below for
cortex are now the `*_before.png` shots (`NeuronRender.H01_SETS.cortex = null`), kept as the fallback and for the
before/after pair.

| close-up | desktop LOD (1280 px): triangles / spines / boutons / nodes of Ranvier | phone LOD (390 px): triangles / spines / boutons / nodes |
|---|---|---|
| cortex, NeuroMorpho fallback / before (100 pyramidal + 25 basket; phone 60 + 15) | 925 569 of 1 000 000 · 44 173 on 37 951 of 62 944 µm · 1 867 · 84 | 183 179 of 250 000 · 7 370 on 9 003 of 33 256 µm · 1 147 · 52 |
| striatum (medium spiny) | 302 790 · 4 842 · 10 · 0 | 94 268 · 2 903 · 6 · 0 |
| thalamus (relay) | 450 580 · 3 657 · 5 · 0 | 102 928 · 2 191 · 3 · 0 |
| hippocampus (CA1 pyramidal) | 999 955 · 55 000 on 22 049 of 70 405 µm · 100 · 60 | 197 481 · 10 800 · 60 · 36 |
| amygdala (principal) | 712 790 · 27 903 · 5 · 0 | 186 552 · 10 800 · 3 · 0 |

Draw calls: 7–11 a frame plus 9 quarter-resolution post passes. Under a mid-phone profile (CPU ×4, 390 px, phone LOD)
the renderer's main-thread time per frame (uniforms, the render calls' submission, the post passes) is **1.4–5.5 ms**;
building a close-up (geometry in JS + first shader compile under SwiftShader) 3.7–4.1 s for one-type regions and
14.7 s for cortex (two hero types), of which the pure geometry is 44–200 ms per hero cell at ×4. FPS here is
**2.3–4.5 under ×4 and ~6.5 unthrottled**: the software rasteriser's numbers, which say nothing about a phone GPU —
the sandbox does not reach 30 fps even for the page's existing fibres. **The ≥ 30 FPS check on a mid phone still
needs a real device**; what this branch controls for it is the triangle cap (250k on phones), ~10 draw calls, 1.5× DPR
at most, quarter-resolution post passes, and nothing drawn off screen. The server is untouched:
`python tests/smoke_demo.py --measure 30` → 6.7 ms CPU per 50 ms tick, 601 ticks in 30 s, SMOKE OK.

Also checked: the module runs unchanged under three.js **r169** (ES module, the room's version): 125 cells,
926k triangles, a spike drawn, no console errors, `close()` leaves no canvas (`scratch` page, not in the repo). With the
H01 set under r169: `prefetch()` then `openAt()` with `normal: [1, 0, 0]`, `cameraDir`, `entry {1500 ms, from 6}` →
the block turned by the expected quaternion (−90° about z), `nr.ready` at ~350 ms, `onEntryEnd` at ~2.4 s, the
scale bar reading 50 µm = 75 px at 900 px wide, `setOpacity(0.5)` on canvas and HUD, `close()` leaves 0 canvases.

## Checks
- `pytest tests/test_neuron_render.py` (#99 part): `tests/js/neuron_render_h01_check.js` decodes both H01 sets as the
  page does and checks kinds, path distances, pulse times on ≥ 90 % of axon vertices and ≥ 60 % of presynaptic sites,
  monotone skeletons, ≤ 3 MB and the triangle caps; the manifest's licence and citation; the caption in the module, the
  credits on `/about` and in `morphology_credits.md`; `NeuronRender.BLOCK` against the manifest's bounding boxes; the
  handoff API (`normal`, `cameraUp`, `prefetch`, `setOpacity`, `detailLine` / `sourceLine`) and that `index.html` prints
  the module's lines instead of a hard-coded source.
- `pytest tests/test_neuron_render.py` (#88 part): the asset (same six credited cells, radii, node budget), the plan (monotone
  arrival times, no pulse on dendrites, myelin only beyond the AIS and only on myelinated types, boutons on the
  unmyelinated axon, spines at the stated density), the triangle budget at both LODs (the focus cell keeps its spines),
  the caption word for word, the sources in this file, the call site on `/brain`.
- `python tests/neuron_render_shots.py`: screenshots at 1920, 1280 and 390 px of every close-up region in both styles
  (cortex: fluorescence and EM with the H01 cells, and the NeuroMorpho `_before` pair),
  offline and live, an action-potential strip (frames at fixed clock times after the spike, through the `debugTime` test
  hook: a software-WebGL screenshot takes seconds), the side-by-side with the reference micrograph, counts and timings.
