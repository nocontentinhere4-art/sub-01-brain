"""Websocket feeds: /ws stays 20 ticks/s with everything; ?rate= and &lite=1 thin it without losing trades; &q=1 is the
brain page's quantised feed. Each variant is serialised once; viewer caps; slow clients skip ticks (issue #14)."""
import asyncio
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import live_server  # noqa: E402
from live_server import ACT_HI, ACT_LO, TICK, WS_HIGH_WATER, Feed, Live, dequantise_act, quantise_act  # noqa: E402


LIFE = {"place": "bed", "activity": "phone", "hunger": 0.4,
        "vitals": {"hr_bpm": 64.0, "resp_per_min": 14.0, "glucose_mg_dl": 92.0}}
NEURO = {"DA": 1.0, "5HT": 0.9, "NE": 1.1, "ACh": 1.2}


def tick(i, trades=(), events=()):
    return {"type": "tick", "i": i, "act": [0.1] * 214, "wave": {"a": 1.0}, "groups": {"a": 0.1}, "slow": None,
            "trades": list(trades), "events": list(events), "life": LIFE, "neuro": NEURO, "sleep": {"stage": "AWAKE"}}


def run(feed, msgs):
    return [json.loads(o) if o is not None else None for o in (feed.take(m, json.dumps(m)) for m in msgs)]


def test_default_is_unchanged():
    f = Feed.from_query({})
    for m in [tick(0), {"type": "chat", "text": "hi"}, tick(1)]:
        data = json.dumps(m)
        assert f.take(m, data) is data


def test_rate_downsamples_and_carries_trades_and_events():
    f = Feed.from_query({"rate": "5"})
    assert f.every == round(1 / (TICK * 5))
    msgs = [tick(i, trades=[{"kind": "buy", "usd": i}] if i % 3 == 0 else [],
                 events=[{"type": "wake", "i": i}] if i == 6 else []) for i in range(12)]
    out = run(f, msgs)
    sent = [o for o in out if o is not None]
    assert [o["i"] for o in sent] == [0, 4, 8]                      # first at once, then every 4th
    got = [t["usd"] for o in sent for t in o["trades"]]
    assert got == [0, 3, 6]                                          # nothing lost up to the last sent tick
    assert [e["i"] for o in sent for e in o["events"]] == [6]
    assert sent[1]["act"] == msgs[4]["act"]                          # not lite: the brain arrays stay


def test_non_ticks_always_pass_through():
    f = Feed.from_query({"rate": "2", "lite": "1"})
    m = {"type": "screen", "device": "desk", "id": 3}
    data = json.dumps(m)
    assert f.take(m, data) is data


def test_lite_drops_brain_arrays_only():
    f = Feed.from_query({"lite": "1"})
    o = run(f, [tick(0, trades=[{"kind": "sell", "usd": 9}])])[0]
    assert "act" not in o and "wave" not in o and "groups" not in o and "slow" not in o
    assert o["life"] == LIFE and o["sleep"]["stage"] == "AWAKE" and o["trades"][0]["usd"] == 9


def test_bad_rates_fall_back_to_every_tick():
    for q in ({"rate": "abc"}, {"rate": "0"}, {"rate": "-5"}, {"rate": "nan"}, {"rate": "inf"}):
        assert Feed.from_query(q).every == 1
    assert Feed.from_query({"rate": "1000"}).every == 1               # faster than the tick: every tick


def test_lite_keeps_what_the_room_shows():
    """The room's cards need life (with the body's vitals), the neuromodulators, sleep, trades and events."""
    f = Feed.from_query({"rate": "5", "lite": "1"})
    msgs = [tick(i, trades=[{"kind": "buy", "usd": i}], events=[{"type": "replay", "i": i}]) for i in range(5)]
    sent = [o for o in run(f, msgs) if o is not None]
    last = sent[-1]
    assert last["life"]["vitals"] == LIFE["vitals"] and last["neuro"] == NEURO and last["sleep"]["stage"] == "AWAKE"
    assert [t["usd"] for o in sent for t in o["trades"]] == [0, 1, 2, 3, 4]
    assert [e["i"] for o in sent for e in o["events"]] == [0, 1, 2, 3, 4]


def test_rate_is_clamped_to_1_20_per_second():
    slowest, fastest = round(1 / (TICK * 1)), 1
    for q in ("1e-310", "1e-9", "0.5", "1"):                         # tiny rates: at least one tick a second
        assert Feed.from_query({"rate": q}).every == slowest, q    # (1e-310 used to raise OverflowError)
    for q in ("20", "1000", "1e308"):
        assert Feed.from_query({"rate": q}).every == fastest, q


def test_tiny_rate_does_not_buffer_without_bound():
    f = Feed.from_query({"rate": "1e-9", "lite": "1"})
    sent = 0
    for i in range(10 * f.every):
        sent += run(f, [tick(i, trades=[{"kind": "buy", "usd": 1}])])[0] is not None
        assert len(f.trades) < f.every                                # flushed at least once a second
    assert sent == 10



# --- launch load (issue #14): one serialisation per variant, caps, slow clients, quantised brain feed ---------------
def bare_live(max_ws=400, max_ws_ip=4, trust_proxy=False):
    """A Live with only its websocket parts (no brain, no state files)."""
    live = Live.__new__(Live)
    live.init_sockets()
    live.max_ws, live.max_ws_ip, live.trust_proxy = max_ws, max_ws_ip, trust_proxy
    live.memory = SimpleNamespace(chat=lambda: [])
    live.nights = lambda: {"type": "nights", "last": None, "tonight": None}
    live.last_frame = None
    return live


class FakeTransport:
    def __init__(self, held=0):
        self.held = held

    def get_write_buffer_size(self):
        return self.held


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_str(self, text):
        self.sent.append(text)


def join(live, query, held=0):
    ws = FakeWS()
    live.feeds[ws] = live.feed_for(query)
    live.transports[ws] = FakeTransport(held)
    live.clients.add(ws)
    return ws


def big_tick(i, trades=()):
    """Shaped like a real --demo tick (214 regions, the reading card, the slow layer's label)."""
    return {"type": "tick", "act": [round(0.05 + 4.5 * ((i + k) % 37) / 37, 3) for k in range(214)],
            "wave": {g: 0.1 for g in "abcdefghijkl"}, "groups": {g: 0.5 for g in "abcdefghijkl"}, "sync": 0.31,
            "stats": {"buys": 3, "sells": 1, "usd": 120.0}, "trades": list(trades), "pool": "demo", "events": [],
            "sleep": {"stage": "AWAKE", "clock": "11:53", "tz": "Tokyo", "date": "Fri 02 Oct", "debt": 0.0,
                      "tired": 0.0, "depth": 0.0, "gain": 1.0, "arousal": 0.0, "woken_tonight": 0, "H": 12.71,
                      "C": 0.635, "V_m": 0.75, "V_v": -9.9, "V_on": -19.35, "V_off": 1.99, "rem_p": 0.001,
                      "pressure": 0.365, "cycle": 0, "modulators": NEURO, "burst": 0.0},
            "baseline": None,
            "slow": {"model": "Hopf slow layer", "connectome": "connectome_v2", "heldout_fc_r": 0.206,
                     "label": "slow activity of a model on his wiring (one fitted coupling). Similarity of its "
                              "co-activity pattern to his recorded activity on unseen sessions: r = 0.21; "
                              "randomised wiring: r = 0.16-0.17"},
            "life": LIFE | {"doing": "reading at the computer", "walking": False, "say": "curious",
                            "reading": {"title": "Tokyo", "extract": "Tokyo is the capital of Japan. " * 10}},
            "neuro": NEURO}


def test_one_serialisation_per_variant_not_per_client(monkeypatch):
    calls = []
    real = json.dumps
    monkeypatch.setattr(live_server.json, "dumps", lambda *a, **k: calls.append(1) or real(*a, **k))

    def run_ticks(n_per_variant):
        live = bare_live()
        groups = {q: [join(live, dict(p.split("=") for p in q.split("&")) if q else {}) for _ in range(n_per_variant)]
                  for q in ("", "rate=10&q=1", "rate=5&lite=1")}
        calls.clear()
        for i in range(20):
            asyncio.run(live.broadcast(big_tick(i)))
        return len(calls), groups

    n_small, _ = run_ticks(2)
    n_big, groups = run_ticks(50)
    assert n_small == n_big == 20 + 10 + 5            # the tick once + q every 2nd tick + lite every 4th
    for q, n in (("", 20), ("rate=10&q=1", 10), ("rate=5&lite=1", 5)):
        assert all(len(ws.sent) == n for ws in groups[q]), q
        assert len({id(ws.sent[0]) for ws in groups[q]}) == 1          # the very same string to every client


def test_variants_are_shared_and_released():
    live = bare_live()
    a, b = join(live, {"rate": "10", "q": "1"}), join(live, {"rate": "10.4", "q": "true"})
    assert live.feeds[a] is live.feeds[b] and len(live.variants) == 1
    live.drop_client(a)
    assert len(live.variants) == 1
    live.drop_client(b)
    assert live.variants == {}


def test_variant_phases_spread_the_sends_over_ticks():
    """The brain page (10/s), the room (5/s lite) and its mini brain (5/s q) do not all send on the same tick."""
    live = bare_live()
    asyncio.run(live.broadcast(big_tick(0)))                            # the tick counter is not at 0
    clients = {q: join(live, dict(x.split("=") for x in q.split("&")))
               for q in ("rate=10&q=1", "rate=5&lite=1", "rate=5&q=1")}
    per_tick = []
    for i in range(40):
        before = {q: len(ws.sent) for q, ws in clients.items()}
        asyncio.run(live.broadcast(big_tick(i)))
        per_tick.append(sum(len(ws.sent) - before[q] for q, ws in clients.items()))
    assert [len(ws.sent) for ws in clients.values()] == [20, 10, 10]
    assert max(per_tick) == 1                                           # never two of the three on one tick


def test_quantised_act_round_trip():
    vals = [ACT_LO, 0.02, 0.047, 0.1, 0.33, 1.0, 2.5, 4.58, ACT_HI]
    back = dequantise_act(quantise_act(vals))
    step = (ACT_HI / ACT_LO) ** (1 / 255)                  # one byte step on the log scale (~2.7 %)
    for v, w in zip(vals, back):
        assert abs(w / v - 1) <= math.sqrt(step) - 1 + 1e-9, (v, w)     # at most half a step: ~1.4 %
    assert dequantise_act(quantise_act([0.0, -1.0, 1e-6, 50.0])) == pytest.approx([ACT_LO, ACT_LO, ACT_LO, ACT_HI])
    assert len(quantise_act([1.0] * 214)) == 288                         # 214 bytes -> 288 base64 chars


def test_brain_feed_is_small_and_keeps_what_the_brain_page_draws():
    f = Feed.from_query({"rate": "10", "q": "1"})
    assert f.every == 2 and f.q and not f.lite
    m = big_tick(3, trades=[{"kind": "buy", "usd": 12.0, "tx": "abc", "who": "x"}])
    m["events"] = [{"type": "replay", "t": "01:00", "text": "hello", "networks": ["default"], "received": "12:00"}]
    text = f.take(m, json.dumps(m))
    assert len(json.dumps(m)) > 3000 and len(text) < 1500, len(text)
    o = json.loads(text)
    assert "act" not in o and "wave" not in o and "groups" not in o and "neuro" not in o
    assert dequantise_act(o["aq"]) == pytest.approx(m["act"], rel=0.015)
    assert o["life"] == {"doing": "reading at the computer", "walking": False}
    assert o["sleep"]["stage"] == "AWAKE" and o["sleep"]["clock"] == "11:53" and "burst" in o["sleep"]
    assert o["slow"] == {"label": m["slow"]["label"]} and o["sync"] == 0.31
    assert o["trades"][0]["usd"] == 12.0 and o["events"][0]["text"] == "hello"
    assert f.take(m, "x") is None                                         # 10/s: every other tick
    assert Feed.from_query({"lite": "1", "q": "1"}).q is False            # lite wins: no brain at all


def test_slow_client_skips_ticks_and_never_blocks():
    live = bare_live()
    fast = join(live, {"rate": "10", "q": "1"})
    slow = join(live, {"rate": "10", "q": "1"}, held=10 ** 6)            # 1 MB still queued
    full_rate = join(live, {})
    for i in range(10):
        asyncio.run(live.broadcast(big_tick(i)))
    assert len(fast.sent) == 5 and slow.sent == [] and len(full_rate.sent) == 10
    assert live.ws_stats["skipped"] == 5
    # held > 1 s of its feed: ~1 KB x 10/s -> the WS_SLOW_MIN floor (16 KB) decides; just under it, it gets ticks
    live.transports[slow].held = 15 * 1024
    asyncio.run(live.broadcast(big_tick(10)))
    asyncio.run(live.broadcast(big_tick(11)))
    assert len(slow.sent) == 1
    # a plain /ws client (~4 KB x 20/s = ~80 KB/s): 40 KB queued is under a second, 100 KB is not
    live.transports[full_rate].held = 40 * 1024
    asyncio.run(live.broadcast(big_tick(12)))
    live.transports[full_rate].held = 100 * 1024
    asyncio.run(live.broadcast(big_tick(13)))
    assert len(full_rate.sent) == 13
    # rare messages (chat, eye) still reach a slow socket unless it is half full
    live.transports[slow].held = 10 ** 5
    asyncio.run(live.broadcast({"type": "chat", "text": "hi"}))
    assert slow.sent[-1] == json.dumps({"type": "chat", "text": "hi"})
    live.transports[slow].held = WS_HIGH_WATER
    asyncio.run(live.broadcast({"type": "chat", "text": "again"}))
    assert slow.sent[-1] != json.dumps({"type": "chat", "text": "again"})


def test_a_failed_send_drops_the_client():
    live = bare_live()
    ok = join(live, {})

    class Broken(FakeWS):
        async def send_str(self, text):
            raise ConnectionResetError

    bad = Broken()
    live.feeds[bad] = live.feed_for({"rate": "5", "lite": "1"})
    live.clients.add(bad)
    for i in range(4):                                                   # its feed's phase comes round
        asyncio.run(live.broadcast(big_tick(i)))
    assert bad not in live.clients and bad not in live.feeds and len(live.variants) == 1 and len(ok.sent) == 4


async def _open(client, ip):
    ws = await client.ws_connect("/ws?rate=5&lite=1", headers={"X-Forwarded-For": f"{ip}, 10.0.0.1"})
    first = await ws.receive_json(timeout=5)
    return ws, first["type"]


async def _wait(cond, timeout=5.0):
    t0 = asyncio.get_running_loop().time()
    while not cond():
        assert asyncio.get_running_loop().time() - t0 < timeout
        await asyncio.sleep(0.01)


def test_caps_total_and_per_ip():
    async def main():
        live = bare_live(max_ws=3, max_ws_ip=2, trust_proxy=True)
        app = web.Application()
        app.router.add_get("/ws", live.ws_handler)
        async with TestClient(TestServer(app)) as client:
            a1, t1 = await _open(client, "1.1.1.1")
            a2, t2 = await _open(client, "1.1.1.1")
            a3, t3 = await _open(client, "1.1.1.1")                  # 3rd from the same address: over the per-IP cap
            assert (t1, t2, t3) == ("hello", "hello", "full")
            closed = await a3.receive(timeout=5)
            assert closed.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED) and a3.close_code == 1013
            b1, tb = await _open(client, "2.2.2.2")
            c1, tc = await _open(client, "3.3.3.3")                  # 4th socket overall: over the total cap
            assert (tb, tc) == ("hello", "full")
            assert len(live.sockets) == 3 and live.ws_per_ip == {"1.1.1.1": 2, "2.2.2.2": 1}
            assert live.ws_stats["refused"] == 2
            await a1.close()
            await _wait(lambda: len(live.sockets) == 2)
            c2, tc2 = await _open(client, "3.3.3.3")                 # a slot freed: let in
            assert tc2 == "hello" and live.ws_per_ip == {"1.1.1.1": 1, "2.2.2.2": 1, "3.3.3.3": 1}
            for ws in (a2, b1, c2, c1):
                await ws.close()
            await _wait(lambda: not live.sockets)
            assert live.ws_per_ip == {} and live.clients == set() and live.variants == {}

    asyncio.run(main())


def test_without_trust_proxy_the_header_is_ignored():
    async def main():
        live = bare_live(max_ws=10, max_ws_ip=1, trust_proxy=False)
        app = web.Application()
        app.router.add_get("/ws", live.ws_handler)
        async with TestClient(TestServer(app)) as client:
            a, ta = await _open(client, "1.1.1.1")
            b, tb = await _open(client, "2.2.2.2")                   # same real address (127.0.0.1)
            assert (ta, tb) == ("hello", "full")
            await a.close()
            await b.close()

    asyncio.run(main())
