# Hands at the desk: resting on the keys, holding the mouse

## Owner's note
The right hand must hold the mouse. The left hand was "ultra strange": fingers splayed and stiff, and the mouse untouched on its mat.

## What was wrong (measured in the page, mouse mode, desk_14)
- **Right hand:** wrist 10 cm and lowest fingertip 8.8 cm above the mouse pad on main 95abd03, so it hovered over the mouse.
  After the posture fix: 4.0 / 5.4 cm. Now: 1.3 / 2.6 cm.
- **Finger shapes:** these came straight from the MakeHuman clip's own curls, never posed for keys or a mouse.
- **The page's wrist pin (boy_mh.js `pin` / `ccd`):** it turns the forearm and upper arm to reach the keys or the mouse,
  and the hand, kept local to the forearm, turned with them. Once he sat upright, that turn stood the right hand on edge:
  palm facing back, fingers up.

## Fix
1. **Clips:** desk_type_ik keys/keys, desk_mouse_ik keys/mouse, desk_watch relax/relax. Built with mh_retarget `handPose`
   (preview/motion-c `tools/motion` has the retarget's sibling tools).
   - Each phalanx is aimed along the hand's wrist-knuckle line, spread about the palm normal, and turned toward the palm
     by the summed flex (MCP, PIP, DIP).
   - The thumb tip is set by CCD onto a point in the hand's frame.
   - The hand's own turn follows the photographs: palm down, fingers forward along the desk; keys pitched down 12 deg and
     turned 12 deg inward, mouse pitched down 8 deg.
   - keys: index 25/35/15, middle 28/38/15, ring 30/40/18, little 32/42/18 deg. Fingers together (spread +3/0/-3/-6),
     a gentle dome, the thumb down toward the space bar. References: kb1, kb2.
   - mouse: index and middle 8/12/6 (nearly straight on the two buttons), ring 28/40/20, little 35/45/25 (curled round
     the far side), the thumb flat along the near side, tip at mid-length. References: mouse1, mouse2.
   - relax (desk_watch): loosely curled, 15-21 / 25-31 / 10-12 deg.
   - `clip_space_check.png`: the clip as authored, without the page's pin. The right hand is palm-down over the mouse and
     the left hand's fingers are curled on the keys.
2. **Page (boy_mh.js `pin`):** after each CCD pass the hand keeps its world turn from the clip (blended by the pin
   weight). Only the arm moves to reach, so the photographed hand shape arrives as authored. This is 2 lines in G10d's code.

## Result
`before_after_over_left_shoulder.jpg`:
- Top row, over his left shoulder (the owner's angle): before on the left, after on the right.
- Bottom row: the left hand close, before and after. With the right hand on the mouse, the left now rests relaxed and
  curled beside the keyboard instead of flat and stiff.

`after_mouse_over_and_side.jpg`: the right hand palm-down on the mouse, index and middle fingers over the buttons.

## Not done here
- No finger motion: no typing taps, no clicks. Typing would be motion and needs a real source, as ruled.
- In mouse mode the page does not pin the left hand. It rests where the clip has it: on the desk by the keyboard, not on the keys.

## References
Pexels License, no faces, logos pixelated; details in `SOURCES.md`:
- kb1 18966470 and kb2 28993052: Matheus Bertelli.
- mouse1 5745010: Ryutaro Tsukata.
- mouse2 5185149: cottonbro studio.

## Mouse grip tightened (COORD's nit: the fingers were fanned in the top-down view)
Measured on the references (mouse2 top-down, pixel positions):
- The index finger points about 14 deg toward the thumb from the middle finger. In mouse1 the two lie closer still.
- The middle and ring fingers are together; the little finger is tucked under the ring on the shell's right flank.
- The thumb lies flat on the left flank.

New per-phalanx pose (MCP / PIP / DIP flex, spread about the palm normal):

| finger | flex (deg) | spread (deg) |
|---|---|---|
| index | 8 / 12 / 6 | +2 |
| middle | 8 / 12 / 6 | 0 |
| ring | 42 / 44 / 22 | -4 |
| little | 52 / 50 / 28 | -7 |

- Ring and little are curled down beside the shell's right side instead of fanned across the pad.
- They cannot curl into the shell: the page lifts the hand until every fingertip clears the shell by 8 mm (`overMouse`).

The numbers, measured in the page in mouse mode (desk_14 scene, `mouseprobe`):

| | wrist above the pad | lowest fingertip above the pad | index tip to mouse centre (xz) |
|---|---|---|---|
| main 95abd03 | 10.0 cm | 8.8 cm | 1.2 cm |
| c36173a (committed hands) | 8.1 cm | 2.8 cm | 3.0 cm |
| tightened grip | 8.7 cm | 2.9 cm | 2.9 cm |

**Correction to the earlier figure:** "wrist 1.3 cm above the pad" was measured before the palm-down hand orientation was added. With the palm resting on top of the ~4 cm shell, the wrist joint sits ~8 cm up. The fingertips are on the buttons in both.

`mouse_grip_tightened.jpg` shows the references on top, then c36173a vs the tightened grip, from three views: top-down, his right side, over his left shoulder.

## Mouse grip: contact instead of clearance (COORD: "he reads as resting his hand next to a mouse")
**What was wrong, measured in the page** (mouse mode, desk_14; `tools/motion/grip_probe.py`). The room's mouse shell is 11 cm long and 6.5 cm wide. Its top is 36 mm high at 2 cm behind its centre.
- **Palm not on the shell.** The palm (60% from wrist to middle knuckle) was 7.2 cm behind the mouse's centre. That is behind the shell's rear edge (−5.5 cm), and 7.9 cm above the pad.
- **Fingers floating.** The fingertips hung 2–3 cm over the buttons.
- **Two causes:**
  - The wrist pin aligned the clip's mouse point, not the hand's actual palm, with the room's mouse. Since the photo-referenced hand poses, that put the palm 5 cm short.
  - `overMouse` then lifted the whole hand until every fingertip and knuckle cleared the shell by 8–20 mm. The hand could never come down onto the shell.
- **Correction to the line above** ("the palm resting on top of the ~4 cm shell"): it was not. The palm was behind the shell.

**Fix: the page resolves the hand against the shell by contact** (`boy_mh.js`, mouse mode only; typing still uses `overMouse` while the hand passes the mouse).
- **Shell height map.** The shell's top is sampled once into a 2.5 mm height map in the mouse's own frame.
- **Mouse follows the clip.** The recorded hand still moves the mouse, as before.
- **Hand placed on the shell.** The wrist is then re-pinned so that:
  - The palm is centred 2.2 cm behind the top of the hump and 1.2 cm right of it. That is where the hand sits in mouse2: index and middle on the two buttons, ring and little on the right flank.
  - The palm rests on the shell: palm skin 16 mm below the bones' line.
  - No knuckle goes into it (11 mm).
- **Fingers laid down.** Each finger is laid down joint by joint (base, middle, end) onto whatever is under it, the shell or the pad, until it touches. The shell is the hard limit.
  - Clearance is checked along each phalanx and across its width, so the uphill side counts on the curved shell.
  - The fingertip is measured once off his skin and follows the end joint.
- **Thumb** along the left flank: tip 1.6 cm over the pad, 1 cm ahead of the palm.
- **Index and ring** set beside the middle finger, seen from above: index turned 3° in, ring parallel.
- **No build-up.** Every finger turn the page makes is undone the next frame unless the clip has rewritten that bone. The turns never add up between frames.

**Measured over 15 s of mouse mode, every 0.25 s** (`grip_contact.json`):

| | before (5f3bc7f) | now |
|---|---|---|
| Palm centre vs mouse | 7.2 cm behind centre, 7.9 cm up | on the hump (−4.3 cm), 5.6 cm up |
| Wrist above the pad | 8.6 cm | 5.6 cm |
| Fingertips over the shell | 2–3 cm | 1.0–1.3 cm, which is the 10 mm finger half-thickness: touching |
| Hand skin inside the shell | n/a | max 1.2 mm, median 0 |
| Hand skin below the pad | 0 | 0 |

**Still open:**
- **Palm hollow.** The palm's centre stays about 1.2 cm over the hump. The knuckle row sits on the shell (the 11 mm limit), so the palm arches over the hump instead of pressing into it.
- **Mouse size.** His hand is long for this 11 cm mouse, so the index and middle tips end right at the front edge.

`mouse_grip_contact.jpg` shows:
- **Top row:** the mouse2 reference beside our top-down over the mouse. The mouse is mostly hidden under the hand.
- **Middle row:** mouse1 beside the view from his left (palm on the shell, thumb on the flank).
- **Bottom row:** the view from his right.

## Mouse grip, second pass: the hand's SHAPE (owner: "not similar at all"; COORD: a flat plank laid on the mouse)
The first pass fixed where each finger sat, not what the hand was doing. The fingers were laid down until they touched, and on a low shell that made them straight. The back of the hand was flat.

**The prop came first.** `room_build/build_mouse.mjs` made an 11.8 × 6.2 × 3.6 cm mouse whose top fell to 62% of the hump at the nose (about 2.2 cm) and rounded off 22% at the sides: a low pebble a hand cannot curl over.
- Now 12.0 × 6.4 × 4.0 cm, with the nose at 70% of the hump and 14% side rounding. Same origin and footprint on the pad.
- The builder was re-run first with its old numbers and reproduced the shipped `mouse.glb` byte for byte.
- See `mouse_prop_before_after.jpg`.

**The pose, measured off the references.** In mouse2's top-down, the fingers' seen length is about 65% of the palm's. In mouse1, the knuckle row is a dome and the fingers bend at both joints over the front.
- Bends set absolutely in the hand's own frame (knuckle / middle / end joint):
  - index and middle: 30 / 45 / 25°;
  - ring: 38 / 52 / 28°;
  - little: 42 / 55 / 28°.
- Index turned 2° in, ring and little 2° and 5° out: the fingers lie together.
- A stronger set (35/55/30) matched the top-down length exactly (0.64 against 0.65) but stood up like a claw from the side. The softer set reads right from the side; its top-down length is 0.75 of the palm.
- **The dome.** The hand tilts about the wrist until the index and middle fingertips meet the shell, with the palm resting on the hump. The wrist ends 2.7 cm over the pad and the knuckles 5.7 cm. The hand is also rolled 12° thumb side up (a hand on a mouse is not flat palm-down).
- **The fingers are no longer laid down.** A finger is only opened if it would enter the shell.
- **The thumb** lies along the left flank, pointing forward: its tip about halfway along the mouse, the pad on the flank 1.6 cm over the pad. Its middle joint moves out and up until none of its skin is in the shell (up to 4 cm).

**Measured over 15 s** (`grip_contact.json`): hand skin into the shell median 1.4 mm, 90th percentile 6.8 mm, max 9 mm. Below the pad: 0.
- The deep values are the thumb's root (the thenar pad) pressing the left flank at moments, measured vertically. On a steep flank that is about 3–5 mm sideways.
- Not yet solved: tilting the hand to lift the heel diverged, and moving the palm back made a claw.

`mouse_grip_silhouette.jpg` shows mouse2 beside our top-down, mouse1 beside ours from behind-left above, ours from his left, and the new mouse alone.

### Third pass: the fingers drape (COORD: from his left, 30/45/25 still read as a claw)
- **Bends lowered at the middle and end joints, set absolutely:**
  - index and middle: 25 / 32 / 12°;
  - ring: 32 / 40 / 15°;
  - little: 36 / 45 / 18°.
- **Fingers together:** index turned 3° in, ring along the middle finger, little 2° out.
- **The arch** is left to the wrist tilt and the palm on the hump (wrist 2.7 cm, knuckles 5.7 cm over the pad).
- **Measured:** the fingers seen from above are 0.86 of the palm (mouse2: 0.65). This moved the wrong way, as expected, and is accepted: from the side they now lie along the shell.
- **Over 15 s:** median 1.0 mm into the shell, max 9.3 mm. The max is the thumb's root at the left flank (vertical depth), still open.
- **Pictures:** `mouse_grip_silhouette.jpg` now also has the view over his right shoulder (the owner's usual camera side).

### Fourth pass: the thumb (owner: "the thumb, if you can fix it")
**Measured first** (`thumb_contact.json`; 15 s of mouse mode). "Along" runs from −1 at the mouse's back to +1 at its front; the index finger's middle knuckle is at +0.30.

| | before (7772f12) | the capture's own thumb, unedited | now |
|---|---|---|---|
| Thumb line vs the mouse's long axis, from above | 44° | 14.5° | **15.9°** |
| Thumb tip along the mouse | −0.22 | +0.14 | **+0.07** (1.4 cm behind the index middle knuckle) |
| Thumb skin into the shell | max 5.9 mm | max 8.8 mm | **max 1.4 mm, median 1.3** (side gap 0: touching) |
| Triangles at the thumb's base over 2.5× bind | 20–38, worst 10× | 0 | **0** |

**Causes.**
1. **The tear was ours.** The old `thumbOnFlank` aimed the thumb's joints at a point on the flank and turned its root up to 45°. The capture already lays the thumb along the mouse; it was only about 8 mm too far into the shell.
2. **Why it never went away.** The clip holds the thumb still. three.js's mixer does not write a value that has not changed since its last write, so the mixer never put the thumb back after the page turned it. The page's undo only fired when the bone still matched exactly what the page had left. During the mode fade it was off by about 0.15°, so the undo skipped, and from then on the page's turn became the thumb's pose for good.

**Fix.**
- The thumb is now left as recorded: no thumb code at all.
- The hand rolls 25° thumb-side up instead of 12°. That lifts the thumb's side onto the flank. Scan: 12° gave 8.8 mm in, 18° 7.7, 24° 2.0, 25° 1.4, 26° 0.4, 30° 0 (hovering).
- The page's finger turns are undone unconditionally at the start of each step, before the mixer runs. They can no longer build up.

**Whole hand, 15 s:** skin into the shell max 1.7 mm, median 1.3 (was max 9.3). Below the pad: the thumb tip, max 1.7 mm into the mouse mat.

**Still over 2.5×:** 2 faces at the index knuckle (3 mm edges at 8.4 mm, 2.74×). They come from the accepted grip's index bend, not the thumb. They are there with the old code too, and they are gone with the page's hand solve off.

**Seen in the renders:** from his left, the thumb reads as one piece with the edge of the palm on the flank. The white disc by the keyboard in the new views is a desk object (it is still there with his body hidden); the forearm used to cover it.

`mouse_thumb_before_after.jpg`: reference | before | now. Views: from his left at mouse height (close), from his left, top-down, behind-left above, and over his right shoulder.
