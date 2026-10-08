"""One cost ledger for SUB-01 (#15): what every paid service spent per Tokyo day, and the daily caps checked before
every paid call.

Where each cost is written (each one in exactly one file, so nothing is counted twice):
- <data>/costs.jsonl           the eye (FLUX frames + its LLM) and the diary text, written here (`Ledger.record`).
                               Rows: {t, service, model, units, usd, note}.
- <data>/eyes_costs.jsonl      the eyes and the mind: their shared ledger (mind.shared_budget), read here as it is.
                               A row whose provider starts with "mind/" is the mind's, any other row the eyes'.
- <data>/spiking/costs.jsonl   RunPod pod sessions (spiking/costs.py), read here as they are; an open pod is valued
                               up to now, like its own budget does.
`spent_today(service)` and `days()` add the three up on the Tokyo day (sleep.ROME).
Social posts of the daily clips (#59, clips.py) are written to costs.jsonl as service "clips" at $0: they are counted
(`posts_today`), never billed.

Daily caps (USD per Tokyo day, env vars):
- SUB01_CAP_EYE_USD (1.00): eye frames and the eye's LLM; over it the eye keeps its last frame ("resting its eyes").
- SUB01_CAP_DIARY_USD (0.10): the diary text (about 1-2 Llama 3 8B calls a night, < $0.001); over it the diary
  writes its template text.
- SUB01_CAP_EYES_USD (1.00) and SUB01_CAP_MIND_USD (1.00): the existing eyes / mind shares of the shared ledger
  (mind.EYES_USD_PER_DAY / MIND_USD_PER_DAY, checked by mind.Share); over them, local options / yesterday's plan.
- The eye's cap is paced over his waking day (`pace_allowed`): by a moment of the Tokyo day the eye may have spent
  EYE_PACE_SLACK (25%) of its cap (dreams at night, the first frames of the morning) plus the rest in proportion to the waking
  hours gone, 08:00 (sleep.WAKE_HOUR) to midnight, less one frame's cost (so the day's last frame stays in the cap). Spent at full rate it had used 0.80 of 1.00 by 11:00 and was capped
  all afternoon and evening (live, 2026-10-07/08). The cap itself is unchanged; SUB01_EYE_PACE=0 turns the pacing off.
- SUB01_CAP_TOTAL_USD (3.10): everything above together. Its default is the sum of the part caps
  (1.00 + 1.00 + 1.00 + 0.10), so with the defaults no part can starve another one; it only bites when a part cap
  is raised. RunPod is not in it: it keeps its own GPU-hour caps (spiking/pod_manager.py).
"""
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sleep import ROME
from state_io import append_jsonl

FILE = "costs.jsonl"
EYES_FILE = "eyes_costs.jsonl"                     # mind.LEDGER
POD_FILE = Path("spiking") / "costs.jsonl"
SERVICES = ("eye", "diary", "eyes", "mind", "runpod")
NOT_IN_TOTAL = ("runpod",)
OWN = ("eye", "diary", "clips")                    # the services written to costs.jsonl

# USD per call / per million tokens (Replicate list prices, 2026-10); the eye logs estimates, Replicate bills by run
FLUX_SCHNELL_USD = 0.003
LLAMA3_8B = (0.05, 0.25)                           # meta/meta-llama-3-8b-instruct, USD per 1M tokens (in, out)


def _cap(name, default):
    try:
        return max(0.0, float(os.environ.get(name) or default))
    except ValueError:
        return default


def caps():
    """The caps now (read from the environment each time, so tests and restarts see changes)."""
    import mind
    return {"eye": _cap("SUB01_CAP_EYE_USD", 1.00), "diary": _cap("SUB01_CAP_DIARY_USD", 0.10),
            "eyes": mind.EYES_USD_PER_DAY, "mind": mind.MIND_USD_PER_DAY, "total": _cap("SUB01_CAP_TOTAL_USD", 3.10)}


EYE_PACE_SLACK = 0.25                              # share of the eye's cap free at any hour of the Tokyo day: the night's dreams (~80 frames; the diary had 71-76)
EYE_FRAME_USD = 0.003 + (1000 * 0.05 + 80 * 0.25) / 1e6   # one frame and its thought (FLUX_SCHNELL_USD + llm_usd(1000, 80)):
                                                   # the paced allowance stops that much short, so the last frame stays in the cap
DAY_END_HOUR = 24                                  # the Tokyo day (and so the cap) ends at midnight


def pace_share(t):
    """Share of a paced daily cap that may be spent by time t: EYE_PACE_SLACK, plus the rest in proportion to the
    waking hours gone (sleep.WAKE_HOUR to midnight); 1.0 at midnight."""
    from sleep import WAKE_HOUR
    d = datetime.fromtimestamp(t, ROME)
    h = d.hour + d.minute / 60 + d.second / 3600
    f = min(1.0, max(0.0, (h - WAKE_HOUR) / (DAY_END_HOUR - WAKE_HOUR)))
    return EYE_PACE_SLACK + (1 - EYE_PACE_SLACK) * f


def paced():
    return os.environ.get("SUB01_EYE_PACE", "1") != "0"


def tokyo_day(t):
    return datetime.fromtimestamp(t, ROME).date().isoformat()


def llm_usd(tokens_in, tokens_out, price=LLAMA3_8B):
    return (tokens_in * price[0] + tokens_out * price[1]) / 1e6


class Capped(Exception):
    """A paid call was refused by a daily cap (the feature takes its free path)."""


class Ledger:
    def __init__(self, data_dir, clock=time.time):
        self.dir = Path(data_dir)
        self.path = self.dir / FILE
        self.clock = clock
        self.lock = threading.Lock()                # appends
        self.read_lock = threading.Lock()           # the incremental read state (eye/diary run in worker threads)
        self._cache = {}                            # file -> (bytes read, {day: {service: usd}})

    # --- writing ----------------------------------------------------------------------------------------------
    def record(self, service, model, units, usd, note=""):
        if service not in OWN:
            raise ValueError(f"{service} costs are logged by their own module (see the docstring)")
        row = {"t": self.clock(), "service": service, "model": model, "units": units, "usd": round(float(usd), 6),
               "note": str(note)[:80]}
        with self.lock:
            append_jsonl(self.path, row)
        return row

    # --- reading ----------------------------------------------------------------------------------------------
    def _read(self, path, convert):
        """{tokyo day: {service: usd}} of one log. Read incrementally: only bytes appended since the last read are
        parsed (a torn or unfinished last line waits for its newline); a file that shrank is read again."""
        with self.read_lock:
            return self._read_locked(path, convert)

    def _read_locked(self, path, convert):
        try:
            size = path.stat().st_size
        except OSError:
            self._cache.pop(path, None)
            return {}
        off, agg = self._cache.get(path, (0, None))
        if agg is None or size < off:
            off, agg = 0, {}
        if size > off:
            with open(path, "rb") as f:
                f.seek(off)
                chunk = f.read(size - off)
            end = chunk.rfind(b"\n") + 1                  # complete lines only
            for ln in chunk[:end].splitlines():
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue                                # a torn line (closed by append_jsonl) is skipped
                if isinstance(r, dict):
                    for t, svc, usd in convert(r):
                        d = agg.setdefault(tokyo_day(t), {})
                        d[svc] = d.get(svc, 0.0) + usd
            off += end
        self._cache[path] = (off, agg)
        return agg

    @staticmethod
    def _own(r):
        if r.get("service") in ("eye", "diary"):          # clips rows are $0: counted by posts_today only
            yield float(r.get("t", 0)), r["service"], float(r.get("usd", 0.0))

    @staticmethod
    def _eyes(r):
        part = "mind" if str(r.get("provider", "")).startswith("mind/") else "eyes"
        yield float(r.get("t", 0)), part, float(r.get("usd", 0.0))

    def _pods(self):
        """{tokyo day: {"runpod": usd}}; small file, read each time (an open pod is valued up to now)."""
        path = self.dir / POD_FILE
        if not path.exists():
            return {}
        from spiking.costs import CostLog
        out = {}
        for r in CostLog(path, clock=lambda: datetime.fromtimestamp(self.clock(), timezone.utc))._records():
            try:
                d = datetime.fromisoformat(r["start"]).astimezone(ROME).date().isoformat()
                out.setdefault(d, {})["runpod"] = out.get(d, {}).get("runpod", 0.0) + float(r.get("cost_usd", 0.0))
            except (KeyError, ValueError, TypeError):
                continue
        return out

    def by_day(self, days=7):
        """{tokyo date: {service: usd}} for the last `days` Tokyo days, today included (all zero when nothing)."""
        today = datetime.fromtimestamp(self.clock(), ROME).date()
        want = [(today - timedelta(days=i)).isoformat() for i in range(days)]
        out = {d: {s: 0.0 for s in SERVICES} for d in want}
        for agg in (self._read(self.path, self._own), self._read(self.dir / EYES_FILE, self._eyes), self._pods()):
            for d, spent in agg.items():
                if d in out:
                    for svc, usd in spent.items():
                        out[d][svc] = out[d].get(svc, 0.0) + usd
        return out

    def spent_today(self, service=None):
        """USD spent on this Tokyo day by one service, or by all of them (RunPod included) when service is None."""
        day = self.by_day(1)
        (spent,) = day.values()
        return sum(spent.values()) if service is None else spent.get(service, 0.0)

    def total_today(self):
        """What SUB01_CAP_TOTAL_USD counts: every service except RunPod."""
        (spent,) = self.by_day(1).values()
        return sum(v for k, v in spent.items() if k not in NOT_IN_TOTAL)

    def posts_today(self):
        """Clip posts on this Tokyo day per platform (clips.py; $0 rows, units = 1 for a post that went through)."""
        from state_io import read_jsonl
        day, out = tokyo_day(self.clock()), {}
        if self.path.exists():
            for r in read_jsonl(self.path):
                if r.get("service") == "clips" and tokyo_day(float(r.get("t", 0))) == day:
                    out[r.get("model", "?")] = out.get(r.get("model", "?"), 0) + int(r.get("units", 0))
        return out

    # --- caps -------------------------------------------------------------------------------------------------
    def total_why_not(self):
        cap = caps()["total"]
        if self.total_today() >= cap:
            return f"daily total AI budget (${cap:.2f}, Tokyo day) reached; resumes tomorrow"
        return None

    def pace_allowed(self, service):
        """USD `service` may have spent by now on this Tokyo day (the eye's cap paced over his waking hours; any
        other service: its whole cap)."""
        cap = caps()[service]
        return cap * pace_share(self.clock()) - EYE_FRAME_USD if service == "eye" and paced() else cap

    def why_not(self, service):
        """None when a paid call of `service` (eye or diary) is allowed now, else the reason."""
        cap, spent = caps()[service], self.spent_today(service)
        if spent >= cap:
            return f"daily {service} budget (${cap:.2f}, Tokyo day) reached; resumes tomorrow"
        allowed = self.pace_allowed(service)
        if spent > 0 and spent >= allowed:
            return f"{service} pacing its daily budget (${cap:.2f}) over the day; more later today"   # (constant: the server logs a new reason)
        return self.total_why_not()

    def check(self, service):
        why = self.why_not(service)
        if why:
            raise Capped(why)

    # --- the view for /api/costs ------------------------------------------------------------------------------
    def report(self, days=7):
        per_day = self.by_day(days)
        today = next(iter(per_day))
        c = caps()
        r2 = lambda d: {k: round(v, 4) for k, v in d.items()}
        return {"tokyo_day": today, "today": r2(per_day[today]),
                "today_total_capped": round(sum(v for k, v in per_day[today].items() if k not in NOT_IN_TOTAL), 4),
                "caps": c, "eye_paced_allowed_now": round(self.pace_allowed("eye"), 4), "capped_now": {s: self.spent_today(s) >= c[s] for s in ("eye", "diary", "eyes", "mind")}
                | {"total": self.total_today() >= c["total"]},
                "days": [{"day": d, **r2(v), "total": round(sum(v.values()), 4)} for d, v in per_day.items()],
                "last_7_days_total": round(sum(sum(v.values()) for v in per_day.values()), 4),
                "posts_today": self.posts_today(),
                "note": "USD. eye + diary from costs.jsonl, eyes + mind from eyes_costs.jsonl, runpod from "
                        "spiking/costs.jsonl; RunPod is not in the total cap (its own GPU-hour caps)."}


class MeteredLLM:
    """A Replicate Llama (eye.ReplicateLLM) whose calls are capped and logged as `service` in the ledger."""

    def __init__(self, llm, ledger, service, model="meta/meta-llama-3-8b-instruct"):
        self.llm, self.ledger, self.service, self.model = llm, ledger, service, model

    def ask(self, system, user):
        self.ledger.check(self.service)
        self.llm.last_usage = None
        try:
            return self.llm.ask(system, user)
        finally:                                        # a failed run may still be billed: log it either way
            tin, tout = getattr(self.llm, "last_usage", None) or (len(system + user) // 4, 0)
            self.ledger.record(self.service, self.model, tin + tout, llm_usd(tin, tout), "llm")
