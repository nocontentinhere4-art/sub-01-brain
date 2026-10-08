# Upright desk posture (desk_type_ik, desk_mouse_ik, desk_watch)

The owner's video showed him folded over the desk: back off the backrest, chest down toward the desk top, head low.

## Cause
- The captured MakeHuman clips lean forward.
- G14's earlier backrest fit added +15 deg of forward spine pitch on top of that.

## Fix (retarget correction of the captured clips, nothing keyed)
- **Spine:** -15 deg pitch spread over Waist / Spine01 / Spine02, replacing the earlier +15.
  - The head keeps its world turn, so his gaze stays on the screen and keys. The neck takes part of the turn.
- **Seat depth:** 1 cm less deep than before (5 cm instead of 6), so his back rests on the backrest pad instead of pressing into it.
  - Lateral centring, `env.seatIn` 0.06 and the forearm-off-the-desk fix are unchanged.
- **desk_watch:** his resting hands come 10 cm in with his shoulders.
- **Loops:** all three clips are eased into their first frame over their last 1 s.
  - Loop seam (worst bone, last to first frame): mouse 24.2 -> 0.0 deg, type 13.7 -> 0.0 deg, watch 4.0 -> 0.0 deg (`tools/motion/seam.mjs`).

## Measured in the page
Measured with `tools/motion/posture_probe.py`, run from the repo root. It is a regression check:
- spine angle from vertical (hips -> neck, in the chair's side plane; - = forward);
- the back skin's gap to the backrest along the chair's +z (lumbar 0.55-0.80 m, mid-back 0.80-1.05 m above the floor);
- elbow angles.

| mode | spine (deg) | head ahead of hips (cm) | lumbar gap (cm) | mid-back gap (cm) | elbows L / R (deg) |
|---|---|---|---|---|---|
| type / mouse, before (main 95abd03) | -29.2 | 28.8 | 3.6 | 5.3 | 65 / 59 |
| type / mouse, after | -7.4 | 7.5 | 1.9 | 1.9 | 123 / 106 |
| watch, after | -4.4 | 6.8 | 0.0 (touching) | 0.1 | 120 / 120 |

The watch row is from a run of the same build: the depth is the same as type/mouse, only the watch hands differ.

- `tests/visual/test_visual.py::test_room_renders_without_hard_errors`: **passes**, 0 hard failures.
  - desk_14_1280 (the mouse pose): desk 0, chair 0 sampled vertices.
  - It was desk 0 / chair 6 at main 95abd03; the left calf is clear now too.
- Contacts (`tests/visual/contacts --chair-regions`) at the -18 deg trial, typing and mouse: back pad 5 mm, seat 10-12 mm, front 4 mm.
  - At -15 deg the back has a 0.9-1.9 cm gap, so it no longer touches the pad.

## Reference
`reference_upright_seated.jpg`: Pexels video 5483087, cottonbro studio, Pexels license, face pixelated.
- A person seated at a desk working, side view: back near the chair back, a slight forward lean, head over the shoulders.

`reference_vs_after.jpg` shows the reference above the result.

## Renders
`posture_<clip>.jpg`: before (left, main) and after (right), side view, frames 1 s apart (1-6 s).
- These are G14's render scene with the chair placed relative to his hips as the page places it.

## Watch mode, checked over the whole clip (G14, after the first push)
`test_visual` covers only the mouse pose (desk_14). The page's own body check (`__qa.body`) every 0.25 s while it
plays desk_watch (watch mode):

| watch mode, max sampled vertices | desk | chair |
|---|---|---|
| main 95abd03 | 86 | 715 |
| this branch, first push (pitch -15) | 143 | 1001 |
| this branch now (desk_watch pitch -10, resting hands 2 cm higher) | 221 | 886 |

The same check in mouse mode over the whole clip: desk 0, chair 0.
- His hips sit at the same spot in the chair's frame in both modes (0.009, 0.676, -0.016).
- The watch-mode chair hits are the lower back (Spine01) and the calves and thighs (the mouse clip's legs, which the page
  uses in watch mode), so the difference is in what the page does in watch mode. Open with G10d.
- Watch posture now: spine 8.0 deg forward, lumbar gap 0.4 cm, elbows 109 / 115.
