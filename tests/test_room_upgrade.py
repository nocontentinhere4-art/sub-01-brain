"""The room upgrade on the live character (preview/room-upgrade-live): the owner's Tripo chair, the picked props and the
sneakers, the clothes taken out."""
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "room.html").read_text()


def glb(name):
    data = (ROOT / "web" / "room" / name).read_bytes()
    n = struct.unpack_from("<I", data, 12)[0]
    return data, json.loads(data[20:20 + n])


def tris(j):
    return sum(j["accessors"][p["indices"]]["count"] // 3 for m in j["meshes"] for p in m["primitives"])


def test_owner_chair_at_the_live_seat_height():
    data, j = glb("chair_owner.glb")                                              # (the owner's Tripo chair, repaired)
    assert len(data) <= 1536 * 1024 and 0 < tris(j) <= 60000
    assert {m["name"] for m in j["materials"]} == {"chair_mesh", "chair_fabric", "chair_plastic", "chair_armpad", "chair_lift", "chair_base", "chair_caster"}
    node = next(nd for nd in j["nodes"] if nd.get("name") == "chair_owner")
    assert node["extras"]["seatTop"] == 0.505 and node["extras"]["back"] == 0.05     # (the live character's seat height)
    acc = [j["accessors"][p["attributes"]["POSITION"]] for p in j["meshes"][0]["primitives"]]
    k = 32767 if acc[0].get("normalized") else 1                                  # (quantised: int16, the node's scale undoes it)
    s, t = node.get("scale", [1, 1, 1])[1], node.get("translation", [0, 0, 0])[1]
    lo, hi = min(a["min"][1] for a in acc) / k * s + t, max(a["max"][1] for a in acc) / k * s + t
    assert abs(lo) < 0.01 and 1.2 <= hi <= 1.3, (lo, hi)                          # (on the floor, 1.2-1.3 m tall)
    assert 'load("room/chair_owner.glb")' in HTML and 'getObjectByName("chair_owner")' in HTML


def test_picked_props_only_the_approved_ones():
    data, j = glb("props_picked.glb")
    mats = {m["name"] for m in j["materials"]}
    assert mats <= {"wicker_basket_02", "wooden_bowl_02", "brass", "leather", "connector", "binder_notebook", "stationery_supplies"}
    assert {"wicker_basket_02", "wooden_bowl_02", "binder_notebook", "stationery_supplies"} <= mats
    assert len(data) <= 2 * 1024 * 1024 and 'load("room/props_picked.glb")' in HTML


def test_sneakers_by_the_door():
    data, j = glb("sneakers_door.glb")
    assert {m["name"] for m in j["materials"]} == {"painted", "jersey"} and 0 < tris(j) <= 8000
    assert 'load("room/sneakers_door.glb")' in HTML


def test_rejected_clothes_taken_out():
    for m in ("hang_hoodie", "hang_rib", "denim", "cushion", "jersey"):
        assert f'"{m}"' in HTML.split("const UPGRADE_DROP", 1)[1].split("\n\n", 1)[0]
