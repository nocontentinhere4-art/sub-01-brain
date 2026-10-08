"""aiohttp routes on the Railway server for the GPU pod: websocket ingress, learned-weights store, results, status.

The three pod routes bypass the site password gate and authenticate with `Authorization: Bearer <SUB01_POD_SECRET>`
(hmac.compare_digest); without that variable on the server they answer 403. Never imports torch or spiking.net.

Live decisions (#58, docs/spiking/live.md), the protocol shared with the CPU network of #55:
  server -> pod  {"type": "decide", "id", "options": [label, ...], "kind": "browse|chess|plan", "deadline_ms"}
  pod -> server  {"type": "decision", "id", "pick", "pool_rates", "sim_ms", "n_neurons"}
  server -> pod  {"type": "reward", "id", "value"}
`await hub.decide(options, kind, deadline_ms)` returns the decision (plus "net": "gpu" and the card label) or None
(no live pod, or no answer in time: the caller falls back to the CPU network, then to the rate model);
`hub.reward(id, value)` forwards the dopamine for a decision the pod answered. Both are logged to
<data>/spiking/gpu_decisions-<Tokyo date>.jsonl.
"""
import asyncio
import hmac
import json
import math
import os
import secrets
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp
from aiohttp import web

from sleep import ROME
from spiking import frames
from spiking.costs import CostLog
from state_io import append_jsonl, load_json, save_json

SPIKING_KEY = web.AppKey("spiking", object)
POD_PATHS = ("/api/spiking/pod", "/api/spiking/weights", "/api/spiking/result")
KINDS = {"pong_curve": "pong_curves", "exam": "exams", "memory_test": "memory_test_runs", "bench": "bench"}
ITEMS_FILE = "memory_tests.jsonl"   # one row per tested item: {day, item, source, recalled, score, ...}
MEMORY_NOTE = "Recall by a simulated spiking network from a partial cue; a model, not a mind."
EXTRA_KINDS = {"encode": "encodes", "rates": "rates", "delays": "delays", "sleep": "sleeps",   # stored, not on the page
               "choice_curve": "choice_curves", "choice_exam": "choice_exams", "choice_replay": "choice_replays",
               "live": "live", "live_bench": "live_bench", "live_learn": "live_learn"}
NET_LABEL = "1M-neuron network on GPU"     # the decision card's name for this network (#58)
DECISIONS_FILE = "gpu_decisions-{day}.jsonl"
LEARNING_FILES = ("decisions-{day}.jsonl", DECISIONS_FILE)   # #55's log and ours, merged by id (#70)
LEARNING_DAYS = 14                  # days in the status's learning curve
LEARNING_TTL_S = 60.0
LEARNING_NOTE = ("Real decisions: the fraction of picks whose later outcome was positive, per day. Replay: on the "
                 "same day's decisions, how often the network's own pick agrees with the outcomes, learned vs its "
                 "frozen twin (every learned change removed). Measured numbers only; a model, not a mind.")
MAX_OPTIONS = 8
MAX_ANSWERED = 512                  # decisions the pod answered that can still get their reward
MAX_WS_MSG = 1 << 20
MAX_WEIGHTS = 512 * 1024 ** 2
RELAY_MIN_S = 0.25                  # at most 4 state frames per second go to the page
RACE_SHOW_S = 1.0                   # the page highlights the action pools this long after a decision (#62)
GOOD_MIN_S = 30.0


def _days(a, b):
    """Whole days from ISO date a to ISO date b (None if either is missing or malformed)."""
    try:
        return (datetime.fromisoformat(str(b)) - datetime.fromisoformat(str(a))).days
    except ValueError:
        return None


class SpikingHub:
    def __init__(self, live, data_dir, secret=None, clock=time.monotonic):
        self.live = live
        self.dir = Path(data_dir) / "spiking"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._secret = secret
        self.clock = clock
        self.ws = None
        self.session = None                 # {"session_id", "n_neurons", "device", "phases"} from the pod's hello
        self.last_state = None
        self.manager = None                 # PodManager (on_hello/on_state/on_done/on_disconnect) when enabled
        self.stage = None
        self._relayed = -1e9
        self._good = -1e9
        self._tasks = set()
        self.live_ready = False             # the pod answers decide messages (it sent live_ready)
        self._waiting = {}                  # decision id -> future
        self.answered = OrderedDict()       # decision id -> Tokyo day of the decision
        self.decide_stats = {"asked": 0, "answered": 0, "timeouts": 0, "rewards": 0}
        self._learning = (-1e9, None)       # (monotonic time, cached learning curve)
        self._manager = None
        self.budget = frames.Budget(clock=lambda: self.clock())     # what each viewer gets of both networks' frames
        self.sample = frames.Sample.one_per_region(200, 214)        # the GPU raster's neurons (set on hello)
        self._samples = {}
        self._race_until = -1e9
        try:
            self.last = load_json(self.dir / "last.json", {})
        except OSError:
            self.last = {}

    @property
    def manager(self):
        return self._manager

    @manager.setter
    def manager(self, mgr):
        """The PodManager; it also gets the night message sender (the server sets send_stop itself)."""
        self._manager = mgr
        if mgr is not None:
            mgr.send_night = self.send_night
            if getattr(mgr, "day_live", False):              # pod_manager.day_live_decide / day_live_reward use us
                from spiking import pod_manager
                pod_manager.register_hub(self)

    # --- auth ---------------------------------------------------------------------
    @property
    def secret(self):
        return self._secret if self._secret is not None else os.environ.get("SUB01_POD_SECRET", "")

    def check(self, request):
        """403 when the server has no secret, 401 on a missing or wrong bearer token."""
        if not self.secret:
            raise web.HTTPForbidden()
        sent = request.headers.get("Authorization", "")
        if not hmac.compare_digest(sent.encode(), ("Bearer " + self.secret).encode()):
            raise web.HTTPUnauthorized()

    # --- results ------------------------------------------------------------------
    def store_result(self, msg):
        kind = msg.get("kind")
        files = KINDS | EXTRA_KINDS
        if kind not in files:
            return False
        rec = {k: v for k, v in msg.items() if k != "type"} | {"received": datetime.now(timezone.utc).isoformat()}
        append_jsonl(self.dir / f"{files[kind]}.jsonl", rec)
        if kind == "memory_test":
            self.store_items(rec)
        self.last[kind] = rec
        save_json(self.dir / "last.json", self.last)
        return True

    def store_items(self, rec):
        """memory_tests.jsonl: one row per item of a memory test (day = the day the item was stored)."""
        thr = (rec.get("thresholds") or {}).get("hc")
        try:
            meta = load_json(self.dir / "item_meta.json", {}) or {}   # #79: host / kind of each reading (pod_manager)
        except OSError:
            meta = {}
        rows = []
        for s in rec.get("scores") or []:
            if not isinstance(s, dict) or "hc" not in s:
                continue
            day = s.get("item_day") or rec.get("day")
            rows.append({"day": day, "days_since": _days(day, rec.get("day")), "item": str(s.get("item") or s.get("text", ""))[:200],
                         "source": s.get("source") if s.get("source") in ("reading", "taught") else "chat",
                         "recalled": bool(s.get("hc_recalled")), "score": s.get("hc"), "threshold": thr,
                         "label": rec.get("label"), "test_day": rec.get("day"), "session": rec.get("session"),
                         "received": rec["received"]})
            m = meta.get(rows[-1]["item"]) if rows[-1]["source"] == "reading" else None
            if isinstance(m, dict):
                rows[-1].update(host=str(m.get("host") or ""), kind=str(m.get("kind") or ""))
        if rows:
            append_jsonl(self.dir / ITEMS_FILE, *rows)
        return rows

    def memory(self, max_lines=2000):
        """Readings of the latest next-day test (the previous session's items, cued in the next session); if no
        next-day test of readings exists yet, the latest test after sleep. One test = one session's rows."""
        try:
            lines = (self.dir / ITEMS_FILE).read_text().splitlines()[-max_lines:]
        except OSError:
            lines = []
        rows = []
        for ln in lines:
            try:
                rows.append(json.loads(ln))
            except ValueError:
                pass
        out = {"day": None, "label": None, "items": [], "note": MEMORY_NOTE}
        key = lambda r: (r.get("session") or "", r.get("label"), r.get("test_day"))     # one test
        for label in ("next day", "after sleep"):
            sel = [r for r in rows if r.get("label") == label and r.get("source") == "reading"]
            if not sel:
                continue
            newest = max(sel, key=lambda r: r.get("received", ""))
            day = max(r.get("day") or "" for r in sel if key(r) == key(newest))              # its latest item day
            test = [r for r in rows if key(r) == key(newest) and r.get("day") == day]
            by_item = {}                                                # one row per item, in test order
            for r in test:
                by_item[(r["item"], r["source"])] = {k: r.get(k) for k in ("item", "source", "recalled", "score", "threshold",
                                                                            "host", "kind")}
            items = list(by_item.values())
            items.sort(key=lambda r: (r["source"] != "reading", not r["recalled"]))
            out.update(day=day, label=label, tested=newest.get("received"), items=items,
                       test_day=newest.get("test_day"), days_since=newest.get("days_since"))
            break
        return out

    def taught_results(self, max_lines=2000):
        """{(day, item): row} of the latest next-day test of each taught item (re-read only when the file changes)."""
        path = self.dir / ITEMS_FILE
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            return {}
        if getattr(self, "_taught", (None,))[0] != mtime:
            out = {}
            for ln in path.read_text().splitlines()[-max_lines:]:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(r, dict) and r.get("source") == "taught" and r.get("label") == "next day":
                    k = (r.get("day"), r.get("item"))
                    if k not in out or r.get("received", "") >= out[k].get("received", ""):
                        out[k] = r
            self._taught = (mtime, out)
        return self._taught[1]

    async def memory_get(self, request):
        return web.json_response(self.memory())

    # --- forwards to the pod (sync entry points: they schedule the send) --------------
    @property
    def connected(self):
        return self.ws is not None and not self.ws.closed

    def _spawn(self, coro):
        t = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return t

    async def _send(self, msg):
        ws = self.ws
        if ws is not None and not ws.closed:
            try:
                await ws.send_json(msg)
                return True
            except Exception:
                pass
        return False

    def forward(self, msg):
        if not self.connected:
            return False
        self._spawn(self._send(msg))
        return True

    def forward_chat(self, text, emotion="neutral"):
        return self.forward({"type": "chat", "text": text, "emotion": emotion})

    def forward_good(self):
        if not self.connected or self.clock() - self._good < GOOD_MIN_S:
            return False
        self._good = self.clock()
        return self.forward({"type": "good"})

    def forward_sleep(self, stage):
        """Forward the sleep engine stage when it changes (called every tick, cheap when unchanged); the pod
        manager follows it in day-live mode."""
        if stage == self.stage:
            return False
        self.stage = stage
        if self._manager is not None and hasattr(self._manager, "on_stage"):
            self._manager.on_stage(stage)
        return self.forward({"type": "sleep", "stage": stage})

    async def send_night(self, payload):
        """End the pod's live phase: the night phases run with this config (day, items, decisions)."""
        self.live_ready = False
        return await self._send({k: v for k, v in payload.items() if k != "type"} | {"type": "night"})

    # --- live decisions (#58) ------------------------------------------------------
    def _log_decision(self, row):
        day = datetime.now(ROME).date().isoformat()
        try:
            append_jsonl(self.dir / DECISIONS_FILE.format(day=day), row | {"t": round(time.time(), 3)})
        except OSError:
            pass
        return day

    async def decide(self, options, kind="browse", deadline_ms=2000, decision_id=None):
        """Ask the GPU network to choose among `options` (2-8 labels). Returns the decision or None."""
        opts = [str(o)[:200] for o in (options or [])]
        if not self.live_ready or not self.connected or not 2 <= len(opts) <= MAX_OPTIONS:
            return None
        did = str(decision_id or secrets.token_hex(8))[:64]
        fut = asyncio.get_running_loop().create_future()
        self._waiting[did] = fut
        self.decide_stats["asked"] += 1
        t0 = time.monotonic()
        try:
            if not await self._send({"type": "decide", "id": did, "options": opts, "kind": str(kind),
                                     "deadline_ms": int(deadline_ms)}):
                return None
            try:
                d = await asyncio.wait_for(fut, max(0.05, deadline_ms / 1000.0))
            except asyncio.TimeoutError:
                self.decide_stats["timeouts"] += 1
                print(f"spiking: no GPU decision within {int(deadline_ms)} ms (fallback)", flush=True)
                return None
        finally:
            self._waiting.pop(did, None)
            self._race_until = self.clock() + RACE_SHOW_S
        pick, rates = d.get("pick"), d.get("pool_rates")
        if not isinstance(pick, int) or isinstance(pick, bool) or not 0 <= pick < len(opts):
            return None
        rates = [float(x) for x in rates] if isinstance(rates, list) and len(rates) == len(opts) else None
        out = {"id": did, "pick": pick, "pool_rates": rates, "sim_ms": d.get("sim_ms"),
               "n_neurons": d.get("n_neurons"), "net": "gpu", "label": NET_LABEL,
               "rtt_ms": round((time.monotonic() - t0) * 1000, 1)}
        self.decide_stats["answered"] += 1
        day = self._log_decision({"id": did, "kind": str(kind), "options": opts, "pick": pick, "net": "gpu",
                                  "pool_rates": rates, "sim_ms": out["sim_ms"], "rtt_ms": out["rtt_ms"]})
        self.answered[did] = day
        while len(self.answered) > MAX_ANSWERED:
            self.answered.popitem(last=False)
        return out

    def reward(self, decision_id, value):
        """Dopamine for a decision the GPU network made (False if it did not make it or no pod is connected)."""
        did = str(decision_id)
        try:
            value = float(value)
        except (TypeError, ValueError):
            return False
        if did not in self.answered or not math.isfinite(value):
            return False
        self.answered.pop(did)
        self._log_decision({"id": did, "reward": value})
        self.decide_stats["rewards"] += 1
        return self.forward({"type": "reward", "id": did, "value": value})

    async def forward_stop(self):
        return await self._send({"type": "stop"})

    # --- websocket from the pod ----------------------------------------------------
    async def pod_ws(self, request):
        self.check(request)
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=MAX_WS_MSG)
        await ws.prepare(request)
        old, self.ws = self.ws, ws
        if old is not None and not old.closed:
            await old.close()
        self.session, self.live_ready = None, False
        if self.stage:
            await ws.send_json({"type": "sleep", "stage": self.stage})
        try:
            async for m in ws:
                if m.type == aiohttp.WSMsgType.TEXT:
                    await self.on_frame(m.data)
        finally:
            if self.ws is ws:
                self.ws, self.session, self.last_state, self.live_ready = None, None, None, False
                if self.manager:
                    self.manager.on_disconnect()
                await self.live.broadcast({"type": "spiking", "live": False})
        return ws

    async def on_frame(self, data):
        try:
            d = json.loads(data)
        except ValueError:
            return
        if not isinstance(d, dict):
            return
        kind = d.get("type")
        if kind == "hello":
            self.session = {k: d.get(k) for k in ("session", "n_neurons", "device", "phases")}
            self.sample = self.gpu_sample(d.get("n_neurons"))
            if self.manager:
                self.manager.on_hello(d)
        elif kind == "state":
            self.last_state = d
            if self.manager:
                self.manager.on_state(d)
            now = self.clock()
            if now - self._relayed >= RELAY_MIN_S:
                self._relayed = now
                race = bool(self._waiting) or now < self._race_until
                await self.relay(frames.viewer_frame({"net": "gpu"} | {k: v for k, v in d.items() if k != "type"}
                                                     | {"type": "spiking"}, self.sample, race=race))
        elif kind == "result":
            self.store_result(d)
        elif kind == "live_ready":
            self.live_ready = True
            print(f"spiking: GPU network answers decisions ({d.get('n_neurons')} neurons)", flush=True)
        elif kind == "decision":
            fut = self._waiting.get(str(d.get("id")))
            if fut is not None and not fut.done():
                fut.set_result(d)
        elif kind == "done":
            if self.manager:
                self.manager.on_done(d)
            await self.live.broadcast({"type": "spiking", "live": False, "done": True, "ok": bool(d.get("ok"))})

    # --- frames for the pages (#62) -------------------------------------------------
    def gpu_sample(self, n_neurons):
        """Which region and slot each of the GPU raster's 200 rows is (frames.gpu_sample, cached per network size)."""
        try:
            n = int(n_neurons)
        except (TypeError, ValueError):
            return frames.Sample.one_per_region(200, 214)
        if n not in self._samples:
            self._samples[n] = frames.gpu_sample(n)
        return self._samples[n]

    async def relay(self, frame):
        """A spiking frame of either network to the pages, through the shared per-viewer budget (frames.Budget)."""
        out = self.budget.fit(frame)
        if out is not None:
            await self.live.broadcast(out)
        return out

    # --- weights ------------------------------------------------------------------
    async def weights_get(self, request):
        self.check(request)
        path = self.dir / "weights.npz"
        if not path.exists():
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    async def weights_post(self, request):
        """Stream the body to a temp file (request.content is not subject to client_max_size), then swap atomically."""
        self.check(request)
        tmp = self.dir / "weights.upload.tmp"
        size, head = 0, b""
        try:
            with open(tmp, "wb") as f:
                async for chunk in request.content.iter_chunked(1 << 20):
                    size += len(chunk)
                    if size > MAX_WEIGHTS:
                        raise web.HTTPRequestEntityTooLarge(max_size=MAX_WEIGHTS, actual_size=size)
                    head = head or chunk[:2]
                    f.write(chunk)
            if size == 0 or head != b"PK":                      # an npz is a zip archive
                raise web.HTTPBadRequest(text="expected an npz body")
            cur = self.dir / "weights.npz"
            if cur.exists():
                os.replace(cur, self.dir / "weights.prev.npz")
            os.replace(tmp, cur)
        finally:
            tmp.unlink(missing_ok=True)
        return web.json_response({"ok": True, "bytes": size})

    async def result_post(self, request):
        self.check(request)
        try:
            d = await request.json()
        except ValueError:
            raise web.HTTPBadRequest(text="bad json")
        if not isinstance(d, dict) or not self.store_result(d):
            raise web.HTTPBadRequest(text="unknown result kind")
        return web.json_response({"ok": True})

    # --- page ---------------------------------------------------------------------
    def learning(self):
        """The real decisions' learning curve (choice.payoff_by_day) over the last LEARNING_DAYS Tokyo days, from
        the decision logs and the night replays; cached for LEARNING_TTL_S."""
        t, cached = self._learning
        if cached is not None and time.monotonic() - t < LEARNING_TTL_S:
            return cached
        from spiking.choice import payoff_by_day
        today = datetime.now(ROME).date()
        rows = {}
        for k in range(LEARNING_DAYS - 1, -1, -1):
            day = (today - timedelta(days=k)).isoformat()
            for name in LEARNING_FILES:
                try:
                    lines = (self.dir / name.format(day=day)).read_text().splitlines()
                except OSError:
                    continue
                for ln in lines:
                    try:
                        rows.setdefault(day, []).append(json.loads(ln))
                    except ValueError:
                        continue
        first = (today - timedelta(days=LEARNING_DAYS - 1)).isoformat()
        replays = []
        try:
            for ln in (self.dir / f"{EXTRA_KINDS['choice_replay']}.jsonl").read_text().splitlines()[-200:]:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(r, dict) and str(r.get("day") or "") >= first:
                    replays.append(r)
        except OSError:
            pass
        out = {"days": payoff_by_day(rows, replays), "note": LEARNING_NOTE}
        self._learning = (time.monotonic(), out)
        return out

    def status(self):
        mgr = self.manager.status() if self.manager else {}
        live = bool(mgr.get("live")) if mgr else self.connected and self.session is not None
        session = mgr.get("session") if mgr else None
        if session is None and self.session:
            session = {"session_id": self.session.get("session"), "device": self.session.get("device"),
                       "n_neurons": self.session.get("n_neurons")}
        return {"live": live, "session": session, "next_session": mgr.get("next_session") if mgr else None,
                "day_live": mgr.get("day_live") if mgr else None,
                "decisions": {"live_ready": self.live_ready, **self.decide_stats},
                "stream": dict(self.budget.sent),
                "learning": self.learning(),
                "last": {k: self.last.get(k) for k in KINDS},
                "spend": mgr.get("spend") or CostLog(self.dir / "costs.jsonl").summary()}

    async def status_get(self, request):
        return web.json_response(self.status())


def attach(app, live, data_dir, secret=None):
    """Register the routes; the hub is also stored under `SPIKING_KEY` and `live.spiking`."""
    hub = SpikingHub(live, data_dir, secret)
    app[SPIKING_KEY] = hub
    live.spiking = hub
    app.router.add_get("/api/spiking/pod", hub.pod_ws)
    app.router.add_get("/api/spiking/weights", hub.weights_get)
    app.router.add_post("/api/spiking/weights", hub.weights_post)
    app.router.add_post("/api/spiking/result", hub.result_post)
    app.router.add_get("/api/spiking/status", hub.status_get)
    app.router.add_get("/api/memory", hub.memory_get)
    return hub
