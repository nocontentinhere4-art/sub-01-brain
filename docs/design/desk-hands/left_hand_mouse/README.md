# Mouse mode: the left hand rests on the keys

**The defect** (G12's measurement): in mouse mode the left hand rested on nothing. No key was under its fingertips. The
contract says it must touch something: keyboard, desk or thigh.

## Fix (`web/room/boy_mh.js`)
While he mouses, the left hand runs the owner's typing take (`ownerKeys(side, w, dt, {rest: true})`; see
`../typing_owner/`), at rest:
- **Slow.** A fifth of the typing's pace (`OT_REST`): his 8.1 s loop takes 40 s, a slow drift rather than a frozen hand.
- **No strokes.** Every finger is settled on its cap by its knuckle bend (±12°, never bent back past 5°). The take's
  hand turn, spread and curl are kept.
- **On the keyboard's left half.** His index fingertip's track is centred on F, with a third of its travel (`OT_DRIFT`).
  - His own place is 3.5 cm left of the F/J middle, and he travels 8 cm through the take. On our keyboard, whose left
    edge is 13.3 cm from the middle, that put the little finger off the edge at moments (up to 2 cm over the frame).
  - Now his index tip moves between −3.8 and −1.2 cm along the keys (F is −2.85).
- **Thumb.** It keeps a 1.5 mm margin over the height map. On the mesh it read up to 3.5 mm into the space bar without
  that margin: the height map misses steep keycap sides, as G12 found on the mouse.

The right hand, the mouse path and the typing are unchanged. With `rest` off and the margin 0, `ownerKeys` and
`otSettle` do exactly what they did.

## Measured (`left_hand_contact.json`; desk_14, mouse mode, 128 samples over 32 s)
Contact is measured on the keyboard's mesh: double-sided faces, inside = odd crossings of a ray straight up, depth =
nearest face. Self-check on every sample: −2.0 / +3.0 mm.

| | value |
|---|---|
| Fingertips (index to little) over the cap | median +1.1 mm, 87% in 0..+2 mm, 94% within ±3, deepest −0.5, none >2 mm in |
| Fingertips >5 mm up | 4 of 509 (index up to 9 mm, middle 5 mm) |
| Per finger, median / max | index 1.2 / 9.0, middle 1.1 / 5.0, ring 1.1 / 2.4, little 1.4 / 4.3 mm |
| Thumb | median +3.3 mm, lowest +0.5 (just over the space bar) |
| Deepest vertex of the left hand inside the keyboard | 0.5 mm |
| Before (G12) | no key under the fingertips |

**Open:** on 3 samples the probe found nothing under the index tip, so they are left out of the table above.

## Pictures
`left_hand_mouse.jpg`:
- **Top row:** the page's desk camera (the follow camera, at the owner's distance) at t = 6 / 14 / 22 / 30 s. From there
  his body hides the left hand.
- **Bottom row:** close-ups of the left hand, from in front-left and from his left, at two moments of the drift.
