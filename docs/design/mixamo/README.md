# Mixamo (and, next, CMU) clips on v5

## Sources and licences

Mixamo clips (mixamo.com, Adobe) are used under Mixamo's terms. They are royalty-free, including commercial use, but the raw animation files may not be redistributed on their own.
- The raw FBX files stay in scratch and are never committed by this pipeline.
- Only the clips retargeted onto v5 and baked are committed (`web/room/mh_v5/*.glb`).

CMU motion capture: data obtained from mocap.cs.cmu.edu. It is free for research and for inclusion in commercial products, but may not be resold, even converted. The same rule applies: the raw BVH stays out of git.

## Pipeline: one path for every source

- `room_build/kimodo/mixamo_src.mjs` reads a Mixamo FBX (Binary, Without Skin) and writes a source in the MakeHuman clips' conventions:
  - MakeHuman bone names, with the finger chains mapped onto v5's `finger1..5-1..3`
  - the rest pose made world-aligned
  - metres, facing +Z
- `room_build/kimodo/mh_retarget.mjs` is the shared retarget (G14's, extended). It applies:
  - the bone map, rest alignment and wrist/ankle IK
  - `{"scale":"hip"}`: scale by the hip joints' rest height over the ankles
  - `pitch`: the torso tipped forward off a backrest
- `room_build/kimodo_g12/post.py` fits a seated clip onto OUR chair:
  - the hips' joint at `seatHipY` over the floor
  - `seatForward`, so the knees clear the cushion's front edge
  - the soles `soleUp` over the floor (the slides under his socks)
  - resting hands `handUp` off his thighs
  - the feet planted by leg IK
- `room_build/kimodo/mixamo_clips.json` holds one row per clip (the fit is data). `room_build/kimodo/mixamo_build.sh <Clip> <work dir>` builds it.
- `room_build/kimodo/contact_pass.mjs` runs over the whole clip in the room (room.html?debug), every frame, every 2nd skin vertex. It checks the chair, the seat cushion, the desk and nearby furniture, the floor (each sole's gap to what supports it), the bed, and his hands and fingers against his own thighs. Results are reported per body region.

## Seated_Idle: the first clip end to end

The clip is `web/room/mh_v5/room_seated_idle.glb`: 4.17 s, 126 frames, 79 joints including the fingers. The page does not load it yet; wiring it is the page's (G10d's) part.

Contact pass, 8.3 s (two loops), in the desk slot, against our chair, desk and bed and his legs:

| region | before: main's seated idle (desk_watch) | after: Mixamo Seated_Idle |
|---|---|---|
| chair (inside) | legs 1.8 cm (18 verts) | legs 2.5 cm (241 verts) |
| seat (thighs/buttocks vs cushion top) | lowest gap -0.8…4.2 cm | lowest gap -2…2.7 cm |
| desk | hands 1.5 cm (41 verts); arms 1.5 cm (15 verts) | clear |
| other furniture | arms 1.5 cm (101 verts); hands 1.5 cm (24 verts) | clear |
| floor | clear | clear |
| bed | clear | clear |
| soles over the floor | L 9.1…13.9, R 5.3…10.4 cm | L 0.1…4.8, R -0.2…4.5 cm |
| hands in his thighs | 0 verts, 0 cm | 0 verts, 0 cm |

- The remaining seat and chair numbers are his thighs settling up to 2–2.5 cm into the cushion (light cushion give).
- The backrest, desk, floor and bed are clear.
- His hands are clear of his thighs over the whole clip.
- His hands rest where the performer's did. The performer's armrests are at our armrests' height and spacing (about 0.69 m and ±0.30 m against our 0.67 m and ±0.30 m), so the hands come down onto the armrests and knees rather than into the legs.

Fit for our chair, measured in the room rather than guessed:
- the hips' joint 0.68 m over the floor, where main's seated poses put it (0.677)
- forward 4.5 cm off the backrest, with the knees beyond the cushion's front edge
- the spine tipped forward 10°
- the soles 2.7 cm up for the slides
- resting hands 1.2 cm off the thighs

Sheets:
- `seated_idle_room_before_after.jpg` (the page's camera)
- `seated_idle_side_back_before_after.jpg` (beside and behind the chair)

Before: main's seated idle, feet hovering 5–14 cm. After: on the seat, feet on the floor, hands on the armrests and knees.

## A note for the page's wiring

`boy_mh.js` swaps in the mouse clip's legs when the watch clip's feet start more than 0.12 m up. Seated_Idle's ankles sit 2.7 cm higher for the slides, which trips that test. So the test here plays it with that swap off, and the wiring should do the same for these clips (or give them their own slot).

## The bed set: what the three captures are, and how they sit on our bed

The page does not place a lying clip by its own pose. It turns and moves him by a reference pose (asleep: `room_bedtime`'s end; lying awake: `room_bed_lie`'s end). So `room_build/kimodo_g12/bed_fit.py` does two things for each clip:
- puts the clip's hips and heading on the reference's;
- holds his lowest skin at the reference's level in every frame, so the page's once-a-second lift never steps (he turns over in Sleeping_Idle).

All three clips loop on their own: the first and last frames match within 1.3°.

| clip (out) | what it actually is | bed penetration | hands in his thighs | feet vs the mattress end (x −0.21) | notes |
|---|---|---|---|---|---|
| Sleeping_Idle → `room_sleeping_idle.glb` | 17.6 s; curled on his side; turns over and back (head 85°, arms 100°) | 0 (whole clip) | 0 | inside (−0.27…−0.37) | the turns carry his head 33 cm off the pillow, and the duvet balloons over the moving arms (`sleeping_idle_room.jpg`) |
| Laying_Sleeping → `room_laying_sleeping.glb` | 1.7 s loop; on his back, breathing (spine/neck 3–4°) | 0 | 0 | **12–18 cm past** (−0.09 / −0.03) | head on the pillow, hands on his chest under the duvet |
| Laying_Nodding → `room_laying_nodding.glb` | 1.43 s loop; on his back, hands clasped on his chest, a 5° nod | 0 | 0 | **12–18 cm past** | for lying awake (`laying_sleeping_nodding_room.jpg`) |

He is 1.75 m and the mattress is 1.65 m, so a straight-legged lying capture overhangs its end whatever the retarget does.

Decisions (COORD A):
- **The mattress gets longer** (a real single bed, about 1.90–1.95 m). That is the room's fix and G10d's. Until it lands, the overhang stays as it is, named here and not patched. The captured legs are not bent to hide it.
- **Laying_Sleeping is the sleep loop.** On his back, breathing, head on the pillow, hands on his chest.
- **Sleeping_Idle is a rare night event**, not the base. It is in the same family as Scared, Angry_Gesture and Standing_Clap: it fires occasionally and never twice close together. Its acceptance criteria when it is wired: his head does not leave the pillow by 33 cm; his arm does not come up out of the covers; the duvet follows the turn instead of ballooning. If the duvet cannot follow a 100° arm sweep and an 85° head turn, the event is cut.
- **The hands are answered by the captures alone.** In Laying_Sleeping and Laying_Nodding his hands rest on his chest, not dead at his sides. No hand motion is invented anywhere (the hand clip was rejected).

## The desk transitions

Built with the seated fit (`web/room/mh_v5/room_mx_*.glb`). The hip lift reaches 0.27–0.29 m because the performer's chair is lower (his hips at 0.41 m); the cap is an option, set to 0.45 m.

### Stand_To_Sit and Sit_To_Stand in the page's sit-down and stand-up steps

Measured in the page's own steps: `room_sit_down` / `room_stand_up` served as these clips, `contact_pass.mjs <port> "window>research" 4` (sit down) and `"research>window" 4` (stand up), sampled from the moment the page's pose step begins.

| region | sit down: main | sit down: Stand_To_Sit | stand up: main (`room_stand_up`) | stand up: Sit_To_Stand |
|---|---|---|---|---|
| chair (inside) | legs 2.9 cm (155 verts); hands 1.3 cm | legs 3.3 cm (1182 verts, as he lands); arms 1.1 cm (2 verts) | legs 4.1 cm (769); feet 3.8 cm | legs 3.4 cm (809) |
| seat (thighs/buttocks vs cushion top) | -1.5 cm lowest | -2.9 cm lowest (as he lands) | -4.7 cm | -2.5 cm |
| desk | hands 1.5 cm (2 frames) | hands 1.5 cm (6 frames), arms 1.5 cm (3 frames) | clear | clear |
| soles over the floor | L -0.2…9.3, R -0.2…5.8 cm | L -0.2…9.4, R -0.2…5.9 cm | L **-2.1**…13.2, R -0.2…9.7 cm | L -0.2…10.6, R -0.2…7.4 cm |
| hands vs his thighs | 61 frames, 11 cm | 45 frames, 13.4 cm | 62 frames, 9 cm | 112 frames, 14.7 cm |

- The soles' maxima are the steps (a foot lifted while he turns into the chair), not hovering.
- "Hands vs his thighs" in a transition is his hands on his thighs as he lowers or pushes himself (the performers of both main's clip and Mixamo's do it). The capsule is measured from his baggy trousers (radius up to 16 cm), so a fist resting on the cloth reads as deep. The close-ups show the fist on the trousers, not in the leg. This row is only a hard gate for the seated loops.

Three fixes, all in the build, all data or general rules:
- **The cushion stops him.** Mixamo's performer drops onto a lower seat, so he dipped 2.4 cm under his seated height as he landed (seat -3.8 cm), and in Sit_To_Stand the hips sank while he leaned forward to rise. post.py now holds the hips at no lower than the seat height whenever they are over the seat. That was keyed to the hips' position, not to "seated" by head height, because the performer's head is low while he bends forward to sit or rise. The lift is not spread early, so the descent is not held up before he lands. Seated_Idle rebuilds byte for byte.
- **`seatOrigin`** (row option): the page places these two clips by its chair (`chairPlace`), with the seat centre at the clip's origin as in `room_stand_up`. The clip is moved along the floor so his hips are there at the join (a sit-down's last frame, a stand-up's first). Before this, the sit-down ended 6.8 cm to the side of where the seated loop then put him; now it ends 0.6 cm away.
- **`trim`** (row option): Mixamo's Sit_To_Stand runs on past the act. Over its last 6 frames his hips drop 20 cm as if sitting back down, so the row keeps 0–2.07 s.

What the page does around them (main's clips do the same; reported, not changed):
- Leaving the desk on the live page is not `room_stand_up`. It is the one-take get-up from `room_bedtime` (`flow()`), so Sit_To_Stand only plays if the wiring gives it that step. These numbers are measured with the get-up take switched off in a test copy of `boy_mh.js`. For the record, the live get-up measures chair legs 13.7 cm, torso 9.2 cm into the chair, seat -10 cm and soles to -3 cm.
- At the start of the sit-down, the cross-fade from the walk carries his root 45 cm in 0.2 s (main: 26 cm). The walk ends where it ends for main's clip, and Mixamo's performer starts standing further from the seat (0.43 m in front of it, main's 0.27 m). The walk's end belongs with the clip's standing start, in the wiring.
- At the end of the stand-up without the get-up take, the page's standing pose is about 30 cm from where either clip leaves him, and he slides there in the fade.

Sheets: `sit_down_before_after.jpg` and `stand_up_before_after.jpg` (behind the bed, every 0.2 s).

### Typing: decided, waiting on the page's resolver

Typing has its own contact row (the `keys` row of the contact pass: his fingertip skin over the room keyboard against its key tops, every frame). How it was found:
- **main's typing (live):** fingertips 0.5…1.1 cm *over* the key tops, touching within 5 mm in 0 of 180 frames. He has been typing on air. No test caught it, because the gate only looked for penetration and a hovering hand penetrates nothing.
- **Mixamo Typing as retargeted:** fingertips 10.4–19.5 cm under the key tops. The performer typed at a lower desk.
- **with only the wrists moved onto our keyboard** (9 cm back, 11.5 cm up, eased in by reach): -10.1…-2.8 cm, and the forearms run through the desk's front edge.

The decision (COORD A): one mechanism, in the page, owned by G14. Nothing is baked into the clip. These three clips are now built without a keyboard fit. The resolver maps the performer's keyboard point onto ours and settles the whole arm chain (shoulder, elbow, wrist, fingers) onto the desk. Moving the wrists alone puts the elbow through the desk edge.

The performer's keyboard point, from `room_mx_typing.glb` over its 16.5 s. It is the mean of the last finger joints (index to little), in the clip's frame: +x forward, y up, z to the side, with the hips' joint at (0.071, 0.680, -0.001).
- left hand: (0.534, 0.679, -0.152), steady (sd 0.5 / 1.7 / 0.5 cm); 0.463 m in front of the hips, level with them
- right hand: (0.564, 0.707, 0.095), but it wanders sideways (sd 13.6 cm across the keyboard)
- our key tops are at 0.84 m over the floor in the same frame (1.001 in the room), so the resolver lifts the hands about 16 cm

## The punctuation clips: what the captures are

Measured from the captures, not their names (`punctuation_postures.jpg`, side views of the retargeted skeleton across each clip):

| clip (out, `web/room/mh_v5/`) | what it is | length |
|---|---|---|
| Scared → `room_mx_scared.glb` | **seated**, startles, jumps up and stands back from the desk (2.9–7.2 s), then sits back down | 10.1 s |
| Angry_Gesture → `room_mx_angry_gesture.glb` | **seated throughout**, a raised fist and a shake, leaning forward | 5.8 s |
| Standing_Clap → `room_mx_standing_clap.glb` | **seated**, stands up (0.7 s), claps with the arms overhead (1.3–2.7 s), sits back down (3.4–4.1 s) | 4.8 s |

All three start and end seated, so they are built with the seated fit (the cushion stops the hips, and the feet are planted).

Contact pass at the desk, in the seated slot, each over its whole length:

| region | Scared | Angry_Gesture | Standing_Clap |
|---|---|---|---|
| chair | legs 8.4 cm (139 frames) | legs 4.8 cm (128) | legs 6.4 cm (60) |
| desk | **torso 186 frames, legs 161**, arms 41, hands 27 | **feet 14.9 cm, every frame** | **legs 80 frames, torso 80**, arms 19 |
| other furniture | torso, legs, arms | feet 16.5 cm, every frame | legs, torso, arms |
| seat | -1.6 cm lowest | no thigh within 10 cm of the cushion top (he sits on its front edge, leaning forward) | -1.1 cm |
| soles over the floor | -0.2…4.8 cm | -0.6…4.8 cm | -0.2…4.8 cm |
| floor, bed | clear | clear | clear |

Stills, the page's camera and beside the chair: `scared_desk.jpg`, `standing_clap_desk.jpg`, `angry_gesture_desk.jpg`.

- **Scared and Standing_Clap stand up inside the clip.** In the desk slot the chair is rolled in under the desk, so he stands up into the desk's front edge. A person stands up by pushing the chair back. The page does that for its own get-up (`flow()`), but not for a slot clip. These are not accepted.
- **Angry_Gesture's performer sat with his feet far forward** (0.6 m in front of the hips). Under our desk that runs his feet into its frame in every frame. Not accepted.
- They are built but not wired, and not accepted.

What the captures change about the chains: Standing_Clap already contains its own stand-up and sit-down. "Sit_To_Stand → Standing_Clap → Stand_To_Sit" would stand him up twice. The two honest options are below; the choice is COORD's.
1. **Trim to the act:** Standing_Clap's row keeps its standing middle (about 1.0–3.2 s), and the chain's own Sit_To_Stand / Stand_To_Sit carry him up and down, with the join jumps measured. This works for the clap. Scared's startle IS the jump up from the chair, so trimming it loses the act.
2. **Whole clip, the chair moved by the page:** the chair rolls back before he rises and in after he sits, as the get-up take does. That is the page's (G10d's).

## The phone clips and Gaming: postures confirmed

From the captures (`phone_gaming_postures.jpg`); none of them travels (hips 0.00 m):
- Texting (18.5 s): **standing**, the phone in both hands at the chest, head down. Not a seated clip, despite the name.
- Texting_While_Standing (23.6 s): standing, the phone in one hand.
- Standing_Using_Touchscreen_Tablet (33.1 s): standing, both hands forward on a tablet.
- Gaming (5.0 s): **seated**, a controller held in both hands over the lap, head down. The performer sits low (hips 0.58 m before scaling).

Not built yet; they follow the chains.

## The chains as data

`room_build/kimodo/mixamo_chains.json` lists each behaviour as clips in order: the cross-fade into each one, which one loops, and the rare events with their minimum gap. `room_build/kimodo_g12/chain_joins.py` measures every join from the baked clips:
- the worst bone-angle jump: the largest angle between the two local rotations of any joint, last frame of one clip against the first of the next;
- that jump spread over the cross-fade;
- the hips' jump.

| join | worst joint | jump | blend | per frame | hips |
|---|---|---|---|---|---|
| arriving: Stand_To_Sit → Seated_Idle | R hand (L forearm 42.1°) | 50.8° | 0.8 s | 2.1° | 0 (both at the seat point) |
| Seated_Idle (loop wrap) | neck | 0.1° | — | — | 0 |
| working: Sit_To_Type → Typing | L thumb | 2.3° | 0.2 s | 0.4° | 0.1 cm |
| Typing (loop wrap) | L index | 1.2° | — | 1.2° | 0 |
| working: Typing → Type_To_Sit | R hand | 4.3° | 0.2 s | 0.7° | 0 |
| link: Seated_Idle → Sit_To_Type | R hand | 48.6° | 0.8 s | 2.0° | horizontal only |
| link: Type_To_Sit → Seated_Idle | R hand | 48.9° | 0.8 s | 2.0° | horizontal only |

- Mixamo's desk set (Stand_To_Sit, Sit_To_Type, Typing, Type_To_Sit) shares one seated rest pose, with the hands on the thighs, so it chains within a few degrees.
- Seated_Idle rests the hands on the armrests instead. Every join into or out of it is a 49–51° move of the hands and forearms. The 0.8 s blends make that the hands moving from thighs to armrests, not a snap. Whether the blend passes the hands through the thighs or armrests is not measured yet: that needs a chain player in the page.
- The hips' 5.4 cm at the links is horizontal. The seated slot re-places Seated_Idle on the seat, so the page absorbs it; the heights agree within 0.4 cm.
- From the captures in scratch, Sitting_Talking (44 s, seated) joins the desk set within 6–11°, against Seated_Idle's 46–48°. It would be the seamless base, but it is a person talking with his hands; it is offered, not chosen.
- Celebrating is pending the Standing_Clap decision (above). The rare events are listed with what each waits on.


## The desk, wired (this branch)

COORD moved the desk to this workstream: replace the hand-built seated poses with the captures, and re-derive every constant that was tuned to them rather than inheriting it. In `web/room/boy_mh.js` and `web/room.html`:

- **Clips:** watching, and every seated slot, is `room_seated_idle`. The sit-down is `room_mx_stand_to_sit`, the stand-up `room_mx_sit_to_stand`.
- **Gone:**
  - the leg swap (the mouse clip's legs and pelvis forced onto the watch clip when its feet started over 0.12 m). This changes the `sit` / `dine` / `eat` slots too. On the old MakeHuman path the feet would go back up; that path is not shipped.
  - the one-take get-up from `room_bedtime` for leaving the desk (`flow()`): it put his torso 9 cm into the chair.
- **Where he stands** to sit down and where the stand-up leaves him come from the clips (`env.setSpots`): the walk's hips meet the sit-down's, and the standing pose's hips meet the stand-up's.
  - The one exception is a measured clearance. He turns on the spot before sitting, and the walk loop's turning steps caught the turned seat's front edge closer than 0.60 m (0.45 m: his right foot; 0.52 m: his toes). He turns at 0.60 m, and the remaining 24 cm is covered over the first 35 % of the sit-down while he is already sitting back.
- **Where each clip's hips sit on the seat** (`SEAT_AT`, in the chair's own frame) was swept in the room:
  - `room_seated_idle`: clear of the chair from 2 to 6.5 cm in front of the pivot. Closer, its calves catch the cushion's front edge.
  - 5.5 cm: also clears the sit-down, whose hips land 2.7 cm further back than they rest.
  - The old mouse and typing clips: clear from 3.5 cm (4.5 used). Main's 0.6 cm puts the mouse clip's left calf on the front edge.
  - The page's own seat point (2 cm behind the pivot) and `env.seatIn` (6 cm) were compensations for the next item, and are no longer used for the desk.
- **The legacy hips turn is not used for the desk slots.** The page placed the desk slots by `pageHips`, a −90° turn kept so G14's v5 tuning still placed the old clips. It moves a clip's forward offset sideways: `room_seated_idle` sat 2.3 cm off centre, its right thigh against the armrest. The desk slots now use the hips as the body has them.
- **How far he and the chair roll** follows from where each capture puts its hands. Typing: the clip's keyboard onto the room's (3.2 cm in). Mouse: the clip's mouse onto the room's (3.9 cm out). Watching (hands on the armrests and knees) needs nothing on the desk, so he stays where he was. During a crossfade his root is the weight-blend of each mode's own placement.
  - The old constants (watch 0.12, mouse 0.06, keys 0.085, less seatIn) are gone for the desk modes. Eating keeps main's, because it is not a desk mode.
- **Seated fit:** `seatHipY` 0.68 → 0.70 for every seated clip. At 0.68 his thighs sat 2.5 cm into the cushion top, which the page counts as in the chair (its margin is 1 cm); at 0.70 they rest on it. The numbers in the sections above were measured at 0.68.
- **Three page bugs fixed on the way:**
  - Walking to the desk while the tick still says `walking`, the page's goal clip was `stand`, so he sat down into the standing pose. That was most of main's walking 105.
  - A desk mode could switch in during the one frame between the sit-down and the chair's ride-in, and ride the turned chair in with its legs through it.
  - The debug `chairVox()` put the chair back at the page's own position, discarding where it had been rolled.

### Measured in the page

The visual gate (`python -m tests.visual.harness`, the core set, every scene swept over 8 s):

| | main (0174183) | this branch |
|---|---|---|
| hard failures | 2 | **0** |
| walking_8: chair | 105 | **0** |
| desk_14: chair | 16 | **0** |
| eating_19: chair | 0 | 0 |

`contact_pass.mjs`, every frame, every second vertex, in the page's own steps:

| | chair | seat (thighs vs cushion top) | desk | floor | soles | hands vs thighs |
|---|---|---|---|---|---|---|
| watching (`LIFE='{"screen":{"kind":"video"}}'`), 8 s | **0** | −0.1…4.7 cm | 0 | 0 | L 0.1…4.8, R −0.2…4.5 cm | 20 frames, 0.5 cm |
| mouse (old clip), 8 s | **0** | −0.4…4.5 cm | 0 | 0 | **L 9.1…13.9, R 5.3…10.4 cm** | 0 |
| typing (old clip), 6 s | **0** | −0.2…4.5 cm | 0 | 0 | **L 9.2…14.1, R 5.9…10.7 cm** | 0 |
| sit-down (`window>research`) | 78 vertices at 1.8 cm, as the chair rides in | −1.2 cm | 0 | 0 | −0.2…9.4 cm (steps) | (hands pushing on the thighs) |

G14's watch-mode numbers to beat:
- root 6.1 cm low and 7.1 cm back of mouse: now on the floor, and on the seat point for its own clip;
- 3713 chair contacts over 8 s: now 0;
- feet 5–14 cm off the floor: now 0–4.8 cm (a heel lifting in the capture).

Still open, reported rather than patched:
- **The old typing and mouse clips hover their feet 5–14 cm.** That is in those two hand-built clips. It goes when they are replaced: Typing with G14's contact resolver, and the mouse needs a capture (none of the twenty is one). Moving another clip's legs onto them would be the leg swap again.
- **Leaving the desk:** two samples remain, out of 60 at 0.1 s. At 1.5 s, 7 vertices: his left calf at the cushion's front edge as he rises. At 3.0 s, 10 vertices: his calf by the chair's base as he walks off. Main's get-up measured 14–238 vertices over most of the same span.
- **Walking from the window to the desk**, his left forearm swings through the parked chair's backrest (27–37 vertices at 2.6–2.7 s). It is identical on main: the path through the gap between the chair and the bed passes 15 cm from the backrest.
- **The phone in bed has no capture.** Texting is standing, Texting_While_Standing and the tablet are standing, and Gaming is seated. None of them is lying down, which is where he watches most of his shorts, so the bed phone pose stays as it is. It is the one place in his day we have no capture for.
- **The hands-vs-thighs row is a weak instrument in transitions.** It is a capsule around the thigh bone sized from baggy trousers (radius up to 16 cm), so a fist resting on the cloth reads as deep. The honest measurement is against the trouser mesh, and it should come with the contact gate.

## The rare events at the desk: the whole capture, the chair moved

COORD's rule for Scared, Angry_Gesture and Standing_Clap: play the whole capture and move the chair, not the performance. `boy_mh.js` `rare(k)` (`mh.rare("scared" | "angry" | "clap")`; the page's scheduler decides when, rarely and never twice close together):

1. **He rides the chair back** (1 s, seated), as far as that capture needs.
2. **The whole capture plays**, with 0.8 s crossfades in and out of the seated loop. The joins are 42–49°, hands from the armrests to the thighs (`chain_joins.py`).
3. **He rides back in** (1 s).

How far back is derived per capture, against the room, when the event starts:
- the capture's hands, forearms, knees, feet, chest and head, every 0.1 s, from its first frame's hips;
- against the free space in front of where he sits: rays toward the desk across his width at every 5 cm of height, plus downward rays for the desk's top, a 3 mm plate at 0.81 m that horizontal rays slip past;
- the deepest any part would go, plus 3 cm.

From his seated place that is 27–33 cm for Scared, 16–22 cm for Angry_Gesture, and 23–37 cm for Standing_Clap. Each capture's hips sit on a seat point swept the same way (`SEAT_AT`): Scared 11.5 cm forward (clear from 9.5), Angry_Gesture 8.5 (clear from 7.5), Standing_Clap where he sits to watch.

`contact_pass.mjs` with `RARE=<k>`, every frame, over the whole event:

| | chair | desk | floor, bed | seat on landing | soles | hands vs thighs |
|---|---|---|---|---|---|---|
| Scared (12.5 s) | **0** | **0** (was torso 186 frames, legs 161) | 0 | −0.1 cm | −0.2…4.8 cm | capsule 15 cm (hands push on the thighs to rise) |
| Angry_Gesture (8.3 s) | **0** | **0** (was feet 15 cm into its frame) | 0 | −0.6 cm | 0.1…4.8 cm | 132 frames, 3.4 cm |
| Standing_Clap (7.2 s) | **0** | **0** (was torso 80 frames, legs 80) | 0 | −0.1 cm | −0.2…4.8 cm | capsule 14 cm (as Scared) |

- Two fixes on the way. An action that was never played reports an effective weight of 1, which pulled his seated placement 4.8 cm sideways. And an event's crossfade has to start before the frame's mixer update; otherwise the root is placed for one frame for a pose that is not showing yet (10.6 cm).
- Sheet: `rare_events_desk.jpg`, from the room's side, seconds into each event. The dark first frame in two rows is a stale capture of the canvas; the log has him seated there.
- Angry_Gesture's 3.4 cm in the thigh capsule: his fist rests on his thigh as he leans in. The capsule is the weak instrument noted above, and it should be checked against the trouser mesh when the contact gate lands.
- Not wired to the scheduler (G10d's). `mixamo_chains.json` "rare" lists each event; celebrating is Standing_Clap played whole.

## The Mixamo skeleton path (no retarget)

COORD is moving the character onto Mixamo's own skeleton: the owner's v5 goes through Mixamo's auto-rigger (Standard Skeleton, 65 bones with fingers). The twenty captures then play on the skeleton they were recorded on, by bone name. The retarget (`mh_retarget.mjs`, `post.py`, `bed_fit.py`) is not used for new clips.

Ready for the file:
- `room_build/kimodo/mixamo_glb.mjs <in.fbx> <out.glb> [--test-skin] [--no-anim]`: a Mixamo FBX (a skinned character, or a clip downloaded "Without Skin") as a GLB.
  - The mixamorig names are kept, and the whole scene goes under one node scaled 0.01 (centimetres to metres).
  - `--test-skin` binds a plain box body to a clip's skeleton, for testing without the character.
- `web/room/char_mixamo.js`, the same shape as `char_v5.js`:
  - `prep()` hangs the hips under the body and gives the bones the names the page already uses (`NAMES`: Mixamo's limb names unchanged, the spine chain to Spine02 / Spine01 / Spine, Neck → neck, the fingers to finger1..5-1..4.L/R).
  - `fixClip()` renames a clip's tracks the same way, carries the hips' track into the body's frame, and scales only the hips' translation by hip height (the character's over the clip skeleton's).
- `room_build/kimodo/mixamo_check.mjs <character.glb> <clip.glb> <clip.fbx> [--scale k]`: the proof. It plays the clip through `char_mixamo.js` and compares every joint's world position every 0.1 s against three's FBXLoader playing the same FBX on its own skeleton.

| clip | character | bones matched | worst gap | lowest foot (played / reference) |
|---|---|---|---|---|
| Seated_Idle | the clip skeleton, as is | 65 / 65 | 0.00 cm | 0.002 / 0.002 m |
| Seated_Idle | scaled 0.9 | 65 / 65 | 0.00 cm | 0.002 / 0.002 m |
| Laying_Nodding | as is | 65 / 65 | 0.00 cm | 1.030 / 1.030 m |
| Laying_Nodding | scaled 0.9 | 65 / 65 | 0.00 cm | 0.927 / 0.927 m |

`mixamo_skeleton_loader.jpg` shows the test body playing Seated_Idle and Laying_Nodding in the browser, with the page's three.js (0.169) and `char_mixamo.js`.

What this settles about the lying clips. G10d measured our retargeted Laying_Nodding with the fists raised in front of the face and the legs lifted 11–19 cm. Played on its own skeleton, the capture lies flat (on the performer's bed, 1.03 m up):
- the hands rest on the stomach, 51 cm from the head and about 10 cm over the hips;
- the ankles are 9.6 cm below the hips.

Laying_Sleeping is the same. The lift and the raised fists came from the retarget and bed-fit chain, not from the captures.

Still to wire when the character arrives:
- room.html's `pickRig` / `V5` switch and `env.fixClip` / `pageHips`;
- boy_mh.js's MakeHuman-only names: `isMH()` (metacarpals), "Spine" in the rare-event reach (Mixamo's lowest spine bone becomes Spine02 here, so the reach's "Spine" is Mixamo's Spine2: correct), and the fingertip names (finger*-3 maps to Mixamo's third joint; Mixamo also has a fourth, the tip).

The placements (seat points, chair rides, spots, rare-event distances) sample each clip on the body, so they carry over.

## Walking past the chair

Traced with the page's `penetration()` every 0.1 s, in walks that pass or leave the desk:

| walk | main | this branch, before | now |
|---|---|---|---|
| window → desk | forearm through the backrest (27–37 vertices at 2.6–2.7 s) | the same | **clear** (one 25-vertex sample at the landing, 8.2 s) |
| desk → window | (main's get-up: 14–238 over most of the span) | 7 + 10 vertices (two samples) | 7 + 10 |
| door → desk | | | clear |
| desk → bed, to sleep | **68 samples, up to 3315 vertices** (room_bedtime's get-up at its own chair) | 65 samples, up to 5570 | 7 + 10, as any time he leaves |

- **The path between the chair and the bed** (`NODES` g, sl) runs down the middle of that gap: z 0.03, against −0.06 / −0.08. The parked chair's route box (with its pad) ends at z −0.065 and the bed's at 0.13; that also holds for the 1.90 m bed on preview/bed-music, which only extends the foot end.
- **`free()` keeps the route 0.25 m off the chair's box** (`ARM_PAD`), not 0.12 m. His swinging arm reaches about 0.3 m out, and the backrest's top is at arm height. That was the cut through the corner, from the sill straight to the desk.
- **Going to sleep from the desk**, he now stands up with `room_mx_sit_to_stand` like any other departure. `room_bedtime` plays only its part at the bed.

tests/visual core set: 0 hard failures. tests/test_boy_mh.py: 7 passed.

## The base seated loop, on the captures' own skeleton

`room_build/kimodo/mixamo_seated_src.mjs` (FBXLoader, no retarget):

| capture | what it shows | worst jump into / out of the desk set |
|---|---|---|
| Seated_Idle (4.2 s) | hands on the armrests (13–14 cm over the thighs, 28–31 cm to the side), head 11 cm ahead of the hips | 46–48° (right hand) |
| Sitting (4.4 s) | not an idle: starts standing and sits down (wraps at 85°) | 92° |
| Sitting_1 (1.2 s) | hands on the lap, head upright; a 1.2 s loop | 49–53° (arms) |
| Sitting_Rubbing_Arm (8.0 s) | leaning in, head 28 cm ahead | 82° |
| Sitting_Talking (44 s) | talking with his hands (ruled out as the base) | 6–11° |

The desk set rests its hands on the thighs (4–5 cm over them). Seated_Idle stays the base. The 0.8 s hands-to-thighs blend gets its contact pass on the Mixamo rig, the body it will play on.

The forward lean G14 measured (13–19°) is partly this pipeline's: the v5 seated fit tipped the spine 10° (`pitch` in `mixamo_clips.json`). On the Mixamo rig there is no fit.

## Rig-change checklist (re-measure first when the Mixamo-rigged character lands)

Measured on 20d32f0 every frame (contact_pass perFrame, positions in the chair's frame; seat cushion top y 0.504, front −z). Everything below is inside the chair; desk, floor and bed are 0.

1. **Sit-down landing** (window → desk, 0.67–0.70 s into the step), 2 frames, up to 1.2 cm.
   - Right lower thigh into the cushion's front, 1.3–1.6 cm under its top.
   - COORD: inside the contract's give (−2.5…+0.5 cm), not a defect. Re-measure.
2. **Rising** (desk → window / bed, 0.47–0.57 s), 4 frames (0.13 s), up to 1.6 cm.
   - The back of the left calf under the cushion's front edge (y 0.435, z −0.24).
   - COORD: a small defect. Re-measure on the new rig.
3. **First step away** (1.93–2.03 s), 4 frames (0.13 s), up to 3.8 cm.
   - The left lower calf/ankle through the chair base's front leg (y 0.05–0.08, z −0.27…−0.30).
   - COORD: a real defect. Fix it on the new rig: the walk-off foot placement, or roll the chair before he steps. Not patched on v5.

Also on the new rig, before anything else is accepted:
- the seat-point sweeps (`SEAT_AT`);
- the chair-ride distances for the rare events;
- the 0.8 s hands-to-thighs blend, contact-passed against thighs, armrests and desk edge;
- hoodie stretch per seated clip;
- the forward lean, measured with no fit;
- the mouse-mode body (Seated_Idle vs Typing), with G14's resolver.

## The Mixamo skeleton without mixamo.com (G20, `rig/autorig.sh`)

`room_build/rig/autorig.sh <in.glb> <out.glb> [clips dir]` puts the character on the Mixamo Standard Skeleton in about
17 s (v5: 260,660 vertices), with no upload and no Adobe login. With a clips dir it then runs the QA and this README's
rig-change checklist (2.5 min in all). On v5 from main the result is `web/room/char_mixamo.glb` (7.3 MB, meshopt; the
page does not load it yet).

How (`room_build/rig/autorig/`):
1. `extract.mjs`: the mesh and v5's own 79-joint skin in its bind space (the slides' second skin brought into the
   first's).
2. `fit.py`:
   - **T-pose from v5's own skin.** Each upper arm, forearm, hand, finger segment and thigh is swung to the direction
     the Mixamo T-pose gives it; the calf to the ankle. The hand is also rolled palm-down (knuckles running as
     Mixamo's: L 13.3°, R −13.6°), and that roll is spread down the forearm's twist bones (15 % / 55 %) so the wrist
     does not wrap. Baked, then the soles put back on y = 0.
   - **Joints.** Where v5 has the joint, its posed position (shoulders, elbows, wrists, knees, finger joints, thumb).
     Where it does not, the mesh: the ankle is the lower leg's cross-section centre at Mixamo's ankle height (v5's
     Foot joints sat on the sole); the finger and thumb tips are the furthest skin along each finger; the top of the
     head is the highest head skin. Finger middle joints are re-centred in the finger's own cross-section (≤ 2.8 mm).
     Where a joint is a convention rather than anatomy, Mixamo's direction decides it: the hips over the hip joints,
     the spine chain in Mixamo's proportions up to v5's neck, the clavicle root, the neck base, the toes.
   - **Rest rotations are Mixamo's.** Every bone keeps the Standard Skeleton's T-pose world rotation
     (`mixamo_standard_skeleton.json`: names, rest positions and rotations only, read from a capture's rest; no motion).
     So a clip's local rotations give the performer's world rotations exactly: the clips play by name.
   - **Weights.** Half geometry, half v5's skin: inverse 4th-power distance to each new bone's segment, only among
     the bones v5's skin already gives that part of the body and their neighbours (no arm vertex bound to the ribs);
     blended 50/50 with v5's weights moved onto the new bones; smoothed 12 times over the surface; coincident
     vertices (UV seams, the head/body join) forced to one set (without that the hoodie cracked open at its seams);
     4 per vertex. 50/50 was chosen by measurement against 0 and 100 % geometry (below).
3. `write.mjs`: the same file (meshes, UVs, materials, textures) with the new positions, normals, skeleton and skin.
   The skeleton is in centimetres under one node scaled 0.01, as `mixamo_glb.mjs` writes Mixamo's own FBX, so a clip's
   hips translation means the same on both. Positions stay float: quantizing a skinned mesh's positions moves the
   dequantization into the inverse bind matrices, and then three's `skeleton.pose()` puts the bones somewhere else.

Result on v5: 65 bones, `mixamorig:Hips` … `mixamorig:LeftToe_End`, the hierarchy exactly the Standard Skeleton's;
1.78 m with the slides, hips 0.92 m. Joint directions within 3° of Mixamo's along every limb (arm, forearm, hand,
legs, feet, thumb segments); the larger offsets are joint roots where his anatomy differs (thumb base 30–46°, clavicle
root 17°, hip joints 11–12°: he is wider at the hips than the performer).

### Proof and numbers

`kimodo/mixamo_check.mjs` now also compares every bone's **world rotation** with the FBX played on its own skeleton
(positions cannot match: his proportions are his own):

| clip | bones matched | worst rotation gap | worst position gap (proportions) |
|---|---|---|---|
| Seated_Idle | 65 / 65 | 0.03° | 9.1 cm (knee) |
| Typing | 65 / 65 | 0.03° | 10.1 cm (thumb tip) |
| Laying_Sleeping | 65 / 65 | 0.04° | 23.1 cm (thumb tip, arms longer than the performer's) |

Deformation (`rig/autorig/qa.mjs`, the skinned mesh every 0.1 s; edge length change in each joint region, worst
frame's 95th percentile and share of edges changed by more than 30 %; folds at a bent joint compress, so these are
large by nature and are for comparing weightings):

| weights | elbows | shoulders | wrists | hips | knees | fingers | whole body |
|---|---|---|---|---|---|---|---|
| v5's moved over (0 % geometry), Typing | 147 % / 46 % | 95 / 32 | 61 / 17 | 103 / 39 | 136 / 39 | 36 / 7 | 60 / 13 |
| **50 / 50 (used)**, Typing | **88 / 30** | **75 / 23** | **53 / 13** | 104 / 39 | 118 / 40 | 35 / 7 | 58 / 13 |
| 100 % geometry, Typing | 65 / 24 | 83 / 23 | 64 / 17 | 110 / 41 | 100 / 42 | 35 / 7 | 58 / 14 |

Contact and self-contact numbers are in `docs/qa/contact.md` (section "The auto-rigged character"). Sheet:
`autorig_v5_sheet.jpg` (T-pose front / side / back and hands; each clip at four moments; close-ups of shoulder, elbow,
hips and both hands). The checklist report: `rig_change_v5.md`.

### The rig-change checklist, automatic

`room_build/kimodo/rig_change.mjs <character.glb> <clips dir> <out dir>` (run by `autorig.sh`) writes
`rig_change.md` / `.json`. On v5: the loader proof PASS; the 0.8 s hands-to-thighs blend PASS (0/28 frames both ways,
against his thighs); the forward lean with no fit measured (Seated_Idle 3.9°, performer 7.9°; Typing 4.4°, performer
5.1°); hoodie stretch and soles measured. The three chair items, the seat-point sweeps, the chair-ride distances and
the mouse-mode body are reported **PENDING**: they need room.html to play this character (a `?char=mixamo` switch in
`pickRig` / `V5`, G10d's) and, for the first step away, a walk, which no Mixamo capture provides.

### Tripo's auto-rig: not used

Tried on 2026-10-06 (room_build/rig/README.md): 25 credits for a 22-bone biped with no fingers. That is over this
task's 5-credit budget and without the fingers the whole point needs, so it was not run again (0 credits spent).

### Fallback: mixamo.com by hand

Only if the result above is not accepted: `rig/mixamo_upload.sh <in.glb> <out.zip>` (OBJ + MTL + 2048² JPEG; v5 →
160,899 triangles, 4.3 MB), the owner's steps in `UPLOAD_STEPS.md` (Italian), then
`rig/mixamo_import.sh <mixamo.fbx> <out.glb> [original.glb]`. The import has only been exercised on a skinless
capture (no Mixamo-rigged FBX of ours exists to test the textured path).

## `room.html?char=mixamo`: the Mixamo skeleton in the room (G21)

The page loads `room/char_mixamo.glb` with `room/char_mixamo.js` and plays the Mixamo captures on their own skeleton,
bone for bone: nothing is retargeted to the old rig. Without the flag the page is unchanged (v5). Status and every
number: `STATUS_WIRING.md`. Sheet: `wiring_sheet.jpg` (watching and typing; the page's camera and his right side; main
above, `?char=mixamo` below).

### The clips (`web/room/mh_mx/`, `room_build/kimodo/mx_build.sh <Clip> <work dir>`, rows in `mx_clips.json`)
`kimodo/mx_fit.py` bakes each capture for this character and our chair. It is G12's seated fit ported to the Mixamo
skeleton, plus what this body needs:
- **The hip joints at 0.68 m, 4.5 cm forward.** G12's numbers: v5's Hip joint sits at the hip joints, where these are
  measured. On the seat, the cushion stops the hips.
- **The hands where the clip puts them on him.** They ride up with him onto our seat (the performer sat 16–24 cm lower
  at his size), then `handUp` / `keys` move them onto our furniture: typing −11 cm onto our keys. Not the performer's
  wrists: his shoulders are not ours, and reaching for them pulled the right arm across the chest.
- **The knees at 0.55 m.** Our chair is high for him: with his feet flat, his shin and ankle reach 0.48 m and his thighs
  went 3–8 cm through the cushion's front edge. As on a high chair, his heels come up 7–8 cm and he rests on the balls
  of his feet (v5's clips hold his knees at 0.55 m the same way). This applies whenever his hips are over the seat and
  near its height, so it covers landing and pushing off too.
- **The feet planted** (stances locked, soles +0.2 cm over the floor with the slides counted).
- **The sleeves off the hoodie.** Where a sleeve would still go more than 0.8 cm in, the elbow swings out about the
  shoulder–wrist line (wrist and hand stay), then the arm abducts at the shoulder (≤ 24°): per frame, the least that
  clears, smoothed.

Slots without a Mixamo capture (the mouse, walking, standing, the bed, eating, the door, the window) play v5's room
clips carried onto this skeleton (`kimodo/mx_convert.mjs`): each bone moves as the v5 joint it was fitted from, plus
place tracks where the two skeletons' joints differ. Measured against v5, the median skin offset is 2–3 mm.

### The page
- `room.html` picks the character: `CHAR_MX ? load("room/char_mixamo.glb") : load("room/char_v5.glb")`.
- `char_mixamo.js` `ROOM` tells `boy_mh.js` (through the page's env):
  - which clip plays which slot;
  - typing's way in and out (Sit_To_Type / Type_To_Sit, with G12's 0.3 / 0.2 / 0.8 s links);
  - the baked Typing's keyboard point (the page rolls him and the chair onto the room's keyboard by it);
  - the seat points, swept for this character with `kimodo/seat_sweep.mjs`.
- `boy_mh.js` takes these as optional env (`clips`, `links`, `clipFrame`, `seatAt`); without them, everything is as on
  main.
- The rig-change checklist's room items are measured by `kimodo/mx_room.sh` (contact_pass.mjs and seat_sweep.mjs, on
  `?char=mixamo` and on v5 alongside). `kimodo/rig_change.mjs` reads them; result: `rig_change_v5.md`.
