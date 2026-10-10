"""His spiking neurons in the day: a small spiking network on the server CPU takes part in his real choices (#55).

A small simulated spiking network (20,000 neurons by default) built on the same wiring as the nightly 1M-neuron
network (the same construction and seed: spiking/wiring.py) runs in its own child process, like browse_service.py, so
the 50 ms brain tick never waits for it. It is a decision server: the main process sends the labels of the options
on offer, the network gets them as cues, its striatal action pools race (spiking/choice.py, #39), and it answers with
its pick, every pool's rate and the simulated decision time. brain_vote.vote adds the pool rates as one small term
(SPIKING_W) next to the rate model's value, the taste and the novelty; the rate model stays the main decider.

Why numpy and not spiking/net.py: torch is not in the server image (it would add ~700 MB), and at 20k neurons an
event-driven numpy step is fast enough (~0.3 ms per simulated ms on one core, measured in docs/spiking/live_cpu.md).
net.py and this file share the numpy construction (wiring.py), so the synapses are identical; the dynamics are the
same LIF equations, without the recorded resting-state drive (the day network idles between decisions and gets the
plain background drive).

Cues = real option labels. A label's content words (spiking/words.py, at most LABEL_WORDS) are each hashed exactly
as memory.py hashes words (wiring.word_neurons, the same sha256 seed) at WORD_FRAC of the excitatory neurons of every
parcel; the visual and language parcels are kept. The same word lands on the same neurons in every label, so what is
learned about "bread" in one label carries over to another label with "bread" in it. Action pools: the excitatory
neurons of the striatum, split among the offered labels by a hashed affinity (choice.py's, averaged over the label's
words and rank-normalised so that a label's word count does not change its pool size). Any 2-6 options, any labels.

Learning (the #39 rule, live): when he leaves a page, the tastes response of the stay (tastes.PageWatch, its
reward-prediction error from Tastes.learn) becomes dopamine for the decision that led to the page:
    dw += eta_t * da * pre * post,  da = clip(DA_GAIN * delta, -1, 1),
pre = clamp((cue-neuron rate in the decision window - 5 Hz) / 40 Hz, 0, 1) and post = +1 on the pool of the option
that was followed, -1/(K-1) on the other offered pools (zero-sum), tagged at the decision. Only the cue -> striatum
synapses learn; w = clamp(w0 + dw, 0, w_max). The stability fix named in docs/spiking/choice.md: a decaying learning
rate, eta_t = ETA / (1 + n / ETA_HALF), never below ETA_FLOOR x ETA, so a preference settles instead of flipping.
The learned dw is saved to /data/spiking/live_weights.npz (atomic write) and loaded at start.

A frozen twin (the same network with no learning, the same offers and the same noise) runs every decision too, so
the page can compare: how often its pick matched the option that later paid off, against the twin and chance.
Wording: a small simulated spiking network built on the same wiring takes part in his choices and learns from a
simulated reward. Never "he thinks / understands / wants".

Protocol: the decision protocol shared with the 1M-neuron GPU network (#58), one JSON object per line on stdin/stdout.
    {"type": "decide", "id": "b-1", "options": [label, ...], "kind": "browse|chess|plan", "deadline_ms": 2000}
        -> {"type": "decision", "id": "b-1", "pick", "pool_rates", "sim_ms", "n_neurons",
            + here: "timeout", "twin_pick", "twin_rates", "cpu_ms", "threshold_hz"}
    {"type": "reward", "id": "b-1", "value": 0.3, "followed": 0}   (value = the tastes prediction error; "followed",
        an extension of this child, is the option the vote followed: default the network's own pick)
        -> {"type": "rewarded", "id": "b-1", "ok", "eta", "n_learn"}
    {"type": "status", "id": "s-1"} -> {"type": "status", "id": "s-1", "cpu_s", "uptime_s", "n_decisions", ...}
Unasked, it streams {"type": "spiking", "net": "cpu", ...} frames like the GPU session's (groups, mean rate), in the
compact form of spiking/frames.py (per-region rates + a sample of every neuron's spikes, #62), at most every FRAME_S
while it simulates. Between decisions it runs IDLE_MS of background
activity every IDLE_EVERY_S, so the page's raster keeps a pulse (~1-2 % of a core). The parent's deadline is enforced by
the parent (LiveClient): a late answer is dropped there. The child exits when its stdin closes or on {"type": "stop"}.

    python -m spiking.live --data-dir /data --neurons 20000
"""
import argparse
import hashlib
import json
import math
import os
import select
import sys
import time
from pathlib import Path

import numpy as np

from spiking import frames
from spiking.config import Config
from spiking.regions import Regions
from spiking.wiring import Layout, input_regions, synapse_lists, word_neurons
from spiking.words import words

HERE = Path(__file__).resolve().parent.parent
N_NEURONS = 20_000
CUE_GROUPS = ("visual", "language")
ACTION_GROUP = "reward"           # striatum: caudate, putamen, accumbens
LABEL_WORDS = 4                   # content words of a label used as its cue
WORD_FRAC = 0.08                  # per word (a 4-word label covers ~28 % of the cue space, one word 8 %)
FRAC_HC = 0.005                   # memory.py's default (only keeps the hashing identical; hippocampus is not a cue)
CUE_AMP = 8.0                     # mV on the cue neurons while the options are on offer (choice.py)
SETTLE_MS = 100                   # background only, before the cues come on
CHECK_MS, MIN_MS, TIMEOUT_MS = 10, 50, 250
THR_Z = 2.0
ETA = 0.6                         # mV per unit dopamine (choice.py)
ETA_HALF = 50.0                   # learning-rate decay: eta halves after 50 learned decisions...
ETA_FLOOR = 0.25                  # ...and never goes below a quarter
DA_GAIN = 2.0                     # tastes' prediction errors are mostly within +-0.5; x2 brings them to choice.py's +-1
MAX_OPTIONS = 6
PENDING = 8                       # decisions kept for a late dopamine (the next page's decision comes first)
VERSION = 1
CALIB_LABELS = ("apple", "river", "cloud", "stone", "lamp", "bird", "salt", "rope")
DA_SHOW_TAU_S = 30.0              # the page's dopamine reading decays back to 0 (wall seconds) after a burst (#89)
FRAME_S = 0.2                     # at most 5 frames/s to the page
RASTER_ROWS = 200
IDLE_MS = int(os.environ.get("SUB01_SPIKING_LIVE_IDLE_MS", 50))     # background run between decisions (0: none)
IDLE_EVERY_S = 2.0
GROUP_KEYS = ("visual", "somatomotor", "attention", "salience", "limbic", "control", "default", "reward", "fear",
              "memory", "relay", "language")


# --- labels -> cues and pools (torch-free: they work on any network with the wiring.py layout) -------------------------
def label_words(label):
    ws = words(str(label or ""), max_words=LABEL_WORDS)
    return ws or [str(label or "").strip().lower()[:40] or "nothing"]


def label_cue(net, label, cue_space, regions=None, frac=WORD_FRAC):
    """Cue neurons of a label: the union of its words' neurons (memory.py hashing) inside the cue space."""
    ids = [word_neurons(net, w, frac, FRAC_HC, regions) for w in label_words(label)]
    return np.intersect1d(np.unique(np.concatenate(ids)), cue_space)


def _word_affinity(word, n):
    h = hashlib.sha256(("sub01-choice-pool:" + word).encode()).digest()       # choice.py's hash
    return np.random.default_rng(int.from_bytes(h[:8], "little")).random(n)


def label_affinity(label, n):
    """Affinity of each of n action neurons for a label: the mean of its words' hashed affinities, rank-normalised to
    (0, 1) so labels with more words do not get smaller pools."""
    a = np.mean([_word_affinity(w, n) for w in label_words(label)], axis=0)
    r = np.empty(n)
    r[np.argsort(a, kind="stable")] = np.arange(n)
    return (r + 0.5) / n


def label_pools(action, affinities):
    """Disjoint pools: each action neuron goes to the offered label it has the highest affinity for."""
    owner = np.argmax(np.stack(affinities), axis=0)
    return [action[owner == k] for k in range(len(affinities))]


def lean(rates, scale_hz=2.0):
    """Pool rates -> a lean per option in -1..1 (0 = no preference): tanh((rate - mean) / 2 Hz)."""
    r = np.asarray(rates, dtype=float)
    return np.tanh((r - r.mean()) / scale_hz)


# --- the numpy network ---------------------------------------------------------------------------------------------
class LiveNet(Layout):
    """LIF network with net.py's construction (wiring.py) in numpy, float32, one CPU core, event-driven delays."""

    def __init__(self, cfg=None, regions=None):
        self.cfg = cfg = cfg or Config(n_neurons=N_NEURONS)
        self.reg = regions or Regions()
        t0 = time.time()
        self._layout()
        src_l, dst_l, w_l, d_l, _, _ = synapse_lists(self)
        src = np.concatenate(src_l)
        order = np.argsort(src, kind="stable")                 # the CSR order of net.py (stable sort by source)
        src = src[order]
        self.dst = np.concatenate(dst_l)[order]
        self.w = np.concatenate(w_l)[order]
        delay = np.concatenate(d_l)[order]
        self.D = int(delay.max()) + 1
        self.rowptr = np.zeros(self.n + 1, dtype=np.int64)
        self.rowptr[1:] = np.cumsum(np.bincount(src, minlength=self.n))
        self.slot_off = delay.astype(np.int64) * self.n + self.dst      # where a spike's input lands, from slot 0
        self.src = src
        self.n_syn = len(src)
        self.a = cfg.dt / cfg.tau_m
        self.n_ref = int(round(cfg.t_ref / cfg.dt))
        self.noise_sd = np.float32(cfg.sigma_ext * math.sqrt(self.a))
        self.build_s = time.time() - t0
        self.row_of, self.raster_ids, self.raster = None, [], []
        self.hook = None                                         # hook(net) every CHECK_MS steps (frames)
        self._state()

    def enable_raster(self, n_rows=RASTER_ROWS, seed=0):
        """Record the spikes of a fixed sample for the page: one neuron per region (net.py's choice), first n_rows."""
        rng = np.random.default_rng(seed)
        ids = np.sort([int(self.off[r] + rng.integers(self.size[r])) for r in range(self.reg.n)][:n_rows])
        self.row_of = np.full(self.n, -1, dtype=np.int16)
        self.row_of[ids] = np.arange(len(ids), dtype=np.int16)
        self.raster_ids, self.raster = ids, []

    def _state(self, seed=0):
        c = self.cfg
        rng = np.random.default_rng(self.cfg.seed + 2000 + seed)
        self.v = (rng.random(self.n) * (c.v_th - c.v_reset) + c.v_reset).astype(np.float32)
        self.ref = np.zeros(self.n, dtype=np.int16)
        self.buf = np.zeros(self.D * self.n, dtype=np.float32)
        self.count = np.zeros(self.n, dtype=np.int64)
        self.mu = np.full(self.n, c.mu_ext, dtype=np.float32)
        self.t = 0
        self.rng = np.random.default_rng(self.cfg.seed + 1000 + seed)

    def twin(self):
        """A copy with its own state and weights, sharing the fixed synapse arrays (a frozen control)."""
        tw = object.__new__(LiveNet)
        tw.__dict__.update(self.__dict__)
        tw.w = self.w.copy()
        tw.row_of, tw.raster_ids, tw.raster, tw.hook = None, [], [], None
        tw._state(seed=1)
        return tw

    def drive(self, ids=None, amp=0.0):
        self.mu.fill(self.cfg.mu_ext)
        if ids is not None and len(ids):
            self.mu[ids] += np.float32(amp)

    def step(self):
        c, n = self.cfg, self.n
        slot = (self.t % self.D) * n
        inp = self.buf[slot:slot + n]
        v = self.v
        v *= np.float32(1.0 - self.a)
        v += np.float32(self.a) * self.mu
        v += self.noise_sd * self.rng.standard_normal(n, dtype=np.float32)
        v += inp
        inp.fill(0.0)
        refr = self.ref > 0
        if refr.any():
            v[refr] = c.v_reset
            self.ref[refr] -= 1
        spk = np.flatnonzero(v >= c.v_th)
        if spk.size:
            v[spk] = c.v_reset
            self.ref[spk] = self.n_ref
            self.count[spk] += 1
            if self.row_of is not None:
                rows = self.row_of[spk]
                rows = rows[rows >= 0]
                if rows.size:
                    self.raster.append((self.t, rows))
            start = self.rowptr[spk]
            cnt = self.rowptr[spk + 1] - start
            tot = int(cnt.sum())
            if tot:
                syn = np.repeat(start - np.cumsum(cnt) + cnt, cnt) + np.arange(tot)
                tgt = (self.slot_off[syn] + slot) % self.buf.size
                np.add.at(self.buf, tgt, self.w[syn])
        self.t += 1
        return spk.size

    def run(self, ms):
        for i in range(int(round(ms / self.cfg.dt))):
            self.step()
            if self.hook is not None and self.t % CHECK_MS == 0:
                self.hook(self)


# --- one decision on one network -------------------------------------------------------------------------------------
class Chooser:
    """Cues, pools and the race (choice.py's) on one LiveNet."""

    def __init__(self, net):
        self.net = net
        reg = net.reg
        cue_regions = sorted(set(sum((reg.groups[g] for g in CUE_GROUPS), [])))
        self.cue_space = np.concatenate([net.region_neurons(r, exc_only=True) for r in cue_regions])
        self.action = net.group_neurons(ACTION_GROUP, exc_only=True)
        self.regions = input_regions(net)
        self._cue, self._aff = {}, {}
        is_cue = np.zeros(net.n, bool)
        is_cue[self.cue_space] = True
        is_act = np.zeros(net.n, bool)
        is_act[self.action] = True
        src = net.src
        self.pidx = np.flatnonzero(is_cue[src] & is_act[net.dst] & (net.w > 0))   # plastic cue -> striatum E -> E
        self.pre, self.post = src[self.pidx], net.dst[self.pidx]
        self.w0 = net.w[self.pidx].copy()
        self.w_max = net.cfg.w_max_ctx
        self.thr_hz = None
        self.timeout_ms = TIMEOUT_MS

    def cue(self, label):
        if label not in self._cue:
            self._cue[label] = label_cue(self.net, label, self.cue_space, self.regions)
            self._aff[label] = label_affinity(label, len(self.action))
        return self._cue[label]

    def present(self, labels, seed):
        """Drive the offered labels' cues and run the race. -> (pick, pool rates Hz, decision ms, timeout,
        pre factor per plastic synapse, option of each plastic synapse's post neuron (-1: none))."""
        net = self.net
        cues = [self.cue(lb) for lb in labels]
        pools = label_pools(self.action, [self._aff[lb] for lb in labels])
        sizes = np.array([max(1, len(p)) for p in pools], dtype=float)
        net.rng = np.random.default_rng(seed)                  # the same noise for the network and its twin
        net.drive()
        net.run(SETTLE_MS)
        c0 = net.count.copy()
        net.drive(np.unique(np.concatenate(cues)), CUE_AMP)
        pick, ms, timeout, rates = None, None, True, None
        try:
            for t in range(self.timeout_ms // CHECK_MS):
                net.run(CHECK_MS)
                ms = (t + 1) * CHECK_MS
                d = net.count - c0
                rates = np.array([d[p].sum() for p in pools]) / sizes / (ms / 1000.0)
                if self.thr_hz is not None and ms >= MIN_MS and (rates > self.thr_hz).any():
                    pick, timeout = int(np.argmax(rates)), False
                    break
            if pick is None:
                pick = int(np.argmax(rates))
            pre_rate = (net.count[self.pre] - c0[self.pre]) / (ms / 1000.0)
        finally:
            net.drive()
        pre = np.clip((pre_rate - 5.0) / 40.0, 0.0, 1.0).astype(np.float32)
        opt = np.full(net.n, -1, dtype=np.int8)
        for k, p in enumerate(pools):
            opt[p] = k
        return pick, rates, ms, timeout, pre, opt[self.post]

    def calibrate(self, presentations=12, seed=0):
        """Threshold = mean + THR_Z sd of the pool rates at 100 ms (4 random calibration words, no race)."""
        rng = np.random.default_rng(seed)
        thr, self.thr_hz, rates = self.thr_hz, None, []
        keep, self.timeout_ms = self.timeout_ms, 100
        try:
            for i in range(presentations):
                labels = list(rng.choice(CALIB_LABELS, size=4, replace=False))
                _, r, _, _, _, _ = self.present(labels, seed=10_000 + i)
                rates.extend(r.tolist())
        finally:
            self.timeout_ms = keep
        self.thr_hz = float(np.mean(rates) + THR_Z * np.std(rates)) if thr is None else thr
        return {"pool_rate_mean_hz": round(float(np.mean(rates)), 2), "pool_rate_sd_hz": round(float(np.std(rates)), 2),
                "threshold_hz": round(self.thr_hz, 2)}


# --- the network that learns, and its frozen twin -------------------------------------------------------------------
def _save_npz_atomic(path, **arrays):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "wb") as f:
            np.savez(f, **arrays)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


class LiveBrain:
    def __init__(self, n_neurons=N_NEURONS, weights=None, regions=None, twin=True, log=print):
        self.cfg = Config(n_neurons=n_neurons)
        self.net = LiveNet(self.cfg, regions)
        self.ch = Chooser(self.net)
        self.tw = Chooser(self.net.twin()) if twin else None
        if self.tw is not None:
            self.tw.pidx, self.tw.pre, self.tw.post = self.ch.pidx, self.ch.pre, self.ch.post
        self.dw = np.zeros(len(self.ch.pidx), dtype=np.float32)
        self.n_learn, self.n_decisions = 0, 0
        self.path = Path(weights) if weights else None
        self.pending = {}
        self.log = log
        self.t_start = time.time()
        self.calib = None
        self.emit, self.phase, self.last_da = None, "idle", 0.0     # emit(frame): the page's raster (serve() sets it)
        self.da_t = time.time()                                       # when last_da was set (it decays on the page)
        self.net.enable_raster()
        self._record_all()
        self._frame_reset()
        self.load()
        if self.ch.thr_hz is None:
            dw, self.dw = self.dw, np.zeros_like(self.dw)
            self._apply()
            self.calib = self.ch.calibrate()                  # on the untrained network, as in #39
            self.dw = dw
            self._apply()
            self.save()
        if self.tw is not None:
            self.tw.thr_hz = self.ch.thr_hz

    # --- weights ---------------------------------------------------------------------------------------------------
    def _apply(self):
        w = np.clip(self.ch.w0 + self.dw, 0.0, self.ch.w_max)
        self.dw = (w - self.ch.w0).astype(np.float32)
        self.net.w[self.ch.pidx] = w

    def save(self):
        if self.path is None:
            return
        _save_npz_atomic(self.path, dw=self.dw, n_learn=self.n_learn, n_decisions=self.n_decisions,
                         thr_hz=np.nan if self.ch.thr_hz is None else self.ch.thr_hz,
                         config_hash=self.cfg.config_hash(), n_neurons=self.cfg.n_neurons, version=VERSION,
                         n_plastic=len(self.dw))

    def load(self):
        if self.path is None or not self.path.exists():
            return False
        try:
            with np.load(self.path) as z:
                if str(z["config_hash"]) != self.cfg.config_hash() or int(z["n_plastic"]) != len(self.dw):
                    self.log(f"spiking live: {self.path.name} is for another network, starting fresh")
                    return False
                self.dw = z["dw"].astype(np.float32)
                self.n_learn, self.n_decisions = int(z["n_learn"]), int(z["n_decisions"])
                thr = float(z["thr_hz"])
                self.ch.thr_hz = thr if math.isfinite(thr) else None
        except Exception as e:                                # torn or corrupt: keep it aside, start fresh
            aside = self.path.with_name(f"{self.path.name}.corrupt-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}")
            try:
                os.replace(self.path, aside)
            except OSError:
                pass
            self.log(f"spiking live: {self.path.name} unreadable ({type(e).__name__}), kept as {aside.name}; starting fresh")
            self.dw[:] = 0
            return False
        self._apply()
        return True

    def eta(self):
        return ETA * max(ETA_FLOOR, 1.0 / (1.0 + self.n_learn / ETA_HALF))

    # --- frames for the page (the GPU session's format, net "cpu") ---------------------------------------------------
    def _frame_reset(self):
        self.f_wall, self.f_t, self.f_count = time.time(), self.net.t, self.net.count.copy()
        self.net.raster.clear()

    def _hook(self, net):
        if self.emit is not None and time.time() - self.f_wall >= FRAME_S:
            self.flush()

    def flush(self):
        """Send one frame with everything since the last one (nothing if no simulated time passed). The page gets the
        compact form (spiking/frames.py): per-region rates, one byte each, and a sample of the recorded spikes."""
        net = self.net
        if self.emit is None or net.t <= self.f_t:
            self._frame_reset()
            return
        now = time.time()
        steps = net.t - self.f_t
        sim_s = steps * net.cfg.dt / 1000.0
        d = net.count - self.f_count
        rr = np.add.reduceat(d, net.off) / net.size / sim_s
        sz = net.size
        groups = {g: round(float((rr[ix] * sz[ix]).sum() / sz[ix].sum()), 2) for g, ix in net.reg.groups.items()
                  if ix and g in GROUP_KEYS}
        if net.raster:
            spikes = np.concatenate([np.stack([np.full(len(rows), t - self.f_t), rows.astype(np.int64)], 1)
                                     for t, rows in net.raster])
        else:
            spikes = np.zeros((0, 2), dtype=np.int64)
        n_sp = float(d.sum())
        frame = {"type": "spiking", "net": "cpu", "live": True, "phase": self.phase, "n_neurons": net.n,
                 "t_sim": round(net.t / 1000.0, 2), "spikes_per_s": round(n_sp / sim_s, 1),
                 "mean_rate_hz": round(n_sp / sim_s / net.n, 3), "realtime_x": round(sim_s / max(1e-6, now - self.f_wall), 3),
                 "groups": groups, "raster": {"n": len(net.raster_ids), "t0": int(self.f_t), "t1": int(net.t), "spikes": spikes},
                 "dopamine": round(self.dopamine_now(), 3)}
        frame = frames.viewer_frame(frame, self.sample, rates=rr, race=self.phase == "deciding")
        self._frame_reset()
        try:
            self.emit(frame)
        except Exception:
            pass

    def _record_all(self):
        """The frames record every neuron's spikes (row = neuron id; the page gets a sample of them, frames.py), so
        each dot of the 3D view is one model neuron. Only the recording: the network itself is unchanged."""
        net = self.net
        if net.n <= np.iinfo(np.int16).max:
            net.row_of = np.arange(net.n, dtype=np.int16)
            net.raster_ids, net.raster = np.arange(net.n), []
        self.sample = frames.Sample.from_ids(net.raster_ids, net.off, net.size)

    def idle(self, ms=IDLE_MS):
        """Background activity between decisions (no cue), shown on the page."""
        self.phase = "idle"
        self.net.drive()
        self.net.hook = self._hook
        try:
            self.net.run(ms)
        finally:
            self.net.hook = None
        self.flush()

    # --- the protocol ----------------------------------------------------------------------------------------------
    def decide(self, labels, did=None):
        t0 = time.process_time()
        labels = [str(x)[:120] for x in list(labels)[:MAX_OPTIONS]]
        if len(labels) < 2:
            raise ValueError("need 2-6 options")
        self.n_decisions += 1
        seed = self.n_decisions * 7919 + 17
        self.phase = "deciding"
        self.net.hook = self._hook
        try:
            pick, rates, ms, timeout, pre, post = self.ch.present(labels, seed)
        finally:
            self.net.hook = None
            self.flush()
            self.phase = "idle"
        out = {"pick": pick, "pool_rates": [round(float(r), 3) for r in rates], "sim_ms": float(ms),
               "timeout": bool(timeout), "n_neurons": self.net.n, "threshold_hz": round(self.ch.thr_hz, 3)}
        if self.tw is not None:
            tp, tr, _, _, _, _ = self.tw.present(labels, seed)
            out.update(twin_pick=tp, twin_rates=[round(float(r), 3) for r in tr])
        act = pre > 0
        self.pending[did if did is not None else self.n_decisions] = (np.flatnonzero(act), pre[act], post[act], len(labels),
                                                                      pick)
        while len(self.pending) > PENDING:
            self.pending.pop(next(iter(self.pending)))
        out["cpu_ms"] = round((time.process_time() - t0) * 1000, 1)
        return out

    def learn(self, did, followed, delta):
        """Dopamine for decision `did`: the tastes prediction error of the stay, tagged on the option that was followed
        (None: the network's own pick)."""
        tag = self.pending.pop(did, None)
        if tag is None:
            return {"ok": False, "why": "unknown or too old decision"}
        q, pre, post, k, own = tag
        try:
            delta, followed = float(delta), int(own if followed is None else followed)
        except (TypeError, ValueError):
            return {"ok": False, "why": "bad delta"}
        if not math.isfinite(delta) or not 0 <= followed < k:
            return {"ok": False, "why": "bad delta"}
        da = max(-1.0, min(1.0, DA_GAIN * delta))
        p = np.where(post == followed, 1.0, np.where(post >= 0, -1.0 / max(1, k - 1), 0.0)).astype(np.float32)
        eta = self.eta()
        self.dw[q] += np.float32(eta * da) * pre * p
        self.last_da, self.da_t = da, time.time()
        self._apply()
        self.n_learn += 1
        self.save()
        return {"ok": True, "eta": round(eta, 4), "da": round(da, 4), "n_learn": self.n_learn,
                "dw_abs_mean": round(float(np.abs(self.dw).mean()), 5)}

    def dopamine_now(self):
        """The phasic dopamine reading for the page: the last value, decaying with DA_SHOW_TAU_S."""
        return self.last_da * math.exp(-max(0.0, time.time() - self.da_t) / DA_SHOW_TAU_S)

    def burst(self, value):
        """#89: a new short / page on his screens: the simulated dopamine-like burst shows on the panel (no weight
        changes: only `learn` changes weights)."""
        try:
            v = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return
        if math.isfinite(v) and v > self.dopamine_now():
            self.last_da, self.da_t = v, time.time()

    def status(self):
        return {"n_neurons": self.net.n, "n_synapses": self.net.n_syn, "n_plastic": len(self.dw),
                "n_decisions": self.n_decisions, "n_learn": self.n_learn, "eta": round(self.eta(), 4),
                "threshold_hz": None if self.ch.thr_hz is None else round(self.ch.thr_hz, 3),
                "dw_abs_mean": round(float(np.abs(self.dw).mean()), 5), "calibration": self.calib,
                "cpu_s": round(time.process_time(), 2), "uptime_s": round(time.time() - self.t_start, 1),
                "build_s": round(self.net.build_s, 2), "twin": self.tw is not None}


def serve(brain, fd_in, out, idle_ms=IDLE_MS, idle_every=IDLE_EVERY_S):
    """Answer one JSON line per request until stdin closes; frames go out as they come; idle background runs when
    nothing arrives for `idle_every` seconds."""
    def send(obj):
        out.write(json.dumps(obj) + "\n")
        out.flush()
    brain.emit = send
    send({"type": "ready", **brain.status()})
    buf = b""
    while True:
        ready, _, _ = select.select([fd_in], [], [], idle_every if idle_ms > 0 else None)
        if not ready:
            brain.idle(idle_ms)
            continue
        chunk = os.read(fd_in, 1 << 16)
        if not chunk:
            return
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if line.strip() and handle(brain, line, send) == "stop":
                return


def handle(brain, line, send):
    msg = {}
    try:
        msg = json.loads(line)
        kind, rid = msg.get("type"), msg.get("id")
        if kind == "decide":
            send({"type": "decision", "id": rid, **brain.decide(msg.get("options") or [], did=rid)})
        elif kind == "reward":
            send({"type": "rewarded", "id": rid, **brain.learn(rid, msg.get("followed"), msg.get("value"))})
        elif kind == "burst":                             # fire and forget: no answer
            brain.burst(msg.get("value"))
        elif kind == "status":
            send({"type": "status", "id": rid, **brain.status()})
        elif kind == "stop":
            send({"type": "stopped", "id": rid})
            return "stop"
        else:
            send({"type": "error", "id": rid, "error": "unknown type"})
    except Exception as e:                                # one bad request never kills the network
        send({"type": "error", "id": msg.get("id") if isinstance(msg, dict) else None,
              "error": f"{type(e).__name__}: {str(e)[:120]}"})

def synthetic(brain, trials=100, seed=0, follow=0.7, vocab=None, probs=None, alpha=0.1, kmin=2, kmax=6):
    """A synthetic reward stream for checks (tests, docs/spiking/live_cpu.md): `vocab` labels with hidden reward
    probabilities; each decision offers a random 2-6 of them; the option followed is the network's pick with
    probability `follow` (else a random offered one, standing in for the rate model); reward ~ Bernoulli(p); dopamine
    = r - V[label], V += alpha (r - V) (a slow value estimate, like the tastes' prediction). Scored: the network's
    pick == the best offered option, for the learning network and its frozen twin on the same offers and noise."""
    vocab = list(vocab or ["read about bread", "tokyo parks", "train timetable", "cat videos", "jazz records", "old maps"])
    probs = np.asarray(probs if probs is not None else [0.8, 0.2, 0.3, 0.4, 0.2, 0.3], dtype=float)
    rng = np.random.default_rng(seed)
    V = {lb: 0.5 for lb in vocab}
    rows = []
    for t in range(trials):
        k = int(rng.integers(kmin, kmax + 1))
        off = [int(i) for i in rng.choice(len(vocab), size=k, replace=False)]
        labels = [vocab[i] for i in off]
        d = brain.decide(labels, did=("synthetic", t))
        fol = d["pick"] if rng.random() < follow else int(rng.integers(k))
        r = float(rng.random() < probs[off[fol]])
        delta = r - V[labels[fol]]
        V[labels[fol]] += alpha * delta
        brain.learn(("synthetic", t), fol, delta / DA_GAIN)    # da = r - V, in choice.py's units
        best = int(np.argmax(probs[off]))
        rows.append((int(d["pick"] == best), int(d.get("twin_pick") == best), 1.0 / k))
    a = np.array(rows, dtype=float)
    blk = lambda col: [round(float(a[i:i + 25, col].mean()), 3) for i in range(0, trials, 25)]
    return {"trials": trials, "seed": seed, "learned": round(float(a[:, 0].mean()), 3), "twin": round(float(a[:, 1].mean()), 3),
            "chance": round(float(a[:, 2].mean()), 3), "learned_last50": round(float(a[-50:, 0].mean()), 3),
            "twin_last50": round(float(a[-50:, 1].mean()), 3), "curve": blk(0), "twin_curve": blk(1)}


# --- the server side: the child process, the day's decisions log, the card ------------------------------------------
CARD = ("A small simulated spiking network ({n} neurons) built on the same wiring takes part in his choices and learns "
        "from simulated reward.")
NOTE = ("Its lean is one small term in the vote (weight {w}); the rate model stays the main decider. \"Paid off\" = the "
        "stay on the chosen page raised his brain model's reward/attention activity above its recent average. Its lean "
        "also nudges which option is followed, so a match is a little more likely for it than for the frozen twin even "
        "without learning; the not-paid-off numbers show how much.")


def _today(t=None):
    from datetime import datetime
    from sleep import TZ
    return datetime.fromtimestamp(time.time() if t is None else t, TZ).date().isoformat()


class DecisionLog:
    """The day's decisions, one file per Tokyo day: /data/spiking/decisions-YYYY-MM-DD.jsonl (append-only, state_io).
    Read at night by the GPU session (#58).
        decision row: {"t", "id", "kind": "browse|chess|plan", "options": [label, ...], "pick": int (the option
                       followed), "net": "gpu|cpu|rate", "reward": null, + "net_pick" (the network's own pick),
                       "twin_pick" (cpu: its frozen twin's pick)}
        reward row (later, same file as its decision): {"t", "id", "reward": float (the tastes prediction error, the
                       dopamine), + "response" (the stay's tastes response, -1..1; > 0 = it paid off)}"""

    def __init__(self, data_dir):
        self.dir = Path(data_dir) / "spiking"

    def path(self, day):
        return self.dir / f"decisions-{day}.jsonl"

    def _append(self, day, row):
        from state_io import append_jsonl
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            append_jsonl(self.path(day), row)
        except OSError as e:
            print("spiking: could not log a decision:", repr(e)[:120], flush=True)

    def decision(self, did, kind, options, pick, net, t=None, **extra):
        t = time.time() if t is None else t
        self._append(_today(t), {"t": round(t, 3), "id": str(did), "kind": kind, "options": [str(o) for o in options],
                                 "pick": int(pick), "net": net, "reward": None, **extra})

    def reward(self, did, value, t_decision, t=None, **extra):
        t = time.time() if t is None else t
        self._append(_today(t_decision), {"t": round(t, 3), "id": str(did), "reward": round(float(value), 4), **extra})

    def joined(self, days=7, now=None):
        """Decision rows of the last `days` Tokyo days with their reward ("reward") and "response" filled in."""
        from datetime import date, timedelta
        from state_io import read_jsonl
        today = date.fromisoformat(_today(now))
        out, by_id = [], {}
        for k in range(days - 1, -1, -1):
            for r in read_jsonl(self.path((today - timedelta(days=k)).isoformat())):
                if not isinstance(r, dict) or "id" not in r:
                    continue
                if "options" in r:
                    row = dict(r, day=(today - timedelta(days=k)).isoformat())
                    by_id[r["id"]] = row
                    out.append(row)
                elif r["id"] in by_id and r.get("reward") is not None:
                    by_id[r["id"]].update(reward=r["reward"], response=r.get("response"))
        return out


def score(rows, block=10, net="cpu"):
    """Learning curve of the CPU network from logged decisions with an outcome: among the decisions whose followed
    option paid off (response > 0), how often its own pick was that option (learned, frozen twin, chance = mean 1/K),
    in blocks of `block`; and the same on the decisions that did not pay off."""
    rows = [r for r in rows if isinstance(r, dict) and r.get("net") == net and r.get("response") is not None
            and r.get("options")]
    paid = [r for r in rows if r["response"] > 0]
    unpaid = [r for r in rows if r["response"] <= 0]
    m = lambda rs, key: round(float(np.mean([r.get(key) == r["pick"] for r in rs])), 3) if rs else None
    chance = lambda rs: round(float(np.mean([1.0 / len(r["options"]) for r in rs])), 3) if rs else None
    curve = [{"n": len(paid[i:i + block]), "learned": m(paid[i:i + block], "net_pick"),
              "twin": m(paid[i:i + block], "twin_pick"), "chance": chance(paid[i:i + block])}
             for i in range(0, len(paid), block)]
    return {"decisions_with_outcome": len(rows), "paid_off": len(paid),
            "matched_paid_off": {"learned": m(paid, "net_pick"), "twin": m(paid, "twin_pick"), "chance": chance(paid)},
            "matched_not_paid_off": {"learned": m(unpaid, "net_pick"), "twin": m(unpaid, "twin_pick"),
                                     "chance": chance(unpaid)},
            "curve": curve, "block": block}


class LiveClient:
    """The server's handle on the child process (asyncio). decide() never waits more than its timeout (2 s)."""

    def __init__(self, data_dir, n_neurons=N_NEURONS, timeout=None, python=sys.executable, twin=True):
        self.data_dir = Path(data_dir)
        # SUB01_SPIKING_LIVE_TIMEOUT_S: a bigger network needs longer (500k neurons: ~2 s a decision on a laptop core)
        if timeout is None:
            timeout = float(os.environ.get("SUB01_SPIKING_LIVE_TIMEOUT_S") or 2.0)
        self.n_neurons, self.timeout, self.python, self.twin = n_neurons, timeout, python, twin
        self.proc, self.ready, self.info = None, False, {}
        self.futs, self.next_id = {}, 0
        self.slow, self.restarts, self.errors = 0, 0, 0
        self.cpu = {}
        self.on_frame = None                 # async callable(frame): the server broadcasts it to the pages
        self.last_frame = 0.0
        self._reader_task = None
        self._stopping = False

    # --- the child process ---------------------------------------------------------------------------------------
    async def start(self):
        import asyncio
        env = {k: v for k, v in os.environ.items()
               if k in ("PATH", "HOME", "LANG", "TZ", "SUB01_TZ", "PYTHONPATH", "SUB01_SPIKING_LIVE_IDLE_MS")}
        env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", PYTHONUNBUFFERED="1")
        args = [self.python, "-m", "spiking.live", "--data-dir", str(self.data_dir), "--neurons", str(self.n_neurons)]
        if not self.twin:
            args.append("--no-twin")
        self.ready = False
        self.proc = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE,
                                                         stdout=asyncio.subprocess.PIPE, env=env, cwd=str(HERE),
                                                         limit=1 << 20)
        self._reader_task = asyncio.get_running_loop().create_task(self._read(self.proc))

    def alive(self):
        return self.proc is not None and self.proc.returncode is None

    async def _read(self, proc):
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                kind = msg.get("type")
                if kind == "ready":
                    self.info, self.ready = msg, True
                    print(f"spiking live: ready, {msg.get('n_neurons')} neurons, {msg.get('n_learn')} learned decisions",
                          flush=True)
                elif kind == "spiking":
                    self.last_frame = time.time()
                    if self.on_frame is not None:
                        try:
                            await self.on_frame(msg)
                        except Exception as e:                # the page feed must never stop the reader
                            print("spiking live: frame not sent:", repr(e)[:120], flush=True)
                elif kind in ("decision", "status", "error"):
                    fut = self.futs.pop(msg.get("id"), None)
                    if fut is not None and not fut.done():
                        fut.set_result(msg)               # an answer after its timeout finds no future: dropped
                elif kind == "rewarded" and msg.get("ok"):
                    self.info["n_learn"] = msg.get("n_learn")
        finally:
            self.ready = False
            for f in self.futs.values():
                if not f.done():
                    f.set_result(None)
            self.futs.clear()

    def send(self, msg):
        if not self.alive():
            return False
        try:
            self.proc.stdin.write((json.dumps(msg) + "\n").encode())
            return True
        except (BrokenPipeError, ConnectionResetError, RuntimeError):
            return False

    async def call(self, msg_type, rid=None, timeout=None, **kw):
        import asyncio
        if not self.ready:
            return None
        if rid is None:
            self.next_id += 1
            rid = f"{msg_type[0]}-{self.next_id}"
        fut = asyncio.get_running_loop().create_future()
        self.futs[rid] = fut
        if not self.send({"type": msg_type, "id": rid, **kw}):
            self.futs.pop(rid, None)
            return None
        try:
            return await asyncio.wait_for(fut, self.timeout if timeout is None else timeout)
        except asyncio.TimeoutError:
            self.futs.pop(rid, None)
            return None

    async def run(self, every=60.0):
        """Keep the child running (restart with a backoff) and sample its CPU use."""
        import asyncio
        backoff = 5.0
        while not self._stopping:
            if not self.alive():
                if self.proc is not None:
                    self.restarts += 1
                    print(f"spiking live: process exited ({self.proc.returncode}); restarting in {backoff:.0f} s", flush=True)
                    await asyncio.sleep(backoff)
                    backoff = min(600.0, backoff * 2)
                try:
                    await self.start()
                except OSError as e:
                    print("spiking live: could not start:", repr(e)[:120], flush=True)
            await asyncio.sleep(every)
            st = await self.call("status", timeout=10.0)
            if st and "cpu_s" in st:
                prev, now = self.cpu.get("_sample"), (time.time(), st["cpu_s"])
                self.cpu = {"_sample": now, "cpu_s": st["cpu_s"], "uptime_s": st.get("uptime_s"),
                            "avg_pct": round(100 * st["cpu_s"] / max(1.0, st.get("uptime_s") or 1.0), 2)}
                if prev:
                    self.cpu["recent_pct"] = round(100 * (now[1] - prev[1]) / max(1.0, now[0] - prev[0]), 2)
                self.info.update({k: st[k] for k in ("n_decisions", "n_learn", "eta", "dw_abs_mean") if k in st})
                backoff = 5.0

    async def stop(self):
        import asyncio
        self._stopping = True
        if self.alive():
            self.send({"type": "stop"})
            try:
                self.proc.stdin.close()
                await asyncio.wait_for(self.proc.wait(), 5)
            except (asyncio.TimeoutError, OSError):
                self.proc.kill()
                await self.proc.wait()

    # --- the protocol --------------------------------------------------------------------------------------------
    async def decide(self, options, kind="browse", did=None, timeout=None):
        """The network's decision for these option labels, or {"why": ...} when it is down, too slow or wrong."""
        options = [str(x) for x in options][:MAX_OPTIONS]
        if len(options) < 2:
            return {"why": "fewer than 2 options"}
        if not self.ready:
            return {"why": "spiking network offline"}
        t0 = time.perf_counter()
        timeout = self.timeout if timeout is None else timeout
        ans = await self.call("decide", rid=did, timeout=timeout, options=options, kind=kind,
                              deadline_ms=int(timeout * 1000))
        if ans is None:
            self.slow += 1
            return {"why": f"spiking network slower than {timeout:g} s"}
        if ans.get("type") != "decision" or len(ans.get("pool_rates") or []) != len(options):
            self.errors += 1
            return {"why": "spiking network error"}
        ans["wall_ms"] = round((time.perf_counter() - t0) * 1000)
        return ans

    def reward(self, did, value, followed=None):
        """Dopamine for decision `did` (fire and forget; the child acknowledges with a "rewarded" line)."""
        msg = {"type": "reward", "id": str(did), "value": float(value)}
        if followed is not None:
            msg["followed"] = int(followed)
        return self.send(msg)

    def burst(self, value):
        """#89: a dopamine-like burst from his screens, shown on the neurons panel (fire and forget)."""
        return self.send({"type": "burst", "value": round(float(value), 4)})

    def state(self):
        return "live" if self.ready else ("starting" if self.alive() else "offline")


def view(backend):
    """GET /api/spiking/live: the "In the day" part of the Neurons card."""
    cpu = getattr(backend, "cpu", None) if backend else None
    log = getattr(backend, "log", None) if backend else None
    if cpu is None and log is None:
        return {"state": "off"}
    rows = log.joined(7) if log else []
    today = _today()
    td = [r for r in rows if r.get("day") == today]
    n = (cpu.info.get("n_neurons") if cpu else None) or (cpu.n_neurons if cpu else N_NEURONS)
    w = float(os.environ.get("SUB01_SPIKING_W", 0.3))
    by_net = {k: sum(1 for r in td if r.get("net") == k) for k in ("gpu", "cpu", "rate")}
    return {"state": cpu.state() if cpu else "off", "n_neurons": n, "card": CARD.format(n=f"{n:,}"), "note": NOTE.format(w=w),
            "weight": w, "decisions_today": len(td), "by_net_today": by_net,
            "learned_today": sum(1 for r in td if r.get("net") == "cpu" and r.get("reward") is not None),
            "n_decisions": cpu.info.get("n_decisions") if cpu else None, "n_learn": cpu.info.get("n_learn") if cpu else None,
            "last": getattr(backend, "last", None), "score": score(rows), "today": score(td),
            "cpu": {k: v for k, v in (cpu.cpu if cpu else {}).items() if not k.startswith("_")},
            "slow": cpu.slow if cpu else None, "restarts": cpu.restarts if cpu else None,
            "timeout_s": cpu.timeout if cpu else None}


def attach(app, backend):
    """GET /api/spiking/live (behind the site's password gate like every /api/ path)."""
    from aiohttp import web

    async def get(request):
        return web.json_response(view(backend))
    app.router.add_get("/api/spiking/live", get)

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--neurons", type=int, default=N_NEURONS)
    ap.add_argument("--no-twin", action="store_true")
    a = ap.parse_args(argv)
    proto = sys.stdout
    sys.stdout = sys.stderr                                   # only protocol lines go to the parent's pipe
    log = lambda *x: print(*x, file=sys.stderr, flush=True)
    brain = LiveBrain(a.neurons, Path(a.data_dir) / "spiking" / "live_weights.npz", twin=not a.no_twin, log=log)
    log(f"spiking live: {brain.net.n:,} neurons, {brain.net.n_syn:,} synapses, {len(brain.dw):,} plastic, "
        f"threshold {brain.ch.thr_hz:.2f} Hz, built in {brain.net.build_s:.1f} s")
    serve(brain, sys.stdin.fileno(), proto)


if __name__ == "__main__":
    main()
