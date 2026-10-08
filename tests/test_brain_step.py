"""Issue #19: the sparse Brain.step is the old dense step, to 1e-9, over 10 s with the same seed.

    python -m pytest tests/test_brain_step.py -q
`reference_step` is the step from main before #19, kept verbatim as the reference (analysis/bench_step.py times it).
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brain_sim import SLOW_DRIVE, Brain  # noqa: E402

TOL = 1e-9


def reference_step(self, k=1):
    """Brain.step before #19: dense delayed gather of the 214x214 ring buffer, (W * zd).sum(1) every step."""
    dt = self.dt
    for _ in range(k):
        now = self.t % self.hist
        z = self.buf[now]
        zd = self.buf[(self.t - self.delay) % self.hist, self._cols]      # z_j(t - tau_ij)
        coupling = self.g * ((self.W * zd).sum(1) - self.W.sum(1) * z)
        if self.slow_on and self.t % 100 == 0:                     # slow layer: every 100 steps (0.1 s)
            self.slow_x = SLOW_DRIVE * self.slow_gain * np.clip(
                self.slow.advance(100 * dt)[self._slow_idx], -2.0, 3.0)
        a_eff = self.a + self.stim + self.drive + self.slow_x + self.neuromod                 # stimulus pushes toward oscillation
        local = np.exp((a_eff + 1j * self.omega - np.abs(z) ** 2) * dt)
        noise = self.noise * np.sqrt(dt) * (self.rng.normal(size=self.n) + 1j * self.rng.normal(size=self.n))
        self.t += 1
        self.buf[self.t % self.hist] = z * local + dt * coupling + noise
        self.stim *= np.exp(-dt / 2.0)
    return self.buf[self.t % self.hist]


def drive(b, step, seconds, neuromod):
    """seconds of the live loop's pattern (step(5) x 10 per 50 ms tick) with stimuli, a sleep-rhythm change and,
    if `neuromod`, a changing neuromodulator excitability; returns the mean amplitude per tick."""
    rng = np.random.default_rng(1)                 # the inputs only; the brain's own stream is its seed
    out = []
    for tick in range(int(seconds / 0.05)):
        if tick % 20 == 0:
            b.stimulate(["reward", "visual", "fear", "language"][tick // 20 % 4], 6.0)
        if tick == 100:
            b.set_rhythm(2.0, coupling=1.4, noise=0.3)          # into "deep sleep"
        if tick == 150:
            b.set_rhythm(10.0, coupling=1.0, noise=0.5)
        if neuromod:
            b.neuromod = 0.4 * np.sin(tick / 7.0) * rng.random(b.n)
        acc = np.zeros(b.n)
        for _ in range(10):
            acc += np.abs(step(b, 5))
        out.append(acc / 10)
    return np.array(out)


@pytest.mark.parametrize("slow", [True, False], ids=["slow_on", "slow_off"])
@pytest.mark.parametrize("neuromod", [True, False], ids=["neuromod_on", "neuromod_off"])
def test_step_matches_reference(slow, neuromod):
    new, old = Brain(seed=0, slow=slow), Brain(seed=0, slow=slow)
    if slow:
        assert new.slow_on, "slow layer data missing (twin/data/slow_layer.npz)"
    a = drive(new, Brain.step, 10.0, neuromod)
    b = drive(old, reference_step, 10.0, neuromod)
    assert new.t == old.t == 10_000
    assert np.abs(new.buf - old.buf).max() < TOL
    assert np.abs(a - b).max() < TOL
    assert np.array_equal(new.stim, old.stim) and np.array_equal(new.slow_x, old.slow_x)
    assert a.mean() > 0.05                          # it oscillated (not a trivially decayed state)


def test_operator_follows_rewiring():
    """analysis/null_test.py assigns a new W after construction: the cached sparse operator must follow it."""
    new, old = Brain(seed=2, slow=False), Brain(seed=2, slow=False)
    new.step(50)
    reference_step(old, 50)
    W = np.random.default_rng(3).permutation(old.W.ravel()).reshape(old.W.shape)
    new.W, old.W = W, W.copy()
    new.step(1000)
    reference_step(old, 1000)
    assert np.abs(new.buf - old.buf).max() < TOL


def test_clone_shares_operator_and_matches():
    b = Brain(seed=4, slow=False)
    b.step(100)
    c = b.clone()
    assert c.ring_coupling()[0] is b.ring_coupling()[0]       # built once, shared read-only
    ref = Brain(seed=4, slow=False)
    reference_step(ref, 100)
    c.step(500)
    reference_step(ref, 500)
    assert np.abs(c.buf - ref.buf).max() < TOL
