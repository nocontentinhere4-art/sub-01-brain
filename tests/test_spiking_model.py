"""CPU tests of the spiking model at small N (same code path as the 1M-neuron GPU runs).

    python -m pytest tests/test_spiking_model.py -q      # ~3 min on 2 cores
"""
import sys
from pathlib import Path

import numpy as np
import pytest
torch = pytest.importorskip("torch")                      # GPU model tests: skipped where torch is absent (CI, Railway image)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from spiking.config import Config  # noqa: E402
from spiking.memory import MemorySystem, words  # noqa: E402
from spiking.net import SpikingNet, allocate  # noqa: E402
from spiking.pong import Game, Pong, random_paddle, tracking_paddle  # noqa: E402

torch.set_num_threads(2)
N = 20_000


@pytest.fixture(scope="module")
def net():
    from real_baseline import RealBaseline
    n = SpikingNet(Config(n_neurons=N))
    n.attach_baseline(RealBaseline(n.reg.names, Path(__file__).resolve().parent.parent / "out" / "rest"))
    n.run(500)
    return n


def test_population_sizes_follow_volume():
    vol = np.array([10.0, 30.0, 60.0])
    s = allocate(1000, vol, 10)
    assert s.sum() == 1000 and s[2] > s[1] > s[0] >= 10
    n = SpikingNet(Config(n_neurons=N, plastic=False))
    assert n.n == N
    big, small = np.argmax(n.reg.volumes), np.argmin(n.reg.volumes)
    assert n.size[big] > n.size[small]
    frac = n.n_exc.sum() / n.n
    assert 0.78 < frac < 0.82


def test_rates_in_range_without_runaway(net):
    exc = torch.as_tensor(net.is_exc_np)
    per_s = []
    for _ in range(3):
        snap = net.snapshot()
        net.run(1000)
        r = net.rates_since(snap)
        per_s.append((float(r[exc].mean()), float(r[~exc].mean()), net.region_rates_since(snap)))
    for e, i, rr in per_s:
        assert 1.0 <= e <= 15.0 and 1.0 <= i <= 15.0
        assert rr.max() < 15.0 and rr.min() > 0.5                      # every region alive, none runaway


def test_long_range_delays_match_fibre_lengths(net):
    long = net.kind == 2
    s = net.region_of[net.src[long].long()].numpy()
    d = net.region_of[net.dst[long].long()].numpy()
    expect = np.maximum(1, np.round(net.reg.lengths[s, d] / net.cfg.velocity_mm_ms))
    assert np.array_equal(net.delay[long].numpy().astype(float), expect)
    assert (s != d).all()                                               # long-range = other regions only
    # source regions follow the streamline counts into each target region (chi-square-free check on the big ones)
    r = int(np.argmax(net.size))
    tgt = d == r
    counts = np.bincount(s[tgt], minlength=net.reg.n).astype(float)
    p = net.reg.W[:, r] / net.reg.W[:, r].sum()
    top = np.argsort(-p)[:5]
    assert np.allclose(counts[top] / counts.sum(), p[top], atol=0.03)


def test_spike_arrives_after_its_delay():
    n = SpikingNet(Config(n_neurons=N, plastic=False, sigma_ext=0.0, mu_ext=0.0))
    i = int(n.region_neurons(0, exc_only=True)[0])
    row = slice(int(n.rowptr[i]), int(n.rowptr[i + 1]))
    dst, dl, w = n.dst[row].long(), n.delay[row].long(), n.w[row]
    k = int(torch.argmax(dl))
    target, delay = int(dst[k]), int(dl[k])
    expected = float(w[(dst == target) & (dl == delay)].sum())
    n.v.zero_()
    n.v[i] = n.cfg.v_th + 5.0                                           # stays above threshold after one leak step
    assert n.step() == 1                                                # only i fires, at t = 0
    assert abs(float(n.buf[delay % n.D, target]) - expected) < 1e-6    # queued in the slot of t = delay
    for _ in range(delay - 1):
        n.step()
        assert abs(float(n.v[target])) < 1e-6 or (dst == target).sum() > 1   # nothing arrives early
    n.step()                                                            # step t = delay delivers it
    assert abs(float(n.v[target]) - expected) < 1e-5


def test_stdp_needs_dopamine_and_stays_bounded():
    n = SpikingNet(Config(n_neurons=N))
    p = n.plast
    n.run(1500)
    assert float(p.dw.abs().max()) == 0.0                               # no modulator -> no weight change
    assert float(p.elig.abs().max()) > 0.0                              # but eligibility is there
    for _ in range(30):
        p.dopamine(50.0)                                                # absurdly large reward
        n.run(100)
    w = p.w0 + p.dw
    assert float(p.dw.abs().max()) > 0.0
    assert float(w.min()) >= -1e-6 and float((w - p._wmax()).max()) <= 1e-6
    assert torch.equal(p.w0, n.w[p.pidx] - p.dw) or torch.allclose(p.w0, n.w[p.pidx] - p.dw, atol=1e-5)
    snap = p.dw.clone()
    p.frozen = True
    p.dopamine(50.0)
    n.run(300)
    assert torch.equal(snap, p.dw)                                      # frozen = nothing changes


def test_w0_is_never_modified_and_weights_roundtrip(tmp_path):
    n = SpikingNet(Config(n_neurons=N))
    p = n.plast
    w0 = p.w0.clone()
    n.run(300)
    p.dopamine(20.0)
    n.run(200)
    assert torch.equal(w0, p.w0)
    dw = p.dw.clone()
    p.save(tmp_path / "w.npz", {"memories": []})
    n2 = SpikingNet(Config(n_neurons=N))
    n2.plast.load(tmp_path / "w.npz")
    assert torch.allclose(n2.plast.dw, dw, atol=2e-3)
    assert torch.allclose(n2.w[n2.plast.pidx], n2.plast.w0 + n2.plast.dw)
    n2.plast.load(tmp_path / "w.npz", elapsed_days=3.0)                 # forgetting: hippocampal decays faster
    hc, ctx = n2.plast.cls == 1, n2.plast.cls == 0
    r_hc = float(n2.plast.dw[hc].abs().sum() / (dw[hc].abs().sum() + 1e-9))
    r_ctx = float(n2.plast.dw[ctx].abs().sum() / (dw[ctx].abs().sum() + 1e-9))
    assert r_hc < r_ctx < 1.0
    other = SpikingNet(Config(n_neurons=N, seed=2))
    with pytest.raises(ValueError):
        other.plast.load(tmp_path / "w.npz")


def test_pattern_completion_small_net():
    n = SpikingNet(Config(n_neurons=N, hc_scale=6))
    mem = MemorySystem(n)
    n.run(500)
    msgs = ["good morning little brain, the sun is warm today", "a red bicycle crossed the bridge near the river",
            "the bakery smells of fresh bread and coffee"]
    for m in msgs:
        mem.encode(m, "d1")
    dw = n.plast.dw.clone()
    res = mem.test("d1", lures=6)
    assert torch.equal(dw, n.plast.dw)                                  # the test itself does not learn
    assert len(res["recalled"]) >= 2
    hc = [s["hc"] for s in res["scores"]]
    lure = [c["hc"] for c in res["control_scores"]]
    assert np.mean(hc) > max(lure) + 1.0                                # Hz above the best lure


def test_words_are_hashed_deterministically():
    n = SpikingNet(Config(n_neurons=N, plastic=False))
    a, b = MemorySystem(n), MemorySystem(n)
    assert np.array_equal(a.word_neurons("bread"), b.word_neurons("bread"))
    assert not np.array_equal(a.word_neurons("bread"), a.word_neurons("coffee"))
    assert words("The bread, the BREAD and coffee!") == ["bread", "coffee"]


def test_sleep_control_restores_state_and_replays(net):
    mem = MemorySystem(net)
    from spiking.memory import sleep_block
    mem.encode("warm bread in the quiet morning", "d1")
    g, ns = net.baseline_gain, net.noise_gain
    none = sleep_block(net, mem, 0.05, cycles=1, rem_frac=0.9, replay_every_s=0.3, replay=False)
    some = sleep_block(net, mem, 0.05, cycles=1, rem_frac=0.9, replay_every_s=0.3, replay=True)
    assert none == [] and len(some) >= 1
    assert (net.baseline_gain, net.noise_gain, net.mu_offset) == (g, ns, 0.0)


def test_region_counter_does_not_saturate(net):
    assert net.region_count.dtype == torch.float64


def test_exam_uses_frozen_weights(net):
    pong = Pong(net, seed=3)
    p = net.plast
    p.frozen = False
    dw, theta = p.dw.clone(), net.theta.clone()
    res = pong.exam(3)
    assert res["frozen"] and res["rallies"] == 3
    assert torch.equal(dw, p.dw) and torch.equal(theta, net.theta)
    assert p.frozen is False                                            # restored afterwards
    assert res["mean_abs_v"] > 0.05                                     # the paddle is actually driven by the network


def test_pong_baselines():
    assert 0.15 < random_paddle(1000)["hit_rate"] < 0.35
    assert tracking_paddle(200)["hit_rate"] > 0.95
    g = Game(np.random.default_rng(0))
    g.paddle, g.x, g.y, g.vx, g.vy = 0.5, 0.03, 0.5, -0.8, 0.0
    assert g.step(0.02, 0.0) == "hit"


def test_good_pulse_is_rate_limited_and_below_reward(net):
    pong = Pong(net, seed=4)
    p = net.plast
    p.frozen = False
    p.mod["da"] = 0.0
    assert pong.good() is True
    assert 0 < p.mod["da"] < pong.reward
    assert pong.good() is False                                         # within 30 s of simulated time
