"""Benchmark / validate the 1M network's live phase on one RunPod pod (#58). Run from a machine with RunPod access.

    python docs/spiking/live/run_live_pod.py bench --gpu "NVIDIA RTX A4000" --cloud SECURE
    python docs/spiking/live/run_live_pod.py validate --gpu "NVIDIA RTX A4000" --rounds 50
    python docs/spiking/live/run_live_pod.py learn --gpu "NVIDIA RTX A4000" --trials 240

bench:    phases bench + live_bench on the pod (no server); prints $/h, steps/s, decision wall times.
learn:    the live_learn phase (#70): the bandit with variable offers and real labels for every read-out, the
          learned run vs the frozen twin vs random (no server); results to docs/spiking/live/<name>.json.
validate: live_pod_host.py on the pod runs the real SpikingHub next to the session; this script sends `rounds`
          decide/reward rounds through the RunPod proxy, waits for a periodic weight upload, sends the night
          message (the day's decisions), waits for the night phases and the final upload, then deletes the pod.
Every pod: one at a time (RunPodOps refuses a second one of ours), a hard deadline (RunPodOps.guard), deleted at the
end and confirmed gone; the pod named "BRAIN" is never touched. Results go to docs/spiking/live/<name>.json and the
cost log to docs/spiking/live/costs.jsonl.
"""
import argparse
import json
import secrets
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

import runpod_api  # noqa: E402
from spiking import podpack  # noqa: E402
from spiking.costs import CostLog  # noqa: E402
from spiking.runpod_ops import RunPodOps  # noqa: E402

LIKED = ("tea", "moon", "park", "bread")             # the synthetic outcome: options with these words pay off
POOL = ["Tea ceremony - Wikipedia", "Moon landing archive", "Inokashira Park map", "Bread recipe forum",
        "Stock market news", "Football transfer rumours", "Chess opening Nf3", "Chess move exd5 (capture)",
        "Snow in Hokkaido photos", "Lighthouse history", "Train timetable Kichijoji", "Cat video compilation",
        "Origami crane tutorial", "Jazz record shop", "Museum of Western Art", "Ramen shop reviews",
        "Moon phases explained", "Green tea health", "Park boats rental", "Sourdough bread starter"]


def tokyo_day():
    return datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def api_with_ports(extra_ports):
    def api(path, method="GET", body=None, timeout=60):
        if method == "POST" and path == "/pods" and body is not None and extra_ports:
            body = dict(body, ports=list(body["ports"]) + list(extra_ports))
        return runpod_api.api(path, method, body, timeout)
    return api


def http(url, data=None, token=None, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 method="POST" if data is not None else "GET",
                                 headers={"Content-Type": "application/json", "User-Agent": "sub01/1.0",
                                          **({"X-Drive-Token": token} if token else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def outcome(label, rng):
    v = 1.0 if any(w in label.lower() for w in LIKED) else -0.5
    return round(v + float(rng.normal(0, 0.2)), 3)


def main():
    import numpy as np
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("bench", "validate", "learn"))
    ap.add_argument("--gpu", default="NVIDIA RTX A4000")
    ap.add_argument("--cloud", default="SECURE")
    ap.add_argument("--fallback", default="", help="more GPU types to try in order when --gpu has no capacity, "
                                                   "comma-separated, same cloud")
    ap.add_argument("--rounds", type=int, default=50)
    ap.add_argument("--trials", type=int, default=240)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--readouts", default="race,scaled,diff,window")
    ap.add_argument("--max-min", type=float, default=None)
    ap.add_argument("--upload-every-min", type=float, default=3.0)
    ap.add_argument("--name", default=None)
    a = ap.parse_args()
    max_min = a.max_min or {"bench": 20, "learn": 28}.get(a.mode, 44)
    name = a.name or f"{a.mode}-{a.gpu.split()[-1].lower()}-{a.cloud.lower()}"
    out_path = HERE / f"{name}.json"
    costs = CostLog(HERE / "costs.jsonl")
    ops = RunPodOps(api=api_with_ports(["8001/http"] if a.mode == "validate" else []), log=costs, hours_cap=2.0)
    drive = secrets.token_hex(24)
    pod_secret = secrets.token_hex(24)
    if a.mode == "learn":
        cfg = {"session_id": name, "n_neurons": 1_000_000, "seed": a.seed, "phases": ["live_learn"],
               "max_minutes": max_min - 4, "bandit_trials": a.trials, "bandit_readouts": a.readouts.split(","),
               "validate": False}
        module, extra = "spiking.session", {}
    elif a.mode == "bench":
        cfg = {"session_id": name, "n_neurons": 1_000_000, "seed": 1, "phases": ["bench", "live_bench"],
               "max_minutes": max_min - 6, "bench_ms": 5000, "live_bench_n": 40, "validate": True}
        module, extra = "spiking.session", {}
    else:
        cfg = {"session_id": name, "day": tokyo_day(), "n_neurons": 1_000_000, "seed": 1,
               "phases": ["live_decide", "recall_yesterday", "encode", "choice_train", "memory_test", "sleep",
                          "memory_test"], "max_minutes": max_min - 4, "upload_every_min": a.upload_every_min,
               "validate": False, "items": [], "sleep_minutes": 2}
        module = "live_pod_host"
        extra = {"live_pod_host.py": (HERE / "live_pod_host.py").read_bytes(),
                 "sleep.py": (ROOT / "sleep.py").read_bytes(), "state_io.py": (ROOT / "state_io.py").read_bytes()}
    data = podpack.pack_bytes(extra=extra)
    token = secrets.token_hex(24)
    env = dict(podpack.boot_env(token, module), SUB01_SESSION=json.dumps(cfg), SUB01_POD_SECRET=pod_secret,
               SUB01_DRIVE_TOKEN=drive, SUB01_SESSION_ID=name)
    if a.mode in ("bench", "learn"):
        env.pop("SUB01_DRIVE_TOKEN")
    brain_before = [p.get("id") for p in ops.pods() if p.get("name") == "BRAIN"]
    t_create = time.time()
    gpus = [(a.gpu, a.cloud)] + [(g.strip(), a.cloud) for g in a.fallback.split(",") if g.strip()]
    pod = ops.create(env, "live-" + a.mode, module, max_min, gpus=gpus)
    pod_id = pod["id"]
    row = next((r for r in costs.open_pods() if r["pod_id"] == pod_id), {})
    rate = row.get("cost_per_hr")
    log("pod", pod_id, row.get("gpu") or a.gpu, a.cloud, f"${rate}/h")
    res = {"mode": a.mode, "gpu": row.get("gpu") or a.gpu, "gpus_tried": gpus,
           "cloud": a.cloud, "pod_id": pod_id, "usd_per_hour": rate}
    try:
        with ops.guard(pod_id):
            ops.upload(pod_id, data, token, timeout=900)
            res["boot_s"] = round(time.time() - t_create, 1)
            log("pack uploaded after", res["boot_s"], "s")
            if a.mode in ("bench", "learn"):
                while True:
                    st = json.loads(ops.wait_http(pod_id, "status.json"))
                    log("phase", st.get("phase"), "progress", st.get("progress"), "wall", st.get("wall_s"))
                    if st.get("done"):
                        break
                    time.sleep(10 if a.mode == "bench" else 30)
                res["results"] = json.loads(ops.fetch(pod_id, "results.json"))
            else:
                validate(ops, pod_id, drive, a, res, np.random.default_rng(0))
    finally:
        gone = ops.delete(pod_id, "done")
        res["deleted"] = gone
        res["still_listed"] = any(p.get("id") == pod_id for p in ops.pods())
        rec = [r for r in costs.rows() if r.get("pod_id") == pod_id and "stop" in r]
        res["cost"] = rec[-1] if rec else None
        res["brain_pod_still_there"] = [p.get("id") for p in ops.pods() if p.get("name") == "BRAIN"] == brain_before
        out_path.write_text(json.dumps(res, indent=1, default=float))
        log("deleted:", gone, "cost:", res["cost"] and res["cost"]["cost_usd"], "->", out_path.name)


def validate(ops, pod_id, drive, a, res, rng):
    base = f"https://{pod_id}-8001.proxy.runpod.net"
    t0 = time.time()
    while True:                                                     # build + calibration
        try:
            st = http(base + "/drive/status", token=drive)
            if st.get("live_ready"):
                break
            if st.get("session_exit") is not None:
                raise RuntimeError("session exited before live_ready")
        except OSError:
            pass
        if time.time() - t0 > 900:
            raise TimeoutError("not live_ready in 15 min")
        time.sleep(5)
    res["live_ready_after_s"] = round(time.time() - t0, 1)
    log("live ready after", res["live_ready_after_s"], "s")
    rounds, decisions = [], []
    for i in range(a.rounds):
        k = int(rng.integers(2, 7))
        opts = [POOL[j] for j in rng.choice(len(POOL), size=k, replace=False)]
        t = time.time()
        r = http(base + "/drive/decide", {"options": opts, "kind": "browse", "deadline_ms": 2000}, drive)
        e2e = round((time.time() - t) * 1000, 1)
        d = r["decision"]
        row = {"i": i, "k": k, "e2e_ms": e2e, "hub_ms": r["hub_ms"], "answered": d is not None}
        if d:
            v = outcome(opts[d["pick"]], rng)
            ok = http(base + "/drive/reward", {"id": d["id"], "value": v}, drive)["ok"]
            liked_offered = any(any(w in o.lower() for w in LIKED) for o in opts)
            row.update(pick=d["pick"], rtt_ms=d["rtt_ms"], sim_ms=d["sim_ms"], reward=v, reward_ok=ok,
                       pool_rates=d["pool_rates"], liked_offered=liked_offered,
                       liked_picked=any(w in opts[d["pick"]].lower() for w in LIKED))
            decisions.append({"options": opts, "pick": d["pick"], "reward": v, "kind": "browse"})
        rounds.append(row)
        log(i, row.get("pick"), e2e, "ms", row.get("reward"))
        time.sleep(0.5)
    res["rounds"] = rounds
    ans = [r for r in rounds if r["answered"]]
    hub = sorted(r["hub_ms"] for r in ans)
    res["summary"] = {"rounds": len(rounds), "answered": len(ans),
                      "hub_ms_p50": hub[len(hub) // 2] if hub else None, "hub_ms_max": hub[-1] if hub else None,
                      "within_2s": sum(r["hub_ms"] <= 2000 for r in ans),
                      "e2e_ms_p50": sorted(r["e2e_ms"] for r in ans)[len(ans) // 2] if ans else None,
                      "rewards_accepted": sum(bool(r.get("reward_ok")) for r in ans)}
    st0 = http(base + "/drive/status", token=drive)
    t1 = time.time()
    while time.time() - t1 < 60 * (a.upload_every_min + 3):          # a periodic upload must land
        st = http(base + "/drive/status", token=drive)
        if st.get("weights_mtime") and st["weights_mtime"] != st0.get("weights_mtime"):
            break
        time.sleep(10)
    res["periodic_upload"] = {"bytes": st.get("weights_bytes"), "seen_after_s": round(time.time() - t1, 1),
                              "realtime_x": st.get("realtime_x")}
    log("periodic weights upload:", res["periodic_upload"])
    items = [{"text": "Tea ceremony history matcha kettle cups", "source": "reading", "item": "Tea ceremony"},
             {"text": "Moon landing apollo astronauts lunar module", "source": "reading", "item": "Moon landing"},
             {"text": "a red bicycle crossed the bridge near the river", "source": "chat"}]
    ok = http(base + "/drive/night", {"day": tokyo_day(), "items": items, "decisions": decisions},
              drive)["ok"]
    log("night sent:", ok)
    t2 = time.time()
    while True:
        st = json.loads(ops.wait_http(pod_id, "status.json"))
        if st.get("done"):
            break
        if time.time() - t2 > 20 * 60:
            raise TimeoutError("night phases not done in 20 min")
        time.sleep(15)
    res["night_s"] = round(time.time() - t2, 1)
    res["final_status"] = http(base + "/drive/status", token=drive)
    res["results"] = json.loads(ops.fetch(pod_id, "results.json"))
    try:
        res["hub_decisions_log"] = [json.loads(x) for x in ops.fetch(
            pod_id, f"host/spiking/gpu_decisions-{tokyo_day()}.jsonl").decode().splitlines()][:6]
    except Exception as e:
        res["hub_decisions_log"] = f"not fetched: {type(e).__name__}"


if __name__ == "__main__":
    main()
