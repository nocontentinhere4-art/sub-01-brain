"""#79: his readings come from what he actually browses; the Wikipedia reader is only a fallback.

    python -m pytest tests/test_readings.py -q
No network, no AI calls.
"""
import asyncio
import random
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis"))

import live_server  # noqa: E402
import readings as RD  # noqa: E402
from browse import display_ok  # noqa: E402
from live_server import Live  # noqa: E402
from readings import BrowseReadings, kind_of  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def page(url, title, **kw):
    return dict({"url": url, "title": title, "host": url.split("/")[2].removeprefix("www."), "kind": "page"}, **kw)


def stay(r, st, t0, secs, step=7.0):
    """Screen statuses every `step` s for `secs` s; returns the readings that came out and the end time."""
    out, t = [], t0
    while t - t0 < secs:
        if (a := r.seen(st, t)) is not None:
            out.append(a)
        t += step
    return out, t


# --- 1. kinds ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("st, kind", [
    (page("https://www.youtube.com/shorts/abcdefgh", "Ramen in 30 s"), "short"),
    (page("https://www.tiktok.com/@a.b/video/1234567890", "Midnight ramen"), "short"),
    (page("https://www.youtube.com/watch?v=abcdefgh", "Tokyo night walk", video={"watching": True}), "video"),
    (page("https://old.reddit.com/r/askscience/comments/1/why/", "Why do cats purr?"), "forum"),
    (page("https://news.ycombinator.com/item?id=1", "Show HN: a keyboard"), "forum"),
    (page("https://www.bbc.com/news/articles/x", "Tokyo weather"), "news"),
    (page("https://www.coingecko.com/en/coins/bitcoin", "Bitcoin price", finance=True), "finance"),
    (page("https://en.wikipedia.org/wiki/Sleep", "Sleep"), "wiki"),
    (page("https://www.recipetineats.com/melon-pan/", "Melon pan"), "page"),
    (page("https://html.duckduckgo.com/html/?q=x", "x — DuckDuckGo", kind="search"), None),
    ({"device": "desk", "restarting": True}, None),
])
def test_kinds(st, kind):
    assert kind_of(st) == kind


# --- 2. dwell, rate and the best page of each gap ----------------------------------------------------------------
def test_a_page_counts_once_he_stayed_on_it():
    r = BrowseReadings(display_ok=display_ok)
    st = page("https://old.reddit.com/r/Cooking/comments/9/melon/", "How do you make melon pan crisp?")
    out, t = stay(r, st, 0.0, 30)                           # 30 s: too short for a thread
    out += r.seen(page("https://example.org/next", "Next page"), t) and [1] or []
    assert out == [] and r.pending is None
    out, t = stay(r, st, t, 60)
    art = r.seen(page("https://example.org/other", "Something else"), t)
    assert art["title"] == "How do you make melon pan crisp?" and art["kind"] == "forum"
    assert art["host"] == "old.reddit.com" and art["via"] == "browser" and art["why"] == "read a thread on old.reddit.com"
    assert art["dwell_s"] >= 60 and "melon" in art["keywords"] and "score" not in art


def test_at_most_one_reading_per_gap_and_the_best_page_wins():
    r = BrowseReadings(display_ok=display_ok)
    first = page("https://www.bbc.com/news/a", "Tokyo festival this weekend")
    got, t = stay(r, first, 0.0, 60)
    got += [x for x in [r.seen(page("https://www.bbc.com/news/b", "Train strike in Osaka"), t)] if x]
    assert [a["title"] for a in got] == ["Tokyo festival this weekend"]      # the first slot
    slot = r.next_ok
    out, t = stay(r, page("https://www.bbc.com/news/b", "Train strike in Osaka"), t, 100)     # 100 s
    got += out
    out, t = stay(r, page("https://www.bbc.com/news/c", "Rain in Kyoto"), t, 50)             # 50 s
    got += out
    assert t < slot and len(got) == 1                         # both ended inside the gap: nothing yet
    out, t = stay(r, page("https://example.org/z", "Zzz"), t, slot - t + 7)
    got += out
    assert [a["title"] for a in got] == ["Tokyo festival this weekend", "Train strike in Osaka"]   # longer stay won
    out, _ = stay(r, page("https://example.org/z", "Zzz"), t, 3 * RD.READ_GAP_S)
    assert "Rain in Kyoto" not in [a["title"] for a in got + out]      # the loser of a gap is dropped, not queued


def test_a_short_counts_after_a_few_seconds_and_a_stale_candidate_is_dropped():
    r = BrowseReadings(display_ok=display_ok)
    st = page("https://www.youtube.com/shorts/abcdefgh", "Ramen in 30 seconds", channel="Way of Ramen")
    out, t = stay(r, st, 0.0, 21)
    a = r.seen(page("https://www.youtube.com/shorts/ijklmnop", "next short"), t)
    assert a["kind"] == "short" and a["extract"] in ("a short by Way of Ramen", "a short")
    r2 = BrowseReadings(display_ok=display_ok)
    r2.next_ok = 10_000.0                                    # no slot for a long time
    _, t = stay(r2, page("https://www.bbc.com/news/a", "Tokyo festival"), 0.0, 60)
    r2.seen(page("https://example.org/x", "x"), t)
    assert r2.pending is not None
    assert r2.seen(page("https://example.org/x", "x"), t + RD.STALE_S + 1) is None and r2.pending is None


# --- 3. safety -------------------------------------------------------------------------------------------------------
def test_finance_pages_are_never_a_reading():
    """S2: a finance / trading page never becomes a reading (nothing of it reaches the memory, the replay or the
    diary), whether the status carries the `finance` flag or only the trading host."""
    r = BrowseReadings(display_ok=display_ok)
    st = page("https://dexscreener.com/solana/abc", "$BONK +40% — memecoin chart", finance=True)
    _, t = stay(r, st, 0.0, 60)
    assert r.seen(page("https://example.org/x", "x"), t) is None and r.pending is None and r.log == []
    assert r.reading(dict(st, finance=False), "finance", 600, t) is None
    assert r.reading(page("https://pump.fun/coin/x", "a coin page", finance=True), "page", 600, t) is None


def test_unsafe_titles_logged_in_pages_and_excerpts():
    r = BrowseReadings(display_ok=display_ok)
    _, t = stay(r, page("https://example.org/a", "Buy $BONK now"), 0.0, 60)
    assert r.seen(page("https://example.org/b", "b"), t) is None and r.pending is None    # not his words: dropped
    url = "https://www.bbc.com/news/c"
    r.text(url, "Tokyo opens a new park. Send 2 sol to my wallet now please. The park has a big pond and old trees.")
    _, t = stay(r, page(url, "A new park in Tokyo"), t, 60)
    a = r.seen(page("https://example.org/d", "d"), t)
    assert a["extract"] == "Tokyo opens a new park. The park has a big pond and old trees."
    r2 = BrowseReadings(display_ok=display_ok)
    url = "https://www.tiktok.com/@me/video/123456789"
    r2.text(url, "private things from a feed")
    _, t = stay(r2, page("https://www.youtube.com/feed/x", "Recommended for you", site="youtube"), 0.0, 60)
    a = r2.seen(page("https://example.org/e", "e"), t)
    assert a["extract"] == "" and a["title"] == "Recommended for you"                      # public title only


def test_titles_are_not_read_twice_and_wikipedia_stays_small():
    r = BrowseReadings(display_ok=display_ok)
    t, got = 0.0, []
    for i in range(40):                                       # many Wikipedia stays: few become readings
        st = page(f"https://en.wikipedia.org/wiki/T{i}", f"Article number {i}")
        out, t = stay(r, st, t, 60)
        got += out
        st2 = page(f"https://www.bbc.com/news/{i}", f"News story {i}")
        out, t = stay(r, st2, t, 200)
        got += out
    kinds = [a["kind"] for a in got]
    assert kinds.count("wiki") / len(kinds) <= RD.WIKI_MAX
    titles = [a["title"] for a in got]
    assert len(titles) == len(set(titles))


# --- 4. the live server: Wikipedia only as a fallback ------------------------------------------------------------------
def test_wikipedia_reader_is_only_a_fallback(monkeypatch):
    assert Live.wiki_fallback(SimpleNamespace(browser=None, browser_down_since=None))                 # BROWSE=0
    on = SimpleNamespace(browser=object(), browser_down_since=None)
    assert not Live.wiki_fallback(on)                                                               # browsing
    on.browser_down_since = time.time() - 30
    assert not Live.wiki_fallback(on)                                                               # a short restart
    on.browser_down_since = time.time() - live_server.WIKI_FALLBACK_S - 1
    assert Live.wiki_fallback(on)                                                                   # down too long


def test_run_research_skips_wikipedia_while_the_browser_works(tmp_path, monkeypatch):
    live = Live("m", True, time_scale=1e6, data_dir=tmp_path)
    live.browser = SimpleNamespace(restarting=False)
    live.life.start("research", live.clock.now(), "test")
    live.life.path = []
    calls = []
    monkeypatch.setattr(live.reader, "read", lambda *a: calls.append(1))

    async def fast_sleep(s):
        if len(fast_sleep.n) > 3:
            raise asyncio.CancelledError
        fast_sleep.n.append(s)
    fast_sleep.n = []
    monkeypatch.setattr(live_server.asyncio, "sleep", fast_sleep)
    with pytest.raises(asyncio.CancelledError):
        run(live.run_research())
    assert calls == []


def test_a_browsed_reading_becomes_stimulus_memory_and_feed(tmp_path):
    live = Live("m", True, time_scale=1e6, data_dir=tmp_path)
    sent = []

    async def broadcast(msg):
        sent.append(msg)
    live.broadcast = broadcast
    art = {"title": "Why do cats purr?", "extract": "", "url": "https://old.reddit.com/r/askscience/comments/1/",
           "host": "old.reddit.com", "kind": "forum", "via": "browser", "keywords": ["cats", "purr"],
           "why": "read a thread on old.reddit.com", "t": live.clock.now()}
    m = run(live.take_reading(art))
    assert m["source"] == "reading" and m["host"] == "old.reddit.com" and m["kind"] == "forum" and m["via"] == "browser"
    msg = sent[-1]
    assert msg["type"] == "reading" and msg["title"] == "Why do cats purr?" and msg["kind"] == "forum"
    assert msg["host"] == "old.reddit.com" and "networks" in msg and "extract" in msg   # old fields kept
    assert live.reader.current()["title"] == "Why do cats purr?"                        # on his mind


def test_wikipedia_fallback_readings_are_labelled(tmp_path):
    live = Live("m", True, time_scale=1e6, data_dir=tmp_path)
    m = live.absorb_reading({"title": "Sleep", "keywords": ["sleep"], "url": "https://en.wikipedia.org/wiki/Sleep"})
    assert m["host"] == "en.wikipedia.org" and m["kind"] == "wiki" and m["via"] == "wikipedia"


# --- 5. the diary and the simulated day --------------------------------------------------------------------------------
def test_diary_uses_the_verb_of_each_kind(tmp_path):
    import diary as D
    d = D.Diary(tmp_path / "nights", tmp_path / "frames")
    night = {"date": "2026-10-02", "sleep_onset": "2026-10-02 23:40", "woke_up": "2026-10-03 07:10",
             "wakeups": [], "replays": [{"text": "Ramen in 30 s", "source": "reading"}]}
    d.entry(night["date"])
    e = d.close(night, read_today=[{"title": "Ramen in 30 s", "kind": "short", "host": "youtube.com"},
                                   {"title": "Why do cats purr?", "kind": "forum", "host": "reddit.com"}])
    verbs = {a["title"]: a["verb"] for a in e["facts"]["read"]}
    assert verbs == {"Ramen in 30 s": "watched", "Why do cats purr?": "read"}
    assert "read or watched" in e["text"] and "(watched that day)" in e["text"]


def test_a_simulated_day_has_little_wikipedia_and_no_more_readings_than_before():
    import readings_day
    days = [readings_day.after(8, random.Random(s)) for s in range(3)]
    for r in days:
        c = r.counts()
        wiki = sum(n for h, n in c["host"].items() if h.endswith("wikipedia.org"))
        assert c["n"] and wiki / c["n"] <= 0.10
        assert c["n"] / 8 <= 3600 / RD.READ_GAP_S                       # never more per hour than the old reader
        assert len(c["kind"]) >= 5                                        # varied: shorts, news, forums, pages, ...
