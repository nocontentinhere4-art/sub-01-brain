"""All parameters of the spiking model in one place (units: ms, mV, Hz, mm).

The network is built deterministically from (structural parameters, seed): the same config gives the same
synapses on CPU and GPU, so learned weights saved after one session load into the next one.
"""
import hashlib
import json
from dataclasses import asdict, dataclass, field, fields

VERSION = 1


@dataclass
class Config:
    # --- size ---------------------------------------------------------------------------------------
    n_neurons: int = 20_000
    seed: int = 1
    frac_exc: float = 0.8
    min_region: int = 10                # smallest population (at 20k the smallest nucleus gets ~11)
    hc_scale: float = 1.0               # test-only: enlarge hippocampal populations (small nets: sparse codes need room)
    # --- fixed in-degree per neuron (Brunel-style: same input statistics in every region, any N) ----------
    k_e_local: int = 45                 # excitatory, same region
    k_i_local: int = 25                 # inhibitory, same region
    k_long: int = 30                    # excitatory, other regions, source region ~ streamline counts
    k_hc_rec: int = 100                 # extra E->E recurrent collaterals for hippocampal E (CA3-like)
    k_hc_rec_i: int = 100               # ...and onto hippocampal interneurons (feedback inhibition tracks assemblies)
    k_vis_sm: int = 0                   # POSITIVE CONTROL ONLY (not the real wiring): direct visual -> somatomotor E->E
    j_vis_sm: float = 0.1               # initial weight of that hypothetical projection (plastic)
    # --- LIF neuron ------------------------------------------------------------------------------------
    dt: float = 1.0
    tau_m: float = 20.0
    v_th: float = 20.0
    v_reset: float = 10.0
    t_ref: float = 2.0
    # --- synapses: instantaneous PSP jumps (mV) ----------------------------------------------------------
    j_e: float = 0.5                    # E -> any
    g_i: float = 5.0                    # I -> any = -g_i * j_e
    j_hc_rec: float = 0.05              # initial hippocampal recurrent collateral weight
    j_hc_ei: float = 0.3                # collateral -> interneuron weight (fixed)
    delay_local: tuple = (1, 2)         # ms, uniform integer
    velocity_mm_ms: float = 6.0         # 6 m/s conduction velocity -> delay = fibre length / v
    # --- background drive: tau dV/dt = -V + mu + sigma*sqrt(tau)*xi -----------------------------------------
    mu_ext: float = 15.0                # mV (resting level the external input alone would reach)
    sigma_ext: float = 4.0              # mV
    baseline_gain: float = 0.05         # mu *= 1 + gain * z_region(t), z = recorded resting-state BOLD (z-scored)
    baseline_dt_ms: int = 50            # how often the recorded drive is refreshed
    # --- plasticity (three-factor STDP) -----------------------------------------------------------------
    plastic: bool = True
    tau_plus: float = 20.0
    tau_minus: float = 20.0
    a_plus: float = 1.0
    a_minus: float = 0.5
    x_theta: float = 0.1                # presynaptic trace threshold (= trace of a 5 Hz Poisson neuron)
    h_pre: float = 0.10                 # heterosynaptic depression per presynaptic spike
    tau_elig: float = 1000.0            # eligibility trace (bridges the delay to a reward, Izhikevich 2007)
    elig_every: int = 10                # trace decay / weight update period (steps)
    tau_da: float = 200.0               # phasic dopamine decay
    w_max_ctx: float = 2.0              # mV, upper bound of plastic cortical (non-hippocampal) E->E weights
    w_max_hc: float = 2.0               # mV, upper bound of plastic hippocampal E->E weights
    # learning rates per synapse class. "da": mV per (unit dopamine x unit eligibility x s) (three-factor STDP);
    # "enc" / "cons": fast Hebbian rate rule for memory, mV per (Hz x Hz x s) on rates above baseline
    eta: dict = field(default_factory=lambda: {
        "ctx": {"da": 0.5, "enc": 0.0005, "cons": 0.002},
        "hc": {"da": 0.0, "enc": 0.025, "cons": 0.0},
    })
    da_groups: tuple = ("somatomotor",)  # dopamine-gated plasticity only at synapses onto these neurons (M1-like;
                                        # Hosp et al. 2011: M1 dopamine is needed for motor skill learning)
    hebb_theta: float = 10.0            # Hz above baseline: pre must exceed it; post above it potentiates, below depresses
    hebb_ltd: float = 0.25              # depression (post below theta) is 4x weaker than potentiation
    homeo_every: int = 1000             # steps between homeostatic updates
    rate_target: float = 5.0            # Hz
    tau_rate: float = 10_000.0          # ms, rate estimate for homeostasis
    eta_theta: float = 0.0001           # mV per Hz error per update (intrinsic excitability; ~0.5 mV per hour)
    theta_max: float = 3.0              # mV bound on the intrinsic offset
    eta_scale: float = 0.0001           # (~10 % per hour at 30 % rate error) synaptic scaling of plastic weights per update, per relative rate error
    tau_forget_hc_days: float = 3.0     # learned hippocampal weights decay between sessions
    tau_forget_ctx_days: float = 60.0   # learned cortical weights decay (much slower)

    STRUCTURAL = ("n_neurons", "seed", "frac_exc", "min_region", "hc_scale", "k_e_local", "k_i_local", "k_long", "k_hc_rec", "k_hc_rec_i", "k_vis_sm",
                  "dt", "j_e", "g_i", "j_hc_rec", "j_hc_ei", "j_vis_sm", "delay_local", "velocity_mm_ms")

    def config_hash(self):
        """Identity of the synapse set: learned weights only load into a network with the same hash."""
        d = {k: getattr(self, k) for k in self.STRUCTURAL}
        d["version"] = VERSION
        return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        names = {f.name for f in fields(cls)}
        return cls(**{k: (tuple(v) if k in ("delay_local", "da_groups") else v) for k, v in d.items() if k in names})


def small(**kw):
    return Config(n_neurons=20_000, **kw)


def full(**kw):
    return Config(n_neurons=1_000_000, **kw)
