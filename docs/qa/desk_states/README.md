# Seated states at the desk (`room.html?char=mixamo&anim=sova`)

A preview layer, off by default. `room/desk_states.js` decides what he does in the chair; `room/boy_mh.js` plays it.
Without `&anim=sova` the page neither loads the module nor queues any message.

## What plays
These states play in `desk_watch` only: a video, a page, or waiting for the opponent at chess. Typing and the mouse stay as on main (the owner's takes).

| slot | kind | stand-in (`room/mh_mx/`) | how it plays |
|---|---|---|---|
| idle_a | waiting | room_seated_idle | loop |
| idle_b | waiting | none | left out: `room_mx_sitting` puts his legs through the seat at every seat point tried (≈5000 vertices) |
| idle_c | waiting | room_mx_sitting_1 | loop |
| attend | on the monitor | room_seated_idle | loop |
| gesture_a | small gesture | room_mx_sitting_rubbing_arm | once; seat −0.22 |
| gesture_b | small gesture | room_mx_sitting_talking | a 5–8 s window, once; seat −0.22 |
| react_win | reaction (a won game only) | room_mx_sitting_talking | a 3–5 s window, once; seat −0.22 |
| react_lose | reaction | room_mx_sitting_rubbing_arm | once; seat −0.22 |
| react_up | reaction (a big burst on a short) | room_mx_sitting_talking | a 3–5 s window, once; seat −0.22 |

**No desk state stands him up.** Two stand-ins were dropped, and react_up stays seated: a short doesn't get him up. Later it becomes Sova's LAUGH SIT / DISTRACTED & THEN SMILE.

| dropped stand-in | was for | why |
|---|---|---|
| room_mx_standing_clap | react_win, react_up | up at the desk, his fingers went into the monitor (up to 834 sampled vertices); his hands were a few cm from the lamp and the monitor |
| room_mx_angry_gesture | react_lose | his forearms went through the monitor (1269 vertices). At seat −0.30 it cleared the monitor, but his right hand went through the bottle on the desk (369) |

**How the loops are picked**
- Each loop is picked at random and never follows the same clip. Two slots on one stand-in count as one clip, so desk_watch is never followed by idle_a or attend.
- Each loop starts at a random phase of its clip and holds for a random time (7–15 s idle, 6–12 s attend). No two loops run in step.
- Between events, the mix is:

  | situation | attend | idle | gesture |
  |---|---|---|---|
  | watching | 0.55 | 0.37 | 0.08 |
  | waiting | 0.25 | 0.65 | 0.10 |

- Gestures come at least 25 s apart and reactions at least 150 s apart.

**Crossfades and the chair**
- Loops crossfade over 0.8 s.
- Gestures and reactions go through the rare events' path (`rareStep`):
  - he rides the chair back by what the take needs (`backFor`), or not at all if it needs nothing;
  - the take plays with a 0.8 s fade in and out;
  - he goes straight into the next loop and rides back in.
- The switches run before the mixer update, like `rareStep`. Run after it, the root blend saw the new clip at full weight for one frame: an 862-vertex chair spike.

**Named clips (G23's).** Put `web/room/desk_states/<slot>.glb` in place and list it in `index.json` (`{"clips": [...], "seat": {...}}`). That slot then plays its own clip instead of the stand-in. The list is empty for now: no clip goes in until its licence is cleared.

## Reactions: only messages the page already receives (`live_server.py`)

| message | when | reaction |
|---|---|---|
| `chess` (#17) | the opponent moved, his turn | attend; with check on him, a gesture |
| `chess` | game over | won → react_win, lost → react_lose, draw → a gesture (the end is broadcast twice; it counts once) |
| `chess` | the opponent's turn | he waits in the chair (desk_watch, idle mix). On his turn he looks for 2.5 s, then takes the mouse. After the end he sits back |
| `decision` (#55) | his brain picked a page or a video | attend |
| `dopamine` (#89) | a new clip or page; size = novelty + interest − expectation | ≥ 0.45 a gesture, ≥ 0.9 react_up. Only shorts reach 0.9: videos are scaled ×0.5, pages ×0.25 |
| `chat` | a viewer's message reaches him | attend |

- **Left out by design:** trades (nothing financial).
- **Also no reaction:** music, ticks and the rest.
- **Expiry:** an event not played within 4 s is dropped. A reaction goes ahead of a look.
- **Scared has no event.** Nothing the page receives warrants it, so it stays unmapped.

## Measured
Measured locally, alone on 2 cores (`taskset -c 0,1`).

**What each sweep covers**
- **Each slot:** swept whole every 0.1 s. For a once slot that covers ride, take and ride back.
- **Natural watching:** 120 s with the page's messages handed in as the socket sends them.
- **Chess:** the wait and look sequence, then a won game.

**Desk, chair, bed, floor** (the page's `qa.body(2)`): 0 in every sweep.

**All of the room** (`sv_room2.py` in the session scratchpad: every room part and every scene object, not only desk/chair/bed/floor):
- **Closed furniture:** inside means an odd number of crossings on 2 of 3 rays, both faces counted. This covers the wardrobe, door, shelves, monitor, lamp, controller, mug and bottle.
- **Walls:** checked against the room's box.
- **Left out:** the keys and the mouse (his hands work on them), flat decals and 4-vertex helper quads.
- **The desk:** counted with freshly built raycast trees. On main the page's trees are stale after the keyboard cut, so they miss 26% of the desk (the freeze-why bug).

| | inside furniture | past a wall | desk during the take (fresh trees) | nearest wall (limbs) | nearest thing other than the desk (limbs) |
|---|---|---|---|---|---|
| every gesture and reaction | 0 | 0 | 0 | ≥ 44 cm | ≥ 3.4 cm (the desk's shelf rail) |

**Inherited from main's own mixamo seated loop** (room_seated_idle, desk_watch's clip on main, and so idle_a and attend too):
- 369–413 sampled vertices are in the desk once the trees are fresh: the forearms on its front edge, which the stale trees hide.
- His right hand and forearm are in the bottle on the desk: 10–22 vertices.

This is not from this layer: the same numbers show with `anim` off.

**The chair ride**
- The rides are longer now: 0.21–0.51 m on top of the slot's seat point.
- The ride-back (`backFor`) misses things in three ways, all fixed for the desk states only (the default page's `rare()` is unchanged):
  - it sampled no fingertips, though raised hands reach 18 cm past the wrist;
  - its rays stopped at 1.14 m, under the monitor;
  - it raycast through main's stale trees.
- The seat points were then swept against the desk counted with fresh trees.

**Crossfades frame by frame** (idle_c↔attend, idle_a→idle_c): chair + desk 0 on every frame. The switches run before the mixer update; run after it, the root saw the new clip at full weight for one frame (an 862-vertex chair spike).

**Before the first fixes:** the slots sat at their clip's hips height instead of the seat's, which lifted him 6 cm at each switch.

## The real clips (G23's seated takes; this branch only, never on main: their licence is pending)
`web/room/desk_states/` carries G23's desk v3 from `preview/sova-phone-src` (b578db3): hands on the thighs, nothing of them inside him, and the bake's arm corrections smoothed over time. `index.json` maps each slot to a file; a slot with its own clip plays it whole.

| slot | clip | plays |
|---|---|---|
| attend | neutral_1 (head straight) | loop |
| idle_a / idle_b | neutral_3 / neutral_5 | loop |
| idle_c / idle_d | look_left_idle / look_right_idle | loop |
| gesture_a / gesture_b / gesture_c | look_down_to_right / look_front_to_left / desk_look_behind | once |
| gesture_d / gesture_e / gesture_f | seat_looking_around_v2 / seat_neck_stretching_idle / seat_thinking_touching_chin | once |
| react_win | seat_happy (a pleased sway, 4 s: G23's pick for a won game) | once |
| react_up | seat_distracted_then_smile | once |
| react_lose | seat_feeling_frustrated_v1 | once |

- All of them sit at desk_watch's seat point (−0.075).
- desk_start_01, a sit-down transition, is not used.
- The stand-ins stay for any slot index.json leaves out.

**Each clip alone** (the mixer only, every bone at 30 fps):
- **v3:** 4–19 mm per frame (room_seated_idle 14 mm), loop seams 0–3 mm.
  - seat_thinking_touching_chin: 62 mm on the fingers over 5 frames.
  - seat_distracted_then_smile: 2 mm.
- **The bake before v3** (0cd8768): 50–150 mm at the elbows.

**In the room** (fresh trees):

| | walls | furniture (bottle and monitor included) | desk, fresh trees | desk, chair, bed, floor (`qa.body`) |
|---|---|---|---|---|
| every slot but gesture_f | 0 | 0 | 0 | 0 |
| gesture_f (thinking v6) | 0 | 0 | 0 | 0 (v3 had chair 90: right fingers at his side, at 8.7 s) |
| react_lose (frustrated V1 v5), react_win (seat_happy) | 0 | 0 | 0 | 0 |
| 120 s natural, chess won | | | | 0 |
| into the first loop, from desk_watch | | | | desk 19 for one frame (2.0 s) |

- **Off the armrests:** G23's armrest fix (94a87c9: a standing performer's hand beside the hip, now put on the lap) takes thinking and frustrated V1 out of the chair. Frustrated had 270 before.
- **A one-off:** one run of the chess sequence counted 31 desk vertices at 10.9 s, after the reaction. Two reruns and a frame-by-frame trace did not reproduce it; the loops are picked at random.

**Transition pops: eased** (preview/freeze-why-ease, merged here; `docs/qa/desk_penetration/README.md`)

| transition (`?char=mixamo&anim=sova`, the biggest move of any bone in one frame) | before (01a061a) | after |
|---|---|---|
| into and out of the arms-crossed reaction | 143–147 mm | 19 mm |
| → watching / → mouse / → typing | 388 / 167 / 156 mm | 85 / 52 / 53 mm |
| a won game straight after the mouse | 275 mm | 140 mm |

**What the easing changed**
- **The desk clearing** keeps its way while that way still clears and lets go over about 0.25 s. While letting go it may stay up to 8 mm in the slab.
- **Hands at a fading weight** are solved whole, then blended from the clip's pose.
- **Here only:** gestures and reactions fade over 1.3 s, and a reaction rides back at least 12 cm. Without the ride, the crossfade to his arms crossed swept his hands through the desk's edge.

**Still open.** A won game straight after the mouse starts from room_seated_idle (main's mixamo seated loop), whose forearms rest on the desk's edge and hold an 8–13° clearing swing. Letting that swing go as the arms cross still meets the edge (140 mm).

**Videos** (G23's 0cd8768 clips, before v3):
- `room_quick.mp4`: 25 s, 640×360.
- `room_video.mp4`: 66 s, 1280×720.
- Each records the real room, the page stepped frame by frame, with the events handed in as the socket sends them. The captions come from the event log.

## The twisted hands (the owner's review of the videos)
- **Cause:** the arm's IK (pin, ccd, the elbow swing) leaves each arm bone's roll about its own length free. Mixamo's rig has no forearm twist bones, so that roll landed on the upper arm and forearm. They flipped 145–165° from one frame to the next and wrung the sleeve into spikes.
- **Fix (`hands()` in boy_mh.js):** keep the clip's own twist of the upper arm and the forearm (swing-twist decomposition) and counter-rotate each child. The hand's world pose and its contacts are unchanged. It only applies to rigs without twist bones.
- **Typing, mouse and watching:**

| | wrist per frame, most | elbow per frame, most | jumps over 30° |
|---|---|---|---|
| before | 150–165° | 57–70° | 27 |
| after | 12–15° | 20–23° | 0 |

`hands_twist_before_after.jpg`: hand close-ups, before | after.

## main's mixamo seated loop (COORD's item 2)
- **Before the merge:** room_seated_idle (desk_watch on main) had 369–413 sampled vertices in the desk with fresh trees, and 10–22 in the bottle.
- **After merging preview/freeze-why:** 0 and 0. Its desk clearing, the least swing of the arm about the shoulder that takes its skin out of the desk's slab, already covers this loop, and the swing also takes his hand off the bottle.
- Typing and the mouse are unchanged.
- No further change was needed.

## The hood (`char_mixamo.glb`'s autorig; not fixed here: G21 / C)
The dark spikes at the back of the hood are the hood's lining and patches (`hood_lining`, `hood_patches`; 3127 vertices) coming out through the hoodie.

**How it is measured**
- **The lining:** the signed distance of each lining or patch vertex to the hoodie's surface near the neck. A vertex counts as out when it is past the outer face. Each vertex is compared with its own value in desk_watch's seated pose, so only the extra counts: the hood's rim is out by design.
- **The hood and shoulders:** the hoodie's own vertices over the shoulders and behind the neck. This reports how much further from the neck they move than in the seated pose, in the neck's frame. That includes the shoulders' ordinary movement as the arms rise.

| slot (take) | lining out, most | lining vertices out more than 0.5 cm | more than 1.6 cm | hood and shoulders, most | vertices more than 1.6 cm |
|---|---|---|---|---|---|
| idle_a (desk_watch's loop, other frames) | 5.6 cm | 9 | 8 | 0.1 cm | 0 |
| attend | 6.3 cm | 32 | 26 | 3.1 cm | 2001 |
| idle_c | 7.1 cm | 52 | 42 | 3.8 cm | 2742 |
| gesture_b / react_win / react_up (sitting_talking) | 7.1 cm | 56–130 | 45–106 | 3.8–4.3 cm | 4811–5002 |
| gesture_a / react_lose (rubbing_arm) | 7.1 cm | 384 | 257 | 7.1 cm | 5633 |

With G23's v3 clips (hands on the thighs), compared the same way:
- **The lining:** 6.3–6.9 cm out at most, with 239–312 vertices more than 1.6 cm out.
- **The hood and shoulders:** 3.9–6.1 cm.

With the arms up, a few hundred lining vertices go 1.6–7 cm past the hoodie. The arm raise pulls the hood's back and shoulders up to 7 cm off their seated place.

`sheet.jpg`: each slot mid-play from the character camera.
