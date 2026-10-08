#!/bin/bash
# usage: rigcheck.sh file.glb  -> uploads, runs rig-check, prints result
F=$1; B=https://openapi.tripo3d.ai/v3
TOK=$(curl -s -m 300 -F "file=@$F" $B/files | python3 -c "import json,sys;print(json.load(sys.stdin)['data']['file_token'])")
T=$(curl -s -m 60 -H "Content-Type: application/json" -d "{\"input\":\"$TOK\"}" $B/animations/rig-check | python3 -c "import json,sys;print(json.load(sys.stdin)['data']['task_id'])")
for i in $(seq 1 40); do R=$(curl -s -m 30 $B/tasks/$T); S=$(echo "$R" | python3 -c "import json,sys;print(json.load(sys.stdin)['data'].get('status'))"); if [ "$S" = "success" ] || [ "$S" = "failed" ]; then echo "$F: $(echo "$R" | python3 -c "import json,sys;d=json.load(sys.stdin)['data'];print(d['status'],d.get('output'),'credits',d.get('credits_consumed'))") token=$TOK"; break; fi; sleep 5; done
