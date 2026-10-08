"""One Tripo generation per run (paid API: https://openapi.tripo3d.ai/v3), guarded against spending twice.

    python room_build/tripo_gen.py text  <name> <prompt.json> [--out DIR]          # text-to-model; prompt.json is the request body
    python room_build/tripo_gen.py image <name> <image.png> <face_limit> [more.json] [--out DIR]   # image-to-model from a picture
    python room_build/tripo_gen.py balance

No key is read, printed or stored here: the session's egress proxy adds the credential for openapi.tripo3d.ai. Each run
submits ONE task and waits for it. It refuses if <name>.task or <name>.glb already exists in the output folder, so a
re-run never pays again (delete the files yourself to retry on purpose). The task id goes to <name>.task as soon as it
exists, the model to <name>.glb. Costs seen on 2026-10-04: text-to-model P1 40 credits, image-to-model P1 50.
A prompt.json, for example:
    {"prompt": "Photorealistic ... plain, no logos, no text, no brand.", "negative_prompt": "cartoon, text, logo, brand",
     "model": "P1-20260311", "face_limit": 4000, "texture": true, "pbr": true, "texture_quality": "standard"}
`image` defaults to P1; its optional more.json is merged into the request body last, so a newer model and better
textures are a file away, e.g. {"model": "v3.1-20260211", "texture_quality": "detailed"}.
Then fit, atlas and compress the GLBs for the web with room_build/build_tripo2.mjs (or build_tripo.mjs / build_kbm_tripo.mjs).
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

API = "https://openapi.tripo3d.ai/v3"
DONE = ("success", "failed", "cancelled", "banned", "expired", "unknown")


def req(method, url, body=None):
    r = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=60) as f:
        return json.load(f)


def run(name, out, body_fn):
    task, glb = out / f"{name}.task", out / f"{name}.glb"
    if task.exists() or glb.exists():
        sys.exit(f"{name}: already submitted or generated ({task.name} / {glb.name} exist); not paying again")
    body = body_fn()
    tid = req("POST", f"{API}/generation/{body.pop('_endpoint')}", body)["data"]["task_id"]
    task.write_text(tid)
    print(name, tid, flush=True)
    while True:
        d = req("GET", f"{API}/tasks/{tid}")["data"]
        if d["status"] in DONE:
            break
        time.sleep(8)
    print(name, d["status"], "credits", d.get("credits_consumed"))
    if d["status"] != "success":
        sys.exit(1)
    urllib.request.urlretrieve(d["output"]["model_url"], glb)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=("text", "image", "balance"))
    ap.add_argument("args", nargs="*")
    ap.add_argument("--out", default=".")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    if a.kind == "balance":
        print(req("GET", f"{API}/account/balance")["data"])
    elif a.kind == "text":
        name, prompt = a.args
        run(name, out, lambda: {**json.loads(Path(prompt).read_text()), "_endpoint": "text-to-model"})
    else:
        name, image, face_limit, *rest = a.args
        more = json.loads(Path(rest[0]).read_text()) if rest else {}

        def body():                                   # upload the picture (multipart: curl), then image-to-model with its token
            up = json.loads(subprocess.run(["curl", "-sS", "-F", f"file=@{image}", f"{API}/files"],
                                           capture_output=True, text=True, check=True).stdout)
            return {"input": up["data"]["file_token"], "model": "P1-20260311", "face_limit": int(face_limit),
                    "texture": True, "pbr": True, "texture_quality": "standard", **more, "_endpoint": "image-to-model"}
        run(name, out, body)


if __name__ == "__main__":
    main()
