"""Tests for the minimal body (twin/body.py) and its link to Life.   python -m pytest tests/test_body.py -q"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from life import CARBS_PER_BREAD_G, Life
from twin.body import Body


def run(b, seconds, step=30.0, **kw):
    for _ in range(int(seconds / step)):
        b.update(step, **kw)


def mean_hr(stage, n=400, seed=1, **kw):
    b = Body(rng=np.random.default_rng(seed))
    run(b, 600, stage=stage, **kw)
    v = []
    for _ in range(n):
        b.update(30.0, stage=stage, **kw)
        v.append(b.vitals())
    return np.mean([x["hr_bpm"] for x in v]), np.mean([x["resp_per_min"] for x in v]), \
        np.std([x["hr_bpm"] for x in v]), np.std([x["resp_per_min"] for x in v])


def test_meal_curve():
    for carbs in (30, 60):
        b = Body({"since_meal_h": 0.0, "ghrelin": 0.1})
        b.eat(carbs)
        g = []
        for _ in range(48):                       # 4 h in 5 min steps
            g.append(b.glucose)
            b.update(300)
        peak_min = 5 * int(np.argmax(g))
        assert 25 <= peak_min <= 65
        assert 110 < max(g) < 190
        assert g[24] < 100 and g[36] < 92          # near fasting after 2-3 h
        assert min(g) > 65


def test_24h_loop_with_meals():
    b = Body(rng=np.random.default_rng(3))
    meals = {7 * 3600: 50, 12.5 * 3600: 70, 19.5 * 3600: 70}
    t, step = 0.0, 60.0
    gl, hu = [], []
    pre, post = {}, {}
    while t < 24 * 3600:
        if t in meals:
            pre[t] = (b.glucose, b.hunger)
            b.eat(meals[t])
        stage = "NREM" if t < 6.5 * 3600 or t >= 23 * 3600 else "AWAKE"
        b.update(step, stage=stage)
        t += step
        gl.append(b.glucose)
        hu.append(b.hunger)
        if t - 3600 in meals:
            post[t - 3600] = b.hunger
    assert 55 < min(gl) and max(gl) < 190
    assert all(0.0 <= h <= 1.0 for h in hu)
    for m in meals:
        assert post[m] < pre[m][1] + 0.05 or post[m] < 0.35     # eating lowers hunger
    # hunger rises as time since the last meal passes (and glucose falls) while fasting
    c = Body({"since_meal_h": 0.0, "ghrelin": 0.05})
    h0, g0 = c.hunger, c.glucose
    run(c, 6 * 3600, step=60)
    assert c.hunger > h0 + 0.3
    assert c.glucose < g0
    assert c.glucose > 65


def test_eating_raises_glucose_and_lowers_hunger():
    b = Body({"since_meal_h": 8.0, "ghrelin": 0.9, "glucose": 76.0})
    h, g = b.hunger, b.glucose
    b.eat(60)
    run(b, 1800)
    assert b.glucose > g + 25
    assert b.hunger < h - 0.2


def test_hr_stage_and_arousal():
    awake, resp_a, sd_a, rsd_a = mean_hr("AWAKE")
    nrem, resp_n, sd_n, rsd_n = mean_hr("NREM")
    rem, resp_r, sd_r, rsd_r = mean_hr("REM")
    assert 60 <= awake <= 78
    assert 45 <= nrem < awake - 8
    assert nrem + 2 < rem < awake                           # REM above NREM, not above daytime wake
    assert sd_r > sd_n and rsd_r > rsd_n                    # REM more variable than NREM
    assert 12 <= resp_a <= 18
    assert 12 <= resp_n < resp_a and rsd_n < rsd_a          # NREM: rate about the same, more regular
    assert 12 <= resp_r <= 19
    ne_hi = mean_hr("AWAKE", levels={"NE": 1.5})
    amy_hi = mean_hr("AWAKE", amygdala=1.0)
    both = mean_hr("AWAKE", levels={"NE": 1.6}, amygdala=1.0)
    assert ne_hi[0] > awake + 8 and amy_hi[0] > awake + 8
    assert 85 < both[0] <= 125 and both[1] > resp_a + 2 and both[1] <= 30


def test_intero_drive():
    fed = Body({"ghrelin": 0.1})
    assert fed.intero_drive() == {}
    low = Body({"glucose": 62.0, "ghrelin": 0.9, "since_meal_h": 12.0})
    d = low.intero_drive()
    assert d["insula"] > 1.0
    from brain_sim import GROUPS
    assert "insula" in GROUPS


def test_persistence_round_trip():
    b = Body(rng=np.random.default_rng(5))
    b.eat(40)
    run(b, 1200, levels={"NE": 1.2}, amygdala=0.3)
    c = Body.from_dict(b.to_dict())
    assert c.to_dict() == b.to_dict()
    assert c.vitals() == b.vitals() and c.hunger == b.hunger
    import json
    assert Body.from_dict(json.loads(json.dumps(b.to_dict()))).glucose == b.glucose


def test_life_buys_bread_and_eats():
    body = Body({"since_meal_h": 9.0, "ghrelin": 0.95, "glucose": 74.0})
    life = Life(state={"place": "window", "activity": "window", "until": 0.0, "bread": 0}, rng=random.Random(2),
                body=body)
    assert life.hunger > 0.6
    from sleep import ROME
    from datetime import datetime
    t = datetime(2026, 10, 5, 9, 0, tzinfo=ROME).timestamp()
    acts, h0, ate = [], life.hunger, False
    for _ in range(60 * 3):                       # 3 sim hours, 1 s real = 60 sim s
        body.update(60.0, stage="AWAKE", exertion=life.exertion())
        life.update(t, 0.5 * 60, 60.0, "AWAKE", {}, 0.0, 0.0)
        t += 60.0
        acts.append(life.activity)
        if "eat" in acts and life.activity != "eat" and not ate:
            ate = True
            break
    assert "buy_bread" in acts and "eat" in acts
    assert acts.index("buy_bread") < acts.index("eat")
    run(body, 1800)
    assert life.hunger < h0 - 0.2
    assert body.glucose > 85
    assert life.snapshot()["hunger"] == round(life.hunger, 2)
    assert CARBS_PER_BREAD_G > 0


def test_life_without_body_and_legacy_state():
    life = Life(rng=random.Random(1))              # owns its body
    assert 0 <= life.hunger <= 1
    h0 = life.hunger
    for i in range(120):
        life.update(1.7e9 + 60 * i, 1.0, 60.0, "AWAKE", {}, 0.0, 0.0)
    d = life.to_dict()
    assert "body" in d and "hunger" in d
    again = Life(d, rng=random.Random(1))
    assert abs(again.hunger - life.hunger) < 1e-9
    legacy = Life({"hunger": 0.7})
    assert 0.3 < legacy.hunger < 0.7 and h0 is not None


def test_life_two_days_eats_a_few_times():
    """Life + its own body + the sleep engine for 2 simulated days (10 s steps): it eats a few times per waking day,
    never starves, never eats constantly, and glucose stays in a healthy range."""
    from datetime import datetime
    from sleep import ROME, SleepEngine, local
    t0 = datetime(2026, 10, 5, 7, 30, tzinfo=ROME).timestamp()
    for seed in (0, 1):
        eng = SleepEngine(t0, rng=random.Random(seed))
        eng.update(t0)
        life = Life(None, rng=random.Random(seed))
        life.time_scale = 10.0                              # 10 s sim per 1 s real step: walks at the same sim speed as live
        t, prev, eats, gl, hu = t0, life.activity, {}, [], []
        while t < t0 + 2 * 86400:
            t += 10.0
            eng.update(t, dt_real=1.0)
            life.update(t, 1.0, 10.0, eng.stage, {}, 0.0, eng.pressure(t))
            if life.activity != prev and life.activity == "eat":
                day = local(t).day
                eats[day] = eats.get(day, 0) + 1
            prev = life.activity
            gl.append(life.body.glucose)
            hu.append(life.hunger)
        assert len(eats) == 2 and all(3 <= n <= 8 for n in eats.values()), eats
        assert max(hu) < 0.95 and min(hu) > 0.05
        assert 70 < min(gl) and max(gl) < 180
