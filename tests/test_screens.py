"""#89: what is really on his screens, the phone's shorts, TikTok embed cards when TikTok's feed is closed to the
server, the capped Wikipedia fallback, and the simulated dopamine-like bursts when a new short starts.

    python -m pytest tests/test_screens.py -q
No network, no AI calls. tests/data/search/tiktok_oembed.json is a real oEmbed reply (TikTok's documented sample).
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

import live_server  # noqa: E402
import screens as SC  # noqa: E402
import search_sources as S  # noqa: E402
import short_videos as SV  # noqa: E402
import youtube_api as YT  # noqa: E402
import browse  # noqa: E402
from browse import Browser  # noqa: E402
from live_server import Live  # noqa: E402
from twin.neurochem import Neuromodulators  # noqa: E402

DATA = ROOT / "tests" / "data" / "search"


def run(coro):
    return asyncio.run(coro)


class Clock:
    def __init__(self, t=1_791_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def st(url, title="x", **kw):
    return dict({"url": url, "title": title, "host": url.split("/")[2].removeprefix("www."), "kind": "page",
                 "device": "phone", "id": 1}, **kw)


# --- 1. the screens status ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("status, kind", [
    (st("https://www.tiktok.com/@a.b/video/1234567890"), "tiktok"),
    (st("https://www.youtube.com/shorts/abcdefgh"), "shorts"),
    (st("https://www.youtube.com/watch?v=abcdefgh", video={"watching": True}), "youtube"),
    (st("https://en.wikipedia.org/wiki/Sleep"), "wikipedia"),
    (st("https://old.reddit.com/r/x/comments/1/y/"), "forum"),
    (st("https://www.bbc.com/news/a"), "news"),
    (st("https://www.coingecko.com/en/coins/bitcoin", finance=True), "finance"),
    (st("https://html.duckduckgo.com/html/?q=x", kind="search"), "search"),
    (st("https://www.recipetineats.com/melon-pan/"), "other"),
    ({"device": "phone", "restarting": True}, None),
])
def test_screen_kinds(status, kind):
    assert SC.screen_kind(status) == kind


def test_status_counts_each_page_once_and_says_when_the_browser_is_down():
    clock = Clock()
    s = SC.ScreensStatus(clock=clock)
    assert s.public()["browser"]["state"] == "starting"
    for i in range(12):
        s.seen(st(f"https://www.youtube.com/shorts/clip{i:04d}", f"clip {i}"))
        s.seen(st(f"https://www.youtube.com/shorts/clip{i:04d}", f"clip {i}"))      # the same page again: counted once
    s.seen(st("https://www.tiktok.com/@a.b/video/1234567890", "a tiktok"))
    s.seen(st("https://en.wikipedia.org/wiki/Sleep", "Sleep", device="desk"))
    p = s.public()
    assert p["browser"]["state"] == "up" and p["today"]["total"] == 14
    assert p["today"]["counts"] == {"shorts": 12, "tiktok": 1, "wikipedia": 1}
    assert p["today"]["share"]["shorts"] == round(12 / 14, 3) and set(p["today"]["share"]) == set(SC.KINDS)
    assert len(p["last"]) == 10 and p["last"][0]["kind"] == "wikipedia" and p["last"][1]["kind"] == "tiktok"
    assert s.browser_down("connection refused") and not s.browser_down("again")     # logged once per outage
    assert s.public()["browser"] == {**s.public()["browser"], "state": "down", "why": "connection refused"}
    s.seen({"device": "phone", "restarting": True})
    s.note(SV.NOTE_BLOCKED)
    s.note(SV.NOTE_BLOCKED)
    assert [n["text"] for n in s.public()["notes"]] == [SV.NOTE_BLOCKED]
    s.set_off("playwright is not installed: no browser")
    assert s.public()["browser"]["state"] == "off"
    clock.t += 86400
    assert s.public()["today"]["total"] == 0                                       # a new Tokyo day


# --- 2. dopamine-like bursts -----------------------------------------------------------------------------------------
def test_burst_size_is_novelty_plus_interest_minus_expectation():
    d = SC.DopamineBursts(clock=Clock())
    a = d.on_new("shorts", "food", interest=0.0)
    assert a["novelty"] == 1.0 and a["interest"] == 0.5 and a["rpe"] == pytest.approx(1.0 + 0.5 - 0.6)
    assert a["size"] == pytest.approx(0.9) and "novelty + predicted interest" in a["label"]
    liked = SC.DopamineBursts(clock=Clock()).on_new("shorts", "food", interest=1.0)
    disliked = SC.DopamineBursts(clock=Clock()).on_new("shorts", "food", interest=-1.0)
    assert liked["size"] > a["size"] > disliked["size"]
    d2 = SC.DopamineBursts(clock=Clock())
    d2.on_new("shorts", "food")
    again = d2.on_new("shorts", "food")                                            # seen this topic minutes ago
    fresh = SC.DopamineBursts(clock=Clock())
    fresh.on_new("shorts", "food")
    other = fresh.on_new("shorts", "anime")
    assert again["novelty"] == 0.3 and other["novelty"] == 1.0 and other["size"] > again["size"]


def test_bursts_habituate_over_a_scroll_session_and_reset_after_a_break():
    clock = Clock()
    d = SC.DopamineBursts(clock=clock)
    sizes = []
    for i in range(20):                                                           # 20 shorts, each a new topic
        clock.t += 30
        sizes.append(d.on_new("shorts", f"topic{i}", 0.0)["size"])
    assert sizes[-1] < sizes[5] < sizes[1]                                         # the doomscrolling curve
    assert d.trace[-1]["n"] == 20 and d.trace[-1]["habituation"] == pytest.approx(1 / (1 + SC.HABITUATION * 19), abs=1e-3)
    clock.t += SC.SESSION_GAP_S + 1
    b = d.on_new("shorts", "new topic", 0.0)
    assert b["n"] == 1 and b["habituation"] == 1.0                                 # a new session


def test_smaller_bursts_for_videos_and_pages_and_none_for_nothing_new():
    mk = lambda: SC.DopamineBursts(clock=Clock())                                  # noqa: E731
    short, video, page = mk().on_new("tiktok", "x"), mk().on_new("youtube", "x"), mk().on_new("news", "x")
    assert short["size"] == pytest.approx(2 * video["size"]) == pytest.approx(4 * page["size"])
    assert mk().on_new(None, "x") is None and mk().on_new("search", "x") is None


def test_neuromodulators_take_the_burst():
    n = Neuromodulators()
    before = n.levels["DA"]
    assert n.burst(0.4) == pytest.approx(0.4) and n.levels["DA"] > before
    assert n.burst(-1) == 0.0 and n.burst("x") == 0.0
    n.burst(1e9)
    assert n.phasic["DA"] == n.p["phasic_max"]                                    # clipped like every kick


# --- 3. the live server: on_screen, the view, the capped fallback, the phone feed ----------------------------------
def test_a_new_short_drives_the_reward_regions_and_goes_on_the_feed(tmp_path):
    live = Live("m", True, time_scale=1e6, data_dir=tmp_path)
    sent = []

    async def broadcast(msg):
        sent.append(msg)
    live.broadcast = broadcast
    live.browser = SimpleNamespace(feed_note=SV.NOTE_BLOCKED)
    da0 = live.neuro.levels["DA"]
    b = run(live.on_screen(st("https://www.youtube.com/shorts/abcdefgh", "Ramen in 30 seconds")))
    assert b["size"] > 0 and live.neuro.levels["DA"] > da0
    msg = sent[-1]
    assert msg["type"] == "dopamine" and msg["kind"] == "shorts" and msg["label"] == SC.DA_LABEL
    assert "enjoy" not in json.dumps(msg) and "feel" not in json.dumps(msg)
    n = len(sent)
    run(live.on_screen(st("https://www.youtube.com/shorts/abcdefgh", "Ramen in 30 seconds")))
    assert len(sent) == n                                                          # nothing new: no burst
    v = live.screens_view()
    assert v["browser"]["state"] == "up" and v["today"]["counts"] == {"shorts": 1}
    assert v["notes"][-1]["text"] == SV.NOTE_BLOCKED and v["dopamine"]["bursts"][-1]["kind"] == "shorts"
    assert v["dopamine"]["label"] == SC.DA_LABEL


def test_the_room_gets_the_real_host_and_kind_of_a_browsed_reading(tmp_path):
    live = Live("m", True, time_scale=1e6, data_dir=tmp_path)
    live.reader.record({"title": "Ramen in 30 seconds", "kind": "short", "host": "youtube.com", "t": 10.0})
    r = live.reading_now(live.clock.now())
    assert (r["host"], r["kind"]) == ("youtube.com", "short")   # room.html draws "youtube.com · short", no Wikipedia
    room = (ROOT / "web" / "room.html").read_text()
    body = room[room.index("function drawReading("):room.index("function drawFood(")]
    assert body.index("wikipedia\\.org") < body.index('"WIKIPEDIA"')       # the host check comes before the frame
    live.reader.record({"title": "Sleep", "kind": "wiki", "host": "en.wikipedia.org", "t": 20.0})
    assert live.reading_now(live.clock.now())["title"] == "Sleep"


def test_wikipedia_is_at_most_once_an_hour_while_the_wanted_browser_is_down(tmp_path, monkeypatch):
    live = Live("m", True, time_scale=1e6, data_dir=tmp_path)
    live.browse_wanted, live.browser = True, None                                  # asked for, but not running
    live.life.start("research", live.clock.now(), "test")
    live.life.path = []
    calls = []
    monkeypatch.setattr(live.reader, "read", lambda *a: calls.append(1))
    monkeypatch.setattr(live.reader, "due", lambda t: True)

    async def fast_sleep(s):
        fast_sleep.n += 1
        if fast_sleep.n > 20:
            raise asyncio.CancelledError
    fast_sleep.n = 0
    monkeypatch.setattr(live_server.asyncio, "sleep", fast_sleep)
    with pytest.raises(asyncio.CancelledError):
        run(live.run_research())
    assert len(calls) == 1                                                         # 20 loops, one reading
    live.browse_wanted = False                                                     # BROWSE=0 on purpose: as before
    calls.clear()
    fast_sleep.n = 0
    with pytest.raises(asyncio.CancelledError):
        run(live.run_research())
    assert len(calls) == 20


def test_phone_time_is_shorts():
    live = SimpleNamespace(mind=None, clock=SimpleNamespace(now=lambda: 1_791_010_800.0),          # 16:00 Tokyo
                           memory=SimpleNamespace(items=[]), tastes=SimpleNamespace(pref={}, top=lambda n=8: {"favoured": []}),
                           life=SimpleNamespace(activity="phone", phone_app="chart", place="bed", path=[]))
    assert S.live_interest(live, None, random.Random(0))["feed"] == "shorts"
    live.life.activity = "research"
    assert S.live_interest(live, None, random.Random(0))["feed"] is None


# --- 4. TikTok embed cards when TikTok's feed is closed to the server ----------------------------------------------
def test_oembed_card_is_parsed_guarded_and_escaped():
    raw = (DATA / "tiktok_oembed.json").read_text()
    url = "https://www.tiktok.com/@scout2015/video/6718335390845095173"
    c = SV.parse_oembed(raw, url)
    assert c["url"] == url and c["author"] == "Scout, Suki & Stella" and c["thumb"].startswith("https://")
    assert c["title"].startswith("Scramble up ur name") and "#foryoupage" in c["hashtags"]
    assert SV.parse_oembed("not json", url) is None and SV.parse_oembed("{}", url) is None
    html = SV.card_html(dict(c, title='<script>alert(1)</script>', author='a"b'))
    assert "<script>" not in html and "&lt;script&gt;" in html and "not played" in html
    assert SV.oembed_url(url).startswith("https://www.tiktok.com/oembed?url=https%3A%2F%2Fwww.tiktok.com%2F%40")


DDG_TIKTOK = """<div class="result results_links"><h2 class="result__title"><a class="result__a"
 href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.tiktok.com%2F%40scout2015%2Fvideo%2F6718335390845095173&rut=x">Scramble
 up ur name</a></h2><a class="result__snippet">pets</a></div>
<div class="result results_links"><h2 class="result__title"><a class="result__a"
 href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fnot-tiktok&rut=y">Other</a></h2></div>"""


class CardPage:
    url = "about:blank"

    def __init__(self):
        self.html = []

    async def set_content(self, html, wait_until=None):
        self.html.append(html)

    async def wait_for_timeout(self, ms):
        pass


def _card_browser(fetch_map):
    b = Browser(decide=True, rng=random.Random(0))
    sc = b.screens["phone"]
    sc.mode, sc.page, sc.ctx = "shorts", CardPage(), object()

    async def _fetch(sc_, url, hops=3):
        if url.endswith("/robots.txt"):
            return 404, ""
        for k, v in fetch_map.items():
            if url.startswith(k):
                return 200, v
        return 404, ""

    async def show(sc_):
        b.log.append({"url": sc_.info["url"], "title": sc_.info["title"]})
        return True
    b._fetch, b.show = _fetch, show
    return b, sc


def _embed_opens(b, ok=True):
    opened = []

    async def _open(sc_, url, why, kind, title=None, min_text=80, shoot=True, revisit=False, referer=None):
        opened.append((url, referer))
        if not ok:
            b.last_skip = "bot wall"
            return False
        sc_.info = {"title": title, "url": url, "host": browse.urllib.parse.urlsplit(url).hostname, "why": why,
                    "t": 0, "kind": kind}
        return True

    async def _play_muted(sc_):
        return {"muted": True, "paused": False}
    b._open, b._play_muted = _open, _play_muted
    return opened


def test_tiktok_found_by_search_plays_in_tiktoks_official_player():
    oembed = (DATA / "tiktok_oembed.json").read_text()
    b, sc = _card_browser({"https://html.duckduckgo.com/": DDG_TIKTOK, "https://www.tiktok.com/oembed": oembed})
    opened = _embed_opens(b)
    assert run(b._public_videos(sc, "tiktok", "cute pets", "short videos — one of his interests"))
    assert opened == [("https://www.tiktok.com/player/v1/6718335390845095173?autoplay=1&muted=1&loop=1&rel=0"
                       "&description=1", browse.EMBED_REFERER)]
    assert sc.info["url"] == "https://www.tiktok.com/@scout2015/video/6718335390845095173" and sc.info["embed"]
    assert SC.screen_kind(dict(sc.info, device="phone")) == "tiktok" and sc.watch_until > 0   # played, muted
    assert b.feed_note == SV.NOTE_EMBEDS and b.limits.public()["per_source_today"].get("tiktok") == 1


def test_a_refused_player_falls_back_to_the_card():
    oembed = (DATA / "tiktok_oembed.json").read_text()
    b, sc = _card_browser({"https://html.duckduckgo.com/": DDG_TIKTOK, "https://www.tiktok.com/oembed": oembed})
    _embed_opens(b, ok=False)
    assert run(b._public_videos(sc, "tiktok", "cute pets", "short videos"))
    assert sc.info["card"] and "Scramble up ur name" in sc.page.html[-1]


def test_duckduckgos_bot_check_sets_it_aside_and_nothing_is_shown():
    b, sc = _card_browser({"https://html.duckduckgo.com/": "<html><body>Unfortunately, bots use DuckDuckGo too."
                                                            "</body></html>"})
    assert not run(b._public_videos(sc, "tiktok", "ramen", "short videos"))
    assert "ddg: bot check" in b.limits.public()["refused_today"]


def test_no_youtube_key_no_youtube_search_and_the_panel_says_so(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    b, sc = _card_browser({})
    asked = []

    async def _fetch(sc_, url, hops=3, headers=None):
        asked.append(url)
        return 404, ""
    b._fetch = _fetch
    assert not run(b._public_videos(sc, "shorts", "ramen", "short videos"))
    assert b.feed_note == YT.NOTE_NO_KEY and not [u for u in asked if "googleapis" in u]


def test_youtube_api_shorts_play_in_the_official_embed_and_the_key_stays_in_a_header(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key-not-real")
    b, sc = _card_browser({})
    calls = []
    api = (DATA / "youtube_api_search.json").read_text()

    async def _fetch(sc_, url, hops=3, headers=None):
        calls.append((url, headers))
        if url.startswith(YT.SEARCH):
            return 200, api
        if "/youtube/v3/videos?" in url:                    # the playability check (1 unit)
            return 200, (DATA / "youtube_api_videos.json").read_text()
        return (404, "") if url.endswith("/robots.txt") else (404, "")
    b._fetch = _fetch
    opened = _embed_opens(b)
    assert run(b._public_videos(sc, "shorts", "ramen", "short videos — lunch"))
    url, headers = next(c for c in calls if c[0].startswith(YT.SEARCH))
    assert "test-key-not-real" not in url and headers == {"X-Goog-Api-Key": "test-key-not-real"}
    assert "videoDuration=short" in url and "safeSearch=strict" in url
    assert opened[0][0].startswith("https://www.youtube-nocookie.com/embed/") and "mute=1" in opened[0][0]
    assert sc.info["url"].startswith("https://www.youtube.com/shorts/") and sc.watch_until > 0
    assert SC.screen_kind(dict(sc.info, device="phone")) == "shorts" and len(sc.queue) >= 1
    units = YT.SEARCH_UNITS + YT.LIST_UNITS                     # the search + the playability check
    assert b.yt.public()["units_used"] == units and "test-key" not in json.dumps(b.yt.public())
    run(b._public_videos(sc, "shorts", "ramen", "again"))            # cached: the query is not searched again
    assert b.yt.public()["units_used"] == units


def test_choosing_a_card_shows_it_and_never_opens_tiktok():
    oembed = json.loads((DATA / "tiktok_oembed.json").read_text())
    b, sc = _card_browser({})
    card = SV.parse_oembed(json.dumps(oembed), "https://www.tiktok.com/@scout2015/video/6718335390845095173")
    sc.cards = {card["url"]: card}
    sc.queue = [{"url": card["url"], "title": card["title"], "video": True}]
    opened = []

    async def _open(*a, **k):
        opened.append(a)
        return True
    b._open = _open
    sc.awaiting = {"links": [{"id": "L1", "href": card["url"], "text": card["title"], "video": True}], "can_back": False}
    run(b.act("phone", {"action": "open_video", "href": card["url"], "label": "pets"}))
    assert opened == [] and sc.info["card"] and sc.page.html                      # shown as a card, not navigated


# --- #89 follow-up: the live data at 18:30 UTC ----------------------------------------------------------------------
def test_a_blocked_short_page_becomes_a_card_from_the_results():
    b, sc = _card_browser({})
    item = {"url": "https://www.youtube.com/shorts/abcDEF12345", "title": "Melon pan in 30 seconds", "video": True,
            "channel": "Tokyo Bakes"}
    sc.queue = [item]

    async def _open(sc_, url, *a, **k):
        b.last_skip = "bot wall"                               # google.com/sorry from the server's network
        return False
    b._open = _open
    sc.awaiting = {"links": [{"id": "L1", "href": item["url"], "text": item["title"], "video": True}],
                   "can_back": False}
    run(b.act("phone", {"action": "open_video", "href": item["url"], "label": "bread"}))
    assert sc.info["card"] and sc.info["host"] == "youtube.com" and b.feed_note == SV.NOTE_SHORTS_CARDS
    assert "i.ytimg.com/vi/abcDEF12345/" in sc.page.html[-1] and "YouTube Shorts" in sc.page.html[-1]
    assert SC.screen_kind(dict(sc.info, device="phone")) == "shorts"


def test_tiktok_rows_carry_the_official_embed_without_autoplay():
    s = SC.ScreensStatus()
    s.seen({"url": "https://www.tiktok.com/@scout2015/video/6718335390845095173", "title": "Scramble up ur name"})
    row = s.public()["last"][0]
    assert row["embed"]["label"] == "TikTok (official embed)" and "autoplay=0" in row["embed"]["src"]
    s.seen({"url": "https://www.tiktok.com/@x.y/video/6718335390845095174", "title": "any caption"})
    assert "embed" not in s.public(lambda t, host="": False)["last"][0]  # a caption that fails the filter: no player
    s.idle("he is not at a screen")
    assert s.public()["browser"]["state"] == "idle"


def test_browsing_view_is_never_null_before_the_first_sync(tmp_path):
    live = Live("m", True, time_scale=1e6, data_dir=tmp_path)
    lim = S.Limits()
    lim.count("hn", "sourdough", "interests")
    lim.refuse("ddg", "no results")
    lim.refuse("ddg", "no results")
    live.browsing_state = {"log": [], "searches": dict(lim.to_dict(), variety={})}
    live.browser = SimpleNamespace(log=[], searches=None, accounts=None, feed_note=None)
    v = live.browsing_view()
    assert v["synced"] is False and v["searches"]["per_source_today"] == {"hn": 1}
    assert isinstance(v["accounts"], dict) and "error" not in v["accounts"]
    assert [x["source"] for x in live.screens_view()["sources"]["blocked"]] == ["ddg"]


def test_music_is_in_the_screens_panel_and_says_where_it_comes_from(tmp_path):
    live = Live("m", True, time_scale=1e6, data_dir=tmp_path)
    live.music.api = None
    assert live.screens_view()["music"]["source"] == "Spotify keys not set: playing from the curated list"
    live.music.api, live.music.api_down = object(), "/search failed (status 502)"
    assert live.music_line()["source"].startswith("Spotify search down: /search failed (status 502)")
    live.music.now = {"id": "4uLU6hMCjMI75M1A2tKUQC", "title": "Plastic Love", "artist": "Mariya Takeuchi",
                      "embed": "https://open.spotify.com/embed/track/4uLU6hMCjMI75M1A2tKUQC", "embed_height": 152}
    now = live.music_line()["now"]
    assert now["title"] == "Plastic Love" and now["embed"].startswith("https://open.spotify.com/embed/")


def test_a_burst_moves_the_neurons_panel_dopamine_and_decays():
    from spiking import live as SL
    b = SimpleNamespace(last_da=0.0, da_t=time.time())
    b.dopamine_now = lambda: SL.LiveBrain.dopamine_now(b)
    SL.LiveBrain.burst(b, 0.4)
    assert b.dopamine_now() == pytest.approx(0.4, abs=0.01)
    SL.LiveBrain.burst(b, 0.1)                                  # a smaller burst does not lower the reading
    assert b.last_da == 0.4
    b.da_t -= SL.DA_SHOW_TAU_S * 3
    assert b.dopamine_now() < 0.03                               # back towards 0 after a while
    sent = []
    SL.handle(SimpleNamespace(burst=lambda v: sent.append(v)), json.dumps({"type": "burst", "value": 0.3}).encode(),
              lambda m: sent.append(m))
    assert sent == [0.3]                                         # applied, no answer line


def test_a_new_short_sends_the_burst_to_the_spiking_child(tmp_path):
    live = Live("m", True, time_scale=1e6, data_dir=tmp_path)
    got = []
    live.decider = SimpleNamespace(cpu=SimpleNamespace(burst=lambda v: got.append(v)))

    async def bc(msg):
        pass
    live.broadcast = bc
    run(live.on_screen({"url": "https://www.youtube.com/shorts/zzzzzzzz1", "title": "Tiny sushi", "device": "phone",
                        "id": 1}))
    assert got and 0 < got[0] <= 1


def test_the_life_phone_shows_only_a_real_screen_and_tiktok_gets_its_embed(tmp_path):
    html = (ROOT / "web" / "life.html").read_text()
    assert 'id="phonecv"' not in html and 'id="phonefr"' in html            # no chart / blank box fallback
    live = Live("m", True, time_scale=1e6, data_dir=tmp_path)
    live.browser = SimpleNamespace(restarting=False, screens={"phone": {
        "url": "https://www.tiktok.com/@scout2015/video/6718335390845095173", "title": "Scramble up ur name",
        "host": "tiktok.com", "id": 3}})
    st = live.screen_status("phone")
    assert st["embed"]["label"] == "TikTok (official embed)" and "autoplay=0" in st["embed"]["src"]
    css = (ROOT / "web" / "index.html").read_text()
    assert "#cards [hidden]" in css                                          # empty cards are really hidden


def test_todays_screens_survive_a_deploy(tmp_path):
    """#89 live (2026-10-04): /api/screens had 44 pages today at 05:26; after the next deploy counts {} and last []."""
    clock = Clock()
    s = SC.ScreensStatus(clock=clock)
    for i in range(3):
        s.seen(st(f"https://www.youtube.com/shorts/clip{i:04d}", f"clip {i}"))
    s.seen(st("https://www.theverge.com/x", "a story", device="desk"))
    s.note("YouTube: uploads of a channel")
    again = SC.ScreensStatus(clock=clock, state=json.loads(json.dumps(s.to_dict())))   # through the saved JSON
    p, q = s.public(), again.public()
    assert q["today"] == p["today"] and q["last"] == p["last"] and q["notes"] == p["notes"]
    again.seen(st("https://www.theverge.com/x", "a story", device="desk"))           # the same page: not counted twice
    assert again.public()["today"]["total"] == 4
    clock.t += 86400                                                                  # the next Tokyo day starts afresh
    assert SC.ScreensStatus(clock=clock, state=s.to_dict()).public()["today"]["total"] == 0
    assert SC.ScreensStatus(state={"counts": {"evil": 5, "shorts": "x"}, "last": [1, {"t": "x"}]}).public()["last"] == []


def test_the_live_server_saves_and_restores_the_screens(tmp_path):
    from live_server import Live
    live = Live("m", True, time_scale=1e6, data_dir=tmp_path)
    live.screens.seen(st("https://www.youtube.com/shorts/clip0001", "clip 1"))
    live.save_screens()
    assert (tmp_path / "screens.json").exists()
    live2 = Live("m", True, time_scale=1e6, data_dir=tmp_path)
    assert live2.screens_view()["today"]["counts"] == {"shorts": 1}
    assert live2.screens_view()["last"][0]["title"] == "clip 1"
