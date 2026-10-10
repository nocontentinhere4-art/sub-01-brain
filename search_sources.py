"""Where he searches (#56): more free search sources, picked per query by topic, rotated and rate-limited per host.

Sources (no key, no login, nothing paid): Bing (SafeSearch strict), DuckDuckGo HTML (kp=1, strict), Wikipedia search,
Wikimedia Commons (images), arXiv listing search, Hacker News (the Algolia API), Open Library subject pages, YouTube
search pages (Restricted Mode, as #53), and two sites searched through their own search box (#40's `site_search`):
RecipeTin Eats (recipes) and Science News (news). Each query is routed by topic (science -> arXiv, a book -> Open
Library, how-to -> DuckDuckGo, ...) and the least used source among the fitting ones wins, so no engine gets heavy
traffic. Every host is limited to PER_HOST_HOUR requests per rolling hour, robots.txt is respected (fetched once a day
per host; Open Library's /search and AP News' search page are disallowed there, which is why Open Library is searched
by subject and the news site is Science News), and every count is kept per Tokyo day for /api/browsing.

Everything here is pure (parsing, routing, limits, query building): browse.py does the network through Chromium and
still runs the guard on every result, page and title. The parsers read saved HTML / JSON in tests (no network in CI).

Queries come from him (`interest_for`): his reading notes (mind.next_interest), what he was reading, words viewers
taught him, topics his tastes favour, and viewer wishes in chat ("look up ...", `wish`). On a page, `follow_ups` builds
up to 2 searches from the page's own words (names, an unknown term: "what is ...?").
"""
import base64
import html as htmlmod
import json
import random
import re
import time
import urllib.parse
from html.parser import HTMLParser
from urllib.robotparser import RobotFileParser

PER_HOST_HOUR = 20                  # requests per rolling hour per host (searches, API calls, robots.txt)
MAX_RESULTS = 10
BLOCK_AFTER = 2                      # consecutive failures before a source is set aside (#89: rotate, never loop)
BLOCK_S = 3600.0                     # first block; doubles on each new block, at most BLOCK_MAX_S
BLOCK_MAX_S = 6 * 3600.0
ROBOTS_BLOCK_S = 86400.0             # a robots.txt refusal holds for the day robots.txt is cached
STATE_V = 2                          # #89 live follow-up: sources changed, older failure counts and blocks are dropped
NOT_BROKEN = ("rate limit", "opened in the last 7 days")     # refusals that do not mean the source is broken
ROBOTS_TTL_S = 86400.0
ROBOTS_RETRY_S = 600.0              # a robots.txt that could not be read refuses the host for 10 min only
UA_TOKEN = "Mozilla"                # robots.txt rules are read for a generic browser ('*' unless Mozilla is named)


# --- a tiny HTML tree (stdlib only) ----------------------------------------------------------------------------------
BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td", "th", "ul", "ol", "section",
         "article", "header", "footer", "dd", "dt", "figcaption", "blockquote", "table"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs=None, parent=None):
        self.tag, self.attrs, self.children, self.parent = tag, dict(attrs or {}), [], parent

    def cls(self):
        return (self.attrs.get("class") or "").split()

    def has_class(self, prefix):
        """A class equal to `prefix` or starting with it (CSS-module names carry a hash: title___vyz1w)."""
        return any(c == prefix or c.startswith(prefix + "_") for c in self.cls())

    def iter(self):
        for c in self.children:
            if isinstance(c, Node):
                yield c
                yield from c.iter()

    def find_all(self, tag=None, cls=None):
        return [n for n in self.iter() if (tag is None or n.tag == tag) and (cls is None or n.has_class(cls))]

    def find(self, tag=None, cls=None):
        return next((n for n in self.iter() if (tag is None or n.tag == tag) and (cls is None or n.has_class(cls))),
                    None)

    def text(self):
        out = []
        for c in self.children:
            if isinstance(c, Node):
                if c.tag in BLOCK:
                    out.append(" " + c.text() + " ")
                elif c.tag not in ("script", "style", "noscript", "template"):
                    out.append(c.text())
            else:
                out.append(c)
        return " ".join("".join(out).split())


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = Node(tag, [(k, v or "") for k, v in attrs], self.cur)
        self.cur.children.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, [(k, v or "") for k, v in attrs], self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:          # an end tag with no open element is ignored
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def parse_html(text):
    b = _Builder()
    try:
        b.feed(text or "")
        b.close()
    except Exception:                                       # broken markup: keep what was read
        pass
    return b.root


def _clean(s, n=200):
    return " ".join(htmlmod.unescape(str(s or "")).split())[:n]


def _result(url, title, snippet="", **extra):
    return dict({"url": url, "title": _clean(title, 140), "snippet": _clean(snippet, 240)}, **extra)


def _dedup(results, n=MAX_RESULTS):
    seen, out = set(), []
    for r in results:
        if r["url"] and r["title"] and r["url"] not in seen and r["url"].startswith(("http://", "https://")):
            seen.add(r["url"])
            out.append(r)
    return out[:n]


# --- parsers: page HTML or API JSON -> [{url, title, snippet}] -------------------------------------------------------
def bing_target(href):
    """Bing wraps results in bing.com/ck/a?...&u=a1<base64url>: the real target, or the href itself."""
    u = urllib.parse.urlsplit(href)
    if (u.hostname or "").endswith("bing.com") and u.path.startswith("/ck/"):
        v = urllib.parse.parse_qs(u.query).get("u", [""])[0]
        if v.startswith("a1"):
            try:
                return base64.urlsafe_b64decode(v[2:] + "=" * (-len(v[2:]) % 4)).decode("utf-8", "replace")
            except ValueError:
                return ""
        return ""
    return href


def parse_bing(text, base=""):
    out = []
    for li in parse_html(text).find_all("li", "b_algo"):
        h2 = li.find("h2")
        a = h2.find("a") if h2 else None
        if not a:
            continue
        cap = li.find("p", "b_lineclamp") or li.find("div", "b_caption")
        snippet = re.sub(r"^.{0,20}?\d{4}\s*·\s*", "", cap.text()) if cap else ""
        out.append(_result(bing_target(htmlmod.unescape(a.attrs.get("href", ""))), a.text(), snippet))
    return _dedup(out)


def ddg_target(href):
    """DuckDuckGo HTML links go through //duckduckgo.com/l/?uddg=<url>: the real target."""
    u = urllib.parse.urlsplit(urllib.parse.urljoin("https://html.duckduckgo.com/", href))
    if (u.hostname or "").endswith("duckduckgo.com"):
        return urllib.parse.parse_qs(u.query).get("uddg", [""])[0]
    return u.geturl()


def parse_ddg(text, base=""):
    out = []
    for res in parse_html(text).find_all("div", "result"):
        if res.has_class("result--ad") or "result--ad" in res.cls():
            continue                                        # ads are never results
        a = res.find("a", "result__a")
        if not a:
            continue
        sn = res.find(None, "result__snippet")
        out.append(_result(ddg_target(a.attrs.get("href", "")), a.text(), sn.text() if sn else ""))
    return _dedup(out)


def _mediawiki(text, base):
    out = []
    for li in parse_html(text).find_all("li", "mw-search-result"):
        head = li.find("div", "mw-search-result-heading")
        a = head.find("a") if head else None
        if not a:
            continue
        sn = li.find("div", "searchresult")
        out.append(_result(urllib.parse.urljoin(base, a.attrs.get("href", "")), a.text(), sn.text() if sn else ""))
    return _dedup(out)


def parse_wikipedia(text, base="https://en.wikipedia.org/"):
    return _mediawiki(text, base or "https://en.wikipedia.org/")


def parse_commons(text, base="https://commons.wikimedia.org/"):
    out = _mediawiki(text, base or "https://commons.wikimedia.org/")
    for r in out:                                           # "File:Inokasira Park.jpg" -> "Inokasira Park"
        name = r["title"].removeprefix("File:")
        r["title"] = re.sub(r"\.(jpe?g|png|gif|svg|tiff?|webp)$", "", name, flags=re.I).strip()
        r["image"] = True
    return out


def parse_arxiv(text, base="https://arxiv.org/"):
    out = []
    for li in parse_html(text).find_all("li", "arxiv-result"):
        t = li.find("p", "title")
        a = next((x for x in li.find_all("a") if "/abs/" in x.attrs.get("href", "")), None)
        if not t or not a:
            continue
        ab = li.find("span", "abstract-short") or li.find("p", "abstract")
        snippet = re.sub(r"\s*▽ More$", "", ab.text()) if ab else ""
        out.append(_result(urllib.parse.urljoin(base, a.attrs["href"]), t.text(), snippet))
    return _dedup(out)


def parse_hn(text, base=""):
    """The Algolia API's JSON: stories with their link (else the HN thread)."""
    try:
        hits = json.loads(text).get("hits") or []
    except (ValueError, AttributeError):
        return []
    out = []
    for h in hits:
        if not isinstance(h, dict) or not h.get("title"):
            continue
        thread = f"https://news.ycombinator.com/item?id={h.get('objectID', '')}"
        pts = h.get("points")
        out.append(_result(h.get("url") or thread, h["title"],
                           f"{pts} points on Hacker News" if isinstance(pts, int) else "Hacker News"))
    return _dedup(out)


def parse_openlibrary(text, base="https://openlibrary.org/"):
    """A subject's JSON (/subjects/<slug>.json): its works with their authors."""
    try:
        works = json.loads(text).get("works") or []
    except (ValueError, AttributeError):
        return []
    out = []
    for w in works:
        if not isinstance(w, dict) or not w.get("title") or not str(w.get("key", "")).startswith("/works/"):
            continue
        authors = ", ".join(a.get("name", "") for a in (w.get("authors") or [])[:2] if isinstance(a, dict))
        year = w.get("first_publish_year")
        out.append(_result(urllib.parse.urljoin("https://openlibrary.org/", w["key"]), w["title"],
                           " · ".join(x for x in (authors, str(year) if year else "") if x)))
    return _dedup(out)


YT_DATA = re.compile(r"(?:var ytInitialData|window\[\"ytInitialData\"\])\s*=\s*(\{.+?\});\s*</script>", re.S)


def parse_youtube(text, base=""):
    """A YouTube results page: the videos in its ytInitialData (title, channel, length)."""
    m = YT_DATA.search(text or "")
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return []
    found = []

    def walk(o, depth=0):
        if depth > 40 or len(found) >= 3 * MAX_RESULTS:
            return
        if isinstance(o, dict):
            if isinstance(o.get("videoRenderer"), dict):
                found.append(o["videoRenderer"])
            if isinstance(o.get("shortsLockupViewModel"), dict):
                found.append({"short": o["shortsLockupViewModel"]})
            for v in o.values():
                walk(v, depth + 1)
        elif isinstance(o, list):
            for v in o:
                walk(v, depth + 1)
    walk(data)

    def runs(x):
        return "".join(r.get("text", "") for r in (x or {}).get("runs", []) if isinstance(r, dict))
    out = []
    for v in found:
        if "short" in v:                                    # a Short: /shorts/<id>, its overlay title
            sh = v["short"]
            vid = (((sh.get("onTap") or {}).get("innertubeCommand") or {}).get("reelWatchEndpoint") or {}).get(
                "videoId")
            meta = sh.get("overlayMetadata") or {}
            title = (meta.get("primaryText") or {}).get("content") or re.sub(
                r",[^,]*views - play Short$", "", sh.get("accessibilityText", ""))
            if vid and re.fullmatch(r"[\w-]{6,20}", str(vid)):
                out.append(_result(f"https://www.youtube.com/shorts/{vid}", strip_tags(title),
                                   (meta.get("secondaryText") or {}).get("content", ""), video=True, short=True,
                                   hashtags=re.findall(r"#\w+", title)[:6]))
            continue
        vid = v.get("videoId")
        if not vid or not re.fullmatch(r"[\w-]{6,20}", str(vid)):
            continue
        meta = [runs(v.get("ownerText")), (v.get("lengthText") or {}).get("simpleText", "")]
        out.append(_result(f"https://www.youtube.com/watch?v={vid}", runs(v.get("title")),
                           " · ".join(x for x in meta if x), channel=runs(v.get("ownerText")), video=True))
    return _dedup(out)


def strip_tags(title):
    """A video caption without its trailing hashtags (they are kept apart and still pass the guard)."""
    t = re.sub(r"(\s*#\w+)+\s*$", "", str(title or "")).strip()
    return t or str(title or "").strip()


def _parse_tiktok(text, base="https://www.tiktok.com/"):
    import short_videos                                     # TikTok lives in its own module (#60 plugs in there)
    return short_videos.parse_tiktok(text, base)


def _tiktok_url(q):
    import short_videos
    return short_videos.tiktok_url(q)


ASIDE_TAGS = {"aside", "nav", "footer", "menu"}                  # (not <header>: articles have an entry header)
ASIDE_CLASS = re.compile(r"\b((?<!no-)sidebar|aside|related|trending|popular|most-read|recommended|widget|"
                         r"site-footer|footer-|site-nav|main-nav|navbar|nav-menu|menu-)", re.I)


def query_words(base):
    """The query a results page was asked for (its own URL's s / q / query / searchTerm / term parameter), as words."""
    u0 = urllib.parse.urlsplit(base)
    q = " ".join(v for k, v in urllib.parse.parse_qsl(u0.query) if k in ("s", "q", "query", "searchTerm", "term"))
    return [w for w in re.findall(r"\w+", q.lower()) if len(w) > 2]


def in_aside(node):
    """B3: a heading inside an aside, nav, footer, header or menu (or a sidebar / related / trending box) is not a
    result."""
    n = node.parent
    while n is not None and n.tag != "#root":
        if n.tag in ASIDE_TAGS or ASIDE_CLASS.search(n.attrs.get("class") or "") or ASIDE_CLASS.search(
                n.attrs.get("id") or ""):
            return True
        n = n.parent
    return False


def parse_headlines(text, base):
    """A site's own search results (site_search): article links in headings on the same site. B3: a heading counts
    only when it shares a word with the query (the same rule as parse_links) and is not in an aside / nav / footer,
    so a results page with nothing about the query gives [] and the rotation moves on."""
    host = urllib.parse.urlsplit(base).hostname or ""
    words = query_words(base)
    out = []
    for h in parse_html(text).iter():
        if h.tag not in ("h1", "h2", "h3", "h4"):
            continue
        a = h.find("a")
        if not a:
            continue
        url = urllib.parse.urljoin(base, a.attrs.get("href", ""))
        u = urllib.parse.urlsplit(url)
        if (u.hostname or "") != host or u.path in ("", "/") or u.query or in_aside(h):
            continue
        box = h.parent
        sn = ""
        for _ in range(3):                                  # an excerpt next to the heading, if there is one
            if box is None:
                break
            p = box.find("p")
            if p and p.text() and p.text() != a.text():
                sn = p.text()
                break
            box = box.parent
        if words and not any(w in f"{a.text()} {sn}".lower() for w in words):
            continue                                        # B3: nothing of the query in it: not a result
        out.append(_result(url, a.text(), sn))
    return _dedup(out)


def parse_links(text, base):
    """A site's own search results page when its results are not in headings: same-site article links whose text
    (at least 20 characters) has one of the query's words (the query is read from the page's own URL)."""
    host = urllib.parse.urlsplit(base).hostname or ""
    words = query_words(base)
    out = []
    for a in parse_html(text).find_all("a"):
        url = urllib.parse.urljoin(base, a.attrs.get("href", ""))
        u = urllib.parse.urlsplit(url)
        t = " ".join(a.text().split())
        if (u.hostname or "") != host or len(t) < 20 or u.path in ("", "/") or "search" in u.path.lower():
            continue
        if words and not any(w in t.lower() for w in words):
            continue
        out.append(_result(url.split("#")[0], t))
    return _dedup(out)


# --- sources ---------------------------------------------------------------------------------------------------------
def _q(params):
    return urllib.parse.urlencode(params)


def ol_slug(q):
    words = [w for w in re.findall(r"[a-z0-9]+", q.lower()) if w not in BOOK_WORDS]
    return "_".join(words[:3])


BOOK_WORDS = {"book", "books", "novel", "novels", "read", "reading", "author", "authors", "by", "about", "the", "a",
              "of", "best", "good", "story", "stories", "literature"}

SOURCES = {
    # name: label shown on the card, how to reach the results, the parser, host(s) used
    "bing": {"label": "Bing", "url": lambda q: "https://www.bing.com/search?" + _q({"q": q, "adlt": "strict",
                                                                                   "setlang": "en"}),
             "parse": parse_bing},
    "ddg": {"label": "DuckDuckGo", "url": lambda q: "https://html.duckduckgo.com/html/?" + _q({"q": q, "kp": "1"}),
            "parse": parse_ddg},
    "wikipedia": {"label": "Wikipedia", "url": lambda q: "https://en.wikipedia.org/w/index.php?" + _q(
        {"search": q, "fulltext": "1", "ns0": "1"}), "parse": parse_wikipedia},
    "commons": {"label": "Wikimedia Commons", "url": lambda q: "https://commons.wikimedia.org/w/index.php?" + _q(
        {"search": q, "fulltext": "1", "ns6": "1"}), "parse": parse_commons},
    "arxiv": {"label": "arXiv", "url": lambda q: "https://arxiv.org/search/?" + _q({"query": q, "searchtype": "all"}),
              "parse": parse_arxiv},
    "hn": {"label": "Hacker News", "url": lambda q: "https://hn.algolia.com/?" + _q({"q": q, "type": "story"}),
           "api": lambda q: "https://hn.algolia.com/api/v1/search?" + _q({"query": q, "tags": "story",
                                                                           "hitsPerPage": "20"}),
           "parse": parse_hn},
    "openlibrary": {"label": "Open Library", "url": lambda q: f"https://openlibrary.org/subjects/{ol_slug(q)}",
                    "api": lambda q: f"https://openlibrary.org/subjects/{ol_slug(q)}.json?limit=12",
                    "parse": parse_openlibrary},
    # youtube.com/robots.txt disallows /results: these two are never asked by route(); YouTube is searched through
    # the official Data API instead (youtube_api.py, with YOUTUBE_API_KEY) and played in its official embed player
    "youtube": {"label": "YouTube", "url": lambda q: "https://www.youtube.com/results?" + _q({"search_query": q}),
                "parse": parse_youtube, "feed": True},
    # short videos on the phone (#56 extension): YouTube Shorts (Restricted Mode cookie), TikTok tag pages logged out
    # (robots.txt disallows TikTok's /search; /tag is allowed)
    "shorts": {"label": "YouTube Shorts", "url": lambda q: "https://www.youtube.com/results?" + _q(
        {"search_query": f"{q} #shorts"}), "parse": parse_youtube, "feed": True},
    "tiktok": {"label": "TikTok", "url": _tiktok_url, "parse": _parse_tiktok, "feed": True},
    # sites with a WordPress search: their own results page (/?s=...), the page their search box loads (#89: the box
    # itself was often not found, "no search box"); robots.txt is checked like every source
    "recipes": {"label": "RecipeTin Eats", "url": lambda q: "https://www.recipetineats.com/?" + _q({"s": q}),
                "parse": parse_headlines},
    "news": {"label": "Science News", "url": lambda q: "https://www.sciencenews.org/?" + _q({"s": q}),
             "parse": parse_headlines},
    # #89 teen interests: sites people his age read, searched through their own results pages (robots.txt allows
    # each of these paths, checked 2026-10-04; robots.txt is checked again at run time like every source)
    "carscoops": {"label": "Carscoops", "url": lambda q: "https://www.carscoops.com/?" + _q({"s": q}),
                  "parse": parse_links},
    "pcgamer": {"label": "PC Gamer", "url": lambda q: "https://www.pcgamer.com/search/?" + _q({"searchTerm": q}),
                "parse": parse_links},
    "mal": {"label": "MyAnimeList", "url": lambda q: "https://myanimelist.net/search/all?" + _q({"q": q, "cat": "all"}),
            "parse": parse_links},
    "tmdb": {"label": "TMDB", "url": lambda q: "https://www.themoviedb.org/search?" + _q({"query": q}),
             "parse": parse_links},
    "nme": {"label": "NME", "url": lambda q: "https://www.nme.com/?" + _q({"s": q}), "parse": parse_headlines},
    "9to5mac": {"label": "9to5Mac", "url": lambda q: "https://9to5mac.com/?" + _q({"s": q}), "parse": parse_headlines},
}
GENERAL = ("ddg", "bing", "wikipedia")      # any query; the topic sources come first when they fit
TAIL = ()                                   # #89 teen: no unrelated fallback ("One Piece" never lands on Science News)
MEAL_ONLY = ("recipes",)                    # cooking sites only when he is hungry or ordering food

# topic -> the sources that fit it, best first (a query can match several topics)
TOPICS = [
    ("science", re.compile(r"\b(brain|neuro\w*|neuron\w*|sleep science|spindle\w*|dream\w*|physics|quantum|"
                           r"particle\w*|galax\w*|black holes?|cosmolog\w*|astro\w*|genom\w*|protein\w*|"
                           r"evolution|climate|mathemat\w*|theorem|equation\w*|neural network\w*|chemistry|"
                           r"molecul\w*|biolog\w*|ecolog\w*|scientists?|new study|research paper)\b", re.I),
     ("arxiv", "news", "wikipedia")),
    # B2: phrases, not generic words: "Tokyo tour" is not music, "zip code" and "Code Geass" are not code, a "series
    # of events" is not a TV series, "race" / "engine" / "switch" alone say nothing
    ("cars", re.compile(r"\b(cars?|supra|gt-?r|skyline|jdm|drift\w*|civic|type r|porsche|ferrari|lamborghini|bmw|"
                        r"toyota|nissan|honda|mazda|subaru|tesla|formula ?(?:1|one)|f1 race|grand prix|motorsport\w*|"
                        r"racing|car engines?|engine swap|tuning|supercar\w*|hypercar\w*)\b", re.I), ("carscoops",)),
    ("games", re.compile(r"\b(games?|gaming|gamer|nintendo( switch)?|playstation|ps5|xbox|steam|elden ring|minecraft|"
                         r"fortnite|zelda|pokemon|gta|valorant|speedrun\w*|esports?|indie games?)\b", re.I),
     ("pcgamer",)),
    ("anime", re.compile(r"\b(anime|manga|one piece|naruto|jujutsu|kaisen|chainsaw man|frieren|demon slayer|"
                         r"solo leveling|ghibli|dragon ball|attack on titan|spy x family|crunchyroll)\b", re.I),
     ("mal",)),
    ("movies", re.compile(r"\b(movies?|films?|tv series|netflix series|trailer|netflix|marvel|dune|cinema|box office|"
                          r"season \d+)\b", re.I), ("tmdb",)),
    ("music", re.compile(r"\b(music|songs?|albums?|rappers?|rap|hip hop|playlist|concert( tour)?|world tour|singer|"
                         r"band|city pop|lo-?fi|k-?pop|j-?pop)\b", re.I), ("nme",)),
    ("tech", re.compile(r"\b(iphone|apple|macbook|ipad|airpods|android|samsung|pixel|smartphones?|gadgets?|"
                        r"headphones|keyboards?|laptops?)\b", re.I), ("9to5mac", "hn")),
    ("code", re.compile(r"\b(programming|software|source code|coding|python|rust|linux|computers?|compilers?|"
                        r"open source|gpu|databases?|startups?)\b", re.I), ("hn",)),
    ("book", re.compile(r"\b(books?|novels?|authors?|poetry|poems?|fiction|literature|reading list)\b", re.I),
     ("openlibrary",)),
    ("recipe", re.compile(r"\b(recipes?|cook\w*|bak\w*|bread|ramen recipe|soup|curry|cake|pastry|sourdough|"
                          r"onigiri|melon ?pan|dessert|sauce|dumplings?)\b", re.I), ("recipes",)),
    ("images", re.compile(r"\b(photos?|pictures?|paintings?|architecture|temple|shrine|landscape|skyline)\b",
                          re.I), ("commons",)),
    ("encyclopedia", re.compile(r"\b(what is|who is|who was|history of|meaning of|definition|origin of|wiki)\b",
                                re.I), ("wikipedia",)),
]


def topics_of(q):
    return [name for name, rx, _ in TOPICS if rx.search(q or "")]


def host_of(name):
    s = SOURCES[name]
    return urllib.parse.urlsplit(s.get("site") or s["url"]("x")).hostname


def hosts_of(name):
    """Every host a search on this source touches (the results page and its API)."""
    s = SOURCES[name]
    out = {host_of(name)}
    if s.get("api"):
        out.add(urllib.parse.urlsplit(s["api"]("x")).hostname)
    return out


# --- per-host rate limits and per-source counts ----------------------------------------------------------------------
def tokyo_day(t):
    from datetime import datetime
    try:
        from sleep import TZ
    except Exception:                                       # pragma: no cover - sleep.py is always there
        from zoneinfo import ZoneInfo
        TZ = ZoneInfo("Asia/Tokyo")
    return datetime.fromtimestamp(t, TZ).date().isoformat()


class Limits:
    """At most `per_host` requests per rolling hour to each host; searches counted per source per Tokyo day.
    to_dict / from_dict keep it across browser restarts (the live server saves it with the browsing log)."""

    def __init__(self, per_host=PER_HOST_HOUR, clock=time.time, state=None):
        self.per_host, self.clock = per_host, clock
        s = state or {}
        self.hits = {h: [float(t) for t in ts if isinstance(t, (int, float))]
                     for h, ts in (s.get("hits") or {}).items() if isinstance(ts, list)}
        self.day = s.get("day")
        self.today = {k: int(v) for k, v in (s.get("today") or {}).items() if isinstance(v, int)}
        self.refused = {k: int(v) for k, v in (s.get("refused") or {}).items() if isinstance(v, int)}
        self.last = list(s.get("last") or [])[-20:]          # recent searches: [{t, source, query, from}]
        same = s.get("v") == STATE_V
        self.fails = {k: int(v) for k, v in (s.get("fails") or {}).items() if isinstance(v, int)} if same else {}
        self.blocked = {k: dict(v) for k, v in (s.get("blocked") or {}).items()
                        if isinstance(v, dict) and isinstance(v.get("until"), (int, float))} if same else {}
        self._roll()

    def _roll(self):
        now = self.clock()
        for h in list(self.hits):
            self.hits[h] = [t for t in self.hits[h] if now - t < 3600]
            if not self.hits[h]:
                del self.hits[h]
        day = tokyo_day(now)
        if day != self.day:
            self.day, self.today, self.refused = day, {}, {}

    def used(self, host):
        self._roll()
        return len(self.hits.get(host, []))

    def allow(self, host):
        return self.used(host) < self.per_host

    def note(self, host):
        """One request to `host` (a results page, an API call, a robots.txt)."""
        self._roll()
        self.hits.setdefault(host, []).append(self.clock())

    def source_ok(self, name):
        return not self.is_blocked(name) and all(self.allow(h) for h in hosts_of(name))

    def is_blocked(self, name):
        b = self.blocked.get(name)
        return bool(b) and b["until"] > self.clock()

    def count(self, name, query="", origin=""):
        self._roll()
        self.fails.pop(name, None)                          # it works: failures start again from zero
        b = self.blocked.get(name)
        if b and b["until"] <= self.clock():
            self.blocked[name] = dict(b, n=0)
        self.today[name] = self.today.get(name, 0) + 1
        self.last = (self.last + [{"t": round(self.clock()), "source": name, "query": query[:60],
                                   "from": origin[:60]}])[-20:]

    def refuse(self, name, why):
        self._roll()
        key = f"{name}: {why}"
        self.refused[key] = self.refused.get(key, 0) + 1
        if why in NOT_BROKEN:
            return
        self.fails[name] = self.fails.get(name, 0) + 1
        if why == "robots.txt":                             # robots.txt does not change by asking again
            self.blocked[name] = {"until": round(self.clock() + ROBOTS_BLOCK_S), "why": why, "n": 1}
            self.fails[name] = 0
            return
        if self.fails[name] >= BLOCK_AFTER:                 # set aside for a while: the next sources get their turn
            n = int((self.blocked.get(name) or {}).get("n", 0)) + 1
            secs = min(BLOCK_MAX_S, BLOCK_S * 2 ** (n - 1))
            self.blocked[name] = {"until": round(self.clock() + secs), "why": str(why)[:80], "n": n}
            self.fails[name] = 0

    def recent(self, name):
        """Searches on this source in the last hour (rotation: the least used fitting source goes first)."""
        self._roll()
        now = self.clock()
        return sum(1 for x in self.last if x.get("source") == name and now - x.get("t", 0) < 3600)

    def to_dict(self):
        self._roll()
        return {"day": self.day, "today": dict(self.today), "refused": dict(self.refused),
                "hits": {h: [round(t, 1) for t in ts] for h, ts in self.hits.items()}, "last": self.last[-20:],
                "fails": dict(self.fails), "blocked": dict(self.blocked), "v": STATE_V}

    def blocked_now(self):
        """Sources set aside right now: {name: {label, why, until (epoch s)}}."""
        return {k: {"label": SOURCES.get(k, {}).get("label", k), "why": v.get("why", ""), "until": v["until"]}
                for k, v in self.blocked.items() if v["until"] > self.clock()}

    def public(self):
        """For /api/browsing: searches per source on this Tokyo day, requests per host in the last hour."""
        self._roll()
        return {"tokyo_day": self.day, "per_source_today": dict(sorted(self.today.items(), key=lambda kv: -kv[1])),
                "total_today": sum(self.today.values()),
                "labels": {k: SOURCES[k]["label"] for k in self.today if k in SOURCES},
                "per_host_last_hour": {h: len(ts) for h, ts in sorted(self.hits.items())},
                "per_host_limit": self.per_host, "refused_today": dict(self.refused),
                "recent": [dict(x, label=SOURCES.get(x.get("source"), {}).get("label", x.get("source")))
                           for x in self.last[-10:]], "blocked": self.blocked_now()}


# --- robots.txt ------------------------------------------------------------------------------------------------------
class Robots:
    """robots.txt per host, fetched once a day by the browser (`fetch` is async: url -> (status, text)). A missing
    file (404) allows everything; 401/403 refuses the host for the day; a file that cannot be read (network error,
    5xx) refuses it for ROBOTS_RETRY_S."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.cache = {}                                     # host -> (RobotFileParser or True/False, expires)

    def known(self, host):
        c = self.cache.get(host)
        return c is not None and c[1] > self.clock()

    def load(self, host, status, text):
        ttl = ROBOTS_TTL_S
        if status == 200:
            rp = RobotFileParser()
            rp.parse((text or "").splitlines())
            v = rp
        else:
            v = status in (404, 410)                        # no file: everything allowed; 401/403/5xx: refused
            if status not in (401, 403, 404, 410):
                ttl = ROBOTS_RETRY_S                        # could not be read (network, 5xx): asked again soon
        self.cache[host] = (v, self.clock() + ttl)
        if len(self.cache) > 500:
            self.cache.pop(next(iter(self.cache)))
        return v

    def allowed(self, url):
        host = urllib.parse.urlsplit(url).hostname or ""
        c = self.cache.get(host)
        if c is None:
            return None                                     # not fetched yet
        v = c[0]
        if isinstance(v, bool):
            return v
        return v.can_fetch(UA_TOKEN, url)

    async def check(self, url, fetch, limits=None):
        """True / False for `url`, fetching the host's robots.txt first when needed (one request, rate-limited)."""
        u = urllib.parse.urlsplit(url)
        host = u.hostname or ""
        if not self.known(host):
            if limits is not None and not limits.allow(host):
                return False
            if limits is not None:
                limits.note(host)
            try:
                status, text = await fetch(f"{u.scheme}://{u.netloc}/robots.txt")
            except Exception:
                status, text = 0, ""
            self.load(host, status, text)
        return bool(self.allowed(url))


# --- routing ---------------------------------------------------------------------------------------------------------
def route(q, limits=None, rng=None, video=False, wiki_share=0.0, hungry=False):
    """Sources to try for query `q`, best first: the topic's sources, then the general engines, the least used ones
    first among sources that fit equally (rotation), sources over their per-host limit left out. Wikipedia weighs
    less once it filled more than a tenth of today's pages (`wiki_share`; novelty, not a quota)."""
    import math
    rng = rng or random.Random()
    if video:                                               # B2: a video search has no page source here: the caller
        return []                                           # goes to the video path (the Data API / the feeds)
    score = {}
    for _, rx, srcs in TOPICS:
        if rx.search(q or ""):
            for i, s in enumerate(srcs):
                score[s] = max(score.get(s, 0.0), 1.0 if i == 0 else 0.6)
    for s in GENERAL:
        score.setdefault(s, 0.35)
    for s in TAIL:                                          # #89: the other any-query sources, last (rotation)
        score.setdefault(s, 0.15)
    if not hungry:
        for s in MEAL_ONLY:                                 # #89 teen: no recipe loops outside meals
            score.pop(s, None)
    if not ol_slug(q or ""):
        score.pop("openlibrary", None)
    for s in [k for k in score if SOURCES.get(k, {}).get("feed")]:
        score.pop(s)                                        # the short-video feeds are only used by the phone feed
    if "wikipedia" in score:
        score["wikipedia"] *= math.exp(-4.0 * max(0.0, float(wiki_share or 0.0) - 0.10))
    ranked = []
    for s, w in score.items():
        if limits is not None and not limits.source_ok(s):
            continue
        used = limits.recent(s) if limits is not None else 0
        ranked.append((w / (1.0 + 0.5 * used) * (0.8 + 0.4 * rng.random()), s))
    ranked.sort(reverse=True)
    return [s for _, s in ranked]


# --- queries from him ------------------------------------------------------------------------------------------------
WISH = re.compile(r"^\s*(?:@?sub-?01[,:]?\s*)?(?:(?:can|could|would) you\s+|please\s+|pls\s+)?"
                  r"(?:look\s*up|search(?:\s+for)?|google|find(?:\s+out)?(?:\s+about)?|read\s+about|check\s+out|"
                  r"what\s+(?:is|are)|who\s+(?:is|was)|tell\s+me\s+about)\s+(.{2,80}?)\s*[?.!]*\s*$", re.I)
WISH_STRIP = re.compile(r"^(?:the|a|an|some|about)\s+|\s+(?:please|pls|for me|for us)$", re.I)


def wish(text):
    """A viewer's wish in chat ("look up melon pan", "what is a sleep spindle?") -> the query, else None. The query
    still goes through eyes.query_ok (the chat filter, blocked words) before anything is searched."""
    m = WISH.match(text or "")
    if not m:
        return None
    q = m.group(1)
    for _ in range(2):
        q = WISH_STRIP.sub("", q.strip())
    return q or None


ORIGINS = {"mind": "from his reading notes", "reading": "from what he was reading",
           "taught": "a word a viewer taught him", "tastes": "a topic his tastes favour",
           "chat": "a viewer's wish in chat", "follow_up": "a follow-up from the page",
           "familiar": "something familiar", "page": "picked on the page",
           "interests": "one of his interests", "video": "saw it in a video", "walk": "passed it on a walk",
           "eye": "something in his room's eye", "screen": "saw it on his screen"}


def interest_text(interest):
    """The plain query of an interest (a string, or {"query", "from"} from interest_for)."""
    if isinstance(interest, dict):
        return str(interest.get("query") or "")
    return str(interest or "")


def interest_origin(interest):
    return ORIGINS.get(interest.get("from"), "") if isinstance(interest, dict) else ""


SEEN_WEIGHT = {"video": 1.5, "walk": 1.2, "eye": 0.8, "screen": 1.0}
# where a walk took him (life.py activities and places) -> what he might look up afterwards
PLACE_QUERIES = {"park": "Inokashira Park", "bench": "Inokashira Park", "buy_bread": "Kichijoji bakery",
                 "bakery": "Kichijoji bakery", "bakery_in": "Kichijoji bakery", "counter": "Kichijoji bakery",
                 "shop": "Kichijoji shops", "window": "Kichijoji street view"}


# B3: words that make no search on their own (web-UI and title filler); a query made only of these, or only of words
# under 5 letters, is dropped by interest_for
GENERIC = set("""video videos watch watching official new best live full free top today really people time news
page click menu home read view part episode shorts tiktok youtube thing things stuff trailer latest update
compilation highlights reaction channel stream subscribe tonight week this that with from about""".split())


def query_fit(q):
    """A query worth typing: at least one word of 5+ letters that is not generic filler."""
    ws = re.findall(r"[^\W\d_]+", str(q or "").lower())
    return any(len(w) >= 5 and w not in GENERIC for w in ws)


def interest_for(mind=(), reading=None, taught=(), tastes=(), rng=None, query_ok=None, seen=None):
    """One query for the browser, drawn from his sources: the mind's memory-linked searches (weight 3), what he was
    reading (1), words viewers taught him (1.5), topics his tastes favour (1), and things he saw (`seen`:
    {"video": [...], "walk": [...], "eye": [...], "screen": [...]}, SEEN_WEIGHT). -> {"query", "from"} or None.
    B3: a query made only of generic filler or short words ("video", "best", "top") is never one."""
    rng = rng or random.Random()
    filt = query_ok or (lambda q: " ".join(str(q or "").split()) or None)
    ok = lambda q: (lambda r: r if r and query_fit(r) else None)(filt(q))          # noqa: E731
    pools = []
    m = [q for q in (ok(x.get("query") if isinstance(x, dict) else x) for x in (mind or [])) if q]
    if m:
        pools.append((3.0, "mind", m))
    if reading and (r := ok(reading)):
        pools.append((1.0, "reading", [r]))
    t = [q for q in (ok(x) for x in (taught or [])) if q]
    if t:
        pools.append((1.5, "taught", t))
    f = [q for q in (ok(x) for x in (tastes or [])) if q]
    if f:
        pools.append((1.0, "tastes", f))
    for origin, items in (seen or {}).items():
        qs = [q for q in (ok(x) for x in (items or [])) if q]
        if qs and origin in SEEN_WEIGHT:
            pools.append((SEEN_WEIGHT[origin], origin, qs))
    if not pools:
        return None
    total = sum(w for w, _, _ in pools)
    x = rng.random() * total
    for w, origin, qs in pools:
        x -= w
        if x <= 0:
            break
    return {"query": rng.choice(qs) if origin != "mind" else qs[min(len(qs) - 1, int(rng.random() ** 2 * len(qs)))],
            "from": origin}


def video_query(title):
    """B3: a video or page title -> a search about what it is about, or None. A name in it (ENTITY: "Ghibli Museum",
    but not in an all-capitalised clickbait title, and not a person's name), else two or more content words that
    map to one of his profile topics ("Beginner Guide to Making Ramen Noodles" -> "ramen noodles"); never the
    title's first words ("I Spent 24 Hours In A Capsule Hotel In Tokyo" -> None)."""
    import interests
    t = re.sub(r"#\w+|\(.*?\)|\[.*?\]|[|｜\-–—:].*$", " ", str(title or ""))
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9'&-]*", t)
    long = [w for w in tokens if len(w) >= 4]
    title_case = long and sum(w[0].isupper() for w in long) / len(long) >= 0.6
    if not title_case:
        for m in ENTITY.finditer(t):
            parts = [p for p in m.group(1).split(" ") if p not in CAP_STOP]
            e = " ".join(parts)
            if len(parts) >= 2 and not person_like(e):
                return e
    content = [w.lower() for w in tokens if len(w) >= 4 and w.lower() not in GENERIC and w.lower() not in COMMON]
    hits = [w for w in content if interests.topic_of(w)]
    if len(hits) >= 2:
        return " ".join(dict.fromkeys(hits[:3]))
    return None


def seen_things(live):
    """What was on his screens and around him lately, as search queries per origin (read defensively)."""
    seen = {"video": [], "walk": [], "eye": [], "screen": []}
    try:
        for st in (getattr(live.browser, "screens", None) or {}).values():
            if not st:
                continue
            if st.get("video") or "youtube.com" in str(st.get("host", "")) or "tiktok.com" in str(st.get("host", "")):
                import interests
                ch = str(st.get("channel") or "")
                seen["video"] += [video_query(st.get("title")), ch if interests.topic_of(ch) else None]   # B3
            elif st.get("kind") == "page" and st.get("title"):
                seen["screen"].append(video_query(st.get("title")))
    except Exception:
        pass
    try:
        life = live.life
        for k in (life.activity, life.place, (life.path or [None])[-1]):
            if k in PLACE_QUERIES:
                seen["walk"].append(PLACE_QUERIES[k])
    except Exception:
        pass
    try:
        if getattr(live, "eye", None):
            seen["eye"] += [o["name"] for o in live.eye.world.top(live.clock.now(), 4)]
    except Exception:
        pass
    return {k: [x for x in v if x] for k, v in seen.items()}


HUNGRY_AT = 0.5                    # life's hunger (0.35 sated .. 0.55 meal time) from which food is on his mind
DESK_VIDEO = 0.55                  # share of desk time slots that are YouTube, before the hour's video tilt
DESK_SLOT_S = 20 * 60


def desk_video(t, tilt=0.5):
    """#89 teen: whether this 20-minute slot of desk time is a YouTube session (the same answer all slot long, so
    the browser does not flip between modes); more in the evening and late at night (the rhythm's video tilt)."""
    p = min(0.9, DESK_VIDEO * (0.6 + 0.8 * float(tilt or 0.0)))
    return random.Random(int(t // DESK_SLOT_S)).random() < p


def live_interest(live, art=None, rng=None):
    """interest_for from the live server's state (a few attributes, read defensively), plus the Tokyo hour of the
    simulated clock, the taste multipliers of the interest profile and the phone's feed for the browser."""
    from eyes import query_ok
    import interests
    mind_q = []
    try:
        if getattr(live, "mind", None):
            live.mind_interest()                            # refreshes the cached next_interest() (every minute)
            mind_q = [x.get("query") for x in (live.interest[1] or []) if isinstance(x, dict)]
    except Exception:
        mind_q = []
    taught = []
    try:
        cutoff = live.clock.now() - 2 * 86400
        taught = [m.get("text") for m in live.memory.items if m.get("source") == "taught" and m.get("t", 0) > cutoff]
    except Exception:
        pass
    liked = []
    try:                                                    # B3: a favoured word only when it names a profile topic
        liked = [f["topic"] for f in live.tastes.top(n=8)["favoured"]
                 if f.get("kind") == "word" and interests.topic_of(str(f["topic"]))][:5]
    except Exception:
        pass
    it = interest_for(mind_q, art["title"] if art else None, taught[-10:], liked, rng=rng, query_ok=query_ok,
                      seen=seen_things(live))
    try:
        hour = interests.tokyo_hour(live.clock.now())
    except Exception:
        hour = interests.tokyo_hour()
    extra = {"hour": round(hour, 2), "feed": interests.rhythm(hour)["feed"]}
    try:
        extra["tastes"] = interests.taste_multipliers(live.tastes.pref)
    except Exception:
        pass
    try:
        if live.life.activity == "phone":
            extra["feed"] = "shorts"                       # #89: on the phone he scrolls shorts (TikTok / Shorts)
        elif desk_video(live.clock.now(), interests.rhythm(hour)["video"]):
            extra["feed"] = "video"                        # #89 teen: part of the desk time is YouTube
    except Exception:
        pass
    try:                                                    # #89 teen: food and cooking only when he is hungry
        from life import FOOD_ACTS
        extra["hungry"] = bool(live.life.activity in FOOD_ACTS or live.life.hunger >= HUNGRY_AT)
    except Exception:
        extra["hungry"] = False
    return dict(it, **extra) if it else dict(extra, query="", **{"from": ""})


# --- follow-up searches from a page's own words ----------------------------------------------------------------------
ENTITY = re.compile(r"\b([A-Z][a-z]{2,}(?:[ -](?:of |de |no |the )?[A-Z][a-z]{2,}){1,2})\b")
CAP_STOP = {"The", "This", "That", "These", "Those", "There", "Their", "They", "When", "Where", "What", "Which",
            "While",
            "After", "Before", "From", "With", "About", "Read", "More", "Sign", "Log", "Share", "Subscribe", "Click",
            "Home", "Menu", "Search", "Contact", "Privacy", "Terms", "Cookie", "Cookies", "Accept", "Advertisement",
            "January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
            "November", "December", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
            "Related", "Comments", "Image", "Photo", "Video", "Getty", "Images", "Updated", "Published", "Our", "You",
            "Your", "His", "Her", "Its", "New", "But", "And", "For", "How", "Why", "Who"}
COMMON = set("""about above after again against almost already also although always among another around because
become becomes before behind being below between beyond cannot could during either enough especially every everything
example following however including instead itself little might nothing often others other people perhaps please
rather really should since something sometimes still through though together toward towards under until usually
various whether which while within without would years important different another although actually available
business children community company country development government information interest national number problem
program question research service several social system through university student students million billion
percent article articles comment comments website online content privacy policy cookies newsletter subscribe
advertisement related latest popular reading continue character characters everything according announced
reported released available experience performance technology president minister particular published statement
television newspaper magazine journalist celebrity personality relationship girlfriend boyfriend apartment
restaurant interview highlights officially yesterday tomorrow afternoon beautiful wonderful incredible absolutely
definitely basically literally generally eventually currently recently previously originally completely""".split())
# B3: a capitalised run that looks like a person's name (two or three capitalised words with no place / work / group
# word) is never searched: no "who is <name>" from a news article
PLACE_WORD = re.compile(r"\b(Park|Museum|Station|Tower|City|Street|River|Temple|Shrine|Island|Bay|Lake|Mount|Mountain|"
                        r"University|Stadium|Festival|Company|Studio|Studios|Line|Airport|Prefecture|Ward|Bridge|"
                        r"Garden|Gardens|Castle|School|Hotel|Market|Store|Game|Games|Series|Season|Film|Movie|Album|"
                        r"Band|League|Cup|Championship|Prize|Award|Awards|Agency|Institute|Center|Centre|Project|"
                        r"Mission|Rover|Telescope|Hospital|Library|Zoo|Aquarium|Cafe|Bakery|Shop|Mall|Avenue|Road|"
                        r"Railway|Express|Dome|Hall|Arena|Club|Team|FC|United|Corp|Inc|Ltd|Co|Bank|Group|Records|"
                        r"Pictures|Entertainment|Motors|Motor|Electric|Industries|Labs|Lab|Foundation|Society|Union|"
                        r"Street|Village|Town|Valley|Forest|Beach|Coast|Sea|Ocean|Desert|Canyon|Falls|Peak|Hill|Hills|"
                        r"Ring|Quest|Legends|Saga|Chronicles|Wars|Trek|Kaisen|Piece|Slayer|Man|Ball|Titan|Family|"
                        r"Museum|Gallery|Exhibition|Theatre|Theater|Cinema|Boulevard|Square|Plaza|Harbor|Harbour|Port|"
                        r"Nintendo|Sony|Toyota|Honda|Nissan|Mazda|Subaru|Apple|Google|Samsung|Netflix|Disney|Ghibli|"
                        r"Pokemon|Zelda|Mario|Supra|Civic|Skyline|Switch|PlayStation|Xbox|iPhone|Galaxy|Pixel)\b")


def person_like(entity):
    """Two or three capitalised words with no place / work / group word: probably a person's name."""
    parts = str(entity or "").split()
    return 2 <= len(parts) <= 3 and all(p[:1].isupper() for p in parts) and not PLACE_WORD.search(entity)


def follow_ups(page, n=2, query_ok=None, seen=()):
    """Up to `n` searches made from the page's own words: entity names (capitalised runs: "Inokashira Park") and an
    unknown term ("what is hypnagogia?": a long word repeated on the page, not a common one, not in the title).
    -> [{"query", "label", "kind"}]."""
    ok = query_ok or (lambda q: " ".join(str(q or "").split()) or None)
    title = page.get("title", "") or ""
    text = f"{title}. {page.get('text', '') or ''}"[:4000]
    tl = title.lower()
    lead = text[:700].lower()                               # B3: the title and the first paragraph
    have = {s.lower() for s in seen}
    out = []
    counts = {}
    for m in ENTITY.finditer(text):
        parts = m.group(1).split(" ")
        while parts and parts[0] in CAP_STOP:                # "The Ghibli Museum" -> "Ghibli Museum"
            parts = parts[1:]
        while parts and parts[-1] in CAP_STOP:
            parts = parts[:-1]
        if len(parts) < 2 and not (parts and "-" in parts[0]):
            continue
        e = " ".join(parts)
        if person_like(e):                                  # B3: a person's name from an article is never searched
            continue
        counts[e] = counts.get(e, 0) + 1
    ents = [e for e in sorted(counts, key=lambda e: (-counts[e], len(e)))
            if e.lower() not in tl and e.lower() in lead]   # not the page's own subject; named up top, not in a footer
    for e in ents:
        q = ok(e)
        if q and q.lower() not in have:
            out.append({"query": q, "label": f"look up {q}", "kind": "entity"})
            have.add(q.lower())
            break
    words_ = re.findall(r"\b[a-z][a-z-]{8,}\b", text)
    wc = {}
    for w in words_:
        w = w.strip("-")
        if w in COMMON or w in tl or w.endswith(PLAIN_SUFFIXES) or len(w) > 22:
            continue
        wc[w] = wc.get(w, 0) + 1
    terms = sorted((w for w in wc if wc[w] >= 2), key=lambda w: (-wc[w], -len(w)))
    for w in terms:
        q = ok(f"what is {w}")
        if q and w not in have and not any(w in x["query"].lower() for x in out):
            out.append({"query": q, "label": f"what is {w}?", "kind": "term"})
            break
    for e in ents[1:]:                                      # no unknown term: a second name
        if len(out) >= n:
            break
        q = ok(e)
        if q and q.lower() not in have and all(q.lower() != x["query"].lower() for x in out):
            out.append({"query": q, "label": f"look up {q}", "kind": "entity"})
            have.add(q.lower())
    return out[:n]


PLAIN_SUFFIXES = ("ing", "ings", "ly", "ed", "tion", "tions", "sion", "sions", "ment", "ments", "ness", "able", "ible",
                  "ity", "ities", "ance", "ence", "ers", "ful", "less", "ships", "ship")
FOLLOW_LABEL = re.compile(r"^(look up .+|what is .+\?)$", re.I)
