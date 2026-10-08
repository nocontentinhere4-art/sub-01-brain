"""Readings per host and kind over a simulated day at his screens, before and after #79. A model, not a live run:

    python analysis/readings_day.py [--hours 8] [--seed 0]

Before #79: research.py read one Wikipedia article every READ_EVERY_S (240 s) while he was at the desk, whatever
the browser showed; those were all his readings. After: readings.BrowseReadings turns the pages he stays on into
readings (dwell rules, one per READ_GAP_S, the best page of each gap). The page stream: queries from
interests.pick by the Tokyo hour, routed by search_sources.route, a results page (not a reading), then one to three
pages on hosts typical of that source (videos 2-10 min, shorts 10-45 s on the phone at lunch and late night,
articles 35-60 s), a screen status every 7 s as browse.py sends them. Titles are the queries (synthetic).
"""
import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import interests as I  # noqa: E402
import search_sources as S  # noqa: E402
from readings import BrowseReadings  # noqa: E402
from research import READ_EVERY_S  # noqa: E402

STEP_S = 7.0
# source -> [(host, url path, kind-ish flags)] the result pages lead to
LEADS = {
    "ddg": [("www.justonecookbook.com", "/recipe/", {}), ("www.reddit.com", "/r/x/comments/1/", {}),
            ("www.theverge.com", "/2026/10/2/story", {}), ("www.japan-guide.com", "/e/e3000.html", {}),
            ("en.wikipedia.org", "/wiki/X", {})],
    "bing": [("www.timeout.com", "/tokyo/things", {}), ("arstechnica.com", "/science/2026/x", {}),
             ("www.reddit.com", "/r/y/comments/2/", {}), ("en.wikipedia.org", "/wiki/Y", {})],
    "wikipedia": [("en.wikipedia.org", "/wiki/Z", {})],
    "commons": [("commons.wikimedia.org", "/wiki/File:x.jpg", {})],
    "arxiv": [("arxiv.org", "/abs/2609.00520", {})],
    "hn": [("news.ycombinator.com", "/item?id=1", {}), ("github.com", "/x/y", {})],
    "openlibrary": [("openlibrary.org", "/works/OL1W", {})],
    "youtube": [("www.youtube.com", "/watch?v=abcdefg", {"video": {"watching": True}})],
    "shorts": [("www.youtube.com", "/shorts/abcdefg", {"video": {"watching": True}})],
    "tiktok": [("www.tiktok.com", "/@a.b/video/123456789", {"video": {"watching": True}})],
    "recipes": [("www.recipetineats.com", "/melon-pan/", {})],
    "news": [("www.sciencenews.org", "/article/x", {})],
}
FINANCE_LEADS = [("www.coingecko.com", "/en/coins/x", {"finance": True}),
                 ("finance.yahoo.com", "/quote/7203.T/", {"finance": True}),
                 ("www.reddit.com", "/r/CryptoCurrency/comments/3/", {"finance": True})]


def after(hours, rng, start_h=10.0):
    r = BrowseReadings(display_ok=lambda s: True)
    t, end = 0.0, hours * 3600
    v = I.Variety(clock=lambda: 1_790_982_000.0 + t)
    while t < end:
        hour = (start_h + t / 3600) % 24
        p = I.pick(v, hour=hour, rng=rng)
        q, topic = p["query"], p["topic"]
        feed = I.rhythm(hour)["feed"] == "shorts" and rng.random() < 0.6
        srcs = (["shorts", "tiktok"] if feed else S.route(q, rng=rng, wiki_share=v.wiki_share()))
        src = srcs[0]
        results = {"url": f"https://{src}.example/search?q=x", "kind": "search", "title": f"{q} — search"}
        for _ in range(2):                                   # the results page: decided at once (~14 s)
            r.seen(results, t)
            t += STEP_S
        for _ in range(rng.randint(1, 3) if not feed else rng.randint(3, 6)):
            host, path, flags = rng.choice(FINANCE_LEADS if topic in ("crypto", "markets") and rng.random() < 0.7
                                           else LEADS.get(src, LEADS["ddg"]))
            url = f"https://{host}{path}{rng.randrange(10 ** 6)}"
            st = dict({"url": url, "title": f"{q} ({host})", "host": host, "kind": "page"}, **flags)
            if flags.get("video") and "/shorts/" not in path and "tiktok" not in host:
                dwell = rng.uniform(120, 600)
            elif flags.get("video"):
                dwell = rng.uniform(10, 45)
            else:
                dwell = rng.uniform(25, 70)
            v.note(st["title"], q, host)
            t0 = t
            while t - t0 < dwell:
                if (art := r.seen(st, t)) is not None:
                    pass
                t += STEP_S
        r.seen({"url": "https://example.org/end", "kind": "search"}, t)
    return r


def summarise(counts, hours):
    n = max(1, counts["n"])
    host = {h: round(c / n, 3) for h, c in sorted(counts["host"].items(), key=lambda kv: -kv[1])[:8]}
    kind = {k: round(c / n, 3) for k, c in sorted(counts["kind"].items(), key=lambda kv: -kv[1])}
    wiki = sum(c for h, c in counts["host"].items() if h.endswith("wikipedia.org")) / n
    return {"readings": counts["n"], "per_hour": round(counts["n"] / hours, 1), "wikipedia_share": round(wiki, 3),
            "kind_share": kind, "top_hosts": host}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=8)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    before_n = int(a.hours * 3600 / READ_EVERY_S)
    out = {"before": {"readings": before_n, "per_hour": round(before_n / a.hours, 1), "wikipedia_share": 1.0,
                      "kind_share": {"wiki": 1.0}, "top_hosts": {"en.wikipedia.org": 1.0}}}
    days = [after(a.hours, random.Random(a.seed + d)) for d in range(5)]
    tot = {"n": 0, "kind": {}, "host": {}}
    for r in days:
        c = r.counts()
        tot["n"] += c["n"]
        for k in ("kind", "host"):
            for x, y in c[k].items():
                tot[k][x] = tot[k].get(x, 0) + y
    out["after"] = summarise(tot, a.hours * len(days))
    out["after"]["memory_test_items_day1"] = [x["title"] for x in days[0].log[:5]]
    out["hours_at_screens"] = a.hours
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
