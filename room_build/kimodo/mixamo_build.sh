#!/bin/bash
# mixamo_build.sh <Clip> <work dir> : a Mixamo FBX (<work dir>/src/<Clip>.fbx, kept out of the repository) to its v5 clip
# web/room/mh_v5/<out>.glb, with the fit of its row in mixamo_clips.json:
#   mixamo_src.mjs (FBX -> MakeHuman-convention source) -> mh_retarget.mjs (hip-height scale, spine pitch)
#   -> kimodo_g12/post.py (seated: the hips onto our chair, feet planted on the floor, hands kept where the performer
#      rested them) -> writeclip -> qa.py. Then run contact_pass.mjs on it in the room (chair, seat, desk, floor, bed, his legs).
# Needs node (three, @gltf-transform, meshoptimizer) and python3 (numpy, scipy); <work dir>/json/v5.json = exp.mjs of
# web/room/char_v5.glb (the body the page shows) and mh_body.json.
set -e
C=$1; WK=$2; R=$(cd "$(dirname "$0")/../.." && pwd); K=$R/room_build/kimodo; G=$R/room_build/kimodo_g12
eval "$(python3 - "$K/mixamo_clips.json" "$C" <<'PY'
import json, sys
t = json.load(open(sys.argv[1])); row = t["clips"][sys.argv[2]]; d = dict(t["defaults"].get(row["kind"], {})); d.update(row)
k = d.get("keys", [0, 0]); print(f'KEYS={k[0]},{k[1]} OUT={d["out"]} PITCH={d.get("pitch", 0)} HIPY={d.get("seatHipY", 0)} FWD={d.get("seatForward", 0)} SOLE={d.get("soleUp", 0.002)} HUP={d.get("handUp", 0)} SCALE={d.get("scale", "hip")} ORIG={1 if d.get("seatOrigin") else ""} TRIM={",".join(map(str, d["trim"])) if "trim" in d else ""}')
PY
)"
mkdir -p $WK/json; echo "{\"scale\":\"$SCALE\",\"pitch\":$PITCH}" > $WK/o_$C.json
node $K/mixamo_src.mjs $WK/src/$C.fbx $WK/src_$C.glb ${TRIM:+--trim $TRIM}
node $K/mh_retarget.mjs $WK/src_$C.glb $R/web/room/char_v5.glb $WK/rt_$C.glb $WK/o_$C.json | tail -c 300; echo
node $G/exp.mjs $WK/rt_$C.glb $WK/rt_$C.json > /dev/null; node $G/exp.mjs $WK/src_$C.glb $WK/json/$C.json > /dev/null
SEAT_ORIGIN=$ORIG NOLIE=1 LOCK_MH=1 SHIFT_MAX=0.45 SEAT_HIP_Y=$HIPY SEAT_FWD=$FWD SOLE_UP=$SOLE HAND_UP=$HUP KEYS=$KEYS python3 $G/post.py $WK/json $C $WK/rt_$C.json $WK/fin_$C.json | tail -2
node $G/writeclip.mjs $WK/fin_$C.json $R/web/room/mh_v5/$OUT.glb | tail -1
node $G/exp.mjs $R/web/room/mh_v5/$OUT.glb $WK/fin_$C.x.json > /dev/null; python3 $G/qa.py $WK/json $C $WK/fin_$C.x.json | tail -1
