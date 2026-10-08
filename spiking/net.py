"""Multiscale spiking network inside the real wiring of one brain (PyTorch, any device, event-driven).

- One population per atlas region (214: Schaefer-200 cortex + 14 deep nuclei), size proportional to the region's
  volume in the subject's own T1 labels; 80 % excitatory / 20 % inhibitory leaky integrate-and-fire neurons.
- Every neuron receives a fixed number of synapses (fixed in-degree): k_e_local excitatory and k_i_local
  inhibitory from its own region, and k_long excitatory from other regions, the source region drawn with
  probability proportional to the streamline count of the real connectome. Conduction delay of a long-range
  synapse = mean fibre length / 6 m/s; delays are realised with a ring buffer of future inputs.
- Background drive: a constant mean (mu) + white noise, modulated per region by the person's recorded
  resting-state activity (real_baseline), refreshed every 50 ms.
- Inhibition-dominated, noise-driven asynchronous regime: K_E - g K_I = 75 - 5*25 < 0, so recurrent input is net
  inhibitory (about -0.5 mV per Hz of population rate) and damps fluctuations; with only 100 synapses per neuron
  this is not a large-K Brunel balanced state - the rate (~3-5 Hz) is set mainly by the external drive
  (mu = 15 mV, sigma = 4 mV; a Siegert mean-field estimate gives ~5.7 Hz with recurrence, ~5.9 Hz without).

The synapse set is generated with numpy from the seed (identical on CPU and GPU), sorted by source neuron
(CSR); a spike reads only its own outgoing row (event-driven, like gpu/bench_lif.py).
"""
import time

import numpy as np
import torch

from .config import Config
from .regions import Regions
from .wiring import Layout, allocate, synapse_lists  # noqa: F401  (allocate: kept importable from here)


class SpikingNet(Layout):
    def __init__(self, cfg=None, device="cpu", regions=None, verbose=False):
        self.cfg = cfg = cfg or Config()
        self.device = torch.device(device)
        self.reg = regions or Regions()
        self.verbose = verbose
        t0 = time.time()
        self._layout()
        self._build_synapses()
        self.build_s = time.time() - t0
        self._state()
        self.plast = None
        if cfg.plastic:
            from .plasticity import Plasticity
            self.plast = Plasticity(self)
        self._log(f"built {self.n:,} neurons, {self.n_syn:,} synapses, max delay {self.D - 1} ms "
                  f"in {time.time() - t0:.1f} s on {self.device}")

    def _log(self, *a):
        if self.verbose:
            print(*a, flush=True)

    # --- synapses -------------------------------------------------------------------------------------------
    def _build_synapses(self):
        src_l, dst_l, w_l, d_l, kind_l, delay_long = synapse_lists(self)   # numpy, from the seed (wiring.py)
        dev = self.device
        src = torch.from_numpy(np.concatenate(src_l).astype(np.int32)).to(dev)
        del src_l
        order = torch.sort(src, stable=True).indices          # CSR by source (stable -> same order on any device)
        self.src = src[order]
        del src
        cat = lambda lst, dt: torch.from_numpy(np.concatenate(lst).astype(dt)).to(dev)[order]
        self.dst = cat(dst_l, np.int32); del dst_l
        self.w = cat(w_l, np.float32); del w_l
        self.delay = cat(d_l, np.uint8); del d_l
        self.kind = cat(kind_l, np.uint8); del kind_l, order
        self.n_syn = int(self.src.numel())
        self.D = int(self.delay.max().item()) + 1
        deg = torch.bincount(self.src.long(), minlength=self.n)
        self.rowptr = torch.zeros(self.n + 1, dtype=torch.int64, device=dev)
        self.rowptr[1:] = torch.cumsum(deg, 0)
        self.delay_long_ms = delay_long

    # --- dynamic state --------------------------------------------------------------------------------------
    def _state(self):
        c, dev, n = self.cfg, self.device, self.n
        self.gen = torch.Generator(device=dev)
        self.gen.manual_seed(c.seed + 1000)
        g = torch.Generator().manual_seed(c.seed + 2000)
        self.v = (torch.rand(n, generator=g) * (c.v_th - c.v_reset) + c.v_reset).to(dev)
        self.ref = torch.zeros(n, dtype=torch.int16, device=dev)
        self.buf = torch.zeros(self.D, n, device=dev)
        self.buf_flat = self.buf.view(-1)
        self.region_of = torch.from_numpy(self.region_of_np).to(dev)
        self.is_exc = torch.from_numpy(self.is_exc_np).to(dev)
        self.count = torch.zeros(n, device=dev)                   # spikes per neuron since start
        self.region_count = torch.zeros(self.reg.n, dtype=torch.float64, device=dev)  # float64: no 2^24 stall
        self.t = 0                                                 # steps
        self.n_spikes = 0
        self.a = c.dt / c.tau_m
        self.n_ref = int(round(c.t_ref / c.dt))
        self.noise_gain = 1.0
        self.z = np.zeros(self.reg.n)                              # recorded resting-state drive (z per region)
        self.baseline_gain = c.baseline_gain
        self.mu_offset = 0.0                                       # global offset (sleep slow oscillation)
        self.region_drive = {}                                     # name -> (R,) mV
        self.neuron_drive = {}                                     # name -> (idx tensor, amp)
        self.theta = torch.zeros(n, device=dev)                    # homeostatic excitability offset (mV)
        self._dirty = True
        self.baseline = None
        self.raster_rows = None
        self.last_spikes = torch.zeros(0, dtype=torch.int64, device=dev)
        self.hook, self.hook_every = None, 50                    # hook(net) every 50 steps (streaming, deadlines)

    # --- inputs ---------------------------------------------------------------------------------------------
    def set_region_drive(self, name, vec):
        """Named additive drive per region (mV on mu), e.g. Pong's visual encoding or a chat stimulus."""
        if vec is None:
            self.region_drive.pop(name, None)
        else:
            self.region_drive[name] = np.asarray(vec, dtype=np.float64)
        self._dirty = True

    def set_neuron_drive(self, name, idx=None, amp=0.0):
        """Named additive drive on a set of neurons (memory patterns). idx=None removes it."""
        if idx is None or amp == 0:
            self.neuron_drive.pop(name, None)
        else:
            self.neuron_drive[name] = (torch.as_tensor(np.asarray(idx), dtype=torch.int64, device=self.device),
                                       float(amp))
        self._dirty = True

    def clear_drives(self):
        self.region_drive.clear()
        self.neuron_drive.clear()
        self._dirty = True

    def attach_baseline(self, baseline):
        """real_baseline.RealBaseline built with self.reg.names: the recorded activity of the person at rest."""
        self.baseline = baseline
        self.z = np.clip(baseline.advance(0.0), -2.0, 3.0)
        self._dirty = True

    def _rebuild_mu(self):
        c = self.cfg
        mu_r = c.mu_ext * (1.0 + self.baseline_gain * self.z) + self.mu_offset
        for v in self.region_drive.values():
            mu_r = mu_r + v
        mu_r = torch.as_tensor(mu_r, dtype=torch.float32, device=self.device)
        mu = mu_r[self.region_of] - self.theta
        for idx, amp in self.neuron_drive.values():
            mu.index_add_(0, idx, torch.full((idx.numel(),), amp, device=self.device))
        self.mu = mu
        self._dirty = False

    # --- simulation -----------------------------------------------------------------------------------------
    def step(self):
        c = self.cfg
        if self.baseline is not None and self.t % c.baseline_dt_ms == 0:
            self.z = np.clip(self.baseline.advance(c.baseline_dt_ms * c.dt / 1000.0), -2.0, 3.0)
            self._dirty = True
        if self._dirty:
            self._rebuild_mu()
        slot = self.t % self.D
        inp = self.buf[slot]
        v = self.v
        v.mul_(1.0 - self.a).add_(self.mu, alpha=self.a)
        v.add_(torch.randn(self.n, device=self.device, generator=self.gen),
               alpha=c.sigma_ext * self.noise_gain * float(np.sqrt(self.a)))
        v.add_(inp)
        inp.zero_()
        refr = self.ref > 0
        v.masked_fill_(refr, c.v_reset)
        self.ref.sub_(refr.to(torch.int16))
        spk = torch.nonzero(v >= c.v_th).squeeze(1)
        ns = spk.numel()
        if ns:
            v[spk] = c.v_reset
            self.ref[spk] = self.n_ref
            self.count.index_add_(0, spk, torch.ones(ns, device=self.device))
            self.region_count.index_add_(0, self.region_of[spk], torch.ones(ns, dtype=torch.float64, device=self.device))
            start = self.rowptr[spk]
            cnt = self.rowptr[spk + 1] - start
            csum = torch.cumsum(cnt, 0)
            tot = int(csum[-1])
            if tot:
                syn = torch.repeat_interleave(start - (csum - cnt), cnt, output_size=tot) + \
                    torch.arange(tot, device=self.device)
                tgt = ((self.t + self.delay[syn].long()) % self.D) * self.n + self.dst[syn].long()
                self.buf_flat.index_add_(0, tgt, self.w[syn])
            if self.raster_rows is not None:
                rows = self.raster_rows[spk]
                rows = rows[rows >= 0]
                if rows.numel():
                    self.raster_log.append((self.t, rows))
        self.last_spikes = spk
        self.n_spikes += ns
        if self.plast is not None:
            self.plast.step(spk)
        self.t += 1
        if self.hook is not None and self.t % self.hook_every == 0:
            self.hook(self)
        return ns

    def run(self, ms, callback=None, every=None):
        """Run `ms` milliseconds; optional callback(net) every `every` steps."""
        steps = int(round(ms / self.cfg.dt))
        for i in range(steps):
            self.step()
            if callback is not None and every and (i + 1) % every == 0:
                callback(self)

    # --- read-out -------------------------------------------------------------------------------------------
    def sync(self):
        if self.device.type == "cuda":
            torch.cuda.synchronize()

    def snapshot(self):
        """Counters to measure rates over a window: (t, per-neuron counts copy, per-region counts copy)."""
        return self.t, self.count.clone(), self.region_count.clone()

    def rates_since(self, snap, idx=None):
        """Mean rate (Hz) of neurons `idx` (or per neuron) since `snap`."""
        t0, c0, _ = snap
        dur = max(1, self.t - t0) * self.cfg.dt / 1000.0
        d = self.count - c0
        if idx is None:
            return d / dur
        idx = torch.as_tensor(np.asarray(idx), dtype=torch.int64, device=self.device)
        return d[idx] / dur

    def region_rates_since(self, snap):
        t0, _, r0 = snap
        dur = max(1, self.t - t0) * self.cfg.dt / 1000.0
        size = torch.as_tensor(self.size, dtype=torch.float64, device=self.device)
        return ((self.region_count - r0) / size / dur).cpu().numpy()

    def group_rates(self, region_rates):
        sz = self.size
        return {g: float((region_rates[ix] * sz[ix]).sum() / sz[ix].sum()) for g, ix in self.reg.groups.items() if ix}

    def enable_raster(self, n_rows=200, seed=0):
        """Record spikes of a fixed sample of neurons for the page: one per region where possible, rest uniform."""
        rng = np.random.default_rng(seed)
        per = [int(self.off[r] + rng.integers(self.size[r])) for r in range(self.reg.n)][:n_rows]
        rest = np.setdiff1d(np.arange(self.n), per)
        ids = np.sort(np.concatenate([per, rng.choice(rest, size=max(0, min(n_rows, self.n) - len(per)),
                                                      replace=False)]).astype(np.int64))
        rows = torch.full((self.n,), -1, dtype=torch.int16, device=self.device)
        rows[torch.as_tensor(ids, device=self.device)] = torch.arange(len(ids), dtype=torch.int16, device=self.device)
        self.raster_rows, self.raster_ids, self.raster_log = rows, ids, []

    def pop_raster(self, since_t):
        """Spikes of the raster sample from step since_t on: [[t_ms_rel, row], ...]."""
        out = []
        keep = []
        for t, rows in self.raster_log:
            if t >= since_t:
                out.extend([[int(t - since_t), int(r)] for r in rows.tolist()])
        self.raster_log = keep
        return out

    def memory_gb(self):
        if self.device.type == "cuda":
            return torch.cuda.max_memory_allocated() / 1e9
        return None
