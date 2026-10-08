# Hard surfaces at game quality (#98 G5)

Before/after of `web/room/room_clean.glb`, shot with `python room_build/shots.py` (fixed cameras, headless Chromium,
software WebGL, the demo server; `before/` from the GLB on `main` 5f12ea9, `after/` from this branch's build). Each
view at 1280×800 and 390×844, day (13:00) and night (21:30, room light and desk lamp on). The character sits at the
desk in the overview only; the close-ups show the room alone.

Views: `overview`, `desk`, `keyboard`, `keycaps`, `chair`, `shelf`, `bed`, `fridge_door`, `door`, `window`, `floor`,
`fan_ac`, `headphones` (`keycaps` and `door` were added after the before set was shot: after only).

## What changed (room_build/props_hard.py, tex_hard.py, hard_layout.py)
- **Floor:** Poly Haven `wooden_floor_01` (CC0, Charlotte Baglioni / Rico Cilliers) graded warm, the gaps darkened from
  its AO, worn paler patches and fine scratches drawn in, a roughness map that goes matte where the lacquer is worn;
  decals of worn lacquer under the chair, scratches by the door, scuffs off the rug.
- **Walls:** plaster with blotches and roller marks, a roughness map, rubs above the skirting, skirting boards with a
  rounded cap on both walls.
- **Materials:** every hard material carries a metallic-roughness map with micro-variation (oak with scratches and
  polished patches, plastic with smudges, painted steel with orange peel and hand marks, brushed aluminium, plaster).
  Edge wear is a tinted vertex colour on every bevel (lighter on oak and the door, grey on black plastic, dirtier on
  the white goods); post.mjs drops the attribute where nothing is tinted.
- **Desk:** bevelled top, levelling feet, a cable tray and grommet; a monitor with a 7 mm bezel, chin, power LED, a
  ported hump and joystick at the back, a flat neck on an oval foot; a tenkeyless keyboard with 87 sculpted keycaps
  (tapered, legends from an atlas, an accent Esc and Enter, a status LED, rubber feet, its cable); a mouse with a
  split, a scroll wheel and a side button; speakers with a surround, dust cap, tweeter, bass port, a volume knob and
  LED; a mug with tea in it and a handle; a ribbed pen cup with capped pens; three books from the spine atlas; a bin
  with a bag folded over its rim and stickers.
- **Chair** (node `chair`, same origin): casters with axles and hub caps, rings on the gas sleeve, a chrome lift, a
  lever with a tip, a tilt knob, a seat pan, armrest buttons, a back knob.
- **Bed frame:** drawer fronts with a shadow gap and a routed pull, a headboard with grooves and a cap, a front rail.
- **Bookshelf:** 60 books from a 16-design spine atlas (generic titles in English and Japanese, head and tail wear,
  page blocks), a leaning book, stacks, a steel bookend, magazines on top, shelf pins.
- **Fridge:** door gaskets, hinges, an aluminium badge, magnets holding a note, two stickers, dust on top, a band on
  the cup noodles.
- **Door:** moulded panel rings with raised fields, door stops, a rose and lever with a rounded end, a lock cylinder
  with a keyhole, a strike plate, three hinges with knuckles, a lipped architrave, scuffs at the foot.
- **Window:** oak architrave with a lip, a thicker sill with an apron, a fixed aluminium frame in the reveal, two
  sliding sashes with glazing beads and rubber gaskets, a bottom track with two rails, a crescent lock and pulls.
- **Air conditioner:** a seam, louvres, a flap, a display, the intake grille on top, the pipe cover.
- **Fan:** buttons, a collar, a tilt hinge, a twelve-spoke grille with four rings, rings on the back, a hub, pitched
  blades.
- **Headphones** (node `headphones`, same origin): a padded band, yokes with hinges, lathed cups with a steel rim.
- **Controller:** a face plate, lathed sticks, coloured buttons, bumpers, a light bar. **Manga** from the atlas.
- **Decals** (one alpha-blended node `decals`, no AO): dust, scuffs, scratches, a coffee ring by the mug, a wall rub, a
  note and stickers on the fridge (cat, waves), stickers on the bin (東京, onigiri) and the bed (a record).

## Budget (final build, AO baked, merged with G4's soft goods)
| | main 5f12ea9 (before both) | main 0885950 (G4 merged) | this branch (G4 + G5) |
|---|---|---|---|
| `room_clean.glb` | 4.17 MB | 5.33 MB | 6.07 MB (budget 7 MB) |
| triangles | 135k | 178k | 193k (budget 200k) |
| draw calls (primitives) | 42 | 48 | 54 (budget 60; new: alu, rubber, keycap, book, decal + the chair's steel and rubber; grey plastic is the black plastic tinted by its vertex colour) |
| prop sweep | 44 props, 0 offenders | 46, 0 | 46 props, 0 offenders (`sweep.txt`) |
