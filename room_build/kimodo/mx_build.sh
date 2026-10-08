#!/bin/bash
# kimodo/mx_build.sh <Clip> <work dir> : a Mixamo FBX (<work dir>/src/<Clip>.fbx, kept out of the repository) baked for
# the Mixamo-rigged character and our chair, into web/room/mh_mx/<out>.glb, with the fit of its row in mx_clips.json:
#   mixamo_glb.mjs (FBX -> GLB, nothing renamed) -> exp.mjs -> mx_fit.py (on char_mixamo's own skeleton: the seat,
#   the feet, the hands, the sleeves off the hoodie) -> writeclip.mjs. <work dir>/fit_<Clip>.json: the fit's numbers.
# Then run contact_pass.mjs on it in the room (room.html?char=mixamo).
set -e
C=$1; WK=$2; R=$(cd "$(dirname "$0")/../.." && pwd); K=$R/room_build/kimodo; G=$R/room_build/kimodo_g12
ROW=$(python3 - "$K/mx_clips.json" "$C" <<'PY'
import json, sys
t = json.load(open(sys.argv[1])); row = t["clips"][sys.argv[2]]; d = dict(t["defaults"].get(row["kind"], {})); d.update(row); print(json.dumps(d))
PY
)
OUT=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['out'])" "$ROW")
mkdir -p $WK $R/web/room/mh_mx
# (the character as the clips are fitted against: re-exported whenever char_mixamo.glb is newer)
[ $WK/char.json -nt $R/web/room/char_mixamo.glb ] || ALLMESH=1 node $G/exp.mjs $R/web/room/char_mixamo.glb $WK/char.json > /dev/null
node $K/mixamo_glb.mjs $WK/src/$C.fbx $WK/$C.glb | tail -1
node $G/exp.mjs $WK/$C.glb $WK/$C.json > /dev/null
python3 $K/mx_fit.py $WK/char.json $WK/$C.json "$ROW" $WK/fin_$C.json $WK/fit_$C.json
node $G/writeclip.mjs $WK/fin_$C.json $R/web/room/mh_mx/$OUT.glb | tail -1
