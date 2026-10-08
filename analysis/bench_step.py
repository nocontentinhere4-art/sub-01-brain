"""CPU ms per 50 ms live tick of Brain.step: the step before #19 (dense gather) vs now (sparse ring operator).

    OPENBLAS_NUM_THREADS=1 python analysis/bench_step.py [--seconds 20]
Same pattern as live_server.run_brain: step(5) x 10 per tick + abs/state, slow layer on, one BLAS thread. The old step
is tests/test_brain_step.py's reference_step (kept verbatim there for the identity test).
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from brain_sim import Brain  # noqa: E402
from test_brain_step import reference_step  # noqa: E402


def ms_per_tick(step, seconds):
    b = Brain(seed=0)
    for _ in range(20):                       # 1 s warm-up (and builds the sparse operator)
        step(b, 50)
    t = time.process_time()
    ticks = int(seconds / 0.05)
    for _ in range(ticks):
        acc = np.zeros(b.n)
        for _ in range(10):
            acc += np.abs(step(b, 5))
        b.state()
    return (time.process_time() - t) / ticks * 1e3


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=20.0)
    s = ap.parse_args().seconds
    old, new = ms_per_tick(reference_step, s), ms_per_tick(Brain.step, s)
    print(json.dumps({"before_ms_per_tick": round(old, 2), "after_ms_per_tick": round(new, 2),
                      "speedup": round(old / new, 1), "simulated_s": s, "tick_s": 0.05}))
