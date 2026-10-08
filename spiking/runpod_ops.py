"""Create, watch and delete our RunPod pods safely (shared by pod_manager and validate).

Hard rules: at most one pod whose name starts with `sub01-spiking-`; a total GPU-hour cap over the cost log; every
stop/delete first re-fetches the pod and refuses unless it is ours (other pods, e.g. the user's `BRAIN`, are never
touched); the RunPod key is only ever sent to rest.runpod.io (pod pages are fetched without credentials).
"""
import atexit
import contextlib
import json
import os
import re
import signal
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone

import runpod_api
from spiking import podpack

PREFIX = "sub01-spiking-"
CREATE_TIMEOUT_S = 150              # RunPod can take more than a minute to place a pod when stock is low
ADOPT_TRIES, ADOPT_EVERY_S = 6, 10  # after an ambiguous create error: look for the pod by name for ~1 min


class NotOurs(RuntimeError):
    """A stop/delete was requested for a pod whose name does not start with our prefix."""


class CapExceeded(RuntimeError):
    pass


class Busy(RuntimeError):
    """A pod with our prefix already exists (ours, an orphan, or another session's validation pod)."""


class CreateFailed(RuntimeError):
    """No pod was created: every GPU type was refused (`errors`: one short line per attempt)."""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("could not create a pod: " + "; ".join(self.errors))


_SECRETISH = re.compile(r"(?i)(bearer\s+\S+|[0-9a-f]{32,}|rpa_[0-9a-z]+|(?:key|token|secret)[\"'=: ]+\S+)")


def scrub(text, n=200):
    """One short line for a log or the status page: no newlines, nothing that looks like a key or a token."""
    return _SECRETISH.sub("[redacted]", " ".join(str(text or "").split()))[:n]


def describe(e):
    """What an API error says, for a log line: the HTTP code and RunPod's own message when there is one."""
    code = getattr(e, "code", None)
    msg = ""
    if code is not None:
        try:
            body = e.read()
            try:
                msg = json.loads(body).get("error") or ""
            except (ValueError, AttributeError):
                msg = body.decode(errors="replace")
        except Exception:
            pass
        return scrub(f"HTTP {code}: {msg}" if msg else f"HTTP {code}", 160)
    return scrub(f"{type(e).__name__}: {e}", 160)


class DeadlineExceeded(RuntimeError):
    pass


def _pods(raw):
    return raw.get("pods", []) if isinstance(raw, dict) else (raw or [])


class RunPodOps:
    def __init__(self, api=None, log=None, prefix=PREFIX, hours_cap=None, sleep=time.sleep, clock=time.monotonic,
                 opener=None, install_hooks=True, cap_days=None):
        self.api = api or runpod_api.api
        self.log = log
        self.prefix = prefix
        self.hours_cap = float(hours_cap if hours_cap is not None else os.environ.get("SUB01_GPU_HOURS_CAP") or 4.0)
        self.cap_days = cap_days                  # None: cap over the whole cost log; else a rolling window
        self.sleep, self.clock = sleep, clock
        self.opener = opener or urllib.request.urlopen
        self.deadlines = {}                       # pod_id -> clock() value after which it must be deleted
        self.created = set()                      # pods created by this process
        self.deleted = set()
        self._lock = threading.RLock()
        self._hooks = not install_hooks            # atexit + SIGTERM cleanup of pods created by this process

    # --- listing -------------------------------------------------------------------
    def pods(self):
        return _pods(self.api("/pods"))

    def ours(self):
        return [p for p in self.pods() if str(p.get("name", "")).startswith(self.prefix)]

    def _assert_ours(self, pod_id):
        """Re-fetch the pod; return it, or None if it no longer exists. Refuse anything not ours."""
        for p in self.pods():
            if p.get("id") == pod_id:
                if not str(p.get("name", "")).startswith(self.prefix):
                    raise NotOurs(f"refusing to touch pod {pod_id}: not one of ours")
                return p
        return None

    # --- create --------------------------------------------------------------------
    def create(self, env, purpose, module="spiking.session", max_minutes=60, gpus=None):
        """Create the one allowed pod, log its start, remember its deadline. `gpus`: [(gpu type, cloud)] tried in
        order (default: podpack.GPUS on the secure cloud: A5000, else 4000 Ada, ...)."""
        with self._lock:
            mine = self.ours()
            if mine:
                raise Busy("a pod of ours already exists (" + ", ".join(str(p.get("name"))[:60] for p in mine)
                           + "); at most one at a time")
            used = (self.log.hours_since(self.cap_days) if self.cap_days else self.log.total_hours()) if self.log else 0.0
            if used + max_minutes / 60 > self.hours_cap + 1e-9:
                raise CapExceeded(f"GPU-hour cap: {used:.2f} h used + {max_minutes / 60:.2f} h > {self.hours_cap:.2f} h")
            name = f"{self.prefix}{purpose}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
            pod, gpu, cloud, errors = None, None, "SECURE", []
            self.last_create_errors = errors
            for gpu, cloud in (gpus or [(g, "SECURE") for g in podpack.GPUS]):
                try:
                    pod = self.api("/pods", "POST", podpack.create_body(env, name, gpu, module, cloud),
                                   timeout=CREATE_TIMEOUT_S)
                    break
                except Exception as e:                                    # no capacity / refused: try the next type
                    errors.append(f"{gpu} ({cloud.lower()}): {describe(e)}")
                    # a refusal with an HTTP answer created nothing; a timeout or a dropped connection may have:
                    # look for it by name for a while, so it is tracked and logged, never left running as an orphan
                    tries = 1 if getattr(e, "code", None) is not None else ADOPT_TRIES
                    for i in range(tries):
                        pod = next((p for p in self.ours() if p.get("name") == name), None)
                        if pod or i == tries - 1:
                            break
                        self.sleep(ADOPT_EVERY_S)
                    if pod:
                        errors.append(f"{gpu}: created despite the error (adopted)")
                        break
            if not pod or not pod.get("id"):
                raise CreateFailed(errors or ["no id returned"])
            pod_id = pod["id"]
            pod = dict(pod, _gpu=gpu, _cloud=cloud)
            self.created.add(pod_id)
            self._install_hooks()
            try:
                rate = pod.get("costPerHr") or pod.get("adjustedCostPerHr")
                if rate is None:
                    rate = next((p.get("costPerHr") for p in self.pods() if p.get("id") == pod_id), None)
                if self.log:
                    self.log.start(pod_id, name, gpu if cloud == "SECURE" else f"{gpu} ({cloud.lower()})", rate or 0.0,
                                   purpose)
            except Exception:
                self.delete(pod_id, "log failure")
                raise
            self.deadlines[pod_id] = self.clock() + max_minutes * 60
            return pod

    # --- delete --------------------------------------------------------------------
    def delete(self, pod_id, reason, retries=3, verify_tries=6):
        """DELETE with retries, then confirm it is gone and log the stop. Returns True when gone."""
        with self._lock:
            if pod_id in self.deleted:
                return True
            pod = self._assert_ours(pod_id)
            err = None
            for i in range(retries if pod else 0):
                try:
                    self.api(f"/pods/{pod_id}", "DELETE")
                    err = None
                    break
                except Exception as e:
                    if getattr(e, "code", None) == 404:
                        err = None
                        break
                    err = e
                    self.sleep(2 ** (i + 1))
            gone = False
            for i in range(verify_tries):
                if not any(p.get("id") == pod_id for p in self.pods()):
                    gone = True
                    break
                if err is None and i < verify_tries - 1:
                    self.sleep(1 + i)
            if gone:
                self.deleted.add(pod_id)
                self.deadlines.pop(pod_id, None)
                if self.log:
                    self.log.stop(pod_id, reason)
                return True
            raise RuntimeError(f"pod {pod_id} still exists after delete attempts"
                               + (f" ({type(err).__name__})" if err else ""))

    def cleanup_ours(self, reason="cleanup"):
        """Delete every pod with our prefix (crash recovery). Never touches other pods."""
        done = []
        for p in self.ours():
            try:
                if self.delete(p["id"], reason):
                    done.append(p["id"])
            except Exception as e:
                print(f"cleanup: could not delete {p.get('id')}: {type(e).__name__}", file=sys.stderr, flush=True)
        return done

    # --- watching ------------------------------------------------------------------
    def proxy_url(self, pod_id, path):
        return f"https://{pod_id}-8000.proxy.runpod.net/{path.lstrip('/')}"

    def fetch(self, pod_id, path, timeout=20):
        """One credential-free GET of a file served by the pod; raises on any failure."""
        req = urllib.request.Request(self.proxy_url(pod_id, path), headers={"User-Agent": "sub01/1.0"})
        with self.opener(req, timeout=timeout) as r:
            return r.read()

    def upload(self, pod_id, data, token, timeout=900, interval=10):
        """PUT the pack to the pod's bootstrap server once it answers (credential-free; one-time token)."""
        self.wait_http(pod_id, "status.json", timeout=timeout, interval=interval)
        last = None
        for i in range(5):
            try:
                req = urllib.request.Request(self.proxy_url(pod_id, "upload"), data=data, method="PUT",
                                             headers={"X-Upload-Token": token, "User-Agent": "sub01/1.0",
                                                      "Content-Type": "application/octet-stream"})
                with self.opener(req, timeout=300) as r:
                    if r.status == 200:
                        return True
            except Exception as e:
                last = e
                if getattr(e, "code", None) in (400, 403):              # rejected for good (bad pack / token)
                    break
            self.sleep(5 * (i + 1))
        raise RuntimeError(f"pack upload to {pod_id} failed ({type(last).__name__ if last else 'no 200'})")

    def wait_http(self, pod_id, path, timeout=600, interval=5):
        end = self.clock() + timeout
        last = None
        while True:
            try:
                return self.fetch(pod_id, path)
            except Exception as e:
                last = e
            if self.clock() >= end:
                raise TimeoutError(f"{path} not served by the pod within {timeout}s ({type(last).__name__})")
            self.sleep(interval)

    @contextlib.contextmanager
    def guard(self, pod_id, deadline=None):
        """Delete the pod on any exception, on KeyboardInterrupt, and when the deadline passes (a timer fires
        even if the body is blocked). A clean exit leaves the pod to the caller's explicit delete()."""
        deadline = self.deadlines.get(pod_id) if deadline is None else deadline
        expired = threading.Event()

        def fire():
            expired.set()
            try:
                self.delete(pod_id, "deadline")
            except Exception as e:
                print(f"deadline delete failed: {type(e).__name__}", file=sys.stderr, flush=True)

        timer = None
        if deadline is not None:
            timer = threading.Timer(max(0.0, deadline - self.clock()), fire)
            timer.daemon = True
            timer.start()
        try:
            yield self
        except BaseException as e:
            if timer:
                timer.cancel()
            reason = "interrupted" if isinstance(e, KeyboardInterrupt) else f"error: {type(e).__name__}"
            if not expired.is_set():
                self.delete(pod_id, reason)
            raise
        else:
            if timer:
                timer.cancel()
            if expired.is_set() or (deadline is not None and self.clock() >= deadline):
                self.delete(pod_id, "deadline")
                raise DeadlineExceeded(f"pod {pod_id} reached its deadline")
        finally:
            if timer and expired.is_set():
                with self._lock:                                  # wait for an in-flight deadline delete
                    pass

    # --- process exit --------------------------------------------------------------
    def _install_hooks(self):
        if self._hooks:
            return
        self._hooks = True
        atexit.register(self._exit_cleanup)
        try:
            prev = signal.getsignal(signal.SIGTERM)

            def on_term(signum, frame):
                self._exit_cleanup()
                if callable(prev):
                    prev(signum, frame)
                else:
                    raise SystemExit(143)
            signal.signal(signal.SIGTERM, on_term)
        except (ValueError, OSError):                              # not the main thread
            pass

    def _exit_cleanup(self):
        for pod_id in list(self.created - self.deleted):
            try:
                self.delete(pod_id, "process exit")
            except Exception as e:
                print(f"exit cleanup: could not delete {pod_id}: {type(e).__name__}", file=sys.stderr, flush=True)
