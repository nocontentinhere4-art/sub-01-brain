# room/mh_v5: the room clips retargeted onto v5, room-mh's names 1:1 (docs/design/room-v5/README.md)

All 16 must be here: room/boy_mh.js loads them together (a missing one is named in the console and the player stays off).

| clips | by |
|---|---|
| desk_type_ik, desk_mouse_ik, desk_watch, room_read, room_phone, room_phone_scroll, room_eat, room_drink | G14 (4cc5c5d): seat fit baked in (hips raised 10-11 cm, forward on the seat, spine forward, heels up) |
| room_window, room_walk, room_sit_down, room_stand_up, room_bed_lie, room_bed_wake, room_door, room_bedtime | G12 (to come). G10d's QA ran with local stand-ins (room-mh's clips through G14's `mh_retarget.mjs` cc57630, default options), not committed |
