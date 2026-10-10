"""Hard novelty rules on the live path (#89, after the owner saw him reopen the same pages again and again).

Live log, 2026-10-02 17:33-18:11 UTC: "Studio Ghibli — Wikipedia" 3x plus "studio ghibli wikipedia — Wikipedia" and
"Ghibli Inc — Wikipedia" within 2 min, the same MediaWiki page 3x, the same news article twice, a Creative Commons
licence deed and "Contact Us" opened from page footers, and a search for "tiktok videos" that ended on Wikipedia.

- Visited: a URL, a video id (YouTube watch/shorts, TikTok) or a near-duplicate title is never opened again within
  REVISIT_S (7 days). Keys: url_key (host without www/m., path, the id-bearing query only) and title_key (lowercase,
  site suffixes like " — Wikipedia" / " - YouTube" removed, the word "wikipedia" removed, punctuation folded).
- Footer links: about, contact, privacy, terms, legal, licence / licence deeds, cookies, imprint, careers, ads, help,
  FAQ, sitemap, accessibility, and a site's own home page are never offered or followed.
- A search with a video word (tiktok, shorts, reels, video, clips) goes to the short-video feed (phone) or a video
  source (desk), never to Wikipedia or the general engines.
- Follow-up searches on things he saw are at most FOLLOW_MAX (25 %) of searches; seen-thing queries over that share
  are replaced by a discovery pick.
Pure; browse.py keeps one Visited per browser and saves it with the browsing state.
"""
import re
import time
import urllib.parse

REVISIT_S = 7 * 86400
KEEP = 4000
FOLLOW_MAX = 0.25
FOLLOW_WINDOW = 20
SEEN_ORIGINS = ("video", "walk", "eye", "screen", "follow_up", "reading")   # B3: what he read counts as "seen" too

ID_QUERY = ("v", "id", "p", "q", "search", "search_query", "query", "s", "list")
YT_ID = re.compile(r"(?:youtube(?:-nocookie)?\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/)|youtu\.be/)([\w-]{6,20})", re.I)
TT_ID = re.compile(r"tiktok\.com/(?:@[\w.]+/video/|player/v1/)(\d{8,25})", re.I)
SUFFIX = re.compile(r"\s*[-—–|·:]\s*(wikipedia|wikimedia commons|youtube|tiktok|reddit|hacker news|the free encyclopedia|"
                    r"bbc news|npr|abc news|the guardian|ap news|bandcamp|metafilter|science news|recipetin eats)\s*$",
                    re.I)
FOOTER_TEXT = re.compile(r"^\W*(about( us)?|contact( us)?|privacy( policy)?|terms( of (use|service))?|legal|licen[cs]e|"
                         r"copyright|cookies?( policy| settings)?|imprint|impressum|careers|jobs|advertis\w*|help|faq|"
                         r"sitemap|accessibility|feedback|press|home|homepage|top|back to top|creative commons\b.*|"
                         r"cc[ -]by.*|attribution.*|all rights reserved.*)\W*$", re.I)
FOOTER_HREF = re.compile(r"/(about|about-us|contact|contact-us|privacy|privacy-policy|terms|terms-of-use|tos|legal|"
                         r"licen[cs]es?|copyright|cookies?|cookie-policy|imprint|impressum|careers|jobs|advertis\w*|"
                         r"help|faq|sitemap|accessibility|feedback|press)(/|\.|\?|$)|creativecommons\.org/(licenses|"
                         r"publicdomain)|/wiki/(Help|Wikipedia|Special|Talk|Portal|File|Category|Template)[:_]", re.I)
# B2: words that ask for videos. Plural "shorts" and "youtube shorts" only (a "short history of tea" is an article),
# "video(s)" unless it is "video game(s)", no bare "reel(s)" / "clip(s)" (film reels, paper clips).
VIDEO_WORDS = re.compile(r"\b(tik ?toks?|youtube shorts|shorts|videos?(?!\s+games?\b)|vlogs?|yt)\b", re.I)
VIDEO_FILLER = re.compile(r"\b(watch(ing)?|see|show me|some|a few|a|an|the|of|on|about)\b", re.I)


def url_key(url):
    """A URL's identity: video id when there is one, else host (no www./m.) + path (no trailing slash) + the id-like
    query parameters."""
    u = str(url or "")
    if m := YT_ID.search(u):
        return f"yt:{m.group(1)}"
    if m := TT_ID.search(u):
        return f"tt:{m.group(1)}"
    try:
        p = urllib.parse.urlsplit(u)
    except ValueError:
        return u
    host = (p.hostname or "").lower()
    for pre in ("www.", "m.", "mobile.", "old."):
        host = host.removeprefix(pre)
    host = host.replace(".m.", ".")                       # en.m.wikipedia.org = en.wikipedia.org
    path = urllib.parse.unquote(p.path or "/").rstrip("/").lower() or "/"
    q = urllib.parse.parse_qsl(p.query)
    keep = "&".join(f"{k}={v.lower()}" for k, v in sorted(q) if k.lower() in ID_QUERY)
    return f"{host}{path}" + (f"?{keep}" if keep else "")


def title_key(title):
    """A title's identity: lowercase, site suffixes and the word "wikipedia" removed, punctuation folded."""
    t = str(title or "").strip()
    for _ in range(2):
        t = SUFFIX.sub("", t)
    t = re.sub(r"\bwikipedia\b", " ", t.lower())
    t = re.sub(r"[^\w\s]", " ", t)
    return " ".join(t.split())


def footer_link(label, href="", page_url=""):
    """A footer / boilerplate link (about, contact, privacy, terms, licences, ...) or the site's own home page."""
    if FOOTER_TEXT.match(" ".join(str(label or "").split())):
        return True
    h = str(href or "")
    if FOOTER_HREF.search(h):
        return True
    try:
        u, cur = urllib.parse.urlsplit(h), urllib.parse.urlsplit(page_url or "")
    except ValueError:
        return False
    if (u.path in ("", "/") and not u.query and cur.hostname
            and (u.hostname or "").removeprefix("www.") == (cur.hostname or "").removeprefix("www.")):
        return True                                       # the site's own home page
    return False


def video_query(q):
    """A search that asks for videos: -> the query without its video words ("" if nothing is left), else None."""
    if not VIDEO_WORDS.search(q or ""):
        return None
    rest = VIDEO_WORDS.sub(" ", q)
    return " ".join(VIDEO_FILLER.sub(" ", rest).split())        # "watch a tiktok dance" -> "dance"


class Visited:
    """URLs, video ids and titles opened in the last REVISIT_S (saved with the browsing state)."""

    def __init__(self, state=None, clock=time.time):
        self.clock = clock
        s = state or {}
        self.urls = {k: float(v) for k, v in (s.get("urls") or {}).items() if isinstance(v, (int, float))}
        self.titles = {k: float(v) for k, v in (s.get("titles") or {}).items() if isinstance(v, (int, float))}
        self.origins = [o for o in (s.get("origins") or []) if isinstance(o, str)][-FOLLOW_WINDOW:]
        self._prune()

    def _prune(self):
        now = self.clock()
        for d in (self.urls, self.titles):
            for k in [k for k, t in d.items() if now - t > REVISIT_S]:
                del d[k]
            while len(d) > KEEP:
                d.pop(next(iter(d)))

    def seen(self, url=None, title=None):
        """True when this URL / video id or a near-duplicate title was opened in the last 7 days."""
        now = self.clock()
        if url and now - self.urls.get(url_key(url), -1e18) < REVISIT_S:
            return True
        tk = title_key(title) if title else ""
        return bool(len(tk) >= 4 and now - self.titles.get(tk, -1e18) < REVISIT_S)

    def add(self, url=None, title=None):
        now = self.clock()
        if url:
            self.urls[url_key(url)] = now
        tk = title_key(title) if title else ""
        if len(tk) >= 4:
            self.titles[tk] = now
        if len(self.urls) > KEEP or len(self.titles) > KEEP:
            self._prune()

    def search(self, origin):
        """A search was made; its origin counts toward the follow-up share."""
        self.origins = (self.origins + [origin or ""])[-FOLLOW_WINDOW:]

    def follow_ok(self):
        """True while follow-up searches on things he saw stay under FOLLOW_MAX of recent searches."""
        if not self.origins:
            return True
        n = sum(1 for o in self.origins if o in SEEN_ORIGINS)
        return (n + 1) / (len(self.origins) + 1) <= FOLLOW_MAX

    def to_dict(self):
        self._prune()
        return {"urls": dict(list(self.urls.items())[-KEEP:]), "titles": dict(list(self.titles.items())[-KEEP:]),
                "origins": self.origins[-FOLLOW_WINDOW:]}
