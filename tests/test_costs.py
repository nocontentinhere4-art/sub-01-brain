"""#15: the cost ledger, the daily caps, /healthz and the admin APIs. Every provider is mocked: no paid call."""
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import costs
import diary as D
import eye as E
import eyes as EY
import live_server
import mind as M
from sleep import TZ

ROOT = Path(__file__).resolve().parents[1]


def at(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=TZ).timestamp()


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        for r in rows:
            f.write((r if isinstance(r, str) else json.dumps(r)) + "\n")


@pytest.fixture(autouse=True)
def default_caps(monkeypatch):
    for k in ("SUB01_CAP_EYE_USD", "SUB01_CAP_DIARY_USD", "SUB01_CAP_TOTAL_USD", "SUB01_ADMIN_TOKEN", "SITE_PASSWORD"):
        monkeypatch.delenv(k, raising=False)


# --- the ledger ---------------------------------------------------------------------------------------------------
def test_day_boundaries_follow_tokyo(tmp_path):
    """23:59 and 00:01 Tokyo are two days, whatever UTC says (00:01 Tokyo is 15:01 UTC the day before)."""
    clock = [at(2026, 10, 3, 0, 30)]
    led = costs.Ledger(tmp_path, clock=lambda: clock[0])
    write(led.path, [{"t": at(2026, 10, 2, 23, 59), "service": "eye", "model": "flux", "units": 1, "usd": 0.5},
                     {"t": at(2026, 10, 3, 0, 1), "service": "eye", "model": "flux", "units": 1, "usd": 0.25}])
    assert datetime.fromtimestamp(at(2026, 10, 3, 0, 1), timezone.utc).date().isoformat() == "2026-10-02"
    assert led.spent_today("eye") == pytest.approx(0.25)
    days = led.by_day(2)
    assert list(days) == ["2026-10-03", "2026-10-02"]
    assert days["2026-10-02"]["eye"] == pytest.approx(0.5)
    clock[0] = at(2026, 10, 4, 0, 0)                               # midnight Tokyo: a new day starts at zero
    assert led.spent_today() == 0.0


def test_every_source_counted_once(tmp_path):
    """eye/diary in costs.jsonl, eyes + mind in the shared eyes_costs.jsonl, RunPod in spiking/costs.jsonl."""
    now = at(2026, 10, 2, 12)
    led = costs.Ledger(tmp_path, clock=lambda: now)
    led.record("eye", "flux", 1, 0.003, "frame")
    led.record("diary", "llama", 900, 0.0001)
    shared = EY.Budget(tmp_path / "eyes_costs.jsonl", clock=lambda: now, max_usd_day=2.0)
    eyes, mind = M.Share(shared, "eyes", 1.0), M.Share(shared, "mind", 1.0)
    eyes.record("openrouter", "anthropic/claude-haiku-4.5", 0, 0, True, usd=0.01)
    mind.record("mind/openrouter", "anthropic/claude-haiku-4.5", 0, 0, True, usd=0.02)
    start = datetime.fromtimestamp(now - 1800, timezone.utc)
    write(tmp_path / "spiking" / "costs.jsonl", [
        {"pod_id": "p", "name": "x", "gpu": "A5000", "cost_per_hr": 0.4, "start": start.isoformat(),
         "stop": (start + timedelta(hours=0.5)).isoformat(), "hours": 0.5, "cost_usd": 0.2}])
    today = led.by_day(1)["2026-10-02"]
    assert today == pytest.approx({"eye": 0.003, "diary": 0.0001, "eyes": 0.01, "mind": 0.02, "runpod": 0.2})
    assert led.spent_today() == pytest.approx(0.2331)
    assert led.total_today() == pytest.approx(0.0331)            # RunPod keeps its own GPU-hour caps
    assert led.spent_today("eyes") == pytest.approx(0.01)        # read again: still once (incremental read)
    with pytest.raises(ValueError):
        led.record("eyes", "x", 0, 1.0)                           # eyes / mind rows only go to their own ledger


def test_incremental_read_and_torn_line(tmp_path):
    now = at(2026, 10, 2, 12)
    led = costs.Ledger(tmp_path, clock=lambda: now)
    write(led.path, [{"t": now, "service": "eye", "usd": 0.1}])
    assert led.spent_today("eye") == pytest.approx(0.1)
    with open(led.path, "a") as f:
        f.write('{"t": %r, "service": "eye", "usd": 0.2' % now)   # being written: no newline yet
    assert led.spent_today("eye") == pytest.approx(0.1)
    led.record("eye", "flux", 1, 0.3)                              # append_jsonl closes the torn line first
    assert led.spent_today("eye") == pytest.approx(0.4)
    led.path.write_text("")                                        # a file that shrank is read again
    assert led.spent_today("eye") == 0.0


def test_default_total_covers_every_part():
    c = costs.caps()
    assert c["eyes"] == 1.0 and c["mind"] == 1.0 and c["eye"] == 1.0
    assert c["total"] >= c["eye"] + c["eyes"] + c["mind"] + c["diary"]


def test_cap_env_names_set_the_existing_shares():
    """SUB01_CAP_EYES_USD is the eyes' share of the shared ledger (mind.EYES_USD_PER_DAY), read at import."""
    out = subprocess.run([sys.executable, "-c", "import mind; print(mind.EYES_USD_PER_DAY, mind.MIND_USD_PER_DAY)"],
                         cwd=ROOT, capture_output=True, text=True, check=True,
                         env=dict(os.environ, SUB01_CAP_EYES_USD="0.5", SUB01_CAP_MIND_USD="0.25"))
    assert out.stdout.split() == ["0.5", "0.25"]


# --- caps stop paid calls and fall back ---------------------------------------------------------------------------
class Calls:
    def __init__(self):
        self.n = 0


def mocked_eye(tmp_path, monkeypatch, calls):
    """An Eye on (mocked) Replicate: every provider call is counted, none leaves the process."""
    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-not-a-token")

    def fake_post(url, token, payload, **kw):
        calls.n += 1
        if "llama" in url:
            return {"output": ['{"new_objects": [], "scene": "a desk", "thought": "quiet"}'],
                    "metrics": {"input_token_count": 900, "output_token_count": 40}}
        raise AssertionError("images go through generate()")
    monkeypatch.setattr(E, "replicate_post", fake_post)

    def fake_generate(self, prompt, seed, w, h):
        from PIL import Image
        calls.n += 1
        return Image.new("RGB", (w, h))
    monkeypatch.setattr(E.ReplicateImages, "generate", fake_generate)
    eye = E.Eye(tmp_path / "frames", tmp_path / "world.json", width=64, height=36)
    eye.ledger = costs.Ledger(tmp_path)
    return eye


def test_eye_frames_are_logged(tmp_path, monkeypatch):
    calls = Calls()
    eye = mocked_eye(tmp_path, monkeypatch, calls)
    eye.step(time.time(), "AWAKE", {}, "calm", [], "12:00")
    assert calls.n == 2
    rows = [json.loads(x) for x in eye.ledger.path.read_text().splitlines()]
    assert [r["note"] for r in rows] == ["thought", "frame"]
    assert rows[0]["units"] == 940 and rows[1]["usd"] == costs.FLUX_SCHNELL_USD
    assert eye.ledger.spent_today("eye") == pytest.approx(costs.FLUX_SCHNELL_USD + costs.llm_usd(900, 40))


@pytest.mark.parametrize("cap", ["SUB01_CAP_EYE_USD", "SUB01_CAP_TOTAL_USD"])
def test_eye_cap_stops_paid_calls(tmp_path, monkeypatch, cap):
    monkeypatch.setenv(cap, "0")
    calls = Calls()
    eye = mocked_eye(tmp_path, monkeypatch, calls)
    with pytest.raises(costs.Capped):
        eye.step(time.time(), "AWAKE", {}, "calm", [], "12:00")
    assert calls.n == 0 and not list((tmp_path / "frames").glob("*.jpg"))


def test_eye_cap_reached_between_the_two_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("SUB01_CAP_EYE_USD", "0.00001")         # the LLM call itself crosses it
    calls = Calls()
    eye = mocked_eye(tmp_path, monkeypatch, calls)
    with pytest.raises(costs.Capped):
        eye.step(time.time(), "AWAKE", {}, "calm", [], "12:00")
    assert calls.n == 1                                          # no image after the cap


def test_diary_llm_is_capped_and_logged(tmp_path, monkeypatch):
    monkeypatch.setenv("SUB01_CAP_DIARY_USD", "0")
    asked = []

    class LLM:
        last_usage = None

        def ask(self, system, user):
            asked.append(user)
            return '{"title": "t", "text": "x"}'
    led = costs.Ledger(tmp_path)
    metered = costs.MeteredLLM(LLM(), led, "diary")
    with pytest.raises(costs.Capped):                            # diary.close catches it: template text
        metered.ask("s" * 400, "u" * 400)
    assert not asked
    monkeypatch.setenv("SUB01_CAP_DIARY_USD", "1")
    assert metered.ask("s" * 400, "u" * 400) and len(asked) == 1
    assert led.spent_today("diary") > 0


def test_total_cap_stops_the_eyes_and_the_mind(tmp_path, monkeypatch):
    now = at(2026, 10, 2, 12)
    led = costs.Ledger(tmp_path, clock=lambda: now)
    led.record("eye", "flux", 1, 0.5)
    monkeypatch.setenv("SUB01_CAP_TOTAL_USD", "0.5")
    shared = EY.Budget(tmp_path / "eyes_costs.jsonl", clock=lambda: now, max_usd_day=2.0)
    eyes_share, mind_share = M.Share(shared, "eyes", 1.0), M.Share(shared, "mind", 1.0)
    for s in (eyes_share, mind_share):
        s.total = led.total_why_not

    class Provider:
        name, model, n = "fake", "m", 0

        def ask(self, system, user):
            Provider.n += 1
            return "{}", 1, 1
    eyes = EY.Eyes(provider=Provider(), budget=eyes_share)
    page = {"url": "https://example.org/", "title": "Example", "text": "hello", "links": [
        {"id": "L1", "text": "a link", "href": "https://example.org/a", "area": 900}]}
    opts, meta = eyes.propose(page)
    assert Provider.n == 0 and "total" in meta["why_local"] and opts      # local options instead
    assert mind_share.over_day() and "total" in mind_share.why_not()
    monkeypatch.setenv("SUB01_CAP_TOTAL_USD", "3.10")
    assert eyes_share.why_not() is None and not mind_share.over_day()


# --- the server: run_eye with caps at 0, /healthz, the admin APIs ---------------------------------------------------
def make_live(tmp_path):
    live = live_server.Live("m", True, data_dir=tmp_path)
    live.sent = []

    async def broadcast(msg):
        live.sent.append(msg)
    live.broadcast = broadcast
    return live


def test_demo_eye_with_caps_at_zero_makes_no_paid_call(tmp_path, monkeypatch):
    """Acceptance: --demo --eye with caps at 0 makes no paid call (providers mocked; watched and unwatched)."""
    for k in ("SUB01_CAP_EYE_USD", "SUB01_CAP_DIARY_USD", "SUB01_CAP_TOTAL_USD"):
        monkeypatch.setenv(k, "0")
    calls = Calls()
    live = make_live(tmp_path)
    live.eye = mocked_eye(tmp_path, monkeypatch, calls)
    live.eye.ledger = live.ledger
    live.diary = D.Diary(tmp_path, tmp_path / "frames")
    live.last_frame = {"t": "11:58", "stage": "AWAKE", "img": "/eye/1.jpg", "thought": "quiet"}
    live.clients.add(object())                                   # someone is watching

    async def run():
        task = asyncio.create_task(live.run_eye())
        await asyncio.sleep(0.3)
        task.cancel()
    asyncio.run(run())
    assert calls.n == 0 and not live.ledger.path.exists()
    assert live.eye_resting and "eye" in live.eye_resting
    assert live.sent == [{"type": "eye", **live.last_frame, "resting": live_server.RESTING}]
    assert live.eye_frame()["resting"] == "resting its eyes"     # also what a new viewer gets in its hello


def test_tick_ring_and_healthz_stall(tmp_path):
    live = make_live(tmp_path)
    assert not live.healthy()                                    # before the first tick: 503 (a deploy not ready)

    async def run():
        task = asyncio.create_task(live.run_brain())
        await asyncio.sleep(0.4)
        task.cancel()
    asyncio.run(run())
    assert len(live.tick_s) >= 3 and live.tick_s.maxlen == 1200
    assert live.healthy()
    h = live.health()
    assert h["ok"] and h["tick_ms"]["p50"] > 0 and h["tick_ms"]["n"] == len(live.tick_s)
    assert h["rss_mb"] > 0 and h["websockets"] == 0 and h["chromium"] == {"on": False}
    assert set(h["spend_today"]) == set(costs.SERVICES)
    live.last_tick -= live_server.HEALTHY_S + 1                   # the loop stalled
    assert not live.healthy()


async def serve(live, tmp_path, password=None):
    mw = [live_server.password_gate(password)] if password else []
    app = web.Application(middlewares=mw)
    app[live_server.GATED] = bool(mw)
    live_server.add_ops_routes(app, live, tmp_path)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


def test_healthz_is_public_and_says_503_when_stalled(tmp_path):
    live = make_live(tmp_path)

    async def run():
        c = await serve(live, tmp_path, password="pw")
        try:
            r = await c.get("/healthz", allow_redirects=False)
            assert r.status == 503 and await r.text() == "stalled"
            live.last_tick = time.monotonic()
            r = await c.get("/healthz", allow_redirects=False)
            assert r.status == 200 and await r.text() == "ok"     # no cookie needed, no data in it
            live.last_tick = time.monotonic() - 6
            assert (await c.get("/healthz")).status == 503
        finally:
            await c.close()
    asyncio.run(run())


def test_api_costs_needs_the_token(tmp_path, monkeypatch):
    live = make_live(tmp_path)
    live.ledger.record("eye", "flux", 1, 0.003)

    async def run():
        c = await serve(live, tmp_path)                           # launch: no SITE_PASSWORD
        try:
            assert (await c.get("/api/costs")).status == 401      # no token configured: closed
            monkeypatch.setenv("SUB01_ADMIN_TOKEN", "s3cret-admin")
            assert (await c.get("/api/costs")).status == 401
            assert (await c.get("/api/costs", headers={"X-Admin-Token": "wrong"})).status == 401
            r = await c.get("/api/costs", headers={"X-Admin-Token": "s3cret-admin"})
            d = await r.json()
            assert r.status == 200 and d["today"]["eye"] == pytest.approx(0.003) and len(d["days"]) == 7
            assert d["caps"]["total"] == 3.10
            r = await c.get("/api/health", headers={"Authorization": "Bearer s3cret-admin"})
            assert r.status == 200 and "tick_ms" in await r.json()
            assert (await c.get("/api/health")).status == 401
        finally:
            await c.close()
        c = await serve(live, tmp_path, password="pw")            # preview: the gate's cookie, or the token
        try:
            assert (await c.get("/api/costs", allow_redirects=False)).status == 401
            assert (await c.get("/api/costs", headers={"X-Admin-Token": "s3cret-admin"})).status == 200
            await c.post("/login", data={"password": "pw"}, allow_redirects=False)
            assert (await c.get("/api/costs")).status == 200
        finally:
            await c.close()
    asyncio.run(run())


# --- the eye's cap paced over his waking day (live 2026-10-07/08: 0.80 of 1.00 spent by 11:00, capped all evening) ---
def _simulate_day(tmp_path, every_s=30, frame_usd=costs.FLUX_SCHNELL_USD + costs.llm_usd(900, 40)):
    """A frame (and its thought) every `every_s` seconds round the clock whenever the ledger allows one: the
    worst case (frames every 30 s, dreams at night too). -> (ledger, [(t, spent after)] of the frames made)."""
    now = [at(2026, 10, 8, 0, 0)]
    led = costs.Ledger(tmp_path, clock=lambda: now[0])
    made, end = [], at(2026, 10, 9, 0, 0) - 1
    while now[0] < end:
        if led.why_not("eye") is None:
            led.record("eye", "flux+llm", 1, frame_usd, "frame")
            made.append((now[0], led.spent_today("eye")))
        now[0] += every_s
    return led, made


def test_eye_spend_is_paced_over_his_waking_day(tmp_path):
    cap = costs.caps()["eye"]
    led, made = _simulate_day(tmp_path)
    spent = lambda h: max([s for t, s in made if t < at(2026, 10, 8, h)] or [0])
    assert spent(11) <= cap * 0.40                               # (live, unpaced: 0.80 by 11:00)
    assert spent(20) < cap                                       # not capped before the evening
    for h in (20, 21, 22, 23):                                   # he still sees in every evening hour
        assert any(at(2026, 10, 8, h) <= t < at(2026, 10, 8, h) + 3600 for t, _ in made), h
    assert made[-1][1] <= cap + 1e-9                             # and the day stays within the cap
    assert spent(8) <= cap * costs.EYE_PACE_SLACK + 0.01         # the night (dreams) gets the slack only


def test_eye_pacing_can_be_turned_off_and_leaves_the_other_caps_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("SUB01_EYE_PACE", "0")
    led, made = _simulate_day(tmp_path)
    capped_at = next(t for t, s in made if s >= costs.caps()["eye"] - 0.004)
    assert capped_at < at(2026, 10, 8, 12)                       # unpaced, the worst case hits the cap by noon
    monkeypatch.delenv("SUB01_EYE_PACE")
    led = costs.Ledger(tmp_path / "d", clock=lambda: at(2026, 10, 8, 9))
    assert led.pace_allowed("diary") == costs.caps()["diary"] and led.why_not("diary") is None


def test_the_night_keeps_enough_frames_for_the_dream_diary(tmp_path):
    """The diary is made of the night's frames (2026-10-05: 76, 2026-10-07: 71): before he wakes the slack must allow
    at least 75 of them, however fast the dreams ask (every 5 s here), and the day still ends within the cap."""
    led, made = _simulate_day(tmp_path, every_s=5)
    night = [t for t, _ in made if t < at(2026, 10, 8, 8)]
    assert len(night) >= 75
    assert made[-1][1] <= costs.caps()["eye"] + 1e-9
