"""Read-outs that scale and the live learning benchmark (#70, docs/spiking/choice.md).

The read-out logic, the bandit stream, the random chooser and the real-decision learning curve are pure numpy and
run everywhere, CI included. The network tests build a 10k-neuron network and skip where torch is absent.

    python -m pytest tests/test_spiking_readout.py -q
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from spiking.choice import (BANDIT_LABELS, BANDIT_PROBS, READOUTS, Readout, RewardSchedule, bandit_random,  # noqa: E402
                            bandit_stream, bandit_value, payoff_by_day, race)


def calibrated(mode, **kw):
    ro = Readout(mode, **kw)
    rng = np.random.default_rng(0)
    # 4 pools with fixed biases (0, 1, 2, 3 Hz) and noise sd 0.5 Hz, 100 neurons each
    ro.calibrate(5.0 + np.arange(4) + rng.normal(0, 0.5, size=(400, 4)), [100] * 4)
    return ro


# --- read-outs ---------------------------------------------------------------------------------------------------
def test_race_readout_is_the_39_rule():
    ro = calibrated("race")
    assert ro.thr_hz == pytest.approx(ro.mean + 2.0 * ro.sd)
    sizes = [10, 10, 10]
    cum = [[1, 2, 0], [2, 10, 1], [30, 12, 2]]
    for thr in (40, 1000):
        ro.thr_hz, ro.min_ms = thr, 0
        got = next(((ro.check(row, sizes, 10 * (t + 1)), 10 * (t + 1)) for t, row in enumerate(cum)
                    if ro.check(row, sizes, 10 * (t + 1)) is not None), None)
        w, ms, timeout = race(cum, sizes, 10, thr)
        assert (got is None) == timeout and (timeout or got == (w, ms))
    assert ro.final(cum[-1], sizes, 30) == 0


def test_scaled_threshold_grows_with_pool_size_and_stays_in_hz():
    small, big = Readout("scaled", ref_pool=100), Readout("scaled", ref_pool=100)
    rng = np.random.default_rng(1)
    small.calibrate(5 + rng.normal(0, 2.0, size=(50, 4)), [100] * 4)      # sd ~ 1/sqrt(n): 2 Hz at 100 neurons
    big.calibrate(5 + rng.normal(0, 0.2, size=(50, 4)), [10_000] * 4)     # 0.2 Hz at 10,000 neurons
    assert small.thr_hz - small.mean == pytest.approx(2.0 * small.sd)     # at ref_pool it is the race
    assert big.thr_hz - big.mean == pytest.approx(2.0 * big.sd * 10.0)    # z x sqrt(10,000 / 100)
    assert abs((big.thr_hz - big.mean) - (small.thr_hz - small.mean)) < 0.5   # about the same margin in Hz
    assert calibrated("race").thr_hz < calibrated("scaled", ref_pool=10).thr_hz
    assert calibrated("scaled", ref_pool=1000).thr_hz == calibrated("race").thr_hz      # never below the race


def test_diff_readout_ignores_fixed_biases_and_waits_for_a_lead():
    ro = calibrated("diff", diff_k=3.0)
    assert 0.6 < ro.sd_diff < 0.8                     # sqrt(2) x 0.5 Hz: the biases (1-3 Hz apart) are not noise
    assert ro.sd > ro.sd_diff
    sizes = [100, 100]
    hz = lambda r, ms: np.asarray(r) * 100 * ms / 1000.0          # rates -> counts since onset
    assert ro.check(hz([10.0, 9.0], 100), sizes, 100) is None      # lead 1 Hz < 3 x 0.7
    assert ro.check(hz([10.0, 7.0], 100), sizes, 100) == 0         # lead 3 Hz > 2.1
    assert ro.check(hz([7.0, 10.0], 40), sizes, 40) is None        # before min_ms (50)
    # the noise of a mean rate shrinks with time: the same 1.2 Hz lead is not enough at 100 ms, enough at 400 ms
    assert ro.check(hz([10.0, 8.8], 100), sizes, 100) is None and ro.check(hz([10.0, 8.8], 400), sizes, 400) == 0
    # and with pool size: 4x the neurons halve the noise
    assert ro.check(hz([10.0, 8.8], 100) * 4, [400, 400], 100) == 0


def test_window_readout_decides_at_the_window():
    ro = calibrated("window", window_ms=200)
    assert ro.check([50, 10], [10, 10], 190) is None and ro.check([1, 9], [10, 10], 200) == 1
    with pytest.raises(ValueError):
        Readout("vote")
    assert set(READOUTS) == {"race", "scaled", "diff", "window"}
    assert Readout("race").check([5, 1], [1, 1], 100) is None                 # not calibrated: never decides


# --- the bandit ------------------------------------------------------------------------------------------------
def test_bandit_stream_variable_offers_and_random_baseline():
    offers, u = bandit_stream(400, 8, seed=3)
    again, u2 = bandit_stream(400, 8, seed=3)
    assert offers == again and np.array_equal(u, u2)                         # the same stream for every arm
    assert {len(o) for o in offers} == {2, 3, 4, 5, 6}
    assert all(len(set(o)) == len(o) and 0 <= min(o) and max(o) < 8 for o in offers)
    sch = RewardSchedule(list(BANDIT_PROBS), 200, seed=0)
    r = bandit_random(sch, offers, u, seed=1)
    assert abs(r["frac_correct"] - r["chance"]) < 0.06 and 0.25 < r["chance"] < 0.33
    assert len(BANDIT_LABELS) == len(BANDIT_PROBS) == 8
    assert bandit_value(True) == 1.0 and bandit_value(False) == -1.0


# --- real decisions: paid off, learned vs frozen twin ----------------------------------------------------------
def test_payoff_by_day_merges_logs_and_replays():
    rows = {"2026-10-03": [{"id": "a", "options": ["x", "y"], "pick": 0, "net": "gpu"},
                           {"id": "a", "options": ["x", "y"], "pick": 0, "net": "gpu", "reward": None},  # #55's copy
                           {"id": "a", "reward": 0.5},
                           {"id": "b", "options": ["x", "y"], "pick": 1, "net": "cpu", "reward": None},
                           {"id": "b", "reward": -1.0},
                           {"id": "c", "options": ["x", "y"], "pick": 1, "net": "gpu"},          # no outcome yet
                           {"id": "d", "options": ["x", "y"], "pick": 1, "net": "rate"},
                           {"id": "d", "reward": 1.0},
                           {"id": "e", "reward": 1.0},                                            # no decision row
                           "junk", {"no": "id"}],
            "2026-10-02": []}
    rep = [{"day": "2026-10-03", "fit_before": 0.6, "fit_frozen_twin": 0.5, "fit_after": 0.7, "fit_n": 10}]
    out = payoff_by_day(rows, rep)
    assert [d["day"] for d in out] == ["2026-10-02", "2026-10-03"]
    d = out[1]
    assert d["gpu"] == {"decisions": 2, "with_outcome": 1, "paid_off": 1, "paid_off_frac": 1.0}
    assert d["other"] == {"decisions": 2, "with_outcome": 2, "paid_off": 1, "paid_off_frac": 0.5}
    assert d["replay"] == {"n": 10, "learned": 0.6, "frozen_twin": 0.5, "after_replay": 0.7}
    assert out[0] == {"day": "2026-10-02"}


def test_status_has_the_learning_curve(tmp_path):
    from sleep import ROME
    from spiking.server import SpikingHub
    hub = SpikingHub(SimpleNamespace(), tmp_path)
    assert hub.status()["learning"]["days"] == []
    day = datetime.now(ROME).date().isoformat()
    d = tmp_path / "spiking"
    (d / f"gpu_decisions-{day}.jsonl").write_text(
        json.dumps({"id": "g1", "options": ["a", "b"], "pick": 1, "net": "gpu", "t": 1}) + "\n"
        + json.dumps({"id": "g1", "reward": -0.5, "t": 2}) + "\nnot json\n")
    (d / f"decisions-{day}.jsonl").write_text(
        json.dumps({"id": "c1", "options": ["a", "b"], "pick": 0, "net": "cpu", "reward": None, "t": 1}) + "\n"
        + json.dumps({"id": "c1", "reward": 1.0, "t": 2}) + "\n")
    (d / "choice_replays.jsonl").write_text(json.dumps({"day": day, "fit_before": 0.55, "fit_frozen_twin": 0.5,
                                                         "fit_after": 0.6, "fit_n": 2}) + "\n")
    hub._learning = (-1e9, None)
    st = hub.status()["learning"]
    assert st["days"][-1]["day"] == day and "frozen twin" in st["note"]
    assert st["days"][-1]["gpu"]["paid_off_frac"] == 0.0 and st["days"][-1]["other"]["paid_off_frac"] == 1.0
    assert st["days"][-1]["replay"]["frozen_twin"] == 0.5
    assert hub.store_result({"kind": "live_learn", "readouts": {}})                 # the benchmark result is kept


# --- on the network (torch) ------------------------------------------------------------------------------------
def test_bandit_experiment_runs_every_readout_and_restores_the_network():
    torch = pytest.importorskip("torch")
    torch.set_num_threads(2)
    from spiking.choice import LiveChooser, bandit_experiment
    from spiking.config import Config
    from spiking.net import SpikingNet
    net = SpikingNet(Config(n_neurons=10_000, seed=3))
    net.run(200)
    net.plast.set_stdp(False)
    live = LiveChooser(net, readout="diff")
    live.V, live.n = {"kept": 0.3}, {"kept": 4}
    dw0, w0 = net.plast.dw.clone(), net.plast.w0.clone()
    seen = []
    out = bandit_experiment(live, trials=8, seed=2, on_readout=lambda m, o: seen.append(m))
    assert seen == list(READOUTS) and set(out["readouts"]) == set(READOUTS)
    for mode, r in out["readouts"].items():
        assert r["calibration"]["readout"] == mode and r["learned"]["trials"] == r["frozen"]["trials"] == 8
        assert r["labels_valued"] > 0                                           # the learned run got dopamine
        if mode == "window":
            assert r["learned"]["mean_rt_ms"] == 200 and r["learned"]["timeout_frac"] == 0
    assert out["random"]["trials"] == 8 and out["reversal_at"] == 4
    assert torch.equal(net.plast.dw, dw0) and torch.equal(net.plast.w0, w0)    # learned changes removed again
    assert live.readout.mode == "diff" and live.V == {"kept": 0.3} and live.n == {"kept": 4}
    w = LiveChooser(net, readout="window", readout_kw={"window_ms": 300})
    assert w.timeout_ms == 300
    w.calibrate(presentations=3)
    r = w.decide(["Tea ceremony", "Stock news"], learn=False)
    assert r["sim_ms"] == 300 and not r["timeout"]


def test_session_live_learn_phase(tmp_path):
    pytest.importorskip("torch")
    from spiking.session import run_session
    res = run_session({"n_neurons": 10_000, "seed": 3, "device": "cpu", "phases": ["live_learn"],
                       "bandit_trials": 6, "bandit_readouts": ["race", "window"], "live_readout": "scaled",
                       "max_minutes": 10}, tmp_path)
    assert res["error"] is None
    ll = json.loads((tmp_path / "results.json").read_text())["phases"]["live_learn"]
    assert len(ll) == 1 and set(ll[0]["readouts"]) == {"race", "window"} and ll[0]["n_neurons"] == 10_000
