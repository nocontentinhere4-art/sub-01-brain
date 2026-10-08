// Seated states at the desk (room.html?char=mixamo&anim=sova; preview/desk-states). What he does in the chair while he
// is not typing or on the mouse: waiting, watching the monitor, small gestures, and now and then a reaction. This module
// only decides (which slot, from when, for how long); room/boy_mh.js plays it (crossfades, the chair, the seat).
//
// The slots are named; each plays its own clip from room/desk_states/ when index.json lists one (the retargeted
// captures, one GLB per clip, on the character's own mixamorig skeleton: {"clips": {slot: "file.glb"}, "seat": {slot: m},
// "once": [slots a loop plays through once]}, or a list of slots named <slot>.glb), else its stand-in, a Mixamo clip
// already in room/mh_mx/. A slot without either is left out (idle_b: none of the wired clips fits the chair).
//
// The reactions come only from what the page already receives from the server (live_server.py), nothing else:
//   chess  (#17)  the opponent moved and it is his turn -> he looks at the board (attend); check on him -> a gesture;
//                 the game over: won -> react_win, lost -> react_lose, a draw -> a gesture. While the opponent thinks
//                 he waits in the chair (boy_mh's wanted(): the idle slots, not the mouse).
//   decision (#55) his brain picked a page or a video on the monitor -> he looks at it (attend)
//   dopamine (#89) the burst a new clip or page gives (size: novelty + predicted interest - expectation) -> a gesture
//                 from 0.45, react_up from 0.9 (only shorts reach it: video and pages are scaled to 0.5 / 0.25); react_up
//                 stays seated (a laugh, a smile at the screen): only a won game gets him up (react_win)
//   chat   a viewer's message reaches him -> he looks at the monitor (attend)
// Trades are left out by design (nothing financial). Nothing is invented: no event, no reaction.

export const SLOTS = {
  //            kind      stand-in (room/mh_mx/)              once: plays through; span: [s, s] a window of a long take;
  //                                                         seat: the stand-in's seat point (m, + = forward on the seat;
  //                                                         else desk_watch's), where it keeps out of the chair (swept)
  idle_a:      {kind: "idle",    standIn: "room_seated_idle"},           // (desk_watch's own loop: never right after it)
  idle_b:      {kind: "idle",    standIn: null},    // (room_mx_sitting puts his legs through our chair's seat wherever he sits: 5000 vertices)
  idle_c:      {kind: "idle",    standIn: "room_mx_sitting_1"},
  idle_d:      {kind: "idle",    standIn: null},
  attend:      {kind: "attend",  standIn: "room_seated_idle"},
  gesture_a:   {kind: "gesture", standIn: "room_mx_sitting_rubbing_arm", once: true, seat: -0.22},
  gesture_b:   {kind: "gesture", standIn: "room_mx_sitting_talking", span: [5, 8], seat: -0.22},
  gesture_c:   {kind: "gesture", standIn: null, once: true},
  gesture_d:   {kind: "gesture", standIn: null, once: true},
  gesture_e:   {kind: "gesture", standIn: null, once: true},
  gesture_f:   {kind: "gesture", standIn: null, once: true},
  react_win:   {kind: "react",   standIn: "room_mx_sitting_talking", span: [3, 5], seat: -0.22},   // (room_mx_standing_clap: up at the desk, his fingers went into the monitor)
  react_lose:  {kind: "react",   standIn: "room_mx_sitting_rubbing_arm", once: true, seat: -0.22},   // (room_mx_angry_gesture: his forearms through the monitor, at -0.30 his hand through the bottle)
  react_up:    {kind: "react",   standIn: "room_mx_sitting_talking", span: [3, 5], seat: -0.22},   // (seated: a short does not get him up)
};
export const DIR = "room/desk_states";                       // (the named GLBs, when they arrive)

// how long a looping slot holds (s), and how often each kind comes up between events, by what he is doing
export const DWELL = {idle: [7, 15], attend: [6, 12]};
export const MIX = {watch: {attend: 0.55, idle: 0.37, gesture: 0.08}, wait: {idle: 0.65, attend: 0.25, gesture: 0.10}};
export const COOL = {gesture: 25, react: 150};               // (s) at least between two gestures, two reactions
export const KEEP = 4;                                       // (s) an event not played by then is dropped (he was busy)
export const DA = {gesture: 0.45, react: 0.9};

// one page message -> what it calls for ({slot} or {kind}), or null. prev: the last chess message seen (its turn, plies)
export function reactionFor(m, prev) {
  if (!m || typeof m !== "object") return null;
  if (m.type === "chess") {
    if (m.finished || (m.result && m.result !== "unfinished")) {
      if (prev && prev.done === `${m.plies}|${m.result}`) return null;                     // (the end is broadcast twice)
      return m.result === "won" ? {slot: "react_win"} : m.result === "lost" ? {slot: "react_lose"} : m.result === "draw" ? {kind: "gesture"} : null;
    }
    const moved = prev && typeof m.plies === "number" && m.plies > (prev.plies || 0);
    if (moved && m.turn === "his") return m.check ? {kind: "gesture"} : {slot: "attend"};
    return null;
  }
  if (m.type === "decision") return {slot: "attend"};
  if (m.type === "chat") return m.text ? {slot: "attend"} : null;
  if (m.type === "dopamine") {
    const s = +m.size; if (!(s > 0)) return null;
    return s >= DA.react ? {slot: "react_up"} : s >= DA.gesture ? {kind: "gesture"} : null;
  }
  return null;                                               // (trades, ticks, music, ...: no reaction)
}

// the picker: have = the slot names that loaded, clipOf(name) = the clip a slot plays (two slots on one stand-in count as
// one: never the same clip twice in a row), durOf(name) = its length (s), rng() in [0, 1)
export function createPicker({have, clipOf, durOf, rng = Math.random}) {
  const S = {last: null, lastClip: null, at: {gesture: -1e9, react: -1e9}, queue: [], chess: null, log: []};
  const of = kind => have.filter(n => SLOTS[n].kind === kind);
  const fresh = n => n !== S.last && clipOf(n) !== S.lastClip;
  function pickOf(kind) {                                    // a random slot of a kind, never the one (or the clip) just played
    const c = of(kind).filter(fresh); return c.length ? c[Math.floor(rng() * c.length)] : null;
  }
  function plan(name, T) {                                   // when it starts in its clip and how long it holds
    const sl = SLOTS[name], d = durOf(name);
    let from = 0, hold;
    if (sl.span) { const [a, b] = sl.span; hold = Math.min(d, a + rng() * (b - a)); from = rng() * Math.max(0, d - hold); }
    else if (sl.once) hold = d;
    else { const [a, b] = DWELL[sl.kind] || DWELL.idle; hold = a + rng() * (b - a); from = rng() * d; }   // (a random phase: no two loops in step)
    S.last = name; S.lastClip = clipOf(name);
    if (sl.kind === "gesture" || sl.kind === "react") S.at[sl.kind] = T;
    S.log.push([+T.toFixed(2), name]); if (S.log.length > 60) S.log.shift();
    return {name, kind: sl.kind, from, hold, once: !!(sl.once || sl.span)};
  }
  const allowed = (kind, T) => !(kind in COOL) || T - S.at[kind] >= COOL[kind];
  return {
    S,
    event(m, T) {                                            // a page message: maybe something to play soon
      const r = reactionFor(m, S.chess);
      if (m && m.type === "chess") {
        const done = m.finished || (m.result && m.result !== "unfinished") ? `${m.plies}|${m.result}` : null;
        const same = S.chess && (m.plies || 0) >= S.chess.plies;   // (fewer plies: a new game)
        S.chess = {turn: m.turn, plies: m.plies || 0, done: done || (same && S.chess.done) || null};
      }
      if (r) { S.queue.push({...r, T, src: m.type}); if (S.queue.length > 8) S.queue.shift(); }
      return r;
    },
    // what to play next; mode: "watch" (a video, a page) or "wait" (the opponent's turn); null: nothing allowed now
    next(T, mode = "watch") {
      const rank = e => { const k = e.slot ? SLOTS[e.slot] && SLOTS[e.slot].kind : e.kind; return k === "react" ? 0 : k === "gesture" ? 1 : 2; };
      S.queue = S.queue.filter(e => T - e.T <= KEEP).sort((a, b) => rank(a) - rank(b) || b.T - a.T);   // (a reaction before a look)
      while (S.queue.length) {                               // an event first, if its kind is allowed now
        const e = S.queue.shift();
        const name = e.slot && have.includes(e.slot) ? e.slot : e.kind ? pickOf(e.kind) : null;
        if (!name) continue; const k = SLOTS[name].kind;
        if (!allowed(k, T) || (k !== "react" && !fresh(name))) continue;
        S.queue.length = 0;                                  // (the rest came with it: one answer to them)
        return {...plan(name, T), why: e.src};
      }
      const w = MIX[mode] || MIX.watch, kinds = Object.keys(w).filter(k => of(k).some(fresh) && allowed(k, T));
      if (!kinds.length) return null;
      let u = rng() * kinds.reduce((s, k) => s + w[k], 0), kind = kinds[kinds.length - 1];
      for (const k of kinds) { u -= w[k]; if (u < 0) { kind = k; break; } }
      const name = pickOf(kind); return name ? plan(name, T) : null;
    },
    loop(T, mode = "watch") {                                // a looping slot only (out of a gesture or a reaction)
      const w = MIX[mode] || MIX.watch, kinds = ["idle", "attend"].filter(k => of(k).some(fresh));
      if (!kinds.length) return null;
      let u = rng() * kinds.reduce((s, k) => s + w[k], 0), kind = kinds[kinds.length - 1];
      for (const k of kinds) { u -= w[k]; if (u < 0) { kind = k; break; } }
      const name = pickOf(kind); return name ? plan(name, T) : null;
    },
    pending: T => S.queue.some(e => T - e.T <= KEEP),
    get chess() { return S.chess; },
  };
}
