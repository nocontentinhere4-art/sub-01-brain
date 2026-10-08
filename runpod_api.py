"""Tiny RunPod REST client (key from the environment / git-ignored .env; never printed or logged).

If no RUNPOD_API_KEY is available the request is sent without an Authorization header: some hosted sandboxes
inject the credential at their egress proxy for rest.runpod.io only. The key is only ever sent to RunPod.
"""
import json
import os
import urllib.request
from pathlib import Path

BASE = "https://rest.runpod.io/v1"


def _key():
    if os.environ.get("RUNPOD_API_KEY"):
        return os.environ["RUNPOD_API_KEY"].strip()
    env = Path(__file__).parent / ".env"
    for line in env.read_text().splitlines() if env.exists() else []:
        if line.startswith("RUNPOD_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def headers():
    h = {"Content-Type": "application/json", "User-Agent": "sub01/1.0 (+https://github.com/nocontentinhere4-art/sub-01)"}
    key = _key()
    if key:
        h["Authorization"] = "Bearer " + key
    return h


def api(path, method="GET", body=None, timeout=60):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None, headers=headers())
    raw = urllib.request.urlopen(req, timeout=timeout).read()
    return json.loads(raw) if raw else None
