"""#18: the server and Chromium run as uid 1000 with Chromium's own sandbox on (no browser or docker needed here).

- `browse.launch_kwargs` / `Browser._ensure`: `--no-sandbox` only as root or after a sandboxed launch failed (loud log).
- `entrypoint.sh` under a simulated root / non-root start (stub `id`, `find`, `chown`, `setpriv` on PATH).
The real image is checked by hand with docker (see the PR): ps shows uid 1000, a root-owned volume is handed over.
"""
import asyncio
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import browse  # noqa: E402
from browse import Browser, launch_kwargs  # noqa: E402


# --- browse flags ----------------------------------------------------------------------------------------------------
def test_launch_kwargs_sandbox_on():
    kw = launch_kwargs(True, environ={"PATH": "/bin", "HOME": "/home/sub01", "SITE_PASSWORD": "x", "ANTHROPIC_API_KEY": "y"})
    assert "--no-sandbox" not in kw["args"] and kw["chromium_sandbox"] is True
    assert kw["env"] == {"PATH": "/bin", "HOME": "/home/sub01"}                 # no secrets reach Chromium
    assert "executable_path" not in kw and "proxy" not in kw


def test_launch_kwargs_sandbox_off():
    kw = launch_kwargs(False, proxy="http://p:1", environ={"BROWSE_CHROMIUM": "/opt/chrome"})
    assert kw["args"][-1] == "--no-sandbox" and kw["args"].count("--no-sandbox") == 1
    assert kw["chromium_sandbox"] is False
    assert kw["executable_path"] == "/opt/chrome" and kw["proxy"] == {"server": "http://p:1"}
    assert kw["env"] == {}                                                     # BROWSE_CHROMIUM is not passed on


def _fake_pw(fail_sandboxed):
    calls = []

    async def launch(**kw):
        calls.append(kw)
        if fail_sandboxed and kw["chromium_sandbox"]:
            raise RuntimeError("No usable sandbox! (simulated)")
        page = mock.MagicMock()
        ctx = mock.MagicMock(route=mock.AsyncMock(), add_cookies=mock.AsyncMock(),
                             new_page=mock.AsyncMock(return_value=page))
        return mock.MagicMock(new_context=mock.AsyncMock(return_value=ctx), is_connected=lambda: True)

    pw = mock.MagicMock()
    pw.chromium.launch = launch
    return pw, calls


def _ensure(uid, fail_sandboxed=False, monkeypatch=None):
    pytest.importorskip("playwright.async_api")
    monkeypatch.setattr(browse.os, "geteuid", lambda: uid)
    b = Browser()
    b.pw, calls = _fake_pw(fail_sandboxed)
    asyncio.run(b._ensure("desk"))
    return b, calls


def test_nonroot_keeps_sandbox(monkeypatch, capsys):
    b, calls = _ensure(1000, monkeypatch=monkeypatch)
    assert len(calls) == 1 and calls[0]["chromium_sandbox"] and "--no-sandbox" not in calls[0]["args"]
    assert b.sandbox is True and "sandbox" not in capsys.readouterr().out.lower()


def test_root_no_sandbox_loudly(monkeypatch, capsys):
    b, calls = _ensure(0, monkeypatch=monkeypatch)
    assert len(calls) == 1 and "--no-sandbox" in calls[0]["args"] and not calls[0]["chromium_sandbox"]
    assert b.sandbox is False and "!!! running as root" in capsys.readouterr().out


def test_sandbox_failure_falls_back_loudly_and_sticks(monkeypatch, capsys):
    b, calls = _ensure(1000, fail_sandboxed=True, monkeypatch=monkeypatch)
    assert [c["chromium_sandbox"] for c in calls] == [True, False]
    assert "--no-sandbox" in calls[1]["args"] and b.sandbox is False and b.no_sandbox
    assert "SANDBOX FAILED TO START" in capsys.readouterr().out
    b.browser = None                                    # the browser died: the relaunch skips the failing attempt
    asyncio.run(b._ensure("desk"))
    assert [c["chromium_sandbox"] for c in calls] == [True, False, False]


def test_launch_failure_without_sandbox_is_raised(monkeypatch):
    pytest.importorskip("playwright.async_api")
    monkeypatch.setattr(browse.os, "geteuid", lambda: 0)
    b = Browser()
    b.pw = mock.MagicMock()
    b.pw.chromium.launch = mock.AsyncMock(side_effect=RuntimeError("no chromium"))
    with pytest.raises(RuntimeError):
        asyncio.run(b._ensure("desk"))
    assert b.pw.chromium.launch.await_count == 1


# --- entrypoint.sh -----------------------------------------------------------------------------------------------------
STUBS = {
    "id": 'echo "$FAKE_UID"',
    "find": '[ -n "$FAKE_FOREIGN" ] && echo "$FAKE_FOREIGN"; exit 0',
    "chown": 'echo "chown $*" >> "$CALLS"',
    "setpriv": 'echo "setpriv $* HOME=$HOME" >> "$CALLS"',
}


def _entry(tmp_path, uid, foreign="", env=None, data_mode=0o755):
    if not Path("/bin/sh").exists():
        pytest.skip("no /bin/sh")
    bindir, data, calls = tmp_path / "bin", tmp_path / "data", tmp_path / "calls"
    bindir.mkdir()
    data.mkdir(mode=data_mode)
    data.chmod(data_mode)
    for name, body in STUBS.items():
        (bindir / name).write_text(f"#!/bin/sh\n{body}\n")
        (bindir / name).chmod(0o755)
    e = {"PATH": f"{bindir}:/usr/bin:/bin", "FAKE_UID": str(uid), "FAKE_FOREIGN": foreign, "CALLS": str(calls),
         "SUB01_DATA_DIR": str(data), "HOME": "/root", **(env or {})}
    p = subprocess.run(["/bin/sh", str(ROOT / "entrypoint.sh"), "sh", "-c", 'echo "ran $0 as-is HOME=$HOME"', "cmd"],
                       env=e, capture_output=True, text=True, timeout=20)
    assert p.returncode == 0, p.stderr
    return p, (calls.read_text().splitlines() if calls.exists() else [])


def test_entrypoint_root_hands_over_data_and_drops(tmp_path):
    p, calls = _entry(tmp_path, 0, foreign=str(tmp_path / "data" / "state.json"))
    assert calls[0] == f"chown -R 1000:1000 {tmp_path / 'data'}"
    assert calls[1].startswith("setpriv --reuid=1000 --regid=1000 --clear-groups --inh-caps=-all --bounding-set=-all -- "
                               "sh -c ")
    assert calls[1].endswith("HOME=/home/sub01") and "ran" not in p.stdout     # the CMD runs only through setpriv


def test_entrypoint_root_already_owned_skips_chown(tmp_path):
    _, calls = _entry(tmp_path, 0)
    assert len(calls) == 1 and calls[0].startswith("setpriv --reuid=1000")


def test_entrypoint_rollback_stays_root(tmp_path):
    p, calls = _entry(tmp_path, 0, foreign="x", env={"RUN_AS_ROOT": "1"})
    assert calls == [] and "ran cmd as-is HOME=/root" in p.stdout and "RUN_AS_ROOT=1" in p.stderr


def test_entrypoint_nonroot_runs_cmd(tmp_path):
    p, calls = _entry(tmp_path, 1000, foreign="x")
    assert calls == [] and "ran cmd as-is" in p.stdout and p.stderr == ""


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root can write anywhere")
def test_entrypoint_nonroot_unwritable_data_warns(tmp_path):
    p, calls = _entry(tmp_path, 1000, data_mode=0o555)
    assert calls == [] and "ran cmd as-is" in p.stdout and "not writable" in p.stderr
