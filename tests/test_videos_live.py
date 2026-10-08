"""#89 live follow-up (2026-10-03): 0 % short video live. Root causes and their fixes, without the network:
- youtube.com/robots.txt disallows /results: the YouTube and Shorts sources were refused all day. Now the official
  Data API v3 (YOUTUBE_API_KEY, header only, free quota) and the official embed player (youtube-nocookie /embed).
- DuckDuckGo answers datacenter IPs with its bot check ("anomaly"): no TikTok URL was ever found. Now recognised and
  set aside; TikTok's official player (/player/v1) for what is found; the logged-in feed says why it shows nothing.
- dopamine-like bursts were ~0 on shorts: every short without a profile topic shared the topic "youtube.com".
- the Hacker News loop: the same query searched again and again ("news wikipedia — Hacker News" twice).
- "no search box": Science News and RecipeTin are searched through their own /?s= results pages.
- Chromium restarts: each restart now records why (exit code / memory / hung).

    python -m pytest tests/test_videos_live.py -q
"""
import asyncio
import json
import random
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import browse  # noqa: E402
import browse_service as BS  # noqa: E402
import screens as SC  # noqa: E402
import search_sources as S  # noqa: E402
import youtube_api as YT  # noqa: E402
from browse import Browser  # noqa: E402
from live_server import Live  # noqa: E402

DATA = Path(__file__).resolve().parent / "data" / "search"


def run(coro):
    return asyncio.run(coro)


class Clock:
    def __init__(self, t=1_790_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


# --- YouTube: robots.txt, the Data API, the embed player ------------------------------------------------------------
def test_youtube_results_are_robots_closed_and_never_routed():
    rp = S.Robots()
    rp.load("www.youtube.com", 200, "User-agent: *\nDisallow: /results\nDisallow: /api/\n")
    assert rp.allowed("https://www.youtube.com/results?search_query=ramen") is False
    assert rp.allowed("https://www.youtube.com/shorts/abcDEF12345") is True
    nc = S.Robots()
    nc.load("www.youtube-nocookie.com", 200, "User-agent: *\nDisallow: /results\nDisallow: /videos\n")
    assert nc.allowed(YT.embed_url("abcDEF12345")) is True                       # the embed player is allowed
    for q, video in (("lo-fi music", False), ("ramen videos", True)):
        assert not {"youtube", "shorts", "tiktok"} & set(S.route(q, video=video, rng=random.Random(0)))


def test_data_api_search_is_parsed_and_its_quota_kept():
    rs = YT.parse_search((DATA / "youtube_api_search.json").read_text(), short=True)
    assert len(rs) == 4 and rs[0]["url"] == "https://www.youtube.com/shorts/aB3dE5fG7hI"          # channels skipped
    assert rs[0]["embed"].startswith("https://www.youtube-nocookie.com/embed/aB3dE5fG7hI?autoplay=1&mute=1")
    assert "key" not in YT.search_url("ramen") and "videoDuration=short" in YT.search_url("ramen")
    clk = Clock()
    q = YT.Quota(clock=clk)
    for _ in range(YT.DAILY_UNITS // YT.SEARCH_UNITS):
        assert q.allow()
        q.spend("x", True, rs)
    assert not q.allow() and q.public()["units_used"] == YT.DAILY_UNITS <= YT.FREE_UNITS
    assert q.cached("X ", True) and q.cached("x", False) is None
    clk.t += 86400                                                                # a new Pacific day
    assert q.allow() and q.public()["units_used"] == 0


def test_the_key_never_reaches_state_or_public_views(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "secret-test-value")
    b = Browser(decide=True)
    blob = json.dumps(b.to_dict()) + json.dumps(b.yt.public())
    assert "secret-test-value" not in blob and b.yt.public()["key_set"] is True
    assert "YOUTUBE_API_KEY" in BS.ENV_KEEP and "YOUTUBE_API_KEY" not in browse.CHROMIUM_ENV


# --- the Hacker News loop, "no search box", robots refusals ----------------------------------------------------------
def test_the_same_query_is_not_searched_twice_a_day():
    b = Browser(decide=True, rng=random.Random(0))
    clk = Clock()
    b.variety = __import__("interests").Variety(clock=clk)
    searched = []

    async def _search_on(sc_, name, q, why, origin):
        searched.append(q)
        sc_.info = {"results": [{"url": f"https://hn.example.org/{len(searched)}", "title": "x"}], "kind": "search",
                    "url": "https://hn.algolia.com/", "title": q}
        return True
    b._search_on = _search_on
    sc = b.screens["desk"]
    run(b._search(sc, "news wikipedia", "", "reading"))
    run(b._search(sc, "news wikipedia", "", "reading"))                            # the live log had it twice
    assert searched[0] == "news wikipedia" and searched[1] != "news wikipedia"
    run(b._search(sc, "news wikipedia", "", "chat"))                               # a viewer asking is honoured
    assert searched[-1] == "news wikipedia"


def test_science_news_and_recipetin_use_their_own_results_pages():
    for name, host in (("news", "www.sciencenews.org"), ("recipes", "www.recipetineats.com")):
        src = S.SOURCES[name]
        assert "site" not in src and src["url"]("sleep spindles") == f"https://{host}/?s=sleep+spindles"
    res = S.parse_headlines((DATA / "news.html").read_text(), "https://www.sciencenews.org/?s=sleep+spindles")
    assert len(res) >= 5


def test_a_robots_refusal_sets_a_source_aside_for_the_day_and_old_blocks_are_dropped():
    clk = Clock()
    lim = S.Limits(clock=clk)
    lim.refuse("bing", "robots.txt")
    assert lim.is_blocked("bing") and lim.blocked_now()["bing"]["why"] == "robots.txt"
    clk.t += S.BLOCK_MAX_S + 60
    assert lim.is_blocked("bing")                                                  # still: robots does not change
    old = {"blocked": {"tiktok": {"until": clk.t + 9999, "why": "no videos reachable from the server"}}}
    assert not S.Limits(clock=clk, state=old).blocked_now()                        # the pre-fix state is dropped
    assert S.Limits(clock=clk, state=lim.to_dict()).is_blocked("bing")


# --- TikTok: why the logged-in feed shows nothing ---------------------------------------------------------------------
class DiagPage:
    url = "https://www.tiktok.com/tag/ramen?lang=en"

    def __init__(self):
        self.styles = []

    async def evaluate(self, js, *a):
        return 0 if "querySelectorAll" in js else None

    async def add_style_tag(self, content):
        self.styles.append(content)

    async def screenshot(self, type="jpeg", quality=60):
        return b"\xff\xd8jpeg"


def test_a_logged_in_feed_with_no_video_says_why_and_keeps_a_masked_screenshot():
    b = Browser(decide=True)
    sc = SimpleNamespace(site="tiktok", page=DiagPage())
    run(b._diag(sc, "bot wall", "TikTok - Make Your Day", "Drag the slider to fit the puzzle  Log in"))
    d = b.diag["tiktok"]
    assert d["reason"] == "bot wall" and d["captcha"] and d["login_prompt"] and d["video_links"] == 0
    assert d["path"] == "/tag/ramen" and "lang" not in json.dumps(d)                  # no query, no account
    assert b.diag_shot["tiktok"].startswith(b"\xff\xd8") and "Avatar" in sc.page.styles[0]


def test_screens_and_health_report_the_feeds_and_the_restarts(tmp_path):
    live = Live("m", True, time_scale=1e6, data_dir=tmp_path)
    live.browser = SimpleNamespace(log=[], searches=None, accounts=None, feed_note=None, restarting=False,
                                   failures=0, youtube={"key_set": False, "units_used": 0},
                                   diag={"tiktok": {"t": 1, "reason": "bot wall", "video_links": 0, "captcha": True,
                                                    "login_prompt": False, "chars": 40, "path": "/tag/x"}})
    v = live.screens_view()
    assert v["feeds"]["tiktok"]["reason"] == "bot wall" and "path" not in v["feeds"]["tiktok"]
    assert v["youtube"]["key_set"] is False


def test_a_restart_records_why():
    lb = BS.LocalBrowser()

    class Proc:
        returncode, pid = -9, 999999
    lb.proc = Proc()

    async def spawn():
        return True

    async def kill():
        pass
    lb.spawn, lb.kill = spawn, kill
    assert run(lb.ensure()) == "restarted"
    assert lb.restarts == 1 and lb.restart_log[-1]["why"] == "exited, killed by signal 9 (out of memory?)"


# --- dopamine-like bursts on short videos -------------------------------------------------------------------------------
def test_a_new_scroll_session_of_shorts_gives_the_biggest_bursts():
    clk = Clock()
    da = SC.DopamineBursts(clock=clk)
    pages = []
    for i in range(10):                                                           # an hour of pages first
        pages.append(da.on_new("news", f"news-topic-{i}", 0.0)["size"])
        clk.t += 360
    first = da.on_new("shorts", "video:a cat jumps", 0.0)["size"]
    clk.t += 40
    second = da.on_new("shorts", "video:ramen in 30 seconds", 0.0)["size"]
    assert first > 0.5 > max(pages) and second > 0.3                               # short-form, new: a real burst
    clk.t += 1800                                                                 # half an hour later: surprise again
    assert da.on_new("tiktok", "video:something else", 0.0)["size"] > 0.5


def test_live_like_a_short_from_the_api_drives_the_reward_regions(tmp_path, monkeypatch):
    """The real path from the Data API to the brain: search (stubbed HTTP) → the official embed opened (stubbed page)
    → the screen status → live.on_screen → a dopamine-like burst, the DA level up, the reward regions driven."""
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key-not-real")
    b = Browser(decide=True, rng=random.Random(0))
    sc = b.screens["phone"]
    sc.mode, sc.page, sc.ctx = "shorts", SimpleNamespace(url="about:blank"), object()

    async def _fetch(sc_, url, hops=3, headers=None):
        if "/youtube/v3/videos?" in url:                    # the playability check (1 unit)
            return 200, (DATA / "youtube_api_videos.json").read_text()
        return (200, (DATA / "youtube_api_search.json").read_text()) if url.startswith(YT.SEARCH) else (404, "")

    async def _open(sc_, url, why, kind, title=None, min_text=80, shoot=True, revisit=False, referer=None):
        sc_.info = {"title": title, "url": url, "host": "www.youtube-nocookie.com", "why": why, "t": time.time(),
                    "kind": kind}
        return True

    async def _ok(*a, **k):
        return True
    b._fetch, b._open, b._play_muted, b._shoot = _fetch, _open, _ok, _ok
    assert run(b._public_videos(sc, "shorts", "ramen", "short videos"))
    sc.shot = b"x"
    st = sc.status()
    live = Live("m", True, time_scale=1e6, data_dir=tmp_path)
    sent, driven = [], []

    async def bc(msg):
        sent.append(msg)
    live.broadcast = bc
    real = live.brain.stimulate
    live.brain.stimulate = lambda region, amp: (driven.append((region, amp)), real(region, amp))
    da0 = live.neuro.levels["DA"]
    burst = run(live.on_screen(st))
    assert SC.screen_kind(st) == "shorts" and burst["size"] > 0.5
    assert live.neuro.levels["DA"] > da0 and any(r == "reward" and a > 0 for r, a in driven)
    assert [m for m in sent if m.get("type") == "dopamine"][0]["kind"] == "shorts"
