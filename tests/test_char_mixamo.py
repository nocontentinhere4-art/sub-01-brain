"""room.html?char=mixamo: every clip boy_mh.js asks for under room/mh_mx/ is in the repository (a missing one is a 404
in the page: boy_mh.js never starts and the character stands in the void, G23's round 3), each is a clip on
char_mixamo.glb's own skeleton, and the page switch is in place."""
import json, re, struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "room"


def glb_json(p):
    b = p.read_bytes(); n = struct.unpack_from("<I", b, 12)[0]
    return json.loads(b[20:20 + n])


def clip_names():
    """boy_mh.js's CLIPS, with char_mixamo.js ROOM.clips over them."""
    js = (WEB / "boy_mh.js").read_text()
    m = re.search(r"const CLIPS = \{(.*?)\};", js, re.S)
    clips = dict(re.findall(r'(\w+): "([\w.-]+)"', m.group(1)))
    mx = (WEB / "char_mixamo.js").read_text()
    m = re.search(r"clips: \{(.*?)\}", mx, re.S)
    clips.update(dict(re.findall(r'(\w+): "([\w.-]+)"', m.group(1))))
    return clips


def test_every_clip_the_page_asks_for_is_there():
    missing = [f for f in clip_names().values() if not (WEB / "mh_mx" / f"{f}.glb").exists()]
    assert not missing, missing


def test_the_clips_play_on_the_mixamo_skeleton():
    bones = {n["name"] for n in glb_json(WEB / "char_mixamo.glb")["nodes"] if n.get("name", "").startswith("mixamorig:")}
    assert len(bones) == 65
    for f in sorted(set(clip_names().values())):
        g = glb_json(WEB / "mh_mx" / f"{f}.glb")
        assert g.get("animations"), f
        targets = {g["nodes"][c["target"]["node"]]["name"] for c in g["animations"][0]["channels"]}
        assert "mixamorig:Hips" in targets and targets <= bones, f


def test_the_page_switch():
    html = (ROOT / "web" / "room.html").read_text()
    assert 'CHAR_MX ? load("room/char_mixamo.glb") : load("room/char_v5.glb")' in html
    assert 'clipDir: "room/mh_mx"' in html and "V5.m.ROOM" in html
