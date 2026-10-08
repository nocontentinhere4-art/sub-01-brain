"""Schedules GPU sessions inside the Railway server process: start a pod, watch it, always delete it.

`SUB01_SESSIONS` = "daily 21:00-22:00 Asia/Tokyo" by default (several windows separated by ';'; the zone defaults
to Asia/Tokyo; a window may cross midnight); "off" disables. The manager also needs SUB01_POD_SECRET, a server URL
and RUNPOD_API_KEY (Railway env; never logged). Hard caps: SUB01_MAX_HOURS_PER_DAY (1.0), SUB01_MAX_SESSION_MIN
(60, counted from pod creation, boot included) and, in RunPodOps, SUB01_GPU_HOURS_CAP (8.0) over a rolling
SUB01_GPU_CAP_DAYS (7) window. Learned weights stay on the server's
/data volume (spiking/server.py), never on paid RunPod storage (pods have no volume).
Each session tests yesterday's items from half cues, stores today's chat messages and readings, sleeps (REM
replay) and tests again; Pong runs only with SUB01_PONG=1 (it has not learned so far), the K-armed choice task
(spiking/choice.py) only with SUB01_CHOICE=1.
A pod is deleted at session end, when the pod reports done, on any error, with no hello in 15 min, when the
stream is lost for more than 3 min, and at shutdown. Blocking RunPod calls run in a thread executor.
Never imports torch or spiking.net.

Day-live mode (#58, SUB01_DAY_LIVE=1, off by default; docs/spiking/live.md) replaces the nightly window: the pod
follows the sleep engine's stage (SpikingHub.forward_sleep -> on_stage). Awake for WAKE_CONFIRM_S: one pod starts
and runs live_decide (the 1M network answers his decisions) for the waking day. Asleep for SLEEP_CONFIRM_S: the
night message goes to the same pod (the day's items and real decisions), the night phases run, then the pod is
deleted. No pod while asleep beyond those phases. Hard caps, enforced here, each with a log line:
SUB01_DAY_MAX_HOURS (17 GPU-h per Tokyo day), SUB01_GPU_USD_PER_DAY ($14.00, RunPod's price x uptime),
SUB01_GPU_HOURS_CAP (weekly; 120 in this mode), SUB01_DAY_MAX_RESTARTS (6 per day, with backoff). At a cap the
pod is stopped and deleted and no pod starts until the next Tokyo day (the CPU network of #55 decides meanwhile).
Exactly one pod: any other pod with our prefix is an orphan and is deleted; "BRAIN" is never touched (RunPodOps).
GPU types: SUB01_GPU_TYPES, "type:CLOUD,type:CLOUD,..." tried in order (default DAY_GPUS).
"""
import asyncio
import json
import secrets
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sleep import ROME, day_of
from spiking import podpack
from spiking.costs import CostLog
from spiking.runpod_ops import Busy, CreateFailed, RunPodOps, describe, scrub
from spiking.words import half_cue_ok
from state_io import load_json, save_json

DEFAULT_TZ = "Asia/Tokyo"
HELLO_TIMEOUT_S = 15 * 60
LOST_S = 3 * 60
STOP_LEAD_S = 90                    # ask the pod to wrap up (upload weights) this long before the deadline
MIN_MINUTES = 25                    # boot + build + one test cycle: a shorter session is not worth a pod
DEFAULT_SESSIONS = "daily 21:00-22:00 Asia/Tokyo"
OFF = ("off", "none", "0", "false", "disabled")
PHASES = ["recall_yesterday", "encode", "memory_test", "sleep", "memory_test", "free"]
PONG_PHASES = ["pong_train", "pong_exam"]                  # inserted after encode with SUB01_PONG=1
CHOICE_PHASES = ["choice_train", "choice_exam"]            # inserted after encode (and Pong) with SUB01_CHOICE=1
MAX_PER_SOURCE = 5
SOURCES = ("chat", "reading", "taught")
WINDOW = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")

# --- day-live mode (#58) ---------------------------------------------------------------------------------------------
NIGHT_PHASES = ["recall_yesterday", "encode", "choice_train", "memory_test", "sleep", "memory_test"]
DAY_PHASES = ["live_decide"] + NIGHT_PHASES
# cheapest first that kept up in the benchmarks (docs/spiking/live.md); secure cloud only by default, because the
# pod carries SUB01_POD_SECRET (community hosts are third-party machines: opt in with SUB01_GPU_TYPES)
DAY_GPUS = (("NVIDIA RTX A4000", "SECURE"), ("NVIDIA RTX A4500", "SECURE"), ("NVIDIA RTX A5000", "SECURE"),
            ("NVIDIA RTX 4000 Ada Generation", "SECURE"), ("NVIDIA A40", "SECURE"))
WAKE_CONFIRM_S = 5 * 60             # awake this long before a day pod starts (a brief waking starts nothing)
SLEEP_CONFIRM_S = 10 * 60           # asleep this long before the night phases start
NIGHT_MAX_MIN = 45                  # the night phases on the pod (a night-only pod gets the same)
MIN_DAY_MIN = 30                    # a day pod with less time allowed than this is not started
BACKOFF_S = (120, 300, 600, 1200, 2400, 3600)   # wait before the next pod after the n-th failure of the day
CREATE_RETRY_S = 300                # no pod could be created (no capacity, API refusal): try again, not a restart
BUSY_RETRY_S = 120                  # another SUB-01 pod exists: wait for it, not a restart
RESTART_LOG_KEEP = 10
MANAGED = ("day-", "night-", "session-")   # name purposes this manager creates (the orphan sweep deletes only these)
ORPHAN_EVERY_S = 600
UPLOAD_EVERY_MIN = 30
DECISION_FILES = ("decisions-{day}.jsonl", "gpu_decisions-{day}.jsonl")   # #55's log, the hub's own log


class Schedule:
    """Daily windows [(start_min, end_min, tz)]; end <= start means the window ends the next day."""

    def __init__(self, windows=()):
        self.windows = list(windows)

    @classmethod
    def parse(cls, spec):
        out = []
        for part in (spec or "").split(";"):
            tz, span = DEFAULT_TZ, None
            for tok in part.split():
                m = WINDOW.match(tok)
                if m:
                    h1, m1, h2, m2 = map(int, m.groups())
                    if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
                        raise ValueError(f"bad time in SUB01_SESSIONS: {tok}")
                    span = (h1 * 60 + m1, h2 * 60 + m2)
                elif tok.lower() != "daily":
                    try:
                        ZoneInfo(tok)
                    except (KeyError, ValueError, OSError):
                        raise ValueError(f"unknown token in SUB01_SESSIONS: {tok!r}") from None
                    tz = tok
            if span:
                out.append((span[0], span[1], tz))
            elif part.strip():
                raise ValueError(f"cannot parse session window: {part.strip()!r}")
        return cls(out)

    @property
    def enabled(self):
        return bool(self.windows)

    def next_session(self, now, skip=()):
        """(start, end) of the first window that has not ended yet (it may be running now), skipping `skip` starts."""
        best = None
        for a, b, tzname in self.windows:
            tz = ZoneInfo(tzname)
            today = now.astimezone(tz).date()
            for off in (-1, 0, 1):
                day = today + timedelta(days=off)
                start = datetime(day.year, day.month, day.day, a // 60, a % 60, tzinfo=tz)
                end = start + timedelta(minutes=(b - a) % 1440 or 1440)
                if end > now and start not in skip and (best is None or start < best[0]):
                    best = (start, end)
        return best


def next_session(now, spec):
    return Schedule.parse(spec).next_session(now)


def _today(memory, t, source):
    today = day_of(t)
    cand = [m for m in memory.items if m["t"] <= t and day_of(m["t"]) == today
            and m.get("source", "chat") == source]
    cand.sort(key=lambda m: memory.weight(m, t, None), reverse=True)
    return cand


def top_messages(memory, t, n=5):
    """Today's accepted chat messages (not readings) with the highest Memory.weight, as [{"text", "emotion"}]."""
    return [{"text": m["text"], "emotion": m["emotion"]} for m in _today(memory, t, "chat")[:n]]


ITEM_META = "item_meta.json"                 # #79: host / kind of each reading sent to a session (for /api/memory)
ITEM_META_KEEP = 500

def top_items(memory, t, n=MAX_PER_SOURCE):
    """The day's items for the GPU session: top n chat messages, top n readings (title + keywords, hashed like
    chat) and up to n words viewers taught it (those with two or more content words first, then the most replayed), as [{"text", "source", "item", "emotion"}]."""
    out = [{"text": m["text"], "source": "chat", "item": m["text"], "emotion": m["emotion"]}
           for m in _today(memory, t, "chat")[:n]]
    for m in _today(memory, t, "reading")[:n]:
        title = m.get("title") or m["text"]
        out.append({"text": " ".join([title] + list(m.get("keywords") or [])), "source": "reading", "item": title,
                    "emotion": m["emotion"], "host": m.get("host", ""), "kind": m.get("kind", "wiki")})   # #79
    taught = sorted(_today(memory, t, "taught"), key=lambda m: (half_cue_ok(m["text"]), m.get("replays", 0)),
                    reverse=True)           # testable from a half cue, then the most replayed; ties: Memory.weight
    out += [{"text": m["text"], "source": "taught", "item": m["text"], "emotion": m["emotion"]} for m in taught[:n]]
    return out


def item_source(src):
    return src if src in SOURCES else "chat"


def _utcnow():
    return datetime.now(timezone.utc)


class PodManager:
    def __init__(self, data_dir, server_url, secret, api=None, clock=None, get_messages=None, schedule=None,
                 ops=None, sleep=None, env=None, tick=5.0, get_items=None):
        env = os.environ if env is None else env
        self.dir = Path(data_dir) / "spiking"
        self.server_url, self.secret = (server_url or "").rstrip("/"), secret
        self.clock = clock or _utcnow
        self._sleep = sleep or asyncio.sleep
        self.tick = tick
        self.get_messages = get_messages or (lambda: [])
        self.get_items = get_items
        spec = env.get("SUB01_SESSIONS")
        spec = DEFAULT_SESSIONS if spec is None or not spec.strip() else spec
        self.schedule = schedule if schedule is not None else Schedule.parse("" if spec.strip().lower() in OFF else spec)
        self.max_hours_day = float(env.get("SUB01_MAX_HOURS_PER_DAY") or 1.0)
        self.max_session_min = float(env.get("SUB01_MAX_SESSION_MIN") or 60)
        self.pong = env.get("SUB01_PONG") == "1"
        self.choice = env.get("SUB01_CHOICE") == "1"
        self.day_live = env.get("SUB01_DAY_LIVE") == "1"
        self.day_max_hours = float(env.get("SUB01_DAY_MAX_HOURS") or 17)
        self.usd_per_day = float(env.get("SUB01_GPU_USD_PER_DAY") or 14.0)
        self.max_restarts = int(env.get("SUB01_DAY_MAX_RESTARTS") or 6)
        self.gpus = parse_gpus(env.get("SUB01_GPU_TYPES")) if self.day_live else None
        self.send_night = None                 # async callable set by the hub: forwards the night message
        self.stage, self.stage_since = None, None
        self.dl = {}                           # day-live state (per Tokyo day; saved in manager.json)
        self._foreign_seen = set()             # pods with our prefix that this manager did not make (said once)
        # RunPod credentials: the Railway env var, or a proxy that injects them (sandbox), or an injected client
        self.has_key = bool(env.get("RUNPOD_API_KEY") or env.get("SUB01_RUNPOD_PROXY_AUTH") == "1"
                            or api is not None or ops is not None)
        self.log = ops.log if ops is not None and getattr(ops, "log", None) is not None else CostLog(self.dir / "costs.jsonl")
        week = float(env.get("SUB01_GPU_HOURS_CAP") or (120.0 if self.day_live else 8.0))
        self.ops = ops or RunPodOps(api=api, log=self.log, hours_cap=week,
                                    cap_days=float(env.get("SUB01_GPU_CAP_DAYS") or 7))
        self.send_stop = None                  # async callable set by the server: forwards {"type":"stop"} to the pod
        self.current = None                    # state of the running session
        self.done_windows = set()
        self.last_result = None
        self._warned = False
        self._pack = None                      # injectable for tests: callable -> env dict

    # --- enablement ------------------------------------------------------------------
    def enabled(self):
        why = None
        if not self.schedule.enabled and not self.day_live:
            why = "SUB01_SESSIONS is not set"
        elif not self.secret:
            why = "SUB01_POD_SECRET is not set"
        elif not self.server_url:
            why = "no server URL (SUB01_SERVER_URL)"
        elif not self.has_key:
            why = "RUNPOD_API_KEY is not set"
        if why and not self._warned:
            self._warned = True
            print(f"spiking pod manager disabled: {why}", flush=True)
        return why is None

    # --- callbacks from the websocket (server.py) -------------------------------------
    def on_hello(self, info=None):
        c = self.current
        if c:
            c["hello"], c["disconnected_at"], c["last_seen"] = True, None, self.clock()

    def on_state(self, state=None):
        c = self.current
        if c:
            c["last_seen"] = self.clock()
            if isinstance(state, dict):
                c["phase"] = state.get("phase", c.get("phase"))
                c["t_sim"] = state.get("t_sim", c.get("t_sim"))

    def on_done(self, msg=None):
        c = self.current
        if c:
            c["done"] = msg if isinstance(msg, dict) else {"ok": True}

    def on_disconnect(self):
        c = self.current
        if c and c.get("hello") and not c.get("disconnected_at"):
            c["disconnected_at"] = self.clock()

    def on_stage(self, stage):
        """The sleep engine's stage (AWAKE / NREM / REM), on every change; stage_since counts from the last
        awake <-> asleep switch (NREM <-> REM is the same sleep)."""
        if self.stage is None or (stage == "AWAKE") != (self.stage == "AWAKE"):
            self.stage_since = self.clock()
        self.stage = stage

    # --- status ----------------------------------------------------------------------
    def status(self):
        c = self.current
        nxt = self.schedule.next_session(self.clock(), self.done_windows) if self.schedule.enabled else None
        live = bool(c and c.get("hello") and not c.get("disconnected_at"))
        sess = None
        if c:
            sess = {"session_id": c["session_id"], "started": c["started"].isoformat(),
                    "ends": c["deadline"].isoformat(), "phase": c.get("phase"), "t_sim": c.get("t_sim")}
        out = {"live": live, "session": sess, "next_session": nxt[0].isoformat() if nxt else None,
               "spend": self.log.summary()}
        if self.day_live:
            hours, usd = self.log.usage_on(self.clock().astimezone(ROME).date())
            out["day_live"] = {"stage": self.stage, "pod": c.get("mode") if c else None,
                               "blocked": self.dl.get("blocked"), "restarts_today": self.dl.get("restarts", 0),
                               "next_try": self.dl.get("next_try"),
                               "restart_log": list(self.dl.get("restart_log") or [])[-RESTART_LOG_KEEP:],
                               "gpu_failures_today": dict(self.dl.get("gpu_fail") or {}),
                               "today_hours": round(hours, 3), "today_usd": round(usd, 3),
                               "caps": {"hours_per_day": self.day_max_hours, "usd_per_day": self.usd_per_day,
                                        "hours_per_week": self.ops.hours_cap, "restarts_per_day": self.max_restarts}}
        return out

    # --- the loop --------------------------------------------------------------------
    async def run(self):
        if not self.enabled():
            return
        loop = asyncio.get_running_loop()
        try:
            try:
                await loop.run_in_executor(None, self.ops.cleanup_ours, "startup recovery")
            except Exception as e:
                print(f"spiking startup recovery failed: {type(e).__name__}", flush=True)
            self._load_done()
            if self.day_live:
                print("spiking: day-live mode on (SUB01_DAY_LIVE=1): the GPU pod follows his waking hours", flush=True)
                return await self.run_day_live()
            while True:
                nxt = self.schedule.next_session(self.clock(), self.done_windows)
                if nxt is None:
                    return
                start, end = nxt
                while self.clock() < start:
                    await self._sleep(min(30.0, max(1.0, (start - self.clock()).total_seconds())))
                self.done_windows.add(start)
                self._save()
                try:
                    self.last_result = await self.run_session(start, end)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self.last_result = f"error: {type(e).__name__}"
                    if type(e).__name__ == "CapExceeded":
                        print(f"spiking: GPU-hour cap reached, sessions paused ({e})", flush=True)
                    else:
                        print("spiking session failed:", self.last_result, flush=True)   # no API bodies in logs
        finally:
            self.shutdown()

    def shutdown(self):
        """Blocking last resort: no pod of ours survives the manager."""
        try:
            self.ops.cleanup_ours("shutdown")
        except Exception as e:
            print(f"spiking shutdown cleanup failed: {type(e).__name__}", file=sys.stderr, flush=True)

    # --- one session -----------------------------------------------------------------
    def session_config(self, start, minutes, now):
        day = now.astimezone(ROME).date()
        try:
            if self.get_items is not None:
                raw = list(self.get_items() or [])
            else:
                raw = [dict(m, source="chat") for m in (self.get_messages() or [])]
        except Exception:
            raw = []
        items, n = [], {}
        for m in raw:
            src = item_source(m.get("source"))
            if m.get("text") and n.get(src, 0) < MAX_PER_SOURCE:
                n[src] = n.get(src, 0) + 1
                items.append({"text": str(m["text"]), "source": src, "item": str(m.get("item") or m["text"]),
                              "emotion": m.get("emotion", "neutral")})
        self.save_item_meta(raw)
        msgs = [{"text": it["text"], "emotion": it["emotion"]} for it in items if it["source"] == "chat"]
        max_min = max(5, int(minutes) - 15)                     # pod-side budget: boot (~5-10 min) is billed too
        phases = list(PHASES)
        if self.pong:
            phases[phases.index("encode") + 1:phases.index("encode") + 1] = PONG_PHASES
        if self.choice:
            at = phases.index("pong_exam") + 1 if self.pong else phases.index("encode") + 1
            phases[at:at] = CHOICE_PHASES
        return {"session_id": "s-" + start.astimezone(ROME).strftime("%Y%m%d-%H%M"), "day": day.isoformat(),
                "n_neurons": 1_000_000, "seed": 1, "max_minutes": max_min,      # fixed: same synapses every day
                "phases": phases, "pong_train_minutes": 20 if max_min >= 60 else max(3, max_min // 4),
                "messages": msgs, "items": items, "elapsed_days": self.elapsed_days(now), "validate": False}

    def save_item_meta(self, raw):
        """#79: where each reading came from ({item: {host, kind}}, spiking/item_meta.json), for /api/memory. The pod
        never sees it: the session's items keep their fields."""
        try:
            meta = load_json(self.dir / ITEM_META, {}) or {}
        except OSError:
            meta = {}
        for m in raw:
            if m.get("source") == "reading" and (m.get("item") or m.get("text")) and m.get("kind"):
                meta[str(m.get("item") or m["text"])[:200]] = {"host": str(m.get("host") or "")[:80],
                                                               "kind": str(m["kind"])[:20]}
        while len(meta) > ITEM_META_KEEP:
            meta.pop(next(iter(meta)))
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            save_json(self.dir / ITEM_META, meta)
        except OSError as e:
            print(f"spiking: item meta not saved ({type(e).__name__})", file=sys.stderr, flush=True)

    def elapsed_days(self, now):
        state = self.dir / "manager.json"
        try:
            last = datetime.fromisoformat(json.loads(state.read_text())["last_session_end"])
        except Exception:
            w = self.dir / "weights.npz"
            last = datetime.fromtimestamp(w.stat().st_mtime, timezone.utc) if w.exists() else None
        if last is None:
            return 1.0
        return round(max(0.0, (now - last).total_seconds() / 86400), 3)

    def _load_done(self):
        """Windows already used (kept across restarts so a crash loop cannot start a second pod in one window)."""
        try:
            for s in load_json(self.dir / "manager.json", {}).get("windows_done", []):
                self.done_windows.add(datetime.fromisoformat(s))
        except Exception:
            pass

    def _save(self, **updates):
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            path = self.dir / "manager.json"
            state = load_json(path, {})
            state.update(updates, windows_done=[d.isoformat() for d in sorted(self.done_windows)[-10:]])
            save_json(path, state)                          # atomic: a torn file would forget windows_done
        except OSError:
            pass

    async def run_session(self, start, end):
        loop = asyncio.get_running_loop()
        now = self.clock()
        day_left = self.max_hours_day - self.log.hours_on(now.astimezone(ROME).date())
        minutes = min(self.max_session_min, (end - now).total_seconds() / 60, day_left * 60)
        if minutes < MIN_MINUTES:
            return f"skipped: only {minutes:.0f} min allowed (daily cap / window)"
        cfg = self.session_config(start, minutes, now)
        data = await loop.run_in_executor(None, self._pack or podpack.pack_bytes)
        token = secrets.token_hex(24)
        env = dict(podpack.boot_env(token), SUB01_SESSION=json.dumps(cfg), SUB01_SERVER_URL=self.server_url,
                   SUB01_POD_SECRET=self.secret, SUB01_SESSION_ID=cfg["session_id"])
        t_create = self.clock()                                  # billed from here: boot counts against the hour
        pod = await loop.run_in_executor(None, self.ops.create, env, "session", "spiking.session", minutes)
        pod_id = pod["id"]
        try:                                                     # code + data go up after boot (create body < 100 KB)
            await loop.run_in_executor(None, self.ops.upload, pod_id, data, token)
        except BaseException:
            await self._delete(pod_id, "pack upload failed")
            raise
        t0 = self.clock()
        self.current = {"session_id": cfg["session_id"], "pod_id": pod_id, "started": t0, "hello": False,
                        "last_seen": t0, "disconnected_at": None, "done": None,
                        "deadline": t_create + timedelta(minutes=minutes)}
        print(f"spiking session {cfg['session_id']} started ({minutes:.0f} min max)", flush=True)
        reason = "error"
        try:
            reason = await self._watch(t0, self.current)
        finally:
            await self._delete(pod_id, reason)
            self._save(last_session_end=self.clock().isoformat())
            self.current = None
        return reason

    async def _watch(self, t0, c):
        """Poll until a stop condition; returns the reason the pod is deleted."""
        stop_sent = False
        while True:
            now = self.clock()
            if c["done"] is not None:
                ok = c["done"].get("ok", True)
                return "done" if ok else f"done with error: {str(c['done'].get('error'))[:120]}"
            if now >= c["deadline"]:
                return "session end"
            if not c["hello"] and (now - t0).total_seconds() > HELLO_TIMEOUT_S:
                return "no hello within 15 min"
            if c["hello"]:
                gap = now - (c["disconnected_at"] or c["last_seen"])
                if gap.total_seconds() > LOST_S:
                    return "stream lost"
            if not stop_sent and c["hello"] and (c["deadline"] - now).total_seconds() <= STOP_LEAD_S:
                stop_sent = True
                if self.send_stop:
                    try:
                        await self.send_stop()
                    except Exception:
                        pass
            await self._sleep(self.tick)

    async def _delete(self, pod_id, reason):
        """Delete in the executor; if that is cancelled or fails, retry blocking so the pod never survives."""
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self.ops.delete, pod_id, reason)
            return
        except BaseException as e:
            err = e
        try:
            self.ops.delete(pod_id, reason)
        except Exception as e2:
            print(f"spiking: could not delete pod {pod_id}: {type(e2).__name__}", file=sys.stderr, flush=True)
        if isinstance(err, asyncio.CancelledError):
            raise err

    # --- day-live mode (#58) -----------------------------------------------------------
    @staticmethod
    def day_key(now, asleep=False):
        """The waking day: awake, cut at 05:00 Tokyo (a morning from 05:00 is a new day); for a sleep, the day
        its onset closes, cut at 08:00 as sleep.day_of (asleep at 01:00 or 06:00 still closes the day before)."""
        return (now.astimezone(ROME) - timedelta(hours=8 if asleep else 5)).date().isoformat()

    def _dl_load(self):
        try:
            self.dl = dict(load_json(self.dir / "manager.json", {}).get("day_live") or {})
        except Exception:
            self.dl = {}

    def _dl_save(self):
        self._save(day_live=self.dl)

    def _dl_roll(self, now):
        today = now.astimezone(ROME).date().isoformat()
        if self.dl.get("day") != today:
            if self.dl.get("day"):
                print(f"spiking: Tokyo day {today}: day-live caps and restart count reset", flush=True)
            self.dl = {"day": today, "restarts": 0, "blocked": None, "next_try": None,
                       "nights": list(self.dl.get("nights") or [])[-7:],
                       "restart_log": list(self.dl.get("restart_log") or [])[-RESTART_LOG_KEEP:]}
            self._dl_save()

    def _stage_for(self, now):
        """'awake' / 'asleep' once the stage has held for its confirmation time, else None."""
        if self.stage is None or self.stage_since is None:
            return None
        held = (now - self.stage_since).total_seconds()
        if self.stage == "AWAKE":
            return "awake" if held >= WAKE_CONFIRM_S else None
        return "asleep" if held >= SLEEP_CONFIRM_S else None

    def allowed_minutes(self, now, rate=None):
        """Minutes left before the first cap (day hours, weekly hours, daily USD at `rate` $/h)."""
        hours, usd = self.log.usage_on(now.astimezone(ROME).date())
        left = [self.day_max_hours - hours, self.ops.hours_cap - self.log.hours_since(self.ops.cap_days or 7)]
        if rate:
            left.append((self.usd_per_day - usd) / rate)
        elif usd >= self.usd_per_day:
            left.append(0.0)
        return max(0.0, min(left) * 60)

    def cap_reason(self, now, rate=None):
        hours, usd = self.log.usage_on(now.astimezone(ROME).date())
        week = self.log.hours_since(self.ops.cap_days or 7)
        lead = STOP_LEAD_S / 3600                                   # stop early enough to upload the weights
        if hours + lead >= self.day_max_hours:
            return f"day GPU-hour cap ({hours:.2f} h of SUB01_DAY_MAX_HOURS={self.day_max_hours:g})"
        if usd + lead * (rate or 0.0) >= self.usd_per_day:
            return f"daily USD cap (${usd:.2f} of SUB01_GPU_USD_PER_DAY={self.usd_per_day:.2f})"
        if week + lead >= self.ops.hours_cap:
            return f"weekly GPU-hour cap ({week:.2f} h of SUB01_GPU_HOURS_CAP={self.ops.hours_cap:g})"
        return None

    def _block(self, reason):
        if self.dl.get("blocked") != reason:
            self.dl["blocked"] = reason
            self._dl_save()
            print(f"spiking: {reason}: no GPU pod until the next Tokyo day; the CPU network decides", flush=True)

    def weights_age_days(self, now):
        w = self.dir / "weights.npz"
        if not w.exists():
            return 0.0
        return round(max(0.0, (now - datetime.fromtimestamp(w.stat().st_mtime, timezone.utc)).total_seconds() / 86400), 4)

    def day_decisions(self, since, now):
        """The real decisions made since `since` (the waking day), with their reward, from #55's log and the hub's
        own log, merged by id: [{options, pick, reward, kind}] (at most 300, labels cut to 120 characters)."""
        days, d = [], since.astimezone(ROME).date()
        while d <= now.astimezone(ROME).date():
            days.append(d.isoformat())
            d += timedelta(days=1)
        rows, t0 = {}, since.timestamp()
        for day in days:
            for name in DECISION_FILES:
                try:
                    lines = (self.dir / name.format(day=day)).read_text().splitlines()
                except OSError:
                    continue
                for ln in lines:
                    try:
                        r = json.loads(ln)
                    except ValueError:
                        continue
                    if not isinstance(r, dict) or r.get("id") is None:
                        continue
                    if not isinstance(r.get("t"), (int, float)) or r["t"] < t0:
                        continue
                    cur = rows.setdefault(str(r["id"]), {"t": r["t"]})
                    if isinstance(r.get("options"), list) and isinstance(r.get("pick"), int):
                        cur.update(options=[str(o)[:120] for o in r["options"]][:8], pick=r["pick"],
                                   kind=str(r.get("kind") or ""))
                    rew = r.get("reward", r.get("value"))
                    if isinstance(rew, (int, float)) and not isinstance(rew, bool):
                        cur["reward"] = float(rew)
        out = [{k: v for k, v in r.items() if k != "t"} for r in sorted(rows.values(), key=lambda r: r["t"])
               if "options" in r and r.get("reward") is not None and 0 <= r["pick"] < len(r["options"])]
        return out[-300:]

    def day_phases(self, mode):
        phases = list(DAY_PHASES if mode == "day" else NIGHT_PHASES)
        if not self.choice:
            phases.remove("choice_train")
        return phases

    def night_payload(self, c, now):
        """The night message: the waking day's name, its top items (as for the nightly session) and, with
        SUB01_CHOICE=1, its real decisions with their outcome."""
        return {"day": c["key"], "items": self.session_config(now, 60, now)["items"],
                "decisions": self.day_decisions(c["started"], now) if self.choice else [], "elapsed_days": 0.0}

    def day_config(self, mode, now, key):
        cfg = {"session_id": f"{mode[0]}-" + now.astimezone(ROME).strftime("%Y%m%d-%H%M"), "day": key,
               "n_neurons": 1_000_000, "seed": 1, "phases": self.day_phases(mode), "validate": False,
               "max_minutes": 20 * 60 if mode == "day" else NIGHT_MAX_MIN - 5, "upload_every_min": UPLOAD_EVERY_MIN,
               "elapsed_days": self.weights_age_days(now), "mode": mode, "items": [], "messages": []}
        if mode == "night":                          # no day pod ran (or it was lost): the night alone
            since = datetime.fromisoformat(key).replace(hour=5, tzinfo=ROME)
            cfg.update({k: v for k, v in self.night_payload({"key": key, "started": since}, now).items()
                        if k != "elapsed_days"})
        return cfg

    async def _sweep_orphans(self):
        """Delete every pod with our prefix that is not the current one (never another prefix: never BRAIN)."""
        loop = asyncio.get_running_loop()
        try:
            pods = await loop.run_in_executor(None, self.ops.ours)
        except Exception as e:
            print(f"spiking: orphan check failed: {type(e).__name__}", flush=True)
            return []
        cur = self.current["pod_id"] if self.current else None
        gone = []
        known = {r.get("pod_id") for r in self.log.open_pods()}
        for pod in pods:
            if not pod.get("id") or pod["id"] == cur:
                continue
            if not str(pod.get("name", ""))[len(self.ops.prefix):].startswith(MANAGED):
                if pod["id"] not in self._foreign_seen:          # e.g. a validation pod from a work session
                    self._foreign_seen.add(pod["id"])
                    print(f"spiking: pod {pod['id']} ({str(pod.get('name'))[:60]}) is not one this manager makes: "
                          "left alone; no new pod until it is gone", flush=True)
                continue
            print(f"spiking: deleting orphan pod {pod['id']} (ours, not tracked)", flush=True)
            await self._delete(pod["id"], "orphan")
            if pod["id"] not in known:                           # never logged: book its cost now
                self.log.orphan(pod, self.clock())
            gone.append(pod["id"])
        return gone

    async def _start_pod(self, mode, now, key):
        loop = asyncio.get_running_loop()
        allowed = self.allowed_minutes(now)
        need = MIN_DAY_MIN if mode == "day" else 20
        if allowed < need:
            self._block(self.cap_reason(now) or f"only {allowed:.0f} min of GPU time left under the caps")
            return None
        cfg = self.day_config(mode, now, key)
        data = await loop.run_in_executor(None, self._pack or podpack.pack_bytes)
        token = secrets.token_hex(24)
        env = dict(podpack.boot_env(token), SUB01_SESSION=json.dumps(cfg), SUB01_SERVER_URL=self.server_url,
                   SUB01_POD_SECRET=self.secret, SUB01_SESSION_ID=cfg["session_id"])
        minutes = min(allowed, 20 * 60 if mode == "day" else NIGHT_MAX_MIN)
        gpus = self.gpu_order()
        try:
            pod = await loop.run_in_executor(None, lambda: self.ops.create(env, mode, "spiking.session", minutes, gpus))
        except Exception as e:
            if type(e).__name__ == "CapExceeded":
                self._block(f"weekly GPU-hour cap ({e})")
                return None
            if isinstance(e, Busy):                              # an orphan of ours is deleted now; anything else waits
                gone = await self._sweep_orphans()
                self._not_started(now, "another SUB-01 pod exists" + (" (orphan deleted)" if gone else ""),
                                  scrub(e), 0 if gone else BUSY_RETRY_S)
                return None
            errs = "; ".join(e.errors) if isinstance(e, CreateFailed) else describe(e)
            self._not_started(now, "no pod created", errs, CREATE_RETRY_S)
            return None
        pod_id, gpu = pod["id"], pod.get("_gpu")
        t_create = self.clock()
        try:
            await loop.run_in_executor(None, self.ops.upload, pod_id, data, token)
        except BaseException as e:
            err = describe(e) if not isinstance(e, asyncio.CancelledError) else "cancelled"
            if isinstance(e, asyncio.CancelledError):
                await self._delete(pod_id, "pack upload failed")
                raise
            pod_said = await self._pod_said(pod_id)
            await self._delete(pod_id, "pack upload failed")
            self._failed(now, "pack upload failed", pod_id=pod_id, gpu=gpu,
                         secs_alive=(self.clock() - t_create).total_seconds(),
                         last_error="; ".join(x for x in (err, pod_said) if x))
            return None
        rate = next((r.get("cost_per_hr") for r in self.log.open_pods() if r.get("pod_id") == pod_id), None)
        t0 = self.clock()
        self.current = {"session_id": cfg["session_id"], "pod_id": pod_id, "started": t0, "hello": False,
                        "gpu": gpu, "created": t_create,
                        "last_seen": t0, "disconnected_at": None, "done": None, "mode": mode, "key": key,
                        "rate": rate, "deadline": t0 + timedelta(minutes=minutes), "stop_sent": None,
                        "stop_reason": None,
                        "night_deadline": t0 + timedelta(minutes=NIGHT_MAX_MIN) if mode == "night" else None}
        self.dl["pods"] = self.dl.get("pods", 0) + 1
        self._dl_save()
        print(f"spiking: {mode} pod {pod_id} started ({cfg['session_id']}, ${rate or 0:.3f}/h)", flush=True)
        return self.current

    def gpu_order(self):
        """The GPU list with the types whose pods failed today moved back (stable: cheapest first among equals)."""
        fails = self.dl.get("gpu_fail") or {}
        return sorted(list(self.gpus or DAY_GPUS), key=lambda g: fails.get(g[0], 0))

    def _log_restart(self, now, why, counted, pod_id=None, gpu=None, secs_alive=None, last_error=""):
        entry = {"t": now.isoformat(timespec="seconds"), "why": str(why)[:120], "pod_id": pod_id, "gpu": gpu,
                 "secs_alive": round(secs_alive) if secs_alive is not None else None,
                 "last_error": scrub(last_error, 300), "counted": bool(counted)}
        log = self.dl.setdefault("restart_log", [])
        log.append(entry)
        del log[:-RESTART_LOG_KEEP]
        return entry

    def _not_started(self, now, why, err, wait):
        """No pod was made (nothing billed): retry after `wait`, without counting a restart."""
        self._log_restart(now, why, False, last_error=err)
        self.dl["next_try"] = (now + timedelta(seconds=wait)).isoformat() if wait else None
        self._dl_save()
        print(f"spiking: {why}: {scrub(err, 300)}; next try in {wait} s (not counted as a restart)", flush=True)

    async def _pod_said(self, pod_id):
        """The pod's own last word (status.json phase / error, last line of session.log), credential-free and short,
        so the restart log says why it died. '' when it cannot be read in time."""
        loop = asyncio.get_running_loop()

        def fetch():
            try:
                st = json.loads(self.ops.fetch(pod_id, "status.json", timeout=10))
            except Exception as e:
                return f"pod status not readable ({describe(e)})"
            out = f"pod phase {st.get('phase')}" + (f", error {st['error']}" if st.get("error") else "")
            try:
                tail = [ln for ln in self.ops.fetch(pod_id, "session.log", timeout=10).decode(errors="replace")
                        .splitlines() if ln.strip()]
                if tail:
                    out += "; log: " + tail[-1]
            except Exception:
                pass
            return out
        try:
            return scrub(await asyncio.wait_for(loop.run_in_executor(None, fetch), 25), 300)
        except Exception:
            return ""

    def _failed(self, now, reason, pod_id=None, gpu=None, secs_alive=None, last_error=""):
        """A pod was made and died: a counted restart with backoff; its GPU type goes to the back of the list."""
        self._log_restart(now, reason, True, pod_id, gpu, secs_alive, last_error)
        if gpu:
            fails = self.dl.setdefault("gpu_fail", {})
            fails[gpu] = fails.get(gpu, 0) + 1
        n = self.dl["restarts"] = self.dl.get("restarts", 0) + 1
        wait = BACKOFF_S[min(n, len(BACKOFF_S)) - 1]
        self.dl["next_try"] = (now + timedelta(seconds=wait)).isoformat()
        self._dl_save()
        if n > self.max_restarts:
            self._block(f"restart cap ({n - 1} restarts of SUB01_DAY_MAX_RESTARTS={self.max_restarts})")
        else:
            print(f"spiking: pod failed ({reason}{'; ' + scrub(last_error, 200) if last_error else ''}); "
                  f"restart {n} of {self.max_restarts} in {wait} s", flush=True)

    async def _end(self, reason, failure=False, last_error=""):
        c = self.current
        if failure and not last_error:
            last_error = await self._pod_said(c["pod_id"])
        try:
            await self._delete(c["pod_id"], reason)
        finally:
            self.current = None
            self._save(last_session_end=self.clock().isoformat())
        print(f"spiking: {c['mode']} pod {c['pod_id']} deleted ({reason})", flush=True)
        if failure:
            now = self.clock()
            self._failed(now, reason, pod_id=c["pod_id"], gpu=c.get("gpu"),
                         secs_alive=(now - c.get("created", c["started"])).total_seconds(), last_error=last_error)
        return reason

    async def _request_stop(self, c, reason, now):
        if c["stop_sent"] is None:
            c["stop_sent"], c["stop_reason"] = now, reason
            print(f"spiking: stopping the {c['mode']} pod: {reason}", flush=True)
            if self.send_stop:
                try:
                    await self.send_stop()
                except Exception:
                    pass

    async def day_step(self, now):
        """One look at the day-live state; starts, steers or deletes the pod. Returns what it did (tests)."""
        self._dl_roll(now)
        c = self.current
        state = self._stage_for(now)
        key = self.day_key(self.stage_since, asleep=True) if state == "asleep" else self.day_key(now)
        nights = self.dl.setdefault("nights", [])
        if c is None:
            if self.dl.get("blocked"):
                return None
            if self.dl.get("next_try") and now < datetime.fromisoformat(self.dl["next_try"]):
                return None
            if state == "awake" and key not in nights:
                return await self._start_pod("day", now, key) and "started day"
            if state == "asleep" and key not in nights:
                return await self._start_pod("night", now, key) and "started night"
            return None
        if c["done"] is not None:
            ok = c["done"].get("ok", True)
            if c["mode"] == "night" and key_done(nights, c["key"]):
                self._dl_save()
            if c["stop_reason"]:
                return await self._end(c["stop_reason"])
            if c["mode"] == "night":
                return await self._end("night done" if ok else f"night done with error: {str(c['done'].get('error'))[:120]}")
            return await self._end("done" if ok else "done with error", failure=not ok,
                                   last_error="" if ok else f"pod: {str(c['done'].get('error'))[:200]}")
        if not c["hello"] and (now - c["started"]).total_seconds() > HELLO_TIMEOUT_S:
            return await self._end("no hello within 15 min", failure=True)
        if c["hello"] and (now - (c["disconnected_at"] or c["last_seen"])).total_seconds() > LOST_S:
            return await self._end("stream lost", failure=True)
        cap = self.cap_reason(now, c.get("rate"))
        if cap:
            self._block(cap)
            await self._request_stop(c, cap, now)
        if c["stop_sent"] is not None:
            hard = self.allowed_minutes(now, c.get("rate")) <= 0
            if hard or (now - c["stop_sent"]).total_seconds() > STOP_LEAD_S + 60:
                return await self._end(c["stop_reason"] + (" (hard)" if hard else ""))
            return None
        if c["mode"] == "day" and state == "asleep":
            if c["key"] in nights or not self.send_night:
                await self._request_stop(c, "asleep (night already done)", now)
                return "stopping"
            payload = self.night_payload(c, now)
            sent = await self.send_night(payload)
            if sent is False:
                await self._request_stop(c, "asleep (night message not delivered)", now)
                return "stopping"
            c["mode"], c["night_deadline"] = "night", now + timedelta(minutes=NIGHT_MAX_MIN)
            print(f"spiking: asleep: night phases on the pod ({len(payload['items'])} items, "
                  f"{len(payload['decisions'])} decisions)", flush=True)
            return "night sent"
        if c["mode"] == "night" and now >= c["night_deadline"]:
            key_done(nights, c["key"])                       # one night per waking day, whatever its outcome
            return await self._end("night deadline")
        return None

    async def run_day_live(self):
        self._dl_load()
        last_sweep = None
        while True:
            now = self.clock()
            if last_sweep is None or (now - last_sweep).total_seconds() >= ORPHAN_EVERY_S:
                last_sweep = now
                await self._sweep_orphans()
            try:
                await self.day_step(now)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"spiking day-live step failed: {type(e).__name__}", flush=True)
            await self._sleep(self.tick)


# --- the API for brain_vote (#55): the hub registers itself when a day-live manager is attached ------------------------
_hub = None


def register_hub(hub):
    global _hub
    _hub = hub


async def day_live_decide(options, kind="browse", deadline_ms=2000):
    """The 1M GPU network's decision among `options`, or None at once when day-live is off or no pod is live, and
    None when it does not answer within `deadline_ms` (the caller falls back to the CPU network). Never raises."""
    hub = _hub
    try:
        if hub is None or not getattr(hub.manager, "day_live", False) or not hub.connected or not hub.live_ready:
            return None
        return await hub.decide(options, kind, deadline_ms)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"spiking: day_live_decide failed: {type(e).__name__}", flush=True)
        return None


async def day_live_reward(decision_id, value):
    """Dopamine for a decision the GPU network made (ignored otherwise). Never raises; returns None."""
    hub = _hub
    try:
        if hub is not None and getattr(hub.manager, "day_live", False):
            hub.reward(decision_id, value)
    except Exception as e:
        print(f"spiking: day_live_reward failed: {type(e).__name__}", flush=True)
    return None


def key_done(nights, key):
    """Mark a waking day's night as done (True if newly added)."""
    if key in nights:
        return False
    nights.append(key)
    del nights[:-7]
    return True


def parse_gpus(spec):
    """SUB01_GPU_TYPES "type:CLOUD,..." -> [(type, cloud)] (only types and clouds podpack allows); default DAY_GPUS."""
    out = []
    for part in (spec or "").split(","):
        if not part.strip():
            continue
        gpu, _, cloud = part.strip().rpartition(":") if ":" in part else (part.strip(), "", "SECURE")
        gpu, cloud = gpu.strip(), (cloud.strip() or "SECURE").upper()
        if gpu not in podpack.GPUS or cloud not in podpack.CLOUDS:
            raise ValueError(f"SUB01_GPU_TYPES: not allowed: {part.strip()!r}")
        out.append((gpu, cloud))
    return out or list(DAY_GPUS)


def from_env(data_dir, get_messages=None, get_items=None):
    """Manager configured from the Railway environment (server URL from SUB01_SERVER_URL or the Railway domain)."""
    url = os.environ.get("SUB01_SERVER_URL", "")
    if not url and os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
        url = "https://" + os.environ["RAILWAY_PUBLIC_DOMAIN"]
    return PodManager(data_dir, url, os.environ.get("SUB01_POD_SECRET", ""), get_messages=get_messages,
                      get_items=get_items)
