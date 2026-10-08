"""BOLD-band Hopf "slow layer" of SUB-01 and its fit to the subject's own resting-state fMRI.

A model of large-scale activity on one real person's wiring; not a mind, not conscious, not the person.

Model (Deco, Kringelbach, Jirsa & Ritter 2017, Sci Rep 7:3095; normal form of a supercritical Hopf bifurcation,
one node per region, operating in the 0.01-0.1 Hz BOLD band; the node signal x_j is compared directly with BOLD):

    dx_j/dt = (a_j - x_j^2 - y_j^2) x_j - w_j y_j + sum_k C_jk (x_k - x_j) + beta * eta_xj(t)
    dy_j/dt = (a_j - x_j^2 - y_j^2) y_j + w_j x_j + sum_k C_jk (y_k - y_j) + beta * eta_yj(t)

with a_j = -0.02 (just below the bifurcation: noisy damped oscillations), beta = 0.02, w_j = 2 pi f_j where f_j is the
peak frequency of region j's BOLD in 0.008-0.08 Hz measured on the FIT half of the runs, and C = G * SC (stage 1,
only the global coupling G is fitted) or C = EC (stage 2, effective connectivity).

Linear (fluctuation) approximation used for fitting (Ponce-Alvarez & Deco 2024 Sci Rep "The Hopf whole-brain
model and its linear approximation"; Gilson et al. 2016 PLoS Comput Biol for the Lyapunov / lagged-covariance method):
with z = x + i y and a near 0, dz = M z dt + noise, M = diag(a + i w) - diag(sum_k C_jk) + C. The stationary complex
covariance P = <z z^H> solves  M P + P M^H + 2 beta^2 I = 0, so Cov(x) = Re(P) / 2 and the lagged covariance
<x(t + tau) x(t)^T> = Re(expm(M tau) P) / 2. Solved exactly through the eigendecomposition of M (batched in PyTorch).

Effective connectivity (Deco, Cruzat & Kringelbach 2019 PNAS 116:18088; Gilson et al. 2016): starting from G * SC,
iterate  C_jk += eps_fc (FC_emp - FC_mod)_jk + eps_tau (COVtau_emp - COVtau_mod)_jk  only on a fixed edge mask, C >= 0.
The mask is the anatomical edges of the connectome PLUS the homotopic (left-right mirror) pairs: tractography badly
under-samples callosal fibres between homotopic regions, which are known to exist anatomically. This is documented
because it is an addition that is not measured in this subject's DWI.

Everything here runs on CPU or GPU (torch), batched over many connectomes (the real one and its nulls).
"""
import glob
import json
import re
from pathlib import Path

import numpy as np
from scipy import signal, stats

try:                       # torch is needed for fitting (batched, CPU/GPU); the live SlowLayer is numpy-only
    import torch
except ImportError:        # the live server (requirements-server.txt) does not install torch
    torch = None

ROOT = Path(__file__).resolve().parents[1]
A_BIF = -0.02
BETA = 0.02
BAND = (0.008, 0.08)


# ----------------------------------------------------------------------------------------------- data
def session_key(s):
    """Chronological order of MyConnectome sessions: numbered sessions first, then 2022, 2022b, WashU."""
    m = re.fullmatch(r"(\d+)(\w*)", s)
    if m and len(m.group(1)) <= 3:
        return (0, int(m.group(1)), m.group(2))
    if m:
        return (1, int(m.group(1)), m.group(2))
    return (2, 0, s)


def load_runs(rest_dir=ROOT / "out" / "rest"):
    """QC-kept runs: list of dicts {stem, session, tr, ts (T x 214 float64, NaN for regions without signal)}."""
    rest_dir = Path(rest_dir)
    qc = json.loads((rest_dir / "qc.json").read_text()) if (rest_dir / "qc.json").exists() else {}
    runs = []
    for f in sorted(glob.glob(str(rest_dir / "*.npz"))):
        stem = Path(f).stem
        if not qc.get(stem, {}).get("kept", True):
            continue
        d = np.load(f)
        ts = d["ts"].astype(np.float64)
        ts[:, ~np.isfinite(ts).all(0) | (np.nanstd(ts, 0) < 1e-6)] = np.nan
        runs.append({"stem": stem, "session": re.search(r"ses-([^_]+)", stem).group(1), "tr": float(d["tr"]), "ts": ts})
    return runs


def split_by_session(runs):
    """Deterministic half split BY SESSION: sessions in chronological order are assigned alternately to fit / held-out,
    except that multi-run sessions go, largest first, to whichever half has fewer runs (keeps the halves balanced).
    No session (and so no run) is in both halves."""
    sessions = sorted({r["session"] for r in runs}, key=session_key)
    count = {s: sum(r["session"] == s for r in runs) for s in sessions}
    halves, n = {0: [], 1: []}, [0, 0]
    for s in sorted([s for s in sessions if count[s] > 1], key=lambda s: -count[s]):
        h = int(n[1] < n[0])
        halves[h].append(s)
        n[h] += count[s]
    for k, s in enumerate([s for s in sessions if count[s] == 1]):
        h = k % 2 if abs(n[0] - n[1]) < 2 else int(n[1] < n[0])
        halves[h].append(s)
        n[h] += 1
    fit = [r for r in runs if r["session"] in halves[0]]
    held = [r for r in runs if r["session"] in halves[1]]
    return fit, held, {"rule": "sessions in chronological order, alternating; multi-run sessions balanced by run count",
                       "fit_sessions": sorted(halves[0], key=session_key),
                       "heldout_sessions": sorted(halves[1], key=session_key)}


def bandpass_z(x, tr):
    """Same processing as process_rest.py: detrend, 2nd-order Butterworth 0.01-0.1 Hz (filtfilt), z-score. x: (..., T, n)."""
    x = signal.detrend(x, axis=-2)
    b, a = signal.butter(2, [0.01 * 2 * tr, min(0.1 * 2 * tr, 0.99)], btype="band")
    x = signal.filtfilt(b, a, x, axis=-2)
    return (x - x.mean(-2, keepdims=True)) / (x.std(-2, keepdims=True) + 1e-9)


def fc(ts):
    """Pearson FC of one run (T x n), NaN rows/cols for regions without signal."""
    ok = np.isfinite(ts).all(0)
    out = np.full((ts.shape[1],) * 2, np.nan)
    out[np.ix_(ok, ok)] = np.corrcoef(ts[:, ok].T)
    return out


def mean_fc(runs):
    """Fisher-z average of per-run FC (pairs averaged over the runs where both regions have signal)."""
    z = np.array([np.arctanh(np.clip(fc(r["ts"]), -0.999999, 0.999999)) for r in runs])
    m = np.tanh(np.nanmean(z, 0))
    np.fill_diagonal(m, 1.0)
    return m


def lagged_cov(ts, lag):
    """Normalised lagged covariance <x_i(t + lag) x_j(t)> / sqrt(var_i var_j) of one z-scored run."""
    x = np.nan_to_num(ts)
    x = (x - x.mean(0)) / (x.std(0) + 1e-9)
    return x[lag:].T @ x[:-lag] / (len(x) - lag)


LAG_TR = 1.16          # the lagged covariance uses only runs with this TR (94 of 131), lag = 2 volumes
LAG_S = 2 * LAG_TR


def mean_lagged_cov(runs, tr=LAG_TR, lag=2):
    """Normalised lagged covariance at lag 2 volumes, averaged over the runs acquired with TR = `tr` (exact lag in s)."""
    sel = [r for r in runs if abs(r["tr"] - tr) < 1e-3]
    return np.mean([lagged_cov(r["ts"], lag) for r in sel], 0)


def fcd(ts, tr, win_s=60.0, step_s=4.0):
    """FC dynamics (Hansen et al. 2015; Deco et al. 2017): correlations between the upper triangles of sliding-window FCs."""
    x = np.nan_to_num(np.asarray(ts, np.float32))
    w, s = int(round(win_s / tr)), max(1, int(round(step_s / tr)))
    win = np.lib.stride_tricks.sliding_window_view(x, w, axis=0)[::s]          # (nw, n, w)
    win = win - win.mean(-1, keepdims=True)
    win = win / (np.linalg.norm(win, axis=-1, keepdims=True) + 1e-12)
    fcs = np.einsum("kiw,kjw->kij", win, win, optimize=True)                    # (nw, n, n) window FCs
    iu = np.triu_indices(x.shape[1], 1)
    v = fcs[:, iu[0], iu[1]]
    v = v - v.mean(1, keepdims=True)
    v = v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-12)
    c = v @ v.T
    return c[np.triu_indices(len(c), 1)]


def fcd_pool(runs, **kw):
    return np.concatenate([fcd(r["ts"], r["tr"], **kw) for r in runs])


def peak_freqs(runs, band=BAND, df=0.001):
    """Per-region peak frequency (Hz) of the BOLD power spectrum inside `band`. Each run's Welch spectrum (with its own
    TR) is normalised to unit power in the band and interpolated onto a common 0.001 Hz grid before averaging, so runs
    with different TRs and lengths all count with the right frequency axis."""
    grid = np.arange(band[0], band[1] + df / 2, df)
    acc = np.zeros((len(grid), runs[0]["ts"].shape[1]))
    for r in runs:
        x = np.nan_to_num(r["ts"])
        f, p = signal.welch(x, fs=1.0 / r["tr"], nperseg=min(256, len(x)), axis=0)
        q = np.array([np.interp(grid, f, p[:, k]) for k in range(p.shape[1])]).T
        acc += q / (q.sum(0, keepdims=True) + 1e-30)
    return grid[np.argmax(acc, 0)]


def upper(m):
    return m[np.triu_indices(m.shape[-1], 1)]


def fc_r(a, b):
    """Pearson r between the upper triangles (pairs that are finite in both)."""
    x, y = upper(a), upper(b)
    ok = np.isfinite(x) & np.isfinite(y)
    return float(np.corrcoef(x[ok], y[ok])[0, 1])


def region_fit(sim, emp):
    """Per-region fit: r between region i's simulated and empirical FC rows (excluding i)."""
    n = len(sim)
    out = np.full(n, np.nan)
    for i in range(n):
        m = np.arange(n) != i
        x, y = sim[i, m], emp[i, m]
        ok = np.isfinite(x) & np.isfinite(y)
        if ok.sum() > 3:
            out[i] = np.corrcoef(x[ok], y[ok])[0, 1]
    return out


def homotopic_pairs(names):
    idx = {nm: i for i, nm in enumerate(names)}
    pairs = []
    for i, nm in enumerate(names):
        mirror = nm.replace("_LH_", "_RH_").replace("Left ", "Right ")
        if mirror != nm and mirror in idx:
            pairs.append((i, idx[mirror]))
    return pairs


def sc_matrix(W):
    """Structural coupling matrix for the model: symmetric, zero diagonal, scaled to max 0.2 (Deco et al. 2017)."""
    C = np.asarray(W, float).copy()
    C = (C + C.T) / 2
    np.fill_diagonal(C, 0)
    return 0.2 * C / C.max()


# ----------------------------------------------------------------------------------------------- linear Hopf (torch)
def _t(x, dev, dtype=None):
    return torch.as_tensor(np.asarray(x), dtype=dtype or torch.float64, device=dev)


def linear_stats(C, a, w, beta=BETA, lag_s=LAG_S):
    """Analytic FC and normalised lagged covariance of the linearised Hopf model.
    C: (B, n, n) torch float64 coupling (C[j, k] = input from k to j); a, w: (n,) torch. Returns FC, COVtau (B, n, n)."""
    n = C.shape[-1]
    eye = torch.eye(n, dtype=C.dtype, device=C.device)
    M = torch.diag_embed(a - C.sum(-1)).to(torch.complex128) + C.to(torch.complex128) + 1j * torch.diag(w).to(torch.complex128)
    lam, V = torch.linalg.eig(M)
    Vi = torch.linalg.inv(V)
    Q = 2 * beta ** 2 * eye.to(torch.complex128)
    Qt = Vi @ Q @ Vi.conj().transpose(-1, -2)
    S = -Qt / (lam[..., :, None] + lam.conj()[..., None, :])
    P = V @ S @ V.conj().transpose(-1, -2)
    cov = P.real / 2
    sd = torch.sqrt(torch.diagonal(cov, dim1=-2, dim2=-1).clamp_min(1e-30))
    norm = sd[..., :, None] * sd[..., None, :]
    E = V @ torch.diag_embed(torch.exp(lam * lag_s)) @ Vi
    covt = (E @ P).real / 2
    stable = (lam.real.max(-1).values < 0)
    return cov / norm, covt / norm, stable


def fit_G(SC, a, w, fc_emp, Gs, dev="cpu"):
    """Stage 1: analytic FC r (upper triangle) vs fit-half FC for each global coupling G. Returns r per G."""
    C = _t(SC, dev)[None] * _t(Gs, dev)[:, None, None]
    FCm, _, stable = linear_stats(C, _t(a, dev), _t(w, dev))
    iu = torch.triu_indices(SC.shape[0], SC.shape[0], 1, device=dev)
    x = FCm[:, iu[0], iu[1]]
    y = _t(fc_emp, dev)[iu[0], iu[1]]
    ok = torch.isfinite(y)
    x, y = x[:, ok], y[ok]
    x = x - x.mean(-1, keepdim=True)
    y = y - y.mean()
    r = (x * y).sum(-1) / (x.norm(dim=-1) * y.norm())
    return torch.where(stable, r, torch.full_like(r, -1.0)).cpu().numpy()


def fit_ec(C0, mask, a, w, fc_emp, covt_emp, iters=400, eps_fc=0.02, eps_tau=0.01, lag_s=LAG_S, dev="cpu", tol=1e-5,
           log=None):
    """Stage 2: effective connectivity, batched. C0, mask: (B, n, n) numpy/torch; a, w: (n,); targets (n, n).
    Gradient-like update (Deco et al. 2019, Gilson et al. 2016), only on mask edges, kept >= 0, diagonal 0.
    Stops when the mean fit-half FC r improves less than `tol` over 20 iterations. Returns EC (B, n, n), history."""
    C = _t(C0, dev).clone()
    m = _t(mask, dev)
    a_, w_ = _t(a, dev), _t(w, dev)
    fe = torch.nan_to_num(_t(fc_emp, dev))
    ce = torch.nan_to_num(_t(covt_emp, dev))
    valid = torch.isfinite(_t(fc_emp, dev)).to(C.dtype)
    n = C.shape[-1]
    off = 1 - torch.eye(n, dtype=C.dtype, device=dev)
    iu = torch.triu_indices(n, n, 1, device=dev)
    hist = []
    for it in range(iters):
        FCm, CTm, stable = linear_stats(C, a_, w_, lag_s=lag_s)
        x = FCm[:, iu[0], iu[1]]
        y = fe[iu[0], iu[1]]
        xc, yc = x - x.mean(-1, keepdim=True), y - y.mean()
        r = ((xc * yc).sum(-1) / (xc.norm(dim=-1) * yc.norm())).cpu().numpy()
        hist.append(r)
        if log and it % 50 == 0:
            log(f"EC it {it}: fit FC r mean {r.mean():.3f}")
        if it >= 20 and np.nanmean(hist[-1] - hist[-21]) < tol:
            break
        dC = eps_fc * (fe - FCm) * valid + eps_tau * (ce - CTm) * valid
        C = torch.clamp(C + dC * m * off, min=0.0)
        bad = ~stable
        if bad.any():                                       # never leave the stable (fluctuating) regime
            C[bad] = C[bad] * 0.95
    return C, np.array(hist)


# ----------------------------------------------------------------------------------------------- nonlinear simulation
def simulate(C, a, w, seconds, tr, beta=BETA, dt=0.1, transient_s=120.0, seed=0, dev="cpu", dtype=None):
    """Euler-Maruyama simulation of the full (nonlinear) Hopf model, batched.
    C: (B, n, n); returns x sampled every TR after the transient: numpy (B, T, n) (raw, not yet band-passed)."""
    dtype = dtype or torch.float32
    g = torch.Generator(device=dev).manual_seed(int(seed))
    C = _t(C, dev, dtype)
    B, n = C.shape[0], C.shape[-1]
    a_, w_ = _t(a, dev, dtype), _t(w, dev, dtype)
    s = C.sum(-1)
    x = 0.1 * torch.randn(B, n, generator=g, device=dev, dtype=dtype)
    y = 0.1 * torch.randn(B, n, generator=g, device=dev, dtype=dtype)
    every = int(round(tr / dt))
    total = int(round((seconds + transient_s) / dt))
    start = int(round(transient_s / dt))
    out = []
    sq = beta * dt ** 0.5
    Ct = C.transpose(-1, -2)
    for k in range(total):
        r2 = x * x + y * y
        cx = torch.bmm(x[:, None, :], Ct)[:, 0] - s * x
        cy = torch.bmm(y[:, None, :], Ct)[:, 0] - s * y
        dx = (a_ - r2) * x - w_ * y + cx
        dy = (a_ - r2) * y + w_ * x + cy
        x = x + dt * dx + sq * torch.randn(B, n, generator=g, device=dev, dtype=dtype)
        y = y + dt * dy + sq * torch.randn(B, n, generator=g, device=dev, dtype=dtype)
        if k >= start and (k - start) % every == 0:
            out.append(x)
    return torch.stack(out, 1).cpu().numpy().astype(np.float64)


def sim_runs(C, a, w, n_runs, run_s, tr, seed=0, dev="cpu", batch_runs=None):
    """Simulate `n_runs` independent runs of `run_s` seconds per connectome; band-pass + z-score like the real data.
    Returns list (per connectome) of lists of runs (dicts with ts, tr) - same format as load_runs."""
    C = torch.as_tensor(np.asarray(C)) if not torch.is_tensor(C) else C
    B = C.shape[0]
    reps = C.repeat_interleave(n_runs, 0)
    x = simulate(reps, a, w, run_s, tr, seed=seed, dev=dev)
    x = bandpass_z(x, tr)
    return [[{"ts": x[b * n_runs + k], "tr": tr} for k in range(n_runs)] for b in range(B)]


def evaluate(runs_sim, fc_target, fcd_target):
    """Held-out comparison: FC r, FCD KS distance, per-region FC-row r."""
    fs = mean_fc(runs_sim)
    return {"fc_r": fc_r(fs, fc_target),
            "fcd_ks": float(stats.ks_2samp(fcd_pool(runs_sim), fcd_target).statistic),
            "region_r": region_fit(fs, fc_target)}


def simulate_linear(C, a, w, n_runs, run_s, tr, beta=BETA, seed=0):
    """Exact sampling of the LINEARISED Hopf model at the TR (complex Ornstein-Uhlenbeck process, no integration error):
    z_{k+1} = A z_k + xi_k with A = expm(M tr), E[xi xi^H] = P - A P A^H, started from the stationary distribution.
    C: (n, n) numpy. Returns x = Re(z) band-passed + z-scored like the data, as a list of run dicts."""
    Ct = torch.as_tensor(np.asarray(C), dtype=torch.float64)[None]
    n = Ct.shape[-1]
    M = (torch.diag_embed(torch.as_tensor(a) - Ct.sum(-1)) + Ct).to(torch.complex128)[0] + 1j * torch.diag(torch.as_tensor(w)).to(torch.complex128)
    lam, V = torch.linalg.eig(M)
    Vi = torch.linalg.inv(V)
    Qt = Vi @ (2 * beta ** 2 * torch.eye(n, dtype=torch.complex128)) @ Vi.conj().T
    P = V @ (-Qt / (lam[:, None] + lam.conj()[None, :])) @ V.conj().T
    P = (P + P.conj().T) / 2
    A = V @ torch.diag(torch.exp(lam * tr)) @ Vi
    Qd = P - A @ P @ A.conj().T
    Qd = (Qd + Qd.conj().T) / 2

    def chol(S):
        ev, U = torch.linalg.eigh(S)
        return U * torch.sqrt(ev.real.clamp_min(0))[None, :]
    LP, LQ = chol(P), chol(Qd)
    g = torch.Generator().manual_seed(int(seed))
    T = int(round(run_s / tr))

    def cn(k):
        return torch.complex(torch.randn(n, k, generator=g, dtype=torch.float64),
                             torch.randn(n, k, generator=g, dtype=torch.float64)) / np.sqrt(2)
    z = LP.to(torch.complex128) @ cn(n_runs)
    out = torch.empty(T, n, n_runs, dtype=torch.float64)
    for t in range(T):
        out[t] = z.real
        z = A @ z + LQ.to(torch.complex128) @ cn(n_runs)
    x = bandpass_z(out.permute(2, 0, 1).numpy(), tr)
    return [{"ts": x[k], "tr": tr} for k in range(n_runs)]


# ----------------------------------------------------------------------------------------------- runtime slow layer
class SlowLayer:
    """The fitted slow layer at run time (light: one 214 x 214 complex mat-vec per 0.1 s of model time).

    Samples the linearised Hopf model exactly on a fixed 0.1 s grid (complex Ornstein-Uhlenbeck process, see
    simulate_linear) from the parameters fitted by analysis/real_wiring.py (twin/data/slow_layer.npz). advance(dt)
    returns each region's slow signal in units of its own stationary standard deviation (a z-score, like the recorded
    fMRI that RealBaseline replays), so it can drive the fast layer exactly where the recording used to."""

    STEP = 0.1

    def __init__(self, path=ROOT / "twin" / "data" / "slow_layer.npz", seed=0, which=None):
        """which: "wiring" (default: his connectome x one fitted global coupling G; randomised wiring reaches most of its FC r)
        or "ec" (effective connectivity fitted on his anatomical + homotopic edges: closer to his recorded FC, but
        randomised wiring fitted the same way does as well). Env SUB01_SLOW overrides the default."""
        import os
        d = np.load(path, allow_pickle=False)
        self.names = [str(x) for x in d["names"]]
        self.meta = json.loads(str(d["meta"]))
        self.which = which or os.environ.get("SUB01_SLOW", "wiring")
        C = (d["C"] if self.which == "ec" else d["C_wiring"]).astype(np.float64)
        n = len(C)
        a = np.full(n, float(d["a"]))
        w = 2 * np.pi * d["freqs"].astype(np.float64)
        M = np.diag(a - C.sum(1) + 1j * w) + C
        lam, V = np.linalg.eig(M)
        Vi = np.linalg.inv(V)
        Qt = Vi @ (2 * float(d["beta"]) ** 2 * np.eye(n)) @ Vi.conj().T
        P = V @ (-Qt / (lam[:, None] + lam.conj()[None, :])) @ V.conj().T
        P = (P + P.conj().T) / 2
        self.A = V @ np.diag(np.exp(lam * self.STEP)) @ Vi
        Qd = self.A @ P @ self.A.conj().T
        Qd = P - Qd
        Qd = (Qd + Qd.conj().T) / 2

        def chol(S):
            ev, U = np.linalg.eigh(S)
            return U * np.sqrt(np.clip(ev.real, 0, None))[None, :]
        self.LQ = chol(Qd)
        self.sd = np.sqrt(np.clip(np.diag(P).real / 2, 1e-30, None))
        self.rng = np.random.default_rng(seed)
        self.z = chol(P) @ self._cn()
        self.acc = 0.0
        self.x = self.z.real / self.sd

    def _cn(self):
        n = len(self.sd)
        return (self.rng.standard_normal(n) + 1j * self.rng.standard_normal(n)) / np.sqrt(2)

    def advance(self, dt):
        """Move dt seconds of model time; returns the z-scored slow signal per region (n,)."""
        self.acc += dt
        while self.acc >= self.STEP:
            self.acc -= self.STEP
            self.z = self.A @ self.z + self.LQ @ self._cn()
        self.x = self.z.real / self.sd
        return self.x

    def status(self):
        m = self.meta
        if self.which != "ec":
            r = m.get("wiring_only_heldout_fc_r")
            lo, hi = m.get("wiring_only_null_mean_strength"), m.get("wiring_only_null_mean_geometry")
            rnd = f"; randomised wiring: r = {min(lo, hi):.2f}-{max(lo, hi):.2f}" if lo is not None and hi is not None else ""
            return {"model": "Hopf slow layer: his connectome x one global coupling", "connectome": m.get("connectome"),
                    "heldout_fc_r": r, "null_p_geometry": m.get("wiring_only_null_p_geometry"),
                    "null_p_strength": m.get("wiring_only_null_p_strength"),
                    "label": f"slow activity of a model on his wiring (one fitted coupling). Similarity of its co-activity "
                             f"pattern to his recorded activity on unseen sessions: r = {r:.2f}" + rnd}
        r = m.get("heldout_fc_r")
        return {"model": "Hopf slow layer: effective connectivity fitted on his anatomical + homotopic edges",
                **{k: m.get(k) for k in ("connectome", "heldout_fc_r", "heldout_fcd_ks", "wiring_only_heldout_fc_r",
                                         "null_p_geometry", "null_p_strength")},
                "label": f"slow activity from connections fitted to his scans (similarity on unseen sessions r = {r:.2f}; "
                         f"randomised wiring fitted the same way does about as well)"}
