"""Per visual test, on stderr: the wall time, the load average and any Chromium still running before and after it.
(2026-10-07, main 448a0b8: in CI test_hand_switch's page did not boot within 180 s, fourth in the job. This shows
whether an earlier test leaves a browser or a page running, and how long each page takes to boot.)"""
import os
import subprocess
import sys
import time

import pytest


def _chromium():
    try:
        out = subprocess.run(["ps", "-eo", "pid,ppid,pcpu,rss,etimes,args"], capture_output=True, text=True, timeout=10).stdout
    except Exception as e:                                       # (no ps: say so, never fail a test on it)
        return [f"ps failed: {e}"]
    return [l.strip()[:160] for l in out.splitlines()[1:] if ("chrom" in l.lower() or "headless_shell" in l) and "ps -eo" not in l]


def _say(msg):
    print(f"[visual] {msg}", file=sys.stderr, flush=True)


@pytest.fixture(autouse=True)
def _runner_state(request):
    left = _chromium()
    _say(f"{request.node.nodeid}: start, load {os.getloadavg()[0]:.1f}, chromium processes left: {len(left)}")
    for l in left[:12]:
        _say("   " + l)
    t0 = time.time()
    yield
    left = _chromium()
    _say(f"{request.node.nodeid}: end after {time.time() - t0:.0f} s, load {os.getloadavg()[0]:.1f}, chromium processes: {len(left)}")
