# SUB-01 v3 — a spiking brain that learns: report

*1 million simulated spiking neurons inside the real wiring of one person's brain; a model, not a mind; not the
person.* Everything below is measured and reported as it came out, including what did not work.

<!-- summary:begin -->
(summary is written after the final validation run)
<!-- summary:end -->

## 1. Architecture

```
 out/connectome.npz (214 regions: streamline counts, fibre lengths)    out/rest/*.npz (recorded resting-state BOLD)
                 │                                                                      │
                 ▼                                                                      ▼
  spiking/net.py  ── one LIF population per region (size ∝ volume, 80 % E / 20 % I) ◄── drive per region
                 │     fixed in-degree: 45 local E + 25 local I + 30 long-range E (source region ∝ streamlines)
                 │     delays = fibre length / 6 m/s (ring buffer, 1–60 ms); event-driven CSR propagation
  spiking/plasticity.py ── three-factor STDP × dopamine (Pong) · fast Hebbian rate rule (memory) · homeostasis
  spiking/memory.py ── chat words → hashed patterns → hippocampal assemblies → recall test → REM replay
  spiking/pong.py   ── ball → visual parcels; paddle ← left − right somatomotor rate; hit → dopamine
  spiking/session.py (on the RunPod GPU) ── phases, status/results files, websocket stream, weights upload
                 ▲  wss /api/spiking/pod (Bearer SUB01_POD_SECRET)            │ POST /api/spiking/weights
  spiking/server.py + pod_manager.py (Railway) ── schedule, hard caps, cost log, /data/spiking, page relay
                 │
  web/neurons.js ── "Neurons" panel on /brain and on the life page
```

Code delivery to the pod uses no GitHub credentials: RunPod refuses create requests above ~100 KB (measured: 95 KB
accepted, 120 KB refused), so the create request carries only a ~2 KB bootstrap and a random one-time token; the
pod serves port 8000 and accepts one `PUT /upload` of the code+data pack (0.5 MB tar.xz) with that token, then runs
the session. Results are read at `https://<pod>-8000.proxy.runpod.net/` without any key.

## 2. Model and equations

**Populations.** 214 regions (Schaefer-200 7-network cortex + 14 Harvard-Oxford deep nuclei). Region *r* gets
*N_r* ∝ its voxel count in the subject's own T1 labels (`spiking/region_volumes.json`), at least 10 neurons;
80 % excitatory, ≥ 2 inhibitory. At 1 M neurons the smallest population has 562 neurons, the largest 16 791.

**Neuron (LIF, dt = 1 ms, exact for the leak at this step).**
τ_m dV/dt = −V + μ_j(t) + σ √τ_m ξ(t) + τ_m Σ_k J_k δ(t − t_k − d_k);  spike at V ≥ θ = 20 mV, reset to 10 mV,
refractory 2 ms. τ_m = 20 ms, σ = 4 mV.

**Drive.** μ_j(t) = μ_ext · (1 + β z_r(t)) + stimulus_j(t) − θ_j, μ_ext = 15 mV, β = 0.05, z_r = the person's own
z-scored resting-state BOLD of region *r* (131 QC-passed runs, played back in real time, refreshed every 50 ms,
clipped to [−2, 3]); θ_j = slow homeostatic offset.

**Synapses (instantaneous PSP jumps).** Each neuron receives exactly 45 excitatory inputs from its own region,
25 inhibitory inputs from its own region and 30 excitatory long-range inputs whose source region *s* is drawn with
probability W[s, r] / Σ_s W[s, r] (W = streamline counts), the source neuron uniform among the excitatory neurons
of *s*. J_E = 0.5 mV, J_I = −g J_E with g = 5. Delays: local 1–2 ms; long-range d = round(L_sr / 6 mm ms⁻¹),
L = mean fibre length (median 12 ms, 5–95 %: 5–27 ms, max 60 ms). Hippocampus (CA3-like): +100 recurrent E→E
collaterals per excitatory neuron (0.05 mV initially, plastic) and +100 E→I collaterals onto its interneurons
(0.3 mV, fixed) so feedback inhibition tracks assemblies.

**Regime.** K_E − g K_I = 75 − 125 < 0: recurrent input is net inhibitory (≈ −0.5 mV per Hz of population rate) and
damps fluctuations. With only 100 synapses per neuron this is not a large-K Brunel balanced state: the rate is
set mainly by the external drive (a Siegert mean-field estimate gives ≈ 5.7 Hz with recurrence, 5.9 Hz without;
independent reviewer's calculation). The network is asynchronous and stable; E and I rates are about equal.

**Plasticity** (excitatory→excitatory synapses only; 60.8 M of the 101 M synapses at 1 M neurons; the
connectome-derived weight w0 is never changed — the learned part dw lives in a separate file):
w = clamp(w0 + dw, 0, w_max), w_max = 2 mV.

1. *Three-factor STDP × dopamine (Pong).* Traces x_i (τ+ = 20 ms), y_j (τ− = 20 ms); eligibility e_ij (τ_e = 1 s):
   post spike: e += A+ (x_i − x_θ); pre spike: e −= A− y_j + h, with A+ = 1, A− = 0.5, x_θ = 0.1, h = 0.1.
   d(dw)/dt = η_DA · DA(t) · (e − ⟨e⟩), DA = phasic dopamine (decay 200 ms), only at synapses onto somatomotor
   neurons (M1 dopamine is needed for motor-skill learning, Hosp et al. 2011), zero-sum around the class mean.
   Expected drift for Poisson pairs: +8 /s for 40 Hz → 40 Hz, ≈ 0 or negative for 40 → 13, 13 → 40 Hz and background.
2. *Fast Hebbian rate rule (memory).* Once per presentation window T:
   dw += η · [Δr_i − ϑ]₊ · (Δr_j − ϑ) · T (the negative branch × 0.25), Δr = window rate − the neuron's 10 s running
   rate; encoding ϑ = 15 Hz (≈ 3 sd of the Poisson noise of a 500 ms window), η_HC = 0.025, η_ctx = 0.0005 mV Hz⁻² s⁻¹
   (hippocampus ≈ 50× faster); REM consolidation ϑ = 6 Hz, η_ctx = 0.002, hippocampus 0. Applied after the window.
3. *Homeostasis* (every simulated second, hours time-scale): θ_j += 10⁻⁴ (r_j − 5 Hz) (|θ| ≤ 3 mV); synaptic
   scaling w ← w (1 − 10⁻⁴ (r_j − 5)/5), stored as a change of dw.
4. *Forgetting between sessions:* dw × exp(−Δdays/3) in the hippocampus, × exp(−Δdays/60) in cortex.

**Memory.** Each content word of a filtered chat message is hashed (sha256) to a fixed 2 % of the excitatory
neurons of each language (LH temporal + frontal operculum), visual and default-network parcel, and to 0.5 % of the
hippocampal excitatory neurons. The hippocampal part stands in for the entorhinal input layer, which the atlas
does not contain: with 30 long-range synapses per neuron, cortical patterns alone did not produce a pattern-
specific hippocampal response (measured cosine 0.47 same vs 0.58 different message). The day's *winning messages*
are the top 5 of the day by the sleep engine's memory weight (recency × emotion). Encoding: pattern driven 500 ms
at +8 mV, then rule 2. Recall test (plasticity frozen): cue = first half of the words; score = rate of the
uncued words' neurons − rate of the other excitatory neurons of the same regions during the cue (Hz),
hippocampus and cortex separately; lures = never-stored word sets with the same word counts, identical
procedure; "recalled" = hippocampal score above every lure (false-positive chance ≈ 1/(n_lures + 1)). REM replay:
a 100 ms excitability burst in the hippocampus, the stored assembly whose neurons respond most wins (softmax), and
its pattern is reinstated at 35 % for 500 ms with rule 2 (CONS). Control: the identical night (same NREM/REM drive,
same pauses) without reactivations, from the same restored weights.

**Pong** (after DishBrain, Kagan et al. 2022, *Neuron* 110:3952 — the task design only). Unit field, paddle
height 0.2 on the left edge. Encoding every 10 ms: horizontal position → hemisphere (left half of the field →
right-hemisphere visual parcels and vice versa, smooth crossover); vertical position of the ball relative to the
paddle → Gaussian place code over the visual parcels ranked by their superior–inferior centroid (ball above →
ventral, below → dorsal, as in retinotopy), peak +4 mV. Paddle velocity = 1.5 · tanh(z/2) field/s, z = z-scored
(10 s running mean/sd) difference of left- and right-hemisphere somatomotor population rates (50 ms smoothing).
Hit → dopamine burst 1 − p̂_hit (reward-prediction error, ≥ 0.2); miss → game paused, 500 ms of unpredictable
stimulation of random visual parcels (re-drawn every 50 ms). Chat "good!" → dopamine 0.3 (≤ ½ the reward),
at most once per 30 s, only during Pong training / free run. Exam: 20 rallies, plasticity frozen, fixed ball
sequences so before / after / controls are paired. Controls: the same network with every learned change (dw and
θ) removed; a random paddle (Ornstein–Uhlenbeck z, same statistics); an ideal tracker (ceiling).

## 3. Results

<!-- results:begin -->
<!-- results:end -->

## 4. Operations (RunPod and Railway)

- Pods: only `NVIDIA RTX A5000` (fallback `NVIDIA RTX 4000 Ada Generation`), 1 GPU, on-demand, secure cloud,
  `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`, 30 GB container disk, no volume, port 8000. Names start with
  `sub01-spiking-`; every stop/delete re-fetches the pod and refuses anything else (the user's `BRAIN` pod was never
  touched). At most one pod; GPU-hour cap (`SUB01_GPU_HOURS_CAP`: 4 h lifetime for validation, 8 h per rolling 7 days
  for the daily sessions), per-day (1 h) and per-session (60 min from creation) caps; deadline
  timer, `atexit`/SIGTERM cleanup, startup recovery on Railway; during validation an independent watchdog deleted any
  of our pods older than 62 min. Every pod is logged in `data/spiking/costs.jsonl`.
- Railway (`spiking/pod_manager.py`): `SUB01_SESSIONS` (default `daily 21:00-22:00 Asia/Tokyo`), uploads the pack,
  waits for the pod's websocket hello (15 min), deletes the pod at session end, on `done`, on any error, if the stream
  is lost > 3 min. Learned weights are stored in `/data/spiking/weights.npz` (dense float16, ~120 MB at 1 M neurons;
  the previous file is kept); results in `/data/spiking/*.jsonl` (`memory_tests.jsonl`: one row per tested item
  `{day, item, source, recalled, score, threshold, label, test_day, days_since}`; whole tests in
  `memory_test_runs.jsonl`).
- Daily session phases: next-day test of the previous session's items (half cues vs lures, after the forgetting
  between sessions) → encode the day's top 5 chat messages and top 5 readings (title + keywords) → memory test →
  compressed night (NREM/REM, replay) → memory test → free run with live chat until the session ends. Pong training
  and exam only with `SUB01_PONG=1` (it has not learned: 17.5 % vs 25 % for the no-plasticity control).
  The sleep engine's REM never falls in the 21:00–22:00 window, so consolidation happens in the session's own
  compressed night; if a session overlaps the real night, REM stage messages from the server trigger replay live.

## 5. What is still unrealistic

<!-- limits:begin -->
- 100 synapses per neuron instead of ~10⁴, instantaneous current-based synapses, a single LIF type, no dendrites,
  no short-term plasticity, no neuromodulator other than a scalar dopamine signal; rates are narrowly distributed
  (no heavy-tailed firing), and with only 100 inputs the network is drive-dominated rather than truly balanced.
- Wiring: region-to-region probabilities come from diffusion tractography streamline counts (undirected, biased by
  region size and fibre length, no layers, no cell types); within a region connectivity is random.
- The hippocampus is one population per hemisphere with CA3-like collaterals; no dentate gyrus, CA1, entorhinal
  cortex or theta/sharp-wave dynamics; the hippocampal part of a word pattern is applied directly.
- Replay reinstates the cortical pattern as an input (hippocampus→cortex fibres carry < 2 % of cortical long-range
  input here); sleep stages are a compressed caricature of sleep.py's stages.
- Pong: the ball is a current injected into whole parcels, the paddle is a population difference; learning, if any,
  is reported against paired controls with 20–40-rally exams (binomial standard error ≈ ±10 percentage points).
- The background drive is the person's recorded fMRI signal (slow, hemodynamic), used as a proxy for slow changes
  in excitability — not neural activity.
<!-- limits:end -->

## 6. Tests

See `docs/spiking/test_output.txt`.
