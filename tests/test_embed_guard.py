"""#89 live bug (2026-10-04 10:46 Tokyo): the desk played "FP3 Highlights | 2026 Bahrain Grand Prix … – Formula1" and
the embed showed "Video unavailable. This video contains content from Formula One Management, who has blocked it from
display on this website or application": a dead black screen on his monitor.

    python -m pytest tests/test_embed_guard.py -q
No network: videos.list answers and the player page are stubbed.
"""
import asyncio
import json
import random
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import browse  # noqa: E402
import youtube_api as YT  # noqa: E402
from browse import Browser  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def item(vid, embeddable=True, privacy="public", rating=None, region=None, duration="PT45S"):
    cd = {"duration": duration}
    if rating:
        cd["contentRating"] = {"ytRating": rating}
    if region:
        cd["regionRestriction"] = region
    return {"id": vid, "contentDetails": cd, "snippet": {"title": vid},
            "status": {"embeddable": embeddable, "privacyStatus": privacy}}


def test_videos_list_keeps_only_what_the_embed_will_play_in_japan():
    resp = json.dumps({"items": [
        item("okokokokok1"),
        item("noembed0001", embeddable=False),
        item("unlisted001", privacy="unlisted"),
        item("agerestrict", rating="ytAgeRestricted"),
        item("blockedinjp", region={"blocked": ["JP", "KR"]}),
        item("onlyinusa01", region={"allowed": ["US", "CA"]}),
        item("allowedinjp", region={"allowed": ["JP", "US"]}),
        {"id": "noflag00001", "contentDetails": {"duration": "PT30S"}, "status": {"privacyStatus": "public"}},
    ]})
    assert set(YT.parse_durations(resp)) == {"okokokokok1", "allowedinjp"}
    assert "snippet" in YT.videos_url(["x"]) and "status" in YT.videos_url(["x"])
    assert "Formula1" not in YT.CHANNELS["cars"]


class PlayerPage:
    """The youtube-nocookie page: per video id, its text after a few seconds."""

    def __init__(self, texts):
        self.texts, self.url = texts, "about:blank"

    async def wait_for_timeout(self, ms):
        pass

    async def evaluate(self, js, *a):
        if "ytp-error" in js:
            vid = self.url.split("/embed/")[1].split("?")[0] if "/embed/" in self.url else ""
            return self.texts.get(vid, "")
        return {"muted": True, "paused": False}                 # VIDEO_JS: a playing, muted video

    async def goto(self, url, **k):
        self.url = url


def _browser(texts):
    b = Browser(decide=True, rng=random.Random(0))
    sc = b.screens["desk"]
    sc.page, sc.ctx = PlayerPage(texts), object()
    shown = []

    async def _open(sc_, url, why, kind, title=None, min_text=80, shoot=True, revisit=False, referer=None):
        sc_.page.url = url
        sc_.info = {"title": title, "url": url, "host": "www.youtube-nocookie.com", "why": why, "t": 0, "kind": kind}
        return True

    async def _fetch(sc_, url, hops=3, headers=None):
        return 404, ""                                          # robots.txt: none

    async def show(sc_):
        shown.append(sc_.info["url"])
        return True

    async def _leave(sc_):
        sc_.page.url = "about:blank"
    b._open, b._fetch, b.show, b._leave = _open, _fetch, show, _leave
    return b, sc, shown


def card(vid, author="Formula1"):
    return {"url": f"https://www.youtube.com/watch?v={vid}", "title": f"Video {vid}", "author": author, "hashtags": [],
            "thumb": "", "embed": YT.embed_url(vid), "host": "youtube.com"}


def test_a_refused_embed_is_never_shown_and_the_next_video_plays():
    blocked = ("Video unavailable This video contains content from Formula One Management, who has blocked it from "
               "display on this website or application. Watch on YouTube")
    b, sc, shown = _browser({"X3dw_sgRwF0": blocked})
    bad, good = card("X3dw_sgRwF0"), card("goodvideo01", author="TopGear")
    sc.cards = {c["url"]: c for c in (bad, good)}
    sc.queue = [{"url": c["url"], "title": c["title"], "video": True} for c in (bad, good)]
    assert run(b._show_card(sc, bad, "videos"))
    assert shown == [good["url"]]                                   # the blocked one never reached the screen
    assert b.yt.is_bad(bad["url"]) and not b._card_ok(bad)          # not again today
    assert sc.watch_until > 0 and sc.info["url"] == good["url"]


def test_an_error_during_the_watch_leaves_the_video():
    b, sc, shown = _browser({})
    good = card("goodvideo01", author="TopGear")
    assert run(b._open_embed(sc, good, "videos"))
    sc.page.texts["goodvideo01"] = "An error occurred. Please try again later."
    assert run(b._watch(sc)) is False and sc.watch_until == 0 and b.yt.is_bad(good["url"])


def test_a_channel_whose_embeds_keep_failing_is_set_aside_for_the_day():
    q = YT.Quota()
    for i in range(YT.BAD_CHANNEL):
        q.refused(f"https://www.youtube.com/watch?v=bad{i:08d}", "SomeLabel")
    assert not q.channel_ok("SomeLabel") and q.channel_ok("TopGear")
    assert q.public()["channels_set_aside"] == ["SomeLabel"]
    assert YT.Quota(state=q.to_dict()).is_bad("https://www.youtube.com/watch?v=bad00000000")   # survives a restart
    b = Browser(decide=True)
    b.yt = q
    picked = []

    async def _yt_api(sc_, url):
        picked.append(url)
        return None
    b._yt_api = _yt_api
    YT.CHANNELS["test-topic"] = ["SomeLabel"]
    try:
        run(b._yt_uploads(SimpleNamespace(), "x", True))
    finally:
        del YT.CHANNELS["test-topic"]
    assert not any("SomeLabel" in u for u in picked)


def test_search_results_are_checked_for_playability(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key-not-real")
    b = Browser(decide=True)
    search = json.dumps({"items": [{"id": {"videoId": v}, "snippet": {"title": f"ramen {v}", "channelTitle": "c"}}
                                   for v in ("okokokokok1", "noembed0001")]})
    videos = json.dumps({"items": [item("okokokokok1"), item("noembed0001", embeddable=False)]})

    async def _fetch(sc_, url, hops=3, headers=None):
        return 200, (videos if "/videos?" in url else search)
    b._fetch = _fetch
    cards = run(b._yt_search(SimpleNamespace(), "ramen", True))
    assert [c["url"] for c in cards] == ["https://www.youtube.com/shorts/okokokokok1"]
    assert b.yt.public()["units_used"] == YT.SEARCH_UNITS + YT.LIST_UNITS
