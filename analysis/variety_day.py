"""Topic variety over a simulated day, before and after the #56 extension (interest profile, rhythm, novelty).
A model, not a live measurement:

    python analysis/variety_day.py [--days 20] [--seed 0]

One simulated waking day (08:00-24:00 Tokyo, PAGES_PER_HOUR pages an hour) of desk browsing. Each page either stays
on the current topic (a link on the page, a follow-up, a search on his notes, which link what he read recently) or
moves on. Before: browse._next before #56 (links 55 %, a search on his reading interest 25 %, a seed site 20 %),
the leave option at 1/6, and searches landing on Wikipedia (Bing results were all bing.com/ck links that the old
code dropped, so the Wikipedia fallback ran; the room's research chain is Wikipedia too). After: browse._next now
(links 40 %, searches 48 % with interests.pick for profile_share() of them, seeds 12 %), the leave option at 1/6 plus
the streak pull, searches routed over 10 sources (Wikipedia for ~1 in 6 when it fits, less once its share grows).
Topic entropy is in bits over the profile's 12 topics (+ "other"); 12 topics evenly = 3.58 bits.
"""
import argparse
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import interests as I  # noqa: E402

PAGES_PER_HOUR = 60
TOPICS = [t for t in I.PROFILE if t != "wikipedia"]
SEED_TOPICS = ["memes", "science", "tech", "tokyo", "food", "music", "sneakers", "anime", "games", "science"]


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def day(after, rng, start=1_790_982_000.0):          # 2026-10-03 08:00 Tokyo
    clock = Clock(start)
    v = I.Variety(clock=clock)
    topic, host = rng.choice(["science", "tokyo"]), "en.wikipedia.org"
    for i in range(16 * PAGES_PER_HOUR):
        clock.t = start + i * 3600 / PAGES_PER_HOUR
        hour = 8 + i / PAGES_PER_HOUR
        v.note(f"{I.PROFILE[topic][1][0]}", "", host)
        p_leave = 1 / 6 + (0.3 * I.streak_pull(v) if after else 0.0)
        if rng.random() >= p_leave and rng.random() < 0.8:  # stays: a link, a follow-up, a search on his notes
            host = "en.wikipedia.org" if not after and rng.random() < 0.3 else "example.org"
            continue
        r = rng.random()                                    # browse._next
        if after:
            if r < 0.40:
                host = "example.org"                        # a link on the page: same topic
            elif r < 0.88:
                if rng.random() < min(0.9, 0.45 + 0.4 * I.streak_pull(v)):
                    topic = I.pick(v, hour=hour, rng=rng)["topic"]
                wiki = 0.17 * math.exp(-4.0 * max(0.0, v.wiki_share() - 0.10))
                host = "en.wikipedia.org" if rng.random() < wiki else "example.org"
            else:
                topic, host = rng.choice(SEED_TOPICS), "example.org"
        else:
            if r < 0.55:
                host = "example.org"
            elif r < 0.80:
                host = "en.wikipedia.org"                   # the search fell back to Wikipedia, same interest
            else:
                topic, host = rng.choice(SEED_TOPICS), "example.org"
    return v.public()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    out = {}
    for name, after in (("before", False), ("after", True)):
        rows = [day(after, random.Random(a.seed + d)) for d in range(a.days)]
        out[name] = {"entropy_bits": round(sum(r["entropy_bits"] for r in rows) / len(rows), 2),
                     "top_topic_share": round(sum(r["top_share"] for r in rows) / len(rows), 3),
                     "wikipedia_share": round(sum(r["wiki_share"] for r in rows) / len(rows), 3),
                     "topics_seen": round(sum(len(r["topics"]) for r in rows) / len(rows), 1)}
    out["max_entropy_bits"] = round(math.log2(len(TOPICS)), 2)
    out["days"] = a.days
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
