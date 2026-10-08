"""Tastes: what kinds of pages have paid off before, learned from the brain model's own response.

A per-topic preference table. A page's topics are the networks of the option that led to it ("net:reward") and up to
5 keywords of its label and title ("kw:bread"). While he stays on a page the live server measures how strongly the
brain responded (value of reward / attention / fear activity relative to his recent average, squashed to -1..1); when
he leaves, the prediction error  delta = response - predict(topics)  moves each topic's preference by alpha * delta
(a reward-prediction-error rule). Preferences decay toward 0 with time constant TAU_DAYS, so unvisited tastes fade.

The first PageWatch.SKIP_S (10 s) of a stay are not counted: the chosen option's own stimulus (2 s decay) is gone by
then, so a choice does not confirm itself (checked: same response with and without it, within 0.003). The model has
no other input from the page, so the stay response also carries whatever else drives the brain meanwhile (chat,
trades, readings, its own slow activity): tastes are a slow, noisy average, not a judgement of the page.

Learning rate (issue #36): a Kalman gain per topic, with an uncertainty `var` per topic. The model behind it is the
one the rule already had: a stay's response is the mean of its topics' values plus noise of variance NOISE_VAR, and
each value drifts back toward 0 with time constant TAU_DAYS (the decay; an Ornstein-Uhlenbeck process whose spread is
PRIOR_VAR). Between stays a value's mean decays by k = exp(-dt / TAU) and its variance moves toward PRIOR_VAR
(var = k^2 var + (1 - k^2) PRIOR_VAR). A stay with m topics has predicted variance S = sum(var) / m^2 + NOISE_VAR, and
each topic moves by gain_t * delta with gain_t = var_t / (m S), then var_t *= 1 - var_t / (m^2 S).
Why not alpha = 1 / (1 + n_seen): that is the Kalman gain of one topic seen alone. A stay carries ~6 topics: with a
count, each new topic on a stay takes the whole error (the prediction overshoots), and the gain falls as 1/n although
one stay tells only ~1/m about each of its topics; in the simulated stream (tests/test_tastes_faster.py) it ranked
the top 5 worse than the old fixed rate. The Kalman gain shares the error by uncertainty and hands it
mostly to the uncertain topics (new, or not seen for days), and a topic seen many times barely moves on one noisy
stay. Old state files have no variances: their topics start at LEGACY_VAR, where a stay on that topic alone has
gain ALPHA (0.2), the old fixed rate.

Overnight replay (issue #36): each stay is also appended to a bounded log of today's stays (topics, response,
prediction error), saved in the same state file. At sleep onset (live_server.sleep_tick, "sleep" event) replay() takes
the REPLAY_N logged stays whose prediction error is largest *now* and applies them again through the same rule at
REPLAY_RATE x their gain, without counting them as new stays, then clears the log: a model of prioritised offline
consolidation, REPLAY_N dictionary updates and one file write per night.

The interface is three methods, kept small so the spiking brain (feature/spiking-brain) can replace the table with
dopamine-modulated synapses later:  topics(option, title) -> [str],  predict(topics) -> float in [-1, 1],
learn(topics, response) -> delta. Nothing here is enjoyment: it is a running average of simulated activity.

History (for /tastes.html): on the first save of each Tokyo day the top HISTORY_TOP topics (by |preference|) are
appended as one line to `tastes_history.jsonl` next to the state file; the file keeps the last HISTORY_DAYS lines.
top() returns the last HISTORY_SHOWN of them as "history", so /api/tastes carries it with no server change.
"""
import datetime as dt
import json
import math
import os
import time
from pathlib import Path

from research import keywords
from sleep import TZ
from state_io import append_jsonl, load_json, read_jsonl, save_json

ALPHA = 0.2                   # the old fixed rate; legacy topics start where a lone stay has this gain
PRIOR_VAR = 0.25              # spread of a topic's value before any stay (sd 0.5 on the -1..1 scale)
NOISE_VAR = 0.1               # variance of one stay's response around the mean of its topics' values
LEGACY_VAR = NOISE_VAR * ALPHA / (1 - ALPHA)
MIN_VAR = 1e-4
DAY_LOG_CAP = 200             # today's stays kept for the night's replay
REPLAY_N = 60                 # stays replayed per sleep onset
REPLAY_RATE = 0.5             # replay step, as a fraction of the stay's gain
REPLAY_MAX_AGE_S = 36 * 3600  # older logged stays are dropped, not replayed
TAU_DAYS = 7.0
CAP = 400                     # topics kept (the weakest are dropped)
MIN_ABS = 0.01
HISTORY_TOP = 20              # topics per daily snapshot
HISTORY_DAYS = 120            # snapshots kept in tastes_history.jsonl
HISTORY_SHOWN = 30            # snapshots returned by top()


class Tastes:
    def __init__(self, path=None, clock=time.time):
        self.path = Path(path) if path else None
        self.clock = clock
        self.pref, self.seen, self.last = {}, {}, clock()
        try:
            d = load_json(self.path, {}) if self.path else {}
        except OSError:                                   # unreadable: start empty, as before
            d = {}
        self.pref, self.seen, self.last = d.get("pref", {}), d.get("seen", {}), d.get("last", self.last)
        var = d.get("var") if isinstance(d.get("var"), dict) else {}
        self.var = {t: float(var.get(t, LEGACY_VAR)) for t in set(self.pref) | set(self.seen)}   # old files: none
        self.day_log = [x for x in d.get("day_log", []) if isinstance(x, dict) and isinstance(x.get("topics"), list)
                        and x["topics"] and isinstance(x.get("response"), (int, float))]
        self.last_replay = d.get("last_replay")
        self.history_path = self.path.with_name("tastes_history.jsonl") if self.path else None
        self._hist_day, self._hist_cache = None, (None, [])

    # --- the interface ---------------------------------------------------------------------------------------------
    @staticmethod
    def topics(option, title=""):
        nets = sorted(option.get("networks", {}).items(), key=lambda kv: -kv[1])
        out = [f"net:{g}" for g, w in nets if w >= 0.2][:3]
        out += [f"kw:{w}" for w in keywords(option.get("label", ""), title or "", n=5)]
        return out

    def predict(self, topics):
        vals = [self.pref[t] for t in topics if t in self.pref]
        return sum(vals) / len(vals) if vals else 0.0

    def alpha(self, topic):
        """Gain of a stay with this topic alone (for reading; learn() uses the gain of the whole stay)."""
        v = self.var.get(topic, PRIOR_VAR)
        return v / (v + NOISE_VAR)

    def learn(self, topics, response):
        """Reward-prediction-error update; `response` in [-1, 1]. Returns the prediction error."""
        if not topics:
            return 0.0
        response = float(response)
        if not math.isfinite(response):                       # a broken measurement teaches nothing
            return 0.0
        self.decay()
        response = max(-1.0, min(1.0, response))
        delta = self._update(list(topics), response, 1.0, count=True)
        self.day_log.append({"topics": list(topics), "response": round(response, 4), "delta": round(delta, 4),
                             "t": round(self.clock())})
        del self.day_log[:-DAY_LOG_CAP]
        self._cap()
        self.save()
        return delta

    def gains(self, topics):
        """-> ({topic: gain}, {topic: var after the stay}) for one stay on `topics` (see the docstring)."""
        m = len(topics)
        var = {t: self.var.get(t, PRIOR_VAR) for t in topics}
        s = sum(var.values()) / m ** 2 + NOISE_VAR
        return ({t: v / (m * s) for t, v in var.items()},
                {t: max(MIN_VAR, v * (1.0 - v / (m * m * s))) for t, v in var.items()})

    def _update(self, topics, response, rate, count):
        delta = response - self.predict(topics)
        now = self.clock()
        gain, post = self.gains(topics)
        for t in topics:
            self.pref[t] = max(-1.0, min(1.0, self.pref.get(t, 0.0) + rate * gain[t] * delta))
            if count:
                self.var[t] = post[t]
                self.seen[t] = now
            else:                                         # a replay is not new evidence: the uncertainty stays
                self.var.setdefault(t, PRIOR_VAR)
                self.seen.setdefault(t, now)
        return delta

    def replay(self, n=None, rate=None):
        """Sleep onset: re-apply the logged stays with the largest current |prediction error| at rate x gain, then
        clear the log. Returns {"t", "stays", "replayed", "error_before", "error_after"} (mean |error| of the log)."""
        n = REPLAY_N if n is None else n
        rate = REPLAY_RATE if rate is None else rate
        self.decay()
        now = self.clock()
        log = [x for x in self.day_log if now - x.get("t", now) <= REPLAY_MAX_AGE_S]
        if not log:
            self.day_log = []
            return None
        err = lambda x: abs(x["response"] - self.predict(x["topics"]))
        before = sum(map(err, log)) / len(log)
        for x in sorted(log, key=err, reverse=True)[:n]:
            self._update(x["topics"], x["response"], rate, count=False)
        after = sum(map(err, log)) / len(log)
        self.day_log = []
        self._cap()
        self.last_replay = {"t": round(now), "stays": len(log), "replayed": min(n, len(log)),
                            "error_before": round(before, 4), "error_after": round(after, 4)}
        try:
            self.save()
        except OSError as e:                              # called from the sleep tick: never break it
            print(f"tastes: replay not saved ({e})", flush=True)
        return self.last_replay

    def _cap(self):
        if len(self.pref) > CAP:
            for t in sorted(self.pref, key=lambda k: abs(self.pref[k]))[:len(self.pref) - CAP]:
                self.pref.pop(t, None)
                self.seen.pop(t, None)
                self.var.pop(t, None)

    # --- housekeeping ------------------------------------------------------------------------------------------------
    def decay(self):
        now = self.clock()
        k = math.exp(-max(0.0, now - self.last) / (TAU_DAYS * 86400))
        self.last = now
        if k < 1.0:
            for t in list(self.pref):
                self.pref[t] *= k
                if abs(self.pref[t]) < MIN_ABS:
                    self.pref.pop(t)
                    self.seen.pop(t, None)
                    self.var.pop(t, None)
            for t in self.var:                            # forgetting: a long-unseen topic is uncertain again
                self.var[t] = k * k * self.var[t] + (1 - k * k) * PRIOR_VAR

    def save(self):
        if not self.path:
            return
        save_json(self.path, {"pref": self.pref, "seen": self.seen, "var": {t: round(v, 6) for t, v in self.var.items()},
                               "last": self.last, "day_log": self.day_log, "last_replay": self.last_replay})
        try:
            self.snapshot()
        except OSError as e:                              # history is a nice-to-have: never break learning
            print(f"tastes: history not written ({e})", flush=True)

    def day(self):
        return dt.datetime.fromtimestamp(self.clock(), TZ).date().isoformat()

    def snapshot(self):
        """Append today's top topics to the history, at most once per Tokyo day. Returns True if a line was added."""
        if not self.history_path:
            return False
        today = self.day()
        if self._hist_day is None:
            rows = read_jsonl(self.history_path, last=1)
            self._hist_day = rows[-1].get("day") if rows and isinstance(rows[-1], dict) else ""
        if self._hist_day == today:
            return False
        top = sorted(self.pref.items(), key=lambda kv: -abs(kv[1]))[:HISTORY_TOP]
        append_jsonl(self.history_path, {"day": today, "t": round(self.clock()),
                                         "top": {k: round(v, 3) for k, v in top}})
        self._hist_day = today
        rows = read_jsonl(self.history_path)
        if len(rows) > HISTORY_DAYS:                      # cap: rewrite with the newest lines only (tmp + rename)
            tmp = self.history_path.with_name(self.history_path.name + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("".join(json.dumps(r) + "\n" for r in rows[-HISTORY_DAYS:]))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.history_path)
        return True

    def history(self, n=HISTORY_SHOWN):
        """The last `n` daily snapshots as [{"day", "top": [{"topic", "kind", "pref"}]}], oldest first."""
        if not self.history_path:
            return []
        try:
            st = self.history_path.stat()
            key = (st.st_mtime_ns, st.st_size)
        except OSError:
            return []
        if self._hist_cache[0] != key:
            rows = [r for r in read_jsonl(self.history_path, last=n)
                    if isinstance(r, dict) and isinstance(r.get("top"), dict)]
            self._hist_cache = (key, [{"day": r.get("day", ""),
                                       "top": [self._fmt((k, v)) for k, v in r["top"].items()
                                               if isinstance(v, (int, float))]} for r in rows])
        return self._hist_cache[1]

    @staticmethod
    def _fmt(kv):
        return {"topic": kv[0].split(":", 1)[-1], "kind": "network" if kv[0].startswith("net:") else "word",
                "pref": round(kv[1], 3)}

    def top(self, n=12):
        self.decay()
        items = sorted(self.pref.items(), key=lambda kv: -kv[1])
        fmt = self._fmt
        return {"favoured": [fmt(kv) for kv in items[:n] if kv[1] > 0],
                "avoided": [fmt(kv) for kv in items[::-1][:n] if kv[1] < 0], "topics": len(self.pref),
                "rule": f"prediction error x a Kalman gain per topic, decay {TAU_DAYS:g} days, "
                        f"night replay of the {REPLAY_N} largest errors at {REPLAY_RATE}x",
                "last_replay": self.last_replay,
                "note": "Learned from the brain model's simulated response to pages.",
                "history": self.history()}


class PageWatch:
    """Measures the brain's response while he stays on a page (fed every tick with the relative group activity)."""

    SKIP_S = 10.0             # the chosen option's own stimulus (2 s decay) must be gone, or every choice "pays off"
    SCALE = 0.5               # response units -> tanh
    BASE_TAU_S = 600.0        # running baseline of the same measure

    def __init__(self):
        self.base, self.cur = None, None

    @staticmethod
    def measure(rel):
        return rel.get("reward", 1.0) + 0.6 * rel.get("attention", 1.0) - 0.8 * rel.get("fear", 1.0)

    def start(self, topics, t):
        self.cur = {"topics": list(topics), "t0": t, "sum": 0.0, "n": 0}

    def feed(self, rel, t, dt):
        v = self.measure(rel)
        self.base = v if self.base is None else self.base + (v - self.base) * min(1.0, dt / self.BASE_TAU_S)
        c = self.cur
        if c is not None and t - c["t0"] >= self.SKIP_S:
            c["sum"] += v - self.base
            c["n"] += 1

    def finish(self):
        """-> (topics, response in -1..1) of the page he is leaving, or None if it was too short to measure."""
        c, self.cur = self.cur, None
        if not c or c["n"] < 20:
            return None
        return c["topics"], math.tanh(c["sum"] / c["n"] / self.SCALE)
