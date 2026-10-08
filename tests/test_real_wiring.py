"""Tests for the real-wiring work: Hopf slow layer maths, held-out split, null pipeline pieces, deployed slow layer.

    python -m pytest tests/test_real_wiring.py -q
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

torch = pytest.importorskip("torch")
torch.set_num_threads(1)
from twin import hopf as H  # noqa: E402

N = 30


def small_net(seed=0):
    rng = np.random.default_rng(seed)
    W = rng.random((N, N)) * (rng.random((N, N)) < 0.3)
    W = np.triu(W, 1)
    W = W + W.T
    f = rng.uniform(0.015, 0.05, N)
    return H.sc_matrix(W), np.full(N, H.A_BIF), 2 * np.pi * f


def test_linear_covariance_matches_real_lyapunov():
    """The complex-form solution equals the textbook 2N x 2N real Lyapunov solution (and its lagged covariance)."""
    from scipy.linalg import expm, solve_continuous_lyapunov
    SC, a, w = small_net()
    C = 0.4 * SC
    D = np.diag(a - C.sum(1)) + C
    J = np.block([[D, -np.diag(w)], [np.diag(w), D]])
    S = solve_continuous_lyapunov(J, -H.BETA ** 2 * np.eye(2 * N))
    cx = S[:N, :N]
    sd = np.sqrt(np.diag(cx))
    FC, CT, stable = H.linear_stats(torch.tensor(C)[None], torch.tensor(a), torch.tensor(w), lag_s=2.32)
    assert bool(stable[0])
    np.testing.assert_allclose(FC[0].numpy(), cx / np.outer(sd, sd), atol=1e-10)
    ct = (expm(J * 2.32) @ S)[:N, :N] / np.outer(sd, sd)
    np.testing.assert_allclose(CT[0].numpy(), ct, atol=1e-10)


def test_exact_simulation_reproduces_analytic_fc():
    SC, a, w = small_net(1)
    C = 0.5 * SC
    FC, _, _ = H.linear_stats(torch.tensor(C)[None], torch.tensor(a), torch.tensor(w))
    runs = H.simulate_linear(C, a, w, n_runs=40, run_s=1200, tr=1.16, seed=3)
    # band-passing changes the covariance a little, so a high correlation (not equality) is expected
    assert H.fc_r(H.mean_fc(runs), FC[0].numpy()) > 0.9


def test_nonlinear_and_linear_simulations_agree():
    SC, a, w = small_net(2)
    C = 0.3 * SC
    lin = H.simulate_linear(C, a, w, 20, 600, 1.16, seed=5)
    non = H.sim_runs(torch.tensor(C)[None], a, w, 20, 600, 1.16, seed=5)[0]
    assert H.fc_r(H.mean_fc(lin), H.mean_fc(non)) > 0.8


def test_ec_fit_only_touches_the_mask_and_improves_fit():
    SC, a, w = small_net(3)
    rng = np.random.default_rng(0)
    target = 0.2 + 0.1 * rng.standard_normal((N, N))
    target = np.clip((target + target.T) / 2, -0.9, 0.9)
    np.fill_diagonal(target, 1)
    mask = (SC > 0).astype(float)
    C0 = 0.3 * SC
    ce = np.zeros((N, N))
    EC, hist = H.fit_ec(C0[None], mask[None], a, w, target, ce, iters=200, eps_tau=0.0, tol=-1)
    EC = EC[0].numpy()
    assert (EC[mask == 0] == 0).all() and (EC >= 0).all()
    assert hist[-1][0] > hist[0][0] + 0.1


def test_fcd_vectorised_equals_naive():
    x = np.random.default_rng(0).standard_normal((300, 12))
    fast = H.fcd(x, 1.16, step_s=2.32)
    w, s = int(round(60 / 1.16)), 2
    iu = np.triu_indices(12, 1)
    vecs = np.array([np.corrcoef(x[t:t + w].T)[iu] for t in range(0, len(x) - w + 1, s)])
    c = np.corrcoef(vecs)
    np.testing.assert_allclose(fast, c[np.triu_indices(len(c), 1)], atol=1e-4)


@pytest.mark.skipif(not (ROOT / "out" / "rest" / "qc.json").exists(), reason="resting-state data not present")
def test_split_is_by_session_disjoint_and_complete():
    runs = H.load_runs(ROOT / "out" / "rest")
    fit, held, info = H.split_by_session(runs)
    assert len(fit) + len(held) == len(runs) == 131
    assert not set(info["fit_sessions"]) & set(info["heldout_sessions"])
    assert {r["session"] for r in fit} == set(info["fit_sessions"])
    assert abs(len(fit) - len(held)) <= 2


def test_homotopic_pairs_are_mirrors():
    names = json.loads((ROOT / "out" / "atlas_names.json").read_text())
    pairs = H.homotopic_pairs(names)
    assert len(pairs) == 85                     # (left, right) pairs present in both hemispheres
    for i, j in pairs:
        assert names[i].replace("LH", "").replace("Left", "") == names[j].replace("RH", "").replace("Right", "")


SLOW = ROOT / "twin" / "data" / "slow_layer.npz"


@pytest.mark.skipif(not SLOW.exists(), reason="slow layer not fitted")
def test_slow_layer_is_stationary_z_scored_and_cheap():
    s = H.SlowLayer(seed=1)
    xs = []
    t = time.process_time()
    for _ in range(6000):                      # 10 minutes of model time
        xs.append(s.advance(0.1).copy())
    cpu = time.process_time() - t
    xs = np.array(xs)
    assert np.isfinite(xs).all()
    assert 0.5 < xs[1000:].std() < 1.5          # unit-variance per region on average
    assert cpu / 600 < 0.01                     # < 1 % of a core at real time


@pytest.mark.skipif(not SLOW.exists(), reason="slow layer not fitted")
def test_brain_runs_with_slow_layer_and_public_api_is_unchanged():
    from brain_sim import Brain
    b = Brain(seed=0)
    assert b.slow_on
    for name in ("stimulate", "step", "run", "state", "set_rhythm", "drive", "group_idx"):
        assert hasattr(b, name)
    out = b.run(3.0)
    assert np.isfinite(out).all()
    assert np.abs(b.slow_x).max() > 0           # the slow layer is modulating the fast layer
    b.stimulate("reward", 12)
    b.set_rhythm(3.0, 2.0, 0.3)
    b.step(50)
    st = b.state()
    assert "reward" in st and "sync" in st
    b.use_slow_layer(False)                     # replaying a real session switches the slow layer off
    b.step(200)
    assert not b.slow_on and np.abs(b.slow_x).max() == 0


@pytest.mark.skipif(not SLOW.exists(), reason="slow layer not fitted")
def test_status_label_is_honest_about_randomised_wiring():
    s = H.SlowLayer(which="wiring")
    lab = s.status()["label"]
    assert "randomised wiring" in lab and "unseen sessions" in lab
    assert f"r = {s.meta['wiring_only_heldout_fc_r']:.2f}" in lab and "generated by his wiring" not in lab


RESULTS = ROOT / "docs" / "real_wiring" / "results.json"


@pytest.mark.skipif(not RESULTS.exists(), reason="null comparison not run")
def test_null_comparison_results_are_complete():
    r = json.loads(RESULTS.read_text())
    for tag, s in r.items():
        for fam in ("geometry", "strength"):
            assert s["nulls"][fam]["n"] >= 100, (tag, fam)
            for k in ("g_held_fc_r", "ec_held_fc_r", "ec_held_fcd_ks", "scfc_held_r"):
                p = s["nulls"][fam][k]["p"]
                assert 0 < p <= 1


@pytest.mark.skipif(not SLOW.exists(), reason="slow layer not fitted")
def test_live_model_does_not_need_torch(tmp_path):
    """The live server installs requirements-server.txt (no torch): brain_sim + the slow layer must still load."""
    import subprocess
    stub = tmp_path / "torch"
    stub.mkdir()
    (stub / "__init__.py").write_text('raise ImportError("no torch on the server")')
    code = "import brain_sim; b = brain_sim.Brain(); b.run(0.5); assert b.slow_on; import twin.hopf as H; assert H.torch is None"
    env = {"PYTHONPATH": f"{tmp_path}:{ROOT}", "PATH": "/usr/bin:/bin", "OMP_NUM_THREADS": "1"}
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
