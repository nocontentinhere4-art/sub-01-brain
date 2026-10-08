"""The room model (#75): web/room/room_clean.glb stays small, keeps the nodes room.html reads, the lamp marker sits under
a lamp that is clear of the walls, and every Poly Haven asset the build imports is credited. Reads only the GLB's JSON
chunk (the meshes are meshopt-compressed; the full prop sweep runs in the Blender build, room_build/build_room.py)."""
import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GLB = ROOT / "web" / "room" / "room_clean.glb"
IX, IZ = -1.9, -1.45                     # inner faces of the window wall and the back wall (build_room.py)
DTOP = 0.97


def gltf():
    data = GLB.read_bytes()
    magic, version, length = struct.unpack_from("<4sII", data, 0)
    assert magic == b"glTF" and version == 2 and length == len(data)
    n, kind = struct.unpack_from("<I4s", data, 12)
    assert kind == b"JSON"
    return json.loads(data[20:20 + n])


def nodes():
    return {n.get("name"): n for n in gltf()["nodes"]}


def test_size_budget():
    assert GLB.stat().st_size <= 7 * 1024 * 1024


def test_nodes_the_page_reads():
    names = nodes()
    for k in ("chair", "headphones", "hangers", "SURF_monitor", "SURF_window", "SURF_lamp"):
        assert k in names, k
    for k in ("chair", "headphones", "hangers"):
        assert names[k].get("children"), k                        # pivots kept: the mesh is in a child node


def test_lamp_marker_over_the_desk_and_off_the_walls():
    m = nodes()["SURF_lamp"]
    x, y, z = (m["matrix"][12:15] if "matrix" in m else m["translation"])
    assert -1.86 < x < -0.36 and -1.45 < z < -0.80, (x, z)        # over the desk
    assert y > DTOP + 0.1, y
    assert x > IX + 0.01 and z > IZ + 0.01, (x, z)


def test_headphones_hang_on_the_back_wall():
    t = nodes()["headphones"]["translation"]
    assert IZ < t[2] < IZ + 0.1 and 1.2 < t[1] < 1.7


def test_door_hangers_turn_about_the_door_hinge():
    t = nodes()["hangers"]["translation"]                         # room.html's opening leaf pivots at (1.11, F + 0.008, IZ)
    assert abs(t[0] - 1.11) < 1e-3 and abs(t[1] - 0.168) < 1e-3 and abs(t[2] - IZ) < 1e-3, t


def test_no_other_material_is_named_door():
    names = [m.get("name", "") for m in gltf()["materials"]]
    assert sum(n.lower().startswith("door") for n in names) == 1, names   # room.html takes the first "door*" material for its leaf


def test_every_imported_asset_is_credited():
    src = (ROOT / "room_build" / "build_room.py").read_text()
    credits = (ROOT / "web" / "room" / "CREDITS.md").read_text()
    used = set(re.findall(r'import_asset\("([a-z0-9_]+)"', src))
    assert used, "no import_asset calls found"
    for k in used:
        assert f"`{k}`" in credits, k


def test_every_texture_is_credited():
    """every Poly Haven texture tex_prep.py reads (tex/<id>/...) has a row in CREDITS.md"""
    src = (ROOT / "room_build" / "tex_prep.py").read_text()
    credits = (ROOT / "web" / "room" / "CREDITS.md").read_text()
    used = set(re.findall(r'\{T\}/([a-z0-9_]+)/', src))
    assert len(used) >= 14, used
    for k in used:
        assert f"`{k}`" in credits, k


# ---- the soft goods (#98 G4, room_build/props_soft.py)
SOFT_MATERIALS = ["sheet", "duvet", "curtain", "rug", "cushion", "bag", "knit", "terry", "denim", "jersey", "hang_hoodie", "hang_canvas", "hang_rib"]


def triangles(g):
    n = 0
    for m in g["meshes"]:
        for p in m["primitives"]:
            acc = g["accessors"][p["indices"]] if "indices" in p else g["accessors"][p["attributes"]["POSITION"]]
            n += acc["count"] // 3
    return n


def test_soft_goods_materials_present():
    names = {m.get("name") for m in gltf()["materials"]}
    for k in SOFT_MATERIALS:
        assert k in names, k
    assert "room_static" in nodes()


def test_fabrics_have_their_normal_maps_and_sheen():
    g = gltf(); by = {m.get("name"): m for m in g["materials"]}
    for k in ("knit", "terry", "duvet", "curtain", "denim", "hang_hoodie"):
        assert "normalTexture" in by[k], k
    for k in ("knit", "terry", "curtain", "duvet"):
        assert "KHR_materials_sheen" in by[k].get("extensions", {}), k


def test_triangle_and_draw_call_budget():
    """the room page must stay >= 30 FPS on a mid-range phone: the whole model stays under 200k triangles and 60 draw
    calls (docs/research/game_look.md section 4: whole room <= 200k, <= ~80 draw calls; today 178k and 48)"""
    g = gltf()
    prims = sum(len(m["primitives"]) for m in g["meshes"])
    assert prims <= 60, prims
    assert 120_000 <= triangles(g) <= 200_000, triangles(g)


def test_phone_screen_module_has_no_brand_ui():
    code = "\n".join(l for l in (ROOT / "web" / "room_phone.js").read_text().splitlines() if not l.strip().startswith("//"))
    for w in ("iOS", "Android", "Apple", "iPhone", "Google", "Samsung", "Galaxy", "Pixel"):
        assert w not in code, w


# ---------------------------------------------------------------- the hard surfaces (#98 G5, room_build/props_hard.py)
def materials():
    return {m.get("name"): m for m in gltf()["materials"]}


def prims_by_material():
    g = gltf(); names = [m.get("name") for m in g["materials"]]
    out = {}
    for m in g["meshes"]:
        for p in m["primitives"]:
            out.setdefault(names[p["material"]], []).append(p)
    return out


def test_hard_surfaces_are_built_by_props_hard():
    src = (ROOT / "room_build" / "build_room.py").read_text()
    for fn in ("materials", "window", "desk", "chair", "bed_frame", "bookshelf", "fridge", "door", "aircon", "headphones", "fan", "decals", "finish"):
        assert f"props_hard.{fn}(globals())" in src, fn
    assert 'm.get("nouv")' in src                                   # the atlases keep their own UVs through the final projection pass


def test_atlases_and_pbr_textures_are_in_the_glb():
    images = {i.get("name") for i in gltf()["images"]}
    for k in ("keycaps", "spines", "decals", "floor_diff", "floor_nor", "floor_mr", "oak_mr", "plastic_mr", "metal_mr", "white_mr", "wall_mr"):
        assert k in images, k


def test_hard_materials_carry_roughness_variation():
    mats = materials()
    for k in ("floor", "wall", "oak", "door", "white", "plastic_black", "metal_dark", "steel", "alu"):
        assert "metallicRoughnessTexture" in mats[k]["pbrMetallicRoughness"], k
    assert mats["decal"].get("alphaMode") == "BLEND"                 # dust, scuffs and stickers are blended over the surfaces
    for k in ("keycap", "book", "decal"):
        assert "baseColorTexture" in mats[k]["pbrMetallicRoughness"], k


def test_edge_wear_lives_in_the_vertex_colours():
    prims = prims_by_material()
    for k in ("oak", "door", "plastic_black", "white"):               # worn edges: tinted vertex colours on the bevels
        assert any("COLOR_0" in p["attributes"] for p in prims[k]), k
    for k in ("floor", "wall", "cut"):                                # untinted surfaces carry no colour attribute (post.mjs drops all-white ones)
        assert all("COLOR_0" not in p["attributes"] for p in prims[k]), k


def test_keycaps_and_books_have_their_own_uvs():
    prims = prims_by_material()
    for k in ("keycap", "book", "decal", "posters", "pinboard"):
        assert all("TEXCOORD_0" in p["attributes"] for p in prims[k]), k


def test_movable_nodes_do_not_share_the_rooms_ao():
    g = gltf(); names = {n.get("name"): n for n in g["nodes"]}; mats = g["materials"]
    for k in ("headphones", "hangers"):
        child = g["nodes"][names[k]["children"][0]]
        for p in g["meshes"][child["mesh"]]["primitives"]:
            m = mats[p["material"]]
            assert "occlusionTexture" not in m, (k, m.get("name"))  # the room's AO is baked without them: they must not read it
    # the chair reads its own (self-occlusion) map, never the room's
    child = g["nodes"][names["chair"]["children"][0]]
    room_ao = [i for i, im in enumerate(g["images"]) if im.get("name") == "room_ao"]
    for p in g["meshes"][child["mesh"]]["primitives"]:
        occ = mats[p["material"]].get("occlusionTexture")
        if occ and room_ao:
            t = g["textures"][occ["index"]]                                # WebP textures name their image in the extension
            assert t.get("source", t.get("extensions", {}).get("EXT_texture_webp", {}).get("source")) != room_ao[0]


def test_markers_and_pivots_stay_where_the_page_expects():
    n = nodes()
    m = n["SURF_monitor"]; x, y, z = m["translation"]
    assert abs(x + 1.06) < 0.01 and abs(y - 1.33) < 0.005 and abs(z + 1.19) < 0.01, (x, y, z)
    assert abs(m["extras"]["w"] - 0.64) < 1e-6 and abs(m["extras"]["h"] - 0.37) < 1e-6
    w = n["SURF_window"]; assert abs(w["translation"][0] + 2.012) < 1e-3 and abs(w["extras"]["w"] - 1.58) < 1e-3
    c = n["chair"]["translation"]
    assert abs(c[0] + 1.13) < 1e-3 and abs(c[1] - 0.16) < 1e-3 and abs(c[2] + 0.585) < 1e-3, c


def test_floor_texture_is_credited():
    credits = (ROOT / "web" / "room" / "CREDITS.md").read_text()
    for k in ("`wooden_floor_01`", "props_hard.py", "keycap", "spines", "decals", "DejaVu"):
        assert k in credits, k
