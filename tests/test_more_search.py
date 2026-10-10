"""More of the internet (#56): more search sources, routing by topic, per-host rate limits, robots.txt, the guard on
every result, queries from his own sources, follow-up searches from a page's words, and no paid call on results pages.

    python -m pytest tests/test_more_search.py -q
No network and no AI calls: the parsers read saved pages in tests/data/search/ (captured 2026-10-02).
"""
import asyncio
import json
import random
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import browse  # noqa: E402
import eyes as E  # noqa: E402
import search_sources as S  # noqa: E402
from browse import Browser, url_ok  # noqa: E402

DATA = Path(__file__).resolve().parent / "data" / "search"


def fx(name):
    return (DATA / name).read_text(encoding="utf-8")


def run(coro):
    return asyncio.run(coro)


class Clock:
    def __init__(self, t=1_790_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


# --- 1. each source's parser, on saved pages ------------------------------------------------------------------------
@pytest.mark.parametrize("name, fn, base, n, first_url, first_title", [
    ("bing.html", S.parse_bing, "", 10, "https://www.sleepfoundation.org/how-sleep-works/sleep-spindles",
     "What are Sleep Spindles? | Sleep Foundation"),
    ("ddg.html", S.parse_ddg, "", 10, "https://www.justonecookbook.com/melon-pan/", "Melon Pan (Video) メロンパン - Just One Cookbook"),
    ("wikipedia.html", S.parse_wikipedia, "", 10, "https://en.wikipedia.org/wiki/Sleep_spindle", "Sleep spindle"),
    ("commons.html", S.parse_commons, "", 10, "https://commons.wikimedia.org/wiki/File:Inokasira_Park.jpg",
     "Inokasira Park"),
    ("arxiv.html", S.parse_arxiv, "", 8, "https://arxiv.org/abs/2609.00520",
     "A distributed-delay Wilson-Cowan model of sleep-related rhythms in the corticothalamic system"),
    ("hn.json", S.parse_hn, "", 10, "https://github.com/hendricius/the-bread-code/blob/master/basics/sourdough.md",
     "Make your own sourdough"),
    ("openlibrary.json", S.parse_openlibrary, "", 8, "https://openlibrary.org/works/OL151798W", "Goodnight Moon"),
    ("youtube.html", S.parse_youtube, "", 8, "https://www.youtube.com/watch?v=_8rsTkOsI2M",
     "Beginner Guide to Making Ramen Noodles from Scratch"),
    # B3: a site's own results count only when the headline or its excerpt has a word of the query (the apple tart
    # and the pavlovas the recipe site returned for "melon pan" are not results)
    ("recipes.html", S.parse_headlines, "https://www.recipetineats.com/?s=melon+pan", 1,
     "https://www.recipetineats.com/watermelon-salad/", "Watermelon Salad"),
    ("news.html", S.parse_headlines, "https://www.sciencenews.org/?s=sleep+spindles", 7,
     "https://www.sciencenews.org/article/nap-science-sleep-health",
     "To nap or not to nap? Science is still waking up to the question"),
])
def test_parsers_read_saved_result_pages(name, fn, base, n, first_url, first_title):
    res = fn(fx(name), base)
    assert len(res) == n
    assert res[0]["url"] == first_url and res[0]["title"] == first_title
    assert all(r["url"].startswith(("https://", "http://")) and r["title"] for r in res)
    assert len({r["url"] for r in res}) == len(res)                                   # no duplicates


def test_parsers_unwrap_redirects_and_keep_snippets():
    bing = S.parse_bing(fx("bing.html"))
    assert not any("bing.com" in r["url"] for r in bing)                              # ck/a?u=a1<base64> decoded
    assert "non-rapid eye movement" in bing[0]["snippet"]
    ddg = S.parse_ddg(fx("ddg.html"))
    assert not any("duckduckgo.com" in r["url"] for r in ddg) and ddg[0]["snippet"].startswith("Make homemade")
    assert S.parse_wikipedia(fx("wikipedia.html"))[0]["snippet"].startswith("between sleep spindles and memory")
    assert S.parse_arxiv(fx("arxiv.html"))[0]["snippet"].startswith("The corticothalamic circuit")
    assert S.parse_hn(fx("hn.json"))[0]["snippet"] == "619 points on Hacker News"
    assert S.parse_openlibrary(fx("openlibrary.json"))[0]["snippet"] == "Margaret Wise Brown · 1947"
    yt = S.parse_youtube(fx("youtube.html"))
    assert all(r["video"] for r in yt) and yt[0]["channel"] == "Way of Ramen" and "10:01" in yt[0]["snippet"]
    assert all(r.get("image") for r in S.parse_commons(fx("commons.html")))
    news = S.parse_headlines(fx("news.html"), "https://www.sciencenews.org/?s=sleep+spindles")
    assert all(r["url"].startswith("https://www.sciencenews.org/") for r in news)      # only the site's own articles
    assert news[0]["snippet"].startswith("Many people struggle to sleep")


def test_parsers_survive_junk_and_bot_checks():
    for fn in (S.parse_bing, S.parse_ddg, S.parse_wikipedia, S.parse_commons, S.parse_arxiv, S.parse_youtube):
        assert fn("") == [] and fn("<html><body><p>nothing</p>") == [] and fn("<div><a href=x>") == []
    for fn in (S.parse_hn, S.parse_openlibrary):
        assert fn("") == [] and fn("not json") == [] and fn("[1, 2]") == [] and fn('{"hits": [1, {}]}') == []
    challenge = fx("ddg_challenge.html")                    # DuckDuckGo's "select all squares containing a duck"
    assert S.parse_ddg(challenge) == []
    text = " ".join(S.parse_html(challenge).text().split())
    assert Browser.wall_text(text)                          # recognised as a bot check: left, never solved
    assert S.bing_target("https://www.bing.com/ck/a?!&u=a1aHR0cHM6Ly9leGFtcGxlLm9yZy8") == "https://example.org/"
    assert S.bing_target("https://www.bing.com/ck/a?!&p=x") == ""
    assert S.ddg_target("//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fa&rut=x") == "https://example.org/a"


def test_every_source_is_free_safe_and_reachable_by_the_guard():
    assert set(S.SOURCES) == {"bing", "ddg", "wikipedia", "commons", "arxiv", "hn", "openlibrary", "youtube",
                              "recipes", "news", "shorts", "tiktok",
                              "carscoops", "pcgamer", "mal", "tmdb", "nme", "9to5mac"}     # #89 teen interests
    for name, src in S.SOURCES.items():
        urls = [src["site"]] if src.get("site") else [src["url"]("sleep spindles")] + (
            [src["api"]("sleep spindles")] if src.get("api") else [])
        assert all(url_ok(u) and u.startswith("https://") for u in urls), name
        assert not any(k in u for u in urls for k in ("key=", "token=", "login", "signin")), name
    assert "adlt=strict" in S.SOURCES["bing"]["url"]("x") and "kp=1" in S.SOURCES["ddg"]["url"]("x")
    assert S.SOURCES["openlibrary"]["url"]("haruki murakami novels") == "https://openlibrary.org/subjects/haruki_murakami"
    # robots.txt (2026-10-02): Open Library disallows /search, AP News its search page: not used as sources
    assert "/search" not in S.SOURCES["openlibrary"]["api"]("sleep") and "apnews" not in json.dumps(
        {k: v.get("site", "") for k, v in S.SOURCES.items()})


# --- 2. routing by topic, rotation ----------------------------------------------------------------------------------
@pytest.mark.parametrize("q, first", [
    ("sleep spindles", "arxiv"), ("neural network memory", "arxiv"), ("haruki murakami novels", "openlibrary"),
    ("Inokashira Park photos", "commons"), ("python compiler", "hn"), ("lo-fi music", "nme"),
    ("history of Kichijoji", "wikipedia"), ("melon pan recipe", "ddg"), ("latest news scientists", "arxiv"),
    ("One Piece latest chapter", "mal"), ("Toyota GR Supra", "carscoops"), ("Elden Ring", "pcgamer"),
    ("iPhone 17", "9to5mac"), ("Netflix series", "tmdb"),
])
def test_routing_by_topic(q, first):
    order = S.route(q, S.Limits(clock=Clock()), random.Random(0))
    assert order[0] == first
    assert set(S.GENERAL) <= set(order)                     # the general engines stay as fallbacks


def test_how_to_goes_to_a_general_engine_and_unknown_topics_rotate():
    assert S.route("how to fix a bike chain", rng=random.Random(0))[0] in ("ddg", "bing")
    firsts = {S.route("quiet afternoon", rng=random.Random(i))[0] for i in range(30)}
    assert firsts == set(S.GENERAL)                         # no single engine gets all the plain queries
    # youtube.com/robots.txt disallows /results: YouTube is never a routed source (its Data API is, with the key)
    assert "youtube" not in S.route("quiet afternoon") and "youtube" not in S.route("quiet afternoon", video=True)
    assert "openlibrary" not in S.route("books")            # nothing left to look up by subject


def test_rotation_moves_traffic_off_a_busy_source():
    lim = S.Limits(clock=Clock())
    for _ in range(4):
        lim.count("arxiv", "sleep spindles")
    assert S.route("sleep spindles", lim, random.Random(0))[0] != "arxiv"
    counts = {}
    for i in range(60):                                     # many science queries in an hour: spread over sources
        name = S.route("sleep spindles", lim, random.Random(i))[0]
        lim.count(name, "sleep spindles")
        counts[name] = counts.get(name, 0) + 1
    assert len(counts) >= 3 and max(counts.values()) < 40


# --- 3. per-host rate limits and counts ------------------------------------------------------------------------------
def test_per_host_rate_limit_and_counts():
    clock = Clock()
    lim = S.Limits(clock=clock)
    assert S.PER_HOST_HOUR == 20
    for _ in range(20):
        assert lim.allow("arxiv.org")
        lim.note("arxiv.org")
    assert not lim.allow("arxiv.org") and lim.allow("export.arxiv.org")
    assert "arxiv" not in S.route("sleep spindles", lim, random.Random(0))     # over its limit: left out
    clock.t += 1800
    assert not lim.allow("arxiv.org")
    clock.t += 1801
    assert lim.allow("arxiv.org") and lim.used("arxiv.org") == 0               # a rolling hour
    for _ in range(20):
        lim.note("hn.algolia.com")
    assert not lim.source_ok("hn")                           # the API host counts for the source


def test_counts_per_tokyo_day_survive_a_restart():
    clock = Clock()
    lim = S.Limits(clock=clock)
    lim.count("arxiv", "sleep spindles", "mind")
    lim.count("ddg", "melon pan", "chat")
    lim.count("ddg", "ramen", "familiar")
    lim.note("html.duckduckgo.com")
    lim.refuse("openlibrary", "robots.txt")
    again = S.Limits(clock=clock, state=json.loads(json.dumps(lim.to_dict())))
    pub = again.public()
    assert pub["per_source_today"] == {"ddg": 2, "arxiv": 1} and pub["total_today"] == 3
    assert pub["labels"]["ddg"] == "DuckDuckGo" and pub["per_host_last_hour"] == {"html.duckduckgo.com": 1}
    assert pub["refused_today"] == {"openlibrary: robots.txt": 1} and pub["per_host_limit"] == 20
    assert pub["recent"][-1]["label"] == "DuckDuckGo" and pub["recent"][0]["from"] == "mind"
    clock.t += 86400                                        # the next Tokyo day starts from zero
    assert again.public()["per_source_today"] == {} and again.public()["refused_today"] == {}
    assert S.Limits(state={"hits": {"x": ["bad"]}, "today": {"ddg": "x"}}).public()["total_today"] == 0


# --- 4. robots.txt ---------------------------------------------------------------------------------------------------
OPENLIBRARY_ROBOTS = "User-agent: *\nDisallow: /api\nDisallow: /search\nDisallow: /account\n"
RECIPES_ROBOTS = "User-agent: *\nDisallow: /?s=\nDisallow: /search/\n"


def test_robots_rules():
    r = S.Robots(clock=Clock())
    r.load("openlibrary.org", 200, OPENLIBRARY_ROBOTS)
    assert not r.allowed("https://openlibrary.org/search?q=murakami")
    assert not r.allowed("https://openlibrary.org/search.json?q=murakami")
    assert r.allowed("https://openlibrary.org/subjects/sleep.json?limit=12")
    r.load("www.justonecookbook.com", 200, RECIPES_ROBOTS)
    assert not r.allowed("https://www.justonecookbook.com/?s=melon+pan")
    r.load("hn.algolia.com", 404, "")
    assert r.allowed("https://hn.algolia.com/api/v1/search?query=x")       # no robots.txt: allowed
    r.load("closed.example", 403, "")
    assert not r.allowed("https://closed.example/")         # 401/403: refused
    assert r.allowed("https://never-fetched.example/") is None
    r.load("flaky.example", 0, "")                          # unreachable: refused, but only for 10 minutes
    assert not r.allowed("https://flaky.example/") and r.known("flaky.example")
    r.clock.t += S.ROBOTS_RETRY_S + 1
    assert not r.known("flaky.example") and r.known("closed.example")


def test_robots_fetched_once_per_host_and_counted():
    clock, lim, fetched = Clock(), None, []
    lim = S.Limits(clock=clock)
    r = S.Robots(clock=clock)

    async def fetch(url):
        fetched.append(url)
        return 200, OPENLIBRARY_ROBOTS

    async def main():
        a = await r.check("https://openlibrary.org/subjects/sleep", fetch, lim)
        b = await r.check("https://openlibrary.org/search?q=x", fetch, lim)
        c = await r.check("https://openlibrary.org/subjects/bread.json", fetch, lim)
        return a, b, c
    assert run(main()) == (True, False, True)
    assert fetched == ["https://openlibrary.org/robots.txt"] and lim.used("openlibrary.org") == 1
    clock.t += S.ROBOTS_TTL_S + 1                           # once a day
    assert run(r.check("https://openlibrary.org/subjects/sleep", fetch, lim)) and len(fetched) == 2


def test_site_search_url_for_the_robots_check():
    f = {"form": True, "form_action": "https://www.recipetineats.com/", "name": "s"}
    assert Browser.site_search_url("https://www.recipetineats.com/", f, "melon pan") == \
        "https://www.recipetineats.com/?s=melon+pan"
    assert Browser.site_search_url("https://www.sciencenews.org/x", {"form": True, "form_action": "/search",
                                                                     "name": "q"}, "sleep") == \
        "https://www.sciencenews.org/search?q=sleep"
    assert Browser.site_search_url("about:blank", f, "x") is None              # local pages: nothing to check


def test_site_search_refused_by_robots_types_nothing():
    b = Browser(decide=True)
    typed = []
    box = SimpleNamespace(evaluate=None, fill=None)
    field = {"i": 0, "tag": "input", "type": "search", "role": "", "name": "s", "id": "", "placeholder": "Search",
             "aria": "", "title": "", "autocomplete": "", "editable": False, "readonly": False, "visible": True,
             "form": True, "form_action": "https://www.justonecookbook.com/", "form_role": "search",
             "form_method": "get", "form_id": "", "form_password": False, "form_fields": 1}

    async def page_eval(js, *a):
        return [field]

    async def box_eval(js):
        return field

    async def fill(q):
        typed.append(q)
    box.evaluate, box.fill = box_eval, fill
    page = SimpleNamespace(url="https://www.justonecookbook.com/", evaluate=page_eval,
                           locator=lambda sel: SimpleNamespace(first=box))
    sc = SimpleNamespace(page=page, name="desk")
    b.robots.load("www.justonecookbook.com", 200, RECIPES_ROBOTS)
    assert not run(b._site_search(sc, "melon pan", "test"))
    assert typed == [] and b.typed == [] and b.last_skip == "robots.txt"


# --- 5. the guard on the new sources ---------------------------------------------------------------------------------
def test_guard_on_results():
    res = [{"url": "https://www.justonecookbook.com/melon-pan/", "title": "Melon Pan", "snippet": "Sweet bread"},
           {"url": "https://www.pornhub.com/x", "title": "Bread"},
           {"url": "https://example.org/a", "title": "Free nudes here"},
           {"url": "https://www.binance.com/en/trade", "title": "Trade now"},
           {"url": "https://example.org/login", "title": "Sign in to read"},
           {"url": "http://127.0.0.1:8080/admin", "title": "Admin"},
           {"url": "http://localhost/x", "title": "Local"},
           {"url": "https://example.org/file.pdf", "title": "A paper"},
           {"url": "https://example.org/ok", "title": "Bread history", "snippet": "visit casino tonight"},
           {"url": "https://www.youtube.com/watch?v=abcdefg", "title": "Buy $SOL now", "video": True},
           {"url": "javascript:alert(1)", "title": "x"}]
    safe = Browser.safe_results(res)
    assert [r["url"] for r in safe] == ["https://www.justonecookbook.com/melon-pan/", "https://example.org/ok"]
    assert safe[0]["snippet"] == "Sweet bread" and safe[1]["snippet"] == ""   # a blocked snippet is dropped


def test_results_page_for_the_eyes_holds_only_guarded_results():
    b = Browser(decide=True)
    sc = b.screens["desk"]
    sc.info = {"title": "melon pan — DuckDuckGo", "kind": "search", "host": "html.duckduckgo.com",
               "results": S.parse_ddg(fx("ddg.html")) + [{"url": "https://xvideos.com/a", "title": "melon"}],
               "search": {"source": "ddg", "engine": "DuckDuckGo", "query": "melon pan", "from": ""}}
    page = b.result_page(sc, "https://html.duckduckgo.com/html/?q=melon+pan")
    assert len(page["links"]) == 10 and all(l["result"] for l in page["links"])
    assert not any("xvideos" in l["href"] for l in page["links"])
    assert page["links"][0]["id"] == "L1" and page["links"][0]["host"] == "justonecookbook.com"
    assert page["kind"] == "search" and not page["search_box"] and "Melon Pan" in page["text"]


# --- 6. a search on a source, end to end (stubbed browser) ------------------------------------------------------------
class FakePage:
    def __init__(self, html_by_url):
        self.html_by_url, self.url = html_by_url, "about:blank"

    async def content(self):
        return self.html_by_url.get(self.url, "")


def _stub_browser(html_by_url, robots=None, api=None):
    b = Browser(decide=True, rng=random.Random(0))
    sc = b.screens["desk"]
    sc.page, sc.ctx = FakePage(html_by_url), object()
    opened = []

    async def _open(sc_, url, why, kind, title=None, min_text=80, shoot=True):
        opened.append(url)
        sc_.page.url = url
        sc_.info = {"title": title or url, "url": url, "host": browse.urllib.parse.urlsplit(url).hostname,
                    "why": why, "t": 0, "kind": kind}
        return True

    async def show(sc_):
        b.log.append({"url": sc_.info["url"], "why": sc_.info["why"], "title": sc_.info["title"]})
        return True

    async def _leave(sc_):
        return False

    async def _fetch(sc_, url, hops=3):
        if url.endswith("/robots.txt"):
            host = browse.urllib.parse.urlsplit(url).hostname
            return (200, robots[host]) if robots and host in robots else (404, "")
        return (200, api.get(url, "")) if api and url in api else (404, "")
    b._open, b.show, b._leave, b._fetch = _open, show, _leave, _fetch
    return b, sc, opened


def test_search_on_arxiv_shows_engine_query_and_origin():
    url = S.SOURCES["arxiv"]["url"]("sleep spindles")
    b, sc, opened = _stub_browser({url: fx("arxiv.html")})
    ok = run(b._search_on(sc, "arxiv", "sleep spindles", S.ORIGINS["mind"], "mind"))
    assert ok and opened == [url]
    assert sc.info["why"] == "searched arXiv for “sleep spindles” — from his reading notes"
    assert sc.info["kind"] == "search" and len(sc.info["results"]) == 8
    assert sc.info["search"] == {"source": "arxiv", "engine": "arXiv", "query": "sleep spindles",
                                 "from": "from his reading notes"}
    assert b.log[-1]["search"]["engine"] == "arXiv"
    pub = b.limits.public()
    assert pub["per_source_today"] == {"arxiv": 1} and pub["per_host_last_hour"]["arxiv.org"] == 2   # robots + page
    assert b.to_dict()["searches"]["today"] == {"arxiv": 1}


def test_search_on_an_api_source_reads_the_json_and_shows_the_page():
    url, api = S.SOURCES["hn"]["url"]("sourdough"), S.SOURCES["hn"]["api"]("sourdough")
    b, sc, opened = _stub_browser({}, api={api: fx("hn.json")})
    assert run(b._search_on(sc, "hn", "sourdough", "", ""))
    assert opened == [url] and sc.info["results"][0]["title"] == "Make your own sourdough"
    assert b.limits.used("hn.algolia.com") == 3              # robots.txt + API + the page shown


def test_robots_refusal_falls_through_to_the_next_source():
    q = "haruki murakami books"
    order = S.route(q, rng=random.Random(0))
    assert order[0] == "openlibrary"
    second = S.SOURCES[order[1]]["url"](q)
    parse_fixture = {"wikipedia": "wikipedia.html", "ddg": "ddg.html", "bing": "bing.html"}[order[1]]
    b, sc, opened = _stub_browser({second: fx(parse_fixture)},
                                  robots={"openlibrary.org": "User-agent: *\nDisallow: /subjects\n"})
    b.rng = random.Random(0)
    assert run(b._search(sc, q, "a word a viewer taught him", "taught"))
    assert opened == [second] and sc.info["search"]["source"] == order[1]
    assert b.limits.public()["refused_today"] == {"openlibrary: robots.txt": 1}


def test_no_results_tries_the_next_source():
    q = "sleep spindles"
    b, sc, opened = _stub_browser({})                       # every page empty
    assert not run(b._search_on(sc, "arxiv", q, "", ""))
    assert b.last_skip == "no results" and b.limits.public()["per_source_today"] == {}


# --- 7. queries from him ---------------------------------------------------------------------------------------------
def test_interest_draws_from_all_his_sources():
    seen = {}
    for i in range(400):
        it = S.interest_for(mind=[{"query": "sleep spindles memory"}, {"query": "bread fermentation"}],
                            reading="Inokashira Park", taught=["melon pan"], tastes=["ramen"],
                            rng=random.Random(i), query_ok=E.query_ok)
        seen[it["from"]] = seen.get(it["from"], 0) + 1
    assert set(seen) == {"mind", "reading", "taught", "tastes"}
    assert seen["mind"] > seen["taught"] > seen["reading"] * 0.9 and seen["mind"] > 140   # weights 3 : 1.5 : 1 : 1
    assert S.interest_for(rng=random.Random(0)) is None


def test_interest_queries_go_through_the_filter():
    for i in range(50):
        it = S.interest_for(taught=["buy $BONK now", "http://spam.example", "melon pan"], tastes=["casino"],
                            rng=random.Random(i), query_ok=E.query_ok)
        assert it == {"query": "melon pan", "from": "taught"}


def test_live_interest_reads_the_live_server():
    class FakeMind:
        def next_interest(self, *a, **k):
            return []
    live = SimpleNamespace(
        mind=object(), interest=(0, [{"query": "sleep spindles dreams"}]), mind_interest=lambda: "sleep spindles dreams",
        clock=SimpleNamespace(now=lambda: 1_000_000.0),
        memory=SimpleNamespace(items=[{"source": "taught", "text": "onigiri", "t": 999_000.0},
                                      {"source": "taught", "text": "too old", "t": 1.0},
                                      {"source": "chat", "text": "hello", "t": 999_999.0}]),
        tastes=SimpleNamespace(top=lambda n=8: {"favoured": [{"topic": "ramen", "kind": "word"},
                                                             {"topic": "reward", "kind": "network"}]}))
    got = {S.live_interest(live, {"title": "Kichijoji"}, random.Random(i))["query"] for i in range(200)}
    assert got == {"sleep spindles dreams", "Kichijoji", "onigiri", "ramen"}
    broken = SimpleNamespace(mind=None)                     # nothing to read: no query, never an exception
    got = S.live_interest(broken, None, random.Random(0))
    assert got["query"] == "" and 0 <= got["hour"] < 24 and "feed" in got


@pytest.mark.parametrize("text, q", [
    ("look up melon pan", "melon pan"), ("Look up the Ghibli Museum please!", "Ghibli Museum"),
    ("what is a sleep spindle?", "sleep spindle"), ("can you search for tokyo trains", "tokyo trains"),
    ("@sub01 tell me about bread", "bread"), ("who was Hokusai", "Hokusai"),
    ("hello sub01", None), ("I love ramen", None), ("look", None),
])
def test_chat_wishes(text, q):
    assert S.wish(text) == q


def test_next_searches_a_chat_wish_and_says_where_it_came_from():
    b = Browser(decide=True, rng=random.Random(0))
    sc = b.screens["desk"]
    calls = []

    async def _search(sc_, q, why="", origin=""):
        calls.append((q, why, origin))
        return True
    b._search = _search
    run(b._next(sc, ["look up melon pan please"], None))
    run(b._next(sc, ["look up buy $BONK now"], None))       # the filter refuses the wish: old keyword search
    assert calls[0] == ("melon pan", "a viewer's wish in chat: “look up melon pan please”", "chat")
    assert calls[1][2] == "chat" and "$" not in calls[1][0] and "bonk" in calls[1][0]
    b.rng = SimpleNamespace(random=lambda: 0.5, choice=random.Random(0).choice)    # the search branch
    run(b._next(sc, [], {"query": "sleep spindles", "from": "mind"}))
    run(b._next(sc, [], "Kichijoji"))
    run(b._next(sc, [], {"query": "x" * 200, "from": "mind", "hour": 20}))           # refused: one of his interests
    assert calls[2] == ("sleep spindles", "from his reading notes", "mind")
    assert calls[3] == ("Kichijoji", "curious about “Kichijoji”", "")
    assert calls[4][2] == "interests" and calls[4][1].startswith("one of his interests (")
    assert calls[4][1].endswith(", evening)")


def test_act_search_marks_follow_ups():
    b = Browser(decide=True)
    calls = []

    async def _search(sc_, q, why="", origin=""):
        calls.append((q, why, origin))
        return True
    b._search = _search
    sc = b.screens["desk"]
    for label in ("look up Ghibli Museum", "search bread"):
        sc.page, sc.awaiting = object(), {"links": [], "can_back": False}
        run(b.act("desk", {"action": "search", "target": "Ghibli Museum", "label": label}, "his brain picked it"))
    assert calls[0] == ("Ghibli Museum", "a follow-up from the page — his brain picked it", "follow_up")
    assert calls[1][2] == "page"


# --- 8. follow-up searches from the page's own words ------------------------------------------------------------------
ARTICLE = {"url": "https://en.wikipedia.org/wiki/Inokashira_Park", "title": "Inokashira Park - Wikipedia",
           "host": "en.wikipedia.org", "kind": "page", "can_back": True, "search_box": False, "chain": 3,
           "max_chain": 30,
           "text": "Inokashira Park is a park in Kichijoji, Musashino. It opened in 1917 and holds the Inokashira Park "
                   "Zoo. The Ghibli Museum sits at its south end; the Ghibli Museum was designed by Hayao Miyazaki. "
                   "Its pond is the source of the Kanda River. The pond is fed by groundwater; groundwater levels fell "
                   "in the 1960s.",
           "links": [{"id": "L1", "href": "https://en.wikipedia.org/wiki/Kichijoji", "text": "Kichijoji station area",
                      "area": 900},
                     {"id": "L2", "href": "https://en.wikipedia.org/wiki/Kanda_River", "text": "Kanda River history",
                      "area": 400}]}


def test_follow_ups_come_from_the_page_words():
    fs = S.follow_ups(ARTICLE, query_ok=E.query_ok)
    assert fs == [{"query": "Ghibli Museum", "label": "look up Ghibli Museum", "kind": "entity"},
                  {"query": "what is groundwater", "label": "what is groundwater?", "kind": "term"}]
    assert all(f["query"].split()[-1].lower() in ARTICLE["text"].lower() for f in fs)
    assert not any("Inokashira Park" == f["query"] for f in fs)                  # not the page's own subject
    assert S.follow_ups({"title": "x", "text": "plain words only here."}) == []
    assert S.FOLLOW_LABEL.match("what is groundwater?") and S.FOLLOW_LABEL.match("look up Ghibli Museum")


def test_eyes_add_up_to_two_follow_ups_and_keep_leave(tmp_path):
    calls = []

    class Fake:
        name, model = "fake", "fake"

        def ask(self, system, user):
            calls.append(1)
            return json.dumps({"options": [{"action": "click", "target": "L1", "label": "Kichijoji"},
                                           {"action": "click", "target": "L2", "label": "Kanda River"},
                                           {"action": "search", "target": "Tokyo parks", "label": "search parks"},
                                           {"action": "scroll", "label": "read on"},
                                           {"action": "back", "label": "back"},
                                           {"action": "leave", "label": "elsewhere"}]}), 100, 50
    opts, meta = E.Eyes(Fake(), E.Budget(tmp_path / "c.jsonl")).propose(ARTICLE)
    assert len(calls) == 1 and meta["source"] == "ai" and len(opts) == E.MAX_OPTIONS
    assert opts[-1]["action"] == "leave"
    follow = [o for o in opts if o["action"] == "search" and S.FOLLOW_LABEL.match(o["label"])]
    assert [o["target"] for o in follow] == ["Ghibli Museum", "what is groundwater"]
    assert opts[0]["target"] == "L1"                        # the AI's own first options stay
    local, _ = E.Eyes(None).propose(ARTICLE, {"query": "parks", "from": "mind"})
    assert any(S.FOLLOW_LABEL.match(o["label"]) for o in local) and local[-1]["action"] == "leave"


# --- 9. results pages: options built locally, no paid call -------------------------------------------------------------
def _results_page(query="sleep spindles", fixture="bing.html", fn=S.parse_bing):
    b = Browser(decide=True)
    sc = b.screens["desk"]
    sc.info = {"title": f"{query} — Bing", "kind": "search", "host": "bing.com", "results": fn(fx(fixture)),
               "search": {"source": "bing", "engine": "Bing", "query": query, "from": ""}}
    sc.history = ["https://a.example/", "https://www.bing.com/search?q=x"]
    return b.result_page(sc, "https://www.bing.com/search?q=sleep+spindles")


def test_results_pages_make_no_paid_call(tmp_path):
    calls = []

    class Fake:
        name, model = "fake", "fake"

        def ask(self, system, user):
            calls.append(1)
            return '{"options": []}', 10, 10
    budget = E.Budget(tmp_path / "c.jsonl")
    eyes = E.Eyes(Fake(), budget)
    page = _results_page()
    for _ in range(5):
        opts, meta = eyes.propose(page, {"query": "sleep spindles", "from": "mind"})
    assert calls == [] and budget.rows() == [] and budget.summary()["calls_today"] == 0
    assert meta["source"] == "local" and "no AI call" in meta["why_local"]
    clicks = [o for o in opts if o["action"] == "click"]
    assert len(clicks) == E.RESULT_OPTIONS and opts[-1]["action"] == "leave"
    assert all(o["href"] in {l["href"] for l in page["links"]} for o in clicks)
    assert clicks[0]["label"].startswith("What are Sleep Spindles")
    assert all(o["networks"] for o in opts)                 # tagged by the lexicon
    assert any(o["action"] == "back" for o in opts) or any(o["action"] == "search" for o in opts)
    eyes.propose(dict(ARTICLE, url="https://example.org/content"))   # a content page still gets its one call
    assert calls == [1]


def test_result_options_use_snippets_for_networks_and_open_videos():
    page = _results_page("ramen making", "youtube.html", S.parse_youtube)
    opts = E.result_options(page, "ramen")
    assert [o["action"] for o in opts[:E.RESULT_OPTIONS]] == ["open_video"] * E.RESULT_OPTIONS
    assert all("youtube.com/watch" in o["href"] for o in opts[:E.RESULT_OPTIONS])
    assert E.is_results_page(page) and not E.is_results_page(ARTICLE)


def test_results_page_options_refine_from_result_words():
    page = _results_page("melon pan", "ddg.html", S.parse_ddg)
    opts = E.result_options(page, None)
    refine = [o for o in opts if o["action"] == "search"]
    assert len(refine) <= 1
    for o in refine:
        assert S.FOLLOW_LABEL.match(o["label"]) and o["target"].lower() != "melon pan"


# --- 10. the browser service reports and restores the counts -----------------------------------------------------------
def test_service_state_reports_search_counts_and_init_restores_them():
    from aiohttp.test_utils import TestClient, TestServer
    from browse_service import make_app
    saved = S.Limits()
    saved.count("arxiv", "sleep spindles", "mind")
    b = Browser(decide=True)

    async def main():
        client = TestClient(TestServer(make_app(b, token="t")))
        await client.start_server()
        try:
            h = {"X-Browse-Token": "t"}
            r = await client.post("/init", json={"state": {"log": [], "used": [], "searches": saved.to_dict()}},
                                  headers=h)
            assert (await r.json())["applied"]
            st = await (await client.get("/state", headers=h)).json()
            return st
        finally:
            await client.close()
    st = run(main())
    assert st["search_counts"]["per_source_today"] == {"arxiv": 1}
    assert st["searches"]["today"] == {"arxiv": 1}           # the raw state the live server saves
