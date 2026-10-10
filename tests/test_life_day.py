"""The shape of his day (plan S1 life part, L1, L2, L3, L5, T1): no chart activity, a softmax choice with a repeat
penalty, a daypart table, nothing at the desk at night, meals in three slots from the bakery before the courier,
walks whose clock starts on arrival on one real route, videos only when something can show, and a day-level run.

    python -m pytest tests/test_life_day.py -q
No network, no AI calls, no server: life.py alone with its own body."""
import math
import random
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import life as L  # noqa: E402
from twin.body import Body  # noqa: E402

TZ = ZoneInfo("Asia/Tokyo")
MON, SAT = 5, 3                                        # 2026-10-05 is a Monday, 2026-10-03 a Saturday


def at(h, m=0, day=MON):
    return datetime(2026, 10, day, h, m, tzinfo=TZ).timestamp()


def life(seed=0, **state):
    return L.Life(state or None, rng=random.Random(seed))


def hungry(level):
    """A body at a given hunger: 'fed' (< SATED), 'peckish' (between SATED and EAT_AT) or 'meal' (>= EAT_AT)."""
    return Body({"fed": {"since_meal_h": 0.5, "ghrelin": 0.1, "glucose": 110.0},
                 "peckish": {"since_meal_h": 3.0, "ghrelin": 0.5, "glucose": 88.0},
                 "meal": {"since_meal_h": 6.0, "ghrelin": 0.9, "glucose": 78.0}}[level])


def arrive(lf, t, dt=1.0, limit=3600):
    """Walk the current path to its end (1 s steps); returns the arrival time."""
    end = t + limit
    while lf.path and t < end:
        t += dt
        lf.update(t, dt, dt, "AWAKE", {}, 0.0, 0.0)
    assert not lf.path
    return t


# --- S1: the chart is gone ----------------------------------------------------------------------------------------------
def test_no_chart_activity_anywhere():
    lf = life()
    for table in (L.ACTIVITIES, L.LABEL, lf.scores(at(12), {}, 0.0, 0.0)):
        assert "chart" not in table
    assert "chart" not in L.INTERRUPTIBLE and not any(act == "chart" for _, act in L.DESIRES)
    bad = re.compile(r"price|prezzo|pump|dump|chart|grafico|candele")
    assert not any(bad.search(pat) for pat, _ in L.DESIRES)
    assert lf.phone_app == "chat"
    lf.start("phone", at(23), "x")
    assert lf.phone_app in ("chat", "tiktok")
    lf.can_watch = False
    for _ in range(20):
        lf.start("phone", at(23), "x")
        assert lf.phone_app == "chat"                   # nothing could play: the chat app, never an empty feed
    # the trades (hot) are a body stimulus, not an activity: the slot is ignored, and the old keyword is gone
    a, b = lf.scores(at(12), {}, 0.0, 0.0), lf.scores(at(12), {}, 1.0, 0.0)
    assert a == b


def test_old_saves_migrate_from_the_chart():
    lf = L.Life({"activity": "chart", "place": "desk", "desires": {"chart": [1.2, 0], "park": [0.6, 0]},
                 "viewer_nudge": ["chart", at(12)]})
    assert lf.activity == "research" and "chart" not in lf.desires and lf.desires["park"] == [0.6, 0]
    assert lf.nudge(at(12)) is None and lf.label() == L.LABEL["research"]
    assert "chart" not in lf.snapshot()["doing"]


# --- L1: the choice ---------------------------------------------------------------------------------------------------
def test_repeat_penalty_counts_recent_starts():
    lf = life()
    t = at(10)
    assert lf.repeats("research", t) == 0 and lf.repeats("window", t) == 1      # what he is doing counts once
    lf.start("research", t, "x")
    lf.start("window", t + 1800, "x")
    lf.start("research", t + 3600, "x")
    assert lf.repeats("research", t + 3601) == 2
    assert lf.repeats("research", t + 3600 + L.REPEAT_WINDOW) == 1              # the first one is out of the window
    assert lf.repeats("eat", t) == 0
    shares = []
    for n in (0, 1, 2):                                 # the more he read in the last 3 h, the less he picks it again
        wins = 0
        for seed in range(300):
            lf = life(seed, activity="window", place="window", until=0.0)
            lf.boredom, lf.body.ghrelin, lf.bread = 0.3, 0.1, 4
            lf.started = [(at(14) - 600 * (k + 1), "research") for k in range(n)]
            wins += lf.choose(at(14), "AWAKE", {}, 0.0, 0.0) == "research"
        shares.append(wins / 300)
    assert shares[0] > shares[1] > shares[2] and shares[2] < 0.5 * shares[0]


def test_softmax_never_picks_the_impossible_and_follows_the_scores():
    lf = life()
    picks = [lf.softmax({"a": 0.9, "b": 0.6, "c": 0.0}) for _ in range(500)]
    assert "c" not in picks and picks.count("a") > picks.count("b") > 0
    assert lf.softmax({"a": 0.0, "b": 0.0}) in ("a", "b")       # nothing possible: still an answer


def test_nothing_at_the_desk_or_the_window_between_midnight_and_six():
    for h in (0, 3, 5):
        for waiting in (0, 1):
            lf = life(h, activity="sleep", place="bed", until=0.0)
            lf.chat_waiting = waiting
            s = lf.scores(at(h, 30), {}, 0.0, 0.0)
            desk = [s["research"], s["watch_video"], s["window"]]
            assert all(v == 0 for v in desk) if not waiting else all(v > 0 for v in desk)
            assert s["phone"] >= 0.5 and s["listen_music"] > 0                   # the phone or the headphones
            picks = {lf.choose(at(h, 30), "AWAKE", {}, 0.0, 0.5) for _ in range(200)}
            if not waiting:
                assert picks <= {"phone", "listen_music", *L.FOOD_ACTS}, picks
            else:
                assert "chat" in picks
    assert life().scores(at(6, 5), {}, 0.0, 0.0)["research"] > 0               # six o'clock: the day may start


def test_chess_once_a_day_evening_or_weekend_and_a_wish_still_wins():
    lf = life()
    lf.start("play_chess", at(20), "x")
    assert not lf.chess_ok(at(21)) and not lf.chess_ok(at(1, 30, day=MON + 1))   # the night belongs to the day
    assert lf.chess_ok(at(9, day=MON + 1))
    assert L.Life(lf.to_dict()).last_chess == at(20)
    week, sat = life().scores(at(14), {}, 0.0, 0.0), life().scores(at(14, day=SAT), {}, 0.0, 0.0)
    assert week["play_chess"] < sat["play_chess"] and week["research"] < sat["research"]
    assert week["park"] > life().scores(at(21), {}, 0.0, 0.0)["park"] == 0       # a weekday afternoon: out, not the desk
    wished = life()
    wished.hear("let's play chess", at(14))
    assert wished.scores(at(14), {}, 0.0, 0.0)["play_chess"] == sat["play_chess"] + 0.6   # the wish is not damped


def test_weekend_park_opens_earlier_and_weighs_more():
    week, sat = life().scores(at(7, 30), {}, 0.0, 0.0), life().scores(at(7, 30, day=SAT), {}, 0.0, 0.0)
    assert week["park"] == 0 < sat["park"]
    assert life().scores(at(11, day=SAT), {}, 0.0, 0.0)["park"] > life().scores(at(11), {}, 0.0, 0.0)["park"] - L.WORKDAY_OUT


def test_research_sessions_are_capped_per_day():
    lf = life()
    base = lf.scores(at(15), {}, 0.0, 0.0)["research"]
    lf.started = [(at(9), "research"), (at(11), "research"), (at(13), "research")]
    assert lf.scores(at(15), {}, 0.0, 0.0)["research"] < 0.3 * base
    assert lf.scores(at(15, day=MON + 1), {}, 0.0, 0.0)["research"] == base    # a new day
    assert L.Life(lf.to_dict()).started == lf.started                            # the count survives a restart


# --- L2: meals ---------------------------------------------------------------------------------------------------------
def test_meals_start_in_a_slot_or_as_a_real_need():
    lf = life(body=None)
    lf.body, lf.bread = hungry("peckish"), 4
    assert L.SATED < lf.hunger < L.EAT_AT
    assert lf.scores(at(12, 30), {}, 0.0, 0.0)["eat"] > 0                       # lunch slot
    assert lf.scores(at(15, 30), {}, 0.0, 0.0)["eat"] == 0                      # between meals: no grazing
    assert lf.scores(at(19), {}, 0.0, 0.0)["eat"] > 0                           # dinner
    lf.body = hungry("meal")
    assert lf.scores(at(15, 30), {}, 0.0, 0.0)["eat"] > 1                       # a real need eats any time
    lf.body, lf.bread, lf.food, lf.food_items = hungry("peckish"), 0, 1, ["ramen"]
    assert lf.scores(at(15, 30), {}, 0.0, 0.0)["eat"] > L.FOOD_WAITING          # a meal on the table is eaten


def test_bakery_before_the_courier_and_an_order_only_at_meal_need_with_a_cooldown():
    lf = life()
    lf.body = hungry("fed")
    s = lf.scores(at(11), {}, 0.0, 0.0)
    assert s["buy_bread"] >= L.BAKERY_ERRAND and s["order_food"] == 0           # no bread: the errand, never an order
    assert lf.scores(at(21), {}, 0.0, 0.0)["buy_bread"] == 0                    # the bakery is closed by arrival
    lf.body = hungry("peckish")
    assert lf.scores(at(13), {}, 0.0, 0.0)["order_food"] == 0                   # below EAT_AT: no delivery
    lf.body = hungry("meal")
    s = lf.scores(at(13), {}, 0.0, 0.0)
    assert s["order_food"] > 0 and s["buy_bread"] > s["order_food"] + 0.25      # the bakery wins at lunch
    s = lf.scores(at(22), {}, 0.0, 0.0)
    assert s["buy_bread"] == 0 and s["order_food"] > 0 and s["buy_konbini"] > 0  # late: the konbini or the courier
    lf.start("order_food", at(13), "x")
    assert lf.last_order == at(13) and lf.scores(at(13, 30), {}, 0.0, 0.0)["order_food"] == 0
    assert lf.scores(at(13) + L.ORDER_EVERY, {}, 0.0, 0.0)["order_food"] > 0    # one order per three hours
    assert L.Life(lf.to_dict()).last_order == at(13)
    lf = life()
    lf.start("buy_bread", at(9), "x")
    lf.place, lf.path, lf.until = "counter", [], at(9)
    lf.update(at(9) + 1, 1, 1, "AWAKE", {}, 0.0, 0.0)
    assert lf.bread == L.BREAD_PER_TRIP                                         # a trip stocks up


def test_past_the_daily_meals_a_snack_weighs_a_fifth_but_a_need_still_eats():
    lf = life()
    lf.body, lf.bread = hungry("peckish"), 4
    base = lf.scores(at(13), {}, 0.0, 0.0)["eat"]
    lf.started = [(at(h), "eat") for h in (7, 9, 12, 12)]
    assert lf.scores(at(13), {}, 0.0, 0.0)["eat"] < 0.25 * base
    lf.body = hungry("meal")
    assert lf.scores(at(13), {}, 0.0, 0.0)["eat"] > 1
    assert lf.scores(at(5, day=MON + 1), {}, 0.0, 0.0)["eat"] > 1               # 04:00 turned the day


def test_a_meal_is_two_rolls():
    lf = life()
    lf.body, lf.bread = hungry("meal"), 4
    lf.start("eat", at(12), "x")
    lf.place, lf.path, lf.until = "table", [], at(12)
    g0 = lf.body.ghrelin
    lf.update(at(12) + 1, 1, 1, "AWAKE", {}, 0.0, 0.0)
    assert lf.bread == 2 and lf.body.ghrelin < 0.3 * g0


def test_meal_time_pulls_him_off_the_bench_a_mild_hunger_does_not():
    lf = life()
    lf.start("park", at(14), "x")
    lf.place, lf.path, lf.until = "bench", [], at(14) + 3600
    lf.body = hungry("peckish")
    assert not lf.hungry_now(at(14, 10), {}, 0.0, 0.0)                              # he stays a while
    lf.body = hungry("meal")
    assert lf.hungry_now(at(14, 10), {}, 0.0, 0.0) in L.FOOD_ACTS                   # and names the food action


# --- L3: walks -------------------------------------------------------------------------------------------------------
def test_the_clock_starts_on_arrival_and_never_runs_to_infinity():
    lf = life()
    t = at(14)
    lf.start("park", t, "x")
    assert lf.trip == "home-park" and lf.path and lf.dur and 20 * 60 <= lf.dur <= 45 * 60
    assert math.isfinite(lf.until) and lf.until >= t + lf.dur                  # provisional, with the walk added
    dur = lf.dur
    t_arr = arrive(lf, t)
    assert lf.place == "bench" and lf.dur is None and lf.until == t_arr + dur   # the bench time is the whole duration
    assert 250 <= t_arr - t <= 500                                             # ~5 min outdoors at 3x (1.3 km real)
    lf2 = life()
    lf2.start("window", at(14), "x")                                            # a walk within the room: no trip
    assert lf2.trip is None and math.isfinite(lf2.until)
    saved = L.Life(lf.to_dict())
    assert saved.dur is None and saved.until == lf.until
    old = L.Life({"activity": "park", "place": "bed", "until": at(15)})         # a save from before: still finite
    assert old.trip == "home-park" and old.until == at(15) and old.dur is None


def test_one_real_route_per_trip_and_the_marker_moves_in_steps():
    for seed in range(3):
        lf = life(seed)
        t = at(14)
        lf.start("park", t, "x")
        names, prev, steps = set(), None, []
        while lf.path:
            t += 1.0
            lf.update(t, 1.0, 1.0, "AWAKE", {}, 0.0, 0.0)
            leg = lf.outdoor_leg()
            if leg:
                names.add(leg[0])
            if lf.geo and prev:
                steps.append(math.hypot((lf.geo["lat"] - prev["lat"]) * 111_000, (lf.geo["lng"] - prev["lng"]) * 90_000))
            prev = lf.geo
        assert names == {"home-park"}                       # door_out -> street_home is on the bakery route too
        assert steps and max(steps) <= L.WALK_SPEED * L.OUTDOOR_SPEEDUP * 2.5   # no jump between routes
        assert lf.geo and lf.geo["route"] == "home-park"
        lf.start("eat", t, "x")                              # home from the bench: the same route back
        assert lf.trip == "home-park"
        lf.bread = 2
        t = arrive(lf, t)
        assert lf.place == "table" and lf.geo is None


def test_the_park_closes_at_eight():
    lf = life()
    assert lf.scores(at(19, 40), {}, 0.0, 0.0)["park"] > 0 and lf.scores(at(19, 56), {}, 0.0, 0.0)["park"] == 0
    lf.start("park", at(19, 40), "x")
    arrive(lf, at(19, 40))
    assert lf.until <= at(20) and lf.until > at(19, 44)
    assert life().scores(at(20, 30), {}, 0.0, 0.0)["park"] == 0


def test_the_courier_interrupts_an_outing():
    lf = life()
    t = at(14)
    lf.start("park", t, "x")
    t = arrive(lf, t)
    lf.delivery = {"ordered": t - 600, "leaves": t - 300, "arrives": t + 60, "dish": "ramen"}
    lf.update(t + 61, 1, 1, "AWAKE", {}, 0.0, 0.0)
    assert lf.activity == "get_delivery" and lf.path and lf.path[-1] == "door_in"   # off the bench, home
    t2 = arrive(lf, t + 61)
    assert lf.place == "door_in" and t2 - (t + 60) <= 6 * 60                          # the courier waits < 6 sim minutes
    lf = life()                                                                       # mid-walk: turns back
    t = at(14)
    lf.start("park", t, "x")
    lf.delivery = {"ordered": t - 600, "leaves": t - 300, "arrives": t + 20, "dish": "ramen"}
    while lf.activity == "park" and t < at(14, 10):
        t += 1.0
        lf.update(t, 1.0, 1.0, "AWAKE", {}, 0.0, 0.0)
    assert lf.activity == "get_delivery" and lf.path[-1] == "door_in" and lf.place in L.STREET
    assert life(delivery={"ordered": 0, "leaves": 0, "arrives": 1e18}).scores(at(14), {}, 0.0, 0.0)["park"] == 0


# --- L5: videos only when something can show -----------------------------------------------------------------------------
def test_videos_only_when_something_can_show():
    lf = life()
    lf.boredom = 0.8
    assert lf.scores(at(15), {}, 0.0, 0.0)["watch_video"] > 0
    lf.can_watch = False
    lf.hear("watch a youtube video", at(15))
    assert lf.scores(at(15), {}, 0.0, 0.0)["watch_video"] == 0 and "watch_video" not in lf.desires
    lf.can_watch = True
    lf.start("watch_video", at(15), "x")
    lf.place, lf.path = "desk", []
    lf.no_video(at(15, 1))
    assert lf.until == at(15, 1) and lf.scores(at(15, 2), {}, 0.0, 0.0)["watch_video"] == 0
    assert lf.scores(at(15, 2) + 1800, {}, 0.0, 0.0)["watch_video"] > 0
    assert L.Life(lf.to_dict()).video_block_until == lf.video_block_until


# --- T1: the day ------------------------------------------------------------------------------------------------------
def simulate(days=12, step=10.0):
    """Waking days 07:00-23:30 (a fixed stage, like the coordinator's), random brain tilt, his own body."""
    out = []
    for seed in range(days):
        day = datetime(2026, 10, 5 + seed, 0, 0, tzinfo=TZ)
        base, rng = day.timestamp(), random.Random(100 + seed)
        lf = L.Life({"place": "bed", "activity": "sleep"}, rng=random.Random(seed))
        t, awake, reading, above = base, 0.0, 0.0, 0.0
        starts, bench, park_t, arrived, geo_prev, jumps = [], [], None, None, None, []
        while t < base + 86400:
            lt = datetime.fromtimestamp(t, TZ)
            h = lt.hour + lt.minute / 60
            stage = "AWAKE" if 7.0 <= h < 23.5 else "NREM"
            rel = {k: 1 + 0.4 * rng.random() for k in ("reward", "fear", "attention", "salience", "visual")}
            n0 = len(lf.started)
            lf.update(t, step, step, stage, rel, 0.0, 0.3 if h > 21 else 0.0)
            if len(lf.started) != n0:
                ts, act = lf.started[-1]
                starts.append((h, act, round(lf.hunger, 2)))
                if act == "park":
                    park_t, arrived = t, None
                elif park_t is not None:
                    bench.append((t - arrived) / 60 if arrived else 0.0)
                    park_t = None
            if lf.activity == "park" and park_t is not None and arrived is None and lf.place == "bench" and not lf.path:
                arrived = t
            if stage == "AWAKE":
                awake += step
                reading += step if lf.activity == "research" else 0.0
                above += step if lf.hunger > L.EAT_AT else 0.0
            if lf.geo and geo_prev:
                jumps.append(math.hypot((lf.geo["lat"] - geo_prev["lat"]) * 111_000, (lf.geo["lng"] - geo_prev["lng"]) * 90_000))
            geo_prev = lf.geo
            t += step
        out.append({"starts": starts, "research_share": reading / awake, "above_min": above / 60, "bench": bench,
                    "max_step": max(jumps) if jumps else 0.0, "weekday": day.weekday()})
    return out


def test_twelve_days_have_the_shape_of_a_day():
    days = simulate()
    bench = [b for d in days for b in d["bench"] if b > 1]          # (a visit cut at once: hunger or the courier)
    assert 20 <= statistics.median(bench) <= 45 and max(bench) <= 46
    for d in days:
        acts = [a for _, a, _ in d["starts"]]
        assert d["research_share"] <= 0.35, d["research_share"]
        after_other = [b for a, b in zip(acts, acts[1:]) if a != "research"]
        assert sum(1 for a in after_other if a == "research") / len(after_other) <= 0.5
        eats = [(h, hu) for h, a, hu in d["starts"] if a == "eat"]
        assert 3 <= len(eats) <= 5, eats
        in_slot = sum(1 for h, hu in eats if any(a <= h < b for a, b in L.MEAL_SLOTS) or hu >= L.EAT_AT)
        assert in_slot == len(eats)                                  # every meal is in a slot or a real need
        assert acts.count("order_food") <= 2 and acts.count("play_chess") <= 1
        assert all(hu >= L.EAT_AT - 0.01 for h, a, hu in d["starts"] if a == "order_food")
        assert acts.count("buy_bread") >= 1 and sum(1 for h, a, _ in d["starts"] if a == "buy_bread" and 7 <= h < 20) >= 1
        assert not any(h < 6 for h, a, _ in d["starts"] if a in ("research", "watch_video", "window"))
        assert d["above_min"] <= 60                                   # hunger past meal time is answered within the hour
        assert d["max_step"] <= L.WALK_SPEED * L.OUTDOOR_SPEEDUP * 10 * 1.5    # the marker never jumps routes
        assert len(set(acts)) >= 7                                    # a varied day
