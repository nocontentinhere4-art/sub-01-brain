"""What is really on his screens (#89), and the simulated dopamine-like bursts when something new plays.

ScreensStatus keeps an honest, always-visible summary for /brain and /life (GET /api/screens):
- the browser: up, down (and why, since when) or off (no playwright / BROWSE=0);
- the last 10 pages, each with its kind and host;
- today's share by kind (Tokyo day): tiktok, shorts (YouTube Shorts), youtube, news, forum, finance, wikipedia,
  search (results pages), other;
- notes from the feed, e.g. "TikTok blocked from the server today → YouTube Shorts".

DopamineBursts: when a new short starts, a phasic dopamine-like burst whose size is a reward-prediction error,
    rpe = novelty + predicted interest - expectation,
- novelty: 1 for a topic not seen in the last NOVEL_S, else 0.3;
- predicted interest: his tastes' prediction for the title's words (tastes.py, -1..1) mapped to 0..1;
- expectation: a running mean of (novelty + interest) over recent clips (a Rescorla-Wagner value), relaxing back to
  EXPECT0 over RELAX_S while nothing new plays (a new scroll session surprises again);
habituating over a scroll session (clips less than SESSION_GAP_S apart): x 1 / (1 + HABITUATION x (n - 1)), the
"doomscrolling" curve. Other videos give half the burst, pages a quarter; nothing new playing gives nothing; a
results page or a finance / trading page (S2) gives nothing either. It is a simulated dopamine-like reward signal in
the model (it drives the reward regions and the DA level), not a feeling.
"""
import math
import re
import time
import urllib.parse

from readings import kind_of

KINDS = ("tiktok", "shorts", "youtube", "news", "forum", "finance", "wikipedia", "search", "other")
LAST_N = 10
NOVEL_S = 30 * 60
SESSION_GAP_S = 5 * 60
HABITUATION = 0.12
ALPHA = 0.15
EXPECT0 = 0.6                       # the expectation at rest; it relaxes back to this between clips (RELAX_S)
RELAX_S = 300.0
SCALE = {"tiktok": 1.0, "shorts": 1.0, "youtube": 0.5, "video": 0.5}
PAGE_SCALE = 0.25
TIKTOK_ID = re.compile(r"^https://www\.tiktok\.com/@[\w.]{2,30}/video/(\d{8,25})(?:[?#]|$)")
TIKTOK_EMBED = "https://www.tiktok.com/player/v1/{}?autoplay=0&muted=1&rel=0"
YT_ID = re.compile(r"^https://www\.youtube\.com/(?:shorts/|watch\?v=)([\w-]{11})(?:[?&#]|$)")
DA_LABEL = "simulated dopamine-like reward signal in the model"


def screen_kind(st):
    """One of KINDS for a screen status (None for a restarting browser or an empty status)."""
    st = st or {}
    if st.get("restarting") or not st.get("url"):
        return None
    if st.get("kind") == "search":
        return "search"
    url = str(st.get("url"))
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    k = kind_of(st)
    if k == "short":
        return "tiktok" if host.endswith("tiktok.com") else "shorts"
    if k == "video":
        return "youtube" if re.search(r"(^|\.)(youtube\.com|youtu\.be)$", host) else "other"
    if k == "wiki":
        return "wikipedia"
    if k in ("news", "forum", "finance"):
        return k
    return "other" if k else None


def tokyo_day(t):
    from search_sources import tokyo_day as d
    return d(t)


def hhmm(t):
    from datetime import datetime
    try:
        from sleep import TZ
    except Exception:                                       # pragma: no cover
        from zoneinfo import ZoneInfo
        TZ = ZoneInfo("Asia/Tokyo")
    return datetime.fromtimestamp(t, TZ).strftime("%H:%M")


class ScreensStatus:
    def __init__(self, clock=time.time, state=None):
        self.clock = clock
        self.state, self.why, self.since = "starting", "", clock()
        self.last = []                       # [{t, kind, host, title, device}]
        self.day, self.counts = None, {}
        self.url = {}                        # device -> url shown last (a page counts once)
        self.notes = []                      # [{t, text}]
        self.restarts = 0
        self._restore(state)

    def _restore(self, s):
        """#89: today's counts, the last pages and the notes survive a deploy (saved with the live server's state)."""
        if not isinstance(s, dict):
            return
        if isinstance(s.get("day"), str):
            self.day = s["day"]
        self.counts = {k: int(v) for k, v in (s.get("counts") or {}).items()
                       if k in KINDS and isinstance(v, (int, float)) and v >= 0}
        ok = lambda x: isinstance(x, dict) and isinstance(x.get("t"), (int, float)) and isinstance(x.get("kind"), str)  # noqa: E731
        self.last = [dict(x) for x in (s.get("last") or []) if ok(x)][-LAST_N:]
        self.notes = [{"t": float(n["t"]), "text": str(n.get("text") or "")[:140]} for n in (s.get("notes") or [])
                      if isinstance(n, dict) and isinstance(n.get("t"), (int, float))][-5:]
        self.url = {k: v for k, v in (s.get("url") or {}).items() if isinstance(k, str) and isinstance(v, str)}

    def to_dict(self):
        self._roll()
        return {"day": self.day, "counts": dict(self.counts), "last": list(self.last), "notes": list(self.notes),
                "url": dict(self.url)}

    def _roll(self):
        d = tokyo_day(self.clock())
        if d != self.day:
            self.day, self.counts, self.notes = d, {}, []

    def set_off(self, why):
        self.state, self.why, self.since = "off", why, self.clock()

    def idle(self, why):
        """Nobody at a screen: the browser process is not needed (it starts when he picks one up)."""
        if self.state not in ("off", "idle"):
            self.state, self.why, self.since = "idle", why, self.clock()

    def browser_down(self, why):
        if self.state != "down":
            self.state, self.why, self.since = "down", str(why)[:120], self.clock()
            self.restarts += 1
            return True                      # first report of this outage (log it once)
        return False

    def browser_up(self):
        if self.state != "up":
            self.state, self.why, self.since = "up", "", self.clock()

    def note(self, text):
        self._roll()
        text = str(text)[:140]
        if not self.notes or self.notes[-1]["text"] != text:
            self.notes = (self.notes + [{"t": self.clock(), "text": text}])[-5:]

    def seen(self, st):
        """A screen status: the browser is up; a new page is counted once. Returns its kind when it is new."""
        st = st or {}
        if st.get("restarting"):
            self.browser_down("restarting")
            return None
        self.browser_up()
        kind = screen_kind(st)
        dev = st.get("device") or "desk"
        if kind is None or self.url.get(dev) == st.get("url"):
            return None
        self.url[dev] = st.get("url")
        self._roll()
        self.counts[kind] = self.counts.get(kind, 0) + 1
        host = (urllib.parse.urlsplit(str(st.get("url"))).hostname or "").removeprefix("www.")
        item = {"t": self.clock(), "kind": kind, "host": host, "device": dev, "title": str(st.get("title") or host)[:90]}
        if kind == "tiktok" and (m := TIKTOK_ID.search(str(st.get("url")))):
            item["tiktok_id"] = m.group(1)   # viewers may play it in TikTok's official embed player (#89)
        elif kind in ("shorts", "youtube") and (m := YT_ID.search(str(st.get("url")))):
            item["youtube_id"] = m.group(1)  # ... or YouTube's (youtube-nocookie), muted, no autoplay
        self.last = (self.last + [item])[-LAST_N:]
        return kind

    @staticmethod
    def _row(x, ok):
        return _row_impl(x, ok)

    def public(self, display_ok=None):
        self._roll()
        total = sum(self.counts.values())
        ok = display_ok or (lambda s, host="": True)   # (title, host) -> shown
        return {"browser": {"state": self.state, "why": self.why, "since": hhmm(self.since), "restarts": self.restarts},
                "last": [self._row(x, ok) for x in reversed(self.last)],
                "today": {"tokyo_day": self.day, "total": total, "counts": dict(self.counts),
                          "share": {k: round(self.counts.get(k, 0) / total, 3) for k in KINDS} if total else {}},
                "notes": [dict(n, t=hhmm(n["t"])) for n in self.notes]}


def _row_impl(x, ok):
    good = ok(x["title"], x.get("host", ""))     # browse.card_title_ok: a video's title by the video rules
    r = dict(x, t=hhmm(x["t"]), title=x["title"] if good else x["host"])
    vid, yid = r.pop("tiktok_id", None), r.pop("youtube_id", None)
    if vid and good:                           # a caption that fails the filter: no player either
        r["embed"] = {"src": TIKTOK_EMBED.format(vid), "label": "TikTok (official embed)"}
    elif yid and good:
        import youtube_api
        r["embed"] = {"src": youtube_api.viewer_embed(yid), "label": "YouTube (official embed)"}
    return r


class DopamineBursts:
    """Phasic dopamine-like bursts when something new plays (see the module docstring)."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.expect = EXPECT0
        self.n, self.last_t, self.last_any = 0, None, None
        self.topics = {}                     # topic -> last time seen
        self.trace = []                      # [{t, size, ...}] newest last

    def on_new(self, kind, topic, interest=0.0):
        """A new clip / page started. kind: screens kind; topic: its topic (str or None); interest: tastes'
        prediction (-1..1). Returns the burst (size >= 0) or None for nothing new."""
        if kind is None or kind in ("search", "finance"):   # S2: a trading page is never a reward
            return None
        t = self.clock()
        if self.last_any is not None:                       # the expectation relaxes while nothing new plays
            self.expect += (EXPECT0 - self.expect) * (1 - math.exp(-max(0.0, t - self.last_any) / RELAX_S))
        self.last_any = t
        novelty = 0.3 if topic and t - self.topics.get(topic, -1e18) < NOVEL_S else 1.0
        if topic:
            self.topics[topic] = t
            if len(self.topics) > 500:
                self.topics.pop(next(iter(self.topics)))
        try:
            v = float(interest)
        except (TypeError, ValueError):
            v = 0.0
        v = (max(-1.0, min(1.0, v)) + 1) / 2 if math.isfinite(v) else 0.5
        rpe = novelty + v - self.expect
        self.expect += ALPHA * (novelty + v - self.expect)
        short = kind in ("tiktok", "shorts")
        if short:
            self.n = self.n + 1 if self.last_t is not None and t - self.last_t < SESSION_GAP_S else 1
            self.last_t = t
        hab = 1.0 / (1.0 + HABITUATION * (self.n - 1)) if short else 1.0
        size = round(max(0.0, rpe) * hab * SCALE.get(kind, PAGE_SCALE), 4)
        b = {"t": t, "size": size, "rpe": round(rpe, 3), "novelty": novelty, "interest": round(v, 3),
             "expect": round(self.expect, 3), "n": self.n if short else 0, "habituation": round(hab, 3), "kind": kind,
             "label": ("new short" if short else "new video" if kind == "youtube" else "new page")
                      + " — novelty + predicted interest"}
        self.trace = (self.trace + [b])[-120:]
        return b
