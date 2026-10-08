#!/usr/bin/env bash
# room_build/rig/mixamo_import.sh <mixamo.fbx> <out.glb> [original.glb]      (FALLBACK, after UPLOAD_STEPS.md)
# Mixamo's rigged character (FBX Binary, T-pose, With Skin) as the GLB web/room/char_mixamo.js loads: the mixamorig:*
# skeleton and skin as Mixamo made them (kimodo/mixamo_glb.mjs, no animation, the whole under one node scaled 0.01).
# Node cannot decode the FBX's textures, so they are left out and, given the original (the GLB that went into
# mixamo_upload.sh), its own base-colour textures are put back on the materials by name (to_obj.mjs names them m0, m1, ...
# in the original's order; Mixamo keeps the OBJ's material names and UVs).
set -euo pipefail
FBX=$(realpath "$1"); OUT=$(realpath -m "$2"); ORIG=${3:+$(realpath "$3")}
cd "$(dirname "$0")/.."
node kimodo/mixamo_glb.mjs "$FBX" "$OUT" --no-anim --no-textures
if [ -n "$ORIG" ]; then node --input-type=module - "$ORIG" "$OUT" <<'JS'
import { NodeIO } from "@gltf-transform/core"; import { ALL_EXTENSIONS } from "@gltf-transform/extensions"; import { MeshoptDecoder } from "meshoptimizer";
await MeshoptDecoder.ready; const [ORIG, OUT] = process.argv.slice(2);
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({"meshopt.decoder": MeshoptDecoder});
const src = await io.read(ORIG), dst = await io.read(OUT), mats = [];
for (const n of src.getRoot().listNodes()) { const m = n.getMesh(); if (m) for (const p of m.listPrimitives()) { const mt = p.getMaterial(); if (mt && !mats.includes(mt)) mats.push(mt); } }
let k = 0;
for (const mt of dst.getRoot().listMaterials()) { const i = +(mt.getName().match(/^m(\d+)/) || [])[1]; const s = mats[i]; if (!s || !s.getBaseColorTexture()) continue;
  const t = s.getBaseColorTexture(), nt = dst.createTexture(t.getName()).setImage(t.getImage()).setMimeType(t.getMimeType());
  mt.setBaseColorTexture(nt).setBaseColorFactor([1, 1, 1, 1]); k++; }
if (dst.getRoot().listTextures().some(t => t.getMimeType() === "image/webp")) dst.createExtension((await import("@gltf-transform/extensions")).EXTTextureWebP);
await io.write(OUT, dst); console.log(`mixamo_import: ${k} material(s) given their textures back from ${ORIG.split("/").pop()}`);
JS
fi
node rig/bones.mjs "$OUT" | head -1
