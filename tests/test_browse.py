"""The screens' browser: what it may open and show (no network needed; the Chromium test is skipped without it)."""
import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from browse import Browser, Guard, host_ok, text_ok, url_ok  # noqa: E402


@pytest.mark.parametrize("url", [
    "https://en.wikipedia.org/wiki/Tokyo", "https://www.bbc.com/news", "http://example.com/a?b=c",
    "https://www.justonecookbook.com/easy-and-authentic-ramen-recipes/", "https://8.8.8.8/",
])
def test_open_web_allowed(url):
    assert url_ok(url)


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "javascript:alert(1)", "ftp://example.com/", "data:text/html,hi", "chrome://settings",
    "http://127.0.0.1:8765/", "http://localhost/", "http://LOCALHOST:80/", "http://localhost.localhost/",
    "http://metadata.google.internal/", "http://10.0.0.5/", "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://[fd00::1]/", "http://0.0.0.0/",
    "http://railway.internal/", "http://db.svc.local/",
    "https://example.com:8443/", "https://user:pw@example.com/",
    "https://www.pornhub.com/", "https://xhamster.com/x", "https://onlyfans.com/a", "https://www.bet365.com/",
    "https://phantom.app/download", "https://metamask.io/", "https://sub01-production.up.railway.app/",
    "https://example.com/file.zip", "https://example.com/report.pdf", "https://example.com/setup.exe",
])
def test_blocked(url):
    assert not url_ok(url)


def test_hosts():
    assert host_ok("en.wikipedia.org")
    assert not host_ok("") and not host_ok("127.0.0.1") and not host_ok("printer.local")


def test_text_guard():
    assert text_ok("Ramen recipes", "Boil the noodles. " * 50)
    assert text_ok("Mental health in Japan", "A news story that mentions suicide prevention once. " + "x " * 500)
    assert not text_ok("Free porn videos", "")
    assert text_ok("Hot new memecoin presale", "")       # finance pages are viewable since #56 (read-only)
    assert not text_ok("Gallery", "nude " * 3)
    assert not text_ok("Casino bonus", "")


def test_guard_dns_private():
    g = Guard()
    loop = asyncio.new_event_loop()
    try:
        assert not loop.run_until_complete(g.resolves_public("localhost"))
        assert not loop.run_until_complete(g.resolves_public("127.0.0.1"))
        assert not loop.run_until_complete(g.resolves_public("169.254.169.254"))
        assert loop.run_until_complete(g.resolves_public("8.8.8.8"))       # a literal public IP: no lookup needed
        assert loop.run_until_complete(Guard(via_proxy=True).resolves_public("anything.example"))
    finally:
        loop.close()


def test_state_roundtrip():
    b = Browser({"log": [{"t": 1, "device": "desk", "title": "x", "url": "https://a.b/", "host": "a.b", "why": "w"}],
                 "used": ["hello"]})
    d = b.to_dict()
    assert d["log"][0]["title"] == "x" and d["used"] == ["hello"]
    assert b.screens["desk"].status() is None                                 # nothing shown yet


def _chromium_ok():
    if not Browser.available():
        return False
    exe = os.environ.get("BROWSE_CHROMIUM")
    return exe is None or Path(exe).exists()


@pytest.mark.skipif(not _chromium_ok(), reason="playwright / chromium not installed")
def test_browser_never_shows_local_pages():
    """A page on this machine (the server itself, cloud metadata, ...) is never loaded, shown or logged."""
    from aiohttp import web

    async def run():
        async def secret(request):
            return web.Response(text="<title>secret</title>" + "internal secret " * 20, content_type="text/html")
        app = web.Application()
        app.router.add_get("/", secret)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        b = Browser()
        try:
            sc = await b._ensure("desk")
        except Exception as e:                                                 # no usable Chromium here
            await runner.cleanup()
            pytest.skip(f"chromium did not start: {e!r}"[:200])
        try:
            for url in (f"http://localhost:{port}/", f"http://127.0.0.1:{port}/"):
                assert not await b._open(sc, url, "test", "page")
            assert sc.shot is None and b.log == []
            body = await sc.page.evaluate("() => document.body ? document.body.innerText : ''")
            assert "secret" not in body
        finally:
            await b.close()
            if b.pw:                                                          # close() may already have stopped it
                await b.pw.stop()
            await runner.cleanup()

    asyncio.run(run())


GOOGLE_SORRY = ("I'm not a robot\nreCAPTCHA\nAbout this page\nOur systems have detected unusual traffic from your "
                "computer network. This page checks to see if it's really you sending the requests, and not a robot.")


@pytest.mark.parametrize("body", [GOOGLE_SORRY, "Checking your browser before accessing example.com",
                                  "Please verify you are human", "Complete the security check to access the site."])
def test_bot_wall_text_is_recognised(body):
    assert Browser.wall_text(body)


@pytest.mark.parametrize("body", ["CAPTCHA is a type of challenge-response test used in computing.",
                                  "Robots in Japan: a history of industrial robots", "Traffic in Tokyo is unusual.",
                                  "To reset it, press and hold the power button for 10 seconds.",
                                  "“Are you a robot?” asks the Turing test. I'm not a robot, says the machine.",
                                  "A long article. " * 150 + "Our systems detected unusual traffic from your network."])
def test_articles_about_captchas_are_not_walls(body):
    assert not Browser.wall_text(body)


def test_bot_wall_page_is_left_not_shown():
    """A CAPTCHA page (here: a reCAPTCHA frame on a normal-looking page) is never screenshotted; he leaves it."""
    async def run():
        b = Browser()
        try:
            sc = await b._ensure("desk")
        except Exception as e:                                                 # no usable Chromium here
            pytest.skip(f"chromium did not start: {e!r}"[:200])
        try:
            await sc.page.set_content("<title>Search</title><p>" + "results " * 40 + "</p>"
                                      "<iframe src='about:blank#https://www.google.com/recaptcha/api2/anchor'></iframe>")
            await sc.page.evaluate("() => document.querySelector('iframe').setAttribute('src', "
                                   "'https://www.google.com/recaptcha/api2/anchor?k=x')")
            await sc.page.set_viewport_size({"width": 1280, "height": 800})
            await sc.page.evaluate("() => { const f = document.querySelector('iframe'); f.width = 304; f.height = 78; }")
            assert await b._walled(sc.page)
            sc.info = {"title": "Search", "url": "x", "host": "x", "why": "", "t": 0, "kind": "search"}
            assert not await b.show(sc)
            assert sc.shot is None and sc.info["kind"] == "left" and b.log == []        # not shown, not logged
            # the invisible reCAPTCHA v3 badge on an ordinary page is not a wall
            await sc.page.set_content("<title>Bakery</title><p>" + "fresh bread daily " * 40 + "</p><div class='grecaptcha-badge'>"
                                      "<iframe width=256 height=60 src='https://www.google.com/recaptcha/api2/anchor?k=x&size=invisible'></iframe></div>")
            assert not await b._walled(sc.page)
            await sc.page.set_content("<title>Bread</title><p>" + "bread is baked " * 40 + "</p>")
            assert not await b._walled(sc.page)
        finally:
            await b.close()
            if b.pw:                                                          # close() may already have stopped it
                await b.pw.stop()

    asyncio.run(run())


def test_money_hype_never_on_screen():
    """Live 2026-10-09: money-making and trading promotion videos reached the monitor (owner rules: no buy pressure,
    no Fomo / trading on the monitor). Plain finance words and big numbers in other videos still pass."""
    import browse
    import eyes
    for t in ("How to make millions on FOMO app... newbie tutorial!",
              "#1 Prop Firm Scalper: The ICT Trader Who Made $2.5+ Million With A 40% Win Rate",
              "Day Trading for beginners", "make money online fast", "crypto gems 100x"):
        assert not browse.media_title_ok(t) and not browse.title_ok(t) and not eyes.query_ok(t), t
    for t in ("How 1 Person Solved A $1,000,000 Puzzle!", "Stockholm Syndrome", "Pokemon trading cards",
              "How to make magnetic slime at home"):
        assert browse.media_title_ok(t), t
