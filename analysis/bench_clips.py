"""#59: does making a clip slow the brain tick? Run with `taskset -c 0 python analysis/bench_clips.py` to put the
server and the render on ONE CPU (worse than Railway's shared vCPUs; on several cores the child has a core of its own).

Starts `live_server.py --demo` (BROWSE=0, CLIPS=0, MIND=0), then reads /api/health (tick body time and loop lag over
the last minute, 1200 ticks) after three 62 s windows:
  1. idle (baseline);
  2. clips rendering back to back at nice 19, as the server runs them (a 30 s "day" clip from fixture frames);
  3. the same renders at nice 0 (what would happen without nice, for comparison).
Prints one JSON line per window and the render times. Needs ffmpeg.
"""
import argparse
import asyncio
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import clips  # noqa: E402
from sleep import TZ  # noqa: E402


def fixture_spec(tmp):
    """A 'day' clip spec like the server's: 12 room frames + 8 captioned events + the end card."""
    from PIL import Image, ImageDraw
    maker = clips.ClipMaker(tmp, clock=lambda: datetime(2026, 10, 2, 12, tzinfo=TZ).timestamp())
    day = "2026-10-01"
    d = maker.day_dir(day)
    t0 = datetime.fromisoformat(day).replace(tzinfo=TZ).timestamp()
    for i in range(12):
        im = Image.new("RGB", (720, 1280), (20 + 10 * i, 30, 50))
        ImageDraw.Draw(im).ellipse((100 + 20 * i, 300, 500, 900), fill=(200, 120, 60))
        im.save(d / f"room-000000-{i:03d}.jpg", quality=85)
    for i, h in enumerate((8, 10, 11, 14, 17, 19, 21, 23)):
        Image.new("RGB", (1280, 720), (40, 60 + 15 * i, 90)).save(d / f"shot-{h:02d}00.jpg", quality=85)
        maker.remember(day, {"kind": "event", "t": round(t0 + h * 3600 + 600), "text": f"event number {i}"})
    return maker.spec("day", day)


async def health(http, base, token):
    async with http.get(base + "/api/health", headers={"X-Admin-Token": token}) as r:
        h = await r.json()
    return {"tick_ms": h["tick_ms"], "loop_lag_ms": h["loop_lag_ms"]}


def render_loop(spec_path, nice, stop_at, ffmpeg):
    """Renders back to back until stop_at; returns [(wall s, cpu s)]."""
    out = []
    while time.time() < stop_at:
        t0 = time.monotonic()
        p = subprocess.run(["nice", "-n", str(nice), sys.executable, str(ROOT / "clips.py"), "render"],
                           stdin=open(spec_path), capture_output=True, text=True, env=clips.child_env())
        info = clips._json_tail(p.stdout)
        out.append((round(time.monotonic() - t0, 1), info.get("cpu_s")))
    return out


async def main(args):
    token = secrets.token_hex(8)
    tmp = Path(tempfile.mkdtemp(prefix="bench-clips-"))
    spec = fixture_spec(tmp)
    spec["ffmpeg"] = args.ffmpeg
    spec_path = tmp / "spec.json"
    spec_path.write_text(json.dumps(spec))
    env = dict(os.environ, BROWSE="0", CLIPS="0", MIND="0", SUB01_ADMIN_TOKEN=token)
    srv = subprocess.Popen([sys.executable, str(ROOT / "live_server.py"), "--demo", "--port", str(args.port),
                            "--data-dir", str(tmp / "data")], env=env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{args.port}"
    try:
        async with aiohttp.ClientSession() as http:
            for _ in range(120):
                try:
                    async with http.get(base + "/healthz") as r:
                        if r.status == 200:
                            break
                except aiohttp.ClientError:
                    pass
                await asyncio.sleep(1)
            print("cpus allowed:", len(os.sched_getaffinity(0)), flush=True)
            await asyncio.sleep(args.window)
            print(json.dumps({"window": "idle", **await health(http, base, token)}), flush=True)
            for nice in (clips.NICE, 0):
                stop = time.time() + args.window
                runs = await asyncio.to_thread(render_loop, spec_path, nice, stop, args.ffmpeg)
                print(json.dumps({"window": f"rendering at nice {nice}", **await health(http, base, token),
                                  "renders (wall s, cpu s)": runs}), flush=True)
                await asyncio.sleep(args.window)                  # let the ring buffer forget this window
    finally:
        srv.terminate()
        srv.wait()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8797)
    p.add_argument("--window", type=float, default=62.0)
    p.add_argument("--ffmpeg", default="ffmpeg")
    asyncio.run(main(p.parse_args()))
