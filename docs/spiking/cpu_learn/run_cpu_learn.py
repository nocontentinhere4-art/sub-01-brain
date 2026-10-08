"""The #70 learning benchmark on CPU (one read-out per process): choice.bandit_experiment on a fresh network.

    python docs/spiking/cpu_learn/run_cpu_learn.py 20000 240 race 1      # n_neurons, trials, read-outs, seed

Results go to docs/spiking/cpu_learn/n<k>k_s<seed>_<read-outs>.json. ~3-4 min per read-out at 20k on 1 core.
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

import torch  # noqa: E402

from spiking.choice import LiveChooser, bandit_experiment  # noqa: E402
from spiking.config import Config  # noqa: E402
from spiking.net import SpikingNet  # noqa: E402

n, trials, modes = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3].split(",")
seed = int(sys.argv[4]) if len(sys.argv) > 4 else 1
torch.set_num_threads(1)
net = SpikingNet(Config(n_neurons=n, seed=seed))
net.run(500)
net.plast.set_stdp(False)
t0 = time.time()
out = bandit_experiment(LiveChooser(net), trials=trials, readouts=modes, seed=seed)
out["wall_s"] = round(time.time() - t0, 1)
keys = ("frac_correct", "trials_to_criterion", "trials_to_criterion_after_reversal", "frac_correct_last20", "curve",
        "mean_rt_ms", "timeout_frac")
print("random", {k: out["random"].get(k) for k in keys + ("chance",)})
for m, r in out["readouts"].items():
    print(m, r["calibration"])
    print("  learned", {k: r["learned"].get(k) for k in keys})
    print("  frozen ", {k: r["frozen"].get(k) for k in keys})
(HERE / f"n{n // 1000}k_s{seed}_{'-'.join(modes)}.json").write_text(json.dumps(out, indent=1, default=float))
