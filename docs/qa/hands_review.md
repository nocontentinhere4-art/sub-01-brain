# Desk hands: review findings F6–F9 (`docs/review/main_since_8d159d2.md`, section 3)

All in `web/room/boy_mh.js`.

## F6: switching between the keys and the mouse snapped
**Cause.** The mode picked the code path at once, while the weights crossfaded. When he took the mouse, the right hand
left the owner's take for the old capture path (`keyOn`) in one frame.

**Fix.**
- The path follows the weights, never `keyOn` while the owner's take is loaded.
- While both weights are up, the right hand is solved twice: for the mouse, and for the keys from the clip's pose. The
  two are crossfaded joint by joint (slerp). `pin()` is not linear in its weight, so weighting it gave a 28 cm jump
  near the end of the fade.
- The left hand blends from typing to rest.
- The fade's time constant is now 0.3 s (was 0.13 s): the right hand travels ~40 cm from the keys to the mouse.

**Per-frame index fingertip movement, max (mm; desk_14, 30 fps, page frames):**

| | type → mouse L | type → mouse R | mouse → type L | mouse → type R | steady typing |
|---|---|---|---|---|---|
| main | 56 | 229–258 | 36 | 31 | 4–8 |
| now | 10 | 72 | 17 | 42 | 6–15 |

The right hand now moves over ~15 frames, with no one-frame spike.

## F7: thumb hinges
They are computed once at load from a sample of the typing clip (`otHinges` at t = 0), not from whatever pose the rig
had then.

## F8: NaN and missing bones
- The stroke count only advances when both values are numbers (`if (dn && kn)`).
- `ownerKeys`, `curl`, `otReach` and `mouseHold` return early if a bone they need is missing (the hand, or the S(side,
  2/3/5, 1) knuckles).

## F9: time per frame
`hands()` now measures itself (`M.handsMs`, `M.handsMsAvg`). Medians in headless software GL (a slow environment):

| | typing | mousing |
|---|---|---|
| before | 26.3 ms | 23.5 ms |
| now | 11–12 ms | 17–18 ms |

- **Warm start.** Each finger's knuckle-bend search starts from last frame's answer, inside a ±3° bracket, and falls
  back to the full search only if that misses.
- **Fewer vertices.** Each fingertip's gap uses its 12 pad-most vertices, not the whole end bone's skin. The thumb keeps
  its whole skin: on the pad alone it went 2.5 mm into the space bar.
- **15 Hz reach.** The curl's reach fit runs at 15 Hz.
- **Tried, then dropped.** The whole settle at 15 Hz, re-applying the last bends in between, brought typing to 7 ms. But
  the take moves between searches: only 48% of fingertips stayed in 0..+2 mm, 23 samples were more than 2 mm in, and the
  thumb went 8.8 mm into the keys.

**Still over 2 ms here.**
- Mousing is mostly the mouse hold (`mouseHold`, ~10 ms; G12's).
- Scratch vectors are reused only in the new code.

## Contact (`tools/motion/key_contact_mesh.py`, keyboard mesh, 64 samples over 16 s)

| | resting fingertips in 0..+2 mm | deepest fingertip | >2 mm in | thumb lowest | deepest hand vertex |
|---|---|---|---|---|---|
| typing, main | 84% | −0.5 mm | 0 | −0.7 mm | 0.7 mm |
| typing, now | 82% | −0.9 mm | 0 | −0.8 mm | 1.4 mm |
| mouse mode, left hand, now | 83% | −0.9 mm | 0 | +0.9 mm | 0.9 mm |

## Tests
- `tests/test_boy_mh.py`, in node: the mode flips twice mid-clip. There must be no `keyOn` on either hand, and the left
  hand's typing/rest share may change by at most 0.3 per frame. On main: `keyOn` 17 times on the right, share step 1.
- `tests/visual/test_hand_switch.py`, in the page: type → mouse → type. Each index fingertip may move at most 30 mm
  (left) and 120 mm (right) per frame. On main the right hand jumped 258 mm in one frame.

## Follow-up: a real reach, a steady elbow, a cheaper mouse hold
COORD: at 402e21f the right hand still moved 72 mm in one frame on type → mouse (2+ m/s). A real reach peaks around
1 m/s, so: at most 40 mm a frame at 30 fps, with a bell-shaped speed profile.

**Weights.** Each mode's weight is a phase moving at a constant rate (`REACH_S` = 0.8 s), shaped minimum-jerk
(10p³ − 15p⁴ + 6p⁵). It starts and ends at rest. The exponential approach peaked at its start.

**The right arm mid-switch, in task space.** Slerping the arm bone by bone between the mouse pose and the typing pose did
not give a smooth path. The forearm turned about 160° between the two poses, so the shortest way round swapped mid-switch:
117 mm in one frame. Now:
- The mouse pose is solved at full weight.
- The wrist moves along the straight line between the two poses' wrists, by the weight.
- The arm is solved to that point from the clip's pose.
- The elbow swings to the blend of the two poses' elbows.
- The hand's turn is slerped in the world, and the fingers in their own frames.

**The elbow.** The arm's solve (`ccd`) leaves the elbow's swing about the shoulder–wrist line free. Even in steady typing
the elbow leapt up to 22 cm in one frame while the wrist moved 5 mm. Main does the same: up to 92 mm in a second of
typing, 247 mm on a switch.
- After each pass, `pin` swings the elbow onto the side of that line where a reference point lies. The wrist stays put.
- The reference is last frame's elbow, drawn over 0.5 s toward the clip's.
- The clip's elbow alone is no reference. Its typing arm is nearly straight, with the elbow 8 mm off the line, so the
  side it lay on turned round from frame to frame.

**Per-frame movement, max (mm; desk_14, 30 fps):**

| | type → mouse, right tip | mouse → type, right tip | right elbow, switches | right elbow, steady typing (300 frames) |
|---|---|---|---|---|
| main | 229 | 31 | 247 | 92 (in 30 frames) |
| 402e21f | 72 | 42 | 143–275 | 79 |
| now | 25 | 26 | 14 (one 35 mm frame at the start of mouse → type) | ≤ 25 |

On type → mouse the right fingertip's speed rises and falls over about 20 frames, peaking at 25 mm a frame half-way
(~0.75 m/s).

**`mouseHold`, profiled** (ms per frame, mousing; headless software GL):

| | before | now |
|---|---|---|
| whole | 11.4 | 7.7 |
| shell pin (`mouseFit`, elbow, hand turn) | 3.8 | 3.4 |
| `omOpen` (fingers opened out of the shell) | 4.1 | 2.9 |
| `mouseSettle` (thumb on the flank) | 3.4 | 1.3 |

- **`omOpen` warm start.** Each opened finger tries last frame's share first. It keeps it while the finger only
  touches (0–0.5 mm clear). Else it bisects a ±0.06 bracket, and only then the whole range (8 skin tests on the shell).
- **`thumbSide`.** At most ~60 vertices per thumb bone, one ray each, where before it cast one from every vertex.

**Contact, after both changes:**

| | before | now |
|---|---|---|
| right fingertips on the mouse (index / middle, median over the shell) | 1.6 / 2.4 mm | 1.6 / 2.6 mm |
| right thumb (median) | 2.5 mm | 1.9 mm |
| right hand, deepest vertex | 2.3 mm in | 2.6 mm in |
| hand into the shell (`grip_probe.py contact`) | 0 | 0 |
| typing: resting tips in 0..+2 mm | 82% | 78% (83% without the elbow swing) |
| typing: tips more than 2 mm in | 0 | 0 |
| typing: thumb lowest | −0.8 mm | −2.1 mm |
| mouse mode, left hand: tips in 0..+2 mm | 83% | 84% |

**Typing contact back** (COORD: the thumb at −2.1 mm and 78% of the tips were not inside the limits). Three runs of the
version above gave 80 / 78 / 78% and a thumb at −1.7 / −2.1 / −2.1 mm: not noise.
- **The thumb.** It has a 1 mm margin over the height map while typing (1.5 mm at rest, as before). The height map misses
  the keycaps' steep sides, as on the mouse.
- **The elbow's swing.** It is now done once, after the arm's passes, not in each of them. Swung in every pass, it moved
  the fit under the right hand: 12 of its tip samples were in the keys, against 5.

| typing (64 samples) | 402e21f | above | now |
|---|---|---|---|
| resting tips in 0..+2 mm | 82% | 78% | 82% |
| tips more than 2 mm in | 0 | 0 | 0 |
| thumb lowest | −0.8 mm | −2.1 mm | −1.3 mm |
| deepest hand vertex | 1.4 mm | 2.5 mm | 1.6 mm |

Unchanged:
- **The elbow.** No jump over 25 mm in 300 frames of typing.
- **Switches.** Right tip at most 25 mm a frame; elbow at most 32 mm (one frame).
- **Mouse.** `grip_probe.py contact` reads 0 mm of hand into the shell. The mesh probe puts the thumb's deepest vertex at
  3.0 mm into the flank, where it is meant to sit; it was 2.6 mm.
- **The left hand in mouse mode.** 83% of tips in 0..+2 mm.

**Test.** `tests/visual/test_hand_switch.py` now allows at most 40 mm a frame for the right fingertip and 50 mm for the
right elbow. At 402e21f it fails: right tip 83 mm, elbow 275 mm.
