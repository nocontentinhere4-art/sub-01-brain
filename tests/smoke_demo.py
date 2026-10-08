"""Smoke test of the live server in --demo mode (CI job `smoke`; run locally with `python tests/smoke_demo.py`).

Starts `live_server.py --demo` with BROWSE=0 in a temporary data dir, waits for /api/config, checks HTTP 200 on the
pages and read APIs, checks that /ws sends a `tick` within 10 s, then prints the server's CPU cost per tick, read
from /proc/<pid>/stat over 20 s of /ws (Linux only; skipped with a note elsewhere).
With --torn-state the data dir first gets state files cut off mid-write (a kill during a save, issue #21): the server
must still start, log one "is corrupt" line per file and keep each one aside as <name>.corrupt-<UTC time>.
With --mind (#33) the clock runs 60x from 09:00 Tokyo and a chat message ("are you a real person? n", answered by a
rule, no AI key needed) is sent every 11 s during the measurement, so the day plan (voted by a brain clone) and the
chat replies run while the tick cost is measured; the run fails if no plan arrives.
After the first tick (#15): /healthz answers 200, /api/costs and /api/health answer 401 without the admin token and
200 with it (a random SUB01_ADMIN_TOKEN is set for the server), and /api/health's tick time is printed.
With --youtube-chess (#17) the clock runs 60x from 10:00 Tokyo and a chat wish ("let's play chess", and with
--browse also "put on some youtube") is sent every 11 s: the run fails unless a chess game is played to its end (and,
with --browse, a video is watched) during the measurement. --browse starts the real browser (BROWSE=1, needs
playwright + Chromium + network) and prints the browser's peak memory while a video plays.
No `test_` prefix, so pytest does not collect it.
"""
import argparse
import asyncio
import os
import secrets
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parent.parent
PATHS = ["/", "/brain", "/diary", "/tastes.html", "/tokyo_area.json", "/api/diary", "/api/reading", "/api/frames", "/api/browsing", "/api/screens", "/api/tastes",
         "/api/taught", "/api/mind", "/api/chess", "/api/music", "/api/spiking/live"]
ADMIN = {"X-Admin-Token": secrets.token_hex(16)}     # the server gets it as SUB01_ADMIN_TOKEN
TICK_S = 0.05            # live_server.TICK: one broadcast per 50 ms
TORN = {                 # state files read back at startup, each cut off mid-write
    "life.json": '{"activity": "research", "path": [], "hunger',
    "body.json": '{"body": {"ghrelin": 0.4, "glucose',
    "reading.json": '{"log": [{"title": "Bread", "url": "https://en.wikipedia.org/wiki/Br',
    "state.json": '{"engine": {"t": 1790000000.0, "stage": "AWAKE", "pressure": 0.3',
}


def seed_torn(data_dir):
    d = Path(data_dir)
    d.mkdir(parents=True, exist_ok=True)
    for name, text in TORN.items():
        (d / name).write_text(text)


def check_torn(data_dir, log_text):
    failures = []
    for name in TORN:
        kept = list(Path(data_dir).glob(name + ".corrupt-*"))
        lines = [ln for ln in log_text.splitlines() if f"{name} is corrupt" in ln]
        ok = len(kept) == 1 and len(lines) == 1
        print(f"{'ok  ' if ok else 'FAIL'} torn {name:<13} {len(lines)} log line, kept aside: {kept[0].name if kept else '-'}")
        if not ok:
            failures.append(f"torn {name}: {len(lines)} log lines, {len(kept)} files kept aside")
    return failures


def browser_mb(server_pid):
    """Memory (PSS) of the browser service child and its Chromium processes, as its own watchdog counts it."""
    sys.path.insert(0, str(ROOT))
    from browse_service import descendants, tree_rss_mb
    return sum(tree_rss_mb(p) for p in descendants(server_pid) if p != server_pid
               and "browse_service" in Path(f"/proc/{p}/cmdline").read_bytes().decode(errors="replace"))


def spiking_child(server_pid):
    """Pid of the daytime spiking network's process (spiking/live.py, #55), or None."""
    sys.path.insert(0, str(ROOT))
    from browse_service import descendants
    for p in descendants(server_pid):
        try:
            if b"spiking.live" in Path(f"/proc/{p}/cmdline").read_bytes():
                return p
        except OSError:
            pass
    return None


def cpu_seconds(pid):
    """utime + stime of a process, in seconds (fields 14 and 15 of /proc/<pid>/stat)."""
    stat = Path(f"/proc/{pid}/stat").read_text()
    fields = stat[stat.rindex(")") + 2:].split()      # skip "pid (comm) ", comm may contain spaces
    return (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")


async def wait_ready(session, base, proc, timeout):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if proc.poll() is not None:
            raise RuntimeError(f"server exited with code {proc.returncode} before /api/config answered")
        try:                                        # a slow answer while starting up is retried like a refusal
            async with session.get(base + "/api/config", timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status == 200:
                    return time.monotonic() - t0
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
        await asyncio.sleep(0.5)
    raise RuntimeError(f"/api/config did not answer within {timeout:g} s")


async def run(args, proc):
    base = f"http://127.0.0.1:{args.port}"
    failures = []
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
        ready = await wait_ready(s, base, proc, args.startup_timeout)
        print(f"ready: /api/config answered after {ready:.1f} s")
        for path in PATHS:
            async with s.get(base + path) as r:
                body = await r.read()
                ok = r.status == 200
                print(f"{'ok  ' if ok else 'FAIL'} GET {path:<14} {r.status}  {len(body)} bytes")
                if not ok:
                    failures.append(f"GET {path} -> {r.status}")

        async with s.ws_connect(base + "/ws") as ws:
            t0 = time.monotonic()
            first = None
            while time.monotonic() - t0 < 10:
                try:
                    msg = await ws.receive_json(timeout=max(0.1, 10 - (time.monotonic() - t0)))
                except asyncio.TimeoutError:
                    break
                if msg.get("type") == "tick":
                    first = time.monotonic() - t0
                    break
            if first is None:
                print("FAIL /ws sent no tick within 10 s")
                failures.append("/ws: no tick within 10 s")
                return failures
            print(f"ok   /ws first tick after {first:.2f} s")
            for path, headers, want in (("/healthz", None, 200), ("/api/costs", None, 401), ("/api/costs", ADMIN, 200),
                                        ("/api/health", None, 401), ("/api/health", ADMIN, 200)):
                async with s.get(base + path, headers=headers) as r:
                    body = await r.read()
                    ok = r.status == want
                    print(f"{'ok  ' if ok else 'FAIL'} GET {path:<14} {r.status}  {len(body)} bytes"
                          f"{' (admin token)' if headers else ''}")
                    if not ok:
                        failures.append(f"GET {path} -> {r.status}, expected {want}")

            # tick cost: server CPU seconds over a window of /ws, divided by the ticks received in it
            linux = Path(f"/proc/{proc.pid}/stat").exists()
            cpu0 = cpu_seconds(proc.pid) if linux else None
            child = spiking_child(proc.pid) if linux else None
            child0 = cpu_seconds(child) if child else None
            t0, ticks, seen, sent, next_chat = time.monotonic(), 0, {}, 0, time.monotonic()
            chatty = args.mind or args.youtube_chess or args.music
            games, videos, peak, tracks = [], [], 0.0, []
            while time.monotonic() - t0 < args.measure:
                if chatty and time.monotonic() >= next_chat:      # one message per 11 s (chat limit: 1 per 10 s)
                    sent += 1
                    if args.mind:
                        text = f"are you a real person? {sent}"
                    elif args.music:
                        text = f"play some city pop {sent}" if sent % 2 else f"metti un po' di lofi {sent}"
                    elif args.browse and sent % 2 == 0:
                        text = f"put on some youtube {sent}"
                    else:
                        text = f"let's play chess {sent}"
                    await ws.send_json({"type": "chat", "text": text})
                    next_chat += 11
                    if args.browse:                               # the browser's memory while it works
                        peak = max(peak, browser_mb(proc.pid))
                try:
                    wait = min(args.measure - (time.monotonic() - t0), max(0.0, next_chat - time.monotonic())
                               if args.mind else args.measure)
                    msg = await ws.receive_json(timeout=max(0.1, wait))
                except asyncio.TimeoutError:
                    continue
                ticks += msg.get("type") == "tick"
                seen[msg.get("type")] = seen.get(msg.get("type"), 0) + 1
                if msg.get("type") == "chess" and msg.get("finished"):
                    games.append(msg)
                    print(f"chess: game over after {msg['plies']} plies, {msg['result']} ({msg['reason']}); "
                          f"last card: {(msg.get('vote') or {}).get('move')} of "
                          f"{[o['label'] for o in (msg.get('vote') or {}).get('options', [])]}")
                if msg.get("type") == "music" and msg.get("playing"):
                    tracks.append(msg)
                    print(f"music: {msg.get('title')!r} ({msg.get('genre_label')}, {msg.get('mode')}) of "
                          f"{len(msg.get('options') or [])} options; {msg.get('reason')}; embed {msg.get('embed')}")
                    if args.music and len(tracks) >= 3:
                        break
                if msg.get("type") == "screen" and (msg.get("video") or {}).get("watching"):
                    peak = max(peak, browser_mb(proc.pid))
                    if not videos or videos[-1]["url"] != msg.get("url"):
                        print(f"video: {msg.get('title')!r} muted={msg['video'].get('muted')} "
                              f"for {msg['video'].get('seconds')} s real; browser {browser_mb(proc.pid):.0f} MB")
                    videos.append({"url": msg.get("url"), "mb": browser_mb(proc.pid)})
                if args.youtube_chess and games and (len(videos) >= 8 or not args.browse):   # a few shots of a video
                    break
            wall = time.monotonic() - t0
            if args.youtube_chess:
                print(f"youtube-chess: {len(games)} chess game(s) finished, {len({v['url'] for v in videos})} video(s) "
                      f"watched in {wall:.0f} s real ({wall:.0f} simulated min at 60x)")
                if not games:
                    failures.append("--youtube-chess: no chess game finished")
                if args.browse:
                    print(f"PEAK BROWSER MEMORY: {peak:.0f} MB (PSS of the browser service and Chromium; "
                          f"watchdog at BROWSE_MEM_MB)")
                    if not videos:
                        failures.append("--youtube-chess --browse: no video was watched")
            if args.music:
                embed = re.compile(r"^https://open\.spotify\.com/embed/track/[A-Za-z0-9]{22}\?")
                print(f"music: {len(tracks)} track(s) picked in {wall:.0f} s real")
                if not tracks:
                    failures.append("--music: no track was picked")
                elif not all(embed.match(m.get("embed") or "") and 3 <= len(m.get("options") or []) <= 5
                             for m in tracks):
                    failures.append("--music: a track without the official embed URL or without 3-5 options")
            if args.mind:
                print(f"mind: {sent} chat messages sent, {seen.get('chat_reply', 0)} replies (AI-written tag), "
                      f"{seen.get('plan', 0)} plan event(s)")
                if not seen.get("plan"):
                    failures.append("--mind: no day plan arrived during the measurement")
            if not ticks:
                failures.append("/ws: no ticks during the measurement window")
                return failures
            print(f"ticks: {ticks} in {wall:.1f} s ({ticks / wall:.1f}/s, nominal {1 / TICK_S:.0f}/s)")
            if linux:
                cpu = cpu_seconds(proc.pid) - cpu0
                print(f"TICK COST: {1000 * cpu / ticks:.1f} ms CPU per {1000 * TICK_S:.0f} ms tick "
                      f"({100 * cpu / wall:.0f}% of one core, {cpu:.2f} CPU-s over {wall:.1f} s)")
                if child:                                 # its start (build + calibration) falls in the window
                    c = cpu_seconds(child) - child0
                    c1 = cpu_seconds(child)
                    await asyncio.sleep(5)
                    idle = cpu_seconds(child) - c1
                    print(f"SPIKING CHILD (#55): {c1:.2f} CPU-s since it started (build + calibration; {c:.2f} of them "
                          f"in the window); between decisions {100 * idle / 5:.2f}% of one core (its idle pulse); "
                          f"{seen.get('spiking', 0)} spiking frames on /ws")
            else:
                print("TICK COST: not measured (/proc not available on this OS)")
            async with s.get(base + "/api/health", headers=ADMIN) as r:   # after the CPU reading
                h = await r.json() if r.status == 200 else {}
            tm = h.get("tick_ms") or {}
            print(f"/api/health: tick body p50 {tm.get('p50')} p95 {tm.get('p95')} ms over {tm.get('n')} ticks · "
                  f"loop lag p95 {(h.get('loop_lag_ms') or {}).get('p95')} ms · RSS {h.get('rss_mb')} MB")
    return failures


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--data-dir", help="server state dir (default: a fresh temporary dir)")
    p.add_argument("--measure", type=float, default=20.0, help="seconds of /ws used for the tick cost")
    p.add_argument("--startup-timeout", type=float, default=90.0)
    p.add_argument("--torn-state", action="store_true", help="start with truncated state files (issue #21)")
    p.add_argument("--mind", action="store_true", help="60x clock from 09:00 with chat messages: plan + replies run")
    p.add_argument("--youtube-chess", action="store_true", help="60x clock from 10:00: a chess game (and a video with "
                                                                    "--browse) must happen during the measurement")
    p.add_argument("--music", action="store_true", help="60x clock from 20:00 with \"play ...\" wishes: his brain model "
                                                         "must pick tracks (#68)")
    p.add_argument("--browse", action="store_true", help="BROWSE=1: the real browser (playwright, Chromium, network)")
    args = p.parse_args()

    tmp = None
    if not args.data_dir:
        tmp = tempfile.TemporaryDirectory(prefix="sub01-smoke-")
        args.data_dir = tmp.name
    if args.torn_state:
        seed_torn(args.data_dir)
    env = dict(os.environ, BROWSE="1" if args.browse else "0", PYTHONUNBUFFERED="1")
    env.setdefault("OPENBLAS_NUM_THREADS", "1")
    env.setdefault("OMP_NUM_THREADS", "1")
    env["SUB01_ADMIN_TOKEN"] = ADMIN["X-Admin-Token"]
    env.pop("SITE_PASSWORD", None)                  # the gate would answer 401; it has its own tests
    log = tempfile.TemporaryFile(mode="w+")
    cmd = [sys.executable, str(ROOT / "live_server.py"), "--demo", "--port", str(args.port),
           "--data-dir", args.data_dir]
    if args.mind:
        cmd += ["--time-scale", "60", "--start", "09:00"]
    elif args.youtube_chess:
        cmd += ["--time-scale", "60", "--start", "10:00"]
    elif args.music:
        cmd += ["--time-scale", "60", "--start", "20:00"]
    print(f"$ BROWSE={env['BROWSE']} python live_server.py", " ".join(cmd[2:]))
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        failures = asyncio.run(run(args, proc))
        if args.torn_state:
            log.seek(0)
            failures += check_torn(args.data_dir, log.read())
    except Exception as e:                          # startup failure, connection refused, ...
        failures = [f"{type(e).__name__}: {e}"]
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    if failures:
        log.seek(0)
        print("\n--- server log (last 60 lines) ---")
        print("".join(log.readlines()[-60:]))
        print("SMOKE FAILED:\n  " + "\n  ".join(failures))
        sys.exit(1)
    print("SMOKE OK")
    if tmp:
        tmp.cleanup()


if __name__ == "__main__":
    main()
