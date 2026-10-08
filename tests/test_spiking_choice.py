"""The K-armed choice task (spiking/choice.py).

Task-logic tests (reward schedule, reversal, decision race, criterion, random chooser) are pure numpy and run
everywhere, CI included. The learning test builds a 10k-neuron network (CPU, ~40 s on 2 cores) and is skipped
where torch is absent (CI, Railway image).

    python -m pytest tests/test_spiking_choice.py -q
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from spiking.choice import RewardSchedule, curve, race, random_chooser, summarize, trials_to_criterion  # noqa: E402


# --- task logic -------------------------------------------------------------------------------------------------
def test_reward_schedule_follows_hidden_probabilities_and_reverses():
    s = RewardSchedule([0.8, 0.6, 0.4, 0.2], reversal_at=100, seed=3)
    assert s.best(0) == 0 and s.best(99) == 0
    assert s.probs(100).tolist() == [0.2, 0.4, 0.6, 0.8] and s.best(100) == 3          # best <-> worst
    assert s.best(150, offered=[0, 1]) == 1                                                # best among the offered
    n = 4000
    r0 = np.mean([s.reward(10, 0) for _ in range(n)])
    r3 = np.mean([s.reward(10, 3) for _ in range(n)])
    r0_rev = np.mean([s.reward(200, 0) for _ in range(n)])
    assert abs(r0 - 0.8) < 0.03 and abs(r3 - 0.2) < 0.03 and abs(r0_rev - 0.2) < 0.03
    assert RewardSchedule([0.7, 0.3]).probs(10 ** 6).tolist() == [0.7, 0.3]              # no reversal by default


def test_race_first_pool_over_threshold_else_timeout():
    sizes = [10, 10, 10]
    # cumulative counts every 10 ms; pool 1 reaches 10 spikes / 10 neurons / 20 ms = 50 Hz first
    cum = [[1, 2, 0], [2, 10, 1], [30, 12, 2]]
    assert race(cum, sizes, 10, thr_hz=40) == (1, 20, False)
    assert race(cum, sizes, 10, thr_hz=40, min_ms=30) == (0, 30, False)                  # nothing counts before min_ms
    w, ms, timeout = race(cum, sizes, 10, thr_hz=1000)                                    # nobody crosses
    assert (w, ms, timeout) == (0, 30, True)                                              # forced: highest rate
    # rates, not counts: a smaller pool with fewer spikes can be the faster one
    assert race([[5, 4]], [10, 4], 10, thr_hz=60)[0] == 1


def test_trials_to_criterion_and_curve():
    assert trials_to_criterion([1] * 20) == 20
    assert trials_to_criterion([0] * 10 + [1] * 14) == 24
    assert trials_to_criterion([0, 1] * 30) is None                                       # 50 % never reaches 70 %
    assert trials_to_criterion([1] * 10) is None                                          # shorter than the window
    assert curve([1] * 20 + [0] * 20) == [1.0, 0.0]


def test_random_chooser_is_at_chance_and_rarely_reaches_criterion():
    s = RewardSchedule([0.8, 0.6, 0.4, 0.2], reversal_at=1000, seed=0)
    r = random_chooser(s, 2000, 4, seed=1)
    assert 0.22 < r["frac_correct"] < 0.28 and 0.45 < r["reward_rate"] < 0.55
    hits = sum(random_chooser(RewardSchedule([0.8, 0.6, 0.4, 0.2], 100, seed=k), 200, 4, seed=k)
               ["trials_to_criterion"] is not None for k in range(200))
    assert hits <= 2                                                                      # 14/20 at chance 1/4: ~1e-4


def test_summarize_splits_at_reversal():
    out = summarize([0] * 30 + [1] * 30 + [0] * 25 + [1] * 25, [1] * 110, 60)
    assert out["trials_to_criterion"] == 44 and out["trials_to_criterion_after_reversal"] == 39
    assert out["frac_correct_last20_before_reversal"] == 1.0 and out["frac_correct_last20"] == 1.0


# --- learning on the network (torch) -----------------------------------------------------------------------------
def test_network_learns_rewarded_cue_better_than_frozen_twin():
    torch = pytest.importorskip("torch")
    from spiking.choice import experiment
    from spiking.config import Config
    from spiking.net import SpikingNet
    torch.set_num_threads(2)

    def build():
        n = SpikingNet(Config(n_neurons=10_000, seed=3))
        n.run(300)
        n.plast.set_stdp(False)
        return n
    net, twin = build(), build()
    w0 = net.plast.w0.clone()
    out = experiment(net, trials=60, reversal=False, frozen_net=twin, seed=3)
    L, F, R = out["learned"], out["frozen"], out["random"]
    print("learned", L, "\nfrozen", F, "\nrandom", R)
    assert min(min(row) for row in out["cue_pool_synapses"]) > 0                  # a cue -> pool pathway exists
    assert L["trials_to_criterion"] is not None and L["trials_to_criterion"] <= 40
    assert F["trials_to_criterion"] is None and R["trials_to_criterion"] is None
    assert L["frac_correct"] >= F["frac_correct"] + 0.25
    assert torch.equal(net.plast.w0, w0)                                          # the connectome weights are untouched
    dw = np.array(out["dw_cue_pool_mean_mv"])
    assert dw[:, 0].mean() > dw[:, 1:].mean()                                     # learned: cues -> the best option's pool
    assert float(twin.plast.dw.abs().max()) == 0.0                                # the frozen twin did not change


def test_session_choice_phases_write_results(tmp_path):
    """choice_train / choice_exam in a CPU session: results.json carries the learned run and its controls."""
    pytest.importorskip("torch")
    import json
    from spiking.session import run_session
    res = run_session({"n_neurons": 10_000, "seed": 3, "device": "cpu", "phases": ["choice_train", "choice_exam"],
                       "choice_trials": 12, "choice_exam_trials": 4, "max_minutes": 10}, tmp_path)
    assert res["error"] is None
    saved = json.loads((tmp_path / "results.json").read_text())
    cc = saved["phases"]["choice_curve"][0]
    assert cc["trials"] == 12 and cc["reversal_at"] == 6
    assert {"learned", "frozen", "random"} <= set(cc) and len(cc["learned"]["curve"]) == 0   # < 20 trials: no block
    ex = saved["phases"]["choice_exam"][0]
    assert ex["trials"] == 4 and set(ex["controls"]) == {"no_learning", "random", "chance"}
