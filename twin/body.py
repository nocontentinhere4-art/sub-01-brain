"""A minimal body for the SUB-01 digital twin: heart rate, breathing, blood glucose, hunger, interoceptive drive.

This is a digital twin model of one real person's brain structure and recorded activity, plus a deliberately small
body model so the brain model receives a hunger signal. Not a mind, not conscious, not the person. The parameters
are textbook adult values (see docs/twin/body.md for equations, sources and what is not realistic); none are fitted
to the recorded person.

Public interface (docs/twin_contracts.md): Body(state=None); update(dt_sim, levels, amygdala, stage); eat(carbs_g);
vitals(); hunger (0..1); intero_drive() -> {group: amount}; to_dict()/from_dict().
"""
import math

import numpy as np

# ---- autonomic model: HR = HR_intrinsic - A_V * vagal + A_S * sympathetic (after Berntson et al. 1991/1993) ----
HR_INTRINSIC = 95.0     # bpm, intrinsic rate of a ~40 y adult: 118.1 - 0.57 * age (Jose & Collison 1970)
A_VAGAL = 45.0          # bpm per unit vagal tone (full pharmacological vagal block raises HR by ~30-40 bpm)
A_SYMP = 70.0           # bpm per unit sympathetic tone
# resting autonomic tone per stage: (sympathetic, vagal). AWAKE is daytime wake (not supine rest). NREM: vagal dominance,
# low sympathetic, HR a few bpm below relaxed wake (Somers 1993; Trinder 2001); REM: sympathetic surges, vagal tone
# lower than NREM, mean HR above NREM and near relaxed wake, with large variability (Somers 1993; Trinder 2001).
TONE = {"AWAKE": (0.15, 0.75), "NREM": (0.04, 0.88), "REM": (0.10, 0.85)}
TAU_SYMP, TAU_VAGAL = 20.0, 5.0       # s, sympathetic effects are slow, vagal effects fast (Berger 1989)
K_NE, K_AMYG = 0.30, 0.30             # sympathetic tone per unit NE excess (NE level - 1) / amygdala excess
HR_NOISE_SD = {"AWAKE": 1.5, "NREM": 0.8, "REM": 3.5}           # bpm, slow beat-to-beat-scale variability
# breaths/min: in NREM ventilation falls ~13-15 % mainly through tidal volume, rate nearly unchanged (Douglas 1982);
# REM breathing is faster and irregular, more so with dense eye movements (Douglas 1982; Gould 1988)
RESP_BASE = {"AWAKE": 14.5, "NREM": 14.0, "REM": 15.0}
RESP_NOISE_SD = {"AWAKE": 1.0, "NREM": 0.35, "REM": 2.2}        # slow, regular in NREM, irregular in REM
NOISE_TAU = 30.0                                                # s, correlation time of the variability

# ---- glucose: Bergman minimal model + two-compartment gut (Bergman 1979; Dalla Man 2006) ----
BW = 70.0               # kg
VG = 1.88               # dl/kg, glucose distribution volume (Dalla Man 2007)
KGRI, KABS = 0.056, 0.057   # 1/min, stomach emptying (kmax) and gut absorption (Dalla Man 2007, healthy subjects)
F_ABS = 0.45            # net fraction of ingested carbohydrate reaching plasma (f = 0.9 absorbed, Dalla Man 2007, minus first-pass splanchnic uptake; tuned)
P1, P2, P3 = 0.03, 0.02, 2.0e-5     # 1/min, 1/min, 1/min^2 per uU/ml (Bergman 1979 range; P3 tuned)
N_INS, GAMMA = 0.27, 0.030          # insulin clearance 1/min; secretion uU/ml/min^2 per mg/dl above set-point (tuned)
I_BASAL = 8.0           # uU/ml, fasting insulin
# mg/dl, h: fasting set-point decays slowly toward the floor (glycogen use): ~85 after an overnight fast, ~80 at 24 h,
# ~72 at 72 h, roughly the fall reported in prolonged fasting (Cahill 1970); phenomenological, not a liver model
G_START, G_FLOOR, TAU_FAST_H = 92.0, 70.0, 30.0
K_EXERCISE = 0.0010     # 1/min extra insulin-independent uptake at full exertion (muscle contraction)

# ---- hunger: gut/ghrelin-like proxy + glucose term (Cummings 2001: ghrelin rises before meals, falls after) ----
TAU_GHRELIN_H = 5.0     # h, rise towards 1 when not eating
GHRELIN_SUPPRESS_G = 35.0   # g carbohydrate for an e-fold suppression of the proxy
W_GHRELIN, W_GLUCOSE = 0.6, 0.4
GLUCOSE_HUNGER = (100.0, 30.0)      # glucose term = clip((100 - G) / 30, 0, 1)

# interoceptive drive (brain stimulus units, same scale as live_server's stimulate amounts)
INSULA_GAIN = {"glucose": 2.0, "hr": 1.0, "hunger": 0.5}


def _clip(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


class Body:
    def __init__(self, state=None, rng=None):
        s = state or {}
        self.rng = rng or np.random.default_rng(s.get("seed", 0))
        self.q_sto = s.get("q_sto", 0.0)         # mg carbohydrate in the stomach
        self.q_gut = s.get("q_gut", 0.0)         # mg in the gut
        self.glucose = s.get("glucose", G_START)  # mg/dl
        self.insulin = s.get("insulin", I_BASAL)  # uU/ml
        self.x = s.get("x", 0.0)                  # remote insulin action (1/min)
        self.since_meal_h = s.get("since_meal_h", 3.0)   # h since the last meal (sets the fasting set-point)
        self.ghrelin = s.get("ghrelin", 0.4)      # 0..1 gut/ghrelin-like proxy
        self.symp = s.get("symp", TONE["AWAKE"][0])
        self.vagal = s.get("vagal", TONE["AWAKE"][1])
        self.hr_noise = s.get("hr_noise", 0.0)
        self.resp_noise = s.get("resp_noise", 0.0)
        self.stage = s.get("stage", "AWAKE")
        self._hr = s.get("hr", 70.0)
        self._resp = s.get("resp", RESP_BASE["AWAKE"])

    # ---- glucose ------------------------------------------------------------------------------------
    def eat(self, carbs_g):
        """Ingest carbohydrate (grams): enters the stomach compartment and suppresses the hunger proxy."""
        carbs_g = max(0.0, float(carbs_g))
        self.q_sto += carbs_g * 1000.0
        self.ghrelin *= math.exp(-carbs_g / GHRELIN_SUPPRESS_G)
        if carbs_g >= 10:
            self.since_meal_h = 0.0

    def setpoint(self):
        return G_FLOOR + (G_START - G_FLOOR) * math.exp(-self.since_meal_h / TAU_FAST_H)

    def _glucose_step(self, h, exertion):
        """One Euler step of h seconds."""
        m = h / 60.0                                            # minutes
        gset = self.setpoint()
        ra = F_ABS * KABS * self.q_gut / BW / VG                # mg/dl/min
        up_exercise = K_EXERCISE * exertion * self.glucose
        dg = -P1 * (self.glucose - gset) - self.x * self.glucose - up_exercise + ra
        dq_sto = -KGRI * self.q_sto
        dq_gut = KGRI * self.q_sto - KABS * self.q_gut
        di = -N_INS * (self.insulin - I_BASAL) + GAMMA * max(self.glucose - gset, 0.0)
        dx = -P2 * self.x + P3 * (self.insulin - I_BASAL)
        self.glucose = _clip(self.glucose + dg * m, 40.0, 400.0)
        self.q_sto = max(0.0, self.q_sto + dq_sto * m)
        self.q_gut = max(0.0, self.q_gut + dq_gut * m)
        self.insulin = max(0.0, self.insulin + di * m)
        self.x = max(0.0, self.x + dx * m)

    # ---- hunger -------------------------------------------------------------------------------------
    @property
    def hunger(self):
        """0..1. Mostly a gut/ghrelin-like time-since-meal proxy plus a glucose term (hunger is not a glucose threshold)."""
        lo, span = GLUCOSE_HUNGER
        gl = _clip((lo - self.glucose) / span, 0.0, 1.0)
        return _clip(W_GHRELIN * self.ghrelin + W_GLUCOSE * gl, 0.0, 1.0)

    # ---- autonomic ------------------------------------------------------------------------------------
    def update(self, dt_sim, levels=None, amygdala=0.0, stage="AWAKE", exertion=0.0):
        """Advance the body dt_sim seconds. levels: neuromodulator dict (uses "NE", 1.0 = resting wake);
        amygdala: amygdala activity excess over its resting level (0 = baseline, ~1 = strongly active);
        stage: AWAKE / NREM / REM (N1-N3 map to NREM); exertion 0..1 (walking ~0.3)."""
        dt = max(0.0, float(dt_sim))
        stage = stage if stage in TONE else ("REM" if str(stage).upper().startswith("REM") else
                                              "AWAKE" if str(stage).upper() in ("AWAKE", "WAKE") else "NREM")
        self.stage = stage
        n = max(1, min(400, math.ceil(dt / 60.0)))
        h = dt / n
        for _ in range(n):
            self._glucose_step(h, exertion)
        dth = dt / 3600.0
        self.since_meal_h += dth
        self.ghrelin += (1.0 - self.ghrelin) * (1.0 - math.exp(-dth / TAU_GHRELIN_H))
        # autonomic tone targets
        ne = float((levels or {}).get("NE", 1.0))
        s0, v0 = TONE[stage]
        hypo = max(0.0, (70.0 - self.glucose) / 20.0)           # sympathoadrenal counter-regulation
        s_t = _clip(s0 + K_NE * (ne - 1.0) + K_AMYG * max(0.0, amygdala) + 0.35 * exertion + 0.3 * hypo, 0.0, 1.0)
        v_t = _clip(v0 - 0.6 * (s_t - s0), 0.0, 1.0)
        self.symp += (s_t - self.symp) * (1.0 - math.exp(-dt / TAU_SYMP))
        self.vagal += (v_t - self.vagal) * (1.0 - math.exp(-dt / TAU_VAGAL))
        # slow variability: Ornstein-Uhlenbeck, exact discretisation, stage-dependent amplitude
        a = math.exp(-dt / NOISE_TAU)
        for attr, sd in (("hr_noise", HR_NOISE_SD[stage]), ("resp_noise", RESP_NOISE_SD[stage])):
            setattr(self, attr, getattr(self, attr) * a + sd * math.sqrt(1 - a * a) * self.rng.standard_normal())
        self._hr = _clip(HR_INTRINSIC - A_VAGAL * self.vagal + A_SYMP * self.symp + self.hr_noise, 38.0, 190.0)
        resp = RESP_BASE[stage] + 9.0 * (self.symp - s0) + self.resp_noise
        self._resp = _clip(resp, 6.0, 35.0)

    def vitals(self):
        return {"hr_bpm": round(self._hr, 1), "resp_per_min": round(self._resp, 1),
                "glucose_mg_dl": round(self.glucose, 1)}

    # ---- body -> brain --------------------------------------------------------------------------------
    def intero_drive(self):
        """Stimulus amounts for brain.stimulate. The atlas has no hypothalamus (214 = Schaefer-200 + 14 Harvard-Oxford
        subcortical), so all interoceptive input goes to the anterior insula / frontal operculum proxy, the
        group "insula" = SalVentAttn_FrOperIns parcels (brain_sim.GROUPS). Zero at resting, fed values."""
        low_g = _clip((85.0 - self.glucose) / 25.0, 0.0, 1.0)
        hi_hr = _clip((self._hr - 80.0) / 30.0, 0.0, 1.0)
        hungry = max(0.0, self.hunger - 0.4) / 0.6
        amount = (INSULA_GAIN["glucose"] * low_g + INSULA_GAIN["hr"] * hi_hr + INSULA_GAIN["hunger"] * hungry)
        return {"insula": round(amount, 3)} if amount > 0 else {}

    # ---- persistence ----------------------------------------------------------------------------------
    def to_dict(self):
        return {"q_sto": self.q_sto, "q_gut": self.q_gut, "glucose": self.glucose, "insulin": self.insulin,
                "x": self.x, "since_meal_h": self.since_meal_h, "ghrelin": self.ghrelin, "symp": self.symp,
                "vagal": self.vagal, "hr_noise": self.hr_noise, "resp_noise": self.resp_noise,
                "stage": self.stage, "hr": self._hr, "resp": self._resp}

    @classmethod
    def from_dict(cls, d, rng=None):
        return cls(d, rng=rng)
