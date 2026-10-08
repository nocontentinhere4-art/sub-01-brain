#!/bin/bash
# kimodo/mx_room.sh <port> <out dir> [v5] : the rig-change checklist's room items (kimodo/rig_change.mjs reads
# <out dir>/room/), measured in the page (web/ served on <port>), every frame, by contact_pass.mjs and seat_sweep.mjs:
#   sit_down     window>research 4 s: the sit-down step (the thigh vs the cushion's front as he lands)
#   stand_up     research>window 4 s: rising (the calf under the cushion's edge)
#   step_away    research>window 8 s: the stand-up and the first steps away (the calf through the chair's base)
#   watch/type/mouse  seated at the desk in each mode, 8 s (typing 6 s: a search types for 4-8 s; the mouse mode: the right palm on the mouse)
#   rare_*       each rare event at the desk from its start, 14 s (the chair's ride back: mh.M.log)
#   sweep        the seat points (SEAT_AT) per desk mode
# With "v5" as the 3rd argument: the same on v5 (the page without ?char=mixamo), for the before column. NOSWEEP=1: not the
# sweep (it takes 20 minutes and does not depend on the seat points chosen).
P=$1; O=$2/room; mkdir -p $O; K=$(cd "$(dirname "$0")" && pwd); cd $K/..
QS="&char=mixamo"; T=mx; [ "$3" = v5 ] && { QS=""; T=v5; }
run() { QS="$QS" LIFE="$4" RARE="$5" node kimodo/contact_pass.mjs $P "$2" $3 $O/${T}_$1.json > /dev/null 2>&1 || echo "contact $1 failed"; }
run sit_down "window>research" 4
run stand_up "research>window" 4
run step_away "research>window" 8
run watch research 8 '{"screen": {"id": "v", "kind": "video"}}'
run type research 6 '{"screen": {"id": "s1", "search": {"query": "how do tides work exactly"}}}'
run mouse chart 8
for r in scared angry clap; do run rare_$r research 14 '' $r; done
[ -n "$NOSWEEP" ] || QS="$QS" node kimodo/seat_sweep.mjs $P $O/${T}_sweep.json > $O/${T}_sweep.log 2>&1 || echo "sweep failed"
ls $O
