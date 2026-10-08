# Brain page v2 — approved direction (2026-10-01)

Static preview of the redesigned `/brain` page: real fibres + real cortex, simulated state.
Open it by serving `web/` assets next to `preview.html` (it fetches `fibres.bin`, `fibres_ends.bin`,
`fibres.json`, `cortex.bin`, `cortex_idx.bin`, `brain.json`). URL params: `?state=AWAKE|NREM|REM`, `&pulse=0.6`.

To build after PR #3 (construct) and the spiking PR are merged:
- full-screen brain, colour by stage (awake warm · deep sleep blue with a front-to-back slow wave · REM violet flicker),
  eased transitions; no additive white blow-out (low per-segment opacity, cortex as a rim-lit shell)
- chat messages and trades travel as a packet along the real fibres from the language parcels to the
  regions they stimulate (rest of the brain dims); note that propagation is slowed ~100x for the eye
- one-line story + event ticker instead of three dashboard columns; details in a drawer
- story cards: last night (diary), today's Pong exam vs no-plasticity control, memory test
- layers: fibres · cortex · regions · neurons (live spike sparkle during GPU sessions)
- a "scientific colours" toggle: standard direction-encoded tractography colours (RGB = LR/AP/SI)
- honesty line always visible and never covered by the brain; test on phones
