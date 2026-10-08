"""His active neurons inside the 3D brain (#62): the compact spiking frames (spiking/frames.py), what each viewer gets
of them (<= ~3 KB/s, measured on a real /ws socket as tests/load_ws.py does), the offline state, and the page's
wording. No torch needed: the networks here are the numpy CPU network (spiking/live.py)."""
import asyncio
import base64
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from live_server import Feed, Live  # noqa: E402
from spiking import frames as F  # noqa: E402
from spiking import live as L  # noqa: E402
from spiking import server as S  # noqa: E402
from spiking.config import Config  # noqa: E402

SMALL = 5000
CAPTION = ("Simulated spiking neurons (1M on GPU / 20k on CPU) inside the real wiring of one person's brain; each drawn "
           "cell stands for a sampled model neuron; a model, not a mind.")
OFFLINE = "neurons offline — the 1M network runs while he is awake when the GPU is on"


# --- quantise / dequantise ---------------------------------------------------------------------------------------
def test_rates_round_trip_within_one_step():
    rates = np.concatenate([np.geomspace(F.RATE_LO, F.RATE_HI, 200), [0.0, 0.05, 150.0, 7.3, 12.0, 0.1, 99.9, 1.0,
                                                                         3.0, 40.0, 0.5, 2.0, 5.0, 8.0]])
    assert len(rates) == 214
    text = F.quantise_rates(rates)
    assert len(text) == 288 and len(base64.b64decode(text)) == 214              # one byte a region
    back = F.dequantise_rates(text)
    on = (rates >= F.RATE_LO) & (rates <= F.RATE_HI)
    step = (F.RATE_HI / F.RATE_LO) ** (1 / 254)                                   # ~2.8 % per byte
    assert np.all(np.abs(np.log(back[on] / rates[on])) <= np.log(step) / 2 + 1e-9)
    assert back[rates < F.RATE_LO].max() == 0.0                                   # below the floor: 0, not invented
    assert back[rates > F.RATE_HI].min() == pytest.approx(F.RATE_HI)              # clipped at the top
    assert F.quantise_rates(F.dequantise_rates(text)) == text                     # stable
    assert F.dequantise_rates(F.quantise_rates([np.nan, np.inf, -1.0])).tolist() == [0.0, F.RATE_HI, 0.0]


def test_spikes_round_trip_region_slot_and_time():
    off, size = np.array([0, 10, 30]), np.array([10, 20, 300])
    sample = F.Sample.from_ids([3, 10, 29, 30, 329], off, size)
    assert sample.region.tolist() == [0, 1, 1, 2, 2] and sample.slot.tolist() == [76, 0, 243, 0, 255]
    spikes = [[0, 0], [199, 4], [100, 2], [57, 3], [57, 9], [-1, 1], [5, -2]]       # rows 9, -2: not in the sample
    text, n = F.pack_spikes(spikes, 200, sample)
    got = F.unpack_spikes(text, 200)
    assert n == 5 and len(got) == 5                                               # the rows 9 and -2 dropped
    assert sorted(map(tuple, got[:, :2].astype(int).tolist())) == sorted([(0, 76), (2, 255), (1, 243), (2, 0), (1, 0)])
    times = dict(((int(r), int(s)), t) for r, s, t in got)
    assert abs(times[(2, 255)] - 199) <= 1 and abs(times[(1, 243)] - 100) <= 1 and times[(0, 76)] == 0
    assert list(got[:, 2]) == sorted(got[:, 2])                                   # sorted by time


def test_pack_caps_with_a_uniform_sample():
    sample = F.Sample(np.arange(214) % 214, np.zeros(214))
    rng = np.random.default_rng(1)
    spikes = np.stack([rng.integers(0, 250, 5000), rng.integers(0, 214, 5000)], 1)
    text, n = F.pack_spikes(spikes, 250, sample)
    got = F.unpack_spikes(text, 250)
    assert n == 5000 and len(got) == F.SPIKE_CAP == 400                           # at most 400 a frame
    assert got[:, 2].mean() == pytest.approx(125, abs=15)                         # spread over the frame, not its start
    assert F.thin_spikes(text, 50) and len(base64.b64decode(F.thin_spikes(text, 50))) == 150
    assert F.thin_spikes(text, 0) == "" and F.thin_spikes(text, 999) == text


def test_gpu_sample_matches_the_network_layout():
    """The hub rebuilds which region and slot each of the GPU raster's rows is; net.py and live.py draw the raster's
    neurons the same way (one per region, seed 0), so the numpy network checks the rebuild."""
    net = L.LiveNet(Config(n_neurons=SMALL))
    net.enable_raster(200)
    want = F.Sample.from_ids(net.raster_ids, net.off, net.size)
    got = F.gpu_sample(SMALL)
    assert got.region.tolist() == list(range(200)) == want.region.tolist()       # row r is region r
    assert got.slot.tolist() == want.slot.tolist()
    fb = F.Sample.one_per_region(200, 214)
    assert fb.region.tolist() == list(range(200)) and set(fb.slot.tolist()) == {128}


def test_points_json_is_the_20k_layout():
    meta = json.loads((ROOT / "web" / "neurons3d.json").read_text())
    assert meta == json.loads(json.dumps(F.points_meta()))
    assert len(meta["sizes"]) == 214 and sum(meta["sizes"]) == 20_000              # <= 20k points
    net = SimpleNamespace(cfg=Config(n_neurons=20_000), reg=None)
    from spiking.regions import Regions
    from spiking.wiring import Layout
    net.reg = Regions()
    Layout._layout(net)
    assert meta["sizes"] == net.size.tolist()


# --- real frames of the CPU network --------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def cpu_frames():
    brain = L.LiveBrain(SMALL, twin=False, log=lambda *a: None)
    out = []
    brain.emit = out.append
    brain.idle(50)
    for i in range(6):
        brain.decide([f"page {i} about bread", "tokyo parks at night", "a video about trains"], did=f"d{i}")
    return out


def gpu_frames(n=40, chunk=250):
    """Frames shaped like the GPU session's `state` (spiking/session.py frame()): a 200-row raster sample as [[ms, row]],
    groups, rates; the activity is the numpy network's (a recorded stream for tests; never served as live)."""
    net = L.LiveNet(Config(n_neurons=SMALL))
    net.enable_raster(200)
    net.drive()
    out = []
    for i in range(n):
        t0, c0 = net.t, net.count.copy()
        net.raster = []
        net.run(chunk)
        spikes = [[int(t - t0), int(r)] for t, rows in net.raster for r in rows.tolist()][:4000]
        d = (net.count - c0).sum()
        out.append({"type": "state", "t_sim": round(net.t / 1000, 2), "phase": "live_decide", "n_neurons": net.n,
                    "spikes_per_s": round(d / (chunk / 1000), 1), "mean_rate_hz": round(d / (chunk / 1000) / net.n, 3),
                    "steps_per_s": 4000.0, "realtime_x": 1.0, "groups": {g: 5.0 + k for k, g in enumerate(L.GROUP_KEYS)},
                    "raster": {"n": 200, "t0": t0, "t1": net.t, "spikes": spikes}, "pong": None, "choice": None,
                    "dopamine": 0.0})
    return out


def test_cpu_frames_are_compact_and_honest(cpu_frames):
    dec = [f for f in cpu_frames if f["phase"] == "deciding"]
    assert dec and all(f["net"] == "cpu" and f["n3"]["race"] for f in dec)
    assert all(not f["n3"]["race"] for f in cpu_frames if f["phase"] == "idle")
    for f in cpu_frames:
        n3 = f["n3"]
        assert "spikes" not in f["raster"] and len(n3["rq"]) == 288
        sp = F.unpack_spikes(n3["sq"], n3["span"])
        assert len(sp) <= F.SPIKE_CAP and len(sp) <= n3["ns"]                      # a sample of recorded spikes
        assert (sp[:, 0] < 214).all() and (sp[:, 2] <= n3["span"]).all()
        rates = F.dequantise_rates(n3["rq"])
        assert rates.max() < 100 and (rates > 0).mean() > 0.5                       # measured, plausible rates
        assert len(json.dumps(f)) < 3000                                           # was 4-12 KB with the spike list


def test_frames_without_a_raster_pass_unchanged():
    f = {"type": "spiking", "live": False}
    assert F.viewer_frame(f, F.Sample.one_per_region(200, 214)) == f
    assert F.Budget().fit(f) == f


# --- per viewer: the budget, measured on a real /ws socket ----------------------------------------------------------
def bare_live():
    """A Live with only its websocket parts (as tests/test_feed.py)."""
    live = Live.__new__(Live)
    live.init_sockets()
    live.max_ws, live.max_ws_ip, live.trust_proxy = 400, 4, False
    live.memory = SimpleNamespace(chat=lambda: [])
    live.nights = lambda: {"type": "nights", "last": None, "tonight": None}
    live.last_frame = None
    return live


async def _until(cond, timeout=10.0):
    t0 = asyncio.get_running_loop().time()
    while not cond():
        assert asyncio.get_running_loop().time() - t0 < timeout
        await asyncio.sleep(0.01)


def test_stream_per_viewer_under_3_kb_s(tmp_path, cpu_frames):
    """60 simulated seconds: 30 s of the CPU network deciding nonstop at 5 frames/s (worse than real: it decides for
    ~0.3 s a page), then 30 s of the GPU network streaming 4000-spike frames, which the hub relays at 4/s while the
    CPU network keeps pulsing. Bytes counted as tests/load_ws.py does: the JSON each viewer receives."""
    gpu = gpu_frames(12)

    async def main():
        live = bare_live()
        app = web.Application()
        app.router.add_get("/ws", live.ws_handler)
        hub = S.attach(app, live, tmp_path, secret="s3cret")
        clock = [1000.0]
        hub.clock = lambda: clock[0]
        async with TestClient(TestServer(app)) as client:
            got = {"brain": [], "life": [], "room": []}

            async def viewer(kind, path):
                ws = await client.ws_connect(path)
                async for m in ws:
                    d = json.loads(m.data)
                    if d.get("type") == "spiking":
                        got[kind].append(m.data)
            tasks = [asyncio.create_task(viewer("brain", "/ws?rate=10&q=1")), asyncio.create_task(viewer("life", "/ws")),
                     asyncio.create_task(viewer("room", "/ws?rate=5&lite=1"))]
            await _until(lambda: len(live.clients) == 3)
            dec = [f for f in cpu_frames if f["phase"] == "deciding"]
            for i in range(150):                                    # CPU: 5 frames/s for 30 s
                clock[0] += 0.2
                await hub.relay(dec[i % len(dec)])
            await _until(lambda: len(got["brain"]) == hub.budget.sent["frames"])
            cpu_bytes = sum(map(len, got["brain"]))
            n_cpu = len(got["brain"])
            pod = await client.ws_connect("/api/spiking/pod", headers={"Authorization": "Bearer s3cret"})
            await pod.send_json({"type": "hello", "session": "t", "n_neurons": SMALL, "device": "cpu", "phases": []})
            await _until(lambda: hub.session is not None)
            for i in range(240):                                    # GPU: 8 frames/s offered (relay keeps 4/s) for 30 s
                clock[0] += 0.125
                await pod.send_json(dict(gpu[i % len(gpu)], t_sim=float(i)))
                await _until(lambda: (hub.last_state or {}).get("t_sim") == float(i))   # handled at this clock
                if i % 10 == 5:                                     # the CPU network's idle pulse: dropped meanwhile
                    await hub.relay(dec[0])
            await _until(lambda: len(got["brain"]) == hub.budget.sent["frames"])
            gpu_part = got["brain"][n_cpu:]
            await pod.close()
            await _until(lambda: any('"live": false' in x for x in got["brain"]))
            for t in tasks:
                t.cancel()
            return got, cpu_bytes, n_cpu, gpu_part, hub
    got, cpu_bytes, n_cpu, gpu_part, hub = asyncio.run(main())
    cpu_bps = cpu_bytes / 30.0
    gpu_bps = sum(map(len, gpu_part)) / 30.0
    print(f"\nspiking stream per viewer: CPU deciding nonstop {cpu_bps:.0f} B/s ({n_cpu} frames, "
          f"{cpu_bytes / n_cpu:.0f} B each); GPU {gpu_bps:.0f} B/s ({len(gpu_part)} frames)")
    assert cpu_bps <= F.RATE_BPS + F.BURST_BYTES / 30 and gpu_bps <= F.RATE_BPS + F.BURST_BYTES / 30
    assert n_cpu == 150                                             # every CPU frame went out (thinned, not dropped)
    gpu_frames_out = [json.loads(x) for x in gpu_part if '"n3"' in x]
    assert 115 <= len(gpu_frames_out) <= 125                        # 4 a second
    assert all(f.get("net") == "gpu" for f in gpu_frames_out)       # the CPU pulses were held back
    assert hub.budget.sent["dropped"] >= 20
    full = [f for f in gpu_frames_out if "groups" in f]
    assert 25 <= len(full) <= 35                                    # the panel's numbers once a second
    assert all("spikes_per_s" not in f and "n" not in f["raster"] for f in gpu_frames_out if "groups" not in f)
    shown = [len(F.unpack_spikes(f["n3"]["sq"], f["n3"]["span"])) for f in gpu_frames_out]
    print(f"spikes shown a GPU frame: mean {np.mean(shown):.0f} (of {np.mean([f['n3']['ns'] for f in gpu_frames_out]):.0f} recorded)")
    assert np.mean(shown) >= 60                                     # spikes still flash
    assert got["life"] == got["brain"]                              # the life page's plain feed gets the same
    assert got["room"] == []                                        # the room's lite feed does not draw them


def test_lite_feed_drops_spiking_frames_only():
    f = Feed.from_query({"rate": "5", "lite": "1"})
    for m in ({"type": "spiking", "net": "cpu"}, {"type": "spiking", "live": False}):
        assert f.take(m, json.dumps(m)) is None
    m = {"type": "chat", "text": "hi"}
    assert f.take(m, json.dumps(m)) is not None
    q = Feed.from_query({"rate": "10", "q": "1"})
    m = {"type": "spiking", "net": "gpu"}
    data = json.dumps(m)
    assert q.take(m, data) is data


# --- offline -----------------------------------------------------------------------------------------------------
def test_offline_nothing_is_invented(tmp_path):
    """No live network: the hub sends nothing; a pod that leaves is announced as not live; the race flag is only set
    by a real pending decision."""
    async def main():
        class Sink:
            sent = []

            async def broadcast(self, m):
                self.sent.append(m)
        live = Sink()
        app = web.Application()
        hub = S.attach(app, live, tmp_path, secret="s")
        async with TestClient(TestServer(app)) as client:
            await asyncio.sleep(0.3)
            assert live.sent == [] and hub.budget.sent["frames"] == 0
            pod = await client.ws_connect("/api/spiking/pod", headers={"Authorization": "Bearer s"})
            await pod.send_json({"type": "hello", "session": "t", "n_neurons": SMALL, "phases": []})
            await pod.send_json(gpu_frames(1)[0])
            await _until(lambda: len(live.sent) == 1)
            assert live.sent[0]["n3"]["race"] is False and "rq" not in live.sent[0]["n3"]   # no rates: none invented
            await pod.close()
            await _until(lambda: len(live.sent) == 2)
            assert live.sent[1] == {"type": "spiking", "live": False}
    asyncio.run(main())


def test_race_is_flagged_while_a_gpu_decision_runs(tmp_path):
    async def main():
        class Sink:
            sent = []

            async def broadcast(self, m):
                self.sent.append(m)
        live = Sink()
        app = web.Application()
        hub = S.attach(app, live, tmp_path, secret="s")
        clock = [50.0]
        hub.clock = lambda: clock[0]
        async with TestClient(TestServer(app)) as client:
            pod = await client.ws_connect("/api/spiking/pod", headers={"Authorization": "Bearer s"})
            await pod.send_json({"type": "hello", "session": "t", "n_neurons": SMALL, "phases": []})
            await pod.send_json({"type": "live_ready", "n_neurons": SMALL})
            await _until(lambda: hub.live_ready)
            fr = gpu_frames(1)[0]
            task = asyncio.create_task(hub.decide(["a", "b"], deadline_ms=3000))
            msg = await pod.receive_json()
            assert msg["type"] == "decide"
            await pod.send_json(fr)
            await _until(lambda: len(live.sent) == 1)
            assert live.sent[0]["n3"]["race"] is True
            await pod.send_json({"type": "decision", "id": msg["id"], "pick": 1, "pool_rates": [1.0, 2.0]})
            assert (await task)["pick"] == 1
            clock[0] += S.RACE_SHOW_S + 0.5                       # the highlight fades after the decision
            await pod.send_json(fr)
            await _until(lambda: len(live.sent) == 2)
            assert live.sent[1]["n3"]["race"] is False
            await pod.close()
    asyncio.run(main())


# --- the pages ----------------------------------------------------------------------------------------------------
def test_brain_page_wording_and_toggle():
    html = (ROOT / "web" / "index.html").read_text()
    assert CAPTION in html and OFFLINE in html                     # word for word
    assert re.search(r'<button[^>]*data-l="fibres"[^>]*>fibres</button><button[^>]*data-l="cortex"[^>]*>cortex</button>'
                     r'<button data-l="regions">regions</button>.*<button data-l="neurons"[^>]*>neurons</button>', html)
    assert '<script src="/neurons3d.js"></script>' in html
    js = (ROOT / "web" / "neurons3d.js").read_text()
    assert "maxCells || 600" in js and "InstancedBufferGeometry" in js   # the forest (#88): instanced cells, capped
    for page in ("index.html", "neurons3d.js", "neurons.js"):
        text = (ROOT / "web" / page).read_text().lower()
        for word in ("conscious", "understands", "he feels", "alive"):
            assert word not in text, (page, word)


def test_neurons_assets_are_in_the_image():
    docker = (ROOT / "Dockerfile").read_text()
    assert "COPY spiking ./spiking" in docker and "COPY web ./web" in docker      # frames.py, neurons3d.* ship


def test_budget_survives_a_clock_set_back():
    t = [1e6]
    b = F.Budget(clock=lambda: t[0])
    t[0] = 10.0                                                    # e.g. the hub's clock replaced: no negative refill
    sample = F.Sample.one_per_region(200, 214)
    f = F.viewer_frame({"type": "spiking", "net": "gpu", "phase": "x", "raster": {"n": 200, "t0": 0, "t1": 250,
                        "spikes": [[i % 250, i % 200] for i in range(400)]}}, sample)
    out = b.fit(f)
    assert out["n3"]["sq"] and b.tokens >= 0


def test_caption_spike_clause_never_says_zero_of():
    """The live caption's spike clause (web/neurons3d.js spikeLine): a frame whose spikes the per-viewer budget left
    out says so plainly instead of "0 of N"; no recorded spikes, no clause. Runs the page's own function in node."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    js = (ROOT / "web" / "neurons3d.js").read_text() + """
const f = globalThis.Neurons3D.spikeLine;
console.log(JSON.stringify([f({recorded: 5668, shown: 0}), f({recorded: 23543, shown: 170}), f({recorded: 0, shown: 0}),
                            f(null), f({recorded: 12, shown: 12})]));"""
    out = json.loads(subprocess.run([node, "-e", js], capture_output=True, text=True, check=True).stdout)
    assert out[0] == "last frame: 5,668 spikes recorded, none sent (the stream's 3 KB/s budget was used up)"
    assert out[1] == "showing 170 of 23,543 recorded spikes in the last frame"
    assert out[2] == "" and out[3] == ""
    assert out[4] == "showing 12 of 12 recorded spikes in the last frame"
    assert not any(re.search(r"\b0 of\b", s) for s in out)
