# His spiking neurons in the day: the small CPU network (issue #55)

The 1M-neuron GPU network of #58 is described in `docs/spiking/live.md`.

Step 3 of "his own neurons decide". Until now the spiking network ran only at night on a RunPod GPU. Now a small
simulated spiking network (20,000 neurons), built on the same wiring, runs on the server CPU all day. It takes part in
his real browsing choices as one small term of the vote, and it learns from what follows.

Since #58, the 1M-neuron network on a GPU pod is asked first when it is on. This small network answers when the pod
is down or over its cap, and the rate model alone decides when neither answers. Every decision and its reward are logged
for the night session (#58 sends them to the pod).

**Short answer.** It works as built, at about 0.4 s of CPU per decision in its own process. The 50 ms brain tick is
unchanged (8.8–9.5 ms vs 8.9–9.2 ms on `main`). On a synthetic reward stream with variable offers it beats its frozen
twin and chance: 0.57–0.65 correct vs 0.28–0.32 (chance 0.28–0.29), 3 of 3 seeds. The decaying learning rate keeps the
preference from drifting: 0.56–0.70 over the last 50 decisions, against 0.38–0.46 without it. There are no live numbers
yet, because nothing has been deployed. The page shows them as they come, whatever they are.

Code:
- `spiking/live.py`: the network, the child process, the server-side client, the day's decisions log and the card;
- `spiking/wiring.py`: the numpy construction shared with `net.py`;
- `brain_vote.py`: the term in `vote` and the decision backend `Backend` (GPU, then CPU, then the rate model).

Tests are in `tests/test_spiking_live.py`.
Numbers are in `docs/spiking/live/results.json`, and the scripts are in `docs/spiking/live/`.

## Design

| part | choice | why |
|---|---|---|
| engine | **numpy**, its own module (`spiking/live.py`), sharing the construction with `net.py` through `spiking/wiring.py` | torch is not in the server image (~700 MB). At 20k neurons an event-driven numpy step costs ~0.6 ms per simulated ms on one core. The same config and seed give the same synapses as `net.py`, checked bit for bit in a test (with torch). The dynamics are the same LIF equations. There is no recorded resting-state drive: the network idles between decisions |
| process | a child process (`python -m spiking.live`) speaking the decision protocol shared with #58 as JSON lines on stdin/stdout. It is started and supervised by `LiveClient` in the server (restarted with a backoff), and exits when its stdin closes | the brain tick never waits for it. A decision runs in the child while the event loop goes on |
| backend | `brain_vote.Backend.ask`: the GPU pod's `day_live_decide` (#58; looked up at each call, absent before #58) with a 1.5 s deadline, then this CPU network (2 s), then nothing. The answer carries `net`: `gpu`, `cpu` or `rate`, and the decision record says which network answered ("1M-neuron network on GPU" / "20k-neuron network on CPU" / "rate model only") | one protocol, so `vote` does not care which network answered |
| size | 20,000 neurons (`SUB01_SPIKING_LIVE_NEURONS`), 2,019,400 synapses. **754** of them are plastic (cue → striatum) | the size of the #39 CPU runs |
| cues | each content word of a label (≤ 4) is hashed exactly as `memory.py` does (`wiring.word_neurons`), at 8 % of the E neurons of every parcel. The visual and language parcels are kept | the same word lands on the same neurons in every label. Option labels change on every page, so the only way something learned can carry over is through shared words |
| pools | the striatal E neurons, split among the offered labels by the hashed affinity of #39, averaged over the label's words and rank-normalised. Any 2–6 options | disjoint pools. Labels that share words share striatal neurons. The word count does not change pool size |
| race | #39's: cues at 8 mV after 100 ms of background; every 10 ms the pool rates since cue onset are compared with the threshold (mean + 2 sd at 100 ms, calibrated once on the untrained network and saved). The first pool over it wins, not before 50 ms. At 250 ms the highest pool is taken | unchanged from #39 |
| the vote | `brain_vote.vote(..., spiking=)` adds `SPIKING_W` (0.3, `SUB01_SPIKING_W`) × lean, where lean = tanh((pool rate − mean rate) / 2 Hz), in −1..1 | a term the size of the novelty bonus, next to the rate-model value (−1..1) and the taste (0.5 × −1..1). The rate model stays the main decider |
| fallback | no answer within 2 s, the process down, or an answer that does not fit → the term is skipped (`spiking: {used: false, why}`) | the vote is then exactly the rate model's |
| dopamine | when he leaves the page, the stay's tastes prediction error (`Tastes.learn`) × `DA_GAIN` (2), clipped to ±1, goes to the decision that led to the page | tastes errors are mostly within ±0.5, and #39's rule was tuned for ±1. This gain was not tuned on live data |
| learning | #39's rule: dw += η · da · pre · post, with the tag set at the decision. post = +1 on the pool of the option **followed** (the vote's choice), −1/(K−1) on the other offered pools | the dopamine belongs to the option that was followed, which can differ from the network's own pick |
| stability fix | η = 0.6 mV / (1 + n / 50), never below 0.15 mV (`ETA_HALF`, `ETA_FLOOR`) | the drift that `docs/spiking/choice.md` named. Measured below |
| weights | `/data/spiking/live_weights.npz` (dw, counters, threshold, config hash), written atomically (tmp + fsync + rename) after every learned decision and loaded at start. A torn file is kept aside as `.corrupt-<time>`, and a file for another network is ignored | as `state_io` does for JSON |
| frozen twin | a copy that shares the synapse arrays and never learns. It gets the same offers and the same noise (the seed is set per decision) | the fair control for the learning curve. Its picks are logged, not voted |
| log | `/data/spiking/decisions-YYYY-MM-DD.jsonl` (Tokyo day, `state_io.append_jsonl`), the format agreed with #58. A decision row is `{"t", "id", "kind", "options", "pick", "net", "reward": null}`, where `pick` is the option followed; it adds `net_pick` (the network's own pick) and, for `cpu`, `twin_pick`. A reward row, appended to the same file when he leaves the page, is `{"t", "id", "reward", "response"}`: `reward` is the tastes prediction error, `response` the stay's response (> 0 = paid off). Every browse decision is logged, whichever network answered | the card's curve, and the night's input (#58) |
| frames | the child streams `{"type": "spiking", "net": "cpu", ...}` frames in the GPU session's format (groups, mean rate, a raster of 200 sampled neurons), at most 5/s while it simulates. Between decisions it runs 50 ms of background activity every 2 s, so the raster keeps a pulse | the Neurons panel on `/brain` draws them like the GPU's. GPU frames win while they come. #62 draws them in 3D |

`/api/spiking/live` (behind the password gate) feeds the "In the day" part of the Neurons card on `/brain`. It shows:
live or offline, choices today, the decisions it learned from, the lean of the last choice ("his spiking neurons leaned
toward …"), and the learning curve.

**The curve on the card.** Among the decisions whose followed option paid off (the stay's tastes response > 0: his
brain model's reward/attention activity went above its recent average), it shows how often the network's own pick was
that option, against the frozen twin's pick and chance (the mean of 1/K).

One bias is stated on the card: its lean nudges which option is followed, so a match is a little more likely for it
than for the twin even with no learning. The same match rate on the decisions that did *not* pay off is shown next to
it. A network that only "agrees with the vote" scores high on both.

## Cost (one core of this sandbox, 20k neurons)

| | measured |
|---|---|
| build + calibration at start (with the twin) | 2.2 s CPU, once (build 0.36 s) |
| one decision, learner + frozen twin | mean **375 ms** CPU, p95 595 ms, max 757 ms (100 decisions, 2–6 options) |
| one decision without the twin | 203 ms |
| simulated decision time | mean 110 ms. 22 of 100 reached the 250 ms timeout (forced choice) |
| between decisions | 1.4–2.0 % of a core (the 50 ms idle pulse every 2 s, for the page's raster; `SUB01_SPIKING_LIVE_IDLE_MS=0` turns it off and then it uses 0.00 %) |
| child peak RSS | 128 MB (learner + twin, 20k) |

The budget was < 10 % of one core = 360 CPU-s per hour, which is ~960 decisions per hour. Browsing makes one decision
per page. The eyes allow 30 AI calls per hour, plus local-option pages. At 30–120 decisions per hour that is
**~0.3–1.3 % of one core**, plus 1.4–2.0 % for the idle pulse: ~2–3 % in all. The rate on Railway has not been measured yet. Check it on the card ("its process: … % of
one CPU core on average", sampled every minute) or in `tests/smoke_demo.py` (the `SPIKING CHILD` line).

**The 50 ms tick** (`tests/smoke_demo.py --measure 30`, demo mode, BROWSE=0, same machine, runs alternated):

| | runs |
|---|---|
| `main` | 9.1, 9.0, 8.9, 9.2 ms CPU per tick |
| this branch | 9.2, 9.0, 9.5 ms; with the frames on `/ws`: 9.4, 8.8 ms |

The child's CPU is not in these numbers: it runs in its own process. In the demo there are no browsing decisions, so the
child only starts (~3 CPU-s), then runs its idle pulse (26 frames reached `/ws` in 30 s). The protocol test also checks that a child which never answers is
skipped after its timeout while a 50 ms ticker on the same event loop keeps ticking (max gap < 150 ms).

## Learning on a synthetic stream (20k, numpy, 150 decisions)

The stream has six labels with hidden reward probabilities 0.8 / 0.2 / 0.3 / 0.4 / 0.2 / 0.3. Each decision offers a
random 2–6 of them. The option followed is the network's pick with probability 0.7, otherwise a random offered one
(standing in for the rate model). Dopamine = r − V, with V += 0.1 (r − V), like the tastes' slow prediction. "Correct" =
the network picked the best offered option. The learner and its twin see identical offers and noise. Script:
`docs/spiking/live/run_live_checks.py learn SEED [ETA_HALF]`.

| seed | learned | frozen twin | chance | learned, last 50 | twin, last 50 | learned curve per 25 decisions |
|---|---|---|---|---|---|---|
| 0 | **0.647** | 0.32 | 0.281 | 0.70 | 0.30 | 0.40 0.92 0.52 0.64 0.80 0.60 |
| 1 | **0.573** | 0.293 | 0.289 | 0.56 | 0.32 | 0.36 0.72 0.72 0.52 0.56 0.56 |
| 2 | **0.62** | 0.28 | 0.29 | 0.64 | 0.38 | 0.40 0.72 0.60 0.72 0.68 0.60 |

The same streams **without the stability fix** (η constant at 0.6 mV):

| seed | learned | learned, last 50 | curve |
|---|---|---|---|
| 0 | 0.56 | 0.44 | 0.32 0.68 0.68 0.80 0.52 0.36 |
| 1 | 0.533 | 0.38 | 0.48 0.76 0.72 0.48 0.28 0.48 |
| 2 | 0.533 | 0.46 | 0.40 0.76 0.56 0.56 0.32 0.60 |

With a constant η the preference forms and then drifts away, as in `choice.md`. The decaying η keeps it: 0.56–0.70 over
the last 50, against 0.38–0.46. It still wobbles from block to block (seed 0: 0.92 → 0.52 → 0.80), so the fix is
partial.

In the pytest version (10k, 100 decisions, seed 1, ~25 s) the network learned 0.64, the twin 0.29 and chance was 0.286.

## The night uses the day

The night session belongs to #58. It reads the day's decisions files (format above) and replays the day's real choices
on the 1M network. An earlier version of this PR had its own night replay; it was dropped when #58 took over
`pod_manager.py`, `session.py` and `server.py`.

A CPU check of that replay (torch, 20k, 120 synthetic choices) was made before it was dropped: frozen 0.35, after one
learning pass 0.53, with learning removed 0.29, chance 0.32. That was 49 paid-off choices, scored on the same choices
it learned from. No GPU run was made for this PR.

## Reading it honestly

- **It is a small term.** The rate model, the tastes and the novelty decide most choices. The spiking network shifts the
  odds by at most ±0.3 on the softmax input.
- **Only 754 synapses learn.** At 20k neurons the wiring gives few visual and language → striatum synapses. That is
  enough for the synthetic stream, where labels repeat. Real labels change on every page, so learning can only carry
  over through shared words ("bread", "search", "video"). Nothing here shows that it does that well on real data.
- **"Paid off" is the tastes response.** That is simulated activity of his brain model during the stay (reward,
  attention and fear relative to its recent average), with chat, trades and readings mixed in. It is a noisy, simulated
  reward. It is not what the page was worth.
- **The frozen twin is not exactly at chance.** Pool sizes and cue → pool synapse counts differ, so it has built-in
  biases, as in #39.
- **What it is.** A small simulated spiking network (20,000 neurons) built on the same wiring takes part in his choices
  and learns from simulated reward. It does not think, understand or want anything.

## Switches

| env | default | what |
|---|---|---|
| `SUB01_SPIKING_LIVE` | `1` | `0` does not start the child: the vote is the rate model's alone |
| `SUB01_SPIKING_W` | `0.3` | the weight of its lean in the vote |
| `SUB01_SPIKING_LIVE_NEURONS` | `20000` | the network's size. Learned weights are only loaded into the same size |
| `SUB01_SPIKING_LIVE_IDLE_MS` | `50` | background activity between decisions, every 2 s, for the page's raster (`0`: none) |
