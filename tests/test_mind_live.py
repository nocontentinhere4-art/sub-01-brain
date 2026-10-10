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
    steps = [M.PLAN_ACTIVITIES[s["activity"]][0] for s in live.mind.plan["steps"]]
    scores = live.life.scores(live.clock.now(), {}, 0.0, 0.0)
    feasible = [a for a in steps if scores.get(a, 0.0) > 0]
    assert feasible and live.life.plan_hint == feasible[0]        # P1: the first step he can take now tilts him
    run(live.mind_step())                                         # the morning plan is made once
    assert len([m for m in live.sent if m["type"] == "plan"]) == 1
    hint = live.life.plan_hint
    live.life.start(hint, live.clock.now() + 1, "test")
    run(live.mind_step())
    k = steps.index(hint)
    assert live.mind.plan["steps"][k]["done"]                     # carried out (it was the hint) -> done
    assert all(not s["done"] for i, s in enumerate(live.mind.plan["steps"]) if i != k)
    view = live.mind_view()
    assert view["caption"] == "An AI reads and remembers for him; his brain model chooses."
    assert view["plan"]["steps"][k]["done"] and view["budget"]["part"] == "mind"
    assert "sleep in" not in view["plan"]["text"]


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


def replies(live):
    return [m for m in live.sent if m["type"] == "chat_reply"]


def missed(live):
    return [m for m in live.sent if m["type"] == "chat_missed"]


def test_chat_is_answered_in_order_one_viewer_at_a_time_and_tagged(tmp_path):
    """C1: FIFO round-robin inbox, peek-not-pop, a visible outcome for every message; C4: real context."""
    live = make_live(tmp_path, "I read about sourdough today; wild yeast does the work.", "The park was quiet.",
                     "Rye bread next, the notes say.", "I am a real person", "Yes.")
    live.mind.plan = {"day": "x"}
    live.mind.due_slot = lambda now=None: None
    t = live.clock.now()
    ws = WS()
    run(live.handle_chat(ws, "1.2.3.4", "what did you read today?", "mika"))
    ack = ws.sent[-1]
    assert ack["ok"] and ack["queued"] and ack["will_reply"] and ack["reason"] is None
    assert live.chat_inbox[-1]["text"] == "what did you read today?" and live.chat_inbox[-1]["nick"] == "mika"
    assert run(live.enqueue_chat(t + 1, "and the bakery?", "1.2.3.4", "mika")) is None     # the same viewer again
    assert run(live.enqueue_chat(t + 2, "how was the park?", "5.6.7.8", "")) is None
    live.life.activity, live.life.path = "window", []
    run(live.mind_step())
    assert live.life.chat_waiting == 3 and not replies(live)     # not at the desk: they wait
    live.life.activity = "chat"
    run(live.mind_step())
    r = replies(live)
    assert len(r) == 1 and r[0]["tag"] == "his reply (AI-written)" and r[0]["source"] == "ai" and r[0]["to"] == "mika"
    assert r[0]["text"].startswith("I read about sourdough") and r[0]["replying_to"] == "what did you read today?"
    assert len(live.chat_inbox) == 2 and live.mind_view()["replies"][-1]["text"] == r[0]["text"]
    user = json.loads(live.mind.provider.calls[0][1])
    assert user["viewer"] == "mika" and user["doing"].startswith("answering chat at the computer")   # C4
    run(live.mind_step())                                         # 2 min between replies: nothing yet
    assert len(replies(live)) == 1 and live.life.chat_waiting == 0   # C2: no reply possible now -> not "waiting"
    live.mind.replies["last"] = 0.0
    run(live.mind_step())
    assert [m["replying_to"] for m in replies(live)] == ["what did you read today?", "how was the park?"]   # round-robin
    live.mind.replies["last"] = 0.0
    run(live.mind_step())
    assert [m["replying_to"] for m in replies(live)][-1] == "and the bakery?" and not live.chat_inbox
    assert json.loads(live.mind.provider.calls[2][1])["turns"][-1]["said"] == "what did you read today?"
    # a rejected model line: a fallback line is posted, never silence
    live.mind.replies["last"] = 0.0
    run(live.enqueue_chat(t + 3, "tell me something", "9.9.9.9", ""))
    run(live.mind_step())
    last = replies(live)[-1]
    assert last["source"] == "fallback" and "real person" not in last["text"] and M.reply_problem(last["text"]) is None
    # reply() raising: the message stays (peek, not pop); the second failure is a visible miss
    live.mind.replies["last"] = 0.0
    run(live.enqueue_chat(t + 4, "still there?", "9.9.9.9", ""))

    def boom(*a, **k):
        raise RuntimeError("down")
    live.mind.reply = boom
    run(live.mind_step())
    assert len(live.chat_inbox) == 1 and live.chat_inbox[0]["tries"] == 1 and not missed(live)
    run(live.mind_step())
    assert not live.chat_inbox and missed(live)[-1]["replying_to"] == "still there?" and "AI" in missed(live)[-1]["why"]
    # a message that waited too long away from the desk is let go with a note
    live.life.activity = "window"
    run(live.enqueue_chat(t - live_server.CHAT_WAIT_S - 1, "old one", "7.7.7.7", ""))
    run(live.mind_step())
    assert not live.chat_inbox and missed(live)[-1]["why"].startswith("he missed that one")


def test_over_the_cap_the_rules_still_answer_and_the_inbox_says_so(tmp_path):
    """C2: no AI reply over the cap (he does not sit down for it), the identity rule still answers; at 40 replies the
    inbox is cleared with one in-world line. L4: a vote never cuts a chess game; it applies when the game ends."""
    live = make_live(tmp_path, "hello")
    live.mind.plan = {"day": "x"}
    live.mind.due_slot = lambda now=None: None
    M.shared_budget(tmp_path).record("claude", "claude-haiku-4-5", 0, 0, True, usd=2.0)   # the day's total spent
    ws = WS()
    run(live.handle_chat(ws, "1.2.3.4", "are you a real person?"))
    assert ws.sent[-1]["queued"] and not ws.sent[-1]["will_reply"] and ws.sent[-1]["reason"].startswith("resting")
    live.life.activity, live.life.path = "chat", []
    run(live.mind_step())
    assert live.life.chat_waiting == 0 and live.mind_view()["status"]["resting"] and live.mind.provider.calls == []
    r = replies(live)
    assert len(r) == 1 and r[0]["source"] == "rule" and r[0]["text"] in M.HONEST_LINES   # C3: the rule, even over the cap
    assert live.mind.reply("hello there", None, {"awake": True, "at_desk": True})["why"].startswith("resting")
    run(live.handle_chat(WS(), "5.6.7.8", "what did you read today?"))
    run(live.mind_step())
    assert len(live.chat_inbox) == 1 and live.life.chat_waiting == 0 and len(replies(live)) == 1   # it waits, no drain
    live.mind.replies["n"] = M.REPLIES_PER_DAY                    # the day's cap: one in-world line, the inbox cleared
    run(live.mind_step())
    assert not live.chat_inbox and replies(live)[-1]["text"] == live_server.CAP_LINE
    assert replies(live)[-1]["source"] == "note" and missed(live)[-1]["why"].startswith("he has answered")
    run(live.mind_step())
    assert [m for m in replies(live) if m["text"] == live_server.CAP_LINE].__len__() == 1    # once a day
    # L4: the vote result waits while he plays chess
    t = live.clock.now()
    live.life.activity = "play_chess"
    live.votes.pending = {"act": "window", "label": "look out of the window", "round": 1, "votes": 1, "total": 1, "at": t}
    msg = {"type": "tick"}
    run(live.audience_tick(msg, t, {}, 0))
    assert live.votes.pending and live.life.nudge(t) is None and msg["aud"]["held"] == "after the game"
    assert live.life.activity == "play_chess"
    g = SimpleNamespace(public=lambda: {"over": True}, record=lambda t: {"result": "1-0"})
    live.chess = g
    run(live.finish_chess(g, t))
    assert live.votes.pending is None and live.life.nudge(t) == "window"
    assert [m for m in live.sent if m["type"] == "vote_applied"][-1]["act"] == "window"


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
