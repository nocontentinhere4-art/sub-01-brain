# SUB-01 — roadmap (coordinator)

Last pass: **2026-10-04 05:30 UTC** (pass 40). Updated after every coordinator pass. Read with `docs/HANDOFF.md`.

## Waiting for the owner
**Pass 25:** merged #53 (#17, server side + /brain): YouTube muted, locked muted and in Restricted Mode, with a
10–600 s watch; chess with python-chess, a depth-2 opponent, and the brain vote picking among 5 scorer moves ("his brain
model picks among 5 candidate moves from a simple move scorer"). 601 tests with torch and Chromium; tick 8.8 ms. The
room desk view is the last open PR.

**Pass 24:** merged #52 (#46, the mind in the room). He sits at the desk to answer chat on the monitor; replies are
tagged "his reply (AI-written)". The day plan shows "voted by his brain model", or "yesterday's, kept while the AI rests"
when the AI is resting, plus the resting line. 531 tests; tick 8.1 ms. #17 continues: server PR first, then the room
desk view (it will also look at the dark rectangle behind the status sub-line).

**Pass 23:** merged #51 (#15): one view of every paid cost per Tokyo day, caps checked before each paid call (eye
$1.00 — the eye's first cap —, diary $0.10, eyes $1.00, mind $1.00, total $3.10), `/healthz` (public), and `/api/costs`
and `/api/health` (password cookie or admin token). Checked live by the coordinator with the gate on. 569 tests; tick
9.3 ms. Worst case at launch ≈ $3.86/day including RunPod. #17 (YouTube + chess) started.

**Pass 22:** merged #50 (#18). The server and Chromium now run as uid 1000; the entrypoint hands the root-owned
/data over once. Rollback: `RUN_AS_ROOT=1`. The coordinator built and ran the real image in Docker: all processes are
uid 1000, a root 0600 file is readable and writable after the start, and `/api/config` returns 200. Under Docker's
default seccomp Chromium's sandbox falls back to `--no-sandbox`, with a loud log line; check Railway's first deploy
logs for `CHROMIUM SANDBOX FAILED`. `tests/test_dockerfile.py` now fails CI if a server import is missing from the
image. #15 (costs, caps, /healthz) is next, ahead of #17: after today's outage, a health check comes first.

**Pass 21b: incident.** #45 (merged ~07:30) made `live_server.py` import `mind`, but the Dockerfile's COPY list
lacked `mind.py`. Any Railway image built from 07:30 to 08:24 stopped at start (`ModuleNotFoundError`), so the live
site was probably down for about an hour. The #18 worker found it with `docker build`. Hotfix #49 (adds `mind.py`) was
verified with the exact image file set and merged at 08:24. A regression test (local imports ⊆ Dockerfile COPY) is
part of #18.

**Pass 21:** merged #48 (#19): the brain loop is **6× cheaper**. Bench 31.7 → 5.0 ms; whole server 34 → 9.0 ms per
50 ms tick (8.5 ms with --mind), about 18 % of a core. Identity test vs the old step < 1e-9, 541 tests, 0 skipped. It
also explains the post-vote slowdown (malloc churn from old temporaries). #18 Chromium non-root started.

**Pass 20b:** merged #47 (#43): the maps are drawn from a static OSM extract (130 KB), with no tile server and ODbL
attribution. /about now states the search-box typing honestly. #46 (the mind in the room) started.

**Pass 20:** merged #45, the mind layer live: page notes, a day plan voted by the brain, chat replies at the
computer tagged "his reply (AI-written)". 531 tests with torch and Chromium, 0 skipped; tick 34.2–34.9 ms. The
coordinator checked the caps on the real `Share` objects: mind $1.00 and eyes $1.00 each block at their cap, the total
is $2.00, and it survives a restart. **AI spend now runs up to $2.00/Tokyo day** (OpenRouter key already on Railway).
#33 closed. Started #19 (brain loop 3× cheaper, plus the tick rise after worker-thread votes). New #46 (the mind in
the room, after #43).

**Pass 19:** merged #44 (#31 room teach card). Both "does not understand" lines are gone from the room (owner
disliked them), with no claim of understanding added; `/about` keeps "a model, not a mind". #31 closed. #43 map
session started.

**Pass 18b:** merged #42 room follow-ups (chair node pulled out and ridden in, bed sit/lie with 0 bed penetration,
one-line disclaimer with the owner's text). Found in its screenshots: OSM blocks the map tiles ("Access blocked – tile
usage policy") → new task #43 (static vector map, no tile server). #31 room card started (also rewords "it does not
understand the text").

**Pass 18:** merged #41 teach him (server side + /brain card; 522 tests with torch and Chromium, 0 skipped; tick
32.6 ms). The room teach card follows in a small PR after the room follow-up PR (still in progress). #33 phase B
(mind wired into the live server, shared $2/day ledger) started on `feature/mind-live`.

**Pass 17:** merged #38 (tastes learn faster: Kalman gain per topic + overnight replay; simulated top 5 found ~2.5×
sooner at noise 0.1; 346 tests, tick 32.5 ms) and #39 (spiking network learns to choose: 1M neurons on GPU reached
criterion in 84 trials, re-learned after reversal in 22, exam 1.00 vs 0.275 with learning removed and 0.26 random;
CPU learning test re-run by the coordinator with torch: 20 passed). RunPod checked read-only: only "BRAIN" (EXITED,
untouched). Then #40 free browsing (#29): site search only into verified search boxes, comments, pagination, muted
video, reject-only consent banners; 472 tests incl. Chromium, tick 33.5 ms. #31 started (server side first; the room
card waits for the room follow-up PR).

**Pass 16 (owner: "finish everything on your own, what's missing with the neurons and the rest, verify and proceed"):**
merged #37 (mind layer phase A, new files only), #27 (MyConnectome attribution), #32 (/tastes page), #28 (room movement: walks around furniture, sits, lies
down) and #34 (launch load). Before merging, the coordinator merged all four onto `main` locally: 291 tests passed
(10 skipped), smoke OK at 32.5 ms per 50 ms tick, and the #34 load test with 300 viewers passed (71 % of one core,
tick late p95 3.3 ms, RSS 173 MB).

Owner actions now:
- **RunPod:** the owner added the RunPod key on Railway (2026-10-02). The pod manager also needs **`SUB01_POD_SECRET`**
  (any long random string). Without it the log says `spiking pod manager disabled: SUB01_POD_SECRET is not set`. With
  both set, the first GPU session runs tonight at 21:00 Tokyo (12:00 UTC): ≤ 1 GPU-hour/day, ≈ $0.27–0.85/day.
- **Turn the 1M network on (after #67):** done 2026-10-02 16:30 UTC (`SUB01_POD_SECRET`, `SUB01_DAY_LIVE=1`, `SUB01_CHOICE=1`).
- **`SUB01_CHOICE=1` on Railway** (optional): adds the choice training to the nightly GPU hour (~90 s, no extra cost).
- **After #51, on Railway:** set the healthcheck path to `/healthz`, set a long random `SUB01_ADMIN_TOKEN`, add a free
  uptime monitor (e.g. UptimeRobot) on `/healthz`, and set a usage alert (see docs/OPERATIONS.md).
- **GPU budget beyond 1 h/day:** not decided. Caps stay as they are until the owner names a daily amount.
- **Email account for him** (18d), **reply to Russ**, **Railway paid plan**: owner only.
- **Railway credit: "24 days or $4.17 left"** (owner's screenshot, 2026-10-02). The service stops when it runs out.

Who is on what (cloud sessions, 2026-10-02):
| work | session | state |
|---|---|---|
| #29 free browsing | `session_01MuUA9dxNCVBWAw6ez7R9Ju` | merged as #40 (its 2 novelty hooks ride with #33 phase B) |
| #31 teach him | `session_017R5d56EEZVdrsHDbvQuww9` | done: #41 (server, /brain) + #44 (room) |
| #43 map without OSM tiles | `session_015XP5haU96uvbRUJf3p7Tam` | merged as #47 |
| #46 the mind in the room | `session_01Ek5DZG7cEvc1v7TV8PrEkz` | merged as #52 |
| #33 mind layer | `session_01KwLm3oYfsh8KhXjWTbrUPt` | done: #37 + #45 |
| #19 brain loop 3× cheaper | `session_017zdDm1BDeRmdNJEEusasoA` | merged as #48 (6×) |
| #18 Chromium non-root | `session_01Fbtw3qXpLr5WZAjU7jQiDT` | merged as #50 (found the #49 outage) |
| #15 costs, caps, /healthz | `session_01M9bv9k1WFLctqBLSHXWPwr` | merged as #51 |
| #17 YouTube + chess | `session_01F3jQL1rvBNU5TaF7Sygkqi` | done: #53 + #54 |
| #35 spiking brain learns to choose | `session_01M78bGx6tpR1jKqBUG5wCPQ` | merged as #39 |
| #36 tastes learn faster | `session_013dKUqHWjLfTXWhGQLBVqcc` | merged as #38 |
| room follow-ups (bed clip, chair, one-line disclaimer) | `session_01Xrq53UQH9EHy4bgPj9B2yL` | merged as #42 |
| `fix/eyes-docstring` | `session_01881q1gcHZBtokE8qi8QjxC` | asked to open the PR |

Next on `live_server.py` / Dockerfile: **#17** (in progress). Then only the launch checklist is left. `web/room.html`: #17 room desk view (next).

## Final goal
A public site where a brain model built from one real person's open MRI data lives as a fictional young man in a
Tokyo room. He:
- sleeps and dreams (diary);
- reads and browses the web, and his brain model decides what to click;
- remembers what he read (spiking memory, tested daily);
- has a body and neuromodulators;
- reacts to chat and to the coin's trades.

The site must be honest: published numbers, and no claims of mind or consciousness. It must be stable on Railway and
cheap to run, with the password gate kept until launch day.

## Milestones
| # | milestone | state | owner |
|---|---|---|---|
| 1 | Brain v2 page, real fibres | done | main |
| 2 | Fitted slow layer (connectome v2, held-out FC r ≈ 0.21, nulls) | done | #5 |
| 3 | Room 3D + open-web screens | done | #6 |
| 4 | Dream diary, Wikipedia reading | done | main |
| 5 | Body + neuromodulators | done | #10 |
| 6 | PCI test (below the cut-off in every state; published as is) | done | main `cd5e25b` |
| 7 | Room lag fix, phone grip, sky, rebuilt bedroom | done | #8 |
| 8 | Reading memory (readings → stimuli, REM replay, curiosity) | done | #7 |
| 9 | Sleep circuit (Phillips-Robinson) | done | #11 |
| 10 | Spiking memory on GPU, daily test card | done (idle until the RunPod keys are set on Railway) | #9 |
| 11 | Brain decides what he clicks (Haiku 4.5 eyes, $1/day cap) | done | #20 |
| 12 | CI (tests + demo smoke on every PR) | done | #22 |
| 13 | Honest `/about.html` (numbers, credits, coin disclaimer) | done (follow-up for credits pending; links from the pages come with the room fix) | #23 |
| 14 | Launch load: cheaper feeds, viewer caps, load test | done (300 viewers: 71 % of a core, 4–7 KB/s each) | #34 |
| 15 | Cost ledger, daily caps, `/healthz`, monitoring | done | #51 |
| 16 | YouTube (muted) + chess, chosen by the brain vote | done | #53, #54 |
| 17 | Chromium as non-root (sandbox on) | done (uid 1000; sandbox on where the host allows it) | #50 |
| 18 | Brain loop 3× cheaper | done (6×: 34 → 9 ms per tick) | #48 |
| 18c | Free browsing (on-site search, forums, news, video, comments; guard kept for public screens) | done | #40 |
| 18e | Daily memory test on the GPU switched on | key added 2026-10-02; needs `SUB01_POD_SECRET` too | #9 |
| 18f | "Teach him something" (viewer word → studied, dreamt, tested next day) | done | #41, #44 |
| 18i | Faster learning of tastes (adaptive rate, overnight replay of surprising pages) | done | #38 |
| 18j | Spiking brain learns to choose (dopamine reward vs frozen and random controls) | done; nightly run needs `SUB01_CHOICE=1` on Railway (~90 s inside the 1 h) | #39 |
| 18k | Room movement (walk around furniture, sit, lie down) | done (+ chair and bed follow-ups) | #28, #42 |
| 18l | Map cards without tile.openstreetmap.org (OSM blocks them) | done | #47 |
| 18g | /tastes page (what he leans towards, over days) | done | #32 |
| 18m | 1M spiking network on GPU through his waking hours (caps 17 h, $14/day, 120 h/week) | done; on with `SUB01_DAY_LIVE=1`; learns (#74: 0.45–0.69 vs frozen 0.24–0.38) | #67, #74 |
| 18n | 20k spiking network on the server CPU votes and learns live (GPU fallback) | done | #65 |
| 18o | Browse like a young guy (interests, Shorts/TikTok, finance read-only, logged-in view-only feeds) | done | #64, #66, #69 |
| 18r | Daily clips for the official social accounts (AI-labelled, private/draft by default) | done | #72 |
| 18u | Natural motion (no frozen poses), headphones while listening | done; food part 2 next | #82 |
| 18v | Readings from real browsing (Wikipedia 100 % → 9.5 %) | done | #81 |
| 18w | Sleep fix: no third-party trades, correct decoding, bounded arousal | done (merged 18:22 UTC) | #85 |
| 18s | Room polish: no floating props, lamp out of the wall, a lived-in room, sharper phone screen | in progress | #75 |
| 18t | A better character (fingers, face, clothes; same animations) | in progress | #76 |
| 18p | Active neurons visible inside the 3D brain, with real neuron shapes | done (/brain, /life); room mini brain next | #77, #83 |
| 18q | Music via Spotify's official embed, picked by the brain vote | done (server, /brain, /life); room after #63 | #71 |
| 18h | Mind layer: reads and remembers meaning, plans his day (brain votes), answers chat from his computer; $2/day shared AI cap | done (#37, #45, #52) | #46 |
| 18d | His own email (owner-created account: read first, then limited replies) | waiting on the owner (account) | — |
| 18b | Atomic state-file writes (a torn JSON file crash-loops the server) | done | #24 |
| 19 | Launch | todo | owner |

## Merge order
One task at a time on `live_server.py`: **#14** launch load (next) → **#19** perf →
**#18** non-root → **#17** YouTube/chess → **#15** ops (last; it reads every cost log).

**#12** CI and **#13** about page touch no shared files and can merge at any time.

Rule: at least 60 minutes between merges to `main`, unless the owner says otherwise. Every branch brings `main` in with
a merge commit. Never force-push.

## Review bots
`graphify-labs[bot]` reviews every PR: a summary, "Worth a look" findings and inline coupling notes. It marks its own
findings "NOT verified", and its reviews are partial on large diffs.
- The coordinator verifies its findings. Authors fix only the ones the coordinator's review lists as required.
- Ignore its "Health regression" coupling counts on test functions.
- Verified real so far:
  - #8: `?rate=` overflow and unbounded per-client buffering → required change on #8;
  - `main`: non-atomic JSON state writes, from #10 → issue #21.
- Checked and not real: #8 HTML injection (all user text is escaped); #10 `Life.hunger` read-only (nothing writes
  it); #11 removed constants (aliases kept, PCI imports work); #20 NumPy group indexes and the fragment login guard;
  #7 thread races (no crash path in CPython).

## Decisions
- **2026-10-01: merge order** as above. #8 goes first because it is smallest and mostly frontend. #7 goes next
  because #9 and brain-decides both contain its commits. #11 goes before #9 because one one-commit PR should absorb
  #7's `sleep.py` changes, rather than three branches absorbing the circuit. #9 goes before brain-decides because it
  is reviewed, validated on a pod and capped, while brain-decides has no PR yet and changes the browser architecture.
- **2026-10-01: sleep circuit without a flag.** PR #11's full port is accepted over a flag with the old engine kept.
  The port loads old state, has a 48 h hypnogram test, and the modulators reach `neurochem`. Two engines would double
  the code that the diary, dreams and memory depend on. Rollback is a revert. Issue #16 is closed.
- **2026-10-01: memory test timing.** Keep one session a day, 21:00–22:00 Tokyo, on 1 pod for ≤ 1 h. The session
  encodes the day's readings, runs compressed sleep and the after-sleep test, and runs the next-day test at the start
  of the following session. "Tested every morning" in the goal means this daily next-day test. A morning slot is
  only a change to `SUB01_SESSIONS`.
- **2026-10-01: #7, #11 and #9 merged at the owner's request**, before their authors pushed the last fixes. The
  coordinator did the merge-only work: conflicts, the torch skip, the sleep wording, the rollback note, and the
  `expected_replays()` fix. #20 and #8 were held: #20 has no spending cap yet, and #8 has an unreviewed room rebuild
  and the `?rate=` bug.
- **2026-10-02: much more freedom on the internet** (the owner wants "no limits"). The coordinator builds everything
  that makes him freer:
  - free browsing (#29): on-site search, forums, news, video, comments, long chains;
  - his own email, on an account the owner creates by hand: read first, then limited, filtered replies signed as an
    AI character;
  - logins only with owner-created accounts on sites that allow bots.

  Not built, because they are harmful in themselves:
  - automatic account creation or CAPTCHA solving (against every provider's terms; the accounts get banned and the
    owner is liable);
  - any money: purchases, wallets, crypto;
  - adult or gore content on the public screens;
  - the character mentioning or promoting the coin, or pretending to be human.
- **2026-10-02: the mind layer** (owner): a language model becomes his inner voice, governed by the brain model (mood, energy, choices). Wording: "an AI reads and remembers for him; his brain model chooses"; never that he understands, feels or is conscious. The shared AI cap is raised to $2.00 per Tokyo day (eyes + mind).
- **2026-10-02: the site is English-only** (owner). Viewers may write in any language and Italian words still reach the brain as stimuli, but nothing shown or generated is in another language.
- **2026-10-02: CI-only and docs-only merges do not count for the 60-minute spacing:** they don't change what runs on Railway.
- **2026-10-02: the room's default is the new clean room** (`room_clean.glb`, #8), and `?room=old` stays for one week.
  I rendered both in headless Chromium. The new room is cleaner, and its provenance is documented as CC0 or made for
  the project (`web/room/CREDITS.md`); the old room is a single AI-generated mesh. A later PR removes the old GLBs.
- **2026-10-01: review-bot findings are advisory.** The coordinator verifies them before they become required changes.
- **2026-10-01: paid-model choice stays with the owner** unless the owner delegates it. Coordinator rule: every paid
  call has a hard daily USD cap and a log line before it can merge.
- **2026-10-01: brain-decides "eyes" use Claude Haiku 4.5 (OpenRouter `anthropic/claude-haiku-4.5`, or `claude-haiku-4-5`
  direct), capped at $1.00 per Tokyo day.** The owner delegated this decision.
  - The task is listing 3–5 safe options from a page; the brain model decides, so Opus quality is not needed.
  - Haiku is ≈ $0.004 per page, about 5× cheaper than Opus 5.5, and reliable at the JSON format; Llama is not.
  - Over the cap, he browses with the page's own links, and the brain still votes.
  - The default is set in code, so nothing needs setting on Railway.
  - Haiku takes no effort or thinking parameters, so the requests are built per model (#20, change 6).

- **2026-10-02: owner delegated finishing ("finish everything on your own, verify and proceed").** The coordinator
  merges verified PRs, including those that touch `live_server.py`, after running tests, smoke and (for load) the load
  test on `main` plus the PR. Unchanged: spending caps (GPU 1 h/day, AI $1–2/day), the password gate, the safety rules,
  never touching the pod "BRAIN".
- **2026-10-02: "accelerate learning" = three separate tracks.** Understanding = the mind layer (#33, LLM, capped).
  Preferences = tastes learn faster (#36). Neurons = the spiking network learns choices from dopamine (#35), reported
  against frozen and random controls whatever the result. No claim of IQ, understanding or consciousness.

- **2026-10-02: music through Spotify's official embed only** (owner asked for Spotify). The server never streams,
  downloads or relays audio. Visitors press play on their own device: a 30 s preview, or the full track if they are
  logged in to Spotify. His brain model picks tracks among candidates (#68). Optional `SPOTIFY_CLIENT_ID/SECRET` (free
  developer app); otherwise a curated list of playlists.
- **2026-10-02: social accounts, both uses** (owner).
  - (a) Official SUB-01 accounts post daily AI-labelled clips (#59): manual, or the official APIs once approved.
  - (b) He browses logged in to his own TikTok/YouTube, view-only (#60, after #56). No likes, follows, comments or
    DMs, and private pages never reach a public screen.
  - The owner creates the accounts; Claude cannot sign up. Terms-of-service ban risk on (b) is accepted; he falls back
    to logged out.
- **2026-10-02: browse like a real young guy, no restrictions** (owner; this supersedes the earlier same-day note).
  - Variety comes from an interest profile, the daily rhythm, boredom and novelty; there are no external topic quotas.
  - YouTube (incl. Shorts) and TikTok, logged out: muted, bounded, sign-in walls left.
  - All crypto and finance pages are read-only allowed, including exchanges, DEX, launchpads and this project's own
    coin.
  - Kept, non-negotiable:
    - the guard's harmful categories (adult, gore, self-harm, extremism, illegal), because the screens are public;
    - no actions with money: no wallet, no buy/sell/swap/connect/sign clicks, no logins, typing only into search boxes;
    - no financial advice in his words, and "nothing here is financial advice" on finance pages, to protect the owner
      legally.
  - Task #56.
- **2026-10-02: the 1M spiking network runs on GPU through his waking hours** (owner's choice: ≈ $4–14/day,
  ≈ $130–400/month). Off in code until `SUB01_DAY_LIVE=1`. Caps: `SUB01_DAY_MAX_HOURS` 17/day, `SUB01_GPU_USD_PER_DAY`
  $14, 120 GPU-h/week, ≤ 6 restarts/day. One pod at a time; never the pod "BRAIN". The fallback is the 20k CPU network
  (#55), then the rate model. Task #58.
- **2026-10-02: #15 goes before #17.** After the outage, a health check and the Railway healthcheck path matter more
  than YouTube and chess.
- **2026-10-02: review checklist gains "new module → Dockerfile COPY".** After the #45 incident, every PR that adds a
  top-level module imported by the server must add it to the Dockerfile. The coordinator checks this by importing
  `live_server` from the exact COPY file set, until #18's test does it in CI.

## Known risks
- ~~Map tiles~~: fixed by #47 (static vector map).
- **YouTube walk footage on /life** showed "error 153" in headless Chromium (a missing Referer?). Check it on the real
  site before launch.
- ~~Dark rectangle top-left in the room~~: not visible on a real GPU (owner's screenshot, 2026-10-02); headless only.
- ~~CPU~~: fixed by #48. The whole server is ~9 ms per 50 ms tick (~18 % of a core), leaving room for Chromium.
- **Bandwidth at launch:** after #34, 7.3 KB/s per brain-page viewer and 4.0 KB/s per room viewer. 300 steady viewers ≈
  1.6 MB/s ≈ 140 GB/day of Railway egress: watch the bill after launch. The per-IP cap (4) trusts the first
  `X-Forwarded-For` entry, which a client can forge; the global cap (400) still holds.
- ~~Unbounded spend~~ (fixed by #51: every paid call is capped and in one view). Was: the eye (Replicate) had no daily cap and no log. With viewers always present it renders up to
  ~960 frames/day. Fix: #15. #20 needs a daily USD cap (Opus 5.5 via OpenRouter is ≈ $0.50/hour at the 30-call cap).
- **State files:** `life.json`, `body.json`, `reading.json` and `browsing.json` are written non-atomically, so a kill mid-write
  crash-loops the server at the next start. Fix: #21.
- **Vote load:** on one core with a vote every 5 s, brain ticks are up to 157 ms late (p95 69 ms). Fine at one vote
  per page; #19 adds headroom.
- **Chromium sandbox:** since #50 Chromium runs as uid 1000. If Railway's seccomp blocks the sandbox, it falls back to
  `--no-sandbox` (still non-root) with a loud log line. Since #40 it browses more freely (median
  ~450 MB, max 622 MB for the Chromium tree): part of the reason for Railway's paid plan.
- **Merge conflicts:** five branches touch `live_server.py`, and four touch `sleep.py`. The strict order above
  limits the re-merges.
- ~~No CI~~: CI runs on every PR since #22.
- ~~Test bug on `main` (Chromium tests stopped the driver twice)~~: fixed with the #7 merge.
- **Honesty:** the PCI and Pong results are negative and must stay visible as such. "Digital twin" wording suggests
  a copy of the person; use "a model built from one person's public MRI data".
- **Stale branches** (`feature/rw-*`, `feature/twin-*`, `feature/real-world`, `assets/cc0`, `test/integration`,
  `claude/youthful-bohr-*`, `claude/affectionate-brown-*`): delete them after launch. The coordinator never deletes
  branches.
- ~~Character movement in the room~~: fixed by #28 (2026-10-02). Bed clip and chair follow-ups are in a new PR.
- **Coordinator pushes to PR branches:** only merge commits that clear conflicts, and only when the owner asks. The
  first was #9's `fe60d9f` (2026-10-01). Authoring sessions must pull before pushing.

## Costs per day (estimates; the ledger in #15 will replace them)
| item | now | at launch |
|---|---|---|
| Railway (1 service, ~0.6–1 vCPU, ~300 MB + Chromium ~0.5–1 GB) | plan price | same, plus egress (see #14) |
| Eye: Replicate FLUX schnell + Llama, only while watched | cents | up to ~960 frames/day with no cap → cap at $1/day (#15) |
| Diary: 18 unattended frames/night | ~$0.05 | same |
| Spiking memory test (RunPod, 1 h/day) | $0 (not on) | $0.27–0.85/day, 8 GPU-h/week cap |
| Eyes + mind (#20, #45; Haiku 4.5 via OpenRouter, one ledger) | ≤ $2.00/day (eyes $1.00 + mind $1.00) | same hard cap |

**Owner decision (2026-10-04 01:20 UTC): visual approval.** Nothing that changes how he moves or looks (animations,
the character, the camera, lighting) merges without the owner's OK on a preview video. Each such PR ships an MP4
(30 fps, rendered frame by frame by stepping the page clock, old vs new, ≤ 25 MB) under its docs/ preview folder; the
coordinator sends it to the owner and merges on his OK. AI4Animation was asked about and declined: research/education
only, its mocap is CC BY-NC 4.0.

**Pass 41 (2026-10-04 16:00 UTC): two coordinators.**
- **Split:** the owner asked for two coordinators to go faster.
  - A keeps the character track: G2, G6, G4, G11, G10d, the mocap retarget, the room preview and the live checks.
  - B keeps the technical PRs, the Actions budget, this file and GitHub hygiene.
- **Merged since pass 40:**
  - #139 and #140: see pass 40.
  - #141: the day-live restart log says why each pod died; pods never made don't burn the restart cap.
  - #142: /api/screens keeps today's counts, last pages and notes across a deploy.
  - #143: gpu_preview gets a per-shot hour and life state, a window-texture wait and a living-idles shot list.
  - #144: walls:
    - messaging and app pages are never opened;
    - after a bot check, that site cools down for 6 h;
    - finance pages need a title word.
  - #145: a Spotify hit that matches a genre only through its album name is dropped.
  - #146: desk video mix:
    - at most 2 in a row from one channel;
    - after 4 desk videos, a 5-minute break of pages;
    - shopping lists last.
  - #148: gpu-preview runs get a 600-minute pod-time cap (owner OK); other jobs keep 2 h.
  - #147: gpu_preview:
    - programs are compiled and textures uploaded per shot, so no dropped materials;
    - a dropout check on encode;
    - the canvas is reset;
    - a lit desk-monitor stub, used in preview renders only (the live room is unchanged).
    - Validated locally by B: pytest 1234 passed / 27 skipped, smoke OK, visual 5 passed.
- **Decisions today:**
  - Owner: every visual item is delivered side by side with a real reference photo.
  - **Owner (2026-10-05): the building ("il palazzo").** Why people come back: the audience is crypto Twitter, so
    the answer is a world the community builds. The brain stays as the engine: every choice he makes comes from it.
    - **V1 (on hold: owner stop 2026-10-05 01:50 UTC; not approved until he confirms):** a building across from his window, with 3 lit windows and 3 fictional CT archetype neighbors:
      - the degen, lights on at 4 a.m. and three monitors;
      - the one shouting from the balcony;
      - the calm one meditating.
      - Their energy follows total market activity, never price direction or individual trades.
      - No text, no wallets.
    - **Later:**
      - V2: apartments earned through community participation (gifts, votes), never through the coin.
      - Eviction after 7 days away.
      - The mystery neighbor (a season-long puzzle with clues in his dreams, chess and searches).
      - The building's weekly meeting with community votes.
      - The building gains a floor at each participation milestone.
    - **Hard limits:**
      - no neighbor per trader;
      - no coin or wallet gating;
      - names and letters filtered;
      - no character talks about prices;
      - no claims about what he feels.
    - **Split:** B does the server (building state, activity energy, later points and moderation). A does the visuals
      and brings the owner a still first.
  - **Owner OK (2026-10-05): a second brain, a neighbor girl.** Offline test only, nothing visual yet.
    - **Who:** a fictional woman, about 20, adult, never sexualized.
    - **Her brain:** built from a different public scan (an adult female participant, open license, never named),
      on the cloud, never on the owner's Mac.
    - **Caveat** (docs/real_wiring_report.md): the specific wiring adds only r ≈ 0.04–0.07 over randomised brains, so
      two scans alone would behave almost alike. Her personality comes from her own profile: interests, hours,
      neurochemistry, what CT teaches her.
    - **Step 1 (B):** find the scan, build her connectome with the v1 dipy pipeline on CPU, simulate a day of both,
      and bring the owner the numbers.
    - **Step 1 result (B, offline, rate model, no slow layer, 300 votes per brain on 12 option kinds):**
      - Her scan: OpenNeuro ds002785 (AOMIC-PIOP1) sub-0001, CC0, adult female. Connectome v1 (dipy) gives
        214 regions, 6,147 edges.
      - Him vs her: preference profile r = 0.995; choice shares differ by 3.7 %. That is less than the same brain
        with another noise seed (7–8 %), and less than his own rewired brain (12.7 %).
      - Both pick games, then chess, memes and music.
      - Conclusion: the scan alone gives no visible difference. A different personality must come from her
        profile.
  - CI skips docs-only changes. Workers push with `[skip ci]` and validate locally.
  - CI runs once on main per merge. Budget: about 1,000 Actions minutes for 28 days, about 20 min per run.
- **Waiting:**
  - #135 (client-side player, the fix for the YouTube bot wall): owner's OK asked.
  - #103: owner's choice, close-up camera or the current overhead view.
    - **Merge guard:** before any merge, `preview/skin_eyes/` (G6's sheets with third-party reference crops) is
      removed in its own commit and must be absent from the squash.
    - Rule for every branch: comparison sheets and reference photos live only on preview branches or `preview/`
      folders, never in main.
  - #129: do not merge yet.
  - #134: head 5a32f70 has a bed regression; not to be merged.
  - #137: clearance, waiting for the owner's OK.
  - #117, #131 and #138: A's track.
- **Owner, GitHub settings:**
  - update the repo description, which still says "wired to live Solana trades";
  - enable "Automatically delete head branches".

**Pass 40 (2026-10-04 05:30 UTC).**
- **Merged since pass 39:**
  - Tests and fixes:
    - #122: the sleep test's clock starts after the engine is built (the flake).
    - #123: the window pane never emits NaN texels.
  - Bed:
    - #124: a generated duvet over him, head on the pillow, slides off.
    - #126: follow-up (G4's mesh, foot-end curtain, the motion layer off the bed).
  - Motion: #114, ARDY clips on the original rig plus a procedural motion layer (G3).
  - His internet:
    - #125: teen-interest profile.
    - #127: /api/screens reports the YouTube API state.
    - #128, #130, #132: YouTube's own pages are never opened, refused embeds never stay on screen, and YouTube
      pauses 30 min on a bot wall.
  - GPU previews:
    - #133: `tools/gpu_preview.py` renders old-vs-new MP4s on one RunPod A5000 pod per run. Outputs go to the
      unmerged `previews` branch. About $0.065 and 14 min per run.
    - #136: follow-up.
- **YouTube bot wall:**
  - YouTube refuses its embed player to the Railway IP, so the server shows no videos. #132 pauses it and says why.
  - #135, the fix: playback moves to the viewer's own browser. It waits for the owner's OK.
- **Chromium memory (05:26 live check):**
  - 10 restarts for "over 1200 MB" between 04:02 and 04:54, some 7–21 s apart. Loop lag p95 3.6 s.
  - Assigned to the #89 worker as a technical PR: host cooldown, no re-open after a restart, relaunch off the event
    loop.
- **06:00 live check:**
  - Merged:
    - #139: the headline says "walking · next: …" on a walk home.
    - #140: the #89 Chromium memory fix, applied by the coordinator from the worker's patch.
  - Day-live GPU mode is off for today: "restart cap (6 restarts…)", 7 pods died within ~30 s each. Yesterday it
    ran 16.7 h for $8.00, within caps. Sent to the #58 worker: a restart log in the status, the root cause, and
    a fallback GPU or backoff.
  - /api/screens loses `today` and `last` on every deploy. Sent to #89 to persist them, after #135.
  - At 390 px the chat feed and its input overlap the chess card. Layout, so it waits for the owner.
- **Waiting for the owner's visual OK** (previews on the `previews` branch or in the PR):
  - #103 (G6 lighting and camera; final f342ce7, v3 render queued);
  - #117 (G2 character refinement: eyes, brows, ears, socks, slides);
  - #131 (Tripo props: mug, headphones, sneakers, ramen);
  - #134 (living idles);
  - #135 (client-side YouTube/TikTok player);
  - #137 (G3 clearance fix);
  - #138 (18 more Tripo props).
- **Tripo:** API credits used about 900/920 for props 1+2. Single guarded tasks only, after one accidental batch re-run.
- **Follow-ups queued:**
  - the drink-interlude hand dip into the desk (main);
  - the typing → eating blend through the desk edge (main; #63 worker);
  - the held-bowl offset 0.065 → 0.069 on #131 (G3).

**Pass 39 (2026-10-03 22:00 UTC).**
- **Merged since pass 38:**
  - Live behaviour and content:
    - #109: Shorts through the YouTube Data API v3 and the official embed; TikTok through its official player.
    - #104: the snapshot now sends the walk path.
    - #101: real H01 close-ups.
    - #111: continuous zoom from brain to column to H01.
    - #106: the anatomical brain.
  - Room:
    - #107: G4 soft goods (socks, towel, duvet).
    - #110: G5 hard surfaces.
    - #113: G7 photographic window.
  - Character and QA:
    - #80: boy_moves.glb, 39 clips on the original boy.glb.
    - #112 and #115: G8 QA re-score, 1.7 → 1.9 → 2.4.
  - Fixes and docs:
    - #116: the room's mini brain shows only real fibres, no cell dots.
    - #118: illustrated README; the technical sections moved to `docs/TECHNICAL.md`.
    - The H01 author list was corrected (9eb0afd).
    - #121: G8's visual suite now checks the room's mini brain (no neurons=1, no forest, fibres present).
    - #120: G7's window glass at grazing angles (G8 #26): the view stays, the reflection is capped, cables are strands.
- **Bed regression (owner, confirmed live at 06:11 Tokyo):**
  - What happens: he lies on top of the duvet, diagonally, with his head into the wall. Then #107's duvet under
    #108's lift becomes a tent with a black hole, and the slides poke out at the foot end (G8 defect #25).
  - Assigned to the #63 worker on `fix/bed-duvet` (the room.html sleep block), with G4 on `props_soft.py` (pillow loft,
    duvet thickness or back faces, seams, sock cuffs = #23, #24).
- **Other G8 defects:** #26 fixed by #120; #27 (typing hands) → G3. G4's mesh half of the bed fix is #119 (draft), which
  ships inside the #63 worker's PR. At 22:36 that worker was still rendering poses and tuning head drift.
- **Open PRs:**
  - #114 (G3, ARDY plus the procedural layer, `?motion=` table): the motion sheet is pending.
  - #103 (G6): fixed exposure per state; boy.glb was rendering fully metallic. The final push is pending.
  - #117 (G2, boy.glb rebuilt in place): changes requested. Doll-like eyes with gaps, a black streak at the collar,
    bake blotches on the slides and socks, noisier side hair, paler skin.
- **GitHub Actions has been down since 19:05 UTC.** Every job ends in seconds with no runner and no logs: an
  account-level billing or spending limit. The owner must check Settings → Billing. Until then, PRs merge on local
  evidence (pytest, smoke, tests/visual).
- **Repo cleanup:**
  - Closed the finished issues #99, #88, #76, #75 and #68.
  - The session cannot delete branches. Still to do by the owner: 61 branches of closed PRs, 19 old unmerged `rw-*` and
    `twin-*` branches, and the repo description (still "wired to live Solana trades").

**Pass 38 (2026-10-03 15:10 UTC).** Overnight, most workers stopped on the weekly usage limit, which reset at 11:00
UTC. The owner said "procedi" and all were restarted at 14:20 UTC.
- **Merged:** #100 (G1 research catalogue), #102 (G8 visual-QA harness + `visual` CI job; photoreal scorecard
  baseline 1.7/5), #105 (B: every meaningless dot gone, plus the `test_no_dots.py` guard) and #108 (#63: he sleeps
  under the duvet, head on the pillow, slides parked by the bed, side poses; 0 bed and 0 chair penetration).
- **Open:**
  - #104 (coordinator: `life.path` and `path_to` in the snapshot, G8 defect #21) and #109 (#89: YouTube Shorts through
    the official Data API v3 and the official embed; TikTok through its official player; real bursts on shorts; the
    HN repeat loop) are being tested together. The **owner must add `YOUTUBE_API_KEY` on Railway** (step-by-step
    sent).
  - #80 (motion for the original boy.glb): eating hand to fix; merge main and leave the sleep slot to #108.
  - #103 (G6 rendering): night auto-exposure overshoots (night floor RGB 10 → 136); fix requested.
  - #106 (G9 anatomical brain): fresh, dissected, tract bundles, arteries and nerves; must merge main.
  - #101 (A, H01 close-ups): draft.
- **Live, day 2026-10-03 (Tokyo):** 390 pages; TikTok, Shorts and YouTube 0 % (the root causes are fixed in #109);
  Wikipedia 4.6 %. The night of 10-02 was dreamed and the diary written ("Whispers in the Night", 28 frames).
  Day-live GPU about $8, within the caps; the pod stops at sleep; BRAIN untouched.
- **Permissions:** G8 is blocked on a permission prompt (the owner must approve it or switch it to Auto).

**Pass 35b (21:00 UTC): #97 merged; #99 opened (neurons and brain at maximum realism).**
- **#97 merged:** no more white-out (pixels above 0.8: 12–31 % → ≤ 0.04 % at rest); about 500 cells at ~6×.
- **The owner wants more:** "realismo massimo", plus "si vedono ancora pallini che non capisco perché esistano"
  (he still sees dots and doesn't know why), plus real brains, neurons and nerves.
  - **B:** first removes every meaningless dot (soma sprites, spike beads, fibre ends, the raster panel), with a test
    that stops them coming back. Then a seamless zoom from the MRI brain → cortical layers → column → real tissue.
  - **A:** close-ups with REAL H01 human electron-microscopy neurons (CC-BY 4.0, to verify; MICrONS as fallback):
    spines, myelin and real synapse positions, with simulated activity on the real axons.
  - **G9 (new, Fable 5.1, `session_01LMGGwqUaFhqqz1Ly4zPgPi`, `web/brain_anatomy.js`):** a real-specimen brain:
    fresh and dissected views, surface vessels, cerebellum, brainstem, circle of Willis, cranial nerves I–XII. The
    caption says which parts are this person's MRI and which come from an atlas or template. Every licence is checked
    (BodyParts3D, Z-Anatomy, ICBM152, BigBrain, Allen, Julich).

**Pass 35 (20:55 UTC): the game-quality pass, #98.** The owner asked for "fino a 10 agenti Fable 5.1 high effort":
the original character and the room should look like a game ("come gta 6"); the socks look like cones today.
Eight Fable 5.1 sessions, each with its own files and branch:

| stream | session | owns |
|---|---|---|
| G1 research | `session_01TkggML3LD8V548ES1VSWzQ` | `docs/research/game_look.md` |
| G2 character asset (same rig and identity) | `session_01P57GRNVUAnrDS7UTVKjNWX` | `web/room/boy.glb`, `room_build/boy_asset/` |
| G3 motion: NVIDIA ARDY clips (on a RunPod GPU, ≤ $10) + procedural layer | `session_01PgdfFVr2NQ1pv4XzcnVdho` | `web/room/boy_m_*.glb`, `web/room/boy_motion.js`, one `room.html` hook |
| G4 soft goods (socks, towel, duvet, curtains) | `session_016aZgMaYz6zrDs9ixK1WSbH` | `room_build/props_soft.py` |
| G5 hard surfaces | `session_01FkKWq952Y3xL491LFipsUr` | `room_build/props_hard.py` |
| G6 rendering and post | `session_01WXcEt8rwJzruPUN8yCSpGc` | `web/room_post.js`, the renderer/lighting block of `room.html` |
| G7 window and outside | `session_01TG1TVAJp29Fn6WptEZsjTq` | `web/room/window_view.js`, the sky/window block |
| G8 visual QA and scorecard | `session_01NDriQn2UBDqaCZqVBJir2i` | `tests/visual/`, `docs/qa/` |

- **ARDY** (nv-tlabs/ardy, the owner's link): the code is Apache-2.0 and the checkpoints are under the NVIDIA Open
  Model License. Its text encoder is the gated Llama-3-8B-Instruct, so the owner may need to accept Meta's licence on
  Hugging Face and add a token as a RunPod secret. G3 reports this before asking.
- **Higgsfield caps:** G2 ≤ 200, G4 ≤ 80, G5 ≤ 80, G7 ≤ 40 credits (625 left at start).
- **Binary GLBs:** `room_clean.glb` is rebuilt by G4 and G5, never hand-merged.
- **#95 merged** (the chess fix: 1109 passed, chess smoke finished a game in 131 s).

**Pass 34 (20:20 UTC):** merged #84, #96, #94 and #91. Each was checked by the coordinator.
- **#84 (room polish and phone screen module):** 1101 passed, smoke OK at 7.2 ms per tick.
- **#96:** the room's mini brain shows the neurons (`?mini&neurons=1`).
- **#94 and #91 (#88 A polish and B, the whole-brain neuron forest):** tested together on main. 1106 passed. One
  CPU-time test failed under load and passes on its own. Smoke OK.
  - Open item: ≥ 30 FPS for the forest on a mid-range phone still needs a real device.
- **#95 (#63 worker): the chess smoke fix.** The cause: `hungry_now()` ended a game he had just started, before the
  board existed. The fix is in `life.py`; CI is running. The sleep pose audit comes next on the same branch.
- **Character:** a second candidate, `boy3`, made with Higgsfield and Meshy 6. It is an original face, styled to the
  owner's brief.
  - Same 24-bone rig as `boy.glb`; the existing clips are retargeted with `room_build/retarget_meshy.mjs`.
  - Branch `claude/loving-davinci-6hqmjx` (bd5804e); preview in `docs/design/boy3/`.
  - The #76 worker compares boy2 (MakeHuman, with fingers and blink) and boy3 in the room and picks one in #80.
  - **Decision (owner, 20:40 UTC): keep the ORIGINAL character (`boy.glb`).**
    - He saw boy4 (boy3's outfit with the original face) and said "bruttissimo, meglio il nostro personaggio
      originale".
    - boy2, boy3 and boy4 are not shipped. They stay only on branch `claude/loving-davinci-6hqmjx`, unmerged.
    - #80 is now limited to better motion for the original rig (new clips retargeted, where they beat the current
      ones) and the room fixes. If nothing retargets cleanly, #80 is closed.

**Pass 33b:** live check (the coordinator logged in with the owner's approval) and merge of #92 (#89).
- **Sleep fix confirmed live:** NREM since 03:19 Tokyo, debt 2.0 h, woken 0×. The day-live pod stopped; only "BRAIN" is left.
- **Found live:**
  - **Browsing:** 30 pages, all on the phone: 8 on Wikipedia, 0 YouTube/Shorts/TikTok, the same page reopened (Studio Ghibli ×5 in 2 min), footer and licence clicks.
  - **Music:** Spotify search 502 from the server.
  - **Room:** he sleeps on top of the duvet, diagonally, with his slides on.
  - **/life:** an old low-poly house and a blank white box.
  - **/brain:** empty "now playing" and "at his desk" cards.
- **#92 merged** (coordinator run: 1087 passed, smoke 7.8 ms). It fixes:
  - the Wikipedia fallback loop and the footer links;
  - the 7-day no-reopen rule;
  - phone time defaulting to the shorts feed;
  - TikTok through the official player;
  - the screens panel;
  - DA bursts;
  - the room's fake Wikipedia frame;
  - /life's real phone screen;
  - the hidden empty cards.

  It is verified live when he wakes, at 00:30 UTC.
- **New:**
  - #93: /life uses the real room scene.
  - #63 worker: sleep pose and animation audit, after #84.
  - #76: mocap animations first (Quaternius UAL CC0 plus keyframed CC0 poses), then a face pass.

**Pass 33 (18:25 UTC):** merged #86, #87 and #85.
- **#86 (#78 follow-up):** neuron close-ups now read as tissue.
- **#87 (#63 part 2):** real food. The dish is picked at order time, arrives in the bag, is eaten bite by bite and
  goes in the bin. Main + #87 + #85: 1031 tests passed.
- **#85: the sleep fix.** Merged by the coordinator on the owner's "procedi".
  - Live before it: absurd "trades" still showed (buy $94,902,346), he was awake at 03:00 Tokyo, and the 1M day-live
    pod had started at 18:00 UTC ($0.49/h, within caps).

Owner feedback and new tasks:
- **"Neurons are glowing balls; I want them as real as possible, with Fable 5.1 and Opus 5.5 agents"** → #88:
  - **A (Fable 5.1, `session_01CUqYBHvE9DFkQCQ3tKaDep`, draft PR #90):** a microscopy-grade close-up renderer in
    `web/neuron_render/`. Real SWC radii, soma with nucleus, spines, myelin with nodes of Ranvier, boutons; a
    fluorescence look; saltatory action potentials.
  - **B (Opus 5.5, `session_011MftcyrW5FVGYgrg1keFNo`):** a whole-brain neuron forest in `neurons3d.js`. Pyramidal cells
    point along the cortical normal. Also fixes the panel overlap at 1920 px.
  - The API is agreed: `NeuronRender.open/onFrame/close`.
- **"Still Wikipedia, no TikTok at all; I want dopamine spikes on TikTok"** → #89 (`session_01GCTUbSh9sLTfmffpYtv3aR`).
  The diagnosis found certain causes:
  - `room.html`'s `drawReading()` paints a fake "WIKIPEDIA – The Free Encyclopedia" frame around any reading title when
    there is no desk screenshot;
  - /life's phone showed TikTok only from an empty static `phone_feed.json`, so it never showed TikTok;
  - logged-out TikTok returns no videos to a datacenter IP;
  - YouTube `/watch` gets "unusual traffic" quickly;
  - shorts ran only at lunch and late at night.

  The fix:
  - real host and kind on the monitor, and the real phone screenshot on /life;
  - phone time defaults to the shorts feed;
  - TikTok through its official embed player (oEmbed JSON on the server);
  - an always-visible "screens" panel;
  - phasic dopamine-like bursts per new short, with habituation, shown as a DA trace.
- **"Ugly animations; log in and check everything":** the coordinator could not log in, because the session's security
  classifier blocks using the site password. The owner is asked either to allow it or to send `/api/browsing` and the
  Railway log lines.

**Pass 32:** merged three PRs, one at a time, after one combined run of main + #85 + #81 + #82 + #83:
1028 tests passed, smoke 7.6 ms.
- **#81 (#79):** his readings come from what he browses. Wikipedia falls from 100 % to 9.5 % of readings, and the
  Wikipedia reader is now only a fallback.
- **#82 (#63 part 1):** natural motion. He holds the phone on the bed, eats at the desk, and lies with headphones
  nodding to music. 0 penetration of bed or chair. This also covers the #68 room follow-up.
- **#83 (#78):** neurons with their real shape (NeuroMorpho, CC BY 4.0). Close-ups of cortex, striatum, thalamus,
  hippocampus and amygdala carry live spikes. Jitter follow-up asked.

**Urgent owner task:** the sleep fix, **PR #85** (`fix/sleep-and-trades`, by the coordinator).
- **Cause:** the default `--mint` was a third-party Raydium LaunchLab token. Its `TradeEvent` shares pump.fun's
  discriminator, so it was decoded as 793,100 SOL buys. Those pinned him awake: arousal 215, debt 105 h, no REM.
- **Fix:**
  - `MINT` empty means no trade feed.
  - The decoder checks the emitter program, our mint and our pools, and is tested on real mainnet transactions.
  - A $250k cap per trade.
  - Total arousal is capped. Past 18 h of debt, sleep pressure overrides outside arousal.
  - Every restart clamps the state. A one-time repair resets the fake debt and tonight's broken record.
- **Checks:** 996 tests passed; CI green.
- **Waiting on:** the owner to merge.

**Next:**
- #84 (room polish) merges main, re-sweeps against #82's paths, then integrates into `room.html`.
- #63 part 2 (food) comes as a new PR.
- #83 follow-up: jitter, plus the room mini brain `neurons=1`.
- #76 (character) stays in draft until it clearly beats the old one.

**Pass 31:** no PRs open. #63 part 1 is due ~17:40 UTC; #75 and #76 are in progress; RunPod shows only "BRAIN"
(he is asleep in Tokyo).

New tasks:
- **#78, neurons with their real shape** (`session_013KjJYiSDhQYs85Ddjfmdgv`). Cells come from NeuroMorpho.Org under
  CC BY 4.0, with three citations per cell. Far away they show as points; close-ups show 100–300 full cells with
  spikes running along the axon. The caption says the shapes are illustrative and the model uses point neurons.
  - **Decision:** no Purkinje close-up. The 214-region model has no cerebellum, so it would show fake activity.
    Hippocampus CA1 replaces it.
- **#79, readings from real browsing** (`session_01GCTUbSh9sLTfmffpYtv3aR`). The owner still sees too much Wikipedia.
  - **Cause:** the old `research.py` Wikipedia reader still runs in parallel (`run_research`) and feeds every "reading"
    (memory card, replay, memory test, diary). #69 only changed the browser.
  - **Fix:** readings come from pages he actually browsed. The Wikipedia reader stays only as a fallback.
  - **Target:** ≤ 10 % Wikipedia in readings.
  - **Scheduling:** `index.html`/`life.html` are shared with #78, but in different sections.

**Pass 30e:** merged #77 (#62): his active neurons are visible inside the 3D brain on /brain and /life.
- Spikes flash per region; region rates tint the clouds.
- The stream is ≈ 3 KB/s per viewer.
- No fake spikes: there is an offline state, and the caption is honest when the budget holds spikes back.
- GPU frames now carry per-region rates (`rq`).
- The Neurons card shows real decisions per day: paid-off picks per network, and the replay learned vs frozen twin.
- Coordinator run: 978 tests passed; tick 7.1 ms. FPS on a real phone is still to be checked by the owner.
- The room mini brain gets a one-line change after #63.

**Owner set `SUB01_POD_SECRET`, `SUB01_DAY_LIVE=1` and `SUB01_CHOICE=1` on Railway (16:30 UTC).** The site restarted
and `/healthz` is ok; RunPod shows only "BRAIN". The first day-live pod should start when he wakes (Tokyo morning, about
22–23 UTC). The coordinator checks it at 23:15 UTC.
- The owner asked about biollm.com. Declined: it is a consumer app with no API and no verifiable data, and it conflicts
  with the rule against unproven claims.
- The owner asked about the RunPod MCP server. Not needed: the site's pod manager runs on its own, and the coordinator
  already has read access to RunPod.

**Pass 30d:** merged #74 (#70): the 1M network's live decisions learn.
- **1M on GPU, 240 trials:** learned 0.45–0.69 correct, against 0.24–0.38 for the frozen twin and 0.24–0.30 for random (chance 0.29).
- **Criterion:** reached in 9/10 runs before and after the reversal. The frozen twin and random never reached it.
- **Why #67 showed no learning:** it had too few rounds, not a bad race.
- **New live read-out:** `diff`, which is robust to the 2.4 → 5.3 Hz baseline drift. It is a reasoned choice, not a measured win.
- **Sample size:** 3 networks, so small samples.
- **RunPod:** $0.106, 3 pods one at a time, all deleted; only "BRAIN" remains.
- **Coordinator run:** 964 tests passed, tick 7.5 ms.

**Pass 30c:** merged #72 (#59): daily clips for the official social accounts.
- Up to 3 vertical clips a day (day, dream, his brain's choice), each frame labelled "AI · fictional character · simulated brain".
- Rendered at nice 19 with a CPU cap; no tick cost.
- Auto-post is off without tokens, and posts are private or drafts flagged as AI-made.
- `/admin/clips` sits behind the admin token or the password cookie.
- Image +300 MB (ffmpeg).
- Coordinator run: 955 tests passed, tick 7.8 ms.

#74 (#70) is approved and waits for its docs conflict fix.

The owner asked for room work: fix the floating post-it and the lamp in the wall, the room looks empty, a better phone screen
and graphics, and a better character. New tasks:
- **#75 room polish:** `room_build/` and `room_clean.glb`, plus new files; `room.html` only after #63.
- **#76 a better character:** a CC0 MakeHuman/MPFB2 route, finger bones, `boy2.glb` behind `?boy=new`; integration after #63.

#63 now gates five pieces of room work (music headphones, #62's mini brain, #75, #76, its own food), so it merges first.

**Pass 30b:** merged #71 (#68 server side): he listens to music.
- His brain vote picks 3–5 candidate tracks by time of day, tastes, taught words and chat wishes.
- Playback is only through Spotify's official embed, started by each viewer on their own device. The server reads JSON only.
- Without `SPOTIFY_CLIENT_ID`/`SECRET` it falls back to a curated list.
- Coordinator run: 935 tests passed; `--music` smoke 9.4 ms with the spiking child running.
- The room part (headphones, head nod) comes after #63.

Also merged #73 (coordinator): `boot.py` now writes `exit_code` atomically. This fixes an intermittent end-to-end test
seen while reviewing #72.

#72 (#59 daily clips) is approved and waits only for its merge of main. Note: the image grows by +300 MB (ffmpeg),
accepted.

**Pass 30:** merged #69 (#56 part 2). He now browses like a young guy: interests rotate with the hour, there are
Shorts/TikTok sessions, he looks up things he has seen, and finance is read-only with a "nothing here is financial
advice" line. In the coordinator's day simulation, Wikipedia's share of pages fell from 28 % to 4 %, and topic entropy
rose from 2.96 to 3.48 bits.

Also merged #65 (#55): a 20k-neuron spiking network runs on the server CPU as a numpy-only child process.
- It votes in browsing choices as one small term (0.3 × lean) and learns from the stay's response.
- The 1M GPU network is asked first, through `day_live_decide`; the rate model is the last fallback.
- Every decision goes to `/data/spiking/decisions-*.jsonl`. The card shows the learned curve against a frozen twin and chance.
- Coordinator run: 901 tests passed. Smoke run with no torch: tick 7.9 ms; the child takes 2.9 CPU-s at start, idles
  at 2 % of a core, and sent 26 frames to /ws.

Started #62 (active neurons in the 3D brain), on /brain and /life only. The room's mini brain follows after #63, and
`session.py`/`choice.py` stay with #70. #71 (music) is waiting for a merge of main (Dockerfile COPY conflict).

**Pass 29:** merged #67 (#58), the 1M network live on GPU through his waking hours. It is off until
`SUB01_DAY_LIVE=1`, with caps of 17 h/day, $14/day, 120 h/week and 6 restarts. Measured A4000 secure at $0.25/h ≈
**$4.1/day**. 842 tests with torch and Chromium; RunPod validation cost $0.127; only "BRAIN" is left (EXITED). No learning is
shown yet at 1M (41/50 races decided at the first check), so follow-up **#70** is started (a read-out that scales).
#68 music (official Spotify embed) is started.

**Pass 28b:** merged #66 (#60): logged-in, view-only TikTok and YouTube from the `SUB01_SESSION_*` secrets.
Chromium's env is scrubbed, cookies are domain-scoped, actions and private pages are blocked, and the avatar is
hidden. 789 tests. After deploy, `/api/browsing` → `accounts.tiktok` should read "logged in". #63 now also covers
real food: props, courier bags, dishes, hand-to-mouth eating.

**Pass 28:** merged #64 (#56 part 1): 10 free search sources routed by topic, ≤ 20 requests/host/hour, follow-up
searches, and queries from notes, reading, taught words, tastes and chat. Searches 31 → 52/hour, with no paid calls on
result pages. Parsers are fixture-tested only; check `/api/browsing` after deploy. Next: #56 part 2 (variety, TikTok
and Shorts, finance) and #60 integration, both in browse.py.

**Pass 27c:** the owner's live screenshot (23:05 Tokyo) shows the site up after the #49 fix, with the mind plan,
the teach card and the static map live. It also shows no dark rectangle on a real GPU, so it was a SwiftShader-only
artifact. He stood frozen while ordering food: `phone_stand` is a `still()` pose in the middle of the room. New #63
(natural movement: no frozen poses, living idles, smooth transitions) is started. The owner set `SUB01_SESSION_TIKTOK`;
#60 is started, with new files first and integration after #56.

**Pass 27b:** merged #61 (#57): he eats before chatting. In the coordinator's re-run, minutes above meal time with
chat waiting went 124–211 → **0** (9 runs); deliveries are eaten within 2 min; a 24 h konbini. New tasks:
- #59 daily clips for the official social accounts (started);
- #60 logged-in, view-only TikTok/YouTube (after #56);
- #62 active neurons inside the 3D brain (after #55 and #58).
The owner has created the TikTok account.

**Pass 27 (owner: "turn his neurons on, more things, more internet searching", "is he fed?", "I want the big one"):**
new tasks:
- #55: a small spiking network on the server CPU votes and learns live; it is the fallback for #58;
- #56: many more free search sources, with queries from memory, wishes and taught words;
- #57: he went hungry while chatting (147 min/day above meal time with chat waiting); fix with needs first and a 24 h konbini;
- #58: the 1M network on GPU through his waking hours.

## Launch readiness (2026-10-02, after pass 26)
**All task issues are closed and no PRs are open.** 27 PRs were merged today, #27–#54: attribution, tastes page,
room movement and follow-ups, launch load, mind layer (A, B, room), tastes faster, spiking choice, free browsing,
teach him (server and room), static map, brain loop 6× cheaper, Dockerfile hotfix, non-root, costs/caps/healthz,
YouTube + chess (server and room). Main has 600+ tests (with torch and Chromium), smoke OK, and a tick of ~9 ms per
50 ms. Every paid call is capped (~$3.10/day AI and images + ≤ 1 GPU-h RunPod).

Everything left is for the owner:
1. Railway: healthcheck path `/healthz`, `SUB01_ADMIN_TOKEN`, an uptime monitor, a usage alert, and a paid plan.
2. Railway: `SUB01_POD_SECRET`, unless already set with the RunPod key; optionally `SUB01_CHOICE=1`.
3. After the next deploys, check the logs and the site:
   - the site is up (the #49 outage is fixed);
   - the `CHROMIUM SANDBOX FAILED` line (fine either way, but note it);
   - YouTube plays muted on /brain (it could not be tested end to end in the sandbox);
   - the /life walk video (headless showed YouTube error 153);
   - the dark rectangle top-left in the room (headless SwiftShader only?).
4. Decide the GPU budget beyond 1 h/day if you want faster neuron learning.
5. Email for him (18d), the reply to Russ, the legal check for the coin, the X account.
6. Launch day: remove `SITE_PASSWORD`; watch `/api/health` and `/api/costs` for 24 h.

## Launch checklist (owner)
- [x] All task milestones merged; CI green (2026-10-02). [ ] `/healthz` monitored (uptime alert to your phone/email).
- [ ] Costs per day measured for 3 days with the password on, all caps set, Railway usage alert set.
- [x] Load test (#14) passed at 300 viewers (#34).
- [ ] `/about.html` live and linked from every page; footer disclaimer on every page.
- [ ] Researcher email: tell the dataset's authors (OpenNeuro ds000031) what the site is, before launch. Do not
      name the scanned person anywhere on the site or on X.
- [ ] Legal check for the coin, in your jurisdiction: the site shows trades only as stimuli; no advice, no buy
      pressure, no wallet or on-chain action by the project.
- [ ] X account ready. Posts follow the same wording rules (no consciousness claims, no price talk).
- [ ] Secrets set on Railway only: `SITE_PASSWORD`, `REPLICATE_API_TOKEN`, `RUNPOD_API_KEY`, `SUB01_POD_SECRET`,
      `OPENROUTER_API_KEY` (set), optional `ANTHROPIC_API_KEY`; later `SUB01_ADMIN_TOKEN`.
- [ ] Railway on a paid plan (trial credit showed 24 days / $4.17 left on 2026-10-02).
- [ ] Launch day: remove `SITE_PASSWORD`; watch `/api/health` and spend for the first 24 h.
