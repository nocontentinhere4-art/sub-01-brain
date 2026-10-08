"""#89: novelty on a live-like run, on the browser's real choice path with a stubbed network.

    python analysis/novelty_replay.py [--hours 3] [--seed 1]

What runs for real: Browser._next / _search / _shorts / pick_links / show, interests.pick, novelty.Visited, the
footer filter, search_sources.route and Limits (blocking, rotation). What is stubbed: the network. Every general
engine "fails" like it did from Railway on 2026-10-02 (no results); Hacker News, Science News and the YouTube Shorts
results page answer; every results page and front page also lists the pages the live site kept reopening (Studio
Ghibli on Wikipedia, the MediaWiki conference page, the abc wetlands article) and footer links (Contact Us, the ABC
home page, a CC licence deed), so the run shows whether he still falls into them. Not a real browser: it measures
what he chooses to open, not whether pages load.

Prints: unique URLs per hour, URL repeat rate (same page within 7 days), topic repeat rate (a short's topic seen in
the previous 2 h), the new-topic share of shorts, follow-up share of searches, and the hosts opened.
"""
import argparse
import asyncio
import collections
import random
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import browse  # noqa: E402
import interests as I  # noqa: E402
import novelty as NV  # noqa: E402
import screens as SC  # noqa: E402
import search_sources as S  # noqa: E402
import youtube_api as YT  # noqa: E402

TRAPS = [("https://en.wikipedia.org/wiki/Studio_Ghibli", "Studio Ghibli"),
         ("https://www.mediawiki.org/wiki/MediaWiki_Users_and_Developers_Conference_Fall_2026",
          "MediaWiki Users and Developers Conference Fall 2026"),
         ("https://www.abc.net.au/news/2026-10-01/wetlands-restoration-birds-return/104412345",
          "Wetlands restoration brings the birds back")]
FOOTER = [("https://www.abc.net.au/contact", "Contact Us"), ("https://www.abc.net.au/", "ABC"),
          ("https://creativecommons.org/licenses/by-sa/4.0/", "Creative Commons Attribution-ShareAlike 4.0")]


class Clock:
    def __init__(self, t=1_790_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=3.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--youtube-key", action="store_true", help="as with YOUTUBE_API_KEY set (the API is stubbed)")
    a = ap.parse_args()
    import os
    if a.youtube_key:
        os.environ["YOUTUBE_API_KEY"] = "replay-not-a-real-key"     # nothing is asked: _yt_search is stubbed below
    else:
        os.environ.pop("YOUTUBE_API_KEY", None)
    clk = Clock()
    browse.time.time = clk                                  # the browser's clock follows the simulation
    b = browse.Browser(decide=False, rng=random.Random(a.seed))
    b.limits, b.variety, b.visited = S.Limits(clock=clk), I.Variety(clock=clk), NV.Visited(clock=clk)
    opened, shorts, searches = [], [], []
    n = [0]

    def results(q, name):
        n[0] += 1
        k = n[0]
        return ([{"url": u, "title": t} for u, t in TRAPS]
                + [{"url": f"https://{name}.example.org/{k}/{i}", "title": f"{q} story {i}"} for i in range(4)])

    async def _search_on(sc, name, q, why, origin):
        searches.append((name, q, origin))
        for h in S.hosts_of(name):                          # the per-host cap (20 an hour) is real here
            if not b.limits.allow(h):
                b.limits.refuse(name, "rate limit")
                return False
            b.limits.note(h)
        if name in ("bing", "wikipedia"):                   # what Railway got on 2026-10-03
            b.limits.refuse(name, "robots.txt")
            return False
        if name in ("ddg", "commons", "arxiv", "openlibrary", "tiktok"):
            b.limits.refuse(name, "bot check" if name == "ddg" else "no results")
            return False
        sc.info = {"title": f"{q} — {name}", "url": f"https://{name}.example.org/search?q={k(q)}", "host": name,
                   "why": why, "t": clk(), "kind": "search", "results": b.safe_results(results(q, name))}
        b.limits.count(name, q, origin)
        return True

    def k(q):
        return urllib.parse.quote(q)

    async def _open(sc, url, why, kind, title=None, min_text=80, shoot=True, revisit=False, referer=None):
        if not revisit and kind != "search" and not b.fresh(url, title):
            b.last_skip = "opened in the last 7 days"
            return False
        sc.info = {"title": title or url, "url": url, "host": urllib.parse.urlsplit(url).hostname, "why": why,
                   "t": clk(), "kind": kind}
        opened.append((clk(), sc.name, url, title))
        return True if not shoot else await b.show(sc)

    async def _shoot(sc):
        return True

    async def _fetch(sc, url, hops=3, headers=None):        # robots.txt: none (allowed); DDG: its bot check
        return (200, "bots use DuckDuckGo too") if "duckduckgo" in url else (404, "")

    async def _play_muted(sc):
        return {"muted": True}

    async def _yt_search(sc, q, short=True):                # the Data API (with the key), its quota real
        if not a.youtube_key:
            b.feed_note = YT.NOTE_NO_KEY
            return []
        hit = b.yt.cached(q, short)
        if hit is None:
            if not b.yt.allow() or not b.limits.allow("www.googleapis.com"):
                return []
            b.limits.note("www.googleapis.com")
            n[0] += 1
            hit = [{"url": YT.video_url(f"v{n[0]:05d}x{i}abc"[:11], short), "title": f"{q} #{i}", "channel": "c",
                    "thumb": "", "video": True, "embed": YT.embed_url(f"v{n[0]:05d}x{i}abc"[:11])} for i in range(5)]
            b.yt.spend(q, short, hit)
        return [{"url": r["url"], "title": r["title"], "author": r["channel"], "thumb": "", "hashtags": [],
                 "embed": r["embed"], "host": "youtube.com"} for r in b.safe_results(hit) if b._card_ok(
                     {"url": r["url"], "title": r["title"], "author": r["channel"]})]

    async def _pick_link(sc, interest):                     # the page's links: traps, footers and two real ones
        raw = [(u, t, 9000, True) for u, t in TRAPS + FOOTER] + [
            (f"https://{sc.info['host']}/next/{n[0]}/{i}", f"Another long article title number {i}", 5000, True)
            for i in range(2)]
        links = b.pick_links(raw, sc.info["url"], "", sc)["links"]
        return (links[0]["href"], links[0]["text"]) if links else None

    origins = []
    record = b.visited.search
    b.visited.search = lambda o: (origins.append(o), record(o))
    b._search_on, b._open, b._shoot, b._pick_link = _search_on, _open, _shoot, _pick_link
    b._fetch, b._play_muted, b._yt_search = _fetch, _play_muted, _yt_search
    da = SC.DopamineBursts(clock=clk)
    bursts = collections.defaultdict(list)

    def screen(sc):                                         # what the live server's on_screen() does with a status
        st = dict(sc.info, device=sc.name)
        kind = SC.screen_kind(st)
        if kind and st["url"] != last.get(sc.name):
            last[sc.name] = st["url"]
            topic = I.topic_of(st.get("title", "")) or ("video:" + NV.title_key(st.get("title", ""))
                                                      if kind in ("shorts", "tiktok", "youtube") else st.get("host"))
            bb = da.on_new(kind, topic, 0.0)                # as live_server.on_screen (interest 0: no tastes here)
            if bb:
                bursts[kind].append(bb["size"])
            if kind in ("shorts", "tiktok"):
                shorts.append((clk(), st["title"], sc.feed_topic, sc.sess[2]))
    last = {}
    phone, desk = b.screens["phone"], b.screens["desk"]
    phone.mode = "shorts"
    end = clk() + a.hours * 3600
    while clk() < end:
        if phone.queue and b.new_share_ok(phone):          # the next short from the queue (the vote picks one)
            r = phone.queue.pop(0)
            if r["url"] in phone.cards:
                asyncio.run(b._show_card(phone, phone.cards[r["url"]], "next short"))
        else:                                                # a new topic (or, at the cap, a page instead)
            phone.queue = []
            asyncio.run(b._next(phone, [], {"query": "studio ghibli", "from": "screen", "feed": "shorts"}))
        if phone.info:
            screen(phone)
        if desk.pending_link:
            u, why = desk.pending_link
            desk.pending_link = None
            asyncio.run(_open(desk, u, why, "page"))
        else:
            asyncio.run(b._next(desk, [], {"query": "studio ghibli wikipedia", "from": "screen"}))
        if desk.info:
            screen(desk)
        clk.t += 40
    keys = [NV.url_key(u) for _, _, u, _ in opened]
    dup = len(keys) - len(set(keys))
    tq = [topic for _, _, topic, _ in shorts]
    ts = [t for t, _, _, _ in shorts]
    rep = sum(1 for i, x in enumerate(tq) if any(tq[j] == x and ts[i] - ts[j] < 7200 for j in range(i)))
    new_clips = len(tq) - rep                               # clips whose topic was not seen in the previous 2 h
    qtopics = list(dict.fromkeys((title.split(" #")[0], topic) for _, title, topic, _ in shorts))
    new_q = sum(1 for i, (_, x) in enumerate(qtopics) if x not in [y for _, y in qtopics[:i]])
    hosts = collections.Counter(urllib.parse.urlsplit(u).hostname for _, _, u, _ in opened)
    follow = sum(1 for o in origins if o in NV.SEEN_ORIGINS)
    print(f"simulated {a.hours:g} h, seed {a.seed} (stubbed network; not a live browser)")
    print(f"pages opened: {len(opened)}, unique URLs per hour: {len(set(keys)) / a.hours:.1f}, "
          f"URL repeats within 7 days: {dup}")
    print(f"shorts: {len(shorts)} ({len(shorts) / a.hours:.0f}/h), from {len(qtopics)} searches; new-topic share of "
          f"clips: {new_clips / max(1, len(tq)):.2f} (topic repeat rate {rep / max(1, len(tq)):.2f}); of searches: "
          f"{new_q / max(1, len(qtopics)):.2f}")
    print(f"phone pages that were not shorts (no key, quota or per-host cap reached): "
          f"{sum(1 for _, d, u, _ in opened if d == 'phone' and 'youtube.com/shorts/' not in u)}")
    print(f"search decisions: {len(origins)} ({len(searches)} source requests), follow-ups on what he saw: "
          f"{follow / max(1, len(origins)):.2f}")
    print("traps opened:", {t: sum(1 for _, _, u, _ in opened if u == tu) for tu, t in TRAPS})
    print("footer links opened:", sum(1 for _, _, u, _ in opened if u in dict(FOOTER)))
    print("blocked sources:", {k_: v["why"] for k_, v in b.limits.blocked_now().items()})
    print("hosts:", dict(hosts.most_common(10)))
    print("dopamine-like bursts by kind (mean size, n):",
          {k_: (round(sum(v) / len(v), 3), len(v)) for k_, v in sorted(bursts.items())})
    print("YouTube Data API:", b.yt.public())


if __name__ == "__main__":
    main()
