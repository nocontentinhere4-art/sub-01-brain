"""End to end: a real Session (20k neurons, CPU) streams to a real aiohttp app running spiking.server.

No RunPod, no network beyond 127.0.0.1. The session runs in a daemon thread; everything is bounded by timeouts.
Run: python -m pytest tests/test_spiking_stream.py -q
"""
import asyncio
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiohttp import web

torch = pytest.importorskip("torch")

from spiking import frames as spiking_frames
from spiking import server as spiking_server
from spiking.session import Link, Session

TOTAL_S = 220


class FakeLive:
    def __init__(self):
        self.sent, self.spiking = [], None

    async def broadcast(self, msg):
        self.sent.append(msg)


class Mgr:
    """Records the hooks the hub calls on a pod manager."""

    def __init__(self):
        self.events = []

    def on_hello(self, d): self.events.append(("hello", d))
    def on_state(self, d): self.events.append(("state", d.get("phase")))
    def on_done(self, d): self.events.append(("done", d))
    def on_disconnect(self): self.events.append(("disconnect", None))
    def status(self): return {}


async def until(cond, secs):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if cond():
            return True
        await asyncio.sleep(0.1)
    return False


def test_session_streams_to_server(tmp_path, monkeypatch):
    monkeypatch.setenv("SUB01_POD_SECRET", "stream-secret")
    prev_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    data, out = tmp_path / "data", tmp_path / "out"
    cfg = {"n_neurons": 20000, "device": "cpu", "seed": 1, "day": "2026-10-01", "max_minutes": 10,
           "phases": ["bench", "encode", "free"], "bench_ms": 300,
           "messages": [{"text": "warm bread in the morning"}], "validate": False}

    async def main():
        live = FakeLive()
        app = web.Application()
        hub = spiking_server.attach(app, live, data)
        mgr = hub.manager = Mgr()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        assert not (data / "spiking" / "weights.npz").exists()                    # no seeded weights: GET -> 404
        link = Link(f"http://127.0.0.1:{port}", "stream-secret", "test-sess")
        sess = Session(cfg, out, link)
        box = {}
        th = threading.Thread(target=lambda: box.update(res=sess.run()), daemon=True)
        th.start()
        spk = lambda: [m for m in live.sent if m.get("type") == "spiking" and "groups" in m]
        try:
            assert await until(lambda: any(e[0] == "hello" for e in mgr.events), 150), "no hello"
            assert await until(lambda: len(spk()) >= 3, 60), "fewer than 3 state frames"
            assert await until(lambda: "bench" in hub.last and "encode" in hub.last, 90), "results missing"
            assert hub.forward_chat("hello sun", "positive") is True
            assert hub.forward_good() is True
            await asyncio.sleep(1.0)                                              # let the pod's hook read them
            await hub.forward_stop()
            assert await until(lambda: not th.is_alive(), 60), "session did not stop"
            assert await until(lambda: any(e[0] == "done" for e in mgr.events), 20), "no done frame"
        finally:
            sess.deadline = 0                                                     # never leave the thread running
            link.stop.set()
        th.join(10)
        link.thread.join(20)
        assert not link.thread.is_alive()
        await runner.cleanup()
        return live, hub, mgr, box["res"], spk()

    try:
        live, hub, mgr, res, frames = asyncio.run(asyncio.wait_for(main(), TOTAL_S))
    finally:
        torch.set_num_threads(prev_threads)
    hello = [d for k, d in mgr.events if k == "hello"][0]
    assert hello["type"] == "hello" and hello["session"] == "test-sess" and hello["n_neurons"] == 20000
    f = frames[0]                                       # what the pages get: the compact form (#62, frames.py)
    assert f["n_neurons"] == 20000 and f["phase"] and f["net"] == "gpu" and "spikes" not in f["raster"]
    assert {"visual", "somatomotor", "memory"} <= set(f["groups"]) and "t_sim" in f and "dopamine" in f
    assert {"spikes_per_s", "mean_rate_hz", "realtime_x"} <= set(f)
    n3 = f["n3"]                                        # per-region rates from the session (rq) and packed spikes
    rates = spiking_frames.dequantise_rates(n3["rq"])
    assert len(rates) == 214 and (rates > 0).mean() > 0.5 and rates.max() < 100
    sp = spiking_frames.unpack_spikes(n3["sq"], n3["span"])
    assert len(sp) and (sp[:, 0] < 200).all()            # the 200-row raster: one neuron a region
    assert {m["phase"] for m in frames} & {"bench", "encode", "free"}
    sdir = data / "spiking"
    assert (sdir / "bench.jsonl").exists() and (sdir / "encodes.jsonl").exists()
    assert hub.last["bench"]["n_neurons"] == 20000 and hub.last["encode"]["stored"]
    assert (sdir / "weights.npz").exists() and len(np.load(sdir / "weights.npz").files) > 0
    assert res["weights"]["upload_status"] == 200
    done = [d for k, d in mgr.events if k == "done"][0]
    assert done["ok"] is True and done["error"] is None                           # a stop is a clean end
    assert res["error"] is None and res.get("stopped") == "stop requested"
    assert any(m.get("done") and m.get("ok") for m in live.sent)
