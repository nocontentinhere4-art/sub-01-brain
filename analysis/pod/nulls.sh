#!/bin/bash
# Null comparison on a RunPod CPU pod (python:3.11-slim): uploaded code + rw_<tag>_inputs.npz (made with --nulls 0)
# -> nulls generated here in parallel -> rw_<tag>_results.npz (saved incrementally, always copied to /out).
set -uo pipefail
while [ ! -f /in/READY ]; do sleep 2; done
N=$(awk '{ if ($1 == "max") print 0; else printf "%d", $1 / $2 }' /sys/fs/cgroup/cpu.max 2>/dev/null || echo 0)
[ "${N:-0}" -lt 1 ] && N=$(nproc)
T0=$(date +%s)
el() { echo "[$(( $(date +%s) - T0 ))s] $*"; }
mkdir -p /work/repo/twin /work/repo/analysis /work/repo/data/analysis
cp /in/hopf.py /in/__init__.py /work/repo/twin/ && cp /in/real_wiring.py /work/repo/analysis/ && cp /in/rw_*_inputs.npz /work/repo/data/analysis/
trap 'cp /work/repo/data/analysis/rw_*_results.npz /out/ 2>/dev/null; ls -la /out' EXIT
pip install -q --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu 2>&1 | tail -1
pip install -q --no-cache-dir scipy netneurotools 2>&1 | tail -1
el "installed ($N cores)"
cd /work/repo
for TAG in $TAGS; do
  OMP_NUM_THREADS=1 python3 -u analysis/real_wiring.py nulls --tag $TAG --nulls ${NNULL:-100} --workers $N
  el "$TAG nulls ready"
  OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python3 -u analysis/real_wiring.py run --tag $TAG --workers $N
  cp data/analysis/rw_${TAG}_results.npz /out/
  el "$TAG done"
done
