"""Sleep/wake engine for SUB-01: a sleep circuit model, arousal, sleep debt and memory replay.

Part of a model of brain activity built from one person's public MRI data; not a mind, not conscious,
not the person. Replay re-applies stored stimulus patterns (of chat messages and of articles it read);
no language model and no generated text. The sleep engine is a small published-model *circuit*, not a rule table:

1. Sleep/wake = the brainstem ascending arousal system model of Phillips & Robinson (2007, J Biol Rhythms
   22:167-179): the monoaminergic group (MA: LC/DR/TMN, mean potential V_m) and the VLPO (V_v) inhibit each
   other (a flip-flop); the VLPO is driven by a homeostatic somnogen H and a circadian drive C. Published
   parameters (below) with ONE calibration: mu (H production per unit MA firing) raised from 3.6 to 5.0 nM s so
   the model sleeps ~8 h a day, plus the circadian phase, set so that it sleeps ~23:55-07:55 on the local clock
   (SUB01_TZ, default Asia/Tokyo). Details and numbers: docs/twin/sleep.md.
2. NREM/REM = a pontine REM-on / REM-off mutual-inhibition flip-flop (anatomy: Lu, Sherman, Devor & Saper 2006,
   Nature 441:589; firing-rate flip-flop models of this kind: Diniz Behn & Booth 2010, J Neurophysiol 103:1937;
   Rempe, Best & Terman 2010, J Math Biol 60:615) using the same population equation and sigmoid as (1), plus
   one slow "REM pressure" variable p that builds during NREM and is used up during REM, which makes the pair a
   relaxation oscillator (the reciprocal-interaction idea of McCarley & Hobson 1975, Science 189:58). The
   REM-circuit parameters are OURS, chosen so ~90 min cycles appear; they are not fitted to data. MA firing
   inhibits REM-on (no REM while awake), and a REM bias grows as H falls and as C approaches its minimum
   (circadian REM propensity, Dijk & Czeisler 1995, J Neurosci 15:3526), so REM episodes lengthen across the
   night. Those couplings are imposed, not emergent.
3. Arousal: chat messages and large trades are an external input to the MA population (impulsive stimuli to
   MA as in Fulcher, Phillips & Robinson 2008, Phys Rev E 78:051920); waking up is the flip-flop switching.
4. Sleep debt (hours) = how far H is above the model's own well-rested 24 h cycle at the same clock time,
   in units of "H gained by one hour awake instead of asleep" (mu Q_wake / chi). It is H, read out in hours.

live_server.py applies `engine.params` (Stuart-Landau stage parameters, gliding) to the brain model every tick;
`engine.modulators` gives tonic neuromodulator levels. No language model and no generated text: replay
re-applies stored stimulus patterns, nothing more.
"""
import math
import os
import random
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from state_io import load_json, save_json

TZ_NAME = os.environ.get("SUB01_TZ", "Asia/Tokyo")        # where SUB-01 lives
TZ = ZoneInfo(TZ_NAME)
ROME = TZ                                                    # old name, kept so existing imports keep working
TZ_LABEL = TZ_NAME.split("/")[-1]

# Stuart-Landau parameters per stage: f_hz, coupling (x baseline g), noise, a (bifurcation), stimulus gain
AWAKE = dict(f_hz=10.0, coupling=1.0, noise=0.5, a=-5.0, gain=1.0)
NREM_LIGHT = dict(f_hz=3.0, coupling=2.0, noise=0.3, a=-2.0, gain=0.25)
NREM_DEEP = dict(f_hz=1.0, coupling=3.0, noise=0.25, a=0.0, gain=0.08)     # slow, synchronous
REM = dict(f_hz=6.0, coupling=0.6, noise=0.9, a=-5.0, gain=0.4)             # theta-like, noisy
KEYS = tuple(AWAKE)

# --- 1. Phillips & Robinson 2007 ascending arousal system (units: mV, s, nM) ------------------------------------
# Values of PR2007 Table 1 (cross-checked against the MIT-licensed R package sleepR, github.com/PabRod/sleepR,
# philrob_default_parms). Only MU and CIRC_PEAK_H are calibrated here.
Q_MAX = 100.0          # s^-1, maximum mean firing rate
THETA = 10.0           # mV, firing threshold (sigmoid midpoint)
SIGMA = 3.0            # mV, sigmoid width
TAU_M = TAU_V = 10.0   # s, population time constants
NU_VM = -1.9           # mV s, MA -> VLPO (inhibitory)
NU_MV = -1.9           # mV s, VLPO -> MA (inhibitory)
NU_VH = 0.19           # mV nM^-1, somnogen H -> VLPO
NU_VC = -6.3           # mV, circadian drive -> VLPO (C in [0, 1])
A_M = 1.0              # mV, constant cholinergic/orexinergic drive to MA (nu_ma * Q_a)
CHI = 10.8 * 3600.0    # s, somnogen clearance time
MU = 5.0               # nM s, somnogen production per MA firing. PR2007/sleepR: 3.6 (= 1e-3 nM h) -> 6.4 h/day asleep by
                       # V_v > V_m (7.8 h by sleepR's dH<0 rule); calibrated to 5.0 -> ~7.95 h (V_v > V_m)
CIRC_PEAK_H = 16.85    # local clock hour where C = 1 (strongest wake drive); calibrated: sleep ~23:55-07:55,
                       # C minimum at ~04:50 (near the usual core-temperature minimum)

# --- 2. REM-on / REM-off flip-flop (same population equation and sigmoid; parameters are ours) ----------------
TAU_R = 10.0           # s
NU_R = -1.9            # mV s, mutual inhibition REM-on <-> REM-off (same strength as the PR flip-flop)
A_OFF = 2.0            # mV, tonic drive to REM-off; then the pair is bistable for D_on in ~[1.48, 3.29] mV
A_ON = 1.5             # mV, tonic drive to REM-on
G_P = 4.0              # mV, REM pressure p -> REM-on
K_MA = 2.0             # mV s, MA firing -> REM-on (inhibitory: aminergic cells are REM-off, McCarley & Hobson)
G_C = 0.3              # mV, circadian REM propensity (1 - C) -> REM-on
G_H = 0.08             # mV nM^-1, somnogen H -> REM-on (inhibitory: high H favours NREM)
H_MID = 14.0           # nM, H where the H term is zero
TAU_UP = 90 * 60.0     # s, REM pressure builds during NREM (towards 1)
TAU_DN = 12 * 60.0     # s, REM pressure is used up during REM (towards P_MIN), at H = H_MID
P_MIN = -0.3           # REM pressure target during REM (far enough below the REM-off gate that REM always ends)
G_TDN = 0.2           # nM^-1, REM use-up time grows as H falls: tau_dn(H) = TAU_DN exp(G_TDN (H_MID - H))
TAU_PW = 30 * 60.0     # s, REM pressure decays while awake (so no REM at sleep onset)

# --- 3./4. inputs, bookkeeping ------------------------------------------------------------------------------------
G_AROUSAL = 1.8        # mV of MA drive per arousal unit (1 unit = one message)
AROUSAL_TAU_S = 5 * 60
WAKE_THRESHOLD = 3.0   # nominal arousal that wakes it in mid-night NREM (what actually decides is the flip-flop)
AROUSAL_MAX = 2 * WAKE_THRESHOLD   # total arousal cap: no input stream (chat, trades) can pin it awake for days
OVERRIDE_DEBT_H = 18.0         # past this much sleep debt (more than one whole lost night, ~17 h), sleep pressure
OVERRIDE_WIDTH_H = 4.0         # overrides outside arousal: its MA drive is divided by 1 + ((debt - 18 h) / 4 h)^2
DEBT_MAX_RESTART_H = 12.0      # sleep debt is capped at this on a restart (a bad input stream must not carry over)
REPAIRS = ("2026-10-02-trades",)   # one-time state repairs, applied once to a saved state (see from_dict)
REPAIR_DEBT_H = 2.0            # the 2026-10-02 repair: the debt the fake trades built is reset to at most this
AROUSAL_NATURAL = 0.3  # a wake-up with less arousal than this counts as natural (no external cause)
BIG_TRADE_USD = 5000
REPLAY_MEAN_S = 4 * 60 # mean interval between REM replays
TAU_DEPTH = 10 * 60.0  # s, NREM depth index follows its target with this lag
MORNING_HOUR, WAKE_HOUR, EVENING_HOUR = 5, 8, 20   # natural wake from 05:00 closes the night; so does 08:00 awake
TRANSITION_S = 30.0          # exponential glide time constant (sim s) of the stage parameters: ~95 % after 90 s
TRANSITION_REAL_S = 1.0      # ...but never faster than this in real seconds (high --time-scale)
STEP_S = 5.0                 # max integration substep (s); the populations have tau = 10 s
COARSE_STEP_S = 10.0
COARSE_AFTER_S = 2 * 3600.0
MAX_STEPS = 13000
MAX_GAP_S = 36 * 3600.0      # longer gaps (server off for days): restart on the rested cycle, debt decays
SWITCH_MV = 2.0              # hysteresis on V_v - V_m and V_on - V_off for naming the state
QM_WAKE = 4.25               # s^-1, MA firing in resting wake on the reference cycle (checked in the tests)

# Neuromodulator anchors (1.0 = resting wake). Ordering from recordings: LC (NE) and DR (5-HT) firing
# wake > NREM > REM ~ silent (Aston-Jones & Bloom 1981, J Neurosci 1:876; McGinty & Harper 1976, Brain Res
# 101:569); cortical ACh wake ~ REM > NREM (Marrosu et al. 1995, Brain Res 671:329); VTA DA burst firing in
# REM (Dahan et al. 2007, Neuropsychopharmacology 32:1232). The numbers are ours (ordinal, not fitted).
MOD_KEYS = ("DA", "5HT", "NE", "ACh")
MOD_WAKE = {"DA": 1.0, "5HT": 1.0, "NE": 1.0, "ACh": 1.0}
MOD_NREM_LIGHT = {"DA": 0.7, "5HT": 0.6, "NE": 0.55, "ACh": 0.45}
MOD_NREM_DEEP = {"DA": 0.5, "5HT": 0.4, "NE": 0.3, "ACh": 0.2}
MOD_REM = {"DA": 0.9, "5HT": 0.15, "NE": 0.1, "ACh": 1.3}
MOD_AROUSED = {"DA": 0.3, "5HT": 0.1, "NE": 0.6, "ACh": 0.2}   # per unit of MA firing above resting wake


def local(t):
    return datetime.fromtimestamp(t, TZ)


def hhmm(t):
    return local(t).strftime("%H:%M")


def stamp(t):
    return local(t).strftime("%Y-%m-%dT%H:%M")


def night_date(t):
    """A night is named after the evening it starts on (00:00-08:00 belongs to the day before)."""
    return (local(t) - timedelta(hours=12)).date().isoformat()


def lerp(p, q, x):
    return {k: p[k] + (q[k] - p[k]) * x for k in p}


def Q(v):
    """PR2007 mean firing rate (s^-1) of a population with mean potential v (mV)."""
    z = (THETA - v) / SIGMA
    return Q_MAX / (1.0 + math.exp(z if z < 60.0 else 60.0))


def circadian(tod_s):
    """C in [0, 1] (PR2007 form 0.5 (1 + cos)), locked to the local clock: 1 at CIRC_PEAK_H."""
    return 0.5 * (1.0 + math.cos(2 * math.pi * (tod_s / 3600.0 - CIRC_PEAK_H) / 24.0))


def tod_offset(t):
    """Seconds to add to an epoch to get local clock seconds (time of day = (t + offset) mod 86400)."""
    return local(t).utcoffset().total_seconds()


def rem_share(von, voff):
    """Which side of the REM flip-flop is active: 0 = REM-off (NREM), 1 = REM-on (REM); logistic, 1 mV wide."""
    z = (voff - von) / 1.0
    return 1.0 / (1.0 + math.exp(z if z < 60.0 else 60.0))


def step_circuit(s, h, tod, drive_m):
    """Advance the circuit state s = [V_m, V_v, H, V_on, V_off, p] by h seconds. Exponential Euler in
    Gauss-Seidel order, so large steps relax onto the flip-flop branches instead of oscillating.
    tod = local seconds of day, drive_m = external input to MA (mV). Returns C."""
    vm, vv, H, von, voff, p = s
    C = circadian(tod)
    a = 1.0 - math.exp(-h / TAU_V)
    vv += a * (NU_VM * Q(vm) + NU_VC * C + NU_VH * H - vv)
    vm += a * (NU_MV * Q(vv) + A_M + drive_m - vm)
    qm = Q(vm)
    hinf = MU * qm
    H = hinf + (H - hinf) * math.exp(-h / CHI)
    # pontine REM flip-flop
    ar = 1.0 - math.exp(-h / TAU_R)
    d_on = A_ON + G_P * p + G_C * (1.0 - C) - G_H * (H - H_MID) - K_MA * qm
    von += ar * (NU_R * Q(voff) + d_on - von)
    voff += ar * (NU_R * Q(von) + A_OFF - voff)
    # REM pressure: builds in NREM, used up in REM, decays while awake (w = wake share, r = REM-on share)
    w = min(1.0, qm / QM_WAKE)
    r = rem_share(von, voff)
    tdn = TAU_DN * math.exp(G_TDN * (H_MID - H))                  # REM episodes last longer as H falls
    alpha = (1.0 - w) * ((1.0 - r) / TAU_UP + r * P_MIN / tdn)
    beta = (1.0 - w) * ((1.0 - r) / TAU_UP + r / tdn) + w / TAU_PW
    pinf = alpha / beta
    p = pinf + (p - pinf) * math.exp(-beta * h)
    s[:] = vm, vv, H, von, voff, p
    return C


class Reference:
    """The model's own well-rested, undisturbed 24 h cycle (no input), one state per minute of local clock time.
    Used to start a fresh engine on its attractor and as the zero line of sleep debt."""
    _cache = None
    STEP = 10.0

    def __init__(self):
        s = [1.0, -10.0, 14.0, -10.0, 2.0, 0.0]
        h = self.STEP
        n = int(86400 / h)
        for _ in range(3):                                  # converge (H relaxes with chi = 10.8 h)
            for i in range(n):
                step_circuit(s, h, i * h, 0.0)
        self.states = []
        per_min = int(60 / h)
        for i in range(n):
            if i % per_min == 0:
                self.states.append(list(s))
            step_circuit(s, h, i * h, 0.0)
        H = [x[2] for x in self.states]
        self.h_min, self.h_max = min(H), max(H)
        wake = [Q(x[0]) for x in self.states if x[1] - x[0] < 0]
        self.qm_wake = sum(wake) / len(wake)
        self.sleep_h = (1440 - len(wake)) / 60
        # H gained by one hour awake instead of asleep: rise while awake + fall while asleep = mu Q_wake / chi
        self.dh_per_h = MU * self.qm_wake * 3600.0 / CHI

    @classmethod
    def get(cls):
        if cls._cache is None:
            cls._cache = cls()
        return cls._cache

    def at(self, t):
        """Reference state at epoch t (linear interpolation between minutes)."""
        tod = ((t + tod_offset(t)) % 86400.0) / 60.0
        i = int(tod)
        x = tod - i
        a, b = self.states[i % 1440], self.states[(i + 1) % 1440]
        return [u + (v - u) * x for u, v in zip(a, b)]


class Clock:
    """Local sim clock. scale=60 -> one sim hour per real minute. `start` = sim epoch to start at."""

    def __init__(self, scale=1.0, start=None):
        self.scale = scale
        self.real0 = time.time()
        self.sim0 = self.real0 if start is None or scale == 1 else start

    def now(self):
        return self.sim0 + (time.time() - self.real0) * self.scale


class Memory:
    """Accepted chat messages (source "chat"), articles it read (source "reading") and words viewers taught it (source
    "taught"): time, stage when received, stimulus pattern and emotional tag. Readings compete for REM replay at
    READING_WEIGHT, and their pool never outweighs READING_POOL x the pool of what people wrote (chat + taught), so
    messages from people still win most nights. Taught items are encoded more strongly (TAUGHT_WEIGHT), but their
    pool is capped at TAUGHT_POOL x everything else, so they cannot take every REM replay."""

    EMO_WEIGHT = {"threat": 3.0, "positive": 2.5, "neutral": 1.0}
    READING_WEIGHT = 0.6
    READING_POOL = 0.6
    TAUGHT_WEIGHT = 1.5
    TAUGHT_POOL = 1.0            # taught <= 1.0 x the rest: at most half the replay chance when anything else is there
    SOURCE_WEIGHT = {"reading": READING_WEIGHT, "taught": TAUGHT_WEIGHT}

    def __init__(self, items=None, cap=2000):
        self.items = list(items or [])
        self.cap = cap

    def add(self, t, text, stage, stimulus, emotion, networks, source="chat", **extra):
        m = {"t": t, "text": text, "stage": stage, "stimulus": stimulus, "emotion": emotion,
             "networks": networks, "asleep": stage != "AWAKE", "source": source, **extra}
        self.items.append(m)
        del self.items[:-self.cap]
        return m

    def chat(self):
        return [m for m in self.items if m.get("source", "chat") == "chat"]

    @staticmethod
    def key(m):
        """Habituation key of a memory; matches replay_key() of its night record."""
        return replay_key(stamp(m["t"]), m["text"])

    def weight(self, m, t, night_start, replayed=0):
        recency = math.exp(-max(0.0, t - m["t"]) / (24 * 3600))
        tonight = 4.0 if night_start is not None and m["t"] >= night_start else 1.0
        src = self.SOURCE_WEIGHT.get(m.get("source"), 1.0)
        return recency * self.EMO_WEIGHT.get(m["emotion"], 1.0) * tonight * src / (1 + replayed)   # habituation

    def weights(self, cand, t, night_start, replayed):
        w = [self.weight(m, t, night_start, replayed.get(self.key(m), 0)) for m in cand]
        w = self.cap_readings(w, [m.get("source") == "reading" for m in cand])
        return self.cap_taught(w, [m.get("source") == "taught" for m in cand])

    def cap_readings(self, w, is_read):
        chat = sum(x for x, r in zip(w, is_read) if not r)
        read = sum(x for x, r in zip(w, is_read) if r)
        if chat > 0 and read > self.READING_POOL * chat:
            k = self.READING_POOL * chat / read
            w = [x * k if r else x for x, r in zip(w, is_read)]
        return w

    def cap_taught(self, w, is_taught):
        rest = sum(x for x, r in zip(w, is_taught) if not r)
        taught = sum(x for x, r in zip(w, is_taught) if r)
        if rest > 0 and taught > self.TAUGHT_POOL * rest:
            k = self.TAUGHT_POOL * rest / taught
            w = [x * k if r else x for x, r in zip(w, is_taught)]
        return w

    def pick(self, t, night_start, rng=random, replayed=None):
        """Weighted by recency, emotion, source and 'arrived tonight'; `replayed` = {key: count} tonight."""
        cand = [m for m in self.items if m["t"] <= t]
        if not cand:
            return None
        return rng.choices(cand, weights=self.weights(cand, t, night_start, replayed or {}))[0]

    def replay_chance(self, m, t_night, n_replays=None, sims=200, seed=0):
        """Estimated chance that `m` is replayed at least once in a night starting at t_night, with what memory
        holds now (no new messages). Monte Carlo of pick() with habituation and the reading and taught caps."""
        import numpy as np
        n_replays = expected_replays() if n_replays is None else n_replays
        cand = [x for x in self.items if x["t"] <= t_night and t_night - x["t"] < 4 * 86400] or [m]
        if not any(x is m for x in cand):
            cand.append(m)
        base = np.array([self.weight(x, t_night, None) for x in cand])
        is_read = np.array([x.get("source") == "reading" for x in cand])
        is_taught = np.array([x.get("source") == "taught" for x in cand])
        me = next(i for i, x in enumerate(cand) if x is m)
        rng = np.random.default_rng(seed)
        counts = np.zeros((sims, len(cand)))
        for _ in range(int(round(n_replays))):
            w = base / (1 + counts)
            chat, read = (w * ~is_read).sum(1), (w * is_read).sum(1)
            k = np.where((chat > 0) & (read > self.READING_POOL * chat),
                         self.READING_POOL * chat / np.maximum(read, 1e-12), 1.0)
            w = np.where(is_read, w * k[:, None], w)
            rest, taught = (w * ~is_taught).sum(1), (w * is_taught).sum(1)
            k = np.where((rest > 0) & (taught > self.TAUGHT_POOL * rest),
                         self.TAUGHT_POOL * rest / np.maximum(taught, 1e-12), 1.0)
            w = np.where(is_taught, w * k[:, None], w)
            c = np.cumsum(w, 1)
            pick = (c < rng.random(sims)[:, None] * c[:, -1:]).sum(1)
            counts[np.arange(sims), np.minimum(pick, len(cand) - 1)] += 1
        return float((counts[:, me] > 0).mean())


def replay_key(received, text):
    return f"{received}|{text}"


_EXPECTED_REPLAYS = None


def expected_replays():
    """Mean number of REM replays in an undisturbed night (REM time / REPLAY_MEAN_S). Measured once, by running the
    sleep circuit itself from 20:00 to 12:00 local with no input (~27 with the parameters above), then cached."""
    global _EXPECTED_REPLAYS
    if _EXPECTED_REPLAYS is None:
        t0 = datetime(2026, 1, 15, 20, 0, tzinfo=TZ).timestamp()
        e, rem, dt = SleepEngine(t0, rng=random.Random(0)), 0.0, 10.0
        for i in range(1, int(16 * 3600 / dt) + 1):
            e.update(t0 + i * dt, dt_real=dt)
            rem += dt if e.stage == "REM" else 0.0
        _EXPECTED_REPLAYS = rem / REPLAY_MEAN_S
    return _EXPECTED_REPLAYS


def day_of(t):
    """The waking day t belongs to, named like the night that follows it (08:00 -> 08:00 next morning)."""
    return (local(t) - timedelta(hours=WAKE_HOUR)).date().isoformat()


def next_bedtime(t):
    """Sim epoch of the coming night's usual sleep onset (00:30 local), or t if it is already night."""
    d = local(t)
    if d.hour < WAKE_HOUR:
        return t
    return (d.replace(hour=0, minute=30, second=0, microsecond=0) + timedelta(days=1)).timestamp()


class SleepEngine:
    CIRCUIT = ("V_m", "V_v", "H", "V_on", "V_off", "rem_p")

    def __init__(self, now, rng=None):
        self.rng = rng or random.Random()
        self.t = now
        self.V_m, self.V_v, self.H, self.V_on, self.V_off, self.rem_p = Reference.get().at(now)
        self.C = circadian((now + tod_offset(now)) % 86400.0)
        self.asleep = self.V_v - self.V_m > 0
        self.rem = self.asleep and self.V_on - self.V_off > 0
        self.stage = self._stage_name()
        self.depth = self._depth_target() if self.stage == "NREM" else 0.0   # NREM depth index 0..1
        self.onset = now if self.asleep else None      # current sleep onset
        self.k_base = 0                                # REM episodes completed tonight
        self.awake_since = now                         # last natural morning wake-up
        self.last_wake = None                          # time of the last wake transition
        self.arousal = 0.0                             # external arousal input (message/trade units), decays
        self.arousal_log = []                          # recent [t, amount, kind, usd]
        self.last_stim = -1e18
        self.night = None                              # current night record (see open_night)
        self.last_night = None                         # summary of the previous closed night
        self.next_replay = None
        self.repairs = list(REPAIRS)                   # a fresh engine needs none of the one-time repairs
        if self.asleep:
            self.open_night(now)
            self.night["sleep_onset"] = stamp(now)
            self.night["timeline"].append({"t": stamp(now), "stage": self.stage})
        self.params = self.stage_params()

    # --- derived quantities ------------------------------------------------------
    @property
    def debt(self):
        """Hours of sleep owed: H above the rested reference at this clock time / (H per hour of lost sleep)."""
        ref = Reference.get()
        return max(0.0, (self.H - ref.at(self.t)[2]) / ref.dh_per_h)

    @debt.setter
    def debt(self, hours):
        ref = Reference.get()
        self.H = ref.at(self.t)[2] + max(0.0, hours) * ref.dh_per_h

    @property
    def tired(self):
        return min(1.0, self.debt / 4.0)

    @property
    def gain(self):
        return self.params["gain"]

    def pressure(self, t=None):
        """Homeostatic sleep pressure: H scaled to the rested cycle (0 = after a full night, 1 = usual bedtime)."""
        ref = Reference.get()
        return (self.H - ref.h_min) / (ref.h_max - ref.h_min)

    def in_night(self, t):
        return local(t).hour < WAKE_HOUR

    @property
    def modulators(self):
        """Tonic neuromodulator levels {DA, 5HT, NE, ACh} (1.0 = resting wake) read from the circuit state:
        m = MA firing / resting-wake firing, r = REM-on share of the pontine flip-flop, depth = NREM depth index."""
        m = Q(self.V_m) / QM_WAKE
        r = rem_share(self.V_on, self.V_off)
        sleep = lerp(lerp(MOD_NREM_LIGHT, MOD_NREM_DEEP, self.depth), MOD_REM, r)
        out = lerp(sleep, MOD_WAKE, min(1.0, m))
        if m > 1.0:
            out = {k: out[k] + MOD_AROUSED[k] * min(m - 1.0, 2.0) for k in out}
        return {k: round(out[k], 3) for k in MOD_KEYS}

    def _stage_name(self):
        return "AWAKE" if not self.asleep else ("REM" if self.rem else "NREM")

    def _depth_target(self):
        """NREM depth index: normalised H (slow-wave activity tracks the homeostatic process: Borbely 1982,
        Hum Neurobiol 1:195; Achermann et al. 1993, Sleep 16:329), lighter as REM pressure nears the REM gate."""
        ref = Reference.get()
        hn = min(1.0, max(0.0, (self.H - ref.h_min) / (ref.h_max - ref.h_min)))
        gate = max(0.0, 1.0 - (max(0.0, self.rem_p) / 0.6) ** 4)
        return hn ** 1.5 * gate

    def stage_params(self):
        if self.stage == "REM":
            return dict(REM)
        if self.stage == "NREM":
            return lerp(NREM_LIGHT, NREM_DEEP, self.depth)
        p = dict(AWAKE)                                       # tired: less reactive, noisier
        p["gain"] *= 1 - 0.5 * self.tired
        p["noise"] *= 1 + self.tired
        return p

    # --- inputs --------------------------------------------------------------------
    def arousal_drive(self):
        """mV of drive to the MA population from outside arousal. Up to OVERRIDE_DEBT_H of debt it is the plain
        G_AROUSAL x arousal (a message wakes him, chat can keep him up a whole night, as before); beyond, a body that
        has lost more than a night falls asleep anyway: the drive shrinks fast with the extra debt, so no input stream
        can keep him awake for days (a nonstop stream of the largest allowed trades: ~7.8 h of sleep a day, debt
        levelling off at ~24 h)."""
        over = max(0.0, self.debt - OVERRIDE_DEBT_H)
        return G_AROUSAL * self.arousal / (1.0 + (over / OVERRIDE_WIDTH_H) ** 2)

    def stimulus(self, t, kind, usd=0.0):
        """Register a chat message ('message') or trade ('trade') as arousal input to the MA population.
        Returns the current stimulus gain."""
        amount = 0.0
        if kind == "message":
            amount = 1.0 if self.stage != "NREM" else 1.0 - 0.4 * self.depth   # thalamic gating in deep NREM
        elif kind == "trade" and usd >= BIG_TRADE_USD:
            amount = min(1.5 * WAKE_THRESHOLD, usd / BIG_TRADE_USD)
        if amount > 0:
            self.arousal = min(AROUSAL_MAX, self.arousal + amount)
            self.last_stim = t
            self.arousal_log.append([t, amount, kind, usd])
        return self.gain

    # --- clock ---------------------------------------------------------------------
    def update(self, t, dt_real=None):
        """Advance to sim time t in bounded substeps. Returns a list of events (dicts with 'type' and 'text')."""
        dt = max(0.0, t - self.t)
        ev = []
        if dt > MAX_GAP_S:
            self._restart(t)
            dt = 0.0
        if dt > 0:
            h_max = STEP_S if dt <= COARSE_AFTER_S else COARSE_STEP_S
            n = min(MAX_STEPS, max(1, math.ceil(dt / h_max)))
            h = dt / n
            # people type in real time: with an accelerated clock, arousal builds up during sleep by decaying
            # at most 3x faster than real time (awake, it settles on the sim clock as usual)
            slow = 1.0 if dt_real is None else min(1.0, 3 * dt_real / dt)
            off = tod_offset(t)
            s = [self.V_m, self.V_v, self.H, self.V_on, self.V_off, self.rem_p]
            kd = 1.0 - math.exp(-h / TAU_DEPTH)
            t0 = self.t
            for i in range(1, n + 1):
                ts = t0 + i * h
                self.arousal *= math.exp(-h * (slow if self.asleep else 1.0) / AROUSAL_TAU_S)
                self.C = step_circuit(s, h, (ts + off) % 86400.0, self.arousal_drive())
                self.V_m, self.V_v, self.H, self.V_on, self.V_off, self.rem_p = s
                self.t = ts
                self._classify(ts, ev)
                if self.stage == "NREM":
                    self.depth += (self._depth_target() - self.depth) * kd
                else:
                    self.depth = 0.0
        self.t = t
        if self.arousal < AROUSAL_NATURAL:
            self.arousal_log = []              # episode over: the next wake-up cause starts fresh
        del self.arousal_log[:-200]

        # clock bookkeeping: awake at midnight -> the night (and lost sleep) starts anyway; awake at 08:00 -> ends
        if self.night is None and not self.asleep and self.in_night(t) and not self._night_done(t):
            self.open_night(t)
        if self.night is not None and not self.asleep and WAKE_HOUR <= local(t).hour < EVENING_HOUR:
            self.close_night(t)

        if self.stage == "REM":
            if self.next_replay is None:
                self.next_replay = t + self.rng.expovariate(1 / REPLAY_MEAN_S)
            if t >= self.next_replay:
                self.next_replay = t + self.rng.expovariate(1 / REPLAY_MEAN_S)
                ev.append({"type": "replay", "text": "replay"})           # live_server picks the memory
        else:
            self.next_replay = None

        # glide parameters toward the stage target (never jump)
        x = dt / TRANSITION_S
        if dt_real is not None:
            x = min(x, dt_real / TRANSITION_REAL_S)
        self.params = lerp(self.params, self.stage_params(), 1 - math.exp(-x))
        return ev

    def _classify(self, t, ev):
        """Name the circuit state (with a small hysteresis) and handle transitions at substep time t."""
        d = self.V_v - self.V_m
        if not self.asleep and d > SWITCH_MV:
            ev.append(self.fall_asleep(t))
        elif self.asleep and d < -SWITCH_MV:
            if self.arousal < AROUSAL_NATURAL:
                ev.append(self.wake(t, f"woke up at {hhmm(t)}", natural=True))
            else:
                ev.append(self.wake(t, f"woken at {hhmm(t)} by {self.cause(t)}"))
        if self.asleep:
            r = self.V_on - self.V_off
            if not self.rem and r > SWITCH_MV:
                self.rem = True
            elif self.rem and r < -SWITCH_MV:
                self.rem = False
                self.k_base += 1
        else:
            self.rem = False
        stage = self._stage_name()
        if stage != self.stage:
            self.stage = stage
            if self.asleep and self.night is not None:
                self.night["timeline"].append({"t": stamp(t), "stage": stage})

    def cause(self, t):
        recent = self.arousal_log              # everything since arousal was last near zero
        trades = [e for e in recent if e[2] == "trade"]
        if trades and sum(e[1] for e in trades) >= 0.5 * sum(e[1] for e in recent):
            return f"a large trade (${max(e[3] for e in trades):,.0f})"
        n = sum(1 for e in recent if e[2] == "message")
        return f"{n} message{'s' * (n != 1)}"

    # --- transitions ---------------------------------------------------------------
    def _night_done(self, t):
        return self.last_night is not None and self.last_night["date"] == night_date(t)

    def open_night(self, t):
        if self._night_done(t):                # e.g. an evening nap that already ended: continue that record
            self.night = self.last_night
            self.night["woke_up"] = None
            return
        self.night = {"date": night_date(t), "timezone": TZ_NAME, "sleep_onset": None, "woke_up": None,
                      "timeline": [], "wakeups": [], "sleep_debt": {"start": round(self.debt, 2), "end": None},
                      "replays": []}
        self.k_base = 0

    def fall_asleep(self, t):
        if self.night is None:
            self.open_night(t)
        n = self.night
        if n["sleep_onset"] is None:
            n["sleep_onset"] = stamp(t)
        self.asleep, self.onset, self.rem, self.stage = True, t, False, "NREM"
        n["timeline"].append({"t": stamp(t), "stage": "NREM"})
        return {"type": "sleep", "text": f"fell asleep at {hhmm(t)}"}

    def wake(self, t, text, natural=False):
        self.asleep, self.rem, self.stage, self.depth = False, False, "AWAKE", 0.0
        self.last_wake = t
        if self.night is None:
            self.open_night(t)
        self.night["timeline"].append({"t": stamp(t), "stage": "AWAKE"})
        if natural and MORNING_HOUR <= local(t).hour < EVENING_HOUR:
            self.awake_since = t
            self.close_night(t)
        elif natural:
            self.night["wakeups"].append({"t": stamp(t), "cause": "spontaneous (no input)"})
        else:
            self.night["wakeups"].append({"t": stamp(t), "cause": text.split(" by ", 1)[-1]})
        self.last_stim = max(self.last_stim, t)
        return {"type": "wake", "text": text, "natural": natural}

    def close_night(self, t):
        n = self.night
        slept = n["sleep_onset"] is not None and self.last_wake is not None and not self.asleep
        n["woke_up"] = stamp(self.last_wake if slept else t)
        n["sleep_debt"]["end"] = round(self.debt, 2)
        self.last_night = n
        self.night = None

    def _restart(self, t):
        """Gap longer than MAX_GAP_S (e.g. server off for days): continue on the rested cycle, debt decays."""
        ref = Reference.get()
        excess = max(0.0, self.H - ref.at(self.t)[2])
        if self.night is not None:
            self.close_night(self.t)
        self.V_m, self.V_v, self.H, self.V_on, self.V_off, self.rem_p = ref.at(t)
        self.H += excess * math.exp(-(t - self.t) / CHI)
        self.t = t
        self.arousal, self.arousal_log, self.depth = 0.0, [], 0.0
        self.asleep = self.V_v - self.V_m > 0
        self.rem = self.asleep and self.V_on - self.V_off > 0
        self.stage = self._stage_name()
        self.onset = t if self.asleep else None
        if self.asleep:
            self.open_night(t)
            self.night["sleep_onset"] = self.night["sleep_onset"] or stamp(t)
            self.night["timeline"].append({"t": stamp(t), "stage": self.stage})

    def _sync_branch(self):
        """Put both flip-flops on the branch that matches the saved stage (loading an old state.json) by
        relaxing them for a few seconds at fixed time; if the branch cannot hold, the next update() switches."""
        self.V_m, self.V_v = (-9.0, 1.5) if self.asleep else (0.6, -10.0)
        self.V_on, self.V_off = (8.0, -8.0) if self.stage == "REM" else (-8.0, 8.0)
        s = [self.V_m, self.V_v, self.H, self.V_on, self.V_off, self.rem_p]
        tod = (self.t + tod_offset(self.t)) % 86400.0
        for _ in range(10):
            self.C = step_circuit(s, 1.0, tod, self.arousal_drive())
        self.V_m, self.V_v, self.H, self.V_on, self.V_off, self.rem_p = s

    def record_replay(self, t, m):
        self.night["replays"].append({"t": stamp(t), "text": m["text"], "emotion": m["emotion"],
                                      "networks": m["networks"], "received": stamp(m["t"]),
                                      "received_stage": m["stage"], "source": m.get("source", "chat")})

    def replay_counts(self):
        counts = {}
        for r in (self.night or {}).get("replays", []):
            k = replay_key(r["received"], r["text"])
            counts[k] = counts.get(k, 0) + 1
        return counts

    def night_start(self):
        """Sim epoch of tonight's first sleep onset (None if not in a night)."""
        if self.night is None or self.night["sleep_onset"] is None:
            return None
        return datetime.fromisoformat(self.night["sleep_onset"]).replace(tzinfo=TZ).timestamp()

    def status(self):
        return {"stage": self.stage, "clock": hhmm(self.t), "tz": TZ_LABEL, "date": local(self.t).strftime("%a %d %b"),
                "debt": round(self.debt, 2), "tired": round(self.tired, 2), "depth": round(self.depth, 2),
                "gain": round(self.gain, 3), "arousal": round(self.arousal, 2),
                "woken_tonight": len(self.night["wakeups"]) if self.night else 0,
                "H": round(self.H, 2), "C": round(self.C, 3), "V_m": round(self.V_m, 2), "V_v": round(self.V_v, 2),
                "V_on": round(self.V_on, 2), "V_off": round(self.V_off, 2), "rem_p": round(self.rem_p, 3),
                "pressure": round(self.pressure(), 3), "cycle": self.k_base + (1 if self.asleep else 0),
                "modulators": self.modulators}

    # --- persistence ---------------------------------------------------------------
    STATE_KEYS = ("t", "asleep", "rem", "stage", "depth", "onset", "k_base", "awake_since", "last_wake", "arousal",
                  "arousal_log", "last_stim", "night", "last_night", "params", "C", "repairs") + CIRCUIT

    def to_dict(self):
        return {k: getattr(self, k) for k in self.STATE_KEYS} | {"debt": round(self.debt, 3)}

    @classmethod
    def from_dict(cls, d, rng=None):
        e = cls(d["t"], rng)
        for k in cls.STATE_KEYS:
            if k in d:
                setattr(e, k, d[k])
        if "H" not in d:                       # old (rule-based) state.json: rebuild the circuit from it
            e.debt = d.get("debt", 0.0)
            e.rem = e.stage == "REM"
            e._sync_branch()
        if "repairs" not in d:
            e.repairs = []
        broken = (float(d.get("arousal") or 0.0) > AROUSAL_MAX or e.debt > DEBT_MAX_RESTART_H
                  or any("trade" in str(w.get("cause", "")) for w in ((e.night or {}).get("wakeups") or [])))
        # a restart never carries a runaway input over: arousal at most the wake threshold, a short cause log,
        # sleep debt at most DEBT_MAX_RESTART_H
        e.arousal = min(max(0.0, float(e.arousal)), WAKE_THRESHOLD)
        e.arousal_log = list(e.arousal_log or [])[-20:]
        if e.debt > DEBT_MAX_RESTART_H:
            e.debt = DEBT_MAX_RESTART_H
        e.repair(broken)
        return e

    def repair(self, broken):
        """One-time repairs of a saved state, each applied once (the tag is saved with the state).
        2026-10-02-trades: a third-party token's mis-decoded "trades" ($97M each) pinned him awake (arousal 215,
        debt 105 h) and broke the night record; drop the arousal, the debt those trades built (at 12 h of debt the
        model's first night has ~15 min of REM; at 2 h, ~75 min) and tonight's record (last_night stays as history),
        so the next sleep starts a clean night with REM and replays."""
        if "2026-10-02-trades" not in self.repairs and broken:
            self.arousal, self.arousal_log = 0.0, []
            if self.debt > REPAIR_DEBT_H:
                self.debt = REPAIR_DEBT_H
            if self.night is not None:
                self.night, self.k_base, self.next_replay = None, 0, None
                if self.asleep:
                    self.open_night(self.t)
                    self.night["sleep_onset"] = stamp(self.t)
                    self.night["timeline"].append({"t": stamp(self.t), "stage": self.stage})
        if "2026-10-02-trades" not in self.repairs:
            self.repairs.append("2026-10-02-trades")       # a healthy old state needs nothing: marked done too


class Store:
    """data/state.json (engine + memory) and data/nights/YYYY-MM-DD.json."""

    def __init__(self, root):
        self.root = Path(root)
        (self.root / "nights").mkdir(parents=True, exist_ok=True)

    def load(self):
        d = load_json(self.root / "state.json")       # missing or torn (kept aside): start fresh, never crash
        if not d or "engine" not in d or "memory" not in d:
            return None, None
        return d["engine"], d["memory"]

    def save(self, engine, memory):
        self._write(self.root / "state.json", {"engine": engine.to_dict(), "memory": memory.items})
        for n in (engine.night, engine.last_night):
            if n is not None:
                self._write(self.root / "nights" / f"{n['date']}.json", n)

    @staticmethod
    def _write(path, obj):
        save_json(path, obj, indent=1, ensure_ascii=False)
