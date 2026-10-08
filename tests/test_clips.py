"""#59: daily clips. Assembly from fixture frames (short and fast), the AI label and no finance words in every caption,
the admin page needs auth, 14-day retention, auto-post off without tokens and the posting calls against mocked APIs."""
import asyncio
import json
import os
import resource
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from aiohttp import web

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import clips  # noqa: E402
import costs  # noqa: E402
from sleep import TZ  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(not FFMPEG or not shutil.which("ffprobe"), reason="ffmpeg not installed")
NOON = datetime(2026, 10, 2, 12, 0, tzinfo=TZ).timestamp()


def fixture_jpg(path, color, size=(640, 360)):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", size, color)
    ImageDraw.Draw(im).rectangle((40, 40, size[0] - 40, size[1] - 40), outline=(255, 255, 255), width=6)
    im.save(path, quality=80)
    return path


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height,codec_type",
                          "-show_entries", "format=duration", "-of", "json", str(path)], capture_output=True,
                         text=True, check=True).stdout
    return json.loads(out)


class FakeDiary:
    def __init__(self, root):
        self.img = Path(root) / "diary" / "img"
        self.nights = {}

    def index(self, n=30):
        return [{"date": d, "closed": x["closed"], "frames": len(x["frames"])} for d, x in sorted(
            self.nights.items(), reverse=True)][:n]

    def load(self, date):
        return self.nights.get(date)


# --- captions and wording ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", clips.TYPES)
def test_caption_has_ai_label_and_no_finance(kind):
    text, tags = clips.post_caption(kind, "A blue train under the sea")
    assert clips.LABEL in text and len(text) <= 150
    assert not clips.FINANCE.search(text + " " + tags) and not clips.CLAIMS.search(text)
    assert "#AI" in tags.split()


def test_dream_caption_drops_unsafe_titles_and_stays_short():
    text, _ = clips.post_caption("dream", "Buy the coin before the pump")
    assert not clips.FINANCE.search(text) and clips.LABEL in text
    text, _ = clips.post_caption("dream", "x" * 400)
    assert len(text) <= 150 and clips.LABEL in text


def test_event_captions_drop_motives_finance_and_feelings():
    assert clips.event_caption("hungry: orders food on the phone") == "orders food on the phone"
    assert clips.event_caption("curious: sits at the computer to read; it is in today's plan") == \
        "sits at the computer to read"
    assert clips.event_caption("the market is moving: checks the chart") == ""
    assert clips.event_caption("feels good: goes out to the park") == "goes out to the park"
    assert clips.safe("he feels sad") == "" and clips.safe("see https://x.y") == "" and clips.safe("$SUB to the moon") == ""


# --- assembly --------------------------------------------------------------------------------------------------------
def make_day(tmp_path, maker, day="2026-10-01"):
    d = maker.day_dir(day)
    t0 = datetime.fromisoformat(day).replace(tzinfo=TZ).timestamp()
    for i, (h, what) in enumerate([(8, "wakes up"), (10.27, "orders food on the phone"),
                                   (14.57, "reads about Kichijoji"), (21, "sits down for a game of chess at the desk")]):
        maker.remember(day, {"kind": "event", "t": round(t0 + h * 3600), "text": what})
        fixture_jpg(d / f"shot-{int(h):02d}00.jpg", (30 + 50 * i, 60, 90))
    maker.remember(day, {"kind": "chess", "move": "Nf3", "color": "white", "plies": 9,
                         "fen": "rnbqkb1r/pppp1ppp/5n2/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3",
                         "options": [{"label": f"move {i}", "p": p, "chosen": i == 1}
                                     for i, p in enumerate((0.1, 0.5, 0.2, 0.15, 0.05))]})
    return d


@needs_ffmpeg
def test_render_day_clip_from_fixture_frames(tmp_path):
    maker = clips.ClipMaker(tmp_path, clock=lambda: NOON)
    make_day(tmp_path, maker)
    spec = maker.spec("day", "2026-10-01")
    for s in spec["slides"]:                                   # short and fast: 1/10 of the real durations
        s["seconds"] = s["seconds"] / 10
    t0 = time.monotonic()
    out = clips.render(spec, ffmpeg=FFMPEG)
    assert time.monotonic() - t0 < 60
    info = probe(out)
    v = info["streams"][0]
    assert (v["codec_name"], v["width"], v["height"]) == ("h264", 1080, 1920)
    assert all(s["codec_type"] == "video" for s in info["streams"])          # no audio
    assert 1.5 < float(info["format"]["duration"]) < 5
    assert not list(tmp_path.glob("clips/clip-*"))                         # temp frames cleaned up


def test_spec_lengths_are_15_to_40_seconds(tmp_path):
    maker = clips.ClipMaker(tmp_path, clock=lambda: NOON)
    make_day(tmp_path, maker)
    for kind in ("day", "choice"):
        spec = maker.spec(kind, "2026-10-01")
        total = sum(s["seconds"] for s in spec["slides"])
        assert 15 <= total <= 40, (kind, total)
        assert spec["slides"][-1]["kind"] == "end"


def test_every_frame_carries_the_label(tmp_path, monkeypatch):
    """The corner label is drawn by chrome(), which every frame kind goes through."""
    seen = []
    real = clips.chrome
    monkeypatch.setattr(clips, "chrome", lambda img, *a, **k: seen.append(1) or real(img, *a, **k))
    maker = clips.ClipMaker(tmp_path, clock=lambda: NOON)
    make_day(tmp_path, maker)
    slides = maker.spec("day", "2026-10-01")["slides"] + maker.spec("choice", "2026-10-01")["slides"]
    slides.append({"kind": "options", "page": "Kichijoji", "options": [{"label": "a", "p": 1, "chosen": True}]})
    for s in slides:
        clips.render_frame(s, "day")
    assert len(seen) == len(slides)


@needs_ffmpeg
def test_make_runs_a_niced_child_and_writes_meta(tmp_path):
    maker = clips.ClipMaker(tmp_path, clock=lambda: NOON)
    make_day(tmp_path, maker)
    real = maker.spec
    maker.spec = lambda *a, **k: (lambda s: dict(s, slides=[dict(x, seconds=0.3) for x in s["slides"]]))(real(*a, **k))
    meta = asyncio.run(maker.make("choice", "2026-10-01"))
    assert meta and (tmp_path / "clips" / "2026-10-01-choice.mp4").exists()
    assert clips.LABEL in meta["caption"] and meta["cpu_s"] is not None and meta["cpu_s"] < clips.CPU_S
    assert maker.state["made"]["2026-10-01-choice"]["ok"]


def test_child_is_niced_has_a_cpu_cap_and_no_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "secret")
    monkeypatch.setenv("TIKTOK_POST_TOKEN", "secret")
    maker = clips.ClipMaker(tmp_path, clock=lambda: NOON)
    probe_py = tmp_path / "probe.py"
    probe_py.write_text("import os, resource, json, sys\nprint(json.dumps({'nice': os.nice(0), "
                        "'env': sorted(k for k in os.environ if 'TOKEN' in k), "
                        "'cpu': resource.getrlimit(resource.RLIMIT_CPU)[0]}))\n")
    monkeypatch.setattr(clips, "__file__", str(probe_py))
    code, out = asyncio.run(maker.run_child([]))
    got = json.loads(out.strip().splitlines()[-1])
    assert code == 0 and got["nice"] >= clips.NICE and got["env"] == []
    # the render entry point sets its own CPU cap
    src = (ROOT / "clips.py").read_text()
    assert "resource.setrlimit(resource.RLIMIT_CPU, (CPU_S" in src


@needs_ffmpeg
def test_cpu_cap_stops_a_runaway_encode(tmp_path):
    """RLIMIT_CPU really ends ffmpeg: a 1-CPU-second budget on a long encode is killed, not finished."""
    out = tmp_path / "x.mp4"
    t0 = time.monotonic()
    p = subprocess.run([FFMPEG, "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i",
                        "testsrc2=size=1080x1920:rate=30:duration=600", "-c:v", "libx264", "-threads", "1", "-y",
                        str(out)], preexec_fn=clips._limit(1), timeout=60)
    assert p.returncode != 0 and time.monotonic() - t0 < 30


def test_dream_slides_from_the_diary(tmp_path):
    maker = clips.ClipMaker(tmp_path, clock=lambda: NOON)
    diary = FakeDiary(tmp_path)
    (diary.img / "2026-10-01").mkdir(parents=True)
    frames = []
    for i in range(4):
        fixture_jpg(diary.img / "2026-10-01" / f"f{i}.jpg", (20, 20 + 40 * i, 120))
        frames.append({"img": f"/diary-img/2026-10-01/f{i}.jpg"})
    diary.nights["2026-10-01"] = {"date": "2026-10-01", "closed": True, "frames": frames, "title": "Trains of glass",
                                  "text": "SUB-01 dreamt of glass trains. A bakery floated by. The price went up."}

    class Live:
        pass
    live = Live()
    live.diary = diary
    assert maker.due(live) == ("dream", "2026-10-01")
    spec = maker.spec("dream", "2026-10-01", live)
    caps = [s.get("caption", "") for s in spec["slides"]]
    assert caps[0] == "Trains of glass" and not any(clips.FINANCE.search(c) for c in caps)
    assert 15 <= sum(s["seconds"] for s in spec["slides"]) <= 40


def test_sampling_skips_the_chart_and_unsafe_choices(tmp_path):
    maker = clips.ClipMaker(tmp_path, clock=lambda: NOON)

    class Obj:
        pass
    live = Obj()
    live.life = Obj()
    live.life.activity = "chart"
    live.life.log = [{"t": NOON - 60, "what": "the market is moving: checks the chart"},
                     {"t": NOON - 30, "what": "hungry: orders food on the phone"}]
    live.reader = Obj()
    live.reader.log = [{"t": NOON - 20, "title": "Bitcoin"}, {"t": NOON - 10, "title": "Inokashira Park"}]
    live.clock = Obj()
    live.clock.now = lambda: NOON
    live.chess = None
    live.decision_log = [{"t": "11:59", "page": "Bread", "options": [{"label": "buy now", "p": 0.5, "chosen": True},
                                                                     {"label": "leave", "p": 0.5}]},
                         {"t": "12:00", "page": "Bread", "options": [{"label": "recipes", "p": 0.7, "chosen": True},
                                                                     {"label": "leave", "p": 0.3}]}]
    maker.sample(live)
    rows = [json.loads(x) for x in (tmp_path / "clips/days/2026-10-02/moments.jsonl").read_text().splitlines()]
    texts = [r.get("text") for r in rows if r["kind"] == "event"]
    assert texts == ["orders food on the phone", "reads about Inokashira Park"]
    assert [r["t"] for r in rows if r["kind"] == "choice"] == ["12:00"]
    maker.sample(live)                                         # the same moments are not written twice
    assert len((tmp_path / "clips/days/2026-10-02/moments.jsonl").read_text().splitlines()) == len(rows)
    asyncio.run(maker.shoot(live))                             # the chart is never photographed
    assert not list((tmp_path / "clips/days").rglob("shot-*.jpg"))


# --- retention -------------------------------------------------------------------------------------------------------
def test_retention_keeps_14_days(tmp_path):
    maker = clips.ClipMaker(tmp_path, clock=lambda: NOON)
    today = datetime.fromtimestamp(NOON, TZ).date()
    for back in (0, 13, 14, 15, 30):
        day = (today - timedelta(days=back)).isoformat()
        (maker.dir / f"{day}-day.mp4").write_bytes(b"x")
        (maker.dir / f"{day}-day.json").write_text("{}")
        maker.day_dir(day)
        maker.state.setdefault("made", {})[f"{day}-day"] = {"ok": True}
    maker.cleanup()
    left = sorted(p.name[:10] for p in maker.dir.glob("*.mp4"))
    keep = sorted((today - timedelta(days=b)).isoformat() for b in (0, 13))
    assert left == keep
    assert sorted(p.name for p in maker.days.iterdir()) == keep
    assert sorted(k[:10] for k in maker.state["made"]) == keep


# --- admin page ------------------------------------------------------------------------------------------------------
async def _serve(maker, is_admin):
    app = web.Application()
    clips.add_routes(app, maker, is_admin)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"


def test_admin_page_needs_auth(tmp_path, monkeypatch):
    import aiohttp
    monkeypatch.setenv("SUB01_ADMIN_TOKEN", "tok-123")
    maker = clips.ClipMaker(tmp_path, clock=lambda: NOON)
    (maker.dir / "2026-10-01-day.mp4").write_bytes(b"mp4")

    async def go():
        from live_server import admin_ok
        runner, base = await _serve(maker, admin_ok)
        try:
            async with aiohttp.ClientSession() as s:
                for path in ("/admin/clips", "/admin/clips/file/2026-10-01-day.mp4"):
                    async with s.get(base + path) as r:
                        assert r.status == 401 and "2026-10-01-day" not in await r.text()
                async with s.get(base + "/admin/clips", headers={"X-Admin-Token": "wrong"}) as r:
                    assert r.status == 401
                async with s.post(base + "/admin/clips/login", data={"token": "wrong"}) as r:
                    assert r.status == 401
                async with s.get(base + "/admin/clips", headers={"X-Admin-Token": "tok-123"}) as r:
                    page = await r.text()
                    assert r.status == 200 and "2026-10-01-day.mp4" in page and "copy caption" in page
                    assert clips.LABEL in page and "#AI" in page
                async with s.get(base + "/admin/clips/file/..%2Fstate.json", headers={"X-Admin-Token": "tok-123"}) as r:
                    assert r.status == 404
            jar = aiohttp.CookieJar(unsafe=True)                           # cookies on a bare IP host
            async with aiohttp.ClientSession(cookie_jar=jar) as s:          # the login form sets the admin cookie
                async with s.post(base + "/admin/clips/login", data={"token": "tok-123"}) as r:
                    assert r.status == 200 and "copy caption" in await r.text()
                async with s.get(base + "/admin/clips/file/2026-10-01-day.mp4") as r:
                    assert r.status == 200 and await r.read() == b"mp4"
                    assert "attachment" in r.headers["Content-Disposition"]
        finally:
            await runner.cleanup()
    asyncio.run(go())


def test_admin_page_without_a_token_configured_is_closed(tmp_path, monkeypatch):
    import aiohttp
    monkeypatch.delenv("SUB01_ADMIN_TOKEN", raising=False)
    maker = clips.ClipMaker(tmp_path, clock=lambda: NOON)

    async def go():
        from live_server import admin_ok
        runner, base = await _serve(maker, admin_ok)
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(base + "/admin/clips/login", data={"token": ""}) as r:
                    assert r.status == 401
                async with s.get(base + "/admin/clips", headers={"X-Admin-Token": ""}) as r:
                    assert r.status == 401
        finally:
            await runner.cleanup()
    asyncio.run(go())


# --- auto-post -------------------------------------------------------------------------------------------------------
POST_ENV = ("TIKTOK_POST_TOKEN", "YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")


def test_autopost_is_off_without_tokens(tmp_path, monkeypatch):
    for k in POST_ENV:
        monkeypatch.delenv(k, raising=False)
    called = []

    async def boom(*a, **k):
        called.append(a)
        raise AssertionError("must not post")
    monkeypatch.setattr(clips, "post_tiktok", boom)
    monkeypatch.setattr(clips, "post_youtube", boom)
    maker = clips.ClipMaker(tmp_path, clock=lambda: NOON)
    (maker.dir / "2026-10-01-day.mp4").write_bytes(b"mp4")
    assert clips.enabled_posters() == {}
    assert asyncio.run(maker.autopost()) == [] and not called
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "only-one-of-three")
    assert clips.enabled_posters() == {}


class MockAPIs:
    """TikTok Content Posting + Google OAuth + YouTube resumable upload, on a local port."""

    def __init__(self):
        self.calls = []

    async def start(self):
        app = web.Application(client_max_size=50 * 1024 ** 2)
        app.router.add_post("/v2/post/publish/inbox/video/init/", self.tt_init)
        app.router.add_post("/v2/post/publish/video/init/", self.tt_init)
        app.router.add_put("/tt-upload", self.upload)
        app.router.add_post("/token", self.token)
        app.router.add_post("/yt", self.yt_init)
        app.router.add_put("/yt-upload", self.upload)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.base = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
        return self

    async def tt_init(self, r):
        self.calls.append(("tt_init", r.path, r.headers.get("Authorization"), await r.json()))
        return web.json_response({"data": {"publish_id": "p1", "upload_url": self.base + "/tt-upload"},
                                  "error": {"code": "ok"}})

    async def upload(self, r):
        self.calls.append(("upload", r.path, r.headers.get("Content-Range"), len(await r.read())))
        return web.json_response({"id": "vid1"}, status=201 if r.path == "/tt-upload" else 200)

    async def token(self, r):
        self.calls.append(("token", dict(await r.post())))
        return web.json_response({"access_token": "at"})

    async def yt_init(self, r):
        self.calls.append(("yt_init", r.query.get("uploadType"), await r.json()))
        return web.Response(headers={"Location": self.base + "/yt-upload"})


def test_autopost_with_tokens_posts_once_a_day_with_the_ai_flags(tmp_path, monkeypatch):
    async def go():
        api = await MockAPIs().start()
        try:
            monkeypatch.setattr(clips, "TIKTOK_API", api.base)
            monkeypatch.setattr(clips, "YOUTUBE_TOKEN_URL", api.base + "/token")
            monkeypatch.setattr(clips, "YOUTUBE_UPLOAD", api.base + "/yt")
            for k in POST_ENV:
                monkeypatch.setenv(k, "x-" + k)
            monkeypatch.setenv("TIKTOK_POST_MODE", "direct")
            maker = clips.ClipMaker(tmp_path, clock=lambda: NOON)
            maker.ledger = costs.Ledger(tmp_path, clock=lambda: NOON)
            (maker.dir / "2026-10-01-day.mp4").write_bytes(b"m" * 1000)
            (maker.dir / "2026-10-01-choice.mp4").write_bytes(b"c" * 10)
            done = await maker.autopost()
            assert sorted(done) == [("tiktok", True), ("youtube", True)]
            assert await maker.autopost() == []                       # once a day per platform
            return api.calls, maker
        finally:
            await api.runner.cleanup()
    calls, maker = asyncio.run(go())
    tt = next(c for c in calls if c[0] == "tt_init")
    assert tt[1] == "/v2/post/publish/video/init/" and tt[2] == "Bearer x-TIKTOK_POST_TOKEN"
    assert tt[3]["post_info"]["is_aigc"] is True and clips.LABEL in tt[3]["post_info"]["title"]
    assert tt[3]["post_info"]["privacy_level"] == "SELF_ONLY"
    assert ("upload", "/tt-upload", "bytes 0-999/1000", 1000) in calls
    yt = next(c for c in calls if c[0] == "yt_init")
    assert yt[1] == "resumable" and yt[2]["status"]["containsSyntheticMedia"] is True
    assert yt[2]["status"]["privacyStatus"] == "private" and clips.LABEL in yt[2]["snippet"]["description"]
    assert not clips.FINANCE.search(yt[2]["snippet"]["description"] + yt[2]["snippet"]["title"])
    posted = maker.state["posted"]["2026-10-01-day.mp4"]
    assert posted["tiktok"]["ok"] and posted["youtube"]["video_id"] == "vid1"
    led = costs.Ledger(tmp_path, clock=lambda: NOON)
    assert led.posts_today() == {"tiktok": 1, "youtube": 1}
    rep = led.report()
    assert rep["posts_today"] == {"tiktok": 1, "youtube": 1} and rep["today_total_capped"] == 0.0   # counted, not billed


def test_tiktok_default_is_a_draft(tmp_path, monkeypatch):
    async def go():
        api = await MockAPIs().start()
        try:
            monkeypatch.setattr(clips, "TIKTOK_API", api.base)
            monkeypatch.setenv("TIKTOK_POST_TOKEN", "t")
            monkeypatch.delenv("TIKTOK_POST_MODE", raising=False)
            p = tmp_path / "a.mp4"
            p.write_bytes(b"x" * 5)
            res = await clips.post_tiktok(p, "A day in 30 s", "caption " + clips.LABEL)
            return res, api.calls
        finally:
            await api.runner.cleanup()
    res, calls = asyncio.run(go())
    assert res["mode"] == "draft" and calls[0][1] == "/v2/post/publish/inbox/video/init/"


def test_failed_post_is_logged_and_not_retried_the_same_day(tmp_path, monkeypatch):
    monkeypatch.setenv("TIKTOK_POST_TOKEN", "t")
    for k in POST_ENV[1:]:
        monkeypatch.delenv(k, raising=False)

    async def fail(*a, **k):
        raise RuntimeError("tiktok init 401")
    monkeypatch.setattr(clips, "enabled_posters", lambda: {"tiktok": fail})
    maker = clips.ClipMaker(tmp_path, clock=lambda: NOON)
    maker.ledger = costs.Ledger(tmp_path, clock=lambda: NOON)
    (maker.dir / "2026-10-01-day.mp4").write_bytes(b"m")
    assert asyncio.run(maker.autopost()) == [("tiktok", False)]
    assert asyncio.run(maker.autopost()) == []
    assert maker.ledger.posts_today() == {"tiktok": 0}
