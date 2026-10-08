"""Run one batch job on a RunPod pod, safely, and bring the results back.

    python analysis/runpod_job.py --kind cpu --image mrtrix3/mrtrix3:3.0.8 --script analysis/pod/tract.sh \
        --upload /path/5tt.nii.gz ... --fetch connectome.tar.gz --tag tract

Hard rules (enforced here):
- only an RTX A5000 GPU pod or a CPU pod; one pod at a time (refuses if one of OUR pods is still alive);
- pods are only ever created, read and deleted by id from data/analysis/my_pods.json - pods we did not create
  (e.g. "BRAIN") are never touched;
- the pod is deleted when the job finishes, fails, on Ctrl-C / SIGTERM, and at the latest after --max-min (<= 60) minutes;
- total pod time across all jobs is capped at 2 h, and the gpu-preview runs (tools/gpu_preview.py) at 10 h of their own
  (data/analysis/costs.jsonl is the ledger);
- every job appends {tag, pod, kind, cost_per_hr, minutes, usd, status} to data/analysis/costs.jsonl.

Pod side: a tiny HTTP server (pod/server.py, sent base64 in env) on port 8000 accepts PUT uploads into /in and serves
/out; the job script waits for /in/READY, writes /out/log.txt and finally /out/STATUS (DONE or FAILED).
RunPod auth is injected by the environment for rest.runpod.io (no key in this repo).
"""
import argparse
import base64
import json
import signal
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
API = "https://rest.runpod.io/v1"
LEDGER = ROOT / "data" / "analysis" / "costs.jsonl"
MINE = ROOT / "data" / "analysis" / "my_pods.json"
TOTAL_CAP_MIN = 120.0
PREVIEW_TAG, PREVIEW_CAP_MIN = "gpu-preview", 600.0   # tools/gpu_preview.py runs: their own pod-minute budget (owner OK 2026-10-04)
UA = "sub01-analysis/1.0 (curl-compatible)"          # Cloudflare rejects the default Python-urllib agent


def api(method, path, body=None, timeout=60):
    req = urllib.request.Request(API + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        txt = r.read().decode()
    return json.loads(txt) if txt.strip() else {}


def mine():
    return json.loads(MINE.read_text()) if MINE.exists() else []


def remember(ids):
    MINE.parent.mkdir(parents=True, exist_ok=True)
    MINE.write_text(json.dumps(ids))


def spent_minutes(preview=False):
    """Pod minutes in the ledger: the gpu-preview runs, or every other job (each has its own cap)."""
    if not LEDGER.exists():
        return 0.0
    rows = [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()]
    return sum(r.get("minutes", 0) for r in rows if str(r.get("tag", "")).startswith(PREVIEW_TAG) == preview)


def log_cost(rec):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def http(method, url, data=None, timeout=120, tries=1):
    """One HTTP call through the RunPod proxy; `tries` > 1 retries transient errors (the proxy 404s now and then)."""
    for k in range(tries):
        try:
            req = urllib.request.Request(url, method=method, data=data, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(5 * (k + 1))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--kind", choices=["cpu", "a5000", "auto"], required=True,
                   help="auto: first available of CPU 32/16/8 vCPU, then RTX A5000")
    p.add_argument("--wait-min", type=float, default=0, help="keep retrying while RunPod has no capacity")
    p.add_argument("--image", required=True)
    p.add_argument("--script", required=True, help="bash script run on the pod after the uploads")
    p.add_argument("--upload", nargs="*", default=[])
    p.add_argument("--fetch", nargs="*", default=[], help="files in /out to download at the end")
    p.add_argument("--dest", default=str(ROOT / "data" / "analysis"))
    p.add_argument("--tag", required=True)
    p.add_argument("--vcpu", type=int, default=32)
    p.add_argument("--disk", type=int, default=60)
    p.add_argument("--max-min", type=float, default=58.0)
    p.add_argument("--env", nargs="*", default=[], help="KEY=VALUE passed to the job")
    a = p.parse_args()
    a.max_min = min(a.max_min, 60.0)

    # one pod at a time: any of our pods still alive?
    alive = []
    for pid in mine():
        try:
            api("GET", f"/pods/{pid}")
            alive.append(pid)
        except urllib.error.HTTPError:
            pass
    remember(alive)
    if alive:
        sys.exit(f"refusing: our pod(s) {alive} still exist - delete them first")
    preview = a.tag.startswith(PREVIEW_TAG)
    cap = PREVIEW_CAP_MIN if preview else TOTAL_CAP_MIN
    left = cap - spent_minutes(preview)
    if left < 5:
        sys.exit(f"refusing: pod-time budget used ({spent_minutes(preview):.1f} of {cap} min)")
    max_min = min(a.max_min, left)

    env = {"SERVER": base64.b64encode((HERE / "pod" / "server.py").read_bytes()).decode(),
           "JOB": base64.b64encode(Path(a.script).read_bytes()).decode(),
           "JOB_MIN": str(int(max_min - 9))}              # leave time to fetch results before the hard stop
    env.update(dict(kv.split("=", 1) for kv in a.env))
    boot = ("mkdir -p /in /out /work && echo up > /out/UP && echo $SERVER | base64 -d > /server.py && echo $JOB | base64 -d > /job.sh && "
            "(cd /work && timeout $(( JOB_MIN * 60 )) bash /job.sh > /out/log.txt 2>&1 "
            "&& echo DONE > /out/STATUS || echo FAILED > /out/STATUS) & python3 /server.py")
    body = {"name": f"sub01-rw-{a.tag}", "imageName": a.image, "containerDiskInGb": a.disk, "volumeInGb": 0,
            "ports": ["8000/http"], "env": env, "dockerEntrypoint": ["bash", "-c"], "dockerStartCmd": [boot]}
    def variants():
        cpu = [dict(computeType="CPU", cpuFlavorIds=["cpu5c", "cpu3c", "cpu5g", "cpu3g"], vcpuCount=v)
               for v in ([a.vcpu] if a.kind == "cpu" else [32, 16, 8])]
        gpu = [dict(computeType="GPU", gpuTypeIds=["NVIDIA RTX A5000"], gpuCount=1, cloudType=c, minVCPUPerGPU=8,
                    minRAMPerGPU=30) for c in ("SECURE", "COMMUNITY")]
        return {"cpu": cpu, "a5000": gpu, "auto": cpu + gpu}[a.kind]

    pod, waited0 = None, time.time()
    while pod is None:
        for v in variants():
            try:
                pod = api("POST", "/pods", body | v)
                kind = "cpu" if v["computeType"] == "CPU" else "a5000"
                break
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors="replace")
                if e.code != 500 or "available" not in msg:
                    raise SystemExit(f"create failed: {e.code} {msg[:300]}")
        if pod is None:
            if time.time() - waited0 > a.wait_min * 60:
                sys.exit("no RunPod capacity for the allowed pod types")
            print(f"no capacity yet ({(time.time() - waited0) / 60:.0f} min), retrying", flush=True)
            time.sleep(90)
    t0 = time.time()
    pid = pod["id"]
    remember([pid])
    cost_hr = float(pod.get("costPerHr") or 0)
    print(f"created pod {pid} ({kind}, {pod.get('vcpuCount')} vCPU, {pod.get('memoryInGb')} GB, ${cost_hr}/h, max {max_min:.0f} min)", flush=True)
    status = "error"
    stopped = {"flag": False}

    def stop(*_):
        stopped["flag"] = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    base = f"https://{pid}-8000.proxy.runpod.net"
    try:
        while not stopped["flag"]:                                    # wait for the server
            if time.time() - t0 > max_min * 60:
                raise TimeoutError("pod never came up")
            try:                                                     # the proxy answers 404 until the pod is up
                if http("GET", base + "/UP", timeout=20).strip() == b"up":
                    break
            except Exception:
                pass
            time.sleep(10)
        print(f"pod up after {time.time() - t0:.0f} s", flush=True)
        for f in a.upload:
            http("PUT", f"{base}/in/{Path(f).name}", Path(f).read_bytes(), timeout=600, tries=6)
            print("uploaded", Path(f).name, flush=True)
        http("PUT", f"{base}/in/READY", b"1", tries=6)
        last = ""
        while not stopped["flag"]:
            time.sleep(20)
            if time.time() - t0 > max_min * 60:
                status = "timeout"
                break
            try:
                logtxt = http("GET", base + "/log.txt", timeout=30).decode(errors="replace")
                if logtxt != last:
                    print(logtxt[len(last):] if logtxt.startswith(last) else logtxt[-2000:], end="", flush=True)
                    last = logtxt
                st = http("GET", base + "/STATUS", timeout=30).decode().strip()
            except Exception:
                continue
            if st in ("DONE", "FAILED"):
                status = st.lower()
                break
        dest = Path(a.dest)
        dest.mkdir(parents=True, exist_ok=True)
        for f in a.fetch + ["log.txt"]:
            try:
                (dest / f"{a.tag}_{Path(f).name}" if f == "log.txt" else dest / Path(f).name).write_bytes(
                    http("GET", f"{base}/{f}", timeout=1200, tries=4))
                print("fetched", f, flush=True)
            except Exception as e:
                print("fetch failed", f, e, flush=True)
    except Exception as e:
        print("job error:", repr(e), flush=True)
    finally:
        for attempt in range(5):
            try:
                api("DELETE", f"/pods/{pid}")
                break
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    break
                time.sleep(5)
            except Exception:
                time.sleep(5)
        remember([])
        minutes = (time.time() - t0) / 60
        log_cost({"tag": a.tag, "pod": pid, "kind": kind, "vcpu": pod.get("vcpuCount"), "image": a.image, "cost_per_hr": cost_hr,
                  "minutes": round(minutes, 2), "usd": round(cost_hr * minutes / 60, 4), "status": status,
                  "ended": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        print(f"pod {pid} deleted; {minutes:.1f} min, ~${cost_hr * minutes / 60:.2f}; status {status}", flush=True)


if __name__ == "__main__":
    main()
