"""The spiking network's populations, synapses and word patterns, in numpy only (no torch).

Shared by spiking/net.py (PyTorch, the nightly 1M-neuron network on the GPU) and spiking/live.py (numpy, the small
network that runs in the day on the server CPU, where torch is not installed): the same config and seed give the
same neurons, the same synapses in the same order and the same word -> neuron hashing in both.
"""
import hashlib

import numpy as np

INPUT_GROUPS = ("language", "visual", "default")      # where memory.py hashes words (plus the hippocampus)


def allocate(n, volumes, minimum):
    """Integer population sizes summing to n, proportional to volume, at least `minimum` (largest remainder)."""
    vol = np.asarray(volumes, dtype=np.float64)
    size = np.full(len(vol), minimum, dtype=np.int64)
    rest = n - size.sum()
    share = vol / vol.sum() * rest
    size += np.floor(share).astype(np.int64)
    left = n - size.sum()
    size[np.argsort(-(share - np.floor(share)), kind="stable")[:left]] += 1
    return size


class Layout:
    """Population layout of a network (needs self.cfg and self.reg): one population per region, excitatory first."""

    def _layout(self):
        c, R = self.cfg, self.reg.n
        vol = self.reg.volumes.copy()
        vol[self.reg.groups["memory"]] *= c.hc_scale
        self.size = allocate(c.n_neurons, vol, c.min_region)
        self.n_exc = np.maximum(1, np.round(c.frac_exc * self.size).astype(np.int64))
        self.n_exc = np.minimum(self.n_exc, self.size - 2)                  # >= 2 inhibitory per region
        self.off = np.concatenate([[0], np.cumsum(self.size)[:-1]])
        self.n = int(self.size.sum())
        region_of = np.repeat(np.arange(R), self.size)
        is_exc = np.zeros(self.n, dtype=bool)
        for r in range(R):
            is_exc[self.off[r]:self.off[r] + self.n_exc[r]] = True
        self.region_of_np, self.is_exc_np = region_of, is_exc
        self.hc_regions = set(self.reg.groups["memory"])

    def region_neurons(self, r, exc_only=False):
        """Global ids of region r (excitatory first)."""
        return np.arange(self.off[r], self.off[r] + (self.n_exc[r] if exc_only else self.size[r]))

    def group_neurons(self, group, exc_only=False):
        return np.concatenate([self.region_neurons(r, exc_only) for r in self.reg.groups[group]])


def synapse_lists(net):
    """All synapses of `net` (a Layout with cfg and reg), drawn from cfg.seed, as per-block lists
    (src, dst, w, delay, kind, delay_long): concatenate each list and sort stably by src for the CSR order."""
    c, R = net.cfg, net.reg.n
    rng = np.random.default_rng(c.seed)
    delay_long = np.maximum(1, np.round(net.reg.lengths / c.velocity_mm_ms / c.dt)).astype(np.int64)
    P = net.reg.W / net.reg.W.sum(0, keepdims=True)                     # P[s, r]: source region s for target r
    cdf = np.cumsum(P, axis=0)
    src_l, dst_l, w_l, d_l, kind_l = [], [], [], [], []
    d0, d1 = c.delay_local
    i32 = lambda a: np.asarray(a, dtype=np.int32).ravel()
    u8 = lambda a: np.asarray(a, dtype=np.uint8).ravel()
    for r in range(R):
        off, ne, sz = net.off[r], net.n_exc[r], net.size[r]
        tgt = np.arange(off, off + sz, dtype=np.int64)
        ni = sz - ne
        # local excitatory (no autapses: a self-draw is shifted to the next E neuron)
        s = off + rng.integers(0, ne, size=(sz, c.k_e_local))
        self_hit = s == tgt[:, None]
        s[self_hit] = off + (s[self_hit] - off + 1) % ne
        src_l.append(i32(s)); dst_l.append(i32(np.repeat(tgt, c.k_e_local)))
        w_l.append(np.full(s.size, c.j_e, np.float32)); kind_l.append(np.zeros(s.size, np.uint8))
        d_l.append(u8(rng.integers(d0, d1 + 1, size=s.size)))
        # local inhibitory
        s = off + ne + rng.integers(0, ni, size=(sz, c.k_i_local))
        self_hit = s == tgt[:, None]
        s[self_hit] = off + ne + (s[self_hit] - off - ne + 1) % ni
        src_l.append(i32(s)); dst_l.append(i32(np.repeat(tgt, c.k_i_local)))
        w_l.append(np.full(s.size, -c.g_i * c.j_e, np.float32)); kind_l.append(np.full(s.size, 1, np.uint8))
        d_l.append(u8(rng.integers(d0, d1 + 1, size=s.size)))
        # long-range excitatory: source region ~ streamline counts into r, source neuron uniform among its E
        m = sz * c.k_long
        sr = np.minimum(np.searchsorted(cdf[:, r], rng.random(m) * cdf[-1, r], side="right"), R - 1)
        s = net.off[sr] + np.floor(rng.random(m) * net.n_exc[sr]).astype(np.int64)
        src_l.append(i32(s)); dst_l.append(i32(np.repeat(tgt, c.k_long)))
        w_l.append(np.full(m, c.j_e, np.float32)); kind_l.append(np.full(m, 2, np.uint8))
        d_l.append(u8(delay_long[sr, r]))
        # hippocampal recurrent collaterals (E -> E, same region)
        if r in net.hc_regions and c.k_hc_rec > 0:
            te = tgt[:ne]
            s = off + rng.integers(0, ne, size=(ne, c.k_hc_rec))
            self_hit = s == te[:, None]
            s[self_hit] = off + (s[self_hit] - off + 1) % ne
            src_l.append(i32(s)); dst_l.append(i32(np.repeat(te, c.k_hc_rec)))
            w_l.append(np.full(s.size, c.j_hc_rec, np.float32)); kind_l.append(np.full(s.size, 3, np.uint8))
            d_l.append(u8(rng.integers(d0, d1 + 1, size=s.size)))
        if r in net.hc_regions and c.k_hc_rec_i > 0:
            ti = tgt[ne:]
            s = off + rng.integers(0, ne, size=(len(ti), c.k_hc_rec_i))
            src_l.append(i32(s)); dst_l.append(i32(np.repeat(ti, c.k_hc_rec_i)))
            w_l.append(np.full(s.size, c.j_hc_ei, np.float32)); kind_l.append(np.full(s.size, 4, np.uint8))
            d_l.append(u8(rng.integers(d0, d1 + 1, size=s.size)))
    if c.k_vis_sm > 0:                       # positive control: a projection the real wiring does not have
        vis_e = np.concatenate([net.region_neurons(r, exc_only=True) for r in net.reg.groups["visual"]])
        for r in net.reg.groups["somatomotor"]:
            te = np.arange(net.off[r], net.off[r] + net.n_exc[r])
            s = vis_e[rng.integers(0, len(vis_e), size=(len(te), c.k_vis_sm))]
            src_l.append(i32(s)); dst_l.append(i32(np.repeat(te, c.k_vis_sm)))
            w_l.append(np.full(s.size, c.j_vis_sm, np.float32)); kind_l.append(np.full(s.size, 5, np.uint8))
            d_l.append(u8(np.full(s.size, 5)))
    return src_l, dst_l, w_l, d_l, kind_l, delay_long


def input_regions(net):
    return sorted(set(sum((net.reg.groups[g] for g in INPUT_GROUPS), [])))


def word_neurons(net, word, frac, frac_hc, regions=None):
    """The neurons a word lands on (memory.py's hashing): a fixed random `frac` of the excitatory neurons of every
    language / visual / default parcel and `frac_hc` of each hippocampus, drawn from sha256("sub01-spiking:" + word)."""
    h = hashlib.sha256(("sub01-spiking:" + word).encode()).digest()
    rng = np.random.default_rng(int.from_bytes(h[:8], "little"))
    ids = []
    for r in (regions if regions is not None else input_regions(net)) + net.reg.groups["memory"]:
        ne = int(net.n_exc[r])
        k = max(1, int(round((frac_hc if r in net.hc_regions else frac) * ne)))
        ids.append(net.off[r] + rng.choice(ne, size=k, replace=False))
    return np.sort(np.concatenate(ids))
