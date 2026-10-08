"""The brain model decides what he clicks: each proposed action is tried out on a copy of the brain first.

An AI (eyes.py) only lists options, each tagged with the networks it would mostly drive ({group: 0..1}). Here:
1. the live brain's state is cloned (history buffer, stimulus, slow layer, random stream: Brain.clone);
2. every option's networks become a stimulus (weight x STIM_AMP x the sleep engine's gain) and all clones, plus one
   without any stimulus, are simulated for VOTE_S (300 ms) at once, with the same noise (common random numbers, so the
   differences come from the stimulus alone);
3. value = d_reward + 0.6 d_attention + 0.3 d_visual (videos only) - 0.8 d_fear, where d_x is the mean amplitude of
   group x relative to the clone without stimulus;
4. the values (scaled to the best one), the learned taste for the option's topics (tastes.py) and a small novelty bonus
   go through a softmax whose temperature rises with boredom and sleep pressure. Leaving (#29) is boredom- and
   taste-driven: the leave option gets LEAVE_BORED x boredom + LEAVE_CHAIN x the chain's pull (0 on the first page,
   1 after 30 pages in a row), and its taste term is the opposite of the taste for the page he is on (its topics are
   the page's), so a page whose topics have paid off holds him and one that has not lets him go;
5. the live brain then receives the chosen option's stimulus.
His spiking neurons (#55, #58): a decision backend (Backend) asks a spiking network to race its striatal pools on
the option labels: the 1M-neuron network on the GPU pod first (spiking/pod_manager.day_live_decide, #58, when it is
on), else the 20k-neuron network on the server CPU (spiking/live.py, a child process). When an answer came in time,
each option gets SPIKING_W x its lean (tanh((pool rate - mean rate) / 2 Hz), -1..1) as one more term. Without one
(both down or too slow) the term is skipped and the vote is the rate model's alone. Every row records the term
("spiking", None if skipped) and the record says which network answered ("spiking": {"net", "network", ...}).
It is a rule on simulated activity, not understanding or liking: the model does not know what the page says.
"""
import asyncio
import math
import os
import time

import numpy as np

from brain_sim import SLOW_DRIVE

VOTE_S = 0.3                 # simulated look-ahead per option
STIM_AMP = 8.0               # drive per unit network weight (a chat message drives 6-8 per rule)
MAX_OPTIONS = 6
VALUE = {"reward": 1.0, "attention": 0.6, "fear": -0.8}
VIDEO_VISUAL = 0.3
TASTE_W = 0.5                # weight of the learned preference next to the brain response (both ~[-1, 1])
NOVELTY = 0.3                # bonus for a link or search he has not done recently
LEAVE_BORED = 0.5            # leave bonus per unit boredom (0..1)
LEAVE_CHAIN = 0.6            # leave bonus at the end of a long chain of pages (eyes.leave_pull, 0..1)
VIDEO_ACTIONS = ("open_video", "play_video")
SPIKING_W = float(os.environ.get("SUB01_SPIKING_W", 0.3))   # the spiking network's lean, next to value/taste/novelty
NETWORKS = {"gpu": "1M-neuron network on GPU", "cpu": "20k-neuron network on CPU", "rate": "rate model only"}
T0 = 0.15                    # softmax temperature when rested and not bored
WATCH_MIN, WATCH_MAX = 2.0, 10.0   # simulated minutes he watches a chosen video before the brain decides again (#17)
NAMES = {"reward": "reward", "attention": "attention", "visual": "visual", "fear": "threat", "language": "language",
         "memory": "memory", "default": "default-mode", "salience": "salience", "somatomotor": "body-movement",
         "control": "control", "limbic": "limbic", "relay": "thalamic relay"}


def temperature(boredom=0.0, pressure=0.0, tired=0.0):
    """Softmax temperature: rises with boredom and with sleep pressure / sleep debt (choices get less decisive)."""
    sleepy = min(1.0, max(0.0, pressure)) + min(1.0, max(0.0, tired))
    return T0 * (1.0 + 1.5 * min(1.0, max(0.0, boredom))) * (1.0 + 1.5 * sleepy)


def watch_minutes(boredom=0.0, value=0.0):
    """How long he watches a chosen video (simulated minutes, WATCH_MIN..WATCH_MAX): longer when the brain's response
    to it was strong (value: the vote's normalised value, -1..1) and when he is not bored; then the brain decides
    again."""
    def unit(x):
        try:
            x = float(x)
        except (TypeError, ValueError):
            return 0.0
        return min(1.0, max(0.0, x)) if x == x else 0.0
    x = 0.6 * unit(value) + 0.4 * (1.0 - unit(boredom))
    return round(WATCH_MIN + (WATCH_MAX - WATCH_MIN) * x, 2)


def stimulus_vector(brain, networks, gain):
    """{group: weight} -> per-region drive, exactly what brain.stimulate(group, w * STIM_AMP * gain) would add."""
    v = np.zeros(brain.n)
    for g, w in networks.items():
        idx = brain.group_idx.get(g)
        if idx:
            v[idx] += float(w) * STIM_AMP * gain
    return v


def simulate(clone, stims, seconds=VOTE_S):
    """Run len(stims) copies of `clone` side by side (one sparse product per step for all of them) with the same noise
    and slow drive; return each copy's mean amplitude per region over the window, shape (K, n). `clone` is not
    modified (its random stream and slow layer are copied again here)."""
    import copy
    b = clone
    n, hist, K = b.n, b.hist, len(stims)
    M, Ws = b.lag_coupling(), b.W.sum(1)
    H = np.empty((hist, n, K), complex)                          # H[d] = z(t - d)
    for d in range(hist):
        H[d] = b.buf[(b.t - d) % hist][:, None]
    stim = b.stim[:, None] + np.array(stims, float).T            # (n, K): what is already decaying + the option
    rng, slow = copy.deepcopy(b.rng), copy.deepcopy(b.slow) if b.slow_on else None
    slow_x, t, dt = b.slow_x.copy(), b.t, b.dt
    decay = math.exp(-dt / 2.0)
    acc = np.zeros((n, K))
    steps = int(round(seconds / dt))
    for _ in range(steps):
        z = H[0]
        coup = b.g * ((M @ H.reshape(hist * n, K)) - Ws[:, None] * z)
        if slow is not None and t % 100 == 0:
            slow_x = SLOW_DRIVE * b.slow_gain * np.clip(slow.advance(100 * dt)[b._slow_idx], -2.0, 3.0)
        a_eff = b.a + stim + (b.drive + slow_x + getattr(b, "neuromod", 0.0))[:, None]   # same terms as Brain.step
        local = np.exp((a_eff + 1j * b.omega[:, None] - np.abs(z) ** 2) * dt)
        noise = b.noise * math.sqrt(dt) * (rng.normal(size=n) + 1j * rng.normal(size=n))
        new = z * local + dt * coup + noise[:, None]
        H[1:] = H[:-1]
        H[0] = new
        t += 1
        stim *= decay
        acc += np.abs(new)
    return (acc / steps).T


def responses(brain, options, gain, seconds=VOTE_S):
    """Per option: {group: change in mean amplitude vs the clone without stimulus}."""
    stims = [np.zeros(brain.n)] + [stimulus_vector(brain, o["networks"], gain) for o in options]
    amp = simulate(brain, stims, seconds)
    groups = {g: i for g, i in brain.group_idx.items() if i}
    base = {g: float(amp[0, i].mean()) for g, i in groups.items()}
    return [{g: float(amp[k, i].mean()) - base[g] for g, i in groups.items()} for k in range(1, len(stims))]


def value(delta, video=False):
    v = sum(w * delta.get(g, 0.0) for g, w in VALUE.items())
    return v + (VIDEO_VISUAL * delta.get("visual", 0.0) if video else 0.0)


def spiking_term(spiking, k):
    """The spiking network's lean per option (-1..1), or None when its answer is missing or does not fit. An answer with
    a pick but no pool rates (the GPU network can send none) leans +1 to its pick and -1/(k-1) to the others."""
    rates = (spiking or {}).get("pool_rates")
    pick = (spiking or {}).get("pick")
    if rates is None and isinstance(pick, int) and not isinstance(pick, bool) and 0 <= pick < k and k >= 2:
        return np.array([1.0 if i == pick else -1.0 / (k - 1) for i in range(k)])
    if not isinstance(rates, (list, tuple)) or len(rates) != k or k < 2:
        return None
    try:
        r = np.array([float(x) for x in rates])
    except (TypeError, ValueError):
        return None
    if not np.isfinite(r).all():
        return None
    return np.tanh((r - r.mean()) / 2.0)


def vote(clone, options, gain=1.0, mood=None, tastes=None, novel=None, rng=None, seconds=VOTE_S, spiking=None):
    """Pick one option. `clone` = brain.clone() taken on the event loop; options = validated eyes.py options;
    mood = {boredom, pressure, tired}; tastes = [prediction in -1..1] per option; novel = [bool] per option;
    spiking = the spiking network's answer for these options ({pick, pool_rates, decision_ms, ...}) or None.
    Returns the decision record (also what the page shows)."""
    t0 = time.perf_counter()
    options = list(options)[:MAX_OPTIONS]
    if not options:
        return None
    mood = mood or {}
    rng = rng or np.random.default_rng()
    tastes = list(tastes) if tastes is not None else [0.0] * len(options)
    novel = list(novel) if novel is not None else [False] * len(options)
    deltas = responses(clone, options, gain, seconds)
    vals = [value(d, o.get("action") in VIDEO_ACTIONS) for d, o in zip(deltas, options)]
    scale = max(abs(v) for v in vals)
    vn = [v / scale if scale > 1e-9 else 0.0 for v in vals]
    tastes = [-ts if o.get("action") == "leave" else ts for o, ts in zip(options, tastes)]
    leave = [leave_bonus(o, mood) for o in options]
    sp = spiking_term(spiking, len(options))
    spk = [None] * len(options) if sp is None else [float(x) for x in sp]
    total = [v + TASTE_W * ts + (NOVELTY if nv else 0.0) + lv + (SPIKING_W * s_ if s_ is not None else 0.0)
             for v, ts, nv, lv, s_ in zip(vn, tastes, novel, leave, spk)]
    T = temperature(mood.get("boredom", 0.0), mood.get("pressure", 0.0), mood.get("tired", 0.0))
    top = max(total)
    w = np.array([math.exp((x - top) / T) for x in total])
    p = w / w.sum()
    k = int(rng.choice(len(options), p=p))
    rows = [{"action": o["action"], "label": o["label"], "target": o.get("target"), "networks": o["networks"],
             "response": round(v, 5), "value": round(n_, 3), "taste": round(ts, 3), "novel": bool(nv),
             "p": round(float(pk), 3), "chosen": i == k, "spiking": None if sv is None else round(sv, 3)}
            for i, (o, v, n_, ts, nv, pk, sv) in enumerate(zip(options, vals, vn, tastes, novel, p, spk))]
    for row, lv in zip(rows, leave):
        if row["action"] == "leave":
            row["leave_bonus"] = round(lv, 3)
    if sp is None:
        sp_rec = {"used": False, "net": "rate", "network": NETWORKS["rate"],
                  "why": (spiking or {}).get("why") or ("no answer" if spiking is None else "did not fit")}
    else:
        top_k = int(np.argmax(spk))
        net = spiking.get("net") if spiking.get("net") in NETWORKS else "cpu"
        sp_rec = {"used": True, "net": net, "network": NETWORKS[net], "weight": SPIKING_W,
                  "pick": int(spiking.get("pick", top_k)), "leaned_to": options[top_k]["label"],
                  "pool_rates": [round(float(x), 3) for x in spiking["pool_rates"]] if spiking.get("pool_rates") else None,
                  "sim_ms": spiking.get("sim_ms"), "n_neurons": spiking.get("n_neurons"), "id": spiking.get("id")}
    return {"options": rows, "chosen": k, "temperature": round(T, 3), "gain": round(gain, 3), "spiking": sp_rec,
            "reason": reason(options, deltas, vals, total, k, mood, tastes),
            "ms": round((time.perf_counter() - t0) * 1000), "clones": len(options) + 1, "seconds": seconds}


def leave_bonus(option, mood):
    """Extra pull of the leave option: boredom, and the length of the chain of pages (eyes.leave_pull)."""
    if option.get("action") != "leave":
        return 0.0
    try:
        pull = float(option.get("pull") or 0.0)
    except (TypeError, ValueError):
        pull = 0.0
    pull = min(1.0, max(0.0, pull)) if pull == pull else 0.0
    return LEAVE_BORED * min(1.0, max(0.0, mood.get("boredom", 0.0))) + LEAVE_CHAIN * pull


def reason(options, deltas, vals, total, k, mood, tastes):
    if options[k].get("action") == "leave":
        bits = []
        if mood.get("boredom", 0.0) >= 0.5:
            bits.append("bored")
        if float(options[k].get("pull") or 0.0) >= 0.5:
            bits.append("a long chain of pages")
        if tastes[k] > 0.2:
            bits.append("this page's topics have not paid off")
        if bits:
            return "moved on: " + ", ".join(bits)
    d = deltas[k]
    up = sorted((g for g in ("reward", "attention", "visual") if d.get(g, 0.0) > 0), key=lambda g: -d[g])[:2]
    if up and vals[k] > 0:
        why = f"chose it: {' and '.join(NAMES[g] for g in up)} areas responded most"
    elif vals[k] >= max(vals):
        why = "chose it: it moved the threat area least"
    else:
        why = "chose it: no option stood out in the brain response"
    best = int(np.argmax(total))
    intensity = [sum(o["networks"].values()) for o in options]
    sleepy = mood.get("pressure", 0.0) >= 0.8 or mood.get("tired", 0.0) >= 0.5
    if k != best:
        if sleepy and intensity[k] < max(intensity):
            why += "; tired, so he picked the lighter option"
        elif sleepy or mood.get("boredom", 0.0) >= 0.6:
            why += f"; {'tired' if sleepy else 'bored'}, so a weaker option won"
        else:
            why += "; by chance, not the top-scoring option"
    elif tastes[k] > 0.3 and tastes[k] * TASTE_W > abs(vals[k] / (max(abs(v) for v in vals) or 1)):
        why += "; its topics have paid off before"
    return why


def apply(brain, option, gain):
    """The live brain receives the chosen option's stimulus (same scaling as the vote)."""
    for g, w in option["networks"].items():
        if brain.group_idx.get(g):
            brain.stimulate(g, float(w) * STIM_AMP * gain)


class Backend:
    """Which network answers a decision: the GPU pod's 1M network (#58) first, the CPU child's 20k network second, the
    rate model alone last. Logs every decision and its reward in the day's decisions file (spiking.live.DecisionLog)
    and sends the reward to the network that decided.
    gpu: an object or module with `async day_live_decide(options, kind, deadline_ms) -> dict | None` and
    `async day_live_reward(id, value)` (spiking/pod_manager.py after #58); looked up at each call, so it may be absent.
    cpu: spiking.live.LiveClient or None."""

    def __init__(self, cpu=None, gpu=None, log=None, gpu_deadline_ms=1500, clock=time.time):
        self.cpu, self.gpu, self.log, self.gpu_deadline_ms, self.clock = cpu, gpu, log, gpu_deadline_ms, clock
        self.pending = None              # the browse decision whose page he is on: rewarded when he leaves it
        self.last = None                 # the last decision, for the card
        self.n = 0

    def _id(self, kind):
        self.n += 1
        return f"{kind[:1]}-{int(self.clock() * 1000)}-{self.n}"

    @staticmethod
    def _fits(ans, k, rates_optional=False):
        if not (isinstance(ans, dict) and isinstance(ans.get("pick"), int) and not isinstance(ans["pick"], bool)
                and 0 <= ans["pick"] < k):
            return False
        rates = ans.get("pool_rates")
        return (rates is None and rates_optional) or (isinstance(rates, (list, tuple)) and len(rates) == k)

    async def ask(self, options, kind="browse"):
        """-> the answer of the first network that answered in time ({"net": "gpu"|"cpu", "id", "pick",
        "pool_rates", ...}), or {"net": "rate", "id", "why"}."""
        labels = [str(o) for o in options][:MAX_OPTIONS]
        did, why = self._id(kind), []
        fn = getattr(self.gpu, "day_live_decide", None) if self.gpu is not None else None
        if fn is not None:
            try:
                ans = await asyncio.wait_for(fn(labels, kind, self.gpu_deadline_ms), self.gpu_deadline_ms / 1000 + 0.5)
            except Exception:
                ans = None
            if self._fits(ans, len(labels), rates_optional=True):     # the id #58 logged it under: no double count
                return {**ans, "net": "gpu", "id": str(ans.get("id") or did)}
            if ans is not None:
                why.append("GPU network answer did not fit")
        if self.cpu is not None:
            ans = await self.cpu.decide(labels, kind, did=did)
            if self._fits(ans, len(labels)):
                return {**ans, "net": "cpu", "id": did}
            why.append(ans.get("why") or "CPU network error")
        return {"net": "rate", "id": did, "why": "; ".join(why) or "no spiking network"}

    def followed(self, ans, chosen, options, kind="browse", rewarded=True):
        """The vote followed option `chosen`: log the decision; a browse decision waits for its reward."""
        ans = ans or {"net": "rate", "id": self._id(kind)}
        net = ans.get("net") if ans.get("net") in NETWORKS else "rate"
        labels = [str(o) for o in options][:MAX_OPTIONS]
        t = self.clock()
        extra = {}
        if net != "rate" and isinstance(ans.get("pick"), int):
            extra["net_pick"] = ans["pick"]
        if net == "cpu" and isinstance(ans.get("twin_pick"), int):
            extra["twin_pick"] = ans["twin_pick"]
        if self.log is not None:
            self.log.decision(ans["id"], kind, labels, chosen, net, t=t, **extra)
        self.pending = {"id": ans["id"], "net": net, "followed": int(chosen), "t": t} if rewarded else None
        lt = spiking_term(ans, len(labels)) if net != "rate" else None
        ln = [round(float(x), 3) for x in lt] if lt is not None else None
        self.last = {"t": round(t), "kind": kind, "net": net, "network": NETWORKS[net], "labels": labels,
                     "followed": int(chosen), "followed_label": labels[int(chosen)], "lean": ln,
                     "leaned_to": labels[int(np.argmax(ln))] if ln else None,
                     "pick_label": labels[ans["pick"]] if "net_pick" in extra else None, "why": ans.get("why")}

    def outcome(self, response=None, delta=None):
        """He left the page the pending decision led to: its tastes prediction error is the reward (the dopamine) of
        the network that decided; logged either way. None (a stay too short to measure): nothing to learn."""
        p, self.pending = self.pending, None
        if p is None or delta is None:
            return
        try:
            value = float(delta)
        except (TypeError, ValueError):
            return
        if not math.isfinite(value):
            return
        if p["net"] == "cpu" and self.cpu is not None:
            self.cpu.reward(p["id"], value, followed=p["followed"])
        elif p["net"] == "gpu":
            fn = getattr(self.gpu, "day_live_reward", None) if self.gpu is not None else None
            if fn is not None:
                try:
                    task = asyncio.get_running_loop().create_task(fn(p["id"], value))
                    task.add_done_callback(lambda t: t.cancelled() or t.exception())   # never an unhandled error
                except RuntimeError:                      # no running loop (tests): nothing to send it on
                    pass
        if self.log is not None:
            extra = {"response": round(float(response), 4)} if response is not None else {}
            self.log.reward(p["id"], value, p["t"], **extra)

