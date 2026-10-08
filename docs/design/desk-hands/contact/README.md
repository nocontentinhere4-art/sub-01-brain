# Contact: his hands settle onto the mouse and the keys instead of being kept clear of them

## The defect
Every desk rule in the page only ever pushed his hand out of things:
- On the mouse, the clearance lift (`overMouse`, 8–20 mm) left the hand hovering. The wrist pin also aimed the clip's reference point, not the hand, which put the palm 7 cm behind the mouse's centre.
- On the keys, the tip floor (`lowestTip`: bone heads minus 8 mm over the caps +3 mm) guaranteed a hover, because his fingertip skin is 10–11 mm thick. G12 measured 0.5–1.1 cm over the caps for a whole clip on main.
- On this branch the photo-referenced hand poses also put the typing fingertips 12 cm ahead of the home row, past the keyboard's far edge, with the wrists 11 cm over the keys.

A hovering limb penetrates nothing, so every test passed.

## The resolver (`web/room/boy_mh.js`, the "contact" block)
One resolver, two callers: the mouse (right hand) and the keys (left hand always at the desk, right hand while typing). Each frame, for each hand:
1. **Carried.** The recorded wrist is carried to the room's object by the existing clip-to-room offset. The clip's motion stays the clip's.
2. **Placed by a point of the hand itself:**
   - Mouse: the palm (60% from wrist to middle knuckle) goes 2.2 cm behind and 1.2 cm right of the shell's top. That is mouse2's hand position: index and middle on the buttons, ring and little on the right flank. The mouse still follows the recorded hand.
   - Keys: the index fingertips, measured off his skin, are centred over F and J. This is a slow correction (~1 s), so the typing motion stays the clip's.
3. **Settled vertically:**
   - Mouse: the palm rests on the shell (palm skin 16 mm below the bones' line).
   - Keys: the knuckles sit 3 cm over the caps under them.
   - Both: no knuckle comes closer than its skin (11 mm).
4. **Whole arm.** The arm turns to get the wrist there (upper arm at the shoulder, forearm at the elbow); the wrist keeps the clip's turn. If the arm's skin (sleeve included, on its twist bones) is in the desk, the elbow swings up about the shoulder–wrist line until it is out, at most 15°.
5. **Fingers onto the surface.** Each finger is bent joint by joint: from straightest, in steps, down to the first touch, then refined. The surface is the hard limit.
   - The first phalanx is tested by its bone line with a 10 mm half-thickness. The middle and end phalanges are tested by their own skinned vertices.
   - Each surface is a 2.5 mm height map of its top (the mouse shell, the keycaps); off the surface it is the pad.
   - Mouse: the thumb lies along the shell's left flank; index and ring are set beside the middle finger.
   - Keys: the thumb is laid like the fingers, onto the space bar. The bend is followed over 0.4 s, so a real clip's quick keystrokes survive, but a finger is never bent further than the touch.
   - If a finger is still in a key when fully straightened, the hand rises by that much on the next frame.
6. **No build-up.** The page's finger turns are undone the next frame unless the clip has rewritten that bone, so they never add up.

**The desk.** The room draws the desk as a single 3 mm skin (`room_static_13`, top 0.970–0.973 m, front edge z ≈ −0.845). The resolver treats the 3 cm under that top as solid.
- **Finding:** the page QA's desk test (`page_checks.js`, inside-intervals with 1 cm margins) cannot see anything inside a 3 mm skin. An arm through the desk top can never fail it. That is why the forearm-through-the-edge G12 saw passed every test. Not fixed here (it is the QA's); reported.

## Measured
All measurements are in the page, scene desk_14, every 0.25 s.

**Mouse, 15 s** (`mouse_contact.json`):

| Measure | Value |
|---|---|
| Hand skin into the shell | max 1.3 mm, median 0 |
| Below the pad | ≤ 0.1 mm |
| Wrist above the pad | 5.6 cm (was 8.6) |

**Keys, 15 s, ten fingertips** (`key_contact.json`; skin over the cap under it, per distal phalanx):

| | min | median | max |
|---|---|---|---|
| all fingers | −4.4 mm | −0.1 mm | +8.2 mm |

- 97% of samples are within ±3 mm. A real key travels about 4 mm.
- Before: hovering 0.5–1.1 cm on main (G12). On this branch before the fix, the fingertips were not over the keyboard at all.

**Arm against the desk** (skin of the arm and sleeve):
- After the resolve: 0 mm in both modes.
- Before the swing: up to 13 mm when a mode starts. The swing engaged on 11 frames typing and 5 mousing, at most 12.6°.
- Check of the check: with the desk slab raised 4 cm as a test, the swing engages on most frames and stops at its 15° cap. Up to 12.8 mm then stays in, held as contact rather than hoisting the shoulder.

**Visual suite:** see the commit message.

## Pictures
- `../hands/mouse_grip_contact.jpg`: the mouse against mouse1 and mouse2.
- `keys_and_arms.jpg`:
  - Top row: references kb1 and kb2.
  - Middle row: our top-down over the keyboard, and from his left at key height.
  - Bottom row: typing and mousing from his right, with the arms out of the desk and the elbows natural. An earlier version swung the elbow up to 20° on a too-fat arm model and hunched the shoulder; that is why the swing is now skin-tested and capped.

## Open
- **G12's typing clip.** Needs the clip's keyboard reference point (where the performer's home row was) to replace the clip-to-room offset in step 1. The resolver does the rest.
- **The QA's desk test** cannot see this desk (above).
- **Right little finger.** On our current static-finger typing clip it lifts up to 8 mm at moments.

## The keys with a real typing capture (room_mx_typing, G12)
Typing mode now plays G12's Mixamo capture, with the hands settled by the same resolver.

**Placement.** The resolver takes G12's measured reference points (the left and right index fingers' last joints, means over the clip).
- Each is moved 1.5 cm on to the fingertip and 1 cm down to the key top.
- Each hand's mean is carried onto our F and J. Each keeps its own motion about that mean, so the right hand still travels its 13.6 cm.
- A rigid map of the performer's keyboard plane was tried first. The performer's hands sat 18 cm apart, which put the left little finger off our narrower keyboard, so it was dropped.

**Hand height.** It comes from the capture itself: the drop from the knuckles to the resting fingertips' skin, followed over ~1 s. The resting fingers then touch as recorded.
- It reads 6 cm on both hands, which is the clamp's limit.
- It is held over the highest surface under any knuckle, so a hand half off the keyboard is not lowered.

**Keystrokes survive.** A finger counts as in a stroke while the capture's fingertip is more than 8 mm above its lowest over the last 1.5 s (G12's lifts: median 0.4 s, longest 1.6 s).
- In a stroke the finger is left as recorded and only opened out of a key.
- Once down, it is settled onto the cap over 0.15 s.

**Measured over the whole 16.5 s, every 0.25 s** (`key_contact_mx_typing.json`):

| | value |
|---|---|
| All fingertips | median 0.0 mm, min −5.4 mm, max +28.7 mm |
| Resting fingers | median −0.1 mm, 86% within ±3 mm, 1 sample more than 5 mm into a cap |
| Fingers in a stroke | median +6.8 mm up; 32 of 57 kept more than 6 mm up |
| Arm skin in the desk | 0; the elbow swings up to 14° |
| Chair and desk (page QA) | 0 |
| Baseline: main | hovering 0.5–1.1 cm, touching in 0 of 180 frames (G12) |
| Baseline: unfitted | 10.4–19.5 cm under the caps (G12) |

**Open:**
- **Strokes:** 25 of 57 stroke samples still read under 6 mm.
- **Resting fingers:** 37 resting samples are more than 5 mm up, probably small lifts under the 8 mm threshold.
- **Elbow swing** fires on most frames (up to 14.4° against the 15° cap) to keep the sleeve out of the desk.
- **Hand height** is clamped at 6 cm on both hands, so the capture's real knuckle drop may be larger.

### Typing capture, second pass (COORD's three open items)
1. **The hand-height clamp.** The capture's knuckle-to-resting-fingertip drop is steady, not out of range: left median 6.1 cm (5.4–6.6), right 6.6 cm (5.5–6.8). The knuckle, surface and units all check.
   - The 6 cm ceiling was simply set too low. It cut 1–8 mm off, which pressed the resting fingers into the caps and ate the strokes' lift.
   - Now bounded at a finger's length (9 cm). Clamped on 0% of frames on both hands.
2. **The −5.4 mm fingertip** was the right index at 9.25 s, at the keyboard's right end, while the capture's hand travelled. Two causes:
   - The height map's nearest cell could read the lower level next to a keycap's side step. The lookup now takes the highest of the cell and its 8 neighbours.
   - The hand-raise for a finger still in a key, even straightened, acted only on the next frame. It now raises the hand and re-solves the fingers in the same frame, twice at most.
   - The skin samples per phalanx are now chosen pad and tip first.
   - Deepest now −1.3 mm. 0 samples more than 2 mm into a cap.
3. **The elbow.** "14.4° on most frames" was my own misreading: the counter counted calls (several per frame, both hands, since page start), not frames. Per frame over the clip:
   - left: never engaged;
   - right: 1.2% of frames;
   - median and 90th percentile 0°; max 14.9° (the cap), on those few frames.

**Measured now over the whole 16.5 s, every 0.25 s** (`key_contact_mx_typing.json`):

| | value |
|---|---|
| All fingertips | median +1.1 mm, min −1.3 mm |
| Resting fingers | median +0.9 mm; 66% in the 0 to +2 mm band, 76% within ±3 mm; 0 more than 2 mm in |
| Fingers in a stroke | median +9.3 mm up; 35 of 57 kept more than 6 mm up |

- **Resting fingers more than 5 mm up:** 15% of resting samples. Of these:
  - 37 are over a gap, edge or frame, where the probe measures to the plate under the fingertip (an artifact of the measure);
  - 47 (8% of resting samples) are over a cap top. These are probably the capture's small finger moves under the 8 mm stroke threshold.

**Sheet:** `typing_capture_sheet.jpg` has four frames over his right shoulder, 4 s apart, and both hands from his left at key height.

### Typing capture, third pass: the hands crossed (owner: "on the keyboard the hands cross")
**Measured per frame over the whole clip, in the keyboard's frame** (`typing_hand_separation.json`, `typing_hand_separation.png`):

| | wrists, right minus left | inner edges (index knuckles) |
|---|---|---|
| The capture alone (resolver off) | min 14.8 cm, 0 frames negative | min 6.0 cm, 0 negative (112 frames under 8 cm) |
| Before (8fd5c5f) | median −0.4 cm, 256 of 495 frames negative, worst −5.6 cm at 10.23 s | 284 frames negative |
| Now | min 14.7 cm, median 19.4 cm, 0 frames negative | min 5.9 cm, median 10.9 cm, 0 negative (135 under 8 cm) |

So the crossing was ours, not the capture's.

**Cause 1: not a mirrored axis.** The F / J points in the page's frame match the capture's own mean index joints to within 1 cm. The cause was **a stale correction**: the slow F / J pull on the left hand, built up in mouse mode (where it brings the seated body's left hand from the knee), was never reset and was added to the typing hands at +10.3 cm. There is now one correction per context (mousing, typing), never carried from one into the other. The capture's typing uses none.

**Cause 2: the F / J anchoring** (COORD's second suspect). Carrying each hand's mean onto its own key took the performer's 18 cm spacing down to F–J's 5.7 cm and laid the inner edges over each other. Now both hands share one carry, so the capture keeps its own spacing. The pair is centred 4.5 cm to his right of the F / J middle (`MX_SHIFT`), so the left little finger stays over the keys (its knuckle at −12.6 cm, the keyboard edge at −13.8). No clamp holds the hands apart.

**Contact after the fix (16.5 s):**
- Resting fingertips: median +0.5 mm, 81% in the 0 to +2 mm band, 0 more than 2 mm in, deepest −0.9 mm.
- Strokes: median +8.7 mm, 37 of 60 kept more than 6 mm up.

**Pictures:** `typing_front_views_fixed.jpg` is the same front view (monitor hidden in that render only) at t = 3/7/11/15 s. At 11 s the right hand is away to his right, off the keys toward the mouse: the capture's own travel.

**Open:** the inner edges come within 8 cm on 135 frames. The capture itself does so on 112.
