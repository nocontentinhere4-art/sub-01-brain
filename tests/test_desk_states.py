"""The desk states (room/desk_states.js; room.html?char=mixamo&anim=sova, preview/desk-states), run in node: the seated
loops are picked at random but never the same clip twice in a row, each from a random phase of its clip (no two loops in
step); gestures and reactions keep their spacing; the reactions answer only messages the page already receives (chess,
a decision, a dopamine burst, a viewer's chat), never a trade; and the page wires it only behind &anim=sova."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

SIM_JS = r"""
const {createPicker, SLOTS, reactionFor, COOL} = await import(process.env.DS);
let s = 7; const rng = () => (s = (s * 16807) % 2147483647) / 2147483647;
const DUR = {room_seated_idle: 4.17, room_mx_sitting: 4.43, room_mx_sitting_1: 1.17, room_mx_sitting_rubbing_arm: 7.97,
  room_mx_sitting_talking: 44.07, room_mx_standing_clap: 4.77, room_mx_angry_gesture: 5.83};
const have = Object.keys(SLOTS).filter(n => SLOTS[n].standIn), clipOf = n => SLOTS[n].standIn, durOf = n => DUR[clipOf(n)];
const out = {};
for (const mode of ["watch", "wait"]) {
  const p = createPicker({have, clipOf, durOf, rng}); p.S.lastClip = "room_seated_idle";
  let T = 0, prev = "room_seated_idle", rep = 0, froms = [], kinds = {}, lastG = -1e9, gapG = 1e9;
  for (let i = 0; i < 400; i++) { const q = p.next(T, mode); if (!q) { T += 2; continue; }
    if (clipOf(q.name) === prev) rep++; prev = clipOf(q.name); kinds[q.kind] = (kinds[q.kind] || 0) + 1;
    if (q.kind === "gesture") { gapG = Math.min(gapG, T - lastG); lastG = T; }
    if (!q.once) froms.push(q.from / durOf(q.name)); T += q.hold; }
  froms.sort(); const spread = froms.length ? froms[Math.floor(froms.length * 0.9)] - froms[Math.floor(froms.length * 0.1)] : 0;
  out[mode] = {rep, kinds, gapG, spread, n: froms.length};
}
// events
const p = createPicker({have, clipOf, durOf, rng}); let T = 100;
const r = {}, ev = (k, m) => { r[k] = p.event(m, T); };
ev("chessStart", {type: "chess", turn: "his", plies: 0, result: null});
ev("oppMoved", {type: "chess", turn: "his", plies: 2, result: null});
ev("oppCheck", {type: "chess", turn: "his", plies: 4, check: true, result: null});
ev("hisMove", {type: "chess", turn: "opponent", plies: 5, result: null});
ev("won", {type: "chess", turn: "his", plies: 30, result: "won", finished: true});
ev("wonAgain", {type: "chess", turn: "his", plies: 30, result: "won", finished: true});
r.wonNext = p.next(T + 1).name;
p.event({type: "chess", turn: "his", plies: 0, result: null}, T + 60); r.newGameDone = p.chess.done;
r.lost = reactionFor({type: "chess", plies: 40, result: "lost", finished: true}, null);
r.draw = reactionFor({type: "chess", plies: 40, result: "draw", finished: true}, null);
r.decision = reactionFor({type: "decision", chosen: 1}); r.chat = reactionFor({type: "chat", text: "hi"});
r.daSmall = reactionFor({type: "dopamine", size: 0.2}); r.daMid = reactionFor({type: "dopamine", size: 0.6}); r.daBig = reactionFor({type: "dopamine", size: 1.0});
r.trade = reactionFor({type: "tick", trades: [{kind: "buy", usd: 5}]}); r.music = reactionFor({type: "music", playing: true});
// a second reaction within the cool-down is not played; a stale event is dropped
const q = createPicker({have, clipOf, durOf, rng}); q.event({type: "dopamine", size: 1.2}, 0); r.firstUp = q.next(0).name;
q.event({type: "dopamine", size: 1.2}, 10); r.secondUp = q.next(10).kind;
q.event({type: "chat", text: "x"}, 20); r.stale = q.next(30).why || null;
out.events = r; out.cool = COOL;
console.log(JSON.stringify(out));
"""


def run_sim():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, "--input-type=module", "-e", SIM_JS], capture_output=True, text=True, timeout=60,
                       env={**os.environ, "DS": (WEB / "room" / "desk_states.js").as_uri()})
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_loops_random_never_twice_in_a_row_out_of_step():
    out = run_sim()
    for mode in ("watch", "wait"):
        m = out[mode]
        assert m["rep"] == 0, m                                  # (never the same clip twice in a row)
        assert m["spread"] > 0.6, m                              # (their phases spread over the clip: no loop in step)
        assert m["kinds"].get("idle", 0) > 50 and m["kinds"].get("attend", 0) > 30 and m["kinds"].get("gesture", 0) > 5, m
        assert "react" not in m["kinds"], m                      # (reactions only on events)
        assert m["gapG"] >= out["cool"]["gesture"], m             # (gestures kept apart)
    assert out["wait"]["kinds"]["idle"] > out["watch"]["kinds"]["idle"], out   # (waiting: more idling, less watching)


def test_reactions_only_on_the_pages_own_messages():
    r = run_sim()["events"]
    assert r["chessStart"] is None and r["hisMove"] is None, r   # (a new game, his own move: nothing)
    assert r["oppMoved"] == {"slot": "attend"} and r["oppCheck"] == {"kind": "gesture"}, r
    assert r["won"] == {"slot": "react_win"} and r["wonAgain"] is None and r["wonNext"] == "react_win", r
    assert r["newGameDone"] is None, r                            # (a new game: the last one's end is behind him)
    assert r["lost"] == {"slot": "react_lose"} and r["draw"] == {"kind": "gesture"}, r
    assert r["decision"] == {"slot": "attend"} and r["chat"] == {"slot": "attend"}, r
    assert r["daSmall"] is None and r["daMid"] == {"kind": "gesture"} and r["daBig"] == {"slot": "react_up"}, r
    assert r["trade"] is None and r["music"] is None, r          # (nothing financial, nothing else)
    assert r["firstUp"] == "react_up" and r["secondUp"] != "react", r
    assert r["stale"] is None, r


def test_page_wires_it_only_behind_anim_sova():
    html = (WEB / "room.html").read_text()
    assert 'CHAR_MX && new URLSearchParams(location.search).get("anim") !== "mixamo" ? [] : null' in html   # (on by default with the mixamo character)
    assert '...(DESK_EV ? {anim: "sova", deskEvents: () => DESK_EV.splice(0)} : {})' in html
    js = (WEB / "room" / "boy_mh.js").read_text()
    assert 'if (env.anim === "sova") try { await svLoad(make, bodyHips); }' in js   # (a load that fails leaves the Mixamo clips)
    assert 'await import("./desk_states.js")' in js and 'from "./desk_states.js"' not in js   # (the default page never loads it)
    ix = json.loads((WEB / "room" / "desk_states" / "index.json").read_text())   # (used with the author's permission)
    assert all((WEB / "room" / "desk_states" / f).is_file() for f in ix["clips"].values()), ix
    ds = (WEB / "room" / "desk_states.js").read_text()
    for name in ("trade", "usd"):
        assert f'"{name}"' not in ds, name                       # (no financial message is read)


def test_no_desk_state_stands_him_up():
    """COORD's review of 33f7f2d: standing up to clap at the desk put his fingers into the monitor, and a short does not
    get him up; the stand-ins are seated takes only, and every gesture and reaction has its swept seat point."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    js = "const {SLOTS} = await import(process.env.DS); console.log(JSON.stringify(SLOTS));"
    r = subprocess.run([node, "--input-type=module", "-e", js], capture_output=True, text=True, timeout=60,
                       env={**os.environ, "DS": (WEB / "room" / "desk_states.js").as_uri()})
    assert r.returncode == 0, r.stderr
    slots = json.loads(r.stdout)
    assert not [n for n, s in slots.items() if s["standIn"] and ("standing" in s["standIn"] or "angry" in s["standIn"])], slots
    assert all(s.get("seat") is not None for s in slots.values() if s["standIn"] and s["kind"] in ("gesture", "react")), slots
