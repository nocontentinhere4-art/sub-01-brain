# The 1M-neuron network live on GPU through his waking hours (issue #58)

Owner decision (2026-10-02): run the large network, 1M LIF neurons on a RunPod GPU, through his waking hours. It
answers his real choices and learns from what follows. Hard daily caps apply. When the pod is down or over a cap,
the small CPU network of #55 decides instead (`docs/spiking/live_cpu.md`), and if that is down too, the rate model alone.

**Off by default.** Nothing changes until `SUB01_DAY_LIVE=1` is set on Railway.

Code:
- `spiking/pod_manager.py` (day-live mode);
- `spiking/server.py` (the decision protocol in the hub);
- `spiking/session.py` (phases `live_decide` and `live_bench`, and the night replay of real decisions);
- `spiking/choice.py` (`LiveChooser`).

Small changes elsewhere:
- `spiking/runpod_ops.py`: a GPU list with a cloud type;
- `spiking/podpack.py`: two more allowed GPU types and the cloud type;
- `spiking/costs.py`: `usage_on`, hours and USD split at Tokyo midnight.

Tests are in `tests/test_day_live.py`. The benchmark and validation driver is `docs/spiking/live/run_live_pod.py`,
with `live_pod_host.py`.

## How a day runs

| sleep engine says | for | the pod manager does |
|---|---|---|
| AWAKE | 5 min (`WAKE_CONFIRM_S`) | starts **one** pod with phases `live_decide` + the night phases; it loads the latest learned weights from the server |
| AWAKE | the waking day | the pod runs the network at most at real time and answers `decide` messages; the learned weights go to the server every 30 min |
| NREM / REM | 10 min (`SLEEP_CONFIRM_S`) | sends `night` to **the same pod**: the day's top items (as for the nightly session) and, with `SUB01_CHOICE=1`, the day's real decisions with their outcome |
| asleep | ≤ 45 min | the pod runs recall_yesterday → encode → choice_train (replay of the real decisions) → memory_test → sleep → memory_test, uploads the weights and says done; the pod is deleted |
| asleep | the rest of the night | no pod. A waking at night (before 05:00) starts nothing: that day's night is already done |

- If no day pod ran (it failed, or the server restarted in the evening), a night-only pod runs the night phases
  alone, bounded by 45 min.
- The NREM ↔ REM switches do not reset the 10-min confirmation; only an awake ↔ asleep switch does.
- The sleep engine's stage reaches the manager through `SpikingHub.forward_sleep`, which `live_server.py`
  already calls every tick. **No `live_server.py` change is needed.**

## The decision protocol (shared with #55)

```
server → network  {"type":"decide","id":str,"options":[label,...],"kind":"browse|chess|plan","deadline_ms":int}
network → server  {"type":"decision","id":str,"pick":int,"pool_rates":[float,...],"sim_ms":float,"n_neurons":int}
server → network  {"type":"reward","id":str,"value":float}
server → pod      {"type":"night","day":str,"items":[...],"decisions":[{"options","pick","reward","kind"}]}   (GPU only)
```

### API for `brain_vote` (#55)

```python
from spiking import pod_manager
d = await pod_manager.day_live_decide(options, kind, deadline_ms=2000)
await pod_manager.day_live_reward(d["id"], value)
```

- Both coroutines never raise. They return `None` at once when day-live is off or no pod is live.
- `d` is also `None` when the pod has not answered by the deadline. The caller then uses the CPU network, then the
  rate model.
- They wrap the hub's `live.spiking.decide(...)` and `live.spiking.reward(...)`; the hub registers itself when a
  day-live manager is attached.
- Otherwise `d` is the decision plus:
  - `"net": "gpu"`;
  - `"label": "1M-neuron network on GPU"`, the text the decision card shows;
  - `"rtt_ms"`.
- `day_live_reward` forwards the dopamine for that decision; a decision the GPU did not make is ignored.

Every GPU decision and reward is logged by the hub to `/data/spiking/gpu_decisions-<Tokyo date>.jsonl`:
- the decision: `{"t","id","kind","options","pick","net":"gpu","pool_rates","sim_ms","rtt_ms"}`;
- its reward, on its own line: `{"t","id","reward"}`.

At sleep onset the manager reads these files together with #55's `/data/spiking/decisions-<Tokyo date>.jsonl`:
- the format agreed with the coordinator: decision rows `{"t","id","kind","options","pick","net","reward":null}`,
  then reward rows `{"t","id","reward"}` appended with `state_io.append_jsonl`;
- merged by `id`;
- decisions from the waking day only, with an outcome, at most 300.

**#55 should log the GPU's own id for decisions the GPU answered**, so no decision is counted twice.

## On the pod: `live_decide` and the learning rule

- **Cues are real option labels.** The label's first 3 content words are each hashed as in `memory.py`, at 5 % of
  the excitatory neurons of every visual and language parcel; a 3-word label gets about the 15 % cue of #39.
  Labels that share a word share part of their cue.
- **Pools.** For 2–6 options of any text, the striatal neurons are split among the offered labels by hashed
  affinity (as in #39).
- **The read-out** (#70) is `diff` by default: decide when the top pool leads the second by more than 3 sd of a
  pool-rate difference, else the highest pool at 250 ms. The 1M benchmark and the reasons are in
  `docs/spiking/choice.md` ("Read-outs at scale"). Session config `live_readout` (`race` / `scaled` / `diff` /
  `window`) and `live_readout_kw` override it.
- **The eligibility tag** is that of #39.
- **Reward** applies `dw += η_label · δ · tag`, with `δ = value − V[label]`.
- **Stability fix** (`docs/spiking/choice.md`: the learned preference drifted):
  - a slower value estimate, α = 0.05 instead of 0.1;
  - a learning rate that decays with the number of rewards the label has had, `η_label = max(0.15, 0.6 / √(1 + n/20))`.
- `value` can already be a reward-prediction error (the tastes signal) or an outcome (chess). `V` absorbs a
  constant offset either way.
- `V` and `n` per label are saved in the weights' meta, so they survive a new pod.
- **Speed.** The network runs in 20 ms chunks, paced to at most real time. The server's messages are read between
  chunks, so a decision starts at most ~20 ms after it arrives.
- **Uploads.** The weights go up every 30 min in a background thread, and again at the end. A lost pod loses at
  most 30 min of learning.
- **Reconnects.** After a websocket reconnect the pod says `hello` and `live_ready` again, so the hub uses it again.
- **Night.** `choice_train` replays the day's real decisions: the option he really took is tagged as chosen and its
  real outcome is the dopamine. Before and after, frozen, it reports how often the network's own pick agrees with
  the outcomes (`fit_before`, `fit_after`). It also reports the same fit for the frozen twin, the network with every
  learned change removed (`fit_frozen_twin`, #70), and the fraction of the day's decisions that paid off.

## Hard caps (all enforced by the server, each with a log line)

| Variable | Default | What happens at the cap |
|---|---|---|
| `SUB01_DAY_LIVE` | `0` | `1` turns the mode on |
| `SUB01_DAY_MAX_HOURS` | 17 | GPU hours on the Tokyo day (a pod's time is split at midnight). The pod is asked to stop 90 s before the cap (it uploads the weights) and is deleted at the cap at the latest. No pod until the next Tokyo day |
| `SUB01_GPU_USD_PER_DAY` | 14.00 | RunPod's reported $/h for the pod (`costPerHr` at creation) × uptime. Same stop/delete; #55's network decides until tomorrow |
| `SUB01_GPU_HOURS_CAP` | 120 in this mode (8 otherwise) | rolling 7 days; same stop/delete |
| `SUB01_DAY_MAX_RESTARTS` | 6 | a pod that was made and died (no hello in 15 min, stream lost for 3 min, pack upload failure, done with an error) is a restart. The next pod waits 2, 5, 10, 20, 40, 60 min; after 6 restarts no pod until the next Tokyo day. No pod made (no capacity, an API refusal, another SUB-01 pod running) is **not** a restart: the manager tries again every 5 min (2 min while another pod runs) |
| `SUB01_GPU_TYPES` | see below | `"type:CLOUD,type:CLOUD"`, tried in order |

Other rules:
- Every pod's cost goes to `/data/spiking/costs.jsonl` as before, so `/api/costs` shows it under `runpod`. Note that
  `/api/costs` books a pod on its start day, while the cap splits it at midnight.
- **Exactly one SUB-01 pod.** Every 10 min, and at startup, any pod named `sub01-spiking-*` that is not the current
  one is deleted as an orphan.
- **"BRAIN" is never touched.** `RunPodOps` re-fetches every pod before a delete and refuses one without our prefix;
  the tests check it.
- `/api/spiking/status` shows `day_live`:
  - the stage and the pod's mode;
  - why the mode is blocked, if it is;
  - restarts today, today's hours and USD, and the caps;
  - `decisions`: whether the pod answers, plus the asked, answered, timed-out and rewarded counts;
  - `learning` (#70): per Tokyo day, the fraction of real picks that later paid off (GPU and the other networks),
    and the night replay's fit, learned vs frozen twin (`docs/spiking/choice.md`).

## Why a pod died: the restart log (fix of 2026-10-04)

On 2026-10-04 the mode hit its restart cap by 06:20 UTC: 7 restarts, while the cost log showed only 0.063 GPU-h.
RunPod's own billing (`GET /v1/billing/pods`) showed 7 pods that day, alive 98–876 s, about 0.93 GPU-h and $0.25.
The status said nothing about why each one ended.

**What the code allowed.**
- `RunPodOps.create` gave the create request a 60 s timeout. When it failed without an HTTP answer (a timeout or
  a dropped connection) it looked for the pod once and moved on to the next GPU type.
- A pod that RunPod created anyway then ran **untracked and unlogged**, until the orphan sweep deleted it within
  about 10 min. That fits the 14.5-min pods, and the cost log being 15× below billing.
- The next try found "a pod of ours already exists", and that, like "no capacity on any type", counted as a restart.
  So the cap could burn with almost no logged cost.
- The same day the hosts themselves worked: a 4000 Ada secure pod ran the 1M benchmark normally (1.25× real time),
  and yesterday's weights and the night replay also run locally on a day-2 sequence.

**Changes.**
- **Restart log.** `/api/spiking/status` → `day_live.restart_log` keeps the last 10 entries, each
  `{t, why, pod_id, gpu, secs_alive, last_error, counted}`:
  - `last_error` is RunPod's own message for a create (for example "HTTP 500: create pod: There are no instances
    currently available"), the upload error, the pod's `status.json` phase and error with the last line of its
    `session.log`, or the error the pod reported with done;
  - everything is cut to one short line, with anything that looks like a key or a token redacted;
  - `day_live.gpu_failures_today` and `day_live.next_try` are shown too.
- **Create.** The create request may take 150 s. After an ambiguous error the manager looks for the pod by name for
  about a minute. If it finds it, the pod is adopted: tracked and logged.
- **No pod made is not a restart.** No capacity on any type, an API refusal, or another SUB-01 pod running: a
  restart-log entry with `counted: false`, and the manager tries again in 5 min (2 min while another pod runs).
- **Orphans.** The sweep deletes only pods this manager makes (`sub01-spiking-day-`, `-night-`, `-session-`) and
  books the cost of one that was never logged, from RunPod's `createdAt` at its `costPerHr`. Another session's
  validation pod is left alone; the manager waits for it to go.
- **GPU fallback.** A type whose pod died today moves to the back of the list for the rest of the day; the list
  keeps its price order otherwise.
- **Backoff.** The first restart waits 2 min instead of 1.
- **CUDA filter.** Create requests ask for a host with CUDA 12.8 or newer (`allowedCudaVersions`), since the image
  is built for CUDA 12.8. A pod on an older driver would never start. Checked live: a 4000 Ada secure pod was created
  with the filter and ran (0.03 GPU-h, $0.009).

## Cheapest GPU that keeps up (measured 2026-10-02)

Viable means a decision within 2 s and the network at ≥ 0.5× real time.

- **Bench pods** ran the `bench` phase, then `live_bench`, with no server:
  - 5 s free-running with the live settings;
  - then 40 decisions among 2–6 random labels, each with a reward and 500 ms between them.
- **The validation pod** ran the full protocol through the real hub (see below).
- All on 1M neurons, 101M synapses, 5.7 GB of GPU memory.

| GPU | cloud | $/h (RunPod) | steps/s free (×real time) | steps/s with decisions | decision wall p50 / p95 / max | plasticity off / STDP on (bench) | verdict |
|---|---|---|---|---|---|---|---|
| RTX A4000 16 GB | community | 0.17 | 1,242 (1.24×) | 1,061 (1.06×) | 78 / 103 / 126 ms | 1,278 / 240 | viable, cheapest |
| RTX A4000 16 GB | **secure** | **0.25** | live: 1.00× (paced to real time) | — | 71 / 306 / 424 ms on the pod; 116 ms p50 at the hub | — | **viable: the default** (validation pod) |
| A40 48 GB | secure | 0.49 | 1,521 (1.52×) | 1,322 (1.32×) | 59 / 82 / 211 ms | 1,493 / 314 | viable, 2× the price |
| L4 24 GB | secure | 0.49 | ~44 (0.04×), build 136 s instead of 3.5 s | — | — | — | **not viable** (stopped after 10 min) |
| RTX A4500 | secure / community | 0.25 / 0.19 | — | — | — | — | no capacity at the time: not measured |
| RTX 4090 | community | 0.34 | — | — | — | — | no capacity at the time: not measured |

For reference, earlier runs (`docs/spiking/gpu*/results.json`) measured plasticity off at:
- RTX A5000: 1,448 steps/s;
- RTX 4000 Ada: 1,353 steps/s;
- A40: 1,266 steps/s.

**Default list (`DAY_GPUS`), cheapest first:**
1. RTX A4000, secure;
2. RTX A4500, secure;
3. RTX A5000, secure;
4. RTX 4000 Ada, secure;
5. A40, secure, the fallback that is usually in stock.

Why secure only: the pod carries `SUB01_POD_SECRET`, and community hosts are third-party machines. The owner can opt
in with `SUB01_GPU_TYPES="NVIDIA RTX A4000:COMMUNITY,..."` (−32 %).

Capacity changes by the minute: two of five attempted types had no instances, and the same A4000 secure that was
full at 14:00 UTC was free at 14:19. The list is tried in order on every start.

**Expected cost:** ~16 h awake + ~0.5 h night ≈ 16.5 GPU-h/day.

| GPU | per day | per 30 days |
|---|---|---|
| A4000 secure, $0.25/h | **≈ $4.1** | ≈ $124 |
| A40, if only that is available | ≈ $8.1 | ≈ $243 |

The $14/day cap is never reached at these prices. 120 GPU-h/week allows 17 h/day.

## Validation run (one pod, from this session)

Raw results: `docs/spiking/live/validate-a4000-secure.json`.

**Setup.** `run_live_pod.py validate` started one RTX A4000 (secure, $0.25/h). On the pod, `live_pod_host.py` ran
the same `SpikingHub` code as Railway on port 8001, and the session's websocket pointed at it. This session sent
the rounds through the RunPod proxy:
- 50 `decide` messages, each among 2–6 labels from a pool of 20 page titles and chess moves, deadline 2 s;
- after each, a `reward`. The synthetic outcome was +1 for options containing tea / moon / park / bread and −0.5
  otherwise, with noise.

Then it waited for a periodic weight upload (every 3 min in this run instead of 30), sent `night` with 3 items and
the 50 decisions, waited for the night phases, and deleted the pod.

| | result |
|---|---|
| boot → pack uploaded | 25 s |
| pack → `live_ready` (build 1M + calibration) | 18 s |
| decisions answered | **50 / 50**, all within 2 s; 0 timeouts, 0 late |
| decision time on the pod | p50 71 ms, p95 306 ms, max 424 ms |
| hub decide → decision (the protocol round trip on the pod) | p50 116 ms, max 479 ms |
| this session → RunPod proxy → hub → back (not the production path) | p50 545 ms |
| rewards accepted | 50 / 50 |
| real time during the live phase | 1.00× (paced) |
| periodic weight upload | 123.6 MB, landed 109 s after the rounds |
| night phases | 175 s (encode, replay of the 50 decisions, memory tests, sleep 2 min sim); 3/3 items recalled after encoding and after sleep |
| final weight upload | HTTP 200, 123.6 MB |
| pod deleted | yes, confirmed gone from the pod list; "BRAIN" still there and untouched |
| cost | **0.115 GPU-h, $0.029** |

**What it does not show.**
- **No learning effect.** In the first 25 rounds where a paying option was on offer the network picked one 18 of
  22 times; in the last 25, 18 of 25. Fifty rounds over 15 labels is far too few to see learning, and many offers
  contained several paying options. The night replay's frozen fit stayed at 0.88 before and after.
- **The race at 1M.** As in #39, 41 of the 50 decisions were taken at the first allowed check (50 ms), because
  large pools have very little rate noise (sd 0.4 Hz). The race is then mostly "which pool is highest at 50 ms".
  Measured in #70 (`docs/spiking/choice.md`): in a 240-trial benchmark the race still learned, and the live default
  is now the `diff` read-out.
- **The production network path.** The Railway → pod websocket path was not exercised; the pod's link pointed at a
  hub on the pod itself. The protocol code is the same and is round-trip tested in CI.

## RunPod use in this task

| pod | GPU, cloud | purpose | minutes | GPU-h | cost |
|---|---|---|---|---|---|
| 9fd5htrbozacib | RTX A4000, community | bench | 1.7 | 0.029 | $0.005 |
| 6jjwp4abcb9ges | L4, secure | bench (stopped by hand: too slow) | 10.0 | 0.167 | $0.082 |
| 3gasanrm71i8ms | A40, secure | bench | 1.5 | 0.025 | $0.012 |
| jwmjydyd51km0r | RTX A4000, secure | validation | 6.9 | 0.115 | $0.029 |
| **total** | | | | **0.334** | **$0.127** |

- #70 learning benchmark (`run_live_pod.py learn`), three more pods, one at a time:
  - knudfgxexrjmom, RTX A5000 secure, 9.0 min, $0.041;
  - m9de4dv6duflno, RTX A4500 secure, 6.8 min, $0.028;
  - ozepfxk1xeiw9m, RTX 4000 Ada secure, 7.8 min, $0.037.

  Total 23.7 min, $0.106. A4000 secure had no capacity each time.
- One pod at a time; each was deleted and confirmed gone.
- Five create attempts were refused by RunPod for lack of capacity (no pod created): A4000 secure (twice),
  A4500 secure (twice), RTX 4090 community.
- The pod named "BRAIN" was never touched.
- Cost log: `docs/spiking/live/costs.jsonl`.

## Owner actions after merge

Set these on Railway:
1. `RUNPOD_API_KEY` (done, per the owner).
2. `SUB01_POD_SECRET`: a long random string.
3. `SUB01_DAY_LIVE=1`.
4. `SUB01_CHOICE=1`, so the night replays the day's real decisions.

Optional:
- `SUB01_GPU_USD_PER_DAY`;
- `SUB01_GPU_TYPES`, for example to allow the community cloud.

Check after deploy:
- the logs say `day-live mode on`, then `day pod … started` within ~5 min of his waking;
- `/api/spiking/status` → `decisions.live_ready` is true;
- `/api/costs` → `runpod` grows by ≈ $0.25 per hour.
