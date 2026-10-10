"""Dream diary: unattended REM frames are paced and capped, the morning entry is written and filtered.

    python -m pytest tests/test_diary.py
"""
import json
import random
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import diary as D
from diary import Diary
from sleep import ROME, SleepEngine


def tokyo(day, hm):
    h, m = map(int, hm.split(":"))
    return datetime(2026, 10, day, h, m, tzinfo=ROME).timestamp()


def fake_frame(frames_dir, n, stage="REM", reused=False):
    name = f"{1000 + n}.jpg"
    (frames_dir / name).write_bytes(b"\xff\xd8fake")
    return {"t": "03:00", "stage": stage, "img": f"/eye/{name}", "thought": "a staircase of bread",
            "scene": "a corridor of warm loaves folding into the sea", "why": {"replayed": ["ciao sub"]},
            "reused": reused}


class FakeLLM:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def ask(self, system, user):
        self.calls += 1
        assert "conscious" in system                 # the safety rules are in the prompt
        json.loads(user)
        return self.reply


def run_night(tmp, attended_every=0):
    """Step one night (22:00 -> 08:30) like live_server's eye loop; returns (diary, engine, frames rendered)."""
    frames = Path(tmp) / "frames"
    frames.mkdir()
    d = Diary(tmp, frames)
    e = SleepEngine(tokyo(1, "22:00"), rng=random.Random(1))
    e.last_stim = tokyo(1, "20:00")
    t, real, n = tokyo(1, "22:00"), 0.0, 0
    while t < tokyo(2, "08:30"):
        t += 30
        real += 30
        e.update(t)
        if d.due(e, t, now_real=real):
            n += 1
            d.add(e.night["date"], fake_frame(frames, n), t, attended=False)
            d.last_real = real
    return d, e, n


def test_unattended_frames_paced_and_capped():
    with tempfile.TemporaryDirectory() as tmp:
        d, e, n = run_night(tmp)
        assert e.last_night is not None and e.night is None              # the night closed at 08:00
        entry = d.load(e.last_night["date"])
        assert 3 <= n <= D.MAX_UNATTENDED                                  # some REM, never above the cap
        assert entry["unattended"] == n == len(entry["frames"])
        times = [f["img"] for f in entry["frames"]]
        assert len(set(times)) == len(times)
        for f in entry["frames"]:                                          # images copied out of the rolling buffer
            assert (Path(tmp) / "diary" / "img" / e.last_night["date"] / Path(f["img"]).name).exists()


def test_cap_holds_with_long_rem():
    with tempfile.TemporaryDirectory() as tmp:
        frames = Path(tmp) / "f"
        frames.mkdir()
        d = Diary(tmp, frames)

        class E:                                                            # a night that is REM all along
            stage, night = "REM", {"date": "2026-10-01"}
        t = 0.0
        for k in range(100):
            t += D.DREAM_EVERY_S
            if d.due(E, t, now_real=t):
                d.add("2026-10-01", fake_frame(frames, k), t, attended=False)
                d.last_real = t
        assert d.load("2026-10-01")["unattended"] == D.MAX_UNATTENDED


def test_skips_reused_and_non_rem_frames():
    with tempfile.TemporaryDirectory() as tmp:
        frames = Path(tmp) / "f"
        frames.mkdir()
        d = Diary(tmp, frames)
        assert d.add("2026-10-01", fake_frame(frames, 1, reused=True), 0, False) is None
        assert d.add("2026-10-01", fake_frame(frames, 2, stage="NREM"), 0, False) is None
        assert d.add("2026-10-01", fake_frame(frames, 3), 0, True)["unattended"] == 0   # watched live: no cap use


def test_morning_entry_with_llm():
    with tempfile.TemporaryDirectory() as tmp:
        d, e, _ = run_night(tmp)
        date = d.pending_close(e)
        assert date == e.last_night["date"]
        llm = FakeLLM('{"title": "Bread that kept folding", "text": "SUB-01 dreamt of a corridor of loaves."}')
        entry = d.close(e.last_night, llm)
        assert llm.calls == 1 and entry["closed"]
        assert entry["title"] == "Bread that kept folding"
        assert entry["share"].endswith("A model of brain activity, not a mind.")
        assert len(entry["share"]) <= 280
        assert d.pending_close(e) is None                                  # written once
        assert d.index()[0]["date"] == date and d.index()[0]["closed"]


@pytest.mark.parametrize("reply", [
    '{"title": "I am alive", "text": "SUB-01 is conscious now."}',
    '{"title": "Moon", "text": "He dreamt the coin went to the moon, buy now."}',
    "not json at all",
])
def test_unsafe_or_broken_summary_falls_back(reply):
    with tempfile.TemporaryDirectory() as tmp:
        d, e, _ = run_night(tmp)
        entry = d.close(e.last_night, FakeLLM(reply))
        assert "alive" not in entry["title"].lower() and "conscious" not in entry["text"].lower()
        assert "buy" not in entry["text"].lower()
        assert entry["text"].startswith("SUB-01 slept")


@pytest.mark.parametrize("text, kept, gone", [
    ("SUB-01 dreamt of a train platform folding into the sea. He walked past warm loaves on the counter.",
     ["train platform", "He walked past warm loaves"], []),
    ("SUB-01 dreamt of a crypto chart glowing over the bed. Then the corridor of loaves came back.",
     ["corridor of loaves"], ["crypto", "chart"]),
    ("A dumpling shop floating over a canal. Pumpkin soup stock steaming in the dark.", ["dumpling", "Pumpkin"], []),
    ("The coin went to the moon, buy now. The bakery door kept opening.", ["bakery door"], ["buy", "coin"]),
    ("She bought bread at the counter; the loaves were still warm.", ["bought bread"], []),
])
def test_clean_line_drops_only_the_offending_sentence(text, kept, gone):
    out = D.clean_line(text, 420)
    for k in kept:
        assert k in out, out
    for g in gone:
        assert g.lower() not in out.lower(), out
    assert D.clean_line("buy now", 80) == "" and D.clean_line("SUB-01 is conscious now.", 80) == ""


def test_dream_text_with_pronouns_is_kept_and_quoted_lines_are_filtered():
    with tempfile.TemporaryDirectory() as tmp:
        d, e, _ = run_night(tmp)
        e.last_night["replays"] = [{"text": "buy this coin now", "source": "chat"}] * 3 + \
                                  [{"text": "sweet dreams sub", "source": "chat"}] * 2 + \
                                  [{"text": "pane", "source": "taught"}]
        llm = FakeLLM('{"title": "Bread that kept folding", "text": "SUB-01 dreamt of a train platform folding '
                      'into the sea. He walked past warm loaves on the counter."}')
        entry = d.close(e.last_night, llm)
        assert entry["text"].startswith("SUB-01 dreamt") and "He walked" in entry["text"]
        assert entry["facts"]["replays"] == 5 and entry["facts"]["taught_replays"] == 1
        assert entry["facts"]["top_replayed"] == ["sweet dreams sub"]            # the blocked line is never quoted
        assert "coin" not in entry["share"] and "sweet dreams sub" in entry["share"]
        # the template too: taught words counted apart, the quoted line filtered
        entry2 = d.close(dict(e.last_night, date="2026-10-03"), FakeLLM("not json"))
        assert "“sweet dreams sub”" in entry2["text"] and "coin" not in entry2["text"]
        assert "1 of the words viewers taught it" in entry2["text"]


def test_title_kept_when_the_text_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        d, e, _ = run_night(tmp)
        entry = d.close(e.last_night, FakeLLM('{"title": "Loaves in the sea", "text": "SUB-01 is conscious now."}'))
        assert entry["title"] == "Loaves in the sea" and entry["text"].startswith("SUB-01 slept")


def test_a_model_without_ask_gets_the_template(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        d, e, _ = run_night(tmp)
        entry = d.close(e.last_night, object())
        assert entry["text"].startswith("SUB-01 slept")
        assert "no ask()" in capsys.readouterr().out


def test_naps_are_not_diary_nights():
    with tempfile.TemporaryDirectory() as tmp:
        frames = Path(tmp) / "f"
        frames.mkdir()
        d = Diary(tmp, frames)

        class E:
            stage = "REM"
            night = {"date": "2026-10-02-nap-1300", "kind": "nap", "sleep_onset": "2026-10-02T13:00"}
            last_night = {"date": "2026-10-02-nap-1000", "kind": "nap", "sleep_onset": "2026-10-02T10:00",
                          "woke_up": "2026-10-02T10:40", "wakeups": [], "replays": []}
        assert d.due(E, 1e9, now_real=1e9) is False                        # no unattended dream frames in a nap
        assert d.add(E.night["date"], fake_frame(frames, 1), 0, True) is None
        assert d.pending_close(E) is None                                  # a nap is not written up
        E.last_night = {"date": "2026-10-01", "kind": "night", "sleep_onset": "2026-10-02T00:20",
                        "woke_up": "2026-10-02T07:55", "wakeups": [], "replays": []}
        assert d.pending_close(E) == "2026-10-01"
        assert not list(d.dir.glob("*nap*"))


def test_share_text_trimmed_to_280():
    long = "x" * 400
    s = Diary.share("2026-10-01", "A title", {"sleep_onset": "00:10", "woke_up": "08:00", "wakeups": 3,
                                               "replays": 40, "top_replayed": [long]})
    assert len(s) <= 280 and s.endswith("not a mind.")


def test_night_without_frames_still_written():
    with tempfile.TemporaryDirectory() as tmp:
        d = Diary(tmp, tmp)

        class E:
            night = None
            last_night = {"date": "2026-10-01", "sleep_onset": "2026-10-01T00:20", "woke_up": "2026-10-01T08:00",
                          "wakeups": [], "replays": [{"text": "buonanotte"}]}
        assert d.pending_close(E) == "2026-10-01"
        entry = d.close(E.last_night, FakeLLM("{}"))
        assert entry["closed"] and "buonanotte" in entry["text"] and entry["facts"]["dream_frames"] == 0
        assert d.pending_close(E) is None
        E.last_night = dict(E.last_night, date="2026-10-02", sleep_onset=None)      # never slept: no entry
        assert d.pending_close(E) is None


def test_bad_dates_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        d = Diary(tmp, tmp)
        for bad in ("../state", "2026-10-01/../../x", "latest"):
            with pytest.raises(ValueError):
                d.load(bad)
