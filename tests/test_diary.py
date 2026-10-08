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
