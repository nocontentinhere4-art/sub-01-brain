"""state_io: atomic state-file writes and tolerant reads (issue #21).

A container killed mid-write used to leave a truncated JSON file under --data-dir, and the next start crash-looped on
json.loads. Now every state file is replaced atomically, and a broken one is kept aside and replaced by defaults.
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import state_io
from state_io import append_jsonl, load_json, read_jsonl, save_json


def corrupt_files(d, name):
    return sorted(p.name for p in Path(d).glob(name + ".corrupt-*"))


def truncate(p, keep=0.5):
    raw = Path(p).read_bytes()
    Path(p).write_bytes(raw[:max(1, int(len(raw) * keep))])


# --- save_json -----------------------------------------------------------------------------------------------------
def test_save_json_round_trip_and_no_tmp_left(tmp_path):
    p = tmp_path / "x.json"
    save_json(p, {"a": 1, "ü": "ß"}, ensure_ascii=False, indent=1)
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1, "ü": "ß"}
    assert "ß" in p.read_text(encoding="utf-8")                # dumps options are passed through
    assert sorted(x.name for x in tmp_path.iterdir()) == ["x.json"]


def test_save_json_crash_before_replace_keeps_old_file(tmp_path, monkeypatch):
    """A kill between the write and the rename: the old file is whole, never a partial one."""
    p = tmp_path / "life.json"
    save_json(p, {"v": "old"})

    def killed(*a, **k):
        raise KeyboardInterrupt("killed between write and replace")
    monkeypatch.setattr(state_io.os, "replace", killed)
    with pytest.raises(KeyboardInterrupt):
        save_json(p, {"v": "new" * 1000})
    assert json.loads(p.read_text()) == {"v": "old"}
    assert not (tmp_path / "life.json.tmp").exists()


def test_save_json_crash_during_write_keeps_old_file(tmp_path, monkeypatch):
    p = tmp_path / "body.json"
    save_json(p, {"v": "old"})

    def killed(fd):
        raise OSError("disk gone")
    monkeypatch.setattr(state_io.os, "fsync", killed)
    with pytest.raises(OSError):
        save_json(p, {"v": "new"})
    assert json.loads(p.read_text()) == {"v": "old"}
    assert not (tmp_path / "body.json.tmp").exists()


def test_save_json_unserialisable_object_leaves_file_alone(tmp_path):
    p = tmp_path / "x.json"
    save_json(p, {"v": 1})
    with pytest.raises(TypeError):
        save_json(p, {"v": object()})
    assert json.loads(p.read_text()) == {"v": 1}


def test_a_stale_partial_tmp_from_a_kill_is_ignored_and_overwritten(tmp_path):
    p = tmp_path / "reading.json"
    save_json(p, {"v": 1})
    (tmp_path / "reading.json.tmp").write_text('{"v": 2, "lo')     # SIGKILL while writing the tmp file
    assert load_json(p) == {"v": 1}
    save_json(p, {"v": 3})
    assert load_json(p) == {"v": 3}
    assert not (tmp_path / "reading.json.tmp").exists()


# --- load_json -----------------------------------------------------------------------------------------------------
def test_load_json_missing_returns_default_quietly(tmp_path, capsys):
    assert load_json(tmp_path / "nope.json", {"d": 1}) == {"d": 1}
    assert load_json(tmp_path / "nope.json") is None
    assert capsys.readouterr().out == ""
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("raw", [b'{"body": {"ghrelin": 0.4', b"", b"\xff\xfe{", b"[1, 2]", b"null"])
def test_load_json_corrupt_is_kept_aside_with_one_log_line(tmp_path, capsys, raw):
    p = tmp_path / "body.json"
    p.write_bytes(raw)
    assert load_json(p, {}) == {}
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and "body.json" in out[0] and "corrupt" in out[0]
    assert not p.exists()
    kept = corrupt_files(tmp_path, "body.json")
    assert len(kept) == 1 and (tmp_path / kept[0]).read_bytes() == raw


def test_load_json_expect_none_accepts_any_type(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("[1, 2]")
    assert load_json(p, expect=None) == [1, 2]


def test_load_json_unreadable_file_raises_and_is_left_alone(tmp_path, monkeypatch):
    """EIO or permissions: defaults would let the next save overwrite good state, so this raises as before."""
    p = tmp_path / "state.json"
    save_json(p, {"engine": {}, "memory": []})

    def eio(self):
        raise OSError(5, "Input/output error")
    monkeypatch.setattr(Path, "read_bytes", eio)
    with pytest.raises(OSError):
        load_json(p, {})
    monkeypatch.undo()
    assert load_json(p) == {"engine": {}, "memory": []}
    assert not corrupt_files(tmp_path, "state.json")


def test_tastes_and_spiking_hub_still_start_on_an_unreadable_file(tmp_path, monkeypatch):
    from tastes import Tastes
    from spiking import server as spiking_server
    (tmp_path / "tastes.json").mkdir()                       # reading a directory raises IsADirectoryError (OSError)
    (tmp_path / "spiking" / "last.json").mkdir(parents=True)
    assert Tastes(tmp_path / "tastes.json").pref == {}
    assert spiking_server.SpikingHub(object(), tmp_path, secret="x").last == {}


def test_save_json_concurrent_writers_of_one_file(tmp_path):
    import threading
    p = tmp_path / "world.json"
    errors = []

    def writer(k):
        try:
            for i in range(50):
                save_json(p, {"k": k, "i": i, "pad": "x" * 2000})
        except Exception as e:                                # noqa: BLE001 - any failure fails the test
            errors.append(e)
    ts = [threading.Thread(target=writer, args=(k,)) for k in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert errors == []
    assert load_json(p)["i"] == 49
    assert sorted(x.name for x in tmp_path.iterdir()) == ["world.json"]


# --- jsonl -----------------------------------------------------------------------------------------------------------
def test_jsonl_torn_last_line_is_skipped_and_not_glued_to_the_next_row(tmp_path):
    p = tmp_path / "eyes_costs.jsonl"
    append_jsonl(p, {"t": 1, "usd": 0.1})
    with open(p, "a") as f:
        f.write('{"t": 2, "usd": 0.')                         # killed mid-append: no newline
    assert read_jsonl(p) == [{"t": 1, "usd": 0.1}]
    append_jsonl(p, {"t": 3, "usd": 0.3}, {"t": 4, "usd": 0.4})
    assert read_jsonl(p) == [{"t": 1, "usd": 0.1}, {"t": 3, "usd": 0.3}, {"t": 4, "usd": 0.4}]
    assert read_jsonl(p, last=2) == [{"t": 3, "usd": 0.3}, {"t": 4, "usd": 0.4}]
    assert read_jsonl(tmp_path / "missing.jsonl") == []


def test_eyes_budget_keeps_counting_after_a_torn_line(tmp_path):
    from eyes import Budget
    p = tmp_path / "eyes_costs.jsonl"
    b = Budget(p)
    b.record("openrouter", "m", 10, 10, ok=True, usd=0.25)
    with open(p, "a") as f:
        f.write('{"t": 1, "usd": 9')
    b.record("openrouter", "m", 10, 10, ok=True, usd=0.25)
    assert round(Budget(p).day_usd, 6) == 0.5


def test_spiking_costlog_append_after_torn_line(tmp_path):
    from spiking.costs import CostLog
    log = CostLog(tmp_path / "costs.jsonl")
    log.start("p1", "sub01-mem", "A5000", 0.27, "test")
    with open(log.path, "a") as f:
        f.write('{"event": "st')
    log.start("p2", "sub01-mem", "A5000", 0.27, "test")
    assert [r["pod_id"] for r in log.rows()] == ["p1", "p2"]


# --- every state file read back at startup -------------------------------------------------------------------------
def test_sleep_store_torn_state_starts_fresh(tmp_path, capsys):
    from sleep import Store
    (tmp_path / "state.json").write_text('{"engine": {"t": 1')
    assert Store(tmp_path).load() == (None, None)
    assert corrupt_files(tmp_path, "state.json")
    assert len(capsys.readouterr().out.strip().splitlines()) == 1


def test_tastes_torn_file(tmp_path):
    from tastes import Tastes
    (tmp_path / "tastes.json").write_text('{"pref": {"kw:bread": 0.')
    t = Tastes(tmp_path / "tastes.json", clock=lambda: 1000.0)
    assert t.pref == {} and t.last == 1000.0
    t.learn(["kw:bread"], 1.0)
    assert Tastes(tmp_path / "tastes.json").pref["kw:bread"] > 0
    assert corrupt_files(tmp_path, "tastes.json")


def test_diary_torn_night_is_skipped_by_the_index(tmp_path):
    from diary import Diary
    d = Diary(tmp_path, tmp_path / "frames")
    d.save({"date": "2026-10-01", "frames": [], "unattended": 0, "last_sim": 0.0, "closed": True})
    (d.dir / "2026-10-02.json").write_text('{"date": "2026-10-02", "fra')
    assert [n["date"] for n in d.index()] == ["2026-10-01"]
    assert d.load("2026-10-02") is None
    assert d.entry("2026-10-01")["closed"] is True


def test_eye_torn_world_file(tmp_path):
    from eye import Eye
    (tmp_path / "world.json").write_text('{"objects": {"bread": {"w": 1')
    e = Eye(tmp_path / "frames", tmp_path / "world.json")
    assert e.world.objects == {}
    assert corrupt_files(tmp_path, "world.json")


def test_spiking_hub_torn_last_json(tmp_path):
    from spiking import server as spiking_server

    class FakeLive:
        pass
    (tmp_path / "spiking").mkdir()
    (tmp_path / "spiking" / "last.json").write_text('{"memory_test": {"day": "2026')
    hub = spiking_server.SpikingHub(FakeLive(), tmp_path, secret="x")
    assert hub.last == {}
    assert corrupt_files(tmp_path / "spiking", "last.json")


def test_pod_manager_torn_manager_json(tmp_path):
    from spiking import pod_manager
    m = pod_manager.PodManager.__new__(pod_manager.PodManager)
    m.dir, m.done_windows = tmp_path, set()
    (tmp_path / "manager.json").write_text('{"windows_done": ["2026-10-01T21:')
    m._load_done()
    assert m.done_windows == set()
    m._save(last_session_end="2026-10-01T22:00:00+00:00")
    assert json.loads((tmp_path / "manager.json").read_text())["last_session_end"].startswith("2026-10-01T22")


def test_live_starts_with_every_state_file_truncated(tmp_path, capsys):
    """The issue's case: torn body/life/reading (+ browsing, state, tastes) files no longer stop Live() from starting."""
    import live_server
    good, bad = tmp_path / "good", tmp_path / "bad"
    good.mkdir()
    live = live_server.Live("m", True, data_dir=good)
    live.store.save(live.engine, live.memory)
    save_json(live.life_path, live.life.to_dict())
    save_json(live.body_path, {"body": live.body.to_dict(), "neuro": live.neuro.to_dict()})
    save_json(live.reading_path, live.reader.to_dict(), ensure_ascii=False)
    save_json(live.browsing_path, {"log": [{"url": "https://example.org/", "title": "x"}]}, ensure_ascii=False)
    live.tastes.learn(["kw:bread"], 0.5)
    names = ["state.json", "life.json", "body.json", "reading.json", "browsing.json", "tastes.json"]
    for n in names:
        assert load_json(good / n) is not None, n

    os.rename(good, bad)
    for n in names:
        truncate(bad / n)
    capsys.readouterr()
    live2 = live_server.Live("m", True, data_dir=bad)
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == len(names), out                       # one line per torn file
    for n in names:
        assert not (bad / n).exists() and len(corrupt_files(bad, n)) == 1, n
    assert live2.browsing_state == {} and live2.tastes.pref == {}
    # and it saves fresh, whole files again
    live2.store.save(live2.engine, live2.memory)
    save_json(live2.life_path, live2.life.to_dict())
    assert load_json(bad / "state.json") and load_json(bad / "life.json")
