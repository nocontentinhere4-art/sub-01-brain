# room/desk_states: the seated states' own clips (room.html?char=mixamo&anim=sova)

`index.json` maps a slot of `room/desk_states.js` (`SLOTS`) to its own clip here: `{"clips": {slot: "file.glb"},
"once": [slots that play through once], "seat": {slot: m}}`. Each file has one animation on `room/char_mixamo.glb`'s
skeleton (`mixamorig:*`; `char_mixamo.js` `fixClip` takes it as it takes `room/mh_mx/`), seated on our chair. A slot
not listed plays its stand-in from `room/mh_mx/`.

The clips here are G23's (preview/sova-phone-src, docs/qa/sova/desk/, 94a87c9: desk v3, thinking v6 and frustrated V1 v5 off the armrests, seat_happy for a won game). Preview branch only: their
licence is pending, so they never go to main.
SovaSims animations used with the author's permission (confirmed by the owner, 2026-10-08).
