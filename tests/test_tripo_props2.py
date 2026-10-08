"""The second batch of Tripo props (web/room/props_tripo2.glb, room_build/build_tripo2.mjs): one joined mesh plus the desk
lamp, one atlas material with WebP maps, meshopt-compressed, under 5k triangles a prop, the list of props it holds in its
scene's extras, the page's replace table covering them, a row per prop in CREDITS.md, and the car poster. Reads only the
GLB's JSON chunk and the WebP headers."""
import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GLB = ROOT / "web" / "room" / "props_tripo2.glb"
NEW = {"skateboard", "console", "figure", "cans", "shoeboxes", "camera"}      # added, replacing nothing


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


def props():
    return chunks()[0]["scenes"][0]["extras"]["props"]


def test_size_budget():
    assert GLB.stat().st_size <= 2 * 1024 * 1024


def test_two_draw_calls_one_material():
    j, _ = chunks()
    prims = [p for m in j["meshes"] for p in m["primitives"]]
    assert len(prims) == 2 and len(j["materials"]) == 1
    assert sorted(m.get("name", "") for m in j["meshes"]) == ["", "T2_lamp"]


def test_triangles_under_5k_a_prop():
    j, _ = chunks()
    tris = sum(j["accessors"][p["indices"]]["count"] // 3 for m in j["meshes"] for p in m["primitives"])
    assert 0 < tris <= 5000 * len(props()), tris


def test_webp_atlases_and_meshopt():
    j, binary = chunks()
    assert "EXT_meshopt_compression" in j["extensionsRequired"]
    assert len(j["images"]) == 3
    for im in j["images"]:
        assert im["mimeType"] == "image/webp"
        bv = j["bufferViews"][im["bufferView"]]
        b = binary[bv.get("byteOffset", 0):bv.get("byteOffset", 0) + bv["byteLength"]]
        assert b[:4] == b"RIFF" and b[8:12] == b"WEBP"


def test_page_replaces_what_it_holds():
    html = (ROOT / "web" / "room.html").read_text()
    assert 'load("room/props_tripo2.glb")' in html
    table = html.split("const T2_OLD = {", 1)[1].split("};", 1)[0]
    keys = set(re.findall(r"(\w+):\{(?:hide|cut):", table))
    for p in props():
        assert p in keys or p in NEW, p


def test_credited_with_task_ids():
    credits = (ROOT / "web" / "room" / "CREDITS.md").read_text()
    sec = credits.split("## The Tripo props, second batch", 1)[1].split("\n## ", 1)[0]
    assert "props_tripo2.glb" in sec and "made with Tripo (paid API)" in sec
    used = sec.split("Generated and not used", 1)[0]
    ids = re.findall(r"`[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}`", used)
    files = {p.removesuffix("_l").removesuffix("_r") for p in props()}            # the two speakers are one model
    assert len(ids) == len(files) == len(set(ids)), (len(ids), sorted(files))


def test_car_poster():
    assert (ROOT / "web" / "room" / "poster_car.webp").read_bytes()[8:12] == b"WEBP"
    assert '"room/poster_car.webp"' in (ROOT / "web" / "room.html").read_text()


def test_keyboard_is_the_original_split_into_its_own_node():
    # the tenkeyless keyboard modelled in room_clean.glb stays; the page cuts it out of room_static into a group "keyboard"
    # (G3's hand pinning finds it by name), its origin at the middle of F and J on the desk top
    html = (ROOT / "web" / "room.html").read_text()
    assert "function splitBox(" in html and '), "keyboard");' in html and "const KB_HOME = [" in html
    assert not (ROOT / "web" / "room" / "keyboard.glb").exists() and not (ROOT / "web" / "room" / "keyboard_tripo.glb").exists()
    assert "room/keyboard" not in html


def test_mouse_is_light_and_by_the_keyboard():
    data = (ROOT / "web" / "room" / "mouse.glb").read_bytes()
    assert len(data) <= 1024 * 1024
    n = struct.unpack_from("<I", data, 12)[0]
    j = json.loads(data[20:20 + n])
    assert {"mouse", "mousepad"} <= {nd["name"] for nd in j["nodes"]}
    tris = sum(j["accessors"][p["indices"]]["count"] // 3 for m in j["meshes"] for p in m["primitives"])
    assert 0 < tris <= 20000
    html = (ROOT / "web" / "room.html").read_text()
    assert "load(`room/mouse${KB_SET}.glb`)" in html and "MOUSE_AT = [" in html
    assert "mouse" not in props()                                                  # (the Tripo mouse is left out)


def test_tripo_mouse_for_comparison():
    data = (ROOT / "web" / "room" / "mouse_tripo.glb").read_bytes()                   # (the file carries the pad too)
    assert len(data) <= 1024 * 1024
    n = struct.unpack_from("<I", data, 12)[0]
    j = json.loads(data[20:20 + n])
    tris = sum(j["accessors"][p["indices"]]["count"] // 3 for m in j["meshes"] for p in m["primitives"])
    assert 0 < tris <= 5000 + 100, tris
    assert "mouse" in {nd.get("name") for nd in j["nodes"]}


def test_controller_and_monitor_modelled_in_code():
    html = (ROOT / "web" / "room.html").read_text()
    assert 'load("room/controller.glb")' in html and 'load("room/monitor.glb")' in html and "const CTRL_AT = [" in html
    assert "controller" not in props() and "monitor" not in props()                # (the Tripo ones are left out)
    for f, name, limit in (("controller.glb", "controller", 20000), ("monitor.glb", "monitor", 8000)):
        data = (ROOT / "web" / "room" / f).read_bytes()
        assert len(data) <= 512 * 1024, f
        n = struct.unpack_from("<I", data, 12)[0]
        j = json.loads(data[20:20 + n])
        assert name in {nd.get("name") for nd in j["nodes"]}
        tris = sum(j["accessors"][p["indices"]]["count"] // 3 for m in j["meshes"] for p in m["primitives"])
        assert 0 < tris <= limit, (f, tris)
