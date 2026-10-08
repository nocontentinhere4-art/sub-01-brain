# room/mh_mx: clips for the Mixamo-rigged character (room.html?char=mixamo)

Every clip here plays on `room/char_mixamo.glb`'s own skeleton (the Mixamo Standard Skeleton, 65 bones; `rig/autorig.sh`).

- **Mixamo captures**, baked for our chair by `room_build/kimodo/mx_build.sh` (`mx_fit.py`, rows in `mx_clips.json`):
  `room_seated_idle`, `room_mx_typing`, `room_mx_sit_to_type`, `room_mx_type_to_sit`, `room_mx_stand_to_sit`,
  `room_mx_sit_to_stand`, `room_mx_sitting*`, and the rare events `room_mx_scared` / `_angry_gesture` / `_standing_clap`.
  Each plays bone for bone as captured. The fit moves the hips onto our seat, plants the feet, places the hands, and
  swings the arms out where the sleeves would go into the hoodie. Mixamo's terms allow the animations in an app but not
  the raw files redistributed: the FBX stay out of the repository, only these baked clips are here.
- **v5's room clips carried over** by `room_build/kimodo/mx_convert.mjs` (no Mixamo capture of these yet):
  `desk_mouse_ik`, `room_walk`, `room_window`, `room_bed_lie`, `room_bed_wake`, `room_bedtime`, `room_eat`, `room_read`,
  `room_phone`, `room_phone_scroll`, `room_drink`, `room_door`. Each bone moves as the v5 joint it was fitted from, so
  the skin lands where v5's does (median 2–3 mm).

Which clip plays which slot: `room/char_mixamo.js` `ROOM` (boy_mh.js reads it through the page's env).
