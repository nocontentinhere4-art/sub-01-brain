"""YouTube through its official Data API v3 and its official embed player (#89 live follow-up).

Why: youtube.com/robots.txt disallows /results for every crawler, so the browser's YouTube and Shorts sources (the
results page) were refused by our own robots check all day, and the phone never showed a short. The compliant path is
YouTube's own API for search and its embed player (youtube-nocookie.com/embed/<id>, allowed by its robots.txt) to
play a video.

- Only with YOUTUBE_API_KEY set (Railway variable; never in git or logs). The key goes in the X-Goog-Api-Key header,
  never in a URL, so no log line that prints a URL can carry it. Without it, nothing is asked and the screens panel
  says so.
- Quota: search.list costs SEARCH_UNITS (100) of the free 10,000 units a day (Pacific day, when Google resets it);
  we stop at DAILY_UNITS (default 9,000, YOUTUBE_DAILY_UNITS can lower it) and cache each query's results for
  CACHE_S. Free quota only: nothing is paid, no cap is raised.
- Search: type=video, safeSearch=strict, videoEmbeddable=true; Shorts: videoDuration=short and "#shorts".
Results go through the browser's guard (safe_results, video_text_ok) like every other result.
"""
import html
import json
import re
import os
import time
import urllib.parse

KEY_ENV = "YOUTUBE_API_KEY"
SEARCH = "https://www.googleapis.com/youtube/v3/search"
SEARCH_UNITS = 100
FREE_UNITS = 10_000
DAILY_UNITS = 9_000
CACHE_S = 6 * 3600
NEG_CACHE_S = 600                     # B6: a search whose playability check failed is asked again after 10 min
EMBED = "https://www.youtube-nocookie.com/embed/{id}?autoplay=1&mute=1&playsinline=1&controls=0&rel=0&loop=1&playlist={id}"
VIEWER_EMBED = "https://www.youtube-nocookie.com/embed/{id}?autoplay=0&mute=1&playsinline=1&rel=0"
NOTE_NO_KEY = "YouTube: YOUTUBE_API_KEY not set (YouTube's search pages are closed to robots), so no YouTube search"
OEMBED = "https://www.youtube.com/oembed?"


# #89 teen interests: well-known channels per topic, whose latest uploads are read through the official API (YouTube's
# Terms of Service forbid automated access to its pages, whatever robots.txt allows): channels.list forHandle ->
# the uploads playlist (1 unit, kept), playlistItems.list -> the latest uploads (1 unit), videos.list -> durations,
# to tell Shorts-length videos (1 unit). Three units instead of search.list's 100. Each handle existed on 2026-10-04.
CHANNELS = {
    "cars": ["TopGear", "carwow", "DougDeMuro"],      # #89 live: Formula1's videos are blocked from embedding
    "games": ["IGN", "PlayStation", "Markiplier"],
    "football": ["PremierLeague", "433", "FIFA", "UEFA"],
    "music": ["Genius", "COLORSxSTUDIOS", "NPRMusic", "The_FirstTake"],
    "anime": ["Crunchyroll", "TOHOanimation", "AniplexUSA"],
    "tech": ["mkbhd", "LinusTechTips", "UnboxTherapy", "Mrwhosetheboss"],
    "sneakers": ["Complex", "highsnobiety", "hypebeast"],
    "creators": ["MrBeast", "DudePerfect", "MarkRober"],
    "memes": ["DailyDoseOfInternet", "MrBeast", "DudePerfect"],
    "movies": ["Netflix", "A24"],
    "tokyo": ["abroadinjapan", "ParisInTokyo"],
    "science": ["veritasium", "kurzgesagt"],
}
CHANNEL_CACHE_S = 3 * 3600
BAD_CHANNEL = 2                      # embeds refused in a day before a channel is set aside for the day
LIST_UNITS = 1                       # channels.list, playlistItems.list, videos.list
SHORT_MAX_S = 180                    # a Short is at most 3 minutes (YouTube, since Oct 2024)
API = "https://www.googleapis.com/youtube/v3/"
NOTE_UPLOADS = "YouTube: latest uploads of channels he likes (official API)"
NOTE_REPLAY_KEY = ("YouTube: today's API budget or the hourly API limit is reached: no new videos found; replaying "
                   "today's already-found videos")
NOTE_PLAYER_DOWN = ("YouTube: its embed player refuses this browser right now ({why}); no videos until {until} UTC, "
                    "other things meanwhile")
PLAYER_FAILS = 2                                        # player-level refusals in a row before YouTube is paused
PLAYER_PAUSE_S = 1800
NOTE_REPLAY = ("YouTube: no API key or no quota left: no new videos found; replaying today's already-found videos")


def channels_url(handle):
    return API + "channels?" + urllib.parse.urlencode({"part": "contentDetails", "forHandle": f"@{handle}"})


def playlist_url(playlist_id, n=25):
    return API + "playlistItems?" + urllib.parse.urlencode({"part": "snippet,contentDetails", "maxResults": str(n),
                                                             "playlistId": playlist_id})


def videos_url(ids):
    return API + "videos?" + urllib.parse.urlencode({"part": "contentDetails,snippet,status", "id": ",".join(ids)})


def parse_uploads_id(text):
    """channels.list -> the channel's uploads playlist id, or None."""
    try:
        d = json.loads(text or "")
        pid = d["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    return pid if isinstance(pid, str) and pid.replace("-", "").replace("_", "").isalnum() else None


def parse_playlist(text):
    """playlistItems.list -> [{id, title, channel}] (newest first)."""
    try:
        d = json.loads(text or "")
    except ValueError:
        return []
    out = []
    for it in (d.get("items") or []) if isinstance(d, dict) else []:
        sn = (it or {}).get("snippet") or {}
        vid = ((it or {}).get("contentDetails") or {}).get("videoId") or (sn.get("resourceId") or {}).get("videoId")
        if isinstance(vid, str) and len(vid) == 11 and vid.replace("-", "").replace("_", "").isalnum():
            out.append({"id": vid, "title": html.unescape(str(sn.get("title") or ""))[:140],
                        "channel": html.unescape(str(sn.get("channelTitle") or ""))[:60]})
    return out


def iso_seconds(d):
    """ISO 8601 duration ("PT1M5S") -> seconds, or None."""
    import re
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", str(d or ""))
    if not m or not any(m.groups()):
        return None
    dd, h, mi, se = (int(x or 0) for x in m.groups())
    return ((dd * 24 + h) * 60 + mi) * 60 + se


REGION = "JP"                         # he is in Tokyo: a video must play there


def playable(item, region=REGION):
    """A videos.list item that the embed player will really play for us: embeddable, public, not age-restricted,
    not region-blocked (#89 live: an F1 video's embed showed "Video unavailable")."""
    st = (item or {}).get("status") or {}
    cd = (item or {}).get("contentDetails") or {}
    if st.get("embeddable") is not True or st.get("privacyStatus") != "public":
        return False
    if (cd.get("contentRating") or {}).get("ytRating") == "ytAgeRestricted":
        return False
    rr = cd.get("regionRestriction") or {}
    if region in (rr.get("blocked") or []) or ("allowed" in rr and region not in (rr.get("allowed") or [])):
        return False
    return True


YT_PAGE = re.compile(r"^https?://(?:(?:www|m|music)\.)?(?:youtube\.com|youtu\.be)(?:/|$)", re.I)
YT_VIDEO = re.compile(r"^https?://(?:(?:www|m)\.)?(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|live/|embed/)|"
                      r"youtu\.be/)([\w-]{11})", re.I)


def page_video(url):
    """#89 live: a youtube.com / youtu.be page URL -> (video id or None, is a YouTube page). The browser never opens
    YouTube's own pages (its Terms forbid automated access); a video link is played in the official embed instead."""
    u = str(url or "")
    if not YT_PAGE.match(u):
        return None, False
    m = YT_VIDEO.match(u)
    return (m.group(1) if m else None), True


def parse_videos(text):
    """videos.list -> {id: {sec, title, channel}} for the videos the embed will play (playable())."""
    try:
        d = json.loads(text or "")
    except ValueError:
        return {}
    out = {}
    for it in (d.get("items") or []) if isinstance(d, dict) else []:
        sec = iso_seconds(((it or {}).get("contentDetails") or {}).get("duration"))
        if playable(it) and isinstance(it.get("id"), str) and sec:
            sn = it.get("snippet") or {}
            out[it["id"]] = {"sec": sec, "title": html.unescape(str(sn.get("title") or ""))[:140],
                             "channel": html.unescape(str(sn.get("channelTitle") or ""))[:60]}
    return out


def parse_durations(text):
    """videos.list -> {id: seconds} for the videos the embed will play (playable())."""
    try:
        d = json.loads(text or "")
    except ValueError:
        return {}
    out = {}
    for it in (d.get("items") or []) if isinstance(d, dict) else []:
        if not playable(it):
            continue
        sec = iso_seconds(((it or {}).get("contentDetails") or {}).get("duration"))
        if isinstance(it.get("id"), str) and sec:
            out[it["id"]] = sec
    return out


def channels_for(topic):
    """The topic's channels; a topic without any (or none given) gets the creators'."""
    return CHANNELS.get(topic or "") or CHANNELS["creators"]


def key():
    return (os.environ.get(KEY_ENV) or "").strip() or None


def headers():
    k = key()
    return {"X-Goog-Api-Key": k} if k else {}


def daily_units():
    try:
        return max(0, min(DAILY_UNITS, int(os.environ.get("YOUTUBE_DAILY_UNITS") or DAILY_UNITS)))
    except ValueError:
        return DAILY_UNITS


def search_url(q, short=True, n=10):
    """The search.list URL (no key in it: the key travels in the header)."""
    p = {"part": "snippet", "type": "video", "maxResults": str(n), "safeSearch": "strict", "videoEmbeddable": "true",
         "relevanceLanguage": "en", "q": f"{q} #shorts" if short else q}
    if short:
        p["videoDuration"] = "short"
    return SEARCH + "?" + urllib.parse.urlencode(p)


def video_url(vid, short=True):
    return f"https://www.youtube.com/shorts/{vid}" if short else f"https://www.youtube.com/watch?v={vid}"


def embed_url(vid):
    return EMBED.format(id=vid)


def viewer_embed(vid):
    return VIEWER_EMBED.format(id=vid)


def oembed_url(video):
    return OEMBED + urllib.parse.urlencode({"url": video, "format": "json"})


def parse_search(text, short=True):
    """search.list JSON -> results [{url, title, channel, thumb, video, short, embed, id}] (unguarded)."""
    try:
        d = json.loads(text or "")
    except ValueError:
        return []
    out = []
    for it in (d.get("items") or []) if isinstance(d, dict) else []:
        vid = ((it or {}).get("id") or {}).get("videoId")
        sn = (it or {}).get("snippet") or {}
        if not isinstance(vid, str) or not vid.replace("-", "").replace("_", "").isalnum() or len(vid) != 11:
            continue
        thumbs = sn.get("thumbnails") or {}
        thumb = ((thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url") or "")
        out.append({"id": vid, "url": video_url(vid, short), "title": html.unescape(str(sn.get("title") or ""))[:140],
                    "channel": html.unescape(str(sn.get("channelTitle") or ""))[:60],
                    "thumb": thumb if thumb.startswith("https://i.ytimg.com/") else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                    "video": True, "short": short, "embed": embed_url(vid), "host": "youtube.com"})
    return out


def parse_oembed(text, video):
    """YouTube's public oEmbed JSON -> {title, channel} or None."""
    try:
        d = json.loads(text or "")
    except ValueError:
        return None
    if not isinstance(d, dict) or not d.get("title"):
        return None
    return {"title": str(d["title"])[:140], "channel": str(d.get("author_name") or "")[:60]}


def pacific_day(t):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.fromtimestamp(t, ZoneInfo("America/Los_Angeles")).date().isoformat()


class Quota:
    """Units spent on the Data API this Pacific day, and each query's cached results."""

    def __init__(self, state=None, clock=time.time):
        self.clock = clock
        s = state or {}
        self.day = s.get("day")
        self.used = int(s.get("used") or 0) if isinstance(s.get("used"), (int, float)) else 0
        self.searches = int(s.get("searches") or 0) if isinstance(s.get("searches"), (int, float)) else 0
        self.errors = [str(e)[:80] for e in (s.get("errors") or [])][-5:]
        self.cache = {k: v for k, v in (s.get("cache") or {}).items()
                      if isinstance(v, dict) and isinstance(v.get("t"), (int, float)) and isinstance(v.get("r"), list)}
        for k in [k for k, v in self.cache.items() if v.get("v") != 2]:
            del self.cache[k]                                # lists cached before playable() was applied
        self.uploads = {k: v for k, v in (s.get("uploads") or {}).items() if isinstance(v, str)}   # handle -> playlist
        self.today = [c for c in (s.get("today") or []) if isinstance(c, dict) and isinstance(c.get("url"), str)]
        self.bad = [x for x in (s.get("bad") or []) if isinstance(x, str)][-500:]      # ids the embed refused today
        self.bad_by = {k: int(v) for k, v in (s.get("bad_by") or {}).items() if isinstance(v, int)}   # channel -> n
        p = s.get("player") if isinstance(s.get("player"), dict) else {}
        self.player = {"until": float(p["until"]) if isinstance(p.get("until"), (int, float)) else 0.0,
                       "why": str(p.get("why") or "")[:60], "fails": int(p["fails"]) if isinstance(p.get("fails"), int) else 0}
        self._roll()

    def _roll(self):
        d = pacific_day(self.clock())
        if d != self.day:
            self.day, self.used, self.searches, self.errors = d, 0, 0, []
            self.today, self.bad, self.bad_by = [], [], {}
        now = self.clock()
        for k in [k for k, v in self.cache.items() if now - v["t"] > (NEG_CACHE_S if v.get("neg") else CACHE_S)]:
            del self.cache[k]

    @staticmethod
    def _k(q, short):
        return ("s:" if short else "v:") + " ".join(str(q).lower().split())

    def cached(self, q, short=True):
        self._roll()
        c = self.cache.get(self._k(q, short))
        return list(c["r"]) if c else None

    def allow(self, units=SEARCH_UNITS):
        self._roll()
        return self.used + units <= daily_units()

    def spend(self, q, short, results, units=SEARCH_UNITS):
        self._roll()
        self.used += units
        self.searches += 1
        self.cache[self._k(q, short)] = {"t": self.clock(), "r": results[:10], "v": 2}
        while len(self.cache) > 200:
            self.cache.pop(next(iter(self.cache)))

    def cache_fail(self, q, short):
        """B6: the playability check (videos.list) failed after a search: the query is not cached as "no videos" for
        CACHE_S but as a short negative entry (NEG_CACHE_S), so it is tried again soon."""
        self.cache[self._k(q, short)] = {"t": self.clock(), "r": [], "v": 2, "neg": True}

    def spend_units(self, n):
        """A cheap call (channels / playlistItems / videos .list)."""
        self._roll()
        self.used += n

    def found(self, cards):
        """Videos found today (replayed when there is no key or no quota left)."""
        self._roll()
        self.today = ([c for c in self.today if c["url"] not in {x["url"] for x in cards}] + list(cards))[-200:]

    def refused(self, url, channel=None):
        """The embed player refused this video (it showed "Video unavailable" or an error): not again today, and a
        channel whose videos keep failing is set aside for the day (BAD_CHANNEL)."""
        self._roll()
        if url not in self.bad:
            self.bad = (self.bad + [url])[-500:]
        self.today = [c for c in self.today if c["url"] != url]
        if channel:
            self.bad_by[channel] = self.bad_by.get(channel, 0) + 1

    def is_bad(self, url):
        self._roll()
        return url in self.bad

    def channel_ok(self, channel):
        self._roll()
        return self.bad_by.get(channel, 0) < BAD_CHANNEL

    def player_failed(self, why):
        """The embed player itself was refused (YouTube's bot check / sign-in screen, or it did not load), whatever the
        video: after PLAYER_FAILS in a row YouTube is paused PLAYER_PAUSE_S (no cards, no API units meanwhile)."""
        self.player["fails"] += 1
        self.player["why"] = str(why)[:60]
        if self.player["fails"] >= PLAYER_FAILS:
            self.player["until"], self.player["fails"] = self.clock() + PLAYER_PAUSE_S, 0

    def player_ok(self):
        self.player["fails"] = 0

    def player_up(self):
        return self.clock() >= self.player["until"]

    def player_note(self):
        import datetime
        until = datetime.datetime.fromtimestamp(self.player["until"], datetime.timezone.utc).strftime("%H:%M")
        return NOTE_PLAYER_DOWN.format(why=self.player["why"] or "refused", until=until)

    def error(self, why):
        self._roll()
        self.errors = (self.errors + [str(why)[:80]])[-5:]

    def to_dict(self):
        self._roll()
        return {"day": self.day, "used": self.used, "searches": self.searches, "errors": self.errors,
                "cache": dict(list(self.cache.items())[-100:]), "uploads": dict(self.uploads),
                "today": self.today[-200:], "bad": self.bad[-500:], "bad_by": dict(self.bad_by), "player": dict(self.player)}

    def public(self):
        """For /api/screens and /api/browsing: the key set or not, units used today; never the key."""
        self._roll()
        return {"key_set": bool(key()), "pacific_day": self.day, "units_used": self.used, "units_cap": daily_units(),
                "free_units": FREE_UNITS, "searches": self.searches, "errors": list(self.errors),
                "found_today": len(self.today), "refused_by_embed_today": len(self.bad),
                "channels_set_aside": sorted(k for k, v in self.bad_by.items() if v >= BAD_CHANNEL),
                "player": "ok" if self.player_up() else "paused", "player_paused_until": self.player["until"] or None,
                "last_player_refusal": self.player["why"] or None}
