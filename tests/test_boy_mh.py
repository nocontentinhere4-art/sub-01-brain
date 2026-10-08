"""preview/room-v5: the v5 character with room-mh's room clips and choreography (room/boy_mh.js). Static checks: the
body (room/char_v5.glb) and the clips retargeted onto it (room/mh_v5/, room-mh's names) are in place, the page's marked
motion block switches to room/boy_mh.js for it (through room/char_v5.js), the module encodes the owner's desk rule
(typing for a search, the mouse otherwise, sitting for videos; 0.4 s crossfades), and the licences are recorded."""
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web" / "room"


def glb_json(path):
    data = path.read_bytes()
    assert data[:4] == b"glTF"
    n = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + n])


CLIPS = ("desk_type_ik", "desk_mouse_ik", "desk_watch", "room_window", "room_walk", "room_sit_down", "room_stand_up",
         "room_bed_lie", "room_bed_wake", "room_eat", "room_read", "room_phone", "room_drink", "room_door", "room_bedtime",
         "room_phone_scroll")
# the Mixamo captures retargeted onto v5 (docs/design/mixamo): one row each in room_build/kimodo/mixamo_clips.json
MIXAMO = tuple(r["out"] for r in json.loads((ROOT / "room_build" / "kimodo" / "mixamo_clips.json").read_text())["clips"].values())


def test_body_is_the_v5_rig():
    g = glb_json(WEB / "char_v5.glb")
    names = {n.get("name") for n in g["nodes"]}
    for bone in ("Root", "Hip", "Spine02", "NeckTwist01", "Head", "L_Hand", "R_Hand", "L_Thigh", "L_Foot", "R_ToeBase"):
        assert bone in names, bone
    assert len(g["skins"][0]["joints"]) >= 41                              # (41; more once G13's fingers are in)


def test_room_clips_retargeted_onto_v5():
    have = sorted(p.stem for p in (WEB / "mh_v5").glob("*.glb"))
    assert set(have) <= set(CLIPS) | set(MIXAMO), set(have) - set(CLIPS) - set(MIXAMO)   # (room-mh's names, 1:1, and the Mixamo rows)
    assert set(CLIPS) <= set(have), set(CLIPS) - set(have)                  # (every required clip is there: boy_mh.js load() throws without one)
    for clip in have:
        g = glb_json(WEB / "mh_v5" / f"{clip}.glb")
        assert g.get("animations"), clip
        ch = g["animations"][0]["channels"]
        targets = {(g["nodes"][c["target"]["node"]]["name"], c["target"]["path"]) for c in ch}
        assert ("Hip", "translation") in targets and ("L_Hand", "rotation") in targets, clip


def test_char_v5_module_maps_to_the_makehuman_names():
    js = (WEB / "char_v5.js").read_text()
    for s in ('Hip: "Hips"', "Thigh`]: `${S}UpLeg`", "Hand`]: `${S}Hand`", "turn.rotation.y = -Math.PI / 2", "sc.attach(hip)", "export function fixClip("):
        assert s in js, s


def test_hook_switches_to_the_module_for_the_makehuman_rig():
    html = (ROOT / "web" / "room.html").read_text()
    assert html.count('import("./room/boy_mh.js")') == 1
    assert 'bones["metacarpal1L"]' in html and '|| V5 ? "mh" : "old"' in html   # (MakeHuman fingers, or v5)
    assert 'load("room/char_v5.glb")' in html and 'clipDir: "room/mh_v5"' in html and "seatUp: 0" in html
    assert "mh.animate(dt)" in html


def _js_function(js, head):
    """The source of one function in the module, from its head to its matching brace."""
    i = js.index(head); j = js.index("{", i); depth = 0
    for k in range(j, len(js)):
        depth += {"{": 1, "}": -1}.get(js[k], 0)
        if depth == 0:
            return js[i:k + 1]
    raise AssertionError(head)


# runs the module's own desk rule (wanted) and its per-frame hand dispatch (hands) in node, against stubs: which mode
# each screen gives, and which hand code runs in each mode
DESK_RULE_JS = r"""
const SRC = JSON.parse(process.env.DESK_RULE_SRC);
const out = {};
// 1. wanted(st): the screen -> the desk mode
{ const M = {lastScreen: null, typeUntil: 0};
  const wanted = new Function("M", SRC.wanted + "; return wanted;")(M);
  const st = (act, screen, T = 0, at = "desk") => ({at, step: null, T, life: {activity: act, screen}});
  out.search = wanted(st("research", {id: "s1", kind: "page", search: {query: "ramen near kichijoji"}}, 0));
  out.searchLater = wanted(st("research", {id: "s1", kind: "page", search: {query: "ramen near kichijoji"}}, 60));
  out.chart = wanted(st("chart", {id: "c1", kind: "page"}, 61));
  out.video = wanted(st("watch_video", {id: "v1", kind: "video"}, 62));
  out.short = wanted(st("research", {id: "v2", kind: "short"}, 63));
  out.away = wanted(st("research", {id: "s2", kind: "page", search: {query: "x"}}, 64, "bed")); }
// 2. hands(dt): which hand code runs per mode (any vector op is a no-op stub)
const calls = [];
const vec = () => new Proxy(function () {}, {get: (t, p) => p === "x" || p === "y" || p === "z" ? 0 : p === "distanceTo" ? () => 0.07 : typeof p === "symbol" ? undefined : vec(), apply: () => vec()});   // (a member is itself callable: hand.parent.getWorldQuaternion())
// (the left hand's share at rest: o.mix, or main's old o.rest flag as 1)
const share = o => !o ? 0 : o.mix != null ? o.mix : o.rest ? 1 : 0;
const rec = name => (...a) => { calls.push([name, a[0], share(a[3]) >= 0.5 ? "rest" : "", share(a[3])]); };
function build(M) {
  const env = {boy: {updateMatrixWorld() {}, rotation: {y: 0}}, bones: {RightHand: vec(), RightForeArm: vec(), RightArm: vec()}};
  const P = {keys: {c: [0, 0, 0]}, kbNode: {}, mouseNode: {}, mouse: [0, 0, 0]};
  const OT = {json: {speed: 0.75}, t: 0, tr: 0};
  const deps = {M, env, P, OT, OT_REST: 0.2, HUMP: 0.02, CLIP: {mouse: [0, 0, 0]}, V: vec, _k: vec(), _c: vec(), _a: vec(), dK: vec(),
    toWorld: () => vec(), kbRef: () => [0, 0, 0], fwdV: () => vec(), S: () => vec(),
    ownerKeys: rec("ownerKeys"), keyOn: rec("keyOn"), pin: () => {}, follow: () => {}, mouseHold: rec("mouseHold"),
    omStep: rec("omStep"), omNow: () => ({move: [0, 0]}), rightChain: () => [], weighted: (side, w, solve) => solve(1), forearmTwistKeep: () => {}, forearmTwistBack: () => {},
    REACH_S: 0.8, ELB_REF: {}, elbowRef: () => {}, elbowKeep: () => {}, swivelTo: () => {}, THREE: {Quaternion: function () { return vec(); }}};
  const names = Object.keys(deps);
  return new Function(...names, SRC.kCtx + "; " + SRC.hands + "; " + (SRC.handsBody || "") + "; return hands;")(...names.map(n => deps[n]));
}
function run(mode, frames) {
  calls.length = 0;
  const M = {mode, w: {type: 0, mouse: 0}, ph: {type: 0, mouse: 0}, noIK: false}, hands = build(M);
  for (let i = 0; i < frames; i++) hands(1 / 30);
  const by = {}; for (const [n, side, o] of calls) { const k = n + (side && typeof side === "string" ? ":" + side : "") + (o ? ":" + o : ""); by[k] = (by[k] || 0) + 1; }
  return by;
}
out.typing = run("desk_type", 60);
out.mousing = run("desk_mouse", 60);
// 3. switching modes in the middle (G24 F6): typing, then mousing, then typing again, frame by frame: the right hand never
// takes the old capture path (keyOn), and the left hand's rest share moves by the weights, not in one jump
{ const M = {mode: "desk_type", w: {type: 0, mouse: 0}, ph: {type: 0, mouse: 0}, noIK: false}, hands = build(M), sw = {keyOnRight: 0, keyOnLeft: 0, maxShareStep: 0, frames: 0};
  let last = null;
  for (let i = 0; i < 150; i++) {
    if (i === 60) M.mode = "desk_mouse"; if (i === 105) M.mode = "desk_type";
    calls.length = 0; hands(1 / 30); sw.frames++;
    for (const [n, side, , sh] of calls) { if (n === "keyOn") sw[side === "Right" ? "keyOnRight" : "keyOnLeft"]++;
      if (n === "ownerKeys" && side === "Left") { if (last != null) sw.maxShareStep = Math.max(sw.maxShareStep, Math.abs(sh - last)); last = sh; } } }
  out.switching = sw; }
console.log(JSON.stringify(out));
"""


def test_module_encodes_the_desk_rule():
    """The owner's desk rule, run from the module itself: a search he is typing -> typing, a chart (anything else at the
    desk) -> the mouse, a video -> sitting back; and in each mode the owner-driven hands run - typing: both hands from his
    typing take (ownerKeys), never the old capture path (keyOn); mousing: the right hand from his mouse take (mouseHold,
    stepping it), the left at rest on the keys from his typing take."""
    import shutil
    import subprocess
    import pytest
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    js = (WEB / "boy_mh.js").read_text()
    src = {"wanted": _js_function(js, "function wanted(st)"), "hands": _js_function(js, "function hands(dt)"),
           "handsBody": _js_function(js, "function handsBody(dt)") if "function handsBody(dt)" in js else "",
           "kCtx": next(line.strip() for line in js.splitlines() if line.strip().startswith("const kCtx ="))}
    import os
    r = subprocess.run([node, "-e", DESK_RULE_JS], capture_output=True, text=True, timeout=60, env={**os.environ, "DESK_RULE_SRC": json.dumps(src)})
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["search"] == "desk_type", out                      # (typing for a search he has just typed)
    assert out["searchLater"] == "desk_mouse", out                # (then back to the mouse)
    assert out["chart"] == "desk_mouse" and out["video"] == "desk_watch" and out["short"] == "desk_watch" and out["away"] is None, out
    t, m = out["typing"], out["mousing"]
    assert t.get("ownerKeys:Left", 0) > 30 and t.get("ownerKeys:Right", 0) > 30, t   # (both hands: the owner's typing)
    assert not any(k.startswith(("keyOn", "mouseHold", "omStep")) for k in t), t
    assert m.get("mouseHold", 0) > 30 and m.get("omStep", 0) > 30, m                  # (the right hand: the owner's mouse take)
    assert m.get("ownerKeys:Left:rest", 0) > 30, m                                    # (the left hand at rest on the keys)
    assert not any(k.startswith("keyOn") or k == "ownerKeys:Right" or k == "ownerKeys:Left" for k in m), m
    sw = out["switching"]                                                             # (G24 F6: across a mode switch)
    assert sw["keyOnRight"] == 0 and sw["keyOnLeft"] == 0, sw                         # (never the old capture path)
    assert sw["maxShareStep"] <= 0.3, sw                                              # (the left hand blends: no one-frame jump)
    assert "const FADE = 0.4;" in js                                                  # (0.4 s crossfades between the modes)
    assert 'fetch("room/mh/owner_typing.json")' in js and 'fetch("room/mh/owner_mouse.json")' in js   # (the takes the page drives)
    for f in ("web/room/mh/owner_typing.json", "web/room/mh/owner_mouse.json"):
        assert (ROOT / f).is_file(), f


def test_licences_recorded():
    credits = (WEB / "CREDITS.md").read_text()
    assert "Character v5 in the room" in credits and "char_v5.glb" in credits and "mh_v5/" in credits and "Tripo" in credits


def test_props_wired():
    js = (WEB / "boy_mh.js").read_text()
    props = json.loads((WEB / "mh" / "props_g2.json").read_text())
    for k in ("room_eat", "room_read", "room_phone", "room_phone_scroll", "room_drink", "room_door", "room_window", "room_bedtime"):
        assert k in props, k
    assert 'fetch("room/mh/props_g2.json")' in js
