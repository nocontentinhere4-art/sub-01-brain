# char-fix: status (preview/char-fix-final)

What this branch carries on top of main: the collar (hood lining, hood patches, the neck-opening band), the feet
(socks and slides, feet.mjs with its own sock/slide atlases) and one page change, the monitor glow's position.
Sheet: `char_fix_final.jpg` (numbers: `char_fix_final_numbers.txt`). Main left, this branch right in each pair.

## C's check of the first final sheet (c3cf6bd)

1. **Dark flap above his shoulder, panel "throat" (a regression, not on main): fixed.**
   It was the hood lining (raycast of its pixels, matched to the lining's grid within 0.07 mm: angles 75-95 deg round
   the neck, the rows from the hood's lip to the neck). Since 6880ee3 the lining meets the neck 4 mm over the highest
   tooth of the skin's cut edge; that tooth was taken over +-9 deg round the neck, and at his side the cut runs from
   1.444 to 1.477 m while the hood's lip is lower: the lining climbed from the lip to 1.48 m and stood up as a flap. In
   `lining.py` the tooth is now taken over +-3 deg, and the contact never rises more than 3 mm over the hood's own lip at
   that angle (+-3 deg alone left a thin sliver standing there; +-1.5 deg too). The throat is still closed: the skin
   meets the lining all round, no black under its edge (panels "throat" 3/4 right and 3/4 left from above, collar 3/4
   right and left, front).
   Not the cause (tested, each a build and the same shot): the top rim's smoothing, the nape roll's arch.

2. **Spiky dark shards in panel "nape" (from above): not changed, they are his hair.**
   The raycast of those pixels hits the head's mesh (`owner_head`, 50 of 61 rays; the rest the hoodie round it): the
   spikes are the crown of his spiky haircut seen from straight above, the dome under them his scalp's hair texture.
   They are on main too. Trimming them would change his haircut, which is the owner's call, not a script fix; nothing
   is done to them here.

## What else is still open on the character (geometry, a later commit)

- The hood lining reads as flat facets (shards) close up from above; the neck skin's cut edge is saw-toothed seen from
  above (where the lining meets it, it is covered; from straight above some teeth still show).
- A thin, faint light line remains along the hood's base on his back seated at the desk (289 white px against 1,681 on
  main in the same frame; the white saw-tooth band is gone).
- The grey patch on his back (a smooth texture island, UV 0.94-1.00 x 0.74-0.81): left as on main (the owner's call).

## Numbers (same frame, main 7f2bf6e vs this branch; `char_fix_final_numbers.txt`)

- The room from the page's camera, 5 scenes at 1280 and 390: at most 0.47% of pixels differ, mean brightness within
  0.5 levels: the room's light is unchanged.
- Seated at the desk: white flecks in the hood fold 7,820 -> 0 px; hood base on his back 1,681 -> 289; collar from
  above 7,065 -> 6,268.
- Collar: back faces seen within 15 cm of the neck over 32 close orbits 32,733 -> 8,389 px; from the desk camera 219 -> 5.

## Tests

Full suite (pytest, pipefail) on this branch: 1 failed, 1462 passed, 27 skipped. The one failure is
`test_room_renders_without_hard_errors` with main's own two hard failures, identical on main 7f2bf6e:
`walking_8_1280: desk penetration 100 sampled vertices at 7.75 s of 8` and
`eating_19_1280: desk penetration 53 sampled vertices at 2.25 s of 8` (G14 is fixing them on main).
