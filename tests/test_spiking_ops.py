"""Spiking ops tests: podpack, cost log, RunPodOps (fake API), pod manager (fake clock), server routes, gate.

No network, no RunPod calls: every API is a recording fake. Run: python -m pytest tests/test_spiking_ops.py -q
"""
import asyncio
import base64
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from spiking import podpack, pod_manager, server as spiking_server
from spiking.costs import CostLog
from spiking.pod_manager import PodManager, Schedule
from spiking.runpod_ops import CapExceeded, DeadlineExceeded, NotOurs, RunPodOps

ROOT = Path(__file__).resolve().parents[1]
TOKYO = ZoneInfo("Asia/Tokyo")
ENV = {"SUB01_PACK_0": "x"}


def run(coro):
    return asyncio.run(coro)


# --- fakes ---------------------------------------------------------------------------
class FakeApi:
    """Records calls; keeps a pod list that always contains the user's foreign pod BRAIN unless told otherwise."""

    def __init__(self, pods=None, fail_gpus=(), fail_deletes=0, foreign=True):
        self.pods = ([{"id": "brain1", "name": "BRAIN", "costPerHr": 0.5}] if foreign else []) + list(pods or [])
        self.calls, self.fail_gpus, self.fail_deletes, self.n = [], set(fail_gpus), fail_deletes, 0

    def __call__(self, path, method="GET", body=None, timeout=60):
        self.calls.append((method, path, body))
        if method == "GET" and path == "/pods":
            return [dict(p) for p in self.pods]
        if method == "POST" and path == "/pods":
            gpu = body["gpuTypeIds"][0]
            if gpu in self.fail_gpus:
                raise OSError("no capacity")
            self.n += 1
            pod = {"id": f"pod{self.n}", "name": body["name"], "costPerHr": 0.3, "gpu": gpu}
            self.pods.append(pod)
            return dict(pod)
        if method == "DELETE" and path.startswith("/pods/"):
            if self.fail_deletes > 0:
                self.fail_deletes -= 1
                raise OSError("boom")
            self.pods = [p for p in self.pods if p["id"] != path.rsplit("/", 1)[1]]
            return None
        raise AssertionError(f"unexpected call {method} {path}")

    def mutating(self):
        return [(m, p) for m, p, _ in self.calls if m != "GET"]


def make_ops(tmp_path, api=None, cap=4.0, clock=None, **kw):
    api = api or FakeApi()
    log = CostLog(tmp_path / "costs.jsonl", **({"clock": clock} if clock else {}))
    kw.setdefault("opener", FakePodHttp())                    # never a real network call
    return RunPodOps(api=api, log=log, hours_cap=cap, sleep=lambda s: None, install_hooks=False, **kw), api, log


class Resp:
    def __init__(self, data=b"", status=200):
        self.data, self.status = data, status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.data


class FakePodHttp:
    """Stands in for the pod behind proxy.runpod.net: status.json answers at once, PUT /upload is recorded."""

    def __init__(self, upload_code=200, put_error=None):
        self.upload_code, self.put_error, self.puts, self.gets = upload_code, put_error, [], []

    def __call__(self, req, timeout=0):
        name = req.full_url.split("proxy.runpod.net/")[1]
        if req.get_method() == "PUT":
            self.puts.append((name, req.data, dict(req.header_items())))
            if self.put_error:
                raise self.put_error
            if self.upload_code != 200:
                raise urllib.error.HTTPError(req.full_url, self.upload_code, "refused", {}, None)
            return Resp(b"ok")
        self.gets.append(name)
        if name == "status.json":
            return Resp(b'{"phase": "waiting_upload", "done": false}')
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)


class FakeClock:
    """Datetime clock whose async sleep advances time and fires scripted callbacks."""

    def __init__(self, now, stop_at=None):
        self.t, self.stop_at, self.script, self.slept = now, stop_at, [], 0

    def now(self):
        return self.t

    async def sleep(self, s):
        self.t += timedelta(seconds=s)
        self.slept += 1
        for item in list(self.script):
            if self.t >= item[0]:
                self.script.remove(item)
                r = item[1]()
                if asyncio.iscoroutine(r):
                    await r
        if self.stop_at and self.t >= self.stop_at:
            raise asyncio.CancelledError()
        await asyncio.sleep(0)


# --- podpack -------------------------------------------------------------------------
def test_pack_unpack_roundtrip(tmp_path, capsys):
    env = podpack.pack(verbose=True)
    total = podpack.packed_chars(env)
    print("packed size of the default set:", total, "characters in", len(env), "variables")
    assert total <= podpack.MAX_CHARS
    assert all(len(v) <= 96_000 for v in env.values())
    assert list(env) == [f"SUB01_PACK_{i}" for i in range(len(env))]
    names = podpack.unpack(env, tmp_path)
    for rel in ("real_baseline.py", "out/connectome.npz", "out/atlas_names.json", "spiking/podpack.py"):
        assert rel in names and (tmp_path / rel).read_bytes() == (ROOT / rel).read_bytes()
    qc = json.loads((tmp_path / "out/rest/qc.json").read_text())
    runs = sorted(p.stem for p in (tmp_path / "out/rest").glob("*.npz"))
    assert runs and sorted(qc) == runs and all(v["kept"] for v in qc.values())
    d = np.load(tmp_path / "out/rest" / f"{runs[0]}.npz")
    assert d["ts"].dtype == np.float16 and float(d["tr"]) > 0
    from real_baseline import RealBaseline
    names = json.loads((tmp_path / "out/atlas_names.json").read_text())[:6]
    b = RealBaseline(names, tmp_path / "out/rest")
    assert len(b.files) == len(runs) and b.advance(1.0).shape == (6,)


def test_pack_limits_and_extra(tmp_path):
    env = podpack.pack(files=["real_baseline.py"], extra={"x/y.bin": b"hello"}, chunk=500)
    assert len(env) > 1 and all(len(v) <= 500 for v in env.values())
    assert "x/y.bin" in podpack.unpack(env, tmp_path)
    junk = np.random.default_rng(0).bytes(800_000)
    with pytest.raises(ValueError):
        podpack.pack(files=["real_baseline.py"], extra={"junk.bin": junk})


def test_rest_subset_only_kept(tmp_path):
    sub = podpack.rest_subset(k=2, seed=3)
    qc_all = json.loads((ROOT / "out/rest/qc.json").read_text())
    stems = [Path(n).stem for n in sub if n.endswith(".npz")]
    assert len(stems) == 2 and all(qc_all[s]["kept"] for s in stems)
    assert sorted(json.loads(sub["out/rest/qc.json"])) == sorted(stems)


def test_create_body_and_start_cmd():
    body = podpack.create_body(ENV, "sub01-spiking-x")
    assert body["gpuTypeIds"] == ["NVIDIA RTX A5000"] and body["gpuCount"] == 1
    assert body["interruptible"] is False and body["cloudType"] == "SECURE"
    assert body["volumeInGb"] == 0 and body["containerDiskInGb"] == 30 and body["ports"] == ["8000/http"]
    assert body["imageName"] == "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404" and body["env"] == ENV
    assert podpack.create_body(ENV, "n", "NVIDIA RTX 4000 Ada Generation")["gpuTypeIds"] == ["NVIDIA RTX 4000 Ada Generation"]
    for bad in ("NVIDIA H100 80GB HBM3", "NVIDIA RTX A6000", ""):
        with pytest.raises(AssertionError):
            podpack.create_body(ENV, "n", bad)
    cmd = podpack.create_body(ENV, "n", module="spiking.validate_pod")["dockerStartCmd"]
    assert cmd[:2] == ["bash", "-c"]
    s = cmd[2]
    assert "python3 -m http.server 8000 -d /out" in s and "echo $? > /out/exit_code; sleep 600" in s
    assert "python3 -m spiking.validate_pod > /out/session.log 2>&1" in s and "mkdir -p /app /out" in s
    assert podpack.start_cmd()[2].count("python3 -m spiking.session") == 1


def test_create_body_boot_env_and_size_limit():
    token = "t" * 48
    env = podpack.boot_env(token, "spiking.session")
    body = podpack.create_body(env, "sub01-spiking-x")
    assert body["dockerStartCmd"] == podpack.boot_cmd() and body["env"]["SUB01_UPLOAD_TOKEN"] == token
    assert len(json.dumps(body)) < 90_000 and "SUB01_PACK_0" not in body["env"]
    assert base64.b64decode(env["SUB01_BOOT"]).decode() == podpack.BOOT_PY
    compile(podpack.BOOT_PY, "boot.py", "exec")                                   # the bootstrap is valid Python
    with pytest.raises(AssertionError):
        podpack.boot_env("short")
    with pytest.raises(AssertionError):                                           # a pack in env vars is too big
        podpack.create_body(dict(env, SUB01_BIG="x" * 100_000), "n")
    with pytest.raises(AssertionError):
        podpack.create_body(env, "n", "NVIDIA H100 80GB HBM3")


def test_pack_bytes_members():
    import tarfile
    names = tarfile.open(fileobj=io.BytesIO(podpack.pack_bytes(k=1)), mode="r:xz").getnames()
    assert "real_baseline.py" in names and "out/connectome.npz" in names and "out/rest/qc.json" in names
    assert any(n.startswith("spiking/") and n.endswith(".py") for n in names)


# --- cost log ------------------------------------------------------------------------
def test_costlog_totals_open_and_days(tmp_path):
    t = [datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)]
    log = CostLog(tmp_path / "s" / "costs.jsonl", clock=lambda: t[0])
    log.start("a", "sub01-spiking-a", "NVIDIA RTX A5000", 0.4, "validate")
    t[0] += timedelta(minutes=90)
    rec = log.stop("a", "done")
    assert rec["hours"] == 1.5 and rec["cost_usd"] == 0.6 and rec["reason"] == "done" and rec["purpose"] == "validate"
    assert {"pod_id", "name", "gpu", "cost_per_hr", "start", "stop", "hours", "cost_usd", "reason", "purpose"} <= set(rec)
    assert log.stop("a", "again") is None and log.open_pods() == []
    assert log.total_hours() == 1.5 and abs(log.total_usd() - 0.6) < 1e-9
    # "crash": started, never stopped -> open, counted up to now
    log.start("b", "sub01-spiking-b", "NVIDIA RTX A5000", 1.0, "session")
    t[0] += timedelta(minutes=30)
    assert [p["pod_id"] for p in log.open_pods()] == ["b"]
    assert abs(log.total_hours() - 2.0) < 1e-9 and abs(log.total_usd() - 1.1) < 1e-9
    # a new process reading the same file sees the same thing
    log2 = CostLog(log.path, clock=lambda: t[0])
    assert [p["pod_id"] for p in log2.open_pods()] == ["b"] and abs(log2.total_hours() - 2.0) < 1e-9
    with open(log.path, "a") as f:
        f.write('{"torn": ')                                  # torn last line is ignored
    assert abs(log2.total_hours() - 2.0) < 1e-9
    # 12:00 UTC = 21:00 Tokyo, the same local day; 1.5 h + 0.5 h
    assert abs(log2.hours_on("2026-10-01") - 2.0) < 1e-9 and log2.hours_on("2026-09-30") == 0
    assert all(json.loads(line) for line in log.path.read_text().splitlines()[:3])


def test_costlog_local_date_is_tokyo(tmp_path):
    log = CostLog(tmp_path / "c.jsonl", clock=lambda: datetime(2026, 10, 1, 16, 0, tzinfo=timezone.utc))
    log.start("a", "n", "g", 0.0, "p")                       # 16:00 UTC = 01:00 on Oct 2 in Tokyo
    assert log.hours_on("2026-10-02") == 0.0 and [p["pod_id"] for p in log.open_pods()] == ["a"]
    log.clock = lambda: datetime(2026, 10, 1, 17, 0, tzinfo=timezone.utc)
    assert abs(log.hours_on("2026-10-02") - 1.0) < 1e-9 and log.hours_on("2026-10-01") == 0


# --- RunPodOps -----------------------------------------------------------------------
def test_ops_ours_and_refuses_second_pod(tmp_path):
    ops, api, log = make_ops(tmp_path)
    assert ops.ours() == []
    pod = ops.create(ENV, "session", max_minutes=30)
    assert pod["name"].startswith("sub01-spiking-") and [p["id"] for p in ops.ours()] == [pod["id"]]
    with pytest.raises(RuntimeError):
        ops.create(ENV, "session", max_minutes=30)
    assert len([c for c in api.calls if c[0] == "POST"]) == 1
    assert log.open_pods()[0]["pod_id"] == pod["id"] and log.open_pods()[0]["cost_per_hr"] == 0.3
    assert pod["id"] in ops.deadlines


def test_ops_hours_cap(tmp_path):
    ops, api, log = make_ops(tmp_path, cap=1.0)
    log.start("old", "sub01-spiking-old", "g", 0.3, "x")
    log.clock = lambda: datetime.now(timezone.utc) + timedelta(minutes=45)       # 0.75 h burnt
    with pytest.raises(CapExceeded):
        ops.create(ENV, "session", max_minutes=30)                                # 0.75 + 0.5 > 1.0
    assert not [c for c in api.calls if c[0] == "POST"]
    ops.hours_cap = 1.5
    assert ops.create(ENV, "session", max_minutes=30)["id"]


def test_ops_falls_back_to_4000_ada(tmp_path):
    ops, api, log = make_ops(tmp_path, api=FakeApi(fail_gpus={"NVIDIA RTX A5000"}))
    pod = ops.create(ENV, "session", max_minutes=30)
    posts = [c[2]["gpuTypeIds"] for c in api.calls if c[0] == "POST"]
    assert posts == [["NVIDIA RTX A5000"], ["NVIDIA RTX 4000 Ada Generation"]]
    assert log.open_pods()[0]["gpu"] == "NVIDIA RTX 4000 Ada Generation" and pod["id"]
    ops2, api2, _ = make_ops(tmp_path / "b", api=FakeApi(fail_gpus=set(podpack.GPUS)))
    with pytest.raises(RuntimeError):
        ops2.create(ENV, "session", max_minutes=30)
    assert len([c for c in api2.calls if c[0] == "POST"]) == len(podpack.GPUS) and ops2.ours() == []      # tried each type once


def test_ops_guard_deletes_on_exception_and_interrupt(tmp_path):
    for exc in (ValueError("x"), KeyboardInterrupt()):
        ops, api, log = make_ops(tmp_path / type(exc).__name__)
        pod = ops.create(ENV, "session", max_minutes=30)
        with pytest.raises(type(exc)):
            with ops.guard(pod["id"]):
                raise exc
        assert ops.ours() == [] and ("DELETE", f"/pods/{pod['id']}") in api.mutating()
        assert log.open_pods() == [] and [p for p in api.pods if p["name"] == "BRAIN"]
    row = [json.loads(line) for line in log.path.read_text().splitlines()][-1]
    assert row["reason"] == "interrupted"


def test_ops_guard_clean_exit_does_not_delete_but_deadline_does(tmp_path):
    ops, api, log = make_ops(tmp_path)
    pod = ops.create(ENV, "session", max_minutes=30)
    with ops.guard(pod["id"]):
        pass
    assert ops.ours() and not [m for m in api.mutating() if m[0] == "DELETE"]
    with pytest.raises(DeadlineExceeded):
        with ops.guard(pod["id"], deadline=ops.clock() - 1):
            pass
    assert ops.ours() == [] and [json.loads(x).get("reason") for x in log.path.read_text().splitlines()][-1] == "deadline"


def test_ops_guard_timer_deletes_blocked_body(tmp_path):
    import time
    ops, api, log = make_ops(tmp_path)
    pod = ops.create(ENV, "session", max_minutes=30)
    with pytest.raises(DeadlineExceeded):
        with ops.guard(pod["id"], deadline=ops.clock() + 0.05):
            time.sleep(0.3)                                        # body blocked past the deadline
    assert ops.ours() == [] and len([m for m in api.mutating() if m[0] == "DELETE"]) == 1


def test_ops_never_touches_foreign_pod(tmp_path):
    ops, api, log = make_ops(tmp_path)
    with pytest.raises(NotOurs):
        ops.delete("brain1", "oops")
    assert not [m for m in api.mutating() if m[0] == "DELETE"]
    ours = ops.create(ENV, "session", max_minutes=30)
    assert ops.cleanup_ours("startup recovery") == [ours["id"]]
    assert [p["name"] for p in api.pods] == ["BRAIN"] and api.mutating()[-1] == ("DELETE", f"/pods/{ours['id']}")
    assert all(p != "/pods/brain1" for _, p in api.mutating())
    # a pod renamed behind our back between list and delete is refused (name re-checked on every delete)
    api.pods.append({"id": "podX", "name": "BRAIN-2"})
    with pytest.raises(NotOurs):
        ops.delete("podX", "x")
    assert ops.cleanup_ours("again") == []


def test_ops_delete_retries_then_logs_cost(tmp_path):
    t = [datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)]
    ops, api, log = make_ops(tmp_path, api=FakeApi(fail_deletes=2), clock=lambda: t[0])
    pod = ops.create(ENV, "session", max_minutes=30)
    t[0] += timedelta(hours=1)
    assert ops.delete(pod["id"], "session end") is True
    assert len([m for m in api.mutating() if m[0] == "DELETE"]) == 3
    rec = [json.loads(x) for x in log.path.read_text().splitlines()][-1]
    assert rec["reason"] == "session end" and rec["hours"] == 1.0 and abs(rec["cost_usd"] - 0.3) < 1e-9
    assert ops.delete(pod["id"], "again") is True                # idempotent


def test_ops_delete_failure_raises_and_keeps_log_open(tmp_path):
    ops, api, log = make_ops(tmp_path, api=FakeApi(fail_deletes=99))
    pod = ops.create(ENV, "session", max_minutes=30)
    with pytest.raises(RuntimeError):
        ops.delete(pod["id"], "x")
    assert len([m for m in api.mutating() if m[0] == "DELETE"]) == 3
    assert [p["pod_id"] for p in log.open_pods()] == [pod["id"]]   # still counted against the cap


def test_ops_exit_cleanup_and_proxy_fetch_has_no_key(tmp_path, monkeypatch):
    seen = []

    def opener(req, timeout=0):
        seen.append((req.full_url, dict(req.header_items())))
        if len(seen) < 3:
            raise OSError("not up yet")
        return Resp(b'{"done": true}')

    monkeypatch.setenv("RUNPOD_API_KEY", "secret-key-123")
    ops, api, log = make_ops(tmp_path, opener=opener)
    pod = ops.create(ENV, "session", max_minutes=30)
    assert ops.wait_http(pod["id"], "status.json", timeout=100) == b'{"done": true}' and len(seen) == 3
    assert seen[0][0] == f"https://{pod['id']}-8000.proxy.runpod.net/status.json"
    assert not any(k.lower() == "authorization" for _, h in seen for k in h)
    ops._exit_cleanup()
    assert ops.ours() == [] and [p["name"] for p in api.pods] == ["BRAIN"]


def test_ops_upload_puts_with_token_and_no_key(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNPOD_API_KEY", "secret-key-123")
    http = FakePodHttp()
    ops, api, log = make_ops(tmp_path, opener=http)
    pod = ops.create(ENV, "session", max_minutes=30)
    assert ops.upload(pod["id"], b"PACK", "tok" * 12) is True
    name, data, headers = http.puts[0]
    assert name == "upload" and data == b"PACK" and headers["X-upload-token"] == "tok" * 12
    assert "Authorization" not in headers and http.gets == ["status.json"]          # waited for the bootstrap first


def test_ops_upload_403_is_final_and_5xx_retries_boundedly(tmp_path):
    http = FakePodHttp(upload_code=403)
    ops, api, log = make_ops(tmp_path, opener=http)
    pod = ops.create(ENV, "session", max_minutes=30)
    with pytest.raises(RuntimeError):
        ops.upload(pod["id"], b"PACK", "t" * 40)
    assert len(http.puts) == 1                                                       # no retry loop on 403
    http = FakePodHttp(upload_code=502)
    ops.opener = http
    with pytest.raises(RuntimeError):
        ops.upload(pod["id"], b"PACK", "t" * 40)
    assert len(http.puts) == 5                                                       # bounded retries otherwise
    ops.opener = FakePodHttp(put_error=OSError("reset"))
    with pytest.raises(RuntimeError):
        ops.upload(pod["id"], b"PACK", "t" * 40)
    assert len(ops.opener.puts) == 5


def test_ops_wait_http_timeout(tmp_path):
    t = [0.0]
    ops, _, _ = make_ops(tmp_path, clock=None)
    ops.clock = lambda: t[0]
    ops.sleep = lambda s: t.__setitem__(0, t[0] + s)
    ops.opener = lambda req, timeout=0: (_ for _ in ()).throw(OSError("down"))
    with pytest.raises(TimeoutError):
        ops.wait_http("p", "status.json", timeout=30, interval=5)


# --- schedule ------------------------------------------------------------------------
def tk(day, h, m=0):
    return datetime(2026, 10, day, h, m, tzinfo=TOKYO)


def test_schedule_parse_and_next():
    s = Schedule.parse("daily 21:00-23:00 Asia/Tokyo")
    assert s.next_session(tk(1, 20)) == (tk(1, 21), tk(1, 23))
    assert s.next_session(tk(1, 22)) == (tk(1, 21), tk(1, 23))              # running now
    assert s.next_session(tk(1, 23, 30)) == (tk(2, 21), tk(2, 23))
    assert s.next_session(tk(1, 20).astimezone(timezone.utc)) == (tk(1, 21), tk(1, 23))
    assert Schedule.parse("21:00-23:00").windows == [(1260, 1380, "Asia/Tokyo")]
    s = Schedule.parse("22:00-02:00")                                        # crosses midnight
    assert s.next_session(tk(2, 1)) == (tk(1, 22), tk(2, 2))
    assert s.next_session(tk(2, 3)) == (tk(2, 22), tk(3, 2))
    s = Schedule.parse("daily 21:00-23:00 Asia/Tokyo; 06:00-07:00 Europe/Rome")
    assert len(s.windows) == 2
    start, end = s.next_session(tk(1, 20))
    assert start == datetime(2026, 10, 1, 6, 0, tzinfo=ZoneInfo("Europe/Rome")) or start == tk(1, 21)
    assert s.next_session(tk(1, 20), skip={tk(1, 21)})[0] != tk(1, 21)
    for off in ("", None, "  "):
        assert not Schedule.parse(off).enabled and Schedule.parse(off).next_session(tk(1, 1)) is None
    with pytest.raises(ValueError):
        Schedule.parse("25:00-26:00")
    with pytest.raises(ValueError):
        Schedule.parse("tonight")


def test_top_messages_weighting():
    from sleep import Memory
    t = tk(1, 21).timestamp()
    mem = Memory()
    mem.add(t - 3600, "plain one", "AWAKE", {}, "neutral", [])
    mem.add(t - 3600, "threat one", "AWAKE", {}, "threat", [])
    mem.add(t - 1800, "positive one", "AWAKE", {}, "positive", [])
    mem.add(t - 2 * 86400, "old one", "AWAKE", {}, "threat", [])
    out = pod_manager.top_messages(mem, t, n=2)
    assert [m["text"] for m in out] == ["threat one", "positive one"] and set(out[0]) == {"text", "emotion"}


# --- pod manager ---------------------------------------------------------------------
def make_mgr(tmp_path, now, api=None, env=None, schedule="21:00-23:00", **kw):
    fc = FakeClock(now, kw.pop("stop_at", None))
    api = api or FakeApi()
    log = CostLog(tmp_path / "spiking" / "costs.jsonl", clock=fc.now)
    ops = RunPodOps(api=api, log=log, hours_cap=4.0, sleep=lambda s: None, install_hooks=False, opener=FakePodHttp())
    mgr = PodManager(tmp_path, "https://srv.example", "pod-secret", clock=fc.now, sleep=fc.sleep, ops=ops, tick=5.0,
                     schedule=Schedule.parse(schedule), env=env or {}, get_messages=kw.pop("get_messages", None))
    mgr._pack = lambda: b"tar-bytes"
    stops = []

    async def send_stop():
        stops.append(fc.now())
    mgr.send_stop = send_stop
    return mgr, fc, api, log, stops


def beats(mgr, fc, start, until=None, every=30):
    """Scripted state frames from `start` (until `until`), like a healthy pod."""
    def beat():
        if until is None or fc.t < until:
            mgr.on_state({})
            fc.script.append((fc.t + timedelta(seconds=every), beat))
    fc.script.append((start, beat))


def reasons(log):
    return [json.loads(x)["reason"] for x in log.path.read_text().splitlines() if '"stop"' in x]


def test_manager_disabled_when_off_or_missing_env(tmp_path, capsys):
    api = FakeApi()
    mgr = PodManager(tmp_path, "https://srv", "s", api=api, env={"SUB01_SESSIONS": "off"})
    assert not mgr.enabled() and not mgr.enabled()
    assert capsys.readouterr().out.count("disabled") == 1                      # said once
    run(mgr.run())
    assert api.calls == []                                                     # no RunPod call at all
    assert PodManager(tmp_path, "https://srv", "", api=api, env={"SUB01_SESSIONS": "21:00-23:00"}).enabled() is False
    assert PodManager(tmp_path, "https://srv", "s", api=api, env={"SUB01_SESSIONS": "21:00-23:00"}).enabled() is True
    # no RunPod key on the server (Railway env RUNPOD_API_KEY): disabled, nothing is called
    nokey = PodManager(tmp_path, "https://srv", "s", env={})
    assert nokey.enabled() is False and "RUNPOD_API_KEY" in capsys.readouterr().out
    assert PodManager(tmp_path, "https://srv", "s", env={"RUNPOD_API_KEY": "k"}).enabled() is True
    st = mgr.status()
    assert st["live"] is False and st["session"] is None and st["next_session"] is None


def test_manager_session_end_stops_and_deletes(tmp_path):
    msgs = [{"text": f"m{i}", "emotion": "neutral"} for i in range(8)]
    mgr, fc, api, log, stops = make_mgr(tmp_path, tk(1, 21), get_messages=lambda: msgs)
    fc.script.append((tk(1, 21, 2), mgr.on_hello))
    keep = []

    def keep_alive():
        mgr.on_state({"phase": "pong_train", "t_sim": 5.0})
        keep.append(mgr.status())
        fc.script.append((fc.t + timedelta(seconds=60), keep_alive))
    fc.script.append((tk(1, 21, 3), keep_alive))
    res = run(mgr.run_session(tk(1, 21), tk(1, 23)))
    assert res == "session end" and reasons(log) == ["session end"]
    assert api.pods == [p for p in api.pods if p["name"] == "BRAIN"] and len(api.pods) == 1
    assert len(stops) == 1 and stops[0] >= tk(1, 21) + timedelta(minutes=58)               # asked to wrap up first
    assert stops[0] <= tk(1, 21) + timedelta(minutes=60)                                    # 60 min cap per session
    assert keep[0]["live"] is True and keep[0]["session"]["phase"] == "pong_train"
    post = [c[2] for c in api.calls if c[0] == "POST"][0]
    cfg = json.loads(post["env"]["SUB01_SESSION"])
    assert cfg["session_id"] == "s-20261001-2100" and cfg["n_neurons"] == 1_000_000 and cfg["validate"] is False
    assert len(cfg["messages"]) == 5 and cfg["max_minutes"] == 45 and cfg["day"] == "2026-10-01"
    assert [it["source"] for it in cfg["items"]] == ["chat"] * 5
    assert cfg["phases"][0] == "recall_yesterday" and "pong_train" not in cfg["phases"]            # Pong is opt-in
    assert post["env"]["SUB01_SERVER_URL"] == "https://srv.example" and post["env"]["SUB01_POD_SECRET"] == "pod-secret"
    assert post["env"]["SUB01_SESSION_ID"] == "s-20261001-2100" and post["name"].startswith("sub01-spiking-")
    assert mgr.current is None


def test_manager_no_hello_deletes_after_15_min(tmp_path):
    mgr, fc, api, log, stops = make_mgr(tmp_path, tk(1, 21))
    t0 = fc.t
    assert run(mgr.run_session(tk(1, 21), tk(1, 23))) == "no hello within 15 min"
    assert timedelta(minutes=15) <= fc.t - t0 < timedelta(minutes=16) and len(api.pods) == 1
    assert reasons(log) == ["no hello within 15 min"] and stops == []


def test_manager_stream_lost_deletes(tmp_path):
    mgr, fc, api, log, stops = make_mgr(tmp_path, tk(1, 21))
    fc.script.append((tk(1, 21, 2), mgr.on_hello))
    beats(mgr, fc, tk(1, 21, 2), until=tk(1, 21, 10))
    fc.script.append((tk(1, 21, 10), mgr.on_disconnect))
    t0 = fc.t
    assert run(mgr.run_session(tk(1, 21), tk(1, 23))) == "stream lost"
    assert timedelta(minutes=13) <= fc.t - t0 <= timedelta(minutes=14) and len(api.pods) == 1
    # a silent stream (no frames, no disconnect event) is also lost after 3 minutes
    mgr, fc, api, log, stops = make_mgr(tmp_path / "b", tk(1, 21))
    fc.script.append((tk(1, 21, 2), mgr.on_hello))
    assert run(mgr.run_session(tk(1, 21), tk(1, 23))) == "stream lost" and len(api.pods) == 1


def test_manager_reconnect_within_grace_keeps_pod(tmp_path):
    mgr, fc, api, log, stops = make_mgr(tmp_path, tk(1, 21))
    fc.script.append((tk(1, 21, 2), mgr.on_hello))
    beats(mgr, fc, tk(1, 21, 2), until=tk(1, 21, 10))
    fc.script.append((tk(1, 21, 10), mgr.on_disconnect))
    fc.script.append((tk(1, 21, 11), mgr.on_hello))
    beats(mgr, fc, tk(1, 21, 11))
    assert run(mgr.run_session(tk(1, 21), tk(1, 23))) == "session end"


def test_manager_done_deletes_and_error_deletes(tmp_path):
    mgr, fc, api, log, stops = make_mgr(tmp_path, tk(1, 21))
    fc.script.append((tk(1, 21, 2), mgr.on_hello))
    fc.script.append((tk(1, 21, 30), lambda: mgr.on_done({"ok": True})))

    beats(mgr, fc, tk(1, 21, 2))
    assert run(mgr.run_session(tk(1, 21), tk(1, 23))) == "done" and len(api.pods) == 1
    assert (tmp_path / "spiking" / "manager.json").exists()
    # an exception while watching still deletes the pod
    mgr, fc, api, log, stops = make_mgr(tmp_path / "e", tk(1, 21))

    def boom():
        raise RuntimeError("watch broke")
    fc.script.append((tk(1, 21, 1), boom))
    with pytest.raises(RuntimeError):
        run(mgr.run_session(tk(1, 21), tk(1, 23)))
    assert len(api.pods) == 1 and reasons(log) == ["error"]
    # pod reports a failure
    mgr, fc, api, log, stops = make_mgr(tmp_path / "f", tk(1, 21))
    fc.script.append((tk(1, 21, 1), mgr.on_hello))
    fc.script.append((tk(1, 21, 2), lambda: mgr.on_done({"ok": False, "error": "cuda out of memory"})))
    assert run(mgr.run_session(tk(1, 21), tk(1, 23))).startswith("done with error") and len(api.pods) == 1


def test_manager_uploads_pack_after_create(tmp_path):
    mgr, fc, api, log, stops = make_mgr(tmp_path, tk(1, 21))
    fc.script.append((tk(1, 21, 2), mgr.on_hello))
    beats(mgr, fc, tk(1, 21, 2), until=tk(1, 21, 10))
    assert run(mgr.run_session(tk(1, 21), tk(1, 23))) == "stream lost"
    name, data, headers = mgr.ops.opener.puts[0]
    env = [c[2] for c in api.calls if c[0] == "POST"][0]["env"]
    assert name == "upload" and data == b"tar-bytes" and headers["X-upload-token"] == env["SUB01_UPLOAD_TOKEN"]
    assert "SUB01_PACK_0" not in env and len(env["SUB01_UPLOAD_TOKEN"]) >= 32


def test_manager_deletes_pod_when_upload_fails(tmp_path):
    mgr, fc, api, log, stops = make_mgr(tmp_path, tk(1, 21))
    mgr.ops.opener = FakePodHttp(upload_code=403)
    with pytest.raises(RuntimeError):
        run(mgr.run_session(tk(1, 21), tk(1, 23)))
    assert [p["name"] for p in api.pods] == ["BRAIN"] and reasons(log) == ["pack upload failed"]
    assert mgr.current is None and len(mgr.ops.opener.puts) == 1
    # any other exception from upload (e.g. a timeout waiting for the pod) also deletes it
    mgr, fc, api, log, stops = make_mgr(tmp_path / "t", tk(1, 21))
    mgr.ops.upload = lambda *a, **k: (_ for _ in ()).throw(TimeoutError("pod never answered"))
    with pytest.raises(TimeoutError):
        run(mgr.run_session(tk(1, 21), tk(1, 23)))
    assert [p["name"] for p in api.pods] == ["BRAIN"] and reasons(log) == ["pack upload failed"]


def test_manager_cancel_deletes_pod(tmp_path):
    mgr, fc, api, log, stops = make_mgr(tmp_path, tk(1, 21), stop_at=tk(1, 21, 5))
    with pytest.raises(asyncio.CancelledError):
        run(mgr.run_session(tk(1, 21), tk(1, 23)))
    assert len(api.pods) == 1 and mgr.current is None and log.open_pods() == []


def test_manager_daily_cap(tmp_path):
    mgr, fc, api, log, stops = make_mgr(tmp_path, tk(1, 21))
    log.start("old", "sub01-spiking-old", "g", 0.3, "session")
    fc.t += timedelta(hours=2.4)                                              # 2.4 h today already
    log.stop("old", "done")
    fc.t = tk(1, 23, 59)
    assert "skipped" in run(mgr.run_session(tk(1, 21), tk(2, 2)))             # only 0.1 h (6 min) left today
    assert not [c for c in api.calls if c[0] == "POST"]
    fc.t = tk(2, 21)                                                          # next local day: fresh budget
    mgr.ops.hours_cap = 100.0
    beats(mgr, fc, tk(2, 21, 1))
    fc.script.append((tk(2, 21, 1), mgr.on_hello))
    out = run(mgr.run_session(tk(2, 21), tk(2, 23)))
    assert out != "" and not str(out).startswith("skipped") and [c for c in api.calls if c[0] == "POST"]


def test_manager_session_minutes_capped_and_total_cap(tmp_path):
    mgr, fc, api, log, stops = make_mgr(tmp_path, tk(1, 21), env={"SUB01_MAX_SESSION_MIN": "30"})
    mgr.max_session_min = 30
    mgr.log.hours_on = lambda d: 0.0
    t0 = fc.t
    fc.script.append((tk(1, 21, 1), mgr.on_hello))

    def beat():
        mgr.on_state({})
        fc.script.append((fc.t + timedelta(seconds=60), beat))
    fc.script.append((tk(1, 21, 1), beat))
    assert run(mgr.run_session(tk(1, 21), tk(1, 23))) == "session end"
    assert fc.t - t0 == timedelta(minutes=30)
    # total GPU-hour cap refuses before any POST
    mgr, fc, api, log, stops = make_mgr(tmp_path / "t", tk(1, 21))
    mgr.ops.hours_cap = 0.25
    with pytest.raises(CapExceeded):
        run(mgr.run_session(tk(1, 21), tk(1, 23)))
    assert not [c for c in api.calls if c[0] == "POST"]


def test_manager_run_loop_recovers_and_runs_window(tmp_path):
    api = FakeApi(pods=[{"id": "stale", "name": "sub01-spiking-session-old"}])
    mgr, fc, api, log, stops = make_mgr(tmp_path, tk(1, 20, 59), api=api, stop_at=tk(1, 22))
    fc.script.append((tk(1, 21, 2), mgr.on_hello))
    fc.script.append((tk(1, 21, 30), lambda: mgr.on_done({"ok": True})))

    def beat():
        mgr.on_state({})
        fc.script.append((fc.t + timedelta(seconds=60), beat))
    fc.script.append((tk(1, 21, 3), beat))
    with pytest.raises(asyncio.CancelledError):
        run(mgr.run())
    assert ("DELETE", "/pods/stale") in api.mutating() and ("DELETE", "/pods/brain1") not in api.mutating()
    assert len([c for c in api.calls if c[0] == "POST"]) == 1 and [p["name"] for p in api.pods] == ["BRAIN"]
    assert "done" in reasons(log)
    # the window is remembered across restarts
    mgr2 = PodManager(tmp_path, "https://srv", "s", api=FakeApi(), schedule=Schedule.parse("21:00-23:00"), env={})
    mgr2._load_done()
    assert tk(1, 21) in {d.astimezone(TOKYO) for d in mgr2.done_windows}


def test_elapsed_days(tmp_path):
    mgr, fc, *_ = make_mgr(tmp_path, tk(2, 21))
    assert mgr.elapsed_days(tk(2, 21)) == 1.0
    mgr._save(last_session_end=tk(1, 21).isoformat())
    assert mgr.elapsed_days(tk(2, 21)) == 1.0 and mgr.elapsed_days(tk(2, 9)) == 0.5


# --- server routes -------------------------------------------------------------------
class FakeLive:
    def __init__(self):
        self.sent, self.spiking = [], None

    async def broadcast(self, msg):
        self.sent.append(msg)


def npz_bytes(**arrays):
    b = io.BytesIO()
    np.savez(b, **arrays)
    return b.getvalue()


async def with_client(tmp_path, fn, middlewares=(), secret="sek", monkeypatch=None):
    live = FakeLive()
    app = web.Application(client_max_size=1024, middlewares=list(middlewares))
    hub = spiking_server.attach(app, live, tmp_path, secret=secret)
    async with TestClient(TestServer(app)) as client:
        await fn(client, hub, live)


AUTH = {"Authorization": "Bearer sek"}


async def until(cond, n=100):
    for _ in range(n):
        if cond():
            return True
        await asyncio.sleep(0.02)
    return False


def test_server_auth_rules(tmp_path, monkeypatch):
    async def go(client, hub, live):
        for path in ("/api/spiking/weights", "/api/spiking/pod"):
            assert (await client.get(path)).status == 401                              # no header
            assert (await client.get(path, headers={"Authorization": "Bearer nope"})).status == 401
            assert (await client.get(path, headers={"Authorization": "sek"})).status == 401
        assert (await client.post("/api/spiking/result", json={"kind": "exam"})).status == 401
        assert (await client.post("/api/spiking/weights", data=b"PK")).status == 401
        assert (await client.get("/api/spiking/weights", headers={"Authorization": "Bearer sék"})).status == 401
    run(with_client(tmp_path, go))

    async def nosecret(client, hub, live):
        monkeypatch.delenv("SUB01_POD_SECRET", raising=False)
        for path in ("/api/spiking/weights", "/api/spiking/pod"):
            assert (await client.get(path, headers=AUTH)).status == 403
        assert (await client.post("/api/spiking/weights", data=b"PK", headers=AUTH)).status == 403
        assert (await client.post("/api/spiking/result", json={}, headers=AUTH)).status == 403
    monkeypatch.delenv("SUB01_POD_SECRET", raising=False)
    run(with_client(tmp_path / "ns", nosecret, secret=None))
    monkeypatch.setenv("SUB01_POD_SECRET", "from-env")

    async def env_secret(client, hub, live):
        assert (await client.get("/api/spiking/weights", headers={"Authorization": "Bearer from-env"})).status == 404
    run(with_client(tmp_path / "env", env_secret, secret=None))


def test_server_weights_roundtrip_and_prev(tmp_path, monkeypatch):
    async def go(client, hub, live):
        assert (await client.get("/api/spiking/weights", headers=AUTH)).status == 404
        first = npz_bytes(w=np.arange(10, dtype=np.float32))
        big = npz_bytes(w=np.zeros(5000, dtype=np.float32))                          # > client_max_size (1 KiB)
        assert len(big) > 1024
        r = await client.post("/api/spiking/weights", data=first, headers=AUTH)
        assert r.status == 200 and (await r.json())["bytes"] == len(first)
        got = await client.get("/api/spiking/weights", headers=AUTH)
        assert got.status == 200 and await got.read() == first
        assert not (tmp_path / "spiking" / "weights.prev.npz").exists()
        r = await client.post("/api/spiking/weights", data=big, headers=AUTH)
        assert r.status == 200
        assert await (await client.get("/api/spiking/weights", headers=AUTH)).read() == big
        assert (tmp_path / "spiking" / "weights.prev.npz").read_bytes() == first
        assert not list((tmp_path / "spiking").glob("*.tmp"))
        r = await client.post("/api/spiking/weights", data=b"not a zip", headers=AUTH)
        assert r.status == 400 and await (await client.get("/api/spiking/weights", headers=AUTH)).read() == big
        monkeypatch.setattr(spiking_server, "MAX_WEIGHTS", 100)
        r = await client.post("/api/spiking/weights", data=big, headers=AUTH)
        assert r.status == 413 and not list((tmp_path / "spiking").glob("*.tmp"))
        assert await (await client.get("/api/spiking/weights", headers=AUTH)).read() == big
    run(with_client(tmp_path, go))


def test_server_results_and_status(tmp_path):
    async def go(client, hub, live):
        st = await (await client.get("/api/spiking/status")).json()
        assert set(st) == {"live", "session", "next_session", "day_live", "decisions", "stream", "learning", "last", "spend"} and st["live"] is False
        assert st["day_live"] is None and st["decisions"]["live_ready"] is False
        assert st["session"] is None and st["next_session"] is None
        assert set(st["last"]) == {"exam", "memory_test", "pong_curve", "bench"} and set(st["last"].values()) == {None}
        assert st["spend"] == {"total_usd": 0.0, "hours": 0.0}
        exam = {"type": "result", "kind": "exam", "day": "2026-10-01", "rallies": 20, "hits": 9, "hit_rate": 0.45,
                "frozen": True, "controls": {"random": 0.2, "no_plasticity": 0.25}}
        assert (await client.post("/api/spiking/result", json=exam, headers=AUTH)).status == 200
        mt = {"kind": "memory_test", "day": "2026-10-01", "cues": ["a"], "recalled": [True], "scores": [0.8],
              "control_scores": [0.1]}
        assert (await client.post("/api/spiking/result", json=mt, headers=AUTH)).status == 200
        assert (await client.post("/api/spiking/result", json={"kind": "nonsense"}, headers=AUTH)).status == 400
        assert (await client.post("/api/spiking/result", data=b"{bad", headers=AUTH)).status == 400
        lines = (tmp_path / "spiking" / "exams.jsonl").read_text().splitlines()
        assert len(lines) == 1 and json.loads(lines[0])["hits"] == 9 and "received" in json.loads(lines[0])
        assert json.loads((tmp_path / "spiking" / "memory_test_runs.jsonl").read_text())["scores"] == [0.8]
        assert not (tmp_path / "spiking" / "memory_tests.jsonl").exists()      # no per-item rows in that record
        last = json.loads((tmp_path / "spiking" / "last.json").read_text())
        assert set(last) == {"exam", "memory_test"}
        st = await (await client.get("/api/spiking/status")).json()
        assert st["last"]["exam"]["hit_rate"] == 0.45 and st["last"]["memory_test"]["cues"] == ["a"]
    run(with_client(tmp_path, go))
    # last.json survives a restart
    hub2 = spiking_server.SpikingHub(FakeLive(), tmp_path, secret="x")
    assert hub2.last["exam"]["hits"] == 9


def test_server_status_merges_manager(tmp_path):
    async def go(client, hub, live):
        mgr = PodManager(tmp_path, "https://s", "x", api=FakeApi(), schedule=Schedule.parse("21:00-23:00"), env={})
        hub.manager = mgr
        st = await (await client.get("/api/spiking/status")).json()
        assert st["live"] is False and st["next_session"] and "T" in st["next_session"]
        assert st["spend"]["hours"] == 0.0
    run(with_client(tmp_path, go))


def test_server_pod_websocket_flow(tmp_path):
    async def go(client, hub, live):
        t = [100.0]
        hub.clock = lambda: t[0]
        events = []

        class Mgr:
            def on_hello(self, d): events.append("hello")
            def on_state(self, d): events.append("state")
            def on_done(self, d): events.append("done")
            def on_disconnect(self): events.append("disconnect")
            def status(self): return {}
        hub.manager = Mgr()
        assert hub.forward_chat("hi", "neutral") is False and hub.forward_good() is False       # no pod: no-op
        hub.forward_sleep("NREM")
        ws = await client.ws_connect("/api/spiking/pod?session=s1", headers=AUTH)
        assert await until(lambda: hub.connected)
        assert (await ws.receive_json()) == {"type": "sleep", "stage": "NREM"}                  # stage on connect
        await ws.send_json({"type": "hello", "session": "s1", "n_neurons": 1000, "device": "cuda", "phases": []})
        assert await until(lambda: hub.session is not None)
        st = await (await client.get("/api/spiking/status")).json()
        assert st["session"]["session_id"] == "s1" and st["session"]["n_neurons"] == 1000
        # state frames relayed to the page, at most 4 per second
        for i in range(3):
            await ws.send_json({"type": "state", "t_sim": float(i), "phase": "pong_train", "n_neurons": 1000})
        assert await until(lambda: events.count("state") == 3)
        relayed = [m for m in live.sent if m.get("type") == "spiking"]
        assert len(relayed) == 1 and relayed[0]["phase"] == "pong_train" and relayed[0]["t_sim"] == 0.0
        t[0] += 0.3
        await ws.send_json({"type": "state", "t_sim": 9.0, "phase": "sleep"})
        assert await until(lambda: len([m for m in live.sent if m.get("type") == "spiking"]) == 2)
        assert [m for m in live.sent if m.get("type") == "spiking"][-1]["t_sim"] == 9.0
        # results over the websocket are stored
        await ws.send_json({"type": "result", "kind": "bench", "steps_per_s": 900.0, "realtime_x": 0.9,
                            "n_neurons": 1000, "synapses": 5, "gpu": "A5000"})
        assert await until(lambda: (tmp_path / "spiking" / "bench.jsonl").exists())
        assert hub.last["bench"]["gpu"] == "A5000" and "type" not in hub.last["bench"]
        # forwards to the pod
        assert hub.forward_chat("hello there", "positive") is True
        assert await ws.receive_json() == {"type": "chat", "text": "hello there", "emotion": "positive"}
        assert hub.forward_good() is True and await ws.receive_json() == {"type": "good"}
        assert hub.forward_good() is False                                                      # 30 s rate limit
        t[0] += 31
        assert hub.forward_good() is True and await ws.receive_json() == {"type": "good"}
        assert hub.forward_sleep("REM") and await ws.receive_json() == {"type": "sleep", "stage": "REM"}
        assert hub.forward_sleep("REM") is False                                                # unchanged: not resent
        await hub.forward_stop()
        assert await ws.receive_json() == {"type": "stop"}
        await ws.send_str("not json")
        await ws.send_json({"type": "done", "ok": True, "error": None})
        assert await until(lambda: "done" in events)
        assert any(m.get("done") for m in live.sent)
        await ws.close()
        assert await until(lambda: "disconnect" in events and not hub.connected)
        assert live.sent[-1] == {"type": "spiking", "live": False} and hub.session is None
        assert events[0] == "hello"
    run(with_client(tmp_path, go))


def test_server_ws_message_cap_and_replace(tmp_path):
    async def go(client, hub, live):
        ws1 = await client.ws_connect("/api/spiking/pod", headers=AUTH)
        assert await until(lambda: hub.connected)
        ws2 = await client.ws_connect("/api/spiking/pod", headers=AUTH)                        # newer connection wins
        msg = await ws1.receive()
        assert msg.type.name in ("CLOSE", "CLOSING", "CLOSED")
        assert await until(lambda: hub.ws is not None and not hub.ws.closed)
        await ws2.send_str("x" * (2 * 1024 * 1024))                                            # over 1 MB: closed
        msg = await ws2.receive()
        assert msg.type.name in ("CLOSE", "CLOSING", "CLOSED")
        assert await until(lambda: not hub.connected)
    run(with_client(tmp_path, go))


def test_password_gate_lets_pod_paths_through(tmp_path):
    import live_server
    token = hashlib.sha256(b"sub01:pw").hexdigest()
    assert live_server.spiking_server is spiking_server and spiking_server.POD_PATHS == (
        "/api/spiking/pod", "/api/spiking/weights", "/api/spiking/result")

    async def go(client, hub, live):
        assert (await client.get("/api/spiking/status")).status == 401                        # gated
        assert (await client.get("/api/spiking/status", headers={"Cookie": "sub01=wrong"})).status == 401
        assert (await client.get("/api/spiking/status", headers={"Cookie": f"sub01={token}"})).status == 200
        # pod routes reach their handlers (which do the secret check) without a cookie
        assert (await client.get("/api/spiking/weights", headers=AUTH)).status == 404
        assert (await client.get("/api/spiking/weights")).status == 401
        assert (await client.post("/api/spiking/result", json={"kind": "bench", "gpu": "x"}, headers=AUTH)).status == 200
        ws = await client.ws_connect("/api/spiking/pod", headers=AUTH)
        assert await until(lambda: hub.connected)
        await ws.close()
        other = await client.get("/api/frames")
        assert other.status == 401                                                            # everything else stays gated
    run(with_client(tmp_path, go, middlewares=[live_server.password_gate("pw")]))


def test_live_server_forwarding_hooks(tmp_path):
    import live_server
    sent = []

    class Hub:
        def forward_chat(self, text, emotion): sent.append(("chat", text, emotion))
        def forward_good(self): sent.append(("good",))
        def forward_sleep(self, stage): sent.append(("sleep", stage))
    assert live_server.GOOD.search("Good!") and live_server.GOOD.search("that was good") and not live_server.GOOD.search("goodness")

    class WS:
        async def send_json(self, m): pass
    live = live_server.Live("m", True, data_dir=tmp_path)
    live.spiking = Hub()
    run(live.handle_chat(WS(), "k1", "good!"))
    assert ("chat", "good!", sent[0][2]) == sent[0] and ("good",) in sent
    sent.clear()
    run(live.handle_chat(WS(), "k2", "the lake was calm today"))
    assert sent and sent[0][0] == "chat" and ("good",) not in sent
    sent.clear()
    live.sleep_tick()
    assert sent == [("sleep", live.engine.stage)]


# --- validate ------------------------------------------------------------------------
def test_validate_gpu_with_fake_pod(tmp_path, monkeypatch):
    from spiking import validate

    polls = [0]
    files = {"results.json": json.dumps({"files": ["curve.png", "../evil.png", "notes.json", "x.exe"]}).encode(),
             "session.log": b"log", "curve.png": b"PNG", "notes.json": b"{}", "../evil.png": b"bad"}

    puts = []

    def opener(req, timeout=0):
        name = req.full_url.split("proxy.runpod.net/")[1]
        if req.get_method() == "PUT":
            puts.append((name, req.data, req.get_header("X-upload-token")))
            return Resp(b"ok")
        if name == "status.json":
            polls[0] += 1
            if polls[0] == 1:
                raise OSError("booting")
            return Resp(json.dumps({"phase": "pong_train", "progress": 0.5, "t_sim": 3.0,
                                    "done": polls[0] >= 3, "error": None}).encode())
        return Resp(files[name])
    monkeypatch.setattr(validate.podpack, "pack_bytes", lambda **kw: b"tar-bytes")
    ops, api, log = make_ops(tmp_path / "ops", opener=opener)
    lines = []
    args = validate.argparse.Namespace(gpu=True, minutes=50, n=1000000, phases=None, pong_minutes=10,
                                       module="spiking.session")
    code = validate.run_gpu(args, ops=ops, out_dir=tmp_path / "gpu", interval=0, say=lines.append)
    assert code == 0 and [p["name"] for p in api.pods] == ["BRAIN"]
    assert sorted(p.name for p in (tmp_path / "gpu").iterdir()) == ["curve.png", "notes.json", "results.json", "session.log"]
    post = [c[2] for c in api.calls if c[0] == "POST"][0]
    cfg = json.loads(post["env"]["SUB01_SESSION"])
    assert cfg["validate"] is True and cfg["n_neurons"] == 1000000 and post["name"].startswith("sub01-spiking-validate-")
    assert any("no pods of ours remain" in x for x in lines) and any("total spend" in x for x in lines)
    assert ("DELETE", "/pods/brain1") not in api.mutating()
    assert post["dockerStartCmd"] == podpack.boot_cmd() and "SUB01_BOOT" in post["env"]
    assert puts == [("upload", b"tar-bytes", post["env"]["SUB01_UPLOAD_TOKEN"])] and "SUB01_PACK_0" not in post["env"]


def test_validate_gpu_deletes_when_polling_fails(tmp_path, monkeypatch):
    from spiking import validate
    monkeypatch.setattr(validate.podpack, "pack_bytes", lambda **kw: b"tar-bytes")
    ops, api, log = make_ops(tmp_path / "ops", opener=lambda req, timeout=0: (_ for _ in ()).throw(OSError("down")))
    t = [0.0]
    ops.clock = lambda: t[0]
    ops.sleep = lambda s: t.__setitem__(0, t[0] + max(s, 60))                    # time passes while polling
    args = validate.argparse.Namespace(gpu=True, minutes=10, n=1000, phases="load", pong_minutes=1, module="m")
    lines = []
    code = validate.run_gpu(args, ops=ops, out_dir=tmp_path / "gpu", interval=20, say=lines.append)
    assert code == 1 and [p["name"] for p in api.pods] == ["BRAIN"] and any("aborted" in x for x in lines)
    assert reasons(log) and log.open_pods() == []


def test_validate_write_report_hook_skips_when_missing(tmp_path):
    from spiking import validate
    lines = []
    if not (ROOT / "spiking" / "report.py").exists():
        assert validate.write_report(tmp_path, tmp_path, say=lines.append) is None and lines


# --- the bootstrap, for real ---------------------------------------------------------
def http_call(port, method, path, data=None, token=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method,
                                 headers={"X-Upload-Token": token} if token is not None else {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_boot_py_subprocess_end_to_end(tmp_path):
    out, app = tmp_path / "out", tmp_path / "app"
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
    token = "k" * 48
    pack = podpack._tar_xz({"dummymod.py": (
        b"import json, os, time\n"
        b"out = os.environ['SUB01_OUT_DIR']\n"
        b"json.dump({'phase': 'run', 'done': False, 'error': None}, open(out + '/status.json.tmp', 'w'))\n"
        b"os.replace(out + '/status.json.tmp', out + '/status.json')\n"     # atomic, as boot.py: never read half-written
        b"time.sleep(0.2)\n"
        b"json.dump({'phase': 'end', 'done': True, 'error': None}, open(out + '/status.json.tmp', 'w'))\n"
        b"os.replace(out + '/status.json.tmp', out + '/status.json')\n")})
    env = dict(os.environ, SUB01_OUT_DIR=str(out), SUB01_APP_DIR=str(app), SUB01_BOOT_PORT=str(port),
               SUB01_UPLOAD_TOKEN=token, SUB01_MODULE="dummymod")
    boot = tmp_path / "boot.py"
    boot.write_text(podpack.BOOT_PY)
    proc = subprocess.Popen([sys.executable, str(boot)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        def wait(cond, secs=20):
            end = time.monotonic() + secs
            while time.monotonic() < end:
                try:
                    if cond():
                        return True
                except OSError:
                    pass
                time.sleep(0.05)
            return False
        assert wait(lambda: http_call(port, "GET", "/status.json")[0] == 200)
        assert json.loads(http_call(port, "GET", "/status.json")[1])["phase"] == "waiting_upload"
        assert http_call(port, "PUT", "/upload", pack, "wrong-token")[0] == 403
        assert http_call(port, "PUT", "/upload", pack)[0] == 403                              # no token
        assert http_call(port, "PUT", "/elsewhere", pack, token)[0] == 403
        assert http_call(port, "PUT", "/upload", b"", token)[0] == 403                        # empty body
        assert http_call(port, "PUT", "/upload", b"not an archive", token)[0] == 400          # bad pack: not consumed
        code, body = http_call(port, "PUT", "/upload", pack, token)
        assert code == 200 and body == b"ok"
        assert http_call(port, "PUT", "/upload", pack, token)[0] == 403                       # one upload only
        assert wait(lambda: json.loads(http_call(port, "GET", "/status.json")[1]).get("done") is True)
        assert json.loads(http_call(port, "GET", "/status.json")[1])["phase"] == "end"
        assert wait(lambda: (out / "exit_code").read_text() == "0")      # OSError until it exists; never seen empty
        assert (app / "dummymod.py").exists() and (out / "session.log").exists()
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_manager_choice_phases_are_opt_in(tmp_path):
    """SUB01_CHOICE=1 adds choice_train / choice_exam after encode (after Pong when both are on); off by default."""
    order = lambda env: make_mgr(tmp_path, tk(1, 21), env=env)[0].session_config(tk(1, 21), 60, tk(1, 21))["phases"]
    assert not {"choice_train", "choice_exam"} & set(order({}))
    ph = order({"SUB01_CHOICE": "1"})
    assert ph[ph.index("encode") + 1:ph.index("encode") + 3] == ["choice_train", "choice_exam"]
    ph = order({"SUB01_CHOICE": "1", "SUB01_PONG": "1"})
    assert ph[ph.index("encode") + 1:ph.index("encode") + 5] == ["pong_train", "pong_exam", "choice_train", "choice_exam"]
