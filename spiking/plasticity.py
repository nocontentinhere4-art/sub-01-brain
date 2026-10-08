"""Plasticity on excitatory -> excitatory synapses, homeostasis and the learned-weight file.

Two rules write into the same learned component dw of each plastic synapse i -> j (both excitatory):

1. Three-factor STDP x dopamine (task learning, Pong):
    pre trace   x_i: decays with tau+, +1 per spike of i;   post trace y_j: decays with tau-, +1 per spike of j
    eligibility e_ij (decays with tau_e = 1 s, bridging the delay to the reward):
        on a spike of j:  e += A+ * (x_i - x_theta)           (pre before post -> potentiation if x_i > x_theta;
                                                               a post spike slightly depresses inputs from silent i)
        on a spike of i:  e -= A- * y_j + h                   (post before pre -> depression; h = heterosynaptic)
    d(dw)/dt = eta_c^DA * DA(t) * (e - <e>_c)                 (DA: phasic dopamine, decays with tau_DA = 200 ms;
                                                               only synapses onto somatomotor neurons, config.da_groups)
   For Poisson firing the expected drift of e is r_j A+ (r_i tau+ - x_theta) - r_i (A- tau- r_j + h): with
   A+ = 1, A- = 0.5, tau = 20 ms, x_theta = 0.1, h = 0.1 it is +8/s for a pair firing together at 40 Hz and
   ~0 or negative for 40 -> 13 Hz, 13 -> 40 Hz and background pairs. The update uses e relative to its class mean
   <e>_c (zero-sum: a reward does not uniformly grow or shrink all synapses).

2. Fast Hebbian rate rule (memory encoding and REM consolidation), applied once per presentation window T:
    dw += eta_c^M * [dr_i - theta]_+ * (dr_j - theta) * T,   dr = rate in the window - the neuron's 10 s running rate,
   theta = 15 Hz for encoding (about 3 sd of the Poisson noise of a 500 ms window), 6 Hz for replay (~2 sd)
   (the depressing branch, dr_j < theta, is scaled by 0.25). Zero unless the presynaptic neuron is well above
   its own running rate (background pairs cross the threshold only by rare noise excursions); potentiates
   co-active pairs, weakly depresses synapses from active onto inactive neurons (interference with older
   assemblies). M = ENC (awake encoding, hippocampal rate ~50x cortical) or CONS (REM replay, cortical only).
   Applied after the window, so a growing assembly cannot run away while it is being driven.

Weights: w = clamp(w0 + dw, 0, w_max); w0 = the connectome-derived weight, never changed. Class c = "hc" if the
postsynaptic neuron is hippocampal, else "ctx". Homeostasis (every second): intrinsic excitability offset
theta_j += eta_theta (r_j - r*) (bounded), and multiplicative synaptic scaling of the plastic weight,
w0 + dw <- (w0 + dw) (1 - eta_s (r_j - r*) / r*) (stored as a change of dw; w0 itself is never modified).
Conduction delays are ignored in the STDP timing (traces use emission times).
"""
import json
import math
import time

import numpy as np
import torch

MODS = ("da",)


def _segments(ptr, ids, device):
    """Concatenate index ranges [ptr[i], ptr[i+1]) for i in ids (event-driven gather)."""
    start = ptr[ids]
    cnt = ptr[ids + 1] - start
    csum = torch.cumsum(cnt, 0)
    tot = int(csum[-1]) if csum.numel() else 0
    if not tot:
        return None
    return torch.repeat_interleave(start - (csum - cnt), cnt, output_size=tot) + torch.arange(tot, device=device)


def _segments2(ptr_a, ptr_b, ids, device):
    """_segments for two pointer arrays with one host sync instead of two."""
    sa, sb = ptr_a[ids], ptr_b[ids]
    ca, cb = ptr_a[ids + 1] - sa, ptr_b[ids + 1] - sb
    csa, csb = torch.cumsum(ca, 0), torch.cumsum(cb, 0)
    ta, tb = torch.stack((csa[-1], csb[-1])).tolist()
    qa = torch.repeat_interleave(sa - (csa - ca), ca, output_size=ta) + torch.arange(ta, device=device) if ta else None
    qb = torch.repeat_interleave(sb - (csb - cb), cb, output_size=tb) + torch.arange(tb, device=device) if tb else None
    return qa, qb


class Plasticity:
    def __init__(self, net):
        self.net = net
        c, dev, n = net.cfg, net.device, net.n
        self.cfg, self.dev = c, dev
        exc = net.is_exc
        mask = exc[net.src.long()] & exc[net.dst.long()]
        self.pidx = torch.nonzero(mask).squeeze(1)               # global synapse ids (ascending = CSR by pre)
        del mask
        self.P = int(self.pidx.numel())
        self.psrc = net.src[self.pidx]
        self.pdst = net.dst[self.pidx]
        self.prow = torch.zeros(n + 1, dtype=torch.int64, device=dev)
        self.prow[1:] = torch.cumsum(torch.bincount(self.psrc.long(), minlength=n), 0)
        self.pcol = torch.sort(self.pdst, stable=True).indices   # plastic positions sorted by post (CSC)
        self.pcol_ptr = torch.zeros(n + 1, dtype=torch.int64, device=dev)
        self.pcol_ptr[1:] = torch.cumsum(torch.bincount(self.pdst.long(), minlength=n), 0)
        hc = torch.zeros(net.reg.n, dtype=torch.bool, device=dev)
        hc[list(net.hc_regions)] = True
        self.cls = hc[net.region_of[self.pdst.long()]].to(torch.uint8)   # 1 = hippocampal post
        self.cls_long = self.cls.long()
        da = torch.zeros(net.reg.n, dtype=torch.bool, device=dev)
        for g in c.da_groups:
            da[net.reg.groups[g]] = True
        self.da_mask = da[net.region_of[self.pdst.long()]].float()      # where dopamine can change weights
        self.w0 = net.w[self.pidx].clone()
        self._wmax_t = None
        self.dw = torch.zeros(self.P, device=dev)
        self.elig = torch.zeros(self.P, device=dev)
        self.x = torch.zeros(n, device=dev)
        self.y = torch.zeros(n, device=dev)
        self.dp = math.exp(-c.dt / c.tau_plus)
        self.dm = math.exp(-c.dt / c.tau_minus)
        self.h = c.h_pre
        self.n_cls = [int((self.cls == k).sum()) for k in (0, 1)]
        self.mod = {m: 0.0 for m in MODS}
        self.frozen = False
        self.stdp = True               # eligibility bookkeeping; off in phases where no dopamine can arrive
        self.rate = torch.full((n,), c.rate_target, device=dev)
        self.last_homeo = None
        self.updates = 0
        self.meta = {"sessions": 0, "history": []}

    # --- modulators -----------------------------------------------------------------------------------------
    def dopamine(self, amount):
        """Phasic dopamine burst (decays with tau_da)."""
        self.mod["da"] += amount

    def set_mod(self, name, value):
        self.mod[name] = float(value)

    def _m_class(self):
        e = self.cfg.eta
        return [sum(e[c][m] * self.mod[m] for m in MODS) for c in ("ctx", "hc")]

    # --- per step ----------------------------------------------------------------------------------------------
    def step(self, spk):
        if self.frozen:
            return
        c = self.cfg
        t = self.net.t + 1
        if self.stdp:
            if spk.numel():
                pre = spk[self.net.is_exc[spk]]
                if pre.numel():
                    q_pre, q_post = _segments2(self.prow, self.pcol_ptr, pre, self.dev)
                    if q_pre is not None:                       # depression on presynaptic spikes
                        self.elig.index_add_(0, q_pre, -(c.a_minus * self.y[self.pdst[q_pre].long()] + self.h))
                    if q_post is not None:                      # potentiation on postsynaptic spikes
                        q = self.pcol[q_post]
                        self.elig.index_add_(0, q, c.a_plus * (self.x[self.psrc[q].long()] - c.x_theta))
            self.x.mul_(self.dp)
            self.y.mul_(self.dm)
            if spk.numel():
                self.x[spk] += 1.0
                self.y[spk] += 1.0
            if t % c.elig_every == 0:
                self._update(c.elig_every * c.dt)
        if t % c.homeo_every == 0:
            self._homeostasis()

    def _update(self, dt_ms):
        c = self.cfg
        self.elig.mul_(math.exp(-dt_ms / c.tau_elig))
        m = self._m_class()
        self.mod["da"] *= math.exp(-dt_ms / c.tau_da)
        if abs(self.mod["da"]) < 1e-2:                     # >= 99 % of a burst's integral has been applied
            self.mod["da"] = 0.0
        if abs(m[0]) < 1e-9 and abs(m[1]) < 1e-9:
            return
        cls = self.cls_long
        sums = torch.stack(((self.elig * (1 - self.cls)).sum(), (self.elig * self.cls).sum()))
        mean = sums / torch.tensor([max(1, k) for k in self.n_cls], device=self.dev, dtype=torch.float32)
        mt = torch.tensor(m, device=self.dev, dtype=torch.float32)
        self.dw.add_(mt[cls] * (self.elig - mean[cls]) * self.da_mask * (dt_ms / 1000.0))
        self._apply()
        self.updates += 1

    def set_stdp(self, on):
        """Eligibility traces only matter where dopamine can arrive (Pong, free run); clear them when switching."""
        if on != self.stdp:
            self.elig.zero_()
            self.x.zero_()
            self.y.zero_()
            self.mod["da"] = 0.0
        self.stdp = bool(on)

    def hebbian(self, dr, mod, seconds, theta=None):
        """Fast Hebbian rate rule on the rate change dr (N,) over a window of `seconds` (see module doc)."""
        if self.frozen:
            return
        theta = self.cfg.hebb_theta if theta is None else theta
        eta = torch.tensor([self.cfg.eta["ctx"][mod], self.cfg.eta["hc"][mod]], device=self.dev, dtype=dr.dtype)
        pre = (dr[self.psrc.long()] - theta).clamp_(min=0.0)
        nz = pre > 0
        if not bool(nz.any()):
            return
        q = torch.nonzero(nz).squeeze(1)
        post = dr[self.pdst[q].long()] - theta
        post = torch.where(post < 0, post * self.cfg.hebb_ltd, post)
        self.dw.index_add_(0, q, eta[self.cls[q].long()] * pre[q] * post * seconds)
        self._apply()

    def _wmax(self):
        if self._wmax_t is None:
            c = self.cfg
            self._wmax_t = torch.where(self.cls.bool(), torch.tensor(c.w_max_hc, device=self.dev),
                                       torch.tensor(c.w_max_ctx, device=self.dev))
        return self._wmax_t

    def _apply(self):
        """Clamp the learned part so w stays in [0, w_max] and write the effective weights."""
        torch.maximum(self.dw, -self.w0, out=self.dw)
        torch.minimum(self.dw, self._wmax() - self.w0, out=self.dw)
        self.net.w[self.pidx] = self.w0 + self.dw

    def _homeostasis(self):
        c, net = self.cfg, self.net
        now = (net.t + 1, net.count.clone())
        if self.last_homeo is not None:
            t0, c0 = self.last_homeo
            dur = (now[0] - t0) * c.dt
            r = (now[1] - c0) / (dur / 1000.0)
            k = math.exp(-dur / c.tau_rate)
            self.rate.mul_(k).add_(r, alpha=1 - k)
            err = self.rate - c.rate_target
            net.theta.add_(err, alpha=c.eta_theta).clamp_(-c.theta_max, c.theta_max)
            net._dirty = True
            f = (1.0 - c.eta_scale * err / c.rate_target).clamp_(0.9, 1.1)[self.pdst.long()]
            self.dw.copy_((self.w0 + self.dw) * f - self.w0)        # scale the whole plastic weight
            self._apply()
        self.last_homeo = now

    # --- inspection ---------------------------------------------------------------------------------------------
    def stats(self):
        w = self.w0 + self.dw
        out = {"plastic_synapses": self.P, "updates": self.updates}
        for name, k in (("ctx", 0), ("hc", 1)):
            sel = self.cls == k
            if sel.any():
                out[name] = {"w_mean": float(w[sel].mean()), "dw_mean": float(self.dw[sel].mean()),
                             "dw_absmax": float(self.dw[sel].abs().max()),
                             "frac_changed": float((self.dw[sel].abs() > 1e-4).float().mean())}
        return out

    # --- learned-weight file (the connectome-derived w0 is never stored or overwritten) ------------------------
    def save(self, path, extra_meta=None):
        nz = torch.nonzero(self.dw.abs() > 1e-5).squeeze(1)
        meta = dict(self.meta)
        meta.update(extra_meta or {})
        meta["saved_at"] = time.time()
        dense = nz.numel() > 0.3 * self.P                              # dense float16 beats index + value
        arrays = {"dw_dense": self.dw.to(torch.float16).cpu().numpy()} if dense else \
            {"dw_idx": nz.to(torch.int32).cpu().numpy(), "dw": self.dw[nz].to(torch.float16).cpu().numpy()}
        np.savez(path, config_hash=self.cfg.config_hash(), n_neurons=self.net.n, P=self.P,
                 theta=self.net.theta.to(torch.float16).cpu().numpy(), meta=json.dumps(meta), **arrays)
        return {"nonzero": int(nz.numel()), "P": self.P, "dense": bool(dense)}

    def load(self, path, elapsed_days=0.0):
        """Load learned weights; decay them by the days since they were saved (forgetting)."""
        z = np.load(path, allow_pickle=False)
        if str(z["config_hash"]) != self.cfg.config_hash() or int(z["P"]) != self.P:
            raise ValueError("learned weights belong to a different network (config hash mismatch)")
        self.dw.zero_()
        if "dw_dense" in z.files:
            self.dw.copy_(torch.as_tensor(z["dw_dense"].astype(np.float32), device=self.dev))
        else:
            idx = torch.as_tensor(z["dw_idx"].astype(np.int64), device=self.dev)
            self.dw[idx] = torch.as_tensor(z["dw"].astype(np.float32), device=self.dev)
        self.net.theta.copy_(torch.as_tensor(z["theta"].astype(np.float32), device=self.dev))
        self.net._dirty = True
        self.meta = json.loads(str(z["meta"]))
        self.forget(elapsed_days)
        self._apply()
        return self.meta

    def forget(self, days):
        """Passive decay of the learned part: hippocampal fast (days), cortical slow (weeks)."""
        if days <= 0:
            return
        c = self.cfg
        k = torch.where(self.cls.bool(), torch.tensor(math.exp(-days / c.tau_forget_hc_days), device=self.dev),
                        torch.tensor(math.exp(-days / c.tau_forget_ctx_days), device=self.dev))
        self.dw.mul_(k)
        self._apply()
