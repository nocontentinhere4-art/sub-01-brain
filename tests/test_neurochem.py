"""Tests for twin/neurochem.py (digital twin model of one real person's brain structure and recorded activity;
not a mind, not conscious, not the person).

    python -m pytest tests/test_neurochem.py -q
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from twin import neurochem as nc  # noqa: E402
from twin.neurochem import LEVEL_KEYS, RECEPTORS, Neuromodulators, region_gain  # noqa: E402

BASE = {k: 1.0 for k in LEVEL_KEYS}


def lv(**kw):
    d = dict(BASE)
    for k, v in kw.items():
        d[{"HT": "5HT"}.get(k, k)] = v
    return d


# --- receptor data ---------------------------------------------------------------------------------------------
def test_receptor_csv_matches_atlas_order():
    names = json.load(open(ROOT / "out" / "atlas_names.json"))
    rows = list(csv.DictReader(open(ROOT / "twin" / "data" / "receptors_214.csv")))
    assert [r["name"] for r in rows] == names
    assert nc.RECEPTORS_FROM_DATA
    for r in RECEPTORS.values():
        assert r.shape == (214,) and np.all(r >= 0) and np.all(r <= 1)
    # cortical rows carry data, subcortical rows are blank and flagged as fallback
    assert all(rows[i]["D1_fmol_mg"] for i in range(200))
    assert not any(rows[i]["D1_fmol_mg"] for i in range(200, 214))
    assert set(nc.RECEPTOR_SOURCE[200:]) == {"fallback_cortical_mean"}
    assert all(s.startswith("autoradiography") for s in nc.RECEPTOR_SOURCE[:200])


def test_receptor_maps_are_not_uniform_in_cortex():
    for r, d in RECEPTORS.items():
        assert np.std(d[:200]) > 0.03, r            # real regional specificity in cortex
        assert np.ptp(d[200:]) == 0.0, r            # subcortical fallback carries none


# --- gain ------------------------------------------------------------------------------------------------------
def test_baseline_gain_is_exactly_one():
    g = region_gain(BASE)
    assert g.shape == (214,)
    assert np.array_equal(g, np.ones(214))
    assert np.array_equal(Neuromodulators().region_gain(), np.ones(214))


@pytest.mark.parametrize("value", [0.0, 0.1, 3.0, 10.0, 100.0])
def test_gain_bounded(value):
    for k in LEVEL_KEYS:
        g = region_gain(lv(**{k: value}))
        assert np.all(g >= 1 - nc.GAIN_SPAN) and np.all(g <= 1 + nc.GAIN_SPAN)
        if value <= 3.0:                                           # realistic levels stay strictly inside
            assert np.all(g > 1 - nc.GAIN_SPAN) and np.all(g < 1 + nc.GAIN_SPAN)
    g = region_gain({k: value for k in LEVEL_KEYS})
    assert np.all(np.isfinite(g)) and np.all(g >= 1 - nc.GAIN_SPAN) and np.all(g <= 1 + nc.GAIN_SPAN)


def test_da_gain_follows_d1_density_real_maps():
    dg = region_gain(lv(DA=1.5)) - 1.0
    assert np.all(dg > 0)                                           # D1 is excitatory
    d1 = RECEPTORS["D1"]
    order = np.argsort(d1)
    assert np.all(np.diff(dg[order]) >= -1e-12)                     # monotone in D1 density
    assert np.corrcoef(dg, d1)[0, 1] > 0.99
    dg_down = region_gain(lv(DA=0.5)) - 1.0
    assert np.all(dg_down < 0)


def test_receptor_weighted_signs_synthetic():
    lo, hi = 0.2, 0.8
    rec = {r: np.array([0.5, 0.5]) for r in nc.RECEPTOR_EFFECTS}
    # 5-HT: region 1 has more 5-HT2A (excitatory) -> larger gain increase; 5-HT1A (inhibitory) the opposite
    r1 = dict(rec, **{"5HT2": np.array([lo, hi])})
    dg = region_gain(lv(HT=2.0), receptors=r1) - 1
    assert dg[1] > dg[0] and dg[1] > 0
    r2 = dict(rec, **{"5HT1a": np.array([lo, hi])})
    dg = region_gain(lv(HT=2.0), receptors=r2) - 1
    assert dg[1] < dg[0] and dg[1] < 0
    # NE: alpha1 excitatory, alpha2 inhibitory
    dg = region_gain(lv(NE=2.0), receptors=dict(rec, a1=np.array([lo, hi]))) - 1
    assert dg[1] > dg[0] and dg[1] > 0          # low-alpha1 region with average alpha2 may be net inhibitory
    dg = region_gain(lv(NE=2.0), receptors=dict(rec, a2=np.array([lo, hi]))) - 1
    assert dg[1] < dg[0]
    # ACh: M1 and alpha4beta2 excitatory
    for r in ("M1", "a4b2"):
        dg = region_gain(lv(ACh=2.0), receptors=dict(rec, **{r: np.array([lo, hi])})) - 1
        assert dg[1] > dg[0] > 0
    # DA: D1 excitatory
    dg = region_gain(lv(DA=2.0), receptors=dict(rec, D1=np.array([lo, hi]))) - 1
    assert dg[1] > dg[0] > 0


def test_ne_increases_mean_gain_and_sleep_like_levels_lower_it():
    assert region_gain(lv(NE=2.0)).mean() > 1.05
    nrem = {"DA": 0.8, "5HT": 0.6, "NE": 0.5, "ACh": 0.4}
    assert region_gain(nrem).mean() < 0.9


def test_gain_other_n_is_uniform():
    g = region_gain(lv(DA=2.0), n=68)
    assert g.shape == (68,) and np.ptp(g) == 0 and g[0] > 1


# --- dynamics --------------------------------------------------------------------------------------------------
def test_rpe_habituation_repeated_identical_pumps():
    m = Neuromodulators()
    das = []
    for i in range(8):
        das.append(m.on_trade("buy", 200.0, t=10.0 * i)["da"])
        m.update(10.0)
    assert all(b < a for a, b in zip(das, das[1:]))
    assert das[-1] < 0.25 * das[0]


def test_surprise_gives_larger_da():
    m = Neuromodulators()
    for i in range(10):
        m.on_trade("buy", 50.0, t=10.0 * i)
        m.update(10.0)
    usual = m.on_trade("buy", 50.0, t=100.0)["da"]
    m2 = Neuromodulators(state=m.to_dict())
    big = m2.on_trade("buy", 5000.0, t=100.0)["da"]
    assert big > 3 * max(usual, 1e-3)
    # a smaller-than-expected pump is a negative RPE -> DA below its pre-trade value
    m3 = Neuromodulators(state=m.to_dict())
    before = m3.levels["DA"]
    assert m3.on_trade("buy", 1.0, t=100.0)["rpe"] < 0
    assert m3.levels["DA"] < before


def test_rpe_is_not_price_level():
    # identical sizes -> same RPE sequence regardless of the absolute time/clock
    a, b = Neuromodulators(), Neuromodulators()
    ra = [a.on_trade("buy", 100.0, t=1000.0 + 5 * i)["rpe"] for i in range(4)]
    rb = [b.on_trade("buy", 100.0, t=1e9 + 5 * i)["rpe"] for i in range(4)]
    assert np.allclose(ra, rb)


def test_omitted_expected_pump_gives_small_dip():
    m = Neuromodulators()
    first = None
    for i in range(8):                               # regular pumps every 10 s
        r = m.on_trade("buy", 200.0, t=10.0 * i)
        first = r["da"] if first is None else first
        for _ in range(10):
            m.update(1.0)
    dips = []
    for _ in range(40):                              # no pump comes
        m.update(0.5)
        dips.append(m.last["omission"])
    fired = [d for d in dips if d < 0]
    assert fired, "expected an omission dip"
    assert 0.85 < m.levels["DA"] < 1.0                # small dip, not a crash
    assert abs(nc.DEFAULTS["k_da_omit"] * fired[0]) < 0.5 * first   # smaller than the first surprise burst
    # no dip without a learned expectation
    m2 = Neuromodulators()
    m2.on_trade("buy", 200.0, t=0.0)
    for _ in range(200):
        m2.update(1.0)
        assert m2.last["omission"] == 0.0


def test_dumps_and_volatility_raise_ne():
    m = Neuromodulators()
    r = m.on_trade("sell", 500.0, t=0.0)
    assert r["ne"] > 0 and m.levels["NE"] > 1.0
    assert r["da"] == 0.0
    # volatile (alternating big buys/sells) vs steady (identical small buys): NE higher after volatile flow
    vol, steady = Neuromodulators(), Neuromodulators()
    for i in range(20):
        vol.on_trade("buy" if i % 2 else "sell", 2000.0, t=5.0 * i)
        steady.on_trade("buy", 20.0, t=5.0 * i)
        vol.update(5.0)
        steady.update(5.0)
    assert vol.levels["NE"] > steady.levels["NE"] + 0.2
    assert vol.vol > 3 * steady.vol


def test_sleep_levels_applied_and_phasic_decays():
    m = Neuromodulators()
    rem = {"DA": 1.0, "5HT": 0.1, "NE": 0.05, "ACh": 1.3}
    for _ in range(400):
        lv_ = m.update(1.0, rem)
    for k in LEVEL_KEYS:
        assert lv_[k] == pytest.approx(rem[k], abs=1e-3)
    # back to wake when the sleep engine gives nothing
    for _ in range(400):
        lv_ = m.update(1.0, None)
    assert all(lv_[k] == pytest.approx(1.0, abs=1e-3) for k in LEVEL_KEYS)
    # phasic DA decays with tau_da
    m.on_trade("buy", 1000.0, t=0.0)
    p0 = m.phasic["DA"]
    m.update(nc.DEFAULTS["tau_da"])
    assert m.phasic["DA"] == pytest.approx(p0 * np.exp(-1), rel=1e-6)
    for _ in range(60):
        m.update(1.0)
    assert abs(m.levels["DA"] - 1.0) < 1e-3
    # NE phasic suppressed when tonic NE is low (REM-like): same dump -> smaller NE excursion
    wake, rem_m = Neuromodulators(), Neuromodulators()
    for _ in range(400):
        rem_m.update(1.0, rem)
    wake.on_trade("sell", 1000.0, t=0.0)
    rem_m.on_trade("sell", 1000.0, t=0.0)
    assert (rem_m.levels["NE"] - rem["NE"]) < 0.2 * (wake.levels["NE"] - 1.0)


def test_state_roundtrip():
    m = Neuromodulators()
    for i in range(5):
        m.on_trade("buy", 100.0 * (i + 1), t=3.0 * i)
        m.update(3.0, {"ACh": 1.2})
    m2 = Neuromodulators.from_dict(json.loads(json.dumps(m.to_dict())))
    assert m2.levels == m.levels
    assert np.array_equal(m2.region_gain(), m.region_gain())


def test_bad_inputs_never_poison_state():
    # NaN / inf / None from a bad trade feed or sleep engine must not enter the state or the gain
    m = Neuromodulators()
    for bad in (float("nan"), float("inf"), -float("inf"), None, "x"):
        assert m.on_trade("buy", bad, t=0.0) == {"rpe": 0.0, "da": 0.0, "ne": 0.0}
        assert m.on_trade("sell", bad) == {"rpe": 0.0, "da": 0.0, "ne": 0.0}
    m.on_trade("buy", 1e30, t=float("nan"))                      # huge size clipped, NaN time ignored
    m.update(float("nan"), {"DA": float("nan"), "NE": None, "ACh": float("inf")})
    m.update(1.0, {"DA": float("nan")})
    assert all(np.isfinite(v) for v in m.levels.values())
    assert np.all(np.isfinite(m.region_gain()))
    assert np.all(np.isfinite(region_gain({"DA": float("nan"), "NE": float("inf"), "5HT": None})))
    assert np.array_equal(region_gain({"DA": float("nan"), "NE": float("inf")}), np.ones(214))
