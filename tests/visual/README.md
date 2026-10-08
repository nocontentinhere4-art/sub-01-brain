# Visual QA of the room (`/room`), issue #98 workstream G8

Fixed-camera screenshots of the character in each activity, at four Tokyo hours and two viewport sizes, with
automated checks, in headless Chromium drawing WebGL in software (SwiftShader). The scorecard built from these shots
is `docs/qa/scorecard.md`.

```
python -m tests.visual.harness --out tests/visual/out          # the core set CI runs (~3 min on 4 cores)
python -m tests.visual.harness --full --out tests/visual/out   # every scene x hour x size (~10 min)
python -m tests.visual.harness --full --only phone,eating --out tests/visual/out   # re-run some scenes into an existing run
python -m tests.visual.harness --only pip --out tests/visual/out                   # only the room's mini brain (~10 s)
python -m pytest tests/visual -q                               # the CI entry (skips without Playwright + Chromium)
python -m tests.visual.fake_server --port 8797                 # look at a scene in your own browser (see below)
```

Needs `pip install -r requirements-server.txt pytest` (Playwright is in there) and a Chromium: `/opt/pw-browsers/chromium`
(`SUB01_CHROMIUM` to point elsewhere) or Playwright's own (`playwright install chromium`).

## How it works
- `fake_server.py` serves `web/` with a fake `/ws`: the room page connects to `/ws?rate=5&lite=1` and gets `hello`, then
  one scripted `tick` (life.py's snapshot shape, `scenes.py`) five times a second. `/api/*` reads answer small empty
  JSON; `/brain` (the mini brain iframe) is a dark stub, because the real brain page would starve a software-GL run;
  `/mini-brain` serves the real brain page (`web/index.html`) for the mini-brain check below, with the fake `/ws`
  adding a flat `act` vector for it.
  By hand: open `http://127.0.0.1:8797/room.html?debug&hour=19` and `curl 'http://127.0.0.1:8797/__qa/scene?name=eating&hour=19'`.
- The room's PiP brain (`<a id="brainpip"><iframe src="/brain?mini">`, #116: no `neurons=1`): the harness reads the embed
  URL out of `room.html`, then opens the brain page itself at 300×225 as `/mini-brain?mini`, waits for its first frames and
  shoots `pip_mini_brain.png`. Hard: the embed URL is `/brain?mini` without `neurons=1`; the page starts and renders
  (no JS error, not blank); no neuron forest (`n3want`, `n3d`, the body's `n3` class), no `THREE.Points`; the fibres
  are there (≥ 5 % of the frame bright; 20 % on main, under 1 % when the forest dims them); draw calls within
  `budgets.json` (`pip_draw_calls` 4: 2 on main, 9 with the forest). The small-bright-blob count is only reported: the
  fibres' own beads are counted too (140 on main, 189 with the forest), so it is a texture figure, not the dots test.
- `harness.py` opens `/room.html?debug` once per size, waits for the room, the character, the ten GLBs and the boot
  screen, freezes the page's own loop (`window.FREEZE`) and steps the simulation itself (`animate_`), so every shot is
  the same pose and the same light. A scene is entered the way the page's first tick does (the debug `act()` snaps him
  into the anchor and clip), then the ticks drive the rest: the phone in bed starts lying asleep and the phone tick brings
  the phone up; walking starts at the door and the research tick sends him off (shot mid-stride).
- `page_checks.js` is injected after load and only uses what `?debug` exposes: close-up cameras from the bones,
  penetration against the bed and the chair (the page's own `penetration()`), the floor and the desk (vertical rays
  through `room_static`, cached), props resting on something, texture texels per metre, FPS, `animate()` cost.
- `image_checks.py`: pure-black and blown-out pixel fractions of the 3D canvas, z-fighting as frame-to-frame flicker on
  flat patches while the camera creeps sideways 0.7 mm a frame (edges change one way; two coplanar surfaces flip to and
  fro), contact sheets.
- `cdn_cache.py`: three.js (jsdelivr for the room, cdnjs r128 for the brain page) and leaflet are fetched once with Python
  and served to the browser from `tests/visual/.cdn_cache/` (a sandbox behind a TLS-inspecting proxy breaks Chromium's
  CDN fetches; CI only saves downloads).

## What fails CI (hard) and what is only reported
Hard: the page loads (room, character, all clips), no JS error, no failed own-origin request, every core scene reaches
its place and clip, the canvas is not blank, bed/chair/desk penetration within `budgets.json` (0 on main), the mini
brain's checks above.
Reported in `out/report.md` and `out/results.json`: vertices below the floor, feet off the floor,
props floating or sunk, texture density, exposure, flicker, FPS under a 4x CPU throttle (a CPU rasteriser's number,
not a phone's), draw calls and triangles. The blown-out fraction counts the monitor's white page too (it is an unlit
255-white texture): compare shots with and without the monitor in frame before calling the light too bright.

## Output
`out/<scene>_<hour>_<size>.png` (the page), `..._clean.png` (the 3D view alone), `..._char.png` (a medium shot of him),
`closeup_<name>_<hour>.png`, `flicker_*.png`, `pip_mini_brain.png`, `report.md`, `results.json`. Nothing under `out/` or
`.cdn_cache/` is committed.

## Scenes
desk (research), eating (ramen), phone (lying, phone up), sleeping (NREM), walking (door → desk), door (standing just
inside), window (leaning on the sill). Hours 8, 14, 19, 23. Sizes 1280×800 and 390×844 (mobile emulation, DPR 1).
Close-ups: face, hands, grip, feet, socks, desk, bed, duvet, night.
