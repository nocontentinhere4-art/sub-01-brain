"""#68: he listens to music on Spotify. His brain model picks among 3-5 candidate tracks; pages show Spotify's official
embed. The source with and without keys (Web API mocked, oEmbed fixture), candidates and the vote, chat wishes through
the filter, needs first, the embed URL format, and no audio fetched by the server. No network: every request is mocked."""
import asyncio
import io
import json
import random
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import brain_vote  # noqa: E402
import diary  # noqa: E402
import life as L  # noqa: E402
import music as M  # noqa: E402
from brain_sim import Brain  # noqa: E402
from state_io import read_jsonl  # noqa: E402
from twin.body import Body  # noqa: E402

DATA = ROOT / "tests" / "data" / "music"
OEMBED = json.loads((DATA / "oembed_track.json").read_text())
SEARCH = json.loads((DATA / "search.json").read_text())
TOKYO = ZoneInfo("Asia/Tokyo")
AUDIO = re.compile(r"p\.scdn\.co|mp3|preview|audio|\.m4a|\.ogg", re.I)


def at(h, m=0):
    return datetime(2026, 10, 2, h, m, tzinfo=TOKYO).timestamp()


class Fake:
    """A mocked network: records every request, answers token / search / track / oEmbed from fixtures."""

    def __init__(self, oembed_status=200, search_status=200, token_status=200):
        self.calls, self.oembed_status, self.search_status, self.token_status = [], oembed_status, search_status, token_status

    def __call__(self, method, url, headers=None, data=None):
        self.calls.append((method, url, dict(headers or {}), data))
        if url == M.TOKEN_URL:
            return (200, {"access_token": "TOKEN-abc", "token_type": "Bearer", "expires_in": 3600}) \
                if self.token_status == 200 else (self.token_status, None)
        if url.startswith(M.API + "/search"):
            return (self.search_status, SEARCH if self.search_status == 200 else None)
        if url.startswith(M.API + "/tracks/"):
            return 200, SEARCH["tracks"]["items"][0]
        if url.startswith("https://open.spotify.com/oembed"):
            return (self.oembed_status, OEMBED if self.oembed_status == 200 else None)
        raise AssertionError(f"unexpected request {url}")

    def urls(self):
        return [u for _, u, _, _ in self.calls]


def music(tmp_path=None, api=None, fake=None, seed=0):
    fake = fake or Fake()
    return M.Music(tmp_path, api=api, fetch=fake, rng=random.Random(seed), clock=lambda: at(20)), fake


# --- the embed ---------------------------------------------------------------------------------------------------
def test_embed_and_track_url_format():
    tid = "2BHj31ufdEqVK5CkYDp9mA"
    assert M.embed_url(tid).startswith(f"https://open.spotify.com/embed/track/{tid}?")
    assert M.track_url(tid) == f"https://open.spotify.com/track/{tid}"
    assert M.EMBED_HEIGHT == 80                                                   # the compact player
    for bad in ("", "x" * 21, "../../etc/passwd", "2BHj31ufdEqVK5CkYDp9m!", None, "2BHj31ufdEqVK5CkYDp9mA?x"):
        with pytest.raises(ValueError):
            M.embed_url(bad)


def test_pages_only_load_the_official_embed():
    for page in ("index.html", "life.html"):
        html = (ROOT / "web" / page).read_text()
        assert 'id="mu-embed"' in html and "open\\.spotify\\.com\\/embed\\/track\\/[A-Za-z0-9]{22}" in html
        assert "<audio" not in html and "autoplay" not in html.split('id="mu-embed"')[1][:300]
        assert "press play to listen on your own device" in html or page == "index.html"


# --- the source without keys ---------------------------------------------------------------------------------------
def test_curated_list_is_valid_and_wide():
    g = M.load_curated()
    for name in ("city_pop", "jpop", "lofi", "hiphop", "anime", "indie", "electronic"):
        assert len(g[name]["tracks"]) >= 8, name
    ids = [t["id"] for v in g.values() for t in v["tracks"]]
    assert all(M.valid_id(i) for i in ids) and len(ids) == len(set(ids))
    assert set(M.SEARCH) == set(g)


def test_keyless_candidates_are_checked_with_oembed_and_cached(tmp_path):
    m, fake = music(tmp_path)
    c = m.candidates(at(20))
    assert 3 <= len(c) <= 5 and len({x["id"] for x in c}) == len(c)
    assert all(x["source"] == "curated" and x["art"] == OEMBED["thumbnail_url"] for x in c)
    assert all(u.startswith("https://open.spotify.com/oembed?url=") for u in fake.urls())   # no key, no API
    n = len(fake.calls)
    for x in c:
        assert m.check(x["id"])["ok"]
    assert len(fake.calls) == n                                                    # cached
    assert M.Music(tmp_path, fetch=fake).checked.keys() >= {x["id"] for x in c}    # and saved


def test_keyless_skips_ids_spotify_does_not_know(tmp_path):
    m, fake = music(tmp_path, fake=Fake(oembed_status=404))
    assert m.candidates(at(20)) == []
    m2, _ = music(None, fake=Fake(oembed_status=0))                                # Spotify unreachable: offered anyway
    assert len(m2.candidates(at(20))) >= 3


def test_dayparts_lean_the_genres():
    assert M.daypart(at(8))[0] == "morning" and M.daypart(at(20))[0] == "evening"
    assert M.daypart(at(23, 30))[0] == M.daypart(at(2))[0] == "late night"
    assert max(M.daypart(at(20))[1], key=M.daypart(at(20))[1].get) == "hiphop"
    assert max(M.daypart(at(2))[1], key=M.daypart(at(2))[1].get) == "lofi"
    m, _ = music()
    w = m.genre_weights(at(20), taste_words=["anime"], taught=["piano"])
    base = M.daypart(at(20))[1]
    assert w["anime"] > base.get("anime", 0.4) and w["piano"] > 0.4


# --- the source with keys (Web API mocked) ---------------------------------------------------------------------------
def test_from_env_needs_both_keys():
    assert M.SpotifyAPI.from_env({}) is None
    assert M.SpotifyAPI.from_env({"SPOTIFY_CLIENT_ID": "a"}) is None
    assert M.SpotifyAPI.from_env({"SPOTIFY_CLIENT_ID": "a", "SPOTIFY_CLIENT_SECRET": "b"}) is not None


def test_api_search_uses_client_credentials_and_hides_the_keys(tmp_path, capsys):
    fake = Fake()
    api = M.SpotifyAPI("my-client-id", "my-secret", fetch=fake, clock=lambda: 1000.0)
    m, _ = music(tmp_path, api=api, fake=fake)
    c = m.candidates(at(20), k=4)
    assert c and all(x["source"] in ("api", "curated") for x in c) and any(x["source"] == "api" for x in c)
    method, url, headers, data = fake.calls[0]
    assert (method, url, data) == ("POST", M.TOKEN_URL, {"grant_type": "client_credentials"})
    assert headers["Authorization"] == "Basic " + __import__("base64").b64encode(b"my-client-id:my-secret").decode()
    searches = [c_ for c_ in fake.calls if c_[1].startswith(M.API + "/search")]
    assert searches and all(h["Authorization"] == "Bearer TOKEN-abc" and "market=JP" in u for _, u, h, _ in searches)
    assert sum(1 for c_ in fake.calls if c_[1] == M.TOKEN_URL) == 1                # the token is reused
    api_ids = {x["id"] for x in c if x["source"] == "api"}
    explicit = next(i for i in SEARCH["tracks"]["items"] if i.get("explicit"))
    assert explicit["id"] == "1111111111111111111111"
    assert M.track_from_api(explicit)["title"] == "An Explicit Track"              # explicit lyrics allowed (owner)
    t = M.track_from_api(SEARCH["tracks"]["items"][0])
    assert t["art"].endswith("00001e0281052badd62d5e14c3377786") and t["artist"] == "Miki Matsubara"
    assert "preview" not in json.dumps(t)                                           # the preview URL is never kept
    text = repr(api) + json.dumps(m.view(at(20))) + capsys.readouterr().out
    assert "my-secret" not in text and "my-client-id" not in text and "TOKEN-abc" not in text


@pytest.mark.parametrize("which", ["token", "search"])
def test_api_failure_falls_back_to_the_curated_list(tmp_path, capsys, which):
    fake = Fake(token_status=401) if which == "token" else Fake(search_status=429)
    api = M.SpotifyAPI("id-x", "secret-y", fetch=fake)
    m, _ = music(tmp_path, api=api, fake=fake)
    c = m.candidates(at(20))
    assert len(c) >= 3 and all(x["source"] == "curated" for x in c)
    out = capsys.readouterr().out
    assert "curated list" in out and "secret-y" not in out and "id-x" not in out
    assert m.view(at(20))["api"].startswith("down:")


# --- no audio, ever --------------------------------------------------------------------------------------------------
def test_no_audio_fetched_by_the_server(tmp_path):
    fake = Fake()
    api = M.SpotifyAPI("a", "b", fetch=fake)
    m, _ = music(tmp_path, api=api, fake=fake)
    for h in (8, 13, 20, 23):
        for x in m.candidates(at(h)):
            m.play(x, {"options": []}, at(h), "activity")
            m.stop(at(h) + 60, "the track ended")
    assert fake.calls and not any(AUDIO.search(u) for u in fake.urls())
    allowed = ("https://accounts.spotify.com/api/token", "https://api.spotify.com/v1/search",
               "https://api.spotify.com/v1/tracks/", "https://open.spotify.com/oembed?url=")
    assert all(u.startswith(allowed) for u in fake.urls())
    assert "preview" not in (tmp_path / "music.jsonl").read_text()
    src = (ROOT / "music.py").read_text()
    assert not re.search(r"""(\.get\(|\[)["']preview""", src) and "audioPreview" not in src


def test_http_json_never_reads_a_non_json_body(monkeypatch):
    class Resp(io.BytesIO):
        status = 200
        headers = {"Content-Type": "audio/mpeg"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, *a):
            raise AssertionError("an audio body was read")
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: Resp(b"ID3"))
    assert M.http_json("GET", "https://open.spotify.com/oembed?url=x") == (200, None)


# --- chat wishes through the filter -----------------------------------------------------------------------------------
@pytest.mark.parametrize("text,q", [
    ("play city pop", "city pop"), ("metti un po' di lofi", "lofi"), ("Play some Miki Matsubara on Spotify!", "Miki Matsubara"),
    ("ascolta jazz", "jazz"), ("play some music", "music"), ("listen to anime soundtracks", "anime soundtracks"),
    ("play https://evil.example/x.mp3", None), ("play $SOLANA now", None), ("play bob@example.com", None),
    ("play chess?", "chess?"), ("hello there", None), ("play retard music", None), ("play <script>", None),
])
def test_chat_wishes_go_through_the_filter(text, q):
    assert M.wish(text) == q


def test_a_wish_comes_first_and_expires(tmp_path):
    m, _ = music(tmp_path)
    assert m.hear("play city pop", at(20)) == "city pop"
    qs = m.queries(at(20, 5))
    assert qs[0]["query"] == "city pop" and "a viewer asked" in qs[0]["why"]
    c = m.candidates(at(20, 5))
    assert c[0]["genre"] == "city_pop" and "a viewer asked" in c[0]["why"]
    assert m.live_wishes(at(20) + M.WISH_TTL + 1) == []
    m.play(c[0], {"options": []}, at(20, 6), "activity")
    assert m.live_wishes(at(20, 7)) == []                                            # answered


def test_life_hears_music_wishes_but_not_chess():
    lf = L.Life(rng=random.Random(0))
    lf.hear("play some music", at(20))
    assert lf.desire("listen_music", at(20)) > 0
    lf2 = L.Life(rng=random.Random(0))
    lf2.hear("play chess with me!", at(20))
    assert lf2.desire("listen_music", at(20)) == 0 and lf2.desire("play_chess", at(20)) > 0


# --- candidates and the vote -------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def brain():
    b = Brain()
    for _ in range(20):
        b.step(10)
    return b


def test_stimulus_comes_from_the_lexicon_and_the_brain_votes(brain, tmp_path):
    m, _ = music(tmp_path, seed=3)
    tracks = m.candidates(at(20), k=5)
    opts = m.options(tracks)
    assert len(opts) == 5 and all(o["action"] == "listen" and M.valid_id(o["target"]) for o in opts)
    for o in opts:
        assert o["networks"] and max(o["networks"].values()) == 1.0
        assert set(o["networks"]) <= set(brain.group_idx)
    lofi = m.networks({"genre": "lofi", "title": "x", "artist": "y"})
    assert lofi.get("reward") and lofi.get("default")                                # music -> reward, dream/sleep -> default
    dec = brain_vote.vote(brain.clone(), opts, 1.0, {"boredom": 0.3}, rng=np.random.default_rng(1))
    assert sum(o["chosen"] for o in dec["options"]) == 1 and abs(sum(o["p"] for o in dec["options"]) - 1) < 0.01
    k = dec["chosen"]
    pub = m.play(tracks[k], dec, at(20), "activity")
    assert pub["embed"] == M.embed_url(tracks[k]["id"]) and pub["url"] == M.track_url(tracks[k]["id"])
    assert len(pub["options"]) == 5 and pub["options"][k]["chosen"]
    assert "love" not in pub["reason"] and "chose it" not in pub["reason"]
    topics = m.topics(opts[k], tracks[k])
    assert f"kw:{tracks[k]['genre']}" in topics


def test_history_today_and_the_diary(tmp_path):
    m, _ = music(tmp_path)
    c = m.candidates(at(21))
    m.play(c[0], {"options": [], "reason": "chose it: reward areas responded most"}, at(21), "activity")
    view = m.view(at(21, 1))
    assert view["now"]["id"] == c[0]["id"] and view["card"] == M.CARD and "never" in view["note"]
    assert view["now"]["reason"].startswith("his brain model leaned toward it")
    m.stop(at(21, 4), "the track ended", 0.4)
    m.play(c[1], {"options": []}, at(23, 50), "activity")
    m.stop(at(23, 55), "fell asleep")
    rows = m.view(at(23, 56))["today"]
    assert [r["id"] for r in rows] == [c[1]["id"], c[0]["id"]] and rows[1]["response"] == 0.4
    assert m.novel(c[0]["id"]) is False and m.novel("2222222222222222222222")
    day = m.day("2026-10-02")
    f = diary.music_facts(day)
    assert f["tracks"] == 2 and f["asleep_genre"] == day[-1]["genre_label"]
    line = diary.music_line(f)
    assert "fell asleep after" in line and not diary.BLOCK.search(line) and c[0]["artist"] not in line


# --- life.py: listen_music is chosen by needs; food still comes first --------------------------------------------------
def test_listen_music_is_an_activity_with_a_place_and_label():
    assert L.ACTIVITIES["listen_music"][0] == "bed" and "music" in L.LABEL["listen_music"]
    assert "listen_music" in L.INTERRUPTIBLE


def test_more_likely_when_bored_tired_or_in_the_evening():
    def share(boredom, h, pressure=0.0, n=300):
        wins = 0
        for seed in range(n):
            lf = L.Life(rng=random.Random(seed))
            lf.boredom, lf.body.ghrelin, lf.activity = boredom, 0.1, "research"
            wins += lf.choose(at(h), "AWAKE", {}, 0.0, pressure) == "listen_music"
        return wins / n
    calm_noon, bored_eve = share(0.1, 13), share(0.9, 21)
    assert bored_eve > calm_noon and bored_eve > 0.1
    assert share(0.4, 15, pressure=0.9) > share(0.4, 15, pressure=0.0)


def test_food_still_comes_first():
    body = Body({"since_meal_h": 6.0, "ghrelin": 0.9, "glucose": 78.0})
    lf = L.Life({"place": "bed", "activity": "listen_music", "until": 1e18}, rng=random.Random(1), body=body)
    lf.boredom = 1.0
    lf.hear("play some music, metti una canzone", at(21))
    assert lf.hunger > L.EAT_AT
    s = lf.scores(at(21), {"reward": 2.0}, 0.0, 1.0)
    assert max(s[a] for a in L.FOOD_ACTS if a in s) > s["listen_music"]
    assert all(lf.choose(at(21), "AWAKE", {}, 0.0, 1.0) in L.FOOD_ACTS for _ in range(200))
    assert lf.hungry_now(at(21), {}, 0.0, 1.0)                                       # and it stops the music early


def test_background_music_is_a_flag_not_an_activity():
    lf = L.Life(rng=random.Random(0))
    lf.start("research", at(14), "x")
    lf.path, lf.place = [], "desk"
    assert lf.music_bg_ok()
    lf.start("eat", at(14), "x")
    lf.path, lf.place = [], "table"
    assert not lf.music_bg_ok()
    lf.start("park", at(14), "x")
    assert lf.path and lf.music_bg_ok() is (lf.outdoor_leg() is not None)
    lf.music = {"title": "t", "artist": "a", "mode": "background"}
    assert lf.snapshot()["music"]["mode"] == "background" and "music" not in lf.to_dict()


# --- the live server: a pick, the stay response, the end ---------------------------------------------------------------
def test_live_listens_votes_logs_and_learns(tmp_path, monkeypatch):
    import live_server
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    live = live_server.Live("m", True, time_scale=1.0, data_dir=tmp_path)
    fake = Fake()
    live.music.fetch = fake
    sent = []

    async def broadcast(msg):
        sent.append(msg)
    live.broadcast = broadcast
    live.engine.stage = "AWAKE"
    t = live.clock.now()
    live.life.start("listen_music", t, "test")
    live.life.path, live.life.place = [], "bed"
    asyncio.run(live.music_step())
    now = live.music.now
    assert now and now["mode"] == "activity" and sent[-1]["type"] == "music" and sent[-1]["playing"]
    assert sent[-1]["embed"] == M.embed_url(now["id"])
    for i in range(40):                                                              # the stay response is measured
        live.music_watch.feed({"reward": 1.5, "attention": 1.2, "fear": 0.8}, now["wall"] + 11 + i, 0.05)
    learned = []
    monkeypatch.setattr(live.tastes, "learn", lambda topics, r: learned.append((topics, r)) or 0.0)
    live.life.activity = "eat"                                                       # he gets up: headphones off
    asyncio.run(live.music_step())
    assert live.music.now is None and learned and f"kw:{now['genre']}" in learned[0][0]
    row = read_jsonl(tmp_path / "music.jsonl")[-1]
    assert row["ended"] == "took the headphones off" and "response" in row
    assert sent[-1] == {"type": "music", "playing": False, "ended": "took the headphones off", "id": now["id"]}
    assert not any(AUDIO.search(u) for u in fake.urls())


def test_a_track_found_through_its_album_name_is_not_labelled_with_that_genre(tmp_path):
    """#89 live (2026-10-04 12:05 UTC): Queen's "Don't Stop Me Now" (album "Jazz", 1978) showed genre "jazz"."""
    queen = {"id": "7hQJA50XrCWABAu5v6QZ4i", "title": "Don't Stop Me Now - Remastered 2011", "artist": "Queen",
             "album": "Jazz (2011 Remaster)", "art": None, "ms": 210000}
    real = {"id": "1YQWosTIljIvxAgHWTp7KP", "title": "Take Five", "artist": "The Dave Brubeck Quartet",
            "album": "Time Out", "art": None, "ms": 324000}
    assert M.album_only_match(queen, "jazz") and not M.album_only_match(real, "jazz")
    assert not M.album_only_match({"title": "Jazz Night", "artist": "x", "album": "Jazz"}, "jazz")   # in the title

    class Api:
        def search(self, q):
            return [queen, real] if q == "jazz" else []
    m = M.Music(tmp_path, api=Api(), fetch=lambda *a, **k: None, rng=random.Random(0), clock=lambda: 1000.0)
    m.queries = lambda *a, **k: [{"genre": "jazz", "query": "jazz", "why": "evening"}]
    got = [c for c in m.candidates(1000.0, k=1) if c.get("source") == "api"]
    assert [c["id"] for c in got] == [real["id"]] and got[0]["genre"] == "jazz"
