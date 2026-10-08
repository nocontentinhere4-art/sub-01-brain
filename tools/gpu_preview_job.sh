#!/bin/bash
# Pod side of tools/gpu_preview.py, run by analysis/runpod_job.py on one RunPod GPU pod: the checkouts arrive in /in as
# tarballs (old.tar.gz, new.tar.gz: web/, tests/visual/page_checks.js, tools/), the preview is rendered with headless
# Chromium on the real GPU (the WebGL renderer string must name the NVIDIA GPU, never SwiftShader), encoded with ffmpeg
# and left in /out/preview.tar.gz. Parameters come in the environment: SIZES ("1280x800 390x844"), FPS, SEGMENTS
# ("14:60,23:30"), LABEL_OLD, LABEL_NEW, MAX_MB. No secrets anywhere.
set -uxo pipefail
cd /work
echo "gpu: $(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq ffmpeg fonts-dejavu-core libegl1 libgles2 libgl1 libvulkan1 mesa-vulkan-drivers 2>&1 | tail -2
pip install -q playwright pillow 2>&1 | tail -1
python3 -m playwright install --with-deps chromium 2>&1 | tail -2
ls /usr/lib/x86_64-linux-gnu/ | grep -i "nvidia-egl\|EGL_nvidia\|nvidia-glvkspirv\|GLX_nvidia" | head -5
ls /etc/vulkan/icd.d/ /usr/share/vulkan/icd.d/ 2>/dev/null | head -5
mkdir -p /work/old /work/new /work/frames
tar -xzf /in/old.tar.gz -C /work/old && tar -xzf /in/new.tar.gz -C /work/new
R=/work/new/tools/gpu_preview_render.py

# which flags give Chromium the NVIDIA GPU here: the first set whose WebGL renderer names it wins
GPU_ARGS=""
# (channel=chromium: Playwright's full Chromium in the new headless mode rather than the headless shell)
# (the first is the one that worked on an RTX A5000 pod, driver 595: ANGLE over the NVIDIA EGL library)
for cand in "channel=chromium,--use-gl=angle,--use-angle=gl-egl" \
            "channel=chromium,--use-angle=vulkan,--use-vulkan=native,--enable-features=Vulkan" \
            "channel=chromium,--use-gl=egl" \
            "--use-gl=angle,--use-angle=gl-egl" \
            "--use-angle=vulkan,--use-vulkan=native,--enable-features=Vulkan" \
            "--use-gl=egl" \
            "channel=chromium,--use-angle=gl,--use-gl=angle"; do
  r=$(python3 $R --probe --gpu-args="$cand" 2>&1 | tail -1)
  echo "probe [$cand] -> $r"
  case "$r" in *NVIDIA*|*nvidia*) GPU_ARGS="$cand"; break;; esac
done
if [ -z "$GPU_ARGS" ]; then echo "NO GPU WEBGL: every flag set fell back to software"; exit 1; fi
echo "$GPU_ARGS" > /out/gpu_args.txt

for size in $SIZES; do
  for side in old new; do
    SHOTS_ARG=""; [ -n "${SHOTS:-}" ] && SHOTS_ARG="--shots /in/$SHOTS"
    Q=$([ $side = old ] && echo "${QUERY_OLD:-}" || echo "${QUERY_NEW:-}")
    python3 $R --web /work/$side/web --side $side --size $size --fps $FPS --segments "$SEGMENTS" $SHOTS_ARG --query "$Q" --frames /work/frames/$size \
      --gpu-args="$GPU_ARGS" --require-gpu --port 88$([ $side = old ] && echo 71 || echo 72) || exit 1
  done
  python3 $R --encode --frames /work/frames/$size --out /out/preview_$size.mp4 --max-mb "$MAX_MB" --label-old "$LABEL_OLD" --label-new "$LABEL_NEW" || exit 1
  cp /work/frames/$size/*_meta.json /out/ 2>/dev/null; for s in old new; do cp /work/frames/$size/${s}_meta.json /out/${s}_${size}_meta.json; done
done
ls -la /out                                       # (the videos and their JSON stay in /out as files: fetched one by one, so a size that failed does not lose the others)
