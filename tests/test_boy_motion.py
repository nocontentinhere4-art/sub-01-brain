"""The character's motion layer (#98 G3): the ARDY clips (web/room/boy_m_*.glb) load, every animated node is a bone of
boy.glb, no value is NaN, no foot or toe goes under the floor (forward kinematics on the rig's rest pose, in Python,
from the GLB JSON and its float / int16 accessors: the clips carry no meshopt), each file stays small, the manifest
matches the files, the module and its one hook block in room.html are in place, and the licences are recorded."""
import json
import math
import re
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "room"
MANIFEST = WEB / "boy_m_manifest.json"
MAX_BYTES = 150 * 1024
FLOOR_TOL = 0.012                     # m: the sole may sink this far (a toe joint sits 2 cm above the sole; the page's planted feet add their own IK)
COMP = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
SIZE = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def glb(path):
    data = path.read_bytes()
    magic, version, length = struct.unpack_from("<4sII", data, 0)
    assert magic == b"glTF" and version == 2 and length == len(data), path
    n, kind = struct.unpack_from("<I4s", data, 12)
    assert kind == b"JSON"
    j = json.loads(data[20:20 + n])
    off = 20 + n
    m, kind = struct.unpack_from("<I4s", data, off)
    assert kind == b"BIN\x00"
    return j, data[off + 8:off + 8 + m]


def accessor(j, bin_, i):
    a = j["accessors"][i]
    bv = j["bufferViews"][a["bufferView"]]
    fmt, size = COMP[a["componentType"]]
    k = SIZE[a["type"]]
    stride = bv.get("byteStride") or size * k
    start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    out = []
    for n in range(a["count"]):
        v = list(struct.unpack_from("<" + fmt * k, bin_, start + n * stride))
        if a.get("normalized"):
            lim = {"b": 127, "h": 32767, "B": 255, "H": 65535}[fmt]
            v = [max(-1.0, x / lim) for x in v]
        out.append(v)
    return out


def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def qrot(q, v):
    x, y, z, w = q
    qv = (x, y, z)
    uv = (y * v[2] - z * v[1], z * v[0] - x * v[2], x * v[1] - y * v[0])
    uuv = (y * uv[2] - z * uv[1], z * uv[0] - x * uv[2], x * uv[1] - y * uv[0])
    return tuple(v[i] + 2 * (w * uv[i] + uuv[i]) for i in range(3))


@pytest.fixture(scope="module")
def rig():
    j, _ = glb(WEB / "boy.glb")
    nodes = j["nodes"]
    parent = {}
    for i, n in enumerate(nodes):
        for c in n.get("children", []):
            parent[c] = i
    return {"nodes": nodes, "parent": parent, "by_name": {n.get("name"): i for i, n in enumerate(nodes)}}


@pytest.fixture(scope="module")
def manifest():
    if not MANIFEST.exists():
        pytest.skip("no ARDY clips built yet (room_build/ardy_to_boy.mjs)")
    return json.loads(MANIFEST.read_text())


def clip_files(manifest):
    return [(name, WEB / info["file"]) for name, info in manifest["clips"].items()]


def test_manifest_matches_files(manifest):
    assert manifest["clips"], "empty manifest"
    for name, f in clip_files(manifest):
        assert f.exists(), f
        assert f.stat().st_size <= MAX_BYTES, (name, f.stat().st_size)
        assert f.name == f"boy_m_{name}.glb"
    for f in WEB.glob("boy_m_*.glb"):
        assert f.name[6:-4] in manifest["clips"], f"{f.name} is not in the manifest"


def world_rest(rig, i, local_q=None, hips_t=None):
    """World rotation and position (m) of node i on the rest pose with per-node local quaternions / Hips translation."""
    n = rig["nodes"][i]
    q = tuple((local_q or {}).get(i) or n.get("rotation", [0, 0, 0, 1]))
    t = tuple(hips_t if (hips_t is not None and n.get("name") == "Hips") else n.get("translation", [0, 0, 0]))
    s = n.get("scale", [1, 1, 1])[0]
    p = rig["parent"].get(i)
    if p is None:
        return q, t, s
    pq, pt, ps = world_rest(rig, p, local_q, hips_t)
    wq = qmul(pq, q)
    wp = tuple(pt[k] + v for k, v in enumerate(qrot(pq, tuple(x * ps for x in t))))
    return wq, wp, ps * s


def test_clips_bind_to_the_rig_without_nan_and_keep_their_feet_on_the_floor(rig, manifest):
    bone_names = {n.get("name") for n in rig["nodes"]}
    feet = ["LeftFoot", "RightFoot", "LeftToeBase", "RightToeBase"]
    rest_h = {b: world_rest(rig, rig["by_name"][b])[1][1] for b in feet}      # the rest pose stands on y = 0
    for name, f in clip_files(manifest):
        j, bin_ = glb(f)
        assert j.get("animations"), name
        anim = j["animations"][0]
        tracks = {}                                     # (bone, path) -> (times, values); each track has its own keys
        for ch in anim["channels"]:
            node = j["nodes"][ch["target"]["node"]]
            assert node.get("name") in bone_names, (name, node.get("name"))
            s = anim["samplers"][ch["sampler"]]
            vals = accessor(j, bin_, s["output"])
            assert all(math.isfinite(x) for v in vals for x in v), (name, node.get("name"))
            if ch["target"]["path"] == "rotation":
                for v in vals:
                    assert abs(math.sqrt(sum(x * x for x in v)) - 1) < 0.02, (name, node.get("name"))
            else:
                assert ch["target"]["path"] == "translation" and node.get("name") == "Hips", (name, node.get("name"))
            t = [x[0] for x in accessor(j, bin_, s["input"])]
            assert all(math.isfinite(x) for x in t) and all(t[k] < t[k + 1] for k in range(len(t) - 1)), name
            assert len(t) == len(vals), name
            tracks[(node.get("name"), ch["target"]["path"])] = (t, vals)
        assert ("Hips", "rotation") in tracks and ("Hips", "translation") in tracks, name
        end = max(t[-1] for t, _ in tracks.values())
        assert end > 0.5 and abs(end - manifest["clips"][name]["duration"]) < 0.06, name

        def at(track, time):                            # linear interpolation on the track's own keys (as the mixer does)
            t, v = track
            if time <= t[0]:
                return v[0]
            if time >= t[-1]:
                return v[-1]
            k = max(i for i in range(len(t)) if t[i] <= time)
            u = (time - t[k]) / (t[k + 1] - t[k])
            out = [a + (b - a) * u for a, b in zip(v[k], v[k + 1])]
            if len(out) == 4:
                n = math.sqrt(sum(x * x for x in out)) or 1
                out = [x / n for x in out]
            return out
        # forward kinematics at 20 fps: every foot and toe at or above its rest height over the floor (y = 0)
        lowest = 9.0
        n_frames = int(end * 20) + 1
        for k in range(n_frames):
            time = min(end, k / 20)
            local_q = {rig["by_name"][b]: at(tr, time) for (b, path), tr in tracks.items() if path == "rotation"}
            hips_t = at(tracks[("Hips", "translation")], time)
            for b in feet:
                y = world_rest(rig, rig["by_name"][b], local_q, hips_t)[1][1]
                lowest = min(lowest, y - rest_h[b])
        assert lowest > -FLOOR_TOL, (name, lowest)


def test_module_and_its_single_hook():
    html = (ROOT / "web" / "room.html").read_text()
    js = (WEB / "boy_motion.js").read_text()
    assert html.count("#98 G3") == 2 and html.count('import("./room/boy_motion.js")') == 1   # one marked block, one import
    block = html[html.index("// ===== #98 G3"):html.index("// ===== end #98 G3")]
    assert "animate = dt =>" in block and "setCurrent" in block and "touch" in block
    for name in ("movesDone", "HIPS0", "stride0", "setStride"):      # #76's clips go in first; ?motion=old gets the first ones back
        assert name in block, name
    for name in ("createMotion", "breathe(", "weightShift(", "feet(", "hands(", "bowl(", "eyes(", "smoothBones("):
        assert name in js, name
    # the per-activity clip choice is one explicit table, overridable with ?motion=ardy|ual|old (per slot too)
    table = js[js.index("export const CHOICE = {"):js.index("}", js.index("export const CHOICE = {"))]
    # the defaults the coordinator picked from docs/screens/motion/sheet_1280.jpg (#114 review)
    for slot, src in {"desk": "ual", "eating": "ual", "standing": "ardy", "walk": "ardy", "window": "ardy"}.items():
        assert f"{slot}: \"{src}\"" in table, (slot, table)
    assert "export function choices(" in js and "?motion=ardy|ual|old" in js
    assert "env.touch(" in js                                                    # every bone it moves is registered
    for word in ("he feels", "he understands", "conscious"):
        assert word not in js.lower()


def test_licences_recorded():
    credits = (WEB / "CREDITS.md").read_text()
    for s in ("ARDY", "Apache-2.0", "NVIDIA Open Model", "Llama 3", "boy_m_"):
        assert s in credits, s
    assert "Mixamo" not in credits.replace("No Mixamo", "")
    job = (ROOT / "room_build" / "ardy" / "job.sh").read_text()
    assert "hf auth login" not in job and not re.search(r"hf_[A-Za-z0-9]{20,}", job)     # no token anywhere
