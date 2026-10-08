"""Free browsing (#29): on-site search boxes only, the query filter, cookie banners rejected, the guard kept for the
public screens, pagination / comments / Wikipedia sources, long chains and leaving.

    python -m pytest tests/test_free_browsing.py -q
No network and no AI calls. The Chromium tests use local HTML only and are skipped without a browser.
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import brain_vote as V  # noqa: E402
import browse  # noqa: E402
import eyes as E  # noqa: E402
from browse import (Browser, LOGIN_HREF, choose_dismiss, link_kind, search_field_ok, url_ok)  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def field(**kw):
    """A FIELDS_JS descriptor: a visible, editable text input outside any form, unless told otherwise."""
    d = {"i": 0, "tag": "input", "type": "text", "role": "", "name": "", "id": "", "placeholder": "", "aria": "",
         "title": "", "autocomplete": "", "editable": False, "readonly": False, "visible": True, "form": False,
         "form_action": "", "form_role": "", "form_method": "", "form_id": "", "form_password": False, "form_fields": 0}
    d.update(kw)
    return d


IN_SEARCH_FORM = dict(form=True, form_action="/search", form_method="get", form_fields=1)


# --- 1. site_search types into search inputs only -------------------------------------------------------------------
@pytest.mark.parametrize("f", [
    field(type="search"),                                                        # <input type=search>
    field(role="searchbox", name="query"),
    field(name="q", placeholder="Search…", **IN_SEARCH_FORM),                    # Stack Exchange / old.reddit style
    field(type="search", name="search", id="searchInput", placeholder="Search Wikipedia", form=True,
          form_action="/w/index.php", form_id="searchform", form_method="get", form_fields=1),
    field(name="q", form=True, form_role="search", form_action="/s", form_fields=1),
    field(name="query", aria="Search recipes", form=True, form_action="/find", form_fields=2),
])
def test_search_boxes_are_accepted(f):
    assert search_field_ok(f)


@pytest.mark.parametrize("f", [
    field(type="password", name="password"),
    field(type="email", name="email", placeholder="Search by email"),
    field(type="search", name="email"),                                          # claims search, is an email field
    field(type="search", autocomplete="current-password"),
    field(name="username", placeholder="Username", **IN_SEARCH_FORM),
    field(tag="textarea", name="comment", placeholder="Add a comment"),
    field(tag="textarea", name="q", placeholder="Search"),                       # textareas never
    field(tag="div", editable=True, role="textbox", aria="Message"),
    field(tag="div", editable=True, role="searchbox"),                           # editable divs never
    field(name="comment", placeholder="Write a comment", **IN_SEARCH_FORM),
    field(name="message", placeholder="Send a message", form=True, form_action="/contact", form_fields=3),
    field(name="reply", type="search"),
    field(name="your-name", placeholder="Your name", form=True, form_action="/subscribe", form_fields=2),
    field(name="q", placeholder="Search", form=True, form_action="/search", form_password=True, form_fields=2),
    field(name="q", placeholder="Search", form=True, form_action="/search", form_method="post", form_fields=1),
    field(name="login", placeholder="Log in", form=True, form_action="/login", form_fields=2),
    field(name="cardnumber", autocomplete="cc-number", placeholder="Card number"),
    field(name="coupon", placeholder="Promo code", form=True, form_action="/cart/search", form_fields=1),
    field(type="search", visible=False),                                         # hidden fields never
    field(type="search", readonly=True),
    field(type="hidden", name="q"),
    field(type="number", name="q"),
    field(name="q", placeholder="Search", form=True, form_action="/search", form_fields=6),  # a big form, not a box
    field(name="q"),                                                             # nothing says it is a search
    field(name="title", placeholder="Title", form=True, form_action="/post/new", form_fields=1),
    "not a descriptor",
])
def test_every_other_field_is_refused(f):
    assert not search_field_ok(f)


@pytest.mark.parametrize("q,ok", [("sourdough starter", True), ("Inokashira Park", True), ("ramen history", True),
                                  ("buy crypto now", False), ("$BONK price", False), ("https://evil.example", False),
                                  ("mail me at a@b.co", False), ("porn", False), ("casino bonus", False),
                                  ("a b c d e f g h", False), ("x", False)])
def test_site_search_query_goes_through_the_filter(q, ok):
    page = {"url": "https://cooking.stackexchange.com/", "links": [], "search_box": True}
    out = E.validate([{"action": "site_search", "target": q, "label": f"search for {q}"}], page)
    assert bool(out) == ok
    if ok:
        assert out[0]["target"] == q and "href" not in out[0]


def test_site_search_needs_a_search_box_the_browser_found():
    page = {"url": "https://example.org/", "links": [], "search_box": False}
    assert E.validate([{"action": "site_search", "target": "bread", "label": "search bread"}], page) == []


def test_browser_act_refuses_bad_site_search_queries_in_its_own_process():
    b = Browser(decide=True)
    typed = []

    async def _site_search(sc, q, why):
        typed.append(q)
        return True

    async def _next(sc, heard, interest):
        return False
    b._site_search, b._next = _site_search, _next

    async def main():
        sc = b.screens["desk"]
        for q in ("buy crypto tokens now", "https://evil.example", "send 2 sol", "bread history"):
            sc.page, sc.awaiting = object(), {"links": [], "search_box": True, "host": "example.org"}
            await b.act("desk", {"action": "site_search", "target": q, "label": "x"})
    run(main())
    assert typed == ["bread history"]


# --- 2. banners: reject when there is a reject button ---------------------------------------------------------------
def btns(*labels, consent=True, aria=""):
    return [{"i": i, "label": t, "aria": aria, "consent": consent, "modal": True} for i, t in enumerate(labels)]


@pytest.mark.parametrize("labels,want", [
    (("Accept all", "Reject all", "Manage preferences"), 1),
    (("Accept all cookies", "Necessary cookies only"), 1),
    (("Allow all", "Use necessary cookies only"), 1),
    (("I agree", "Only essential"), 1),
    (("Agree", "Disagree"), 1),
    (("Accept", "Decline"), 1),
    (("Accept all", "Continue without accepting"), 1),
    (("ACCEPT ALL", "REJECT ALL"), 1),
    (("Accept all", "Settings", "×"), 2),                                           # no reject: close, never accept
    (("Accept all", "Got it", "OK"), None),                                         # only accept: hidden, not pressed
    (("Accept & close",), None),
    (("Agree and continue", "Learn more"), None),
])
def test_banner_dismissal_chooses_reject(labels, want):
    assert choose_dismiss(btns(*labels)) == want


def test_modals_are_closed_not_accepted():
    assert choose_dismiss(btns("Subscribe", "No thanks", consent=False)) == 1
    assert choose_dismiss(btns("Sign in", "Not now", consent=False)) == 1
    assert choose_dismiss(btns("", consent=False, aria="Close dialog")) == 0
    assert choose_dismiss(btns("OK", consent=True, aria="Close")) is None              # "OK" on a banner is accept
    assert choose_dismiss(btns("Sign up", "Log in", consent=False)) is None
    assert choose_dismiss([]) is None


# --- 3. the guard: what is newly allowed, what stays blocked ---------------------------------------------------------
@pytest.mark.parametrize("url", [
    "https://old.reddit.com/r/askscience/", "https://www.reddit.com/r/Cooking/comments/abc/how_to_knead/",
    "https://news.ycombinator.com/item?id=4100", "https://cooking.stackexchange.com/questions/1/bread",
    "https://www.youtube.com/watch?v=abc", "https://vimeo.com/123", "https://www.openstreetmap.org/#map=15/35.70/139.57",
    "https://www.seriouseats.com/ramen", "https://www.metmuseum.org/art/collection/search/1", "https://bandcamp.com/",
    "https://www.sussex.ac.uk/research", "https://www.essexwildlife.org.uk/", "https://apnews.com/article/x",
    "https://lobste.rs/s/abc", "https://xkcd.com/1/", "https://en.wikipedia.org/wiki/Bread?page=2",
])
def test_newly_allowed_sites(url):
    assert url_ok(url)


@pytest.mark.parametrize("url", [
    "https://www.pornhub.com/", "https://old.reddit.com.nsfw.example/", "https://www.xvideos.com/", "https://nudes.example/",
    "https://bestgore.com/", "https://www.pokerstars.com/", "https://www.bet365.com/", "https://casino.example/",
    "https://metamask.io/", "https://phantom.app/", "https://www.4chan.org/", "https://kiwifarms.net/",
])
def test_still_blocked_sites(url):
    assert not url_ok(url)


@pytest.mark.parametrize("href", ["https://old.reddit.com/login/", "https://news.ycombinator.com/login?goto=news",
                                  "https://example.org/signup", "https://shop.example/checkout/", "https://x.org/register",
                                  "https://site.example/account/settings", "https://site.example/oauth2/authorize"])
def test_login_signup_and_checkout_stay_blocked(href):
    assert LOGIN_HREF.search(href)
    page = {"url": "https://example.org/", "links": [{"id": "L1", "href": href, "text": "Some interesting page"}]}
    assert E.validate([{"action": "click", "target": "L1", "label": "go"}], page) == []


def test_bot_walls_and_sign_in_walls_are_recognised():
    assert Browser.wall_text("Please verify you are human")
    assert browse.LOGIN_WALL.search("Log in to continue reading")
    assert browse.LOGIN_WALL.search("You must be logged in to view this page")
    assert not browse.LOGIN_WALL.search("How to bake bread at home")


# --- 4. pagination, comments, Wikipedia's external sources ------------------------------------------------------------
@pytest.mark.parametrize("href,label,rel,kind", [
    ("https://news.ycombinator.com/?p=2", "More", "", "next"),
    ("https://old.reddit.com/r/space/?count=25&after=t3_x", "next ›", "nofollow next", "next"),
    ("https://example.org/blog/page/2", "", "next", "next"),
    ("https://example.org/blog/page/2", "Older posts", "", "next"),
    ("https://news.ycombinator.com/item?id=41", "128 comments", "", "comments"),
    ("https://news.ycombinator.com/item?id=41", "discuss", "", "comments"),
    ("https://old.reddit.com/r/space/comments/abc/x/", "1.2k comments", "", "comments"),
    ("https://example.org/post#comments", "View all 12 comments", "", "comments"),
    ("https://example.org/a", "Next generation telescopes", "", None),
    ("https://example.org/comments-policy", "Our policy", "", None),
])
def test_link_kinds(href, label, rel, kind):
    assert link_kind(href, label, rel) == kind


def test_page_links_keep_pagination_comments_and_wikipedia_sources():
    b = Browser(decide=True)
    sc = b.screens["desk"]
    sc.info = {"title": "Bread", "host": "en.wikipedia.org", "kind": "page", "search_box": True}
    sc.history = ["a", "b"]
    sc.chain = 7
    raw = [[f"https://en.wikipedia.org/wiki/Article_{i}", f"Article number {i}", 5000 - i, True, "", False, ""]
           for i in range(60)]
    raw += [["https://www.breadhistory.example.org/history", "History of bread baking", 10, False, "nofollow", True, ""],
            ["https://doi.org/10.1/x", "A study of yeast fermentation", 10, False, "", True, ""],
            ["https://en.wikipedia.org/w/index.php?title=Bread&page=2", "next page", 10, False, "next", False, ""],
            ["https://en.wikipedia.org/wiki/Talk:Bread", "Join the discussion", 10, False, "", False, ""],
            ["https://www.pornhub.com/x", "Something else entirely", 10, False, "", True, ""]]
    page = b.pick_links(raw, "https://en.wikipedia.org/wiki/Bread", "Bread is food.", sc)
    links = page["links"]
    assert len(links) == browse.PAGE_LINKS
    by_href = {l["href"]: l for l in links}
    assert by_href["https://www.breadhistory.example.org/history"]["external"]
    assert by_href["https://doi.org/10.1/x"]["external"]
    assert by_href["https://en.wikipedia.org/w/index.php?title=Bread&page=2"]["next"]
    assert by_href["https://en.wikipedia.org/wiki/Talk:Bread"]["comments"]
    assert "https://www.pornhub.com/x" not in by_href                                    # the guard still applies
    assert [l["id"] for l in links] == [f"L{i + 1}" for i in range(len(links))]
    assert page["search_box"] and page["chain"] == 7 and page["max_chain"] == browse.MAX_CHAIN and page["can_back"]


PAGE = {"url": "https://news.ycombinator.com/", "title": "Hacker News", "host": "news.ycombinator.com", "kind": "page",
        "text": "Stories", "can_back": True, "search_box": True, "chain": 15, "max_chain": 30,
        "links": [{"id": "L1", "href": "https://example.org/bread", "text": "The history of sourdough bread", "area": 900},
                  {"id": "L2", "href": "https://news.ycombinator.com/item?id=1", "text": "88 comments", "comments": True},
                  {"id": "L3", "href": "https://news.ycombinator.com/?p=2", "text": "More", "next": True},
                  {"id": "L4", "href": "https://www.youtube.com/watch?v=x", "text": "Tokyo night walk video",
                   "video": True},
                  {"id": "L5", "href": "https://example.org/maps", "text": "Old maps of Tokyo rivers", "area": 400}]}


def test_new_actions_need_links_of_their_kind():
    items = [{"action": "next_page", "target": "L3", "label": "next page"},
             {"action": "next_page", "target": "L1", "label": "not a next link"},
             {"action": "open_comments", "target": "L2", "label": "read the comments"},
             {"action": "open_comments", "target": "L5", "label": "not comments"},
             {"action": "play_video", "target": "L4", "label": "watch the night walk", "networks": {"visual": 1}},
             {"action": "play_video", "target": "L1", "label": "not a video"},
             {"action": "site_search", "target": "ramen", "label": "search ramen here"},
             {"action": "leave", "label": "go elsewhere"}]
    out = E.validate(items, PAGE)
    assert [(o["action"], o["target"]) for o in out] == [("next_page", "L3"), ("open_comments", "L2"),
                                                         ("play_video", "L4"), ("site_search", "ramen"), ("leave", None)]
    assert out[0]["href"] == "https://news.ycombinator.com/?p=2" and out[-1]["pull"] == 0.5
    prompt = E.prompt(PAGE)
    assert '"comments": true' in prompt and '"next": true' in prompt and '"search_box": true' in prompt
    assert "site_search" in E.SYSTEM and "3 to 6" in E.SYSTEM


def test_up_to_six_options_and_leave_always_offered(tmp_path):
    class Fake:
        name, model = "fake", "fake"

        def ask(self, system, user):
            import json
            return json.dumps({"options": [{"action": "click", "target": "L1", "label": f"opt {i}"} for i in range(1)]
                              + [{"action": "open_comments", "target": "L2", "label": "comments"},
                                 {"action": "next_page", "target": "L3", "label": "next"},
                                 {"action": "play_video", "target": "L4", "label": "video"},
                                 {"action": "click", "target": "L5", "label": "maps"},
                                 {"action": "site_search", "target": "ramen", "label": "search ramen"},
                                 {"action": "scroll", "label": "read on"}]}), 100, 50
    opts, meta = E.Eyes(Fake(), E.Budget(tmp_path / "c.jsonl")).propose(PAGE)
    assert len(opts) == E.MAX_OPTIONS == V.MAX_OPTIONS == 6 and meta["source"] == "ai"
    assert opts[-1]["action"] == "leave"
    local = E.local_options(PAGE, "ramen")
    kinds = {o["action"] for o in local}
    assert len(local) <= 6 and {"open_comments", "next_page", "leave"} <= kinds
    assert kinds & {"site_search", "search"}


def test_costs_unchanged_one_call_per_page_and_caps(tmp_path):
    assert E.MAX_CALLS_PER_HOUR == 30 and E.MAX_USD_PER_DAY == 1.0
    calls = []

    class Fake:
        name, model = "fake", "fake"

        def ask(self, system, user):
            calls.append(1)
            return '{"options": []}', 10, 10
    eyes = E.Eyes(Fake(), E.Budget(tmp_path / "c.jsonl", per_hour=2))
    for i in range(5):
        eyes.propose(dict(PAGE, url=f"https://example.org/{i}"))
        eyes.propose(dict(PAGE, url=f"https://example.org/{i}"))                     # same page: no new call
    assert len(calls) == 2                                                             # the hourly cap holds


# --- 5. long chains, boredom- and taste-driven leaving --------------------------------------------------------------
@pytest.fixture(scope="module")
def brain():
    from brain_sim import Brain
    b = Brain()
    for _ in range(40):
        b.step()
    return b


def _opts():
    return [{"action": "click", "target": "L1", "label": "bread", "networks": {"attention": 0.3}},
            {"action": "leave", "target": None, "label": "wander somewhere else", "networks": {"attention": 0.3},
             "pull": 0.0}]


def _p_leave(brain, mood=None, tastes=None, pull=0.0):
    o = _opts()
    o[1]["pull"] = pull
    d = V.vote(brain.clone(), o, 1.0, mood or {}, tastes, None, np.random.default_rng(0))
    return d["options"][1]["p"], d


def test_leaving_rises_with_boredom_chain_and_bad_tastes(brain):
    base, _ = _p_leave(brain)
    bored, d = _p_leave(brain, {"boredom": 1.0})
    long_chain, _ = _p_leave(brain, pull=1.0)
    bad_page, _ = _p_leave(brain, tastes=[0.0, -0.8])                                 # this page's topics: not paid off
    good_page, _ = _p_leave(brain, tastes=[0.0, 0.8])
    assert bored > base and long_chain > base and bad_page > base > good_page
    assert d["options"][1]["leave_bonus"] == V.LEAVE_BORED
    assert V.leave_bonus({"action": "click", "pull": 1}, {"boredom": 1}) == 0.0
    assert V.leave_bonus({"action": "leave", "pull": float("nan")}, {}) == 0.0


def test_play_video_counts_as_video_in_the_vote(brain):
    o = [{"action": "play_video", "target": "L4", "label": "video", "networks": {"visual": 1.0}}]
    d = V.vote(brain.clone(), o + [{"action": "scroll", "label": "read", "networks": {"language": 0.2}}], 1.0,
               rng=np.random.default_rng(0))
    assert d and len(d["options"]) == 2


def test_chain_ends_after_max_pages():
    b = Browser(decide=True)
    sc = b.screens["desk"]
    sc.page, sc.ctx, sc.chain = SimpleNamespace(url="https://example.org/x"), object(), browse.MAX_CHAIN
    sc.info = {"title": "x", "url": "https://example.org/x", "host": "example.org", "kind": "page", "why": "", "t": 0}
    sc.shot, sc.scrolls_left = b"jpg", 0
    handed, wandered = [], []

    async def ensure(device):
        return sc

    async def page_info(sc_):
        handed.append(1)
        return {"links": [], "can_back": True}

    async def _next(sc_, heard, interest):
        wandered.append(1)
        sc_.chain = 1
        sc_.info = dict(sc_.info, why="curious about bread")
        return True
    b._ensure, b.page_info, b._next = ensure, page_info, _next
    st = run(b.step("desk"))
    assert wandered == [1] and handed == [] and "30 pages in a row" in st["why"] and st["chain"] == 1


def test_act_needs_the_link_flag_in_the_browser_process():
    b = Browser(decide=True)
    opened = []

    async def _open(sc, url, why, kind, **kw):
        opened.append(url)
        return True

    async def _next(sc, heard, interest):
        return False

    async def _play(sc):
        opened.append("played")
    b._open, b._next, b._play_muted = _open, _next, _play

    async def main():
        sc = b.screens["desk"]
        for action in ({"action": "next_page", "href": "https://example.org/bread"},       # not a next link
                       {"action": "open_comments", "href": "https://news.ycombinator.com/?p=2"},
                       {"action": "play_video", "href": "https://example.org/bread"},
                       {"action": "next_page", "href": "https://news.ycombinator.com/?p=2"},
                       {"action": "open_comments", "href": "https://news.ycombinator.com/item?id=1"},
                       {"action": "play_video", "href": "https://www.youtube.com/watch?v=x"}):
            sc.page, sc.awaiting = object(), dict(PAGE)
            await b.act("desk", action)
    run(main())
    assert opened == ["https://news.ycombinator.com/?p=2", "https://news.ycombinator.com/item?id=1",
                      "https://www.youtube.com/watch?v=x", "played"]


def test_seeds_cover_the_open_web_and_pass_the_guard():
    # #89 teen re-seed: the sites people his age read, per interest; cooking sites only when he is hungry
    assert all(url_ok(u) for u in browse.SEEDS) and len(browse.SEEDS) >= 30
    for topic in ("cars", "games", "football", "anime", "music", "tech", "sneakers", "memes", "movies"):
        assert browse.SEED_TOPICS[topic]
    hosts = {browse.urllib.parse.urlsplit(u).hostname for u in browse.SEEDS}
    assert not hosts & {browse.urllib.parse.urlsplit(u).hostname for u in browse.SEED_TOPICS["food"]}
    assert "old.reddit.com" not in hosts                       # robots.txt disallows everything there


# --- 6. in a real Chromium (local HTML only) --------------------------------------------------------------------------
FORM_PAGE = """<title>Recipes</title><p>""" + "Bread and noodles. " * 30 + """</p>
<form action="/login" method="post"><input name="user" placeholder="Username"><input type="password" name="pw"></form>
<form id="comment" action="/comment" method="post"><textarea name="comment" placeholder="Add a comment"></textarea>
  <input name="author" placeholder="Your name"><input type="email" name="email" placeholder="Email"></form>
<input name="newsletter" placeholder="Your email for our newsletter">
<form role="search" action="/search" onsubmit="event.preventDefault(); window.submitted = this.q.value;">
  <input type="search" name="q" placeholder="Search recipes"></form>"""


async def _chromium():
    b = Browser()
    try:
        sc = await b._ensure("desk")
    except Exception as e:                                                             # no usable Chromium here
        pytest.skip(f"chromium did not start: {e!r}"[:200])
    return b, sc


async def _shut(b):
    await b.close()
    if b.pw:
        await b.pw.stop()


def test_chromium_types_only_into_the_search_box(monkeypatch):
    if not Browser.available():
        pytest.skip("playwright not installed")
    monkeypatch.setattr(browse, "SITE_SEARCH_NAV_MS", 300)

    async def main():
        b, sc = await _chromium()
        try:
            async def settle(sc_, why, kind, **kw):
                return True
            b._settle = settle
            await sc.page.set_content(FORM_PAGE)
            fields = await sc.page.evaluate(browse.FIELDS_JS)
            assert [f["name"] for f in fields if search_field_ok(f)] == ["q"]
            assert await b._has_search_box(sc.page)
            assert await b._site_search(sc, "sourdough", "test")
            values = await sc.page.evaluate("() => [...document.querySelectorAll('input, textarea')]"
                                            ".map(e => [e.name, e.value])")
            assert dict(values) == {"user": "", "pw": "", "comment": "", "author": "", "email": "", "newsletter": "",
                                    "q": "sourdough"}
            assert await sc.page.evaluate("() => window.submitted") == "sourdough"       # submitted with Enter
            assert [t["query"] for t in b.typed] == ["sourdough"] and "search" in b.typed[0]["field"]
            # a page with a login form, a comment box and a newsletter field but no search box: nothing is typed
            await sc.page.set_content(FORM_PAGE.split('<form role="search"')[0])
            assert not await b._has_search_box(sc.page)
            assert not await b._site_search(sc, "sourdough", "test") and b.last_skip == "no search box"
            values = await sc.page.evaluate("() => [...document.querySelectorAll('input, textarea')].map(e => e.value)")
            assert values == [""] * 6 and len(b.typed) == 1
        finally:
            await _shut(b)
    run(main())


BANNER = """<title>News</title><p>""" + "Today in Tokyo. " * 40 + """</p>
<div id="cmp" style="position:fixed;bottom:0;left:0;right:0;background:#eee">We use cookies and similar tracking
  with our partners. <button onclick="window.choice='accept'">Accept all</button>
  <button onclick="window.choice='reject'">Reject all</button></div>"""


def test_chromium_rejects_cookie_banners_and_never_accepts():
    if not Browser.available():
        pytest.skip("playwright not installed")

    async def main():
        b, sc = await _chromium()
        try:
            await sc.page.set_content(BANNER)
            await b._dismiss(sc, rounds=1)
            assert await sc.page.evaluate("() => window.choice") == "reject"
            assert b.dismissed[-1]["kind"] == "reject"
            await sc.page.set_content(BANNER.replace("<button onclick=\"window.choice='reject'\">Reject all</button>", ""))
            await sc.page.evaluate("() => { delete window.choice; }")                   # set_content keeps the window
            await b._dismiss(sc, rounds=1)
            assert await sc.page.evaluate("() => window.choice") is None                 # only accept: never pressed
            await sc.page.set_content("<title>x</title><p>" + "story " * 50 + "</p><div role=dialog aria-modal=true>"
                                      "Get our newsletter <button onclick=\"window.choice='sub'\">Subscribe</button>"
                                      "<button aria-label='Close' onclick=\"window.choice='closed'\">×</button></div>")
            await b._dismiss(sc, rounds=1)
            assert await sc.page.evaluate("() => window.choice") == "closed"
            # a sign-in wall is recognised (and left by _settle), never filled in
            await sc.page.set_content("<title>Sign in</title><p>Log in to continue</p><input type=password>")
            assert await b._login_walled(sc.page, "Log in to continue")
        finally:
            await _shut(b)
    run(main())
