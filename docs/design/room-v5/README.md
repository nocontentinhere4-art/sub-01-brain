# Character v5 in the room (preview/room-v5, G10d): integration preview, nothing live

From main (56525bb: the live room, the owner's chair at the live seat height 0.505 m), with preview/room-mh's room side
merged in (0b6efe3): room/boy_mh.js (the clip player and G3's choreography: desk modes, sit / stand, the chair pulled and
pushed, routes, the bed), `mh/props_g2.json`, the page's wiring for it, its tests. Not merged in: G2's MakeHuman body,
G11's hair and the MakeHuman-rig clips (`mh/*.glb`). `?char=old` shows the live character with its own clips.

## Release note (for the owner's go; nothing of this is on `main` yet)

**What changes on the live site** (main 56525bb -> this branch, one release):
- **The character:** the v5 Tripo character (`web/room/char_v5.glb`, his own hair, socked feet with slides that come off
  in bed) replaces the live one. `?char=old` still shows the live character with its own clips, unchanged.
- **His motion:** 16 mocap clips retargeted onto him (`web/room/mh_v5/`, G14 and G12), played by `web/room/boy_mh.js`
  through `web/room/char_v5.js`: typing for a search, the mouse otherwise, seated for videos, 0.4 s crossfades, the
  wrists re-pinned to the real keyboard and mouse, sitting down / getting up with the chair, walking, the window, the
  door, going to bed, asleep under the duvet (a quilt drawn up over him), waking.
- **The tea bottle:** G15's generated bottle replaces the last code-modelled prop (`web/room/bottle.glb`; `?bottle=old`
  keeps the old one).
- **Weight:** about 13.8 MB of new binary assets (the character 6.8 MB, the clips 6.9 MB, the bottle 0.1 MB).
- **Tests:** tests/test_boy_mh.py, tests/test_prop_bottle.py, and tests/visual's contact pass with the chair by part,
  the bed (mattress plane, duvet) and the bottle.

**Known and accepted (by the coordinator):**
- tests/visual `desk_14_1280`: chair penetration **6 sampled vertices** (left calf at the seat's front edge, about
  4 mm: contact, not penetration). The visual suite's one failure; everything else passes (pytest 1285 passed).
- `room_read`: **17 mm** into the seat top: the cushion's give.

**Known and open (with the owner: not in this release unless he decides otherwise):**
- On v5 the page's old prop layer does not run (`room.html` returns into boy_mh.js before it): the bottle is never
  picked up, the phone is not in his hand, the headphones do not go on, meals show placeholder shapes instead of the
  dish, the bags are not carried; and the old idle variants, gaze and breathing are off. Three scopes are with the owner.
- The get-ups: his left hand passes through the tea bottle (up to 108 mm), his right toe enters the bed's footprint for
  3 frames on the way to the window, the chair up to 40 mm as he rises (to be assigned with the prop scope).

**Merging to `main` (mechanical, once the owner says go):**
1. Every commit on this branch carries `[skip ci]`, and Railway does not deploy a `main` whose head commit message
   contains `[skip ci]`. So **never fast-forward**: the branch starts at main's head, so a plain merge would
   fast-forward and leave a `[skip ci]` commit on top.
2. From an up-to-date `main`: `git merge --no-ff origin/preview/room-v5 -m "Release: the v5 character in the room
   (preview/room-v5)"`. The merge commit's own message must **not** contain `[skip ci]`.
3. Before pushing, check: `git log -1 --format=%B main | grep -c "skip ci"` prints `0`.
4. Push `main`; watch Railway deploy that merge commit; open the live room and check one desk frame and the bed at night.

## The contract
- **The body:** `web/room/char_v5.glb`, the v5 character as Tripo's rig gives it (41 bones, faces +X; G13's finger bones
  welcome, MakeHuman names `finger1-1.L` ... `finger5-3.R`). For now: preview/char-tripo-v2's
  `docs/design/char-tripo-v5/char_tripo_v5.glb`, as it is.
- **The clips:** `web/room/mh_v5/<name>.glb`, room-mh's names 1:1 (`desk_type_ik`, `desk_mouse_ik`, `desk_watch`,
  `room_window`, `room_walk`, `room_sit_down`, `room_stand_up`, `room_bed_lie`, `room_bed_wake`, `room_eat`, `room_read`,
  `room_phone`, `room_phone_scroll`, `room_drink`, `room_door`, `room_bedtime`), each one animation on the bare v5 rig in
  its own frame, as G14's `room_build/kimodo/mh_retarget.mjs` (preview/anim-kimodo ef9c0e4) writes them: the rig facing
  +X, Hip translation horizontally in the MakeHuman clips' metres. Drop new files in with the same names; nothing else
  changes. **The ones here now are placeholders**: room-mh's clips run through that script as it is at ef9c0e4.
- **The player:** `web/room/char_v5.js` turns the body to face +z (G14's "MH heading - 90 deg"), hangs its Hip straight
  under that turn (world transform kept, so the skin does not move) and carries every clip's Hip tracks into that frame;
  the bones G3's code names get the MakeHuman names (Hip -> Hips, L_Thigh -> LeftUpLeg, ..., in the rig and in the
  tracks). So `boy_mh.js` runs as on room-mh. Given by the page (`mhEnv`): `clipDir` room/mh_v5, `fixClip`, `seatUp: 0`
  (the live chair stays at 0.505 m; room-mh raised it 1.6 cm for its 0.52 m clips), `noHair` (v5 has its own).

## Contacts
`SEAT=0.505 python -m tests.visual.chair_sdf <repaired chair PLY> sdf.npz` (see `docs/design/chair-tripo/README.md` for
the PLY), then `python -m tests.visual.contacts --chair-sdf sdf.npz`: with `boy_mh.js` driving, it runs room-mh's scenario
set (desk typing / mouse / watch, read, phone, phone scroll, eating, the bedtime get-up, getting up to the window,
sitting down) on the v5 skin, vertex by vertex, against the chair (all of him) and the keyboard, mouse and controller
(hands).

## The armrests 3.5 cm further out: tried and rejected
v5's wide trousers pressed into the owner's chair's armrests in every seated clip, so each arm's pad and post was moved
3.5 cm outward (the bar under the seat stretched to keep the mount attached) at 6f2ca19. Rejected (coordinator): it no
longer reads as the chair the owner approved (from the front the pads stand off the seat on a thin stalk, from above they
sit outside its silhouette on stretched bars), and it bought about 1 mm of depth per 3.5 mm of width, nothing at all while
eating. The chair is main's again, byte for byte. The record: `arms_before_after.jpg` (the chair alone, before and after),
`arms_seated_side.jpg` (him seated, close side view, before and after). The fix is in the clips instead (G14): he sits
deeper on the seat, the chair moved toward the desk by as much, so his thighs lie between the arms.

The contact grid can now say which part of the chair a hit is in (`SEAT=0.505 python -m tests.visual.chair_sdf parts.ply
sdf.npz` stores each cell's nearest part; `tests.visual.contacts --chair-sdf sdf.npz --chair-regions`). G14's seated clips,
v5, with the original arms -> with the rejected 3.5 cm (max mm into the part):

| clip | arm posts | arm pads | seat top | seat front | frame |
|---|---|---|---|---|---|
| typing / mouse | 23 -> 11 | 20 -> 11 | 18 -> 18 | 8 -> 8 | 13 -> 0 |
| read | 29 -> 19 | 25 -> 15 | 11 -> 11 | 0 | 13 -> 0 |
| phone / phone scroll | 24 -> 12 | 20 -> 7 | 0 | 0 | 12 -> 0 |
| eating | 29 -> 29 | 25 -> 25 | 3 -> 3 | 0 | 13 -> 0 |

The rest is not a matter of width: G14's clips sit him 8-20 cm forward on the seat (seen from above, the seat is behind
his hips in typing, mouse and eating), so his thighs cross the pads' and posts' front ends rather than pressing on their
sides; eating does not change at all.

## Two page bugs behind "he raises his fists as he gets up" (fixed)
Getting up from the desk to go somewhere does not play `room_stand_up`: boy_mh.js's one-take get-up ("flow") plays the
get-up stretch of `room_bedtime` (as recorded, and mirrored as `room_getup_R`), from just before his hips rise.
- **Body-relative heights.** boy_mh.js found the clips' moments by fixed heights of the MakeHuman body: "up" = the hips
  over 0.9 m, on the bed's edge = the hips under 0.80 m with the head over 1.05 m, and so on. v5's hips stand about
  0.87 m up, so "up" was never found and the get-up began at room_bedtime's seated stretch, arms over his head. Every such
  height is now multiplied by `M.k` = this body's walking hips / the MakeHuman body's (0.977 m): 0.887 for v5. The desk
  get-up also starts 0.4 s after his hands were last over his head, whatever the clip.
- **The Hip's frame.** char_v5.js used to hang v5's Hip under the group that turns the rig 90 deg, so a clip's raw
  `Hips.position` values (boy_mh.js's hipsAt, the re-rooted get-up, the bed's mixPlace, the page's HIPS) were turned
  90 deg from where boy_mh.js samples his hips (the body's frame): the re-rooted get-up put him 2 m off, through the wall.
  The Hip now hangs straight under the body (world transform kept: what the mixer plays is the same in the room), so
  every raw value is in the body's frame by construction. One exception, on purpose: the page's own placement table
  (HIPS, where it puts his root so his hips land on the seat) gets the values turned back as they read before
  (char_v5.js `legacyHips`, boy_mh.js `pageHips`): G14 tuned v5's seat placement (pass 2, f525887) against those, and
  with the corrected values he sat up to 14.5 cm off (eating: 756 sampled vertices into the chair back).
The new segment times (s): the get-up from the desk 5.97 (was -2.1, the stretch); bed_lie: stand 0.9, edge 2.9 (were
0.35, 1.95); bed_wake: sat 4.6 (4.85); sit_down: from 2.0 (1.1); bedtime: walk 13.15, edge 17.05 (12.6, 17.85).

## The bed in the contact pass
`tests.visual.contacts` now also checks him in bed (two scenarios from the harness's "sleeping" scene, 23:00: asleep,
and waking out of it): `bed@mattress:<bone>` is skin under the mattress top (boy_mh.js's BED: 0.82 m less 1.5 cm of give,
over its footprint), `bed@duvet:<bone>` is skin over the top of the page's duvet over him (`duvet_over`; his head and
neck excluded), and `bed_gap_mm` is how far his lowest point lies over the mattress while he is on the bed (0: lying on
it; much more: floating). The duvet is the page's own: room.html's coverShape builds it every frame 3 cm over whatever
part of him is under each point, so its hills are his raised knees, hands and feet. The pose it covers asleep is
room_bedtime's last frame (boy_mh.js's `mh_sleep`), not room_bed_lie's.

## The duvet over v5 (fixed in the page)
The duvet he sleeps under (room.html coverShape) rests on a model of his body: a tube along each bone segment
(BODY_SEGS), its thickness the 97th percentile of how far his skin lies from the bone, measured once. On v5 that model
was wrong three ways, which is what made the "mountain range" even over G12's flat sleeping pose:
1. most of a limb's skin follows Tripo's twist bones (L_ThighTwist01 ... R_ForearmTwist02), and the toes' and fingers'
   skin their own bones, none of them in BODY_SEGS: the legs and forearms got the least thickness and poked through;
2. the thickness was the girth all round, in the standing bind pose: his oversized hoodie and trousers are far wider
   than deep, so (once 1 was fixed) the cover stood a hand over him and buried his head;
3. a round tube cannot cover a body that is wide and shallow: its sides poked through.
On v5 (only: the live character's duvet is unchanged) the twist bones count for their limb, the toes for the foot and
the fingers for the hand; and since bedInit first runs as he lies down under it, each segment is measured on him as he
lies: how high his skin rises over the bone, and how far to the sides; each segment is an oval of those two. Asleep:
skin through the duvet up to 145 mm (fingers, toes, thighs) -> none; lying on the mattress (gap 0).

That stopped him poking through, but the cover still followed every bulge of him, 3 cm over each (a lumpy mass: v5 is
34 cm deep lying down in that hoodie). So on v5 the cloth itself behaves like a quilt (room.html `coverCloth`): along
his length it spans taut from one high point to the next (chest, knees, feet: the upper convex hull of his outline down
each lengthwise line, sagging a quarter of the way back toward him between them); across, it spans over him the same way
and falls to the mattress within 8 cm of his side, instead of flaring wide; and it is smoothed hard along his length,
barely across (a quilt creases across a sleeper). Never into him: 0 vertices through it asleep and while he gets out.
References looked at (Unsplash licence, not committed: close crops, part of a face): photo-1531353826977 and
photo-1525169267298, a sleeper under a quilt from the side; the cover spans the body in one soft form, creased across.

## The contact table (f525887 + these fixes; max mm / frames, every 2nd frame)
`SEAT=0.505 python -m tests.visual.contacts --chair-sdf sdf.npz --chair-regions`. Chair by part; hands against the keyboard, the mouse and the tea bottle (and his head against the bottle); the bed as above.

| scenario | frames | chair (max mm / frames) by part | hands vs keyboard / mouse / bottle | bed |
|---|---|---|---|---|
| desk typing | 150 | seat 10/150, seat_front 4/55 | keyboard 3.4/1, mouse 0.9/1 |  |
| desk mouse | 120 | seat 10/120, seat_front 4/120 | 0 |  |
| desk watch | 90 | 0 | 0 |  |
| room_read | 262 | seat 17/262, seat_front 7/262 | 0 |  |
| room_phone | 326 | seat 8/326, seat_front 3/3 | 0 |  |
| room_phone_scroll | 326 | seat 8/326, seat_front 3/3 | 0 |  |
| eating at the desk | 120 | seat 3/52, seat_front 3/39 | keyboard 6/23 |  |
| bedtime: stretch, get up, to bed | 330 | base 5/1, caster 4/1, frame 17/78, lumbar 17/79, mesh 17/81, seat 33/97, seat_front 28/97 | tea_bottle 107.9/11 | mattress 40.2/15 |
| getting up to the window | 180 | arm_post 29/11, armpad 25/11, base 14/5, caster 20/4, frame 40/9, lumbar 14/4, mesh 13/4, seat 40/10, seat_front 25/9 | keyboard 4.7/1, tea_bottle 107.9/4 | mattress 573.8/3 |
| sitting down at the desk | 240 | arm_post 19/5, armpad 15/4, frame 22/27, seat 17/110, seat_front 23/108 | keyboard 14/5, mouse 15.4/2 |  |
| in bed, asleep (mh_sleep: room_bedtime's end) | 120 | 0 | 0 | 0 (gap -0 mm) |
| waking, out of bed (room_bed_wake) | 150 | 0 | 0 | duvet 5.9/4, mattress 18.5/1 (gap 40.6 mm) |

The tea bottle in the get-ups (108 mm) is his left hand passing through it as he pushes up from the desk (the bottle stands where the hand goes); "getting up to the window": his right toe enters the bed's footprint for 3 frames as he walks off past it. Not yet run against the branch without these fixes, so not attributed; noted for G14 and the prop scope.
