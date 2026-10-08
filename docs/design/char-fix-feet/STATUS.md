# char-fix-feet (G19): STATUS

**State: DONE.** Branch `preview/char-fix-feet`, off main 92395c7. See README.md for how it works.

## Paths
- Script: `room_build/charfix/feet.mjs` (in GLB -> out GLB; feet and ankles only). Its input:
  `room_build/charfix/ref_feet.glb`, made by `room_build/charfix/ref_feet.mjs` from the owner's reference.
- **Output GLB: `web/room/char_v5.glb`** on this branch (main's char_v5.glb run through feet.mjs; 7.65 MB, was 6.76 MB).
- For G10d: `node room_build/charfix/feet.mjs <after-collar.glb> <out.glb>` (needs `room_build/node_modules`: `npm ci`
  in room_build).
- Sheets: `docs/design/char-fix-feet/sheet_rest.jpg`, `sheet_room.jpg`. Numbers: `feet_report.json`, `probe/`.

## Counts (feet_report.json)
| what | value |
|---|---|
| triangles | body −12,612; old slides −19,854; socks +25,801; slides +28,848; **net +22,183** |
| open edges | slides **0**; socks 445 (= the two top rims, inside the trouser legs, 212 + 233) |
| back faces / orientation | slides: 0 conflicting edges, signed volume +2085 cm³ (all faces out). Socks: 4 conflicting edges (heel zip, 5.4–6.0 cm up, hidden under the strap), volume +2332 cm³ |
| sock–slide seam | 1,984 shared vertices: gap **0** |
| sock–slide under the strap | tube gap 0.41 mm by construction |
| sock inside slide, rest | 170 vertices, all hidden under-strap/footbed, **≤ 0.41 mm** deep (3D distance to the slide surface) |
| sock inside slide, animated (page, every 3rd frame) | still poses ≤ 0.41 mm; worst frame in sit-down / typing / walk: 260 vertices, 219 < 0.5 mm, 26 at 0.5–1 mm, 15 at 1–2 mm, **3 at 2.0–2.2 mm (max 2.18 mm)**; seam/tube pairs stay ≤ 1.6 mm apart (rest ≤ 1.0 mm) |
| soles at rest | both at y = 0 exactly (297 L / 388 R vertices within 1 mm of the floor) |

## Sole to floor in the page (mm over the floor F, lowest foot vertex per frame; before -> after)
| clip | lowest foot, min..max | note |
|---|---|---|
| standing at the door (mh_stand, 6 s) | 4.7 -> **5.3** (L 18.2 -> 18.9) | within the contract's 0..+10 for the supporting foot |
| getting up, walking to the window (14 s) | −2.2..53.9 -> −2.0..54.3 | the max is a swing frame (both feet off mid-step) |
| seated: desk typing (10 s) | 53.0..61.0 -> **53.4..61.4** | **both feet 5–9 cm over the floor: pre-existing, the same before; not from the feet** |
| seated: desk mouse (8 s) | 53.0..58.4 -> 53.5..59.0 | same |
| sitting down (16 s) | −2.1..58.4 -> −2.0..59.0 | |

The new feet move the soles by +0.4 to +0.6 mm. Seated in the chair, the feet hovering 5–9 cm (the contract wants
0..+1 cm) is in the clips/IK on this tree and is the same before and after. I did not change it (out of scope here).
It is worth a check against G12's desk work (0eaf73a).

## Known, not fixed
- With the slides off (in bed), the sock under the strap shows the strap's outline in slight relief, and thin grey lines
  remain at the old seam.
- The bridge has small folds where it meets the sole's rim along the crease. These are hidden, ≤ 0.41 mm at rest, and
  the reason for the 170 parity hits above.

## Tests
- Full pytest on this branch (with the new char_v5.glb), `set -o pipefail; python -m pytest 2>&1 | tail; echo "pytest exit $?"`:
  **1287 passed, 27 skipped, pytest exit 0** (10 min 37 s). `tests/visual/out/results.json`: **hard_failures == []**.
- RunPod: not used. No pods created.
