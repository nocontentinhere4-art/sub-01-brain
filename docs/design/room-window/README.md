# The window and the outside (#98 G7, PR `feature/gl-window`)

Before (main) and after, at Tokyo hours 07, 12, 18, 21 and 02, at 1280 and 390 px, clear and in the rain. Each sheet:
**before | after, clear | after, rain**; the page's overview camera above, the view from his place at the window below.
Made by `python tests/room_window_shots.py --before <checkout of main>`; `results.json` has the weather state of each shot
and the cost figures. Headless Chromium draws WebGL in software here (SwiftShader), so the colours are right but the
anti-aliasing and the texture filtering are coarser than on a phone or a laptop.

## What changed
- The owner asked for the most realistic view possible, so the outside is made of **photographs** (all CC0 or public
  domain, listed with authors and licences in `web/room/CREDITS.md` and `web/room/window/plates.json`): an elevated
  daytime view over the low houses of Suginami, the ward next to Kichijōji; a night view of the same kind of
  neighbourhood with its real lit windows; the Minato skyline at twilight, far and small; six real skies from Poly Haven
  (clear, partly cloudy, overcast, sunset, dusk, night). Only the utility pole and its cables are drawn (silhouettes).
- `web/room/window_view.js`: one plane on the glass marker. Its shader casts the view ray from the real camera through
  each glass pixel onto the plates behind the window (near 14 m, the neighbourhood 40 m, the skyline 200 m, the sky at
  infinity): true parallax from every camera; nothing exists outside the glass.
- By the hour: the sky photographs cross-fade by the sun's elevation and the cloud cover; the daylight photograph is relit
  (dusk dark and warm, blue hour cool); the night photograph fades in through the blue hour, and some of its real lit
  windows switch off and on (each pane has an id in `mid_l.webp`; a hash of id and a 2-minute slot decides, following
  the evening). The far skyline is a faint silhouette in the haze by day and the twilight photograph at dusk and night.
  The sun and the moon cross the window; birds by day; a train's lit windows glide past at night.
- Weather: clear, overcast, rain. Rain streaks run down the glass and drops refract the view; rain falls outside; the
  layers haze over; the sun goes. **There is no weather feed**: nothing in `live_server.py` or `life.py` fetches one, so
  the weather is a **deterministic** daily pattern (`weatherAt`: smooth noise over Tokyo time, about a fifth of the
  hours wet and a third overcast, the same for every viewer), never presented as real. `?debug&weather=rain|overcast|clear`
  previews one. `view.light.sun` (0..1) says how much sun the weather lets through, for the room's lighting (G6's block).
- The glass reflects the room (#20): a 64 px cube probe rendered from just inside the glass once the room has loaded and
  every 20 s, blended by a Fresnel term, so the lamp and the screens show in the glass at night.
- G6's HDR light units: `windowView.setEmission(day, night)`; the room passes `hdr:() => post.hdr`, so once G6's branch
  is merged the window emits 5 by day and 0.05 at night without another change.
- A diorama cheat, stated plainly: the room's cameras all look down (the orbit controls never go below 12.6° of pitch, and
  the overview looks down ~25°), so a true window would show only the street from the default view. The view rays are
  flattened vertically (gain 0.5) and lifted by a slope that grows with the camera's height over the window (0.10 + 0.045
  per metre, at most 0.35), so the horizon follows the camera up. The horizontal parallax is true (gain 0.7).

## Budget
- Assets: all the plates together are 760 KB (`room_build/window_cards.py` prints the sizes; budget 1.5 MB), one draw
  call, at most ~14 texture reads per glass pixel, no per-frame JS beyond a few uniforms (`results.json` →
  `window_update_js_ms`); the reflection probe renders the room six times at 64 px every 20 s.
- The 2 ms per frame on a mid-range phone cannot be measured here (software GL); the shader is bounded by the glass's
  pixels (a fraction of the screen). Needs a real device (G8's suite).

## Known limits
- The daytime neighbourhood photograph could only be fetched at 1280 px (Wikimedia rate-limits this address for the
  original); it is upscaled to 2048 and reads a little soft in close-ups. Re-running `--fetch` from another network gets
  the 2412 px original (the script prefers it) and `window_cards.py` rebuilds the plate.
- Day and night are two different neighbourhoods of the same kind; the swap happens inside the blue hour, when both are
  dark, and reads as the lights coming on.

## Fix: the glass at grazing angles (G8 defect #26, `fix/window-glass`)
`glass/sill_{08,19,23}_before_after.jpg`: G8's harness camera from the sill (`window_<hour>_1280_char`), main vs the fix.
- Before, seen along the glass the left pane was a pale wash: the view ray's slope grows without bound towards 90°, so the
  finite plates ran out and only sky and haze were left, and the Fresnel term reached 1.0, so the lit wall's reflection
  covered what remained.
- Now the slope is soft-clamped (asymptotes 0.55 m/m sideways, 0.9 m/m up), so a grazing look lands on the
  neighbourhood, compressed, as the eye expects; the Fresnel term is capped at 0.25 and the reflection's colour at 1.0,
  the view keeps at least 79 % of its light, and the reflection's weight follows the hour (0.32 at night, 0.10 by day),
  so the room shows faintly in the glass at night and hardly at all by day. The frontal views are unchanged.
- The cables are drawn at 4× supersampling as 1–1.6 cm strands with their own sag and slant (seven of them), so they
  downsample to soft anti-aliased lines instead of identical 3 cm bars.
