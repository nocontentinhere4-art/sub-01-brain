"""Get the code and data onto a pod without GitHub credentials.

RunPod refuses create requests above ~100 KB, so the create body carries only a small bootstrap (`boot_env`): the
pod starts an HTTP server on port 8000 that serves /out and accepts ONE upload of the code+data pack
(`pack_bytes()`, tar.xz) at PUT /upload with a random per-pod token (X-Upload-Token, constant-time compare). The
controller (validate / pod_manager) uploads through https://<podId>-8000.proxy.runpod.net/upload; then the pod
unpacks into /app and runs the session module. `create_body()` is the RunPod create-pod JSON; only the two
allowed GPU types can ever be requested. `pack()`/`unpack()` (env-var chunks) remain for small packs and tests.
"""
import base64
import glob
import io
import json
import lzma
import os
import tarfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
IMAGE = "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404"
GPUS = ("NVIDIA RTX A5000", "NVIDIA RTX 4000 Ada Generation",   # validated
        "NVIDIA A40", "NVIDIA RTX A4500", "NVIDIA GeForce RTX 4090", "NVIDIA L40",   # fallbacks: >= 20 GB, < $0.85/h
        "NVIDIA RTX A4000", "NVIDIA L4")                        # 1M neurons use 5.7 GB (day-live list, #58)
CLOUDS = ("SECURE", "COMMUNITY")
CUDA_VERSIONS = ("12.8", "12.9", "13.0")                       # the image is cu128: a host with an older driver cannot run it
MAX_CHARS = 900_000
REST_PREFIX = "out/rest/"
STATIC_FILES = ["spiking/region_volumes.json", "real_baseline.py", "out/connectome.npz", "out/atlas_names.json"]

UNPACK_PY = ("import os,base64,io,tarfile; ks=sorted((k for k in os.environ if k.startswith('SUB01_PACK_')), "
             "key=lambda k:int(k.rsplit('_',1)[1])); tarfile.open(fileobj=io.BytesIO(base64.b64decode("
             "''.join(os.environ[k] for k in ks))), mode='r:xz').extractall('/app')")


def default_files(root=ROOT):
    """Relative paths of the default set; spiking/*.py is globbed now, not at import time."""
    code = sorted(Path(p).relative_to(root).as_posix() for p in glob.glob(str(Path(root) / "spiking" / "*.py")))
    return code + [f for f in STATIC_FILES if f != "out/rest/qc.json"]


DEFAULT_FILES = default_files


def rest_subset(k=2, seed=0, rest_dir=None, max_trs=None):
    """k QC-kept resting-state runs re-saved with float16 ts, plus a qc.json listing only those as kept.

    Returns {arcname: bytes}; `max_trs` crops each run to its first volumes (keeps the pack small).
    """
    rest_dir = Path(rest_dir) if rest_dir else ROOT / "out" / "rest"
    qc = json.loads((rest_dir / "qc.json").read_text())
    rows = qc.get("runs", qc) if isinstance(qc, dict) else qc
    if isinstance(rows, dict):
        kept = sorted(r for r, v in rows.items() if not isinstance(v, dict) or v.get("kept", True))
    else:
        kept = sorted(r["run"] for r in rows if r.get("kept", True))
    kept = [r for r in kept if (rest_dir / f"{r}.npz").exists()]
    rng = np.random.default_rng(seed)
    pick = sorted(kept[i] for i in rng.permutation(len(kept))[:k])
    out, qc_out = {}, {}
    for stem in pick:
        d = np.load(rest_dir / f"{stem}.npz")
        ts = np.nan_to_num(d["ts"].astype(np.float32))
        if max_trs:
            ts = ts[:max_trs]
        buf = io.BytesIO()
        np.savez_compressed(buf, ts=ts.astype(np.float16), tr=d["tr"])
        out[f"{REST_PREFIX}{stem}.npz"] = buf.getvalue()
        qc_out[stem] = {"kept": True}
    out[f"{REST_PREFIX}qc.json"] = json.dumps(qc_out, indent=1).encode()
    return out


def _tar_xz(members):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz", preset=9 | lzma.PRESET_EXTREME) as tf:
        for name, data in members.items():
            ti = tarfile.TarInfo(name)
            ti.size, ti.mtime, ti.mode = len(data), 0, 0o644
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def pack(files=None, extra=None, chunk=96_000, root=ROOT, k=2, max_trs=None, verbose=False):
    """tar.xz + base64 chunked env vars. `files`: relative paths (default set + rest_subset); `extra`: {arc: bytes}."""
    root = Path(root)
    members = {}
    if files is None:
        for rel in default_files(root):
            members[rel] = (root / rel).read_bytes()
        members.update(rest_subset(k=k, rest_dir=root / "out" / "rest", max_trs=max_trs))
    else:
        for rel in files:
            members[str(rel)] = (root / rel).read_bytes()
    members.update(extra or {})
    b64 = base64.b64encode(_tar_xz(members)).decode()
    env = {f"SUB01_PACK_{i}": b64[j:j + chunk] for i, j in enumerate(range(0, len(b64), chunk))}
    total = len(b64)
    if verbose:
        print(f"pack: {len(members)} files, {total} characters in {len(env)} variables", flush=True)
    if total > MAX_CHARS:
        raise ValueError(f"pack is {total} characters (limit {MAX_CHARS}); lower k or max_trs")
    return env


def packed_chars(env):
    return sum(len(v) for k, v in env.items() if k.startswith("SUB01_PACK_"))


def unpack(env, dest):
    """What the pod runs at start (same logic as UNPACK_PY); returns the extracted file names."""
    ks = sorted((k for k in env if k.startswith("SUB01_PACK_")), key=lambda k: int(k.rsplit("_", 1)[1]))
    raw = base64.b64decode("".join(env[k] for k in ks))
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as tf:
        names = tf.getnames()
        tf.extractall(dest, filter="data")
    return names


BOOT_PY = r'''
import hmac, http.server, io, json, os, subprocess, sys, tarfile, threading, time
TOKEN, MODULE = os.environ["SUB01_UPLOAD_TOKEN"], os.environ.get("SUB01_MODULE", "spiking.session")
OUT, APP = os.environ.get("SUB01_OUT_DIR", "/out"), os.environ.get("SUB01_APP_DIR", "/app")
PORT = int(os.environ.get("SUB01_BOOT_PORT", "8000"))
MAX = 300 * 1024 * 1024
state = {"received": False}
os.makedirs(OUT, exist_ok=True)
def status(**kw):
    open(OUT + "/status.json.tmp", "w").write(json.dumps(dict({"done": False, "error": None, "progress": 0}, **kw)))
    os.replace(OUT + "/status.json.tmp", OUT + "/status.json")
def run():
    log = open(OUT + "/session.log", "w")
    try:
        subprocess.run([sys.executable, "-c", "import numpy, aiohttp"], check=True, capture_output=True)
    except Exception:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "numpy", "aiohttp"], stdout=log, stderr=log)
    code = subprocess.run([sys.executable, "-m", MODULE], cwd=APP, stdout=log, stderr=subprocess.STDOUT).returncode
    open(OUT + "/exit_code.tmp", "w").write(str(code))           # atomic, like status(): never read empty
    os.replace(OUT + "/exit_code.tmp", OUT + "/exit_code")
    try:
        st = json.load(open(OUT + "/status.json"))
    except Exception:
        st = {}
    if not st.get("done"):
        status(phase="crashed", done=True, error="session exited with code %d" % code)
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=OUT, **k)
    def log_message(self, *a):
        pass
    def do_PUT(self):
        n = int(self.headers.get("Content-Length") or 0)
        if self.path != "/upload" or state["received"] or n <= 0 or n > MAX or \
                not hmac.compare_digest(self.headers.get("X-Upload-Token", ""), TOKEN):
            self.send_response(403); self.end_headers(); return
        data = self.rfile.read(n)
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as tf:
                tf.extractall(APP, filter="data")
        except Exception as e:
            self.send_response(400); self.end_headers(); self.wfile.write(type(e).__name__.encode()); return
        state["received"] = True
        status(phase="unpacked")
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
        threading.Thread(target=run, daemon=True).start()
status(phase="waiting_upload")
http.server.ThreadingHTTPServer(("", PORT), H).serve_forever()
'''


def pack_bytes(k=3, root=ROOT, max_trs=None, extra=None):
    """tar.xz of the default code + data set and a few resting-state runs (uploaded to the pod after boot)."""
    root = Path(root)
    members = {rel: (root / rel).read_bytes() for rel in default_files(root)}
    members.update(rest_subset(k=k, rest_dir=root / "out" / "rest", max_trs=max_trs))
    members.update(extra or {})
    return _tar_xz(members)


def boot_env(token, module="spiking.session"):
    """The small env the create request carries: bootstrap script, upload token, module to run."""
    assert len(token) >= 32
    return {"SUB01_BOOT": base64.b64encode(BOOT_PY.encode()).decode(), "SUB01_UPLOAD_TOKEN": token,
            "SUB01_MODULE": module}


def boot_cmd():
    script = "mkdir -p /app /out && printf '%s' \"$SUB01_BOOT\" | base64 -d > /app/boot.py && cd /app && exec python3 /app/boot.py"
    return ["bash", "-c", script]


def start_cmd(module="spiking.session"):
    """The pod's docker start command: unpack, serve /out on 8000, run the module, keep results readable 10 min."""
    script = (f"mkdir -p /app /out && cd /app\n"
              f"python3 -c \"{UNPACK_PY}\"\n"
              f"python3 -c 'import numpy, aiohttp' 2>/dev/null || pip install -q numpy aiohttp > /out/pip.log 2>&1\n"
              f"(python3 -m http.server 8000 -d /out >/dev/null 2>&1 &)\n"
              f"python3 -m {module} > /out/session.log 2>&1; echo $? > /out/exit_code; sleep 600")
    return ["bash", "-c", script]


def create_body(env, name, gpu="NVIDIA RTX A5000", module="spiking.session", cloud="SECURE"):
    """RunPod create-pod JSON: one on-demand GPU (secure cloud unless asked), no volume, port 8000 proxied.

    With a bootstrap env (SUB01_BOOT) the pod waits for the pack upload; otherwise it unpacks SUB01_PACK_* itself."""
    assert gpu in GPUS, f"GPU type not allowed: {gpu}"
    assert cloud in CLOUDS, f"cloud type not allowed: {cloud}"
    body = {"name": name, "imageName": IMAGE, "gpuTypeIds": [gpu], "gpuCount": 1, "interruptible": False,
            "cloudType": cloud, "allowedCudaVersions": list(CUDA_VERSIONS), "containerDiskInGb": 30, "volumeInGb": 0, "ports": ["8000/http"],
            "env": dict(env), "dockerStartCmd": boot_cmd() if "SUB01_BOOT" in env else start_cmd(module)}
    assert len(json.dumps(body)) < 90_000, "create request too large for RunPod (~100 KB limit)"
    return body


if __name__ == "__main__":
    e = pack(verbose=True)
    print("total characters:", packed_chars(e))
