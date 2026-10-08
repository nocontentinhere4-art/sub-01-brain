# Phone camera (preview/phone-camera, worker G25) — status

Defect (coordinator A, live, 16:03): on a 390×844 phone, asleep in bed, the follow camera framed the room and left him
out (the bed off the left edge); at 1280 he was in frame.

## Milestone 1 — failing test on main: done
`tests/visual/test_phone_camera.py` + `tests/visual/phone_camera.js`. Headless Chromium (SwiftShader), the existing
harness and fake server; the page's follow camera stepped as `frame()` steps it (goal, 1.2/s lerp, keepClear). Each
frame: his projected bounding box (all visible skinned meshes, CPU-skinned) and his head (12 cm sphere). The frame is the
3D canvas less the header (`#top`) that lies over its top on phones. Hard on 390×844, 360×780, 430×932: in bed (asleep,
on his side, music, phone in bed, getting in, getting out) ≥ 80 % of the box in frame and the head in frame every frame;
standing and walking the same; at the desk (the monitor shot, 54 % of him at 1280 by design) the head.

Numbers on main (b851745), worst share of his box in frame / frames with his head cut (90 frames per steady mode;
into bed 690, out of bed 750):

| mode | 390×844 | 360×780 | 430×932 | 1280×800 |
|---|---|---|---|---|
| asleep | 0.917 / 90 | 0.914 / 90 | 0.914 / 90 | 1.0 / 0 |
| on his side | 0.917 / 90 | 0.914 / 90 | 0.914 / 90 | 1.0 / 0 |
| lying, music | 0.915 / 90 | 0.912 / 90 | 0.912 / 90 | 1.0 / 0 |
| phone in bed | 0.915 / 90 | 0.822 / 90 | 0.912 / 90 | 1.0 / 0 |
| into bed (door → lying) | 0.63 / 495 | 0.532 / 546 | 0.745 / 335 | 1.0 / 0 |
| out of bed (→ desk) | 0 / 645 | 0 / 645 | 0 / 645 | 0 / 538 |
| desk (monitor shot) | 0.387 / 25 | 0.373 / 31 | 0.402 / 17 | 0.548 / 0 |
| standing (door) | 0.884 / 90 | 0.817 / 90 | 0.963 / 0 | 1.0 / 0 |
| walking | 0.757 / 90 | 0.685 / 90 | 0.842 / 20 | 1.0 / 0 |

On the phones the overview (fixed at (5.2, 5, 6) → (0, 0.6, 0), vertical FOV 30° on a 0.74-aspect canvas) puts his
head ~11 px from the left edge and the bed past it. Out of bed the monitor shot starts as soon as the desk tick arrives,
while he is still getting up from the bed (at 1280 too: 538/750 frames; left as it is, 1280 must not change).

## Milestone 2 — the fix: done (web/room.html, camera logic only)
- Phones (`camera.aspect < 1`, he is in the room): instead of the fixed overview, the follow camera keeps the overview's
  angle but frames him: a 1.05 m sphere round his hips (lying: him and the bed; standing: head to feet) fitted into the
  band of the canvas under the header (`#top`, read twice a second), so the distance follows the aspect ratio and the
  header's height; his hips sit in the middle of that band. The goal follows his hips continuously and the page's 1.2/s
  lerp moves the camera, so there is no jump between asleep / on his side / awake / getting in or out.
- Phones: the monitor shot waits until he is at the desk (at main it started as soon as the desk tick arrived, with him
  still in bed); at the desk it is the same shot (angle, distance) slid up under the header so his head is not under it.
- The camera's spring arm no longer collides with `shadow_shell` (the invisible slabs that only close the cut-open room
  for the sun's shadow map: no colour, no depth): near the door it pulled the phone camera into his back.
- 1280×800 / desktop: the same code path as before (`aspect ≥ 1`): camera positions identical, 1280 shots pixel-equal
  (max diff 8/255, SwiftShader noise), the desk camera unchanged. 1280's numbers equal main's, including the out-of-bed
  frames where the monitor shot comes in early (538/750, not touched: desktop must not change).

After the fix (worst share in frame / frames with the head cut):

| mode | 390×844 | 360×780 | 430×932 | 1280×800 |
|---|---|---|---|---|
| asleep | 1.0 / 0 | 1.0 / 0 | 1.0 / 0 | 1.0 / 0 |
| on his side | 1.0 / 0 | 1.0 / 0 | 1.0 / 0 | 1.0 / 0 |
| lying, music | 1.0 / 0 | 1.0 / 0 | 1.0 / 0 | 1.0 / 0 |
| phone in bed | 1.0 / 0 | 1.0 / 0 | 1.0 / 0 | 1.0 / 0 |
| into bed (door → lying, 623 frames) | 1.0 / 0 | 1.0 / 0 | 1.0 / 0 | 1.0 / 0 |
| out of bed, on the way (608 frames) | 0.884 / 0 | 0.889 / 0 | 0.852 / 0 | 0 / 516 (as main) |
| out of bed, sitting down (monitor shot, 60 frames) | 0.16 / 0 | 0.155 / 0 | 0.165 / 0 | 0.13 / 21 (as main) |
| desk (monitor shot) | 0.327 / 0 | 0.319 / 0 | 0.335 / 0 | 0.548 / 0 |
| standing (door) | 1.0 / 0 | 1.0 / 0 | 1.0 / 0 | 1.0 / 0 |
| walking | 1.0 / 0 | 1.0 / 0 | 1.0 / 0 | 1.0 / 0 |

Out of bed, "on the way" ends where the page starts the monitor shot (sitting down at the desk), checked every frame;
from there only the head is required. Largest camera move per frame getting out of bed: 3.2 cm on the phones (no jump;
1280: 0.33 m, as on main). `pytest tests/visual/test_phone_camera.py`: 6 passed (636 s).

Sheet: `docs/qa/phone_camera_before_after.jpg` (390×844 asleep, awake in bed with music, at the desk, walking, before /
after; 1280×800 asleep before / after).

## Milestone 3 — full suite: done
`set -o pipefail; python -m pytest 2>&1 | tail; echo "pytest exit $?"` → **1446 passed, 27 skipped, 3 warnings in
1526.67 s; pytest exit 0**. `tests/visual/out/results.json` `hard_failures == []`. (Environment note: `chess` needed
`pip install --upgrade setuptools` before it would build here.)

Files changed: `web/room.html` (camera logic only: `updateCameraGoal`, the phone framing, the spring arm's mesh list),
`tests/visual/test_phone_camera.py`, `tests/visual/phone_camera.js`, `tests/visual/scenes.py` (a music-in-bed scene and
the 360 / 430 phone sizes, both kept out of the shot sets). char_v5.glb and the bed clips are not touched.

## Milestone 4 — merge with main + review G26's defect: done (`d9bbf3a`)
- Merged origin/main (448a0b8, includes A's desk-arrive). `web/room.html` merged by itself; `tests/visual/scenes.py`
  conflicted (main's `computer` scene vs this branch's `music` scene): both kept, both out of the shot sets.
- G26 (docs/review/phone-camera.md on preview/review), HIGH, intermittent: right after load, before the v5 layer was
  ready, the framing followed the old rig's hips (~100 m up): camera at y 115 m, black canvas. Fix (`narrow()` in
  web/room.html): the phone framing runs only when the drawn body is ready (the rig layer sets `bodyReady`: the v5 /
  MakeHuman layer's `mh.ready`) and its hips are finite and inside the room box (x −1.75…3.5, y 0…2.5, z −1.3…3.5);
  otherwise the overview, as on main.
- `tests/visual/test_phone_camera_load.py`:
  - forced: hips moved 100 m up, then NaN; the goal must stay the overview, and the framing must come back when the
    hips do. Without the fix it fails exactly as the review saw: hips y 101 → camera goal y 104.2.
  - live: the 390 page loaded 4×, the scene asleep from the first tick, the page's own loop running 40 s, the camera
    recorded after every rendered frame (requestAnimationFrame wrapped by an init script). With the fix: 10–14 frames
    per load before the v5 layer became ready (~42 s here, software GL), the camera at the overview every frame (9.08 m
    from the room's centre, y 5.0), 0 NaN. The live race did not show here without the fix either (4 loads); the
    forced case is the one that pins it.
- Phone-camera numbers on the merged head: unchanged (asleep / side / music / phone / into bed / standing / walking
  1.0 with the head always in; out of bed on the way 0.884 / 0.889 / 0.852; desk head in every frame; 1280 as main).
- Full suite on `d9bbf3a`: **1471 passed, 27 skipped, 8 warnings in 2176 s; pytest exit 0**; `results.json`
  `hard_failures == []`.

## Milestone 5 — main moved again (7f2bf6e): merged, tests trimmed for CI (`5628d3f`)
- Merged origin/main 7f2bf6e cleanly (CI: the visual job split into "scenes" and "pages", 30 min each; the harness
  freezes the page from its first script; tests/visual/conftest.py).
- My tests are in the "pages" part: trimmed so it stays well inside its 30 min. `test_phone_camera.py` measures the three
  phones only in pytest (1280 is recorded by hand: `python -m tests.visual.test_phone_camera 1280`); the live load test
  2 loads instead of 4 (the forced stale-hips case pins the defect). The "pages" part here: 12 passed in 13 min 12 s.
- Full suite on `5628d3f`: **2 failed, 1469 passed, 27 skipped (31 min); pytest exit 1**; `hard_failures`:
  `walking_8_1280: desk penetration 100 sampled vertices`, `eating_19_1280: desk penetration 53 sampled vertices`.
  - `test_visual` (those desk penetrations): **main's, not this branch's.** A clean worktree of origin/main 7f2bf6e
    fails it with the identical two hard failures (`pytest tests/visual/test_arrival.py tests/visual/test_visual.py`
    on main: 1 failed, 6 passed). This branch merged with main 448a0b8 (`d9bbf3a`) had it green; the change in
    between is main's harness/CI commit 7f2bf6e (it freezes the page from its first script). Not a camera change; not
    fixed here (out of this branch's scope). For C / the owner of 7f2bf6e.
  - `test_arrival.py::test_he_sits_in_real_time_on_a_slow_frame_rate`: timing-sensitive; failed once in that full run
    (its message not kept: the run's output was tailed), passed on this branch alone (2 passed, 109 s), in the "pages"
    run and in the d9bbf3a full run, and on main. In the suite it runs before any phone-camera test.
