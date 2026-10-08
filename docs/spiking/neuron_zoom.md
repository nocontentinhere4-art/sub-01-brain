# The zoom: the whole brain → a cortical column → the tissue (#99 B)

> Shapes are real data from named public datasets: the cells are NeuroMorpho.Org reconstructions of human cortical
> neurons, and the layers are measured in H01 (human temporal cortex, Shapson-Coe et al. 2024, CC BY 4.0); here they
> are drawn at true size. The activity is simulated by a network of point neurons (no dendrites are simulated). A
> model, not a mind.

The owner (#99): "Deve essere più reale possibile … puntiamo al realismo massimo."

On `/brain`, with neurons on, zooming in (wheel or pinch past 110 mm) or pressing **dive ↓** is one continuous motion
at true scale. The scene is in millimetres (`brain.json` space).

| camera distance | what is drawn | scale bar |
|---|---|---|
| ~360 mm (default) | the MRI brain: fibres, cortex, the dim forest of small real cells (~6× enlarged, #97) | "20 mm · cells drawn ~6×" |
| 80 → 30 mm | the brain fades (fibres to 0, cortex rim to 0, forest to 0 by 6 mm); the column fades in at the point aimed at | — |
| ~5 mm | a 0.5 mm-wide column of cortex, 2.15 mm deep, layers L1–L6 labelled, at true size, pia at the top of the screen | "500 µm · true scale" |
| < 0.9 mm | hand-over to the tissue block (`NeuronRender.openAt`, #99 A: real H01 EM reconstructions) at the same spot, looking the same way | A's HUD |

Zooming back out reverses it. The tissue view's `onClose("zoomout")` returns to the column at the same spot. Beyond
170 mm the zoom ends and the camera's target eases back to the brain's centre.

## Where the dive goes
- The cortex vertex under the screen's centre that faces the camera (every 3rd vertex of `cortex.bin`, nearest to the
  centre ray; the nearer surface wins ties).
- Its outward normal comes from `cortex_idx.bin`, exactly as the forest's pyramids use it (#88).
- Its region is the nearest Schaefer parcel centroid. The column shows that region's sampled spikes and its rate.
- The camera ends looking **across** the column, perpendicular to the normal (like a slice under a microscope).
  `camera.up` turns to the normal as the brain fades, so the pia is at the top.

## The column (`Neurons3D.column`, `web/neurons3d.js`)
- **Layers.** These are H01's own thicknesses, measured from its public layer annotation by `analysis/h01_layers.py`
  (build time, `cloud-volume`; the page never loads it).
  - The annotation is `gs://h01-release/data/20210601/layers`, read at 8 × 8 × 8.448 µm.
  - Thickness is the median boundary-to-boundary distance in 3 sections.
  - Result: **L1 413, L2 303, L3 447, L4 272, L5 449, L6 261 µm (2 145 µm)**, in `docs/spiking/h01_layers.json`.
  - A test checks that the page's constants equal it.
  - L1 is thick in this sample; that is the measurement, not a choice.
- **How many neurons it stands for.** H01's ~16 000 neurons per mm³ (Shapson-Coe et al., bioRxiv: "The number of
  neurons in this human sample is ∼16k/1 mm³").
  - L1 is assumed to be 10 % of that; it is cell-sparse.
  - Result: ~7 100 neurons in the 0.5 × 0.5 × 2.145 mm column.
- **Sparse label.** Like a Golgi stain, a few percent are drawn: 3 %, so **213 cells**. Each is a real reconstruction
  at **true size**, simplified to ≤ 90 segments, with the axon kept to its first 600 µm.
  - L1: basket interneurons (the human basket cell; L1 has no pyramids).
  - L2–L4 and L6: the human L2/3 pyramid (NMO_107146) 70–80 %, basket 20–30 %.
  - L5: the **human L5 pyramid NMO_159993** (Valiante archive, anterior temporal cortex, dendrites complete, no axon
    reconstructed; Moradi Chameh et al. 2021). Its apical tuft reaches ~1.5 mm. Each one is scaled 0.8–1.15× so that
    its tuft ends 40–300 µm below the pia, in L1, as real tufts do (a test checks all of them).
  - No pyramid crosses the pia.
- **Orientation.**
  - Pyramids stand along the outward normal: the apical dendrite is the column's +y, with any turn about it and a lean
    of ≤ ±8°. Half are mirrored.
  - Interneurons take any orientation.
- **Look.**
  - The forest's dim sparse-stain colours (#97) and soma bodies, not dots (#105).
  - Faint square outlines at the pia, at each layer boundary and at the white matter.
  - The tissue block's depth band (`NeuronRender.BLOCK.depthUm`, 400–1 250 µm in H01's column), within the column's
    width.
  - While the column is small on screen it is dimmed by (5.5 mm / distance)^1.5, so its 213 cells don't pile into a
    white blob.
- **Optics** (`lightSheet()`, in the vertex shaders of the forest and the column; no post-processing pass, so phones
  pay nothing for it).
  - A light sheet / shallow depth of field: cells at the focal depth (the distance looked at) are at full strength,
    and the rest dim to 35 %.
  - Out-of-focus light drifts toward a faint blue-green, like scatter in a fluorescence image.
  - It only dims or re-tints; it never brightens.
- **Activity.**
  - The column's region's sampled spikes (`n3.sq`): the soma flashes, and the axon lights from the soma to the front
    and fades.
  - Its measured rate (`n3.rq`) warms the dendrites a little.
  - Offline: static, captioned.
- **Assets are lazy.** `web/column_morph.json` (15 KB, the L5 cell) is fetched when the zoom first starts.
  `NeuronRender.prefetch({kind: "cortex"})` starts A's H01 load when the camera passes 10 mm.

## Hooks
- **`window.zoomBrain`** (1 → 0 as the brain fades). `web/brain_anatomy.js` (G9) multiplies its materials' alpha by it.
- **The hand-over.**
  - When `NeuronRender.openAt` exists (#99 A, PR #101), the call is
    `openAt(host, {worldPos, normal, cameraDir, cameraUp, entry: {ms: 1200, from: 6}, …})`.
  - Before that, it is the plain close-up (`closeupOpen("cortex", region)`).
  - The tissue view's caption is A's (`NeuronRender.CAPTION`, `info().detailLine` / `sourceLine`).

## Measured
These are from `python tests/neuron_zoom_shots.py`, on 2026-10-03 after merging #101, in this sandbox: headless Chromium with software WebGL
(SwiftShader), and the recorded 20k CPU stream replayed into the page. Frames, contact sheets (`zoom_{1920,390}_sheet.jpg`),
GIFs (`zoom_{1920,390}.gif`) and `results.json` are in `docs/screens/neuron_zoom/`.

| dive | distance | stage | scale bar (1920) | % > 0.8 (1920 / 390) | mean (1920 / 390) |
|---|---|---|---|---|---|
| 0.00 | 361 mm | brain | 20 mm · cells drawn ~6× | 0.14 / 0.10 | 0.10 / 0.13 |
| 0.30 | 70 mm | brain | 5 mm | 0.00 / 0.01 | 0.08 / 0.12 |
| 0.45 | 19 mm | column fading in | 1 mm · true scale | 0.00 / 0.00 | 0.05 / 0.07 |
| 0.55 | 9 mm | column | 500 µm | 0.00 / 0.00 | 0.09 / 0.08 |
| 0.62 | 6.4 mm | column | 500 µm | 0.00 / 0.00 | 0.16 / 0.13 |
| 0.70 | 5.5 mm | the whole column | 200 µm | 0.01 / 0.00 | 0.18 / 0.14 |
| 0.80 | 3.3 mm | column, closer | 200 µm | 0.67 / 0.01 | 0.23 / 0.18 |
| 0.90 | 1.3 mm | toward the block's depth | 50 µm | 0.00 / 0.06 | 0.13 / 0.23 |
| 1.00 | 0.81 mm | tissue: A's real H01 cells (`openAt`) | 50 µm | 0.05 / 0.15 | 0.13 / 0.21 |

- **Luminance:** every frame is under the #97 gate (≤ 2 % of pixels above 0.8). A first run without the pixel-density
  dimming had 12–20 % at 390 in the column; the column now dims by its height on screen in pixels, not by distance.
- **Counts:** the column has 213 cells, 19 049 segments and 5 draw calls; the brain's layers are not drawn once faded.
- **FPS at 390 px**, software WebGL (a CPU rasteriser, not a phone's GPU):

  | where | FPS ×1 | FPS ×4 | JS per frame (×1 / ×4) |
  |---|---|---|---|
  | the whole column (5.5 mm) | 6.3 | 4.0 | 1.6 / 5.1 ms |
  | close in (1.6 mm) | 5.3 | 3.5 | 1.2 / 2.9 ms |

  Before the faded-out fibres and cortex were taken out of the draw it was 0.2 FPS: inside the column the camera sits
  within the fibres, and drawing them at zero opacity still cost every one of their pixels. **≥ 30 FPS on a phone
  still needs a real device.** The layer's own JS is a few ms.
- **The hand-over:** with #101 merged, the dive ends in `NeuronRender.openAt` at the same spot and direction: A's real
  H01 electron-microscopy cells (20 cells, 318k triangles on desktop), with A's caption and source line. A measured
  `nr.ready` at ~260 ms after a prefetch; the zoom prefetches below 10 mm.
- **Re-check after #101 (390 px, ×4 CPU, the whole column):** 4.5 FPS, 2.9 ms JS per frame.

## Where it can't look real, and the cut
- **The brain scale** cannot show cells you can study. A real neuron is 0.5–1.5 mm across, and the brain is ~150 mm.
  That is why the forest is drawn ~6× enlarged, dim and sparse, and labelled so.
- **The jump from 5 mm to the tissue** is the cut. Below ~1 mm, a true column of 7 000 neurons drawn at their real
  density would be a solid wall. So the column shows a 3 % sparse label (honest: "213 of ~7 093 drawn, like a Golgi
  stain"), and the dense, real tissue is A's H01 block, which is the real thing at that scale.
