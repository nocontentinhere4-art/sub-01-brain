"""#89 live (2026-10-04 04:02-04:53 UTC): Chromium was restarted 12 times "over 1200 MB", several 7-21 s apart: a restart
re-opened the same heavy page (highsnobiety, knowyourmeme, boredpanda, ...) and blew the limit again, and the brain's
ticks ran late meanwhile. This module keeps what each process needs to know about heavy pages:

- HeavyPages: the pages and hosts that pushed Chromium over its memory cap. Such a page is never opened again (its URL
  key), and a host that did it HEAVY_STRIKES times within HEAVY_WINDOW_S is left alone for HEAVY_COOLDOWN_S. It
  survives a restart: the watchdog (browse_service.LocalBrowser) records the pages on screen when it kills the child
  and the live server hands them to the new process with /init, merged with what the old process saved.
- AD_HOST: ad, tracking and outstream-video networks; nothing is loaded from them (they are most of a heavy page's
  memory: auctions, video players, iframes within iframes).
- same_site: whether two hosts belong to the same site (cross-site iframes are not loaded either).
"""
import re
import time

HEAVY_STRIKES = 2                         # memory restarts caused by one host ...
HEAVY_WINDOW_S = 3600                     # ... within an hour ...
HEAVY_COOLDOWN_S = 1800                   # ... and it is left alone for 30 minutes
HEAVY_URLS_MAX = 200

AD_HOST = re.compile(
    r"(^|\.)(doubleclick\.net|googlesyndication\.com|googleadservices\.com|googletagservices\.com|adservice\.google\.\w+|"
    r"adnxs\.com|amazon-adsystem\.com|taboola\.com|outbrain\.com|criteo\.(com|net)|pubmatic\.com|rubiconproject\.com|"
    r"openx\.net|casalemedia\.com|indexww\.com|moatads\.com|scorecardresearch\.com|adsrvr\.org|teads\.tv|"
    r"sharethrough\.com|33across\.com|media\.net|adform\.net|smartadserver\.com|yieldmo\.com|lijit\.com|sovrn\.com|"
    r"connatix\.com|primis\.tech|aniview\.com|vidazoo\.com|anyclip\.com|ex\.co|jwpltx\.com|springserve\.com|"
    r"spotxchange\.com|spotx\.tv|tremorhub\.com|undertone\.com|gumgum\.com|triplelift\.com|3lift\.com|"
    r"bidswitch\.net|adsafeprotected\.com|doubleverify\.com|quantserve\.com|krxd\.net|bluekai\.com|exelator\.com|"
    r"demdex\.net|adroll\.com|zemanta\.com|revcontent\.com|mgid\.com|nativo\.com|kargo\.com|seedtag\.com|"
    r"minutemedia-prebid\.com|prebid\.org|adlightning\.com|confiant-integrations\.net|id5-sync\.com|"
    r"crwdcntrl\.net|everesttech\.net|rlcdn\.com|agkn\.com|tapad\.com|adition\.com|richaudience\.com)$", re.I)

# second-level public suffixes common on the sites he reads (enough for "same site"; not the full public-suffix list)
_SL = {"co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "co.jp", "ne.jp", "or.jp", "ac.jp", "go.jp",
       "co.nz", "com.br", "co.kr", "com.cn", "com.tw", "co.in", "com.sg", "com.hk", "co.za", "com.mx"}


def site_of(host):
    """The registrable part of a host ("www.bbc.co.uk" -> "bbc.co.uk", "i.guim.co.uk" -> "guim.co.uk")."""
    parts = (host or "").lower().rstrip(".").split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in _SL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def same_site(a, b):
    return bool(a) and bool(b) and site_of(a) == site_of(b)


# a video site's own domains count as one site: the official players' pages load their own frames from them
FAMILIES = ({"youtube.com", "youtube-nocookie.com", "youtu.be", "ytimg.com", "googlevideo.com", "google.com",
             "gstatic.com"},
            {"tiktok.com", "tiktokcdn.com", "tiktokcdn-us.com", "tiktokv.com", "ttwstatic.com", "byteoversea.com",
             "ibytedtos.com", "ibyteimg.com"})


def frame_allowed(top, host):
    """An iframe `host` inside a page from `top`: the same site, or the same video site's own domains (the YouTube
    and TikTok players' own frames). Everything else (ads, other sites' players, social embeds) is not loaded."""
    if same_site(top, host):
        return True
    a, b = site_of(top), site_of(host)
    return any(a in f and b in f for f in FAMILIES)


def ad_host(host):
    return bool(AD_HOST.search((host or "").rstrip(".")))


class HeavyPages:
    """Pages and hosts that pushed Chromium over its memory cap (see the module docstring)."""

    def __init__(self, state=None, clock=time.time):
        self.clock = clock
        s = state if isinstance(state, dict) else {}
        self.urls = [u for u in (s.get("urls") or []) if isinstance(u, str)][-HEAVY_URLS_MAX:]
        self.strikes = {h: [float(t) for t in ts if isinstance(t, (int, float))]
                        for h, ts in (s.get("strikes") or {}).items() if isinstance(h, str) and isinstance(ts, list)}
        self._trim()

    def _trim(self):
        now = self.clock()
        self.strikes = {h: [t for t in ts if now - t < HEAVY_WINDOW_S + HEAVY_COOLDOWN_S] for h, ts in self.strikes.items()}
        self.strikes = {h: ts[-10:] for h, ts in self.strikes.items() if ts}

    def strike(self, pages):
        """The pages that were on screen when Chromium went over its cap: [(url, host)]."""
        from novelty import url_key
        now = self.clock()
        for url, host in pages:
            if url and url.startswith("http"):
                k = url_key(url)
                if k not in self.urls:
                    self.urls = (self.urls + [k])[-HEAVY_URLS_MAX:]
            h = (host or "").lower().removeprefix("www.")
            if h:
                self.strikes[h] = self.strikes.get(h, []) + [now]
        self._trim()

    def heavy_url(self, url):
        from novelty import url_key
        return bool(url) and url_key(url) in self.urls

    def cooling(self, host):
        """True while a host that caused HEAVY_STRIKES memory restarts within HEAVY_WINDOW_S is left alone."""
        h = (host or "").lower().removeprefix("www.")
        ts = sorted(self.strikes.get(h, []))
        now = self.clock()
        for i in range(len(ts) - HEAVY_STRIKES + 1):
            last = ts[i + HEAVY_STRIKES - 1]
            if last - ts[i] < HEAVY_WINDOW_S and now - last < HEAVY_COOLDOWN_S:
                return True
        return False

    def merge(self, other):
        o = other if isinstance(other, HeavyPages) else HeavyPages(other, self.clock)
        self.urls = list(dict.fromkeys(self.urls + o.urls))[-HEAVY_URLS_MAX:]
        for h, ts in o.strikes.items():
            self.strikes[h] = sorted(set(self.strikes.get(h, []) + ts))
        self._trim()
        return self

    def to_dict(self):
        self._trim()
        return {"urls": list(self.urls), "strikes": {h: list(ts) for h, ts in self.strikes.items()}}

    def public(self):
        return {"pages": len(self.urls), "cooling": sorted(h for h in self.strikes if self.cooling(h))}
