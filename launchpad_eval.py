"""The launchpad asks his brain about an idea: POST /api/launchpad/evaluate (server-to-server, signed).

An idea (title + concept) is routed to networks with chat.py's word lexicon and rule table, exactly as a chat message
or a page title would be. Two options then go through the ordinary brain vote (brain_vote.vote, cloned live brain,
the same softmax as his clicks):
  build: the idea's networks;
  pass:  keep doing what he is doing (a weak default-mode drive, the same for every idea).
The record says which option won, each option's simulated response (reward, attention, threat ...) and which network
answered (rate model, or the spiking network through the decider). The chosen option's stimulus reaches the live brain,
so an idea he builds is also something he "heard".

What this is not: the model does not read or understand the idea. Words are routed to brain networks by a hand-written
table; the vote is a rule on simulated activity. No language model is involved here.

Always on (owner, 2026-10-10): asleep he votes too, on the clone with his sleeping gain and mood, and every answer
and ledger row carries the stage.
Auth: HMAC-SHA256 over "<timestamp>.<body>" with LAUNCHPAD_BRAIN_SECRET (header X-Launchpad-Signature,
X-Launchpad-Timestamp, max 300 s skew). No secret set: the route answers 503 (off).
Idempotent: the same request_id returns the stored record (data_dir/launchpad_evals.jsonl), never a second vote.
"""
import asyncio
import hashlib
import hmac
import json
import os
import re
import time

from aiohttp import web

import brain_vote
import chat
from sleep import AWAKE

VERSION = "launchpad-eval/1"
MAX_SKEW_S = 300
MAX_BODY = 8 * 1024
PASS = {"default": 0.3}            # "keep doing what he is doing": the same small drive for every idea
ID = re.compile(r"^[A-Za-z0-9_.:-]{6,80}$")


def idea_networks(title, concept):
    """-> {group: weight 0..1}: the lexicon (chat.networks_for) plus the chat rule table (chat.stimulus), normalised.
    Every idea drives language (it is words); the rest depends on which listed words it contains."""
    text = f"{title}. {concept}"
    out = dict(chat.networks_for(text))
    stim, _, _ = chat.stimulus(text)
    for g, a in stim.items():
        out[g] = out.get(g, 0.0) + a / 8.0          # rule drives are ~6-8 at gain 1: one rule ~ one lexicon hit
    top = max(out.values()) if out else 0.0
    return {g: round(v / top, 3) for g, v in sorted(out.items())} if top > 0 else {"language": 1.0}


def check_signature(secret, ts, body, sig, now=None):
    try:
        ts_i = int(ts)
    except (TypeError, ValueError):
        return False
    if abs((now or time.time()) - ts_i) > MAX_SKEW_S:
        return False
    want = hmac.new(secret.encode(), f"{ts_i}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, str(sig or ""))


class Store:
    """request_id -> record, append-only JSONL; loaded once."""

    def __init__(self, path):
        self.path, self.rows = path, {}
        if path.exists():
            for line in path.read_text().splitlines():
                try:
                    r = json.loads(line)
                    self.rows[r["request_id"]] = r
                except (ValueError, KeyError):
                    continue

    def get(self, rid):
        return self.rows.get(rid)

    def put(self, rec):
        self.rows[rec["request_id"]] = rec
        with self.path.open("a") as f:
            f.write(json.dumps(rec) + "\n")


async def evaluate(live, title, concept, rng=None):
    """-> (status, payload). status: 'ok' (always on: a sleeping brain votes too and says its stage)."""
    stage = getattr(live.engine, "stage", "AWAKE")
    nets = idea_networks(title, concept)
    opts = [{"action": "build", "label": f"build: {title[:60]}", "networks": nets},
            {"action": "pass", "label": "pass: keep doing what he is doing", "networks": dict(PASS)}]
    t = live.clock.now()
    mood = dict(live.mood(t))
    gain = live.engine.gain
    # Owner 2026-10-10: ideas are judged in his daytime tone even at night. Asleep, the vote runs on the clone with the
    # awake gain (SUB01_LAUNCHPAD_AWAKE_GAIN, default 1.0) and without the sleep tiredness; the answer says so
    # ("as_if_awake", with the sleeping gain it replaced), so nothing is hidden.
    sleeping_gain = None
    if stage != "AWAKE":
        sleeping_gain = gain
        gain = max(float(gain), float(os.environ.get("SUB01_LAUNCHPAD_AWAKE_GAIN") or 1.0))
        mood["tired"] = 0.0
    clone = live.brain.clone()
    if sleeping_gain is not None and hasattr(clone, "set_rhythm"):
        # the clone wakes up too: awake rhythm and excitability, then a second to settle, so the cortex model responds
        # to the idea as it would by day (a sleeping clone answers nothing and the vote fell to chance)
        clone.set_rhythm(AWAKE["f_hz"], AWAKE["coupling"], AWAKE["noise"])
        clone.a = AWAKE["a"]
        try:
            clone.step(int(round(1.0 / float(getattr(clone, "dt", 0.001)))))
        except Exception:
            pass
    decider = getattr(live, "decider", None)
    sp = None
    if decider:
        try:
            # the launchpad can wait for a big network (SUB01_LAUNCHPAD_DECIDE_S, default 15 s); browsing cannot
            sp = await decider.ask([o["label"] for o in opts], "launchpad",
                                   timeout=float(os.environ.get("SUB01_LAUNCHPAD_DECIDE_S") or 15))
        except Exception:
            sp = None
    loop = asyncio.get_running_loop()
    dec = await loop.run_in_executor(None, lambda: brain_vote.vote(clone, opts, gain, mood, None, None,
                                                                   rng, spiking=sp))
    brain_vote.apply(live.brain, opts[dec["chosen"]], gain)
    if decider:
        try:
            decider.followed(sp, dec["chosen"], [o["label"] for o in opts], "launchpad", rewarded=False)
        except Exception:
            pass
    # The launchpad takes the vote's build probability, not the dice: build when p(build) >= 0.5 (the browsing
    # choices keep their temperature sampling; an idea his brain liked at 91 % must not fall on "pass" by chance —
    # owner 2026-10-10, "Konbini Confession"). The sampled pick stays in the record as vote.chosen.
    p_build = float(dec["options"][0]["p"]) if dec.get("options") else (1.0 if dec["chosen"] == 0 else 0.0)
    return "ok", {"decision": "build" if p_build >= 0.5 else "pass", "p_build": round(p_build, 3), "networks": nets, "vote": dec,
                  "mood": {k: round(float(v), 3) for k, v in mood.items()}, "stage": stage, "gain": round(gain, 3),
                  "as_if_awake": sleeping_gain is not None, "sleeping_gain": None if sleeping_gain is None else round(float(sleeping_gain), 3)}


def add_routes(app, live, data_dir):
    store = Store(data_dir / "launchpad_evals.jsonl")
    lock = asyncio.Lock()
    rng = __import__("numpy").random.default_rng()     # its own stream: vote_rng is used by the browse thread

    async def handler(request):
        secret = os.environ.get("LAUNCHPAD_BRAIN_SECRET", "")
        if not secret:
            return web.json_response({"status": "off"}, status=503)
        body = await request.content.read(MAX_BODY + 1)
        if len(body) > MAX_BODY:
            return web.json_response({"status": "too_large"}, status=413)
        if not check_signature(secret, request.headers.get("X-Launchpad-Timestamp"), body,
                               request.headers.get("X-Launchpad-Signature")):
            return web.json_response({"status": "bad_signature"}, status=401)
        try:
            req = json.loads(body)
            rid, title, concept = str(req["request_id"]), str(req["title"])[:120], str(req["concept"])[:2000]
        except (ValueError, KeyError, TypeError):
            return web.json_response({"status": "bad_request"}, status=400)
        if not ID.match(rid):
            return web.json_response({"status": "bad_request"}, status=400)
        async with lock:                              # one idea at a time; duplicates return the first answer
            old = store.get(rid)
            if old:
                return web.json_response({**old, "replayed": True})
            status, out = await evaluate(live, title, concept, rng)
            if status == "asleep":
                return web.json_response({"status": "asleep", "stage": out["stage"], "version": VERSION}, status=409)
            rec = {"status": "ok", "request_id": rid, "version": VERSION, "t": round(time.time(), 3), **out,
                   "demo": bool(getattr(live, "demo", False))}
            store.put(rec)
            return web.json_response(rec)

    app.router.add_post("/api/launchpad/evaluate", handler)
