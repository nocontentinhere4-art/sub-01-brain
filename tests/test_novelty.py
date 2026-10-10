"""#89 follow-up: hard novelty rules on the live path, replayed on what the live site really did (2026-10-02,
/api/browsing at 18:30 UTC: 30 phone pages, all Wikipedia / abc.net.au / MediaWiki / bandcamp / npr / Creative
Commons; "Studio Ghibli — Wikipedia" 3x plus variants, a MediaWiki page 3x, an abc wetlands article twice, "Contact
Us", the ABC home page and licence deeds followed from footers, and a search for "tiktok videos" ending on Wikipedia).

    python -m pytest tests/test_novelty.py -q
No network: browser methods that would load a page are stubbed; the parsers and the guard are the real ones.
"""
import asyncio
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import browse  # noqa: E402
import interests as I  # noqa: E402
import novelty as NV  # noqa: E402
import search_sources as S  # noqa: E402
from browse import Browser  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def run(coro):
    return asyncio.run(coro)


class Clock:
    def __init__(self, t=1_790_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


# what the live log showed (hosts and titles as reported by the coordinator; URLs as those sites write them)
LIVE = [
    ("https://en.wikipedia.org/wiki/Studio_Ghibli", "Studio Ghibli — Wikipedia"),
    ("https://en.wikipedia.org/wiki/Studio_Ghibli", "Studio Ghibli — Wikipedia"),
    ("https://en.m.wikipedia.org/wiki/Studio_Ghibli", "Studio Ghibli - Wikipedia"),
    ("https://en.wikipedia.org/w/index.php?search=studio+ghibli+wikipedia&title=Special:Search",
     "studio ghibli wikipedia — Wikipedia"),
    ("https://www.mediawiki.org/wiki/MediaWiki_Users_and_Developers_Conference_Fall_2026",
     "MediaWiki Users and Developers Conference Fall 2026 - MediaWiki"),
    ("https://www.mediawiki.org/wiki/MediaWiki_Users_and_Developers_Conference_Fall_2026/",
     "MediaWiki Users and Developers Conference Fall 2026 - MediaWiki"),
    ("https://mediawiki.org/wiki/MediaWiki_Users_and_Developers_Conference_Fall_2026?utm_source=x",
     "MediaWiki Users and Developers Conference Fall 2026"),
    ("https://www.abc.net.au/news/2026-10-01/wetlands-restoration-birds-return/104412345",
     "Wetlands restoration brings the birds back - ABC News"),
    ("https://www.abc.net.au/news/2026-10-01/wetlands-restoration-birds-return/104412345?utm_campaign=abc_news",
     "Wetlands restoration brings the birds back - ABC News"),
]


# --- 1. identities: URLs, video ids, near-duplicate titles --------------------------------------------------------
def test_live_repeats_are_the_same_page():
    keys = {NV.url_key(u) for u, _ in LIVE[:3]}
    assert keys == {"en.wikipedia.org/wiki/studio_ghibli"}                       # mobile = desktop
    assert len({NV.url_key(u) for u, _ in LIVE[4:7]}) == 1                      # slash / www / tracking query
    assert len({NV.url_key(u) for u, _ in LIVE[7:9]}) == 1
    assert {NV.title_key(t) for _, t in LIVE[:4]} == {"studio ghibli"}         # " — Wikipedia", "wikipedia" word
    assert NV.url_key("https://www.youtube.com/watch?v=abcDEF12345&t=3") == NV.url_key(
        "https://youtube.com/shorts/abcDEF12345") == "yt:abcDEF12345"
    assert NV.url_key("https://www.tiktok.com/@cat.vids/video/7312345678901234567?lang=en") == "tt:7312345678901234567"


def test_visited_refuses_within_7_days_and_forgets_after():
    clk = Clock()
    v = NV.Visited(clock=clk)
    v.add(*LIVE[0])
    for u, t in LIVE[1:4]:
        assert v.seen(u, t)
    assert v.seen("https://en.wikipedia.org/wiki/Ghibli_Museum", "Studio Ghibli — Wikipedia")   # same title
    assert not v.seen("https://en.wikipedia.org/wiki/Ghibli_Museum", "Ghibli Museum — Wikipedia")
    v2 = NV.Visited(state=v.to_dict(), clock=clk)                                   # saved with the browsing state
    assert v2.seen(*LIVE[2])
    clk.t += NV.REVISIT_S + 1
    assert not v2.seen(*LIVE[0]) and not NV.Visited(state=v.to_dict(), clock=clk).urls


# --- 2. footer, licence, contact, about, privacy, terms and home-page links are never offered ---------------------
@pytest.mark.parametrize("label, href", [
    ("Contact Us", "https://www.abc.net.au/contact"),
    ("ABC", "https://www.abc.net.au/"),
    ("Home", "https://www.abc.net.au/news"),
    ("Creative Commons Attribution-ShareAlike 4.0", "https://creativecommons.org/licenses/by-sa/4.0/"),
    ("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/deed.en"),
    ("Privacy Policy", "https://www.npr.org/about-npr/179878450/privacy-policy"),
    ("Terms of Use", "https://www.npr.org/about-npr/179876898/terms-of-use"),
    ("About Wikipedia", "https://en.wikipedia.org/wiki/Wikipedia:About"),
    ("About MediaWiki.org", "https://www.mediawiki.org/wiki/Project:About"),
    ("Help", "https://en.wikipedia.org/wiki/Help:Contents"),
    ("Cookie statement", "https://foundation.wikimedia.org/wiki/Special:MyLanguage/Policy:Cookie_statement"),
])
def test_footer_links_are_junk(label, href):
    page = "https://www.abc.net.au/news/2026-10-01/wetlands-restoration-birds-return/104412345"
    b = Browser(decide=True)
    sc = b.screens["desk"]
    sc.info = {"title": "Wetlands", "host": "abc.net.au", "kind": "page"}
    raw = [(href, label, 4000, True), ("https://www.abc.net.au/news/2026-10-02/kakadu-fires-season/104419999",
                                        "Kakadu's early fire season is changing the park", 9000, True)]
    hrefs = [l["href"] for l in b.pick_links(raw, page, "text", sc)["links"]]
    assert hrefs == ["https://www.abc.net.au/news/2026-10-02/kakadu-fires-season/104419999"]


def test_a_page_seen_this_week_is_not_offered_as_a_link():
    b = Browser(decide=True)
    sc = b.screens["desk"]
    sc.info = {"title": "Ghibli Museum", "host": "en.wikipedia.org", "kind": "page"}
    b.visited.add(*LIVE[0])
    raw = [("https://en.wikipedia.org/wiki/Studio_Ghibli", "Studio Ghibli", 9000, True),
           ("https://en.wikipedia.org/wiki/Hayao_Miyazaki", "Hayao Miyazaki", 9000, True)]
    links = b.pick_links(raw, "https://en.wikipedia.org/wiki/Ghibli_Museum", "text", sc)["links"]
    assert [l["text"] for l in links] == ["Hayao Miyazaki"]


# --- 3. the live log, replayed through the browser's own open path --------------------------------------------------
def _stub(b, results_by_source=None):
    """The browser without Chromium: _open records the visit and 'shows' it (show() is the real one, minus the
    screenshot); _search_on returns canned results per source."""
    opened, searched = [], []
    sc = b.screens["phone"]

    async def _shoot(sc_):
        return True

    real_open = Browser._open

    async def _open(sc_, url, why, kind, title=None, min_text=80, shoot=True, revisit=False):
        if not revisit and kind != "search" and not b.fresh(url):     # _open's check, before any page load
            b.last_skip = "opened in the last 7 days"
            return False
        if not revisit and kind != "search" and not b.fresh(url, title):   # _settle's, on the loaded page's title
            b.last_skip = "opened in the last 7 days"
            return False
        opened.append(url)
        sc_.info = {"title": title or url, "url": url, "host": browse.urllib.parse.urlsplit(url).hostname,
                    "why": why, "t": 0, "kind": kind}
        return await b.show(sc_)

    async def _search_on(sc_, name, q, why, origin):
        searched.append((name, q))
        res = (results_by_source or {}).get(name)
        if not res:
            b.limits.refuse(name, "no results")
            return False
        sc_.info = {"title": q, "url": f"https://{name}.example/?q={q}", "host": name, "why": why, "t": 0,
                    "kind": "search", "results": res}
        b.limits.count(name, q, origin)
        return True
    b._shoot, b._open, b._search_on = _shoot, _open, _search_on
    assert real_open is not _open
    return sc, opened, searched


def test_replaying_the_live_log_opens_each_page_once():
    b = Browser(decide=True, rng=random.Random(1))
    sc, opened, _ = _stub(b)
    shown = [run(b._open(sc, u, "replay", "page", title=t)) for u, t in LIVE]
    # the 9 live visits were 3 pages: Studio Ghibli, the MediaWiki page, the abc article
    assert shown == [True, False, False, False, True, False, False, True, False]
    assert len(opened) == 3 and b.last_skip == "opened in the last 7 days"


def test_the_real_open_refuses_a_seen_url_before_loading_anything():
    b = Browser(decide=True)
    sc = b.screens["desk"]                                  # no page, no context: loading would raise
    b.visited.add(*LIVE[7])
    assert run(b._open(sc, LIVE[8][0], "again", "page")) is False
    assert b.last_skip == "opened in the last 7 days"


def test_a_tiktok_search_goes_to_the_shorts_feed_never_wikipedia(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    b = Browser(decide=True, rng=random.Random(0))
    sc, opened, searched = _stub(b)
    fed = []

    async def _shorts(sc_, interest, force=False):
        fed.append((sc_.name, interest, force))
        return True
    b._shorts = _shorts
    assert run(b._search(sc, "tiktok videos", "from chat", "chat"))
    assert fed and fed[0][0] == "phone" and fed[0][2] and searched == [] and opened == []
    assert fed[0][1]["query"] is None                       # nothing left but video words: a discovery pick
    assert run(b._search(sc, "funny cat shorts", "", "chat")) and fed[-1][1]["query"] == "funny cat"
    desk = b.screens["desk"]
    assert not run(b._search(desk, "ramen videos", "", "chat"))   # no YouTube key: nothing, not Wikipedia
    assert searched == []


def test_failing_sources_are_set_aside_and_the_rest_rotate():
    clk = Clock()
    b = Browser(decide=True, rng=random.Random(3))
    b.limits = S.Limits(clock=clk)
    sc, opened, searched = _stub(b, {"hn": [{"url": "https://example.org/bread", "title": "Bread at home"}]})
    seeds = []

    async def _seed(sc_, why, *a, **k):
        seeds.append(why)
        return True
    b._seed = _seed
    for _ in range(6):
        run(b._search(sc, "quiet afternoon", "", ""))
    names = [n for n, _ in searched]
    blocked = b.limits.blocked_now()
    assert {"ddg", "bing"} <= set(blocked) and blocked["ddg"]["why"] == "no results"
    for n in blocked:                                       # a set-aside source is not asked again while blocked
        hits = [i for i, x in enumerate(names) if x == n]
        assert len(hits) == S.BLOCK_AFTER
    assert len(set(names)) >= 5                             # rotation through every source that works
    assert b.limits.public()["blocked"] == blocked
    clk.t += S.BLOCK_S + 1
    assert not b.limits.is_blocked("ddg")


def test_rate_limits_never_set_a_source_aside():
    lim = S.Limits(clock=Clock())
    for _ in range(5):
        lim.refuse("ddg", "rate limit")
    assert not lim.blocked_now()
    lim.refuse("ddg", "bot wall")
    lim.count("ddg", "x")                                   # it worked: failures start again
    lim.refuse("ddg", "bot wall")
    assert not lim.blocked_now()


def test_route_never_sends_a_video_search_to_wikipedia_and_keeps_every_source():
    order = S.route("ghibli videos", video=True, rng=random.Random(0))
    assert "youtube" not in order and "wikipedia" not in order       # YouTube: its Data API, never /results
    plain = S.route("quiet afternoon", rng=random.Random(0))
    assert set(S.TAIL) <= set(plain) and "youtube" not in plain and "openlibrary" not in plain   # any-query only
    assert not set(plain) & {"shorts", "tiktok"}


# --- 4. follow-ups at most a quarter, topics not repeated within 2 hours ----------------------------------------------
def test_follow_ups_are_capped_at_a_quarter():
    v = NV.Visited(clock=Clock())
    n = 0
    for i in range(40):
        if v.follow_ok():
            v.search("follow_up")
            n += 1
        else:
            v.search("interests")
    assert n / 40 <= NV.FOLLOW_MAX + 0.01


def test_a_follow_up_over_the_cap_becomes_a_discovery_search():
    b = Browser(decide=True, rng=random.Random(0))
    sc, _, searched = _stub(b, {s: [{"url": "https://example.org/a", "title": "A page"}] for s in S.SOURCES})
    for _ in range(4):
        b.visited.search("follow_up")
    run(b._search(sc, "studio ghibli", "", "follow_up"))
    assert searched[-1][1] != "studio ghibli" and b.visited.origins[-1] == "interests"


def test_discovery_never_picks_a_topic_seen_in_the_last_two_hours():
    clk = Clock()
    v = I.Variety(clock=clk)
    rng = random.Random(0)
    for _ in range(100):                                    # a pick a minute for 100 minutes: every topic new
        p = I.pick(v, rng=rng, discover=True)
        assert p["new"], p
        clk.t += 60
    new = 0
    for _ in range(600):                                    # a long day of picks, 90 s apart
        new += I.pick(v, rng=rng, discover=True)["new"]
        clk.t += 90
    assert new / 600 >= 0.9
    v.mark("music")
    assert I.weights(v)["music"] == pytest.approx(I.weights(I.Variety(clock=clk))["music"] * I.RECENT_W)


def test_queries_are_not_typed_again_within_a_week():
    clk = Clock()
    v = I.Variety(clock=clk)
    rng = random.Random(0)
    qs = [I.pick(v, rng=rng)["query"] for _ in range(60)]
    profile_qs = sum(len(x[1]) for k, x in I.PROFILE.items() if k != "wikipedia")
    assert len(set(qs[:profile_qs])) >= 0.9 * min(60, profile_qs)


def test_front_page_headlines_become_trending_discovery():
    b = Browser(decide=True)
    sc = b.screens["desk"]
    sc.info = {"title": "Hacker News", "host": "news.ycombinator.com", "kind": "page"}
    raw = [("https://news.ycombinator.com/item?id=1", "A new kind of battery made from salt water", 3000, True),
           ("https://news.ycombinator.com/item?id=2", "Show HN: a tiny synth in the browser", 3000, True)]
    b.pick_links(raw, "https://news.ycombinator.com/", "text", sc)
    assert "A new kind of battery made from salt water" in b.variety.trending


# --- 5. the measurement on the real code path (stubbed network) --------------------------------------------------------
def test_shorts_session_measurement():
    """A scroll session of 60 shorts on the real _shorts / pick path with a stubbed network: unique URLs, topic
    repeat rate and new-topic share. Not a live browser: it measures the choice of what to look up."""
    clk = Clock()
    b = Browser(decide=True, rng=random.Random(7))
    b.variety = I.Variety(clock=clk)
    b.visited = NV.Visited(clock=clk)
    queries = []
    n = [0]

    async def _public_videos(sc_, kind, q, why, origin="", short=True):     # the API / embed path, stubbed
        queries.append(q)
        n[0] += 1
        return True
    b._public_videos = _public_videos
    sc = b.screens["phone"]
    interest = {"query": "studio ghibli", "from": "screen", "feed": "shorts"}   # what he saw: a follow-up
    for _ in range(60):
        run(b._shorts(sc, interest))
        clk.t += 40
    topics = [I.topic_of(q) or I.discovery_topic(q) for q in queries]
    new = sum(1 for i, t in enumerate(topics) if t not in topics[max(0, i - 180):i])   # 2 h = 180 clips of 40 s
    follow = sum(1 for q in queries if q == "studio ghibli")
    assert len(queries) == 60 and len(set(queries)) >= 50
    assert new / len(topics) >= 0.6, (new, topics)
    assert follow / len(queries) <= NV.FOLLOW_MAX + 0.02


# live 2026-10-08 10:56-11:01 Tokyo: a failed search opened a site about something else ("Mark Rober" -> timeout.com
# Tokyo, "ramen in Osaka" -> nintendolife.com, "Day Deals" -> nme.com, "discover shop next" -> thedrive.com)
def _no_search(b):
    sc, opened, searched = _stub(b)

    async def _public_videos(*a, **k):
        return False
    b._public_videos = _public_videos
    return sc, opened


@pytest.mark.parametrize("q, hungry", [("Mark Rober", False), ("anime season", False), ("ramen in Osaka", True)])
def test_a_failed_search_falls_back_on_a_site_about_it(q, hungry):
    b = Browser(decide=True, rng=random.Random(5))
    b.hungry = hungry                                                       # (recipe sites: only at meal times)
    sc, opened = _no_search(b)
    topic = I.topic_of(q)
    assert run(b._search(sc, q, "", "chat"))
    assert opened and all(u in browse.SEED_TOPICS[topic] for u in opened), (topic, opened)


def test_a_failed_search_with_no_site_about_it_gives_up():
    b = Browser(decide=True, rng=random.Random(5))
    sc, opened = _no_search(b)
    assert not run(b._search(sc, "quiet afternoon thoughts", "", "chat"))      # no topic: nothing opened
    assert opened == [] and "no site about it" in b.last_skip
    assert not run(b._search(sc, "ramen in Osaka", "", "chat"))              # not hungry: no recipe site, and
    assert opened == []                                                      # not a games site instead
    b.hungry = True
    now = browse.time.time()
    for u in browse.SEED_TOPICS["food"]:                                     # hungry, but its sites all opened lately
        b.seed_t[u] = now
    assert not run(b._search(sc, "ramen in Osaka", "", "chat")) and opened == []


@pytest.mark.parametrize("q", ["Day Deals", "discover shop next", "Summer Sale", "free shipping on sneakers"])
def test_a_shops_words_are_not_interests(q):
    from eyes import query_ok
    assert query_ok(q) is None
    assert query_ok("Kichijoji shops") == "Kichijoji shops"                 # (the walk's street)
    assert S.interest_for(seen={"screen": [q]}, query_ok=query_ok) is None


# live 2026-10-08 04:02: page titles became queries with their site's name ("anime movie — MyAnimeList", "Demon Slayer —
# MyAnimeList", searched on MyAnimeList itself) and a video search was just the site's name ("myanimelist anime")
@pytest.mark.parametrize("q, want", [
    ("anime movie — MyAnimeList", "anime movie"), ("Demon Slayer — MyAnimeList", "Demon Slayer"),
    ("Demon Slayer | MyAnimeList.net", "Demon Slayer"), ("Frieren: Beyond Journey's End - MyAnimeList.net", "Frieren: Beyond Journey's End"),
    ("Inokashira Park - Wikipedia", "Inokashira Park"), ("Spirited Away ｜ YouTube", "Spirited Away"),
    ("Spider-Man", "Spider-Man"), ("Atlas - Bakery", "Atlas - Bakery"), ("studio ghibli", "studio ghibli"),
    ("Mark Rober", "Mark Rober"),
    ("myanimelist anime", None), ("MyAnimeList", None), ("YouTube video", None), ("Wikipedia — the free encyclopedia", None)])
def test_a_page_titles_site_name_is_not_part_of_the_query(q, want):
    from eyes import query_ok
    assert query_ok(q) == want
    it = S.interest_for(seen={"screen": [q]}, query_ok=query_ok)
    assert (it and it["query"]) == (want or None)
