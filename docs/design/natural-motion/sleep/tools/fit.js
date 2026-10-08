act("sleep"); sim(0.05, 80);
const want = {head:[-0.03, 0], back:[-0.03, 0.005], pelvis:[-0.015, 0.005], thighs:[-0.01, 0.008], shins:[-0.01, 0.008], feet:[-0.012, 0.005]};
const cost = c => Object.entries(want).reduce((s, [k, [a, b]]) => { const g = c[k] ? c[k].gap : 0; return s + (g < a ? a - g : g > b ? g - b : 0) ** 2; }, 0);
const ev = x => { Object.assign(LIE, x); OFF.breathe = true; sim(0.05, 1); return cost(contacts(4)); };
let x = {pitch:0.11, dy:0.03, spine:0.16, legs:-0.04, knee:0}, best = ev(x);
for (let st of [0.04, 0.02, 0.01, 0.005]) for (let it = 0; it < 6; it++) { let moved = false;
  for (const k of Object.keys(x)) for (const d of [st, -st]) { const y = {...x, [k]: x[k] + d}; const c = ev(y); if (c < best) { best = c; x = y; moved = true; } }
  if (!moved) break; }
ev(x); return {x, best, c: contacts(2)};
