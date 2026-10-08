"""Reading memory: what it reads becomes a stimulus, a memory, replay material and guides what it reads next.

    python -m pytest tests/test_reading.py
No network: the Wikipedia calls are replaced by fakes.
"""
import random
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chat
import live_server
import research as R
from diary import Diary
from live_server import Live
from sleep import ROME, Memory, SleepEngine, day_of


def tokyo(day, hm):
    h, m = map(int, hm.split(":"))
    return datetime(2026, 10, day, h, m, tzinfo=ROME).timestamp()


class FakeBrain:
    def __init__(self):
        self.calls = []

    def stimulate(self, g, a):
        self.calls.append((g, a))

    def total(self):
        return sum(a for _, a in self.calls)


def engine_at(day, hm):
    e = SleepEngine(tokyo(day, "08:00"), rng=random.Random(0))
    t = tokyo(day, "08:00")
    while t <= tokyo(day, hm) if hm >= "08:00" else t <= tokyo(day + 1, hm):
        e.update(t)
        t += 120
    return e


def fake_live(engine, t, memory=None):
    return SimpleNamespace(brain=FakeBrain(), engine=engine, memory=memory or Memory(),
                           clock=SimpleNamespace(now=lambda: t))


# --- 1. keywords ----------------------------------------------------------------------------------------
def test_keywords_title_first_stopwords_out_max_8():
    kw = R.keywords("Inokashira Park",
                    "Inokashira Park is a park in Kichijoji, Tokyo. The park is known for its pond, its cherry "
                    "blossoms and a small zoo, and it is one of the first public parks in Japan.")
    assert kw[:2] == ["park", "inokashira"]
    assert len(kw) <= 8 and len(set(kw)) == len(kw)
    for stop in ("the", "is", "and", "its", "known", "one", "first"):
        assert stop not in kw
    it = R.keywords("Pane", "Il pane è un alimento della cucina che si prepara con farina, acqua e lievito, "
                            "ed è uno dei cibi più antichi.")
    assert it[0] == "pane" and "della" not in it and "che" not in it and "più" not in it and "farina" in it


# --- 2. stimulus: chat rules at 0.5x + language/attention; sleep gain applies ----------------------------
def test_reading_stimulus_is_half_a_chat_message_plus_language_attention():
    title, kw = "Sweet bread", ["bakery", "love", "warm"]
    c, _, c_emo = chat.stimulus(" ".join([title] + kw))
    r, hits, r_emo = R.reading_stimulus(title, kw)
    assert set(c) <= set(r) and {"language", "attention"} <= set(r)
    for g in r:
        assert abs(r[g] - (0.5 * c.get(g, 0.0) + R.READING_DRIVE.get(g, 0.0))) < 1e-9, g
    assert r["reward"] == 0.5 * c["reward"]                       # positive words still count, at half gain
    assert r_emo == c_emo == "positive" and set(hits) == set(r)
    _, _, emo = R.reading_stimulus("Inokashira Park", ["park", "pond"])
    assert emo == "neutral"


def test_reading_is_attenuated_asleep_like_chat():
    art = {"title": "Bread", "keywords": ["bread", "flour", "bakery"], "url": "u"}
    awake = engine_at(1, "15:00")
    assert awake.stage == "AWAKE"
    live = fake_live(awake, tokyo(1, "15:00"))
    m = Live.absorb_reading(live, dict(art))
    stim, _, _ = R.reading_stimulus(art["title"], art["keywords"])
    assert abs(live.brain.total() - awake.gain * sum(stim.values())) < 1e-9
    asleep = engine_at(1, "02:30")
    assert asleep.stage != "AWAKE"
    live2 = fake_live(asleep, tokyo(2, "02:30"))
    Live.absorb_reading(live2, dict(art))
    assert live2.brain.total() < 0.5 * live.brain.total()          # sleep gain: much less gets through
    assert abs(live2.brain.total() / live.brain.total() - asleep.gain / awake.gain) < 1e-9
    # it is stored as a reading memory, not as chat
    assert m["source"] == "reading" and m["title"] == "Bread" and m["keywords"] == art["keywords"]
    assert m["stimulus"] == stim and m["emotion"] == "neutral"
    assert live.memory.chat() == []


def test_readings_never_count_as_heard_chat():
    mem = Memory()
    t = tokyo(1, "15:00")
    mem.add(t - 60, "do you like trains?", "AWAKE", {}, "neutral", [])
    mem.add(t - 30, "Bread", "AWAKE", {}, "neutral", [], source="reading", title="Bread", keywords=[])
    live = SimpleNamespace(memory=mem)
    assert Live.heard(live, t) == ["do you like trains?"]


# --- 3. memory + replay ---------------------------------------------------------------------------------
def night_engine():
    e = engine_at(1, "02:00")
    assert e.asleep
    return e


def test_readings_are_replayable_but_chat_wins():
    e = night_engine()
    mem = Memory()
    mem.add(tokyo(1, "18:00"), "good night sub", "AWAKE", {"language": 6}, "neutral", ["language"])
    for k in range(10):
        mem.add(tokyo(1, "14:00") + 240 * k, f"Article {k}", "AWAKE", {"language": 3, "attention": 1.5}, "neutral",
                ["language", "attention"], source="reading", title=f"Article {k}", keywords=[])
    rng = random.Random(3)
    picks = [mem.pick(tokyo(2, "02:00"), e.night_start(), rng)["source"] for _ in range(2000)]
    assert picks.count("chat") > 0.55 * len(picks)               # one message from a person beats ten readings
    assert picks.count("reading") > 0.2 * len(picks)              # ...but readings do get replayed
    # one reading vs one equal chat message: 0.6x
    m2 = Memory()
    m2.add(tokyo(1, "18:00"), "hello", "AWAKE", {}, "neutral", [])
    m2.add(tokyo(1, "18:00"), "Moon", "AWAKE", {}, "neutral", [], source="reading")
    w = m2.weights(m2.items, tokyo(2, "02:00"), e.night_start(), {})
    assert abs(w[1] / w[0] - 0.6) < 1e-9
    # with no chat at all, readings are the night's material
    m3 = Memory()
    m3.add(tokyo(1, "14:00"), "Moon", "AWAKE", {"language": 3}, "neutral", ["language"], source="reading")
    assert m3.pick(tokyo(2, "02:00"), e.night_start(), rng)["text"] == "Moon"


def test_replay_of_a_reading_reapplies_its_stimulus_and_is_recorded():
    e = night_engine()
    e.stage = "REM"
    mem = Memory()
    stim = {"language": 3.0, "attention": 1.5, "reward": 4.0}
    mem.add(tokyo(1, "14:00"), "Bread", "AWAKE", stim, "positive", list(stim), source="reading", title="Bread")
    t = tokyo(2, "02:00")
    e.update = lambda t, dt_real=None: [{"type": "replay", "text": "replay"}]
    brain = FakeBrain()
    brain.set_rhythm = lambda *a: None
    live = SimpleNamespace(brain=brain, engine=e, memory=mem, clock=SimpleNamespace(now=lambda: t), burst=0.0,
                           recent_replays=[], recent_read_replays=[], store=None, spiking=None)
    out = Live.sleep_tick(live)
    assert out[0]["type"] == "replay" and out[0]["source"] == "reading" and out[0]["text"] == "Bread"
    for g, a in stim.items():
        assert (g, live_server.REPLAY_AMP * a) in brain.calls
    assert ("memory", 6.0) in brain.calls
    assert live.recent_read_replays == ["Bread"] and live.recent_replays == []
    rec = e.night["replays"][-1]
    assert rec["source"] == "reading" and rec["text"] == "Bread"
    assert e.replay_counts() == {Memory.key(mem.items[0]): 1}


def test_tonight_chance_estimate():
    mem = Memory()
    t = tokyo(1, "15:00")
    alone = mem.add(t, "Moon", "AWAKE", {}, "neutral", [], source="reading")
    bed = tokyo(2, "00:30")
    assert mem.replay_chance(alone, bed) == 1.0                   # the only memory: replayed for sure
    for k in range(60):
        mem.add(t - 3600 - k * 60, f"message {k}", "AWAKE", {}, "threat" if k % 2 else "positive", [])
    for k in range(40):
        mem.add(t - k * 120, f"Article {k}", "AWAKE", {}, "neutral", [], source="reading")
    p = mem.replay_chance(alone, bed)
    assert 0.0 < p < 0.8
    assert mem.replay_chance(alone, bed) == p                     # fixed seed: stable on the page


# --- 4. brain-guided curiosity --------------------------------------------------------------------------
LINKS = ["History of Kyoto", "Ancient museum archive", "Football", "Bicycle", "Swimming", "Basalt", "Sushi festival"]


def fake_wiki(monkeypatch, links=LINKS, blocked_extract=()):
    monkeypatch.setattr(R, "links", lambda title, lang="en": [x for x in links if R.safe(x)])

    def summary(title, lang="en"):
        extract = f"{title} is a thing. " + ("A massacre happened." if title in blocked_extract else "")
        if not R.safe(title, extract):
            return None
        return {"title": title, "extract": extract, "url": "https://en.wikipedia.org/wiki/x", "lang": lang}
    monkeypatch.setattr(R, "summary", summary)
    monkeypatch.setattr(R, "search", lambda w, lang="en": [])


def reader_after(title="Tokyo", seed=7):
    r = R.Reader(rng=random.Random(seed))
    r.log = [{"title": title, "extract": "", "url": "", "t": 0.0, "why": ""}]
    return r


MEMORY_HOT = {"memory": 3.0, "reward": 0.4, "somatomotor": 0.4, "visual": 0.6, "default": 0.8}
BODY_HOT = {"memory": 0.4, "reward": 0.4, "somatomotor": 3.0, "visual": 0.6, "default": 0.8}


def test_curiosity_is_deterministic_with_a_seed(monkeypatch):
    fake_wiki(monkeypatch)
    a = [reader_after(seed=11).read(1000.0, [], MEMORY_HOT)["title"] for _ in range(3)]
    b = [reader_after(seed=11).read(1000.0, [], MEMORY_HOT)["title"] for _ in range(3)]
    assert a == b
    t1, i1 = R.curiosity(LINKS, MEMORY_HOT, {}, 0.0, random.Random(5))
    t2, i2 = R.curiosity(LINKS, MEMORY_HOT, {}, 0.0, random.Random(5))
    assert (t1, i1) == (t2, i2)


def test_curiosity_prefers_titles_of_the_most_active_networks(monkeypatch):
    fake_wiki(monkeypatch)
    mem_titles = {"History of Kyoto", "Ancient museum archive"}
    body_titles = {"Football", "Bicycle", "Swimming"}
    picks = [R.curiosity(LINKS, MEMORY_HOT, {}, 0.0, random.Random(s))[0] for s in range(300)]
    assert sum(p in mem_titles for p in picks) > 0.8 * len(picks)
    picks = [R.curiosity(LINKS, BODY_HOT, {}, 0.0, random.Random(s))[0] for s in range(300)]
    assert sum(p in body_titles for p in picks) > 0.8 * len(picks)
    art = reader_after(seed=1).read(1000.0, [], MEMORY_HOT)
    assert art["title"] in mem_titles
    assert "chose it: memory" in art["why"] and "followed a link from “Tokyo”" in art["why"]
    assert art["curiosity"]["networks"][0] == "memory" and 0 < art["curiosity"]["p"] <= 1
    assert len(art["keywords"]) <= 8


def test_curiosity_why_names_only_above_average_areas():
    quiet = {"memory": 0.5, "reward": 0.5, "somatomotor": 0.5}
    _, info = R.curiosity(["History of Kyoto"], quiet, {}, 0.0, random.Random(0))
    assert "most active" not in info["why"] and "new to it" in info["why"] and info["networks"] == []
    _, info = R.curiosity(["History of Kyoto"], quiet, {"History of Kyoto": 0.0}, 3600.0, random.Random(0))
    assert info["why"] == "chose it by chance"
    _, info = R.curiosity(["History of Kyoto"], MEMORY_HOT, {}, 0.0, random.Random(0))
    assert info["why"].startswith("chose it: memory areas were most active")


def test_curiosity_novelty_and_temperature():
    flat = {}
    hist = {"Basalt": 0.0}                                      # read recently: not new
    picks = [R.curiosity(["Basalt", "Granite"], flat, hist, 3600.0, random.Random(s))[0] for s in range(300)]
    assert picks.count("Granite") > 0.75 * len(picks)
    old = {"Basalt": 0.0}                                       # read 8 days ago: new again
    picks = [R.curiosity(["Basalt", "Granite"], flat, old, 8 * 86400.0, random.Random(s))[0] for s in range(400)]
    assert 0.3 < picks.count("Basalt") / len(picks) < 0.7
    hot = [R.curiosity(LINKS, MEMORY_HOT, {}, 0.0, random.Random(s), temperature=50.0)[0] for s in range(400)]
    assert len(set(hot)) >= 5                                   # high temperature: close to uniform


def test_reader_keeps_a_7_day_history(monkeypatch):
    fake_wiki(monkeypatch)
    r = reader_after()
    r.history = {"Old": 0.0}
    art = r.read(8 * 86400.0, [], {})
    assert art["title"] in r.history and "Old" not in r.history
    assert R.Reader(r.to_dict()).history == r.history


# --- 5. safety: the blocklist still applies -------------------------------------------------------------
def test_blocklist_still_enforced(monkeypatch):
    # "museum history" would score high with memory active, but the blocked titles never reach the pick
    links = ["Nazi history museum", "Massacre memorial archive", "Casino history", "Bread"]
    fake_wiki(monkeypatch, links=links)
    for s in range(30):
        art = reader_after(seed=s).read(1000.0, [], MEMORY_HOT)
        assert art["title"] == "Bread"
    # a safe title whose extract is blocked is skipped too
    fake_wiki(monkeypatch, links=["Ancient museum archive", "Bread"], blocked_extract={"Ancient museum archive"})
    for s in range(10):
        assert reader_after(seed=s).read(1000.0, [], MEMORY_HOT)["title"] == "Bread"
    assert not R.safe("Casino archive") and not R.safe("Suicide") and R.safe("Inokashira Park")
    assert R.safe("Bitcoin history")                      # finance may be read since #56 (read-only, never advice)


def test_links_filter_uses_the_blocklist(monkeypatch):
    pages = {"query": {"pages": {"1": {"links": [{"title": t} for t in
                                                 ["Memory", "Genocide", "List of museums", "Bread", "Casino history"]]}}}}
    monkeypatch.setattr(R, "get", lambda url, timeout=12: pages)
    assert R.links("Tokyo") == ["Memory", "Bread"]


# --- diary: read that day, replayed that night ----------------------------------------------------------
def test_diary_lists_readings_apart_from_chat():
    night = {"date": "2026-10-01", "sleep_onset": "2026-10-02T00:20", "woke_up": "2026-10-02T08:00", "wakeups": [],
             "replays": [{"text": "ciao sub", "source": "chat"}, {"text": "ciao sub"},
                         {"text": "Bread", "source": "reading"}, {"text": "Bread", "source": "reading"},
                         {"text": "Moon", "source": "reading"}]}
    with tempfile.TemporaryDirectory() as d:
        dia = Diary(d, Path(d) / "frames")
        out = dia.close(night, None, [{"title": "Bread", "url": "u1"}, {"title": "Basalt", "url": "u2"}])
    f = out["facts"]
    assert f["replays"] == 2 and f["top_replayed"] == ["ciao sub"] and f["reading_replays"] == 3
    read = {a["title"]: a for a in f["read"]}
    assert read["Bread"]["replayed"] == 2 and read["Bread"]["today"]
    assert read["Basalt"]["replayed"] == 0 and read["Basalt"]["today"]
    assert read["Moon"]["replayed"] == 1 and not read["Moon"]["today"]     # read on an earlier day
    assert f["read"][0]["title"] == "Bread"
    assert "Bread" in out["text"] and "2 messages" in out["text"]
    assert "It also replayed what it read" in out["share"] and len(out["share"]) <= 280


def test_day_of_names_the_day_like_the_night_after_it():
    assert day_of(tokyo(1, "10:00")) == "2026-10-01"
    assert day_of(tokyo(2, "00:40")) == "2026-10-01"              # still up after midnight: same day
    assert day_of(tokyo(2, "08:10")) == "2026-10-02"
