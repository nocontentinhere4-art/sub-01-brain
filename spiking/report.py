"""Figures + result tables for docs/spiking_report.md from the saved validation results.

    python -m spiking.report          # (or python -m spiking.validate --report)

Inputs (any may be missing): docs/spiking/gpu/results.json (full 1M-neuron validation), docs/spiking/gpu_bridge/
results.json (positive control), docs/spiking/gpu_smoke/results.json, docs/spiking/cpu*/results.json,
data/spiking/costs.jsonl, docs/spiking/test_output.txt. Writes docs/spiking/fig_*.png and
docs/spiking/results.md (generated numbers, included by the hand-written report).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs" / "spiking"


def _load(p):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return None


def _costs():
    rows = []
    p = ROOT / "data" / "spiking" / "costs.jsonl"
    if p.exists():
        for line in p.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("event") != "start":
                rows.append(r)
    return rows


def _ph(res, kind):
    return (res or {}).get("phases", {}).get(kind, [])


def _fig_pong(runs, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7, 3.6), dpi=130)
    colors = {"real wiring": "#ff6a00", "positive control (+ visual->motor projection)": "#2a7bd6"}
    chance = None
    for label, res in runs.items():
        curve = _ph(res, "pong_curve")
        if not curve:
            continue
        pts = curve[-1]["points"]
        x = [p["block"] + 1 for p in pts]
        y = [p["hit_rate"] for p in pts]
        ax.plot(x, y, "o-", ms=3, lw=1.4, color=colors.get(label, "#444"), label=f"{label}: training blocks")
        for e in _ph(res, "exam"):
            if "after" in str(e.get("label", "")):
                ax.axhline(e["hit_rate"], color=colors.get(label, "#444"), ls="--", lw=1,
                           label=f"{label}: exam after training (frozen) {e['hit_rate']:.2f}")
                c = e.get("controls", {})
                if c.get("no_plasticity") is not None:
                    ax.axhline(c["no_plasticity"], color=colors.get(label, "#444"), ls=":", lw=1,
                               label=f"{label}: same net, learning removed {c['no_plasticity']:.2f}")
                chance = c.get("random", chance)
    if chance is not None:
        ax.axhline(chance, color="#888", lw=1, label=f"random paddle {chance:.2f}")
    ax.set_xlabel("training block (20 rallies)")
    ax.set_ylabel("hit rate")
    ax.set_ylim(0, 1)
    ax.legend(fontsize=6.5, loc="upper left", frameon=False)
    ax.set_title("Pong: hit rate per block vs controls", fontsize=9)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _fig_memory(res, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    tests = _ph(res, "memory_test")
    if not tests:
        return False
    fig, axes = plt.subplots(1, 2, figsize=(7.5, 3.2), dpi=130)
    for ax, key, title in ((axes[0], "hc", "hippocampal completion"), (axes[1], "ctx", "cortical completion")):
        labels, means, lures = [], [], []
        for t in tests:
            labels.append(str(t.get("label") or "test").replace(" (control)", "\n(control)").replace("after ", "after\n"))
            means.append([s[key] for s in t["scores"]])
            lures.append([c[key] for c in t["control_scores"]])
        for i, (m, lu) in enumerate(zip(means, lures)):
            ax.scatter([i - 0.12] * len(m), m, s=14, color="#ff6a00", label="stored messages" if i == 0 else None)
            ax.scatter([i + 0.12] * len(lu), lu, s=14, color="#888", label="lures (never stored)" if i == 0 else None)
        ax.axhline(0, color="#ccc", lw=0.8)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, fontsize=6.5)
        ax.set_title(title, fontsize=9)
        ax.set_ylabel("completion score", fontsize=8)
    axes[0].legend(fontsize=6.5, frameon=False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return True


def _fig_rates(res, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    r = _ph(res, "rates")
    if not r:
        return False
    r = r[-1]
    fig, axes = plt.subplots(1, 2, figsize=(7.5, 3.0), dpi=130)
    axes[0].plot(range(1, len(r["per_second_e"]) + 1), r["per_second_e"], color="#ff6a00")
    axes[0].set_ylim(0, max(10, max(r["per_second_e"]) * 1.2))
    axes[0].set_xlabel("second")
    axes[0].set_ylabel("mean excitatory rate (Hz)")
    g = r["groups"]
    names = sorted(g, key=g.get)
    axes[1].barh(names, [g[k] for k in names], color="#444")
    axes[1].set_xlabel("mean rate (Hz)")
    for ax in axes:
        ax.tick_params(labelsize=7)
    fig.suptitle(f"Resting activity with the recorded drive, {res['build']['n_neurons']:,} neurons", fontsize=9)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return True


def write_report(gpu_dir=DOCS / "gpu", cpu_dir=DOCS / "cpu"):
    gpu = _load(Path(gpu_dir) / "results.json")
    bridge = _load(DOCS / "gpu_bridge" / "results.json")
    smoke = _load(DOCS / "gpu_smoke" / "results.json")
    cpu = _load(Path(cpu_dir) / "results.json")
    cpu_bridge = _load(DOCS / "cpu_bridge" / "results.json")
    out = []
    main = gpu or smoke
    if main:
        b = main["build"]
        out.append(f"### Build ({b.get('gpu') or b['device']})\n")
        out.append(f"{b['n_neurons']:,} neurons, {b['synapses']:,} synapses ({b['plastic_synapses']:,} plastic), "
                   f"max conduction delay {b['max_delay_ms']} ms, built in {b['build_s']} s, torch {b['torch']}.\n")
    for label, res in (("GPU, full validation", gpu), ("GPU smoke test", smoke), ("CPU", cpu)):
        for bench in _ph(res, "bench"):
            out.append(f"**Speed ({label}, {bench['n_neurons']:,} neurons, {bench['synapses']:,} synapses"
                       f"{', ' + bench['gpu'] if bench.get('gpu') else ''}):** "
                       f"{bench['plasticity_off']['steps_per_s']:,.0f} steps/s with plasticity off "
                       f"({bench['plasticity_off']['realtime_x']:.2f}x real time at dt = 1 ms), "
                       f"{bench['plasticity_on']['steps_per_s']:,.0f} steps/s with STDP eligibility on "
                       f"({bench['plasticity_on']['realtime_x']:.2f}x)"
                       f"{'; GPU memory ' + str(bench['gpu_mem_gb']) + ' GB' if bench.get('gpu_mem_gb') else ''}.\n")
        for r in _ph(res, "rates"):
            out.append(f"**Rates ({label}, {r['seconds']} s with the recorded resting-state drive):** excitatory "
                       f"{r['mean_e_hz']:.2f} Hz, inhibitory {r['mean_i_hz']:.2f} Hz; region rates 1st-99th percentile "
                       f"{r['region_rate_pct']['1']:.2f}-{r['region_rate_pct']['99']:.2f} Hz (max {r['region_rate_max']:.2f}); "
                       f"single neurons (2 s) 5th-99th percentile {r['neuron_rate_pct']['5']}-{r['neuron_rate_pct']['99']} Hz, "
                       f"silent {100 * r['frac_silent_2s']:.2f} %; runaway: {'YES' if r['runaway'] else 'no'}.\n")
        for d in _ph(res, "delays"):
            out.append(f"**Delays ({label}):** {d['n_long_synapses']:,} long-range synapses; delay = fibre length / "
                       f"{d['velocity_m_s']} m/s, max deviation {d['max_abs_error_ms']} ms; median fibre "
                       f"{d['fibre_mm_pct']['50']} mm -> median delay {d['delay_ms_pct']['50']:.0f} ms "
                       f"(5th-95th: {d['delay_ms_pct']['5']:.0f}-{d['delay_ms_pct']['95']:.0f} ms).\n")
    for label, res in (("GPU", gpu), ("CPU", cpu)):
        tests = _ph(res, "memory_test")
        if tests:
            out.append(f"\n#### Memory ({label}, {res['build']['n_neurons']:,} neurons)\n")
            out.append("| test | recalled (of stored) | mean hippocampal score | mean cortical score | lures: max hc / max ctx |")
            out.append("|---|---|---|---|---|")
            for t in tests:
                sc = t["scores"]
                mh = sum(s["hc"] for s in sc) / max(1, len(sc))
                mc = sum(s["ctx"] for s in sc) / max(1, len(sc))
                lh = max((c["hc"] for c in t["control_scores"]), default=0)
                lc = max((c["ctx"] for c in t["control_scores"]), default=0)
                out.append(f"| {t.get('label') or ''} | {len(t['recalled'])} / {len(sc)} | {mh:.3f} | {mc:.3f} | "
                           f"{lh:.3f} / {lc:.3f} |")
            reps = [s for s in _ph(res, "sleep") if s.get("replay")]
            if reps:
                out.append(f"\nREM replays during the compressed night ({reps[-1]['minutes_sim']} simulated minutes): "
                           f"{len(reps[-1]['replays'])}.\n")
    for label, res in (("GPU, real wiring", gpu), ("GPU, positive control", bridge), ("CPU, real wiring", cpu),
                       ("CPU, positive control", cpu_bridge)):
        exams = _ph(res, "exam")
        curve = _ph(res, "pong_curve")
        if not exams and not curve:
            continue
        out.append(f"\n#### Pong ({label}, {res['build']['n_neurons']:,} neurons)\n")
        for e in exams:
            c = e.get("controls", {})
            line = f"- {e.get('label', 'exam')}: {e['hits']} / {e['rallies']} hits ({e['hit_rate']:.2f})"
            if c:
                line += (f"; same network with all learned changes removed {c.get('no_plasticity')}, random paddle "
                         f"{c.get('random')}" + (f", ideal tracker {c['ideal_tracker']}" if c.get("ideal_tracker") else ""))
            out.append(line)
        if curve:
            pts = curve[-1]["points"]
            out.append(f"- training: {len(pts)} blocks x {curve[-1].get('block_rallies', 20)} rallies; hit rate per block: "
                       + ", ".join(f"{p['hit_rate']:.2f}" for p in pts))
    for label, res in (("GPU", gpu), ("CPU", cpu)):
        for c in _ph(res, "choice_curve"):
            out.append(f"\n#### Choice task ({label}, {res['build']['n_neurons']:,} neurons, K = {c['k']}, "
                       f"p = {c['probs']}, reversal at trial {c.get('reversal_at')})\n")
            out.append("| | trials to criterion | after reversal | fraction correct | last 20 before reversal | last 20 |")
            out.append("|---|---|---|---|---|---|")
            for name, key in (("learned (dopamine)", "learned"), ("same network, plasticity frozen", "frozen"),
                              ("random chooser", "random")):
                r = c[key]
                out.append(f"| {name} | {r.get('trials_to_criterion')} | {r.get('trials_to_criterion_after_reversal')} | "
                           f"{r.get('frac_correct')} | {r.get('frac_correct_last20_before_reversal')} | "
                           f"{r.get('frac_correct_last20')} |")
        for e in _ph(res, "choice_exam"):
            ctl = e.get("controls", {})
            out.append(f"- choice exam ({label}, frozen, {e['trials']} trials): {e['frac_correct']} correct; same network "
                       f"with learned changes removed {ctl.get('no_learning')}, random {ctl.get('random')}")
    rows = _costs()
    if rows:
        out.append("\n#### RunPod spend\n")
        out.append("| pod | purpose | GPU | start (UTC) | hours | cost (USD) | reason |")
        out.append("|---|---|---|---|---|---|---|")
        for r in rows:
            out.append(f"| {r['pod_id']} | {r.get('purpose')} | {r.get('gpu')} | {str(r.get('start'))[:19]} | "
                       f"{r.get('hours', 0):.3f} | {r.get('cost_usd', 0):.3f} | {r.get('reason')} |")
        out.append(f"| **total** | | | | **{sum(r.get('hours', 0) for r in rows):.3f}** | "
                   f"**{sum(r.get('cost_usd', 0) for r in rows):.2f}** | |")
    DOCS.mkdir(parents=True, exist_ok=True)
    figs = []
    try:
        if gpu or cpu or bridge or cpu_bridge:
            runs = {k: v for k, v in (("real wiring", gpu or cpu),
                                      ("positive control (+ visual->motor projection)", bridge or cpu_bridge)) if v}
            _fig_pong(runs, DOCS / "fig_pong.png")
            figs.append("fig_pong.png")
        if _fig_memory(gpu or cpu, DOCS / "fig_memory.png"):
            figs.append("fig_memory.png")
        if _fig_rates(gpu or smoke or cpu, DOCS / "fig_rates.png"):
            figs.append("fig_rates.png")
    except Exception as e:                                     # figures are optional
        out.append(f"\n(figures skipped: {type(e).__name__})")
    text = "\n".join(out) + "\n"
    (DOCS / "results.md").write_text(text)
    rep = ROOT / "docs" / "spiking_report.md"
    a, b = "<!-- results:begin -->", "<!-- results:end -->"
    if rep.exists() and a in rep.read_text():
        r = rep.read_text()
        rep.write_text(r[:r.index(a) + len(a)] + "\n" + text + r[r.index(b):])
    return {"results_md": str(DOCS / "results.md"), "figures": figs}


if __name__ == "__main__":
    print(write_report())
