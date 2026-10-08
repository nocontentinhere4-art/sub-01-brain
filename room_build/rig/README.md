# Putting v5 on a standard skeleton

The animations that worked first time were real captures; what kept failing was carrying them across onto our own
79-bone rig and patching the result in the page. These scripts take the character to an auto-rigger so the captures
can play on the skeleton they were recorded for.

Run from `room_build/` (they import the packages in `room_build/node_modules`).

| step | script | what it does |
|---|---|---|
| 1 | `static.mjs char_v5.glb out.glb` | drops the skin, the animations and the compression; keeps the bind pose as drawn (skinned meshes ignore their node transforms, so no parent scale is baked in); feet on y = 0, 1.75 m tall, facing +Z |
| 2 | `simplify.mjs in.glb out.glb RATIO` | meshoptimizer simplify (0.4 → ~160k triangles) |
| 3 | `rot.mjs in.glb out.glb DEG` | turns him about Y |
| 4 | `rigcheck.sh file.glb` | uploads to Tripo and runs the free rig-check |
| 5 | `to_obj.mjs in.glb dir/` | OBJ + MTL + textures, for Mixamo's auto-rigger (FBX, OBJ or ZIP only) |
| — | `bones.mjs file.glb` | lists a rigged file's joints |

## What we found, 2026-10-06

- **Tripo** (`/v3/animations/rig`, `spec: mixamo`, model `v1.0-20240301`): rig-check refused the model in every
  orientation but one — facing −X after step 1, i.e. `rot.mjs … -90`. It then rigged the full 402k-triangle mesh for
  25 credits, but the biped rig has **22 bones and no fingers**. Unusable for a character whose hands are on a mouse,
  a keyboard and a phone all day.
- **Mixamo's auto-rigger** offers the Standard Skeleton (65) with fingers — the skeleton the twenty captures in
  `mocap_src/mixamo/` were recorded on. It needs the owner's Adobe login, so the upload is a ZIP of step 5's output
  (160k triangles, textures at 2048² JPEG, 4.4 MB) that the owner uploads by hand.

Nothing generated here is committed: the GLBs, the ZIP and the rigged outputs are working files.
