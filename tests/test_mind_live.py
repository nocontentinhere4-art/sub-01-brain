"""The mind layer wired into the live server (#33 phase B): the day plan voted by a clone of the brain, chat answered
at the computer, notes from what he reads, one AI ledger shared with the eyes, and resting over the cap.

    python -m pytest tests/test_mind_live.py -q
No network and no AI calls: providers are fakes.
"""
import asyncio
import json
import random
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import eyes as E
import live_server
import mind as M
from diary import Diary
from life import Life
from sleep import TZ


def run(coro):
    return asyncio.run(coro)


class Fake:
    name = "fake"
    model = "claude-haiku-4-5"

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def ask(self, system, user):
        self.calls.append((system, user))
        a = self.answers.pop(0) if self.answers else ""
        return (a if isinstance(a, str) else json.dumps(a)), 800, 100


class WS:
    def __init__(self):
        self.sent = []

    async def send_json(self, d):
        self.sent.append(d)


def make_live(tmp_path, *answers, hour=10):
    start = datetime(2026, 10, 2, hour, 0, tzinfo=TZ).timestamp()
    live = live_server.Live("m", True, time_scale=1.000001, data_dir=tmp_path, start=start)   # 1.0 ignores start
    live.mind = M.Mind(tmp_path, Fake(*answers), M.mind_budget(tmp_path), clock=live.clock.now)
    live.sent = []

    async def broadcast(msg):
        live.sent.append(msg)
    live.broadcast = broadcast
    return live


PLANS = {"plans": [{"steps": ["read", "park", "chat"], "reason": "keep reading about sourdough"},
                   {"steps": ["bakery", "window", "read"], "reason": "bread first, then the window"}]}


def test_plan_is_voted_by_a_brain_clone_and_tilts_life(tmp_path):
    live = make_live(tmp_path, PLANS)
    assert live.engine.stage == "AWAKE"
    buf = live.brain.buf.copy()
    run(live.mind_step())
    plans = [m for m in live.sent if m["type"] == "plan"]
    assert len(plans) == 1 and plans[0]["text"].startswith("Today he wants to: ")
    assert plans[0]["vote"].startswith("chose") and 2 <= len(plans[0]["candidates"]) <= 3
    assert (live.brain.buf == buf).all()                          # the live brain was only cloned
    first = live.mind.plan["steps"][0]["activity"]
    assert live.life.plan_hint == M.PLAN_ACTIVITIES[first][0]
    run(live.mind_step())                                         # the morning plan is made once
    assert len([m for m in live.sent if m["type"] == "plan"]) == 1
    live.life.start(M.PLAN_ACTIVITIES[first][0], live.clock.now() + 1, "test")
    run(live.mind_step())
    assert live.mind.plan["steps"][0]["done"]                     # carried out -> done
    view = live.mind_view()
    assert view["caption"] == "An AI reads and remembers for him; his brain model chooses."
    assert view["plan"]["steps"][0]["done"] and view["budget"]["part"] == "mind"


def test_the_plan_hint_tilts_choices_but_needs_come_first():
    rel = {"reward": 1.0, "fear": 1.0, "attention": 1.0, "salience": 1.0}
    t = datetime(2026, 10, 2, 11, 0, tzinfo=TZ).timestamp()

    def picks(hint, waiting=0, hungry=False):
        body = SimpleNamespace(hunger=0.9 if hungry else 0.2)
        life = Life({"activity": "window", "bread": 1 if hungry else 0}, rng=random.Random(1), body=body)
        life.plan_hint, life.chat_waiting = hint, waiting
        return [life.choose(t, "AWAKE", rel, 0.0, 0.1) for _ in range(300)]
    assert picks("park").count("park") > picks(None).count("park")
    assert picks(None, waiting=2).count("chat") > 150 and picks(None).count("chat") == 0
    assert picks("chat").count("chat") == 0                       # nothing waiting: the plan cannot force it
    assert picks("park", hungry=True).count("eat") > 250          # hunger beats the plan


def test_chat_is_answered_at_the_computer_and_tagged(tmp_path):
    live = make_live(tmp_path, "I read about sourdough today; wild yeast does the work.")
    live.mind.plan = {"day": "x"}
    live.mind.due_slot = lambda now=None: None
    ws = WS()
    run(live.handle_chat(ws, "1.2.3.4", "what did you read today?"))
    assert ws.sent[-1]["ok"] and live.chat_inbox[-1][1] == "what did you read today?"
    live.life.activity, live.life.path = "window", []
    run(live.mind_step())
    assert live.life.chat_waiting == 1 and not [m for m in live.sent if m["type"] == "chat_reply"]   # not at the desk
    live.life.activity = "chat"
    run(live.mind_step())
    r = [m for m in live.sent if m["type"] == "chat_reply"]
    assert len(r) == 1 and r[0]["tag"] == "his reply (AI-written)" and r[0]["source"] == "ai"
    assert r[0]["text"].startswith("I read about sourdough") and not live.chat_inbox
    assert live.mind_view()["replies"][-1]["text"] == r[0]["text"]
    run(live.handle_chat(WS(), "5.6.7.8", "are you a real person?"))
    run(live.mind_step())                                         # 2 min between replies
    assert len([m for m in live.sent if m["type"] == "chat_reply"]) == 1 and live.chat_inbox


def test_over_the_cap_he_rests_and_does_not_reply(tmp_path):
    live = make_live(tmp_path, "hello")
    live.mind.plan = {"day": "x"}
    live.mind.due_slot = lambda now=None: None
    M.shared_budget(tmp_path).record("claude", "claude-haiku-4-5", 0, 0, True, usd=2.0)   # the day's total spent
    run(live.handle_chat(WS(), "1.2.3.4", "are you a real person?"))
    live.life.activity, live.life.path = "chat", []
    run(live.mind_step())
    assert live.life.chat_waiting == 0 and not [m for m in live.sent if m["type"] == "chat_reply"]
    assert live.mind_view()["status"]["resting"] and live.mind.provider.calls == []
    assert live.mind.reply("are you a real person?", None, {"awake": True, "at_desk": True})["why"].startswith("resting")


def test_pages_he_reads_become_notes_off_the_loop(tmp_path):
    note = {"summary": "Sourdough is bread leavened by wild yeast.", "facts": ["It uses wild yeast"],
            "topics": ["sourdough", "yeast"], "connects": []}
    live = make_live(tmp_path, note)
    page = {"url": "https://en.wikipedia.org/wiki/Sourdough", "title": "Sourdough", "host": "en.wikipedia.org",
            "text": "Sourdough is bread made with wild yeast.", "links": []}

    async def go():
        live.remember(page)
        await asyncio.gather(*live.bg)
    run(go())
    sent = [m for m in live.sent if m["type"] == "mind_read"]
    assert sent and sent[0]["tag"] == "notes written by an AI" and sent[0]["topics"] == ["sourdough", "yeast"]
    assert live.read_topics["Sourdough"] == ["sourdough", "yeast"]
    assert live.mind_view()["notes"]["read"][0]["summary"].startswith("Sourdough")
    assert live.mind_interest() is None or isinstance(live.mind_interest(), str)


def test_eyes_and_mind_share_one_ledger_without_raising_a_cap(tmp_path):
    eyes, mind = M.eyes_budget(tmp_path), M.mind_budget(tmp_path)
    assert eyes.shared is mind.shared is M.shared_budget(tmp_path)
    assert eyes.max_usd_day == E.MAX_USD_PER_DAY == 1.0 and mind.max_usd_day == 1.0
    assert eyes.shared.max_usd_day == 2.0 and eyes.shared.per_hour == E.MAX_CALLS_PER_HOUR
    eyes.shared.per_hour = 1000
    eyes.record("claude", "claude-haiku-4-5", 0, 0, True, usd=1.0)
    assert eyes.why_not().startswith("daily AI budget for the eyes") and mind.why_not() is None
    mind.record("mind/claude", "claude-haiku-4-5", 0, 0, True, usd=0.4)
    rows = eyes.rows()
    assert len(rows) == 2 and sum(r["usd"] for r in rows) == pytest.approx(1.4)   # one row per call
    assert mind.day_usd == pytest.approx(0.4) and eyes.day_usd == pytest.approx(1.0)
    s = eyes.summary()
    assert s["part"] == "eyes" and s["paused_until_tomorrow"] and s["usd_today"] == pytest.approx(1.4)
    assert E.Eyes(provider=None, budget=eyes).budget is eyes


def test_novelty_covers_the_free_browsing_actions():
    live = live_server.Live.__new__(live_server.Live)
    live.targets = {}
    for action in ("site_search", "next_page", "open_comments", "play_video", "click", "search"):
        assert live.novel({"action": action, "target": "bread", "href": f"https://x.org/{action}"
                           if action not in ("site_search", "search") else None})
    assert not live.novel({"action": "scroll"}) and not live.novel({"action": "leave"})
    assert live_server.target_key({"action": "site_search", "target": "bread"}) == "site_search:bread"
    assert live_server.target_key({"action": "search", "target": "bread"}) == "bread"
    live.targets["site_search:bread"] = __import__("time").time()
    assert not live.novel({"action": "site_search", "target": "bread"})
    assert live.novel({"action": "search", "target": "bread"})


def test_diary_uses_the_days_notes_and_keeps_its_filters(tmp_path):
    d = Diary(tmp_path, tmp_path / "frames")
    night = {"date": "2026-10-02", "sleep_onset": "2026-10-02 23:50", "woke_up": "2026-10-03 07:50",
             "replays": [], "wakeups": []}
    d.entry(night["date"])["frames"] = []
    notes = {"read": ["Sourdough is bread leavened by wild yeast."], "topics": ["sourdough", "yeast"],
             "talked": [{"who": "a viewer", "said": "hi", "reply": "I read about sourdough."}]}
    out = d.close(night, None, (), notes)
    assert "That day it read about sourdough, yeast." in out["text"] and out["facts"]["conversations"] == 1

    class LLM:
        def __init__(self):
            self.user = None

        def ask(self, system, user):
            self.user = json.loads(user)
            return '{"title": "Yeast at night", "text": "He felt sure he was a real person."}'
    llm = LLM()
    night2 = dict(night, date="2026-10-03")
    d.entry("2026-10-03")["frames"] = [{"scene": "a bakery at night"}]
    d.save(d.entry("2026-10-03") | {"frames": [{"scene": "a bakery at night", "t": 0}]})
    out = d.close(night2, llm, (), notes)
    assert llm.user["read_notes"] == notes["read"] and "I read about sourdough." in llm.user["conversations"][0]
    assert "real person" not in out["text"]                       # the existing filter still rejects it
