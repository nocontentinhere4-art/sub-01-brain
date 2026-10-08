"""Build music_curated.json: the keyless track list music.py picks from (#68).

    python analysis/build_music_list.py            # rewrites music_curated.json next to music.py

Dev-time only, never run by the server. For each genre it reads public Spotify playlists through the official embed
page's metadata (open.spotify.com/embed/playlist/<id>: track IDs, titles, artists, durations), drops explicit,
19+ and unplayable tracks and titles the chat filter blocks, and keeps up to PER_GENRE tracks. It never touches
audio: the `audioPreview` field of that metadata is ignored. Each playlist is checked with Spotify's oEmbed first.
"""
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from chat import blocked  # noqa: E402

PER_GENRE = 14
UA = {"User-Agent": "Mozilla/5.0 (sub-01 music list builder)"}
GENRES = {   # genre -> (label, lexicon tags, public playlists)
    "city_pop": ("Tokyo city pop", "city pop music dance night nostalgia",
                 ["1sDUV75FdWsjf2uIdooCzz", "1VdpRTsLCEipiJTrQERMST"]),
    "jpop": ("J-pop", "pop song music dance", ["37i9dQZF1DXayDMsJG9ZBv"]),
    "lofi": ("lofi", "lofi calm study dream sleep music", ["37i9dQZF1DWWQRwui0ExPn", "54XEvcqtFLIcodkZAW9cxu"]),
    "hiphop": ("hip-hop", "hip-hop rap words rhythm music",
               ["16tpPSjRXzDFr614qvjNwv", "6YsPOwWFDeraCgnUg98Cca", "0JTOLgpeHOVxyRVp7xnRvv"]),
    "anime": ("anime soundtracks", "anime animation film soundtrack music", ["37i9dQZF1DWT8aqnwgRt92"]),
    "indie": ("indie", "indie guitar song album music", ["37i9dQZF1DX2Nc3B70tvx0"]),
    "electronic": ("electronic", "electronic synth dance signal music",
                   ["37i9dQZF1DX4dyzvuaRJ0n", "37i9dQZF1DX0r3x8OtiwEM"]),
    "jazz": ("jazz", "jazz coffee calm music", ["37i9dQZF1DX0SM0LYsmbMT", "37i9dQZF1DWVqfgj8NZEp1"]),
    "piano": ("piano and ambient", "piano calm peace sleep dream", ["37i9dQZF1DX4sWSpwq3LiO", "37i9dQZF1DX3Ogo9pFvBkY"]),
}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def oembed(kind, sid):
    u = "https://open.spotify.com/oembed?url=" + urllib.parse.quote(f"https://open.spotify.com/{kind}/{sid}", safe="")
    return json.loads(get(u))


def playlist_tracks(pid):
    h = get(f"https://open.spotify.com/embed/playlist/{pid}")
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', h, re.S)
    ent = json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    out = []
    for t in ent.get("trackList", []):
        uri = t.get("uri", "")
        title, artist = (" ".join((t.get(k) or "").split()) for k in ("title", "subtitle"))
        tid = uri.rsplit(":", 1)[-1]
        if not uri.startswith("spotify:track:") or not re.fullmatch(r"[A-Za-z0-9]{22}", tid):
            continue
        if t.get("isExplicit") or t.get("isNineteenPlus") or t.get("isPlayable") is False:
            continue
        if not title or blocked(title) or blocked(artist):
            continue
        out.append({"id": tid, "title": title[:120], "artist": artist[:120], "ms": int(t.get("duration") or 0)})
    return ent.get("name", ""), out


def main():
    out = {"built": "analysis/build_music_list.py", "genres": {}}
    seen = set()                                          # a track belongs to one genre only
    for g, (label, tags, pids) in GENRES.items():
        tracks, lists = [], []
        for pid in pids:
            name = oembed("playlist", pid).get("title", "")
            _, ts = playlist_tracks(pid)
            lists.append({"id": pid, "name": name})
            per = max(1, PER_GENRE // len(pids))
            for t in ts:
                if t["id"] in seen or sum(1 for x in tracks if x.get("_p") == pid) >= per:
                    continue
                seen.add(t["id"])
                tracks.append(dict(t, _p=pid))
        for t in tracks:
            t.pop("_p", None)
        out["genres"][g] = {"label": label, "tags": tags, "playlists": lists, "tracks": tracks[:PER_GENRE]}
        print(f"{g}: {len(tracks[:PER_GENRE])} tracks from {', '.join(x['name'] for x in lists)}")
    (ROOT / "music_curated.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    main()
