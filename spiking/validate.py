"""Validation CLI (run from the sandbox, not on Railway).

    python -m spiking.validate --gpu [--minutes 50] [--n 1000000]    # one RunPod pod, always deleted afterwards
    python -m spiking.validate --cpu [--n 20000]                     # in-process on this machine
    python -m spiking.validate --report                              # only (re)build the report from saved results

GPU results go to docs/spiking/gpu/, CPU results to docs/spiking/cpu/. The pod is deleted in a `finally` block, on
errors and on the deadline; the cost log is data/spiking/costs.jsonl.
"""
import argparse
import json
import secrets
import sys
import time
from datetime import date
from pathlib import Path

from spiking import podpack
from spiking.costs import CostLog
from spiking.runpod_ops import DeadlineExceeded, RunPodOps

ROOT = Path(__file__).resolve().parent.parent
GPU_DIR, CPU_DIR = ROOT / "docs" / "spiking" / "gpu", ROOT / "docs" / "spiking" / "cpu"
MAX_VALIDATE_MIN = 60
PHASES = ["bench", "rates", "delays", "validate_memory", "validate_pong"]
SAVE_EXT = (".png", ".json", ".log", ".txt")


def session_config(n, minutes, phases=None, pong_minutes=10, seed=1, extra=None):
    cfg = {"session_id": "validate-" + time.strftime("%Y%m%d-%H%M%S"), "day": date.today().isoformat(),
           "n_neurons": int(n), "seed": seed, "max_minutes": max(5, int(minutes) - 8),
           "phases": phases or PHASES, "pong_train_minutes": pong_minutes, "messages": [], "elapsed_days": 1.0,
           "validate": True}
    cfg.update(extra or {})
    return cfg


def _json(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return {}


def run_gpu(args, ops=None, out_dir=GPU_DIR, interval=20, say=print):
    """Create the pod, poll status.json, fetch results, delete the pod. Returns 0 only if none of ours remain."""
    minutes = min(float(args.minutes), MAX_VALIDATE_MIN)
    cfg = session_config(args.n, minutes, args.phases.split(",") if args.phases else None, args.pong_minutes,
                         extra=json.loads(args.extra) if getattr(args, "extra", None) else None)
    out_dir = Path(args.out) if getattr(args, "out", None) else out_dir
    ops = ops or RunPodOps(log=CostLog(ROOT / "data" / "spiking" / "costs.jsonl"))
    token = secrets.token_hex(24)
    data = podpack.pack_bytes()
    say(f"pack: {len(data) / 1e6:.2f} MB (uploaded to the pod after boot)")
    env = dict(podpack.boot_env(token, args.module), SUB01_SESSION=json.dumps(cfg))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pod = ops.create(env, "validate", args.module, minutes)
    pod_id = pod["id"]
    say(f"pod {pod_id} created ({minutes:.0f} min max); polling every {interval}s")
    status = {}
    try:
        deadline = ops.deadlines[pod_id]
        with ops.guard(pod_id, deadline):
            ops.upload(pod_id, data, token, timeout=min(900, max(60, deadline - ops.clock() - 60)))
            say("pack uploaded")
            last = None
            while True:
                if ops.clock() >= deadline:
                    raise DeadlineExceeded("validation deadline reached")
                try:
                    status = _json(ops.fetch(pod_id, "status.json"))
                except Exception:
                    status = {}                                        # still booting / unpacking
                line = (status.get("phase"), status.get("progress"), status.get("t_sim"))
                if status and line != last:
                    say(f"phase={line[0]} progress={line[1]} t_sim={line[2]}")
                    last = line
                if status.get("done") or status.get("error"):
                    break
                ops.sleep(interval)
            say("session finished" + (f" with error: {status['error']}" if status.get("error") else ""))
            results = {}
            try:
                raw = ops.wait_http(pod_id, "results.json", timeout=90, interval=5)
                (out_dir / "results.json").write_bytes(raw)
                results = _json(raw)
            except Exception as e:
                say(f"results.json not available: {type(e).__name__}")
            names = ["session.log"] + [f for f in results.get("files", []) if isinstance(f, str)]
            for name in names:
                safe = Path(name).name
                if safe != name or not safe.endswith(SAVE_EXT) or safe == "results.json":
                    continue
                try:
                    (out_dir / safe).write_bytes(ops.fetch(pod_id, safe, timeout=60))
                except Exception as e:
                    say(f"could not fetch {safe}: {type(e).__name__}")
    except Exception as e:                                                   # guard already deleted the pod
        say(f"session aborted: {type(e).__name__}: {e}")
        status = dict(status, error=type(e).__name__)
    finally:
        try:
            ops.delete(pod_id, "validate finished")
        except Exception as e:
            say(f"WARNING: delete failed for {pod_id}: {type(e).__name__}")
    if ops.log:
        say(f"total spend so far: ${ops.log.total_usd():.2f} over {ops.log.total_hours():.2f} GPU-hours")
    left = ops.ours()
    say("no pods of ours remain" if not left else f"WARNING: pods of ours still exist: {[p.get('id') for p in left]}")
    return 0 if not left and not status.get("error") else 1


def run_cpu(args, out_dir=CPU_DIR, say=print):
    from spiking.session import run_session                              # written by the core agent
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir = Path(args.out) if getattr(args, "out", None) else out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = session_config(args.n, 600, args.phases.split(",") if args.phases else None, args.pong_minutes,
                         extra=json.loads(args.extra) if getattr(args, "extra", None) else None)
    cfg["device"] = "cpu"
    res = run_session(cfg, out_dir, stream=None)
    if isinstance(res, dict) and not (out_dir / "results.json").exists():
        (out_dir / "results.json").write_text(json.dumps(res, indent=1, default=str))
    say(f"cpu results in {out_dir}")
    return 0


def write_report(gpu_dir=GPU_DIR, cpu_dir=CPU_DIR, say=print):
    """Hook: spiking/report.py (written later) turns the saved results into docs; skipped when absent."""
    try:
        from spiking import report
    except ImportError:
        say("spiking.report not found; skipping the report")
        return None
    return report.write_report(gpu_dir, cpu_dir)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--gpu", action="store_true")
    mode.add_argument("--cpu", action="store_true")
    mode.add_argument("--report", action="store_true")
    p.add_argument("--minutes", type=float, default=50, help=f"GPU pod time limit (max {MAX_VALIDATE_MIN})")
    p.add_argument("--n", type=int, help="neurons (default 1000000 on --gpu, 20000 on --cpu)")
    p.add_argument("--phases", help="comma-separated phase list (default: the full session minus 'free')")
    p.add_argument("--pong-minutes", type=float, default=10)
    p.add_argument("--module", default="spiking.session", help="module the pod runs")
    p.add_argument("--extra", help="JSON merged into the session config (e.g. sleep_minutes, pong_blocks)")
    p.add_argument("--out", help="results directory (default docs/spiking/gpu or docs/spiking/cpu)")
    p.add_argument("--no-report", action="store_true")
    args = p.parse_args(argv)
    if args.gpu:
        args.n = args.n or 1_000_000
        code = run_gpu(args)
    elif args.cpu:
        args.n = args.n or 20_000
        code = run_cpu(args)
    else:
        code = 0
    if not args.no_report:
        write_report()
    return code


if __name__ == "__main__":
    sys.exit(main())
