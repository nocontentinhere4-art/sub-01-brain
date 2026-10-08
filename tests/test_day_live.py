"""Day-live mode (#58): the 1M network on a GPU pod through his waking hours, with hard daily caps.

No real pods: RunPod is the recording FakeApi of test_spiking_ops, time is a fake clock. Covered: the day/night
schedule follows the sleep stage, every cap stops and deletes the pod, restarts back off, orphans are deleted
(never "BRAIN"), the decide / decision / reward / night messages round-trip through the hub, the fallback on a
timeout, and the periodic weight upload (the session part needs torch, like every spiking network test).

    python -m pytest tests/test_day_live.py -q
"""
import asyncio
import json
import queue
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_spiking_ops import AUTH, FakeApi, FakePodHttp, until, with_client  # noqa: E402

from spiking import pod_manager  # noqa: E402
from spiking.costs import CostLog  # noqa: E402
from spiking.pod_manager import PodManager  # noqa: E402
from spiking.runpod_ops import RunPodOps  # noqa: E402

TOKYO = ZoneInfo("Asia/Tokyo")


def tk(day, h, m=0):
    return datetime(2026, 10, day, h, m, tzinfo=TOKYO)


class Clock:
    def __init__(self, t):
        self.t = t

    def now(self):
        return self.t


class Day:
    """A PodManager in day-live mode on a fake clock and a fake RunPod; `step()` advances time like the loop."""

    def __init__(self, tmp_path, now, env=None, api=None, items=None):
        self.clock = Clock(now)
        self.api = api or FakeApi()
        self.log = CostLog(tmp_path / "spiking" / "costs.jsonl", clock=self.clock.now)
        env = {"SUB01_DAY_LIVE": "1", "SUB01_CHOICE": "1", **(env or {})}
        ops = RunPodOps(api=self.api, log=self.log, hours_cap=float(env.get("SUB01_GPU_HOURS_CAP") or 120),
                        sleep=lambda s: None, install_hooks=False, opener=FakePodHttp(), cap_days=7)
        self.mgr = PodManager(tmp_path, "https://srv.example", "pod-secret", clock=self.clock.now, ops=ops,
                              env=env, get_items=lambda: list(items or []))
        self.mgr._pack = lambda: b"tar"
        self.stops, self.nights, self.alive = [], [], True

        async def send_stop():
            self.stops.append(self.clock.t)

        async def send_night(payload):
            self.nights.append(payload)
            return True
        self.mgr.send_stop, self.mgr.send_night = send_stop, send_night

    def stage(self, s):
        self.mgr.on_stage(s)

    async def astep(self, minutes=1.0, n=1):
        out = []
        for _ in range(n):
            c = self.mgr.current
            if c is not None and self.alive:
                if not c["hello"]:
                    self.mgr.on_hello({})
                self.mgr.on_state({"phase": "live_decide"})
            out.append(await self.mgr.day_step(self.clock.t))
            self.clock.t += timedelta(minutes=minutes)
        return out

    def step(self, minutes=1.0, n=1):
        return asyncio.run(self.astep(minutes, n))

    def until(self, t, minutes=1.0):
        out = []
        while self.clock.t < t:
            out += self.step(minutes)
        return out

    def creates(self):
        return [c[2] for c in self.api.calls if c[0] == "POST"]

    def ours(self):
        return [p for p in self.api.pods if p["name"] != "BRAIN"]

    def reasons(self):
        return [json.loads(x)["reason"] for x in self.log.path.read_text().splitlines() if '"stop"' in x]


# --- the schedule follows the sleep stage -------------------------------------------------------------------------
def test_day_pod_follows_waking_hours_and_night_runs_on_same_pod(tmp_path, capsys):
    items = [{"text": "Tea ceremony matcha kettle", "source": "reading", "item": "Tea ceremony"}]
    d = Day(tmp_path, tk(2, 7, 50), items=items)
    sp = tmp_path / "spiking"
    sp.mkdir(parents=True, exist_ok=True)
    t_dec = tk(2, 12).timestamp()
    (sp / "decisions-2026-10-02.jsonl").write_text("\n".join(json.dumps(r) for r in [   # #55's log (CPU answered)
        {"t": t_dec, "id": "a", "kind": "browse", "options": ["Tea", "News"], "pick": 0, "net": "cpu"},
        {"t": t_dec + 60, "id": "a", "reward": 0.8},
        {"t": t_dec + 120, "id": "b", "kind": "chess", "options": ["Nf3", "e4", "d4"], "pick": 2},   # no reward yet
        {"t": tk(1, 12).timestamp(), "id": "old", "options": ["x", "y"], "pick": 0, "reward": 1.0}]) + "\n")
    (sp / "gpu_decisions-2026-10-02.jsonl").write_text("\n".join(json.dumps(r) for r in [   # the hub's own log
        {"t": t_dec + 200, "id": "g", "kind": "plan", "options": ["park", "home"], "pick": 1, "net": "gpu"},
        {"t": t_dec + 260, "id": "g", "reward": -0.5}, "torn {"]) + "\n")
    d.stage("AWAKE")
    d.step(n=4)
    assert d.creates() == []                                           # awake for less than 5 min: nothing yet
    d.step(n=2)
    assert len(d.creates()) == 1 and d.mgr.current["mode"] == "day"
    body = d.creates()[0]
    cfg = json.loads(body["env"]["SUB01_SESSION"])
    assert cfg["phases"] == ["live_decide", "recall_yesterday", "encode", "choice_train", "memory_test", "sleep",
                             "memory_test"]
    assert cfg["n_neurons"] == 1_000_000 and cfg["upload_every_min"] == 30 and cfg["day"] == "2026-10-02"
    assert body["gpuTypeIds"] == [pod_manager.DAY_GPUS[0][0]] and body["cloudType"] == pod_manager.DAY_GPUS[0][1]
    d.until(tk(2, 23, 50), minutes=10)                                  # the whole waking day on one pod
    assert len(d.creates()) == 1 and d.mgr.current["mode"] == "day" and d.nights == [] and d.stops == []
    d.stage("NREM")
    d.step(n=9)
    assert d.nights == []                                               # asleep < 10 min: still the day phase
    d.step(n=2)
    assert len(d.nights) == 1 and d.mgr.current["mode"] == "night" and len(d.creates()) == 1
    night = d.nights[0]
    assert night["day"] == "2026-10-02" and night["items"][0]["item"] == "Tea ceremony"
    assert night["decisions"] == [{"options": ["Tea", "News"], "pick": 0, "kind": "browse", "reward": 0.8},
                                  {"options": ["park", "home"], "pick": 1, "kind": "plan", "reward": -0.5}]
    d.stage("REM")
    d.step(n=20)
    d.mgr.on_done({"ok": True})
    d.step()
    assert d.mgr.current is None and d.ours() == [] and d.reasons() == ["night done"]
    assert "2026-10-02" in d.mgr.dl["nights"]
    d.until(tk(3, 3), minutes=10)                                        # asleep: no pod beyond the night phases
    d.stage("AWAKE")                                                     # a waking at 03:00 for 30 min
    d.until(tk(3, 3, 30))
    d.stage("NREM")
    d.until(tk(3, 7, 55), minutes=5)
    assert len(d.creates()) == 1
    d.stage("AWAKE")                                                     # the next morning: a new day pod
    d.until(tk(3, 8, 10))
    assert len(d.creates()) == 2 and d.mgr.current["mode"] == "day" and d.mgr.current["key"] == "2026-10-03"
    st = d.mgr.status()["day_live"]
    assert st["stage"] == "AWAKE" and st["pod"] == "day" and st["caps"]["hours_per_day"] == 17
    assert "BRAIN" in [p["name"] for p in d.api.pods] and ("DELETE", "/pods/brain1") not in d.api.mutating()


def test_night_only_pod_when_no_day_pod_ran(tmp_path):
    d = Day(tmp_path, tk(2, 23, 0), items=[{"text": "a red bicycle near the river", "source": "chat"}])
    d.stage("NREM")
    d.step(n=12)
    assert len(d.creates()) == 1 and d.mgr.current["mode"] == "night"
    cfg = json.loads(d.creates()[0]["env"]["SUB01_SESSION"])
    assert cfg["phases"][0] == "recall_yesterday" and "live_decide" not in cfg["phases"]
    assert cfg["items"][0]["text"] == "a red bicycle near the river" and cfg["max_minutes"] == 40
    d.step(minutes=5, n=10)                                              # the night pod is bounded
    assert d.mgr.current is None and d.reasons() == ["night deadline"] and d.ours() == []


def test_day_live_off_by_default_and_choice_switch(tmp_path):
    mgr = PodManager(tmp_path, "https://srv", "s", api=FakeApi(), env={})
    assert mgr.day_live is False and mgr.ops.hours_cap == 8.0                    # the nightly session as before
    mgr = PodManager(tmp_path, "https://srv", "s", api=FakeApi(), env={"SUB01_DAY_LIVE": "1", "SUB01_SESSIONS": "off"})
    assert mgr.day_live and mgr.enabled() and mgr.ops.hours_cap == 120.0
    assert mgr.day_max_hours == 17 and mgr.usd_per_day == 14.0 and mgr.max_restarts == 6
    assert "choice_train" not in mgr.day_phases("day")                           # SUB01_CHOICE off: no replay
    assert PodManager(tmp_path, "https://srv", "s", api=FakeApi(),
                      env={"SUB01_DAY_LIVE": "1", "SUB01_GPU_HOURS_CAP": "50"}).ops.hours_cap == 50.0


# --- caps -----------------------------------------------------------------------------------------------------------
def run_until_capped(d, t_end, minutes=1.0):
    d.stage("AWAKE")
    d.until(t_end, minutes)
    return d


def test_day_hour_cap_stops_and_deletes(tmp_path, capsys):
    d = run_until_capped(Day(tmp_path, tk(2, 8), env={"SUB01_DAY_MAX_HOURS": "2"}), tk(2, 12))
    assert len(d.creates()) == 1 and d.ours() == [] and len(d.stops) == 1      # asked to upload first, then deleted
    assert d.reasons()[0].startswith("day GPU-hour cap")
    hours, _ = d.log.usage_on("2026-10-02")
    assert 1.95 <= hours <= 2.0 + 1 / 60
    assert "day GPU-hour cap" in capsys.readouterr().out and d.mgr.dl["blocked"]
    d.until(tk(3, 8, 10), minutes=10)                                   # blocked until the next Tokyo day
    assert len(d.creates()) == 2


def test_daily_usd_cap_stops_and_deletes(tmp_path, capsys):
    d = run_until_capped(Day(tmp_path, tk(2, 8), env={"SUB01_GPU_USD_PER_DAY": "0.60"}), tk(2, 12))   # $0.30/h
    _, usd = d.log.usage_on("2026-10-02")
    assert d.ours() == [] and d.reasons()[0].startswith("daily USD cap") and 0.58 <= usd <= 0.61
    assert "daily USD cap" in capsys.readouterr().out and len(d.creates()) == 1


def test_weekly_cap_stops_and_deletes(tmp_path, capsys):
    d = Day(tmp_path, tk(1, 9), env={"SUB01_GPU_HOURS_CAP": "3"})
    d.log.start("old", "sub01-spiking-day-old", "g", 0.3, "day")
    d.clock.t = tk(1, 11, 30)
    d.log.stop("old", "done")                                           # 2.5 h yesterday
    d.clock.t = tk(2, 8)
    run_until_capped(d, tk(2, 10))
    assert d.ours() == [] and d.reasons()[-1].startswith("weekly GPU-hour cap")
    assert 2.95 <= d.log.hours_since(7) <= 3.0 + 1 / 60 and "weekly GPU-hour cap" in capsys.readouterr().out


def test_cap_already_reached_starts_nothing(tmp_path, capsys):
    d = Day(tmp_path, tk(2, 8), env={"SUB01_GPU_USD_PER_DAY": "0.10"})
    d.log.start("old", "sub01-spiking-day-old", "g", 1.0, "day")
    d.clock.t = tk(2, 8, 10)
    d.log.stop("old", "done")                                           # $0.17 spent today
    d.clock.t = tk(2, 9)
    run_until_capped(d, tk(2, 10))
    assert d.creates() == [] and "no GPU pod until the next Tokyo day" in capsys.readouterr().out


def test_usage_is_split_at_tokyo_midnight(tmp_path):
    c = Clock(tk(2, 23))
    log = CostLog(tmp_path / "c.jsonl", clock=c.now)
    log.start("p", "sub01-spiking-x", "g", 0.5, "day")
    c.t = tk(3, 1)
    assert [round(x, 3) for x in log.usage_on("2026-10-02")] == [1.0, 0.5]       # open pod, up to now
    log.stop("p", "done")
    assert [round(x, 3) for x in log.usage_on("2026-10-03")] == [1.0, 0.5]


# --- restarts and orphans -------------------------------------------------------------------------------------------
def test_restarts_back_off_then_stop_for_the_day(tmp_path, capsys):
    d = Day(tmp_path, tk(2, 8))
    d.alive = False                                                     # every pod boots but never says hello
    d.stage("AWAKE")
    d.until(tk(2, 22), minutes=1)
    starts = [datetime.fromisoformat(r["start"]) for r in d.log.rows() if r.get("event") == "start"]
    assert len(starts) == 7                                             # first pod + 6 restarts, then the cap
    assert set(d.reasons()) == {"no hello within 15 min"} and d.ours() == []
    gaps = [(b - a).total_seconds() / 60 for a, b in zip(starts, starts[1:])]
    waits = [g - 16 for g in gaps]                                      # 15 min hello timeout (+1 tick)
    assert all(w2 >= w1 for w1, w2 in zip(waits, waits[1:])) and waits[0] >= 1 and waits[-1] >= 40
    out = capsys.readouterr().out
    assert "restart 1 of 6" in out and "restart cap" in out and d.mgr.dl["blocked"].startswith("restart cap")
    d.until(tk(2, 23, 59), minutes=10)
    assert len([r for r in d.log.rows() if r.get("event") == "start"]) == 7
    d.until(tk(3, 0, 5))                                                # a new Tokyo day resets the count
    assert len([r for r in d.log.rows() if r.get("event") == "start"]) == 8 and d.mgr.dl["restarts"] == 0


def test_stream_lost_restarts_after_backoff(tmp_path):
    d = Day(tmp_path, tk(2, 8))
    d.stage("AWAKE")
    d.until(tk(2, 9))
    first = d.mgr.current["pod_id"]
    d.alive = False                                                     # the pod stops streaming
    d.mgr.on_disconnect()
    d.until(tk(2, 9, 5))
    assert d.mgr.current is None and d.reasons() == ["stream lost"]
    d.alive = True
    d.until(tk(2, 9, 10))
    assert d.mgr.current is not None and d.mgr.current["pod_id"] != first and d.mgr.dl["restarts"] == 1


def test_orphan_pod_is_deleted_never_brain(tmp_path, capsys):
    api = FakeApi(pods=[{"id": "lost", "name": "sub01-spiking-day-20261001", "costPerHr": 0.3},
                        {"id": "other", "name": "someone-else", "costPerHr": 0.3}])
    d = Day(tmp_path, tk(2, 8), api=api)
    d.stage("AWAKE")
    gone = asyncio.run(d.mgr._sweep_orphans())
    assert gone == ["lost"] and "deleting orphan pod lost" in capsys.readouterr().out
    d.until(tk(2, 8, 10))
    cur = d.mgr.current["pod_id"]
    api.pods.append({"id": "lost2", "name": "sub01-spiking-day-x", "costPerHr": 0.3})
    assert asyncio.run(d.mgr._sweep_orphans()) == ["lost2"]
    names = sorted(p["name"] for p in api.pods)
    assert names[0] == "BRAIN" and "someone-else" in names and cur in [p["id"] for p in api.pods]
    assert not [m for m in api.mutating() if m[1] in ("/pods/brain1", "/pods/other")]


def test_run_loop_sweeps_and_shuts_down(tmp_path):
    api = FakeApi(pods=[{"id": "stale", "name": "sub01-spiking-day-old", "costPerHr": 0.3}])
    d = Day(tmp_path, tk(2, 8), api=api)
    d.stage("AWAKE")
    n = {"k": 0}

    async def fake_sleep(s):
        d.clock.t += timedelta(seconds=60)
        if d.mgr.current is not None:
            d.mgr.on_hello({})
            d.mgr.on_state({})
        n["k"] += 1
        if n["k"] > 30:
            raise asyncio.CancelledError()
    d.mgr._sleep = fake_sleep
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(d.mgr.run())
    assert ("DELETE", "/pods/stale") in api.mutating() and len(d.creates()) == 1
    assert d.ours() == [] and [p["name"] for p in api.pods] == ["BRAIN"]          # shutdown deleted ours


def test_gpu_type_list(tmp_path):
    assert pod_manager.parse_gpus("") == list(pod_manager.DAY_GPUS)
    assert pod_manager.parse_gpus("NVIDIA RTX A4000:community, NVIDIA A40") == [
        ("NVIDIA RTX A4000", "COMMUNITY"), ("NVIDIA A40", "SECURE")]
    with pytest.raises(ValueError):
        pod_manager.parse_gpus("NVIDIA H100 80GB HBM3:SECURE")                  # not on the allow list
    api = FakeApi(fail_gpus={pod_manager.DAY_GPUS[0][0]})                        # no capacity: the next type
    d = Day(tmp_path, tk(2, 8), api=api)
    d.stage("AWAKE")
    d.until(tk(2, 8, 10))
    assert [b["gpuTypeIds"][0] for b in d.creates()] == [pod_manager.DAY_GPUS[0][0], pod_manager.DAY_GPUS[1][0]]
    assert d.log.open_pods()[0]["gpu"] == pod_manager.DAY_GPUS[1][0]


# --- the protocol through the hub ---------------------------------------------------------------------------------
def test_protocol_round_trips_through_hub(tmp_path):
    async def go(client, hub, live):
        assert await hub.decide(["a", "b"]) is None                       # no pod: the caller falls back at once
        ws = await client.ws_connect("/api/spiking/pod?session=d1", headers=AUTH)
        await ws.send_json({"type": "hello", "session": "d1", "n_neurons": 1_000_000})
        assert await until(lambda: hub.session is not None)
        assert await hub.decide(["a", "b"]) is None                       # connected but not live yet
        await ws.send_json({"type": "live_ready", "n_neurons": 1_000_000})
        assert await until(lambda: hub.live_ready)

        async def pod():
            m = await ws.receive_json()
            assert m["type"] == "decide" and m["options"] == ["Tea ceremony", "Stock news", "Park"]
            assert m["kind"] == "browse" and m["deadline_ms"] == 2000 and m["id"]
            await ws.send_json({"type": "decision", "id": m["id"], "pick": 2, "pool_rates": [3.1, 3.2, 4.4],
                                "sim_ms": 50.0, "n_neurons": 1_000_000})
            return m["id"]
        task = asyncio.ensure_future(pod())
        d = await hub.decide(["Tea ceremony", "Stock news", "Park"], "browse", 2000)
        did = await task
        assert d["id"] == did and d["pick"] == 2 and d["pool_rates"] == [3.1, 3.2, 4.4] and d["net"] == "gpu"
        assert d["label"] == "1M-neuron network on GPU" and d["n_neurons"] == 1_000_000 and d["sim_ms"] == 50.0
        assert hub.reward(did, 0.7) is True
        m = await ws.receive_json()
        assert m == {"type": "reward", "id": did, "value": 0.7}
        assert hub.reward(did, 0.7) is False and hub.reward("never-asked", 1.0) is False
        assert hub.reward(did, float("nan")) is False
        assert await hub.send_night({"day": "2026-10-02", "items": [], "decisions": [{"options": ["a", "b"]}]})
        m = await ws.receive_json()
        assert m["type"] == "night" and m["day"] == "2026-10-02" and hub.live_ready is False
        rows = [json.loads(x) for x in next((tmp_path / "spiking").glob("gpu_decisions-*.jsonl")).read_text().splitlines()]
        assert rows[0]["id"] == did and rows[0]["pick"] == 2 and rows[0]["options"][0] == "Tea ceremony"
        assert rows[1] == {"id": did, "reward": 0.7, "t": rows[1]["t"]}
        st = hub.status()["decisions"]
        assert st["asked"] == 1 and st["answered"] == 1 and st["rewards"] == 1
        await ws.close()
        assert await until(lambda: not hub.connected) and hub.live_ready is False
    asyncio.run(with_client(tmp_path, go))


def test_decide_falls_back_on_timeout_and_bad_answers(tmp_path, capsys):
    async def go(client, hub, live):
        ws = await client.ws_connect("/api/spiking/pod", headers=AUTH)
        await ws.send_json({"type": "live_ready"})
        assert await until(lambda: hub.live_ready)
        t0 = time.monotonic()
        assert await hub.decide(["a", "b"], deadline_ms=150) is None       # the pod never answers
        assert 0.14 <= time.monotonic() - t0 < 1.0 and hub.decide_stats["timeouts"] == 1
        assert "fallback" in capsys.readouterr().out
        (await ws.receive_json())                                          # the unanswered decide

        async def answer(**fields):
            m = await ws.receive_json()
            await ws.send_json({"type": "decision", "id": m["id"], **fields})
        for bad in ({"pick": 5, "pool_rates": [1, 2]}, {"pick": True}, {"pick": "0"}):
            task = asyncio.ensure_future(answer(**bad))
            assert await hub.decide(["a", "b"], deadline_ms=1000) is None
            await task
        assert await hub.decide(["only one"]) is None and await hub.decide(["x"] * 9) is None
        late = asyncio.ensure_future(hub.decide(["a", "b"], deadline_ms=100))
        m = await ws.receive_json()
        assert await late is None
        await ws.send_json({"type": "decision", "id": m["id"], "pick": 0})  # too late: dropped quietly
        await asyncio.sleep(0.05)
        assert hub.answered == {} and hub.reward(m["id"], 1.0) is False
        await ws.close()
    asyncio.run(with_client(tmp_path, go))


def test_hub_forwards_stage_to_manager_and_wires_night(tmp_path):
    async def go(client, hub, live):
        d = Day(tmp_path, tk(2, 8))
        hub.manager = d.mgr
        assert d.mgr.send_night == hub.send_night                          # wired by the hub
        hub.forward_sleep("AWAKE")
        hub.forward_sleep("AWAKE")
        assert d.mgr.stage == "AWAKE" and d.mgr.stage_since == tk(2, 8)
        d.clock.t = tk(2, 23)
        hub.forward_sleep("NREM")
        assert d.mgr.stage == "NREM" and d.mgr.stage_since == tk(2, 23)
        assert await hub.send_night({"day": "x"}) is False                 # no pod connected
    asyncio.run(with_client(tmp_path, go))


# --- the pod side (torch) -------------------------------------------------------------------------------------------
class FakeLink:
    def __init__(self):
        self.inbox, self.sent, self.puts, self.connects, self.sid = queue.Queue(), [], [], 1, "t"

    def send(self, msg):
        self.sent.append(msg)

    def get_weights(self, path):
        return False

    def put_weights(self, path):
        self.puts.append(Path(path).stat().st_size)
        return 200

    def close(self, timeout=10):
        pass


def test_session_answers_decides_learns_and_uploads_periodically(tmp_path):
    torch = pytest.importorskip("torch")
    torch.set_num_threads(2)
    from spiking.session import Session
    link = FakeLink()
    cfg = {"n_neurons": 10_000, "seed": 3, "max_minutes": 10, "upload_every_min": 0.04, "day": "2026-10-02",
           "phases": ["live_decide", "choice_train"], "items": []}
    s = Session(cfg, tmp_path / "out", link)
    s.build()
    link.inbox.put({"type": "decide", "id": "d1", "options": ["Tea ceremony", "Stock news", "Park boats"],
                    "kind": "browse", "deadline_ms": 5000})
    link.inbox.put({"type": "decide", "id": "bad", "options": ["only one"]})
    t0 = time.time()

    def feeder():
        while not any(m.get("type") == "decision" and m.get("id") == "d1" for m in link.sent):
            time.sleep(0.05)
        link.inbox.put({"type": "reward", "id": "d1", "value": 1.0})
        link.inbox.put({"type": "reward", "id": "unknown", "value": 1.0})
        while len(link.puts) < 2 and time.time() - t0 < 60:
            time.sleep(0.1)
        link.inbox.put({"type": "night", "day": "2026-10-02", "items": [],
                        "decisions": [{"options": ["Tea ceremony", "Stock news"], "pick": 0, "reward": 1.0},
                                      {"options": ["a"], "pick": 0, "reward": 1.0},          # invalid: skipped
                                      {"options": ["Park boats", "News"], "pick": 1, "reward": -0.5}]})
    import threading
    th = threading.Thread(target=feeder, daemon=True)
    th.start()
    res = s.run()
    th.join(5)
    assert res["error"] is None
    dec = [m for m in link.sent if m.get("type") == "decision"]
    good = [m for m in dec if m["id"] == "d1"][0]
    assert 0 <= good["pick"] < 3 and len(good["pool_rates"]) == 3 and good["n_neurons"] == 10_000
    assert good["sim_ms"] <= 250 and [m for m in dec if m["id"] == "bad"][0]["error"] == "bad decide message"
    assert any(m.get("type") == "live_ready" for m in link.sent)
    assert s.live_stats["rewards"] == 1 and s.live_stats["unknown_reward"] == 1
    assert len(link.puts) >= 3                                          # >= 2 periodic + the final upload
    replay = res["phases"]["choice_replay"][0]
    assert replay["decisions"] == 2 and replay["fit_n"] == 2 and "fit_frozen_twin" in replay
    assert replay["paid_off_frac"] == 0.5
    z = np.load(tmp_path / "out" / "weights.npz")
    meta = json.loads(str(z["meta"]))
    assert "tea ceremony" in meta["live_choice"]["V"] and meta["live_choice"]["n"]["tea ceremony"] >= 2


def test_live_chooser_variable_offers_and_stable_rule():
    torch = pytest.importorskip("torch")
    torch.set_num_threads(2)
    from spiking.choice import LiveChooser, label_key
    from spiking.config import Config
    from spiking.net import SpikingNet
    net = SpikingNet(Config(n_neurons=10_000, seed=3))
    net.run(200)
    net.plast.set_stdp(False)
    live = LiveChooser(net)
    live.calibrate(presentations=4)
    assert label_key("The Tea Ceremony, 2nd ed.") == "tea ceremony nd" or label_key("The Tea Ceremony") == "tea ceremony"
    w0 = net.plast.w0.clone()
    for k in range(2, 7):
        labels = [f"option {chr(97 + i)} {k}" for i in range(k)]
        r = live.decide(labels)
        assert 0 <= r["pick"] < k and len(r["pool_rates"]) == k and r["sim_ms"] <= 250
        pools = live.pools(labels)
        assert sum(len(p) for p in pools) == len(live.action)              # disjoint, cover the striatum
    r = live.decide(["Tea ceremony", "Stock news"])
    dw0 = net.plast.dw.clone()
    out = live.reward(r["elig"], 1.0)
    changed = torch.nonzero(net.plast.dw != dw0).squeeze(1)
    assert out["dw_abs"] > 0 and changed.numel() > 0
    assert set(changed.tolist()) <= set(r["elig"]["q"].tolist())          # only the tagged cue -> pool synapses
    assert torch.equal(net.plast.w0, w0)
    key = r["elig"]["label"]
    etas = [live.eta_for(key)]
    for _ in range(40):
        live.reward(r["elig"], 1.0)
        etas.append(live.eta_for(key))
    assert etas[0] == 0.6 * (1 / np.sqrt(1 + 1 / 20)) and etas[-1] < etas[0] and min(etas) >= live.eta_min
    assert 0 < live.V[key] < 1 and live.V[key] < 1 - (1 - 0.05) ** 41 + 1e-6     # slow value (alpha 0.05)
    meta = live.to_meta()
    other = LiveChooser(net)
    other.from_meta(json.loads(json.dumps(meta)))
    assert other.V == pytest.approx(live.V, abs=1e-5) and other.n == live.n
    assert live.reward(None, 1.0)["dw_abs"] == 0.0


def test_day_live_api_for_brain_vote(tmp_path):
    """pod_manager.day_live_decide / day_live_reward: None at once when off or no pod, never raise."""
    async def go(client, hub, live):
        pod_manager.register_hub(None)
        assert await pod_manager.day_live_decide(["a", "b"]) is None
        assert await pod_manager.day_live_reward("x", 1.0) is None
        hub.manager = PodManager(tmp_path, "https://srv", "s", api=FakeApi(), env={})       # day-live off
        assert pod_manager._hub is None
        d = Day(tmp_path, tk(2, 8))
        hub.manager = d.mgr                                                                 # day-live on
        assert pod_manager._hub is hub
        t0 = time.monotonic()
        assert await pod_manager.day_live_decide(["a", "b"], "browse", 2000) is None      # no pod: at once
        assert time.monotonic() - t0 < 0.05
        ws = await client.ws_connect("/api/spiking/pod", headers=AUTH)
        await ws.send_json({"type": "live_ready"})
        assert await until(lambda: hub.live_ready)

        async def pod():
            m = await ws.receive_json()
            await ws.send_json({"type": "decision", "id": m["id"], "pick": 1, "pool_rates": [1.0, 2.0],
                                "sim_ms": 50.0, "n_neurons": 1_000_000})
        task = asyncio.ensure_future(pod())
        out = await pod_manager.day_live_decide(["a", "b"], "chess", 2000)
        await task
        assert out["pick"] == 1 and out["net"] == "gpu"
        assert await pod_manager.day_live_reward(out["id"], 0.5) is None
        assert (await ws.receive_json()) == {"type": "reward", "id": out["id"], "value": 0.5}

        async def broken(*a, **k):
            raise RuntimeError("boom")
        hub.decide = broken
        assert await pod_manager.day_live_decide(["a", "b"]) is None                       # never raises
        hub.reward = lambda *a: 1 / 0
        assert await pod_manager.day_live_reward("x", 1.0) is None
        await ws.close()
        pod_manager.register_hub(None)
    asyncio.run(with_client(tmp_path, go))


# --- why pods die, and not burning the restart cap (2026-10-04) ---------------------------------------------------
import io  # noqa: E402
import urllib.error  # noqa: E402

from spiking import podpack  # noqa: E402
from spiking.runpod_ops import scrub  # noqa: E402


class SlowCreateApi(FakeApi):
    """RunPod creates the pod but the create request fails on our side (a timeout): the pod runs untracked unless
    it is found by name. The listing shows it only after `lag` list calls."""

    def __init__(self, lag=2, **kw):
        super().__init__(**kw)
        self.lag, self.hidden = lag, []

    def __call__(self, path, method="GET", body=None, timeout=60):
        if method == "POST" and path == "/pods":
            self.calls.append((method, path, body))
            self.n += 1
            self.hidden.append({"id": f"pod{self.n}", "name": body["name"], "costPerHr": 0.28,
                                "createdAt": "2026-10-02 08:05:00.000 +0000 UTC"})
            raise TimeoutError("timed out")
        if method == "GET" and path == "/pods" and self.hidden:
            self.lag -= 1
            if self.lag <= 0:
                self.pods += self.hidden
                self.hidden = []
        return super().__call__(path, method, body, timeout)


def no_capacity(*a, **k):
    return urllib.error.HTTPError("https://rest.runpod.io/v1/pods", 500, "err", {},
                                  io.BytesIO(b'{"error":"create pod: There are no instances currently available"}'))


class NoCapacityApi(FakeApi):
    def __call__(self, path, method="GET", body=None, timeout=60):
        if method == "POST" and path == "/pods":
            self.calls.append((method, path, body))
            raise no_capacity()
        return super().__call__(path, method, body, timeout)


def test_create_that_times_out_is_adopted_not_orphaned(tmp_path, capsys):
    d = Day(tmp_path, tk(2, 8), api=SlowCreateApi(lag=3))
    d.stage("AWAKE")
    d.until(tk(2, 8, 10))
    assert len(d.creates()) == 1 and d.mgr.current is not None and d.mgr.current["pod_id"] == "pod1"
    assert d.log.open_pods()[0]["pod_id"] == "pod1"                          # logged: its cost counts
    assert d.mgr.dl.get("restarts", 0) == 0


def test_no_capacity_retries_without_burning_restarts(tmp_path, capsys):
    d = Day(tmp_path, tk(2, 8), api=NoCapacityApi())
    d.stage("AWAKE")
    d.until(tk(2, 12))
    st = d.mgr.status()["day_live"]
    assert st["restarts_today"] == 0 and st["blocked"] is None and d.ours() == []
    tries = len(d.creates()) // len(pod_manager.DAY_GPUS)
    assert 40 <= tries <= 50                                                   # every 5 min, every type each time
    last = st["restart_log"][-1]
    assert last["why"] == "no pod created" and last["counted"] is False and last["pod_id"] is None
    assert "HTTP 500: create pod: There are no instances currently available" in last["last_error"]
    assert len(st["restart_log"]) == 10 and "not counted as a restart" in capsys.readouterr().out


def test_foreign_pod_waits_and_managed_orphan_is_deleted_and_booked(tmp_path, capsys):
    api = FakeApi(pods=[{"id": "val", "name": "sub01-spiking-live-validate-20261002", "costPerHr": 0.25}])
    d = Day(tmp_path, tk(2, 8), api=api)
    d.stage("AWAKE")
    d.until(tk(2, 8, 30))
    assert len(d.creates()) == 0 and ("DELETE", "/pods/val") not in api.mutating()      # a session's pod: left alone
    st = d.mgr.status()["day_live"]
    assert st["restarts_today"] == 0 and st["restart_log"][-1]["why"] == "another SUB-01 pod exists"
    assert "left alone" in capsys.readouterr().out
    api.pods = [p for p in api.pods if p["id"] != "val"]                     # its owner deletes it
    api.pods.append({"id": "orph", "name": "sub01-spiking-day-20261002-0700", "costPerHr": 0.28,
                     "createdAt": "2026-10-01 22:50:00.000 +0000 UTC"})       # one of ours, never logged
    d.until(tk(2, 8, 40))
    assert ("DELETE", "/pods/orph") in api.mutating() and d.mgr.current is not None
    booked = [r for r in d.log.rows() if r.get("pod_id") == "orph"]
    assert booked[0]["reason"] == "orphan" and booked[0]["cost_per_hr"] == 0.28 and booked[0]["hours"] > 0.2


def test_restart_log_says_why_and_rotates_gpu(tmp_path):
    d = Day(tmp_path, tk(2, 8))
    d.mgr.ops.opener = FakePodHttp()
    d.alive = False                                                          # no hello: the pod dies after 15 min
    d.stage("AWAKE")
    d.until(tk(2, 8, 30))
    st = d.mgr.status()["day_live"]
    e = st["restart_log"][-1]
    assert e["why"] == "no hello within 15 min" and e["counted"] and e["pod_id"] == "pod1"
    assert e["gpu"] == pod_manager.DAY_GPUS[0][0] and 15 * 60 <= e["secs_alive"] <= 17 * 60
    assert "pod phase waiting_upload" in e["last_error"]                     # the pod's own status.json
    assert st["gpu_failures_today"] == {pod_manager.DAY_GPUS[0][0]: 1}
    d.until(tk(2, 8, 40))
    second = d.creates()[1]["gpuTypeIds"][0]
    assert second == pod_manager.DAY_GPUS[1][0]                              # the failed type moved to the back
    assert [g[0] for g in d.mgr.gpu_order()[-2:]] == [pod_manager.DAY_GPUS[0][0], pod_manager.DAY_GPUS[1][0]]


def test_done_with_error_is_logged_with_the_pods_error(tmp_path):
    d = Day(tmp_path, tk(2, 8))
    d.stage("AWAKE")
    d.until(tk(2, 8, 7))
    d.mgr.on_done({"ok": False, "error": "OutOfMemoryError: CUDA out of memory"})
    d.step()
    e = d.mgr.status()["day_live"]["restart_log"][-1]
    assert e["why"] == "done with error" and "CUDA out of memory" in e["last_error"] and e["counted"]


def test_restart_log_has_no_secrets(tmp_path):
    assert "[redacted]" in scrub("Authorization: Bearer abc.def") and "abc.def" not in scrub("Bearer abc.def")
    assert "0123456789abcdef0123456789abcdef" not in scrub("token 0123456789abcdef0123456789abcdef!")
    d = Day(tmp_path, tk(2, 8))
    d.alive = False
    d.stage("AWAKE")
    d.until(tk(2, 9))
    env = d.creates()[0]["env"]
    dump = json.dumps(d.mgr.status())
    assert env["SUB01_POD_SECRET"] not in dump and env["SUB01_UPLOAD_TOKEN"] not in dump


def test_create_body_requires_a_driver_for_the_image():
    body = podpack.create_body({"SUB01_PACK_0": "x"}, "sub01-spiking-x", "NVIDIA RTX A4000", cloud="SECURE")
    assert body["allowedCudaVersions"] == ["12.8", "12.9", "13.0"]
