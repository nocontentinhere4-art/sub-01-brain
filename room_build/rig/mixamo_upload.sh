#!/usr/bin/env bash
# room_build/rig/mixamo_upload.sh <in.glb> <out.zip>      (FALLBACK: only if rig/autorig.sh's result is not accepted)
# The character as the ZIP mixamo.com's auto-rigger takes (OBJ + MTL + textures): skin and animations dropped, the bind
# pose kept, feet on y = 0, 1.75 m, facing +Z (static.mjs); simplified to ~160k triangles (simplify.mjs, RATIO, default 0.4: v5 402k -> 160,899;
# 0.33 gives 132,741); textures 2048² JPEG. The owner uploads it by hand: UPLOAD_STEPS.md.
set -euo pipefail
IN=$(realpath "$1"); OUT=$(realpath -m "$2"); RATIO=${RATIO:-0.4}
cd "$(dirname "$0")/.."
W=$(mktemp -d "${TMPDIR:-/tmp}/mixamo_up.XXXXXX"); trap 'rm -rf "$W"' EXIT
node rig/static.mjs "$IN" "$W/static.glb" | tail -1
node rig/simplify.mjs "$W/static.glb" "$W/small.glb" "$RATIO"
node rig/to_obj.mjs "$W/small.glb" "$W/obj"
# textures: 2048² JPEG (to_obj writes each base colour as m<k>.png)
node -e '
const sharp = require("sharp"), fs = require("fs"), d = process.argv[1]; let mtl = fs.readFileSync(d + "/character.mtl", "utf8");
(async () => { for (const f of fs.readdirSync(d).filter(f => f.endsWith(".png"))) { const j = f.replace(/\.png$/, ".jpg");
  await sharp(d + "/" + f).resize(2048, 2048, {fit: "inside"}).jpeg({quality: 90}).toFile(d + "/" + j); fs.unlinkSync(d + "/" + f); mtl = mtl.split(f).join(j); }
  fs.writeFileSync(d + "/character.mtl", mtl); })();' "$W/obj"
mkdir -p "$(dirname "$OUT")"; rm -f "$OUT"; (cd "$W/obj" && zip -q -9 "$OUT" character.obj character.mtl *.jpg)
echo "mixamo_upload: $OUT ($(du -h "$OUT" | cut -f1)): $(unzip -l "$OUT" | tail -1 | awk '{print $2}') files"
