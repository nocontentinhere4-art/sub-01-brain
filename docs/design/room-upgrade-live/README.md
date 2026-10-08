# Room upgrade on the live character (preview/room-upgrade-live, G10d)

Built from origin/main (f40d696), with only what the owner approved for the live site and nothing from preview/room-mh:
the live character, its clips and the live chair logic (CHAIR: pulled out, swivelled, ridden in) are unchanged.

| in | from | how |
|---|---|---|
| the Tripo props: the restored keyboard, the remodelled mouse, the controller and the monitor modelled in code, and the twenty Tripo props of `props_tripo.glb` / `props_tripo2.glb` (ramen bowl, mug, headphones, white sneakers, desk lamp, plants, box, alarm clock, backpack, floor fan, bin, speakers, skateboard, console, figure, cans, sneaker boxes, film camera) and the made-up car poster | feature/tripo-props-2 (1631de8) | merged whole, as in the room-upgrade previews |
| the woven laundry basket, the key bowl with the keys, the notebook with a pen and a pencil | preview/room-upgrade | `web/room/props_picked.glb` |
| the upright sneakers by the door | preview/room-upgrade | `web/room/sneakers_door.glb` |
| OUT: the hoodie on the door, the jeans on the floor, the T-shirt with the grey cushion; their baked floor shadows lightened out | preview/room-upgrade | `UPGRADE_DROP` in `web/room.html` |
| the owner's Tripo chair (letters covered over, own materials), its seat at the live seat height, 0.505 m | preview/chair-tripo (d5487f0) | `web/room/chair_owner.glb` (`SEAT=0.505`) into the room's `chair` node |

Not in: the code-built chair (`chair_office.glb`) and anything of preview/room-mh (G2's body and clips, G11's hair, G3's
choreography).

`before_after.jpg`: main as it is live today against this branch, 14:00, him at the desk typing: at the desk (two
angles), the room, and two views over the floor by the bed and the door.

## Contacts with the live character (vertex by vertex, every 2nd frame)
`python -m tests.visual.contacts --chair-sdf <sdf.npz>` (the chair through a 5 mm signed-distance grid,
`tests/visual/chair_sdf.py`, 2 mm tolerance; hands against the keyboard, the mouse and the controller). The same run on
main gives today's figures: its chair is tested by ray parity, and that chair is not closed (2803 of its 17856 columns
odd), so its numbers are rough; main has no separate keyboard or mouse to test.

| scenario (live clip) | frames | chair, this branch | chair, main today | hands vs keyboard / mouse, this branch |
|---|---|---|---|---|
| desk typing (type) | 150 | 0 | thighs 2.7 mm, all frames | fingers into the keys, 61 frames, 14 mm |
| desk mouse (type) | 120 | 0 | thighs 2.7 mm | 62 frames, 14 mm |
| desk watch, desk chess (m_idle) | 90 each | 0 | 0 | 0 |
| eating at the desk (Chair_Sit_Idle) | 120 | thighs 5 mm, 2 frames | thighs 9.5 mm, 43 frames | 0 |
| seated variants: leaning back, legs, drinking, phone, scratch | 60–120 each | 0 | thighs 2.3–2.7 mm, all frames | 8–111 frames, 14 mm |
| getting up to the window | 180 | 0 | thighs 7.1 mm, 35 frames | 6 frames, 14 mm |
| bedtime: get up, to bed | 330 | 0 | thighs 7.1 mm, 16 frames | 1 frame, 12 mm |
| sitting down at the desk | 240 | a foot on the base, 10 mm, 2 frames | thighs 7.1 mm, 117 frames | 96 frames, 14 mm |

(Main's "legs" figures, up to 148 mm, are its chair's open mesh fooling the parity test, not contacts; left out.)

- **The seat:** the live character sits on the old seat's height, 0.505 m over the floor, so the owner's chair is built
  at that height here (`SEAT=0.505`, x1.241, 1.21 m tall). Built at preview/chair-tripo's 0.52 m, his thighs sank 8-13 mm
  into it and tests/visual's desk scene failed its chair budget (0).
- **The keyboard:** feature/tripo-props-2's keyboard is the room's original one, cut out of the room mesh into its own
  node in the same place; the live typing clip's fingers go into its keys by up to 14 mm today too (on main it is part of
  the room mesh and not tested). The mouse and the controller are not touched.
