"""One GPU session on the pod: `python -m spiking.session` (config in the SUB01_SESSION env var, JSON).

Loads the learned weights (from the server, or none), runs the phases, streams compact state to the server over
a websocket authenticated with SUB01_POD_SECRET, writes /out/status.json + /out/results.json (read by
validate / pod_manager through the pod's port 8000) and uploads the learned weights at the end.
Phases: bench, rates, delays, recall_yesterday, encode, pong_train, pong_exam, choice_train, choice_exam,
memory_test, sleep, free, live_decide, live_bench, live_learn.
Items (cfg "items") are the day's chat messages and readings, each {text, source: chat|reading, item}; a reading's
text is its title + keywords. recall_yesterday tests the previous session's items before anything new is stored.
In validate mode extra controls run (no-plasticity Pong, random paddle, sleep without replay).
choice_train / choice_exam (spiking/choice.py): the K-armed choice task with its controls (frozen network on the
same trials, random chooser, reversal halfway). With cfg "decisions" (the day's real decisions, #58) choice_train
replays them instead.
Day mode (#58, docs/spiking/live.md): live_decide keeps the network running (at most at real time) through his
waking hours and answers the server's {"type": "decide"} messages with the race on the real option labels
(choice.LiveChooser); {"type": "reward"} applies the dopamine to that decision. The learned weights are uploaded
every `upload_every_min` (30) minutes and at the end. {"type": "night", "day", "items", "decisions"} ends the
phase; the remaining phases (the night: recall_yesterday, encode, choice_train on the day's decisions, sleep,
memory_test) then run on the same pod with that config. The decision read-out is cfg "live_readout" (choice.Readout:
race / scaled / diff / window); live_learn measures them all (#70, docs/spiking/choice.md).
"""
import json
import math
import os
import queue
import sys
import threading
import time
import traceback
import urllib.request
from collections import OrderedDict, deque
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import torch

from .choice import (READOUTS, ChoiceTask, LiveChooser, RewardSchedule, bandit_experiment, random_chooser,
                     replay_fit, summarize)
from .config import Config
from .frames import quantise_rates
from .memory import MemorySystem, sleep_block, words
from .net import SpikingNet
from .pong import Pong, random_paddle, tracking_paddle

ROOT = Path(__file__).resolve().parent.parent
GROUP_KEYS = ("visual", "somatomotor", "attention", "salience", "limbic", "control", "default", "reward", "fear",
              "memory", "relay", "language")
MAX_OPTIONS = 8                     # a decide message with more options is refused
MAX_PENDING = 256                   # decisions waiting for their reward (oldest dropped)
PENDING_S = 3 * 3600                # a reward later than this finds no eligibility left
MAX_DECISIONS = 400                 # real decisions replayed at night


class StopSession(Exception):
    pass


# --- link to the Railway server (optional) ----------------------------------------------------------------------
class Link:
    """Websocket to the server in a background thread; frames out via a queue, commands in via a queue."""

    def __init__(self, server, secret, session_id):
        self.server, self.secret, self.sid = server.rstrip("/"), secret, session_id
        self.out, self.inbox = queue.Queue(maxsize=200), queue.Queue()
        self.connected = False
        self.connects = 0                                                # live_decide re-announces itself on each
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        import asyncio
        asyncio.run(self._main())

    async def _main(self):
        import asyncio
        import aiohttp
        url = self.server.replace("https://", "wss://").replace("http://", "ws://") + f"/api/spiking/pod?session={self.sid}"
        headers = {"Authorization": "Bearer " + self.secret}
        while not self.stop.is_set():
            try:
                async with aiohttp.ClientSession() as http, http.ws_connect(url, headers=headers, heartbeat=20,
                                                                           max_msg_size=1 << 20) as ws:
                    self.connected = True
                    self.connects += 1

                    async def reader():
                        async for m in ws:
                            if m.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    self.inbox.put(json.loads(m.data))
                                except ValueError:
                                    pass
                    rd = asyncio.ensure_future(reader())
                    while not self.stop.is_set() and not rd.done():
                        try:
                            msg = self.out.get_nowait()
                            await ws.send_str(json.dumps(msg))
                        except queue.Empty:
                            await asyncio.sleep(0.05)
                    while not self.out.empty():                          # flush (done frame) before closing
                        await ws.send_str(json.dumps(self.out.get_nowait()))
                    rd.cancel()
            except Exception as e:
                print("link error:", type(e).__name__, flush=True)
            self.connected = False
            if not self.stop.is_set():
                await asyncio.sleep(3)

    def send(self, msg):
        try:
            self.out.put_nowait(msg)
        except queue.Full:                                               # drop state frames rather than block the sim
            pass

    def close(self, timeout=10):
        t0 = time.time()
        while not self.out.empty() and time.time() - t0 < timeout:
            time.sleep(0.1)
        self.stop.set()

    def _req(self, path, method="GET", data=None, ctype="application/octet-stream", timeout=300):
        req = urllib.request.Request(self.server + path, method=method, data=data,
                                     headers={"Authorization": "Bearer " + self.secret, "Content-Type": ctype,
                                              "User-Agent": "sub01-pod/1.0"})
        return urllib.request.urlopen(req, timeout=timeout)

    def get_weights(self, path):
        try:
            with self._req("/api/spiking/weights") as r:
                Path(path).write_bytes(r.read())
            return True
        except Exception as e:
            print("no learned weights from server:", type(e).__name__, getattr(e, "code", ""), flush=True)
            return False

    def put_weights(self, path):
        with self._req("/api/spiking/weights", "POST", Path(path).read_bytes()) as r:
            return r.status


# --- the session ---------------------------------------------------------------------------------------------
class Session:
    def __init__(self, cfg, out_dir, link=None):
        self.cfg = cfg
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.link = link
        self.t_wall0 = time.time()
        self.deadline = self.t_wall0 + 60 * float(cfg.get("max_minutes", 55)) - 120   # 2 min to save + upload
        self.results = {"session_id": cfg.get("session_id"), "day": cfg.get("day"), "validate": bool(cfg.get("validate")),
                        "phases": {}, "files": []}
        self.phase, self.progress = "start", 0.0
        self.last_frame_wall, self.last_frame_t, self.last_frame_n, self.frame_snap = 0.0, 0, 0, None
        self.pong = None
        self.choice = None
        self.stage = "AWAKE"
        self.chat_until = -1
        self.stopping = False
        self.live = None                    # choice.LiveChooser (live_decide, night replay)
        self.decide_q, self.reward_q = deque(), deque()
        self.pending = OrderedDict()        # decision id -> (wall time, eligibility)
        self.night = None                   # the night message once received
        self.live_stats = {"decisions": 0, "rewards": 0, "late": 0, "refused": 0, "unknown_reward": 0,
                           "wall_ms": [], "uploads": 0, "upload_errors": 0}
        self._upload = None                 # background weight upload thread
        self.live_rt = None                 # live_decide: simulated / wall time
        self.status()

    # --- status / streaming -------------------------------------------------------------------------------------
    def status(self, done=False, error=None):
        st = {"phase": self.phase, "progress": round(self.progress, 3), "done": done, "error": error,
              "t_sim": round(getattr(self, "net", None).t / 1000.0, 1) if getattr(self, "net", None) else 0.0,
              "wall_s": round(time.time() - self.t_wall0, 1)}
        tmp = self.out / "status.json.tmp"
        tmp.write_text(json.dumps(st))
        tmp.replace(self.out / "status.json")

    def log(self, *a):
        print(f"[{time.time() - self.t_wall0:7.1f}s] {self.phase}:", *a, flush=True)

    def hook(self, net):
        now = time.time()
        if now > self.deadline and not self.stopping:
            self.stopping = True
            raise StopSession("deadline")
        if self.chat_until >= 0 and net.t >= self.chat_until:
            net.set_neuron_drive("chat", None)
            self.chat_until = -1
        if now - self.last_frame_wall >= 0.25:
            self.frame(net, now)
        if self.link is not None:
            while True:
                try:
                    msg = self.link.inbox.get_nowait()
                except queue.Empty:
                    break
                self.command(msg)

    def frame(self, net, now):
        if self.frame_snap is None:
            self.frame_snap, self.last_frame_wall, self.last_frame_t = net.snapshot(), now, net.t
            return
        dt_steps = max(1, net.t - self.last_frame_t)
        rr = net.region_rates_since(self.frame_snap)
        groups = net.group_rates(rr)
        n_sp = float((net.region_count - self.frame_snap[2]).sum())
        wall = max(1e-6, now - self.last_frame_wall)
        sim_s = dt_steps * net.cfg.dt / 1000.0
        if int(now) % 5 == 0:
            self.status()
        if self.link is not None:
            p = net.plast
            msg = {"type": "state", "t_sim": round(net.t / 1000.0, 2), "phase": self.phase, "n_neurons": net.n,
                   "spikes_per_s": round(n_sp / sim_s, 1), "mean_rate_hz": round(n_sp / sim_s / net.n, 3),
                   "steps_per_s": round(dt_steps / wall, 1), "realtime_x": round(sim_s / wall, 3),
                   "groups": {k: round(v, 2) for k, v in groups.items() if k in GROUP_KEYS},
                   "rq": quantise_rates(rr),                  # per-region rates, 1 byte each, for the 3D neurons (#62)
                   "raster": {"n": len(net.raster_ids), "t0": int(self.last_frame_t), "t1": int(net.t),
                              "spikes": net.pop_raster(self.last_frame_t)[:4000]},
                   "pong": self.pong.shown.frame() if (self.pong is not None and "pong" in self.phase) else None,
                   "choice": self.choice.last if (self.choice is not None and "choice" in self.phase) else None,
                   "dopamine": (self.choice.last or {}).get("dopamine", 0.0) if (self.choice is not None and "choice" in self.phase)
                   else (round(p.mod["da"], 3) if p is not None else 0.0)}
            self.link.send(msg)
        else:
            net.raster_log.clear() if net.raster_rows is not None else None
        self.frame_snap, self.last_frame_wall, self.last_frame_t = net.snapshot(), now, net.t

    def command(self, msg):
        kind = msg.get("type")
        if kind == "stop":
            self.stopping = True
            raise StopSession("stop requested")
        if kind == "decide":
            self.decide_q.append((msg, time.time()))
            return
        if kind == "reward":
            self.reward_q.append(msg)
            return
        if kind == "night":
            self.night = msg
            return
        if kind == "good" and self.pong is not None and self.phase in ("pong_train", "free"):
            self.pong.good()
        elif kind == "sleep" and msg.get("stage") in ("AWAKE", "NREM", "REM"):
            self.stage = msg["stage"]
        elif kind == "chat" and isinstance(msg.get("text"), str):
            ws = words(msg["text"])                              # only in the free run: never during exams / tests
            if ws and getattr(self, "mem", None) is not None and self.phase == "free":
                self.net.set_neuron_drive("chat", self.mem.pattern(ws), 4.0)
                self.chat_until = self.net.t + 300
                self.pending_chat.append(msg["text"])

    def result(self, kind, payload):
        rec = {"type": "result", "kind": kind, "day": self.cfg.get("day"), "session": self.cfg.get("session_id"),
               **payload}
        self.results["phases"].setdefault(kind, []).append(payload)
        if self.link is not None:
            self.link.send(rec)
        self.save_results()

    def save_results(self):
        tmp = self.out / "results.json.tmp"
        tmp.write_text(json.dumps(self.results, indent=1, default=float))
        tmp.replace(self.out / "results.json")

    # --- build --------------------------------------------------------------------------------------------------
    def build(self):
        c = self.cfg
        self.phase = "build"
        self.status()
        dev = c.get("device") or ("cuda" if torch.cuda.is_available() else "cpu")
        conf = Config(n_neurons=int(c.get("n_neurons", 20_000)), seed=int(c.get("seed", 1)),
                      **{k: v for k, v in (c.get("config") or {}).items()})
        t0 = time.time()
        self.net = net = SpikingNet(conf, device=dev, verbose=True)
        self.results["build"] = {"device": dev, "gpu": torch.cuda.get_device_name(0) if str(dev).startswith("cuda") else None,
                                 "n_neurons": net.n, "synapses": net.n_syn, "max_delay_ms": net.D - 1,
                                 "plastic_synapses": net.plast.P if net.plast else 0, "build_s": round(time.time() - t0, 1),
                                 "config_hash": conf.config_hash(), "config": conf.to_dict(),
                                 "torch": torch.__version__}
        try:
            from real_baseline import RealBaseline
            net.attach_baseline(RealBaseline(net.reg.names, ROOT / "out" / "rest"))
            self.results["build"]["baseline_runs"] = len(net.baseline.files)
        except Exception as e:
            self.log("no recorded baseline:", type(e).__name__)
        net.enable_raster(200)
        self.mem = MemorySystem(net)
        self.pending_chat = []
        wpath = self.out / "weights_in.npz"
        meta = None
        if self.link is not None and self.link.get_weights(wpath):
            pass
        if wpath.exists() and net.plast is not None:
            try:
                meta = net.plast.load(wpath, elapsed_days=float(c.get("elapsed_days", 0.0)))
                self.mem.from_meta(meta)
                self.log("loaded learned weights:", net.plast.stats())
            except Exception as e:
                self.log("could not load learned weights:", e)
        self.results["build"]["weights_loaded"] = meta is not None
        net.hook = self.hook
        if self.link is not None:
            self.link.send({"type": "hello", "session": c.get("session_id") or self.link.sid, "n_neurons": net.n,
                            "device": self.results["build"]["gpu"] or dev, "phases": c.get("phases")})
        net.run(500)                                                     # settle

    # --- phases -------------------------------------------------------------------------------------------------
    def ph_bench(self):
        net = self.net
        out = {}
        p = net.plast
        for label, frozen in (("plasticity_off", True), ("plasticity_on", False)):
            if p is not None:
                p.frozen = frozen
            net.run(200)
            net.sync()
            t0, s0, n0 = time.time(), net.t, net.n_spikes
            ms = int(self.cfg.get("bench_ms", 5000))
            for k in range(0, ms, 1000):                     # with learning on, a reward every second (as in Pong)
                if p is not None and not frozen:
                    p.dopamine(0.8)
                net.run(min(1000, ms - k))
            net.sync()
            wall = time.time() - t0
            steps = net.t - s0
            out[label] = {"steps_per_s": round(steps / wall, 1), "realtime_x": round(steps / wall / 1000.0, 3),
                          "mean_rate_hz": round((net.n_spikes - n0) / net.n / (steps / 1000.0), 3)}
        if p is not None:
            p.frozen = False
        out.update(n_neurons=net.n, synapses=net.n_syn, gpu=self.results["build"]["gpu"],
                   gpu_mem_gb=round(net.memory_gb(), 2) if net.memory_gb() else None,
                   steps_per_s=out["plasticity_on"]["steps_per_s"], realtime_x=out["plasticity_on"]["realtime_x"])
        self.result("bench", out)

    def ph_rates(self):
        """Mean rates per population over a minute with the recorded drive; runaway check."""
        net = self.net
        secs = int(self.cfg.get("rates_s", 60))
        per_s, e_rates, i_rates = [], [], []
        exc = torch.as_tensor(net.is_exc_np, device=net.device)
        for k in range(secs):
            snap = net.snapshot()
            net.run(1000)
            r = net.rates_since(snap)
            per_s.append(net.region_rates_since(snap))
            e_rates.append(float(r[exc].mean()))
            i_rates.append(float(r[~exc].mean()))
            self.progress = (k + 1) / secs
        rr = np.array(per_s)
        neuron_rates = None
        snap = net.snapshot()
        net.run(2000)
        nr = net.rates_since(snap).cpu().numpy()
        out = {"seconds": secs, "mean_e_hz": round(float(np.mean(e_rates)), 3), "mean_i_hz": round(float(np.mean(i_rates)), 3),
               "region_rate_pct": {str(q): round(float(np.percentile(rr, q)), 3) for q in (1, 5, 50, 95, 99)},
               "region_rate_max": round(float(rr.max()), 3),
               "groups": {k: round(v, 3) for k, v in net.group_rates(rr.mean(0)).items()},
               "per_second_e": [round(x, 3) for x in e_rates],
               "neuron_rate_pct": {str(q): round(float(np.percentile(nr, q)), 3) for q in (5, 50, 95, 99)},
               "frac_silent_2s": round(float(np.mean(nr == 0)), 4),
               "runaway": bool(rr.max() > 50 or np.mean(e_rates) > 15)}
        self.result("rates", out)

    def ph_delays(self):
        net = self.net
        reg = net.reg
        long = (net.kind == 2)
        src_r = net.region_of[net.src[long].long()].cpu().numpy()
        dst_r = net.region_of[net.dst[long].long()].cpu().numpy()
        d = net.delay[long].cpu().numpy().astype(float)
        expect = np.maximum(1, np.round(reg.lengths[src_r, dst_r] / net.cfg.velocity_mm_ms))
        sample = np.random.default_rng(0).choice(len(d), size=min(len(d), 200_000), replace=False)
        out = {"n_long_synapses": int(long.sum()), "max_abs_error_ms": float(np.abs(d - expect).max()),
               "delay_ms_pct": {str(q): float(np.percentile(d[sample], q)) for q in (5, 50, 95)},
               "fibre_mm_pct": {str(q): round(float(np.percentile(reg.lengths[src_r[sample], dst_r[sample]], q)), 1)
                                for q in (5, 50, 95)},
               "velocity_m_s": net.cfg.velocity_mm_ms}
        self.result("delays", out)

    def day_items(self):
        """The day's items: cfg "items" ({text, source: chat|reading|taught, item}), else cfg "messages" as chat; max 5
        of each source."""
        raw = self.cfg.get("items")
        if raw is None:
            raw = [{"text": m["text"] if isinstance(m, dict) else str(m), "source": "chat"}
                   for m in (self.cfg.get("messages") or [])]
        out, n = [], {}
        for it in raw:
            src = it.get("source") if it.get("source") in ("reading", "taught") else "chat"
            if it.get("text") and n.get(src, 0) < MAX_PER_SOURCE:
                n[src] = n.get(src, 0) + 1
                out.append({"text": str(it["text"]), "source": src, "item": str(it.get("item") or it["text"])})
        return out

    def ph_encode(self, items=None, day=None):
        items = self.day_items() if items is None else items
        day = day or self.cfg.get("day")
        stored = []
        for i, it in enumerate(items):
            r = self.mem.encode(it["text"], day, it["source"], it["item"])
            if r:
                stored.append({"text": it["text"], "item": it["item"], "source": it["source"], "words": r["words"],
                               "drive_rate": round(r["drive_rate"], 2)})
            self.progress = (i + 1) / max(1, len(items))
        self.result("encode", {"stored": stored, "n_registry": len(self.mem.registry)})

    def ph_memory_test(self, label=None, items=None, day=None):
        res = self.mem.test(day or self.cfg.get("day"), lures=int(self.cfg.get("lures", 6)), items=items)
        res.pop("kind", None)
        if label:
            res["label"] = label
        self.result("memory_test", res)
        return res

    def ph_recall_yesterday(self, today=None):
        """Half-cue recall of the previous session's items, a day later (after forgetting), before new encoding."""
        today = today or self.cfg.get("day")
        days = sorted({m.get("day") for m in self.mem.registry if m.get("day") and m.get("day") != today})
        if not days:
            self.result("memory_test", {"label": "next day", "skipped": "nothing stored on an earlier day",
                                        "scores": [], "recalled": []})
            return None
        items = [m for m in self.mem.registry if m.get("day") == days[-1]]
        return self.ph_memory_test("next day", items=items, day=today)

    def _pong(self):
        if self.pong is None:
            self.pong = Pong(self.net, seed=int(self.cfg.get("seed", 1)))
        return self.pong

    def _exam_no_learning(self, rallies, game_seed=None):
        """Control: the same network with every learned change removed (frozen), same exam."""
        p = self.net.plast
        if p is None:
            return self._pong().exam(rallies, game_seed=game_seed)
        dw, theta = p.dw.clone(), self.net.theta.clone()
        p.dw.zero_()
        p._apply()
        self.net.theta.zero_()                                       # also the homeostatic excitability
        self.net._dirty = True
        try:
            return self._pong().exam(rallies, game_seed=game_seed)
        finally:
            p.dw.copy_(dw)
            p._apply()
            self.net.theta.copy_(theta)
            self.net._dirty = True

    def ph_pong_train(self):
        pong = self._pong()
        minutes = float(self.cfg.get("pong_train_minutes", 10))
        blocks = int(self.cfg.get("pong_blocks", 0)) or None
        t_end = self.net.t + minutes * 60_000
        n = 0
        while (blocks is None and self.net.t < t_end) or (blocks is not None and n < blocks):
            pong.train(1, int(self.cfg.get("block_rallies", 20)))
            n += 1
            self.progress = min(1.0, (n / blocks) if blocks else 1 - (t_end - self.net.t) / (minutes * 60_000))
            self.log("block", pong.curve[-1])
        self.result("pong_curve", {"points": pong.curve, "block_rallies": int(self.cfg.get("block_rallies", 20))})

    def ph_pong_exam(self, label="exam"):
        pong = self._pong()
        rallies = int(self.cfg.get("exam_rallies", 20))
        seed = 1000 + len(self.results["phases"].get("exam", []))
        exam = pong.exam(rallies, game_seed=seed)
        ctrl = self._exam_no_learning(rallies, game_seed=seed) if self.net.plast is not None else None
        rnd = random_paddle(2000, seed=int(self.cfg.get("seed", 1)))
        out = {"label": label, **exam, "controls": {"no_plasticity": ctrl["hit_rate"] if ctrl else None,
                                                     "no_plasticity_hits": ctrl["hits"] if ctrl else None,
                                                     "random": rnd["hit_rate"]}}
        self.result("exam", out)
        return out

    # --- choice task (spiking/choice.py) ----------------------------------------------------------------------------
    def _choice(self):
        if self.choice is None:
            c = self.cfg
            kw = {k[len("choice_"):]: c[k] for k in ("choice_cue_frac", "choice_eta", "choice_bonus_mv", "choice_thr_z",
                                                       "choice_timeout_ms", "choice_iti_ms", "choice_alpha") if k in c}
            k = int(c.get("choice_k", 4))
            self.choice = ChoiceTask(self.net, labels=c.get("choice_labels"), k=k, probs=c.get("choice_probs"),
                                     seed=int(c.get("seed", 1)), **kw)
            self.choice.calibrate()
        return self.choice

    def ph_choice_train(self):
        """Frozen control on the same trials first (no weight change), then training with dopamine; reversal halfway;
        a random chooser on the same schedule. All three in one result, whatever the numbers are. With the day's
        real decisions in cfg "decisions" (day mode), they are replayed instead (ph_choice_replay)."""
        if self.cfg.get("decisions"):
            return self.ph_choice_replay()
        task = self._choice()
        n = int(self.cfg.get("choice_trials", 200))
        rev = n // 2 if self.cfg.get("choice_reversal", True) else None
        seed = int(self.cfg.get("seed", 1))
        frozen = task.run(n, RewardSchedule(task.probs, rev, seed=seed), mode="exam")
        self.progress = 0.5
        t0 = task.trial
        learned = task.train(n, RewardSchedule(task.probs, rev, seed=seed),
                             on_trial=lambda tr: setattr(self, "progress", 0.5 + 0.5 * (task.trial - t0) / n))
        out = {"k": task.k, "labels": task.labels, "probs": task.probs, "trials": n, "reversal_at": rev,
               "criterion": "14 of the last 20 trials correct", "calibration": task.calib,
               "pool_sizes": [len(pl) for pl in task.pools(range(task.k))], "cue_sizes": [len(c) for c in task.cues],
               "cue_pool_synapses": task.synapse_count(),
               "learned": {**summarize(learned["correct"], learned["rewards"], rev), "timeout_frac": learned["timeout_frac"],
                           "mean_rt_ms": learned["mean_rt_ms"]},
               "frozen": {**summarize(frozen["correct"], frozen["rewards"], rev), "timeout_frac": frozen["timeout_frac"]},
               "random": random_chooser(RewardSchedule(task.probs, rev, seed=seed), n, task.k, seed=seed + 1),
               "dw_cue_pool_mean_mv": task.dw_stats()}
        self.log("learned", out["learned"]["trials_to_criterion"], out["learned"].get("trials_to_criterion_after_reversal"),
                 "frozen", out["frozen"]["frac_correct"], "random", out["random"]["frac_correct"])
        self.result("choice_curve", out)

    def real_decisions(self):
        """cfg "decisions" with a reward, at most MAX_DECISIONS (the latest): [{options, pick, reward}]."""
        out = []
        for d in self.cfg.get("decisions") or []:
            try:
                opts = [str(o)[:200] for o in d["options"]][:MAX_OPTIONS]
                pick, rew = int(d["pick"]), d.get("reward")
            except (KeyError, TypeError, ValueError):
                continue
            if len(opts) >= 2 and 0 <= pick < len(opts) and isinstance(rew, (int, float)) and math.isfinite(rew):
                out.append({"options": opts, "pick": pick, "reward": float(rew)})
        return out[-MAX_DECISIONS:]

    def ph_choice_replay(self):
        """Night replay of the day's real decisions: each offer is presented again, the option he really took is
        tagged as chosen and its real outcome is the dopamine (LiveChooser rule). Before and after, frozen: how
        often the network's own pick agrees with the outcomes (choice.replay_fit). Reported whatever it is."""
        live = self._live()
        decs = self.real_decisions()
        passes = max(1, int(self.cfg.get("replay_passes", 1)))
        p = self.net.plast

        def frozen_picks():
            was = p.frozen if p is not None else None
            if p is not None:
                p.frozen = True
            try:
                return [live.decide(d["options"], learn=False)["pick"] for d in decs]
            finally:
                if p is not None:
                    p.frozen = was

        def twin_picks():
            """The frozen twin: the same network with every learned change removed (it never learned)."""
            if p is None:
                return frozen_picks()
            dw, theta = p.dw.clone(), self.net.theta.clone()
            p.dw.zero_()
            p._apply()
            self.net.theta.zero_()
            self.net._dirty = True
            try:
                return frozen_picks()
            finally:
                p.dw.copy_(dw)
                p._apply()
                self.net.theta.copy_(theta)
                self.net._dirty = True
        twin = replay_fit(decs, twin_picks())
        before = replay_fit(decs, frozen_picks())
        agree = 0
        for k in range(passes):
            for i, d in enumerate(decs):
                r = live.decide(d["options"], learn=True, force=d["pick"])
                agree += int(r["pick"] == d["pick"])
                live.reward(r["elig"], d["reward"])
                self.net.run(100)
                self.progress = (k * len(decs) + i + 1) / max(1, passes * len(decs))
        after = replay_fit(decs, frozen_picks())
        self.result("choice_replay", {"decisions": len(decs), "passes": passes,
                                      "rewarded": sum(d["reward"] > 0 for d in decs),
                                      "punished": sum(d["reward"] < 0 for d in decs),
                                      "fit_before": before[0], "fit_after": after[0], "fit_n": after[1],
                                      "fit_frozen_twin": twin[0],
                                      "paid_off_frac": round(sum(d["reward"] > 0 for d in decs) / len(decs), 4)
                                      if decs else None,
                                      "own_pick_agreed_during_replay": round(agree / max(1, passes * len(decs)), 4),
                                      "calibration": live.calib, "labels_valued": len(live.V)})

    def ph_choice_exam(self):
        """Frozen exam on the current hidden probabilities (after the reversal if training reversed), the same exam
        with every learned change removed, and the random chooser."""
        task = self._choice()
        n = int(self.cfg.get("choice_exam_trials", 40))
        rev = int(self.cfg.get("choice_trials", 200)) // 2 if self.cfg.get("choice_reversal", True) else None
        probs = RewardSchedule(task.probs, rev).probs(task.trial).tolist()
        exam = task.exam(n, probs)
        p = self.net.plast
        ctrl = None
        if p is not None:
            dw, theta = p.dw.clone(), self.net.theta.clone()
            p.dw.zero_()
            p._apply()
            self.net.theta.zero_()
            self.net._dirty = True
            try:
                ctrl = task.exam(n, probs)
            finally:
                p.dw.copy_(dw)
                p._apply()
                self.net.theta.copy_(theta)
                self.net._dirty = True
        rnd = random_chooser(RewardSchedule(probs, None, seed=int(self.cfg.get("seed", 1))), 2000, task.k)
        self.result("choice_exam", {"label": "after training (frozen)", "probs": probs, **exam,
                                    "controls": {"no_learning": ctrl["frac_correct"] if ctrl else None,
                                                 "random": rnd["frac_correct"], "chance": round(1.0 / task.k, 4)}})

    # --- day mode: live decisions (#58) ----------------------------------------------------------------------------
    def _live(self):
        if self.live is None:
            c = self.cfg
            kw = {k[len("live_"):]: c[k] for k in ("live_thr_z", "live_eta", "live_eta_min", "live_eta_tau",
                                                     "live_alpha", "live_timeout_ms", "live_cue_amp", "live_readout",
                                                     "live_readout_kw") if k in c}
            self.live = LiveChooser(self.net, **kw)
            if self.net.plast is not None:
                self.live.from_meta(self.net.plast.meta.get("live_choice"))
            self.live.calibrate()
            self.log("live chooser calibrated:", self.live.calib)
        return self.live

    def drain(self, timeout=0.0):
        """Commands from the server outside net.run (the hook reads them during it); waits up to `timeout` s."""
        if self.link is None:
            if timeout > 0:
                time.sleep(timeout)
            return
        try:
            msg = self.link.inbox.get(timeout=timeout) if timeout > 0 else self.link.inbox.get_nowait()
        except queue.Empty:
            return
        self.command(msg)
        while True:
            try:
                msg = self.link.inbox.get_nowait()
            except queue.Empty:
                return
            self.command(msg)

    def answer(self, msg, received):
        """One decide message -> one decision message (also when it is too late: the server drops it)."""
        st = self.live_stats
        did = str(msg.get("id", ""))[:64]
        opts = msg.get("options")
        if not did or not isinstance(opts, list) or not 2 <= len(opts) <= MAX_OPTIONS:
            st["refused"] += 1
            if self.link is not None:
                self.link.send({"type": "decision", "id": did, "error": "bad decide message"})
            return None
        late = (time.time() - received) * 1000 > float(msg.get("deadline_ms") or 2000)
        if late:                                         # its deadline passed while queued: do not spend sim on it
            st["late"] += 1
            if self.link is not None:
                self.link.send({"type": "decision", "id": did, "error": "late"})
            return None
        r = self._live().decide([str(o)[:200] for o in opts], learn=True)
        wall_ms = round((time.time() - received) * 1000, 1)
        self.pending[did] = (time.time(), r["elig"])
        while len(self.pending) > MAX_PENDING:
            self.pending.popitem(last=False)
        st["decisions"] += 1
        st["wall_ms"] = (st["wall_ms"] + [wall_ms])[-500:]
        out = {"type": "decision", "id": did, "pick": r["pick"], "pool_rates": r["pool_rates"], "sim_ms": r["sim_ms"],
               "n_neurons": self.net.n, "wall_ms": wall_ms, "timeout": r["timeout"]}
        if self.link is not None:
            self.link.send(out)
        return out

    def apply_reward(self, msg):
        did = str(msg.get("id", ""))
        got = self.pending.pop(did, None)
        try:
            value = float(msg.get("value"))
        except (TypeError, ValueError):
            value = float("nan")
        if got is None or time.time() - got[0] > PENDING_S or not math.isfinite(value):
            self.live_stats["unknown_reward"] += 1
            return None
        self.live_stats["rewards"] += 1
        return self._live().reward(got[1], value)

    def weights_meta(self):
        meta = {**self.mem.to_meta(), "last_day": self.cfg.get("day"),
                "sessions": int(self.net.plast.meta.get("sessions", 0)) + 1}
        if self.live is not None:
            meta["live_choice"] = self.live.to_meta()
        return meta

    def upload_weights(self, reason="periodic"):
        """Save the learned weights now and upload them in a background thread (skipped while one is running)."""
        net = self.net
        if net.plast is None or self.link is None or (self._upload is not None and self._upload.is_alive()):
            return False
        path = self.out / "weights.live.npz"
        net.plast.save(path, {**self.weights_meta(), "sessions": int(net.plast.meta.get("sessions", 0))})
        st = self.live_stats

        def up():
            try:
                self.link.put_weights(path)
                st["uploads"] += 1
                self.log("weights uploaded", reason)
            except Exception as e:
                st["upload_errors"] += 1
                self.log("weights upload failed:", type(e).__name__)
        self._upload = threading.Thread(target=up, daemon=True)
        self._upload.start()
        return True

    def live_summary(self):
        st = self.live_stats
        w = sorted(st["wall_ms"])
        pct = (lambda q: w[min(len(w) - 1, int(q * len(w)))] if w else None)
        return {k: v for k, v in st.items() if k != "wall_ms"} | {
            "wall_ms_p50": pct(0.5), "wall_ms_p95": pct(0.95), "wall_ms_max": w[-1] if w else None,
            "labels_valued": len(self.live.V) if self.live else 0, "calibration": self.live.calib if self.live else None,
            "realtime_x": self.live_rt}

    def ph_live_decide(self):
        """His waking day: run the network at most at real time and answer decide / reward messages until the
        night message (or a stop / the deadline). Weights go to the server every upload_every_min minutes."""
        net = self.net
        live = self._live()
        seen = None
        every = 60.0 * float(self.cfg.get("upload_every_min", 30))
        chunk = int(self.cfg.get("live_chunk_ms", 20))
        next_up, next_sum = time.time() + every, time.time() + 300
        anchor_wall, anchor_t = time.time(), net.t
        t_wall0, t_sim0 = time.time(), net.t
        self.live_rt = None
        while self.night is None:
            if time.time() > self.deadline:
                raise StopSession("deadline")
            if self.link is not None and self.link.connects != seen:  # (re)connected: the hub forgets us
                seen = self.link.connects
                self.link.send({"type": "hello", "session": self.cfg.get("session_id") or self.link.sid,
                                "n_neurons": net.n, "device": self.results["build"]["gpu"] or str(net.device),
                                "phases": self.cfg.get("phases")})
                self.link.send({"type": "live_ready", "n_neurons": net.n, "calibration": live.calib})
            self.drain()
            while self.decide_q:
                self.answer(*self.decide_q.popleft())
            while self.reward_q:
                self.apply_reward(self.reward_q.popleft())
            now = time.time()
            if now >= next_up:
                next_up = now + every
                self.upload_weights("periodic")
            if now >= next_sum:
                next_sum = now + 300
                self.live_rt = round((net.t - t_sim0) * net.cfg.dt / 1000.0 / max(1e-6, now - t_wall0), 3)
                self.result("live", self.live_summary())
            ahead = (net.t - anchor_t) * net.cfg.dt / 1000.0 - (now - anchor_wall)
            if ahead > 0:                                # at most real time: wait for messages instead
                self.drain(timeout=min(ahead, 0.05))
            else:
                if ahead < -1.0:                         # slower than real time: never try to catch up in bursts
                    anchor_wall, anchor_t = now, net.t
                net.run(chunk)
        self.live_rt = round((net.t - t_sim0) * net.cfg.dt / 1000.0 / max(1e-6, time.time() - t_wall0), 3)
        self.result("live", self.live_summary() | {"ended": "night"})
        self.start_night(self.night)

    def start_night(self, msg):
        """The night config from the server replaces the day's: its day, items and real decisions."""
        for k in ("day", "items", "decisions", "elapsed_days"):
            if k in msg:
                self.cfg[k] = msg[k]
        self.log("night:", len(self.cfg.get("items") or []), "items,", len(self.cfg.get("decisions") or []), "decisions")

    def ph_live_bench(self):
        """GPU benchmark at the live load, no server needed: free-running speed with the live settings (STDP off),
        then `live_bench_n` decisions among 2-6 random labels with a reward each (decision wall time, sim ms)."""
        net = self.net
        live = self._live()
        rng = np.random.default_rng(int(self.cfg.get("seed", 1)))
        vocab = ("moon tea bread river chess knight bishop pawn castle music video park museum recipe forum news map "
                 "ocean snow lamp bird stone rope salt cloud apple garden train station bakery cat dog").split()
        net.run(200)
        net.sync()
        t0, s0 = time.time(), net.t
        net.run(int(self.cfg.get("bench_ms", 5000)))
        net.sync()
        free = (net.t - s0) / (time.time() - t0)
        walls, sims, tos = [], [], 0
        n = int(self.cfg.get("live_bench_n", 40))
        t1, s1 = time.time(), net.t
        for i in range(n):
            k = int(rng.integers(2, 7))
            labels = [" ".join(rng.choice(vocab, size=int(rng.integers(1, 4)), replace=False)) for _ in range(k)]
            a = time.time()
            r = live.decide(labels, learn=True)
            net.sync()
            walls.append((time.time() - a) * 1000)
            sims.append(r["sim_ms"])
            tos += int(r["timeout"])
            live.reward(r["elig"], float(rng.choice([-1.0, 0.0, 1.0])))
            net.run(500)
            self.progress = (i + 1) / n
        net.sync()
        mixed = (net.t - s1) / (time.time() - t1)
        self.result("live_bench", {"gpu": self.results["build"]["gpu"], "n_neurons": net.n,
                                   "steps_per_s_free": round(free, 1), "realtime_x_free": round(free / 1000.0, 3),
                                   "steps_per_s_with_decisions": round(mixed, 1),
                                   "realtime_x_with_decisions": round(mixed / 1000.0, 3), "decisions": n,
                                   "decision_wall_ms_p50": round(float(np.percentile(walls, 50)), 1),
                                   "decision_wall_ms_p95": round(float(np.percentile(walls, 95)), 1),
                                   "decision_wall_ms_max": round(float(np.max(walls)), 1),
                                   "decision_sim_ms_mean": round(float(np.mean(sims)), 1),
                                   "timeout_frac": round(tos / n, 3), "calibration": live.calib,
                                   "gpu_mem_gb": round(net.memory_gb(), 2) if net.memory_gb() else None})

    def ph_live_learn(self):
        """The learning benchmark of #70 at the live settings, no server needed: #39's bandit with variable offers
        (2-6 of 8 real labels) and a reversal halfway, for each read-out in `bandit_readouts`: the frozen twin, the
        learned run and a random chooser on the same offers and reward stream (choice.bandit_experiment). The result
        is saved after every read-out, so a deadline keeps what was measured."""
        net, c = self.net, self.cfg
        live = self._live()
        n = int(c.get("bandit_trials", 240))
        modes = tuple(c.get("bandit_readouts") or READOUTS)
        info = {"gpu": self.results["build"]["gpu"], "n_neurons": net.n}
        t0 = time.time()

        def saved(mode, out):
            rec = {**info, **out, "wall_s": round(time.time() - t0, 1)}
            self.results["phases"]["live_learn"] = [rec]
            self.save_results()
            self.log("read-out", mode, "learned", out["readouts"][mode]["learned"]["frac_correct"],
                     "frozen", out["readouts"][mode]["frozen"]["frac_correct"], "random", out["random"]["frac_correct"])
        out = bandit_experiment(live, trials=n, readouts=modes, readout_kw=c.get("bandit_readout_kw"),
                                seed=int(c.get("seed", 1)), on_trial=lambda f: setattr(self, "progress", f),
                                on_readout=saved)
        self.results["phases"].pop("live_learn", None)
        self.result("live_learn", {**info, **out, "wall_s": round(time.time() - t0, 1)})

    def ph_sleep(self, replay=True, label=None):
        minutes = float(self.cfg.get("sleep_minutes", 4))
        reps = sleep_block(self.net, self.mem, minutes, cycles=int(self.cfg.get("sleep_cycles", 2)), replay=replay)
        out = {"minutes_sim": minutes, "replay": replay, "label": label,
               "replays": [r["text"] for r in reps] if reps else []}
        self.result("sleep", out)

    def ph_free(self):
        """Free run with live inputs until the session ends (chat drives patterns; REM from the server replays)."""
        rng = np.random.default_rng(0)
        end = self.deadline
        next_replay = 0.0
        while time.time() < end:
            if self.pending_chat:
                self.mem.encode(self.pending_chat.pop(0), self.cfg.get("day"))
            if self.stage == "REM" and self.net.t >= next_replay:
                self.mem.replay_once(rng)
                next_replay = self.net.t + rng.exponential(5000)
            self.net.mu_offset = (-1.0 + 2.5 * math.sin(2 * math.pi * 0.8 * self.net.t / 1000.0)) if self.stage == "NREM" else 0.0
            self.net._dirty = True
            self.net.run(200)

    # --- run ------------------------------------------------------------------------------------------------------
    def run(self):
        err = None
        try:
            self.build()
            phases = self.cfg.get("phases") or ["bench", "rates", "delays"]
            for i, ph in enumerate(phases):
                self.phase, self.progress = ph, 0.0
                if self.net.plast is not None:                   # eligibility only where dopamine can arrive
                    self.net.plast.set_stdp(ph in ("bench", "pong_train", "validate_pong", "free"))
                self.status()
                self.log("start")
                t0 = time.time()
                if ph == "validate_memory":
                    self.validate_memory()
                elif ph == "validate_reading":
                    self.validate_reading()
                elif ph == "validate_pong":
                    self.validate_pong()
                elif ph == "memory_test":
                    n_before = len([r for r in self.results["phases"].get("memory_test", [])
                                    if r.get("label") != "next day"])
                    slept = any(k.endswith(":sleep") for k in self.results.get("timing", {}))
                    today = [m for m in self.mem.registry if m.get("day") == self.cfg.get("day")]
                    self.ph_memory_test("after sleep" if slept else ("after encoding" if n_before == 0 else None),
                                        items=today or None)               # yesterday's: the next-day test
                elif ph == "pong_exam":
                    self.ph_pong_exam()
                else:
                    getattr(self, "ph_" + ph)()
                self.results.setdefault("timing", {})[f"{i}:{ph}"] = {"wall_s": round(time.time() - t0, 1)}
                self.log("done in", round(time.time() - t0, 1), "s")
        except StopSession as e:
            self.log("stopping:", e)
            self.results["stopped"] = str(e)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        finally:
            self.finish(err)
        return self.results

    def validate_memory(self):
        """Encode -> test -> sleep with replay -> test, and the same sleep without replay (restored weights)."""
        if not self.cfg.get("messages"):
            self.cfg["messages"] = DEMO_MESSAGES
        self.ph_encode()
        self.ph_memory_test("after encoding")
        p = self.net.plast
        dw0 = p.dw.clone()
        theta0, rate0 = self.net.theta.clone(), p.rate.clone()
        reg0 = json.loads(json.dumps(self.mem.registry))
        self.ph_sleep(replay=False, label="control: same time, no replay")
        self.ph_memory_test("after sleep without replay (control)")
        p.dw.copy_(dw0)
        p._apply()
        self.net.theta.copy_(theta0)
        p.rate.copy_(rate0)
        p.last_homeo = None
        self.net._dirty = True
        self.mem.registry = reg0
        self.ph_sleep(replay=True, label="sleep with REM replay")
        self.ph_memory_test("after sleep with replay")

    def validate_reading(self):
        """Two days in one pod: day 1 encodes chat + readings, sleeps with replay, is tested; a day of forgetting
        passes (the decay applied between real sessions); day 2 first tests day 1's items from half cues (the
        "next morning" test), then encodes its own items and sleeps."""
        d2 = self.cfg.get("day") or date.today().isoformat()
        d1 = (date.fromisoformat(d2) - timedelta(days=1)).isoformat()
        day1 = self.cfg.get("items_day1") or DEMO_ITEMS[:6]
        day2 = self.cfg.get("items_day2") or DEMO_ITEMS[6:]
        self.ph_encode(self._norm(day1), d1)
        self.ph_memory_test("after encoding", day=d1)
        self.ph_sleep(replay=True, label="day 1 sleep with REM replay")
        self.ph_memory_test("after sleep", day=d1)
        if self.net.plast is not None:
            self.net.plast.forget(float(self.cfg.get("elapsed_days", 1.0)))
        self.ph_recall_yesterday(today=d2)
        self.ph_encode(self._norm(day2), d2)
        self.ph_sleep(replay=True, label="day 2 sleep with REM replay")
        self.ph_memory_test("after sleep", items=[m for m in self.mem.registry if m.get("day") == d2], day=d2)

    @staticmethod
    def _norm(items):
        return [{"text": it["text"], "source": it.get("source", "chat"), "item": it.get("item") or it["text"]}
                for it in items]

    def validate_pong(self):
        """Exams before training (= no plasticity), training curve, exams after (frozen) + controls."""
        pong = self._pong()
        reps = int(self.cfg.get("exam_repeats", 2))
        er = int(self.cfg.get("exam_rallies", 20))
        pre = [pong.exam(er, game_seed=500 + k) for k in range(reps)]      # same ball sequences before / after
        self.result("exam", {"label": "before training (no learning yet)", "exams": pre,
                             "hits": sum(e["hits"] for e in pre), "rallies": sum(e["rallies"] for e in pre),
                             "hit_rate": round(sum(e["hits"] for e in pre) / sum(e["rallies"] for e in pre), 4)})
        self.ph_pong_train()
        post = [pong.exam(er, game_seed=500 + k) for k in range(reps)]
        ctrl = [self._exam_no_learning(er, game_seed=500 + k) for k in range(reps)]
        rnd = random_paddle(5000, seed=int(self.cfg.get("seed", 1)))
        trk = tracking_paddle(500)
        self.result("exam", {"label": "after training (frozen)", "exams": post,
                             "hits": sum(e["hits"] for e in post), "rallies": sum(e["rallies"] for e in post),
                             "hit_rate": round(sum(e["hits"] for e in post) / sum(e["rallies"] for e in post), 4),
                             "controls": {"no_plasticity": round(sum(e["hits"] for e in ctrl) / sum(e["rallies"] for e in ctrl), 4),
                                          "no_plasticity_exams": ctrl, "random": rnd["hit_rate"],
                                          "ideal_tracker": trk["hit_rate"]}})

    def finish(self, err):
        net = getattr(self, "net", None)
        self.phase = "save"
        self.status()
        try:
            if net is not None and net.plast is not None:
                net.hook = None
                if self._upload is not None:
                    self._upload.join(timeout=300)                   # a periodic upload must not race the last one
                wpath = self.out / "weights.npz"
                info = net.plast.save(wpath, self.weights_meta())
                self.results["weights"] = {**info, "stats": net.plast.stats(), "bytes": wpath.stat().st_size}
                if self.link is not None and not self.cfg.get("validate") and err is None:
                    self.results["weights"]["upload_status"] = self.link.put_weights(wpath)
        except Exception as e:
            err = err or f"save: {type(e).__name__}: {e}"
            traceback.print_exc()
        self.results["wall_s"] = round(time.time() - self.t_wall0, 1)
        self.results["sim_s"] = round(net.t / 1000.0, 1) if net is not None else 0
        self.results["error"] = err
        self.results["files"] = sorted({"results.json", "session.log"} | set(self.results.get("files", [])))
        self.save_results()
        if self.link is not None:
            self.link.send({"type": "done", "ok": err is None, "error": err})
            self.link.close()
        self.phase = "done"
        self.status(done=True, error=err)


MAX_PER_SOURCE = 5
# synthetic validation items: invented chat lines + public Wikipedia titles with keywords (no real chat content)
DEMO_ITEMS = [
    {"text": "good morning little brain, the sun is warm today", "source": "chat"},
    {"text": "a red bicycle crossed the bridge near the river", "source": "chat"},
    {"text": "Inokashira Park park pond cherry blossoms kichijoji zoo boats", "source": "reading",
     "item": "Inokashira Park"},
    {"text": "Bread flour dough yeast baking oven crust wheat", "source": "reading", "item": "Bread"},
    {"text": "Moon orbit tides craters lunar apollo satellite phases", "source": "reading", "item": "Moon"},
    {"text": "Origami paper folding crane sheet japanese craft", "source": "reading", "item": "Origami"},
    {"text": "do you dream about the ocean and its waves", "source": "chat"},
    {"text": "Tea leaves brewing ceremony matcha kettle cups", "source": "reading", "item": "Tea"},
    {"text": "Lighthouse tower lamp coast ships beacon keeper", "source": "reading", "item": "Lighthouse"},
    {"text": "Snow crystals winter flakes cold mountains white", "source": "reading", "item": "Snow"},
]
DEMO_MESSAGES = [  # synthetic messages for validation (no real chat content)
    {"text": "good morning little brain, the sun is warm today", "emotion": "positive"},
    {"text": "a red bicycle crossed the bridge near the river", "emotion": "neutral"},
    {"text": "do you dream about the ocean and its waves", "emotion": "neutral"},
    {"text": "the bakery smells of fresh bread and coffee", "emotion": "positive"},
    {"text": "we watched the stars over the quiet mountain", "emotion": "neutral"},
]


def run_session(cfg, out_dir, stream=None):
    """In-process entry (CPU validation, tests). `stream`: optional Link-like object."""
    return Session(dict(cfg), out_dir, stream).run()


def main():
    cfg = json.loads(os.environ.get("SUB01_SESSION") or "{}")
    out = Path(os.environ.get("SUB01_OUT", "/out"))
    link = None
    if os.environ.get("SUB01_SERVER_URL") and os.environ.get("SUB01_POD_SECRET"):
        link = Link(os.environ["SUB01_SERVER_URL"], os.environ["SUB01_POD_SECRET"],
                    os.environ.get("SUB01_SESSION_ID") or cfg.get("session_id") or "session")
        for _ in range(100):                                             # up to 10 s for the websocket
            if link.connected:
                break
            time.sleep(0.1)
    res = Session(cfg, out, link).run()
    sys.exit(0 if not res.get("error") else 1)


if __name__ == "__main__":
    main()
