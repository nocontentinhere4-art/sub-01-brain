"""His "readings" come from what he actually browses (#79).

Before, the Wikipedia reader (research.py) ran next to the browser whenever he was at the desk, and everything
labelled "read" (the reading stimulus, reading memory, REM replay, the memory test, the diary) was Wikipedia,
whatever the screens showed. Now a page he really stayed on becomes the reading, and research.py only runs as a
fallback when the browser is off, restarting or failing (live_server.run_research).

BrowseReadings follows the screen statuses the browser sends:
- a page counts once he leaves it (or it changes) after at least MIN_DWELL_S[kind] simulated seconds on it;
- at most one reading per READ_GAP_S simulated seconds (research.READ_EVERY_S: the same rate the reading memory,
  the replay and the memory test were built for); when several pages qualify in one gap, the best one wins (longer
  stay, real text), and an unused candidate goes stale after STALE_S;
- the kind of source (video, short, forum, news, finance, wiki, page) and its host go with the reading, so the
  pages can say "watched a Short on youtube.com" instead of "read";
- safety: the title must pass browse.display_ok (the strict filter for his own words and the cards); a finance /
  trading page is never a reading (S2: the browser refuses such pages; a status still flagged `finance` gives
  None here too, so nothing of it reaches the memory, the replay or the diary); a logged-in page keeps only its
  public title (no excerpt); the excerpt keeps only sentences that pass display_ok.
Pure: no network, no AI, nothing paid.
"""
import re
import time
import urllib.parse

from research import READ_EVERY_S, keywords

READ_GAP_S = READ_EVERY_S                 # simulated seconds between two readings (~15 per hour at the desk)
STALE_S = 30 * 60                         # an unused candidate older than this is dropped
MIN_DWELL_S = {"short": 15, "video": 60, "page": 45, "forum": 45, "news": 45, "wiki": 45, "finance": 45}
EXCERPT = 320
WIKI_MAX = 0.10                           # Wikipedia pages become readings only while they stay at most 10 % of today's
KEEP = 60

KIND_LABEL = {"video": "watched a video on {host}", "short": "watched a short on {host}",
              "forum": "read a thread on {host}", "news": "read the news on {host}", "wiki": "read about it on {host}",
              "page": "read a page on {host}"}
VERB = {"video": "watched", "short": "watched", "forum": "read", "news": "read", "wiki": "read", "page": "read"}

FORUM = re.compile(r"(^|\.)(reddit\.com|news\.ycombinator\.com|stackexchange\.com|stackoverflow\.com|lobste\.rs|"
                   r"metafilter\.com|discourse\.|forum\.)|/comments/|/thread|/t/|/item\?id=", re.I)
NEWS = re.compile(r"(^|\.)(bbc\.com|bbc\.co\.uk|nhk\.or\.jp|japantimes\.co\.jp|theguardian\.com|apnews\.com|npr\.org|"
                  r"arstechnica\.com|theverge\.com|sciencenews\.org|reuters\.com|nytimes\.com|cnn\.com|phys\.org|"
                  r"newscientist\.com|quantamagazine\.org|smithsonianmag\.com|coindesk\.com|cointelegraph\.com)$", re.I)
SHORT = re.compile(r"youtube\.com/shorts/|tiktok\.com/@[\w.]+/video/", re.I)
VIDEO = re.compile(r"youtube\.com/watch|youtu\.be/|vimeo\.com/\d|nicovideo\.jp/watch|dailymotion\.com/video", re.I)


def kind_of(status):
    """video, short, forum, news, finance, wiki or page; None for what is not a reading (results pages, left pages,
    the browser restarting)."""
    st = status or {}
    if st.get("restarting") or st.get("kind") in ("search", "left") or not st.get("url"):
        return None
    url = str(st.get("url"))
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if SHORT.search(url):
        return "short"
    if st.get("video") or VIDEO.search(url):
        return "video"
    if st.get("finance"):
        return "finance"
    if host.endswith("wikipedia.org"):
        return "wiki"
    if FORUM.search(host) or FORUM.search(urllib.parse.urlsplit(url).path + "?" + urllib.parse.urlsplit(url).query):
        return "forum"
    if NEWS.search(host) or "/news/" in url:
        return "news"
    return "page"


def excerpt(text, ok, n=EXCERPT):
    """The first sentences of the page text that may be shown (ok = browse.display_ok), cut to n characters."""
    out = []
    for s in re.split(r"(?<=[.!?])\s+", " ".join(str(text or "").split())):
        if 15 <= len(s) <= 300 and ok(s):
            out.append(s)
        if sum(len(x) + 1 for x in out) >= n:
            break
    return " ".join(out)[:n]


class BrowseReadings:
    """Turns the pages he stays on into readings (see the module docstring). `seen(status, t)` is called with every
    screen status (t = simulated time); it returns a reading when one is due, else None."""

    def __init__(self, gap_s=READ_GAP_S, display_ok=None, clock=time.time):
        if display_ok is None:
            from browse import display_ok
        self.ok, self.gap_s, self.clock = display_ok, float(gap_s), clock
        self.cur = None                    # {url, title, host, kind, t0, t1, status}
        self.texts = {}                    # url -> visible text (from the eyes' page capture)
        self.pending = None                # the best page of this gap, waiting for the next slot
        self.next_ok = 0.0
        self.recent = []                   # titles turned into readings lately (no repeats)
        self.log = []                      # [{t, title, host, kind, via}]

    def text(self, url, text):
        if url and text:
            self.texts[url] = str(text)[:4000]
            while len(self.texts) > 50:
                self.texts.pop(next(iter(self.texts)))

    def seen(self, status, t):
        st = status or {}
        url = st.get("url")
        if self.cur and url == self.cur["url"]:
            self.cur["t1"] = t
            self.cur["status"] = dict(self.cur["status"], **st)
            return self._due(t)
        self._end(t)
        kind = kind_of(st)
        self.cur = {"url": url, "t0": t, "t1": t, "kind": kind, "status": dict(st)} if kind else None
        return self._due(t)

    def flush(self, t):
        """He left the screen (put the phone down, the browser restarted): the current page ends now."""
        self._end(t)
        self.cur = None
        return self._due(t)

    def _end(self, t):
        c = self.cur
        if not c:
            return
        dwell = max(c["t1"], t) - c["t0"]
        if dwell < MIN_DWELL_S.get(c["kind"], 45):
            return
        if c["kind"] == "wiki" and not self.wiki_room(t):
            return                                          # Wikipedia is a small part of his readings, never most
        art = self.reading(c["status"], c["kind"], dwell, t)
        if art is None:
            return
        if self.pending is None or art["score"] > self.pending["score"]:
            self.pending = art

    def _due(self, t):
        p = self.pending
        if p is None:
            return None
        if t - p["t"] > STALE_S:
            self.pending = None
            return None
        if t < self.next_ok:
            return None
        self.pending, self.next_ok = None, t + self.gap_s
        self.recent = (self.recent + [p["title"]])[-KEEP:]
        self.log = (self.log + [{"t": t, "title": p["title"], "host": p["host"], "kind": p["kind"],
                                 "via": "browser"}])[-200:]
        p = dict(p, t=t)
        p.pop("score", None)
        return p

    def reading(self, st, kind, dwell, t):
        """A page -> a reading like research.py's ({title, extract, url, keywords, why}) plus host, kind, via,
        topic; None when nothing of it may be stored."""
        if kind == "finance" or st.get("finance"):          # S2: never a reading (nothing of it is stored)
            return None
        url = str(st.get("url") or "")
        host = (urllib.parse.urlsplit(url).hostname or "").removeprefix("www.")
        title = " ".join(str(st.get("title") or "").split())[:140]
        text = self.texts.get(url, "")
        logged_in = bool(st.get("site") or st.get("logged_in"))
        topic = None
        if not title or not self.ok(title) or title in self.recent:
            return None
        if kind in ("video", "short"):
            ch = str(st.get("channel") or "")
            extract = f"a {'short' if kind == 'short' else 'video'}" + (f" by {ch}" if ch and self.ok(ch) else "")
        else:
            extract = "" if logged_in else excerpt(text, self.ok)
        kws = keywords(title, extract)
        try:
            import interests
            topic = interests.topic_of(f"{title} {extract}", host)
        except Exception:
            pass
        score = min(dwell, 600) / 60 + (1.0 if len(extract) > 100 else 0.0) + (0.5 if kind != "page" else 0.0)
        why = KIND_LABEL[kind].format(host=host or "the web")
        return {"title": title, "extract": extract, "url": url, "host": host,
                "kind": kind, "via": "browser", "topic": topic, "keywords": kws, "why": why, "t": t,
                "dwell_s": round(dwell), "score": score}

    def wiki_room(self, t):
        """True while one more Wikipedia reading keeps Wikipedia at most WIKI_MAX of the last day's readings."""
        day = [r for r in self.log if t - r["t"] < 86400]
        wiki = sum(1 for r in day if r["kind"] == "wiki")
        return (wiki + 1) / (len(day) + 1) <= WIKI_MAX

    def counts(self, since=None):
        """Readings per kind and per host (for the measurement and /api/reading)."""
        rows = [r for r in self.log if since is None or r["t"] >= since]
        by_kind, by_host = {}, {}
        for r in rows:
            by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
            by_host[r["host"]] = by_host.get(r["host"], 0) + 1
        return {"n": len(rows), "kind": by_kind, "host": by_host}
