"""Pages/hour and paid eyes calls/hour at the desk, before and after #56 (results pages get local options), and how far
the eyes' $1.00/Tokyo-day cap stretches. A model, not a live measurement:

    python analysis/search_budget.py [--hours 100] [--seed 0]

A chain of pages is simulated with the real option builders (eyes.local_options, eyes.result_options,
eyes.with_follow_ups) on two saved pages: a content page (a news article) and a results page (DuckDuckGo, from
tests/data/search/). The brain's vote is replaced by a uniform pick among the options (the real vote depends on the
live brain state). Timing follows browse.py: a content page is read for SCROLLS (3..7) screenshots SCROLL_EVERY_S
(7 s x 0.8..1.3) apart, a results page is decided as soon as it is shown; a page load takes ~4 s. "Before" is the code
before #56: every decided page (results pages too) costs one eyes call, at most one search among a content page's
options, and a leave searches 25 % of the time. Costs: Haiku 4.5 ($1/$5 per M tokens), input = the fixed system prompt
+ the page prompt (eyes.prompt) at ~3.6 characters per token, output ~260 tokens; eyes.MAX_CALLS_PER_HOUR (30) holds.
"""
import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import browse  # noqa: E402
import eyes as E  # noqa: E402
import search_sources as S  # noqa: E402

DATA = ROOT / "tests" / "data" / "search"
LOAD_S = 4.0
CHARS_PER_TOKEN = 3.6
OUT_TOKENS = 260
PRICE_IN, PRICE_OUT = 1.0, 5.0              # Haiku 4.5, USD per million tokens


def pages():
    news = (DATA / "news.html").read_text()
    links = [{"id": f"L{i + 1}", "href": r["url"], "text": r["title"][:100], "area": 20000 - 400 * i}
             for i, r in enumerate(S.parse_headlines(news, "https://www.sciencenews.org/?s=x"))]
    content = {"url": "https://www.sciencenews.org/article/nap-science-sleep-health", "kind": "page",
               "title": "To nap or not to nap? Science is still waking up to the question",
               "host": "sciencenews.org", "can_back": True, "search_box": True, "chain": 5, "max_chain": 30,
               "text": " ".join(S.parse_html(news).text().split())[:1500], "links": links}
    b = browse.Browser(decide=True)
    sc = b.screens["desk"]
    sc.info = {"title": "melon pan — DuckDuckGo", "kind": "search", "host": "html.duckduckgo.com",
               "results": S.parse_ddg((DATA / "ddg.html").read_text()),
               "search": {"source": "ddg", "engine": "DuckDuckGo", "query": "melon pan", "from": ""}}
    sc.history = ["a", "b"]
    results = b.result_page(sc, "https://html.duckduckgo.com/html/?q=melon+pan")
    old_results = dict(results, links=[{k: v for k, v in l.items() if k not in ("result", "snippet")}
                                       for l in results["links"]])       # before #56: plain links of the page
    return content, results, old_results


def call_usd(page):
    tin = (len(E.SYSTEM) + len(E.prompt(page))) / CHARS_PER_TOKEN
    return (tin * PRICE_IN + OUT_TOKENS * PRICE_OUT) / 1e6, round(tin)


def simulate(after, hours, rng):
    content, results, old_results = pages()
    usd_content, _ = call_usd(content)
    usd_results, _ = call_usd(old_results)
    t, kind, hour_calls = 0.0, "search", []
    stats = {"pages": 0, "search_pages": 0, "content_pages": 0, "calls": 0, "usd": 0.0, "capped": 0,
             "calls_on_results": 0, "ai_content_pages": 0}
    while t < hours * 3600:
        h = int(t // 3600)
        while len(hour_calls) <= h:
            hour_calls.append(0)
        stats["pages"] += 1
        stats[f"{kind}_pages"] += 1
        if kind == "search":
            t += LOAD_S + 7.0 * (0.8 + 0.5 * rng.random())
            if after:
                opts, paid, usd = E.result_options(results, "melon pan", rng), False, 0.0
            else:
                opts, paid, usd = E.local_options(old_results, "melon pan", rng), True, usd_results
        else:
            t += LOAD_S + sum(7.0 * (0.8 + 0.5 * rng.random()) + 0.9 for _ in range(rng.randint(3, 7)))
            opts, paid, usd = E.local_options(content, "sleep", rng), True, usd_content
            if after:
                opts = E.with_follow_ups(opts, content)
        if paid:
            if hour_calls[h] < E.MAX_CALLS_PER_HOUR:
                hour_calls[h] += 1
                stats["calls"] += 1
                stats["usd"] += usd
                stats["calls_on_results" if kind == "search" else "ai_content_pages"] += 1
            else:
                stats["capped"] += 1                        # over 30/hour: local options, no cost
        o = rng.choice(opts)
        a = o["action"]
        if a in ("search", "site_search"):
            kind = "search"
        elif a in ("click", "open_video", "play_video", "next_page", "open_comments"):
            kind = "content"
        elif a == "leave":                                  # browse._next: after #56 0.88 search, before 0.8 x ~0.3
            kind = "search" if rng.random() < (0.48 if after else 0.25) else "content"
        elif a == "back":
            kind = "content" if kind == "search" else "search"
        # scroll: the same page is read on (no new call: same URL)
    per_h = {k: v / hours for k, v in stats.items()}
    return stats, per_h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=100)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    content, results, old_results = pages()
    out = {}
    for name, after in (("before", False), ("after", True)):
        stats, per_h = simulate(after, a.hours, random.Random(a.seed))
        usd_call = stats["usd"] / max(1, stats["calls"])
        out[name] = {"pages_per_hour": round(per_h["pages"], 1), "searches_per_hour": round(per_h["search_pages"], 1),
                     "content_pages_per_hour": round(per_h["content_pages"], 1),
                     "eyes_calls_per_hour": round(per_h["calls"], 1),
                     "eyes_calls_on_results_pages_per_hour": round(per_h["calls_on_results"], 1),
                     "content_pages_with_ai_options": f"{stats['ai_content_pages'] / max(1, stats['content_pages']):.0%}",
                     "usd_per_call": round(usd_call, 5),
                     "usd_per_desk_hour": round(per_h["usd"], 4),
                     "desk_hours_per_1usd": round(1.0 / per_h["usd"], 1) if per_h["usd"] else None,
                     "pages_per_1usd": round(stats["pages"] / stats["usd"]) if stats["usd"] else None}
    _, tok_c = call_usd(content)
    out["assumptions"] = {"content_prompt_tokens_in": tok_c, "out_tokens": OUT_TOKENS, "vote": "uniform",
                          "hours_simulated": a.hours}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
