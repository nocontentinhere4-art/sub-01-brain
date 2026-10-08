"""Neuromodulators for the SUB-01 digital twin (component: neurochem).

A digital twin model of one real person's brain structure and recorded activity; not a mind, not conscious, not
the person. The receptor maps below are GROUP data from post-mortem human brains (not this person's), the
neuromodulator dynamics are small phenomenological rules. See docs/twin/neurochem.md for equations, sources and
what is not realistic.

Public interface (docs/twin_contracts.md):
    RECEPTORS                      {receptor: (214,) float in 0..1}, atlas_names.json order
    Neuromodulators()              levels {"DA","5HT","NE","ACh"}, 1.0 = resting wake
        .on_trade(kind, usd, t)    buy/pump -> phasic DA as reward-prediction error; sell/dump + volatility -> NE
        .update(dt, sleep_levels)  tonic levels follow the sleep engine, phasic parts decay -> levels
        .region_gain(levels=None)  (n,) gain vector, exactly 1.0 at baseline, bounded in (1-GAIN_SPAN, 1+GAIN_SPAN)
    region_gain(levels, receptors=None)   same as a module function

Receptor densities: Zilles & Palomero-Gallagher 2017, Front. Neuroanat. 11:78 (CC BY 4.0), quantitative in-vitro
autoradiography, mapped to Schaefer-200 by twin/build_receptors.py -> twin/data/receptors_214.csv.
Subcortical regions have NO data in that source: they get a flagged neutral fallback (cortical mean density,
i.e. no regional specificity) - see RECEPTOR_SOURCE.
"""
import csv
import math
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "data" / "receptors_214.csv"
N_REGIONS = 214
LEVEL_KEYS = ("DA", "5HT", "NE", "ACh")

# ---------------------------------------------------------------------------------------------------------------
# Receptor maps
# ---------------------------------------------------------------------------------------------------------------
# receptor -> (modulator, sign, weight). sign +1: excitatory gain (Gq/Gs-coupled or cation channel), -1: inhibitory
# (Gi-coupled). The coupling uses density RELATIVE to its mean over regions (maps give the spatial pattern), and the
# weights set each system's net balance (model choices, see docs):
# - NE is net gain-increasing (+1 - 0.5 = +0.5 on average), as in the LC-NE adaptive-gain account (Aston-Jones &
#   Cohen 2005 Annu Rev Neurosci 28:403; Shine et al. 2018 eLife 7:e31130; Shine et al. 2021 Nat Neurosci 24:765);
# - 5-HT is balanced (5-HT2A excitatory vs 5-HT1A inhibitory, net 0 on average, only the regional pattern changes);
# - ACh (M1 + alpha4beta2) and DA (D1) are excitatory.
RECEPTOR_EFFECTS = {
    "D1": ("DA", +1, 1.0),      # Gs; D1-dependent gain increase in PFC (Seamans & Yang 2004 Prog Neurobiol 74:1)
    "5HT2": ("5HT", +1, 0.5),   # Gq, ketanserin site ~5-HT2A; gain scaled by density (Deco et al. 2018 Curr Biol)
    "5HT1a": ("5HT", -1, 0.5),  # Gi, GIRK hyperpolarisation
    "a1": ("NE", +1, 1.0),      # alpha1 adrenoceptor, Gq
    "a2": ("NE", -1, 0.5),      # alpha2 adrenoceptor, Gi (half weight, see above)
    "M1": ("ACh", +1, 0.5),     # muscarinic M1, Gq
    "a4b2": ("ACh", +1, 0.5),   # nicotinic alpha4beta2, cation channel
}
# Wanted but not used - no permissively licensed source reachable (see twin/data/RECEPTORS_SOURCES.md).
MISSING = {
    "D2": "malen2022 raclopride (CC0) only on OSF (blocked); other D2 maps CC BY-NC-SA or unlicensed",
    "DAT": "PET maps CC BY-NC-SA or licence unspecified",
    "5HTT": "PET maps CC BY-NC-SA or licence unspecified",
    "NET": "PET maps licence unspecified; alpha1/alpha2 autoradiography used for NE instead",
}
REL_CAP = 2.0           # relative densities are capped at 2x the cortical mean (one outlier would dominate)
NEUTRAL_DENSITY = 1.0 / REL_CAP   # used only if the CSV is missing: no regional specificity


def _load_receptors(path=CSV_PATH, n=N_REGIONS):
    """-> (RECEPTORS {r: (n,) 0..1}, RECEPTOR_SOURCE (n,) str, RAW {r: (n,) fmol/mg or nan}, ok).

    RECEPTORS[r] = min(raw / cortical_mean(raw), REL_CAP) / REL_CAP, so 0.5 = cortical mean density and 1.0 =
    twice the mean or more. Subcortical rows (no data) are set to 0.5 and flagged "fallback_cortical_mean"."""
    names = list(RECEPTOR_EFFECTS)
    try:
        rows = list(csv.DictReader(open(path)))
        assert len(rows) == n
    except (OSError, AssertionError):
        uni = {r: np.full(n, NEUTRAL_DENSITY) for r in names}
        return uni, np.array(["fallback_no_data"] * n, dtype=object), {r: np.full(n, np.nan) for r in names}, False
    raw = {r: np.array([float(x[f"{r}_fmol_mg"]) if x[f"{r}_fmol_mg"] else np.nan for x in rows]) for r in names}
    has = ~np.isnan(raw[names[0]])
    source = np.array([x["source"] for x in rows], dtype=object)
    dens = {}
    for r in names:
        rel = raw[r] / np.nanmean(raw[r])                # 1 = mean over the 200 cortical parcels
        rel = np.minimum(rel, REL_CAP)                   # robustness cap (area-6 alpha1 outlier, see docs)
        rel[~has] = 1.0                                  # FALLBACK (flagged): cortical mean, no specificity
        dens[r] = rel / REL_CAP                          # 0..1, 1 = REL_CAP x cortical mean
    source[~has] = "fallback_cortical_mean"
    return dens, source, raw, True


RECEPTORS, RECEPTOR_SOURCE, RECEPTORS_RAW, RECEPTORS_FROM_DATA = _load_receptors()

# ---------------------------------------------------------------------------------------------------------------
# Gain
# ---------------------------------------------------------------------------------------------------------------
GAIN_SLOPE = {"DA": 0.25, "5HT": 0.3, "NE": 0.4, "ACh": 0.25}   # d gain / d level per unit coupling
GAIN_SPAN = 0.5                                                  # gain stays in (0.5, 1.5)


def _finite(x, default):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return default
    return x if math.isfinite(x) else default


def coupling(receptors=None):
    """{modulator: (n,) net signed receptor weighting c_m,i = sum_r sign_r * w_r * d_r,i / mean_i(d_r,i)}.

    Dividing by the mean makes the weights (not the arbitrary density units) set each system's net balance; the
    receptor map sets which regions are affected more or less. For RECEPTORS the mean over 214 regions is close to the
    cortical mean (the subcortical fallback is the pre-cap cortical mean)."""
    rec = RECEPTORS if receptors is None else receptors
    n = len(next(iter(rec.values())))
    c = {m: np.zeros(n) for m in LEVEL_KEYS}
    for r, (m, s, w) in RECEPTOR_EFFECTS.items():
        if r in rec:
            d = np.asarray(rec[r], float)
            c[m] = c[m] + s * w * d / max(float(np.mean(d)), 1e-12)
    return c


_COUPLING = coupling()


def region_gain(levels, receptors=None, n=None):
    """Per-region multiplicative gain (n,).

    drive_i = sum_m GAIN_SLOPE_m * (L_m - 1) * c_m,i ;  g_i = 1 + GAIN_SPAN * tanh(drive_i / GAIN_SPAN)
    Exactly 1.0 when every level is 1.0 (tanh(0) = 0); bounded in (1 - GAIN_SPAN, 1 + GAIN_SPAN).
    If n is given and differs from the receptor maps, a uniform (non-specific) coupling is used.
    """
    c = _COUPLING if receptors is None else coupling(receptors)
    size = len(c["DA"])
    if n is not None and n != size:
        c = {m: np.full(n, float(np.mean(v))) for m, v in c.items()}
        size = n
    drive = np.zeros(size)
    for m in LEVEL_KEYS:
        lev = _finite(levels.get(m, 1.0), 1.0)           # NaN/inf/None from a bad feed -> baseline, never NaN gain
        dl = lev - 1.0
        if dl != 0.0:
            drive += GAIN_SLOPE[m] * dl * c[m]
    return 1.0 + GAIN_SPAN * np.tanh(drive / GAIN_SPAN)


# ---------------------------------------------------------------------------------------------------------------
# Neuromodulator dynamics
# ---------------------------------------------------------------------------------------------------------------
DEFAULTS = {
    "usd_ref": 50.0,        # USD; trade size x = log(1 + usd/usd_ref) (compressive, model choice)
    "alpha": 0.3,           # Rescorla-Wagner learning rate of the expected pump size V
    "k_da_pos": 0.4,        # phasic DA per unit positive RPE
    "k_da_neg": 0.15,       # per unit negative RPE (smaller: dips have limited range, Bayer & Glimcher 2005)
    "k_da_omit": 0.06,      # per unit omission RPE (small dip when an expected pump does not come)
    "alpha_ibi": 0.3,       # learning rate of the expected inter-buy interval
    "omit_factor": 1.5,     # a pump is "missing" after omit_factor * expected interval
    "min_buys_timing": 3,   # buys needed before timing expectations exist
    "k_ne_dump": 0.25,      # phasic NE per unit sell size
    "k_ne_surprise": 0.1,   # phasic NE per unit unsigned flow prediction error (any trade)
    "beta_flow": 0.2,       # learning rate of the running signed-flow mean and volatility
    "k_ne_vol": 0.12,       # slow NE per unit flow volatility
    "tau_da": 2.0,          # s, phasic DA decay (DAT clearance is sub-second to seconds; Garris & Wightman 1994)
    "tau_ne": 4.0,          # s, phasic NE decay (LC burst + NET reuptake; seconds)
    "tau_other": 4.0,       # s, phasic 5-HT / ACh decay (not driven by trades here)
    "tau_vol": 60.0,        # s, volatility memory
    "tau_tonic": 20.0,      # s, tonic levels follow the sleep engine with this lag
    "phasic_min": -0.9,
    "phasic_max": 2.0,
    "level_max": 3.0,
}
USD_MAX = 1e9            # USD; larger sizes are clipped (keeps log size and RPE finite)
BUY_KINDS = {"buy", "pump"}
SELL_KINDS = {"sell", "dump"}


class Neuromodulators:
    """Tonic + phasic DA, 5-HT, NE, ACh. Level_m = tonic_m * (1 + phasic_m [+ volatility term for NE]).

    Tonic follows the sleep engine's `modulators` (1.0 = resting wake). Phasic parts are fractions of tonic, so a
    silent system (e.g. NE in REM, locus coeruleus nearly off) also gives small phasic responses.
    """

    def __init__(self, receptors=None, params=None, state=None):
        self.p = dict(DEFAULTS, **(params or {}))
        self.receptors = receptors
        self._c = _COUPLING if receptors is None else coupling(receptors)
        self.t = 0.0
        self.tonic = {k: 1.0 for k in LEVEL_KEYS}
        self.phasic = {k: 0.0 for k in LEVEL_KEYS}
        self.V = 0.0              # learned expected pump size (log units)
        self.n_buys = 0
        self.ibi = None           # learned mean inter-buy interval, s
        self.since_buy = 0.0      # s since the last buy (update() clock)
        self.last_buy_t = None    # t of the last buy as given to on_trade
        self.next_omit = None     # since_buy value at which the next omission dip fires
        self.flow_mean = 0.0      # running mean of signed trade size
        self.vol = 0.0            # running unsigned prediction error of signed flow (volatility)
        self.last = {"rpe": 0.0, "omission": 0.0}
        if state:
            self._load(state)

    # -- levels ----------------------------------------------------------------------------------------------
    @property
    def levels(self):
        out = {}
        for k in LEVEL_KEYS:
            extra = self.p["k_ne_vol"] * self.vol if k == "NE" else 0.0
            out[k] = float(min(self.p["level_max"], max(0.0, self.tonic[k] * (1.0 + self.phasic[k] + extra))))
        return out

    def _kick(self, k, amount):
        self.phasic[k] = min(self.p["phasic_max"], max(self.p["phasic_min"], self.phasic[k] + amount))

    # -- events ----------------------------------------------------------------------------------------------
    def on_trade(self, kind, usd, t=None):
        """A trade. Returns {"rpe", "da", "ne"} (the phasic increments applied).

        `t` (seconds) must run on the same clock as the `dt` given to update(), since both feed the learned
        inter-pump interval. A non-finite `usd` (bad feed) is ignored, so NaN/inf can never enter the state."""
        p = self.p
        kind = str(kind).lower()
        usd = _finite(usd, None)
        if usd is None:
            return {"rpe": 0.0, "da": 0.0, "ne": 0.0}
        t = _finite(t, None) if t is not None else None
        x = math.log1p(min(max(usd, 0.0), USD_MAX) / p["usd_ref"])
        da = ne = rpe = 0.0
        if kind in BUY_KINDS:
            rpe = x - self.V                                           # delta = r - V  (Rescorla & Wagner 1972)
            self.V += p["alpha"] * rpe
            da = (p["k_da_pos"] if rpe > 0 else p["k_da_neg"]) * rpe
            self._kick("DA", da)
            interval = (t - self.last_buy_t) if (t is not None and self.last_buy_t is not None) else self.since_buy
            if self.n_buys >= 1 and interval > 0:
                self.ibi = interval if self.ibi is None else self.ibi + p["alpha_ibi"] * (interval - self.ibi)
            self.n_buys += 1
            self.last_buy_t = t
            self.since_buy = 0.0
            self.next_omit = p["omit_factor"] * self.ibi if self.ibi else None
            s = x
        elif kind in SELL_KINDS:
            ne += p["k_ne_dump"] * x
            s = -x
        else:
            return {"rpe": 0.0, "da": 0.0, "ne": 0.0}
        err = abs(s - self.flow_mean)                                  # unexpected flow (Yu & Dayan 2005)
        self.flow_mean += p["beta_flow"] * (s - self.flow_mean)
        self.vol += p["beta_flow"] * (err - self.vol)
        ne += p["k_ne_surprise"] * err
        self._kick("NE", ne)
        self.last["rpe"] = rpe
        return {"rpe": rpe, "da": da, "ne": ne}

    def burst(self, amount):
        """A phasic dopamine-like burst from outside the market (#89: a new short starts). `amount` is the phasic
        increment (>= 0), clipped like every kick; returns what was applied."""
        try:
            a = max(0.0, float(amount))
        except (TypeError, ValueError):
            return 0.0
        before = self.phasic["DA"]
        self._kick("DA", a)
        return self.phasic["DA"] - before

    def update(self, dt, sleep_levels=None):
        """Advance dt seconds. sleep_levels: the sleep engine's modulators dict (missing keys -> 1.0)."""
        p = self.p
        dt = max(0.0, _finite(dt, 0.0))
        self.t += dt
        self.since_buy += dt
        self.last["omission"] = 0.0
        # omitted expected pump: negative RPE at the time it was due (Schultz, Dayan & Montague 1997 Science)
        if (self.next_omit is not None and self.n_buys >= p["min_buys_timing"] and self.V > 1e-6
                and self.since_buy >= self.next_omit):
            rpe = -self.V
            self._kick("DA", p["k_da_omit"] * rpe)
            self.V += p["alpha"] * (0.0 - self.V)                      # extinction
            self.next_omit += self.ibi                                 # next due time; successive dips shrink
            self.last["omission"] = rpe
        target = sleep_levels or {}
        a = 1.0 - math.exp(-dt / p["tau_tonic"]) if p["tau_tonic"] > 0 else 1.0
        for k in LEVEL_KEYS:
            self.tonic[k] += a * (_finite(target.get(k, 1.0), 1.0) - self.tonic[k])
            tau = p["tau_da"] if k == "DA" else p["tau_ne"] if k == "NE" else p["tau_other"]
            self.phasic[k] *= math.exp(-dt / tau)
        self.vol *= math.exp(-dt / p["tau_vol"])
        return self.levels

    # -- gain ------------------------------------------------------------------------------------------------
    def region_gain(self, levels=None, n=None):
        return region_gain(self.levels if levels is None else levels,
                           receptors=self.receptors, n=n)

    # -- persistence -----------------------------------------------------------------------------------------
    _STATE = ("t", "tonic", "phasic", "V", "n_buys", "ibi", "since_buy", "last_buy_t", "next_omit",
              "flow_mean", "vol")

    def to_dict(self):
        return {k: getattr(self, k) for k in self._STATE}

    def _load(self, d):
        for k in self._STATE:
            if k in d:
                v = d[k]
                setattr(self, k, dict(v) if isinstance(v, dict) else v)

    @classmethod
    def from_dict(cls, d, **kw):
        return cls(state=d, **kw)
