"""Render a preview video of the room on a real GPU: one RunPod pod, headless Chromium on the NVIDIA GPU, ffmpeg, the
MP4 brought back, the pod deleted. For the owner's approval of visual changes (#98): old vs new, side by side.

    python tools/gpu_preview.py --old main --new feature/gl-render --out docs/design/room-render/preview \
        --sizes 1280x800,390x844 --fps 30 --segments 14:60,23:30 --name render
    python tools/gpu_preview.py --new HEAD --sizes 1280x800 --segments 14:20 --dry-run     # package only, no pod

Two git refs (or one: --new only) are packaged with `git archive` (web/, tests/visual/page_checks.js, tools/) and
uploaded to the pod by analysis/runpod_job.py, which already enforces: one pod at a time, only pods we created (the pod
named "BRAIN" is never touched), deletion on finish / error / Ctrl-C and at the latest after --max-min, a ledger line in
data/analysis/costs.jsonl. This tool adds its own caps: 45 minutes, <= $1 per run and <= $5 over every run tagged
gpu-preview (the ledger is the record), and refuses before creating a pod when they would be exceeded. On the pod,
tools/gpu_preview_job.sh checks that WebGL runs on the GPU (the renderer string names the NVIDIA card, never
SwiftShader) before rendering; tools/gpu_preview_render.py does the frame-stepped rendering and the encoding (the same
script runs in a sandbox on software WebGL for a check: see --local). RunPod auth is injected by the environment for
rest.runpod.io; there is no key here and none is logged.

Where the videos go: NOT into main. Each MP4 is 10-30 MB and would stay in the repository's history for good, so the
previews live on the separate, never-merged branch `previews`, one folder per pull request (previews/<pr-number>/...);
the coordinator fetches them from there. --out defaults to a folder outside the working tree (data/previews/<name>);
publish with --publish <pr-number>, which commits the videos and their JSON to a checkout of that branch
(data/previews_branch, created from main the first time) and pushes it. The small JSON and the pod log may be
committed with a PR as a record; the MP4s never.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "data" / "analysis" / "costs.jsonl"
TAG = "gpu-preview"
CAP_RUN_USD, CAP_TOTAL_USD, MAX_MIN = 1.0, 5.0, 45.0
A5000_USD_PER_HR = 0.29                               # the rate seen so far ($0.27-0.29/h); the runner records the real one
IMAGE = "runpod/pytorch:2.8.0-py3.11-cuda12.8.1-cudnn-devel-ubuntu22.04"
PARTS = ["web", "tests/visual/page_checks.js", "tools/gpu_preview_render.py"]


def spent():
    """(usd, runs) of this tool so far, from the shared ledger."""
    if not LEDGER.exists():
        return 0.0, 0
    rows = [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()]
    mine = [r for r in rows if str(r.get("tag", "")).startswith(TAG)]
    return sum(r.get("usd", 0) for r in mine), len(mine)


def archive(ref, dest, log):
    """git archive <ref> of the parts the page needs, with this tool's renderer and the QA helpers from the working tree
    when the ref predates them (the old side is main, which may not carry tools/ yet)."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        have = [p for p in PARTS if subprocess.run(["git", "cat-file", "-e", f"{ref}:{p}"], cwd=ROOT, capture_output=True).returncode == 0]
        tar = td / "a.tar"
        with tar.open("wb") as f:
            subprocess.run(["git", "archive", "--format=tar", ref] + have, cwd=ROOT, stdout=f, check=True)
        with tarfile.open(tar) as t:
            t.extractall(td / "x")
        for p in PARTS:
            if p not in have:
                src = ROOT / p
                if src.exists():
                    (td / "x" / p).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy(src, td / "x" / p)
        with tarfile.open(dest, "w:gz") as t:
            for p in sorted((td / "x").iterdir()):
                t.add(p, arcname=p.name)
    log(f"packaged {ref} -> {dest.name} ({dest.stat().st_size / 1e6:.1f} MB: {', '.join(have)})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default="origin/main", help="git ref of the old side (main); '' for a single-side video")
    ap.add_argument("--new", default="HEAD", help="git ref of the new side")
    ap.add_argument("--out", default="", help="where the MP4s land (default: data/previews/<name>, outside the tree)")
    ap.add_argument("--publish", default="", help="pull request number: commit the videos to the `previews` branch (previews/<n>/) and push it")
    ap.add_argument("--name", default="preview")
    ap.add_argument("--sizes", default="1280x800,390x844")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--segments", default="14:60,23:30", help="hour:seconds,...")
    ap.add_argument("--max-mb", type=float, default=25)
    ap.add_argument("--label-old", default="main (old)"); ap.add_argument("--label-new", default="new")
    ap.add_argument("--shots", default="", help="a shot list JSON (tools/shots/*.json): custom cameras instead of --segments")
    ap.add_argument("--query-old", default=""); ap.add_argument("--query-new", default="", help="extra URL query per side (e.g. props=old)")
    ap.add_argument("--max-min", type=float, default=MAX_MIN)
    ap.add_argument("--wait-min", type=float, default=20, help="keep retrying while RunPod has no A5000")
    ap.add_argument("--dry-run", action="store_true", help="package the refs and print the runner command; no pod")
    ap.add_argument("--local", action="store_true", help="render here instead (software WebGL, tiny: 2 s a side) to check the pipeline")
    a = ap.parse_args()
    log = lambda *x: print(*x, flush=True)  # noqa: E731
    max_min = min(a.max_min, MAX_MIN)
    usd, runs = spent()
    est = A5000_USD_PER_HR * max_min / 60
    if est > CAP_RUN_USD:
        sys.exit(f"refusing: {max_min:.0f} min at ${A5000_USD_PER_HR}/h could cost ${est:.2f} > ${CAP_RUN_USD} per run")
    if usd + est > CAP_TOTAL_USD:
        sys.exit(f"refusing: ${usd:.2f} spent over {runs} runs + up to ${est:.2f} would pass the ${CAP_TOTAL_USD} total")
    log(f"gpu-preview: ${usd:.2f} spent over {runs} runs; this run <= {max_min:.0f} min (<= ${est:.2f})")

    work = Path(tempfile.mkdtemp(prefix="gpu_preview_"))
    sides = {"new": a.new} | ({"old": a.old} if a.old else {})
    for side, ref in sides.items():
        archive(ref, work / f"{side}.tar.gz", log)
    if not a.old:                                     # a single side still needs an old.tar.gz for the job: the same ref
        shutil.copy(work / "new.tar.gz", work / "old.tar.gz")
    out = (ROOT / a.out) if a.out else (ROOT / "data" / "previews" / a.name)
    out.mkdir(parents=True, exist_ok=True)

    if a.local:
        rd = ROOT / "tools" / "gpu_preview_render.py"
        for size in a.sizes.split(","):
            fr = work / "frames" / size
            for side in sides:
                x = work / "x" / side
                shutil.rmtree(x, ignore_errors=True); x.mkdir(parents=True)
                with tarfile.open(work / f"{side}.tar.gz") as t:
                    t.extractall(x)
                subprocess.run([sys.executable, str(rd), "--web", str(x / "web"), "--side", side, "--size", size, "--fps", str(a.fps),
                                "--segments", a.segments, "--frames", str(fr), "--local-cdn", "--shadow-every", "3",
                                "--query", a.query_old if side == "old" else a.query_new] + (["--shots", str(Path(a.shots).resolve())] if a.shots else []) + [
                                "--chromium", os.environ.get("SUB01_CHROMIUM", "/opt/pw-browsers/chromium"), "--port", str(8880 + (side == "new"))], check=True)
            subprocess.run([sys.executable, str(rd), "--encode", "--frames", str(fr), "--out", str(out / f"{a.name}_{size}.mp4"), "--max-mb", str(a.max_mb),
                            "--label-old", a.label_old, "--label-new", a.label_new], check=True)
        shutil.rmtree(work, ignore_errors=True)
        return 0

    cmd = [sys.executable, str(ROOT / "analysis" / "runpod_job.py"), "--kind", "a5000", "--wait-min", str(a.wait_min), "--image", IMAGE,
           "--script", str(ROOT / "tools" / "gpu_preview_job.sh"), "--upload", str(work / "old.tar.gz"), str(work / "new.tar.gz")] + ([str(Path(a.shots).resolve())] if a.shots else []) + [
           "--fetch"] + [f"preview_{sz}.{ext}" for sz in a.sizes.split(",") for ext in ("mp4", "json")] + ["gpu_args.txt",
           "--dest", str(work / "fetched"), "--tag", f"{TAG}-{a.name}", "--disk", "40", "--max-min", str(max_min),
           "--env", f"SIZES={' '.join(a.sizes.split(','))}", f"FPS={a.fps}", f"SEGMENTS={a.segments}", f"LABEL_OLD={a.label_old}", f"LABEL_NEW={a.label_new}",
           f"MAX_MB={a.max_mb:g}", "NVIDIA_DRIVER_CAPABILITIES=all", f"SHOTS={Path(a.shots).name if a.shots else ''}", f"QUERY_OLD={a.query_old}", f"QUERY_NEW={a.query_new}"]
    if a.dry_run:
        log("dry run; the runner command would be:\n  " + " ".join(cmd))
        return 0
    t0 = time.time()
    r = subprocess.run(cmd, cwd=ROOT)
    got = []
    mp4s = sorted((work / "fetched").glob("preview_*.mp4"))
    if r.returncode != 0 or not mp4s:
        sys.exit(f"the pod job failed (exit {r.returncode}) and brought no video; the runner's log is in {work / 'fetched'} if it got that far")
    for mp4 in mp4s:
        dest = out / f"{a.name}_{mp4.name.split('_', 1)[1]}"
        shutil.copy(mp4, dest); got.append(dest)
        j = mp4.with_suffix(".json")
        if j.exists():
            shutil.copy(j, dest.with_suffix(".json"))
    (work / "fetched" / f"{TAG}-{a.name}_log.txt").exists() and shutil.copy(work / "fetched" / f"{TAG}-{a.name}_log.txt", out / f"{a.name}_pod_log.txt")
    usd2, runs2 = spent()
    log(f"done in {(time.time() - t0) / 60:.1f} min; this run ${usd2 - usd:.3f}; tool total ${usd2:.2f} over {runs2} runs")
    for d in got:
        log(f"  {d.relative_to(ROOT) if d.is_relative_to(ROOT) else d} ({d.stat().st_size / 1e6:.1f} MB)")   # (--out may lie outside the tree)
    shutil.rmtree(work, ignore_errors=True)
    if got and a.publish:
        publish(got + [d.with_suffix(".json") for d in got if d.with_suffix(".json").exists()] + [out / f"{a.name}_pod_log.txt"], a.publish, log)
    return 0 if got else 1


def publish(files, pr, log):
    """Commit the preview files to the never-merged `previews` branch under previews/<pr>/ and push it."""
    wt = ROOT / "data" / "previews_branch"
    if not wt.exists():
        subprocess.run(["git", "fetch", "-q", "origin", "main", "previews"], cwd=ROOT)
        has = subprocess.run(["git", "rev-parse", "-q", "--verify", "origin/previews"], cwd=ROOT, capture_output=True).returncode == 0
        subprocess.run(["git", "worktree", "add", "-q"] + (["-B", "previews", str(wt), "origin/previews"] if has else ["-b", "previews", str(wt), "origin/main"]), cwd=ROOT, check=True)
    else:
        subprocess.run(["git", "pull", "-q", "--ff-only", "origin", "previews"], cwd=wt)
    dest = wt / "previews" / str(pr)
    dest.mkdir(parents=True, exist_ok=True)
    for f in files:
        if Path(f).exists():
            shutil.copy(f, dest / Path(f).name)
    subprocess.run(["git", "add", f"previews/{pr}"], cwd=wt, check=True)
    msg = f"previews/{pr}: " + ", ".join(Path(f).name for f in files if Path(f).exists() and str(f).endswith(".mp4"))
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=wt, check=True)
    subprocess.run(["git", "push", "-u", "origin", "previews"], cwd=wt, check=True)
    log(f"published to the previews branch: previews/{pr}/")


if __name__ == "__main__":
    sys.exit(main())
