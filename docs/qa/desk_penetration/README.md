# Through the desk: what the desk check could not see

## How it was found
Freezing the page's loop while it booted (7f2bf6e) turned two scenes red: walking_8 and eating_19, both "in the desk".
Nothing else differed at those frames: clip times, chair, body, every arm bone. The only difference was the desk that
the check saw.

## Why the check was blind (`web/room.html`)
1. **The trees are built first.** `camRoom()`, the camera's spring arm, runs from the first live frame. It builds a
   bounding-volume tree (three-mesh-bvh) on every room mesh, `room_static` included.
2. **Then the meshes are cut.** After that, `splitBox()` (the keyboard) and `cutBox()` re-index `room_static` with
   `setIndex`.
3. **The trees go stale.** A tree built on the old index misses what was re-indexed.

| desk zone of the visual checks | surfaces found |
|---|---|
| live boot (main), through the stale trees | 3794 |
| no trees, or rebuilt trees | 5124 |

The desk check passed with 26% of the desk missing. The rig's own desk avoidance (`deskCols`, `armIn`) raycasts the
same way, and the camera did too.

**Fix.** A re-indexed geometry drops its tree (`dropBVH`); `camRoom()` builds a new one on its next refresh.

**Test.** `tests/visual/test_room_raycast.py`: after a live boot, raycasts through the page's trees must find what
raycasts without them find. On main: 3794 against 5124.

## What it had hidden
Real depth: distance to the nearest desk surface over six axis rays, at every counted vertex. The desk top is a slab
about 3 cm thick (y 0.94–0.97), with its front edge at z ≈ −0.776.

| scene | part | sampled vertices | where |
|---|---|---|---|
| walking_8, riding the chair in (7.75 s of the sweep) | left forearm (twist bones) | 100 | 25–63 mm past the front edge, 12–18 mm under the top |
| eating_19 (0–3.75 s) | belly (Spine01) | 53 | 31 mm into the front edge |
| eating_19 | right forearm | 26 | 26 mm into the front edge |
| eating_19 (1.5–3.5 s) | right hand and fingers, in the **monitor** | 774 | the clip's reach for a bite: 0.44 m out from the shoulder, 30 cm past the dish |

**The monitor was never measured.** The desk check knew only `room_static`. `qa.body` now also counts skin inside the
solid things on the desk: the monitor and the game controller. A point is inside if it gets an odd number of crossings
on at least 2 of 3 horizontal rays (the monitor's housing is open on top). Budget `desk_things_vertices`: 0.
- **Left out by design:** the keyboard and the mouse (his hands are on them) and the mug and the bottle (he picks
  them up).
- **On main:** eating_19 reads 774 inside the monitor.

## Fixes (`web/room/boy_mh.js`)
- **Riding in, watching or eating at the desk** (not on the keys or the mouse): an arm whose skin, or its hand's, is
  in the desk slab swings about the shoulder by the least angle that takes it out. Four ways are tried: back, forward,
  out and in. Walking_8 needs it on 12 frames, at most 12.9°.
- **Eating:** he sits 5 cm further from the desk (`EAT_BACK`). On the desk-mode seat he leaned in over the dish. His
  body now goes with the chair when no desk clip is running; before, only the chair moved.
  - With that, eating needs no arm swing (0 frames).
- **The reach for a bite** (`eatReach`). While the clip's right hand is out ahead of him (0.26 → 0.40 m from the
  shoulder), it goes to a point 10 cm over the dish instead. The share follows at most 1 / 0.5 s.
  - The hand is pinned at full weight to a point blended between the clip's and the dish's. `pin()` is not linear in
    its weight: weighted, the hand leapt 20 cm in a frame.
  - The hand moves at most 31 mm a frame; the clip alone moves it up to 24.
  - To the mouth and back, the clip is unchanged.
  - The seat 5 cm back did not keep the hand out of the monitor: 680 vertices.
- **`deskCols`** builds a mesh's tree if a cut dropped it. Raycasting the desk without one took seconds, and made him
  sit late in the real-time arrival test. Time to seated, alone on 2 cores (limit 45 s):

  | | runs (s) |
  |---|---|
  | main | 25.9, 35.8, 14.5 |
  | now | 15.5, 35.7, 27.3, 30.9 |

- **On the mouse** (desk_14, found once merged with the hands' elbow swivel, 2198d69/d4d1970): after the arm's passes
  the elbow swings to its reference, lower over the mouse, and the 15° elbow lift could not take the right forearm out
  of the desk's edge again (9 sampled vertices, 12 mm under the top). On the mouse the swing now goes only as far as
  keeps the forearm out; its check samples the forearm alone (`foreIn`: 120 vertices on the forearm, where `armIn`'s
  120 spread over the whole arm missed it).
  - Raising the lift to 20° also cleared it, but his shoulder rose and the upper sleeve showed a stretch crease.
  - Typing is untouched: 81% of resting tips in 0..+2 mm (main 82%), none more than 2 mm in, thumb lowest −1.3 mm,
    deepest vertex 1.3 mm.

## After
test_visual: desk 0, desk things 0, bed 0, chair 0, floor within budget. The existing budgets are unchanged; the new one is 0.

`before_after.jpg`: both frames, before and after, from his front right and from above his shoulder at the desk edge.

## Eased (preview/freeze-why-ease)
The desk clearing and the hands' weights snapped in single frames.

**What jumped**
- **Mouse to watching (default page):** the mouse hold's `pin()` is not linear in its weight. At a weight of 0.02 his hand was still on the mouse; at 0.01 it let go.
- **Into the arms-crossed reaction (`?char=mixamo&anim=sova`, preview/desk-states):** the clearing took the least swing of four ways each frame, and mid-crossfade it flipped from 6° back to 7° forward.
- **On the default page,** `watch_video` and `play_chess` had no entry in the page's activity table. They fell back on standing at the desk, so each switch to them started a pose step and the desk modes dropped for a frame.

**Fixes (`web/room/boy_mh.js`, `web/room.html`)**
- **A hand at a fading weight** (the mouse hold, the left hand on the keys, the right hand's typing) is solved at full weight. The arm is then blended bone by bone from the clip's pose by the weight. At full weight (steady typing and mousing) nothing changes.
- **The desk clearing's swing**
  - keeps last frame's way while that way still clears, so it no longer flips;
  - still comes in at once, so no skin stays in the desk;
  - lets go over about 0.25 s. While letting go it may stay up to 8 mm in the slab (the desk check counts skin over 1 cm in). The clip's arm may have moved on, and the way back can pass the desk's edge: held to 3 mm, an 18° swing dropped at once.
- **`watch_video` and `play_chess`** are seated at the desk, like research and chat.

**The biggest move of any bone in one frame, stepped at 30 fps**

| transition | before (63538e6) | after |
|---|---|---|
| default page: mouse → watching | 382 mm | 48 mm |
| default page: → typing | 236 mm | 53 mm |
| default page: typing → mouse | 210 mm | 31 mm |
| default page: watching → mouse | 134 mm | ≤ 53 mm |
| steady mousing (a forearm twist bone, the clip itself) | 50 mm | 50 mm |
| mixamo + desk states: → watching, → mouse, → typing | 388 / 167 / 156 mm | 85 / 52 / 53 mm |
| mixamo + desk states: into and out of the arms-crossed reaction | 143–147 mm | 19 mm, with the reactions' minimum ride-back (desk-states only) |
| mixamo + desk states: a won game straight after the mouse | 275 mm | 140 mm |

**Still open.** The won game straight after the mouse starts from room_seated_idle, whose forearms rest on the desk's edge and hold an 8–13° clearing swing. When the reaction takes the arms away, releasing that swing still meets the edge.

**Typing contact** (`tools/motion/key_contact_mesh.py`, 64 samples over 16 s):

| | resting fingertips in 0..+2 mm | more than 2 mm in | lowest thumb | deepest vertex |
|---|---|---|---|---|
| 63538e6, counted the same way | 83% | 0 | −1.3 mm | −1.4 mm |
| eased | 83% | 0 | −1.3 mm | −1.3 mm |
