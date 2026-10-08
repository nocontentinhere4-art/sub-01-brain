"""#89 live bug (2026-10-04 10:58 and 11:02 Tokyo): on a link chain his monitor showed the full
youtube.com/watch?v=qpkTV1VolHU page (header, Sign in, sponsored cards, a pre-roll ad with "Skip", then "Something
went wrong"). YouTube's Terms forbid automated access to its pages: the browser never navigates to youtube.com/watch,
/shorts or youtu.be; a link to a video is played in the official youtube-nocookie embed after videos.list says it is
playable; an ad or error in the embed moves on to the next video (no ad is ever skipped by us).

    python -m pytest tests/test_no_youtube_pages.py -q
"""
import asyncio
import json
import random
import re
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import browse  # noqa: E402
import youtube_api as YT  # noqa: E402
from browse import Browser  # noqa: E402

YT_PAGE = re.compile(r"^https?://((www|m)\.)?(youtube\.com/(watch|shorts|@|channel|results|$)|youtu\.be/)", re.I)


def run(coro):
    return asyncio.run(coro)


class Page:
    """Records every navigation and answers like a playing embed."""

    def __init__(self, player_text=""):
        self.url, self.visited, self.player_text = "about:blank", [], player_text

    async def goto(self, url, **k):
        self.visited.append(url)
        self.url = url

    async def wait_for_timeout(self, ms):
        pass

    async def evaluate(self, js, *a):
        if "ytp-error" in js:
            return self.player_text
        return {"muted": True, "paused": False}


def _browser(monkeypatch, player_text="", key=True, playable=True):
    if key:
        monkeypatch.setenv("YOUTUBE_API_KEY", "test-key-not-real")
    else:
        monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    b = Browser(decide=True, rng=random.Random(0))
    sc = b.screens["desk"]
    sc.page, sc.ctx = Page(player_text), object()
    api = []

    async def _fetch(sc_, url, hops=3, headers=None):
        api.append(url)
        if "/youtube/v3/videos?" in url:
            vid = url.split("id=")[1].split("&")[0]
            return 200, json.dumps({"items": [{"id": vid, "snippet": {"title": "Colonial Pipeline ransomware",
                                                                        "channelTitle": "Some Channel"},
                                               "contentDetails": {"duration": "PT12M"},
                                               "status": {"embeddable": playable, "privacyStatus": "public"}}]})
        return 404, ""                                          # robots.txt: none

    async def _use(sc_, url):
        pass

    async def _settle(sc_, why, kind, title=None, min_text=80, shoot=True, revisit=False):
        sc_.info = {"title": title or sc_.page.url, "url": sc_.page.url, "host": "x", "why": why, "t": 0, "kind": kind}
        return True

    async def show(sc_):
        return True

    async def _leave(sc_):
        sc_.page.url = "about:blank"
    b._fetch, b._use, b._settle, b.show, b._leave = _fetch, _use, _settle, show, _leave
    return b, sc, api


def test_a_watch_link_plays_in_the_embed_and_no_youtube_page_is_ever_requested(monkeypatch):
    b, sc, api = _browser(monkeypatch)
    assert run(b._open(sc, "https://www.youtube.com/watch?v=qpkTV1VolHU", "followed a link", "page"))
    assert not [u for u in sc.page.visited if YT_PAGE.match(u)]
    assert sc.page.visited == ["https://www.youtube-nocookie.com/embed/qpkTV1VolHU?autoplay=1&mute=1&playsinline=1"
                               "&controls=0&rel=0&loop=1&playlist=qpkTV1VolHU"]
    assert any("/youtube/v3/videos?" in u for u in api)                   # checked as playable first
    assert sc.info["url"] == "https://www.youtube.com/watch?v=qpkTV1VolHU" and sc.info["embed"]
    for link in ("https://youtu.be/abcDEF12345", "https://www.youtube.com/shorts/abcDEF12346",
                 "https://m.youtube.com/watch?feature=share&v=abcDEF12347"):
        run(b._open(sc, link, "a link", "page"))
    assert not [u for u in sc.page.visited if YT_PAGE.match(u)]
    assert all("youtube-nocookie.com/embed/" in u for u in sc.page.visited)


def test_other_youtube_pages_are_never_opened(monkeypatch):
    b, sc, _ = _browser(monkeypatch)
    for u in ("https://www.youtube.com/@MrBeast", "https://www.youtube.com/", "https://www.youtube.com/results?q=x"):
        assert run(b._open(sc, u, "x", "page")) is False
    assert sc.page.visited == [] and "YouTube page" in b.last_skip


def test_without_a_key_or_when_not_playable_the_link_is_not_played(monkeypatch):
    b, sc, _ = _browser(monkeypatch, key=False)
    assert run(b._open(sc, "https://www.youtube.com/watch?v=qpkTV1VolHU", "x", "page")) is False
    assert sc.page.visited == []
    b, sc, _ = _browser(monkeypatch, playable=False)
    assert run(b._open(sc, "https://www.youtube.com/watch?v=qpkTV1VolHU", "x", "page")) is False
    assert sc.page.visited == [] and b.yt.is_bad("https://www.youtube.com/watch?v=qpkTV1VolHU")


def test_an_ad_or_youtubes_error_in_the_embed_moves_on_and_is_never_skipped_by_us(monkeypatch):
    for text in ("advertisement playing Skip", "Something went wrong. Refresh or try again later."):
        b, sc, _ = _browser(monkeypatch, player_text=text)
        assert run(b._open(sc, "https://www.youtube.com/watch?v=qpkTV1VolHU", "x", "page")) is False
        assert b.last_skip == "embed refused"
    q = YT.Quota()
    q.refused("https://www.youtube.com/watch?v=adadadadad1", None)       # an ad: the channel is not blamed
    assert q.channel_ok("Some Channel")
    assert "click" not in browse.EMBED_ERROR_JS and ".click()" not in browse.EMBED_ERROR_JS


def test_the_guard_aborts_a_top_level_navigation_to_youtube(monkeypatch):
    g = browse.Guard()
    seen = []

    async def resolves_public(host):
        return True
    g.resolves_public = resolves_public

    class Route:
        def __init__(self, url, top=True):
            self.request = SimpleNamespace(url=url, resource_type="document", method="GET",
                                           is_navigation_request=lambda: True,
                                           frame=SimpleNamespace(parent_frame=None if top else object()))

        async def abort(self):
            seen.append(("abort", self.request.url))

        async def continue_(self):
            seen.append(("go", self.request.url))
    run(g.route(Route("https://www.youtube.com/watch?v=qpkTV1VolHU")))     # a redirect or a click to the watch page
    run(g.route(Route("https://www.youtube-nocookie.com/embed/qpkTV1VolHU")))
    assert seen == [("abort", "https://www.youtube.com/watch?v=qpkTV1VolHU"),
                    ("go", "https://www.youtube-nocookie.com/embed/qpkTV1VolHU")]


def test_banner_closer_never_presses_anything_in_the_youtube_player():
    """CLOSE_BUTTON matches "Skip": the ad's Skip button in the embed must never be pressed by _dismiss."""
    import asyncio
    from types import SimpleNamespace
    import browse

    class Frame:
        def __init__(self, url):
            self.url, self.calls = url, []

        async def evaluate(self, js, *a):
            self.calls.append(js)
            return [{"i": 0, "label": "Skip", "consent": False}] if "consentRe" in js else None

    for url in ("https://www.youtube-nocookie.com/embed/abcdefghijk", "https://www.youtube.com/embed/abcdefghijk"):
        main = Frame(url)
        page = SimpleNamespace(url=url, frames=[main], main_frame=main)

        async def wait(ms):
            pass
        page.wait_for_timeout = wait
        b = browse.Browser(decide=False)
        asyncio.run(b._dismiss(SimpleNamespace(page=page, site=None), rounds=1))
        assert main.calls == [] and not b.dismissed
    # an ordinary page's "Skip" modal button is still closed as before
    main = Frame("https://example.org/a")
    page = SimpleNamespace(url=main.url, frames=[main], main_frame=main, wait_for_timeout=wait)
    b = browse.Browser(decide=False)
    asyncio.run(b._dismiss(SimpleNamespace(page=page, site=None), rounds=1))
    assert any("click" in c for c in main.calls)


# --- #89 live regression (2026-10-04 11:54 Tokyo): every video showed as a card, "the video is not played" -----------

class RealishPlayer:
    """The youtube-nocookie page as the real _open / _settle / _open_embed path sees it (no _open stub)."""

    def __init__(self, body):
        self.body, self.url, self.frames, self.main_frame, self.cards = body, "about:blank", [], None, 0

    async def goto(self, url, **k):
        self.url = url

    async def wait_for_timeout(self, ms):
        pass

    async def add_style_tag(self, **k):
        pass

    async def title(self):
        return "Grandmaster blunders - YouTube"

    async def screenshot(self, **k):
        return b"jpeg"

    async def set_content(self, html, **k):
        self.cards += 1
        self.url = "about:blank"

    async def evaluate(self, js, *a):
        import browse
        if js == browse.VIDEO_JS:
            return None if "not a bot" in self.body else {"muted": True, "paused": False}
        if "innerText" in js or "ytp-error" in js:
            return self.body
        return None


def _realish(body, monkeypatch):
    import random
    import browse
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-not-real")
    b = browse.Browser(decide=False, rng=random.Random(0))
    sc = b.screens["desk"]
    sc.page, sc.ctx, sc.public = RealishPlayer(body), object(), None
    api = []

    async def _fetch(sc_, url, hops=3, headers=None):
        api.append(url)
        return 404, ""                                          # robots.txt: none

    async def _use(sc_, url):
        pass
    b._fetch, b._use = _fetch, _use
    return b, sc, api


def _card(vid):
    import youtube_api as YT
    return {"url": YT.video_url(vid, False), "title": f"Grandmaster blunders {vid}", "author": "chess channel",
            "hashtags": [], "thumb": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg", "embed": YT.embed_url(vid),
            "host": "youtube.com", "site": "YouTube", "how": "YouTube's official embed player"}


def test_a_normal_embeddable_video_ends_up_playing_not_as_a_card(monkeypatch):
    import asyncio
    b, sc, _ = _realish("Grandmaster blunders\nchess channel\nWatch on YouTube", monkeypatch)
    c = _card("D_E5UB9hMZg")
    sc.queue, sc.cards = [], {c["url"]: c}
    assert asyncio.run(b._show_card(sc, c, "test"))
    assert sc.page.cards == 0 and "youtube-nocookie.com/embed/D_E5UB9hMZg" in sc.page.url
    assert sc.info.get("card") is False and sc.info.get("embed") and sc.watch_until > 0
    assert b.yt.player_up() and b.yt.public()["player"] == "ok"


def test_youtube_refusing_the_player_shows_no_card_and_pauses_youtube(monkeypatch):
    import asyncio
    import youtube_api as YT
    b, sc, api = _realish("Sign in to confirm you’re not a bot\nThis helps protect our community. Learn more",
                          monkeypatch)
    cards = [_card(v) for v in ("aaaaaaaaaa1", "aaaaaaaaaa2", "aaaaaaaaaa3")]
    sc.cards = {c["url"]: c for c in cards}
    sc.queue = [{"url": c["url"]} for c in cards[1:]]
    assert not asyncio.run(b._show_card(sc, cards[0], "test"))
    assert sc.page.cards == 0                                   # never "the video is not played" for YouTube
    assert not b.yt.player_up() and b.yt.public()["player"] == "paused"
    assert b.yt.public()["last_player_refusal"] == "bot wall"
    assert b.yt.public()["refused_by_embed_today"] == 0         # not the videos' fault: they are not set aside
    api.clear()
    assert not asyncio.run(b._public_videos(sc, "youtube", "chess", "test", short=False))
    assert api == [] and b.feed_note.startswith("YouTube: its embed player refuses this browser")   # no units spent
    assert not asyncio.run(b._open(sc, "https://www.youtube.com/watch?v=aaaaaaaaaa9", "link", "page"))
    assert api == [] and "paused" in b.last_skip
    # after the pause it tries again; the pause survives a restart (state)
    q = YT.Quota(b.yt.to_dict(), clock=lambda: b.yt.player["until"] - 1)
    assert not q.player_up()
    q.clock = lambda: b.yt.player["until"] + 1
    assert q.player_up()


def test_with_a_key_the_replay_note_does_not_claim_there_is_no_key(monkeypatch):
    import youtube_api as YT
    assert "no API key" not in YT.NOTE_REPLAY_KEY and "API" in YT.NOTE_REPLAY_KEY
