"""The vote and the reactions after the audit (brain_plan S5, A1, A2; audience.py, live_server.audience_tick):
  S5  one vote per server-issued cookie (two browsers behind one address and user agent both vote; a made-up cookie
      counts for nothing), the per-address cap at VOTES_PER_ADDRESS (25), flood buckets over all clients;
  A1  rounds are short (10 min), never offer what he is doing, do not open while he sleeps, and `vote_applied` goes
      out when the voted activity actually starts, not when the nudge is set;
  A2  a viewer alone can make him glance (the burst is a spike's worth), the reactions' memory is bounded.
Nothing here spends on an API; the server fixture is the one of tests/test_interactive.py (no brain file)."""
import asyncio
import random

import pytest

import audience
from audience import Reactions, Votes, pick_options


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


# --- S5: who may vote --------------------------------------------------------------------------------------------
def test_two_cookies_behind_one_address_and_user_agent_both_vote():
    v = Votes(round_s=60, rng=random.Random(1), clock=Clock())
    v.open(["research", "park", "window"])
    a, b = v.fp.ids("cookie-a", "1.2.3.4", "UA"), v.fp.ids("cookie-b", "1.2.3.4", "UA")
    assert v.cast(a, 0) == (True, "") and v.cast(b, 1) == (True, "")        # a flat-share: two people, one router
    assert v.cast(a, 1)[0] is False and v.cast(b, 0)[0] is False
    assert v.round.counts == [1, 1, 0] and v.mine(a) == 0 and v.mine(b) == 1
    assert len(a) == len(b) == 1 and a != b                                 # (one hash each: the cookie's)


def test_only_a_cookie_the_server_issued_counts_as_a_cookie():
    c = audience.new_viewer_id()
    assert audience.issued_cookie(c) == c
    assert audience.issued_cookie("made-up") is None and audience.issued_cookie(None) is None
    assert audience.issued_cookie(123) is None
    # the registry is bounded: the oldest ids are forgotten (memory only; a restart forgets them all)
    first = audience.new_viewer_id()
    for _ in range(audience.ISSUED_MAX + 5):
        audience.new_viewer_id()
    assert audience.issued_cookie(first) is None and len(audience._ISSUED) == audience.ISSUED_MAX


def test_the_per_address_cap_lets_a_shared_network_vote():
    v = Votes(round_s=60, rng=random.Random(1), clock=Clock())
    v.open(["research", "park"])
    addr = v.fp.address("1.2.3.4")
    oks = [v.cast(v.fp.ids(None, "1.2.3.4", f"UA-{i}"), i % 2, addr=addr)[0] for i in range(30)]
    assert oks[:audience.VOTES_PER_ADDRESS] == [True] * 25                  # the 11th to the 25th count (it was 10)
    assert not any(oks[audience.VOTES_PER_ADDRESS:])                        # the 26th does not
    assert v.cast(v.fp.ids(None, "1.2.3.4", "UA-x"), 0, addr=addr) == (False, "too many votes from this network this round")
    assert v.cast(v.fp.ids(None, "5.6.7.8", "UA-x"), 0, addr=v.fp.address("5.6.7.8")) == (True, "")   # another address


def test_vote_flood_bucket_over_all_clients():
    clk = Clock(0.0)
    v = Votes(round_s=60, rng=random.Random(1), clock=clk)
    v.flood.clock = clk
    v.open(["research", "park"])
    oks = [v.cast(v.fp.ids(f"c{i}", f"10.0.{i // 250}.{i % 250}", "UA"), 0)[0] for i in range(audience.VOTE_ALL_BURST + 3)]
    assert sum(oks) == audience.VOTE_ALL_BURST and not any(oks[-3:])
    ok, why = v.cast(v.fp.ids("late", "1.1.1.1", "UA"), 0)
    assert not ok and "too many votes at once" in why
    assert v.cast(v.fp.ids("c0", "x", "UA"), 1) == (False, "one vote per viewer per round")   # a repeat costs it nothing
    clk.t += 10 * audience.VOTE_ALL_EVERY_S                                 # tokens come back with time
    assert v.cast(v.fp.ids("late", "1.1.1.1", "UA"), 0) == (True, "")


def test_reaction_flood_bucket_over_all_clients():
    clk = Clock(0.0)
    r = Reactions(clock=clk)
    got = sum(r.react(f"v{i}", 0, addr=f"a{i}")[0] for i in range(audience.REACT_ALL_BURST + 20))
    assert got == audience.REACT_ALL_BURST
    assert r.react("new", 0, addr="new") == (False, "slow down")
    clk.t += 5 * audience.REACT_ALL_EVERY_S
    assert r.react("new", 0, addr="new")[0]


# --- A1: the round ------------------------------------------------------------------------------------------------
def test_round_defaults_are_short_and_a_result_waits_a_night_at_most():
    assert 300 <= audience.VOTE_ROUND_S <= 600
    assert audience.PENDING_MAX_S <= 12 * 3600


def test_a_round_never_offers_what_he_is_doing():
    now = {"research": 0.9, "park": 1.4, "window": 0.2, "phone": 0.5}
    for seed in range(40):
        opts = pick_options(now, now, random.Random(seed), n=3, votable=dict.fromkeys(now, ""), exclude={"park"})
        assert "park" not in opts and len(opts) == 3, opts
    # two possibilities minus the one he is doing: fewer than 2 left, no round
    assert pick_options({"research": 1, "park": 1}, {"research": 1, "park": 1}, random.Random(0), exclude={"park"}) == []


@pytest.fixture
def server(tmp_path):
    pytest.importorskip("aiohttp")
    from aiohttp import web
    import live_server

    async def make():
        live = live_server.Live(None, True, 1.0, tmp_path)
        live.votes.round_s = 60
        app = web.Application(middlewares=[live_server.viewer_cookie])
        app.router.add_get("/ws", live.ws_handler)
        return live, app
    return make


def test_server_no_round_opens_while_he_sleeps_and_none_offers_his_activity(server):
    async def run():
        live, app = await server()
        sent = []

        async def broadcast(msg):
            sent.append(msg)
        live.broadcast = broadcast
        v = live.votes
        clk = Clock(1000.0)
        v.clock = clk
        v.retry_at = 0.0
        live.engine.stage = "NREM"
        for _ in range(3):
            await live.audience_tick({"type": "tick"}, live.clock.now(), {}, 0)
            clk.t += 61
        assert v.round is None and not [m for m in sent if m["type"] == "vote"]   # asleep: no round at all
        live.engine.stage = "AWAKE"
        life = live.life
        noon = 1_700_000_000 - (1_700_000_000 % 86400) + 3 * 3600                 # 12:00 in Tokyo
        life.activity = "research"
        clk.t += 61
        await live.audience_tick({"type": "tick"}, noon, {}, 0)
        assert v.round is not None and "research" not in v.round.options            # awake: a round, minus what he does
        assert [m for m in sent if m["type"] == "vote"][-1]["round"]["options"][0]["act"] == v.round.options[0]
    asyncio.run(run())


def test_server_vote_applied_is_broadcast_when_the_activity_starts(server):
    async def run():
        live, app = await server()
        sent = []

        async def broadcast(msg):
            sent.append(msg)
        live.broadcast = broadcast
        v, life = live.votes, live.life
        clk = Clock(1000.0)
        v.clock = clk
        noon = 1_700_000_000 - (1_700_000_000 % 86400) + 3 * 3600
        live.engine.stage = "AWAKE"
        life.activity = "research"
        v.open(["window", "phone"], now=clk.t)
        v.cast(v.fp.ids("a", "1", "x"), 0, now=clk.t)
        clk.t += 61
        await live.audience_tick({"type": "tick"}, noon, {}, 0)                    # the round closes: the nudge is set
        assert v.pending is None and life.nudge(noon) == "window"
        assert not [m for m in sent if m["type"] == "vote_applied"]               # but nothing is announced yet
        await live.audience_tick({"type": "tick"}, noon + 5, {}, 0)
        assert not [m for m in sent if m["type"] == "vote_applied"]
        life.start("window", noon + 10, "goes to the window")                    # his model starts it: now
        await live.audience_tick({"type": "tick"}, noon + 10, {}, 0)
        applied = [m for m in sent if m["type"] == "vote_applied"]
        assert len(applied) == 1 and applied[0]["act"] == "window" and applied[0]["started"] is True
        await live.audience_tick({"type": "tick"}, noon + 20, {}, 0)
        assert len([m for m in sent if m["type"] == "vote_applied"]) == 1          # once
        # a nudge that runs out without a start is dropped quietly; a winner he is already doing is dropped too
        v.open(["phone", "window"], now=clk.t)
        v.cast(v.fp.ids("b", "2", "x"), 0, now=clk.t)
        clk.t += 61
        await live.audience_tick({"type": "tick"}, noon + 30, {}, 0)
        assert life.nudge(noon + 30) == "phone"
        await live.audience_tick({"type": "tick"}, noon + 30 + 2 * 3600, {}, 0)
        assert getattr(live, "vote_due", None) is None
        life.activity = "window"
        v.pending = {"act": "window", "label": "look out of the window", "round": 9, "votes": 1, "total": 1, "at": noon}
        await live.audience_tick({"type": "tick"}, noon + 3 * 3600, {}, 0)
        assert v.pending is None and life.nudge(noon + 3 * 3600) != "window"
        assert len([m for m in sent if m["type"] == "vote_applied"]) == 1
    asyncio.run(run())


# --- A2: the reactions ----------------------------------------------------------------------------------------------
def test_one_viewer_tapping_makes_him_glance():
    clk = Clock(0.0)
    r = Reactions(clock=clk)
    for _ in range(12):                                                     # one key, every 0.1 s
        r.react("solo", 0, addr="home")
        clk.t += 0.1
    assert r.total == audience.REACT_BURST >= audience.SPIKE_N
    assert r.glance_due() == "👋"


def test_reactions_memory_is_bounded():
    clk = Clock(0.0)
    r = Reactions(clock=clk)
    for i in range(audience.RECENT_MAX + 300):
        r.react(f"v{i}", 1)
    assert len(r.recent) <= audience.RECENT_MAX
    clk.t += audience.SPIKE_S + 1
    r.react("late", 1)                                                      # an accepted reaction trims the old ones
    assert len(r.recent) == 1
