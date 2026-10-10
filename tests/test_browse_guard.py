"""Phase 0 / Phase 4 browsing items (S2, S9, B1-B8): trading hosts never reach a screen, a reading or the reward; the
random link-follow, loaded pages and error pages pass the same guard as links; YouTube searches before uploads and
replays fit the request; routing and query hygiene; a discovery pool for a 20-year-old in season; the Wikipedia link
pool past the alphabetical prefix; no cached emptiness and no strike for an ad; title_ok word boundaries; a closed
screen shows nothing.

    python -m pytest tests/test_browse_guard.py -q
No network, no AI, no Chromium: fake pages and fake API replies only.
"""
import asyncio
import json
import random
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import browse  # noqa: E402
import interests as I  # noqa: E402
import novelty as NV  # noqa: E402
import readings as RD  # noqa: E402
import research as R  # noqa: E402
import screens as SC  # noqa: E402
import search_sources as S  # noqa: E402
import youtube_api as YT  # noqa: E402
from browse import Browser  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class Page:
    """A loaded page for _settle / _open: title, visible text, a response status, links for _pick_link."""

    def __init__(self, url, title, body, status=200, links=()):
        self.url, self._title, self.body, self.status, self.links = url, title, body, status, list(links)
        self.frames, self.main_frame, self.visited = [], None, []

    async def wait_for_timeout(self, ms):
        pass

    async def add_style_tag(self, **k):
        pass

    async def title(self):
        return self._title

    async def goto(self, url, **k):
        self.url = url
        self.visited.append(url)
        return SimpleNamespace(status=self.status)

    async def evaluate(self, js, *a):
        if "querySelectorAll('a[href]')" in js:
            return [[h, t, 5000] for h, t in self.links]
        if "HTMLMediaElement" in js:                        # VIDEO_JS: no <video> element on these pages
            return None
        if "innerText" in js:
            return self.body
        return [] if "querySelectorAll" in js else False


def _browser(page):
    b = Browser(decide=True, rng=random.Random(0))
    sc = b.screens["desk"]
    sc.page, sc.ctx, sc.public = page, object(), (object(), page)
    shown = []

    async def show(sc_):
        shown.append(sc_.info["url"])
        return True

    async def _fetch(sc_, url, hops=3, headers=None):
        return 404, ""                                      # robots.txt: none
    b.show, b._fetch = show, _fetch
    return b, sc, shown


# --- S2: trading hosts, titles, readings, reward, the public card --------------------------------------------------------
def test_trading_links_are_never_numbered_and_the_old_exception_is_gone():
    b = Browser(decide=True)
    sc = b.screens["desk"]
    sc.info = {"title": "Crypto news", "kind": "page", "host": "example.org"}
    raw = [["https://dexscreener.com/solana/x", "Solana pairs on Dexscreener today", 9000, True],
           ["https://pump.fun/coin/abc", "A brand new coin launched", 9000, True],
           ["https://www.tradingview.com/symbols/BTCUSD/", "BTCUSD live chart", 9000, True],
           ["https://example.org/news/memecoins", "Memecoin news: what happened this week", 900, True],
           ["https://example.org/price", "Bitcoin price today and tomorrow", 900, True]]
    links = b.pick_links(raw, "https://example.org/", "text", sc)["links"]
    assert [l["text"] for l in links] == ["Memecoin news: what happened this week"]
    src = (ROOT / "browse.py").read_text()
    assert "NO RESTRICTIONS" not in src and "ADVICE_LINE" not in src and "finance_note" not in src


def test_a_trading_page_reached_anyway_is_left_before_it_is_shown():
    body = "Market cap $1.2B · 24h volume $3M · Liquidity $400k · Connect wallet · slippage 0.5% " * 5
    b, sc, shown = _browser(Page("https://example.org/token/x", "WIF token", body))
    assert not run(b._settle(sc, "followed a link", "page")) and b.last_skip == "guard" and shown == []
    assert not run(b._open(sc, "https://gmgn.ai/sol/token/x", "x", "page"))     # a trading host: never even loaded
    assert not any(u.startswith("http") for u in sc.page.visited)


def test_finance_never_becomes_a_reading_or_a_reward():
    r = RD.BrowseReadings(display_ok=browse.display_ok)
    assert r.reading({"url": "https://pump.fun/coin/x", "title": "a coin", "finance": True}, "page", 600, 1.0) is None
    assert r.reading({"url": "https://example.org/x", "title": "Bitcoin price today"}, "finance", 600, 1.0) is None
    assert r.reading({"url": "https://example.org/x", "title": "Melon pan guide"}, "page", 600, 1.0)["title"] == "Melon pan guide"
    d = SC.DopamineBursts(clock=lambda: 1.0)
    assert d.on_new("finance", "crypto") is None and d.on_new("news", "x")["size"] >= 0
    assert "finance" not in RD.KIND_LABEL and not hasattr(RD, "finance_word")


def test_the_public_card_and_the_screenshot_hide_a_refused_or_finance_screen():
    from live_server import Live
    ok = {"url": "https://example.org/a", "title": "Melon pan", "host": "example.org", "id": 3}
    bad = {"url": "https://example.org/b", "title": "Bitcoin price today", "host": "example.org", "id": 4}
    fin = {"url": "https://example.org/c", "title": "A page", "host": "example.org", "id": 5, "finance": True}
    assert browse.screen_showable(ok) and not browse.screen_showable(bad) and not browse.screen_showable(fin)
    assert not browse.screen_showable({"url": "https://dexscreener.com/x", "title": "Pairs", "host": "dexscreener.com"})
    live = SimpleNamespace(browser=SimpleNamespace(restarting=False, screens={"desk": bad, "phone": fin}), decisions={})
    for dev in ("desk", "phone"):
        st = Live.screen_status(live, dev)
        assert st == {"device": dev, "restarting": True}          # the placeholder: no title, url or id
    live.browser.screens["desk"] = ok
    assert Live.screen_status(live, "desk")["title"] == "Melon pan"


# --- S9: the random link-follow, loaded pages and error pages ----------------------------------------------------------
def test_the_random_link_follow_uses_the_same_guard_as_the_numbered_links():
    links = [("https://jup.ag/swap", "Connect wallet to swap tokens now"),
             ("https://www.binance.com/en/trade/BTC_USDT", "Trade BTC/USDT with leverage today"),
             ("https://example.org/login", "Log in to read the rest of this article"),
             ("https://example.org/privacy", "Privacy policy and cookie settings"),
             ("https://example.org/ramen", "The best ramen shops in Kichijoji, ranked")]
    b, sc, _ = _browser(Page("https://example.org/", "Example", "x", links=links))
    sc.info = {"title": "Example", "url": "https://example.org/", "host": "example.org", "kind": "page"}
    for _ in range(20):
        pick = run(b._pick_link(sc, "ramen"))
        assert pick == ("https://example.org/ramen", "The best ramen shops in Kichijoji, ranked"), pick


def test_an_error_page_is_left_not_shown_and_a_hype_page_gets_the_guard():
    b, sc, shown = _browser(Page("https://example.org/missing", "Oops", "Sorry, nothing here. " * 10, status=404))
    assert not run(b._open(sc, "https://example.org/missing", "followed a link", "page"))
    assert b.last_skip == "error page" and shown == [] and b.log == []
    b, sc, shown = _browser(Page("https://example.org/x", "404 - Not Found | Example", "The page you requested could not be found. " * 3))
    assert not run(b._settle(sc, "followed a link", "page", min_text=10)) and b.last_skip == "error page"
    assert browse.error_page("Tokyo", "Wikipedia does not have an article with this exact name.")
    assert not browse.error_page("Error handling in Rust", "A long article about errors. " * 300)
    hype = "How to make millions on FOMO app... newbie tutorial! " + "Lorem ipsum dolor sit amet. " * 40
    b, sc, shown = _browser(Page("https://example.org/hype", "A tutorial", hype))
    assert not run(b._settle(sc, "followed a link", "page")) and b.last_skip == "guard" and shown == []
    b, sc, shown = _browser(Page("https://example.org/sex", "free sex cams tonight", "x " * 200))
    assert not run(b._settle(sc, "followed a link", "page")) and b.last_skip == "guard"
    b, sc, shown = _browser(Page("https://example.org/ok", "Sussex Cricket Club season review", "cricket " * 100))
    assert run(b._settle(sc, "followed “Sussex” from example.org", "page")) and shown == ["https://example.org/ok"]
    assert sc.info["why"] == "followed “Sussex” from example.org" and "finance" not in sc.info
    b, sc, shown = _browser(Page("https://example.org/ok2", "A page", "fine " * 100))
    assert run(b._settle(sc, "followed “make money online fast” from x", "page")) and sc.info["why"] == "browsing"


def test_a_refused_status_cools_the_site():
    b, sc, _ = _browser(Page("https://example.org/a", "Fine", "fine " * 100, status=429))
    assert not run(b._open(sc, "https://example.org/a", "x", "page")) and b.walled["example.org"] > time.time()


# --- B1: YouTube: search first, honest fallbacks ---------------------------------------------------------------------
def test_uploads_need_a_topic_and_replays_fit_the_request(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key-not-real")
    b = Browser(decide=True, rng=random.Random(0))
    asked = []

    async def _yt_api(sc_, url):
        asked.append(url)
        return None
    b._yt_api = _yt_api
    assert run(b._yt_uploads(SimpleNamespace(), "Frank Ocean", False)) == [] and asked == []   # no topic: no MrBeast
    card = lambda vid, title, author: {"url": YT.video_url(vid, True), "title": title, "author": author,   # noqa: E731
                                       "hashtags": [], "thumb": "", "embed": YT.embed_url(vid), "host": "youtube.com"}
    b.yt.found([card("abcDEF12340", "Elden Ring boss guide", "IGN"), card("abcDEF12341", "Cute cat compilation", "Pets")])
    assert [c["title"] for c in b._yt_replay(True, "cat video")] == ["Cute cat compilation"]
    assert [c["title"] for c in b._yt_replay(True, "Zelda speedrun")] == ["Elden Ring boss guide"]   # same topic: games
    assert b._yt_replay(True, "Frank Ocean") == []


def test_public_videos_search_first_then_uploads_then_a_fitting_replay(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key-not-real")
    b = Browser(decide=True, rng=random.Random(0))
    sc = b.screens["desk"]
    order, shown = [], []

    async def _yt_search(sc_, q, short=True):
        order.append("search")
        return []

    async def _yt_uploads(sc_, q, short=True):
        order.append("uploads")
        return [{"url": "https://www.youtube.com/watch?v=abcDEF12340", "title": "GR Supra track day", "author": "TopGear",
                 "hashtags": [], "thumb": "", "embed": YT.embed_url("abcDEF12340"), "host": "youtube.com"}]

    async def _show_card(sc_, card, why):
        shown.append((card["title"], why))
        return True
    b._yt_search, b._yt_uploads, b._show_card = _yt_search, _yt_uploads, _show_card
    assert run(b._public_videos(sc, "youtube", "Toyota GR Supra", "looked for videos about “Toyota GR Supra”", short=False))
    assert order == ["search", "uploads"] and shown[0][1].startswith("latest from TopGear") and b.feed_note == YT.NOTE_UPLOADS
    b._yt_uploads = _yt_search                                      # nothing new: an earlier find about the same thing
    b.yt.found([{"url": "https://www.youtube.com/watch?v=abcDEF12341", "title": "Nissan GT-R review", "author": "carwow",
                 "hashtags": [], "thumb": "", "embed": YT.embed_url("abcDEF12341"), "host": "youtube.com"}])
    assert run(b._public_videos(sc, "youtube", "JDM cars", "looked for videos about “JDM cars”", short=False))
    assert shown[-1] == ("Nissan GT-R review", "nothing new today; an earlier pick")
    assert not run(b._public_videos(sc, "youtube", "cat video", "x", short=False))   # no cat video today: nothing shown


# --- B2: routing -----------------------------------------------------------------------------------------------------
def test_routing_phrases_and_video_mode():
    assert S.route("Tokyo tour", rng=random.Random(0))[0] != "nme"
    assert "hn" not in S.route("zip code", rng=random.Random(0)) and "hn" not in S.route("Code Geass", rng=random.Random(0))
    assert "carscoops" not in S.route("a race against time") and "pcgamer" not in S.route("switch the light off")
    assert S.route("ramen", video=True) == [] and S.route("ghibli videos", video=True, rng=random.Random(0)) == []
    assert S.route("Formula 1 race weekend")[0] == "carscoops" and S.route("Netflix series tonight")[0] == "tmdb"
    assert NV.video_query("short history of Japanese tea") is None and NV.video_query("watch a tiktok dance") == "dance"
    assert NV.video_query("best video games 2026") is None and NV.video_query("paper clips") is None
    assert NV.video_query("funny cat shorts") == "funny cat" and NV.video_query("ramen videos") == "ramen"


# --- B3: query hygiene -----------------------------------------------------------------------------------------------
def test_headlines_need_the_query_and_skip_asides():
    html = """<main><article><h2><a href="/zzzqqq-guide">A zzzqqq guide</a></h2><p>About zzzqqq.</p></article>
    <article><h2><a href="/other">Something else entirely</a></h2><p>Nothing here.</p></article></main>
    <aside><h3><a href="/trending-zzzqqq">Trending: zzzqqq again</a></h3></aside>
    <nav><h4><a href="/zzzqqq-menu">zzzqqq menu</a></h4></nav>"""
    res = S.parse_headlines(html, "https://example.org/?s=zzzqqq")
    assert [r["url"] for r in res] == ["https://example.org/zzzqqq-guide"]
    assert S.parse_headlines(html.replace("zzzqqq", "melon"), "https://example.org/?s=zzzqqq") == []


def test_follow_ups_never_search_a_person_and_titles_give_their_subject():
    page = {"title": "A new film from Tokyo", "text": "Yuki Tanaka said the character was hard to play. Yuki Tanaka "
                                                       "grew up in Osaka. The character returns in the sequel, the "
                                                       "character is loved. Shinjuku Station appears in one scene."}
    fs = S.follow_ups(page)
    assert not any("Tanaka" in f["query"] for f in fs) and not any("character" in f["query"] for f in fs)
    assert S.person_like("Yuki Tanaka") and not S.person_like("Ghibli Museum") and not S.person_like("Inokashira Park")
    assert S.video_query("I Spent 24 Hours In A Capsule Hotel In Tokyo") in (None, "Capsule Hotel")
    assert S.video_query("Beginner Guide to Making Ramen Noodles from Scratch | Way of Ramen") == "ramen noodles"
    assert S.video_query("Ghibli Museum opens new exhibit") == "Ghibli Museum"
    assert S.video_query("Yuki Tanaka talks about her new film") is None
    kw = R.keywords("Elden Ring Official Trailer | New Gameplay", "")
    assert "official" not in kw and "new" not in kw and "trailer" not in kw and kw[:2] == ["elden", "ring"]
    for q in ("video", "best videos", "watch this", "top", "new"):
        assert S.interest_for(seen={"screen": [q]}, rng=random.Random(0)) is None
    assert S.interest_for(seen={"screen": ["melon pan bakery"]}, rng=random.Random(0))["query"] == "melon pan bakery"
    live = SimpleNamespace(mind=None, clock=SimpleNamespace(now=lambda: 1_791_000_000.0), memory=SimpleNamespace(items=[]),
                           tastes=SimpleNamespace(pref={}, top=lambda n=8: {"favoured": [
                               {"topic": "video", "kind": "word"}, {"topic": "watch", "kind": "word"},
                               {"topic": "best", "kind": "word"}, {"topic": "ramen", "kind": "word"}]}),
                           life=SimpleNamespace(activity="research", place="desk", path=[], hunger=0.2))
    got = {S.live_interest(live, None, random.Random(i))["query"] for i in range(100)}
    assert not got & {"video", "watch", "best"} and got <= {"ramen", ""}
    assert "reading" in NV.SEEN_ORIGINS


# --- B4: a discovery pool for him, in season ---------------------------------------------------------------------------
def test_discovery_fits_a_20_year_old_the_season_and_the_hour():
    from eyes import query_ok
    craft = ("bonsai", "kintsugi", "beekeeping", "knife", "pottery", "glassblowing", "blacksmith", "calligraphy",
             "carpentry", "origami", "darkroom", "polaroid", "forging", "sharpening", "foraging")
    picks = [I.pick(rng=random.Random(i), discover=True, month=10)["query"] for i in range(3000)]
    assert not any("cherry blossom" in q or "hanami" in q or "snow festival" in q for q in picks)
    assert sum(any(c in q.lower() for c in craft) for q in picks) / len(picks) <= 0.10
    assert any("blossom" in q for q in I.discovery_pool(3)) and not any("blossom" in q for q in I.discovery_pool(10))
    assert all(query_ok(q) == q and browse.title_ok(q) for q in I.DISCOVERY)       # every entry is typeable
    assert len(I.discovery_pool(10)) >= 60 and I.rhythm(3)["name"] == "late night" and "early" not in [r[2] for r in I.RHYTHM]
    v = I.Variety(clock=lambda: 1_791_000_000.0)
    pool = [I.pick(v, rng=random.Random(i), discover=True, month=10, pool_share=0.15)["source"] for i in range(400)]
    assert pool.count("discovery") / len(pool) < 0.35                                   # the phone: mostly his topics
    assert I.PHONE_DISCOVERY == 0.15


def test_the_no_search_branch_opens_a_site_about_the_topic_by_the_hour():
    b = Browser(decide=True, rng=random.Random(0))
    sc = b.screens["desk"]
    seeds = []

    async def _seed(sc_, why, topic=None, hungry=False, only_topic=False, hour=None):
        seeds.append((why, topic, hour))
        return True
    b._seed = _seed
    b.rng = SimpleNamespace(random=lambda: 0.95, choice=random.Random(0).choice)     # the 12 % branch
    assert run(b._next(sc, [], {"query": "Toyota GR Supra", "from": "mind", "hour": 15}))
    assert seeds[-1] == ("opened a site about cars", "cars", 15)
    assert run(b._next(sc, [], {"query": "", "from": "", "hour": 2}))
    assert seeds[-1][1] and seeds[-1][0].startswith("opened a site about ")
    b2 = Browser(decide=True, rng=random.Random(0))
    opened = []

    async def _open(sc_, url, why, kind, **k):
        opened.append(url)
        return True
    b2._open = _open
    for _ in range(10):
        b2.seed_t = {}
        run(b2._seed(b2.screens["desk"], "x", hour=2))
    assert not any(u in browse.SEED_TOPICS["football"] for u in opened)              # no sports fronts at 02:00
    run(b2._seed(b2.screens["desk"], "x", "football", hour=15))
    assert opened[-1] in browse.SEED_TOPICS["football"]


# --- B5: the Wikipedia link pool -------------------------------------------------------------------------------------
def test_wikipedia_links_follow_the_continuation_and_drop_numbers(monkeypatch):
    calls = []

    def get(url, timeout=12):
        calls.append(url)
        if "plcontinue" not in url:
            return {"continue": {"plcontinue": "x|y", "continue": "||"},
                    "query": {"pages": {"1": {"links": [{"title": f"Alpha {i:03d}"} for i in range(200)]}}}}
        return {"query": {"pages": {"1": {"links": [{"title": "1,000,000,000"}, {"title": "1917"}, {"title": ", comma"},
                                                     {"title": "Zebra crossing"}, {"title": "Casino history"}]}}}}
    monkeypatch.setattr(R, "get", get)
    out = R.links("Tokyo")
    assert len(calls) == 2 and "pllimit=500" in calls[0] and "plcontinue=x%7Cy" in calls[1]
    assert "Zebra crossing" in out and "1,000,000,000" not in out and "1917" not in out and ", comma" not in out
    assert "Casino history" not in out and len(out) == 201
    title, _ = R.curiosity(out, {}, {}, 0.0, random.Random(3), temperature=50.0)
    assert any(R.curiosity(out, {}, {}, 0.0, random.Random(s), temperature=50.0)[0] == "Zebra crossing" for s in range(400))


# --- B6: the YouTube cache and ads -------------------------------------------------------------------------------------
def test_a_failed_playability_check_is_not_cached_for_six_hours(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key-not-real")
    clk = SimpleNamespace(t=1_791_000_000.0)
    b = Browser(decide=True, rng=random.Random(0))
    b.yt = YT.Quota(clock=lambda: clk.t)
    sc = b.screens["phone"]
    sc.public = (object(), object())
    api = (ROOT / "tests" / "data" / "search" / "youtube_api_search.json").read_text()

    async def _fetch(sc_, url, hops=3, headers=None):
        return (200, api) if url.startswith(YT.SEARCH) else (500, "")      # videos.list fails
    b._fetch = _fetch
    assert run(b._yt_search(sc, "ramen", True)) == []
    assert b.yt.cached("ramen", True) == [] and b.yt.cache[b.yt._k("ramen", True)].get("neg")
    clk.t += YT.NEG_CACHE_S + 1
    assert b.yt.cached("ramen", True) is None                                   # asked again after 10 min, not 6 h
    pid_calls = []

    async def _yt_api(sc_, url):
        pid_calls.append(url)
        if "/channels?" in url:
            return json.dumps({"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UUx0123456789"}}}]})
        if "/playlistItems?" in url:
            return json.dumps({"items": [{"contentDetails": {"videoId": "abcDEF12340"}, "snippet": {"title": "GR Supra"}}]})
        return None                                                              # videos.list fails
    b._yt_api = _yt_api
    assert run(b._yt_uploads(sc, "Toyota GR Supra", True)) == [] and "p:UUx0123456789" not in b.yt.cache


def test_an_ad_during_a_watch_keeps_the_timer_and_blames_nobody():
    b = Browser(decide=True, rng=random.Random(0))
    sc = b.screens["desk"]
    sc.page = Page("https://www.youtube-nocookie.com/embed/x", "x", "advertisement playing Skip ad")
    sc.info = {"url": "https://www.youtube.com/watch?v=abcDEF12340", "title": "x", "host": "youtube.com", "kind": "page",
               "embed": "https://www.youtube-nocookie.com/embed/x", "channel": "Some Channel", "video": {}}
    sc.watch_until = time.time() + 100

    async def _shoot(sc_):
        sc_.shot = b"x"
        return True
    b._shoot = _shoot
    assert run(b._watch(sc)) and sc.watch_until > time.time() + 100
    assert not b.yt.is_bad(sc.info["url"]) and b.yt.channel_ok("Some Channel")
    sc.page.body = "advertisement playing This video is unavailable"
    assert not run(b._watch(sc)) and b.yt.is_bad(sc.info["url"])           # a real error still moves on


# --- B7: title_ok word boundaries ------------------------------------------------------------------------------------
@pytest.mark.parametrize("title, ok", [("Sussex Cricket Club", True), ("Essex coast walk", True), ("Adulthood in Japan", True),
                                       ("Sextant navigation", True), ("Middlesex Hospital history", True),
                                       ("free sex cams", False), ("adult chat rooms", False), ("casino night tips", False)])
def test_title_ok_word_boundaries(title, ok):
    assert browse.title_ok(title) is ok


# --- B8: a closed or timed-out screen shows nothing ---------------------------------------------------------------------
def test_a_closed_screen_drops_its_status_and_shot():
    from browse_service import BrowserClient
    c = BrowserClient("http://127.0.0.1:1")
    c.screens["desk"] = {"url": "https://example.org/", "title": "x", "id": 3}
    c.shots["desk"] = (3, b"jpeg")
    c._closed({"status": None, "closed": "desk"})
    assert "desk" not in c.screens and "desk" not in c.shots
    assert run(c.shot("desk")) is None                                        # no status: nothing to show, no request
    src = (ROOT / "browse_service.py").read_text()
    assert '"closed": dev' in src and "return CLOSED" in src
