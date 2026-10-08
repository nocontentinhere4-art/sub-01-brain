// node fbx2ply.mjs <in.fbx> <out.ply>: FBX -> binary PLY (per-corner positions, normals, uvs) with three.js's FBXLoader, no DOM
// (the owner's Tripo chair, docs/design/chair-tripo/chair_owner_raw.fbx, for chair_owner_repair.py)
import fs from "node:fs";
globalThis.self = globalThis; globalThis.window = globalThis;
globalThis.document = {createElementNS: () => ({style: {}}), createElement: () => ({style: {}, getContext: () => null})};
const THREE = await import("three");
const { FBXLoader } = await import("three/examples/jsm/loaders/FBXLoader.js");
THREE.TextureLoader.prototype.load = () => new THREE.Texture();
const buf = fs.readFileSync(process.argv[2]);
const obj = new FBXLoader().parse(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.length), "");
obj.updateMatrixWorld(true);
const P = [], N = [], U = [], I = []; let mats = [];
obj.traverse(o => { if (!o.isMesh) return; const g = o.geometry.clone().applyMatrix4(o.matrixWorld);
  mats.push([o.name, [].concat(o.material).map(m => m.name)]);
  const pos = g.attributes.position, nor = g.attributes.normal, uv = g.attributes.uv, base = P.length / 3;
  for (let i = 0; i < pos.count; i++) { P.push(pos.getX(i), pos.getY(i), pos.getZ(i)); if (nor) N.push(nor.getX(i), nor.getY(i), nor.getZ(i)); if (uv) U.push(uv.getX(i), uv.getY(i)); }
  if (g.index) for (let i = 0; i < g.index.count; i++) I.push(base + g.index.getX(i)); else for (let i = 0; i < pos.count; i++) I.push(base + i); });
const nv = P.length / 3, nf = I.length / 3;
const hdr = `ply\nformat binary_little_endian 1.0\nelement vertex ${nv}\nproperty float x\nproperty float y\nproperty float z\nproperty float nx\nproperty float ny\nproperty float nz\nproperty float s\nproperty float t\nelement face ${nf}\nproperty list uchar int vertex_indices\nend_header\n`;
const vb = Buffer.alloc(nv * 32), fb = Buffer.alloc(nf * 13);
for (let i = 0; i < nv; i++) { const o = i * 32; vb.writeFloatLE(P[3*i], o); vb.writeFloatLE(P[3*i+1], o+4); vb.writeFloatLE(P[3*i+2], o+8);
  vb.writeFloatLE(N[3*i] || 0, o+12); vb.writeFloatLE(N[3*i+1] || 0, o+16); vb.writeFloatLE(N[3*i+2] || 0, o+20); vb.writeFloatLE(U[2*i] || 0, o+24); vb.writeFloatLE(U[2*i+1] || 0, o+28); }
for (let f = 0; f < nf; f++) { const o = f * 13; fb.writeUInt8(3, o); fb.writeInt32LE(I[3*f], o+1); fb.writeInt32LE(I[3*f+1], o+5); fb.writeInt32LE(I[3*f+2], o+9); }
fs.writeFileSync(process.argv[3], Buffer.concat([Buffer.from(hdr), vb, fb]));
const lo = [1e9,1e9,1e9], hi = [-1e9,-1e9,-1e9]; for (let i = 0; i < nv; i++) for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], P[3*i+k]); hi[k] = Math.max(hi[k], P[3*i+k]); }
console.log({nv, nf, lo, hi, mats, hasUV: U.length > 0});
