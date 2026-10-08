"""Issue #36: tastes learn faster (adaptive rate per topic, overnight replay of the day's largest prediction errors).

The measure: a simulated stream of stays drawn from hidden "true" topic values plus noise; how many stays until the
learned top 5 topics are the true top 5, and stay so for the rest of the run. Compared: the old fixed rate (0.2),
the adaptive rate, each with and without the night replay. `python tests/test_tastes_faster.py` prints the table.
"""
import json
import math
import random
import statistics

import tastes as T
from tastes import Tastes

DAY = 86400.0
T0 = 1_789_948_800.0                      # 09:00 Tokyo
N_NETS, N_WORDS = 7, 33
STAYS_PER_DAY = 120                       # one stay every 8 minutes over a 16 h day
NOISE = 0.1                               # sd of the stay response around the mean true value of its topics
HORIZON = 3000                            # 25 simulated days
HOLD = STAYS_PER_DAY // 2                 # "ranked": the top 5 stays right for half a day of stays
TOP = 5


class FixedTastes(Tastes):
    """The rule before #36: one fixed rate for every topic."""

    def gains(self, topics):
        return {t: T.ALPHA for t in topics}, {t: T.PRIOR_VAR for t in topics}


def world(seed):
    rng = random.Random(seed)
    nets = [f"net:{i}" for i in range(N_NETS)]
    words = [f"kw:{i}" for i in range(N_WORDS)]
    true = {t: max(-0.9, min(0.3, rng.gauss(0, 0.4))) for t in nets + words}
    for t in rng.sample(nets[:3] + words, TOP):                   # a clear top 5 (a near-tie at 5/6 has no answer)
        true[t] = rng.uniform(0.5, 0.9)
    pop = {t: 1.0 / (1 + i) ** 0.6 for i, t in enumerate(rng.sample(words, len(words)))}   # some words are common
    return rng, nets, words, true, pop


def stays(seed):
    rng, nets, words, true, pop = world(seed)
    wl, ww = list(pop), list(pop.values())
    for _ in range(HORIZON):
        topics = rng.sample(nets, rng.randint(1, 3))
        topics += list(dict.fromkeys(rng.choices(wl, ww, k=rng.randint(3, 5))))
        mean = sum(true[t] for t in topics) / len(topics)
        yield topics, math.tanh(mean + rng.gauss(0, NOISE))


def simulate(seed, adaptive=True, replay=True):
    """-> stays until the learned top 5 is the true top 5 and holds for HOLD stays in a row (HORIZON if never)."""
    _, _, _, true, _ = world(seed)
    best = set(sorted(true, key=true.get, reverse=True)[:TOP])
    now = [T0]
    t = (Tastes if adaptive else FixedTastes)(None, clock=lambda: now[0])
    good_since = None
    for i, (topics, r) in enumerate(stays(seed)):
        now[0] = T0 + (i // STAYS_PER_DAY) * DAY + (i % STAYS_PER_DAY) * (16 * 3600 / STAYS_PER_DAY)
        t.learn(topics, r)
        if replay and i % STAYS_PER_DAY == STAYS_PER_DAY - 1:      # the day's last stay: he falls asleep
            now[0] += 3600
            t.replay()
        if set(sorted(t.pref, key=t.pref.get, reverse=True)[:TOP]) == best:
            good_since = i + 1 if good_since is None else good_since
            if i + 1 - good_since >= HOLD:
                return good_since
        else:
            good_since = None
    return HORIZON


SEEDS = range(16)


def table(noise=None):
    global NOISE
    keep, NOISE = NOISE, noise if noise is not None else NOISE
    try:
        out = {}
        for name, adaptive, replay in [("fixed", False, False), ("fixed+replay", False, True),
                                       ("adaptive", True, False), ("adaptive+replay", True, True)]:
            v = [simulate(s, adaptive, replay) for s in SEEDS]
            out[name] = {"median": statistics.median(v), "mean": round(statistics.mean(v)),
                         "never": sum(x >= HORIZON for x in v)}
        return out
    finally:
        NOISE = keep


# --- tests ----------------------------------------------------------------------------------------------------------
def test_adaptive_is_faster_than_fixed_and_replay_helps():
    r = table()
    print(json.dumps(r, indent=1))
    assert all(v["never"] == 0 for v in r.values())
    assert r["adaptive"]["median"] < 0.6 * r["fixed"]["median"]
    assert r["fixed+replay"]["median"] < r["fixed"]["median"]
    assert r["adaptive+replay"]["mean"] < r["adaptive"]["mean"]


def test_first_stays_move_fast_and_known_topics_are_stable():
    now = [T0]
    t = Tastes(None, clock=lambda: now[0])
    assert t.learn(["kw:new"], 0.8) == 0.8 and t.pref["kw:new"] > 0.5                  # gain ~0.7 on a first stay
    for _ in range(40):
        t.learn(["kw:old"], 0.5)
    p = t.pref["kw:old"]
    t.learn(["kw:old"], -1.0)                                                          # one noisy stay
    assert 0 < p - t.pref["kw:old"] < 0.05 and t.alpha("kw:old") < 0.03
    assert t.alpha("kw:unknown") > 0.7


def test_the_error_goes_to_the_uncertain_topic():
    now = [T0]
    t = Tastes(None, clock=lambda: now[0])
    for _ in range(30):
        t.learn(["kw:old"], 0.0)
    t.learn(["kw:old", "kw:new"], 1.0)
    assert t.pref["kw:new"] > 10 * t.pref["kw:old"] > 0


def test_uncertainty_returns_with_time():
    now = [T0]
    t = Tastes(None, clock=lambda: now[0])
    for _ in range(30):
        t.learn(["kw:a"], 0.9)
    v = t.var["kw:a"]
    now[0] += T.TAU_DAYS * DAY
    t.decay()
    k2 = math.exp(-2)
    assert abs(t.var["kw:a"] - (k2 * v + (1 - k2) * T.PRIOR_VAR)) < 1e-9


def test_old_state_file_without_variances_loads(tmp_path):
    p = tmp_path / "tastes.json"
    p.write_text(json.dumps({"pref": {"kw:bread": 0.4, "net:reward": -0.2},
                             "seen": {"kw:bread": T0, "net:reward": T0}, "last": T0}))
    t = Tastes(p, clock=lambda: T0)
    assert t.var == {"kw:bread": T.LEGACY_VAR, "net:reward": T.LEGACY_VAR}
    assert abs(t.alpha("kw:bread") - T.ALPHA) < 1e-9                                   # the old rate, to start
    assert t.day_log == [] and t.last_replay is None
    t.learn(["kw:bread"], 1.0)
    d = json.loads(p.read_text())
    assert d["var"]["kw:bread"] < T.LEGACY_VAR and len(d["day_log"]) == 1


def test_replay_picks_the_largest_errors_and_clears_the_log(tmp_path):
    now = [T0]
    t = Tastes(tmp_path / "tastes.json", clock=lambda: now[0])
    for i in range(10):
        t.learn([f"kw:{i}"], 0.1 * i)                             # remaining error after one stay ~ 0.3 x response
    now[0] += 3600
    t.decay()
    var_before, pref_before = dict(t.var), dict(t.pref)
    res = t.replay(n=2)
    assert res["stays"] == 10 and res["replayed"] == 2 and res["error_after"] < res["error_before"]
    moved = {k for k in t.pref if t.pref[k] != pref_before[k]}
    assert moved == {"kw:9", "kw:8"}                               # the two largest errors, nothing else
    assert t.var == var_before                                     # replays are not new stays
    assert t.day_log == []
    saved = Tastes(tmp_path / "tastes.json", clock=lambda: now[0])
    assert saved.day_log == [] and saved.last_replay == res and saved.pref == t.pref
    assert t.top()["last_replay"] == res
    assert t.replay() is None                                      # nothing logged since: nothing to do


def test_day_log_is_bounded_and_old_stays_are_not_replayed():
    now = [T0]
    t = Tastes(None, clock=lambda: now[0])
    for i in range(T.DAY_LOG_CAP + 50):
        t.learn(["kw:a"], 0.3)
    assert len(t.day_log) == T.DAY_LOG_CAP
    now[0] += T.REPLAY_MAX_AGE_S + 1
    assert t.replay() is None and t.day_log == []


def test_live_server_replays_at_sleep_onset(tmp_path):
    from types import SimpleNamespace
    import live_server
    now = [T0]
    tastes = Tastes(tmp_path / "tastes.json", clock=lambda: now[0])
    tastes.learn(["kw:bread"], 0.8)
    engine = SimpleNamespace(stage="NREM", params={"f_hz": 1.0, "coupling": 1.0, "noise": 0.1, "a": -0.1},
                             update=lambda t, dt_real=None: [{"type": "sleep", "text": "fell asleep at 23:00"}])
    brain = SimpleNamespace(set_rhythm=lambda *a: None, a=0.0)
    live = SimpleNamespace(brain=brain, engine=engine, clock=SimpleNamespace(now=lambda: now[0]), burst=0.0,
                           spiking=None, tastes=tastes)
    out = live_server.Live.sleep_tick(live)
    assert out[0]["type"] == "sleep" and tastes.day_log == [] and tastes.last_replay["replayed"] == 1


if __name__ == "__main__":
    for noise in (0.1, 0.2):
        print(f"noise {noise}:", json.dumps(table(noise)))
