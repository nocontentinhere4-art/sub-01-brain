"""No meaningless dots on the brain pages (#88 follow-up, the owner: "Si vedono ancora pallini che non capisco perché
esistano"). Every disc, sprite or point layer that draws on /brain, the room's mini brain (/brain?mini), the Neurons
panel (/brain, /life) or the close-ups must be listed here with the reason it exists; a new one fails this test until
it is either removed or documented.

Removed in this change: the forest's soma discs (THREE.Points: now a solid soma body at the base of each cell's own
tree, web/neurons3d.js), the region glow sprites (now the region's own patch of the cortex surface, web/index.html),
the fibres' travelling white beads (now the fibre itself brightening along its length), the axon's travelling bead
(now the axon lit from the soma to the front), the Neurons panel's spike-dot raster (now a heatmap of the measured
rate of each region, web/neurons.js), its live LED and its curve's end marker. Fibre end points (fibres_ends.bin)
were never drawn: the file only says which two regions each fibre joins."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ["web/index.html", "web/neurons3d.js", "web/neurons.js", "web/neurons.css", "web/life.html",
         *sorted(str(p.relative_to(ROOT)) for p in (ROOT / "web" / "neuron_render").glob("*.js"))]
# a layer that draws discs, sprites or points, one match per layer (shader internals like gl_PointSize are not layers)
LAYER = re.compile(r"new THREE\.Points\(|new THREE\.Sprite\(|\.arc\(|createElementNS\([^)]*\"circle\"|border-radius:\s*50%")
# each such layer needs its reason: a `dot-ok: <why>` comment on its line or the 3 lines above, or an entry here,
# keyed by (file, the layer's .name on the same line). Keep the reasons short and true.
ALLOWED = {
    ("web/neuron_render/neuron_render.js", "nr-tissue"):
        "#88/#99 A's close-up: the out-of-focus tissue around the hero cells, drawn as oriented neurite streaks; its "
        "'counterstain' blobs are flagged to A for removal",
}


def layers():
    for f in FILES:
        p = ROOT / f
        if not p.exists():
            continue
        lines = p.read_text().splitlines()
        for i, ln in enumerate(lines):
            if LAYER.search(ln):
                name = re.search(r"\.name\s*=\s*\"([^\"]+)\"", ln)
                yield f, i + 1, (name.group(1) if name else None), "\n".join(lines[max(0, i - 3):i + 1])


def test_every_dot_layer_has_a_reason():
    unexplained = []
    for f, line, name, ctx in layers():
        why = re.search(r"dot-ok:\s*(.{20,})", ctx)
        if not why and (f, name) not in ALLOWED:
            unexplained.append(f"{f}:{line}" + (f" ({name})" if name else ""))
    assert not unexplained, f"dot-like layers without a documented reason (add `dot-ok: why` or remove them): {unexplained}"


def test_the_removed_dots_stay_removed():
    js = (ROOT / "web" / "neurons3d.js").read_text()
    html = (ROOT / "web" / "index.html").read_text()
    panel = (ROOT / "web" / "neurons.js").read_text()
    assert "forest-somata" in js and "new THREE.Mesh(sg, smat)" in js            # the soma is a body, not a disc
    assert "glowTex" not in html and "glows" not in html                          # no region balls
    assert "vec3(0.55, 0.92, 1.0) * (pk * 30.0" not in html                       # no white beads along the fibres
    assert "col *= 1.0 + 2.5 * pk + 1.5 * trail" in html
    assert "step(aDist, front) * exp(-(front - aDist) / uTrail)" in js           # the axon lights soma -> front
    assert "ctx.fillRect((t - tMin) * sx" not in panel and "createImageData(HEAT_N, rows)" in panel   # a rate map
    assert "nx-dot" not in panel and "nx-dot" not in (ROOT / "web" / "neurons.css").read_text()
