# Viewers in the room: the vote on what he does next, live viewers, reactions (preview/interactive)

Status: **first working version done** (G24): code, tests and the demo video are pushed. Branch `preview/interactive`; `main` untouched, no PR.

## What was built

### 1. Vote on what he does next
- **Rounds**: one every `VOTE_ROUND_S` seconds, default **3600 (60 min)**; configurable with `--vote-round SECONDS`
  or the env `SUB01_VOTE_ROUND_S`. A round opens as soon as the last one closes.
- **Options (3)**: drawn from the activities his activity model (`life.py`, `Life.scores`) allows **both now and at the
  round's end** (score > 0 at both), so nothing impossible is offered: no park at 3 am (the park is day-only, 08–20 in
  Tokyo), no chess after 23:30, no park at 19:30 for a round ending at 20:30. Never offered: food, sleep, the door
  (needs) and the chart (nothing financial). Votable set: read at the computer, watch a video at the desk, play a game of
  chess, listen to music on the bed, walk to the park, look out of the window, scroll the phone in bed.
  Fewer than 2 possible: no round; it retries a minute later.
- **Result**: the most-voted option becomes a **strong nudge** in his activity model when the round ends:
  `Life.viewer_nudge`, a bonus of `VOTE_BONUS = 1.2` on that activity's score (the day plan's tilt is 0.35, a meal need
  1.6), held for one simulated hour or until carried out. It is carried out like a chat wish: what he is doing at home
  ends early when the nudged activity now beats it. Needs still come first (a hungry boy eats first). His caption then
  reads "…; viewers voted for it".
- **Asleep**: the result waits (`Votes.pending`) and is applied when he is awake **and** the activity is possible then
  (up to 2 simulated days, then dropped). The card says "viewers voted “…” · waiting until he is awake".
- **Tie rule**: options are listed in the order his own model ranks them when the round opens; a tie goes to the tied
  option listed first (what the model already leaned toward). No votes: no nudge.
- **One vote per viewer per round**: an **HttpOnly cookie** `sub01v` (random id, `SameSite=Lax`, `Secure` behind
  HTTPS; set on `/` and `/brain`) **and** a **salted hash of IP + user agent**. Both are HMAC-SHA256 hashed with a salt
  that lives only in memory; a vote is checked against those hashes re-hashed with a **per-round salt**. Nothing raw is
  kept, nothing is written to disk, and a round's hashes are dropped when it closes. Either hash already seen = voted.
  (Known trade-off: two people on the same network with the same browser build share the IP + UA hash.)
- **Panel** ("What next? · viewers vote", top of the room's side column; first card under the room on phones): the 3
  options with live counts and bars, time left, your vote marked, the last round's result. Wording is neutral:
  "viewers voted “walk to the park”", never what he wants or feels.
- `GET /api/vote`: the running round (options, counts, seconds left), the last result, a result waiting for him to wake.

### 2. Live viewers + reactions
- **Viewer count**: open websockets (`len(Live.sockets)`), anonymous, in every tick as `aud.n`; shown as "N watching"
  next to the reactions.
- **Reactions**: a fixed set of 6 — 👋 ❤️ 😂 😮 👏 ✨ — no free text; a bar of buttons above the chat (on phones in
  the fixed bottom dock, always reachable).
- **Rate limit**: per viewer token bucket, **1 every 3 s, burst 5** (keyed by the viewer's hash, never the address);
  over the limit the page gets `react_ack {ok: false, reason: "slow down"}` and dims the buttons for 3 s.
- **Aggregation**: accepted reactions are summed server-side and broadcast **in the existing tick** (`rx`: a count per
  emoji since the last tick); feeds at a lower rate (`?rate=5`) sum the skipped ticks' counts, like trades. They float up
  over the room for everyone (CSS, at most 40 on screen).
- **Spike glance**: **≥ 10 reactions within 10 s** → the server sends `{type: "glance"}`, **at most once every 2 min**,
  and only when he is **awake, in the room and upright** (sitting, standing or walking). Asleep, lying on the bed or out
  at the park, the spike waits; a sleeping figure doesn't turn to the camera, and a head turn while lying down looked
  like a twist.
  The page turns his head toward the camera once (`web/room/glance.js`: neck 40 % + head 60 %, capped at 55° turn /
  27° nod, 0.35 s in, 1.3 s hold, 0.6 s out), drawn after the clips; the desk-states layer gets the same message through
  its existing event hook (`deskEv` → `room/desk_states.js` `reactionFor`: `glance` → the calm `attend` loop).

### Wire format (websocket `/ws`)
| direction | message |
|---|---|
| server → page | `hello.audience = {reactions, viewers, vote, react_every, react_burst}` |
| server → page | tick: `aud = {n, v: [round id, counts, seconds left]}`, `rx = [counts]` (only when > 0) |
| server → page | `vote` (a round opens), `vote_result` (it closed), `vote_applied` (the nudge is on), `glance` |
| page → server | `{type: "vote", k}` → `vote_ack {ok, reason, mine}`; `{type: "react", k}` (ack only on refusal) |

## Hard rules, checked
- No claim that he understands, is conscious or alive; the vote card says what happens to the result, in model terms.
- No financial or buy language; the chart is not votable.
- No new LLM/API spend: counting and hashing only.
- No PII stored: hashes only, salts in memory, a round's hashes dropped at its end; the IP + UA never leave the
  connection's handler; nothing written to disk.
- Mobile 390 px: checked (screenshots below and the phone segment of the video).

## Files
- `audience.py` — rounds, options, tie rule, pending-while-asleep, fingerprints, token bucket, reactions, spike.
- `life.py` — `viewer_nudge`, `apply_vote`, `nudge`, the bonus in `scores`, carried out via `wish_now`.
- `live_server.py` — `audience_tick` (in the 50 ms brain tick), `handle_vote`, `handle_react`, the hello, the cookie
  middleware, `/api/vote`, `--vote-round`, `Feed` sums `rx` over skipped ticks.
- `web/room.html` — the vote card, the reactions bar + viewer count, floating reactions, the glance.
- `web/room/glance.js`, `web/room/desk_states.js` (the `glance` event).
- `tests/test_interactive.py` — 16 tests.
- `Dockerfile` — copies `audience.py` (`test_dockerfile` caught it).
- `tools/interactive_demo.py` — records `demo.mp4`.

## Numbers
- Server cost: `audience_tick` takes **3.1 µs per 50 ms tick** (viewer count, vote counts, reaction sums, spike check).
  Opening a round (picking the options from his model's scores) takes 0.15 ms, once per round.
- `python tests/smoke_demo.py`: **SMOKE OK**: 7.1 ms CPU per 50 ms tick (14 % of one core), tick body p50 9.6 /
  p95 15.7 ms, RSS 143 MB, all pages and APIs 200, first `/ws` tick after 0.04 s.
- Tick size: `aud` ≈ 40 bytes (`{"n":16,"v":[3,[1,8,3],97]}`); `rx` only on ticks with reactions. The brain page's
  `q=1` feed is unchanged (it doesn't carry them).
- Demo run (tools/interactive_demo.py): 16 viewers, a round of 12 votes (8 · 3 · 1) → "play a game of chess" won → he
  got off the bed and sat down at the desk: *"sits down for a game of chess at the desk; viewers voted for it"*. Then 13
  reactions in a few seconds → one glance. No page errors on desktop or phone.

## Tests
`tests/test_interactive.py`, **16 passed**:
- vote round: one vote per viewer (the same cookie on another network, a cleared cookie on the same IP + UA, a second
  tab: all refused), bad options and ended rounds refused, a new salt and no hashes kept after a round, **tie → the
  option listed first**, no votes → no nudge, options in his model's order, options only what the schedule allows (no
  park or chess at 3 am; no park for a 19:30 round that ends after 20:00), **asleep: the result waits, applied once
  when awake**, dropped after 2 simulated days, the nudge tilts by `VOTE_BONUS` but never makes the impossible possible,
  and once applied he does it ("…; viewers voted for it");
- reactions: **rate limit (burst 5, then 1 every 3 s, per viewer, the burst capped after a pause)**, only the fixed
  set (no free text), counts summed and drained per tick, spike → glance once, not again within 2 min, no spike when
  spread out;
- server: the `Feed` sums `rx` over skipped ticks, the HttpOnly cookie, hello / vote / react over a real websocket,
  `aud.n` and `rx` in the tick, hashes only in memory, round end while asleep → applied on waking, glance only when awake
  and upright in the room.

The existing suite and smoke run:
- `python tests/smoke_demo.py`: **SMOKE OK** (above).
- `pytest tests` (full suite, 1,558 tests with these 16): everything outside `tests/visual/` passes, including
  `test_dockerfile` (it caught `audience.py` missing from the Dockerfile; fixed). In `tests/visual/` (headless Chromium
  + SwiftShader), the tests that fail here **fail the same way on the untouched base commit `96d6cad`** (run side by
  side in a worktree), so this branch didn't cause them:
  - `test_hand_switch::test_no_snap_switching_between_keys_and_mouse`: fails on the base too.
  - `test_visual::test_room_renders_without_hard_errors`: the same 3 items on the base and the branch (chair/desk
    penetration in `walking_8_1280`, desk penetration in `eating_19_1280`). Under CPU load it adds timing items on both
    (`desk_14_390`, and once `door_8_1280` here); run alone, the branch shows only the 3.
  - `test_phone_camera` (6 cases): fail here, and `test_in_bed_he_is_in_the_picture[390]` **fails the same way on the
    base** ("out_of_bed, at the desk: head out 25/60"). Only that one case was re-run on the base (each takes ~6 min
    under software GL).

## Demo video
`demo.mp4`: 45 s, 1280×720. The desktop part shows a vote round, his move to the desk, then the reactions and the
glance; the 390 px phone part shows the vote card, the dock with the reactions and the viewer count, and reactions
floating over the room.

How it was made: headless Chromium has no GPU here, and one software-GL (SwiftShader) frame of the room takes ~15 s.
So `tools/interactive_demo.py` doesn't screen-record. It runs the demo server (`live_server.py --demo --start 21:00
--time-scale 1.001 --vote-round 150`) with 14 bot viewers (websockets with their own cookie and user agent) and the
page in `?debug` with `FREEZE`. The 3D view is rendered on keyframes with the page's own `sim()` and its follow camera.
The glance uses a fixed camera on his face. The page's CSS animations run on a virtual clock, one step per frame. The
frames are then timed to 45 s, so the video runs a little faster or slower than real time: the countdown on the card
jumps between keyframes. Everything on screen comes from the running server.

Stills: `desktop_vote.png` (your vote and the counts), `desktop_glance.png` (the glance at the desk),
`phone_390.png`.

## Not done / notes
- Only the room page (`/`, `web/room.html`, the front page) has the panel and the reactions. The brain page
  (`/brain`, `web/index.html`) is unchanged.
- The vote result is carried by his **activity model** (`life.py`), the layer that picks what he does; it isn't a
  stimulus to the simulated brain regions. That keeps it a nudge he can't be "forced" by and needs no new model.
- Viewers behind one NAT with an identical browser build count as one voter (the IP + UA hash). That's the rule as
  asked: cookie **and** hash.

## Follow-up (2026-10-09): abuse limits
- Reactions are rate-limited per viewer by the IP + UA hash (a new cookie per connection no longer gives a fresh
  bucket), and per address: 1 a second, burst 15, all of an address's browsers together.
- Votes: at most 10 voters per address per round (`VOTES_PER_ADDRESS`), so one machine faking a new cookie and user
  agent per vote is capped. A shared network still gets 10.
- `test_abuse_rapid_requests_and_cookieless_clients`:
  - 50 rapid votes and reactions from one viewer: 1 vote and 5 reactions count;
  - a cookie-less client: 1 vote and 5 reactions;
  - a new cookie per connection: nothing more;
  - a new cookie and UA per connection: the address caps hold;
  - `POST /api/vote`: 405.
- `tests/test_interactive.py`: 17 passed; smoke OK. `origin/main` is merged in (`7e72cd3`).
- The full pytest run asked for was stopped when the work was reprioritised; the last full results are above.
