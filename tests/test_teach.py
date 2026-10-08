"""Teach him something (#31): a viewer's word or short phrase is filtered, limited, stored with source "taught",
replayed at a stronger but capped weight, sent to the GPU session and shown on /api/taught.

    python -m pytest tests/test_teach.py
No GPU and no network.
"""
import asyncio
import json
import random
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chat                                                                                   # noqa: E402
import live_server                                                                            # noqa: E402
from sleep import ROME, Memory, day_of                                                        # noqa: E402
from spiking import pod_manager, server as spiking_server                                     # noqa: E402
from spiking.words import half_cue_ok                                                            # noqa: E402


def tokyo(day, hm):
    h, m = map(int, hm.split(":"))
    return datetime(2026, 10, day, h, m, tzinfo=ROME).timestamp()


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, msg):
        self.sent.append(msg)


def make_live(tmp_path, t):
    live = live_server.Live("m", True, data_dir=tmp_path)
    live.clock = SimpleNamespace(now=lambda: live.t_now)
    live.t_now = t
    live.broadcasts = []

    async def broadcast(msg):
        live.broadcasts.append(msg)
    live.broadcast = broadcast
    return live


def teach(live, key, text, nick=""):
    ws = FakeWS()
    asyncio.run(live.handle_teach(ws, key, text, nick))
    return ws.sent[-1]


# --- 1. filters and limits ---------------------------------------------------------------------------------
def test_teach_filter_words_and_nickname_rules():
    lim, day = chat.TeachLimits(), "2026-10-01"
    ok = lambda text, nick="", key="a": chat.check_teach(text, nick, key, lim, day, [])
    assert ok("  red   bicycle ", "Mika") == (True, None, "red bicycle", "Mika")
    assert ok("visit www.example.com", key="b")[1] == "links are not allowed"
    assert ok("buy $COIN now", key="c")[1] == "tickers are not allowed"
    assert ok("you are stupid", key="d")[1] == "insults are not allowed"
    assert ok("one two three four five six seven", key="e")[1] == "max 6 words"
    assert ok("", key="f")[1] == "empty"
    # nickname: same rules, max 16 characters, display only
    assert ok("moon", "x" * 17, key="g")[1] == "nickname: max 16 characters"
    assert ok("moon", "t.me/spam", key="h")[1] == "nickname: links are not allowed"
    assert ok("moon", "$PUMP", key="i")[1] == "nickname: tickers are not allowed"
    assert ok("moon", "0xdeadbeef", key="j")[1] == "nickname: addresses are not allowed"
    assert ok("moon", "idiot", key="k")[1] == "nickname: insults are not allowed"
    # rejected attempts never use up the viewer's teach for the day
    assert ok("lighthouse keeper", key="b")[0]


def test_one_teach_per_viewer_per_day_and_30_in_total():
    lim = chat.TeachLimits()
    assert chat.check_teach("moon", "", "ip1", lim, "d1", [])[0]
    assert chat.check_teach("sun", "", "ip1", lim, "d1", ["moon"])[1] == "one teach per viewer per day"
    assert chat.check_teach("MOON!", "", "ip2", lim, "d1", ["moon"])[1] == "already taught today"
    assert chat.check_teach("sun", "", "ip1", lim, "d2", [])[0]                       # a new day, a new teach
    full = [f"w{i}" for i in range(chat.TEACH_PER_DAY)]
    assert "taught 30 things today" in chat.check_teach("sun", "", "ip9", lim, "d2", full)[1]


def test_handle_teach_stores_source_taught_and_stimulates(tmp_path):
    t = tokyo(2, "15:00")
    live = make_live(tmp_path, t)
    assert teach(live, "1.2.3.4", "warm bread", "Mika") == {"type": "teach_ack", "ok": True}
    m = live.memory.items[-1]
    assert m["source"] == "taught" and m["text"] == "warm bread" and m["nick"] == "Mika" and m["replays"] == 0
    assert "language" in m["stimulus"]                                     # chat rules: every message hits language
    assert live.broadcasts[-1]["type"] == "taught" and live.broadcasts[-1]["nick"] == "Mika"
    assert live.memory.chat() == []                                        # never shown as a chat message
    # the same viewer again today: refused, nothing stored
    assert teach(live, "1.2.3.4", "cold tea")["reason"] == "one teach per viewer per day"
    assert len(live.memory.items) == 1


def test_handle_teach_daily_cap_counts_from_memory(tmp_path):
    t = tokyo(2, "15:00")
    live = make_live(tmp_path, t)
    for i in range(chat.TEACH_PER_DAY):
        live.memory.add(t - 60, f"word {i}", "AWAKE", {}, "neutral", [], source="taught", nick="", replays=0)
    live.memory.add(t - 86400, "yesterday word", "AWAKE", {}, "neutral", [], source="taught")
    assert "try again tomorrow" in teach(live, "5.6.7.8", "late word")["reason"]
    live.t_now = tokyo(3, "09:00")                                          # next Tokyo day: open again
    assert teach(live, "5.6.7.8", "early word")["ok"]


def test_daily_cap_survives_a_restart_without_storing_viewer_keys(tmp_path):
    path = tmp_path / "teach.json"
    lim = chat.TeachLimits(per_day=3, path=path)
    for i in range(3):
        assert chat.check_teach(f"word {i}", "", f"ip{i}", lim, "d1", [])[0]     # memory lost: count from the file
    saved = json.loads(path.read_text())
    assert saved == {"day": "d1", "count": 3}                                    # no viewer keys on disk
    lim2 = chat.TeachLimits(per_day=3, path=path)                                # restart
    assert "try again tomorrow" in chat.check_teach("late", "", "ip9", lim2, "d1", [])[1]
    assert chat.check_teach("fresh", "", "ip9", lim2, "d2", [])[0]               # a new day starts from zero
    path.write_text('{"day": "d2", "cou')                                        # torn file: defaults, no crash
    assert chat.TeachLimits(path=path).count == 0


def test_live_restart_keeps_the_taught_items_and_the_cap(tmp_path):
    t = tokyo(2, "15:00")
    live = make_live(tmp_path, t)
    assert teach(live, "a", "paper crane")["ok"]
    live2 = make_live(tmp_path, t)                                               # no periodic save happened
    assert [m["text"] for m in live2.memory.items if m.get("source") == "taught"] == ["paper crane"]
    assert live2.teach_limits.count == 1 and live2.taught()["left"] == chat.TEACH_PER_DAY - 1


# --- 2. replay weighting with its cap ---------------------------------------------------------------------
def test_taught_weighs_1_5x_a_chat_message():
    mem, t = Memory(), tokyo(2, "23:00")
    a = mem.add(t - 600, "hello there", "AWAKE", {}, "neutral", [])
    b = mem.add(t - 600, "hello there", "AWAKE", {}, "neutral", [], source="taught")
    assert abs(mem.weight(b, t, None) / mem.weight(a, t, None) - 1.5) < 1e-9


def test_taught_pool_capped_at_half_of_the_replays():
    mem, t = Memory(), tokyo(2, "23:00")
    mem.add(t - 600, "one chat message", "AWAKE", {}, "neutral", [])
    for i in range(30):
        mem.add(t - 600, f"taught {i}", "AWAKE", {}, "positive", [], source="taught")
    w = mem.weights(mem.items, t, None, {})
    taught = sum(w[1:])
    assert abs(taught - w[0]) < 1e-9                                       # taught <= 1.0 x the rest: half at most
    rng = random.Random(1)
    picks = [mem.pick(t, None, rng=rng)["source"] for _ in range(4000)]
    assert 0.45 < picks.count("taught") / len(picks) < 0.55
    # with nothing else in memory the cap has nothing to share with, and taught items are replayed
    only = Memory()
    only.add(t - 600, "lonely word", "AWAKE", {}, "neutral", [], source="taught")
    assert only.pick(t, None)["text"] == "lonely word"


def test_replay_chance_respects_the_taught_cap():
    mem, t = Memory(), tokyo(2, "23:00")
    chat_m = mem.add(t - 600, "one chat message", "AWAKE", {}, "neutral", [])
    for i in range(30):
        mem.add(t - 600, f"taught {i}", "AWAKE", {}, "positive", [], source="taught")
    # 30 taught items vs one chat message: the chat message still gets about half of the replays
    assert mem.replay_chance(chat_m, t, n_replays=6, sims=300) > 0.9


def test_sleep_tick_counts_replays_of_taught_items(tmp_path):
    t = tokyo(2, "15:00")
    live = make_live(tmp_path, t)
    teach(live, "ip", "paper crane")
    m = live.memory.items[-1]
    live.engine.update = lambda t, dt_real=None: [{"type": "replay", "text": "replay"}]
    live.engine.night = {"replays": [], "sleep_onset": None}
    ev = live.sleep_tick()
    assert ev[0]["source"] == "taught" and ev[0]["text"] == "paper crane"
    assert m["replays"] == 1 and live.engine.night["replays"][0]["source"] == "taught"
    live.engine.night |= {"date": "2026-10-02", "woke_up": None, "wakeups": [], "sleep_debt": 0}
    assert live.nights()["tonight"]["n_replays"] == {"chat": 0, "reading": 0, "taught": 1}


# --- 3. the GPU session gets taught items ------------------------------------------------------------------
def test_top_items_include_up_to_5_taught_testable_and_most_replayed_first():
    t = tokyo(2, "21:00")
    mem = Memory()
    mem.add(t - 3600, "good night", "AWAKE", {}, "positive", [])
    for i, (text, reps) in enumerate([("moon", 9), ("red bicycle", 1), ("paper crane", 4), ("warm bread", 0),
                                      ("tea kettle", 2), ("snow crystals", 3), ("lighthouse keeper", 5)]):
        mem.add(t - 3000 + i, text, "AWAKE", {}, "neutral", [], source="taught", nick="x", replays=reps)
    mem.add(t - 86400, "old lesson", "AWAKE", {}, "neutral", [], source="taught", replays=50)
    items = pod_manager.top_items(mem, t)
    taught = [i["item"] for i in items if i["source"] == "taught"]
    assert taught == ["lighthouse keeper", "paper crane", "snow crystals", "tea kettle", "red bicycle"]
    assert all(i["text"] == i["item"] for i in items if i["source"] == "taught")      # nickname never sent
    assert not half_cue_ok("moon") and half_cue_ok("red bicycle")


def test_session_config_and_pod_keep_the_taught_source(tmp_path):
    from test_spiking_ops import make_mgr, tk
    t = tk(1, 21)
    mem = Memory()
    mem.add(t.timestamp() - 600, "paper crane", "AWAKE", {}, "neutral", [], source="taught", replays=2)
    mem.add(t.timestamp() - 600, "hello brain", "AWAKE", {}, "neutral", [])
    mgr, fc, *_ = make_mgr(tmp_path, t)
    mgr.get_items = lambda: pod_manager.top_items(mem, fc.now().timestamp())
    cfg = mgr.session_config(t, 60, t)
    assert {"text": "paper crane", "source": "taught", "item": "paper crane", "emotion": "neutral"} in cfg["items"]
    assert cfg["messages"] == [{"text": "hello brain", "emotion": "neutral"}]          # taught is not chat


def test_hub_stores_taught_rows_and_finds_next_day_results(tmp_path):
    hub = spiking_server.SpikingHub(SimpleNamespace(), tmp_path, secret="x")
    rec = {"kind": "memory_test", "label": "next day", "day": "2026-10-03", "session": "s2",
           "thresholds": {"hc": 0.4},
           "scores": [{"item": "paper crane", "text": "paper crane", "source": "taught", "item_day": "2026-10-02",
                       "hc": 1.2, "hc_recalled": True},
                      {"item": "Moon", "text": "Moon tides", "source": "reading", "item_day": "2026-10-02",
                       "hc": 0.1, "hc_recalled": False}]}
    hub.store_result(rec)
    hub.store_result(rec | {"label": "after sleep"})
    res = hub.taught_results()
    assert list(res) == [("2026-10-02", "paper crane")]
    r = res[("2026-10-02", "paper crane")]
    assert r["recalled"] and r["score"] == 1.2 and r["threshold"] == 0.4 and r["days_since"] == 1
    assert hub.memory()["items"][0]["source"] == "reading"           # the reading card is unchanged


# --- 4. /api/taught ---------------------------------------------------------------------------------------
def test_api_taught_shape_gpu_off_shows_replays_only(tmp_path):
    t = tokyo(2, "15:00")
    live = make_live(tmp_path, t)
    teach(live, "a", "paper crane", "Mika")
    teach(live, "b", "moon")
    live.memory.items[-1]["replays"] = 3
    d = live.taught()
    json.dumps(d)
    assert d["gpu"] is False and d["day"] == day_of(t) and d["left"] == chat.TEACH_PER_DAY - 2
    assert d["note"] == live_server.REPLAY_NOTE and "recall" not in d["note"].lower()
    assert [x["text"] for x in d["today"]] == ["paper crane", "moon"] and d["yesterday"] == []
    assert d["today"][0] == {"text": "paper crane", "nick": "Mika", "t": "15:00", "day": day_of(t), "replayed": 0}
    assert d["today"][1]["replayed"] == 3
    assert all("result" not in x and "testable" not in x for x in d["today"])   # no recall claim with the GPU off


def test_api_taught_gpu_on_shows_next_day_result(tmp_path):
    t = tokyo(2, "15:00")
    live = make_live(tmp_path, t)
    teach(live, "a", "paper crane", "Mika")
    teach(live, "b", "moon")
    live.gpu_test = True
    live.spiking = spiking_server.SpikingHub(live, tmp_path, secret="x")
    live.spiking.store_result({"kind": "memory_test", "label": "next day", "day": "2026-10-03", "session": "s",
                               "thresholds": {"hc": 0.4},
                               "scores": [{"item": "paper crane", "source": "taught", "item_day": day_of(t),
                                           "hc": 0.9, "hc_recalled": True}]})
    live.t_now = tokyo(3, "21:30")
    d = live.taught()
    assert d["note"] == live_server.RECALL_NOTE == "Recall by a simulated spiking network from a partial cue; a model, not a mind."
    assert d["today"] == [] and [x["text"] for x in d["yesterday"]] == ["paper crane", "moon"]
    crane, moon = d["yesterday"]
    assert crane["result"] == {"recalled": True, "score": 0.9, "best_lure": 0.4, "days_since": 1, "test_day": "2026-10-03"}
    assert moon["result"] is None and moon["testable"] is False


def test_teach_over_the_websocket_and_get_api_taught(tmp_path):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    async def go():
        live = live_server.Live("m", True, data_dir=tmp_path)
        app = web.Application()
        app.router.add_get("/ws", live.ws_handler)

        async def taught(request):
            return web.json_response(live.taught())
        app.router.add_get("/api/taught", taught)
        async with TestClient(TestServer(app)) as c:
            ws = await c.ws_connect("/ws")
            await ws.send_str(json.dumps({"type": "teach", "text": "paper crane", "nick": "Mika"}))
            got = None
            while got is None:
                m = await ws.receive_json(timeout=5)
                if m.get("type") == "teach_ack":
                    got = m
            assert got["ok"]
            d = await (await c.get("/api/taught")).json()
            assert d["today"][0]["text"] == "paper crane" and d["today"][0]["nick"] == "Mika"
            await ws.close()
    asyncio.run(go())


# --- 5. on the pod (CPU, small N; skipped without torch) --------------------------------------------------------
def test_pod_encodes_and_tests_taught_items_with_their_source(tmp_path):
    import pytest
    torch = pytest.importorskip("torch")
    from spiking.session import Session, run_session
    items = [{"text": f"taught {i} lesson words", "source": "taught"} for i in range(7)]
    assert [x["source"] for x in Session({"items": items}, tmp_path / "s").day_items()] == ["taught"] * 5
    prev = torch.get_num_threads()
    torch.set_num_threads(2)
    try:
        cfg = {"n_neurons": 20000, "device": "cpu", "seed": 1, "day": "2026-10-02", "max_minutes": 10,
               "config": {"hc_scale": 6}, "phases": ["encode", "memory_test"], "lures": 4, "session_id": "teach",
               "items": [{"text": "paper crane folding", "source": "taught"},
                         {"text": "good morning little brain", "source": "chat"}]}
        res = run_session(cfg, tmp_path / "out")
    finally:
        torch.set_num_threads(prev)
    assert res["error"] is None, res["error"]
    t = res["phases"]["memory_test"][0]
    assert {s["item"]: s["source"] for s in t["scores"]} == {"paper crane folding": "taught",
                                                            "good morning little brain": "chat"}
    hub = spiking_server.SpikingHub(SimpleNamespace(), tmp_path, secret="x")
    rows = hub.store_items(t | {"label": "next day", "day": "2026-10-03", "received": "x"})
    assert {r["source"] for r in rows} == {"taught", "chat"}
