// node seam.mjs clip.glb...: the loop seam: per bone, the rotation jump last->first frame (deg) vs the clip's typical
// frame-to-frame step; the Hip translation jump (cm)
import { NodeIO } from "@gltf-transform/core"; import { ALL_EXTENSIONS } from "@gltf-transform/extensions"; import { MeshoptDecoder } from "meshoptimizer"; import * as THREE from "three";
await MeshoptDecoder.ready; const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({"meshopt.decoder": MeshoptDecoder});
for (const f of process.argv.slice(2)) { const d = await io.read(f), a = d.getRoot().listAnimations()[0]; let worst = [0, ""], hipJ = 0, dur = 0, step = 0, nstep = 0;
  for (const c of a.listChannels()) { const s = c.getSampler(), inp = s.getInput().getArray(), o = s.getOutput().getArray(), n = inp.length; dur = Math.max(dur, inp[n - 1]);
    if (c.getTargetPath() === "rotation") { const q0 = new THREE.Quaternion().fromArray(o, 0), q1 = new THREE.Quaternion().fromArray(o, (n - 1) * 4), g = q0.angleTo(q1) * 57.3;
      if (g > worst[0]) worst = [g, c.getTargetNode().getName()];
      for (let i = 1; i < n; i++) { step += new THREE.Quaternion().fromArray(o, (i - 1) * 4).angleTo(new THREE.Quaternion().fromArray(o, i * 4)) * 57.3 / Math.max(1e-3, (inp[i] - inp[i - 1]) * 30); nstep++; } }
    else if (c.getTargetPath() === "translation") hipJ = Math.hypot(o[0] - o[(n - 1) * 3], o[1] - o[(n - 1) * 3 + 1], o[2] - o[(n - 1) * 3 + 2]) * 100; }
  console.log(f.split("/").pop(), "dur", dur.toFixed(2), "s | worst bone jump at the loop", worst[0].toFixed(1), "deg", worst[1], "| Hip jump", hipJ.toFixed(1), "cm | mean step/frame", (step / nstep).toFixed(2), "deg"); }
