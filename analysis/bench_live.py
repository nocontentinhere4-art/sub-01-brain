"""CPU cost of the deployed model at real time (live_server settings: 50 ms ticks of step(5) x 10, 1 BLAS thread).

    OMP_NUM_THREADS=1 python analysis/bench_live.py
Reports CPU seconds per simulated second (= fraction of one core when run in real time) with and without the slow layer.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from brain_sim import Brain  # noqa: E402


def cost(slow, seconds=20.0):
    b = Brain(seed=0, slow=slow)
    b.run(1.0)
    t = time.process_time()
    for _ in range(int(seconds / 0.05)):
        acc = np.zeros(b.n)
        for _ in range(10):
            acc += np.abs(b.step(5))
        b.state()
    return (time.process_time() - t) / seconds


if __name__ == "__main__":
    out = {"fast_layer_only": round(cost(False), 3), "fast_plus_slow_layer": round(cost(True), 3)}
    from twin.hopf import SlowLayer
    s = SlowLayer()
    t = time.process_time()
    for _ in range(6000):
        s.advance(0.1)
    out["slow_layer_alone"] = round((time.process_time() - t) / 600, 4)
    out["unit"] = "CPU seconds per simulated second = fraction of one core at real time"
    print(json.dumps(out))
