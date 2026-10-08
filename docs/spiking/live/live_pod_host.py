"""Runs ON the validation pod (#58): the server side of the live protocol next to the session, so a controller
outside RunPod can drive real decide / reward rounds through the RunPod proxy.

- spiking/server.py's SpikingHub (the same code Railway runs) on port 8001, with the pod routes;
- spiking.session in a child process, its websocket pointed at that hub (SUB01_SERVER_URL=http://127.0.0.1:8001);
- driver routes (header X-Drive-Token = SUB01_DRIVE_TOKEN): POST /drive/decide {options, kind, deadline_ms},
  POST /drive/reward {id, value}, POST /drive/night {day, items, decisions}, POST /drive/stop, GET /drive/status.
The hub logs decisions and stores uploaded weights under /out/host/spiking/ (served on port 8000 with /out).
"""
import asyncio
import hmac
import json
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    ZoneInfo("Asia/Tokyo")
except Exception:                                         # no tz database in the image
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "tzdata"], check=False)

from aiohttp import web

APP = os.environ.get("SUB01_APP_DIR", "/app")
sys.path.insert(0, APP)
from spiking import server as spiking_server  # noqa: E402

TOKEN = os.environ["SUB01_DRIVE_TOKEN"]
SECRET = os.environ["SUB01_POD_SECRET"]
OUT = Path(os.environ.get("SUB01_OUT_DIR", "/out"))


class Live:
    def __init__(self):
        self.spiking = None

    async def broadcast(self, msg):
        pass


async def main():
    live = Live()
    app = web.Application(client_max_size=64 * 1024 ** 2)
    hub = spiking_server.attach(app, live, OUT / "host", secret=SECRET)
    t_start = time.time()

    def check(request):
        if not hmac.compare_digest(request.headers.get("X-Drive-Token", ""), TOKEN):
            raise web.HTTPUnauthorized()

    async def decide(request):
        check(request)
        d = await request.json()
        t0 = time.monotonic()
        out = await hub.decide(d["options"], d.get("kind", "browse"), int(d.get("deadline_ms", 2000)))
        return web.json_response({"decision": out, "hub_ms": round((time.monotonic() - t0) * 1000, 1)})

    async def reward(request):
        check(request)
        d = await request.json()
        return web.json_response({"ok": hub.reward(d["id"], d["value"])})

    async def night(request):
        check(request)
        return web.json_response({"ok": await hub.send_night(await request.json())})

    async def stop(request):
        check(request)
        return web.json_response({"ok": await hub.forward_stop()})

    async def status(request):
        check(request)
        w = OUT / "host" / "spiking" / "weights.npz"
        return web.json_response({"connected": hub.connected, "live_ready": hub.live_ready, "stats": hub.decide_stats,
                                  "phase": (hub.last_state or {}).get("phase"),
                                  "realtime_x": (hub.last_state or {}).get("realtime_x"),
                                  "weights_bytes": w.stat().st_size if w.exists() else None,
                                  "weights_mtime": w.stat().st_mtime if w.exists() else None,
                                  "uptime_s": round(time.time() - t_start, 1),
                                  "session_exit": proc.poll()})

    for path, fn in (("/drive/decide", decide), ("/drive/reward", reward), ("/drive/night", night),
                     ("/drive/stop", stop)):
        app.router.add_post(path, fn)
    app.router.add_get("/drive/status", status)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8001).start()
    env = dict(os.environ, SUB01_SERVER_URL="http://127.0.0.1:8001", SUB01_OUT=str(OUT))
    log = open(OUT / "session_inner.log", "w")
    proc = subprocess.Popen([sys.executable, "-m", "spiking.session"], cwd=APP, env=env, stdout=log,
                            stderr=subprocess.STDOUT)
    while proc.poll() is None:
        await asyncio.sleep(1)
    await asyncio.sleep(3600)                           # keep the hub readable until the controller deletes the pod


if __name__ == "__main__":
    asyncio.run(main())
