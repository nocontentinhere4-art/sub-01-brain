"""The bottle of green tea (web/room/bottle.glb, room_build/build_bottle.mjs): one node T_bottle, one material with WebP
maps, meshopt-compressed, a couple of thousand triangles, not metal, and fitted to the place web/room.html and
room_build/build_room.py already keep for it - origin at the prop's, base 0.08 m under it, long axis +y, radius 3.2 cm,
inside the collision box reserved at BOTTLE_AT. Reads only the GLB's JSON chunk (quantized positions: the accessor's
min/max through the node's scale and translation) and the WebP headers."""
import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GLB = ROOT / "web" / "room" / "bottle.glb"
BASE_BELOW = 0.080            # room.html: PROP.bottle sits at BOTTLE_AT + (0, 0.08, 0), so its base is on the desk top
RADIUS = 0.032                # build_room.py KEEP["the tea bottle's spot"]: "r 3.2 cm"
BOX_H = 0.30                  # that box is DTOP+0.004 .. DTOP+0.30 tall and 8 cm square


def gltf():
    data = GLB.read_bytes()
    magic, version, length = struct.unpack_from("<4sII", data, 0)
    assert magic == b"glTF" and version == 2 and length == len(data)
    n, kind = struct.unpack_from("<I4s", data, 12)
    assert kind == b"JSON"
    j = json.loads(data[20:20 + n])
    m, kind = struct.unpack_from("<I4s", data, 20 + n)
    assert kind == b"BIN\x00"
    return j, data[28 + n:28 + n + m]


def bounds(j):
    """the mesh's world box: the quantized POSITION accessor through its node's scale and translation"""
    node = next(n for n in j["nodes"] if "mesh" in n)
    prim = j["meshes"][node["mesh"]]["primitives"][0]
    acc = j["accessors"][prim["attributes"]["POSITION"]]
    assert acc["componentType"] == 5122 and acc.get("normalized"), acc        # SHORT, normalized by quantize()
    s, t = node.get("scale", [1, 1, 1]), node.get("translation", [0, 0, 0])
    lo = [acc["min"][a] / 32767 * s[a] + t[a] for a in range(3)]
    hi = [acc["max"][a] / 32767 * s[a] + t[a] for a in range(3)]
    return lo, hi


def test_size_and_triangles():
    assert GLB.stat().st_size <= 256 * 1024, GLB.stat().st_size
    j, _ = gltf()
    tris = sum(j["accessors"][p["indices"]]["count"] // 3 for m in j["meshes"] for p in m["primitives"])
    assert 0 < tris <= 2500, tris                                             # a couple of thousand, like the other props


def test_one_node_one_material_webp_meshopt():
    j, binary = gltf()
    assert "T_bottle" in {n.get("name") for n in j["nodes"]}
    assert len(j["materials"]) == 1
    assert sum(len(m["primitives"]) for m in j["meshes"]) == 1                # one draw call, where the four cylinders were
    assert "EXT_meshopt_compression" in j["extensionsRequired"]
    assert len(j["images"]) == 3                                             # colour, normal, metal/roughness
    for im in j["images"]:
        assert im["mimeType"] == "image/webp"
        bv = j["bufferViews"][im["bufferView"]]
        b = binary[bv.get("byteOffset", 0):bv.get("byteOffset", 0) + bv["byteLength"]]
        assert b[:4] == b"RIFF" and b[8:12] == b"WEBP"


def test_a_pet_bottle_is_not_metal():
    # Tripo bakes a metal look into its ORM map; build_bottle.mjs takes the factor to 0
    j, _ = gltf()
    assert j["materials"][0]["pbrMetallicRoughness"]["metallicFactor"] == 0


def test_it_stands_where_the_page_holds_the_prop():
    j, _ = gltf()
    lo, hi = bounds(j)
    assert abs(lo[1] + BASE_BELOW) <= 0.001, lo                              # the base exactly 0.08 m under the origin
    assert hi[1] > 0, hi                                                      # cap up, long axis +y
    assert (hi[1] - lo[1]) <= BOX_H, hi[1] - lo[1]
    for a in (0, 2):                                                          # centred on the axis, radius near 3.2 cm
        assert abs(lo[a] + hi[a]) <= 0.002, (a, lo, hi)
        assert abs(hi[a] - RADIUS) <= 0.002, (a, hi[a])
    assert (hi[1] - lo[1]) > 2 * hi[0], "it should be taller than it is wide"


def test_it_fits_the_box_build_room_reserves():
    src = (ROOT / "room_build" / "build_room.py").read_text()
    row = next(l for l in src.splitlines() if '"the tea bottle\'s spot"' in l).split("#", 1)[0]
    pairs = [(float(a), float(b)) for a, b in re.findall(r"\((-?\d+\.\d+), (-?\d+\.\d+)\)", row)]
    (x0, x1), (z0, z1) = pairs                        # the y range is written in terms of DTOP, so only x and z match
    at_x, at_z = (x0 + x1) / 2, (z0 + z1) / 2         # BOTTLE_AT, the middle of the reserved square
    lo, hi = bounds(gltf()[0])
    assert at_x + lo[0] >= x0 and at_x + hi[0] <= x1, (x0, x1, lo[0], hi[0])
    assert at_z + lo[2] >= z0 and at_z + hi[2] <= z1, (z0, z1, lo[2], hi[2])


def test_the_page_puts_it_in_the_prop_group():
    html = (ROOT / "web" / "room.html").read_text()
    assert 'load("room/bottle.glb")' in html and 'getObjectByName("T_bottle")' in html
    assert 'get("bottle") !== "old"' in html                                  # ?bottle=old keeps the modelled one
    assert 'bo.name = "tea_bottle"' in html                                   # the name the contact probe looks for
    assert "PROP.bottle" in html and "function tripoBottle()" in html


def test_credited_with_its_task_id_and_a_cc0_reference():
    credits = (ROOT / "web" / "room" / "CREDITS.md").read_text()
    sec = credits.split("## The bottle of green tea", 1)[1].split("\n## ", 1)[0]
    assert "bottle.glb" in sec and "made with Tripo (paid API)" in sec
    used = sec.split("Generated and not used", 1)[0]
    assert len(re.findall(r"`[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}`", used)) == 1
    assert "CC0" in sec and "commons.wikimedia.org" in sec                    # the reference photograph, credited
    assert (ROOT / "docs" / "design" / "prop-bottle" / "README.md").exists()
