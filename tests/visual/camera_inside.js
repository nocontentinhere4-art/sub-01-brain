// The camera never looks into anything (preview/camera-clip): a view is rendered once more with every surface two-sided,
// front faces near-black and back faces red, and the red pixels counted. A back face in view is a view into a shell:
// the inside of his clothes, of the chair, the desk, the monitor. Surfaces meant to be seen from inside do not count
// (two-sided materials, and his drawn inside, *_inside). Run by tests/visual/test_camera_inside.py: the page's own
// camera, put where a visitor could put it, after the page's own clearance (keepClear), 320 x 200.
(() => {
  const vs = `#include <common>
#include <skinning_pars_vertex>
void main(){
#include <skinbase_vertex>
#include <begin_vertex>
#include <skinning_vertex>
#include <project_vertex>
}`;
  const mk = ok => new THREE.ShaderMaterial({side: THREE.DoubleSide, vertexShader: vs, fragmentShader: ok
    ? `void main(){ gl_FragColor = vec4(0.05, 0.05, 0.05, 1.0); }`
    : `void main(){ gl_FragColor = gl_FrontFacing ? vec4(0.05, 0.05, 0.05, 1.0) : vec4(1.0, 0.0, 0.0, 1.0); }`});
  const BAD = mk(false), OK = mk(true);
  function backFaces() {
    const insides = new Set(), hidden = [], keep = [];
    scene.traverse(x => { if (x.isMesh && /_inside$/.test(x.name)) insides.add(x.name.replace(/_inside$/, "")); });
    scene.traverse(x => { if (x.isMesh && /_inside$/.test(x.name)) { Object.defineProperty(x, "visible", {value: false, writable: true, configurable: true}); hidden.push(x); } });
    scene.traverse(x => { if (x.isMesh && !/_inside$/.test(x.name)) { keep.push([x, x.material]);
      const two = insides.has(x.name) || [].concat(x.material).some(m => m && m.side === THREE.DoubleSide); x.material = two ? OK : BAD; } });
    const bg = scene.background; scene.background = new THREE.Color(0, 0, 0);
    const rt = new THREE.WebGLRenderTarget(320, 200); renderer.setRenderTarget(rt); renderer.render(scene, camera); renderer.setRenderTarget(null);
    const px = new Uint8Array(320 * 200 * 4); renderer.readRenderTargetPixels(rt, 0, 0, 320, 200, px);
    let red = 0; for (let i = 0; i < px.length; i += 4) if (px[i] > 200 && px[i + 1] < 40) red++;
    for (const [x, m] of keep) x.material = m; for (const x of hidden) delete x.visible; scene.background = bg; rt.dispose();
    return red;
  }
  // put the camera where a visitor could (around the page's target, or a given spot), let the page clear it, count
  window.__cameraInside = o => {
    window.FREEZE = true;
    const t = o.tgt ? new THREE.Vector3(...o.tgt) : new THREE.Vector3(...SURF.monitor.c);
    const p = o.pos ? new THREE.Vector3(...o.pos) : new THREE.Vector3().setFromSpherical(new THREE.Spherical(o.r, o.pol, o.az)).add(t);
    camera.position.copy(p); controls.target.copy(t); controls.update(); window.__keepClear(); camera.updateMatrixWorld(true);
    return {cam: camera.position.toArray().map(v => +v.toFixed(3)), red: backFaces()};
  };
})();
