act("sleep"); sim(0.05, 80); ROLL.force = ROLL.ang * SIGN; sim(0.05, 120);
const want = {head:[-0.04, 0.01], back:[-0.02, 0.01], pelvis:[-0.02, 0.01], thighs:[-0.02, 0.01], shins:[-0.015, 0.03], feet:[-0.015, 0.05], arms:[-0.07, 0.03]};
const cost = c => Object.entries(want).reduce((s, [k, [a, b]]) => { const g = c[k] ? c[k].gap : 0; return s + (g < a ? 3 * (a - g) : g > b ? g - b : 0) ** 2; }, 0) + 1e-6 * penetration(4).bed;
const ev = x => { ROLL.lift = x.lift; ROLL.hip = x.hip; ROLL.knee = x.knee; ROLL.arm = [x.hf, x.hy, x.cf, x.cy]; OFF.breathe = true; sim(0.05, 1); return cost(contacts(4)); };
let x = {lift:ROLL.lift, hip:ROLL.hip, knee:ROLL.knee, hf:0.12, hy:0.05, cf:0.22, cy:0.06}, best = ev(x);
for (let st of [0.04, 0.02, 0.01]) for (let it = 0; it < 5; it++) { let moved = false;
  for (const k of Object.keys(x)) for (const d of [st, -st]) { const y = {...x, [k]: x[k] + d * (/hip|knee/.test(k) ? 3 : 1)}; const c = ev(y); if (c < best) { best = c; x = y; moved = true; } }
  if (!moved) break; }
ev(x); return {x, best, c: contacts(2), p: penetration(2)};
