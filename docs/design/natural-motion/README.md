# Natural, fluid movement in the room (#63, part 1: motion)

The owner's report: "Why is he stuck in this position? I want more fluid, real movements." He stood frozen in the middle
of the room, holding the phone, for the whole 2–4 minutes of ordering food. Part 2 (real dishes, bags, the bin and the
`delivery.dish` field) follows in its own PR.

Everything here is in `web/room.html`. No animation clips or models were added (GLB size change: 0 bytes). The new
props are a few three.js primitives built in code (credited as CC0 in `web/room/CREDITS.md`).

## What changed

### No frozen poses: additive layers on top of the clips (`alive()`, `aliveHead()`)
After the mixer, the walking and sitting steps and the seat IK, every frame:
- **breathing** at his body model's breathing rate (`vitals.resp_per_min`): the chest rises, the shoulders lift; deeper
  asleep;
- **weight shifts** standing: the hips drift a few cm from foot to foot, and two-bone IK keeps both feet planted (no
  sliding);
- **gaze**: head and neck turn towards a point that moves on a spring, within what a neck does. What he looks at depends
  on what he does: reading saccades on the monitor, the street from the window, the phone, glances up from it, the
  door when the courier is due (`courier.status` "on the way" with ≤ 2 min, or "at the door");
- **hands**: thumb flicks and taps on the phone (it dips and tips under the thumb, the wrist rolls a little), the mouse
  at the desk, chopsticks or bread to his mouth, the door handle, the bag;
- **seated**: a slow sway of the back; he sits up from the seated clip's hunch while eating, and a little at the screen.

### Idle variety
Idle variants per situation, picked at random with cooldowns, never the same twice in a row:

| situation | variants |
|---|---|
| standing | look around, scratch head, stretch, check the phone, shift weight |
| at the desk | look around, scratch head, drink from his bottle of tea, lean back, check the phone, knee bounce, hand on the mouse |
| on the bed edge | look around, swing the legs (forward only, never back into the bed frame), scratch head, shift |
| at the window | look around, chin on his hand, shift weight, scratch head, stretch |
| lying (phone, music) | a knee comes up, a foot taps to the music |

Getting up after more than 4 minutes at the desk, he stretches before he walks off.

### Places and poses
| activity | before | now |
|---|---|---|
| `order_food` | frozen standing in the middle of the room | sitting on the bed edge with the phone, or lying if he was in bed |
| `phone` | frozen on the bed edge | on the bed edge, then (at once or after 30–120 s) lies back; the phone moves |
| `window` | standing 2 m from the window | walks through the gap between the chair and the bed and leans on the sill with both hands, looks out (street, sky, towers), glances back in, rests his chin on his hand |
| `get_delivery` | the door clip, alone | walks to the handle side of the door, opens it with the left hand (the leaf swings in; the hallway is dark behind it), takes the courier's bag with the right, pushes the door shut, carries the bag at his side (it swings with his steps) to the desk and puts it down |
| `eat` | the "drink" clip, nothing in his hands | seated upright: a bento held in his left hand and chopsticks, or a bread roll; bites (picking, to the mouth, a bite, down, chewing nods) at a natural pace; the roll gets smaller |
| `listen_music` (#68, new on main) | standing beside the bed | on his back on the bed, headphones on, small nods to the music; at the desk the headphones are on while background music plays |
| away: `buy_konbini` | "out" | "at the konbini" |

Standing now uses a calm pose: the first frame of the door clip. The idle clip turns his whole body through 90°
every 4 s, which was the "same loop for minutes" in the report.

### Transitions
- He **turns on the spot before walking off** (more than 35° off), with small steps: the walk clip at half weight over the
  standing pose, slower. Full strides swept round would kick the bed or the chair.
- **He speeds up and slows down**: 1.4 m/s², top speed 0.9 m/s; he brakes to the end of a path and slows for corners.
  The walk clip plays at the speed his feet move (`timeScale = v / 0.65`), so the feet never slide.
- **Clip fades** are 0.3–0.6 s. Sitting down and getting up use the chair and the bed edge as in #42; that logic is
  unchanged, except for where the chair is parked (below).
- Walking or turning close to the chair or the bed, he keeps his hands in front of his hips (clearance-based).

## Changes to existing behaviour
- **The desk chair.** The model has it turned out by 0.54 rad, which left 34 cm between its backrest and the bed: no
  way through to the window. At load it is squared to the desk and parked 15 cm further in. He still sits where he sat
  before: the ride-in stops at the old distance (`CHAIR.seat`), and only getting up pushes it fully in. It only swivels
  between the seat and pulled out. The route treats it as ±0.40 m (it was ±0.33 m, smaller than the real chair).
- **Bugs fixed along the way:**
  - `q.slerpQuaternions(a, q, w)` always gave `a`: three.js copies `a` into `q` first. So every partly weighted IK
    blend snapped to the clip: the phone arm coming up, the hand on the chair, the feet planted on the bed edge.
    `blendQ()` does it right.
  - A clip that ended a sit-down blend at weight 0 kept `weight = 0`, and `reset()` does not restore it, so a later
    fade-in faded in nothing (he sank into the bed). `play()` sets the weight to 1 first.
  - `touch()` now also keeps bone positions (the hips move for weight shifts).
  - `holdPhone()` decided "lying" from the current clip only; going from the phone to music in bed, the arm came down
    as if he sat up, through the duvet. It now also reads the torso.

## Evidence
All frames are from headless Chromium (SwiftShader WebGL) driving the page in `?debug&nolive`. The rAF loop is frozen
and the page's own `sim()` steps him, so every case is exactly reproducible. Scripts are in `tools/` here (`cap.mjs`: strips and WebMs; `sweep.mjs`, `sweep_m.mjs`: penetration;
`perf.mjs`: timing; `ui.mjs`: screenshots; run against `python -m http.server -d web`). The strips and WebMs were
captured just before the last two small fixes (a clip's weight reset in `play()`, and how `holdPhone()` tells he is
lying); the penetration sweeps are on the final code.

- `strip_<case>.jpg` (after) and `before/strip_<case>.jpg` (main before this PR): one frame every 0.5 s, for order_food,
  phone, phone lying, window (the walk there and the lean), get_delivery (whole, and the door close up), eating a meal
  and bread, and 2 minutes at the window and at the desk (one frame every 4 s).
- `webm/<case>.webm` (after): 10 fps, the same cases.
- `screens/*_1280.png`, `screens/*_390.png`: the whole page at the window, eating, on the phone and listening to music.
- **Penetration** (the #42 check, every skinned vertex inside the bed or the chair): `penetration_sweep.txt`.
  **0 bed and 0 chair vertices** over the whole chained sweep (17 activity changes, about 12 simulated minutes,
  every vertex every 0.25 s) with three random seeds, plus a run with `listen_music`; and 0 in every captured case.
- **Performance** (mid phone profile: 390×844, DPR 2, CPU ×4 by CDP): `perf.txt`. The new layers cost at most about
  +1 ms of script per frame at CPU ×4 (0.6–1.5 ms against 0.2–0.7 ms before). Draw calls go from 41–43 to 45–53 per frame (small props); triangles +0.2%. No new skinned meshes. The real frame rate
  cannot be measured headless: SwiftShader draws WebGL on the CPU, so both before and after run at ~0.1 FPS at
  390×844. That is a limit of this environment, not a result.

## Part 2: food
Real dishes, bags and the bin, and the `delivery.dish` field with labels that name the meal: see `food/README.md`.

## Asleep
Under the duvet, slides parked by the bed, aligned on the pillow, on his side now and then: see `sleep/README.md`.
