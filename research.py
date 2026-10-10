"""What SUB-01 reads at the computer: a curiosity chain on Wikipedia.

While the life simulation is in the "research" activity, every READ_EVERY_S simulated seconds the character opens
one article: a word from recent chat if there is a fresh one, otherwise a link from the article it read last.
Which link is brain-guided: each link title is routed to networks through chat.py's lexicon, weighted by how active
those networks are right now (relative activity from the live tick), plus a bonus for titles not read in the last
7 days and a little noise; the pick is a softmax draw. Only the public Wikipedia API is used (text under CC BY-SA
4.0, credited with a link on the page); no other website is visited and nothing is posted anywhere. Articles about
violence, sex, self-harm, drugs, extremism, gambling and real living people's private matters are skipped
(finance is allowed since #56: read-only, never advice).

One source among many (#56): when the screens' browser showed him something lately (a video, an article, a forum
thread), `saw()` keeps it, `current()` returns whichever is newer, so "on his mind" is what he is actually reading,
and the Wikipedia chain waits (`due()`) until he has not looked at anything else for READ_EVERY_S.

What it reads reaches the brain model only as a stimulus: up to 8 keywords (title + extract) go through chat.py's
rule table at half the gain of a chat message, plus a small language + attention drive. The model does not
understand the text; the keywords only decide which stimulus groups get a push.
"""
import json
import math
import os
import random
import re
import time
import urllib.parse
import urllib.request

from chat import networks_for, stimulus as chat_stimulus

API = "https://{lang}.wikipedia.org/w/api.php"
SUMMARY = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
UA = "SUB-01/1.0 (simulated reader; https://github.com/nocontentinhere4-art/sub-01)"
READ_EVERY_S = 4 * 60                 # simulated seconds per article while researching
KEEP = 40                             # articles kept in the reading log
N_KEYWORDS = 8
READING_GAIN = 0.5                    # a reading drives the chat rules at half the gain of a chat message...
READING_DRIVE = {"language": 1.5, "attention": 1.5}   # ...plus a small push to language + attention
NOVEL_S = 7 * 86400                   # "new to it": not read in the last 7 simulated days
NOVELTY = 1.0                         # score bonus for a new title
NOISE = 0.3                           # sd of the score noise
TEMPERATURE = float(os.environ.get("SUB01_CURIOSITY_TEMP", "0.5"))   # softmax temperature of the link pick
NET_NAME = {"memory": "memory", "reward": "reward", "visual": "visual", "somatomotor": "body-movement",
            "language": "language", "attention": "attention", "control": "control", "default": "default-mode",
            "limbic": "limbic", "salience": "salience", "fear": "threat", "relay": "thalamic relay"}
BLOCK = re.compile(
    r"murder|killing|massacre|genocide|terror|suicide|self.?harm|rape|sexual|porn|nude|drug|cocaine|heroin|"
    r"weapon|firearm|bomb|shooting|war crime|nazi|extremis|abuse|torture|execution|cannibal|"
    r"casino|gambling|scandal|death of|assassination", re.I)
STOP = set("the a an and or but if of to in on at for with from by is are was were be been it this that these those "
           "i you he she we they me my your his her our their what why how who when where which not no yes so very "
           "just can will would could should do does did have has had il lo la i gli le un una e o ma di da in con su "
           "per tra fra che chi non si sono sei è era ciao hello hi lol ok "
           # extra EN/IT function words and encyclopedia filler (keywords only)
           "also its into onto over under after before during between than then there about since while being both "
           "each only some such other others many most more much known called named first second third one two "
           "three four five used uses using may might well like made make makes part include includes including "
           "included located based number often several way became become becomes later early late among within "
           "without throughout through around upon towards area areas form forms type types term terms refers refer "
           "referred "
           # B3: web-UI and video-title filler, never a keyword or a query ("Elden Ring Official Trailer" -> elden ring)
           "video videos watch watching official new best live full episode part shorts tiktok youtube page click "
           "menu home news read view free time top people today really latest trailer teaser reaction reacts vlog "
           "compilation highlights update updated subscribe channel stream streaming premiere exclusive viral "
           "del della dello dei degli delle nel nella nei negli nelle sul sulla alla alle agli allo come anche "
           "più molto questo questa questi queste quello quella sua suo suoi sue loro essere stato stata tra "
           "dopo prima durante dove quando mentre ogni altri altre altro altra viene sono".split())


def get(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def safe(title, text=""):
    return not BLOCK.search(title) and not BLOCK.search(text[:600])


def search(word, lang="en"):
    q = urllib.parse.urlencode({"action": "opensearch", "search": word, "limit": 5, "namespace": 0, "format": "json"})
    titles = get(API.format(lang=lang) + "?" + q)[1]
    return [t for t in titles if safe(t)]


LINK_PAGES = 3                        # B5: requests per article (pllimit 500 each: the pool is the whole article's links,
LINK_LIMIT = 500                      # not the alphabetical prefix that one 200-link page gave)


def links(title, lang="en"):
    out, cont = [], {}
    for _ in range(LINK_PAGES):
        q = urllib.parse.urlencode({"action": "query", "titles": title, "prop": "links", "plnamespace": 0,
                                    "pllimit": LINK_LIMIT, "format": "json", **cont})
        d = get(API.format(lang=lang) + "?" + q)
        pages = d.get("query", {}).get("pages", {})
        out += [l["title"] for p in pages.values() for l in p.get("links", [])]
        cont = {k: v for k, v in (d.get("continue") or {}).items() if k in ("plcontinue", "continue")}
        if not cont.get("plcontinue"):
            break
    # no lists / indexes, no years and numbers ("1,000,000,000", "1917"), no titles starting with punctuation
    return [t for t in dict.fromkeys(out)
            if safe(t) and not re.match(r"^(List of|Index of|Outline of|\d|[,.;:'\"(\[-])", t)]


def summary(title, lang="en"):
    d = get(SUMMARY.format(lang=lang, title=urllib.parse.quote(title.replace(" ", "_"), safe="")))
    if d.get("type") not in ("standard", None) or not d.get("extract"):
        return None
    if not safe(d.get("title", title), d.get("extract", "")):
        return None
    return {"title": d.get("title", title), "extract": d["extract"][:420],
            "url": d.get("content_urls", {}).get("desktop", {}).get("page", ""), "lang": lang}


def words(text):
    return [w for w in re.findall(r"[a-zA-ZÀ-ÿ]{4,}", text.lower()) if w not in STOP]


def keywords(title, extract="", n=N_KEYWORDS):
    """Up to n keywords of an article: title words first, then the most frequent extract words (stopwords out)."""
    score, order = {}, []
    for k, (text, bonus) in enumerate(((title, 3.0), (extract, 0.0))):
        for w in re.findall(r"[a-zA-ZÀ-ÿ]{3,}", text.lower()):
            if w in STOP:
                continue
            if w not in score:
                score[w] = 0.0
                order.append(w)
            score[w] += 1.0 + bonus
    return sorted(order, key=lambda w: (-score[w], order.index(w)))[:n]


def reading_stimulus(title, kws):
    """-> ({group: drive}, [groups hit], emotion): chat.py's rules on title + keywords at READING_GAIN, plus
    READING_DRIVE. Drives are before the sleep-stage gain, like chat.stimulus."""
    stim, _, emotion = chat_stimulus(" ".join([title] + list(kws)))
    stim = {g: READING_GAIN * a for g, a in stim.items()}
    for g, a in READING_DRIVE.items():
        stim[g] = stim.get(g, 0.0) + a
    return stim, list(stim), emotion


def curiosity(cands, rel, history, t, rng, temperature=TEMPERATURE):
    """Softmax pick among link titles. score = sum(lexicon weight x relative activity of that network)
    + NOVELTY if not read in the last 7 days + noise. -> (title, info) or (None, None)."""
    if not cands:
        return None, None
    rel = rel or {}
    rows = []
    for title in cands:
        contrib = {g: w * rel.get(g, 1.0) for g, w in networks_for(title).items()}
        novel = t - history.get(title, -1e18) > NOVEL_S
        score = sum(contrib.values()) + (NOVELTY if novel else 0.0) + rng.gauss(0.0, NOISE)
        rows.append((title, score, contrib, novel))
    top = max(r[1] for r in rows)
    w = [math.exp((r[1] - top) / max(temperature, 1e-6)) for r in rows]
    k = rng.choices(range(len(rows)), weights=w)[0]
    title, score, contrib, novel = rows[k]
    hot = {g: c for g, c in contrib.items() if rel.get(g, 1.0) > 1.0}        # only above-average areas count as "active"
    nets = sorted(hot, key=lambda g: -hot[g])[:2]
    if nets and sum(hot.values()) >= NOVELTY:
        names = [NET_NAME.get(g, g) for g in nets]
        why = f"chose it: {' and '.join(names)} areas were most active (its title maps there)"
    elif novel:
        why = "chose it: new to it (not read in the last 7 days)"
    else:
        why = "chose it by chance"
    return title, {"why": why, "networks": nets, "p": round(w[k] / sum(w), 3), "candidates": len(rows),
                   "novel": novel}


class Reader:
    def __init__(self, state=None, rng=None):
        s = state or {}
        self.log = s.get("log", [])          # [{t, title, extract, url, why}]
        self.used = set(s.get("used", []))   # chat messages already turned into a search
        self.history = s.get("history", {})  # title -> last sim time read (novelty, 7 days)
        self.next_t = 0.0
        self.rng = rng or random.Random()
        self.temperature = TEMPERATURE
        self.seen = s.get("seen")             # the last page or video the browser showed him (#56)

    def to_dict(self):
        return {"log": self.log[-KEEP:], "used": list(self.used)[-200:], "history": self.history, "seen": self.seen}

    def current(self):
        """What is on his mind: the newer of the last Wikipedia article and the last thing the browser showed."""
        art = self.log[-1] if self.log else None
        if self.seen and (art is None or self.seen.get("t", 0) >= art.get("t", 0)):
            return self.seen
        return art

    def due(self, t):
        return t >= self.next_t and not (self.seen and t - self.seen.get("t", 0) < READ_EVERY_S)

    def record(self, art):
        """A reading that came from the browser (#79): in the log ("on his mind", /api/reading) like an article."""
        self.log = (self.log + [art])[-KEEP:]
        self.history[art["title"]] = art.get("t", 0)
        return art

    def saw(self, status, t):
        """The browser showed a page or a video (a screen status). Only titles fit for the public card are kept."""
        from browse import display_ok
        title = " ".join(str((status or {}).get("title") or "").split())[:140]
        if not title or not display_ok(title) or status.get("restarting"):
            return None
        if self.seen and self.seen.get("url") == status.get("url"):
            self.seen["t"] = t
            return self.seen
        video = bool(status.get("video")) or "youtube.com" in str(status.get("host")) or "tiktok.com" in str(
            status.get("host"))
        self.seen = {"title": title, "url": status.get("url", ""), "host": status.get("host", ""), "t": t,
                     "source": "browser", "kind": "video" if video else "page", "extract": "",
                     "why": "on his screen: " + ("a video" if video else str(status.get("host") or "a page")),
                     "keywords": keywords(title)}
        return self.seen

    def read(self, t, heard, rel=None):
        """Open one article (blocking: run in a worker thread). `heard` = recent chat texts, newest last;
        `rel` = {group: activity / mean activity} from the latest brain tick (guides which link it follows)."""
        self.next_t = t + READ_EVERY_S
        seen = {e["title"] for e in self.log}
        tries = []
        for text in reversed(heard[-5:]):
            if text in self.used:
                continue
            self.used.add(text)
            for w in sorted(words(text), key=len, reverse=True)[:3]:
                tries.append((w, f"from chat: “{text[:60]}”"))
            break
        last = self.current()
        try:
            for w, why in tries:
                for title in search(w):
                    if title not in seen and (art := summary(title)):
                        return self._add(t, art, why)
            if last:
                options = [x for x in links(last["title"]) if x not in seen]
                for _ in range(6):
                    title, info = curiosity(options, rel, self.history, t, self.rng, self.temperature)
                    if title is None:
                        break
                    options.remove(title)
                    if art := summary(title):
                        return self._add(t, art, f"followed a link from “{last['title']}” · {info['why']}",
                                         curiosity=info)
            for title in ("Tokyo", "Kichijōji", "Inokashira Park", "Sleep", "Dream", "Bread", "Memory"):
                if title not in seen and (art := summary(title)):
                    return self._add(t, art, "started somewhere familiar")
        except Exception as e:                    # offline or rate-limited: try again next time
            print("research: wikipedia failed:", repr(e)[:120], flush=True)
        return None

    def _add(self, t, art, why, **extra):
        art = dict(art, t=t, why=why, keywords=keywords(art["title"], art.get("extract", "")), **extra)
        self.log = (self.log + [art])[-KEEP:]
        self.history[art["title"]] = t
        self.history = {k: v for k, v in self.history.items() if t - v <= NOVEL_S}
        return art
