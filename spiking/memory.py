"""Memory in the synapses: chat messages and readings -> sparse patterns -> hippocampal assemblies -> REM replay.

Items are chat messages (source "chat") or articles it read (source "reading": title + keywords, hashed the same
way). Each stored item keeps its source, a display name (`item`: the message or the article title) and its day.

- Pattern: every content word of an (already filtered) chat message is hashed (sha256) to a fixed random 2 %
  of the excitatory neurons of each language / visual / default-network parcel, and to 0.5 % of the excitatory
  neurons of each hippocampus. The hippocampal part stands in for the entorhinal input layer, which this atlas
  does not contain (cortex -> hippocampus fibres here are too few, at 30 long-range synapses per neuron, to give
  a pattern-specific hippocampal response; measured: cos 0.47 same vs 0.58 different message). A message = the
  union of its words. Deterministic: the same word always lands on the same neurons, in every session.
- Encoding (awake, fast): the pattern is driven for 500 ms; then the fast Hebbian rate rule (plasticity.py, rule 2)
  is applied with the ENC learning rates (hippocampal ~50x cortical) on rates relative to each neuron's own
  running rate, threshold 15 Hz. It binds the co-active neurons on the CA3-like recurrent collaterals (100 extra
  E->E synapses per hippocampal neuron, plus 100 E->I collaterals so feedback inhibition tracks assemblies).
- Recall test (plasticity frozen): cue = the first half of the message's words (cortical + hippocampal parts).
  Completion, separately in hippocampus and cortex, in Hz: rate of the uncued words' neurons minus rate of the
  other excitatory neurons of the same regions, during the cue. Lures (word sets never stored, with the same
  word counts as the stored messages) go through the identical procedure. A message counts as recalled
  (hippocampal read-out) when its score is above every lure's; the cortical read-out is reported separately.
  With n lures the chance of a false "recalled" is about 1 / (n + 1) per message.
- REM replay: a brief excitability burst in the hippocampus; the stored assembly whose hippocampal neurons respond
  most wins (decayed or overwritten assemblies win less). Its pattern is then reinstated at 35 % of the waking
  drive while CONS is on, so cortical synapses among its words slowly strengthen (complementary learning
  systems). Simplification: hippocampus -> neocortex fibres carry < 2 % of cortical long-range input in this
  connectome, too few to reinstate a pattern on their own, so the cortical reinstatement is applied as an input
  selected by the hippocampal competition.
- Forgetting: hippocampal learned weights decay between sessions (tau 3 days), cortical ones slowly (60 days),
  and the depressing branch of the Hebbian rule makes each new encoding take a little from synapses of older
  assemblies that share neurons with it (interference).
"""
import numpy as np
import torch

from spiking.wiring import INPUT_GROUPS, word_neurons  # torch-free, shared with live.py (the day network)
from spiking.words import STOP, words  # noqa: F401  (torch-free: the server counts words too)


class MemorySystem:
    def __init__(self, net, frac=0.02, frac_hc=0.005, amp=8.0, enc_ms=500, cue_ms=500, gap_ms=300,
                 replay_amp=0.35, cap=50, enc_theta=15.0, cons_theta=6.0, replay_ms=500):
        self.net, self.frac, self.frac_hc, self.amp = net, frac, frac_hc, amp
        self.enc_ms, self.cue_ms, self.gap_ms, self.replay_amp, self.cap = enc_ms, cue_ms, gap_ms, replay_amp, cap
        self.enc_theta, self.cons_theta, self.replay_ms = enc_theta, cons_theta, replay_ms
        reg = net.reg
        self.input_regions = sorted(set(sum((reg.groups[g] for g in INPUT_GROUPS), [])))
        self.hc_e = np.concatenate([net.region_neurons(r, exc_only=True) for r in reg.groups["memory"]])
        in_e = np.concatenate([net.region_neurons(r, exc_only=True) for r in self.input_regions])
        self.input_e = in_e
        self.hc_drive = np.zeros(reg.n)
        self.hc_drive[reg.groups["memory"]] = 2.0
        self.registry = []
        self._cache = {}

    # --- patterns -----------------------------------------------------------------------------------------------
    def word_neurons(self, word):
        if word not in self._cache:
            self._cache[word] = word_neurons(self.net, word, self.frac, self.frac_hc, self.input_regions)
        return self._cache[word]

    def pattern(self, ws):
        return np.unique(np.concatenate([self.word_neurons(w) for w in ws])) if ws else np.zeros(0, np.int64)

    def split(self, ids):
        """(hippocampal part, cortical part) of a set of neuron ids."""
        hc = np.isin(ids, self.hc_e)
        return ids[hc], ids[~hc]

    # --- primitives ---------------------------------------------------------------------------------------------
    def _present(self, ids, ms, amp):
        """Drive neurons `ids` for ms; return (hippocampal E rates, snapshot) over the window."""
        net = self.net
        net.set_neuron_drive("memory", ids, amp)
        try:
            snap = net.snapshot()
            net.run(ms)
        finally:
            net.set_neuron_drive("memory", None)
        return net.rates_since(snap, self.hc_e), snap

    def _baseline(self):
        """Each neuron's running rate (10 s, from homeostasis) - the reference for the Hebbian rule."""
        p = self.net.plast
        return p.rate if p is not None else torch.zeros(self.net.n, device=self.net.device)

    def _rest(self, ms=None):
        snap = self.net.snapshot()
        self.net.run(ms or self.gap_ms)
        return snap

    # --- encoding ----------------------------------------------------------------------------------------------
    def encode(self, text, day=None, source="chat", item=None):
        ws = words(text)
        if not ws:
            return None
        net, p = self.net, self.net.plast
        ids = self.pattern(ws)
        h, snap = self._present(ids, self.enc_ms, self.amp)
        if p is not None:                  # fast Hebbian, expressed after the window (no runaway feedback)
            p.hebbian(net.rates_since(snap) - self._baseline(), "enc", self.enc_ms / 1000.0, theta=self.enc_theta)
        drive_rate = float(net.rates_since(snap, ids).mean())
        index = self.split(ids)[0]
        self._rest()
        rec = {"text": text, "words": ws, "day": day, "index": index.astype(int).tolist(), "drive_rate": drive_rate,
               "source": source, "item": item or text}
        self.registry = [m for m in self.registry if m["text"] != text] + [rec]
        del self.registry[:-self.cap]
        return rec

    # --- recall test ---------------------------------------------------------------------------------------------
    def _probe(self, ws):
        """Frozen-weight probe of one word list: all words driven, then the first half as a cue."""
        net = self.net
        half = max(1, len(ws) // 2)
        cue_ids = self.pattern(ws[:half])
        all_ids = self.pattern(ws)
        tgt = np.setdiff1d(all_ids, cue_ids)
        out = {"cue": ws[:half]}
        snap_full = self._present(all_ids, self.cue_ms, self.amp)[1]
        r_full = net.rates_since(snap_full)
        self._rest()
        snap_cue = self._present(cue_ids, self.cue_ms, self.amp)[1]
        r_cue = net.rates_since(snap_cue)
        self._rest()
        for part, pool in (("hc", self.hc_e), ("ctx", self.input_e)):
            t = np.intersect1d(tgt, pool)
            o = np.setdiff1d(pool, all_ids)
            if len(t) == 0 or len(o) == 0:
                out[part] = 0.0
                continue
            ti = torch.as_tensor(t, device=net.device)
            oi = torch.as_tensor(o, device=net.device)
            out[part] = float(r_cue[ti].mean() - r_cue[oi].mean())          # completion, Hz
            out[part + "_full_hz"] = round(float(r_full[ti].mean() - r_full[oi].mean()), 2)
        return out

    def test(self, day=None, lures=8, items=None):
        """Pattern-completion test of stored messages vs length-matched lures, plasticity frozen."""
        p = self.net.plast
        was = p.frozen if p is not None else None
        if p is not None:
            p.frozen = True
        try:
            items = [m for m in (items if items is not None else self.registry) if len(m["words"]) >= 2]
            res = [{"text": m["text"], "item": m.get("item", m["text"]), "source": m.get("source", "chat"),
                    "item_day": m.get("day"), **self._probe(m["words"])} for m in items]
            lengths = [len(m["words"]) for m in items] or [6]
            lure_res = []
            for i in range(lures):
                ws = [f"lure{day or ''}x{i}w{j}" for j in range(lengths[i % len(lengths)])]
                lure_res.append(self._probe(ws))
        finally:
            if p is not None:
                p.frozen = was
        thr = {k: max((r[k] for r in lure_res), default=0.0) for k in ("hc", "ctx")}
        scores, recalled = [], []
        for r in res:
            s = {"text": r["text"], "item": r["item"], "source": r["source"], "item_day": r["item_day"],
                 "hc": round(r["hc"], 3), "ctx": round(r["ctx"], 3),
                 "hc_full": r.get("hc_full_hz"), "ctx_full": r.get("ctx_full_hz"),
                 "hc_recalled": bool(r["hc"] > thr["hc"]), "ctx_recalled": bool(r["ctx"] > thr["ctx"])}
            scores.append(s)
            if s["hc_recalled"]:
                recalled.append(r["text"])
        return {"kind": "memory_test", "day": day, "cues": [" ".join(r["cue"]) for r in res],
                "recalled": recalled, "scores": scores, "unit": "Hz",
                "control_scores": [{"hc": round(r["hc"], 3), "ctx": round(r["ctx"], 3)} for r in lure_res],
                "thresholds": {k: round(v, 3) for k, v in thr.items()}, "n_stored": len(self.registry),
                "false_positive_rate_per_message": round(1.0 / (len(lure_res) + 1), 3)}

    # --- REM replay -------------------------------------------------------------------------------------------
    def replay_once(self, rng=None, burst_ms=100, replay_ms=None):
        """Spontaneous hippocampal reactivation picks a memory; its pattern is reinstated with CONS on."""
        if not self.registry:
            return None
        net, p = self.net, self.net.plast
        replay_ms = replay_ms or self.replay_ms
        rng = rng or np.random.default_rng()
        snap = net.snapshot()
        net.set_region_drive("hc_state", self.hc_drive * 1.5)
        try:
            net.run(burst_ms)
        finally:
            net.set_region_drive("hc_state", None)
        r = net.rates_since(snap)
        act = np.array([float(r[torch.as_tensor(m["index"], device=net.device)].mean()) for m in self.registry])
        z = (act - act.max()) / max(1e-6, act.std() + 1.0)
        prob = np.exp(3 * z)
        prob /= prob.sum()
        m = self.registry[int(rng.choice(len(self.registry), p=prob))]
        snap = self._present(self.pattern(m["words"]), replay_ms, self.amp * self.replay_amp)[1]
        if p is not None:
            p.hebbian(net.rates_since(snap) - self._baseline(), "cons", replay_ms / 1000.0, theta=self.cons_theta)
        return {"text": m["text"], "hc_activation": round(float(act.max()), 2)}

    # --- persistence (stored with the learned weights) ------------------------------------------------------
    def to_meta(self):
        return {"memories": self.registry}

    def from_meta(self, meta):
        self.registry = list(meta.get("memories", []))


def sleep_block(net, mem, minutes, cycles=2, rem_frac=0.4, replay_every_s=3.0, rng=None, on_tick=None, replay=True):
    """A compressed night: NREM (global ~0.8 Hz up/down drive, recorded drive damped) then REM (noisier, replay).

    Stage parameters follow sleep.py qualitatively (NREM: slow and synchronous, low input gain; REM: noisy,
    hippocampal replay); a real night's cycles are compressed into `minutes` of simulated time. replay=False runs
    the identical night without replays (the control). Returns the list of replays.
    """
    rng = rng or np.random.default_rng(0)
    replays = []
    total_ms = int(minutes * 60_000)
    cyc_ms = total_ms // max(1, cycles)
    base_gain, base_noise = net.baseline_gain, net.noise_gain
    chunk = 50
    try:
        for k in range(cycles):
            nrem_ms = int(cyc_ms * (1 - rem_frac))
            net.baseline_gain = base_gain * 0.3
            for t in range(0, nrem_ms, chunk):
                net.mu_offset = -1.0 + 2.5 * np.sin(2 * np.pi * 0.8 * (net.t * net.cfg.dt / 1000.0))
                net._dirty = True
                net.run(chunk)
                if on_tick:
                    on_tick("NREM")
            net.mu_offset = 0.0
            net._dirty = True
            net.baseline_gain, net.noise_gain = base_gain * 0.7, base_noise * 1.2
            t_rem, next_replay = 0, rng.exponential(replay_every_s * 1000)
            while t_rem < cyc_ms - nrem_ms:
                if t_rem >= next_replay and mem.registry:
                    t0 = net.t
                    if replay:
                        r = mem.replay_once(rng)
                        if r:
                            replays.append(r)
                    else:                                    # same time, same stage, no reactivation
                        net.run(100 + mem.replay_ms)
                    t_rem += net.t - t0
                    next_replay = t_rem + rng.exponential(replay_every_s * 1000)
                else:
                    net.run(chunk)
                    t_rem += chunk
                if on_tick:
                    on_tick("REM")
    finally:
        net.baseline_gain, net.noise_gain, net.mu_offset = base_gain, base_noise, 0.0
        net._dirty = True
    return replays
