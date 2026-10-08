# v5's feet: white socks in black slides (G19, preview/char-fix-feet)

The owner's Tripo reference (preview/char-owner-tripo, `docs/design/char-owner-tripo/char_owner_tripo.glb`) has the
socks and slides he wants. Its feet are transplanted onto v5's, as a deterministic script that only touches the feet and
ankles, so it composes with G10d's collar fix (run it after the collar script):

```
node room_build/charfix/feet.mjs <in.glb> <out.glb> [--report report.json] [--debug dir]
# this branch: node room_build/charfix/feet.mjs <main's web/room/char_v5.glb> web/room/char_v5.glb
```

Its input `room_build/charfix/ref_feet.glb` (committed, 1.4 MB) is made from the reference by
`node room_build/charfix/ref_feet.mjs char_owner_tripo.glb room_build/charfix/ref_feet.glb` (the reference cut under
16 cm, its 15 texture charts packed in one 2048² atlas). Both scripts are deterministic (two runs, same md5).

## What the script does
1. **Split** each reference foot into sock and slide along the 0.5 contour of its smoothed base colour (one shared
   boundary: no gap, no overlap where sock meets strap and footbed). The trouser cuff is dropped.
2. **Close both.** The reference is one surface: no foot under the strap, no footbed under the foot. A tube bridges the
   sock's heel loop and toe loop (the hidden sock under the strap and the foot), 2.5 mm under the strap and on the
   footbed (lowered wherever the sock's own surface would sit under it). The slide's footbed and strap underside are the
   same tube 0.4 mm further out, along the sock's normals. Slides: closed (0 open edges). Socks: open only at the top,
   inside the trouser leg.
3. **Fit to v5.** Each foot goes on v5's: the old slides' sole gives the long axis, centre and length (scale 1.020 L,
   1.018 R), soles on y = 0. The sock's top is drawn to 2 mm inside v5's cuff (over the 2.5 cm under the hem, above the
   strap only) and carried 2.5 cm up inside the leg (to y = 0.155 m; hem at 0.116 m).
4. **Skin.** Weights are a smooth field over v5's old feet, old slides and hem (gaussian, σ 1.2 cm, top 4 bones), one
   set per position. Shared seam vertices get identical weights, the slide's tube copies the sock's, so sock and slide
   move together.
5. **Texture.** Each new mesh has its own copy of the atlas (webp): material `socks` for the socks, `feet` for the
   slides. Under the sock's triangles, the strap's black, the toe's dark spot and the seam lines are filled with sock
   white, grown 4 texels to take their light rims too. Under the slide's, the white fringe is filled with black. Each
   copy is then bled 16 texels out from its own charts, so texture filtering never brings the other's colour over a
   chart's edge. That bleed was the dark line along the sock's edges in bed and the grey nick on the big toe (G23's
   review; fixed on preview/char-fix-feet2). The sock's normal map is cleaned the same way: texels tilted more than
   about 30° (the strap edge's relief rim) are filled from the flat knit.
6. **v5's body** loses its old feet: 12,612 triangles (everything under 10.5 cm, the sock's white up to 16 cm),
   vertices compacted. The mesh `slides` is rebuilt; a new mesh `socks` is added before it (the slides stay the last
   skinned mesh, as the page's `skinMesh()` expects).

## The bed (barefoot = in his socks)
The page's mechanism is unchanged and works. boy_mh.js hides the meshes named /slide/ before he lies down and parks a
copy of them by the bed; the socks stay on. Measured in the page: going to bed, the slides are on for 101 frames and
off for 119; asleep, slides hidden, the parked pair shown, socks shown; waking, the slides go back on. The parked pair is
now a closed, clean pair (footbed and strap underside), where before it was open shells with white fringes.

## Renders
- `sheet_rest.jpg`: before / after at rest. Front, side, back, sole from below, close-up, and close-up with the slides off.
- `sheet_room.jpg`: before / after in the room (tests/visual harness): standing at the door, seated at the desk, lying
  on the duvet with the phone (slides off, socks on), the parked slides by the bed, asleep under the duvet.
  Made by `python room_build/charfix/probe.py --tag before|after --out DIR` (it picks camera angles with a clear line of
  sight).
