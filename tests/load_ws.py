"""Load test of the live websocket feeds (issue #14). Run by hand: `python tests/load_ws.py`
(no `test_` prefix: pytest does not collect it).

Starts `live_server.py --demo --trust-proxy` (BROWSE=0, a temporary data dir) and opens N simulated viewers, each
from its own made-up address (X-Forwarded-For), so the per-address cap does not refuse them:
  - brain page: one socket, /ws?rate=10&q=1;
  - room page: two sockets, the room's /ws?rate=5&lite=1 and its mini brain /ws?rate=5&q=1 (the PiP iframe);
  - slow readers: --slow extra sockets on plain /ws read at 1 message/s; the server must skip their ticks.
Every socket offers permessage-deflate, as browsers do (the server accepts it only for feeds other than q=1).

Reports:
  - brain tick lag from the server's own "ws stats" log lines (SUB01_WS_STATS_S=5 for the run): `late`, how late each
    tick's step starts against its 50 ms slot (the acceptance figure: what sends to viewers can delay), and `jitter`,
    how late each broadcast is against the fastest one (adds the brain step's own variation);
  - bytes/s per viewer type: the JSON received (raw) and on the wire (for a deflate socket, the meter re-compresses
    what it receives the way the server does: raw deflate, context takeover, sync flush);
  - the server's peak RSS and CPU share; sockets refused as full.

    python tests/load_ws.py                          # 300 viewers, half brain page, half room, 60 s
    python tests/load_ws.py --server-cpu 0           # the server pinned to one CPU (taskset -c 0)
    python tests/load_ws.py --viewers 300 --room-share 0.8 --seconds 120 --max-ws 400
Linux only for RSS/CPU (/proc). The clients run in this process; pin them elsewhere with --client-cpus 1-3.
"""
import argparse
import asyncio
import os
import random
import re
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parent.parent
FEEDS = {"brain": ["/ws?rate=10&q=1"], "room": ["/ws?rate=5&lite=1", "/ws?rate=5&q=1"]}
STATS = re.compile(r"ws stats: (\d+) sockets .* tick late p50 ([\d.]+) p95 ([\d.]+) max ([\d.]+) ms · "
                   r"jitter p50 ([\d.]+) "
                   r"p95 ([\d.]+) max ([\d.]+) ms · over (\d+) ticks · skipped (\d+) sends to slow clients · refused (\d+)")


class Meter:
    """Bytes received on one feed: the JSON (raw) and what it costs on the wire. When the server compresses the
    socket (permessage-deflate), the wire size is estimated by compressing the same stream the way it does
    (raw deflate, context takeover, sync flush per message); otherwise it is the raw size. Frame headers not counted."""

    def __init__(self):
        self.raw = self.wire = self.msgs = 0
        self.z = None
        self.deflate = None

    def connected(self, deflate):
        self.deflate = bool(deflate)
        self.z = zlib.compressobj(zlib.Z_BEST_SPEED, zlib.DEFLATED, -15) if deflate else None

    def add(self, text):
        b = text.encode()
        self.raw += len(b)
        self.msgs += 1
        self.wire += len(self.z.compress(b) + self.z.flush(zlib.Z_SYNC_FLUSH)) - 4 if self.z else len(b)  # -4: 00 00 ff ff


async def viewer(session, base, path, ip, meter, counters):
    try:
        async with session.ws_connect(base + path, headers={"X-Forwarded-For": ip}, compress=15, heartbeat=None,
                                      max_msg_size=0) as ws:
            counters["open"] += 1
            if meter is not None:
                meter.connected(ws.compress)
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    break
                if msg.data.startswith('{"type": "full"') or msg.data.startswith('{"type":"full"'):
                    counters["full"] += 1
                    break
                if meter is not None and counters["measuring"]:
                    meter.add(msg.data)
    except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError) as e:
        counters["errors"] += 1
        counters["last_error"] = repr(e)[:120]


async def stalled(session, base, ip, counters):
    """A viewer on a link far too slow for its feed: plain /ws (20 ticks/s, ~4 KB each) read at one message a second
    (pings are still answered while it reads). Its buffers fill within seconds; the server must then skip its ticks
    instead of queueing them or waiting for it."""
    try:
        async with session.ws_connect(base + "/ws", headers={"X-Forwarded-For": ip}, heartbeat=None,
                                      max_msg_size=0) as ws:
            counters["open"] += 1
            sock = ws._response.connection.transport.get_extra_info("socket")    # a small window, like a slow link
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
            while True:
                msg = await ws.receive()
                if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    counters["stalled_closed"] = counters.get("stalled_closed", 0) + 1
                    return
                await asyncio.sleep(1.0)
    except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError) as e:
        counters["errors"] += 1
        counters["last_error"] = repr(e)[:120]


def proc_stat(pid):
    stat = Path(f"/proc/{pid}/stat").read_text()
    f = stat[stat.rindex(")") + 2:].split()
    cpu = (int(f[11]) + int(f[12])) / os.sysconf("SC_CLK_TCK")
    rss = int(f[21]) * os.sysconf("SC_PAGE_SIZE") / 2 ** 20
    return cpu, rss


async def wait_ready(base, proc, timeout=90):
    t0 = time.monotonic()
    async with aiohttp.ClientSession() as s:
        while time.monotonic() - t0 < timeout:
            if proc.poll() is not None:
                raise RuntimeError(f"server exited with code {proc.returncode}")
            try:
                async with s.get(base + "/api/config", timeout=aiohttp.ClientTimeout(total=5)) as r:
                    if r.status == 200:
                        return
            except (aiohttp.ClientError, asyncio.TimeoutError):
                pass
            await asyncio.sleep(0.5)
    raise RuntimeError("server did not start")


async def run(args, proc, log_path):
    base = f"http://127.0.0.1:{args.port}"
    await wait_ready(base, proc)
    rng = random.Random(1)
    n_room = round(args.viewers * args.room_share)
    kinds = ["room"] * n_room + ["brain"] * (args.viewers - n_room)
    rng.shuffle(kinds)
    meters = {(k, p): Meter() for k, paths in FEEDS.items() for p in paths}       # one meter socket per feed
    counters = {"open": 0, "full": 0, "errors": 0, "last_error": "", "measuring": False}
    conn = aiohttp.TCPConnector(limit=0)
    async with aiohttp.ClientSession(connector=conn) as session:
        tasks, metered = [], set()
        for i, kind in enumerate(kinds):
            ip = f"10.{i // 65536 % 256}.{i // 256 % 256}.{i % 256}"
            for path in FEEDS[kind]:
                meter = None
                if (kind, path) not in metered:
                    metered.add((kind, path))
                    meter = meters[(kind, path)]
                tasks.append(asyncio.create_task(viewer(session, base, path, ip, meter, counters)))
            if i % 25 == 24:
                await asyncio.sleep(0.2)                      # viewers arrive over a few seconds, not in one burst
        for i in range(args.slow):
            tasks.append(asyncio.create_task(stalled(session, base, f"10.255.0.{i}", counters)))
        await asyncio.sleep(args.warmup)
        log_mark = log_path.stat().st_size
        cpu0, _ = proc_stat(proc.pid)
        t0, peak_rss = time.monotonic(), 0.0
        counters["measuring"] = True
        while time.monotonic() - t0 < args.seconds:
            await asyncio.sleep(1)
            peak_rss = max(peak_rss, proc_stat(proc.pid)[1])
            if proc.poll() is not None:
                raise RuntimeError("server died during the run")
        counters["measuring"] = False
        wall = time.monotonic() - t0
        cpu = proc_stat(proc.pid)[0] - cpu0
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    with open(log_path) as f:
        f.seek(log_mark)
        rows = [tuple(float(x) for x in m.groups()) for m in STATS.finditer(f.read())]
    if args.verbose:
        for r in rows:
            print(f"  window: {int(r[0])} sockets, tick late p50 {r[1]:.1f} p95 {r[2]:.1f} max {r[3]:.1f} ms, "
                  f"jitter p50 {r[4]:.1f} p95 {r[5]:.1f} max {r[6]:.1f} ms, skipped {int(r[8])}")
    print(f"\n{args.viewers} viewers ({n_room} room = 2 sockets each, {args.viewers - n_room} brain = 1 socket), "
          f"+ {args.slow} slow readers on plain /ws ({counters.get('stalled_closed', 0)} closed by the server); {len(tasks)} sockets connected, {counters['full']} of them refused as full, "
          f"{counters['errors']} errors {counters['last_error']}")
    print(f"server: {100 * cpu / wall:.0f}% of one core over {wall:.0f} s, peak RSS {peak_rss:.0f} MB"
          f"{' (pinned to CPU ' + args.server_cpu + ')' if args.server_cpu else ''}")
    late95 = None
    if rows:
        allr = lambda i: [r[i] for r in rows]
        late95 = max(allr(2))
        print(f"brain tick lag over {len(rows)} windows of {args.stats_s:g} s (p50: median window, p95/max: worst window):")
        print(f"  late (step start vs its 50 ms slot): p50 {statistics.median(allr(1)):.1f} ms, p95 {late95:.1f} ms, "
              f"max {max(allr(3)):.1f} ms")
        print(f"  jitter (broadcast vs the fastest tick, includes the step's own variation): "
              f"p50 {statistics.median(allr(4)):.1f} ms, p95 {max(allr(5)):.1f} ms, max {max(allr(6)):.1f} ms")
        print(f"  sockets in the server: {int(rows[-1][0])}; sends skipped for slow clients: {int(sum(allr(8)))}")
    else:
        print("brain tick lag: no 'ws stats' lines in the server log")
    print("bytes/s per viewer (raw JSON / on the wire, i.e. after permessage-deflate where the server uses it):")
    per_kind = {}
    for (kind, path), m in meters.items():
        raw, wire = m.raw / wall, m.wire / wall
        per_kind.setdefault(kind, [0.0, 0.0])
        per_kind[kind][0] += raw
        per_kind[kind][1] += wire
        print(f"  {kind:<5} {path:<20} {m.msgs / wall:5.1f} msg/s  {raw / 1024:6.1f} KB/s raw  {wire / 1024:6.1f} KB/s wire"
              f"{' (deflate)' if m.deflate else ''}"
              f"  ({m.raw / max(1, m.msgs):.0f} B a message raw)")
    for kind, (raw, wire) in per_kind.items():
        print(f"  {kind} page total: {raw / 1024:.1f} KB/s raw, {wire / 1024:.1f} KB/s wire")
    ok = bool(rows) and late95 < args.max_p95 and peak_rss < args.max_rss
    print(f"\nACCEPTANCE (tick late p95 < {args.max_p95:g} ms, RSS < {args.max_rss:g} MB): {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--viewers", type=int, default=300)
    p.add_argument("--room-share", type=float, default=0.5, help="share of viewers on the room page (2 sockets each)")
    p.add_argument("--seconds", type=float, default=60.0, help="measurement window")
    p.add_argument("--warmup", type=float, default=10.0, help="seconds after the last viewer joined")
    p.add_argument("--port", type=int, default=8790)
    p.add_argument("--server-cpu", help="pin the server with taskset -c (e.g. 0)")
    p.add_argument("--client-cpus", help="pin this client process with taskset (e.g. 1-3)")
    p.add_argument("--max-ws", type=int, help="SUB01_MAX_WS for the run (default: room for every socket)")
    p.add_argument("--stats-s", type=float, default=5.0, help="SUB01_WS_STATS_S for the run")
    p.add_argument("--max-p95", type=float, default=25.0)
    p.add_argument("--max-rss", type=float, default=400.0)
    p.add_argument("--verbose", action="store_true", help="print every stats window")
    p.add_argument("--keep-log", help="copy the server log here at the end")
    p.add_argument("--slow", type=int, default=10, help="extra sockets on plain /ws read at 1 message/s")
    args = p.parse_args()

    if args.client_cpus:
        os.sched_setaffinity(0, {c for part in args.client_cpus.split(",") for c in
                                 range(int(part.split("-")[0]), int(part.split("-")[-1]) + 1)})
    n_sockets = round(args.viewers * args.room_share) * 2 + args.viewers - round(args.viewers * args.room_share) + args.slow
    tmp = tempfile.TemporaryDirectory(prefix="sub01-load-")
    env = dict(os.environ, BROWSE="0", PYTHONUNBUFFERED="1", SUB01_WS_STATS_S=str(args.stats_s),
               SUB01_MAX_WS=str(args.max_ws or max(400, n_sockets + 10)))
    env.setdefault("OPENBLAS_NUM_THREADS", "1")
    env.setdefault("OMP_NUM_THREADS", "1")
    env.pop("SITE_PASSWORD", None)
    cmd = [sys.executable, str(ROOT / "live_server.py"), "--demo", "--trust-proxy", "--port", str(args.port),
           "--data-dir", tmp.name]
    if args.server_cpu:
        cmd = ["taskset", "-c", args.server_cpu] + cmd
    log_path = Path(tmp.name) / "server.log"
    print("$", " ".join(cmd[cmd.index(sys.executable):] if sys.executable in cmd else cmd),
          f"(SUB01_MAX_WS={env['SUB01_MAX_WS']}{', taskset -c ' + args.server_cpu if args.server_cpu else ''})")
    with open(log_path, "w") as log:
        proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        ok = asyncio.run(run(args, proc, log_path))
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        if args.keep_log:
            Path(args.keep_log).write_text(log_path.read_text())
        tmp.cleanup()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
