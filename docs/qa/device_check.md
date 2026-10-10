# Device check: iPhone and integrated-graphics laptops (10 minutes, by the owner)

What we can test from the cloud is a headless Chromium drawing in software: it proves the page's logic, not a
real GPU. These two checks are the only real-device evidence we have, so please run them after a deploy that
touches `web/room.html` or `web/room/*.js`.

## A. iPhone (Safari)

1. Open https://subzerone.live/ in Safari (not inside another app's browser). Wait for the room.
2. Leave it 5 minutes with the screen on. It must not reload, go white, or show "a problem repeatedly occurred".
3. Rotate the phone, scroll the panel, send one emoji reaction. The dot next to the state must stay green.
4. Lock the phone 1 minute, unlock: within ~5 s the caption must update again (no "connection lost" stuck).
5. Open https://subzerone.live/?lite : same checks; it should feel smoother. If only `?lite` works, say so.

Report: iPhone model + iOS version, and which step failed (or "all fine", with how warm the phone got).

## B. Laptop with integrated graphics (Intel/AMD, or an older Mac)

1. Open https://subzerone.live/ in Chrome. Press F12 → Console: note any red errors (screenshot them).
2. Watch the fan/heat for 5 minutes with the tab in front. Then switch to another tab for 2 minutes: the fan
   must calm down (the room stops drawing while hidden).
3. In the address bar add `?debug` and press Enter; in the Console type `renderer.info.render` and
   `dpr` and send a screenshot of the output (frames, calls, triangles, the pixel ratio in use).
4. Try `?lite` (light mode: no shadows, 1x pixels, no live brain) and say whether it is noticeably better.
5. Try `?full` (forces the full room even on a weak machine) only to compare; do not leave it on.

Report: CPU/GPU model, Chrome version, steps 1–4 results.

## What the page does by itself (so you know what to expect)

- 30 frames a second at most, 1x pixels; the resolution drops further by itself while frames are slow and
  comes back when they are fast (`adapt()`).
- `?lite` is chosen automatically on machines with ≤ 4 GB, ≤ 4 cores, or an old/software GPU.
- The live brain beside the room is a still link; `?brainlive` turns the embed on.
- 20 s without data while connected: the page says "connection lost · reconnecting…" and reconnects by
  itself; "too many tabs open on this address" means more than 12 tabs/devices share your IP.
