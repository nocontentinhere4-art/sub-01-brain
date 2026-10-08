# The spiking network learns to choose (issue #35)

Step 2 of "his own neurons decide". Question: can the spiking network, from dopamine alone, learn to pick the
option that is rewarded more often among K cued options, faster than chance and better than its own frozen copy?

**Short answer.** Yes, in this simple task. The model learned to pick the rewarded cue in 20–61 trials at 20k
neurons on CPU (median 25) and in 84 trials at 1M neurons on GPU. After the reversal it re-learned in 22–46
trials. The frozen network and the random chooser never reached the criterion before the reversal. The learned
preference is not stable in every network, though, and the frozen network has built-in biases. Both are reported
below. This is a 4-armed bandit with fixed cues. It does not show that the network understands the options.

Code: `spiking/choice.py`, session phases `choice_train` / `choice_exam` in `spiking/session.py` (scheduled only
with `SUB01_CHOICE=1`; off by default), tests in `tests/test_spiking_choice.py`.

## Design

| part | choice | why |
|---|---|---|
| cues | each option label is hashed as in `memory.py` (`MemorySystem.word_neurons`, same seed), at 15 % of the excitatory neurons of each **visual and language** parcel | the same word always lands on the same neurons, so real option labels can be cues later |
| action pools | the excitatory neurons of the **striatum** (caudate, putamen, accumbens, both sides: the `reward` group of `regions.py`), split among the offered options by a hashed affinity per label | cortico-striatal synapses are the classic site of dopamine-gated plasticity. Pools are disjoint, and a given label set gets the same pools in every session |
| decision | race: every 10 ms each pool's mean rate since cue onset is compared with a threshold (mean + 2 sd of pool rates at 100 ms, calibrated on the untrained network). The first pool over it wins (not before 50 ms). At 250 ms the highest pool is taken and the trial is flagged as a timeout | a forced choice at the timeout keeps learning from stalling while the network is untrained |
| reward | Bernoulli, hidden p = 0.8 / 0.6 / 0.4 / 0.2. At the halfway trial the probabilities are reversed (best ↔ worst) | the reversal tests unlearning |
| dopamine | prediction error δ = r − V[chosen], V += 0.1 δ (a running estimate per cue, prior 0.5) | |
| learning | only on plastic **cue → action-pool** synapses: dw += η δ · pre · post, tagged at decision time. pre = clamp((cue-neuron rate in the decision window − 5 Hz) / 40 Hz, 0, 1). post = +1 for the chosen pool, −1/(K−1) for the other offered pools (zero-sum). η = 0.6 mV per unit δ | the eligibility is set at the decision, with no 1 s trace to bridge, so only the synapses that took part in the choice are tagged |
| weights | `w0` (connectome) untouched; all learning in `dw`; w = clamp(w0 + dw, 0, w_max = 2 mV) as in `plasticity.py` | checked in the test |

**Does a pathway exist in the real wiring?** At 20k neurons, about 2.3 of the 30 long-range excitatory inputs of
a striatal neuron come from visual and language parcels. Somatomotor neurons get about 2.2, salience 9.0, dorsal
attention 4.8 and control 5.4. With 15 % cues, every (cue, pool) pair has 19–42 plastic synapses at 20k neurons.
An open-loop check with all four cues driven and every cue → pool-0 synapse set to w_max (20k, 5 × 200 ms):

| action group | cue fraction | pool 0 rate before → at w_max (Hz) | other pools at w_max (Hz) |
|---|---|---|---|
| striatum | 0.1 | 5.9 → 9.0 | 5.9–6.3 |
| striatum | 0.3 | 7.5 → 15.6 | 7.9–9.1 |
| somatomotor | 0.3 | 6.0 → 12.4 | 7.5–7.7 |
| salience | 0.3 | 9.9 → 40.4 | 15.2–15.8 |

So the striatum is not the easiest target (salience would be), but its pathway is large enough. We kept the
striatum for the biology.

**What did not help.** In 10k sweeps (3 networks × 100 trials), raising η to 1.2 made learning less reliable,
and a lower threshold (1 sd) did not help. A count-based exploration bonus (1 mV / √(1 + times chosen) on each
pool) was mixed at 10k. At 20k, network 1, it did worse (criterion at 26 and 44 trials vs 25 and 36, and 0.54 vs
0.75 correct overall). The bonus stays in the code, off by default (`bonus_mv`). A per-trial learning-rate decay
(`eta_decay`) is also available, off by default, and was not tuned. The STDP × dopamine rule of
`plasticity.py`, with its 1 s trace, is not used in this task. The session switches it off in the choice phases.

## Numbers

Criterion: 14 of the last 20 trials correct (70 %). "Correct" means the option with the highest current reward
probability. At chance (1/4), reaching 14/20 has p ≈ 10⁻⁴ per window. Over hundreds of trials a random chooser can
still reach it occasionally, and the test checks that this is rare. Trials to criterion count from the start of
the phase (before or after the reversal), so the minimum is 20.

### CPU, 20k neurons, 5 networks (net seeds 1–5), 200 trials, reversal at trial 100

Each network is compared with a frozen twin built from the same seed: same synapses, plasticity frozen, the same
trial and reward stream. Raw results are in `docs/spiking/cpu_choice/*.json`. Script:
`docs/spiking/cpu_choice/run_cpu_choice.py`. Each run takes ~2 min on 1 CPU core.

| net | learned: trials to criterion | after reversal | fraction correct | last 20 before reversal | last 20 | frozen: to criterion / after rev. / fraction correct | random: fraction correct |
|---|---|---|---|---|---|---|---|
| 1 | 25 | 36 | 0.75 | 1.00 | 0.95 | never / never / 0.27 | 0.23 |
| 2 | 61 | 46 | 0.575 | 0.60 | 0.85 | never / never / 0.265 | 0.24 |
| 3 | 20 | 22 | 0.70 | 0.40 | 0.85 | never / never / 0.305 | 0.22 |
| 4 | 25 | 38 | 0.765 | 0.95 | 0.85 | never / **42** / 0.335 | 0.27 |
| 5 | 43 | 32 | 0.645 | 0.35 | 0.80 | never / never / 0.31 | 0.235 |
| **mean** | **34.8** (median 25) | **34.8** (median 36) | **0.687** | 0.66 | 0.86 | 0 of 5 / 1 of 5 / **0.297** | **0.239** |

Learning curves (fraction correct per block of 20 trials; the reversal comes after block 5):

| net | learned | frozen |
|---|---|---|
| 1 | 0.55 0.85 0.85 0.80 1.00 · 0.10 0.85 0.95 0.60 0.95 | (0.27 overall) |
| 2 | 0.20 0.45 0.65 0.75 0.60 · 0.00 0.45 0.90 0.90 0.85 | (0.265) |
| 3 | 0.70 0.75 0.60 0.65 0.40 · 0.60 0.85 0.95 0.65 0.85 | (0.305) |
| 4 | 0.60 0.90 0.90 0.50 0.95 · 0.25 0.75 0.95 1.00 0.85 | (0.335) |
| 5 | 0.10 0.60 0.80 0.85 0.35 · 0.20 0.95 0.90 0.90 0.80 | (0.31) |

The run with the exploration bonus (net 1, 1 mV) reached criterion at 26 and 44 trials with 0.535 correct, worse
than without the bonus.

### CPU test, 10k neurons (in `pytest`, ~25 s)

`test_network_learns_rewarded_cue_better_than_frozen_twin`: net seed 3, 60 trials, no reversal. Learned: criterion
at trial 20, 0.87 correct. Frozen twin: 0.20 correct, never at criterion. Random: 0.18. The test also checks that
`w0` is unchanged, that the frozen twin's `dw` stays zero, and that the learned weights point to the best option's
pool. At 10k the pools are small (~42 neurons) and learning is less reliable: in a 3-network × 100-trial sweep,
networks 2 and 3 reached criterion before and after the reversal, while network 1 reached it only before (42
trials) and did not re-learn after the reversal.

### GPU, 1,000,000 neurons (one validation pod, NVIDIA A40)

Raw results are in `docs/spiking/gpu_choice/results.json`. Wall time on the pod: 105 s (choice_train 72.5 s for
400 trials, choice_exam 14.7 s). Speed: 1,266 steps/s, 1.27× real time with plasticity off. Pools have 3,872–3,907
neurons and cues 26,846. Calibrated threshold: 4.08 Hz (pool rate 3.56 ± 0.26 Hz).

| | trials to criterion | after reversal | fraction correct | last 20 before reversal | last 20 |
|---|---|---|---|---|---|
| learned (dopamine) | **84** | **22** | 0.66 | 1.00 | 0.95 |
| same network, plasticity frozen | never | never | 0.285 | 0.30 | 0.45 |
| random chooser | never | never | 0.23 | 0.30 | 0.25 |

Learned curve per 20 trials: 0.05 0.00 0.50 0.50 1.00 · 0.60 1.00 1.00 1.00 0.95. Exam after training (frozen, 40
trials on the post-reversal probabilities): **1.00 correct**. The same network with all learned changes removed
scored 0.275, the random chooser 0.26 (chance 0.25).

Cost: one pod, 0.04 GPU-hours, $0.02. It was deleted at the end, and the "BRAIN" pod was not touched.

## Reading the numbers honestly

- **It beats both controls.** In 5 of 5 CPU networks and on the GPU, the learned run reached the criterion before
  the reversal, and its overall fraction correct (0.58–0.77) was well above the frozen twin (0.27–0.34) and the
  random chooser (0.22–0.27). The frozen network never reached the criterion before the reversal.
- **The frozen network is not exactly at chance.** Pools receive unequal numbers of cue synapses (19–42 per pair
  at 20k), so the frozen network prefers some pools. On net 4, the post-reversal best option happened to be the
  preferred one, and the frozen twin met the post-reversal criterion (42 trials) with no learning at all. Fraction
  correct over the whole run is the fairer comparison.
- **The learned preference drifts.** In nets 3 and 5, the last 20 trials before the reversal were only 0.40 and
  0.35 correct after reaching the criterion earlier. With a prediction-error rule, δ goes to zero for the chosen
  option once V matches its reward rate. Negative δ on its unrewarded trials (20 % of them for p = 0.8) then keeps
  pushing its weights down. Exploration of the other options gives them positive δ, so preferences can flip back
  and forth. The 1M GPU run did not show this within 100 trials.
- **At 1M neurons, decisions were always fast** (mean 51 ms, 0 % timeouts). Large pools have little rate noise
  (sd 0.26 Hz), so the calibrated threshold sits only 0.5 Hz above the mean and is crossed at the first allowed
  check. The race then becomes "which pool is highest at 50 ms". The first 40 trials (0.05, 0.00) stayed on a
  wrong option. A higher `thr_z` at scale is the obvious next thing to try; it was not tried here.
- **What this is not.** The options are four fixed words shown together. The network learns which striatal pool
  the cue input should favour. It has not been shown to generalise to new labels, to handle variable offer sets
  (the code supports `offered`, but it is not measured here), or to remember across sessions (the learned `dw` is
  saved with the weights like everything else, but that was not tested). Nothing here says it understands or wants
  anything. The model learned to pick the rewarded cue.

## What a GPU session adds

- Bigger pools, so cleaner races. That made the post-reversal re-learning fast (22 trials) and the frozen exam
  perfect (1.00).
- Time for more trials in the daily hour: ~400 trials took 72 s of pod time.
- The same code path as the scheduled sessions. With `SUB01_CHOICE=1`, `choice_train` runs a frozen pass, then
  training, then a random-chooser baseline. `choice_exam` runs a frozen exam, the same exam with learned changes
  removed, and the random chooser. Results go to `results.json` (`choice_curve`, `choice_exam`) and to the report
  (`spiking/report.py`).

Next, before wiring this into his real choices (`brain_vote.py` / `tastes.py`, not touched here): variable offer
sets with real labels, a stability fix for the drifting preference (for example a slower V, or a decaying η), and
a higher race threshold at 1M neurons.

**Update (#55):** variable offer sets with real labels, and the stability fix (a decaying learning rate), are now in
`spiking/live.py`, where a small network uses them in the day. See `docs/spiking/live_cpu.md`. Read-outs for 1M (a higher threshold among them) are measured in #70, below.

## Read-outs at scale and the live learning benchmark (issue #70)

**Question.** In the #67 validation, 41 of 50 races at 1M neurons ended at the first 50 ms check. Large pools have
little rate noise, so the calibrated threshold is crossed at once and the pick is mostly the network's built-in
pool bias. Does a read-out that scales make the live decisions learn, measured against the frozen twin and random?

**Short answer.** At 1M neurons on GPU, every read-out tried, the merged race included, learned clearly above the
frozen twin and the random chooser: 0.45–0.69 correct vs 0.24–0.38 (frozen) and 0.24–0.30 (random). The frozen twin
and the random chooser never reached the criterion. No read-out was better than the others in every network. The
first-check race did **not** stop learning in this benchmark. The "no learning" of the #67 validation came from too
few rounds (50 over 15 labels), not from the race. The live default is now the `diff` read-out. It learned as
well as the race, and it does not depend on the absolute pool rate, which drifted 2.4 → 5.3 Hz within minutes.
These are three networks, one run each: small samples, reported as they are.

Code: `spiking/choice.py` (`Readout`, `bandit_experiment`, `payoff_by_day`), phase `live_learn` in
`spiking/session.py`, tests in `tests/test_spiking_readout.py`.

### The read-outs (`choice.Readout`, shared by `ChoiceTask` and `LiveChooser`)

All are calibrated on the network as it is: the pool rates at 100 ms in 12 presentations of one 4-label offer.
Nothing is decided before 50 ms; at the 250 ms timeout the highest pool is taken.

| read-out | rule | at 1M |
|---|---|---|
| `race` (#39, merged) | first pool above mean + 2 sd of the calibration rates | sd 0.12–0.18 Hz: decided at the first check in 72–100 % of trials |
| `scaled` | the race with `thr_z` × √(pool size / 100), never below the race: the margin of a 100-neuron pool | threshold +1.5 to +3.1 Hz above the mean; whether it is crossed depends on the drifting rate (see below) |
| `diff` | the top pool leads the second by more than 3 sd of a pool-rate difference. That sd is measured over presentations, so fixed pool biases are not counted as noise. It is scaled as Poisson noise to the time since onset (√(100 ms / t)) and to the offered pools' size | difference sd 0.09–0.13 Hz; mean decision 104–127 ms, 17–24 % timeouts |
| `window` | the highest pool at a fixed 200 ms | always 200 ms |

### The benchmark: #39's bandit with variable offers and real labels

- Labels: 8 page-title-like labels, e.g. "Tea ceremony history" or "Stock market news". Their hidden reward
  probabilities are 0.85, 0.75, …, 0.15. The cues and pools are those of the live decisions (`LiveChooser`).
- Offers: every trial offers a random 2–6 of the 8 labels. "Correct" means picking the best offered label.
- Reward and reversal: the outcome is Bernoulli and the dopamine value is +1 if it paid off, −1 if not. At trial
  120 of 240 the probabilities are reversed.
- Settings: the live learning rule (α 0.05, decaying η) and a 150 ms gap between trials.
- Criterion: 14 of the last 20 correct.
- Controls, for each read-out on the same network, the same offers and the same reward numbers:
  - the frozen twin: the same network before learning, with plasticity frozen;
  - the learned run;
  - a random chooser. Chance is the mean of 1/K over the offers, ≈ 0.29.
- Between read-outs every learned change is removed again, so each read-out starts from the same weights.

Driver: `docs/spiking/live/run_live_pod.py learn`. Raw results:
`docs/spiking/live/learn-1m.json`, `learn-1m-seed2.json`, `learn-1m-seed3.json`.

### GPU, 1,000,000 neurons, three networks (seeds 1–3), 240 trials each

Pools have ~3,890 neurons (4-label calibration). Decision: mean decision time in simulated ms, then the fraction
decided at the first check / timed out.

| seed (GPU) | read-out | calibration mean ± sd (Hz) | learned: trials to criterion / after reversal | **learned: fraction correct** | last 20 | decision | frozen twin: to criterion / after | frozen: fraction correct | random |
|---|---|---|---|---|---|---|---|---|---|
| 1 (RTX A5000) | race | 2.40 ± 0.13 | 66 / 47 | **0.50** | 0.15 | 50 ms, 100 % / 0 % | never / never | 0.24 | 0.30 |
| 1 | scaled | 5.32 ± 0.25 | 29 / 43 | **0.69** | 0.85 | 234 ms, 0 % / 87 % | never / never | 0.28 | 0.30 |
| 1 | diff | 4.51 ± 0.32 | 87 / 47 | **0.51** | 0.65 | 127 ms, 31 % / 24 % | never / never | 0.32 | 0.30 |
| 1 | window | 4.08 ± 0.12 | never / 47 | **0.49** | 0.55 | 200 ms | never / never | 0.35 | 0.30 |
| 2 (RTX A4500) | scaled | 2.36 ± 0.12 | 44 / never | **0.45** | 0.20 | 52 ms, 93 % / 0 % | never / never | 0.32 | 0.30 |
| 2 | race | 3.06 ± 0.18 | 57 / 54 | **0.64** | 0.80 | 52 ms, 98 % / 0 % | never / never | 0.28 | 0.30 |
| 2 | window | 4.93 ± 0.14 | 72 / 70 | **0.54** | 0.65 | 200 ms | never / never | 0.30 | 0.30 |
| 3 (RTX 4000 Ada) | diff | 2.42 ± 0.11 | 46 / 37 | **0.68** | 0.80 | 104 ms, 44 % / 17 % | never / never | 0.31 | 0.24 |
| 3 | window | 3.10 ± 0.17 | 46 / 54 | **0.63** | 0.95 | 200 ms | never / never | 0.38 | 0.24 |
| 3 | race | 4.43 ± 0.16 | 47 / 38 | **0.60** | 0.75 | 74 ms, 72 % / 8 % | never / never | 0.32 | 0.24 |

Per read-out (mean of its runs, learned / frozen): race 0.58 / 0.28 (3 runs, criterion reached before and after the
reversal in 3 of 3); scaled 0.57 / 0.30 (2 runs); diff 0.59 / 0.32 (2 runs, 2 of 2 before and after); window
0.55 / 0.34 (3 runs, 2 of 3 before the reversal, 3 of 3 after).

Learned curves (fraction correct per 20 trials; the reversal comes after block 6):

| seed | read-out | curve |
|---|---|---|
| 1 | race | 0.15 0.60 0.55 0.45 0.70 0.65 · 0.15 0.60 0.80 0.70 0.50 0.15 |
| 1 | scaled | 0.50 0.85 0.65 0.70 0.50 0.50 · 0.35 0.65 0.85 0.95 0.90 0.85 |
| 1 | diff | 0.15 0.15 0.20 0.60 0.75 0.65 · 0.25 0.50 0.80 0.55 0.85 0.65 |
| 1 | window | 0.10 0.35 0.40 0.45 0.35 0.40 · 0.40 0.40 0.85 0.70 0.90 0.55 |
| 2 | scaled | 0.25 0.55 0.65 0.60 0.75 0.75 · 0.20 0.40 0.30 0.30 0.40 0.20 |
| 2 | race | 0.40 0.40 0.80 0.75 0.60 0.65 · 0.45 0.60 0.60 0.80 0.80 0.80 |
| 2 | window | 0.15 0.30 0.40 0.75 0.70 0.90 · 0.35 0.35 0.45 0.80 0.70 0.65 |
| 3 | diff | 0.40 0.60 0.60 0.95 0.85 0.65 · 0.30 0.70 0.65 0.85 0.80 0.80 |
| 3 | window | 0.25 0.60 0.60 0.95 0.80 0.50 · 0.25 0.55 0.70 0.70 0.75 0.95 |
| 3 | race | 0.35 0.55 0.95 0.75 0.50 0.60 · 0.15 0.70 0.70 0.65 0.50 0.75 |

Speed: one read-out (calibration, 240 frozen + 240 learned decisions) took ~2 min of pod time. Every decision fit
within the 2 s deadline in simulated time (≤ 250 ms).

Cost: three pods, one at a time, 23.7 min in total, **$0.106**. Each was deleted and confirmed gone; "BRAIN" was
not touched. A4000 secure had no capacity, so the cheapest secure type in stock was taken: A5000 $0.27/h,
A4500 $0.25/h, 4000 Ada $0.28/h. Cost log: `docs/spiking/live/costs.jsonl`.

### CPU, 20k neurons, one network (seed 1), the same benchmark

Raw results: `docs/spiking/cpu_learn/*.json`. Script: `docs/spiking/cpu_learn/run_cpu_learn.py`.
The 20k `scaled` run used an earlier version without the "never below the race" floor. At 81-neuron pools its
threshold was slightly *below* the race. With the floor it is the race at this size.

| read-out | learned: to criterion / after reversal | learned: fraction correct | decision (ms) | frozen: to criterion / after | frozen | random |
|---|---|---|---|---|---|---|
| race | never / 90 | 0.44 | 102 | never / never | 0.30 | 0.30 |
| scaled | never / 49 | 0.41 | 91 | never / never | 0.31 | 0.30 |
| diff | 87 / 45 | 0.57 | 238 | never / never | 0.31 | 0.30 |
| window | 103 / 36 | 0.44 | 200 | never / never | 0.30 | 0.30 |

At 20k the pools are noisy (sd ~1 Hz) and learning with variable offers is weaker than at 1M.

### Reading the numbers honestly

- **Learning, at 1M, in this task.** All 10 learned runs beat their frozen twin, by +0.13 to +0.41 in fraction
  correct. 9 of 10 reached the criterion before the reversal, 9 of 10 after it. None of the 10 frozen twins and
  none of the random choosers reached it.
- **The fast race was not what stopped learning.** With the race deciding at the first check in 72–100 % of trials,
  the learned runs still reached the criterion in 47–66 trials. The built-in bias decides the first picks. Dopamine
  then shifts the cue → pool weights until the bias is overcome. In the #67 validation, 50 rounds over 15 labels
  were simply too few to see this.
- **The baseline rate drifts.** The pools' calibrated mean rate moved between 2.4 and 5.3 Hz within minutes on the
  same network: the recorded resting baseline drives the network. A threshold in Hz is fixed at calibration, so
  `race` and `scaled` change behaviour as the rate moves. `scaled` decided like a 250 ms window in seed 1 (87 %
  timeouts, the best run, 0.69). In seed 2 it decided like a first-check race (93 %, the worst run, 0.45). The
  `scaled` numbers therefore say little about pool-size scaling itself.
- **Why `diff` is the live default.** `diff` learned as well as the race (0.51 and 0.68 vs 0.50, 0.64 and 0.60). It
  reached the criterion before and after the reversal in both runs. Its threshold is a lead between pools, so a
  common rise or fall of all rates does not change it. Over a 16-hour waking day that matters more than in a
  10-minute benchmark. It still decides early when one pool clearly leads (mean 104–127 ms). This is a reasoned
  choice, not a measured win: with two runs, the difference from the race is within run-to-run spread.
- **Preferences still drift.** Some learned runs fell back late in a phase: seed 1 race, last 20 = 0.15; seed 2
  scaled after the reversal, 0.20. This is the drift already seen in #39.
- **What this is not.** Eight labels with fixed hidden probabilities, a reversal, 240 trials, one run per network
  and read-out. Real days have many more labels, few repeats per label and noisy outcomes. Whether the live
  network learns from his real decisions is measured separately (below), not assumed from this benchmark.

### On real decisions: `/api/spiking/status` → `learning`

`learning.days` has one entry per Tokyo day for the last 14 days (`choice.payoff_by_day`).
- **From the decision logs:** #55's `decisions-<day>.jsonl` and the hub's `gpu_decisions-<day>.jsonl` are merged
  by id. For `gpu` (this network) and `other` (#55's CPU network or the rate model), each entry gives the number of
  decisions, those with an outcome, and the fraction that **paid off** (a later reward > 0).
- **From the night replay (`choice_replay`):** on the same day's real decisions, how often the network's own pick
  agrees with the outcomes, for:
  - `learned`: before the night's replay;
  - `frozen_twin`: the same network with every learned change removed;
  - `after_replay`.
  The replay also reports `paid_off_frac`.

The neurons card can draw "learning curve vs frozen" from `replay.learned` against `replay.frozen_twin`, day by
day. Those two numbers come from the same decisions, so the comparison is fair. The payoff fraction depends on
what was offered, so it is not on its own a sign of learning. Until days of data exist, nothing should be claimed.
