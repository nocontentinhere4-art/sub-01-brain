# Contact: what has to touch what

Written 2026-10-06 by the coordinator, after four separate floating-body defects were found on `main` in one
afternoon by three different people. It is the acceptance contract for every pose and every clip. The gate measures
against this file; clip work is judged against this file.

## Why this exists

Every check we had asked one question: **is any part of him inside something?** `budgets.json` is four counters of
"sampled skinned vertices inside that surface". `floorLift` and the mattress lift only ever push him **up** out of a
surface. `pin()` lifts the hand until the lowest fingertip clears the keycaps. The camera test forbids seeing inside
him.

Nothing anywhere asked the opposite question: **is he touching what he is supposed to be touching?**

A body that floats penetrates nothing, so it passed everything. What that cost us, all live on `main` on
2026-10-06 and none of it caught by the suite:

| what | measured | found by |
|---|---|---|
| both feet off the floor, seated at the desk | 5–14 cm, the whole clip | G12 |
| fingertips over the keycaps, typing | 0.5–1.1 cm, never touching, the whole clip | G12 |
| right hand beside the mouse instead of on it | palm 7.2 cm behind the mouse centre, wrist 8.6 cm up | G14 |
| back off the mattress, lying in bed | visible gap in every rendered view | coordinator, from G10d's sheet |

The typing hover was not even unknown: `defects.md` item 27 recorded "both hands float 3–5 cm above the keys" days
ago. It was written down, routed, and shipped anyway, because nothing failed when it was true.

One cause, not four: **we built the half of the system that rejects penetration and never built the half that
requires contact.** The keyboard rule is the clearest proof that this was arithmetic, not bad luck — `pin()` lifts
the hand until the lowest fingertip **bone** is 8 mm above the caps +3 mm, and fingertip skin is 10–11 mm thick, so
contact was impossible by construction. Nobody mistuned it. It could never have worked.

## The contract

For each pose: what must be **touching**, and what must stay **out**. Contact means the skin is within the tolerance
of the surface — neither further away nor further inside.

Tolerances are per surface because the surfaces differ: a cushion and a mattress compress under load, a desk top and
a keycap do not.

### Seated at the desk — all three modes (type, mouse, watch)

| part | surface | must |
|---|---|---|
| both soles | floor | touch, 0 to +1 cm (he is in slides: the sole sits on the slide, the slide on the floor) |
| buttocks and back of thighs | seat cushion | touch, −2.5 to +0.5 cm (the cushion gives) |
| back | backrest | touch in `watch`, where he leans back; free in `type` and `mouse` |
| right hand | mouse shell, in `mouse` | palm on the shell, fingertips on the buttons, skin into the shell ≤ 2 mm |
| both hands' fingertips | keycaps, in `type` | touch, 0 to +2 mm, through the whole clip, not at one frame |
| left hand | keyboard, desk or thigh, in `mouse` | touch **something**; resting on nothing is a defect |
| forearms | desk front edge | out, 0 vertices inside |
| any part | desk top, chair frame, the chair's arm pads | out, 0 vertices inside |

### Lying in bed — awake, with music, and asleep

| part | surface | must |
|---|---|---|
| back, hips, shoulders | mattress (or the quilt folded under him) | touch, −1 to +0.5 cm |
| head | pillow | touch, −2 to 0 cm (the pillow gives more than the mattress) |
| feet | within the mattress, not past its end | inside its length |
| whole body | headboard and bed frame | out, 0 vertices inside |
| duvet, where it covers him | his skin | follow his shape; no gap reading as a balloon over him |

### Standing — at the door, the window, walking

| part | surface | must |
|---|---|---|
| the supporting sole | floor | touch, 0 to +1 cm, on the foot bearing weight at that frame |
| any part | wall, sill, furniture | out, 0 vertices inside |

## How it is measured

Three rules, each of which one of today's defects would have broken:

1. **Every mode.** `test_visual` checked a single frame of **mouse** mode only, which is why watch mode could carry
   3713 chair contacts over 8 s and still be green.
2. **Every frame of the clip, not one sample.** A pose can be right at frame 0 and wrong for the rest of the loop.
   Report the worst frame, not the average.
3. **Every solid in the room**, not a named list of two per pose. The headboard intersection survived because the
   bed's check knew only the mattress plane and the duvet.

And the gate reports **both signs**: how far inside, and how far away. A gap at a surface that the table above says
must be touched is a failure of the same weight as a penetration.

Two more, learned the hard way on the same day:

4. **Measure contact where the contact is supposed to be, not at the body's lowest point.** The bed probe said "back
   and hips 1–3 mm over the quilt" while the render showed open air under his spine. G10d found why: the slice took
   each 10 cm bin's single *lowest* vertex — the buttocks or the heels. As long as any one part of him touches, a
   lowest-point measure reports contact, so it is structurally blind to a gap under the back. Contact for a lying back
   is measured along the spine; for a seated back, against the backrest; for a hand, at the palm and fingertips.
5. **A number that changes between runs on the same code is not a measurement.** `desk_14`'s chair count read 6 on
   one run and 14 on the next. It measured whichever frame the scene stopped on, and how far the clip had run by then
   depended on how long the page took to load. The sweep (`qa.bodySweep`) steps a fixed span at a fixed rate and
   keeps the worst frame, so the same code gives the same number.

And one about tests in general: three of our gates measured nothing they claimed to. The chair count tracked load
time. `test_boy_mh` asserted `set(have) <= set(CLIPS)`, which can never fail on a missing required clip. The bed
probe sampled the lowest point. When a test is changed to make it pass, the report says what the test no longer
catches — and a fix to a test is proven by breaking the thing it guards and watching it fail.

## Status

The table is the target, not a description of today. As of 2026-10-06 `main` fails it in the four rows listed at
the top, plus the mouse-mode `desk_14` chair contact (6 sampled vertices, budget 0 — a hard failure on live `main`,
repeatedly reported as "accepted", which it never was).

The seated rows are being fixed by replacement rather than by patching: the hand-built seated poses are being
replaced with retargeted motion capture, and the patches that propped them up (the leg swap when a watch clip's
ankles start above 0.12 m, the roll distances tuned to the old poses) go with them.

**`sleeping_side` measures nothing on v5.** Found by G10d: the turn onto his side (`rollStep()`, applied in
`lieFit()`) runs only on the old rig's per-frame path. With v5, `boy_mh.js` drives him, neither function runs, and
`ROLL.a` stays 0 however long the scene plays. So the scene renders him on his back exactly like `sleeping`, and a pass
there says nothing about lying on his side. Live has no side-lying sleep at all. The old roll is hand-set angles on the
hips, knees, spine and arms, so it is not being ported. The side pose comes from a capture on the Mixamo rig, and the
duvet drape is measured on it then. Until that lands, read `sleeping_side` as a second `sleeping`.

## The auto-rigged character (G20, preview/mixamo-pipeline): what can be measured before the page plays it

`web/room/char_mixamo.glb` is v5 put on the Mixamo Standard Skeleton by `room_build/rig/autorig.sh` (no mixamo.com).
The page does not load it yet, so the room rows above cannot be measured on it. What can be, is, by
`room_build/rig/autorig/qa.mjs` on the skinned mesh itself, every 0.1 s of each clip, in the clip's own frame (the
performer's floor at y = 0; the performer's bed and chair are not in the capture). 2026-10-07, on v5 from main:

| check | Seated_Idle (4.2 s) | Typing (16.5 s) | Laying_Sleeping (1.7 s) |
|---|---|---|---|
| soles vs the floor (lowest sole skin) | L −0.6…−0.5, R −1.0 cm | L −1.4…−0.9, R −2.1…−1.7 cm | (lying) |
| hands in his thighs | 0 frames | 0 frames | **18/18 frames, 2.2 cm** (hands resting on the stomach / hips, see below) |
| arm in torso | 42/42 frames, ≤ 2.4 cm (≤ 532 verts) | 165/165, ≤ 2.3 cm | 18/18, ≤ 2.5 cm |
| leg in the other leg | 42/42, ≤ 1.2 cm (≤ 37 verts) | 165/165, ≤ 1.5 cm | 18/18, ≤ 1.3 cm |
| lying: each part's lowest skin over the lowest skin of the whole clip | — | — | back 0…0.3, head 2.1…3.3, shoulders 2.9…3.5, thighs 4.5…4.7, hips 8.3…8.4, heels 10.4 cm |

Baselines, same instrument: in the T-pose rest 0–2 vertices of any pair are inside (≤ 0.8 cm); with the arms rotated
down to v5's modelled pose, arm in torso is 8–15 vertices at ≤ 1.2 cm.

Read it as:
- **The soles are 0.5–2.1 cm under the floor seated.** His shin is longer and his thigh shorter than the performer's
  in proportion (0.41 / 0.37 m against 0.39 / 0.39 at his scale), and the clip's hips are scaled by hip height, so a
  seated foot lands lower. Against the contract (0…+1 cm) that fails until the page plants him; the page's seated fit
  is re-derived on this rig anyway (rig-change checklist).
- **Arm in torso, seated and lying (2.3–2.5 cm, hundreds of vertices):** the hoodie's sleeve folding into its body at
  the armpit when the arms come down from the T-pose; with the arms down at rest it is 8–15 vertices. A real
  deformation defect, small in depth and not visible in the sheet (`docs/design/mixamo/autorig_v5_sheet.jpg`); it is
  the first thing to improve in the weights (the underarm fabric should follow the torso more).
- **Lying is not flat on one plane:** the upper back touches, the hips are 8 cm and the heels 10 cm up. The capture's
  pelvis and legs are raised relative to the back, and this hoodie is thick at the back. Per rule 4 this is per
  region, not one lowest point; the bed fit must hold the back and the hips, not just the lowest skin.
- The lying "hands in thighs" is the capsule-free version of the old instrument (a hand vertex behind the nearest thigh
  vertex's normal): his hands rest on his stomach and hip, and the baggy trousers come up to them.
