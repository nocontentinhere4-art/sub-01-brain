"""The launchpad's question to his brain: signed, idempotent, refused while asleep, decided by the brain vote.

    python -m pytest tests/test_launchpad_eval.py -q
No network, no AI: a real Brain clone votes; the rest of the live server is a stand-in.
"""
import asyncio
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from aiohttp.test_utils import TestClient, TestServer
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import launchpad_eval as L
from brain_sim import Brain

SECRET = "test-secret-123"


def fake_live(stage="AWAKE"):
    return SimpleNamespace(brain=Brain(), engine=SimpleNamespace(stage=stage, gain=1.0),
                           clock=SimpleNamespace(now=time.time),
                           mood=lambda t: {"boredom": 0.2, "pressure": 0.1, "tired": 0.0}, demo=True)


def signed(body, secret=SECRET, ts=None):
    ts = int(ts or time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return {"X-Launchpad-Timestamp": str(ts), "X-Launchpad-Signature": sig, "Content-Type": "application/json"}


def call(live, tmp_path, body, headers, monkeypatch, secret=SECRET, twice=False):
    if secret:
        monkeypatch.setenv("LAUNCHPAD_BRAIN_SECRET", secret)
    else:
        monkeypatch.delenv("LAUNCHPAD_BRAIN_SECRET", raising=False)

    async def go():
        app = web.Application()
        L.add_routes(app, live, tmp_path)
        async with TestClient(TestServer(app)) as c:
            out = []
            for _ in range(2 if twice else 1):
                r = await c.post("/api/launchpad/evaluate", data=body, headers=headers)
                out.append((r.status, await r.json()))
            return out
    return asyncio.run(go())


IDEA = json.dumps({"request_id": "idea_1.v1", "title": "Ramen Radar",
                   "concept": "A coin about a map of the best ramen and sushi in Tokyo at night"}).encode()


def test_networks_route_words():
    n = L.idea_networks("Ramen Radar", "A map of the best ramen in Tokyo")
    assert n["reward"] > 0 and n["attention"] > 0 and n["language"] > 0
    assert max(n.values()) == 1.0
    assert L.idea_networks("zzz", "qqq") == {"language": 1.0, "somatomotor": 0.5}


def test_vote_and_replay(tmp_path, monkeypatch):
    live = fake_live()
    (s1, r1), (s2, r2) = call(live, tmp_path, IDEA, signed(IDEA), monkeypatch, twice=True)
    assert s1 == 200 and r1["status"] == "ok" and r1["decision"] in ("build", "pass")
    assert len(r1["vote"]["options"]) == 2 and r1["vote"]["spiking"]["net"] == "rate"
    assert r2["replayed"] is True and r2["vote"] == r1["vote"]          # duplicate delivery: no second vote
    assert len((tmp_path / "launchpad_evals.jsonl").read_text().splitlines()) == 1


def test_asleep_still_votes_and_says_so(tmp_path, monkeypatch):
    [(s, r)] = call(fake_live("NREM"), tmp_path, IDEA, signed(IDEA), monkeypatch)
    assert s == 200 and r["status"] == "ok" and r["stage"] == "NREM" and r["decision"] in ("build", "pass")
    assert r["as_if_awake"] is True and r["gain"] >= 1.0 and r["sleeping_gain"] is not None


def test_bad_or_stale_signature(tmp_path, monkeypatch):
    [(s, _)] = call(fake_live(), tmp_path, IDEA, signed(IDEA, "wrong"), monkeypatch)
    assert s == 401
    [(s, _)] = call(fake_live(), tmp_path, IDEA, signed(IDEA, ts=time.time() - 3600), monkeypatch)
    assert s == 401


def test_off_without_secret(tmp_path, monkeypatch):
    [(s, r)] = call(fake_live(), tmp_path, IDEA, signed(IDEA), monkeypatch, secret=None)
    assert s == 503 and r["status"] == "off"
