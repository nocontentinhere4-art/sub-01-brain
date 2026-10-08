### Build (NVIDIA RTX A5000)

1,000,000 neurons, 100,972,600 synapses (60,778,400 plastic), max conduction delay 60 ms, built in 4.6 s, torch 2.8.0+cu128.

**Speed (GPU smoke test, 1,000,000 neurons, 100,972,600 synapses, NVIDIA RTX A5000):** 1,404 steps/s with plasticity off (1.40x real time at dt = 1 ms), 654 steps/s with STDP eligibility on (0.65x); GPU memory 4.74 GB.

**Rates (GPU smoke test, 20 s with the recorded resting-state drive):** excitatory 3.22 Hz, inhibitory 3.23 Hz; region rates 1st-99th percentile 2.02-5.32 Hz (max 6.04); single neurons (2 s) 5th-99th percentile 1.5-7.0 Hz, silent 0.07 %; runaway: no.

**Delays (GPU smoke test):** 30,000,000 long-range synapses; delay = fibre length / 6.0 m/s, max deviation 0.0 ms; median fibre 72.7 mm -> median delay 12 ms (5th-95th: 5-27 ms).


#### RunPod spend

| pod | purpose | GPU | start (UTC) | hours | cost (USD) | reason |
|---|---|---|---|---|---|---|
| f08isgep89khcp | probe | NVIDIA RTX A5000 | 2026-10-01T00:55:49 | 0.002 | 0.000 | probe done |
| dx0sq2uhp5glau | probe | NVIDIA RTX A5000 | 2026-10-01T00:56:30 | 0.001 | 0.000 | probe done |
| 54ckpdp2oldkkx | validate | NVIDIA RTX A5000 | 2026-10-01T01:00:38 | 0.028 | 0.007 | validate finished |
| **total** | | | | **0.030** | **0.01** | |
