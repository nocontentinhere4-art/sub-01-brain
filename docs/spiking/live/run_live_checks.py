"""Numbers for docs/spiking/live_cpu.md (#55): the daytime spiking network on one CPU core, numpy only.

    python docs/spiking/live/run_live_checks.py cost          # build, CPU per decision (with the frozen twin)
    python docs/spiking/live/run_live_checks.py learn SEED [ETA_HALF]   # synthetic stream, 20k, 150 decisions

Results are printed as one JSON line each (collected by hand into results.json)."""
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import spiking.live as L  # noqa: E402


def cost(n=L.N_NEURONS, decisions=100, seed=0):
    t0 = time.process_time()
    b = L.LiveBrain(n, None)
    start_cpu = time.process_time() - t0
    rng = np.random.default_rng(seed)
    words = "bread tokyo parks train timetable cat videos jazz records old maps museum hours next page keep reading".split()
    ms, sim = [], []
    for i in range(decisions):
        k = int(rng.integers(2, 7))
        labels = [" ".join(rng.choice(words, size=int(rng.integers(1, 4)))) for _ in range(k)]
        d = b.decide(labels, did=i)
        ms.append(d["cpu_ms"])
        sim.append(d["decision_ms"])
        b.learn(i, 0, float(rng.normal(0, 0.3)))
    one = L.LiveBrain(n, None, twin=False)
    solo = [one.decide(["read about bread", "tokyo parks", "wander somewhere else"], did=i)["cpu_ms"] for i in range(30)]
    print(json.dumps({"n_neurons": b.net.n, "synapses": b.net.n_syn, "plastic": len(b.dw), "build_s": round(b.net.build_s, 2),
                      "startup_cpu_s": round(start_cpu, 2), "calibration": b.calib,
                      "cpu_ms_per_decision_with_twin": {"mean": round(float(np.mean(ms)), 1), "p95": round(float(np.percentile(ms, 95)), 1),
                                                        "max": round(float(np.max(ms)), 1)},
                      "cpu_ms_per_decision_without_twin": round(float(np.mean(solo)), 1),
                      "simulated_decision_ms": {"mean": round(float(np.mean(sim)), 1), "timeouts": int(np.sum(np.array(sim) >= L.TIMEOUT_MS))}}))


def learn(seed, eta_half=None, n=L.N_NEURONS, trials=150):
    if eta_half is not None:
        L.ETA_HALF = float(eta_half)
    t0 = time.process_time()
    r = L.synthetic(L.LiveBrain(n, None), trials=trials, seed=int(seed))
    r.update(n_neurons=n, eta_half=L.ETA_HALF, cpu_s=round(time.process_time() - t0, 1))
    print(json.dumps(r))


if __name__ == "__main__":
    {"cost": lambda *a: cost(), "learn": learn}[sys.argv[1]](*sys.argv[2:])
