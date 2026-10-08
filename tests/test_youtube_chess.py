"""YouTube (muted, read-only) and chess at the desk, both chosen by the brain vote (#17).

    python -m pytest tests/test_youtube_chess.py -q
No network and no AI calls. The Chromium tests serve local HTML under YouTube's URL (page.route) and are skipped
without a browser.
"""
import asyncio
import io
import json
import math
import random
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import chess
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import brain_vote as V
import browse
import chess_game as C
import eyes as E
import life as L
import live_server
from browse import Browser, Screen, scene_change, video_text_ok
from live_server import Live
from state_io import read_jsonl
from tastes import PageWatch, Tastes


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def brain():
    from brain_sim import Brain
    b = Brain()
    b.run(1)
    return b


# --- 1. the guard on video titles and channels ----------------------------------------------------------------------
@pytest.mark.parametrize("text, ok", [
    ("Baking sourdough bread at dawn", True), ("Tokyo night walk 4K - Kichijoji", True), ("Lo-fi beats to study to", True),
    ("NHK WORLD-JAPAN", True),
    ("$PEPE to the moon 100x", False),                    # ticker + blocked words
    ("Send me 0.5 SOL for a shoutout", False),            # money request (chat filter)
    ("Free airdrop: claim now", False),                   # blocked topic
    ("visit www.example.com for more", False),            # links
    ("uncensored nsfw compilation", False),               # guard words
    ("Best online casino bonus", False),
])
def test_video_titles_and_channels_go_through_guard_and_chat_filter(text, ok):
    assert video_text_ok(text) is ok


def test_youtube_links_use_the_title_not_the_duration_and_drop_refused_titles():
    b = Browser(decide=True)
    sc = Screen("desk")
    sc.info = {"title": "bread baking — YouTube", "host": "youtube.com", "kind": "page"}
    raw = [["https://www.youtube.com/watch?v=a1", "10:50\nNow playing", 9000, True],
           ["https://www.youtube.com/watch?v=a1", "Sourdough from scratch, a slow morning", 2000, True],
           ["https://www.youtube.com/watch?v=b2", "$SOL pump 100x live", 2000, True],
           ["https://www.youtube.com/watch?v=c3", "Kneading dough by hand", 2000, True],
           ["https://accounts.google.com/ServiceLogin?service=youtube", "Sign in", 300, True]]
    page = b.pick_links(raw, "https://www.youtube.com/results?search_query=bread", "", sc)
    texts = {l["href"]: l["text"] for l in page["links"]}
    assert texts == {"https://www.youtube.com/watch?v=a1": "Sourdough from scratch, a slow morning",
                     "https://www.youtube.com/watch?v=c3": "Kneading dough by hand"}
    assert all(l["video"] for l in page["links"])
    assert browse.LOGIN_HREF.search("https://accounts.google.com/ServiceLogin?service=youtube")


def test_restricted_mode_cookie_and_muted_chromium_flags():
    assert {"name": "PREF", "value": "f2=8000000", "domain": ".youtube.com", "path": "/", "secure": True} \
        in browse.YOUTUBE_COOKIES                                         # f2=8000000: YouTube Restricted Mode
    assert "--mute-audio" in browse.CHROMIUM_ARGS
    assert browse.is_youtube("www.youtube.com") and browse.is_youtube("youtu.be") and not browse.is_youtube("notyoutube.co")
    assert browse.youtube_search_url("bread baking") == "https://www.youtube.com/results?search_query=bread+baking"


def _jpeg(color):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (128, 72), color).save(buf, "JPEG")
    return buf.getvalue()


def test_scene_change_measures_screenshot_differences():
    black, white, grey = _jpeg((0, 0, 0)), _jpeg((255, 255, 255)), _jpeg((20, 20, 20))
    assert scene_change(None, black) == 0.0 and scene_change(black, black) == 0.0
    assert scene_change(black, white) == 1.0
    assert 0.4 < scene_change(black, grey) < 0.8                          # 20 grey levels of SCENE_FULL (32)


def test_video_drive_feeds_the_visual_network(brain):
    live = SimpleNamespace(brain=brain.clone(), engine=SimpleNamespace(gain=0.5))
    vis = live.brain.group_idx["visual"]
    before = live.brain.stim[vis].copy()
    assert Live.video_drive(live, {"scene": 0.5}) == pytest.approx(live_server.VIDEO_DRIVE * 0.5 * 0.5)
    assert np.allclose(live.brain.stim[vis] - before, live_server.VIDEO_DRIVE * 0.25)
    assert Live.video_drive(live, {"scene": "nan?"}) == 0.0 and Live.video_drive(live, {}) == 0.0


# --- 2. the time bound ----------------------------------------------------------------------------------------------
def test_watch_time_is_bounded_and_follows_boredom_and_the_brain_response():
    grid = [-5, -1, -0.3, 0, 0.2, 0.5, 1, 7, None, float("nan"), "x"]
    for b in grid:
        for v in grid:
            assert V.WATCH_MIN <= V.watch_minutes(b, v) <= V.WATCH_MAX == 10.0
    assert V.WATCH_MIN == 2.0
    assert V.watch_minutes(0.0, 1.0) == 10.0 and V.watch_minutes(1.0, -1.0) == 2.0
    assert V.watch_minutes(0.2, 0.9) > V.watch_minutes(0.2, 0.1)          # a strong response: watches longer
    assert V.watch_minutes(0.1, 0.5) > V.watch_minutes(0.9, 0.5)          # bored: shorter


def test_the_browser_clamps_any_watch_time():
    b = Browser(decide=True)
    sc = Screen("desk")
    sc.info = {"title": "x", "kind": "page"}
    for asked, want in ((1e9, browse.MAX_WATCH_S), (0.01, browse.MIN_WATCH_S), (None, 120.0), ("nan", 120.0),
                        (90, 90.0)):
        run(b._start_watch(sc, asked))
        assert sc.watch_s == want and sc.watch_until - time.time() <= browse.MAX_WATCH_S
        assert sc.info["video"]["watching"] and sc.info["video"]["muted"]


class FakeBrowser:
    def __init__(self):
        self.acts = []

    async def act(self, device, action, why, interest):
        self.acts.append(action)
        return {"id": 2, "device": device, "url": action.get("href")}


class FakeProvider:
    name, model = "fake", "fake"

    def __init__(self, text):
        self.text = text

    def ask(self, system, prompt):
        return self.text, 100, 20


PAGE = {"url": "https://www.youtube.com/results?search_query=bread", "title": "bread — YouTube", "host": "youtube.com",
        "kind": "page", "text": "Results", "can_back": False,
        "links": [{"id": "L1", "href": "https://www.youtube.com/watch?v=a1", "text": "Sourdough from scratch",
                   "video": True, "area": 4000}]}


@pytest.mark.parametrize("scale", [1.0, 60.0])
def test_a_chosen_video_gets_its_bounded_watch_time(brain, tmp_path, scale):
    async def broadcast(msg):
        pass
    fb = FakeBrowser()
    eyes = E.Eyes(FakeProvider(json.dumps({"options": [
        {"action": "play_video", "target": "L1", "label": "sourdough video", "networks": {"visual": 1.0}}]})),
        E.Budget(tmp_path / "c.jsonl"))
    live = SimpleNamespace(eyes=eyes, brain=brain.clone(), browser=SimpleNamespace(act=fb.act), broadcast=broadcast,
                           engine=SimpleNamespace(gain=1.0, tired=0.0, pressure=lambda t: 0.1),
                           life=SimpleNamespace(boredom=0.3), clock=SimpleNamespace(now=time.time),
                           tastes=Tastes(tmp_path / "t.json"), pagewatch=PageWatch(), decisions={}, decision_log=[],
                           targets={}, vote_rng=np.random.default_rng(0), time_scale=scale)
    live.novel = lambda o: Live.novel(live, o)
    live.end_page = lambda: Live.end_page(live)
    live._vote_and_act = lambda *a: Live._vote_and_act(live, *a)
    run(Live.decide(live, "desk", dict(PAGE, device="desk"), "bread"))
    dec = live.decisions["desk"]
    chosen = dec["options"][dec["chosen"]]
    act = fb.acts[0]
    if chosen["action"] == "play_video":
        assert 2.0 <= dec["watch_min"] <= 10.0
        assert act["watch_s"] == pytest.approx(dec["watch_min"] * 60 / scale)
        assert dec["watch_min"] == V.watch_minutes(0.3, chosen["value"])
    else:                                                                 # the leave option won the vote
        assert "watch_s" not in act


# --- 3. in a real Chromium: muted, bounded, then the brain decides again --------------------------------------------
WATCH = """<!doctype html><title>{title} - YouTube</title>
<style>body{{margin:0}} #scene{{width:1280px;height:600px;background:#000}}</style>
<div id="scene"></div><video id="v" width="320" height="180"></video>
<ytd-video-owner-renderer><ytd-channel-name><a href="/@bakery">{channel}</a></ytd-channel-name></ytd-video-owner-renderer>
<p>{text}</p>
<a href="https://www.youtube.com/watch?v=b2">Kneading dough by hand, slowly</a>
<a href="https://www.youtube.com/watch?v=c3">Rye bread in a wood oven, full process</a>
<ytd-comments id="comments">Comment: nobody should see this</ytd-comments>
<script>let i = 0; setInterval(() => {{ document.getElementById('scene').style.background = (i++ % 2) ? '#fff' : '#000';
  const v = document.getElementById('v'); v.muted = false; v.volume = 1; }}, 400);</script>"""


async def _chromium():
    b = Browser(decide=True)
    try:
        sc = await b._ensure("desk")
    except Exception as e:                                                             # no usable Chromium here
        pytest.skip(f"chromium did not start: {e!r}"[:200])
    return b, sc


async def _shut(b):
    await b.close()
    if b.pw:
        await b.pw.stop()


VIDEOS = "https://www.slowbakery-videos.org"                       # a video site that is not YouTube (fixture pages)


def _serve(sc, pages):
    async def handler(route):
        url = route.request.url
        html = next((h for k, h in pages.items() if k in url), None)
        if html is None:
            return await route.abort()
        await route.fulfill(status=200, content_type="text/html", body=html)
    return sc.page.route("https://**/*", handler)


def test_chromium_watch_is_muted_restricted_bounded_then_decides_again(monkeypatch):
    """Since #130 YouTube's own pages are never opened in Chromium (its videos play in the official embed), so the
    watch loop is checked on another video site's page; a youtube.com/watch URL is refused before any request."""
    if not Browser.available():
        pytest.skip("playwright not installed")
    monkeypatch.setattr(browse, "MIN_WATCH_S", 0.5)
    monkeypatch.setattr(browse, "VIDEO_SHOT_S", 0.0)
    page = WATCH.replace("https://www.youtube.com/watch?v=", VIDEOS + "/videos/").replace(" - YouTube</title>", "</title>")

    async def main():
        b, sc = await _chromium()
        try:
            cookies = await sc.ctx.cookies("https://www.youtube.com")
            assert {(c["name"], c["value"]) for c in cookies} >= {("PREF", "f2=8000000")}   # Restricted Mode
            requested = []
            sc.page.on("request", lambda r: requested.append(r.url))
            await _serve(sc, {"/videos/a1": page.format(title="Sourdough from scratch", channel="Slow Bakery",
                                                       text="A quiet morning of baking. " * 10),
                              "/videos/bad": page.format(title="Gallery", channel="x", text="nude " * 3 + "x " * 50)})
            sc.mode = "video"
            assert not await b._open(sc, "https://www.youtube.com/watch?v=a1", "picked", "page")   # #130
            assert "YouTube page" in b.last_skip and not [u for u in requested if "youtube.com" in u]
            b.robots.load("www.slowbakery-videos.org", 200, "User-agent: *\nAllow: /")   # its robots.txt (fixture)
            assert await b._open(sc, VIDEOS + "/videos/a1", "picked", "page")
            state = await b._play_muted(sc)
            assert state["muted"] and state["volume"] == 0
            await b._start_watch(sc, 2.5)
            seen = []
            while True:
                out = await b.step("desk", [], None, "video")
                if out and "decide" in out:
                    break
                if out:
                    seen.append(out["video"])
                    assert out["video"]["muted"]                          # muted again at every screenshot,
                    assert await sc.page.evaluate("() => document.getElementById('v').muted")   # whatever the page does
                await asyncio.sleep(0.25)
                assert len(seen) < 40
            assert seen and all(v["watching"] for v in seen) and max(v["scene"] for v in seen) > 0.3
            assert sc.watch_until == 0.0 and sc.info["video"]["watching"] is False
            assert await sc.page.evaluate("() => document.getElementById('v').paused")
            links = out["decide"]["links"]
            assert {l["text"] for l in links if l["video"]} == {"Kneading dough by hand, slowly",
                                                                 "Rye bread in a wood oven, full process"}
            # a page the guard refuses is never shown (finance titles are viewable on the web since #56)
            assert not await b._open(sc, VIDEOS + "/videos/bad", "picked", "page")
            assert b.last_skip == "guard"
        finally:
            await _shut(b)
    run(main())


# --- 4. chess: legal moves only, 5 candidates, the vote picks one ---------------------------------------------------
def test_games_are_legal_to_the_end_and_logged_fields():
    rng = random.Random(3)
    for seed in range(3):
        g = C.Game(0.0, color=chess.WHITE if seed % 2 else chess.BLACK, rng=random.Random(seed))
        ref = chess.Board()
        while not g.over:
            if g.his_turn:
                cands = g.candidates()
                assert 1 <= len(cands) <= C.CANDIDATES and len({c["target"] for c in cands}) == len(cands)
                assert all(chess.Move.from_uci(c["target"]) in ref.legal_moves for c in cands)
                assert all(0.0 <= w <= 1.0 for c in cands for w in c["networks"].values())
                mv = rng.choice(cands)["target"]
            else:
                mv = g.opponent().uci()
            assert chess.Move.from_uci(mv) in ref.legal_moves
            ref.push(chess.Move.from_uci(mv))
            g.push(mv)
        assert g.board.fen() == ref.fen() and g.result in ("won", "lost", "draw", "unfinished")
        rec = g.record(100.0)
        assert rec["plies"] == len(g.sans) and rec["moves"].split() == g.sans and rec["result"] == g.result


def test_illegal_moves_are_refused():
    g = C.Game(0.0, color=chess.WHITE)
    with pytest.raises(ValueError):
        g.push("e2e5")
    with pytest.raises(ValueError):
        g.push("e7e5")                                                    # not white's piece
    assert g.sans == [] and g.board.fen() == chess.STARTING_FEN


def test_scorer_ranks_a_free_queen_first_and_tags_it_as_reward():
    b = chess.Board("4k3/8/8/3q4/4P3/8/8/4K3 w - - 0 1")               # e4xd5 wins the queen for free
    cands = C.candidates(b, random.Random(0))
    assert cands[0]["label"] == "exd5" and cands[0]["networks"]["reward"] > 0.9
    assert b.fen() == "4k3/8/8/3q4/4P3/8/8/4K3 w - - 0 1"                  # the board is left as it was


def test_opponent_takes_free_material_and_sees_mate_in_one():
    b = chess.Board("4k3/8/8/8/4p3/3Q4/8/4K3 b - - 0 1")               # exd3 takes the queen for free
    assert C.opponent_move(b, random.Random(0)).uci() == "e4d3"
    b = chess.Board("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1")              # Ra8# for white
    assert C.opponent_move(b, random.Random(1)).uci() == "a1a8"
    b = chess.Board("4k3/8/8/8/8/8/1q6/K7 w - - 0 1")                   # one legal move: Kxb2
    assert C.opponent_move(b, random.Random(0)).uci() == "a1b2"


def test_the_brain_vote_picks_among_the_candidates(brain):
    g = C.Game(0.0, color=chess.WHITE, rng=random.Random(5))
    cands = g.candidates()
    for seed in range(5):
        dec = V.vote(brain.clone(), cands, 1.0, {"boredom": 0.4}, rng=np.random.default_rng(seed))
        assert len(dec["options"]) == len(cands) == 5
        assert [o["label"] for o in dec["options"]] == [c["label"] for c in cands]
        assert 0 <= dec["chosen"] < 5 and sum(o["chosen"] for o in dec["options"]) == 1
        assert math.isclose(sum(o["p"] for o in dec["options"]), 1.0, abs_tol=0.01)


def test_card_wording():
    assert C.CARD == "his brain model picks among 5 candidate moves from a simple move scorer"
    for text in (C.CARD, C.NOTE):
        low = text.lower()
        assert "understand" not in low and "plan" not in low.replace("plays", "")


def test_live_plays_a_game_and_logs_it(tmp_path, monkeypatch):
    monkeypatch.setattr(live_server, "CHESS_MIN_GAP_S", 0.0)
    monkeypatch.setattr(C, "MAX_PLIES", 12)                              # a short game: "unfinished (move limit)"
    live = Live("m", True, time_scale=1e6, data_dir=tmp_path)
    sent = []

    async def broadcast(msg):
        sent.append(msg)
    live.broadcast = broadcast
    live.engine.stage = "AWAKE"
    t = live.clock.now()
    live.life.start("play_chess", t, "test")
    live.life.path, live.life.place = [], "desk"

    async def main():
        for _ in range(200):
            await live.chess_step()
            if live.chess_last:
                break
    run(main())
    rows = read_jsonl(tmp_path / "chess.jsonl")
    assert len(rows) == 1 and rows[0]["plies"] == 12 and rows[0]["result"] in ("won", "lost", "draw", "unfinished")
    board = chess.Board()
    for san in rows[0]["moves"].split():
        board.push_san(san)                                              # every logged move is legal
    votes = [m for m in sent if m.get("type") == "chess" and m.get("vote")]
    assert votes and all(len(m["vote"]["options"]) <= 5 for m in votes)
    v = live.chess_last["vote"]
    assert sum(o["chosen"] for o in v["options"]) == 1
    assert next(o["label"] for o in v["options"] if o["chosen"]) == v["move"]
    assert live.life.until <= live.clock.now() + 1                       # the activity ends with the game
    assert sent[-1].get("finished") and live.chess is None
    view = live.chess_view()
    assert view["card"] == C.CARD and view["games"][0]["plies"] == 12


def test_getting_up_leaves_the_game_unfinished(tmp_path):
    live = Live("m", True, time_scale=1e6, data_dir=tmp_path)

    async def broadcast(msg):
        pass
    live.broadcast = broadcast
    live.engine.stage = "AWAKE"
    live.life.start("play_chess", live.clock.now(), "test")
    live.life.path, live.life.place = [], "desk"
    run(live.chess_step())
    assert live.chess is not None
    live.life.activity = "eat"
    run(live.chess_step())
    rows = read_jsonl(tmp_path / "chess.jsonl")
    assert rows[-1]["result"] == "unfinished" and rows[-1]["reason"] == "he got up" and live.chess is None


# --- 5. life.py: the two activities are chosen by needs like the others ------------------------------------------
def _life(boredom=0.5, seed=0):
    lf = L.Life(rng=random.Random(seed))
    lf.boredom = boredom
    return lf


NOON = 1790000000.0 - (1790000000.0 % 86400) + 3 * 3600                 # 12:00 Tokyo (UTC+9)


def test_activities_exist_with_places_labels_and_reasons():
    for act in ("watch_video", "play_chess"):
        assert L.ACTIVITIES[act][0] == "desk" and act in L.LABEL
    assert "muted" in L.LABEL["watch_video"]


def test_both_activities_get_chosen_by_needs():
    picks = {}
    for seed in range(400):
        lf = _life(boredom=random.Random(seed).random(), seed=seed)
        lf.body.ghrelin, lf.activity = 0.1, "research"                  # after a while of reading at the desk
        act = lf.choose(NOON + seed * 60, "AWAKE", {}, 0.0, 0.0)
        picks[act] = picks.get(act, 0) + 1
    assert picks.get("watch_video", 0) > 0 and picks.get("play_chess", 0) > 0


def test_at_most_one_chess_game_an_hour_and_no_videos_without_a_browser():
    lf = _life(boredom=0.9)
    lf.hear("let's play chess", NOON)
    assert lf.desire("play_chess", NOON) > 0
    lf.start("play_chess", NOON, "test")
    assert not lf.chess_ok(NOON + 3599) and lf.chess_ok(NOON + 3600)
    for seed in range(200):
        lf.rng = random.Random(seed)
        lf.hear("chess chess", NOON + 1800)
        assert lf.choose(NOON + 1800, "AWAKE", {}, 0.0, 0.0) != "play_chess"
    lf.can_watch = False
    lf.hear("watch a youtube video", NOON + 1800)
    assert all(lf.choose(NOON + 1800, "AWAKE", {}, 0.0, 0.0) != "watch_video" for _ in range(100))
    saved = L.Life(lf.to_dict())
    assert saved.last_chess == NOON                                      # survives a restart


def test_a_chat_wish_makes_the_activity_likely():
    wins = 0
    for seed in range(50):
        lf = _life(boredom=0.3, seed=seed)
        lf.body.ghrelin = 0.1
        lf.hear("play chess with me!", NOON)
        wins += lf.choose(NOON, "AWAKE", {}, 0.0, 0.0) == "play_chess"
    assert wins >= 40
    lf = _life()
    lf.start("play_chess", NOON, "x")
    lf.end_activity(NOON + 60)
    assert lf.until == NOON + 60


def _hungry(lf, lo, hi):
    """Sets the body's ghrelin-like proxy so that lo < hunger < hi."""
    for g in np.linspace(0.0, 1.0, 201):
        lf.body.ghrelin = g
        if lo < lf.hunger < hi:
            return lf
    raise AssertionError((lo, hi))


def _at(lf, act, t):
    """He is doing `act` at its place since t (already arrived)."""
    lf.start(act, t, "test")
    lf.place, lf.path = L.ACTIVITIES[act][0], []
    lf.x, lf.z = L.PLACES[lf.place]
    return lf


def test_a_game_in_progress_is_not_cut_by_a_mild_hunger():
    """The chess smoke failure: the one-game-an-hour rule scored the game he had just started 0, so any hunger above
    SATED ended it before live_server could set up the board. Mild hunger: he finishes the game, then eats."""
    for seed in range(20):
        lf = _hungry(_at(_life(seed=seed), "play_chess", NOON), L.SATED + 0.03, L.EAT_AT - 0.02)
        for k in range(30):                                             # 30 simulated minutes at the board
            lf.update(NOON + 60 * k, 1.0, 60.0, "AWAKE", {}, 0.0, 0.0)
            lf.body.ghrelin = min(lf.body.ghrelin, 0.99)
            if lf.hunger >= L.EAT_AT:
                break
            assert lf.activity == "play_chess", (seed, k, lf.hunger)
    lf = _hungry(_at(_life(), "play_chess", NOON), L.EAT_AT + 0.1, 1.01)           # meal time: needs first still holds
    assert lf.hungry_now(NOON + 60, {}, 0.0, 0.0)


def test_a_heard_chess_wish_leads_to_a_game_within_minutes():
    for seed in range(30):
        for act in ("research", "chat", "window", "park"):
            lf = _hungry(_life(seed=seed), 0.0, L.SATED)
            lf.chat_waiting = 1 if act == "chat" else 0
            _at(lf, act, NOON)
            for _ in range(2 if act == "chat" else 1):                  # answering the chat: the wish is in it
                lf.hear("let's play chess", NOON + 60)
            t = NOON + 60
            while lf.activity != "play_chess" and t < NOON + 5 * 60:
                t += 30
                lf.update(t, 0.5, 30.0, "AWAKE", {}, 0.0, 0.0)
            assert lf.activity == "play_chess", (seed, act)
    lf = _hungry(_at(_life(), "research", NOON), 0.0, L.SATED)           # one game an hour: no wish breaks that rule
    lf.last_chess = NOON - 600
    lf.hear("let's play chess", NOON + 60)
    for k in range(10):
        lf.update(NOON + 60 * (k + 1), 1.0, 60.0, "AWAKE", {}, 0.0, 0.0)
    assert lf.activity == "research"


def test_the_vote_card_stays_on_the_video_it_chose():
    dec = {"options": [], "reason": "r", "page_url": "https://www.youtube.com/results?search_query=x", "status_id": 3,
           "led_to": "https://www.youtube.com/watch?v=a1", "watch_min": 4.0}
    live = SimpleNamespace(browser=SimpleNamespace(restarting=False, screens={}), decisions={"desk": dec})
    live.browser.screens["desk"] = {"id": 9, "url": "https://www.youtube.com/watch?v=a1", "title": "Sourdough",
                                    "video": {"watching": True}}
    assert Live.screen_status(live, "desk")["decision"]["watch_min"] == 4.0
    live.browser.screens["desk"] = {"id": 10, "url": "https://www.youtube.com/watch?v=zz", "title": "Other"}
    assert "decision" not in Live.screen_status(live, "desk")
