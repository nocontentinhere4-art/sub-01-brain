"""He listens to music on Spotify (#68): his brain model picks tracks; pages show Spotify's official embed player.

Legal frame: the server never streams, downloads or relays audio. The page shows what he is listening to with Spotify's
own embed player (open.spotify.com/embed/track/<id>); each visitor presses play on their own device (a 30 s preview,
or the whole track when logged in to Spotify in that browser). Nothing here fetches an audio URL: the only requests are
Spotify's Web API (search + track metadata, with keys) and its oEmbed endpoint (no key), both JSON.

Where the candidates come from:
- with SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET (a free developer app; client-credentials flow, read from the
  environment only, never logged or returned): the Web API's search. `audio-features` and `recommendations` are
  restricted for new apps since Nov 2024 and not used;
- without keys (or when the API fails): music_curated.json, public tracks from public playlists per genre
  (analysis/build_music_list.py); each picked ID is checked once with Spotify's oEmbed endpoint (no key) and cached.
Queries come from the time of day (morning chill, evening hip-hop, late-night lofi), his tastes (tastes.py), words
taught in the last days, what he has been reading about (mind.next_interest) and viewer wishes in chat ("play …",
"metti …", through chat.blocked).

His brain chooses: 3-5 candidates become brain_vote options whose stimulus comes from the genre tags, title and artist
through chat.py's word-to-network lexicon (no audio analysis: the model never hears the music). The stay response while
the track plays (tastes.PageWatch) feeds the tastes, so a music taste forms over days. It is a rule on simulated
activity, not enjoyment: the pages say "his brain model leaned toward ...", never "he loves this song".
"""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path

from chat import blocked, networks_for
from sleep import local
from state_io import append_jsonl, load_json, read_jsonl, save_json

try:                                    # one rule for song and video titles (browse.media_title_ok, review G24 F5/F12)
    from browse import media_title_ok
except Exception as e:                  # never on a normal deployment; without the guard no track is shown (fail closed)
    print(f"music: browse.media_title_ok unavailable ({type(e).__name__}); API tracks are not shown", flush=True)

    def media_title_ok(text):
        return False

HERE = Path(__file__).parent
CURATED = HERE / "music_curated.json"
ID = re.compile(r"[A-Za-z0-9]{22}")
EMBED = "https://open.spotify.com/embed/track/{}?utm_source=generator&theme=0"
TRACK = "https://open.spotify.com/track/{}"
OEMBED = "https://open.spotify.com/oembed?url={}"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
EMBED_HEIGHT = 80             # Spotify's compact player
CANDIDATES = (3, 5)           # options per vote
DEFAULT_MS = 210_000          # a track whose length is unknown: 3.5 min
RECENT_N = 30                 # not offered again while among the last RECENT_N tracks
NOVEL_DAYS = 7                # the vote's novelty bonus: not played in this many days
WISH_TTL = 2 * 3600           # a viewer's "play ..." is remembered this long (simulated s)
WISHES_MAX = 5
OEMBED_TTL = 7 * 86400        # a checked ID is trusted this long
TIMEOUT = 8.0
CARD = "his brain model picked this track; press play to listen on your own device"
NOTE = ("Spotify's official player: a 30 s preview, or the whole track if you are logged in to Spotify in this "
        "browser. The server never plays, downloads or relays audio. The pick is a brain-model vote among 3-5 "
        "candidates on simulated activity, not liking: the model never hears the music.")
SEARCH = {    # genre -> what the Web API is asked (keys only)
    "city_pop": "japanese city pop", "jpop": "j-pop", "lofi": "lofi beats", "hiphop": "japanese hip hop",
    "anime": "anime soundtrack", "indie": "indie", "electronic": "electronic", "jazz": "jazz", "piano": "piano ambient",
}
DAYPARTS = [  # (from hour, name, {genre: weight}): morning chill, evening hip-hop, late-night lofi
    (0, "late night", {"lofi": 3, "piano": 2, "city_pop": 1.5, "jazz": 1}),
    (5, "morning", {"jazz": 2.5, "piano": 2, "lofi": 1.5, "city_pop": 1.5, "indie": 1}),
    (11, "afternoon", {"jpop": 2, "indie": 2, "anime": 2, "electronic": 1.5, "city_pop": 1}),
    (18, "evening", {"hiphop": 3, "city_pop": 2.5, "electronic": 1.5, "jpop": 1}),
    (22, "late night", {"lofi": 3, "city_pop": 2, "piano": 1.5, "jazz": 1}),
]
WISH = re.compile(r"^\s*(?:please\s+)?(?:play|put on|metti|mettimi|ascolta|suona|listen to)\s+(?:some\s+|un po' di\s+)?"
                  r"(.{2,60}?)\s*(?:on spotify|su spotify)?[.!]*\s*$", re.I)


class SpotifyError(Exception):
    """A Web API failure. Its message never carries a key, a token or a header."""


def valid_id(tid):
    return isinstance(tid, str) and bool(ID.fullmatch(tid))


def embed_url(tid):
    """Spotify's official embed player for one track (the only way the page plays anything)."""
    if not valid_id(tid):
        raise ValueError("not a Spotify track id")
    return EMBED.format(tid)


def track_url(tid):
    if not valid_id(tid):
        raise ValueError("not a Spotify track id")
    return TRACK.format(tid)


def daypart(t):
    """-> (name, {genre: weight}) for the Tokyo hour of sim time t."""
    h = local(t).hour
    name, w = DAYPARTS[0][1:]
    for start, n, ws in DAYPARTS:
        if h >= start:
            name, w = n, ws
    return name, w


def wish(text):
    """A viewer's "play …" / "metti …" -> the query (filtered), else None."""
    m = WISH.match(text or "")
    if not m:
        return None
    q = " ".join(m.group(1).split())
    if not q or blocked(q) or re.search(r"[<>{}\\]|https?:|www\.", q, re.I):
        return None
    if q.lower() in ("music", "musica", "a song", "some music", "something", "qualcosa", "una canzone"):
        return "music"
    return q[:60]


def http_json(method, url, headers=None, data=None, timeout=TIMEOUT):
    """(status, json) for a JSON endpoint. Errors carry the status only, never the request's headers."""
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers=dict(headers or {}))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ctype = r.headers.get("Content-Type", "")
            if "json" not in ctype:                      # an audio or HTML body is never read
                return r.status, None
            return r.status, json.loads(r.read(2_000_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, OSError, ValueError):
        return 0, None


class SpotifyAPI:
    """Client-credentials access to Spotify's Web API: search and track metadata only."""

    def __init__(self, client_id, client_secret, fetch=http_json, clock=time.time, market="JP"):
        self._auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        self.fetch, self.clock, self.market = fetch, clock, market
        self._token, self._expires = None, 0.0
        self.calls, self.errors = 0, 0

    def __repr__(self):                                  # never shows the key or the token
        return f"SpotifyAPI(market={self.market!r}, calls={self.calls})"

    @classmethod
    def from_env(cls, env=None, **kw):
        env = os.environ if env is None else env
        cid, sec = env.get("SPOTIFY_CLIENT_ID", "").strip(), env.get("SPOTIFY_CLIENT_SECRET", "").strip()
        return cls(cid, sec, **kw) if cid and sec else None

    def token(self):
        if self._token and self.clock() < self._expires - 60:
            return self._token
        st, d = self.fetch("POST", TOKEN_URL, {"Authorization": f"Basic {self._auth}",
                                               "Content-Type": "application/x-www-form-urlencoded"},
                           {"grant_type": "client_credentials"})
        if st != 200 or not isinstance(d, dict) or not d.get("access_token"):
            self.errors += 1
            raise SpotifyError(f"token request failed (status {st})")
        self._token, self._expires = d["access_token"], self.clock() + float(d.get("expires_in", 3600))
        return self._token

    def _get(self, path, params):
        url = f"{API}{path}?{urllib.parse.urlencode(params)}"
        st, d = self.fetch("GET", url, {"Authorization": f"Bearer {self.token()}"}, None)
        self.calls += 1
        if st == 401:                                    # expired early: one fresh token
            self._token = None
            st, d = self.fetch("GET", url, {"Authorization": f"Bearer {self.token()}"}, None)
        if st != 200 or not isinstance(d, dict):
            self.errors += 1
            raise SpotifyError(f"{path} failed (status {st})")
        return d

    def search(self, query, limit=10):
        d = self._get("/search", {"q": query, "type": "track", "limit": limit, "market": self.market})
        return [t for t in (track_from_api(x) for x in (d.get("tracks") or {}).get("items") or []) if t]

    def track(self, tid):
        if not valid_id(tid):
            return None
        return track_from_api(self._get(f"/tracks/{tid}", {"market": self.market}))


def track_from_api(x):
    """A Web API track object -> our track dict (metadata only; preview_url is never read), or None."""
    if not isinstance(x, dict) or not valid_id(x.get("id")) or x.get("is_playable") is False:
        return None
    title = " ".join(str(x.get("name") or "").split())[:120]
    artist = ", ".join(" ".join(str(a.get("name") or "").split()) for a in (x.get("artists") or [])[:3]
                       if isinstance(a, dict))[:120]
    album = x.get("album") if isinstance(x.get("album"), dict) else {}
    imgs = [i for i in album.get("images") or [] if isinstance(i, dict) and str(i.get("url", "")).startswith("https://")]
    art = min(imgs, key=lambda i: abs((i.get("width") or 300) - 300))["url"] if imgs else None
    if not title or not media_title_ok(title) or not media_title_ok(artist):   # explicit lyrics allowed (owner)
        return None
    return {"id": x["id"], "title": title, "artist": artist, "album": " ".join(str(album.get("name") or "").split())[:120],
            "art": art, "ms": int(x.get("duration_ms") or 0)}


def album_only_match(track, query):
    """A search hit that matches a genre query only through its album's name (Queen's "Don't Stop Me Now" is on the
    album "Jazz": not a jazz track). Such a hit is dropped instead of being labelled with that genre."""
    words = [w for w in str(query or "").lower().split() if len(w) > 2]
    album = str(track.get("album") or "").lower()
    text = f"{track.get('title', '')} {track.get('artist', '')}".lower()
    return bool(words) and any(w in album for w in words) and not any(w in text for w in words)


def load_curated(path=CURATED):
    d = json.loads(Path(path).read_text())
    out = {}
    for g, v in d.get("genres", {}).items():
        tracks = [dict(t, genre=g) for t in v.get("tracks", []) if valid_id(t.get("id"))]
        out[g] = {"label": v.get("label", g), "tags": v.get("tags", ""), "tracks": tracks,
                  "playlists": v.get("playlists", [])}
    return out


class Music:
    def __init__(self, data_dir=None, api=None, fetch=http_json, rng=None, clock=time.time, curated=None):
        import random
        self.dir = Path(data_dir) if data_dir else None
        self.api, self.fetch, self.clock = api, fetch, clock
        self.rng = rng or random.Random()
        self.genres = curated if curated is not None else load_curated()
        self.now = None                                  # the track playing (public record + private ends)
        self.wishes = deque(maxlen=WISHES_MAX)           # (sim t, query)
        self.api_down = None                             # why the Web API was not used last time
        st = load_json(self.state_path, {}) if self.dir else {}
        self.checked = st.get("checked", {}) if isinstance(st.get("checked"), dict) else {}

    # --- files ---
    @property
    def log_path(self):
        return self.dir / "music.jsonl" if self.dir else None

    @property
    def state_path(self):
        return self.dir / "music.json" if self.dir else None

    def history(self, last=200):
        return read_jsonl(self.log_path, last=last) if self.dir else []

    def _save(self):
        if self.dir:
            save_json(self.state_path, {"checked": self.checked})

    @property
    def source(self):
        return "Spotify Web API search" if self.api else "a curated list of public Spotify playlists"

    # --- inputs ---
    def hear(self, text, t):
        q = wish(text)
        if q:
            self.wishes.append((t, q))
        return q

    def live_wishes(self, t):
        return [q for t0, q in self.wishes if 0 <= t - t0 <= WISH_TTL]

    # --- queries ---
    def genre_weights(self, t, taste_words=(), taught=(), interests=()):
        """{genre: weight}: the time of day, plus genres whose tags meet his tastes, taught words and interests."""
        _, w = daypart(t)
        w = {g: float(w.get(g, 0.4)) for g in self.genres}
        for src, bonus in ((taste_words, 1.5), (taught, 1.0), (interests, 0.8)):
            words = {x.lower() for s in src for x in re.findall(r"[\w-]+", str(s))}
            for g, v in self.genres.items():
                tags = set(v["tags"].lower().split()) | set(v["label"].lower().split()) | {g}
                tags.discard("music")
                if words & tags:
                    w[g] += bonus
        return w

    def queries(self, t, taste_words=(), taught=(), interests=()):
        """-> [{genre, query, why}] in the order they are tried (a wish first, then genres by weight, sampled)."""
        out = [{"genre": None, "query": q, "why": f"a viewer asked for “{q}”"} for q in self.live_wishes(t)[-2:]]
        part, base = daypart(t)
        w = self.genre_weights(t, taste_words, taught, interests)
        pool = dict(w)
        while pool and len(out) < 5:
            tot = sum(pool.values())
            r, acc = self.rng.random() * tot, 0.0
            for g, x in pool.items():
                acc += x
                if acc >= r:
                    break
            pool.pop(g)
            why = f"{part} music" if base.get(g) else "from his tastes and what he has been reading"
            if base.get(g) and w[g] > base[g] + 0.1:
                why += "; it meets his tastes"
            out.append({"genre": g, "query": SEARCH.get(g, g), "why": why})
        return out

    # --- candidates ---
    def recent_ids(self, n=RECENT_N):
        ids = [r.get("id") for r in self.history(n)]
        return set(ids + ([self.now["id"]] if self.now else []))

    def novel(self, tid, now=None):
        now = self.clock() if now is None else now
        return not any(r.get("id") == tid and now - r.get("wall", 0) < NOVEL_DAYS * 86400 for r in self.history(500))

    def curated_match(self, query, avoid):
        q = query.lower()
        hits = []
        for g, v in self.genres.items():
            meta = f"{g} {v['label']} {v['tags']}".lower()
            for tr in v["tracks"]:
                text = f"{tr['title']} {tr['artist']}".lower()
                if tr["id"] not in avoid and (q in text or q in meta or (q == "music")):
                    hits.append(tr)
        self.rng.shuffle(hits)
        return hits

    def candidates(self, t, taste_words=(), taught=(), interests=(), k=None):
        """3-5 candidate tracks [{id, title, artist, genre, why, ...}]. Network I/O with keys or for oEmbed checks:
        call it off the event loop."""
        k = k or self.rng.randint(*CANDIDATES)
        avoid, out = self.recent_ids(), []
        qs = self.queries(t, taste_words, taught, interests)
        if self.api:
            try:
                for q in qs[:3]:
                    got = [x for x in self.api.search(q["query"]) if x["id"] not in avoid
                           and (q["genre"] is None or not album_only_match(x, q["query"]))]
                    self.rng.shuffle(got)
                    for x in got[:2 if q["genre"] is None else 1]:
                        out.append(dict(x, genre=q["genre"] or self.guess_genre(x), why=q["why"], source="api"))
                        avoid.add(x["id"])
                self.api_down = None
            except SpotifyError as e:
                self.api_down = str(e)
                print("music: Spotify Web API unavailable, using the curated list:", e, flush=True)
        for q in qs:
            if len(out) >= k:
                break
            pool = (self.curated_match(q["query"], avoid) if q["genre"] is None
                    else [x for x in self.genres[q["genre"]]["tracks"] if x["id"] not in avoid])
            if not pool:
                continue
            x = self.rng.choice(pool)
            info = self.check(x["id"])
            if info is False:
                continue
            avoid.add(x["id"])
            out.append(dict(x, art=(info or {}).get("art"), why=q["why"], source="curated"))
        return out[:k]

    def guess_genre(self, track):
        text = f"{track.get('title', '')} {track.get('artist', '')}".lower()
        for g, v in self.genres.items():
            if any(tr["id"] == track["id"] for tr in v["tracks"]) or v["label"].lower() in text:
                return g
        return None

    def check(self, tid):
        """oEmbed check of a curated ID (no key): {title, art} if Spotify knows it, False if it does not,
        None when Spotify could not be asked (then it is offered anyway; the embed says if it is gone)."""
        c = self.checked.get(tid)
        if c and self.clock() - c.get("t", 0) < OEMBED_TTL:
            return c if c.get("ok") else False
        st, d = self.fetch("GET", OEMBED.format(urllib.parse.quote(TRACK.format(tid), safe="")), {}, None)
        if st == 200 and isinstance(d, dict) and d.get("type") == "rich":
            art = d.get("thumbnail_url") if str(d.get("thumbnail_url", "")).startswith("https://") else None
            c = {"ok": True, "t": self.clock(), "title": str(d.get("title", ""))[:120], "art": art}
        elif st in (400, 404):
            c = {"ok": False, "t": self.clock()}
        else:
            return None
        self.checked[tid] = c
        if len(self.checked) > 2000:
            for old in sorted(self.checked, key=lambda i: self.checked[i].get("t", 0))[:500]:
                self.checked.pop(old)
        self._save()
        return c if c["ok"] else False

    # --- the vote ---
    def label(self, track):
        return f"{track['title']} — {track['artist']}" if track.get("artist") else track["title"]

    def networks(self, track):
        """{group: 0..1}: genre tags + title + artist through chat.py's lexicon (what the words lean on)."""
        g = self.genres.get(track.get("genre") or "", {})
        text = " ".join([g.get("tags", "music"), g.get("label", ""), track.get("title", ""), track.get("artist", "")])
        nets = networks_for(text) or {"reward": 1.0}
        top = max(nets.values())
        return {k: round(v / top, 3) for k, v in sorted(nets.items(), key=lambda kv: -kv[1])[:5]}

    def options(self, tracks):
        return [{"action": "listen", "label": self.label(x), "target": x["id"], "networks": self.networks(x)}
                for x in tracks]

    @staticmethod
    def topics(option, track):
        from tastes import Tastes
        return Tastes.topics(option, track.get("artist", "")) + ([f"kw:{track['genre']}"] if track.get("genre") else [])

    # --- playing ---
    def play(self, track, decision, t, mode):
        """He starts listening (the page shows the embed); returns the public record."""
        dec = decision or {}
        reason = str(dec.get("reason", "")).replace("chose it:", "his brain model leaned toward it:")
        rec = {"id": track["id"], "title": track["title"], "artist": track.get("artist", ""),
               "album": track.get("album", ""), "art": track.get("art"), "genre": track.get("genre"),
               "genre_label": self.genres.get(track.get("genre") or "", {}).get("label"),
               "url": track_url(track["id"]), "embed": embed_url(track["id"]), "embed_height": EMBED_HEIGHT,
               "mode": mode, "t": t, "wall": self.clock(), "ms": track.get("ms") or DEFAULT_MS,
               "why": track.get("why", ""), "reason": reason, "source": track.get("source", "curated"),
               "options": [{"label": o["label"], "p": o.get("p"), "value": o.get("value"), "chosen": o.get("chosen"),
                            "networks": o.get("networks")} for o in dec.get("options", [])]}
        self.now = rec
        self.wishes = deque([(t0, q) for t0, q in self.wishes if q.lower() not in
                             f"{rec['title']} {rec['artist']} {rec['genre_label'] or ''}".lower()], maxlen=WISHES_MAX)
        return self.public(rec)

    def ends(self):
        return self.now["t"] + self.now["ms"] / 1000.0 if self.now else None

    def stop(self, t, why, response=None):
        """The track ended or he took the headphones off: one row in music.jsonl."""
        rec, self.now = self.now, None
        if not rec:
            return None
        row = {k: rec[k] for k in ("id", "title", "artist", "genre", "genre_label", "mode", "t", "wall", "why",
                                   "reason", "source", "art")}
        row.update(end=t, ended=why, listened_s=round(max(0.0, t - rec["t"])))
        if response is not None:
            row["response"] = round(float(response), 3)
        if self.dir:
            try:
                append_jsonl(self.log_path, row)
            except OSError as e:
                print("music: could not log the track:", repr(e)[:120], flush=True)
        return row

    @staticmethod
    def public(rec):
        if not rec:
            return None
        return {k: rec.get(k) for k in ("id", "title", "artist", "album", "art", "genre", "genre_label", "url", "embed",
                                        "embed_height", "mode", "why", "reason", "options", "source")}

    def tick_view(self):
        """What rides on every tick (life.music): small, for the room's headphones."""
        return {"title": self.now["title"], "artist": self.now["artist"], "mode": self.now["mode"]} if self.now else None

    def day(self, date):
        """Tracks of Tokyo day `date` (YYYY-MM-DD), oldest first (the diary and the mind's day notes)."""
        return [r for r in self.history(300) if local(r.get("t", 0)).date().isoformat() == date]

    def view(self, t):
        """GET /api/music."""
        today = local(t).date().isoformat()
        rows = [{k: r.get(k) for k in ("id", "title", "artist", "genre_label", "mode", "why", "reason", "ended",
                                       "listened_s", "response", "art")}
                | {"time": local(r["t"]).strftime("%H:%M"), "url": track_url(r["id"])}
                for r in self.day(today) if valid_id(r.get("id"))][::-1]
        return {"now": self.public(self.now), "today": rows, "source": self.source,
                "api": None if not self.api else ("down: " + self.api_down if self.api_down else "ok"),
                "wishes": self.live_wishes(t), "daypart": daypart(t)[0], "card": CARD, "note": NOTE}
