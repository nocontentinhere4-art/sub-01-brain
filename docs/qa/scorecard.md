# Room realism scorecard (issue #98, G8)

How close `/room` is to a **photograph of a real Tokyo bedroom**, area by area, scored 1–5 against written criteria,
from the fixed-camera shots of `tests/visual/` (headless Chromium, software WebGL, the same poses and light every run).
The owner's brief (2026-10-02, via the coordinator): "deve essere più reale possibile … puntiamo al realismo massimo".
So the bar is photorealism, not a nice game: every area also lists what gives it away as CG (plastic materials,
uniform textures, floating objects, clean edges, flat light). The reference under each area is what a 5 looks like;
it is a description, not a shipped image. Shots are in a run's `tests/visual/out/` (`python -m tests.visual.harness`);
contact sheets of the run this scorecard was made from are in `docs/qa/shots/`. The routed defect list is
`docs/qa/defects.md`.

Scale: 1 obviously CG at a glance · 2 CG at a glance, some real-looking parts · 3 passes as a render of a real room,
CG on a second look · 4 passes as a photo at the page's camera distances, CG only in close-ups · 5 passes as a photo
in the close-ups too.

## Scores on `main` (5d9a934, 2026-10-03 evening; the previous score in brackets where changed)

| area | score | one line |
|---|---|---|
| character face | 1 | a photo projected on a faceted low-poly head; painted eyes, shard hair; CG at any distance where the face is readable |
| character body (clothes, hands, feet) | 1 | glossy black hoodie and trousers (PVC), faceted sleeves and socks, mitten hands, no cloth motion; the phone-grip mesh alone looks real |
| character motion | 3 | he sits, types, lies, walks, eats, breathes and glances; asleep under the duvet with side turns (#108); #80's typing clip keeps the forearms off the desk; still stiff: no secondary motion, hands hover over the keys, toes under the floor |
| soft goods (duvet, pillow, curtains, hanger socks, towel, cushion, hoodie on the door) | 3 (2) | #107: real socks with heel and ribbing, a terry towel, a box-quilted duvet with a turned-back fold, pleated curtains, a sculpted hoodie, tote, backpack, jeans and T-shirt; left: a flat oval pillow, a sawtooth fold edge, translucent sock cuffs, quilt seams as hard ribs when the duvet lies over him |
| hard surfaces (furniture, desk items, shelf, fridge, door) | 4 (3) | #110: keycaps, book spines, a monitor chin, coffee in the mug with a ring decal, edge wear and decals; the desk set passes at the page's distances; left: uniform plaster, no skirting or trim |
| lighting (day, dusk, night, lamp, screens) | 2 | day and dusk are pleasant renders: flat fill, no bounce colour, no contact shadows; night is black; the lamp blows the hood out; the monitor is pure white |
| window and outside | 3 (1) | #113: photographic CC0 plates with true parallax, real skies by the sun's elevation, lit windows at night, haze, the room reflected in the glass; left: the reflection washes the view out at grazing angles, the wires are drawn lines, and the plates' light does not follow the room's hour exactly |
| **overall** | **2.4 (1.9)** | the room is getting there (a real view, real cloth, worn hard surfaces); the character and the light still give it away at a glance |

Measured on the same run (`tests/visual/out/full3b/results.json`, 58 shots): bed/chair/desk penetration 0 in every
shot (the desk since #80's typing clip; now a hard check); left toes 1.2 cm below the floor when standing; while he
walks to the desk the monitor is off and the camera stays on the overview; 64 draw calls and 226k triangles in the
overview (was 52 and 168k before #107/#110; the room GLB is 6.4 MB, all room assets 9.3 MB without the old
`room.glb`); night (23:00, lights off) mean luminance 10/255 with 12 % pure-black pixels at 1280 and
18 % at 390; the only blown-out pixels are the monitor's white page (4 % at 1280, 9 % at 390); animate() 0.16–0.27
ms/frame; 55 draw calls, 171k triangles; no z-fighting flagged; no JS errors; the character's 2048² texture has
anisotropy 1 (room textures 8). Every separate prop rests on its support (gap ≤ 4 mm) or hangs on a wall.

## What reads as CG today (the owner's five tells)
- **Plastic materials:** the hoodie and trousers (baked gloss on black), the white socks (flat shading), the bottle's
  perfectly even PET, the desk mat, the phone body; the skin has no roughness variation (`closeup_face_14.png`,
  `door_8_1280_char.png`).
- **Uniform textures:** one plaster texture over four metres of wall with no marks, switch-plate smudges or corner
  wear (128 texels/m); oak veneer repeating on the desk, shelf, bed and door; the duvet's waffle weave identical from
  edge to edge; the rug a flat herringbone plane.
- **Floating objects:** none by measurement (rays from every separate object find its support within 4 mm), but he
  *looks* like he floats: no contact shadow or occlusion where his feet meet the floor, his hips the chair or his body
  the duvet; the duvet does not dent under him (`closeup_bed_14.png`).
- **Clean edges:** the desk top, shelf, bed frame, fridge and door have knife edges without a bevel highlight; wall
  corners are perfect 90°; no skirting board, no gap under the door, no misaligned poster; curtains hang in equal
  cylinders; cables are smooth tubes.
- **Flat light:** a hemisphere fill with no colour bleed (the floor's warm bounce does not reach the walls), the sun's
  patch is a soft additive rectangle, corners are dark only where AO was baked; the lamp is a point light with no
  visible filament, bulb glow or warm pool on the desk; the monitor's light on his face is a single tint.

## Criteria and reference, per area

### Character face
Criteria: (a) smooth head and jaw at the 0.5 m close-up, no facets; (b) eyes with a cornea highlight, lids, lashes and
a blink; (c) brows and lips as geometry or alpha cards, not only paint; (d) skin with pores, roughness variation and a
subsurface tint on ears and nose; (e) hair as cards or strands with an anisotropic highlight and a believable hairline;
(f) the identity kept (the owner keeps this character).
Reference (a 5): a portrait photo of a young man indoors by window light: soft skin with visible pores, moist eyes
catching the window, individual hair strands at the fringe.
On main: ~31k triangles for the whole body with one 2048 texture; flat triangles visible on cheeks, jaw and neck in
`closeup_face_14.png`; hair as spiky black shards without specular; eyes painted but readable; identity fine. **1**.

### Character body
Criteria: (a) cloth reads as cloth: matte cotton hoodie, soft trouser folds, roughness ≥ 0.8, no baked specular, a
fabric normal map; (b) clean silhouette, no faceting on sleeves and legs; (c) hands with fingers; (d) feet, socks and
slides with round cross-sections and ankle wrinkles; (e) the cloth moves with him (sleeves, hood) and dents where he
sits or lies.
Reference: a photo of someone in a black hoodie and sweatpants on a bed: matte fabric, visible seams, soft folds at the
elbows and ankles, five fingers, socks that wrinkle.
On main: glossy black hoodie and trousers with baked highlights (`door_8_1280_char.png`), faceted sleeves, faceted
white socks (`closeup_feet_14.png`), mitten hands (`closeup_bed_14.png`, `closeup_hands_14.png`); the `hand_phone.glb`
grip is good (`closeup_grip_14.png`). **1**.

### Character motion
Criteria: (a) no frozen poses: breathing, weight shifts, glances; (b) transitions walk–sit–lie without pops; (c) no
interpenetration with the bed, chair, desk or floor; (d) relaxed seated and lying poses (arms, hands, head); (e)
secondary motion: hair, hood and sleeves settle after a move; (f) the camera shows what he does.
Reference: video of a person at a desk: typing hands, a slouch that changes, feet flat on the floor, a head turn to the
window; asleep: under the duvet, on his side, slow breathing, the duvet moving with the breath.
On main: breathing, glances and idle variants exist; bed/chair penetration 0; forearms through the desk top and toes
through the floor (measured); since #108 he sleeps under the duvet, head in the pillow, slides parked, a side pose now
and then (`closeup_bed_14.png`, `closeup_side_14.png`); since #104 the camera waits on the overview until he reaches the
desk; no secondary motion; the follow camera at the desk still looks at the back of his head (`desk_14_1280.png`). **3**
(was 2 on 00af116).

### Soft goods
Criteria: (a) sculpted forms: a pillow with a dent, a duvet with folds and a soft edge over the frame, socks and a towel
that hang and bend; (b) fabric normal maps at ≥ 300 texels/m with variation (creases, a worn patch); (c) no box or
cylinder silhouettes on cloth; (d) curtains with irregular folds, a hem and a slight sway.
Reference: a photo of an unmade single bed in a Tokyo flat: a crumpled duvet, a dented pillow, a towel over a hanger.
On main: duvet and sheet textures are good (374 and 311 texels/m); since #108 the duvet lifts over him and the pillow
dents under his head when he lies down, but the empty bed's pillow is still a hard rounded box and the lifted duvet
has smooth bumps without creases (`closeup_duvet_14.png`, `closeup_bed_14.png`); the hanger socks are 10-sided straight cylinders with flat-cut ends and a second cylinder
for the foot, the towel a flat box, the pegs boxes (`closeup_socks_14.png`); the hoodie and tote on the door are slabs;
the curtains are equal ribbed cylinders. **2**.

### Hard surfaces
Criteria: (a) bevelled edges that catch light; (b) PBR materials with normal and roughness maps and *variation*: wear
on the desk edge, scuffs on the floor, fingerprints on the fridge, dust on the shelf; (c) desk clutter with real
shapes; (d) baked AO in corners and under objects; (e) trim: skirting, window reveal, door frame, a gap under the door.
Reference: a photo of a real desk set-up: a lamp with visible joints and a slightly scuffed shade, speakers with a
grille, a keyboard with worn key caps, a mug with a tea ring.
On main: the Poly Haven props and the modelled desk items hold up at close range (`closeup_desk_19.png`); AO is baked;
but every edge is knife-sharp, wood and plaster are uniform, walls are bare white with no skirting, books are coloured
blocks, the mouse a blob, the bin a cylinder. **3**.

### Lighting
Criteria: (a) every hour readable: shapes visible at night, whites not clipped in the morning; (b) key, fill and rim:
window light by day with coloured bounce off the floor, lamp and ceiling light in the evening with a warm pool, screen
glow on his face; (c) soft shadows with contact under him and the props; (d) exposure that follows the hour without
flattening the room; (e) a glow on the lamp bulb and the screens, a faint bloom, no pure 255 whites except light
sources.
Reference: a photo of a bedroom at night: moonlight and city glow through the window, a dim blue fill on the floor, the
phone lighting his face, the rest dark but legible; by day: a warm bounce on the wall beside the window.
On main: 08:00, 14:00 and 19:00 are pleasant renders (`door_8_1280_clean.png`, `desk_14_1280_clean.png`,
`eating_19_1280_clean.png`; ≤ 0.2 % blown pixels without the monitor in frame) but flat: no bounce colour, no contact
shadows; the monitor's page is unlit 255 white; the lamp blows the hood out (`eating_19_1280_char.png`); 23:00 with
the lights off is almost black (`sleeping_23_1280_clean.png`); no AO on the character. **2**.

### Window and outside
Criteria: (a) a city with depth: parallax layers, haze, rooftops, water tanks, windows with structure; (b) a sky with
moving clouds and a sun or moon of the right size; (c) glass with reflection, dirt and a sill that catches light; (d)
weather (rain) that reaches the room; (e) night windows and a tower light.
Reference: a photo out of a Kichijōji window: dense low-rise blocks, a tower, haze towards the horizon, a glint and
the room's reflection on the glass.
On main: the sky gradient, sun, moon and stars are pleasant (`phone_23_1280_clean.png`); the city by day is flat grey
cuboids and two grey towers on one plane (`closeup_socks_14.png`, `closeup_grip_14.png`); no glass reflection; rain is
a uniform in the shader. **1**.

## How to re-score
Run `python -m tests.visual.harness --out tests/visual/out` on the branch (or `--full`), read `report.md`, compare
the same shots against the criteria above, and change only the scores whose evidence changed. Every re-score gets a
dated row in `docs/qa/history.md`.
