"""#89 live (2026-10-04 04:02-04:53 UTC): Chromium restarted 12 times "over 1200 MB", several 7-21 s apart (a restart
re-opened the same heavy page), while the brain's ticks ran late (loop lag p95 3.5 s). Here: ads and cross-site
iframes are not loaded; a page that blew the cap is never opened again and its host is left alone after two; the
browser recycles itself at a soft cap before the watchdog's hard kill; the watchdog backs off, reads /proc in a thread,
runs the service at a lower CPU priority, and hands the heavy pages to the new process.

    python -m pytest tests/test_chromium_memory.py -q
No network, no Chromium: the pages, the process and the clock are stubbed.
"""
import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import browse  # noqa: E402
import browse_service as BS  # noqa: E402
import memory_guard as MG  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class Clock:
    def __init__(self, t=1_790_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_a_heavy_page_is_never_reopened_and_a_host_cools_down_after_two_strikes():
    clk = Clock()
    h = MG.HeavyPages(clock=clk)
    h.strike([("https://www.boredpanda.com/funny-cats/?utm_source=x", "www.boredpanda.com")])
    assert h.heavy_url("https://boredpanda.com/funny-cats/") and not h.heavy_url("https://www.boredpanda.com/other/")
    assert not h.cooling("www.boredpanda.com")                 # one strike: only that page
    clk.t += 600
    h.strike([("https://www.boredpanda.com/dogs/", "boredpanda.com")])
    assert h.cooling("boredpanda.com") and h.cooling("www.boredpanda.com") and not h.cooling("bbc.com")
    clk.t += MG.HEAVY_COOLDOWN_S + 1
    assert not h.cooling("boredpanda.com")                     # 30 minutes later it may be read again
    again = MG.HeavyPages(h.to_dict(), clock=clk)              # survives a restart
    assert again.heavy_url("https://www.boredpanda.com/dogs/")
    merged = MG.HeavyPages(clock=clk).merge({"urls": ["x.com/a"], "strikes": {"y.com": [clk.t]}}).merge(again)
    assert merged.heavy_url("https://www.boredpanda.com/dogs/") and "y.com" in merged.strikes


def test_two_strikes_more_than_an_hour_apart_do_not_cool_a_host():
    clk = Clock()
    h = MG.HeavyPages(clock=clk)
    h.strike([(None, "theguardian.com")])
    clk.t += MG.HEAVY_WINDOW_S + 5
    h.strike([(None, "theguardian.com")])
    assert not h.cooling("theguardian.com")


def test_sites_and_ad_networks():
    assert MG.site_of("i.guim.co.uk") == "guim.co.uk" and MG.site_of("www.bbc.co.uk") == "bbc.co.uk"
    assert MG.same_site("www.knowyourmeme.com", "i.kym-cdn.com") is False
    assert MG.same_site("www.theverge.com", "platform.theverge.com")
    for host in ("securepubads.g.doubleclick.net", "pagead2.googlesyndication.com", "c.amazon-adsystem.com",
                 "cdn.taboola.com", "widgets.outbrain.com", "ib.adnxs.com", "cd.connatix.com"):
        assert MG.ad_host(host), host
    assert not MG.ad_host("www.bbc.com") and not MG.ad_host("i.ytimg.com") and not MG.ad_host("media.netflix.com")
    for host in ("rr3---sn-oguelnsy.googlevideo.com", "i.ytimg.com", "www.youtube.com", "www.youtube-nocookie.com",
                 "www.tiktok.com", "p16-sign-va.tiktokcdn.com", "sf16-website-login.neutral.ttwstatic.com",
                 "www.gstatic.com", "fonts.googleapis.com", "www.googleapis.com"):
        assert not MG.ad_host(host), host                       # the content hosts themselves are never blocked


def test_the_official_players_own_frames_are_never_cut():
    # the player is the top page (the server opens the embed itself): its own frames from its own domains load
    assert MG.frame_allowed("www.youtube-nocookie.com", "www.youtube.com")
    assert MG.frame_allowed("www.youtube-nocookie.com", "www.google.com")
    assert MG.frame_allowed("www.tiktok.com", "p16-sign-va.tiktokcdn.com")
    # another site's page holding a player, an ad or a social embed: not loaded
    assert not MG.frame_allowed("www.knowyourmeme.com", "www.youtube.com")
    assert not MG.frame_allowed("www.youtube-nocookie.com", "securepubads.g.doubleclick.net")
    g = browse.Guard()

    async def resolves_public(host):
        return True
    g.resolves_public = resolves_public
    for top in ("https://www.youtube-nocookie.com/embed/qpkTV1VolHU", "https://www.tiktok.com/player/v1/6718335390845095173"):
        r = Route(top)                                          # the player page itself: a top-level navigation
        run(g.route(r))
        assert r.seen == "go", top
    r = Route("https://www.youtube.com/s/player/abc/frame.html", top_url="https://www.youtube-nocookie.com/embed/x")
    run(g.route(r))
    assert r.seen == "go"
    r = Route("https://www.tiktok.com/embed/frame", top_url="https://www.tiktok.com/player/v1/6718335390845095173")
    run(g.route(r))
    assert r.seen == "go"


class Route:
    def __init__(self, url, top_url=None, nav=True, rtype="document"):
        main = SimpleNamespace(url=top_url or url)
        frame = SimpleNamespace(parent_frame=None if top_url is None else object(), page=SimpleNamespace(main_frame=main))
        self.request = SimpleNamespace(url=url, resource_type=rtype, method="GET", is_navigation_request=lambda: nav,
                                       frame=frame)
        self.seen = None

    async def abort(self):
        self.seen = "abort"

    async def continue_(self):
        self.seen = "go"


def test_the_guard_loads_no_ads_and_no_cross_site_iframes():
    g = browse.Guard()

    async def resolves_public(host):
        return True
    g.resolves_public = resolves_public
    cases = [(Route("https://www.boredpanda.com/a/"), "go"),
             (Route("https://securepubads.g.doubleclick.net/gampad/ads?x=1", nav=False, rtype="script"), "abort"),
             (Route("https://cdn.taboola.com/libtrc/x.js", nav=False, rtype="script"), "abort"),
             (Route("https://www.ex.co/player", top_url="https://www.knowyourmeme.com/memes/x"), "abort"),
             (Route("https://embed.example-video.com/p/1", top_url="https://www.90min.com/posts/x"), "abort"),
             (Route("https://www.theguardian.com/embed/x", top_url="https://www.theguardian.com/uk"), "go"),
             (Route("https://i.kym-cdn.com/photos/x.jpg", top_url="https://knowyourmeme.com/", nav=False,
                    rtype="image"), "go")]                     # a cross-site image is fine: only frames are cut
    for r, want in cases:
        run(g.route(r))
        assert r.seen == want, (r.request.url, r.seen)


def test_open_refuses_a_heavy_page_and_a_cooling_host():
    b = browse.Browser(decide=False)
    sc = b.screens["desk"]
    sc.page, sc.ctx = SimpleNamespace(url="about:blank"), object()
    b.heavy.strike([("https://www.highsnobiety.com/p/sneakers/", "www.highsnobiety.com")])
    assert not run(b._open(sc, "https://www.highsnobiety.com/p/sneakers/", "x", "page"))
    assert "heavy on memory" in b.last_skip
    b.heavy.strike([("https://www.highsnobiety.com/p/other/", "www.highsnobiety.com")])
    assert not run(b._open(sc, "https://www.highsnobiety.com/p/third/", "x", "page"))
    assert "heavy on memory" in b.last_skip
    assert "heavy" in b.to_dict() and b.to_dict()["heavy"]["urls"]


def test_the_browser_recycles_chromium_at_its_soft_cap(monkeypatch):
    b = browse.Browser(decide=False)
    b.browser = object()
    b.screens["desk"].info = {"url": "https://www.boredpanda.com/a/", "host": "www.boredpanda.com"}
    closed, threads = [], []

    async def close(device=None):
        closed.append(device)
        b.browser = None
    b.close = close
    real_to_thread = asyncio.to_thread

    async def to_thread(fn, *a):
        threads.append(fn.__name__)
        return await real_to_thread(fn, *a)
    monkeypatch.setattr(browse.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(BS, "tree_rss_mb", lambda pid: browse.SOFT_MEM_MB + 50)
    assert run(b._over_soft_cap()) and closed == [None] and threads == ["<lambda>"]
    assert b.heavy.heavy_url("https://www.boredpanda.com/a/") and b.recycles == 1
    b.browser = object()
    assert not run(b._over_soft_cap())                         # checked at most every MEM_CHECK_S
    b.mem_checked -= browse.MEM_CHECK_S + 1
    monkeypatch.setattr(BS, "tree_rss_mb", lambda pid: browse.SOFT_MEM_MB - 50)
    assert not run(b._over_soft_cap()) and closed == [None]
    assert browse.SOFT_MEM_MB < BS.MEM_MB                      # before the watchdog's hard limit


def _watchdog(monkeypatch, rss):
    lb = BS.LocalBrowser()

    class Proc:
        returncode, pid = None, 424242
    lb.proc = Proc()
    calls = {"threads": [], "sleeps": [], "spawned": 0}

    async def spawn():
        calls["spawned"] += 1
        lb.proc = Proc()
        return True

    async def kill():
        lb.proc.returncode = -9
    lb.spawn, lb.kill = spawn, kill
    lb.client.screens = {"desk": {"url": "https://www.knowyourmeme.com/memes/x", "host": "www.knowyourmeme.com"},
                         "phone": None}
    real_to_thread = asyncio.to_thread

    async def to_thread(fn, *a):
        calls["threads"].append(getattr(fn, "__name__", "?"))
        return await real_to_thread(fn, *a)

    async def sleep(s):
        calls["sleeps"].append(s)
    monkeypatch.setattr(BS.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(BS.asyncio, "sleep", sleep)
    monkeypatch.setattr(BS, "tree_rss_mb", lambda pid: rss)
    return lb, calls


def test_the_watchdog_records_the_heavy_page_reads_proc_in_a_thread_and_backs_off(monkeypatch):
    lb, calls = _watchdog(monkeypatch, 1523.0)
    assert run(lb.ensure()) == "restarted"
    assert lb.restart_log[-1]["why"] == "over 1200 MB" and lb.restart_log[-1]["rss_mb"] == 1523.0
    assert lb.restart_log[-1]["pages"] == ["www.knowyourmeme.com"] and calls["threads"]   # /proc read off the loop
    assert lb.heavy.heavy_url("https://www.knowyourmeme.com/memes/x") and calls["sleeps"] == []   # first: no wait
    lb.client.screens = {"desk": {"url": "https://www.knowyourmeme.com/memes/y", "host": "www.knowyourmeme.com"}}
    assert run(lb.ensure()) == "restarted"                     # 7-21 s later, as live: now it waits
    assert calls["sleeps"] == [BS.BACKOFF_S] and lb.heavy.cooling("knowyourmeme.com")
    st = lb.init_state({"log": [], "heavy": {"urls": ["old.example/p"], "strikes": {}}})
    assert "old.example/p" in st["heavy"]["urls"] and any("knowyourmeme" in u for u in st["heavy"]["urls"])
    assert "knowyourmeme.com" in lb.heavy.public()["cooling"]


def test_the_watchdog_leaves_a_process_under_the_limit_alone(monkeypatch):
    lb, calls = _watchdog(monkeypatch, 800.0)
    assert run(lb.ensure()) == "ok" and calls["spawned"] == 0 and calls["threads"]


def test_the_service_runs_at_a_lower_cpu_priority(monkeypatch):
    lb = BS.LocalBrowser()
    seen = []

    async def exec_(*args, **kw):
        seen.append(args)
        return SimpleNamespace(returncode=1, pid=1)
    monkeypatch.setattr(BS.asyncio, "create_subprocess_exec", exec_)

    async def sleep(s):
        pass
    monkeypatch.setattr(BS.asyncio, "sleep", sleep)
    run(lb.spawn())
    assert seen and seen[0][:3] == ("nice", "-n", str(BS.NICE)) and seen[0][3] == lb.python


def test_init_merges_the_heavy_pages_into_the_new_process():
    from aiohttp.test_utils import TestClient, TestServer
    b = browse.Browser(decide=False)

    async def main():
        app = BS.make_app(b)
        async with TestClient(TestServer(app)) as c:
            r = await c.post("/init", json={"state": {"heavy": {"urls": ["boredpanda.com/a"],
                                                               "strikes": {"boredpanda.com": [time.time()]}}}})
            assert r.status == 200
    run(main())
    assert b.heavy.heavy_url("https://www.boredpanda.com/a") and "boredpanda.com" in b.heavy.strikes
