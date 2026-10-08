"""Compact spiking frames for the page: the 3D neurons inside the brain (#62). numpy only, no torch.

Both live spiking networks stream {"type": "spiking", ...} frames (the GPU session's `state`, relayed by
spiking/server.py, and the CPU network's own, spiking/live.py). `viewer_frame` puts a producer's frame in the compact
form the pages read (web/neurons.js, web/neurons3d.js): the raster's verbose spike list ([[ms, row], ...], up to 4000
pairs, ~4-36 KB a frame) is replaced by

  "n3": {"v": 1,
         "rq": base64, one byte a region (214): the region's spike rate on a log scale (quantise_rates), when the
               producer measured per-region rates (both networks do: spiking/live.py and spiking/session.py),
         "sq": base64, 3 bytes a spike: region index, neuron slot 0-255 inside the region, time in the frame (0-255 of
               `span`) (pack_spikes): a uniform sample of the recorded spikes, at most SPIKE_CAP (400),
         "span": simulated ms the frame covers, "ns": spikes recorded in the frame (before the sample),
         "race": true while a decision race runs (the striatal action pools)}

Then one `Budget` on the server (spiking/server.py, SpikingHub.relay) decides what every viewer gets, both networks
together: at most RATE_BPS (3 KB/s) as the server serialises it. The panel's numbers (n_neurons, t_sim, spikes_per_s,
mean_rate_hz, realtime_x, groups, dopamine) go out at most once a second; the frames between carry type, net, live,
phase, raster t0/t1 and n3, and the spike sample is cut to the bytes left. tests/test_neurons3d.py measures it on /ws.

Nothing here invents activity: every packed spike is a recorded spike of a sampled model neuron, and a frame without
measured per-region rates has no "rq" (the page then tints the regions by their network's group rate and says so).
With no live network nothing is sent, and the page says the neurons are offline.

GPU session (spiking/session.py): its frame() sends "rq": quantise_rates(rr), the per-region rates it measures anyway;
viewer_frame passes a producer's "rq" through (a pod built before that sends none).
"""
import base64
import json
import math
import time

import numpy as np

VERSION = 1
RATE_LO, RATE_HI = 0.1, 100.0          # Hz: byte 1 = 0.1 Hz, byte 255 = 100 Hz (log scale, ~2.7 % steps); 0 = below
SPIKE_CAP = 400                        # spikes a frame, hard cap (the issue's bound)
RATE_BPS = 3000                        # bytes a second a viewer gets of the spiking frames, both networks together
BURST_BYTES = 1500                     # the bucket: a decision's first frames may use a little more
GPU_HOLD_S = 10.0                      # the CPU network's frames wait this long after the GPU network's last frame
FULL_EVERY_S = 1.0                     # the panel's numbers at most once a second
FULL_KEYS = ("n_neurons", "t_sim", "spikes_per_s", "mean_rate_hz", "realtime_x", "groups", "dopamine")
DROP_KEYS = ("raster", "rq", "steps_per_s")
SLOTS = 256


# --- per-region rates: one byte a region --------------------------------------------------------------------------
def quantise_rates(rates):
    """Per-region rates (Hz) -> base64 of one byte a region: 0 below RATE_LO, else 1..255 log-spaced to RATE_HI."""
    r = np.nan_to_num(np.asarray(rates, dtype=np.float64), nan=0.0, posinf=RATE_HI, neginf=0.0)
    q = np.zeros(r.shape, dtype=np.uint8)
    on = r >= RATE_LO
    x = np.log(np.minimum(r[on], RATE_HI) / RATE_LO) / math.log(RATE_HI / RATE_LO)
    q[on] = np.clip(np.rint(1 + 254 * x), 1, 255).astype(np.uint8)
    return base64.b64encode(q.tobytes()).decode()


def dequantise_rates(text):
    """Inverse of quantise_rates (what web/neurons3d.js does): Hz per region, 0 for byte 0."""
    q = np.frombuffer(base64.b64decode(text), dtype=np.uint8).astype(np.float64)
    return np.where(q > 0, RATE_LO * (RATE_HI / RATE_LO) ** ((q - 1) / 254.0), 0.0)


# --- which region and slot each recorded neuron is -----------------------------------------------------------------
class Sample:
    """Raster row -> (region, slot 0-255). `region` is -1 for a row the page cannot place."""

    def __init__(self, region, slot):
        self.region = np.asarray(region, dtype=np.int16)
        self.slot = np.asarray(slot, dtype=np.uint8)

    def __len__(self):
        return len(self.region)

    @classmethod
    def from_ids(cls, ids, off, size):
        """Neuron ids of a layout (one population per region, `off` its first id, `size` its count)."""
        ids, off, size = np.asarray(ids, dtype=np.int64), np.asarray(off, dtype=np.int64), np.asarray(size, dtype=np.int64)
        reg = np.searchsorted(off, ids, side="right") - 1
        slot = (ids - off[reg]) * SLOTS // np.maximum(1, size[reg])
        return cls(reg, np.clip(slot, 0, SLOTS - 1))

    @classmethod
    def one_per_region(cls, n_rows, n_regions, slot=SLOTS // 2):
        """net.py's raster with n_rows <= regions: row r is region r's sampled neuron (the slot unknown: the middle)."""
        rows = np.arange(n_rows)
        return cls(np.where(rows < n_regions, rows, -1), np.full(n_rows, slot))


def gpu_sample(n_neurons, n_rows=200, regions=None):
    """The GPU session's raster sample (net.enable_raster(n_rows), seed 0) rebuilt without torch: the layout comes from
    Config(n_neurons) and the region volumes, as in spiking/wiring.py. Falls back to one_per_region (slots unknown)."""
    try:
        from spiking.config import Config
        from spiking.regions import Regions
        from spiking.wiring import allocate
        reg = regions or Regions()
        c = Config(n_neurons=int(n_neurons))
        vol = reg.volumes.copy()
        vol[reg.groups["memory"]] *= c.hc_scale
        size = allocate(c.n_neurons, vol, c.min_region)
        off = np.concatenate([[0], np.cumsum(size)[:-1]])
        rng = np.random.default_rng(0)                    # net.enable_raster's draws, in its order
        per = [int(off[r] + rng.integers(size[r])) for r in range(reg.n)][:n_rows]
        if len(per) < n_rows:                             # more rows than regions: net.py adds uniform rows we cannot rebuild
            raise ValueError("raster larger than one neuron a region")
        return Sample.from_ids(np.sort(per), off, size)
    except Exception:
        return Sample.one_per_region(n_rows, 214)


# --- spikes: 3 bytes each ------------------------------------------------------------------------------------------
def pack_spikes(spikes, span_ms, sample, cap=SPIKE_CAP, seed=0):
    """[[ms since the frame's start, row], ...] (or an (n, 2) array) -> (base64 of 3 bytes a spike, spikes placed).
    Rows the sample cannot place are dropped; over `cap`, a uniform random subset (sorted by time) is kept."""
    a = np.asarray(spikes, dtype=np.int64).reshape(-1, 2)
    rows = a[:, 1]
    ok = (rows >= 0) & (rows < len(sample))
    a = a[ok]
    reg = sample.region[a[:, 1]] if len(a) else np.zeros(0, dtype=np.int16)
    a, reg = a[reg >= 0], reg[reg >= 0]
    n = len(a)
    cap = max(0, min(int(cap), SPIKE_CAP))
    if n > cap:
        keep = np.sort(np.random.default_rng(seed).choice(n, size=cap, replace=False))
        a, reg = a[keep], reg[keep]
    span = max(1, int(span_ms))
    out = np.empty((len(a), 3), dtype=np.uint8)
    out[:, 0] = reg
    out[:, 1] = sample.slot[a[:, 1]]
    out[:, 2] = np.clip(np.rint(a[:, 0] * 255.0 / span), 0, 255)
    order = np.argsort(out[:, 2], kind="stable")
    return base64.b64encode(out[order].tobytes()).decode(), n


def unpack_spikes(text, span_ms):
    """Inverse of pack_spikes: an (n, 3) array of region, slot, ms (ms rounded to span/255)."""
    b = np.frombuffer(base64.b64decode(text), dtype=np.uint8).reshape(-1, 3)
    out = b.astype(np.float64)
    out[:, 2] = np.rint(out[:, 2] * max(1, int(span_ms)) / 255.0)
    return out


# --- the frame the viewers get -------------------------------------------------------------------------------------
def viewer_frame(frame, sample, rates=None, race=False, cap=SPIKE_CAP):
    """A producer's frame in the compact form (module doc), with up to `cap` spikes; Budget.fit thins it per viewer.
    `rates`: per-region Hz measured by the producer (else a producer's "rq" string is passed through)."""
    out = {k: v for k, v in frame.items() if k not in DROP_KEYS and v is not None}
    r = frame.get("raster")
    if not isinstance(r, dict):
        return out
    t0, t1 = int(r.get("t0") or 0), int(r.get("t1") or 0)
    span = max(1, t1 - t0)
    spikes = r.get("spikes")
    sq, ns = pack_spikes([] if spikes is None else spikes, span, sample, cap=cap, seed=t1)
    out["raster"] = {"n": r.get("n"), "t0": t0, "t1": t1}
    out["n3"] = {"v": VERSION, "span": span, "ns": ns, "race": bool(race), "sq": sq}
    if rates is not None:
        out["n3"]["rq"] = quantise_rates(rates)
    elif isinstance(frame.get("rq"), str):
        out["n3"]["rq"] = frame["rq"]
    return out


def thin_spikes(sq, k):
    """Keep k of the packed spikes, evenly spread over the frame (they are sorted by time)."""
    b = np.frombuffer(base64.b64decode(sq), dtype=np.uint8).reshape(-1, 3)
    if k >= len(b):
        return sq
    if k <= 0:
        return ""
    idx = np.unique(np.floor((np.arange(k) + 0.5) * len(b) / k).astype(np.int64))
    return base64.b64encode(b[idx].tobytes()).decode()


class Budget:
    """What every viewer gets of the spiking frames, for the whole server (both networks share it): a token bucket of
    RATE_BPS bytes a second (as json.dumps writes the frame: the server's broadcast). The panel's numbers go out at
    most every FULL_EVERY_S (and when the phase changes), the spike sample is cut to the bytes left, and the CPU
    network's frames are dropped while the GPU network streams (the page shows the GPU's then, web/neurons.js)."""

    def __init__(self, rate=RATE_BPS, burst=BURST_BYTES, every_s=FULL_EVERY_S, gpu_hold_s=GPU_HOLD_S,
                 clock=time.monotonic):
        self.rate, self.burst, self.every_s, self.gpu_hold_s, self.clock = rate, burst, every_s, gpu_hold_s, clock
        self.tokens, self.t = float(burst), clock()
        self.gpu_at = -1e9
        self.full_at, self.phase = {}, {}
        self.sent = {"frames": 0, "bytes": 0, "dropped": 0}

    def fit(self, frame):
        """The frame to broadcast (thinned), or None to skip it. Frames without "n3" (e.g. live: false) pass as is."""
        now = self.clock()
        self.tokens = min(self.burst, self.tokens + max(0.0, now - self.t) * self.rate)   # a clock set back: no refill
        self.t = now
        n3 = frame.get("n3")
        if not isinstance(n3, dict):
            return frame
        net = "cpu" if frame.get("net") == "cpu" else "gpu"
        if net == "gpu":
            self.gpu_at = now
        elif now - self.gpu_at < self.gpu_hold_s:
            self.sent["dropped"] += 1
            return None
        full = now - self.full_at.get(net, -1e9) >= self.every_s or frame.get("phase") != self.phase.get(net)
        self.phase[net] = frame.get("phase")
        if full:
            self.full_at[net] = now
        out = {k: v for k, v in frame.items() if full or k not in FULL_KEYS}
        if not full and isinstance(out.get("raster"), dict):
            out["raster"] = {k: v for k, v in out["raster"].items() if k != "n"}
        n3 = out["n3"] = dict(n3)
        sq, n3["sq"] = n3.get("sq") or "", ""
        room = self.tokens - len(json.dumps(out))
        n3["sq"] = thin_spikes(sq, int(min(len(sq) // 4, max(0, room // 4)))) if sq else ""
        size = len(json.dumps(out))
        self.tokens -= size
        self.sent["frames"] += 1
        self.sent["bytes"] += size
        return out


# --- the page's points: web/neurons3d.json ---------------------------------------------------------------------------
def points_meta(n_points=20_000, regions=None):
    """Points a region for the 3D view: the 20k CPU network's populations (spiking/wiring.py), so with that network
    live each dot is one of its neurons; the 1M network's populations have the same proportions."""
    from spiking.config import Config
    from spiking.regions import Regions
    from spiking.wiring import allocate
    reg = regions or Regions()
    c = Config(n_neurons=n_points)
    vol = reg.volumes.copy()
    vol[reg.groups["memory"]] *= c.hc_scale
    return {"v": VERSION, "note": "points a region = the 20k spiking network's populations (spiking/frames.py)",
            "rate_lo_hz": RATE_LO, "rate_hi_hz": RATE_HI, "slots": SLOTS,
            "sizes": [int(x) for x in allocate(c.n_neurons, vol, c.min_region)]}


if __name__ == "__main__":                                  # python -m spiking.frames > web/neurons3d.json
    print(json.dumps(points_meta(), separators=(",", ":")))
