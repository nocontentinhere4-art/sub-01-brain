# ARDY clips for the room's character (#98 G3)

Text-to-motion with NVIDIA [ARDY](https://github.com/nv-tlabs/ardy) on one RunPod GPU pod, retargeted onto `web/room/boy.glb`
(the original Meshy rig, 24 bones). Licences and the gated-model note are in `web/room/CREDITS.md`.

## Rebuild
From the repository root (RunPod auth is injected by the environment for `rest.runpod.io`; one RTX A5000 pod at a time,
deleted by the runner when the job ends; every minute goes to `data/analysis/costs.jsonl`):

    python analysis/runpod_job.py --kind a5000 --wait-min 25 --image runpod/pytorch:2.8.0-py3.11-cuda12.8.1-cudnn-devel-ubuntu22.04 \
        --script room_build/ardy/job.sh --upload room_build/ardy/gen.py room_build/ardy/specs.json \
        --fetch ardy_out.tar.gz gen.log llama_shards_check.txt ardy_commit.txt --dest data/analysis/ardy --tag ardy --disk 60
    tar xzf data/analysis/ardy/ardy_out.tar.gz -C data/analysis/ardy
    cd room_build && npm install && node ardy_to_boy.mjs ../data/analysis/ardy/ardy ../web/room/boy.glb ../web/room

A run takes about 7 minutes (4 of them set-up: ARDY, its checkpoint and the text encoder download at the pod's speed; the
model loads in 150 s; a clip generates in 0.5 s). `specs.json` holds the prompts, durations, seeds and the optional
constraint pins; `specs_v2.json` was the second pass (stronger text guidance, more seeds, the walk picked by root speed)
whose `walk`, `lie_back` and `stretch` replaced the first pass's. `gen.py` keeps every sample (`<name>_samples/`) and
picks the cleanest (foot skating + jitter + feet under the floor, after ARDY's own foot-skate post-process).

## What the retarget does (`ardy_to_boy.mjs`)
World-space rotation of every mapped joint, with the two rest poses aligned per bone (ARDY's T-pose vs the rig's A-pose:
about 60 degrees on the arms); Hips translation scaled by the hip-height ratio (0.963); a seamless loop per cyclic clip
(the best matching pose pair is cropped out, the seam blended over 8 frames); the walk made in-place and timed so its feet
move at the page's stride speed (room.html's `STRIDE_V`, 0.65 m/s); the turn de-yawed (the page turns the root); the
root lifted by any foot penetration. Output: rotation tracks + Hips translation, float, no meshopt (the tests read the
files without a decoder), 13-61 KB per clip, and `boy_m_manifest.json` (hips offsets for the page's HIPS table, loop,
duration, the prompt and seed, the sample's scores).

## Checks
    python -m pytest tests/test_boy_motion.py                  # every clip binds, no NaN, feet on the floor, sizes, the hook
    python tests/clip_sheet.py --clips boy_m_walk,boy_walk     # a clip on the rig alone, frames side by side
    python tests/motion_shots.py --out docs/screens/motion     # old vs new in the room at 1280 and 390
