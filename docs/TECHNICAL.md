# SUB-01 — technical overview

The long technical sections that used to be in the README: the MRI pipeline, the real-wiring slow layer, the
resting-state processing, sleep/chat/memory (Phase A) and the spiking network (v3). Back to the
[README](../README.md).

- **Data:** MyConnectome, OpenNeuro [ds000031](https://openneuro.org/datasets/ds000031) (public domain, PDDL). Raw scans are never stored here; the scripts download what they need.
- **Real parts:** nerve-fibre tractography (diffusion MRI), cortical surface (T1), recorded resting-state activity (fMRI).
- **Simulated part:** region-to-region dynamics in two layers on the subject's connectome: a slow (BOLD-band) Hopf layer
  fitted on half of the subject's resting-state runs and tested on the other half, which modulates a fast ~10 Hz
  delayed Stuart-Landau layer used for the live display. How much of the result comes from the wiring itself, compared
  with randomised wiring, is reported in [real_wiring_report.md](real_wiring_report.md).
- It is a model of brain activity, not a mind, and makes no claim of consciousness.

CI: tests + demo smoke test on every PR (`.github/workflows/tests.yml`; locally `python tests/smoke_demo.py`), plus
the room's visual QA job (`tests/visual/`, see [tests/visual/README.md](../tests/visual/README.md)).

## Pipeline

| Step | Script | Output |
|---|---|---|
| Connectome (tractography + Schaefer-200 / Harvard-Oxford atlas) | `build_connectome.py` | `out/connectome.npz`, `out/labels_dwi.nii.gz` |
| Real fibres for the web | `export_fibres.py` | `web/fibres*.bin`, `web/fibres.json` |
| Cortical surface | `build_cortex.py` | `web/cortex*.bin` |
| Resting-state activity (streamed, raw deleted) | `process_rest.py N` | `out/rest/*.npz` |
| Nodes / edges for the page | `export_web.py` | `web/brain.json` |
| Live pages + model + chat + sleep (optional trade-feed input, see below) | `live_server.py --demo` (or `--mint <MINT>`) | http://localhost:8765 |
| Sleep/wake engine, memory replay | `sleep.py` (used by `live_server.py`) | `data/state.json`, `data/nights/YYYY-MM-DD.json` |
| Chat filter + message -> stimulus rules | `chat.py` (used by `live_server.py`) | |
| His computer and phone screens: real web pages (headless Chromium, read-only, guarded) | `browse.py` (`--browse` / `BROWSE=1`) | `/api/screen/{desk,phone}.jpg`, `data/browsing.json` |

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
./fetch_data.sh   # ~900 MB from OpenNeuro into data/ (git-ignored)
```

`requirements.txt` is the MRI pipeline; the live server alone needs `requirements-server.txt`.

**Trade-feed input (optional).** The live server can take public trades of one Solana token as an extra stimulus
(`--mint` / `MINT`). With `MINT` empty there is no trade feed; `--demo` generates fake trades locally. Trades only
move the model's simulated arousal and neuromodulators (see below and [twin/neurochem.md](twin/neurochem.md)); a
single trade above $250k is treated as a decoding error and ignored (`live_server.py`, `MAX_TRADE_USD`). Nothing in
the project is financial advice.

## Real wiring: connectome v2 and the slow layer

| Step | Script | Output |
|---|---|---|
| ACT tissue map from the T1 (tried, not used: it truncated streamlines) | `analysis/make_5tt.py` | (pod input) |
| MRtrix3 tractography on a RunPod pod (gradient check, msmt-CSD, iFOD2, SIFT2) | `analysis/runpod_job.py` + `analysis/pod/tract.sh` | `data/analysis/connectome_v2_raw.tar.gz` |
| Consistency threshold, lengths, centroids | `analysis/build_connectome_v2.py` | `out/connectome_v2.npz` (v1 `out/connectome.npz` kept) |
| Hopf slow layer: fit on half of the runs, test on the other half, 100 + 100 nulls | `analysis/real_wiring.py prep / nulls / run / report / export` | `docs/real_wiring/`, `twin/data/slow_layer.npz` |
| Old quick checks (originals; reconstructions with `--conn` for v1/v2) | `analysis/null_test.py`, `analysis/hopf_test.py` (`analysis/*_test_recon.py`) | |

Pods follow fixed rules (`analysis/runpod_job.py`): only CPU or RTX A5000 pods, one at a time, deleted on finish, error or
60 min, 2 h in total, every pod logged in `data/analysis/costs.jsonl`; pods it did not create are never touched.
`live_server.py` runs the slow layer by default: the wiring-only version (his connectome × one fitted global coupling);
`SUB01_SLOW=ec` switches to the effective-connectivity version (`twin/hopf.py`, `SlowLayer`;
[real_wiring_report.md](real_wiring_report.md)). `--replay-real-session` replays a recorded session instead (the old
default).

Headline result (from [real_wiring_report.md](real_wiring_report.md)): the wiring-only model matches the recorded
correlation pattern at r ≈ 0.21 (0.206) on held-out sessions; strength-preserving randomised brains reach a mean of
0.166 (p = 0.01), geometry-preserving ones 0.162 (p = 0.059, borderline). The two halves of the recordings agree at
r = 0.96. The old public "r = 0.40" came from replaying the recorded activity, not from the wiring, and is not a result.

## Resting-state activity (real recorded brain activity)

`process_rest.py N [--workers 6]` streams the first N of the 132 resting-state runs listed in `rest_runs.txt`
from OpenNeuro in parallel worker processes (~1.9 GB RAM each), keeps a region x time series per run in
`out/rest/` (~240 KB each) and deletes the raw file. Runs already in `out/rest/` are skipped. It only needs `out/labels_t1.nii.gz` and `out/t1_brain_1mm.nii.gz` (skull-stripped,
committed), so it runs on a fresh clone: `pip install -r requirements.txt && python process_rest.py 132`.
After processing (or with `--validate` alone) it runs a QC: mean homotopic (left/right, name-matched) correlation
vs mean correlation over all pairs, per run, written to `out/rest/qc.json`. Runs with homotopic < 0.3 (likely bad
registration or motion) are moved to `out/rest/rejected/` (not committed) and not re-downloaded on later runs.

## Sleep, chat and memory (Phase A)

Sleep is a small published circuit model (`sleep.py`, details and numbers in [twin/sleep.md](twin/sleep.md)); chat
filtering and memory are rule tables. (Phase A had no language model at all. Later phases added AI-written diary
lines, dream images, page notes, day plans and replies, all labelled as AI-written and capped per day: see
[HANDOFF.md](HANDOFF.md) and [OPERATIONS.md](OPERATIONS.md).)

- **Clock:** Asia/Tokyo (`SUB01_TZ`). Undisturbed it sleeps ~23:56-07:54 with 5 NREM-REM cycles of ~90 min.
  `--time-scale 60` runs one sim hour per real minute, `--start 23:55` starts the demo clock there.
- **Sleep circuit:** sleep/wake is the Phillips & Robinson (2007) MA/VLPO flip-flop driven by a homeostatic
  somnogen H and a circadian drive C; NREM/REM is a REM-on/REM-off flip-flop with a slow REM pressure (our
  parameters), so REM episodes lengthen and NREM gets lighter across the night. The engine also exports tonic
  neuromodulator levels `{DA, 5HT, NE, ACh}` per state (`engine.modulators`), which drive `twin/neurochem.py`.
- **Stages** (Stuart-Landau parameters glide over ~1-2 min, never jump):
  AWAKE 10 Hz, normal coupling, stimulus gain 1.0 · NREM 1-3 Hz, 2-3x coupling, high synchrony, gain ~0.15
  (deepest in early cycles) · REM 6 Hz, 0.6x coupling, more noise, gain 0.4 (longer in later cycles).
- **Arousal:** messages and, when the trade feed is on, large trades (>= $5k) are input to the MA population and decay
  over minutes; when it flips the switch the brain wakes ("woken at 03:12 by 5 messages"); once the input fades it
  falls asleep again. Total arousal is capped, and past 18 h of sleep debt sleep pressure overrides outside arousal
  ([HANDOFF.md](HANDOFF.md), "Trades and sleep").
- **Sleep debt:** H above the rested cycle, in hours of lost sleep. Lost sleep and wake-ups raise it, sleep repays it,
  high debt sends it to bed earlier. A tired brain is less reactive (lower gain) and noisier the next day.
- **Chat:** max 280 characters, 1 message / 10 s per client, duplicates dropped. The filter runs first and blocks links,
  Solana/ETH addresses, $TICKERS, insults, requests for money and personal data (e-mail, phone): blocked messages are
  never shown or stored. Accepted messages hit: language (left temporal + frontal operculum) + somatomotor always,
  reward (positive words), fear + salience (threat words), attention + control (questions), default network
  (mentions of SUB-01 / "you"). Asleep, the drive is scaled by the stage gain and the message is marked "heard while asleep".
- **Memory + replay:** accepted messages are stored with time, stage, stimulus pattern and emotional tag. In REM the
  hippocampus replays them at 35 % amplitude, picked by recency, emotion and "arrived tonight" (with habituation).
  Each night is written to `data/nights/YYYY-MM-DD.json` (stage timeline, wake-ups + cause, sleep debt, replayed
  messages = "dream ingredients"). State is saved every minute to `data/state.json`. IPs are only kept for the
  10 s rate-limit window; nothing about who sent a message is stored.

```bash
python live_server.py --demo --time-scale 60 --start 23:55   # accelerated night (state in data/demo/)
python tests/test_sleep.py                                    # or: python -m pytest tests/
```

## Spiking brain (v3, `spiking/`)

One million simulated spiking neurons inside the real wiring of one person's brain; a model, not a mind; not the
person. One leaky integrate-and-fire population per atlas region (size proportional to the region's volume),
long-range synapses sampled from the streamline counts with delays from the fibre lengths (6 m/s), driven by the
recorded resting-state activity. Three-factor plasticity (STDP eligibility x dopamine), fast hippocampal Hebbian
memory with REM replay, and a Pong task after DishBrain (Kagan et al. 2022). It runs in scheduled GPU sessions on
RunPod; the Railway server keeps the learned weights. Full description, equations, results and limits:
[spiking_report.md](spiking_report.md).

```bash
python -m pytest tests/test_spiking_model.py tests/test_spiking_ops.py -q   # CPU, small networks
python -m spiking.validate --cpu --n 20000                                  # CPU validation
python -m spiking.validate --gpu                                            # 1M neurons on one RunPod pod (deleted after)
```

Railway env: `SUB01_POD_SECRET` and `RUNPOD_API_KEY` turn the daily session on; `SUB01_SESSIONS` (default
`daily 21:00-22:00 Asia/Tokyo`, `off` disables). Optional caps: `SUB01_MAX_SESSION_MIN` (60, counted from pod
creation), `SUB01_MAX_HOURS_PER_DAY` (1), `SUB01_GPU_HOURS_CAP` (8, or 120 with the day-live mode) per
`SUB01_GPU_CAP_DAYS` (7, rolling); `SUB01_PONG=1` adds Pong (it has not learned so far: 17.5 % vs 25 % for the
no-plasticity control); `SUB01_CHOICE=1` adds the choice training to the session. Learned weights and results live in
`/data/spiking/` (per-item recall rows in `memory_tests.jsonl`, shown by `GET /api/memory` and the room page's memory
card). Defaults are in `spiking/pod_manager.py`.

Later additions (each with its own doc):
- **Day-live on GPU** ([spiking/live.md](spiking/live.md)): the 1M network runs through his waking hours and votes in
  his browsing choices. Off until `SUB01_DAY_LIVE=1`; caps `SUB01_DAY_MAX_HOURS` (17), `SUB01_GPU_USD_PER_DAY` ($14).
- **20k-neuron network on the server CPU** ([spiking/live_cpu.md](spiking/live_cpu.md)): votes and learns live as a
  small term and is the GPU fallback. On by default; `SUB01_SPIKING_LIVE=0` turns it off.
- **Learning to choose** ([spiking/choice.md](spiking/choice.md)): at 1M neurons on GPU it reached criterion in 84
  trials and scored 1.00 in the exam, against 0.275 with every learned change removed and 0.26 for a random chooser.
- **Neurons on the page** ([spiking/neurons3d.md](spiking/neurons3d.md), [spiking/neuron_render.md](spiking/neuron_render.md),
  [spiking/neuron_zoom.md](spiking/neuron_zoom.md)): the shapes are real reconstructed neurons (NeuroMorpho.Org, H01);
  the simulated network uses point neurons. Credits: [spiking/morphology_credits.md](spiking/morphology_credits.md).
