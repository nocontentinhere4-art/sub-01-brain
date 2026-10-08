# The Tripo props, second batch

Sixteen props made with Tripo (paid API) replace earlier ones or are new in the room, plus a made-up car poster. The Tripo
game controller and monitor were later replaced by ones modelled in code (`room_build/build_desk_tech.mjs`; see
`docs/design/props/controller_before_after.jpg`, `monitor_before_after.jpg`), and the stills below predate that. The
details, task ids and what was left out are in `web/room/CREDITS.md`, "The Tripo props, second batch".

- `1280_<shot>.webp` (before above, after below) and `390_<shot>.webp` (before left, after right): the room with the
  earlier props (`?props=old`) and with the Tripo ones, at 14:00, him at the desk, at the visual QA's two sizes. Each
  shot's name lists the props it shows: `overview`, `desk_monitor_speakers_mouse`,
  `desk_right_console_controller_succulent_speaker`, `desk_left_lamp_camera_speaker`, `plant`, `sill_alarm_figure`,
  `shelf_top_box`, `fridge_cans`, `backpack`, `door_fan_skateboard_shoeboxes`, `bin`, `posters_car`.
  Made by `python room_build/tripo_stills.py --set 2`.
- The live screen: the monitor's panel is fitted around the page's own screen quad, which still shows the live page
  (see `desk_monitor_speakers_mouse`).

Budget, measured in the page (overview at 1280, `?props=old` against the new props):

| | before | after |
|---|---|---|
| triangles in the scene | 227.0k | 200.2k (−26.9k) |
| draw calls per frame, shadow passes included | 276 | 265 (−11) |
| download | | +1.42 MB (`props_tripo2.glb`) + 14 KB (`poster_car.webp`) |

The triangles drawn per frame with the shadow passes rise (1.01M → 1.13M): the joined mesh spans the room, so every
shadow map draws all of it. The atlases are 2560 px (5 × 5 tiles of 512 px, one per prop); the metal/roughness and
normal atlases are at half that, for GPU memory (about 52 MB for the three).

Known: the skateboard lies wheels up (Tripo put a stray third truck on its grip tape; it is underneath). The desk lamp's
lower arm is filled in like a sheet. The chair and the phone stay as they were. The keyboard is the original tenkeyless one,
split from the static room into its own node `keyboard`; the mouse is modelled in code (see CREDITS.md).

## Tripo credits (G10d)
Generation: `room_build/tripo_gen.py` (one guarded task per run; the proxy supplies the key, nothing is stored). Tally:

| batch | what | credits |
|---|---|---|
| #131 | ramen, mug, headphones, sneakers (and a paid duplicate of three), the realistic ramen | 320 |
| #138 (cap 920 → 1020) | 15 props, the lamp and plant retries, monitor, keyboard, mouse, speaker, chair | 900 |
| 2026-10-04, from G10d's budget of 400 | Tripo keyboard and mouse (image-to-model, comparison) | 100 |

G10d's 400: 100 spent, 300 left.
