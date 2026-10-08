"""A small stand-in for live_server.py that serves `web/` with a fake `/ws` (issue #98, G8).

The room page (web/room.html) connects to `/ws?rate=5&lite=1` and expects `hello` and then `tick` messages carrying
`life` (life.py's snapshot), `sleep` (stage, clock) and `neuro`. This server sends one scripted scene at 5 ticks a
second: the scene is set by the test through `GET /__qa/scene?name=<scene>&hour=<h>` (see scenes.py), so the character
is put into an activity without the brain model, the body model or any paid service. Every `/api/*` read endpoint the
page fetches answers a small empty JSON so the cards stay quiet; `/brain` (the PiP iframe) is a dark stub page, because
the real brain page draws a million fibres and would starve a software-WebGL run.

Run it by hand to look at a scene in a browser:

    python -m tests.visual.fake_server --port 8797
    # then open http://127.0.0.1:8797/room.html?debug&hour=19 and
    #      curl 'http://127.0.0.1:8797/__qa/scene?name=eating&hour=19'

No network is used besides the browser's own CDN fetches (three.js from jsdelivr, leaflet from unpkg, as the page does).
"""
import argparse
import asyncio
import json
from pathlib import Path

from aiohttp import web

from . import scenes as S

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
BRAIN_STUB = ("<!doctype html><html><head><meta charset='utf-8'><title>brain stub</title></head>"
              "<body style='margin:0;background:#000;color:#555;font:10px monospace'>"
              "<div style='padding:6px'>brain PiP stubbed by tests/visual</div></body></html>")
API_EMPTY = {
    "/api/mind": {"on": False}, "/api/music": {"now": None}, "/api/chess": {"playing": False},
    "/api/memory": {"items": []}, "/api/taught": {"left": 30, "per_day": 30, "today": [], "yesterday": [], "gpu": False,
                                                  "note": "visual QA: no server"},
    "/api/config": {"qa": True}, "/api/diary": {}, "/api/reading": {}, "/api/frames": [], "/api/browsing": {},
    "/api/screens": {}, "/api/tastes": {}, "/api/spiking/live": {},
}


class State:
    def __init__(self):
        self.scene = "desk"
        self.hour = 14
        self.version = 0
        self.clients = set()
        self.hits = []          # every request path, for the test's own-origin 404 check


def make_app(state=None):
    st = state or State()
    app = web.Application()
    app["state"] = st

    @web.middleware
    async def log_hits(request, handler):
        resp = await handler(request)
        st.hits.append((request.path_qs, getattr(resp, "status", 0)))
        return resp
    app.middlewares.append(log_hits)

    async def ws(request):
        sock = web.WebSocketResponse(heartbeat=20)
        await sock.prepare(request)
        st.clients.add(sock)
        brain = request.query.get("lite") is None            # the brain page (and the room's mini brain) asks for the full feed
        try:
            await sock.send_json({"type": "hello", "chat": [], "replies": [], "music": None})
            seen = -1
            while not sock.closed:
                msg = S.tick(st.scene, st.hour)
                if brain:
                    msg = dict(msg, act=S.ACT_FLAT, sync=0.4, groups={})
                await sock.send_json(msg)
                seen = st.version
                try:
                    await asyncio.wait_for(sock.receive(), timeout=0.2)     # chat / teach from the page: acknowledged, dropped
                    if sock.closed:
                        break
                    await sock.send_json({"type": "chat_ack", "ok": False, "reason": "visual QA server"})
                except asyncio.TimeoutError:
                    pass
        finally:
            st.clients.discard(sock)
        return sock

    async def set_scene(request):
        name = request.query.get("name", st.scene)
        if name not in S.SCENES:
            return web.json_response({"error": f"unknown scene {name}", "scenes": sorted(S.SCENES)}, status=400)
        st.scene = name
        st.hour = float(request.query.get("hour", st.hour))
        st.version += 1
        return web.json_response({"scene": st.scene, "hour": st.hour, "version": st.version, "tick": S.tick(st.scene, st.hour)})

    async def brain(request):
        return web.Response(text=BRAIN_STUB, content_type="text/html")

    async def mini_brain(request):                             # what /brain?mini serves live: web/index.html (its data files are static)
        return web.Response(text=(WEB / "index.html").read_text(), content_type="text/html")

    async def api(request):
        return web.json_response(API_EMPTY[request.path])

    async def room(request):
        raise web.HTTPFound("/room.html" + (("?" + request.query_string) if request.query_string else ""))

    app.router.add_get("/ws", ws)
    app.router.add_get("/__qa/scene", set_scene)
    app.router.add_get("/brain", brain)                       # the room's PiP iframe: a stub (software GL budget)
    app.router.add_get("/mini-brain", mini_brain)              # the real /brain?mini page, for the harness's own PiP check
    for p in API_EMPTY:
        app.router.add_get(p, api)
    app.router.add_get("/", room)
    app.router.add_static("/", WEB)
    return app


async def start(port=0, host="127.0.0.1"):
    """Start in the current loop; returns (runner, base_url, state)."""
    st = State()
    runner = web.AppRunner(make_app(st), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    real = site._server.sockets[0].getsockname()[1]
    return runner, f"http://{host}:{real}", st


class Server:
    """The fake server in a background thread, for synchronous Playwright code."""

    def __init__(self, port=0):
        import threading
        self.port = port
        self.base = None
        self.state = None
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        asyncio.set_event_loop(self._loop)
        self._runner, self.base, self.state = self._loop.run_until_complete(start(self.port))
        self._ready.set()
        self._loop.run_forever()
        self._loop.run_until_complete(self._runner.cleanup())

    def __enter__(self):
        self._thread.start()
        self._ready.wait(20)
        return self

    def __exit__(self, *a):
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(10)

    def set_scene(self, name, hour):
        async def _set():
            self.state.scene, self.state.hour = name, float(hour)
            self.state.version += 1
        fut = asyncio.run_coroutine_threadsafe(_set(), self._loop)
        fut.result(5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8797)
    args = ap.parse_args()

    async def run():
        runner, base, st = await start(args.port)
        print(f"visual QA server on {base}/room.html?debug&hour={st.hour:g}  (scenes: {', '.join(sorted(S.SCENES))})")
        print(f"set a scene: {base}/__qa/scene?name=eating&hour=19")
        while True:
            await asyncio.sleep(3600)
    asyncio.run(run())


if __name__ == "__main__":
    main()
