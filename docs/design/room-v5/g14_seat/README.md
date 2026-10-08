# G14: v5 sat deeper and centred on the owner's chair (clear of the arm pads)

Measured in the page (room-v5 + `tests/visual/contacts --chair-regions`, and a probe of his hips in the chair's frame,
`page_probe.json`): before, his hips sat 7.4-13 cm to his right of the seat's centre (eat 13), so the right thigh's
trousers (outer side at x ~ +0.27 m) went into the right arm pad (pads at x ~ +-0.26 m, y 0.63-0.67, z -0.13 ... +0.11 in
the chair's frame), and 5-7 cm further forward on the seat than the backrest fit in G14's clips assumes.

One pass, then one lateral calibration in the page:
- the clips (web/room/mh_v5, mh_retarget.mjs `shift` / `handShift`): hips and feet 6 cm back on the seat and re-centred
  to his left (type / mouse / watch 1.4-1.7 cm, read 0.6, phone 2.0, eat 7.0: the page's own placement moves him by part
  of it); in read / phone / phone_scroll / eat his hands and the world props (room/mh/props_g2.json) move with him; type /
  mouse keep their hands (the page re-pins them to the keys / mouse anyway);
- the page (`env.seatIn` 0.06 in room.html, boy_mh.js roll()): the chair rolls 6 cm further in at the desk.

Result in the page (max depth, mm, per region of the chair; `contacts_regions.json`, typing re-run with the scenario that
types: `contacts_typing.json`):

| scenario | hips in chair frame x / z (m), before -> after | arm pads | seat cushion | seat front | elbows L / R (deg) |
|---|---|---|---|---|---|
| desk typing / mouse | +0.077 / -0.052 -> 0.000 / -0.006 | 18 (left thigh, first try) -> 0 | 23 | 18 | 53 / 60 (before 57 / 54) |
| room_read | +0.066 / -0.089 -> 0.000 / -0.043 | 12 -> 0 | 18 | 7 | 119 / 87 (unchanged) |
| room_phone, phone_scroll | +0.080 / -0.146 -> 0.000 / -0.100 | 14 -> 0 | 8 | 3 | 73 / 88 (unchanged) |
| eating at the desk | +0.130 / -0.113 -> 0.000 / -0.123 | 29 -> 0 | 3 | 3 | 46 / 89 (unchanged) |

No contact with the arm pads, posts, backrest or base in any seated scenario of G14's clips. Left: cushion compression up
to 23 mm (typing, right thigh) and the seat front 18 mm; the page's mouse re-pin puts the right hand 13 mm into the mouse
in the typing scenario. The elbow angles at the desk are the page's wrist re-pin onto the room's keyboard (unchanged by this
pass; not 100-115 deg: flagged). Stills: `*_side.png`, `all_side.jpg` (G14's render scene with the chair where the page has
it relative to his hips; read, type, mouse, watch / phone, phone_scroll, eat).

## Pass 2: `test_visual.py::test_room_renders_without_hard_errors`, scene desk_14_1280 (mouse mode)

Measured in the page: the left forearm (mouse mode, hand not pinned) crossed the desk's front edge 3.6 cm below its top
(elbow at y 1.00 m, z -0.79); the page pins his seated hips to its own height (boy_mh.js seatHeight), so the clips' seat
lift did not raise him and the right thigh sat 23 mm in the cushion. desk_type_ik / desk_mouse_ik (mh_retarget options,
final2.py): the left arm swung up about its shoulder-wrist axis until the elbow is 4 cm higher (`elbowUp`; the hand keeps
its place and turn: no stretch), the hips 2.1 cm higher over the feet (the page's floor lift carries him up), the feet 2.5
cm forward and the left foot 2 cm more (`feetForward`, `leftFootForward`: the calves clear of the seat front). Lateral
centring, the 6 cm depth and env.seatIn 0.06 unchanged.

| desk_14_1280 (test_visual) | before | after |
|---|---|---|
| desk (sampled vertices) | 208 (L_ForearmTwist01) | 0 |
| chair (sampled vertices) | 211 (R thigh 167, L calf 39, R calf 5) | 6 (L calf) - still over the budget of 0 |

| contacts --chair-regions, max mm | before | after |
|---|---|---|
| desk typing: seat / front / arm | 23 / 18 / 0 | 10 / 4 / 0 |
| desk mouse: seat / front / arm | 23 / 18 / 0 | 10 / 4 / 0 |
| left forearm below the desk top (page probe) | 36 | 0 |
| hips in chair frame (x, y, z) | 0.000, 0.656, -0.006 | 0.000, 0.677, -0.006 |
| elbows L / R, mouse (deg) | 53 / 61 | 65 / 64 |

Unchanged by this pass: room_read seat 17 mm, the page's mouse re-pin 12.5 mm into the mouse, G12's sit-down / get-up.
