"""Issue #76: better motion for the first character (web/room/boy_moves.glb on boy.glb's rig) and its skin check.

Reads only the GLB's JSON chunk, so it needs no 3D library: meshopt-compressed buffers still carry their accessors'
counts and the channels their target nodes.
"""
import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROOM = ROOT / "web" / "room"
MOVES = ROOM / "boy_moves.glb"
DEFORM = ROOT / "docs" / "motion" / "deform_check.json"
MB = 1024 * 1024


def glb_json(path):
    raw = path.read_bytes()
    magic, _version, _length = struct.unpack_from("<4sII", raw, 0)
    assert magic == b"glTF", path
    n, kind = struct.unpack_from("<I4s", raw, 12)
    assert kind == b"JSON"
    return json.loads(raw[20:20 + n])


def anim_names(path):
    return [a.get("name") for a in glb_json(path).get("animations", [])]


def room_moves():
    """The clip each room slot takes from boy_moves.glb (room.html's MOVE table)."""
    html = (ROOT / "web" / "room.html").read_text()
    m = re.search(r"const MOVE = \{([^}]*)\}", html)
    assert m, "room.html has no MOVE table"
    return dict(re.findall(r'(\w+):"(\w+)"', m.group(1)))


def test_moves_play_on_the_first_rig():
    assert MOVES.stat().st_size <= 1.5 * MB
    old = glb_json(ROOM / "boy.glb")
    bones = {old["nodes"][j]["name"] for j in old["skins"][0]["joints"]}
    if "metacarpal1.L" in bones:                       # preview/room-mh: boy.glb is the MakeHuman rig, which room/boy_mh.js
        import pytest                                  # drives with its own clips; these #76 clips are for the first rig
        pytest.skip("boy.glb is the MakeHuman rig on this preview branch; #76's clips belong to the first rig")
    js = glb_json(MOVES)
    for a in js["animations"]:
        rot = set()
        for ch in a["channels"]:
            name, path = js["nodes"][ch["target"]["node"]]["name"], ch["target"]["path"]
            assert name in bones, (a["name"], name)
            assert path in ("rotation", "translation"), (a["name"], path)
            if path == "rotation":
                rot.add(name)
            else:
                assert name == "Hips", (a["name"], name)
        # every bone of the rig but the head's end markers (not skinned) is keyed: nothing is left to the old clip
        assert rot >= bones - {"head_end", "headfront"}, (a["name"], bones - rot)


def test_moves_has_the_clip_list():
    names = anim_names(MOVES)
    for n in ["stand_idle", "walk", "walk_start", "walk_stop", "sit_down_chair", "stand_up_chair", "sit_idle_upright",
              "type", "mouse", "sit_eat_chopsticks", "sit_drink", "sit_lean_back", "lie_back_idle", "lie_side_left",
              "lie_side_right", "sleep_breathing", "lie_phone", "roll_back_to_side_L", "roll_back_to_side_R",
              "sit_down_bed_edge", "stand_up_bed_edge", "sit_edge_idle", "lie_down_from_edge", "get_up_to_edge",
              "door_open_pull", "take_item", "put_down", "crouch_drop", "lean_on_sill", "stretch_arms_up",
              "scratch_head", "look_around", "turn_in_place_L90", "turn_in_place_R90"]:
        assert n in names, n
    assert not any(n.startswith("boy_m_") for n in names)       # #98's generated clips keep their own names


def test_room_takes_its_clips_from_moves():
    moves = room_moves()
    assert set(moves) == {"walk", "sit", "phone_lie"}             # sleep stays with #63's bed work; eating keeps the first sit
    assert set(moves.values()) <= set(anim_names(MOVES))
    html = (ROOT / "web" / "room.html").read_text()
    assert 'load("room/boy_moves.glb")' in html and 'get("moves") !== "old"' in html


def test_deform_check_covers_every_clip():
    report = json.loads(DEFORM.read_text())
    checked = {(c["file"], c["clip"]) for c in report["clips"]}
    assert {("boy_moves.glb", n) for n in anim_names(MOVES)} <= checked
    for f in ["boy.glb", "boy_door.glb", "boy_eat.glb", "boy_idle.glb", "boy_sleep.glb", "boy_text.glb", "boy_walk.glb"]:
        assert {("%s" % f, n) for n in anim_names(ROOM / f)} <= checked, f


def test_room_clips_are_no_worse_than_the_first_ones():
    """On boy.glb's own skin: the new clips the room plays swell his skin and clothes off the bones no more than the
    clips he plays today (per region: legs, arms, trunk), and no forearm or hand goes into his torso."""
    report = json.loads(DEFORM.read_text())
    first = [c for c in report["clips"] if c["file"] != "boy_moves.glb"]
    worst = {k: max(c[k] for c in first) for k in ("bulge_legs_cm", "bulge_arms_cm", "bulge_trunk_cm")}
    used = set(room_moves().values())
    for c in report["clips"]:
        if c["file"] == "boy_moves.glb" and c["clip"] in used:
            for k, limit in worst.items():
                assert c[k] <= limit, (c["clip"], k, c[k], limit, c["bulge_at"])
            assert c["torso_cm"] <= 1.0, (c["clip"], c["torso_cm"], c["torso_at"])
