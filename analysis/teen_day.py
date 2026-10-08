"""#89 teen interests: a simulated waking day on the browser's real choice path, before / after, as a share table.

    python analysis/teen_day.py [--days 3] [--youtube-key]

What runs for real: Browser.step / _next / _search / _search_on / _shorts / _public_videos / _open (its checks:
7-day novelty, the per-site guard, robots.txt) / pick_links / show, interests.pick, search_sources.route and Limits.
What is stubbed: the network and the page. The stub answers the way the live site was answered on 2026-10-03/04:
DuckDuckGo gives its bot check, Bing and Wikipedia refuse searches in robots.txt, the YouTube Data API answers only
with --youtube-key (channels / playlistItems / videos / search), the topic sites' own search pages answer, and every
page lists six same-site articles and two other sites (so link chains on one site can happen, as the seven King
Arthur Baking pages did live). Not a browser: it measures what he chooses to put on his screens.

The day: 07:00-23:00 Tokyo, a step every 40 s; 20-minute blocks on the phone (35 %), at the desk (45 %) or away;
hungry around breakfast, lunch and dinner. Prints the share by kind over the day (screens.screen_kind), recipe pages
outside meals, Wikipedia, the longest run of pages on one site, and the hosts.
"""
import argparse
import asyncio
import collections
import os
import random
import re
import sys
import time
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(os.environ.get("SUB01_ROOT") or Path(__file__).resolve().parents[1])))

import browse  # noqa: E402
import interests as I  # noqa: E402
import screens as SC  # noqa: E402
import search_sources as S  # noqa: E402

RECIPE_HOSTS = re.compile(r"(kingarthurbaking|justonecookbook|seriouseats|allrecipes|recipetineats)\.com$")
MEALS = ((7.5, 8.25), (12.5, 13.25), (19.0, 19.75))


def _jpeg():
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (40, 40, 40)).save(buf, "JPEG")
    return buf.getvalue()


JPEG = _jpeg()


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class Page:
    """A page that answers what browse.py asks of it."""

    def __init__(self, world):
        self.world, self.url = world, "about:blank"

    async def goto(self, url, **k):
        self.url = url

    async def content(self):
        return self.world.content(self.url)

    async def evaluate(self, js, *a):
        if "querySelectorAll('a[href]')" in js:            # _pick_link: the page's links
            return [[u, t, 9000] for u, t in self.world.links(self.url)]
        return None

    async def title(self):
        return self.url

    async def wait_for_timeout(self, ms):
        pass

    async def set_content(self, html, **k):
        self.url = "about:blank"


class World:
    def __init__(self):
        self.n = 0

    def links(self, url):
        host = urllib.parse.urlsplit(url).hostname or "example.org"
        self.n += 1
        own = [(f"https://{host}/article/{self.n}-{i}", f"A long story on {host} number {self.n}-{i}") for i in range(6)]
        other = [(f"https://www.othersite{self.n % 7}.com/post/{self.n}", f"Something else entirely {self.n}"),
                 ("https://www.kingarthurbaking.com/recipes/pretzels-" + str(self.n), f"Bavarian pretzels {self.n}")]
        return own + other

    def content(self, url):
        u = urllib.parse.urlsplit(url)
        host = u.hostname or ""
        if "duckduckgo" in host:
            return "<html><body>Unfortunately, bots use DuckDuckGo too.</body></html>"
        q = " ".join(v for k, v in urllib.parse.parse_qsl(u.query)) or "x"
        self.n += 1
        rows = "".join(f'<h3><a href="https://{host}/news/{self.n}-{i}">{q} story {self.n}-{i}</a></h3>'
                       for i in range(6))
        return f"<html><body>{rows}</body></html>"


def run_day(seed, youtube_key):
    rng = random.Random(seed)
    t0 = 1_790_000_000.0 - (1_790_000_000.0 % 86400) + 86400 * seed - 9 * 3600 + 7 * 3600   # 07:00 Tokyo
    clk = Clock(t0)
    browse.time.time = clk
    if youtube_key:
        os.environ["YOUTUBE_API_KEY"] = "simulated-not-real"
    else:
        os.environ.pop("YOUTUBE_API_KEY", None)
    world = World()
    b = browse.Browser(decide=False, rng=random.Random(seed))
    b.limits = S.Limits(clock=clk)
    b.variety = I.Variety(clock=clk)
    if hasattr(b, "visited"):
        b.visited = type(b.visited)(clock=clk)
    if hasattr(b, "yt"):
        b.yt = type(b.yt)(clock=clk)
    for sc in b.screens.values():
        sc.page, sc.ctx, sc.public = Page(world), object(), None
    shown = []

    async def _ensure(device):
        return b.screens[device]

    async def _use(sc, url):
        pass

    async def _settle(sc, why, kind, title=None, min_text=80, shoot=True, revisit=False):
        host = urllib.parse.urlsplit(sc.page.url).hostname or ""
        if not revisit and kind != "search" and hasattr(b, "fresh") and not b.fresh(sc.page.url, title or sc.page.url):
            return False
        sc.info = {"title": (title or f"page {sc.page.url}")[:140], "url": sc.page.url, "host": host.removeprefix("www."),
                   "why": why, "t": clk(), "kind": kind, "search_box": False}
        sc.scrolls_left = 0
        return await b.show(sc) if shoot else True

    async def _shoot(sc):
        sc.shot = JPEG
        sc.shot_id += 1
        return True

    async def _fetch(sc, url, hops=3, headers=None):
        u = urllib.parse.urlsplit(url)
        host = u.hostname or ""
        if u.path == "/robots.txt":
            if host in ("www.bing.com", "en.wikipedia.org"):
                return 200, "User-agent: *\nDisallow: /search\nDisallow: /w/\n"
            if host == "www.youtube.com":
                return 200, "User-agent: *\nDisallow: /results\nDisallow: /feeds/videos.xml\n"
            return 404, ""
        if host == "www.googleapis.com" and youtube_key:     # the official API (the only way videos are found)
            world.n += 10
            if "/channels" in u.path:
                return 200, '{"items":[{"contentDetails":{"relatedPlaylists":{"uploads":"UU%08d"}}}]}' % world.n
            if "/playlistItems" in u.path:
                items = ",".join('{"snippet":{"title":"upload %d"},"contentDetails":{"videoId":"%s"}}'
                                 % (world.n + i, f"upl{world.n + i:08d}") for i in range(20))
                return 200, '{"items":[%s]}' % items
            if "/videos" in u.path:
                ids = urllib.parse.parse_qs(u.query)["id"][0].split(",")
                items = ",".join('{"id":"%s","contentDetails":{"duration":"%s"},"status":{"embeddable":true,"privacyStatus":"public"}}'
                                 % (v, "PT40S" if int(v[-1]) % 2 else "PT9M") for v in ids)
                return 200, '{"items":[%s]}' % items
            items = ",".join('{"id":{"videoId":"%s"},"snippet":{"title":"api short %d","channelTitle":"c"}}'
                             % (f"api{world.n + i:08d}", world.n + i) for i in range(10))
            return 200, '{"items":[%s]}' % items
        if "duckduckgo" in host:
            return 200, "bots use DuckDuckGo too"
        return 404, ""

    async def _play_muted(sc):
        return {"muted": True}

    b._ensure, b._use, b._settle, b._shoot, b._fetch, b._play_muted = _ensure, _use, _settle, _shoot, _fetch, _play_muted
    end = t0 + 16 * 3600
    block, where = 0, None
    while clk() < end:
        if clk() >= block:
            r = rng.random()
            where = "phone" if r < 0.35 else "desk" if r < 0.80 else None
            block = clk() + 20 * 60
        hour = I.tokyo_hour(clk())
        hungry = any(a <= hour < b_ for a, b_ in MEALS)
        if where:
            interest = {"query": "", "from": "", "hour": round(hour, 2), "hungry": hungry,
                        "feed": "shorts" if where == "phone" else None}
            dv = getattr(S, "desk_video", None)
            if where == "desk" and dv and dv(clk(), I.rhythm(hour)["video"]):
                interest["feed"] = "video"
            sc = b.screens[where]
            sc.next_at = 0
            try:
                st = asyncio.run(b.step(where, [], interest))
            except Exception as e:                          # a crash in the code under test is a finding
                print("step error:", repr(e)[:200])
                st = None
            if st and st.get("url") and (not shown or shown[-1]["url"] != st["url"] or shown[-1]["device"] != where):
                shown.append({"t": clk(), "url": st["url"], "device": where, "kind": SC.screen_kind(st),
                              "host": (urllib.parse.urlsplit(st["url"]).hostname or "").removeprefix("www."),
                              "hungry": hungry})
        clk.t += 40
    UNITS.append(b.yt.used if hasattr(b, "yt") else 0)
    return shown


UNITS = []


def table(rows):
    kinds = collections.Counter(r["kind"] for r in rows if r["kind"])
    n = sum(kinds.values()) or 1
    video = sum(kinds[k] for k in ("tiktok", "shorts", "youtube"))
    recipe_out = sum(1 for r in rows if RECIPE_HOSTS.search(r["host"]) and not r["hungry"])
    run, best, prev = 0, 0, None
    for r in rows:
        if r["kind"] in ("search", "tiktok", "shorts", "youtube"):
            prev, run = None, 0
            continue
        run = run + 1 if r["host"] == prev else 1
        prev, best = r["host"], max(best, run)
    return {"pages": n, "short video + YouTube": round(video / n, 3),
            **{k: round(kinds[k] / n, 3) for k in SC.KINDS}, "recipes outside meals": round(recipe_out / n, 3),
            "longest run on one site": best,
            "YouTube API units per day (cap 9,000)": round(sum(UNITS) / len(UNITS)) if UNITS else 0,
            "top hosts": dict(collections.Counter(r["host"] for r in rows).most_common(6))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--youtube-key", action="store_true")
    a = ap.parse_args()
    rows = []
    for d in range(a.days):
        rows += run_day(d, a.youtube_key)
    import json
    print(json.dumps(table(rows), indent=1))


if __name__ == "__main__":
    main()
