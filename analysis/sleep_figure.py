"""Figure for docs/twin/sleep.md: 48 undisturbed hours of the sleep circuit (sleep.py), two nights.

    python analysis/sleep_figure.py        # -> docs/twin/hypnogram.png, prints each night's numbers

Panels share the time axis (12:00 day 1 -> 12:00 day 3, local clock): somnogen H, circadian drive C, the MA/VLPO
flip-flop, the hypnogram (with the NREM depth index) and the four neuromodulator levels the engine exports to
twin/neurochem.py. The engine is stepped like the live server at --time-scale 120 (6 s of sim time per 50 ms tick).
A model of brain activity; not a mind, not conscious, not the person.
"""
import random
import sys
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import sleep  # noqa: E402

SURFACE, INK, INK2, GRID, SHADE = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df", "#efeee9"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]      # categorical slots 1-4, validated (light surface)
STAGE_Y = {"AWAKE": 3, "REM": 2, "NREM": 1}
STEP = 6.0
HOURS = 48


def simulate():
    t0 = datetime(2026, 10, 1, 12, 0, tzinfo=sleep.TZ).timestamp()
    e = sleep.SleepEngine(t0, rng=random.Random(0))
    rows, t = [], t0
    while t < t0 + HOURS * 3600:
        t += STEP
        e.update(t, dt_real=0.05)
        rows.append((t, e.H, e.C, e.V_m, e.V_v, e.stage, e.depth, e.modulators))
    return t0, rows


def nights(rows):
    """Per night: onset, wake, hours asleep, REM share, first REM latency, episode list, REM minutes."""
    eps = []
    for r in rows:
        if not eps or eps[-1][0] != r[5]:
            eps.append([r[5], r[0], r[0]])
        eps[-1][2] = r[0] + STEP
    out, cur = [], []
    for ep in eps:
        if ep[0] == "AWAKE":
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append(ep)
    res = []
    for n in out:
        dur = lambda x: (x[2] - x[1]) / 60
        rem = [round(dur(x)) for x in n if x[0] == "REM"]
        total = sum(dur(x) for x in n)
        res.append({"onset": sleep.hhmm(n[0][1]), "wake": sleep.hhmm(n[-1][2]), "sleep_h": round(total / 60, 2),
                    "cycles": len(rem), "rem_share": round(sum(rem) / total, 3),
                    "first_rem_after_min": round((next(x[1] for x in n if x[0] == "REM") - n[0][1]) / 60),
                    "episodes_min": " ".join(f"{x[0][0]}{dur(x):.0f}" for x in n), "rem_min": rem})
    return res


def main(out=ROOT / "docs" / "twin" / "hypnogram.png"):
    t0, rows = simulate()
    x = np.array([(r[0] - t0) / 3600 + 12 for r in rows])
    col = lambda i: np.array([r[i] for r in rows])
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK2, "xtick.color": INK2,
                         "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.facecolor": SURFACE, "figure.facecolor": SURFACE})
    fig, ax = plt.subplots(5, 1, figsize=(12, 10.5), sharex=True,
                           gridspec_kw={"height_ratios": [1, 0.8, 1.2, 1.1, 1.5], "hspace": 0.4})
    asleep = np.array([r[5] != "AWAKE" for r in rows])
    for a in ax:
        a.grid(True, color=GRID, lw=0.8)
        a.set_axisbelow(True)
        a.fill_between(x, 0, 1, where=asleep, transform=a.get_xaxis_transform(), color=SHADE, lw=0)
    title = lambda a, s: a.set_title(s, loc="left", color=INK, fontsize=10)
    xe = x[-1] + 0.3

    ax[0].plot(x, col(1), color=SERIES[0], lw=2)
    ax[0].set_ylabel("H (nM)")
    title(ax[0], "Homeostatic somnogen H: rises while awake, cleared during sleep")
    ax[1].plot(x, col(2), color=SERIES[0], lw=2)
    ax[1].set_ylabel("C")
    title(ax[1], f"Circadian drive C, locked to the local clock (peak {sleep.CIRC_PEAK_H:.2f} h)")
    for i, (k, lab) in enumerate(((3, "MA  V_m"), (4, "VLPO  V_v"))):
        ax[2].plot(x, col(k), color=SERIES[i], lw=2, label=lab)
        ax[2].text(xe, col(k)[-1], lab, color=INK2, va="center", fontsize=8)
    ax[2].set_ylabel("mV")
    ax[2].legend(loc="lower right", frameon=False, ncol=2, bbox_to_anchor=(1, 1.0))
    title(ax[2], "Flip-flop: MA and VLPO inhibit each other (Phillips & Robinson 2007)")
    st = np.array([STAGE_Y[r[5]] for r in rows])
    ax[3].step(x, st, where="post", color=INK, lw=1.2)
    d = col(6)
    ax[3].fill_between(x, 1 - 0.9 * d, 1, where=d > 0, step="post", color=SERIES[0], alpha=0.4, lw=0,
                       label="NREM depth index (down = deeper)")
    ax[3].fill_between(x, 1.75, 2.25, where=st == 2, step="post", color=SERIES[1], lw=0, label="REM")
    ax[3].set_yticks([0.1, 1, 2, 3], ["deep", "NREM", "REM", "AWAKE"])
    ax[3].set_ylim(-0.05, 3.3)
    ax[3].legend(loc="center", frameon=False, ncol=1, bbox_to_anchor=(0.585, 0.3))     # in the empty daytime band
    title(ax[3], "Hypnogram: REM-on/REM-off flip-flop + REM pressure; ~90 min cycles, REM longer late")
    for i, k in enumerate(sleep.MOD_KEYS):
        y = [r[7][k] for r in rows]
        ax[4].plot(x, y, color=SERIES[i], lw=1.6, label=k)
        j = int(np.searchsorted(x, 24.67))                        # 00:40, night 1: deep NREM separates the four
        ax[4].text(23.8, y[j], f"{k} ", color=INK2, va="center", ha="right", fontsize=8)   # left of sleep onset
    ax[4].axhline(1.0, color=INK2, lw=0.8, ls=":")
    ax[4].set_ylabel("level (1 = resting wake)")
    ax[4].legend(loc="lower right", frameon=False, ncol=4, bbox_to_anchor=(1, 1.0))
    title(ax[4], "Neuromodulators read from the circuit (engine.modulators -> twin/neurochem.py)")
    ticks = np.arange(12, 12 + HOURS + 1, 3)
    ax[4].set_xticks(ticks, [f"{int(h) % 24:02d}:00" for h in ticks])
    ax[4].set_xlim(12, 12 + HOURS)
    ax[4].set_xlabel(f"local time ({sleep.TZ_NAME}), two undisturbed days, no input; shaded = asleep")
    fig.suptitle("SUB-01 sleep circuit: 48 h (a model, not the person)", x=0.125, y=0.93, ha="left", color=INK,
                 fontsize=12, fontweight="bold")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120, bbox_inches="tight", facecolor=SURFACE)
    res = nights(rows)
    for n in res:
        print(n)
    return res


if __name__ == "__main__":
    main()
