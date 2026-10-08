# NeuronRender: the close-up API (#88, part A ↔ part B)

`web/neuron_render/neuron_render.js` draws one region's neurons at microscopy scale: tapered tubes from the SWC
radii, a soma with a nucleus, spines, myelin with nodes of Ranvier, boutons, an out-of-focus tissue background,
bloom and a mild depth of field, in a **fluorescence** or a **3D render** style. It is a classic script
(`window.NeuronRender`, no modules, no bundler) and takes the page's `THREE` (r128 global on `/brain`, r169 module
in the room: both work; it uses nothing newer than r128).

Part B (`web/neurons3d.js`, the whole-brain forest) hands over to it when the viewer zooms into a region or presses a
close-up button, and takes back when it closes. The module owns **its own canvas**, overlaid on the container it is
given, with its own render loop, camera and orbit (drag to turn, wheel / pinch to zoom): the page's brain scene is
not drawn while a close-up is open (the page's loop should `return` while `nr` exists, as it does today).

```html
<script src="/neuron_render/neuron_render.js"></script>   <!-- after three.js; loads /neuron_render/cells.json itself -->
```

## #99: real H01 cells, the seamless zoom, two looks (additions; everything above still holds)

- The cortex close-up draws **real electron-microscopy reconstructions** (H01, Shapson-Coe et al. 2024, CC BY 4.0:
  proofread human temporal-cortex cells with their spines, synapses and H01's own axon / dendrite / soma / AIS /
  myelinated-axon labels; glia from the automated segmentation; a real EM image behind). Assets are lazy-loaded from
  `web/neuron_render/h01/` (≤ 3 MB per region set, gzip; decoded with `DecompressionStream`). Regions H01 does not
  cover (striatum, thalamus, hippocampus, amygdala) keep the NeuroMorpho.Org procedural cells; `info().source` says
  which ("H01" or "NeuroMorpho"), and `nr.caption()` says it in words.
- **Entry animation for B's zoom:** `open(container, {..., entry: {ms: 1200, from: 6}})`: the camera starts `from`×
  farther than the default framing and flies in over `ms` while the canvas fades in. `nr.ready` is a Promise resolved
  at the first drawn frame; `onEntryEnd()` fires when the fly-in ends.
- **`NeuronRender.openAt(container, opts)`** = `open()` + B's zoom end, all in B's world coordinates:
  - `worldPos` (the brain-space point B zoomed into; stored in `info().worldPos` for B's bookkeeping);
  - `normal` (the outward cortical normal there): the block's **+y is "toward the pia"**; the whole block is turned so
    that +y lies along `normal` (shortest rotation; `info().normal` echoes it). Without it the block stands with +y up;
  - `cameraDir` (unit vector: B's view direction at the cut) and optionally `cameraUp` (B's camera up, default
    world +y): the entry camera looks along `cameraDir` with that up, so the cut is continuous;
  - `entry: {ms, from}` (the fly-in, above). Without any of them `openAt` behaves as `open`.
- **`NeuronRender.BLOCK`** (a static, readable before `open()`): the cortex block's extent in µm in the block frame,
  the union of the H01 cells' bounding boxes (`h01/cortex.json`): `{um: [w, h, d], min, max, pia: "+y", focusUm:
  [0, 0, 0], focusDepthUm, depthUm: [top, bottom], depthApprox: true}`. `depthUm` is how deep below the pia the
  block's top and bottom lie, estimated from H01's soma table (the highest layer-1 somata of this column sit about
  780 µm above the focus soma), good to roughly ± 100 µm; `focusDepthUm` is the focus soma's. B sizes and places
  the zoom target from it; a test checks it against the manifest.
- **`NeuronRender.prefetch({kind, lod, base})`** starts fetching the region's H01 set (`h01.js`, the cells, the EM
  slice) while B's camera is still flying; a later `open()`/`openAt()` finds it in the module cache. Resolves to the
  decoded set, or `null` where the kind has no H01 set or the browser lacks `DecompressionStream` (then `open()`
  draws the NeuroMorpho cells as before). Safe to call more than once.
- **`nr.setOpacity(a)`** (0..1) fades the whole close-up (canvas, HUD, scale bar) for B's cross-fade on the way out;
  `nr.opacity()` reads it back. It multiplies the entry fade-in, which the module runs by itself (the canvas starts
  at 0 and is fully in after 40 % of `entry.ms`), so B need not drive the fade-in.
- **`info().detailLine` / `info().sourceLine`**: two ready-made sentences for the page's panel: what this close-up
  draws (cells, proofread detail, synapses, myelin, triangles, style) and where the shapes come from (H01 cells with
  their ids, or the NeuroMorpho.Org ids). `index.html` prints them as they are, so the panel never says NeuroMorpho
  for H01 cells or the other way round.
- **Styles:** `setStyle("em" | "fluorescence")`: EM-grey tissue (membrane-like shading, the real SEM slice behind, a
  dark grey field) and confocal fluorescence (sparse-label colours, depth of field). `"render"` is kept as an alias of
  `"fluorescence"`. A real **scale bar** (µm) sits in the HUD, computed from the camera at the focus depth.
- **Caption:** `NeuronRender.CAPTION` is now: "Shapes are real reconstructed neurons from public datasets (H01 human
  cortex electron microscopy, Shapson-Coe et al. 2024; NeuroMorpho.Org), CC BY 4.0. The activity is simulated by a
  point-neuron network and slowed down to be visible. A model, not a mind." It is true for every close-up;
  `nr.caption()` adds which dataset this close-up draws.
- Activity on H01 cells: the pulse runs along the cell's **real axon** (its skeleton, path distance from the soma),
  saltatory on the stretches H01 labels as myelinated; the cell's **real presynaptic sites** flash when the pulse
  reaches them; its incoming synapses are drawn as dots. Still only recorded spikes of sampled model neurons.

## Open / close

```js
const nr = NeuronRender.open(container, {
  THREE,                       // the page's three.js
  region: 12,                  // brain.json region index (0-213): the region whose spikes this close-up shows
  kind: "cortex",              // "cortex" | "striatum" | "thalamus" | "hippocampus" | "amygdala"
                               //   (NeuronRender.kindOf(node) gives it from a brain.json node; null = no close-up)
  label: "left Vis 13",        // the region's label for the caption
  style: "fluorescence",       // "fluorescence" (GFP green / tdTomato orange on black) | "render" (soft 3D)
  lod: "auto",                 // "auto" (by screen width and devicePixelRatio) | "phone" | "desktop"
  live: false,                 // is a spiking network live now? (updated by onFrame / setLive; see Activity)
  onClose(reason) {},          // the viewer zoomed out past the block ("zoomout") or pressed ✕ ("button")
  onInfo(info) {},             // counts changed (first build, LOD or style change): same object as nr.info()
  debug: false,                // show fps in the overlay (default: only when the page URL has ?debug)
  groupRate(msg) {},           // optional: Hz of this region's network group from a frame without n3.rq (a pod built
                               //   before #62's per-region rates); the module quantises it like quantise_rates
});
nr.close();                    // removes the canvas, frees every GPU resource, stops the loop (no onClose call)
```

`container` is a positioned element (the brain's host `div`): the module appends `<canvas class="nr">` with
`position:absolute; inset:0` and a small HUD (style toggle, ✕) in the container's corner; `nr.close()` removes
both. Nothing else on the page is touched.

## Activity (never faked)

```js
nr.onFrame(msg)                // every {"type":"spiking"} websocket frame, as received (spiking/frames.py: n3.rq, n3.sq, n3.span)
                               //   the module keeps only this region's sampled spikes (frame slot 0-255 -> a drawn cell)
                               //   and its rate byte; it goes offline by itself 10 s after the last frame
nr.spike(slot, delayMs = 0)    // alternative to onFrame: one recorded spike of this region (slot 0-255), to play after delayMs
nr.rates(rq)                   // alternative to onFrame: Uint8Array(214) of rate bytes (quantise_rates) or a number for this region
nr.setLive(false)              // force offline (e.g. the socket closed): static cells, caption "no live network"
nr.debugTime(s | null)         // test hook: freeze the clock s seconds after the last spike(); frames bring no new spikes while held
```

What a spike does: the cell's soma flashes; an action potential runs from the soma along the axon at the real
conduction speed divided by `NeuronRender.SLOWDOWN` (stated in the caption), hopping node to node where the type is
myelinated (saltatory: an internode lights at once, the next after its delay); the axon's boutons glow when it
arrives. The region's rate byte sets a faint dendritic glow. With no frames for 10 s nothing moves and the caption
says so. No frames → no activity, ever: there is no demo mode.

## Look, LOD, measure

```js
nr.setStyle("render"); nr.style()         // toggle; the HUD does the same
nr.setLod("phone"); nr.lod()              // "phone" | "desktop"; "auto" picks by screen width / DPR
nr.focus(i)                               // put the depth-of-field focus and the hero detail on drawn cell i
nr.resize()                               // the container changed size (the module also listens to window resize)
nr.info()                                 // {kind, region, label, style, lod, cells, heroCells, triangles, triangleCap,
                                          //  spines, boutons, nodesOfRanvier, drawCalls, live, spikes, fps, jsMs, offScreen}
nr.caption()                              // the honest caption, plain text (see below)
```

Rendering stops while the container is off screen (IntersectionObserver) or the tab is hidden; `info().fps` and
`info().jsMs` are measured over the last second. `triangles` is the count drawn at the current LOD; `triangleCap`
is the LOD's cap (the planner drops far cells, then spines, then tube sides until it fits).

## Statics

```js
NeuronRender.kindOf(node)        // brain.json node -> kind or null (same rules as Neurons3D.kindOf)
NeuronRender.KINDS               // kind -> {types: [[type, share]], cells: {phone, desktop}}
NeuronRender.SLOWDOWN            // the stated slowdown of the pulses (number)
NeuronRender.CAPTION             // the fixed sentence (word for word from #88):
                                 //   "Shapes are real reconstructed neurons (public databases); thickness, spines and
                                 //    myelin are drawn from published typical values. The simulated network uses point
                                 //    neurons (no dendrites are simulated); cells are enlarged and pulses slowed to be
                                 //    visible. A model, not a mind."
NeuronRender.CELLS               // once loaded: the asset (cells.json) with per-type credits (NeuroMorpho.Org ids, papers)
NeuronRender.load()              // Promise of the asset (open() calls it; B may call it early to prefetch)
```

## What B keeps doing (today's call site, `web/index.html` `closeupOpen` / `closeupExit`)

- pick the region (most active of its kind, or nearest the camera) and call `open` with `region`, `kind`, `label`;
- pass every spiking frame to `nr.onFrame(msg)` next to `n3d.onFrame(msg)`;
- on `onClose`, drop `nr`, restore the brain camera and the layer buttons;
- the caption line (`nr.caption()` + credits) in the panel, as `closeupLine()` does today. The module never writes
  into the panel.

A: `web/neuron_render/*`, `docs/spiking/neuron_render.md`, this file, and the close-up call site only.
B: everything else in `web/neurons3d.js`, the panel HTML/CSS.
