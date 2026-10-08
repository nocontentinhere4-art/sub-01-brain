# Office chair made by the owner on Tripo

Made on preview/chair-tripo; shipped with the live character by preview/room-upgrade-live (its room views and contacts:
`docs/design/room-upgrade-live/README.md`).

`chair_owner_raw.fbx`: the owner's Tripo export (79.9k tris, one mesh). `raw_clay.jpg`: six views in neutral grey.
`owner_marked_defects.jpg`: the owner circled the letter-shaped holes and dents on the backrest, the headrest and the back
of the frame; those must go. Tripo's own texture atlas is not used: it has the same letters, so the owner asked for
materials made here instead, matched to a real chair.

## Sheets
- `defects_before_after.jpg`: the backrest close up from the front, the back, 3/4 front and 3/4 back. Top: as exported.
  Bottom: repaired.
- `materials.jpg`: the finished chair in a neutral studio (3/4 front, 3/4 back, side), close-ups of the mesh, the seat
  fabric and the base, and the parts map.
- `real_reference.jpg`: the chair next to two real chairs (CC0 photos) at about the same angles.

## The pipeline
All four steps are deterministic: running them again gives the same files byte for byte.

```
node room_build/fbx2ply.mjs docs/design/chair-tripo/chair_owner_raw.fbx raw.ply      # FBX -> PLY (three.js FBXLoader)
python room_build/chair_owner_repair.py raw.ply repaired.ply --report repair.json      # the letters covered over
python room_build/chair_owner_parts.py repaired.ply parts.ply [--preview colours.ply]  # the parts, box UVs
SEAT=0.505 node room_build/build_chair_owner.mjs parts.ply <ambientCG folder> web/room/chair_owner.glb  # (live seat)
```

`<ambientCG folder>` holds `Fabric030/` and `Plastic006/`, the 1K JPG sets from https://ambientcg.com/a/Fabric030 and
https://ambientcg.com/a/Plastic006 (CC0).

## The repair (geometry)
The letters are real holes through the cushions, with inverted, non-manifold walls, so cutting them out and capping them
does not hold. Each area is covered over instead:
1. a smooth surface (a thin-plate spline) is fitted to the cushion's outer envelope, leaving out the letters' pits;
2. the raised fringes that stick out past that surface are deleted, only where the new surface will cover them;
3. a new surface is laid 1.2 mm over the old one. Over its last 2.2 cm it follows the original surface and tucks 0.8 mm
   under it, so there is no step at the edge;
4. it gets texture coordinates from the faces under it.

Nothing outside the five areas is changed.

| area | faces deleted | new faces | fit residual |
|---|---|---|---|
| backrest, front (upper) | 204 | 4986 | 0.09 mm |
| back of the mesh panel (down to the lower cross-bar: the third line of letters behind it) | 223 | 4090 | 0.19 mm |
| lumbar pad | 33 | 2544 | 0.12 mm |
| headrest, front | 0 (dents only) | 1064 | 0.16 mm |
| headrest, back (the small plate and two pits in its recess, and a spike) | 3 | 748 | 0.33 mm |

79,893 -> 92,862 faces before the decimation. Left as they are: small rough patches at the left and right edges of the
mesh panel's back. They are in the original, outside the marked areas, and are not letters. The mesh panel and the
plastic are drawn from both sides, so their small openings show the dark inside, not the room.

## The materials
`room_build/chair_owner_parts.py` splits the mesh into the parts of a real mesh chair (positions and facing in the
model's frame). Where a mesh panel meets its frame ring, the faces are cut along a smooth line a fixed distance in from
the panel's outline, so the change of material is a clean edge. Tripo's UVs belong to its atlas; each face gets a box
projection in metres instead, for tiling micro-textures.

| part | material | made of |
|---|---|---|
| backrest and headrest mesh (front and back, inside the frame rings) | `chair_mesh` | black knit drawn in the build: about 2.9 mm cells on a 4 cm tile, the darker gaps in the colour, the strands in the normal and roughness |
| seat cushion, lumbar pad | `chair_fabric` | black upholstery: ambientCG Fabric 030's weave (colour variation, normal, roughness), darkened, on a 12 cm tile |
| frame rings, spine, headrest arm, arm posts, seat pan, mechanism | `chair_plastic` | black matte plastic: a fine moulded grain drawn in the build (normal), ambientCG Plastic 006's mottled roughness (~0.7) |
| armrest tops | `chair_armpad` | the same plastic, softer and rougher |
| gas lift | `chair_lift` | black, a little glossy (as in the reference) |
| five-star base | `chair_base` | polished aluminium (as in both references) |
| casters | `chair_caster` | black nylon |

The mesh is opaque, not see-through. Tripo's backrest is a solid cushion shell, not a membrane: holes in it would show
its inside and the old surface left under the covers. The knit reads in the colour, the normal and the sheen.

The real chairs (`real_reference.jpg`, both CC0 1.0 from the WordPress Photo Directory). No CC0 or public-domain photo of a
black mesh chair with a headrest, shown whole from the front, could be found.
- "Ergonomic desk chair" by Ohidul Islam (https://wordpress.org/photos/photo/53365c4f26/): a grey mesh chair with a
  headrest in a white frame. Used for the parts and finishes: mesh back and headrest, polished aluminium base, black lift.
- A photo by Manjil Aryal (https://wordpress.org/photos/photo/54687c82e4/), cropped, with no logo in the crop: the black
  mesh and the black matte frame, seen from behind.

## In the room
`room_build/build_chair_owner.mjs` -> `web/room/chair_owner.glb`:
- scaled so the seat cushion's top is at the room's seat height: x1.241 for the live character's 0.505 m (`SEAT=0.505`;
  x1.278 for 0.52 m on preview/chair-tripo). The chair is 1.21 m tall with the headrest;
- turned 180° (Tripo's model faces +z; the sitter in the room's chair faces -z);
- its gas lift on the pivot of the room's `chair` node, then moved 5 cm back.

Then it is welded and decimated a little: 54.1k triangles, 7 materials, 1.07 MB (of which the textures are 326 KB). The
page puts it whole into the room's own `chair` node, so CHAIR, pulling, swivelling and riding are unchanged.

**Why 5 cm back:** on preview/chair-tripo the seated clips' backs and heads cleared the backrest from 5 cm back; the
chair stays built that way. Its contacts with the live character: `docs/design/room-upgrade-live/README.md`.
