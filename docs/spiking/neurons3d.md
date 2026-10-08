# His active neurons inside the 3D brain (#62)

> Simulated spiking neurons (1M on GPU / 20k on CPU) inside the real wiring of one person's brain; each drawn cell
> stands for a sampled model neuron; a model, not a mind.

## What the viewer sees
- `/brain`: a fifth layer button, **neurons** (fibres · cortex · regions · science colours · neurons). On phones the
  layer row is now shown too (without "science colours").
- **Since #88 B the points below are small real cells (§ "The whole-brain neuron forest"), and offline they stand
  still instead of hiding; the rest of this section describes #62 as built.**
- With a live spiking network, ≤ 20 000 points (12 000 on screens under 600 px, 8 000 in the mini) sit inside the brain: each region gets as many points as the 20k CPU
  network has neurons there (`web/neurons3d.json`), placed just under its parcel of the real cortex mesh
  (`cortex.bin`, nearest region centroid) or, for the 14 subcortical nuclei, in a small cloud around the centroid.
  - a recorded spike flashes its point (a short glow, ~0.35 s fade), played back over the time to the next frame as it
    was spread over the frame;
  - the region's spike rate tints its cloud (blue-grey → orange);
  - while a decision race runs, the striatum (caudate, putamen, accumbens: the action pools) is highlighted;
  - the caption says which network is live, how many of the frame's recorded spikes are shown (or, when the 3 KB/s
    budget left a frame without spikes, "N spikes recorded, none sent"), and the sentence above.
- With no live network the button reads **neurons offline** and the caption says "neurons offline — the 1M network runs
  while he is awake when the GPU is on". Nothing flashes: there is no demo or recorded stream on the server.
- `/brain?mini&neurons=1` (the room's picture-in-picture iframe, 300 × 225): the same layer, 8 000 points, a one-line
  caption at the top. **Room follow-up (after #63):** change the iframe's `src` in `web/room.html` from `/brain?mini` to
  `/brain?mini&neurons=1`; nothing else is needed. A room that draws its own brain can instead call
  `Neurons3D.create({THREE, scene, nodes, cortex, sizes})` (`web/neurons3d.js`, works with r128 and r169).
- `/life` (`web/life.html`) and `/brain`: the Neurons panel (`web/neurons.js`) reads the compact frames; its raster now
  has one row a region (214) and shows the sampled spikes. It also lists the real decisions per Tokyo day from
  `/api/spiking/status` → `learning` (#70): picks that paid off per network, and the night replay's learned vs frozen
  twin agreement, as measured.
- Drawing: one `THREE.Points` draw call, attributes uploaded only when spikes arrive and the layer is on; the page
  draws nothing while the brain is off screen (IntersectionObserver, now for the full page too) or the tab is hidden.

## Stream (`spiking/frames.py`)
Both networks' `{"type": "spiking"}` frames are made compact before any viewer gets them:

| field | what |
|---|---|
| `n3.rq` | base64, 1 byte a region (214 → 288 chars): spike rate, log scale 0.1–100 Hz (byte 0 = below 0.1 Hz) |
| `n3.sq` | base64, 3 bytes a spike: region index, neuron slot 0–255 in the region, time 0–255 of `span`; ≤ 400 a frame |
| `n3.span`, `n3.ns` | simulated ms the frame covers; spikes recorded in it (before the sample) |
| `n3.race` | a decision race is running (CPU: phase `deciding`; GPU: a `decide` pending in the hub, or < 1 s ago) |

- CPU network (`spiking/live.py`, frame builder only): records every neuron's spikes (row = neuron id; the network
  itself is unchanged), measures per-region rates, packs a uniform sample of ≤ 400 spikes.
- GPU network (`spiking/server.py`, `spiking/session.py`): the session's `frame()` adds `"rq":
  frames.quantise_rates(rr)` (the per-region rates it already measured); the hub turns the pod's `raster.spikes` (200
  rows, one neuron a region) into `n3.sq`, which region and slot each row is coming from `frames.gpu_sample(n_neurons)`,
  the same draws as `net.enable_raster`. A pod built before this change sends no `rq`: the page then tints each region
  by its network group's rate and says so.

### Per-viewer budget (`frames.Budget`, one on the server)
A token bucket of 3 000 B/s (burst 1 500 B) over both networks, as the server serialises each frame:
- the panel's numbers (n_neurons, t_sim, spikes_per_s, mean_rate_hz, realtime_x, groups, dopamine) at most once a
  second (and on a phase change); the frames between carry type, net, live, phase, raster t0/t1, n3;
- the spike sample is cut to the bytes left (evenly over the frame);
- the CPU network's frames are dropped while the GPU network streams (the panel already showed the GPU's then);
- the room's lite feed (`/ws?rate=5&lite=1`) no longer gets spiking frames at all (it never drew them; its mini brain
  is the `/brain?mini` iframe with its own socket).

Before: every viewer, room included, got the full raster JSON: 4–12 KB a CPU frame while deciding, up to ~36 KB a GPU
frame (4000 spikes), ~9–40 KB/s.

Measured (`tests/test_neurons3d.py::test_stream_per_viewer_under_3_kb_s`, a real `/ws` socket, bytes as
`tests/load_ws.py` counts them; `-s` prints them):
- CPU network deciding nonstop at 5 frames/s for 30 s (worse than real: it decides ~0.3 s a page): **3 030 B/s**,
  606 B a frame;
- GPU network at the hub's 4 frames/s for 30 s, 4000-spike frames in: **2 987 B/s**, 126 of ~405 recorded spikes shown a frame;
- room (lite feed): 0 B/s of spiking frames.

## Honesty
- Every flash is a recorded spike of a model neuron, sampled; every tint is a measured rate (or, from a pod without `rq`, its network group's
  measured rate, labelled). With no frames the layer is off and says offline.
- The recorded stream in `tests/neurons3d_shots.py` (real frames of the 20k CPU network recorded in the test process)
  is replayed by the test into the page's socket handler for screenshots and FPS only; the server never serves it.
- Wording: "a model, not a mind"; nothing says he understands, feels, is conscious or alive.

## Checks
- `pytest tests/test_neurons3d.py`: quantise/dequantise round trip (within half a step, ~1.4 %), spike packing round
  trip, the GPU sample rebuilt exactly as the network draws it, the 20k layout of `neurons3d.json`, compact CPU frames,
  the budget on `/ws`, the lite feed, the offline state (nothing sent; pod gone → `live: false`), the race flag, the
  page's caption and offline sentence word for word.
- `python tests/neurons3d_shots.py --out docs/screens/neurons3d`: screenshots (1280 and 390 px, offline and live, the
  mini) and the FPS / main-thread numbers under ×4 CPU throttle (`docs/screens/neurons3d/results.json`).

### Measured (2026-10-02, this sandbox: headless Chromium, WebGL in software via SwiftShader, no GPU)
- Main-thread cost of the layer under ×4 CPU throttle (20 000 points): building the clouds 119–232 ms once (when the
  toggle is first switched on), 0.08–0.12 ms per incoming frame, 0.011–0.014 ms per rendered frame.
- FPS under ×4 throttle at 390 px, fibres and cortex hidden: 10.9–15.9 with neurons off, 7.4–10.0 with neurons on.
  These are SwiftShader numbers: the sandbox rasterises on the throttled CPU and does not reach 30 even for an empty
  scene, and the existing fibres alone draw at < 1 frame/s here. **The ≥ 30 FPS phone check still needs a real device
  (or a machine with a GPU)**; the layer's own JS cost (~0.01 ms a frame) is not what would stop it. Mitigations in
  place: 12 000 points under 600 px, one draw call, no uploads while hidden, nothing drawn off screen.
- Server: `python tests/smoke_demo.py --measure 30` tick 5.6 ms CPU per 50 ms tick on this branch and 5.6 ms on main;
  the CPU child between decisions 1.2 % of a core (main 1.6 %).

## Real neuron shapes: close-ups (#78)
> Shapes are real reconstructed neurons from public databases and are illustrative: the simulated network uses point
> neurons (no dendrites are simulated). Pulses are slowed down to be visible.

- **Cells** (`web/neurons_morph.json`, 72 KB, built by `analysis/build_morphologies.py`; credits in
  `docs/spiking/morphology_credits.md` and on `/about`): six real reconstructions from NeuroMorpho.Org, CC BY 4.0,
  each simplified to ≤ 300 segments (axon and dendrites get separate shares of the budget; shortest terminal branches
  pruned first, then Ramer–Douglas–Peucker), soma at the origin, apical dendrites turned up. Human where the
  database has a usable cell:
  | drawn as | cell | species, region |
  |---|---|---|
  | pyramidal (cortex) | NMO_107146 (Tamas; Molnár et al. 2016) | human neocortex L2/3, dendrites + axon complete |
  | basket interneuron (cortex) | NMO_107145 (Tamas; Molnár et al. 2016) | human neocortex L2/3, dendrites + axon complete |
  | medium spiny (striatum) | NMO_10032 (Spiga; Spiga et al. 2005) | rat nucleus accumbens shell (no human MSN) |
  | relay (thalamus) | NMO_115363 (Markram; Iavarone et al. 2019) | rat VPM (no human relay cell) |
  | CA1 pyramidal (hippocampus) | NMO_00222 (Amaral; Ishizuka et al. 1995) | rat CA1 (no human CA1 cell with dendrites + axon) |
  | principal cell (amygdala) | NMO_139102 (Hsueh; Hsu et al. 2020) | mouse basolateral amygdala (no human one) |

  None of them is from the scanned person; no data of that person exist at this scale. The Allen Cell Types archive
  (its own terms) is not used. NeuroMorpho.Org was accessed through its API and direct .swc links with a named user
  agent, as its terms ask; the downloads are cached in `data/morph_cache/` (not in git).
- **Only simulated regions get a close-up.** The cerebellum is not one of the model's 214 regions, so there is no
  Purkinje close-up (the coordinator's call on #78): every close-up carries that region's live spikes.
- **Levels of detail** (`web/neurons3d.js`): the whole brain keeps the #77 points. With neurons on, zooming in on the
  brain (camera distance < `LOD_IN`) opens a close-up of the region nearest the camera (the pallidum, which has no
  close-up shape, falls back to the most active cortical region); zooming out of a close-up (beyond `LOD_OUT` × its
  framing distance) returns to the whole brain. The row "close-up: cortex · striatum · thalamus · hippocampus ·
  amygdala · whole brain" does the same by hand (the most active region of that kind).
- **Close-up**: a block of tissue with 120 (cortex: 96 pyramidal + 24 basket), 220 (striatum), 160 (thalamus),
  150 (hippocampus) or 150 (amygdala) cells, ≤ 60 000 segments, drawn as instanced `LineSegments`: one draw call per
  cell type (cortex 2, the others 1); each soma is three short crossed strokes in the same geometry. Nothing is drawn
  while the brain is off screen or the tab hidden (as before).
- **Spikes on the shape**: each drawn cell stands for a sampled model neuron of the close-up's region (the frame's
  slot 0–255 picks the cell). When its spike arrives in `n3.sq`, the soma flashes and a pulse runs from the soma
  along the axon at 1 mm/s on screen — about 500× slower than a thin unmyelinated axon (~0.5 m/s) — and the
  dendrites glow with the region's rate (`n3.rq`). Per-instance spike times and the pulse live in the shader: no
  per-frame JS loop over segments. Axons stop where the reconstruction stops (the MSN's, relay cell's and amygdala
  cell's are short stubs). The stream is unchanged: a close-up shows the few sampled spikes of one region (≲ 1–2 a
  frame). Offline (no live network), every close-up is static and says "no live network: shapes only, no activity".
- **Checks**: `tests/test_neurons_morph.py` (asset, credits, simplification budget, and via node
  `tests/js/neurons_morph_check.js`: cells / segments / draw calls per close-up, no activity offline or from another
  region, every close-up reacting to its own region, the LOD switch); screenshots and timings:
  `python tests/neurons_morph_shots.py` → `docs/screens/neurons_morph/`.

## The whole-brain neuron forest (#88 B)
> Shapes are real reconstructed neurons (public databases); thickness, spines and myelin are drawn from published
> typical values. The simulated network uses point neurons (no dendrites are simulated); cells are enlarged and pulses
> slowed to be visible. A model, not a mind.

The owner's complaint was that the neurons looked like glowing balls. The whole-brain **neurons** view now draws every
sampled model neuron as a small real cell instead of a dot.
- **Cells:** the six NeuroMorpho.Org reconstructions of the close-ups (CC BY 4.0, `neurons_morph.json`; credits
  unchanged). In the cortex they are pyramidal (80 %) and basket (20 %) cells. The striatum (caudate, putamen,
  accumbens) uses the medium spiny cell; the thalamus, the relay cell; the hippocampus, the CA1 pyramid; and the
  amygdala, its principal cell. The pallidum has no reconstruction in the set, so its few cells (≤ 12) are somata
  only. None of these cells is from the scanned person.
- **Simplified to ≤ 40 segments** (`Neurons3D.simplify`, in the page at start, ~5–40 ms a type):
  1. the 300-segment tree is rebuilt;
  2. the axon is kept only to its first 400 µm of path length (its long straight runs are clutter at this scale);
  3. unbranched runs are straightened (Ramer–Douglas–Peucker, 4 % of the cell);
  4. the shortest terminal branches are pruned first, the axon gets ≤ 35 % of the segments, and the last branch of
     each kind (axon, basal, apical) is never pruned.

  Result: pyramidal 14 axon + 26 dendrite segments; basket 11 + 29; medium spiny, relay and amygdala 2 + 37–38;
  CA1 8 + 32.
- **Enlarged ~6×** (the caption says "cells enlarged ~6× for visibility"; ~14× in the first version, see below). Relative sizes are kept: a medium spiny
  cell stays much smaller than a pyramidal cell. Each soma is a round point of its real radius × 14, at least 2.5 px.
- **Orientation:**
  - Cortical pyramidal cells point their apical dendrite (+y in the asset) along the **local surface normal** of
    `cortex.bin`, at the vertex the cell sits under. Normals are face normals summed per vertex over
    `cortex_idx.bin`, flipped once so they point out (the mesh is wound inwards). Each cell then gets any turn about
    that axis, and half of the cells are mirrored.
  - Check: the page's normals agree with those of a heavily smoothed copy of the mesh on > 90 % of vertices
    (96.7 % measured), and every pyramidal cell's apical axis matches its normal (dot > 0.999).
  - CA1 pyramids point within 30° of one axis per region. The multipolar types (basket, medium spiny, relay,
    amygdala) take any orientation.
- **Activity:**
  - A recorded spike in `n3.sq` lights the soma point and, in the shader, a glow runs from the soma along the axon
    at 2 mm/s of the cell's real (unenlarged) length. That is ~250× slower than a thin unmyelinated axon.
  - The region's measured rate (`n3.rq`) tints the dendrites from blue-grey to orange. The striatum is highlighted
    while a decision race runs (as before).
  - **Offline**, the cells stand still in a neutral colour: no glow, no tint. The caption reads "neurons offline … ·
    static cells, no activity". Nothing is faked; the cells are shown so the view is not empty.
- **Level of detail and cost:**
  - ≤ 600 cells on desktop, ≤ 300 on screens < 600 px, and ≤ 240 in the room's mini. Each region gets cells in
    proportion to its 20k-network population, at least 1 (every region keeps its spikes); over the cap the largest
    regions are trimmed.
  - Desktop: 504 cells and 20 071 segments; phone: 246 cells and 9 756 segments; mini: 224 cells.
  - 7 draw calls: one instanced `LineSegments` per cell type (6) and one `THREE.Points` for the somata.
  - Per-instance spike times are uploaded only when spikes arrive and the layer is drawn.
  - The page draws nothing while the brain is off screen or the tab is hidden (unchanged).
- **Stream:** unchanged (≈ 3 KB/s a viewer, `spiking/frames.py` untouched). More than one slot of a region can map to
  the same cell (1 500–3 000 cells for 256 slots × 214 regions).
- **Close-ups:** zooming in, or a close-up button, opens a region close-up as before. Agent A's renderer
  (`web/neuron_render/`, #88 A) replaces the #78 line close-ups once its module lands; until then those are the
  fallback.
- **Panel layout:** at 1920 px the layer row ("fibres · cortex · regions · science colours · neurons") used to cover
  the bottom of the cards column. The cards' `max-height` assumed a fixed dock height, but the dock grows with the
  close-up row and the caption. Now:
  - a `ResizeObserver` writes the dock's real height into `--dock-h`, and the cards end 14 px above it;
  - the panel is `clamp(340px, 22vw, 420px)` wide;
  - the layer buttons wrap instead of squashing "science colours" onto two lines;
  - the caption scrolls past 30 % of the viewport height.
- **Checks:**
  - `tests/test_neuron_forest.py`, via node `tests/js/neuron_forest_check.js`: segments per cell, LOD caps, draw
    calls, pyramidal alignment, normals against the smoothed mesh, offline static with no spike, a frame lighting
    only its own region, the caption word for word, and the panel CSS.
  - `python tests/neurons3d_shots.py --out docs/screens/neuron_forest`: screenshots at 1920, 1280 and 390 px, live
    and offline, and the forest zoomed; the panel's boxes; counts; JS cost and FPS (`results.json`).

### The look, after the owner's "it looks like a Christmas tree" (#88 B follow-up)
The first version drew ~2 900 cells at ~14× with bright additive colours (dendrite base 0.8–1.5, ×0.75): they
overlapped and saturated to white. Now, like a sparse stain under a dark-field microscope:
- **Fewer, smaller cells:** ≤ 600 / 300 / 240 (desktop / phone / mini), enlarged ~6×.
- **Dim, muted colour:** one hue per cell type, low saturation, base 0.12 before additive blending:
  - pyramidal and CA1: grey-green;
  - basket: grey-amber;
  - medium spiny: grey-mauve;
  - relay: grey-blue;
  - amygdala: grey-rose.
  The axon is drawn at 0.6 of that, and a soma point at 1.6× (≥ 1.5 px).
- **Rates:** a region's rate warms the hue by ≤ 25 % and lifts the brightness by ≤ 50 % of the base. The race
  highlight stays as dim.
- **Spikes:** only a recorded spike brightens a cell (+0.7 × hue), briefly, from the soma along its axon.
- **Behind the cells:** while neurons are on, the fibres step back to 15 % and the cortex rim to 30 %, so the brain's
  shape stays a faint outline.
- **Measured** by `python tests/neuron_forest_look.py --tag before|after` (`docs/screens/neuron_forest_look/`):
  - default layers, text and panels hidden for the measurement;
  - "brain pixels" are those with luma > 0.03;
  - target: ≤ 2 % of them above 0.8 at rest.

  | view | before: > 0.8 | before: mean | after: > 0.8 | after: mean |
  |---|---|---|---|---|
  | 1920 offline | 14.3 % | 0.47 | 0.00 % | 0.10 |
  | 1920 live | 29.5 % | 0.57 | 0.01 % | 0.09 |
  | 390 offline | 12.5 % | 0.43 | 0.00 % | 0.09 |
  | 390 live | 30.9 % | 0.58 | 0.20 % | 0.09 |
  | forest alone, 1920 live | 31.5 % | 0.58 | 0.10 % | 0.11 |
  | forest alone, 390 live | 30.2 % | 0.56 | 2.01 % | 0.16 |

  The last "after" row is just over 2 %. It is live, not at rest: the replayed spikes brighten cells, and on a
  phone-size canvas the few lit pixels weigh more.
- **FPS:** fewer segments, faster. Measured at 390 px with fibres and cortex hidden, software WebGL (SwiftShader) in
  the sandbox:

  | cells (segments) | FPS ×1 | FPS ×4 |
  |---|---|---|
  | none | 19.2 | 13.0 |
  | 246, phone default (9 756) | 13.0 | 10.8 |
  | 504 (20 071) | 13.2 | 8.2 |

  The first version, 1 407 cells and 56 016 segments, ran at 3.6 and 2.0–2.4. **A real device is still the only test
  of ≥ 30 FPS.**
- **Honest limit:** at whole-brain scale a real cell at ~6× is small, about 10–25 px at 1920 and a few px at 390. The
  view now reads as dim, separate cells inside a faint brain, not as cells you can study. For the shapes themselves,
  the close-ups (NeuronRender, #88 A) are the place.

### Measured for the first version (2026-10-02; superseded above: ~14×, 2 901 / 1 407 cells)
- **Counts:**
  - desktop: 2 901 cells and 115 511 segments;
  - phone (< 600 px): 1 407 cells and 56 016 segments;
  - mini: 800 cells requested, at least 3 a region;
  - 7 draw calls in each case (6 instanced types + the somata);
  - ≤ 40 segments in every cell.
- **Panel:** the cards end above the dock at 1920, 1280 and 390 px, offline and live, and no layer button
  overflows its label.

  | width | cards end | dock starts |
  |---|---|---|
  | 1920 | y = 666 | y = 680 |
  | 1280 | y = 377 | y = 391 |

  At 390 the page scrolls and the dock is sticky, as before (`results.json`).
- **Main-thread cost under ×4 CPU throttle** (390 px):
  - building the 1 407-cell forest: 603–674 ms, once, when the toggle is first switched on. This is mostly
    `simplify`, the cortex normals and the layout;
  - 0.11–0.17 ms per incoming frame;
  - 0.01–0.04 ms per rendered frame for the layer's own `update`;
  - the page's whole `frame()`, with three.js submitting the draws: 4–7 ms with the forest on, 3–4 ms off.
- **FPS** (390 px, fibres and cortex hidden, the recorded stream playing, counted from the page's own `frame()`):

  | cells | segments | FPS ×1 | FPS ×4 |
  |---|---|---|---|
  | none | 0 | 19.2 | 13.0 |
  | ~640 | 25 634 | 6.0 | 4.2 |
  | ~800 | 31 548 | 5.2 | 3.4 |
  | 1 407 (phone default) | 56 016 | 3.6 | 2.0–2.4 |
  | 2 901 (desktop default) | 115 511 | 2.0 | 1.2 |

  SwiftShader rasterises every line on the (throttled) CPU, so FPS falls with the segment count. JS per frame stays
  at 1.2–1.9 ms unthrottled and 4–7 ms at ×4, so the layer's own work is not what limits FPS here.
- **The ≥ 30 FPS phone target cannot be shown in this sandbox.** It needs a real device or a machine with a GPU.
  56k instanced line segments (112k vertices, one texture fetch each) are a light load for a mid phone GPU, but
  that is an expectation, not a measurement.
  - Levers if a device falls short: `maxCells` for phones (one number in `web/index.html`), and `FOREST_SEG`.
- **Off screen:** with the scene moved out of view, the IntersectionObserver reports it hidden and the page renders 0
  frames in 2 s.
- **Stream:** unchanged. The recorded 20k CPU stream measured 2 332 B/s per viewer while the screenshots were taken.

Screenshots (`docs/screens/neuron_forest/`, JPEG):
- `brain_{1920,1280,390}_offline.jpg`: static cells;
- `brain_{1920,1280,390}_neurons.jpg`: live, from the recorded stream replayed into the page;
- `forest_{1920,1280,390}_live_zoom.jpg`: the forest alone at half the camera distance;
- `mini_{offline,neurons}.jpg`.

## No meaningless dots (#88 follow-up: "Si vedono ancora pallini che non capisco perché esistano")
Every disc, sprite and point layer on /brain, in the room's mini brain (/brain?mini) and in the Neurons panel, and what
became of it. The guard is `tests/test_no_dots.py`: a new points/sprite/disc layer on these pages fails it until it is
removed or listed there with its reason.

| was | where | now |
|---|---|---|
| forest somata: `THREE.Points` discs, ≥ 1.5 px | `web/neurons3d.js` (`forest-somata`) | a solid soma body at the base of each cell's own tree, turned with the cell, sized from the reconstruction's soma radius: an ellipsoid, or a pyramid-like teardrop for pyramidal cells. Below a pixel at whole-brain scale |
| an axon's spike: a bead running along it | `web/neurons3d.js` forest shader | the axon lights from the soma up to the front and fades (≤ 0.5 s) |
| a stimulus on the fibres: a white bead (×30) running along them | `web/index.html` fibre shader | the fibre itself brightens along its length: a broad front and a fading trail, in its own colour |
| AWAKE fibre shimmer: sharp travelling dashes (`pow(…, 6)`) | `web/index.html` fibre shader | a slow, broad wave with the same mean brightness |
| region markers: glow sprites at the 214 region centroids | `web/index.html` | the region's own patch of the real cortex surface lights, rim-lit like the surface (the "regions" toggle, activity, a stimulus arriving). Subcortical nuclei have no surface: no marker |
| Neurons panel: spike raster (a dot per sampled spike) | `web/neurons.js` | a rate map: the measured spike rate of each of the 214 regions (`n3.rq`) over the last 60 frames, like a calcium-imaging kymograph |
| Neurons panel: live LED; learning curve's end marker | `web/neurons.js`, `web/neurons.css` | removed (the panel says "LIVE"; the caption gives the last value) |
| page header: connection LED | `web/index.html` `#live` | the word "live" / "offline" |
| fibre end points | `web/fibres_ends.bin` | never drawn: the file only says which two regions each fibre joins |

Left, with their reason (in the test): the Pong ball in the Neurons panel (the game's real ball), and the close-up's
out-of-focus tissue layer (`web/neuron_render/`, #88/#99 A; its "counterstain" blobs are flagged to A).

Luminance (`tests/neuron_forest_look.py`, neurons on, default layers, text hidden; % of brain pixels above 0.8): 1920
offline 0.00 → 0.00, live 0.04 → 0.13; 390 offline 0.00 → 0.00, live 0.10 → 0.19; the forest alone live 0.21 → 0.69
(1920) and 0.24 → 1.06 (390): a spike now lights a stretch of axon instead of a bead. All under the 2 % gate. With the
regions toggle on (neurons off) the patches add +0.036 mean luminance to the brain, the old sprites +0.03.
Screenshots: `docs/screens/no_dots/{before,after}_*`.
