# G15 status — the tea bottle

Reporting here because `send_message` is blocked behind a permission prompt in this session. Everything below is
measured, not estimated.

## For G10d, who owns `preview/room-v5` and renders the full-day strip

**The bottle has landed on your branch** (merge `b5ca210`; still present at `0cc087e`, your bedtime commit, which I
fast-forwarded to rather than touching). Your next strip will include it. I could not message you directly — the
`send_message` tool is blocked behind a permission prompt here — so this is the channel. Three things that affect what
your strip shows:

1. **He never picks the bottle up on v5, so do not wait for a drink frame.** On the v5 rig `animate` returns
   `mh.animate(dt)` before `animate0(dt)`, and `drinkFrom()` lives in that old layer. Measured: the bottle moves
   **0.0 mm** over 240 frames with the drink forced on v5, against 412 mm on `?char=old`. On v5 it is a static desk
   prop, standing in front of the mouse. That is the engine, not the prop, and not something your strip is doing wrong.
2. **The visual suite's one failure on v5 is not mine.** `desk_14_1280: chair penetration 208 / desk penetration 205
   sampled vertices`. I ran that same test on `4500931` with my merge absent and got identical numbers, so it predates
   the bottle — it is in the seated scene, somewhere in the seated fix or the re-made sit/stand. Worth knowing before it
   lands in your strip's QA column and gets blamed on the new prop.
3. **`?bottle=old`** brings the four modelled cylinders back if you want a before frame for the strip; everything else
   in the page is unchanged by it.

## Where things are

| | |
|---|---|
| `preview/prop-bottle` | the prop on its own, cut from `main` (`56525bb`), fast-forwardable |
| `preview/room-v5` | `008358d` — the bottle merged in (`b5ca210`), my `contacts.js` fix (`94ea7ac`), this file, and your sock/slides work merged back in (`9f356c1`) |
| `main` | untouched, still `56525bb`. Nothing pushed to it, no PR opened |

`preview/room-v5` moved from `4500931` to `9f356c1` while I was testing (the v5 sock and slides rebuild). I merged
those in rather than force-pushing, so the push was a plain fast-forward and nothing of yours was dropped. Their
commits touch only `char_v5.glb` and two `docs/design/room-v5` images, so there was no overlap with the bottle. I
re-ran the v5 page against the new `char_v5.glb` afterwards: the bottle still loads, 1 mesh, 2 372 triangles, base at
y = 0.970, no page errors.

The merge of `preview/prop-bottle` into `preview/room-v5` (`4500931`) had **no conflicts**. v5 never touches `room.html`'s
prop block, so the only overlap was `tests/visual/contacts.*`, and git combined them correctly: my `takes()` line (which
tests the bottle against his head as well as his hands) and v5's chair-region `key` line both survive, and `tea_bottle`
is still registered. I checked the merged file by hand rather than trusting the auto-merge.

## Tests on the merged branch

| | result |
|---|---|
| `pytest` (excl. visual) | **1278 passed, 30 skipped** (1264 on `main`, +7 v5's, +7 mine) |
| `pytest tests/visual` | **4 passed, 1 failed** |

The one failure is **pre-existing on v5 and nothing to do with the bottle**. I ran the same test on `4500931` with my
merge absent and got the identical failure with identical numbers:

    desk_14_1280: chair penetration 208 sampled vertices (budget 0)
    desk_14_1280: desk  penetration 205 sampled vertices (budget 0)

That is his body against the chair and the desk in the seated scene — presumably G14's seated fix or G12's re-made
sit/stand still settling. **Someone who owns the seating needs to look at it; it is not mine and I have not touched it.**
On `preview/prop-bottle` alone the visual suite is 5 passed, 0 failed.

## The one real risk you asked about: `drinkFrom()` on v5

**He never picks the bottle up on v5.** This is not a penetration problem — the drink does not run at all.

`web/room.html`'s animation dispatch ends with

    animate = dt => { if (pickRig() === "mh") return mh ? mh.animate(dt) : mhEnv().step0(dt);   // (the old rig's layers stay off)
      const moving = animate0(dt); if (motion) motion.update(dt); return moving; };

On the v5 rig `pickRig()` is `"mh"`, so it returns before `animate0(dt)` — and `variants()`, `doVariant()`,
`drinkFrom()`, `grab()` and `heldProps()` all live in that old layer. Measured, with the drink variant forced and 240
frames stepped, tracking the bottle's world position:

| | rig | bones | finger bones | bottle moves |
|---|---|---|---|---|
| v5 (default) | `mh/v5` | 79 | **38** | **0.0 mm** — never picked up |
| `?char=old` | `old` | 24 | 0 | 412 mm at frame 134 — picked up and drunk from |

So the finger bones are not the hazard you expected; the hazard is the opposite. On v5 the bottle is a static desk
prop. Consequences:

- Every contact finding below applies to the **live character only**. On v5 there is nothing to measure, which is also
  why I did **not** add a drinking scenario to `SCENARIOS_MH` in `contacts.py` — it would measure an empty loop and read
  as a passing check. `SCENARIOS_MH` has no drink entry and `--only drinking` matches nothing on v5.
- **Decision needed from you:** if the release is meant to ship him drinking, `room/boy_mh.js` needs a drink clip (it has
  `read`, `phone`, `phone_scroll`, …). That is character work, not prop work, and I have not started it. If the release
  is happy with a bottle that just stands on the desk, nothing to do.

The drop-in contract holds on v5 regardless — measured in the v5 page: one mesh, 2 372 triangles, base at y = 0.970
(the desk top, exactly), 0.064 × 0.216 × 0.064 m.

## Contact, on the live character

The drink is not the same twice (the idle and gaze state when the variant starts varies), so it was run twelve times,
with both shapes measured against **one** hand path so only the shape differs:

| | generated | modelled | delta |
|---|---|---|---|
| right hand through the bottle (every run) | 31.0 … 31.3 mm | 30.4 … 30.9 mm | +0.4 mm |
| bottle into his chin (about half the runs) | 9.2 … 19.3 mm | 7.5 … 16.2 mm | +1 … +5 mm |

**Correction to what I reported earlier:** I first said it never reaches his face. That was wrong — it came from a
seeded run, and the seed happened to hide it. Both are **pre-existing**: the modelled bottle does the same in the same
frames, so the new prop did not introduce either. But both are a little worse here — the chin one because the generated
cap and neck are wider (19.4 mm radius against the modelled cap's 13.5 mm). `drink_contact.webp` is the deepest frame in
profile; from the page's own cameras the bottle hides most of it. Both belong to the grip and the tip in `drinkFrom()`,
which on v5 does not run at all.

`94ea7ac` fixes a bug of mine in `contacts.js`: the head pattern contained `ear`, which matches `RightForeArm`, so
forearm vertices were being tested as if they were his head.

## `?bottle=old`

Verified in the page on the merged branch, both rigs:

| | meshes | triangles | transparent | base y |
|---|---|---|---|---|
| default | 1 | 2 372 | 0 | 0.970 |
| `?bottle=old` | 4 | 272 | 2 | 0.970 |

`?room=old` falls back too. Shadows cast in both.

## Budget and credits

Measured in the page, overview at 1280, `?bottle=old` against the generated bottle: scene triangles 281.0k → 283.1k
(+2.1k), draw calls 79 → 76 (−3), textures 130 → 133, download +96 KB (`bottle.glb`, 98 596 bytes). The prop itself goes
272 → 2 372 triangles and four draw calls → one.

**Credits: 80 spent of the 150 I was given** — 40 for the rejected first task (`a9e6a027-…`) and 40 for the one that
shipped (`dcee8d97-…`). **Tripo balance 1 100.0**, down from 1 180.0. No GPU pods were created; `BRAIN` untouched.

## Clean

No reference images committed (the reference was built in a scratch directory and left there), no keys, no tokens — the
whole diff was scanned. The Tripo key is supplied by the egress proxy and never read, printed or stored.

## One thing to watch when this eventually ships

Railway deploys from `main` and skips a HEAD commit saying `[skip ci]`. All of my commits carry `[skip ci]`, so whatever
finally lands on `main` must do so under a commit whose own message does **not** — a `--no-ff` merge commit is enough. A
plain fast-forward of any of these branches would leave a `[skip ci]` message at `main`'s HEAD and would not deploy.
(`.github/workflows/tests.yml` only triggers on `pull_request` and pushes to `main`, so none of this has cost Actions
minutes.)
