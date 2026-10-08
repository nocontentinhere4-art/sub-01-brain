# The bed on the new room model: under the duvet, on the pillow, slides off

#108 put him under the duvet by lifting the room's own duvet mesh over him. #107 then replaced that mesh with a game
quality quilt: 17k triangles, its own loft and folds, lying folded over the foot half of the bed. Lifting *that* over him
made the shape the owner and G8 saw on live main:

1. a tent whose inside faces showed as a black hole, with hard dark ribs along the quilt's seams;
2. his feet, or the slides, poking out of it at the foot end;
3. before the duvet rose he was lying on top of it, diagonally;
4. his head off the pillow and pushed into the headboard and the wall.

(3) and (4) are the same cause: #108's measurements (the pillow at x −1.8…−1.4, the duvet's top at y 0.866, the mattress
as the duvet's own surface) were taken on the old model. On the new one the pillow sits at x −1.80…−1.36 and the
mattress top is 0.82 everywhere.

The generated duvet, his place on the pillow and the slides went in with #124. The follow-up (this branch) carries
G4's mesh fix (#119, `feature/gl-soft-fix`): the folded quilt as a closed slab with a rolled fold, the pillow lofted to
15 cm (top 0.95 m, centre −1.571, 0.867), the T-shirt moved off the bed. It also answers the review of #124 (a foot
showing at the foot end on his side, the foot end hanging in strands) and a regression #114 brought to the bed.
Everything below is measured on that model, with #114's motion layer running.

## What this changes (all in `web/room.html`)
- **The duvet over him is generated, not lifted.** `COV`: a 60 × 46 grid pulled up over him, as a closed shell — a top
  surface, an underside a duvet's thickness below it, joined at the rim, every normal outward. There is no inside to
  see, so no black hole, and no seam of the folded quilt to stretch into a rib. It uses the room duvet's own material
  (the same quilted texture and normal map, its AO dropped: that needs the model's own second UV set).
  - Its height is the top of whatever is under each point plus the duvet's loft, then smoothed three times so the cloth
    bridges between his limbs instead of shrink-wrapping them, and never less than 3 cm above him.
  - Over the sides of the mattress it falls freely. At the foot it stays up until just past his toes' tips — one
    straight line across the bed, measured from his toe bones — then hangs straight down 28 cm to a level hem, clear of
    the floor. (In #124 each row of the grid started falling where his toes ended in that row, which hung the end in
    pointed strands, and in his side pose a foot showed past it.)
  - While it is over him the room's folded quilt is hidden: he has picked it up. It is drawn up from the foot of the
    bed over the 2.2 s he takes to settle, so you see it come up, not appear.
- **He lies where the new pillow is.** `ANCHOR.bedlie` moves back 15 cm toward the foot (x −1.03): his head rests on the
  pillow (gap −0.3 cm), its centre 3.4 cm from the pillow's centre, and the back of his head stops 3 cm short of the
  curtain.
- **He is longer than the bed.** The mattress is 1.65 m and he is 1.72 m, so asleep his knees stay a little bent
  (`LIE.hip`, `LIE.bend`, lowered in the follow-up so the knee makes less of a hump), and the duvet hangs over his toes.
  Only the sleeping clip gets this; the phone and music clips lie with their own bent legs.
- **Turning over, he stays on the pillow** (`ROLL.zfix`): rolling about the length of the bed would carry his head 8 cm
  across it.
- **The slides come off before he lies down**, and a pair stands parked by the bed. Under the duvet his slides are
  hidden outright (their triangles left out). Lying on top of it with the phone or music, his feet show, and the model's
  socks have no sole of their own (the slide *is* the sole), so there the slides keep their shape and take the sock's
  white: a closed sock rather than an open shell (`after_phone_feet_h14.jpg`).
- **#114's motion layer kept his legs in the mattress as he lay down** (up to 1,908 vertices on main c88eade) and
  dragged him into the desk chair as he sat down (up to 228). Two guards in `web/room/boy_motion.js`, following G3's
  diagnosis: the pop killer (`smoothBones`) skips any step but the walk, and while he is on the bed; the foot layer
  (`feet`) skips any step but the walk, and while he is on the bed (lying or on its edge). The page's own keys move him
  there. The standing scenes are unchanged (G8's harness: bed 0, chair 0, nothing below the floor).
- **The page may open while he is already asleep:** then he is under the duvet from the first frame.
- `penetration()` now measures against the mattress top (0.82, the hard surface) rather than the duvet's: the duvet is
  soft goods and is above him, not under him.
- New in `contacts()` (debug): `wall`, his vertices past the curtain line, and `pillow`, how far his head's centre is
  from the pillow's centre.

## Evidence
From headless Chromium (SwiftShader WebGL), the page in `?debug&nolive`, its rAF loop frozen and stepped by the page's
own `sim()`. "before" is main at f1aa14a, "after" is this branch.

| | before | after |
|---|---|---|
| 02:00, default camera | `before_h2_1280.jpg`, `before_h2_390.jpg` | `after_h2_1280.jpg`, `after_h2_390.jpg` |
| 06:00, default camera | `before_h6_1280.jpg`, `before_h6_390.jpg` | `after_h6_1280.jpg`, `after_h6_390.jpg` |
| on his side, 02:00 | `before_side_h2_1280.jpg` | `after_side_room_h2_1280.jpg`, `after_side_wall_h2_1280.jpg` |
| turning over (mid-roll), 02:00 | | `after_roll_mid_h2_1280.jpg` |
| the foot end, on his side, 14:00 | | `after_foot_end_side_h14.jpg` |
| the phone in bed, his feet, 14:00 | | `after_phone_feet_h14.jpg` |
| the bed close up, 14:00 and 02:00 | `before_bedcam_h14.jpg`, `before_bedcam_h2.jpg` | `after_bedcam_h14.jpg`, `after_bedcam_h2.jpg` |

G8's own scenes, from `python -m tests.visual.harness`: `qa_closeup_bed_14.jpg`, `qa_closeup_night_23.jpg`,
`qa_closeup_side_14.jpg` (its defect #25 shots).

- **`penetration.txt`** — 0 bed, 0 chair and 0 wall vertices through a whole night (into bed, both turns, the phone and
  music on top of it, back to sleep, getting up from his side), 3 seeds, every vertex every 0.25 s. His head's centre
  stays within 5.0 cm of the pillow's centre asleep, through both turns (7.7 cm is the phone-in-bed clip, which props
  his head up); on his side his head rests on the pillow (gaps −1.4 and +1.4 cm).
  In the chained sweep of every activity the bed and the desk transitions are clean (0–3 chair vertices, as before
  #114). Two hits remain, exactly as on main c88eade: his leg through the bed frame as #114's walk clip carries him from
  the window past the bed's corner (1,698 vertices for one frame), and his hand in the chair's back in the stretch
  beside the desk (160–272). Those are #114's clips, reported to G3.
- **`perf.txt`** — mid phone profile (390 × 844, DPR 2, CPU ×4): asleep 2.6–3.3 ms of script per frame against main's
  2.1 ms, within the 33 ms a 30 FPS frame has. The cover is reshaped at 10 Hz while he lies still.
- **Tests** (local: GitHub Actions is down at the account level) — `pytest tests --ignore=tests/visual`: 1156 passed,
  27 skipped (`tests/test_boy_motion.py` included). `pytest tests/visual`: 5 passed. `python -m tests.visual.harness`:
  0 hard failures (bed 0, chair 0 in every scene).
