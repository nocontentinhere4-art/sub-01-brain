"""The brain vote after the audit (brain_plan V1; brain_vote.py, tastes.py): a scale floor (options the brain told apart
by less than SCALE_FLOOR are not decided by its noise, and the reason says so), a temperature cap (bored and tired is
still a choice, not a coin toss), network weights for memory / language / default-mode shared with the stay measure, the
leave row's taste from the page he is on, a repeat penalty over the last choices, a reason built from the chosen row's
own terms, and tastes that need stays before they move the vote (and keep the net:* topics out of it).

    python -m pytest tests/test_brain_vote_v1.py -q
No network, no AI calls."""
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import brain_vote as V
from tastes import PageWatch, Tastes


@pytest.fixture(scope="module")
def brain():
    from brain_sim import Brain
    b = Brain()
    b.run(1)
    return b


REWARD = {"action": "click", "label": "bakery", "networks": {"reward": 1.0, "visual": 0.3}}
FEAR = {"action": "click", "label": "storm warning", "networks": {"fear": 1.0, "salience": 0.6}}
QUIET = [{"action": "click", "label": f"note {i}", "networks": {"memory": 0.5, "language": 0.5}} for i in range(4)]


def test_four_alike_options_are_not_decided_by_the_brains_noise(brain):
    """Four memory/language-only links: their responses differ by less than the floor, so the brain term is left out,
    the pick is taste and novelty (here: novelty), and the caption says so instead of naming an area."""
    d = V.vote(brain.clone(), QUIET, 1.0, novel=[False, False, True, False], rng=np.random.default_rng(0))
    assert d["brain"] is False and all(o["value"] == 0.0 for o in d["options"])
    assert d["chosen"] == 2 and d["options"][2]["p"] > 0.6                      # the one new thing wins (chance: 0.25)
    assert d["reason"].startswith("no brain response: picked on something he has not tried lately")
    assert "areas responded" not in d["reason"] and "threat" not in d["reason"]
    d0 = V.vote(brain.clone(), QUIET, 1.0, rng=np.random.default_rng(0))       # nothing else to go on: chance, said so
    assert d0["reason"] == "no brain response: picked on chance" and max(o["p"] for o in d0["options"]) < 0.3


def test_a_telling_response_still_decides_and_names_what_rose(brain):
    d = V.vote(brain.clone(), [FEAR, REWARD], 1.0, rng=np.random.default_rng(0))
    assert d["brain"] is True and d["chosen"] == 1 and d["options"][1]["p"] > 0.95
    assert d["reason"].startswith("chose it: reward") and "visual" not in d["reason"]   # (visual named for videos only)
    v = V.vote(brain.clone(), [FEAR, dict(REWARD, action="open_video")], 1.0, rng=np.random.default_rng(0))
    assert "reward" in v["reason"] or "visual" in v["reason"]


def test_temperature_is_capped_and_rested_votes_on_equal_options_do_not_favour_one(brain):
    assert V.temperature(1.0, 1.0, 1.0) == V.T_MAX == pytest.approx(0.35)
    assert V.temperature(0.0, 0.0, 0.0) < V.temperature(0.8, 0.0, 0.0) <= V.T_MAX
    same = [dict(REWARD, label=f"bakery {i}") for i in range(3)]
    picks = Counter(V.vote(brain.clone(), same, 1.0, rng=np.random.default_rng(s))["chosen"] for s in range(120))
    assert max(picks.values()) <= 0.6 * 120, picks                                   # no option over 60 %


def test_bored_and_tired_show_in_the_terms(brain):
    heavy = {"action": "click", "label": "big", "networks": {"reward": 0.6, "attention": 0.6, "visual": 0.6}}
    light = {"action": "click", "label": "small", "networks": {"reward": 0.6}}
    rested = V.vote(brain.clone(), [heavy, light], 1.0, {"boredom": 0.0}, rng=np.random.default_rng(1))
    tired = V.vote(brain.clone(), [heavy, light], 1.0, {"pressure": 1.0, "tired": 1.0}, rng=np.random.default_rng(1))
    assert "tired" not in rested["options"][0] and tired["options"][0]["tired"] == pytest.approx(-V.TIRED_W, abs=1e-3)
    assert tired["options"][1]["tired"] == pytest.approx(-V.TIRED_W / 3, abs=1e-3)   # (the lighter option loses less)
    assert tired["temperature"] <= V.T_MAX
    same = [dict(REWARD, label="a"), dict(REWARD, label="b")]
    calm = V.vote(brain.clone(), same, 1.0, {"boredom": 0.0}, novel=[False, True], rng=np.random.default_rng(0))
    bored = V.vote(brain.clone(), same, 1.0, {"boredom": 1.0}, novel=[False, True], rng=np.random.default_rng(0))
    assert bored["options"][1]["p"] > calm["options"][1]["p"]                         # bored: the new thing pulls harder


def test_repeat_penalty_over_the_last_choices(brain):
    games = {"action": "click", "label": "speedrun of a video game", "href": "https://en.wikipedia.org/wiki/Speedrun",
             "networks": {"reward": 1.0}}
    other = {"action": "click", "label": "a ramen shop in Kichijoji", "href": "https://example.org/ramen",
             "networks": {"reward": 1.0}}
    assert V.repeat_key(games) and V.repeat_key(other) and V.repeat_key(games) != V.repeat_key(other)
    assert V.repeat_key({"action": "leave", "label": "move on", "networks": {}}) is None
    fresh = V.vote(brain.clone(), [games, other], 1.0, rng=np.random.default_rng(0))
    again = V.vote(brain.clone(), [games, other], 1.0, rng=np.random.default_rng(0), recent=[V.repeat_key(games)] * 5)
    assert "repeat" not in fresh["options"][0] and again["options"][0]["repeat"] == pytest.approx(-3 * V.REPEAT_W)
    assert again["options"][0]["p"] < fresh["options"][0]["p"]
    assert "repeat" not in again["options"][1]


def test_leave_taste_is_the_pages_negated(brain):
    leave = {"action": "leave", "label": "move on", "networks": {}, "pull": 0.0}
    stay = {"action": "scroll", "label": "keep reading", "networks": {"language": 0.3}}
    liked = V.vote(brain.clone(), [stay, leave], 1.0, tastes=[0.0, 0.8], rng=np.random.default_rng(0))   # the page paid off
    disliked = V.vote(brain.clone(), [stay, leave], 1.0, tastes=[0.0, -0.8], rng=np.random.default_rng(0))
    assert liked["options"][1]["taste"] == -0.8 and disliked["options"][1]["taste"] == 0.8
    assert liked["options"][1]["p"] < disliked["options"][1]["p"]
    assert disliked["chosen"] == 1 and disliked["reason"] == "moved on: this page's topics have not paid off"


def test_live_server_passes_the_pages_taste_and_the_recent_picks(brain, tmp_path):
    """_vote_and_act: the leave row gets the taste of the page he is on (pagewatch.cur topics), the vote gets the
    repeat keys of the last choices, and the chosen key is appended."""
    import asyncio
    import time
    from types import SimpleNamespace
    from live_server import Live

    acts = []

    async def act(dev, a, why, interest=None):
        acts.append(a)
        return {"id": 1}

    async def broadcast(msg):
        pass
    t = Tastes(tmp_path / "t.json")
    for _ in range(12):
        t.learn(["kw:bread"], -1.0)                                           # the page he is on has not paid off
    pw = PageWatch()
    pw.start(["kw:bread"], 0.0)
    opts = [{"action": "scroll", "label": "keep reading", "networks": {"language": 0.3}},
            {"action": "leave", "label": "move on", "networks": {}, "pull": 0.0}]
    live = SimpleNamespace(brain=brain.clone(), browser=SimpleNamespace(act=act), broadcast=broadcast,
                           engine=SimpleNamespace(gain=1.0, tired=0.0, pressure=lambda t: 0.2),
                           life=SimpleNamespace(boredom=0.0), clock=SimpleNamespace(now=time.time), tastes=t, pagewatch=pw,
                           decisions={}, decision_log=[], targets={}, vote_rng=np.random.default_rng(0),
                           recent_picks=["topic:games"] * 3)
    live.novel = lambda o: Live.novel(live, o)
    live.end_page = lambda: Live.end_page(live)
    live.outcome = lambda chosen, st: None
    page = {"url": "https://en.wikipedia.org/wiki/Bread", "title": "Bread", "device": "desk"}
    asyncio.run(Live._vote_and_act(live, "desk", page, opts, {"source": "local"}, "bread"))
    dec = live.decisions["desk"]
    assert dec["options"][1]["taste"] > 0.3                                   # minus the page's (negative) taste
    assert len(live.recent_picks) == 4 and live.recent_picks[:3] == ["topic:games"] * 3


def test_tastes_need_stays_before_they_move_the_vote(tmp_path):
    t = Tastes(tmp_path / "t.json")
    t.learn(["kw:bread", "net:reward"], 1.0)
    full = t.predict(["kw:bread", "net:reward"])
    assert 0.3 < full <= 1.0
    assert t.predict(["kw:bread"], vote=True) == pytest.approx(t.pref["kw:bread"] * 1 / 9)   # one stay: 1/9 of its value
    assert t.predict(["net:reward"], vote=True) == 0.0                              # net:* left out of the vote
    assert t.predict(["kw:bread", "net:reward"], vote=True) == t.predict(["kw:bread"], vote=True)
    for _ in range(7):
        t.learn(["kw:bread"], 1.0)
    assert t.n["kw:bread"] == 8 and t.predict(["kw:bread"], vote=True) == pytest.approx(t.pref["kw:bread"] * 0.5)
    saved = Tastes(tmp_path / "t.json")
    assert saved.n == t.n                                                           # the counts are saved
    old = Tastes(tmp_path / "old.json")
    old.pref, old.var = {"kw:x": 0.6}, {"kw:x": 0.01}
    old.save()
    legacy = Tastes(tmp_path / "old.json")
    assert legacy.n == {"kw:x": 8} and legacy.predict(["kw:x"], vote=True) == pytest.approx(0.3)   # an old file: half weight
    t.replay()                                                                      # a replay is not a stay
    assert t.n["kw:bread"] == 8


def test_stay_measure_uses_the_votes_weights():
    rel = {"reward": 1.2, "attention": 1.0, "memory": 1.5, "language": 1.0, "default": 1.0, "fear": 0.5}
    expect = sum(w * rel[g] for g, w in V.VALUE.items())
    assert PageWatch.measure(rel) == pytest.approx(expect)
    assert PageWatch.measure({}) == pytest.approx(sum(V.VALUE.values()))             # (every group at its baseline 1.0)
    assert set(V.VALUE) == {"reward", "attention", "memory", "language", "default", "fear"}
    assert V.VALUE["memory"] == 0.4 and V.VALUE["language"] == 0.3 and V.VALUE["default"] == 0.2
