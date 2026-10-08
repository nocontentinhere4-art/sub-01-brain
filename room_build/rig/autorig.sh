#!/usr/bin/env bash
# room_build/rig/autorig.sh <in.glb> <out.glb> [clips dir]
# Puts a rigged character (v5's layout: one skin, MakeHuman/Tripo joint names, fingers) on the Mixamo Standard Skeleton
# (65 bones with fingers, mixamorig:* names, Mixamo's hierarchy, T-pose rest) without mixamo.com, in a few minutes:
#   extract.mjs  the mesh and its old skin, in bind space
#   fit.py       T-pose from its own skin, the joints fitted, the weights computed (rig/autorig/fit.py says how)
#   write.mjs    the same file with the new skeleton and skin (meshopt, positions float)
# With a clips dir (Mixamo clips as GLB, kimodo/mixamo_glb.mjs's: <dir>/Seated_Idle.glb ...), also the QA:
# qa.mjs (render sheet + deformation and contact numbers) and rig_change.mjs (the rig-change checklist report),
# written next to <out.glb> as <out>.qa/.
# The Mixamo reference (mixamo_standard_skeleton.json) is the Standard Skeleton's T-pose only (bone names, rest
# positions and rotations, read from a capture's rest with refskel.mjs): no motion, no raw capture.
set -euo pipefail
IN=$(realpath "$1"); OUT=$(realpath -m "$2"); CLIPS=${3:-}
HERE=$(cd "$(dirname "$0")" && pwd); cd "$HERE/.."                    # (room_build: its node_modules)
mkdir -p "$(dirname "$OUT")"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/autorig.XXXXXX"); trap 'rm -rf "$WORK"' EXIT
t0=$(date +%s)
node rig/autorig/extract.mjs "$IN" "$WORK/x" >/dev/null
mkdir -p "$WORK/fit"
python3 rig/autorig/fit.py "$WORK/x" rig/autorig/mixamo_standard_skeleton.json "$WORK/fit"
node rig/autorig/write.mjs "$IN" "$WORK/fit" "$OUT" | grep -v '^prune'
cp "$WORK/fit/skel.json" "${OUT%.glb}.rig.json"
echo "autorig: $(( $(date +%s) - t0 )) s -> $OUT (+ ${OUT%.glb}.rig.json: joints and fit report)"
if [ -n "$CLIPS" ]; then
  QA="${OUT%.glb}.qa"; mkdir -p "$QA"
  node rig/autorig/qa.mjs "$OUT" "$CLIPS" "$QA"
  node kimodo/rig_change.mjs "$OUT" "$CLIPS" "$QA"
  echo "autorig QA: $QA ($(( $(date +%s) - t0 )) s in all)"
fi
