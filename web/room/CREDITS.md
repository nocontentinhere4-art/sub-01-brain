# Room assets: sources and licences

`room_clean.glb` is SUB-01's bedroom, built in Blender 4.2 from simple modelled parts plus a few scanned props.
The build scripts are in `room_build/` at the repository root. Everything in the file is CC0, or original work made for
this project and released under CC0.

## Modelled for this project (CC0)
The walls, floor, window with aluminium sashes, curtains, desk, monitor, keyboard, mouse, speakers, mug, pen cup, office
chair, storage bed, mattress, pillow, duvet, bookshelf and books, fridge, door, hook rail and tote bag, air conditioner,
rug, doormat and poster frames are all built from code in `room_build/build_room.py`. So are the lived-in things added in
#75: the hoodie on the door hook, the backpack, the floor cushion, the electric fan, the slippers, the laundry pinch
hanger with socks and a towel, the manga stack, the game controller (a generic shape, no maker's design), the
headphones and their wall hook, the cat figure on the window sill, the cork pinboard, the wall socket, the power strip
and the cables. The soft goods (#98) are built by `room_build/props_soft.py`: the socks (heel, toe, ribbed cuff) and
the terry hand towel on the pinch hanger, the mattress with its fitted sheet, the pillow in its case, the duvet (a
Blender cloth simulation, turned back over itself at the head end, then box-quilted), the curtains with their pencil
pleats and hems, the rug with its bound edge, the tufted floor cushion, the hoodie and the canvas tote on the door
hooks, the backpack, and two clothes: jeans in a heap by the bed's foot and a T-shirt thrown on the bed (a second cloth
simulation). The ambient occlusion is baked with Cycles into `room_ao` (second UV set). The office chair
is its own node, `chair` (origin on the floor under the gas lift), so it can be moved: it has its own materials and its
own AO (`chair_ao`, self-occlusion only), and the room's AO is baked without it.

The headphones are their own node, `headphones` (origin where the band rests on the hook), left out of the room's AO,
so that the page can take them off the hook. The things hanging on the door (hook rail, hooks, tote, hoodie) are the node
`hangers`, whose origin is the door's hinge, so that they swing with the page's opening door leaf.

The posters (`posters.png`, packed into the GLB) and the pinboard (`pinboard.png`: a calendar page, notes and doodles)
are original graphics drawn by `room_build/tex_prep.py`. Their Japanese
text is set in **Noto Sans JP** (© Adobe, SIL Open Font License 1.1). Only rendered pixels are used; the font file is not
shipped.

## The hard surfaces at game quality (#98 G5, CC0)
`room_build/props_hard.py` rebuilds the hard surfaces with more detail and `room_build/tex_hard.py` draws their textures
(both original work for this project, CC0): the desk and its steel frame, the monitor, the tenkeyless keyboard with real
keycaps, the mouse, the speakers, the mug, the pen cup, the office chair, the storage bed frame, the bookshelf and its
books, the fridge, the door with its handle and hinges, the window frame and aluminium sashes, the air conditioner, the
fan, the headphones and the controller. Edge wear sits in the vertex colours of every bevel, roughness micro-variation in
small generated maps (plastic, painted metal, brushed steel, plaster, oak) and the decals (dust, scuffs, scratches, a
coffee ring, stickers: a cat, a mountain, a 東京 badge, a star, a record, a smile, waves, an onigiri; no brands) are
alpha-blended quads from `decals.png`. The keycap legends (`keycaps.png`) and the book spines (`spines.png`: generic
titles, no real books) are original drawings; their Latin text is set in **DejaVu Sans** (Bitstream Vera licence, free
to use and redistribute), the Japanese text in Noto Sans JP as above. Only rendered pixels are shipped.

## Poly Haven (https://polyhaven.com), CC0 1.0
Textures (each recoloured or regraded in `tex_prep.py`):

| use | asset | authors |
|---|---|---|
| floor (#98 G5) | `wooden_floor_01` (graded, worn patches and scratches added in `tex_hard.py`) | Charlotte Baglioni, Rico Cilliers |
| floor (until #98) | `wood_floor` | Dimitrios Savva |
| wall plaster | `white_stucco` | Amal Kumar |
| desk, shelf, bed, door wood | `oak_veneer_01` | Jenelle van Heerden |
| bed sheet, mattress cover, pillow; the floor cushion and the T-shirt (recoloured) | `cotton_jersey` | colormass, Rico Cilliers |
| duvet | `waffle_pique_cotton` | colormass, Rico Cilliers |
| curtains; the tote's canvas (recoloured) | `rough_linen` | colormass, Rico Cilliers |
| rug | `poly_wool_herringbone` | colormass, Rico Cilliers |
| chair fabric, desk mat (normal map) | `jersey_melange` | colormass, Rico Cilliers |
| socks (normal map) | `knitted_fleece` | colormass, Rico Cilliers |
| hand towel | `terry_cloth` | colormass, Rico Cilliers |
| hoodie | `jogging_melange` | colormass, Rico Cilliers |
| the hoodie's ribbed hem and cuffs (normal map) | `ribbed_corduroy` | colormass, Rico Cilliers |
| backpack (normal map) | `bi_stretch` | colormass, Rico Cilliers |
| jeans | `denim_fabric_05` | colormass, Rico Cilliers |

Models:

| use | asset | authors |
|---|---|---|
| desk lamp | `desk_lamp_arm_01` | Yann Kervran, Kuutti Siitonen |
| floor plant | `potted_plant_02` (soil replaced by a simple disc) | Rico Cilliers |
| desk succulent | `potted_plant_04` | James Ray Cock |
| wall clock | `wall_clock` | PierreB3D |
| alarm clock (window sill) | `alarm_clock_01` | Yann Kervran, James Ray Cock |
| box on the bookshelf | `cardboard_box_01` | Rahul Chaudhary |
| sticky notes | `office_notepads` (one stack) | Ulan Cabanilla |

Poly Haven assets are CC0: https://polyhaven.com/license

## The prop sweep
Every prop is placed from its real bounding box (an imported file's origin can be far from its mesh), and before
anything is joined the build measures every prop: none may reach into the window wall or the back wall (the desk lamp
keeps 1 cm off both), and each one's lowest vertex must lie within 2 mm of its support (desk, floor, sill, shelf; wall
items within 2 mm of the wall). No prop may enter the places the page hard-codes (his place at the window, the delivery
bag's and the tea bottle's spots on the desk), his walking graph (the page's waypoints, links and standing places, 22 cm
each side) or the door's swing. The report lists every prop and every offender (`room_build/out/sweep.txt`); any
offender stops the build.

## Rebuilding
From `room_build/`, with Blender 4.2 and Node 22:

    python ph.py tex 2k wooden_floor_01
    python ph.py tex 1k white_stucco oak_veneer_01 cotton_jersey waffle_pique_cotton rough_linen poly_wool_herringbone jersey_melange
    python ph.py tex 1k knitted_fleece terry_cloth jogging_melange ribbed_corduroy bi_stretch denim_fabric_05
    python ph.py model 1k desk_lamp_arm_01 potted_plant_02 potted_plant_04 wall_clock alarm_clock_01 cardboard_box_01 office_notepads
    # fonts/NotoSansJP.ttf (from google/fonts, ofl/notosansjp) is needed for the poster text
    python tex_prep.py                       # (runs tex_hard.py too: the hard surfaces' textures and atlases)
    blender -b -P build_room.py -- --sweep   # a few minutes (the two cloth simulations): only the prop sweep (out/sweep.txt), no bake, no export
    blender -b -P build_room.py          # the cloth simulations plus the two AO bakes
    npm install && node post.mjs out/room_raw.glb out/ao_raw.png ../web/room/room_clean.glb out/ao_chair.png
    python shots_soft.py --glb ../web/room/room_clean.glb --tag after   # fixed-camera renders (docs/design/room-soft)
    python shots.py --out ../docs/design/room-hard/after      # fixed-camera screenshots of the hard surfaces (from the repository root: python room_build/shots.py)

## His motion (`boy_moves.glb`, #76)
New clips for the first character (`boy.glb`, its own 24-bone rig): in the room they take over walking, sitting at the
desk (typing) and lying with the phone (`?moves=old` shows the first clips); the other clips are in the file for later.
- **Quaternius, Universal Animation Library (Standard)** (https://quaternius.com/packs/universalanimationlibrary.html),
  obtained 2026-10-02. Licence, recorded on that date: the archive's own `License.txt` reads "CC0 1.0 Universal (CC0 1.0)
  Public Domain Dedication, https://creativecommons.org/publicdomain/zero/1.0/ / Models by @Quaternius", and the pack
  page says "CC0 License"; the site-wide Quaternius Asset License v1.0 (https://quaternius.com/license.html, last
  updated 2026-08-28; its § 7: the version in effect when the assets were obtained governs) allows incorporating the
  assets, original or modified, into a product and distributing that product without attribution, and forbids
  redistributing them as a standalone asset or pack. The clips here are retargeted onto this project's rig inside the
  site's own file (`boy_moves.glb`), not offered as a pack; credit to Quaternius is given anyway. Clips used:
  `Idle_Loop` → `stand_idle`, `Walk_Loop` → `walk`, `Sitting_Enter` / `Sitting_Exit` / `Sitting_Idle_Loop` → `sit_down_chair` / `stand_up_chair` / `sit_idle_upright` (and, raised to the mattress,
  `sit_down_bed_edge` / `stand_up_bed_edge` / `sit_edge_idle`), `PickUp_Table` → `take_item`, `Interact` → `door_open_pull`;
  `Crouch_Idle_Loop` is a key pose of `crouch_drop`.
- **Keyed for this project** (original keyframes and IK; the standing and seated poses they start from are UAL's,
  under the terms above): the bed set (`lie_back_idle`, `lie_side_left/right`,
  `roll_*`, `sleep_breathing*`, `lie_down_from_edge`, `get_up_to_edge`, `lie_phone`), `type`, `mouse`, `walk_start`,
  `walk_stop`, `turn_in_place_*`, `lean_on_sill`, `stretch_arms_up`, `scratch_head`, `look_around`, `crouch_drop`,
  `put_down`, `sit_lean_back`, `sit_eat_chopsticks`, `sit_drink`.

They are made on an authoring body, not shipped: a MakeHuman / MPFB 2 body (CC0 base mesh and `game_engine` rig, given
the first rig's bone names and rest frames) built by `room_build/build_boy.py`. The UAL clips are retargeted onto it
(T-pose correspondence, feet pinned by IK) and the keyed poses are set on it by IK against its own skin (the mattress,
the seat, the keys). `room_build/boy_post.mjs` then carries every clip onto the first rig: each bone turns in the world
as on the authoring body from its rest; the hips are scaled by the leg ratio and set from his own lowest skin (the
floor, or the mattress when lying); when seated his hips go up to his seat height and his legs reach down by IK. It
also writes `docs/motion/deform_check.json`, a skin check of every clip on `boy.glb`.

Rebuild, from `room_build/` (Blender 4.2 with the MPFB extension and the MakeHuman system assets; UAL's glTF at
`$UAL`):

    node boy_ref.mjs                     # the first rig's rest pose and palms -> out/boy_ref.json
    blender -b -P build_boy.py           # the authoring body -> out/boy2_raw.glb, out/boy2_bind.json
    node boy_post.mjs                    # -> ../web/room/boy_moves.glb, ../docs/motion/deform_check.json

## The first character
`boy.glb` and the clips `boy_*.glb` (shown by default) are the earlier AI-generated character (Meshy, via Higgsfield;
generated content under those services' terms, not a Creative Commons licence), and `hand_phone.glb` the
phone-gripping hand (GPT Image + Tripo, via Higgsfield); the clips are Meshy library animations re-rigged on its
skeleton.

## His movement and the things he handles (#63)
No animation clips were added. The clips are the ones already in `web/room/` (`boy_*.glb`, the same rig). Everything new is
procedural code in `web/room.html`, written for this project and released under CC0:
- additive layers on top of the clips (breathing, weight shifts with the feet planted, head and neck gaze, idle variants,
  the lean on the window sill, eating, drinking, the door, carrying the bag);
- small props modelled in code from three.js primitives: the delivery bag, a bento box (its top is drawn on a canvas),
  chopsticks, a bread roll and the bakery's paper bag, a bottle of green tea, headphones, and the door leaf that opens
  (it uses the room's own `door` material from `room_clean.glb`).

The standing pose is the first frame of `boy_door.glb`'s clip. GLB size change: none (0 bytes).

## Food (#63, part 2): Kenney "Food Kit" 2.0, CC0 1.0
`food.glb` packs these models from Kenney's Food Kit (https://kenney.nl/assets/food-kit, created by Kenney, www.kenney.nl;
licence: Creative Commons Zero, as stated in the kit's `License.txt`): `bowl-broth` (ramen), `bowl-soup` (curry),
`bowl`, `plate-rectangle`, `sushi-salmon`, `sushi-egg`, `maki-salmon`, `pizza-box`, `pizza`, `rice-ball` (onigiri),
`croissant`, `bag`, `bag-flat`, `chopstick`. Unmodified apart from scale and, for the konbini's bag, a white material
set in `web/room.html`. Rebuild (from `room_build/`, with the kit unzipped somewhere):

    node build_food.mjs "<kit>/Models/GLB format" ../web/room/food.glb      # 84 KB

## The Tripo props: made with Tripo (paid API)
`props_tripo.glb` holds four props **made with Tripo (paid API)** (https://www.tripo3d.ai): text-to-model, model
`P1-20260311` (low-poly), PBR textures at standard quality, generated on 2026-10-04 from text prompts asking for plain
objects with no logos or text. They are AI-generated content under Tripo's terms of service, not a Creative Commons
licence. Each prop and its Tripo task id:

| prop | where | task |
|---|---|---|
| ramen bowl with chopsticks: tonkotsu, chashu, ajitama egg, nori, in a matte stoneware bowl | the ramen he eats at the desk (it replaces Kenney's `bowl-broth`; the empty bowl is still Kenney's `bowl`) | `4a044baf-40b1-4c6f-a5f6-e290acc4c5b2` |
| ceramic mug | the mug on the desk (the modelled one is cut out of the static room by the page) | `277633c0-2bfe-4b38-ae60-0bcaa9445a0f` |
| over-ear headphones | the pair on the wall hook (inside the room's `headphones` node; the pair he wears is still procedural) | `6a2cac63-a839-4d0c-8e0f-53c67e641321` |
| white sneakers | a pair on the floor in the front right corner | `62e8af56-3302-4a6a-9fe4-d4af8bd5d821` |

`room_build/build_tripo.mjs` scales each to real size (origin at the centre of its base), turns it, cuts its textures
to 1024 px WebP and meshopt-compresses the lot (3.8k–4.6k triangles a prop). The page puts them in place
(`web/room.html`, "Tripo props"); `?props=old` shows the earlier ones. The raw downloads are not committed. Rebuild
(from `room_build/`, with the four raw GLBs in a folder named as in the script):

    node build_tripo.mjs <folder> ../web/room/props_tripo.glb

## The Tripo props, second batch: made with Tripo (paid API)
`props_tripo2.glb` holds sixteen props **made with Tripo (paid API)** (https://www.tripo3d.ai), model `P1-20260311`, PBR,
standard textures, generated on 2026-10-04 (AI-generated content under Tripo's terms of service, not a Creative Commons
licence). Most came from text prompts asking for plain, unbranded objects. The desk lamp and the floor plant came from
images (image-to-model): Poly Haven's own renders of the CC0 models they replace, `desk_lamp_arm_01` (Yann Kervran,
Kuutti Siitonen) and `potted_plant_02` (Rico Cilliers), CC0 1.0. The figure is an original character and the
skateboard's graphic an original pattern; no brands, logos or characters of others.

| prop | where (it replaces) | task |
|---|---|---|
| clamp desk lamp | the desk's back left (the Poly Haven desk lamp, hidden) | `ff1d73a1-cbf7-47fe-8017-214e00df5bf1` |
| potted plant | the floor by the window (the Poly Haven plant, hidden) | `35c33d17-2985-4143-a53e-1b2eff7cd136` |
| taped cardboard box | on top of the bookshelf (the Poly Haven box, hidden) | `c7eb9d15-e87c-42b1-9420-fa48cd38006e` |
| twin-bell alarm clock | the window sill (the Poly Haven alarm clock, hidden) | `b683843e-2e74-4474-808b-5a8c6d7b415f` |
| aloe in a terracotta pot | the desk (the Poly Haven succulent, hidden; its saucer, which came out floating, is left out) | `37835eed-7fb1-472b-a2de-bbb6b152ca68` |
| black canvas backpack | by the bed (the modelled one, cut out) | `b7b15962-24d0-4d99-85c7-05d09cf4748b` |
| floor fan | by the door (the modelled one, cut out) | `5b704311-1409-4b14-ba67-a71988047dc1` |
| waste bin with a liner | under the desk (the modelled one and its stickers, cut out) | `b52a9f88-6d94-4244-a2f1-19f37250e268` |
| bookshelf speaker, used for the pair | the desk (the modelled pair, cut out) | `ae7531ac-6f5e-4ca1-bc85-3fc761223e7b` |
| skateboard | new, on the floor by the door, wheels up | `fd5e06a2-38c1-402c-bbe1-78bb7deb0d2e` |
| game console (generic) | new, the desk's back | `b08f7166-7a2e-4538-86e6-e3a05838fb38` |
| anime-style figure (original) | new, the window sill | `2bb87361-92e0-48a7-a780-10c7a7455ad9` |
| three energy drink cans (unbranded) | new, on the fridge | `4a5e3826-fca8-42a4-bcae-251189326032` |
| stack of sneaker boxes | new, by the door | `827927f2-220e-4563-bd36-3a1680d02a34` |
| 35mm film camera (no brand) | new, on the desk's books | `0f650a9e-edaa-4828-94f2-b9f959671e75` |

Generated and not used (paid for, left out): a mouse (`7f6dd270-5668-4826-82ed-090af0124e8b`; the mouse modelled in code
below took its place, built to the profile his hand is solved against); a first desk lamp, whose shade floated off its arm
(`21b4442f-4fc2-408b-81a5-d911bb16337a`); a first plant, with purple leaves (`2df53e11-6008-4f00-9d52-2b3452078f93`); a
keyboard, built on a wedge with letters on its keys (`64db3634-167d-498a-8589-9140e01b7782`; the modelled keyboard stays,
his typing is aimed at it); an office chair (`5af3f609-8dc7-4815-996f-6c9cd2f27247`; the modelled chair stays, his sitting
poses and resting hands are fitted to it); a game controller (`39586f31-cc3e-488b-8454-533df47ffed9`) and a computer monitor
(`40a67c5e-c2f0-4b5f-8a05-b6cba29fc020`), both replaced by ones modelled in code (below). His phone stays too: the one he
holds is the hand-and-phone mesh above.

`room_build/build_tripo2.mjs` scales and turns each, puts it in its place in the room and joins them all into one mesh
(the lamp kept apart, out of its own light's shadow map) with one material, its maps packed in atlases (a 512 px tile per
prop), WebP, meshopt. The page puts it in and hides or cuts out what it replaces (`web/room.html`, "Tripo props");
`?props=old` shows the earlier room. Rebuild, from `room_build/`, with the raw GLBs in a folder:

    node build_tripo2.mjs <folder> ../web/room/props_tripo2.glb controller,monitor

The keyboard is the tenkeyless one modelled in `room_clean.glb` (above); the page cuts its triangles out of the joined
static mesh into a group of its own named `keyboard` (origin: the middle of F and J on the desk top), so nothing about its
look changes. The mouse on its pad (`mouse.glb`, `room_build/build_mouse.mjs`) is modelled in code for this project, CC0,
to real sizes: a generic mouse, 11.8 × 6.2 × 3.6 cm, no logo, with a sharp split between its buttons, the wheel in a
slot, a parting seam all round over an upright skirt and a chamfered base. Its micro-texture is ambientCG's **Plastic 016 A**
(https://ambientcg.com/a/Plastic016A, CC0 1.0), its roughness and normal maps (`room_build/desk_pbr.mjs`). Tried and not
installed: a full-size keyboard modelled in code (`room_build/build_keyboard.mjs`), and a keyboard and mouse made with
Tripo (paid API, image-to-model from renders of the code-made ones; keyboard task `0c5caa4a-9169-4ed7-bbfc-f90cd06883be`,
mouse task `926e444c-4a59-4b34-b318-db6d3f72f95a`, fitted by `room_build/build_kbm_tripo.mjs`); the Tripo mouse is kept
as `mouse_tripo.glb` for comparison (`?debug&kb=tripo`).

The game controller (`controller.glb`) and the monitor (`monitor.glb`), both from `room_build/build_desk_tech.mjs`, are
modelled in code for this project, CC0, with no maker's shape or logo. The controller is a generic modern gamepad, 15.4 ×
10.4 × 5.6 cm, resting on its grips: two analogue sticks with knurled concave caps on rubber boots, a D-pad, four plain face
buttons, two menu buttons and a round centre button, bumpers and triggers, matte dark plastic with glossier buttons. The
monitor's panel is fitted around the page's live screen (SURF_monitor, 0.64 × 0.37 m) with 6 mm bezels, a 14 mm chin and a
glossy rim. Behind it are a tapered rear housing with vent slots, a port bay and a VESA plate, a hinge, a flat dark-metal
neck with a cable hole and a flat rounded foot. Its cable runs down behind the neck and over the desk's back edge. Both use
ambientCG's **Plastic 016 A** (CC0 1.0) via `desk_pbr.mjs`. When the screen is off, the page gives it an anti-glare finish
that faintly reflects the room.

The car poster (`poster_car.webp`, `room_build/poster_car.py`) is an original drawing, CC0, of no real car or maker; the
page paints it over the record sleeve in the posters atlas.

## The bottle of green tea: made with Tripo (paid API)
`bottle.glb` is the bottle on the desk **made with Tripo (paid API)** (https://www.tripo3d.ai): image-to-model, model
`v3.1-20260211`, PBR, detailed textures, `face_limit` 2500, generated on 2026-10-06 (AI-generated content under Tripo's
terms of service, not a Creative Commons licence). Task `dcee8d97-ef32-4d6a-974e-ad0a53a41bec`. It takes the place of the
last prop still modelled in `web/room.html` itself — four cylinders making a translucent body, a green band, a cone
shoulder and a white cap — which `?bottle=old` brings back. 2 372 triangles, 96 KB.

It was generated from a reference built for it, not from a photograph as found. The photograph is **"Bottle of Water"**
by Jiafei Slay Queen (https://commons.wikimedia.org/wiki/File:Bottle_of_Water.jpg, Wikimedia Commons, **CC0 1.0**): a
plain, label-free, unbranded clear PET bottle with a white screw cap, shot upright and front-on. On top of it, made
here: the bottle filled to the neck with green tea, and a label of leaves, a cream band and a thin rule wrapped round
the middle with cylindrical foreshortening. The label is an original design — no text, no logo, no brand, no real
product, and no person appears in the photograph. The reference is not committed.

`room_build/build_bottle.mjs` scales it by its width to a 3.2 cm radius (21.6 cm tall), turns it, puts its origin where
the page holds the prop (the base 0.08 m under it, so it stands on the desk top), sets the metallic factor to 0 — Tripo
baked a metal look into its ORM map, and a PET bottle is not metal — and cuts its maps to 1024 px colour with the
metal/roughness and normal maps at 512, WebP, meshopt. The page loads it into the same `PROP.bottle` group, so taking
it, drinking and putting it back are unchanged. The raw download is not committed. Rebuild, from `room_build/`:

    node build_bottle.mjs <raw bottle.glb> ../web/room/bottle.glb

Generated and not used (paid for, left out): a first bottle (`a9e6a027-4f9f-4f55-9761-65bdc50fa5de`), made from a
reference that kept the photograph's half-full, clear-walled upper body; it came back dented, with the cap swallowed
into the body. Before and after, the budget and what is still wrong: `docs/design/prop-bottle/README.md`.

Credits: 80 of a budget of 150 (40 for each of the two tasks, the rejected one and the one in the room). The Tripo
balance went 1180 → 1100.

## His motion: clips generated with NVIDIA ARDY (#98 G3)
`boy_m_*.glb` (listed in `boy_m_manifest.json`) are motions generated from text prompts with **ARDY**
(https://github.com/nv-tlabs/ardy, NVIDIA; the paper's authors are credited there), checkpoint
`nvidia/ARDY-Core-RP-20FPS-Horizon40`, on one RunPod GPU pod (`room_build/ardy/`: `job.sh`, `gen.py`, `specs.json` and
`specs_v2.json` with the prompts; `README.md` to rebuild), then retargeted onto `boy.glb`'s rig by
`room_build/ardy_to_boy.mjs`. The character is the same original one; the clips move his bones only. Licences:
- ARDY's code: Apache-2.0.
- The ARDY checkpoint: the **NVIDIA Open Model License** (https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/):
  commercially usable; "NVIDIA claims no ownership rights in outputs. You are responsible for outputs and their subsequent
  uses." The generated clips are outputs, so they may ship in this public, commercial web app; the model itself is not
  redistributed here. Attribution, as the licence asks for distributed models (kept here for clarity): "Licensed by NVIDIA
  Corporation under the NVIDIA Open Model License".
- ARDY's text encoder is LLM2Vec (McGill-NLP, MIT) on top of Meta Llama 3 8B Instruct (**Llama 3 Community License**,
  https://llama.meta.com/llama3/license): used offline as ARDY's text encoder, on the pod; not distributed; nothing of
  it is shipped (only the text prompts went through it). The weights were taken from the public `NousResearch/Meta-Llama-3-8B-Instruct` re-upload, whose four
  safetensors shards have the same SHA-256 as `meta-llama/Meta-Llama-3-8B-Instruct`'s (verified on the pod, `job.sh`);
  no Hugging Face token was used. "Built with Meta Llama 3."
- The clips' retargeting, `boy_motion.js` (the procedural layer: breathing, weight shifts, foot and hand IK, eyes, the pop
  killer) and the scripts above are made for this project, CC0.
No Mixamo or other non-redistributable animation is used.

## Map card
The map of his neighbourhood (room card and `/life`) is © OpenStreetMap contributors (ODbL,
https://www.openstreetmap.org/copyright). It is drawn from `web/tokyo_area.json`, one static extract made by
`python room_build/osm_area.py` (one Overpass API query, run by hand); no map tiles are loaded.

## The earlier room
`room.glb` (shown with `?room=old`) is the earlier AI-generated single mesh (Meshy, via Higgsfield).

## The view out of the window (#98 G7)
`web/room/window_view.js` draws the outside on the glass marker (`SURF_window`): a parallax shader that casts each view
ray from the room's camera through the glass onto photographic plates behind it (the neighbourhood by day and at night,
the far skyline, a utility pole, a real sky), so the view has true depth from every camera. The plates in
`web/room/window/` are cut out and prepared by `room_build/window_cards.py` from these sources (all free for any use;
each licence was read from the Commons API's `extmetadata` / Poly Haven's `/info` at fetch time and is recorded with the
source's URL and checksum in `web/room/window/plates.json`):

| plate | source | author | licence |
|---|---|---|---|
| `mid.webp`: the neighbourhood by day (an elevated view over the ward next to Kichijōji) | [Suginami City 2024-05-06.jpg](https://commons.wikimedia.org/wiki/File:Suginami_City_2024-05-06.jpg) | ウィキ太郎 | Public domain |
| `mid_n.webp`: the neighbourhood at night, with its real lit windows (`mid_l.webp` marks them) | [Blue illuminated buildings in Tokyo.jpg](https://commons.wikimedia.org/wiki/File:Blue_illuminated_buildings_in_Tokyo.jpg) | Syced | CC0 |
| `far.webp`: the far skyline at twilight (the water and the expressway cropped away) | [Illuminated buildings at twilight in Minato-ku, Tokyo, view from Rainbow Bridge (2016-12-10 by xegxef @Pixabay 2086645).jpg](https://commons.wikimedia.org/wiki/File:Illuminated_buildings_at_twilight_in_Minato-ku,_Tokyo,_view_from_Rainbow_Bridge_(2016-12-10_by_xegxef_@Pixabay_2086645).jpg) | xegxef | CC0 |
| `sky.webp` row 0: clear day | [Kloofendal 43d Clear (Pure Sky)](https://polyhaven.com/a/kloofendal_43d_clear_puresky) | Greg Zaal (All) | CC0 |
| `sky.webp` row 1: partly cloudy day | [Kloofendal 48d Partly Cloudy (Pure Sky)](https://polyhaven.com/a/kloofendal_48d_partly_cloudy_puresky) | Greg Zaal (Original), Jarod Guest (Sky edits) | CC0 |
| `sky.webp` row 2: overcast | [Kloofendal Overcast (Pure Sky)](https://polyhaven.com/a/kloofendal_overcast_puresky) | Greg Zaal (All) | CC0 |
| `sky.webp` row 3: sunset | [Belfast Sunset (Pure Sky)](https://polyhaven.com/a/belfast_sunset_puresky) | Greg Zaal (Processing), Dimitrios Savva (Photography), Jarod Guest (Sky edits) | CC0 |
| `sky.webp` row 4: dusk (blue hour) | [Qwantani Dusk 2 (Pure Sky)](https://polyhaven.com/a/qwantani_dusk_2_puresky) | Greg Zaal (Photography), Jarod Guest (Processing) | CC0 |
| `sky.webp` row 5: night | [Kloppenheim 02 (Pure Sky)](https://polyhaven.com/a/kloppenheim_02_puresky) | Greg Zaal (Original), Jarod Guest (Sky edits) | CC0 |

Wikimedia Commons CC0: https://creativecommons.org/publicdomain/zero/1.0/ · the Suginami photograph was released into the
public domain by its author (Commons `{{PD-self}}`). The Rainbow Bridge photograph is a Pixabay picture from 2016, when
Pixabay's licence was CC0; the Commons copy carries that licence. Poly Haven assets are CC0: https://polyhaven.com/license.
Only the skies' upper hemispheres are used (±70° of azimuth, -2..50° of elevation, with the sun or the moon kept out of
the crop; the shader draws its own). The photographs contain no readable signage; the skyline's landmark tower appears as
photographed. The utility pole and its cables (`near.webp`) and the rain's noise texture are drawn from code, original work
for this project, CC0. The sources themselves (~120 MB) are not committed: `python room_build/window_cards.py --fetch`
re-downloads them (Wikimedia rate-limits shared addresses; the script waits and retries).

The weather shown is **not real weather**: the server has no weather feed, so `weatherAt()` is a deterministic daily
pattern over Tokyo time (about a fifth of the hours wet, a third overcast), the same for every viewer and never presented
as a forecast or an observation.

## The room upgrade (preview/room-upgrade-live)
Owner-approved pieces from the props previews and the clothes the owner turned down taken out:
- `props_picked.glb` (`room_build/pick_props.mjs`, from preview/props-hard's `props_clutter.glb`): the laundry hamper
  (Poly Haven `wicker_basket_02`, Kuutti Siitonen), the key bowl (`wooden_bowl_02`, Kuutti Siitonen) with the keys in it
  (modelled for preview/props-hard), and the notebook (`binder_notebook`, DaDrood; its emblem cloned out) with a pen and a
  pencil (`stationery_supplies`, Mateusz Sadek; the printed maker's name cloned out). All CC0 1.0 (https://polyhaven.com).
- `sneakers_door.glb` (`room_build/pick_sneakers.mjs`, from preview/props-soft's `room_clean.glb`): the pair of worn canvas
  sneakers standing by the door, modelled in code for preview/props-soft (`props_soft.py`), CC0, no brand.
- Taken out at load (`web/room.html`, UPGRADE_DROP): the hoodie on the door, the jeans on the floor, and the T-shirt with the
  grey floor cushion under it. Their baked shadows are lightened out of the floor's occlusion map.

## The owner's chair
- `chair_owner.glb` (`room_build/fbx2ply.mjs` -> `chair_owner_repair.py` -> `chair_owner_parts.py` -> `build_chair_owner.mjs`):
  the office chair the owner generated on Tripo (https://www.tripo3d.ai), used under Tripo's terms of service; the
  owner's export is `docs/design/chair-tripo/chair_owner_raw.fbx`. The letter-shaped holes and dents Tripo put on the
  backrest, the lumbar pad, the headrest and the back of the mesh panel are covered over with new smooth surface; nothing
  else in the model is changed. Scaled to the live seat height (0.505 m), turned to face the desk and placed in the room's
  `chair` node.
  Tripo's texture atlas is not used. Its materials are made for this project: a black knit mesh, black matte plastic
  (a moulded grain drawn in the build) and soft arm pads, a black gas lift, a polished aluminium base, black casters, and
  black upholstery from ambientCG's **Fabric 030** (CC0 1.0, https://ambientcg.com/a/Fabric030); the plastic's roughness
  from ambientCG's **Plastic 006** (CC0 1.0, https://ambientcg.com/a/Plastic006). Matched to two CC0 photos
  (`docs/design/chair-tripo/real_reference.jpg`, WordPress Photo Directory: Ohidul Islam, Manjil Aryal).

## Character v5 in the room (preview/room-v5, an integration preview)
| file | source | licence |
|---|---|---|
| `char_v5.glb` (for now the placeholder `docs/design/char-tripo-v5/char_tripo_v5.glb` from preview/char-tripo-v2, turned to face +z) | the v5 character: AI-generated with Tripo (tripo3d.ai, paid API), an original fictional young man, no brands | Tripo's terms of service |
| `char_v5.glb`'s socks and slides (preview/char-fix-feet, `room_build/charfix/feet.mjs`) | the owner's own Tripo character (preview/char-owner-tripo), its feet transplanted onto v5's | Tripo's terms of service |
| `mh_v5/*.glb` (the room clips retargeted onto v5, by G14; the same names as preview/room-mh's `mh/`) | preview/mh-motion's clips, retargeted | as their sources |
| `mh/props_g2.json` (the activity clips' placeholder props and the door / window keys) | preview/mh-motion `room_build/mh/glb/clips_g2/props_g2.json` | made for this project, CC0 |
| `boy_mh.js` (the clip player and the room choreography: desk modes, sit / stand, the chair pulled and pushed, routes) | preview/room-mh (G3, G10d) | this project's code |

## The same character on a standard 65-bone skeleton (room.html?char=mixamo, preview/mixamo-wiring)
| file | source | licence |
|---|---|---|
| `char_mixamo.glb` (v5 auto-rigged onto the standard 65-bone skeleton by `room_build/rig/autorig.sh`, offline: the same mesh and textures, a new skeleton and weights; docs/design/mixamo/README.md) | `char_v5.glb` | as `char_v5.glb` (Tripo's terms of service); the rig is made for this project |
| `mh_mx/room_seated_idle.glb`, `mh_mx/room_mx_*.glb` (the desk captures baked for this character and our chair by `room_build/kimodo/mx_build.sh`) | the captures listed in `docs/design/mixamo/README.md` ("Sources and licences"), as `mh_v5/`'s desk clips | as recorded there: the raw files are not redistributed (they stay out of the repository), only these baked clips |
| `mh_mx/` the other clips (`desk_mouse_ik`, `room_walk`, `room_window`, `room_bed_*`, `room_bedtime`, `room_eat`, `room_read`, `room_phone*`, `room_drink`, `room_door`) | `mh_v5/`'s clips carried onto this skeleton by `room_build/kimodo/mx_convert.mjs` | as their sources |
| `char_mixamo.js` (the loader and which clip plays which slot) | preview/mixamo-pipeline (G12, G20), this branch | this project's code |
