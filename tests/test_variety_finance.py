"""#56 scope extension: browse like a real young guy. Interest profile and daily rhythm, variety, YouTube Shorts and
TikTok on the phone (muted, bounded, walls left), queries from things he saw, "on his mind" from what he really reads,
and (S2) trading hosts and price / chart / ticker titles refused while neutral market news stays readable (no money
actions, the harmful categories kept).

    python -m pytest tests/test_variety_finance.py -q
No network and no AI calls. tests/data/search/youtube_shorts.html is a trimmed real capture (2026-10-02);
tiktok_tag.html is synthetic (TikTok could not be captured from the sandbox) and says so.
"""
import asyncio
import json
import random
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import browse  # noqa: E402
import eyes as E  # noqa: E402
import interests as I  # noqa: E402
import research as R  # noqa: E402
import search_sources as S  # noqa: E402
import short_videos as SV  # noqa: E402
from browse import Browser, url_ok  # noqa: E402

DATA = Path(__file__).resolve().parent / "data" / "search"


def fx(name):
    return (DATA / name).read_text(encoding="utf-8")


def run(coro):
    return asyncio.run(coro)


class Clock:
    def __init__(self, t=1_790_982_000.0):
        self.t = t

    def __call__(self):
        return self.t


# --- A. interest profile, rhythm, variety ----------------------------------------------------------------------------
def test_profile_covers_a_young_guys_interests():
    # #89 teen re-seed (docs/research/teen_online.md); no money or crypto topics; food only while hungry
    for want in ("games", "music", "creators", "football", "cars", "anime", "tech", "sneakers", "memes", "movies",
                 "tokyo", "science", "food", "wikipedia"):
        assert want in I.PROFILE
    assert not {"crypto", "markets"} & set(I.PROFILE)
    assert I.PROFILE["wikipedia"][0] < min(w for k, (w, _, _) in I.PROFILE.items() if k not in ("wikipedia", "food"))
    assert I.weights(hour=12.5)["food"] == 0 and I.weights(hour=12.5, hungry=True)["food"] > 1
    assert all(E.query_ok(q) for _, qs, _ in I.PROFILE.values() for q in qs)        # every seed query is typeable


@pytest.mark.parametrize("hour, name, top, feed", [
    (8, "morning", ("football", "tech", "music"), None), (12.5, "lunch", ("memes", "creators"), "shorts"),
    (15, "afternoon", ("games", "cars"), None), (20, "evening", ("games",), None),
    (1, "late night", ("memes", "music"), "shorts"),
])
def test_rhythm_tilts_by_tokyo_hour(hour, name, top, feed):
    r = I.rhythm(hour)
    assert r["name"] == name and r["feed"] == feed
    w = I.weights(hour=hour)
    best = sorted(w, key=lambda k: -w[k])[:3]
    assert set(top) & set(best)
    picks = [I.pick(hour=hour, rng=random.Random(i))["topic"] for i in range(300)]
    assert len(set(picks)) >= 8                             # a tilt, never a single topic


def test_tastes_move_weights_but_never_collapse():
    love = {f"kw:{w}": 5.0 for w in ("ramen", "kichijoji", "recipe", "onigiri", "street", "food", "snacks")}
    hate = {f"kw:{w}": -5.0 for w in ("anime", "manga", "season", "chainsaw", "piece", "frieren", "studio", "ghibli")}
    assert I.taste_multiplier("food", love) == 1.6 and I.taste_multiplier("anime", hate) == 0.5
    picks = [I.pick(pref={**love, **hate}, hour=15, rng=random.Random(i))["topic"] for i in range(400)]
    assert max(picks.count(t) for t in set(picks)) / len(picks) < 0.25
    assert "anime" in picks                                 # disliked, still there now and then
    assert I.taste_multipliers({})["music"] == 1.0


def test_saturation_and_streak_push_him_to_something_else():
    clock = Clock()
    v = I.Variety(clock=clock)
    for _ in range(4):
        v.note("Toyota Supra and Nissan GT-R drift", "", "www.carscoops.com")
    assert v.last == "cars" and v.streak == 4 and v.host_streak == 4 and I.streak_pull(v) == 0.55
    assert I.weights(v, hour=15)["cars"] < 0.25 * I.weights(None, hour=15)["cars"]
    page = {"chain": 3, "max_chain": 30, "streak_pull": I.streak_pull(v)}
    assert E.leave_pull(page) == 0.55                       # the leave option pulls harder (brain_vote's LEAVE_CHAIN)
    v.note("Ramen ranking Tokyo", "", "example.org")
    assert v.streak == 1 and I.streak_pull(v) == 0.0
    clock.t += 86400
    assert v.public()["pages"] == 0                         # a new Tokyo day


def test_wikipedia_weighs_less_once_it_filled_a_tenth_of_the_day():
    many = [S.route("history of Kichijoji", rng=random.Random(i), wiki_share=0.0)[0] for i in range(40)]
    few = [S.route("history of Kichijoji", rng=random.Random(i), wiki_share=0.5)[0] for i in range(40)]
    assert many.count("wikipedia") == 40 and few.count("wikipedia") < 10


def test_a_simulated_day_is_varied_with_little_wikipedia():
    """T1: the real Browser._next over a simulated desk day (08:00-24:00 Tokyo, a new chain every 3 minutes), with
    the page loads stubbed: a search lands on the source search_sources.route picks, a link stays on the page's
    topic, a seed site is a front page. The live Variety counts what was shown."""
    import urllib.parse
    start = 1_790_982_000.0                                  # 2026-10-03 08:00 Tokyo
    for seed in range(3):
        clock = Clock(start)
        b = Browser(decide=True, rng=random.Random(seed))
        b.variety, b.watched = I.Variety(clock=clock), True
        sc = b.screens["desk"]
        shown = []

        def note(title, host):
            b.variety.note(title, "", host)
            shown.append((title, host))
            sc.info = {"kind": "page", "host": host, "title": title}

        async def _search(sc_, q, why="", origin=""):
            name = S.route(q, b.limits, b.rng, wiki_share=b.variety.wiki_share())[0]
            src = S.SOURCES[name]
            host = urllib.parse.urlsplit(src["url"](q)).hostname if src.get("url") else f"{name}.example"
            note(q, host)                                    # the results page, then its top result on the topic
            return True

        async def _open(sc_, url, why, kind, **kw):
            note(sc.info.get("title", "") if sc.info else "", urllib.parse.urlsplit(url).hostname)
            return True

        async def _public_videos(sc_, kind, q, why, origin="", short=True):
            note(q, "www.youtube.com")
            return True

        async def _pick_link(sc_, interest):
            return (f"https://{sc.info['host']}/p{len(shown)}", sc.info.get("title", "")) if sc.info else None

        async def _seed(sc_, why, topic=None, hungry=False, only_topic=False, hour=None, **kw):   # (hour: B4)
            note(topic or "front page", "news.example")
            return True
        b._search, b._open, b._public_videos, b._pick_link, b._seed = _search, _open, _public_videos, _pick_link, _seed
        for i in range(16 * 20):
            clock.t = start + i * 180
            assert run(b._next(sc, [], {"query": "", "from": "", "hour": 8 + i / 20}))
        r = b.variety.public()
        assert len(shown) == 320 and r["pages"] == 320
        assert r["top_share"] < 0.25 and r["wiki_share"] < 0.15 and len(r["topics"]) >= 10, r
        assert r["entropy_bits"] > 3.0                       # 13 topics evenly would be 3.7 bits


def test_next_uses_the_profile_and_says_so():
    b = Browser(decide=True, rng=random.Random(3))
    calls = []

    async def _search(sc, q, why="", origin=""):
        calls.append((q, why, origin))
        return True
    b._search = _search
    sc = b.screens["desk"]
    b.rng = SimpleNamespace(random=lambda: 0.1, choice=random.Random(0).choice)   # search branch + profile pick
    run(b._next(sc, [], {"query": "sleep spindles", "from": "mind", "hour": 8}))
    q, why, origin = calls[0]
    assert origin == "interests" and why.startswith("one of his interests (") and why.endswith(", morning)")
    assert any(q in qs for _, qs, _ in I.PROFILE.values())


# --- B. short videos on the phone ------------------------------------------------------------------------------------
def test_shorts_parser_and_restricted_mode():
    shorts = S.parse_youtube(fx("youtube_shorts.html"))
    assert len(shorts) == 8 and all(r["url"].startswith("https://www.youtube.com/shorts/") for r in shorts)
    assert shorts[0]["title"] == "Why this Spicy Ramen Hot Pot is addictive" and shorts[0]["short"]
    assert shorts[0]["hashtags"] == ["#food", "#ramen", "#shorts"]
    assert "%23shorts" in S.SOURCES["shorts"]["url"]("ramen")
    assert browse.YOUTUBE_COOKIES == [{"name": "PREF", "value": "f2=8000000", "domain": ".youtube.com", "path": "/",
                                       "secure": True}]            # Restricted Mode on every context
    assert browse.VIDEO_LINK.search(shorts[0]["url"])
    assert "shorts" not in S.route("lo-fi music") and "tiktok" not in S.route("lo-fi music")   # the phone feed only


def test_the_phone_switches_to_the_shorts_feed():
    b = Browser(decide=True)
    seen = []

    async def ensure(device):
        sc = b.screens[device]
        sc.page = sc.page or SimpleNamespace(url="about:blank")
        return sc

    async def _next(sc, heard, interest):
        seen.append(sc.mode)
        return False
    b._ensure, b._next = ensure, _next
    run(b.step("phone", [], {"query": "", "from": "", "feed": "shorts", "hour": 12.5}))
    run(b.step("desk", [], {"query": "", "from": "", "feed": "shorts", "hour": 12.5}))
    assert seen == ["shorts", None]                         # the feed is the phone's only


def test_shorts_feed_queues_and_the_next_short_costs_no_call(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key-not-real")
    b = Browser(decide=True, rng=random.Random(1))
    sc = b.screens["phone"]
    sc.mode, sc.page = "shorts", SimpleNamespace(url="about:blank")
    shorts = [r for r in Browser.safe_results(S.parse_youtube(fx("youtube_shorts.html"))) if r.get("video")]
    cards = [{"url": r["url"], "title": r["title"], "author": r.get("channel", ""), "hashtags": [], "thumb": "",
              "embed": "https://www.youtube-nocookie.com/embed/x", "host": "youtube.com"} for r in shorts]

    async def _yt_search(sc_, q, short=True):
        return cards

    async def _show_card(sc_, card, why):                       # the official embed player, stubbed
        sc_.queue = [r for r in sc_.queue if r.get("url") != card["url"]]
        sc_.info = {"title": card["title"], "url": card["url"], "host": "youtube.com", "kind": "page", "why": why,
                    "t": 0, "embed": card["embed"]}
        return True
    b._yt_search, b._show_card = _yt_search, _show_card
    b.rng = SimpleNamespace(random=lambda: 0.9, choice=random.Random(0).choice)     # YouTube Shorts first
    assert run(b._shorts(sc, {"query": "ramen", "from": "video", "hour": 12.5}))
    assert len(sc.queue) == len(cards) - 1 >= 4
    # a short is watched for at most SHORTS_MAX_S (muted), then the next shorts are the options
    run(b._start_watch(sc, 600))
    assert sc.watch_s == SV.SHORTS_MAX_S
    sc.feed_fresh = True                                        # the queue stays (the >= 60 % new-topic rule allows it)
    run(b._end_watch(sc))
    assert sc.info["kind"] == "search" and sc.info["results"] == sc.queue and "next one" in sc.info["why"]
    sc.history = ["a", "b"]
    page = b.result_page(sc, shorts[0]["url"])
    calls = []

    class Fake:
        name, model = "fake", "fake"

        def ask(self, system, user):
            calls.append(1)
            return "{}", 1, 1
    opts, meta = E.Eyes(Fake(), E.Budget(None)).propose(page)
    assert calls == [] and all(o["action"] in ("open_video", "search", "back", "leave") for o in opts)
    assert sum(o["action"] == "open_video" for o in opts) == min(E.RESULT_OPTIONS, len(sc.queue))


def test_videos_stay_muted():
    assert "--mute-audio" in browse.CHROMIUM_ARGS
    assert "d('muted').set.call(v, true)" in browse.VIDEO_JS and "set: () => {}" in browse.VIDEO_JS


def test_tiktok_logged_out_captions_guarded_walls_left():
    res = SV.parse_tiktok(fx("tiktok_tag.html"))
    assert [r["channel"] for r in res] == ["@ramenlover.tokyo", "@noodlecam", "@spam.example", "@x.example"]
    safe = Browser.safe_results(res)
    assert [r["title"] for r in safe] == ["Midnight tonkotsu in Kichijoji", "How to pull noodles by hand"]
    assert S.SOURCES["tiktok"]["url"]("Tokyo night walk") == "https://www.tiktok.com/tag/tokyonightwalk"
    robots = S.Robots(clock=Clock())
    robots.load("www.tiktok.com", 200, "User-agent: *\nAllow: /tag\nDisallow: /search?\nDisallow: /search/video?\n"
                                       "Disallow: /auth\n")
    assert robots.allowed("https://www.tiktok.com/tag/ramen")
    assert not robots.allowed("https://www.tiktok.com/search/video?q=ramen")
    assert "comment" in SV.HIDE_TIKTOK and "LoginModal" in SV.HIDE_TIKTOK
    assert browse.LOGIN_WALL.search("Log in to TikTok") and browse.LOGIN_WALL.search("Sign in to watch")
    assert url_ok("https://www.tiktok.com/@noodlecam/video/7398765432109876543")
    assert browse.is_video_host("www.tiktok.com") and browse.is_video_host("m.youtube.com")


def test_harmful_videos_stay_blocked_on_youtube_and_tiktok():
    bad = [{"url": "https://www.youtube.com/shorts/abcdefgh", "title": "nude dance", "video": True},
           {"url": "https://www.youtube.com/watch?v=abcdefgh", "title": "beheading video", "video": True},
           {"url": "https://www.tiktok.com/@a.b/video/12345678901", "title": "self-harm tips", "video": True},
           {"url": "https://www.tiktok.com/@a.b/video/12345678902", "title": "join the jihad", "video": True},
           {"url": "https://www.tiktok.com/@a.b/video/12345678903", "title": "cute cat", "video": True,
            "hashtags": ["#porn"]},
           {"url": "https://www.pornhub.com/view_video.php?viewkey=1", "title": "cat", "video": True}]
    assert Browser.safe_results(bad) == []


# --- C. queries from things he saw -----------------------------------------------------------------------------------
def test_seen_things_become_queries_with_their_origin():
    live = SimpleNamespace(
        browser=SimpleNamespace(screens={
            "desk": {"title": "Beginner Guide to Making Ramen Noodles from Scratch | Way of Ramen", "host": "youtube.com",
                     "video": {"watching": True}, "channel": "Way of Ramen", "kind": "page"},
            "phone": {"title": "Ghibli Museum opens new exhibit", "host": "japantimes.co.jp", "kind": "page"}}),
        life=SimpleNamespace(activity="park", place="bench", path=[]),
        eye=SimpleNamespace(world=SimpleNamespace(top=lambda t, k: [{"name": "melon pan"}, {"name": "rain"}])),
        clock=SimpleNamespace(now=lambda: 1_790_982_000.0))
    seen = S.seen_things(live)
    assert seen["video"] == ["ramen noodles", "Way of Ramen"]       # B3: what it is about, not the title's first words
    assert seen["walk"] == ["Inokashira Park", "Inokashira Park"] and seen["eye"] == ["melon pan", "rain"]
    assert seen["screen"] == ["Ghibli Museum"]                        # B3: the name in the headline, not the headline
    origins = {S.interest_for(seen=seen, rng=random.Random(i), query_ok=E.query_ok)["from"] for i in range(200)}
    assert origins == {"video", "walk", "eye", "screen"}
    for o in origins:
        assert S.ORIGINS[o]                                 # each is labelled ("saw it in a video")
    assert S.ORIGINS["video"] == "saw it in a video" and S.ORIGINS["walk"] == "passed it on a walk"


def test_live_interest_carries_hour_feed_and_tastes():
    live = SimpleNamespace(mind=None, clock=SimpleNamespace(now=lambda: 1_790_960_400.0),     # 02:00 Tokyo
                           memory=SimpleNamespace(items=[]), tastes=SimpleNamespace(
                               pref={"kw:ramen": 1.0}, top=lambda n=8: {"favoured": []}),
                           life=SimpleNamespace(activity="phone", phone_app="chat", place="bed", path=[]))
    it = S.live_interest(live, None, random.Random(0))
    assert round(it["hour"]) == 2 and it["feed"] == "shorts" and it["tastes"]["food"] > 1.0
    live.clock = SimpleNamespace(now=lambda: 1_791_000_000.0)                                 # 13:00 Tokyo
    live.life.phone_app = "tiktok"
    assert S.live_interest(live, None, random.Random(0))["feed"] == "shorts"


# --- A.4 research.py is one source among many --------------------------------------------------------------------------
def test_on_his_mind_is_what_he_actually_reads():
    r = R.Reader()
    r.log = [{"title": "Sleep", "t": 100.0, "url": "https://en.wikipedia.org/wiki/Sleep"}]
    assert r.current()["title"] == "Sleep" and r.due(100.0)
    r.saw({"title": "Beginner Guide to Making Ramen Noodles", "url": "https://www.youtube.com/watch?v=x",
           "host": "youtube.com", "video": {"watching": True}}, 200.0)
    cur = r.current()
    assert cur["title"] == "Beginner Guide to Making Ramen Noodles" and cur["kind"] == "video"
    assert cur["why"] == "on his screen: a video" and "ramen" in cur["keywords"]
    assert not r.due(300.0) and r.due(200.0 + R.READ_EVERY_S)     # Wikipedia waits while he browses
    r.saw({"title": "Buy $BONK now", "url": "https://x.example/"}, 400.0)     # not fit for the card: ignored
    assert r.current()["title"].startswith("Beginner Guide")
    assert R.Reader(json.loads(json.dumps(r.to_dict()))).current()["kind"] == "video"


# --- D. crypto and finance: trading hosts go (S2), neutral news stays ---------------------------------------------------
@pytest.mark.parametrize("url", [
    "https://www.binance.com/en/trade/BTC_USDT", "https://pump.fun/coin/abc", "https://dexscreener.com/solana/x",
    "https://www.coingecko.com/en/coins/bitcoin", "https://coinmarketcap.com/currencies/solana/",
    "https://www.tradingview.com/symbols/BTCUSD/", "https://finance.yahoo.com/quote/7203.T/",
    "https://www.google.com/finance/quote/NI225:INDEXNIKKEI", "https://jup.ag/swap/SOL-USDC",
    "https://gmgn.ai/sol/token/x", "https://www.okx.com/trade-spot/btc-usdt", "https://raydium.io/swap/",
    "https://kabutan.jp/stock/?code=7203", "https://stocktwits.com/symbol/TSLA",
])
def test_trading_hosts_are_refused(url):
    """S2 (owner rules: no trading content on screen): exchanges, DEX, launchpads, chart and quote sites never load,
    so nothing of them reaches a screen, a link list, a reading, the diary or the reward."""
    assert not url_ok(url) and browse.trading_url(url) and browse.is_finance(url)


@pytest.mark.parametrize("url", [
    "https://old.reddit.com/r/CryptoCurrency/", "https://www.coindesk.com/markets/", "https://www.reuters.com/markets/",
    "https://www.google.com/search?q=ramen", "https://www.bloomberg.com/asia", "https://www.nikkei.com/",
])
def test_news_about_markets_stays_readable(url):
    assert url_ok(url) and not browse.trading_url(url)          # the owner's choice: neutral news is fine


@pytest.mark.parametrize("url", ["https://metamask.io/", "https://phantom.app/", "https://verify.walletconnect.com/",
                                 "https://www.pornhub.com/", "https://www.bet365.com/", "https://bestgore.com/",
                                 "https://kiwifarms.net/"])
def test_wallets_and_harmful_sites_stay_blocked(url):
    assert not url_ok(url)


@pytest.mark.parametrize("title", ["Bitcoin price today", "$WIF jumps 20%", "SOL/USDT chart", "Solana price prediction",
                                   "memecoin presale is live", "BTC pumping again", "stocks rally as Nikkei surges",
                                   "Dogecoin to the moon", "ETH airdrop whitelist"])
def test_price_chart_and_ticker_titles_never_show(title):
    assert browse.trading_title(title) and not browse.title_ok(title) and browse.is_finance("https://x.example/", title)


@pytest.mark.parametrize("title", ["memecoin news", "Nikkei 225 today", "Nikkei and Nasdaq stocks fall", "Bitcoin history",
                                   "Pokemon trading cards", "Stockholm Syndrome", "pumpkin soup stock", "do you like dumplings",
                                   "$5 Pizza Hack", "A$AP Rocky live", "what is the price of ramen", "Sussex Cricket Club"])
def test_neutral_market_news_and_everyday_words_pass(title):
    assert not browse.trading_title(title) and browse.title_ok(title)


def test_a_terminal_like_page_is_finance_an_anime_page_is_not():
    terminal = "Market cap $1.2B · 24h volume · Liquidity · Connect wallet · slippage 0.5%"
    assert browse.is_finance("https://example.org/a", "A token page", terminal)
    assert not browse.is_finance("https://example.org/a", "Sousou no Frieren", "mana tokens and trading cards")
    assert not browse.is_finance("https://www.google.com/search?q=ramen")
    # the old advice-line card is gone: the browser refuses the page instead of showing it with a disclaimer
    assert not hasattr(browse, "finance_note") and not hasattr(browse, "ADVICE_LINE")


@pytest.mark.parametrize("label, href", [
    ("Buy now", "https://www.binance.com/en/buy-sell-crypto"), ("Connect wallet", "https://jup.ag/"),
    ("Swap", "https://jup.ag/swap/SOL-USDC"), ("Sign transaction", "https://x.example/"),
    ("Trade", "https://www.binance.com/en/trade"), ("Bitcoin chart", "https://pump.fun/create"),
    ("Claim your airdrop", "https://x.example/"), ("Sell BTC", "https://x.example/"),
    ("Deposit", "https://www.kraken.com/"), ("Stake SOL", "https://x.example/"),
])
def test_money_actions_are_never_offered_or_clicked(label, href):
    assert browse.money_action(label, href)
    page = {"url": "https://example.org/", "kind": "page", "can_back": False, "chain": 1, "max_chain": 30,
            "links": [{"id": "L1", "href": href, "text": label}, {"id": "L2", "href": "https://example.org/history",
                                                                   "text": "Solana blockchain history explained"}]}
    assert E.validate([{"action": "click", "target": "L1", "label": "go"}], page) == []      # never offered
    raw = [[href, label, 9000, True], ["https://example.org/history", "Solana blockchain history explained", 900, True],
           ["https://example.org/chart", "Solana price chart history", 900, True]]          # S2: a price chart: no
    b = Browser(decide=True)
    sc = b.screens["desk"]
    sc.info = {"title": "Crypto news", "kind": "page", "host": "example.org"}
    links = b.pick_links(raw, "https://example.org/", "text", sc)["links"]
    assert [l["text"] for l in links] == ["Solana blockchain history explained"]           # never numbered
    opened = []

    async def _open(sc_, url, why, kind, **kw):
        opened.append(url)
        return True

    async def _next(sc_, heard, interest):
        return False
    b._open, b._next = _open, _next
    sc.page, sc.awaiting = object(), page                   # even if the brain picks such a link: not clicked
    run(b.act("desk", {"action": "click", "href": href, "label": label}))
    assert opened == [] and b.last_skip == "never acts with money"
    sc.page, sc.awaiting = object(), page
    run(b.act("desk", {"action": "click", "href": "https://example.org/history", "label": "the history"}))
    assert opened == ["https://example.org/history"]


def test_his_words_carry_no_buy_or_sell_and_no_finance_talk():
    for q in ("buy bitcoin", "should I sell solana", "ape into memecoins", "swap sol for usdc"):
        assert E.query_ok(q) is None                        # never typed
    for q in ("bitcoin price", "memecoin news", "Nikkei 225 today", "solana memecoins"):
        assert E.query_ok(q) == q                           # read-only finance searches are fine
    assert E.clean_label("buy the dip") == "" and E.clean_label("Bitcoin price chart") == ""     # S2: a chart label: no
    assert E.clean_label("Bitcoin history") == "Bitcoin history"                                 # neutral: fine
    assert not browse.display_ok("Bitcoin price today")     # his own words (mind notes, the card title): no finance
    assert not browse.title_ok("Bitcoin price today") and not browse.title_ok("$WIF jumps 20%")   # S2: nor a web title
    assert browse.title_ok("memecoin news") and browse.title_ok("Nikkei 225 today")               # neutral news: yes
    assert not browse.title_ok("send 5 sol to my wallet address") and not browse.title_ok("crypto giveaway")
    assert not browse.title_ok("7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU")
