# room/desk_states: the seated states' own clips (room.html?char=mixamo&anim=sova)

`index.json` maps a slot of `room/desk_states.js` (`SLOTS`) to its own clip here: `{"clips": {slot: "file.glb"},
"once": [slots that play through once], "seat": {slot: m}}`. Each file has one animation on `room/char_mixamo.glb`'s
skeleton (`mixamorig:*`; `char_mixamo.js` `fixClip` takes it as it takes `room/mh_mx/`), seated on our chair. A slot
not listed plays its stand-in from `room/mh_mx/`.

The clips here are G23's (preview/sova-phone-src, docs/qa/sova/desk/, 94a87c9: desk v3, thinking v6 and frustrated V1 v5 off the armrests, seat_happy for a won game). Preview branch only: their
licence is pending, so they never go to main.
SovaSims animations used with the author's permission (confirmed by the owner, 2026-10-08).

## The bed layer (`bed/`, room/boy_mh.js `bedStep()`)
G23's Sova bed clips (preview/sova-phone-src `docs/qa/sova/mattina/bed`), each placed on the room's bed by its own pose (`bedPlace()`), crossfaded over 0.8 s with the page's lie and sleep clips underneath (a clip that does not load is left out; none loaded: the page's clips).
- **Phone in bed:** `bed_phone_watch_portrait` for a short (or anything else), `bed_phone_watch_landscape` for a video, `bed_phone_typing` for a chat. The phone hangs on his left hand by each clip's grip (`bed/index.json`); the page's `holdPhone()` stands aside while it does. With this body the page's own step shows no phone at all, so the layer shows it while a clip holds it.
- **Asleep:** `sleep_side`; after 40-90 s `sleep_roll_to_back` (once), then `sleep_back` and `sleep_back_idle` taking turns.
- **Left out:** `bed_phone_lift`. Its source lies across a bed with the feet on the floor; laid along this mattress its legs went 7122 sampled vertices into it.
- **Measured** (the page's bed counter over a sweep of each clip, `tests/visual/test_bed_layer.py`): 0 in the bed for the other seven. The phone's screen faces his face (0.96), 22 cm from it.
- **The duvet asleep** follows his skin (the page's `coverShape()`, every 0.1 s, from boy_mh.js `env.cover`). On his back (`sleep_back`, `sleep_back_idle` and the end of `sleep_roll_to_back`) the clips have his head and shoulders up at an angle, the head about 15 cm toward the foot from the pillow's centre (head 1.02-1.04 m up, on his side 1.14 m), and his knees up: the duvet covers him from the chest and mounds over the knees, so the head and shoulders look propped out of it. The duvet is right for that pose; the pose wants a refit (the head down onto the pillow): G23.
- **The phone in bed from a desktop:** the follow camera keeps its angle and comes in slowly to 2.6 m from him (at 2.1 his feet left the 1280x800 frame; `docs/qa/launch/bed_phone_desktop_1280x800.jpg`) (3 s in, 2 s out: room/glance_cam.js `BED`); phones are framed close already.
