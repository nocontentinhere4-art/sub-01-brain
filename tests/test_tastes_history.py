"""Issue #30: tastes keep one snapshot per Tokyo day (top topics), capped, and /api/tastes carries it."""
import json

import tastes as T
from tastes import Tastes

DAY = 86400.0
T0 = 1_789_948_800.0 + 16 * 3600   # 01:00 Tokyo


def make(tmp_path, now):
    return Tastes(tmp_path / "tastes.json", clock=lambda: now[0])


def lines(tmp_path):
    p = tmp_path / "tastes_history.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_one_snapshot_per_tokyo_day(tmp_path):
    now = [T0]
    t = make(tmp_path, now)
    t.learn(["net:reward", "kw:bread"], 0.8)
    t.learn(["kw:bread"], 0.5)
    now[0] += 3600
    t.learn(["kw:rain"], -0.6)
    rows = lines(tmp_path)
    assert len(rows) == 1 and rows[0]["day"] == t.day()
    assert rows[0]["top"]["kw:bread"] > 0
    now[0] += DAY
    t.learn(["kw:rain"], -0.6)
    rows = lines(tmp_path)
    assert len(rows) == 2 and rows[1]["day"] != rows[0]["day"]
    assert rows[1]["top"]["kw:rain"] < 0


def test_a_restart_on_the_same_day_does_not_add_a_line(tmp_path):
    now = [T0]
    make(tmp_path, now).learn(["kw:bread"], 0.8)
    make(tmp_path, now).learn(["kw:bread"], 0.8)          # a new process, same Tokyo day
    assert len(lines(tmp_path)) == 1


def test_tokyo_day_not_utc(tmp_path):
    now = [1_790_000_000.0 - (1_790_000_000.0 % DAY) + 14 * 3600 + 60]   # 14:01 UTC = 23:01 Tokyo
    t = make(tmp_path, now)
    t.learn(["kw:a"], 0.5)
    now[0] += 2 * 3600                                    # 16:01 UTC: same UTC day, next Tokyo day
    t.learn(["kw:a"], 0.5)
    assert len(lines(tmp_path)) == 2


def test_snapshot_keeps_top_topics_by_size(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "HISTORY_TOP", 3)
    now = [T0]
    t = make(tmp_path, now)
    t.pref = {"kw:a": 0.9, "kw:b": -0.8, "kw:c": 0.1, "kw:d": 0.5, "net:reward": -0.05}
    t.save()
    top = lines(tmp_path)[0]["top"]
    assert set(top) == {"kw:a", "kw:b", "kw:d"}


def test_history_is_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "HISTORY_DAYS", 5)
    now = [T0]
    t = make(tmp_path, now)
    days = []
    for _ in range(9):
        t.learn(["kw:bread"], 0.7)
        days.append(t.day())
        now[0] += DAY
    rows = lines(tmp_path)
    assert [r["day"] for r in rows] == days[-5:]
    assert not (tmp_path / "tastes_history.jsonl.tmp").exists()


def test_top_carries_history_and_works_empty(tmp_path):
    now = [T0]
    t = make(tmp_path, now)
    out = t.top()
    assert out["favoured"] == [] and out["avoided"] == [] and out["history"] == []
    json.dumps(out)
    t.learn(["net:reward", "kw:bread"], 0.8)
    now[0] += DAY
    t.learn(["kw:rain"], -0.8)
    h = t.top()["history"]
    assert len(h) == 2 and all(x["top"] for x in h)
    assert any(e["topic"] == "reward" and e["kind"] == "network" for e in h[0]["top"])


def test_no_path_no_history():
    t = Tastes(None)
    t.learn(["kw:bread"], 0.8)
    assert t.top()["history"] == []


def test_torn_history_line_is_skipped(tmp_path):
    (tmp_path / "tastes_history.jsonl").write_text('{"day": "2020-01-01", "top": {"kw:a": 0.5}}\n{"day": "2020-01-0')
    now = [T0]
    t = make(tmp_path, now)
    t.learn(["kw:bread"], 0.8)
    h = t.top()["history"]
    assert [x["day"] for x in h] == ["2020-01-01", t.day()]
