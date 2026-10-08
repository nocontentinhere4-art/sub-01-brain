"""#57: needs first. Hunger outranks chat, the plan and the desk; deliveries are eaten promptly; a 24 h konbini at night."""
import random
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import life as L
from twin.body import Body

TOKYO = ZoneInfo("Asia/Tokyo")


def at(h, m=0):
    return datetime(2026, 10, 2, h, m, tzinfo=TOKYO).timestamp()


def day(waiting, seed, plan_hint=None, step=2.0):
    """The coordinator's simulation: one waking day 07:00-24:00 at time scale 1, `waiting` chat messages all day."""
    lf = L.Life(rng=random.Random(seed))
    lf.time_scale = 1.0
    lf.chat_waiting, lf.plan_hint = waiting, plan_hint
    t, end = at(7), at(23, 59)
    above, meals, prev, arrived, lags = 0.0, 0, None, None, []
    while t < end:
        lf.update(t, step, step, "AWAKE", {}, 0.0, 0.0)
        if lf.delivery and t >= lf.delivery["arrives"] and arrived is None:
            arrived = lf.delivery["arrives"]
        if arrived is not None and lf.activity == "eat" and not lf.path:
            lags.append((t - arrived) / 60)
            arrived = None
        if prev == "eat" and lf.activity != "eat":
            meals += 1
        prev = lf.activity
        above += step if lf.hunger > L.EAT_AT else 0.0
        t += step
    return above / 60, meals, lags


def test_day_with_chat_waiting_stays_fed():
    for waiting in (0, 1, 3):
        for seed in range(3):
            above, meals, lags = day(waiting, seed)
            assert above < 30, (waiting, seed, above)
            assert 3 <= meals <= 7, (waiting, seed, meals)               # fed, not eating constantly
            assert all(x <= 10 for x in lags), (waiting, seed, lags)     # the delivery is eaten within 10 sim-minutes


def test_plan_bonus_does_not_beat_meal_time():
    above, meals, _ = day(3, 0, plan_hint="chat")
    assert above < 30 and meals >= 3


def _hungry_life(hunger_state, **state):
    body = Body(hunger_state)
    lf = L.Life({"place": "desk", "activity": "chat", "until": 1e18, **state}, rng=random.Random(4), body=body)
    lf.chat_waiting, lf.plan_hint = 3, "chat"
    return lf


def test_food_outranks_chat_and_plan_at_meal_time():
    lf = _hungry_life({"since_meal_h": 6.0, "ghrelin": 0.9, "glucose": 78.0})
    assert lf.hunger > L.EAT_AT
    s = lf.scores(at(13), {}, 0.0, 0.0)
    food = max(s[a] for a in L.FOOD_ACTS if a in s)
    assert food > s["chat"] + 0.15 and food > s["research"] + 0.15
    assert all(lf.choose(at(13), "AWAKE", {}, 0.0, 0.0) in L.FOOD_ACTS for _ in range(200))


def test_ramp_is_smooth():
    lf = L.Life(rng=random.Random(0))
    prev = -1.0
    for g in [i / 50 for i in range(51)]:
        lf.body = Body({"ghrelin": g, "glucose": 95 - 25 * g, "since_meal_h": 8 * g})
        n = lf.need()
        assert n >= prev - 1e-9                     # monotone with hunger
        prev = n
    lf.body = Body({"ghrelin": 0.0, "glucose": 100.0, "since_meal_h": 0.0})
    assert lf.hunger < L.SATED and lf.need() == 0.0


def test_hunger_ends_the_chat_early_and_waiting_meal_is_eaten():
    lf = _hungry_life({"since_meal_h": 6.0, "ghrelin": 0.9, "glucose": 78.0}, food=1)
    t = at(14)
    for _ in range(5 * 30):                        # 5 sim minutes in 2 s steps
        lf.update(t, 2.0, 2.0, "AWAKE", {}, 0.0, 0.0)
        t += 2.0
        if lf.activity == "eat":
            break
    assert lf.activity == "eat" and lf.say.startswith("hungry:")


def test_night_konbini():
    lf = L.Life({"place": "bed", "activity": "phone", "until": 0.0}, rng=random.Random(1),
                body=Body({"since_meal_h": 6.0, "ghrelin": 0.9, "glucose": 78.0}))
    assert lf.hunger > L.EAT_AT
    t = at(23, 45)
    s = lf.scores(t, {}, 0.0, 0.0)
    assert s["buy_bread"] == 0.0 and s["order_food"] == 0.0 and s["buy_konbini"] > 1.0
    lf.update(t, 1.0, 1.0, "AWAKE", {}, 0.0, 0.0)
    assert lf.activity == "buy_konbini" and lf.say.startswith("hungry")
    seen_geo, acts = False, []
    for _ in range(4000):                          # walk there (real Tokyo route), buy, walk back, eat
        t += 1.0
        lf.update(t, 1.0, 1.0, "AWAKE", {}, 0.0, 0.0)
        seen_geo |= lf.geo is not None
        acts.append(lf.activity)
        if lf.activity == "eat" and not lf.path:
            break
    assert seen_geo                                # he is out: the room shows the map, like buy_bread
    assert lf.activity == "eat" and lf.food == 1   # the konbini meal is waiting on the table
    # #63: the label names what he eats (it used to say "eating bread at the table" for the konbini meal too)
    assert lf.eating in L.KONBINI and lf.snapshot()["doing"] == L.EAT_LABEL[lf.eating]


def test_konbini_only_when_bakery_closed():
    lf = L.Life(rng=random.Random(0), body=Body({"since_meal_h": 6.0, "ghrelin": 0.9, "glucose": 78.0}))
    assert lf.scores(at(12), {}, 0.0, 0.0)["buy_konbini"] == 0.0
    assert lf.scores(at(6, 30), {}, 0.0, 0.0)["buy_konbini"] > 0.0


def test_go_eat_chat_still_works():
    lf = L.Life({"place": "desk", "activity": "research", "until": 1e18, "food": 1}, rng=random.Random(0),
                body=Body({"since_meal_h": 3.0, "ghrelin": 0.5, "glucose": 88.0}))
    t = at(15)
    base = lf.scores(t, {}, 0.0, 0.0)["eat"]
    lf.hear("mangia qualcosa!", t)
    assert lf.scores(t, {}, 0.0, 0.0)["eat"] >= base + 0.5 or lf.hunger <= L.SATED
    lf.desires.clear()
    lf.food = 0
    lf.hear("go eat", at(23, 50))
    assert lf.scores(at(23, 50), {}, 0.0, 0.0)["buy_konbini"] >= 0.5
    lf.start("buy_konbini", at(23, 50), "test")
    assert "buy_bread" not in lf.desires           # the wish is answered by the konbini trip


def test_dish_follows_the_order():
    """#63: a viewer's wish picks the dish; it rides with the courier, waits as a food item and names the meal."""
    lf = L.Life(rng=random.Random(3))
    lf.time_scale = 1.0
    t = at(19)
    lf.hear("could you order some sushi?", t)
    lf.start("order_food", t, "hungry: orders food on the phone")
    assert lf.order_dish == "sushi" and lf.snapshot()["order"] == "sushi"
    assert lf.snapshot()["doing"] == "ordering sushi on the phone"
    lf.path, lf.until = [], t                                # (already on the bed) the order is done: the courier sets off
    lf.update(t + 1, 1, 1, "AWAKE", {}, 0.0, 0.0)
    assert lf.delivery and lf.delivery["dish"] == "sushi" and lf.courier(t + 1)["dish"] == "sushi"
    t2 = lf.delivery["arrives"] + 1
    lf.start("get_delivery", t2, "the courier rings: goes to the door")
    lf.path, lf.until = [], t2
    lf.update(t2 + 1, 1, 1, "AWAKE", {}, 0.0, 0.0)
    assert lf.food == 1 and lf.food_items == ["sushi"]
    lf.start("eat", t2 + 2, "hungry: eats the sushi at the table")
    assert lf.eating == "sushi" and lf.snapshot()["doing"] == "eating sushi from the delivery"


def test_dish_without_a_wish():
    lf = L.Life(rng=random.Random(4))
    lf.start("order_food", at(20), "hungry")
    assert lf.order_dish in L.DISHES


def test_snapshot_sends_the_walk_path():
    """room.html keys on life.path / life.path_to (screens, props, follow camera, door anchor): while he walks the
    snapshot must carry them, and both are null once he has arrived: the page tests `!life.path`, and an empty JS array
    is truthy (#98 G8 defect #21)."""
    lf = L.Life(rng=random.Random(0))
    lf.path = ["hall", "desk"]
    s = lf.snapshot()
    assert s["walking"] and s["path"] == ["hall", "desk"] and s["path_to"] == "desk"
    lf.path = []
    s = lf.snapshot()
    assert not s["walking"] and s["path"] is None and s["path_to"] is None
