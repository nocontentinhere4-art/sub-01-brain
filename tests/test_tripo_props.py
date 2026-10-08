"""The Tripo props (web/room/props_tripo.glb, room_build/build_tripo.mjs): four nodes the page reads, each under 5k
triangles, WebP textures of at most 1024 px, meshopt-compressed, a small file, and credited in CREDITS.md. Reads only
the GLB's JSON chunk and the WebP headers."""
import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GLB = ROOT / "web" / "room" / "props_tripo.glb"
PROPS = ("ramen", "mug", "headphones", "sneakers")


def chunks():
    data = GLB.read_bytes()
    magic, version, length = struct.unpack_from("<4sII", data, 0)
    assert magic == b"glTF" and version == 2 and length == len(data)
    n, kind = struct.unpack_from("<I4s", data, 12)
    assert kind == b"JSON"
    j = json.loads(data[20:20 + n])
    m, kind = struct.unpack_from("<I4s", data, 20 + n)
    assert kind == b"BIN\x00"
    return j, data[28 + n:28 + n + m]


def test_size_budget():
    assert GLB.stat().st_size <= 1024 * 1024


def test_nodes_the_page_reads():
    j, _ = chunks()
    names = [j["nodes"][i]["name"] for i in j["scenes"][0]["nodes"]]
    assert names == [f"T_{p}" for p in PROPS]
    html = (ROOT / "web" / "room.html").read_text()
    assert 'load("room/props_tripo.glb")' in html
    for p in PROPS:
        assert f"T.{p}" in html, p


def test_triangles_per_prop():
    j, _ = chunks()
    for i in j["scenes"][0]["nodes"]:
        tris, todo = 0, [i]
        while todo:
            nd = j["nodes"][todo.pop()]
            todo += nd.get("children", [])
            if "mesh" in nd:
                tris += sum(j["accessors"][p["indices"]]["count"] // 3 for p in j["meshes"][nd["mesh"]]["primitives"])
        assert 0 < tris <= 5000, (j["nodes"][i]["name"], tris)


def test_webp_textures_at_most_1024_and_meshopt():
    j, binary = chunks()
    assert "EXT_meshopt_compression" in j["extensionsRequired"]
    assert j["images"]
    for im in j["images"]:
        assert im["mimeType"] == "image/webp"
        bv = j["bufferViews"][im["bufferView"]]
        b = binary[bv.get("byteOffset", 0):bv.get("byteOffset", 0) + bv["byteLength"]]
        assert b[:4] == b"RIFF" and b[8:12] == b"WEBP"
        if b[12:16] == b"VP8 ":
            w, h = struct.unpack_from("<HH", b, 26); w, h = w & 0x3FFF, h & 0x3FFF
        elif b[12:16] == b"VP8L":
            v = int.from_bytes(b[21:25], "little"); w, h = (v & 0x3FFF) + 1, ((v >> 14) & 0x3FFF) + 1
        else:                                                     # VP8X
            w, h = int.from_bytes(b[24:27], "little") + 1, int.from_bytes(b[27:30], "little") + 1
        assert w <= 1024 and h <= 1024, (w, h)


def test_credited_as_tripo_paid_api():
    credits = (ROOT / "web" / "room" / "CREDITS.md").read_text()
    sec = credits.split("## The Tripo props", 1)[1].split("\n## ", 1)[0]
    assert "props_tripo.glb" in sec and "made with Tripo (paid API)" in sec
    assert len(re.findall(r"`[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}`", sec)) == 4   # one task id per prop
