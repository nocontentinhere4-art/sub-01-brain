# Visible defects on `main`, routed (issue #98, G8)

From the core and full runs of `tests/visual/` on `main` 5f12ea9 / 00af116 (2026-10-02), sent to the coordinator the
same evening and routed by them (G2: 1–6; G3: 7–8; #63: 9; G6: 10, 15–18, 21, 22; G4: 11–13; G5: 14; G7: 19–20).
The bar is photorealism (owner's brief): the "what reads as CG" list in `scorecard.md` adds the general tells
(plastic materials, uniform textures, no contact shadows, knife edges, flat light) that no single item below carries.
Measured numbers come from `tests/visual/out/results.json`; the shots named are in the run's output directory.
Status: open unless marked. Re-checked on `main` 9353bda (2026-10-03, full matrix, 0 hard failures): items 9 and 21
are **fixed**. Re-checked on `main` 5d9a934 (2026-10-03 evening, after #107 soft goods, #113 window, #110 hard
surfaces, #80 motion): items 7, 11, 12, 13, 14, 19 and 20 **fixed or largely fixed**; new items 23–26 below. Items 7 and 8 become hard CI checks (budgets.json `desk_vertices`, `below_floor_vertices`
→ 0) once G3's fix lands.

## G2 · character asset (`web/room/boy.glb`)
1. **Faceted face.** Flat triangles on cheeks, jaw, neck and collarbones at the 0.5 m close-up (`closeup_face_14.png`);
   the head shares one 2048² texture with the whole body. Needs more head triangles and a normal map, or a smoothed head.
2. **Hair** is spiky flat black shards with no specular, jagged silhouette.
3. **Hoodie and trousers** are glossy black with baked highlights (PVC/latex look) and flat-shaded facets on the sleeves
   and back (`door_8_1280_char.png`, `eating_19_1280_char.png`).
4. **Faceted white socks** on his feet (`closeup_feet_14.png`); the slides are fine.
5. **Mitten hands** on the own mesh (`closeup_bed_14.png`); the `hand_phone.glb` grip is good (`closeup_grip_14.png`).
6. **Texture anisotropy 1** on the character's map (room textures use 8): blur at grazing angles.

## G3 · motion (`web/room/boy_motion.js`, the room's hook block)
7. ~~**Forearms through the desk top** in the sitting pose: 12–50 of ~17,700 sampled vertices inside the desk slab
   (left forearm mostly).~~ **Fixed by #80** (5d9a934): the typing clip keeps the forearms above the desk, 0 vertices
   inside it in every desk shot; `desk_vertices` is now a hard budget (0) in `tests/visual/budgets.json`.
8. **Toes under the floor** when standing at the door and the sill: left toes/foot 1.2 cm below (3 sampled vertices);
   still 3 on 5d9a934.
27. **Typing hands hover** (`closeup_hands_14.png`, #80's `type` clip): both hands float 3–5 cm above the keys with
    splayed mitten fingers; the right hand never reaches the mouse. Better than the forearms through the desk (7),
    but a contact pose (fingertips on the keys, wrists on the desk) is what reads as real.
9. ~~**Sleeping on top of the duvet**, fully dressed, slides on, arms stiff, a hand on the belly.~~ **Fixed by #108**
   (9353bda): under the duvet, head denting the pillow, slides parked by the bed, a side pose now and then; the duvet
   lifts over his limbs and breathes (`closeup_bed_14.png`, `closeup_side_14.png`, `sleeping_14_1280_char.png`); bed
   penetration 0 with the duvet's weight counted. Left: the duvet's lumps read as smooth bumps (no fold creases).
10. **The follow camera at the desk** looks at the back of his head over the monitor (`desk_14_1280.png`); his face is
    never seen in the most common activity.
21. ~~**The camera jumps to the monitor before he reaches the desk.**~~ **Fixed by #104** (9353bda): the snapshot now
    sends `path` and `path_to` while he walks; in `walking_*` the monitor is off and the follow camera stays on the
    overview until he arrives (the harness records `screen.monitor_on` and `screen.camera` per shot). Was: the page's
    `!life.path` guards were always true because the server never sent `path`.

## G4 · soft goods (`room_build/props_soft.py`)
11. ~~**Hanger socks are tubes**.~~ **Fixed by #107** (5d9a934): swept socks with heel, toe and ribbed cuff, a terry
    towel with drape (`closeup_socks_14.png`). Left (see 23): the dark pair's cuffs render pale grey / translucent and
    the hanger ring draws doubled.
12. ~~**Pillow** is a hard rounded box; the **duvet** has one fold.~~ **Largely fixed by #107**: box-quilted duvet
    with a turned-back fold, mattress with a fitted sheet, pillow in its case. Left (see 24): the empty pillow is a
    flat oval slab with no loft, and the fold's edge is a sawtooth.
13. ~~**Hoodie and tote on the door** are slabs; curtains are uniform ribbed cylinders.~~ **Fixed by #107**: sculpted
    hoodie with pocket and cuffs, canvas tote, pencil-pleat curtains with hems, jeans and a T-shirt added.
23. **Sock cuffs read translucent, hanger ring doubled** (`closeup_socks_14.png`): the dark socks' cuffs render pale
    grey as if the inside faces showed through (back faces or a missing thickness), and the hanger's ring appears as
    two concentric rings (a duplicated or offset mesh).
24. **Flat pillow and sawtooth fold** (`closeup_duvet_14.png`): the empty pillow is a 4–5 cm oval slab (a pillow in
    a case has loft and a crease at the opening); the duvet's turned-back fold has a jagged zigzag edge where the
    fold meets the top sheet.
25. **Duvet over him: quilt seams as hard ribs, a body part poking through** (`closeup_bed_14.png`, sleeping@14): when
    the page lifts the new duvet over him, the quilting seams render as thick dark bevelled channels following his
    body, and a dark shape (his foot or the parked slides) shows through the lifted cloth at the foot end. The
    page's lift (#108) and the new 89k-triangle duvet (#107) need tuning together (G4 + #63).

## G5 · hard surfaces (`room_build/props_hard.py`)
14. ~~Nits: the mouse is a smooth blob, the books are coloured blocks, the bin a plain cylinder, no skirting board.~~
    **Largely fixed by #110** (5d9a934): keycaps, book spines, a monitor chin, a mug with coffee and a ring decal,
    edge wear, a real bin (`closeup_desk_19.png`). Left: no skirting board or trim along the walls; wall plaster still
    one uniform texture (128 texels/m).

## G6 · rendering (`web/room_post.js`, the renderer/lighting block)
15. **Night is black**: at 23:00 with the lights off the canvas has mean luminance 10/255, 12 % pure-black pixels at
    1280 and 18 % at 390 (`sleeping_23_1280_clean.png`, `sleeping_23_390_clean.png`); floor, bed and he barely read.
16. **The monitor's page is pure white**: the fake Wikipedia page is an unlit 255-white texture (`toneMapped:false`), so
    it reads as a blown rectangle in every desk shot (4 % of the canvas at 1280, 9 % at 390; all of the "blown" pixels
    the harness counts). A monitor in a game is a little dimmer and off-white, with glow and a faint reflection.
    (Correction to the first list sent: the morning itself does not clip; 08:00 without the monitor in frame has
    ≤ 0.2 % blown pixels.)
17. **No contact shadows or AO on the character**: he floats visually on the floor and on the bed.
22. **The desk lamp blows out the hoodie**: with the lamp lit (eating or research after dusk) the hood and the shoulder
    nearest the lamp go to flat white (`eating_19_1280_char.png`); the lamp's intensity plus the hoodie's glossy
    material (defect 3) clip under ACES. Shared with G2.
18. **Only a far overview camera** when he is not at a screen: he is ~70 px tall at 1280; a medium shot never happens
    (the harness's `_char.png` shots show what one would look like).

## G7 · window (`web/room/window_view.*`)
19. ~~**Flat city**: grey cuboids on one plane.~~ **Fixed by #113** (5d9a934): photographic CC0 plates with true
    parallax, real skies by the sun's elevation, lit windows at night, haze (`closeup_socks_14.png`, `closeup_grip_14.png`).
20. ~~**No glass**.~~ **Fixed by #113**: the glass reflects the room from a cube probe by Fresnel. See 26.
26. **Glass reflection washes the view out at grazing angles** (`window_8_1280_char.png`): seen along the glass from
    the sill, the left half of the window is a pale grey wash (the lit wall's reflection) and the view only reads on the
    right; a real window at that angle shows a faint reflection over a still-visible view. Also the wires across the
    view read as drawn lines (no thickness, no sag variation).

## Not a defect, noted
- Z-fighting: none flagged by the flicker test (desk at 14:00, 5 frames, camera creeping 0.7 mm a frame).
- Props: every separate object rests on its support (gap ≤ 4 mm) or hangs on a wall; the merged room props are checked
  by the build-time sweep in `room_build/build_room.py`.
- Performance: animate() 0.27 ms per frame at 1280 and 1.2 ms under a 4x CPU throttle at 390; 55 draw calls and 171k
  triangles with the lamp lit. FPS cannot be judged here (software WebGL).
