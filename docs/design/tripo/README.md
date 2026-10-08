# The Tripo props

Four props made with Tripo (paid API) take the place of earlier ones in the room. The details and task ids are in
`web/room/CREDITS.md`, "The Tripo props".

- `props.webp`: the four props, rendered alone (ramen bowl, mug, headphones, sneakers).
- `1280_<shot>.webp` (before above, after below) and `390_<shot>.webp` (before left, after right): the room with the
  earlier props (`?props=old`) and with the Tripo ones, at 14:00, at the visual QA's two sizes. Shots: `overview`, `mug`,
  `headphones`, `sneakers`, `ramen` (him eating it). Made by `python room_build/tripo_stills.py`.
- The preview video is rendered on a GPU pod by `tools/gpu_preview.py` (branch `tools/gpu-preview`), not here.

Known: the ramen bowl comes with its own chopsticks resting across the rim (the brief asked for them), so while he eats
there are two pairs, his and the bowl's. When he finishes, the empty bowl is still Kenney's `bowl`. He holds the bowl
on his upturned left palm (web/room/boy_motion.js, `bowl()`). A probe over 16 moments of the meal measured his skin
inside the bowl: the palm touches the base (≤ 7 mm), and the chopstick forearm can still graze the rim as a bite goes
to his mouth. That path is the page's eating arm (#63), not this PR's.
