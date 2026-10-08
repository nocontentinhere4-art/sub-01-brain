# Asleep in bed: under the duvet, slides off, on his side now and then

The defect (confirmed by the G8 visual QA on main):
- He slept on top of the duvet, dressed, with his slides on.
- His arms were stiff and his hands on his belly.
- His legs floated 9–14 cm above the bed, and his head sank 7 cm into the pillow. The clip tilts him feet-up.
- He lay about 11 cm too far toward the foot of the bed: his toes passed its end and his head was on the pillow's front edge.

Everything is in `web/room.html`, in one block ("in bed", after `tuck()`), plus a few hook lines. The original
`boy.glb` and every other asset are untouched; nothing new is loaded.

## What he does now
- **Aligned on the bed:** he lies 11 cm further toward the headboard (`ANCHOR.bedlie`), with his head in the middle of the pillow.
- **On the bed, not above it:** `lieFit()` corrects the clip:
  - it tips him level about his hips, lowers him onto the bed and straightens his knees;
  - his feet fall forward, relaxed;
  - he rests on the sheet under the duvet, and on the duvet's top when he lies on it (phone, music).

  The values were fitted to a contact measure (`contacts()` under `?debug`). For each body part it gives the lowest gap to a
  heightmap of the sheet, pillow and duvet. On his back:

  | part | head | back | pelvis | thighs | shins | heels | arms |
  |---|---|---|---|---|---|---|---|
  | gap (cm) | +1.0 | −4.0 | +0.9 | +0.6 | −0.5 | −2.6 | −0.7 |

  - The back's −4 cm is his shoulders sinking into the pillow, which dents under them (below).
  - The −0.5 to −2.6 cm are within the mattress's 2 cm of give, the margin the #42 check already allows. The heels'
    lowest point is the slides' sole; the slides are hidden while he is covered.
- **Under the duvet:** a copy of the room's own duvet (same material and texture) is reshaped every 0.1 s over his limbs:
  - his limbs are capsules on the bones, their thickness measured from his own mesh;
  - the cloth drapes about 20 cm around each limb, and the full thickness lifts, so it is never paper-thin;
  - it is pulled up from the foot of the bed to just below his shoulders when he goes to sleep (2.2 s), and goes back when he wakes;
  - it rises and falls with his breathing (his body model's rate: slower asleep);
  - he is longer than the mattress (his toes end about 7 cm past it), so near his feet the duvet's end is pushed out over them.
- **The pillow gives** under his head and shoulders whenever he lies on the bed: a reshaped copy of the bed's mesh.
- **Slides off:** once the duvet covers his feet, his slides are taken off his feet and stand side by side at the bed's edge,
  toes out (`screens/after_slides_parked.jpg`); they are back on when he gets up.
  - They are the triangles of his own mesh, found by colour and bone: dark, on the feet, below the ankle.
  - The parked pair is those triangles in his bind pose, at his scale.
  - Lying on top of the duvet with the phone or music, he keeps them on: under the slides his socks have no soles in the model.
- **On his side now and then:** every 3–8 min asleep, for 1–4 min, he turns over slowly (about 2.5 s), toward the room
  or the wall.
  - He rises off his shoulder by the amount the turn needs.
  - His upper leg rests on the lower one, a little forward.
  - His lower arm goes onto the pillow by his face, the upper one onto the mattress in front of his chest.
  - The hem moves back off his raised shoulder.
  - He turns onto his back before he gets up.
- **Breathing:** as before (#63 part 1): the body model's rate, ×0.8 asleep, deeper; now it also moves the duvet.

## Changed lines (`web/room.html`, against main fc9e455)
- 355: `ANCHOR.bedlie` (11 cm toward the headboard).
- 464–465: at load, find the slides and build their shader (no hitch at bedtime).
- 1475: `drive()` waits until he is on his back before getting up.
- 2092–2303: the new block: `bedInit`, `duvetShape`, `pillowDent`, slides, `rollStep`, `lieFit`, `inBed`.
- 2322: `alive()` calls `lieFit()`.
- 2662: `animate()` calls `inBed(dt)`.
- 2669–2706: debug only:
  - `sim()` refreshes the shadow map;
  - `penetration()` counts against the sheet under the duvet;
  - new `contacts()`;
  - exports.

## Evidence
All frames are from headless Chromium with SwiftShader WebGL, driving the page in `?debug&nolive` with its rAF loop
frozen; the page's own `sim()` steps him. Scripts are in `tools/`; run them against `python -m http.server -d web`.
- `screens/`, from the default camera:
  - before/after asleep at 14:00 and 02:00 (1280 px), and at 23:00 at 390 px;
  - after, on his side both ways, at 23:00;
  - the parked slides.
- Strips (one frame every 0.5 s) and `webm/`:
  - `sleep_in`: from the desk into bed, with the duvet coming up (default camera);
  - `sleep_in_c`, `breathing`: close up;
  - `roll` (default camera), `roll_c` (close): onto his side and back;
  - `wake`: off his side, out of bed, slides back on, to the desk.
- **Penetration:** `penetration_sleep.txt` has 0 bed and 0 chair vertices:
  - in a sleep sweep (into bed, both turns, phone and music on top of the duvet, back to sleep, getting up from his side), 3 seeds;
  - in part 1's chained sweep of every activity, 3 seeds;
  - in every captured frame.
- **Performance** (mid phone profile: 390×844, DPR 2, CPU ×4): `perf_sleep.txt`.
  - Asleep, the script costs about +2 ms per frame (2.3–2.7 ms, against 0.3–0.45 ms on main), against a 33 ms budget at
    30 FPS. The reshape runs at 10 Hz on a 2.5 cm grid; its normals come from the grid's slope.
  - Draw calls: +1 (the duvet copy replaces the duvet, the pillow copy replaces the bed sheet, and the parked slides add one).
  - As in part 1, the real frame rate can't be measured headless: SwiftShader draws WebGL on the CPU.

## The new room model (#107/#110)
The duvet, pillow and mattress were remade as game-quality soft goods after this was written, which broke the lift and
the measurements above. `bedfix/README.md` has what replaced them: the duvet over him is generated rather than lifted,
and his place on the bed is measured on the new pillow.
