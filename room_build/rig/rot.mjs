import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import * as THREE from 'three';
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS);
const doc = await io.read(process.argv[2]); const deg = +process.argv[4];
const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0), deg*Math.PI/180);
for (const n of doc.getRoot().listNodes()) if (n.getMesh()) { const r = new THREE.Quaternion().fromArray(n.getRotation()).premultiply(q); n.setRotation(r.toArray()); }
await io.write(process.argv[3], doc); console.log('rotated', deg);
