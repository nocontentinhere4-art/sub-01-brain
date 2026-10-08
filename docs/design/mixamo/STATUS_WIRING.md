# G21: `room.html?char=mixamo` wiring: status

Branch `preview/mixamo-wiring` (off `origin/preview/mixamo-pipeline`). The raw Mixamo FBX stayed in scratch (taken from
`claude/loving-davinci-6hqmjx:mocap_src/mixamo/`); none is committed, only the clips baked for our skeleton. No RunPod
pod, no Tripo credits used. Method and pipeline: `README.md`, last section.

## Merge with hands-reach (2026-10-07 18:51 UTC, branch `preview/mixamo-wiring-main`)
- `preview/mixamo-wiring-main` 5c6f9b9 + `origin/preview/hands-reach` 2198d69 merged: **2973f0b** (pushed). The conflict in
  `web/room/boy_mh.js` kept both: G14's mode phases `M.ph` (minimum-jerk weights), task-space crossfade and elbow
  reference, and the `?char=mixamo` wiring (`CL`/`CLIP`/`MXK` env overrides, type_in/type_out links + `link()`, `M.link`
  reset, `SEAT_AT` with `env.seatAt`). `node --check` ok.
- `tests/test_boy_mh.py`, `tests/test_char_mixamo.py`, `tests/visual/test_hand_switch.py`: 11 passed.
- Full suite on 2973f0b: **1 failed, 1465 passed, 27 skipped, pytest exit 1**. The failure is
  `test_visual.py::test_room_renders_without_hard_errors`, hard_failures:
  `walking_8_1280: desk penetration 100 at 7.75 s`, `desk_14_1280: desk penetration 11 at 2.75 s`,
  `eating_19_1280: desk penetration 53 at 2.25 s`.
- **main 7f2bf6e alone** (clean worktree, same test): fails with the same `walking_8_1280` (100) and `eating_19_1280` (53).
  These two come from main, not from this branch. Without `?char=mixamo` the wiring does nothing: `CL` = `CLIPS`, no type_in/out
  actions so `setMode` takes main's branch, `link()` returns at once, the seat loop skips them.
  `desk_14_1280` (11 vertices) shows up only after the hands-reach merge. I have not root-caused it yet (G14's desk
  hands, or noise in the sampled frame).
- **Switch test** `tests/visual/test_char_switch.py` (C's request). It works in the page, with no screenshot diff:
  - Default `room.html`: it fetches `room/char_v5.glb` and `room/mh_v5/*`, never `room/char_mixamo.glb`/`.js` or
    `room/mh_mx/*`. The skinned skeleton has v5's 79 joints with its 32 twist/metacarpal bones and none of Mixamo's
    end bones.
  - `?char=mixamo`: it fetches `char_mixamo.glb`/`.js` and `mh_mx/*`, never `char_v5.glb` or `mh_v5/*`. The skeleton has
    65 joints (all `mixamorig:` in the GLB) with the 13 Mixamo end bones and none of v5's.
  - Both page loaders rename bones to the page's names, so the test tells the skeletons apart by size and signature
    bones, not by name.
  - Result: 2 passed. With `CHAR_MX` inverted locally (`!==`), both fail.
  - It is a commit on top of the merge, not inside it: 2973f0b was already pushed when the request reached me.
- Full suite on **390af79** (merge + switch test): **1 failed, 1467 passed, 27 skipped, pytest exit 1**. The one failure
  is the same `test_visual` (walking_8 100, desk_14 11, eating_19 53). It is red from main 7f2bf6e's harness, see the
  bisect below. `test_char_switch` (2) and `test_hand_switch` pass.
- So **hard_failures is not [] on 2973f0b**, and it is not [] on main either.
- 18:57 UTC: **`origin/preview/hands-reach` 2198d69 alone passes test_visual (hard_failures [])**. Its base is 402e21f.
  Between 402e21f and main 7f2bf6e, main only changed `web/room.html` (+41/−13) and tests/visual. That is b3b14cd
  "He sits in real time at any frame rate, and the caption says going to the desk" (G14 a307871 / db6eb20), plus 448a0b8 /
  0ac47f8 (walls). So the red walking_8 / eating_19 desk penetration most likely comes from b3b14cd's change to how he
  sits, not from mixamo-wiring and not from hands-reach. I haven't bisected it. desk_14 (11 vertices) then shows up when
  hands-reach meets that main.
- 19:30 UTC, **bisect done** (test_visual alone, clean worktree each time). b851745, b3b14cd, 7541e19 and 448a0b8 are
  all **green**, with hard_failures []. **7f2bf6e** is the first red one (walking_8 100, eating_19 53). That commit
  changes no page code. Its `tests/visual/harness.py` adds `ctx.add_init_script("window.FREEZE = true")`, so the page's
  loop is frozen from its first script, not only once it has booted. The scenes then start from a different boot state,
  and walking_8 (7.75 s) and eating_19 (2.25 s) put him into the desk. The cause is that harness change on main (or the
  page state it now skips), not mixamo-wiring and not b3b14cd. My note at 18:57 was wrong about b3b14cd.
  desk_14 (11 vertices) appears in the same frozen-boot harness together with hands-reach.

## Round after review (2026-10-07 18:30 UTC, head of this branch)
Answers to Coordinator C's messages and G23 / G26's reviews (docs/review/mixamo-wiring.md on preview/review):
- **404 / floating at 73 m (edd3a02): fixed.** That commit was pushed while the clips were still baking. All 26 clips the
  page asks for are committed, and `tests/test_char_mixamo.py` now fails if any is missing or not on the Mixamo skeleton.
  The page check: he sits at the desk with his root at y 0.16 (the floor).
- **One character source: done.** origin/main merged (448a0b8, after b2593d7). `rig/autorig.sh` re-run on main's
  `web/room/char_v5.glb` (collar closed, socks in slides; 249,148 vertices, 6 primitives). Every clip re-baked and
  re-converted on it.
- **Hem "horns": fixed in autorig.** v5's skin gives the hoodie hem's sides to the thigh (0.5–0.7), so they were neither
  sleeve nor hoodie and kept 0.1 of the upper arm. Skin 4 cm or more over the hip joints whose main joint is a thigh is
  now the hoodie's. G23's pose (only the arms move; hoodie vertices below 1.15 m moved more than 3 cm):

  | pose | G23 on edd3a02 | now |
  |---|---|---|
  | T | 172, max 4.8 cm | 0, max 0.8 cm |
  | arms up 40° | 359, max 7.2 cm | 0, max 0.8 cm |

- **Feet hanging 4–7.6 cm, right hand on the mug (94061b7): gone with main's mouse body.** Both came from v5's old
  mouse clip carried over. The mouse now plays Seated_Idle's body, as on main, with G14's resolver:
  - his palm is 3.2–4.6 cm from the mouse's centre and 2.1–4 cm over its top;
  - his left hand is on the keys every frame;
  - soles 0.2 cm (desk_mouse_ik is dropped from mh_mx).
- **G14's typing resolver** now takes this bake's own F/J points (`char_mixamo.js` ROOM.clipMX, `boy_mh.js` env.clipMX).
  Fingertips touch the keys on 171 of 180 frames (was 5).
- Still the known cost of the armpit cut: raised high, the arm leaves the back of the armpit behind, a web (10,067
  vertices over 5 cm off v5's own T-pose, up to 19.5 cm). It needs an arm-raise corrective shape; not made.

## State
- [x] 1. `room.html?char=mixamo` loads `room/char_mixamo.glb` with `room/char_mixamo.js` and plays the Mixamo clips on
  their own skeleton (`room/mh_mx/`, nothing retargeted to the old rig). Without the flag the page is as on main.
  - Desk: Seated_Idle (watching, and the mouse's body as on main), Typing with Sit_To_Type / Type_To_Sit in and out,
    Stand_To_Sit / Sit_To_Stand.
  - Sitting* are baked, but no slot plays them.
- [x] 2. Armpit weights fixed inside autorig. Arm in torso on the raw desk clips is ≤ 0.6 cm, and ≤ 0.8 cm on every frame
  of the baked desk clips (gate 1.2).
- [x] 3. `rig_change.mjs`: no PENDING items (1 PASS, 2 FAIL, 3 FAIL, 4 PASS, 5 MEASURED, 6 FAIL: below).
  `contact_pass.mjs` over every frame.
- [x] 4. `wiring_sheet.jpg`: main (448a0b8) above, `?char=mixamo` below.
- [x] 5. pytest **1466 passed, 27 skipped, exit 0** (24 min 26 s, on 60d81ae + the seat points); visual `hard_failures == []`.

## In the room, head of this branch (`kimodo/mx_room.sh`, every frame, ?char=mixamo against v5 on the same page)

| | ?char=mixamo | v5 (no flag) |
|---|---|---|
| watching (8 s) | chair / desk / floor clear; seat −0.5…+4.1 cm; soles 0.2 (*); hands in thighs 0 frames | clear; seat −0.1…+4.5; hands in thighs 154 frames |
| typing (6 s) | clear; seat −0.4…+4.2; fingertips touching 171/180 frames, 19 frames under 5 mm into the key tops (−0.8 cm deepest) | clear; touching 166/180, 1 frame under |
| mouse (8 s) | clear; palm 3.2–4.6 cm from the mouse's centre, 2.1–4 cm over it; left hand on the keys 240/240 | palm 4.1–4.4 / 1.9–3.7 cm |
| sit-down (4 s) | chair legs 1.3 cm (24 verts, 18 frames); seat −1.3 | chair legs 1.3 cm (58 verts, 2 frames); seat −1.3 |
| stand-up (4 s) | **chair feet 3.9 cm (138 verts, 4 frames)**, legs 2.4 cm (124 verts, 3 frames); one sole −2.9 cm on the hand-over to the walk | chair legs 1.5 cm (102 verts, 6 frames) |
| rare scared / angry / clap | ride back 35 / 0 / 32 cm; chair legs 2.2 cm (110 verts) / clear / 3.4 cm (442 verts) | 33 / 20 / 31 cm; chair clear |

(*) Soles read up to 4.8 cm only in the first 0.5 s after he is placed, while the page's floor lift eases down (v5 the
same).

Seat points (swept on the new rig): clear from −0.06 m in all three modes. All set to −0.075 m.

Checklist (`rig_change_v5.md`):
- **1. Sit-down landing: PASS.**
- **2. Rising and 3. First step away: FAIL.** A foot goes into the chair's base for 4 frames as he steps off.
- **4. Seat points: PASS.**
- **5. Rare events: MEASURED.** Angry_Gesture rides back 0: the performer sat off-centre.
- **6. Mouse: FAIL** against my 4 cm criterion. The palm reaches 4.6 cm; v5 4.4 cm also fails it.

## 2. Weights (rig/autorig/fit.py, write.mjs, extract.mjs)
All measured every frame at 30 fps, all vertices, with qa.html's test (an arm vertex more than 5 mm behind the nearest
hoodie vertex's normal, within 2.5 cm).

| raw Mixamo clip on the rig | before (G20) L / R | after L / R |
|---|---|---|
| Seated_Idle | 2.4 / 2.4 cm (532 / 373 verts) | 0 / 0.6 cm (0 / 2 verts) |
| Typing | 2.3 / 2.0 cm (113 / 64) | 0 / 0 |
| Sit_To_Type, Type_To_Sit | – | 0 / 0 |
| Stand_To_Sit, Sit_To_Stand, Sitting, Sitting_1, Sitting_Rubbing_Arm | – | 1.1–2.5 cm. The arms hang at his sides or rest on his lap against a slimmer performer's body; the bake moves them out (table below) |

qa.mjs (G20's QA, every 0.1 s, every 2nd vertex): Seated_Idle 0 / 0.5 cm, Typing 0 / 0, the 0.8 s blends both ways
0 / 0. The arms-down rest is 0 (G20: 8 / 15 verts, ≤ 1.2 cm).

What changed, and why:
- **Bound as modelled, not in the T-pose.** Each bone's inverse bind is its T-pose placement taken back through the rigid
  T-posing map of the v5 joint it stands for (fit.py `bindmap`, write.mjs). Rigid parts pose exactly as before.
  Linear blending is not invertible where two maps differ, so a T-posed bind never came back at the armpit.
- **The arm part is the arm.** v5's own (Tripo) skin gives the upper arm 0.9–1.0 of patches of the hoodie's back and
  chest, medial to the shoulder joint. With the arms forward to type, those patches sank 2.4 cm into the torso. Now skin
  is "arm" only within 13 cm of the arm's bind axis and no more than 2.5 cm medial of the shoulder joint.
- **Sleeve and hoodie as two parts** more than 7 cm from the shoulder joint, and **no clavicle on the sleeve** under
  the shoulder. The hoodie keeps the clavicle: without it the hoodie went 2.5 cm into the sleeve instead.
- **Span rule** (v5's skin put 0.18 of the forearm on the armpit), **legs only below the hips** (0.2 of the thigh on the
  chest), **each side's bones on its own side** (0.07 of the right clavicle on the left sleeve).
- **His size kept:** fit.py assumed 0.875 m per bind unit (1.78 m). It now reads the source's own scale (0.8508), so
  char_mixamo is 1.731 m, like v5 in the page. The chair and desk fits were made for that size.
- Tried and measured, not kept: re-centring the shoulder joint; welding the seam; ramps instead of cuts; a pose-driven
  weight hand-over (it diverged).
- **Known cost: raised arms leave a web.** With the arm raised high (the T-pose), the back of the armpit stays behind:
  10,010 vertices end more than 5 cm (max 19.5 cm) from where v5's own skin puts them. Without the 7 cm cut that drops to
  29 vertices, but seated the sleeves go 2.3 cm into the hoodie again. The desk clips keep the arms down. The clips that
  raise them are room_bedtime's stretch, Standing_Clap and the window. The fix for both is an arm-raise corrective
  shape; not made.

## 1. The baked clips (`kimodo/mx_build.sh`, `mx_fit.py` report, every frame; before the re-bake on main's char_v5. Re-bake: the desk clips ≤ 0.8 cm again; Sitting 1.6 / 1.9 cm, Scared 1.1 / 2.2 cm)

| clip | frames | arm in torso before the clearance, L / R cm | after | elbow swing ° L / R | abduction ° L / R | soles cm L / R | knees m |
|---|---|---|---|---|---|---|---|
| Seated_Idle | 126 | 0.3 / 0.0 | 0.3 / 0.0 | 0 / 0 | 0 / 0 | 0.2…0.2 / 0.2…0.2 | 0.59 / 0.57 |
| Typing | 495 | 0.0 / 1.8 | 0.0 / 0.8 | 0 / 14 | 0 / 0 | 0.2 / 0.2 | 0.60 / 0.57 |
| Sit_To_Type | 37 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0.2 / 0.2 | 0.60 / 0.57 |
| Type_To_Sit | 29 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0.2 / 0.2 | 0.60 / 0.57 |
| Stand_To_Sit | 68 | 2.5 / 2.5 | 0 / 0 | 24 / 30 | 20 / 24 | 0.2…0.8 / 0.2…2.0 | 0.60 / 0.56 |
| Sit_To_Stand | 63 | 2.5 / 2.5 | 0 / 0 | 30 / 28 | 20 / 18 | 0.2…0.7 / 0.2…1.2 | 0.59 / 0.57 |
| Sitting_1 | 36 | 1.1 / 2.5 | 0.7 / 0.5 | 2 / 14 | 0 / 0 | 0.2 / 0.2 | 0.59 / 0.58 |
| Sitting_Rubbing_Arm | 240 | 2.2 / 2.5 | 0.8 / 0.7 | 28 / 30 | 0 / 22 | 0.2 / 0.2 | 0.55 / 0.59 |
| Sitting_Talking | 1323 | 2.5 / 2.5 | 0.8 / 0.8 | 30 / 30 | 12 / 18 | 0.2 / 0.2 | 0.60 / 0.57 |
| **Sitting** | 134 | 2.5 / 2.5 | **1.6 / 1.6** (12 / 9 frames over) | 30 / 25 | 24 / 22 | 0.2…1.1 / 0.2…0.9 | 0.58 / 0.57 |
| **Scared** (rare) | 303 | 2.5 / 2.5 | **1.2 / 2.2** (7 / 34 frames over) | 30 / 26 | 16 / 20 | 0.2…1.4 / 0.2…2.2 | 0.58 / 0.57 |
| Angry_Gesture (rare) | 176 | 2.5 / 2.5 | 0.6 / 0.7 | 30 / 26 | 14 / 18 | 0.2 / 0.2 | 0.59 / 0.56 |
| Standing_Clap (rare) | 144 | 2.5 / 2.5 | 0.7 / 0.0 | 30 / 16 | 10 / 24 | 0.2…1.0 / 0.2…0.6 | 0.58 / 0.58 |

Sitting and Scared still go over 1.2 cm (all the reach of the swing and abduction used). Neither is played by a page
slot; the rare events are not accepted on v5 either (README).

The fit, briefly:
- Hip joints at 0.68 m, 4.5 cm forward; the cushion stops the hips.
- His own wrists, ridden up with him; typing `keys` −11 cm puts his fingertips over our key tops (0.86 m).
- Knees at 0.55 m. Our chair is high for him: with the feet flat his thighs went 3–8 cm through the cushion's front edge,
  so his heels come up 7–8 cm, as on v5.
- Feet planted with the soles +0.2 cm; sleeves off the hoodie.

## Tests
- Head of this branch: `set -o pipefail; python -m pytest 2>&1 | tail; echo "pytest exit $?"` → **1466 passed, 27
  skipped, pytest exit 0**. `tests/visual/out/results.json` `hard_failures == []`.
- Before the merge: 1287 passed, 27 skipped, exit 0. One earlier run failed `test_boy_motion.py::test_licences_recorded`,
  which asserts CREDITS.md never names Mixamo. **For the coordinator:** CREDITS points to this folder's README
  ("Sources and licences") instead of naming the source. Whether that guard should stay is a policy call. I did not
  edit the test.
