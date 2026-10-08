#!/bin/bash
# Connectome v2 on a RunPod pod (MRtrix3 3.0.8 image). Inputs in /in (uploaded): 5tt.nii.gz, labels.nii.gz,
# mask_t1grid.nii.gz (all on the T1 1 mm grid, headers already in DWI world space). DWI streamed from OpenNeuro.
# 1) dwigradcheck fixes the gradient table orientation; 2) pilots with and without ACT (the 5TT is T1-derived without
# FSL/FreeSurfer, see analysis/make_5tt.py) - ACT is used only if it does not truncate streamlines; 3) deadline-aware
# production in chunks (independent seeds = consistency subsets); SIFT2; assignment. Partial results are always packed.
set -uo pipefail
while [ ! -f /in/READY ]; do sleep 2; done
N=$(awk '{ if ($1 == "max") print 0; else printf "%d", $1 / $2 }' /sys/fs/cgroup/cpu.max 2>/dev/null || echo 0)
[ "${N:-0}" -lt 1 ] && N=$(nproc)
T0=$(date +%s)
el() { echo "[$(( $(date +%s) - T0 ))s] $*"; }
left() { echo $(( JOB_MIN * 60 - ( $(date +%s) - T0 ) )); }
pack() { tar czf /out/connectome_v2_raw.tar.gz $(ls conn_sift2.csv assign.txt sift2.txt mu.txt lengths.txt chunks.txt chunk_counts.txt wm.txt gm.txt csf.txt pilot.txt grad.b 2>/dev/null); el "packed $(du -h /out/connectome_v2_raw.tar.gz | cut -f1)"; }
trap pack EXIT
B=https://s3.amazonaws.com/openneuro.org/ds000031/sub-01/ses-2015/dwi/sub-01_ses-2015_acq-g79_dir-pe0_dwi
python3 - <<PY
import urllib.request
for ext in ("nii.gz", "bval", "bvec"):
    urllib.request.urlretrieve("$B." + ext, "dwi." + ext)
PY
el "downloaded DWI ($N threads)"
set -e
cp /in/*.nii.gz .
mrconvert -quiet dwi.nii.gz -fslgrad dwi.bvec dwi.bval dwi_raw.mif -datatype float32
mrgrid -quiet mask_t1grid.nii.gz regrid -template dwi_raw.mif -interp nearest mask.mif
dwigradcheck -quiet dwi_raw.mif -mask mask.mif -export_grad_mrtrix grad.b -nthreads $N
mrconvert -quiet dwi_raw.mif -grad grad.b dwi.mif
el "gradient check: $(diff <(mrinfo dwi_raw.mif -dwgrad) grad.b > /dev/null && echo 'table unchanged' || echo 'table CHANGED by dwigradcheck')"
dwi2response -quiet dhollander dwi.mif wm.txt gm.txt csf.txt -mask mask.mif -nthreads $N
dwi2fod -quiet msmt_csd dwi.mif -mask mask.mif wm.txt wmfod.mif gm.txt gm.mif csf.txt csf.mif -nthreads $N
mtnormalise -quiet wmfod.mif wmfod_n.mif gm.mif gm_n.mif csf.mif csf_n.mif -mask mask.mif -nthreads $N
5ttcheck -quiet 5tt.nii.gz
5tt2gmwmi -quiet 5tt.nii.gz gmwmi.mif
# WM seed mask from the DWI itself: l=0 WM-FOD coefficient > 0.15 (~ > 50 % WM after mtnormalise)
mrconvert -quiet wmfod_n.mif -coord 3 0 -axes 0,1,2 - | mrthreshold -quiet - -abs 0.15 wmseed.mif
el "FODs done"
ACT_OPTS="-act 5tt.nii.gz -backtrack -crop_at_gmwmi -seed_gmwmi gmwmi.mif"
NOACT_OPTS="-seed_image wmseed.mif -cutoff 0.06"
tckgen -quiet -algorithm iFOD2 $ACT_OPTS -select 200000 -maxlength 250 -nthreads $N wmfod_n.mif pa.tck
tckgen -quiet -algorithm iFOD2 $NOACT_OPTS -select 200000 -minlength 10 -maxlength 250 -nthreads $N wmfod_n.mif pn.tck
ma=$(tckstats -quiet pa.tck -output median); mn=$(tckstats -quiet pn.tck -output median)
tck2connectome -quiet -symmetric -zero_diagonal pa.tck labels.nii.gz pa.csv -nthreads $N
tck2connectome -quiet -symmetric -zero_diagonal pn.tck labels.nii.gz pn.csv -nthreads $N
python3 - > pilot.txt <<PY || true
rows = {}
for f in ("pa", "pn"):
    W = [[float(v) for v in l.replace(",", " ").split()] for l in open(f + ".csv") if l.strip()]
    n = len(W)
    lh = [i < 100 or 200 <= i < 207 for i in range(n)]
    tot = sum(map(sum, W)) / 2
    inter = sum(W[i][j] for i in range(n) for j in range(n) if lh[i] and not lh[j])
    print(f, "median_len", {"pa": "$ma", "pn": "$mn"}[f], "assigned", int(tot), "inter_share", round(inter / max(tot, 1), 4),
          "homotopic_edges", sum(W[i][i + 100] > 0 for i in range(100)))
PY
cat pilot.txt
if python3 -c "import sys; sys.exit(0 if float('$ma') >= 0.8 * float('$mn') else 1)"; then
  OPTS=$ACT_OPTS; SIFT_ACT="-act 5tt.nii.gz"; el "using ACT"
else
  OPTS="$NOACT_OPTS -minlength 10"; SIFT_ACT=""; el "ACT truncates streamlines with this 5TT (median $ma vs $mn mm): using no ACT"
fi
echo "OPTS $OPTS" >> pilot.txt
rm -f pa.tck pn.tck
CHUNK=${CHUNK:-500000}
MAXCHUNKS=${MAXCHUNKS:-20}
k=0; last=0
while [ $k -lt $MAXCHUNKS ]; do
  k=$((k + 1)); s=$(date +%s)
  tckgen -quiet -algorithm iFOD2 $OPTS -select $CHUNK -maxlength 250 -nthreads $N wmfod_n.mif t$k.tck
  last=$(( $(date +%s) - s ))
  el "chunk $k ($CHUNK streamlines, ${last}s)"
  need=$(( 300 + k * last / 4 + last + 120 ))
  if [ $(left) -lt $need ]; then el "stopping after $k chunks (time left $(left)s, need ~${need}s)"; break; fi
done
ls t*.tck | sort -V > chunks.txt
for f in $(cat chunks.txt); do tckinfo -count $f | grep "actual count"; done > chunk_counts.txt
tckedit -quiet $(cat chunks.txt) tracks.tck
rm -f t[0-9]*.tck
el "merged: $(tckinfo -count tracks.tck | grep 'actual count')"
tcksift2 -quiet $SIFT_ACT tracks.tck wmfod_n.mif sift2.txt -out_mu mu.txt -nthreads $N
el "SIFT2 done"
tck2connectome -quiet -symmetric -zero_diagonal -tck_weights_in sift2.txt tracks.tck labels.nii.gz conn_sift2.csv \
               -out_assignments assign.txt -nthreads $N
tckstats -quiet tracks.tck -dump lengths.txt
el "connectome + assignments done"
