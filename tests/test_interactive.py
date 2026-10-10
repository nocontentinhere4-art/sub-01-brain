"""Viewers in the room (preview/interactive, audience.py): the vote round (one vote per viewer, the tie rule, a result
that waits while he sleeps, options only from what his activity model allows at that hour), the reactions' rate limit
and spike glance, and the server wiring (cookie, ws messages, the tick's viewer count and reaction sums)."""
import asyncio
import json
import random

import pytest

import audience
from audience import Reactions, TokenBucket, VoteRound, Votes, pick_options
from life import Life, VOTE_BONUS


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


# --- the vote round ----------------------------------------------------------------------------------------------
def test_one_vote_per_viewer_per_round():
    v = Votes(round_s=60, rng=random.Random(1), clock=Clock())
    v.open(["research", "park", "window"])
    a = v.fp.ids("cookie-a", "1.2.3.4", "UA-a")
    assert v.cast(a, 1) == (True, "")
    assert v.cast(a, 0)[0] is False                                    # same cookie, same IP + UA
    assert v.cast(v.fp.ids("cookie-a", "9.9.9.9", "other"), 0)[0] is False   # same cookie, other network: still voted
    # no cookie, same IP + UA: a cookieless viewer is known by IP + UA alone, so this counts (two people on one network
    # with the same browser both vote; a script clearing its cookie runs into the per-address cap, VOTES_PER_ADDRESS)
    assert v.cast(v.fp.ids(None, "1.2.3.4", "UA-a"), 0) == (True, "")
    assert v.cast(v.fp.ids(None, "1.2.3.4", "UA-a"), 2)[0] is False    # (and only once)
    assert v.cast(v.fp.ids("cookie-b", "5.6.7.8", "UA-b"), 1) == (True, "")
    assert v.round.counts == [1, 2, 0]
    assert v.mine(a) == 1


def test_vote_rejects_bad_options_and_closed_rounds():
    clk = Clock()
    v = Votes(round_s=60, clock=clk)
    v.open(["research", "park"])
    ids = v.fp.ids("c", "ip", "ua")
    for bad in (-1, 2, "0", None, True, 1.0):
        assert v.cast(ids, bad)[0] is False
    clk.t += 61
    assert v.cast(ids, 0) == (False, "this round has ended")


def test_new_round_new_salt_and_no_hashes_kept():
    clk = Clock()
    v = Votes(round_s=60, clock=clk)
    v.open(["research", "park"])
    ids = v.fp.ids("c", "ip", "ua")
    v.cast(ids, 0)
    r = v.round
    clk.t += 60
    assert v.due()
    v.close(sim_t=0)
    assert r.voted == {}                                              # who voted is forgotten with the round
    v.open(["research", "park"])
    assert v.cast(ids, 1) == (True, "")                               # a new round: one more vote
    # nothing raw: the stored keys are hex hashes, not the address or the cookie
    assert all(len(k) == 24 and "ip" not in k for k in v.round.voted)


def test_tie_goes_to_the_option_listed_first():
    r = VoteRound(1, 0, 60, ["research", "park", "window"])
    r.counts = [2, 3, 3]
    assert r.winner() == 1                                            # park and window tie: park is listed first
    r.counts = [4, 4, 4]
    assert r.winner() == 0
    r.counts = [0, 0, 0]
    assert r.winner() is None                                         # no votes: no nudge


def test_options_listed_in_his_models_order():
    now = {"research": 0.9, "park": 1.4, "window": 0.2, "phone": 0.5}
    opts = pick_options(now, now, random.Random(3), n=3, votable=dict.fromkeys(now, ""))
    assert opts == sorted(opts, key=lambda a: -now[a]) and len(opts) == 3


def test_options_only_what_the_schedule_allows():
    life = Life(rng=random.Random(0))
    rel = {}
    three_am = 1_700_000_000 - (1_700_000_000 % 86400) + 18 * 3600    # 18:00 UTC = 03:00 in Tokyo
    for seed in range(30):
        opts = pick_options(life.scores(three_am, rel, 0, 0), life.scores(three_am + 3600, rel, 0, 0),
                            random.Random(seed))
        assert opts and "park" not in opts and "play_chess" not in opts   # no going out, no chess at 3 am
        assert set(opts) <= set(audience.VOTABLE)                         # never food, sleep or the chart
    # possible now but not at the round's end (19:30 -> 20:30 in Tokyo: the park closes at 20:00): left out
    t1930 = 1_700_000_000 - (1_700_000_000 % 86400) + 10 * 3600 + 30 * 60
    s_now, s_end = life.scores(t1930, rel, 0, 0), life.scores(t1930 + 3600, rel, 0, 0)
    assert s_now["park"] > 0 and s_end["park"] == 0
    assert all("park" not in pick_options(s_now, s_end, random.Random(k)) for k in range(30))


def test_asleep_the_result_waits_until_he_wakes():
    clk = Clock()
    v = Votes(round_s=60, clock=clk)
    v.open(["research", "park", "window"])
    v.cast(v.fp.ids("a", "1", "x"), 2)
    clk.t += 60
    res = v.close(sim_t=5000)
    assert res["winner"] == "window" and res["total"] == 1
    assert v.take_pending(5100, awake=False) is None                  # asleep: not applied
    assert v.take_pending(9000, awake=False) is None                  # still asleep
    p = v.take_pending(9100, awake=True)                              # awake: applied once
    assert p["act"] == "window"
    assert v.take_pending(9200, awake=True) is None
    # a result that waits longer than PENDING_MAX_S is dropped
    v.pending = {"act": "park", "label": "", "round": 9, "votes": 1, "total": 1, "at": 0}
    assert v.take_pending(audience.PENDING_MAX_S + 1, awake=True) is None and v.pending is None


def test_nudge_tilts_his_choice_but_never_the_impossible():
    life = Life(rng=random.Random(0))
    noon = 1_700_000_000 - (1_700_000_000 % 86400) + 3 * 3600          # 12:00 in Tokyo
    base = life.scores(noon, {}, 0, 0)
    life.apply_vote("window", noon)
    assert life.scores(noon, {}, 0, 0)["window"] == pytest.approx(base["window"] + VOTE_BONUS)
    life.apply_vote("park", noon - 15 * 3600)                          # (applied long ago: the hold ran out)
    assert life.nudge(noon) is None
    three_am = noon - 9 * 3600
    life.apply_vote("park", three_am)
    assert life.scores(three_am, {}, 0, 0)["park"] == 0                # the park stays closed at 3 am
    assert not life.apply_vote("sleep", noon)


def test_nudge_is_carried_out_when_awake():
    life = Life(rng=random.Random(0))
    noon = 1_700_000_000 - (1_700_000_000 % 86400) + 3 * 3600
    life.start("research", noon, "reads")
    life.place, life.path = "desk", []
    life.x, life.z = life.x, life.z
    life.apply_vote("window", noon + 60)
    life.update(noon + 60, 0.05, 0.05, "AWAKE", {}, 0, 0)
    assert life.activity == "window" and "viewers voted for it" in life.say
    assert life.viewer_nudge is None                                   # spent once carried out


# --- reactions ------------------------------------------------------------------------------------------------------
def test_reaction_rate_limit_burst_then_one_every_3s():
    clk = Clock(0.0)
    b = TokenBucket(every=3.0, burst=5, clock=clk)
    assert [b.allow("v") for _ in range(7)] == [True] * 5 + [False] * 2   # a burst of 5, then nothing
    clk.t += 2.9
    assert not b.allow("v")
    clk.t += 0.2                                                          # 3.1 s: one more token
    assert b.allow("v") and not b.allow("v")
    assert b.allow("other")                                               # per viewer
    clk.t += 300                                                          # a long pause: the burst is back, capped at 5
    assert sum(b.allow("v") for _ in range(10)) == 5


def test_reactions_summed_and_only_the_fixed_set():
    r = Reactions(clock=Clock(0.0))
    assert r.react("a", 0)[0] and r.react("a", 0)[0] and r.react("b", 3)[0]
    assert r.react("a", len(audience.REACTIONS))[0] is False
    assert r.react("a", "🔥")[0] is False                                 # no free text
    assert r.drain() == [2, 0, 0, 1, 0, 0]
    assert r.drain() is None


def test_spike_glance_names_its_dominant_reaction():
    """The glance carries the spike's most-sent reaction (it picks his answer: desk_states.js GLANCE); a tie goes to the
    latest of the tied ones."""
    clk = Clock(0.0)
    r = Reactions(clock=clk)
    for i, k in enumerate([2, 2, 2, 2, 0, 0, 1, 2, 5, 2]):              # mostly the laugh
        r.react(f"v{i}", k)
    assert r.glance_due() == "😂"
    clk.t += 130
    for i, k in enumerate([0, 0, 0, 0, 0, 4, 4, 4, 4, 4]):              # 5 waves, 5 claps: the claps came last
        r.react(f"w{i}", k)
    assert r.glance_due() == "👏"


def test_spike_glance_at_most_once_per_2_min():
    clk = Clock(0.0)
    r = Reactions(clock=clk)
    for i in range(9):
        r.react(f"v{i}", 1)
    assert not r.glance_due()                                             # 9 in 10 s: not yet
    r.react("v9", 1)
    assert r.glance_due() and not r.glance_due()                          # 10: once
    clk.t += 60
    for i in range(10):
        r.react(f"w{i}", 1)
    assert not r.glance_due()                                             # a minute later: too soon
    clk.t += 61
    for i in range(10):
        r.react(f"x{i}", 1)
    assert r.glance_due()                                                 # past 2 minutes: again
    clk.t += 200
    for i in range(10):                                                   # 10 spread over 20 s: no spike
        r.react(f"y{i}", 1)
        clk.t += 2.0
    assert not r.glance_due()


# --- the server ---------------------------------------------------------------------------------------------------
def test_feed_sums_reactions_over_skipped_ticks():
    from live_server import Feed
    f = Feed(rate=5, lite=True)
    sent = []
    for i in range(8):
        msg = {"type": "tick", "trades": [], "events": [], "aud": {"n": 3, "v": None}}
        if i in (1, 2, 5):
            msg["rx"] = [1, 0, 0, 0, 0, 2]
        out = f.take(msg, json.dumps(msg))
        if out:
            sent.append(json.loads(out))
    total = [sum(m.get("rx", [0] * 6)[k] for m in sent) for k in range(6)]
    assert total[0] + 0 <= 3 and all(m["aud"]["n"] == 3 for m in sent)
    # what was not sent yet stays summed for the next send
    assert total[0] + (f.rx[0] if f.rx else 0) == 3


@pytest.fixture
def server(tmp_path):
    aiohttp = pytest.importorskip("aiohttp")
    from aiohttp import web
    import live_server

    async def make():
        live = live_server.Live(None, True, 1.0, tmp_path)
        live.votes.round_s = 60
        app = web.Application(middlewares=[live_server.viewer_cookie])
        app.router.add_get("/ws", live.ws_handler)
        async def page(request):
            return web.Response(text="room", content_type="text/html")
        app.router.add_get("/", page)
        return live, app
    return make


def test_server_cookie_vote_and_react(server):
    from aiohttp.test_utils import TestClient, TestServer

    async def run():
        live, app = await server()
        tsim = live.clock.now()
        async with TestClient(TestServer(app)) as c:
            r = await c.get("/")
            ck = r.cookies.get(audience.VIEWER_COOKIE)
            assert ck is not None and ck["httponly"]
            live.votes.open(["research", "window", "phone"])
            ws = await c.ws_connect("/ws")
            hello = await ws.receive_json()
            assert hello["type"] == "hello" and hello["audience"]["reactions"] == list(audience.REACTIONS)
            assert hello["audience"]["vote"]["round"]["options"][0]["act"] == "research"
            await ws.receive_json()                                    # nights
            await ws.send_json({"type": "vote", "k": 2})
            ack = await ws.receive_json()
            assert ack == {"type": "vote_ack", "ok": True, "reason": "", "mine": 2}
            ws2 = await c.ws_connect("/ws")                            # same browser (cookie), a second tab
            await ws2.receive_json(); await ws2.receive_json()
            await ws2.send_json({"type": "vote", "k": 0})
            ack2 = await ws2.receive_json()
            assert ack2["ok"] is False and ack2["mine"] == 2
            for _ in range(audience.REACT_BURST + 1):
                await ws.send_json({"type": "react", "k": 1})
            nack = await ws.receive_json()
            assert nack == {"type": "react_ack", "ok": False, "reason": "slow down"}
            msg = {"type": "tick"}
            await live.audience_tick(msg, tsim, {}, 0)
            assert msg["aud"]["n"] == 2 and msg["rx"] == [0, audience.REACT_BURST, 0, 0, 0, 0]
            assert msg["aud"]["v"][1] == [0, 0, 1]
            # nothing about the viewer in what the server keeps: hashes only
            assert all(len(i) == 24 for ids in live.viewer_ids.values() for i in ids)
            assert "127.0.0.1" not in json.dumps(list(live.viewer_ids.values()))
            await ws.close(); await ws2.close()
    asyncio.run(run())


def test_server_round_end_applies_when_awake(server):
    async def run():
        live, app = await server()
        v = live.votes
        clk = Clock(1000.0)
        v.clock = clk
        v.open(["window", "research"], now=clk.t)
        v.cast(v.fp.ids("a", "1", "x"), 0, now=clk.t)
        clk.t += 61
        live.engine.stage = "NREM"                                    # asleep when the round ends
        msg = {"type": "tick"}
        await live.audience_tick(msg, live.clock.now(), {}, 0)
        assert v.pending and v.pending["act"] == "window" and live.life.nudge(live.clock.now()) is None
        live.engine.stage = "AWAKE"                                    # he wakes up: now it is applied
        live.life.activity = "research"                               # (the demo starts him at the window: a vote for what he
        await live.audience_tick({"type": "tick"}, live.clock.now(), {}, 0)   # already does is dropped, not nudged)
        assert v.pending is None and live.life.nudge(live.clock.now()) == "window"
    asyncio.run(run())


def test_server_glance_only_when_awake(server):
    async def run():
        live, app = await server()
        sent = []

        async def broadcast(msg):
            sent.append(msg)
        live.broadcast = broadcast
        live.votes.open(["window", "research"])
        for i in range(10):
            live.reactions.react(f"v{i}", 0)
        seated = {"place": "desk", "pose": "sitting_desk", "geo": None}
        live.engine.stage = "REM"
        await live.audience_tick({"type": "tick", "life": seated}, live.clock.now(), {}, 0)
        assert not any(m["type"] == "glance" for m in sent)            # asleep: he does not turn to the camera
        live.engine.stage = "AWAKE"
        for life in ({"place": "bed", "pose": "lying_headphones"}, {"place": "bench", "pose": "sitting"}):
            await live.audience_tick({"type": "tick", "life": life}, live.clock.now(), {}, 0)
        assert not any(m["type"] == "glance" for m in sent)            # lying on the bed, out at the park: not either
        await live.audience_tick({"type": "tick", "life": seated}, live.clock.now(), {}, 0)
        assert sum(m["type"] == "glance" for m in sent) == 1            # at the desk: once
    asyncio.run(run())


def test_abuse_rapid_requests_and_cookieless_clients(server):
    """50 rapid votes and reactions from one viewer, a cookie-less client, a client with a new cookie per connection
    and one with a new cookie and user agent per connection: the counts never move past the limits; /api/vote takes no
    votes."""
    import aiohttp
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    async def run():
        live, app = await server()
        async def vote_api(request):
            return web.json_response(live.votes.public())
        app.router.add_get("/api/vote", vote_api)
        live.votes.round_s = 3600                                       # (the round must outlast the test)
        frozen = lambda: 1000.0                                         # no refill while the test runs (the
        live.reactions.limit.clock = live.reactions.limit_ip.clock = frozen   # limits, not the machine's speed)
        live.votes.open(["research", "window", "phone"])
        tsim = live.clock.now()

        async def drain_acks(ws, n):
            acks = []
            for _ in range(n):
                try:
                    acks.append(await asyncio.wait_for(ws.receive_json(), 2))
                except asyncio.TimeoutError:
                    break
            return acks

        async def counts():
            msg = {"type": "tick"}
            await live.audience_tick(msg, tsim, {}, 0)
            return list(live.votes.round.counts), sum(msg.get("rx") or [])

        async with TestClient(TestServer(app)) as c:
            await c.get("/")                                            # gets the cookie
            ws = await c.ws_connect("/ws", headers={"User-Agent": "UA-a"})
            await ws.receive_json(); await ws.receive_json()
            for _ in range(50):                                         # one viewer, 50 votes, 50 reactions
                await ws.send_json({"type": "vote", "k": 0})
            for _ in range(50):
                await ws.send_json({"type": "react", "k": 1})
            acks = await drain_acks(ws, 100)
            votes = [a for a in acks if a["type"] == "vote_ack"]
            assert len(votes) == 50 and sum(a["ok"] for a in votes) == 1
            B = audience.REACT_BURST
            assert sum(1 for a in acks if a["type"] == "react_ack") == 50 - B       # a burst got through, the rest refused
            assert await counts() == ([1, 0, 0], B)

            # a cookie-less client (no cookie jar), its own user agent: one vote, a burst of reactions, no more
            async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as s:
                url = c.make_url("/ws")
                ws2 = await s.ws_connect(url, headers={"User-Agent": "UA-b"})
                await ws2.receive_json(); await ws2.receive_json()
                for _ in range(50):
                    await ws2.send_json({"type": "vote", "k": 1})
                    await ws2.send_json({"type": "react", "k": 2})
                await drain_acks(ws2, 100)
                assert await counts() == ([1, 1, 0], min(B, audience.REACT_IP_BURST - B))   # (the address's bucket, part used)
                await ws2.close()
                # the same browser, a made-up cookie on every connection: not one the server issued, so it counts for
                # nothing - the same IP + UA as before, nothing more counts
                for i in range(6):
                    w = await s.ws_connect(url, headers={"User-Agent": "UA-b", "Cookie": f"sub01v=fake{i}"})
                    await w.receive_json(); await w.receive_json()
                    for _ in range(10):
                        await w.send_json({"type": "vote", "k": 2})
                        await w.send_json({"type": "react", "k": 3})
                    await drain_acks(w, 20)
                    await w.close()
                assert await counts() == ([1, 1, 0], 0)
                # a new cookie AND a new user agent on every connection (one machine posing as many): the address caps
                for i in range(40):
                    w = await s.ws_connect(url, headers={"User-Agent": f"UA-fake-{i}", "Cookie": f"sub01v=x{i}"})
                    await w.receive_json(); await w.receive_json()
                    await w.send_json({"type": "vote", "k": 2})
                    for _ in range(5):
                        await w.send_json({"type": "react", "k": 4})
                    await drain_acks(w, 6)
                    await w.close()
                c_votes, rx = await counts()
                assert sum(c_votes) == audience.VOTES_PER_ADDRESS               # 2 + 23 more from the fake ones, then the cap
                assert rx <= audience.REACT_IP_BURST                            # the address's bucket (already part used)

            # /api/vote is read-only
            r = await c.post("/api/vote", json={"k": 0})
            assert r.status == 405
            r = await c.get("/api/vote?k=0")
            assert (await r.json())["round"]["total"] == audience.VOTES_PER_ADDRESS
            await ws.close()
    asyncio.run(run())

