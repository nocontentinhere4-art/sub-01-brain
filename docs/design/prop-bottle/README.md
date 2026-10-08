# The bottle of green tea

The bottle on the desk was the last prop still modelled in code: four `THREE.Cylinder` primitives (a translucent body, a
flat green band, a cone shoulder, a white cap) built in `web/room.html`'s prop block. It is now a model made with Tripo
(paid API), like the other twenty. The task id and what it is made of are in `web/room/CREDITS.md`, "The bottle of green
tea".

- `1280_<shot>.webp` (before above, after below) and `390_<shot>.webp` (before left, after right): the room with the
  modelled bottle (`?bottle=old`) and with the generated one, at 14:00, him at the desk, at the visual QA's two sizes.
  Shots: `overview`, `desk_bottle` (over the mouse), `bottle_close`, `drink` (the bottle at his mouth, the drink variant
  forced and stepped to the same frame on both pages). Made by `python room_build/tripo_stills.py --set bottle`.
- `drink_contact.webp`: the deepest frame of the bottle against his chin, in profile — see "Contact" below. It is not a
  pair: the moment it catches does not fall on the same frame twice, so there is no honest before to put beside it.
- Both pages park the idle variants (`variant('none', 60)`: an unknown name holds the slot and does nothing) before the
  static shots, so each pair is the same pose and the same moment.

Budget, measured in the page (overview at 1280, `?bottle=old` against the generated bottle):

| | before | after |
|---|---|---|
| triangles in the scene | 281.0k | 283.1k (+2.1k) |
| the prop alone | 272 | 2 372 |
| draw calls per frame | 79 | 76 (−3) |
| textures | 130 | 133 |
| download | | +96.3 KB (`bottle.glb`) |

The four primitives were 272 triangles and four draw calls; the generated bottle is one mesh, one material and three
maps, so the scene gains 2.1k triangles and loses three draw calls.

## It drops into the place the page already kept
`room_build/build_bottle.mjs` fits it to the contract `web/room.html` and `room_build/build_room.py` already hold it to:
one node `T_bottle`, in metres, long axis +y, cap up, origin where the page puts the prop. Measured in the page:

| | asked | built |
|---|---|---|
| base under the origin | 0.080 m | 0.0800 m |
| radius | near 0.032 m | 0.0320 m |
| height | ≤ 0.30 m | 0.2160 m (the modelled one was 0.221) |

It is scaled by its width, not its height: `build_room.py`'s `KEEP["the tea bottle's spot"]` reserves an 8 cm square at
(−0.83, −0.85) and his right hand is solved against a 3.2 cm radius, so the radius is what has to hold. The bottle fills
x (−0.862, −0.798) and z (−0.882, −0.818) of that box and stands 21.6 cm, against the 30 cm the box allows. Nothing in
`drinkFrom()`, `grab()` or `drop()` changed: the generated mesh goes inside the same `PROP.bottle` group, so his taking
it, drinking and putting it back run on the geometry they always did. `?bottle=old` brings the modelled one back.

## Contact
`tests/visual/contacts.js` now also measures the bottle (`tea_bottle`), and against his head as well as his hands,
since he brings it to his mouth. Its depth is the vertical one it uses for the desk things, which means little for a
21 cm solid, so the shapes were compared a second way: in one run, with one hand path, every hand and head vertex was
measured against **both** radius profiles — the generated mesh's own, and the four primitives' — so only the shape
differs (`seated: drinking`, the forced variant, every frame):

The drink is not the same twice — the idle and gaze state when the variant starts varies — so it was run twelve times.
Over the runs where contact happened at all:

| | generated | modelled | difference |
|---|---|---|---|
| deepest hand vertex (every run) | 31.0 … 31.3 mm | 30.4 … 30.9 mm | +0.4 mm |
| deepest head vertex (about half the runs) | 9.2 … 19.3 mm | 7.5 … 16.2 mm | +1.1 … +4.6 mm |

Both are pre-existing: the modelled bottle does the same, in the same frames. Neither is this prop's doing, and
neither got materially worse, but neither is clean either.

- **The hand.** His right hand already passes through the bottle as he picks it up and puts it down, up to the full
  radius — the fingers curl to their own radius, not the bottle's, and the reach target in `drinkFrom()` is only
  offset from `BOTTLE_AT`. The generated bottle is 0.4 mm deeper, the 1 mm it is wider. What changed is how plainly it
  reads: the modelled bottle was 55 % transparent, so fingers inside it looked like fingers seen through glass, and the
  generated one is opaque.
- **His face.** In about half the runs the bottle reaches his chin as he tips it up, for a dozen frames around the
  middle of the drink. The generated bottle goes 1–5 mm deeper than the modelled one did, because its cap and neck are
  wider: 19.4 mm radius against the modelled cap's 13.5 mm. `drink_contact.webp` is the deepest frame of one run, in
  profile; from the page's own cameras the bottle hides most of it.

Both belong to the grip and the tip in `drinkFrom()`, the same kind of thing as the eating arm noted in
`docs/design/tripo/README.md`. Fixing them means posing the fingers against the bottle's radius and stopping the tip
short of his chin, which is character work, not prop work.

Known: Tripo bakes an opaque surface, so the clear PET and the tea inside are painted on, not refracted — the bottle
reads as a filled bottle rather than a transparent one. The lower body keeps a slight waviness where the reference's
grip ribs were. The generated material came back with metalness ≈ 0.8 baked into its ORM map; a PET bottle is not
metal, so the build sets the metallic factor to 0.

## Tripo credits (G15)
Generation: `room_build/tripo_gen.py` (one guarded task per run; the proxy supplies the key, nothing is stored). Its
`image` subcommand now takes an optional JSON of extra body fields, so a newer model and better textures are a file
away. Budget 150 credits, 80 spent, 70 left:

| task | what | credits |
|---|---|---|
| `a9e6a027-4f9f-4f55-9761-65bdc50fa5de` | first try, rejected (see below) | 40 |
| `dcee8d97-ef32-4d6a-974e-ad0a53a41bec` | the bottle in the room | 40 |

The first try came from the photograph with the tea and the label composited onto it as it stood: a half-full bottle,
the clear upper half against a grey backdrop. Single-image reconstruction had nothing to find a silhouette in, and it
came back dented, with the cap swallowed into the body and the waterline modelled as a sloshing diagonal. The second
reference fixed the input rather than the settings: the bottle filled to the neck (as a sealed one is), an exact
silhouette, the label wrapped with real cylindrical foreshortening, and a flat backdrop.
