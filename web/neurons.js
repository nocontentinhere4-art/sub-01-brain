/* "Neurons" panel for SUB-01 (/brain and the life page).
   One million simulated spiking neurons inside the real wiring of one person's brain; a model, not a mind; not the person.

   Data in:
     - Neurons.onMessage(msg) from the page's existing websocket: frames {"type":"spiking", ...state}
       (t_sim, phase, n_neurons, spikes_per_s, mean_rate_hz, realtime_x, groups, raster, pong, dopamine).
       Since #62 the server sends them compact (spiking/frames.py): the numbers at most once a second, and the
       raster as n3.sq (3 bytes a recorded spike: region, slot, time) and the measured rates as n3.rq (1 byte a region).
       Since #88 the panel draws no spike dots: its map is the measured spike rate of every region over the last
       frames (n3.rq, one row a region, a column a frame), a heatmap like a calcium-imaging kymograph.
     - GET /api/spiking/status on load and every 60 s:
       {live, session, next_session, last:{exam, memory_test, pong_curve, bench}, spend}.
     - GET /api/spiking/live on load and every 60 s (#55): the small daytime network that votes in his choices
       {state, n_neurons, card, note, decisions_today, learned_today, last, score, cpu}.
   Nothing here talks to any other host. Errors are silent: the panel then says "no session has run yet". */
window.Neurons = (() => {
  "use strict";
  const FIXED = "1 million simulated spiking neurons inside the real wiring of one person's brain; a model, not a mind; not the person.";
  const HONEST = "Learning results are reported as measured, including when it does not learn.";
  const PONG_NOTE = "Pong: not learning yet. In the last full validation (1M neurons) it hit 17.5 % after training vs 25 % with plasticity switched off.";
  const PONG_CONTROLS = ["no_plasticity", "random"];
  const PHASES = { load: "loading", recall_yesterday: "next-day memory test", encode: "storing today's messages and readings", pong_train: "learning Pong",
    pong_exam: "Pong exam (learning frozen)", memory_test: "memory test", sleep: "sleep: replaying memories", free: "free run",
    deciding: "deciding (small network on the CPU)", idle: "between choices (small network on the CPU)" };
  const CONTROL_NAMES = { random: "random paddle", random_paddle: "random paddle", no_plasticity: "no plasticity",
    frozen: "no plasticity", no_learning: "no plasticity" };
  const GROUP_LABEL = { somatomotor: "motor", relay: "thalamus" };
  const LIVE_MS = 10000, HEAT_N = 60;
  const RATE_LO = 0.1, RATE_HI = 100;
  const rateByte = hz => !(hz >= RATE_LO) ? 0 : Math.max(1, Math.min(255, Math.round(1 + 254 * Math.log(Math.min(hz, RATE_HI) / RATE_LO) / Math.log(RATE_HI / RATE_LO))));
  const NUMBERS = ["n_neurons", "t_sim", "spikes_per_s", "mean_rate_hz", "realtime_x", "groups", "dopamine"];   // once a second

  const S = { inited: false, open: true, live: false, lastWall: -1e9, st: null, status: null, raf: 0, timers: [],
    el: {}, rx: 1, prevPhase: null, refetch: 0, sized: false,
    // rate map: the last HEAT_N frames' per-region rate bytes (log 0.1-100 Hz), fixed size, no per-frame allocation
    heat: new Uint8Array(HEAT_N * 255), hHead: 0, hCount: 0, hRows: 214, hDirty: false,
    text: Object.create(null) };

  // ---------- helpers ----------
  const h = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const num = v => typeof v === "number" && isFinite(v);
  const int = v => num(v) ? Math.round(v).toLocaleString("en-US") : "—";
  const floor2 = v => (Math.floor(v * 100 + 1e-9) / 100).toFixed(2);     // shown as measured, never rounded up
  const pct = v => num(v) ? Math.floor(v * 100 + 1e-9) + " %" : "—";
  const rate = v => !num(v) ? "—" : v >= 1e6 ? floor2(v / 1e6) + "M" : v >= 1e4 ? Math.floor(v).toLocaleString("en-US") : v >= 100 ? Math.floor(v) + "" : floor2(v);
  const phaseWords = p => p == null ? "—" : (PHASES[p] || String(p).replace(/_/g, " "));
  function setText(key, s) { const e = S.el[key]; if (!e) return; if (S.text[key] !== s) { S.text[key] = s; e.textContent = s; } }
  function show(key, on) { const e = S.el[key]; if (e) e.classList.toggle("nx-hidden", !on); }
  function tokyo(iso) {
    const d = new Date(iso); if (isNaN(d)) return null;
    const far = Math.abs(d - Date.now()) > 6 * 864e5;
    const o = { timeZone: "Asia/Tokyo", weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false };
    if (far) { o.day = "numeric"; o.month = "short"; }
    const parts = Object.create(null);
    for (const p of new Intl.DateTimeFormat("en-GB", o).formatToParts(d)) parts[p.type] = p.value;
    return `${parts.weekday}${far ? " " + parts.day + " " + parts.month : ""} ${parts.hour}:${parts.minute} Tokyo`;
  }

  // ---------- DOM ----------
  function build(mount, open) {
    const det = h("details", "nx"); det.open = open;
    const sum = h("summary"); sum.append(document.createTextNode("Neurons · "), S.el.state = h("b", null, "offline"));
    const body = h("div", "nx-body");
    S.el.count = h("div", "nx-count");
    S.el.liverow = h("div", "nx-row");
    S.el.grouprow = h("div", "nx-row");
    S.el.raster = h("canvas", "nx-raster"); S.el.rastercap = h("div", "nx-cap");
    const pr = h("div", "nx-pongrow"); S.el.pongrow = pr;
    S.el.pong = h("canvas", "nx-pong"); S.el.pongstats = h("div", "nx-pongstats"); pr.append(S.el.pong, S.el.pongstats);
    S.el.curve = h("div", "nx-curve"); S.el.curvecap = h("div", "nx-cap");
    S.el.results = h("div", "nx-results");
    S.el.day = h("div", "nx-day nx-hidden");
    S.el.learn = h("div", "nx-day nx-hidden");
    S.el.next = h("div", "nx-row");
    S.el.note = h("div", "nx-note", HONEST);
    S.el.fixed = h("div", "nx-fixed", FIXED);
    body.append(S.el.count, S.el.liverow, S.el.grouprow, S.el.raster, S.el.rastercap, pr, S.el.curve, S.el.curvecap, S.el.day, S.el.learn, S.el.results, S.el.next, S.el.note, S.el.fixed);
    det.append(sum, body); mount.append(det); S.el.root = det;
    det.addEventListener("toggle", () => { S.open = det.open; ensureLoop(); });
    if (window.ResizeObserver) new ResizeObserver(() => { S.sized = false; }).observe(det);
    return det;
  }

  // ---------- live frames ----------
  function onMessage(m) {
    if (!S.inited || !m || m.type !== "spiking") return;
    // the small CPU network (#55) streams too; while the GPU network streams, its frames win the raster
    if (m.net === "cpu") { if (performance.now() - (S.gpuWall || -1e9) < LIVE_MS) return; }
    else if (m.raster || m.t_sim != null) S.gpuWall = performance.now();
    try { frame(m); } catch (e) { /* a malformed frame must never break the page */ }
  }
  function unb64(t) { const b = atob(t || ""), out = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) out[i] = b.charCodeAt(i); return out; }
  function frame(m) {
    if (S.st && S.st.net === m.net) {                   // frames between two full ones carry no numbers: keep the last
      m = Object.assign({}, m);
      for (const k of NUMBERS) if (m[k] == null && S.st[k] != null) m[k] = S.st[k];
    }
    S.st = m; S.lastWall = performance.now();
    if (num(m.realtime_x) && m.realtime_x > 0) S.rx = Math.min(m.realtime_x, 50);
    const r = m.raster, n3 = m.n3, span = r && num(r.t0) && num(r.t1) ? Math.max(0, r.t1 - r.t0) : 0;
    let col = null, rows = 214;
    if (n3 && typeof n3.rq === "string") {               // measured: each region's spike rate in this frame
      col = unb64(n3.rq); rows = col.length;
      setText("rastercap", `measured spike rate of each region (rows: ${rows} regions) over the last ${HEAT_N} frames; dark = slow, orange = fast (log scale, 0.1–100 Hz)`);
    } else if (r && Array.isArray(r.spikes) && num(r.n) && r.n > 0 && span > 0) {   // an older pod: rate of each sampled neuron
      rows = Math.min(255, r.n); const cnt = new Float32Array(rows);
      for (const sp of r.spikes) if (sp && sp.length > 1 && sp[1] < rows) cnt[sp[1] | 0]++;
      col = new Uint8Array(rows); for (let i = 0; i < rows; i++) col[i] = rateByte(cnt[i] * 1000 / span);
      setText("rastercap", `spike rate of each of ${rows} sampled neurons over the last ${HEAT_N} frames; dark = slow, orange = fast (log scale, 0.1–100 Hz)`);
    }
    if (col && rows > 0 && rows <= 255) {
      if (rows !== S.hRows) { S.hRows = rows; S.hCount = 0; S.hHead = 0; }
      S.heat.set(col.subarray(0, rows), S.hHead * 255); S.hHead = (S.hHead + 1) % HEAT_N; S.hCount = Math.min(HEAT_N, S.hCount + 1);
      S.hDirty = true;
    }
    if (!S.live) setLive(true);
    if (m.phase !== S.prevPhase) {                       // a phase ended: results may have landed on the server
      if (S.prevPhase != null) { clearTimeout(S.refetch); S.refetch = setTimeout(fetchStatus, 4000); }
      S.prevPhase = m.phase;
    }
    updateLiveText(m);
  }
  function updateLiveText(m) {
    const n = num(m.n_neurons) ? m.n_neurons : (S.status && S.status.session && S.status.session.n_neurons);
    setText("count", `${int(n)} simulated spiking neurons`);
    const row = S.el.liverow;
    if (row && !row.firstChild) { row.append(h("b"), document.createTextNode(" spikes/s · "), h("i"), document.createTextNode(" · mean "), h("b"), document.createTextNode(" Hz · dopamine "), h("b"));
      S.el.spk = row.children[0]; S.el.phase = row.children[1]; S.el.mean = row.children[2]; S.el.dopa = row.children[3]; }
    setText("spk", rate(m.spikes_per_s)); setText("phase", phaseWords(m.phase));
    setText("mean", num(m.mean_rate_hz) ? floor2(m.mean_rate_hz) : "—"); setText("dopa", num(m.dopamine) ? floor2(m.dopamine) : "—");
    const g = m.groups;
    if (g && typeof g === "object") {
      const top = Object.keys(g).filter(k => num(g[k])).sort((a, b) => g[b] - g[a]).slice(0, 4);
      setText("grouprow", top.length ? "most active: " + top.map(k => `${GROUP_LABEL[k] || k} ${(Math.floor(g[k] * 10 + 1e-9) / 10).toFixed(1)}`).join(" · ") + " Hz" : "");
    }
    const p = m.pong; show("pongrow", !!p);
    if (p) setText("pongstats", `Pong · hits ${int(p.hits)} · misses ${int(p.misses)} · rally ${int(p.rally)}`);
  }
  function setLive(on) {
    S.live = on; S.el.root.dataset.live = on ? "1" : "0";
    setText("state", on ? "LIVE" : "offline");
    show("liverow", on); show("grouprow", on); show("raster", on); show("rastercap", on); show("pongrow", on && !!(S.st && S.st.pong));
    renderStatus(); ensureLoop();
  }
  function tick() { if (S.live && performance.now() - S.lastWall > LIVE_MS) setLive(false); }

  // ---------- drawing (only while live, open and visible) ----------
  function ensureLoop() { if (!S.raf && S.live && S.open && !document.hidden) S.raf = requestAnimationFrame(loop); }
  function loop() {
    S.raf = 0;
    if (!S.live || !S.open || document.hidden) return;
    drawRaster(); drawPong(); S.raf = requestAnimationFrame(loop);
  }
  function size(cv) { const d = Math.min(2, devicePixelRatio || 1), w = Math.max(1, Math.round(cv.clientWidth * d)), hh = Math.max(1, Math.round(cv.clientHeight * d));
    if (cv.width !== w || cv.height !== hh) { cv.width = w; cv.height = hh; } return d; }
  function drawRaster() {                             // the rate map: a pixel per region and frame, oldest left
    const cv = S.el.raster; if (!S.hDirty && cv.width > 1) return;
    const ctx = cv.getContext("2d"); if (!ctx) return;
    size(cv); S.hDirty = false;
    const rows = S.hRows, img = ctx.createImageData(HEAT_N, rows), px = img.data;
    for (let c = 0; c < HEAT_N; c++) {
      const age = HEAT_N - 1 - c, slot = (S.hHead - 1 - age + 2 * HEAT_N) % HEAT_N, has = age < S.hCount;
      for (let y = 0; y < rows; y++) {
        const v = has ? S.heat[slot * 255 + y] / 255 : 0, o = 4 * (y * HEAT_N + c);
        px[o] = 7 + 248 * Math.pow(v, 1.3); px[o + 1] = 7 + 110 * Math.pow(v, 1.8); px[o + 2] = 11 + 10 * v; px[o + 3] = 255;
      }
    }
    const tmp = drawRaster.tmp || (drawRaster.tmp = document.createElement("canvas"));
    tmp.width = HEAT_N; tmp.height = rows; tmp.getContext("2d").putImageData(img, 0, 0);
    ctx.imageSmoothingEnabled = false; ctx.drawImage(tmp, 0, 0, cv.width, cv.height);
  }
  function drawPong() {
    const p = S.st && S.st.pong, cv = S.el.pong; if (!p || !cv) return;
    const ctx = cv.getContext("2d"); if (!ctx) return;
    const d = size(cv), w = cv.width, hh = cv.height;
    ctx.fillStyle = "#07070b"; ctx.fillRect(0, 0, w, hh);
    ctx.strokeStyle = "#23232f"; ctx.lineWidth = d; ctx.strokeRect(0.5 * d, 0.5 * d, w - d, hh - d);
    const ph = num(p.paddle_h) ? p.paddle_h : 0.2, py = num(p.paddle) ? p.paddle : 0.5;
    ctx.fillStyle = "#ff6a00"; ctx.fillRect(0, (py - ph / 2) * hh, 3 * d, ph * hh);
    if (Array.isArray(p.ball) && num(p.ball[0]) && num(p.ball[1])) {
      // dot-ok: the Pong ball, the game's real ball at its position in the game the network plays
      ctx.fillStyle = "#ececf2"; ctx.beginPath(); ctx.arc(p.ball[0] * w, p.ball[1] * hh, 2.2 * d, 0, 6.2832); ctx.fill(); }
  }

  // ---------- status (results, next session) ----------
  async function fetchStatus() {
    try {
      const r = await fetch(S.statusUrl, { cache: "no-store", credentials: "same-origin" });
      if (!r.ok) throw new Error(r.status);
      const j = await r.json(); if (j && typeof j === "object") S.status = j;
    } catch (e) { /* no server / not logged in / no sessions yet: keep whatever we had */ }
    renderStatus();
  }
  // ---------- the daytime network (#55): a small spiking network votes in his choices and learns ----------
  async function fetchDay() {
    try {
      const r = await fetch(S.dayUrl, { cache: "no-store", credentials: "same-origin" });
      if (!r.ok) throw new Error(r.status);
      const j = await r.json(); if (j && typeof j === "object") S.day = j;
    } catch (e) { /* not logged in / an older server: the block stays hidden */ }
    try { renderDay(); } catch (e) { /* a malformed answer must never break the page */ }
  }
  function dayCurve(curve) {
    const pts = (Array.isArray(curve) ? curve : []).filter(b => b && num(b.learned) && num(b.twin) && num(b.chance));
    if (pts.length < 2) return null;
    const W = 300, H = 46, pad = 3, n = pts.length;
    const X = i => pad + i / (n - 1) * (W - 2 * pad), Y = v => H - pad - Math.max(0, Math.min(1, v)) * (H - 2 * pad);
    const NS = "http://www.w3.org/2000/svg", svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("preserveAspectRatio", "none");
    const line = (key, col, dash, width) => { const p = document.createElementNS(NS, "path");
      p.setAttribute("d", pts.map((b, i) => `${i ? "L" : "M"}${X(i)} ${Y(b[key])}`).join(" ")); p.setAttribute("fill", "none");
      p.setAttribute("stroke", col); p.setAttribute("stroke-width", width); p.setAttribute("vector-effect", "non-scaling-stroke");
      if (dash) p.setAttribute("stroke-dasharray", dash); svg.append(p); };
    line("chance", "#55556a", "1.5 3", 1); line("twin", "#80808f", "5 4", 1); line("learned", "#ff6a00", null, 1.5);
    const box = h("div", "nx-curve"); box.append(svg); return box;
  }
  function renderDay() {
    const d = S.day, box = S.el.day; if (!box) return;
    box.replaceChildren();
    if (!d || d.state === "off" || !num(d.n_neurons)) { show("day", false); return; }
    show("day", true);
    const head = h("div", "nx-row");
    head.append(document.createTextNode("In the day · "), h("b", null, d.state === "live" ? "live" : d.state === "starting" ? "starting" : "offline"),
      document.createTextNode(` · ${int(d.n_neurons)} neurons · ${int(d.decisions_today)} choices today · learned from ${int(d.learned_today)}`));
    box.append(head);
    const bn = d.by_net_today || {};
    if (num(d.decisions_today) && d.decisions_today > 0)
      box.append(h("div", "nx-cap", `answered today by: 1M network on GPU ${int(bn.gpu || 0)} · 20k network on CPU ${int(bn.cpu || 0)} · rate model only ${int(bn.rate || 0)}`));
    const L = d.last;
    if (L && Array.isArray(L.labels)) {
      const r = h("div", "nx-row");
      if (L.leaned_to) {
        r.append(document.createTextNode(`Last choice (${L.network || "spiking network"}): his spiking neurons leaned toward `), h("b", null, `“${String(L.leaned_to).slice(0, 80)}”`));
        if (L.followed_label && L.followed_label !== L.leaned_to) r.append(document.createTextNode(` · he followed “${String(L.followed_label).slice(0, 80)}”`));
        else if (L.followed_label) r.append(document.createTextNode(" · he followed it"));
      } else r.append(document.createTextNode(`Last choice: rate model only${L.why ? " (" + String(L.why).slice(0, 80) + ")" : ""}`));
      box.append(r);
    }
    const sc = d.score || {}, mp = sc.matched_paid_off || {}, mn = sc.matched_not_paid_off || {};
    const cv = dayCurve(sc.curve); if (cv) box.append(cv);
    if (num(sc.paid_off) && sc.paid_off > 0) {
      box.append(h("div", "nx-cap", `Its pick matched the option that later paid off: ${pct(mp.learned)} (orange) · frozen twin ${pct(mp.twin)} (dashed) · chance ${pct(mp.chance)} (dotted) · ${int(sc.paid_off)} paid-off choices`
        + (num(mn.learned) ? ` · when it did not pay off: ${pct(mn.learned)} vs twin ${pct(mn.twin)}` : "")));
    } else box.append(h("div", "nx-cap", "no choice with an outcome yet"));
    if (d.cpu && num(d.cpu.avg_pct)) box.append(h("div", "nx-cap", `its process: ${floor2(d.cpu.avg_pct)} % of one CPU core on average`));
    if (d.card) box.append(h("div", "nx-note", d.card + (d.note ? " " + d.note : "")));
  }
  // ---------- real decisions, per Tokyo day (#70, /api/spiking/status "learning"): as measured, no extra claims ----------
  function renderLearning(L) {
    const box = S.el.learn; if (!box) return;
    box.replaceChildren();
    const days = L && Array.isArray(L.days) ? L.days.filter(d => d && d.day).slice(-5) : [];
    if (!days.length) { show("learn", false); return; }
    show("learn", true);
    box.append(h("div", "nx-row", "Real decisions, per day"));
    const net = (s, name) => s && num(s.with_outcome) && s.with_outcome > 0
      ? `${name} picks paid off ${pct(s.paid_off_frac)} of ${int(s.with_outcome)}` : null;
    for (const d of days.slice().reverse()) {
      const r = d.replay || {}, bits = [net(d.gpu, "1M GPU"), net(d.other, "20k CPU")].filter(Boolean);
      if (num(r.learned) || num(r.frozen_twin))
        bits.push(`replay: learned ${pct(r.learned)} vs frozen twin ${pct(r.frozen_twin)}${num(r.chance) ? ` vs chance ${pct(r.chance)}` : ""}${num(r.n) ? ` (${int(r.n)} decisions)` : ""}`);
      box.append(h("div", "nx-cap", `${d.day} · ${bits.length ? bits.join(" · ") : "no decision with an outcome"}`));
    }
    if (L.note) box.append(h("div", "nx-note", String(L.note)));
  }
  function controlName(k) { return CONTROL_NAMES[k] || String(k).replace(/_/g, " "); }
  function memoryLine(mt) {
    if (!mt || typeof mt !== "object") return null;
    const cues = Array.isArray(mt.cues) ? mt.cues.length : (num(mt.n_cues) ? mt.n_cues : null);
    let k = num(mt.n_recalled) ? mt.n_recalled : num(mt.recalled_count) ? mt.recalled_count : null;
    if (k == null && Array.isArray(mt.recalled)) k = mt.recalled.filter(Boolean).length;
    const mean = a => Array.isArray(a) && a.length && a.every(num) ? a.reduce((x, y) => x + y, 0) / a.length : null;
    const ms = num(mt.mean_score) ? mt.mean_score : mean(mt.scores), mc = num(mt.control_mean) ? mt.control_mean : mean(mt.control_scores);
    const bits = [];
    if (k != null) bits.push(`recalled ${int(k)}${cues != null ? " of " + int(cues) : ""} cues`); else if (cues != null) bits.push(`${int(cues)} cues`);
    if (ms != null) bits.push(`mean score ${floor2(ms)}`);
    if (mc != null) bits.push(`control ${floor2(mc)}`);
    if (num(mt.day)) bits.push(`day ${mt.day}`);
    return bits.length ? "Memory test: " + bits.join(" · ") : null;
  }
  function pongLearns(ex) {                               // only "learning" when it beats every control clearly
    const c = (ex && ex.controls) || {}, ctl = PONG_CONTROLS.map(k => c[k]).filter(num);
    return !!ex && num(ex.hit_rate) && ctl.length > 0 && ex.hit_rate > Math.max(...ctl) + 0.05;
  }
  function examLine(ex) {
    if (!ex || typeof ex !== "object") return null;
    let s = `Pong${pongLearns(ex) ? "" : " (not learning yet)"} exam: ${int(ex.hits)}/${int(ex.rallies)} hits (${ex.frozen === false ? "learning not frozen" : "learning frozen"})`;
    const c = ex.controls || {};
    for (const k of PONG_CONTROLS) if (num(c[k])) s += ` · ${controlName(k)} ${pct(c[k])}`;
    if (num(ex.day)) s += ` · day ${ex.day}`;
    return s;
  }
  function benchLine(b) {
    if (!b || typeof b !== "object") return null;
    const bits = [];
    if (num(b.steps_per_s)) bits.push(`${Math.floor(b.steps_per_s).toLocaleString("en-US")} steps/s`);
    if (num(b.realtime_x)) bits.push(`${floor2(b.realtime_x)}× real time`);
    if (num(b.n_neurons)) bits.push(`${int(b.n_neurons)} neurons`);
    if (num(b.synapses)) bits.push(`${int(b.synapses)} synapses`);
    if (b.gpu) bits.push(String(b.gpu));
    return bits.length ? "Bench: " + bits.join(" · ") : null;
  }
  function series(v) {                                   // control value -> per-block numbers or a flat level
    if (num(v)) return { flat: v };
    if (Array.isArray(v) && v.length) {
      const ys = v.map(p => num(p) ? p : (p && num(p.hit_rate) ? p.hit_rate : null));
      return ys.every(num) ? { ys } : null;
    }
    return null;
  }
  function renderCurve(pc) {
    const box = S.el.curve, cap = S.el.curvecap; box.replaceChildren();
    const pts = pc && Array.isArray(pc.points) ? pc.points.filter(p => p && num(p.hit_rate)) : [];
    if (!pts.length) { show("curve", false); show("curvecap", false); return; }
    show("curve", true); show("curvecap", true);
    const W = 300, H = 56, pad = 3, n = pts.length;
    const X = i => pad + (n > 1 ? i / (n - 1) : 0.5) * (W - 2 * pad), Y = v => H - pad - Math.max(0, Math.min(1, v)) * (H - 2 * pad);
    const NS = "http://www.w3.org/2000/svg", svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("preserveAspectRatio", "none");
    const line = (d, col, dash, width) => { const p = document.createElementNS(NS, "path"); p.setAttribute("d", d); p.setAttribute("fill", "none");
      p.setAttribute("stroke", col); p.setAttribute("stroke-width", width); p.setAttribute("vector-effect", "non-scaling-stroke");
      if (dash) p.setAttribute("stroke-dasharray", dash); svg.append(p); };
    for (const lv of [0.25, 0.5, 0.75]) line(`M${pad} ${Y(lv)} H${W - pad}`, "#15151d", null, 1);
    const capBits = [`Pong training · hit rate per block, ${n} block${n === 1 ? "" : "s"} (orange)`];
    const ctl = pc.controls && typeof pc.controls === "object" ? pc.controls : {};
    const dashes = { "random paddle": "5 4", "no plasticity": "1.5 3" }; let di = 0;
    for (const k of Object.keys(ctl)) {
      const s = series(ctl[k]); if (!s) continue;
      const name = controlName(k), dash = dashes[name] || ["3 2", "6 2 1 2"][di++ % 2];
      const d = s.ys ? s.ys.map((v, i) => `${i ? "L" : "M"}${X(i * (n - 1) / Math.max(1, s.ys.length - 1))} ${Y(v)}`).join(" ")
                     : `M${pad} ${Y(s.flat)} H${W - pad}`;
      line(d, "#80808f", dash, 1);
      capBits.push(`${name} ${s.flat != null ? pct(s.flat) : pct(s.ys[s.ys.length - 1])} (dashed)`);
    }
    line(pts.map((p, i) => `${i ? "L" : "M"}${X(i)} ${Y(p.hit_rate)}`).join(" "), "#ff6a00", null, 1.5);
    const last = pts[n - 1];
    box.append(svg);
    capBits.push(`last block ${pct(last.hit_rate)}${num(last.rallies) ? " of " + int(last.rallies) + " rallies" : ""}`);
    cap.textContent = capBits.join(" · ");
  }
  function renderStatus() {
    const st = S.status, last = (st && st.last) || {}, res = S.el.results; res.replaceChildren();
    const lines = [examLine(last.exam), memoryLine(last.memory_test), benchLine(last.bench)].filter(Boolean);
    if (!last.exam && last.pong_curve) lines.unshift(PONG_NOTE);           // no exam numbers of its own: the last validation
    renderCurve(last.pong_curve);
    try { renderLearning(st && st.learning); } catch (e) { /* a malformed answer must never break the panel */ }
    const any = lines.length || (last.pong_curve && Array.isArray(last.pong_curve.points) && last.pong_curve.points.length);
    if (!S.live) {
      const n = num(st && st.session && st.session.n_neurons) ? st.session.n_neurons : (last.bench && num(last.bench.n_neurons) ? last.bench.n_neurons : null);
      setText("count", n != null ? `${int(n)} simulated spiking neurons` : "simulated spiking neurons");
      if (st && st.live) res.append(h("div", null, "session in progress · no live frames right now"));
      if (!any) res.append(h("div", null, "no session has run yet"));
    }
    for (const l of lines) res.append(h("div", null, l));
    const nx = !S.live && st && st.next_session ? tokyo(st.next_session) : null;
    setText("next", nx ? `next session: ${nx}` : ""); show("next", !!nx);
  }

  // ---------- public ----------
  function init(opts) {
    if (S.inited) return S.el.root;
    const o = opts || {}, mount = o.mount || document.body; if (!mount) return null;
    S.statusUrl = o.statusUrl || "/api/spiking/status"; S.dayUrl = o.dayUrl || "/api/spiking/live"; S.open = o.open !== false;
    build(mount, S.open); S.inited = true;
    setLive(false); fetchStatus(); fetchDay();
    S.timers.push(setInterval(fetchStatus, 60000), setInterval(fetchDay, 60000), setInterval(tick, 1000));
    document.addEventListener("visibilitychange", ensureLoop);
    return S.el.root;
  }
  return { init, onMessage, refresh: fetchStatus, get live() { return S.live; } };
})();
