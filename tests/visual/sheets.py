"""Contact sheets for docs/qa/ from a harness run (issue #98, G8): small JPEGs that the scorecard can point at.

    python -m tests.visual.sheets --run tests/visual/out/full --out docs/qa/shots

Three sheets: the activities (one per scene at its natural hour, the page as viewers see it), the hours (two scenes
across 8/14/19/23, the 3D view alone) and the close-ups. Only these go into git; the run's PNGs never do.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from tests.visual import image_checks as IC   # noqa: E402
from tests.visual import scenes as S          # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="tests/visual/out")
    ap.add_argument("--out", default="docs/qa/shots")
    args = ap.parse_args()
    run, out = Path(args.run), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    res = json.loads((run / "results.json").read_text())
    have = lambda n: (run / n).exists()                    # noqa: E731

    acts = [(f"{s} @ {S.NATURAL_HOUR[s]}:00", run / f"{s}_{S.NATURAL_HOUR[s]}_1280.png") for s in S.SCENES if have(f"{s}_{S.NATURAL_HOUR[s]}_1280.png")]
    acts += [(f"{s} @ {S.NATURAL_HOUR[s]}:00, him", run / f"{s}_{S.NATURAL_HOUR[s]}_1280_char.png") for s in S.SCENES if have(f"{s}_{S.NATURAL_HOUR[s]}_1280_char.png")]
    IC.contact_sheet(acts, out / "activities.jpg", cols=4, thumb_w=440)

    hours = []
    for s in ("desk", "sleeping", "window"):
        for h in S.HOURS:
            n = f"{s}_{h}_1280_clean.png"
            if have(n):
                hours.append((f"{s} @ {h}:00", run / n))
    if hours:
        IC.contact_sheet(hours, out / "hours.jpg", cols=4, thumb_w=440)

    closeups = [(f"{k} ({v['scene']} @ {v['hour']}:00)", run / f"closeup_{k}_{v['hour']}.png") for k, v in res.get("closeups", {}).items()
                if have(f"closeup_{k}_{v['hour']}.png")]
    if closeups:
        IC.contact_sheet(closeups, out / "closeups.jpg", cols=3, thumb_w=440)

    phones = [(f"{k}", run / f"{k}.png") for k in res["shots"] if k.endswith("_390") and have(f"{k}.png")]
    if phones:
        IC.contact_sheet(phones[:8], out / "phone.jpg", cols=4, thumb_w=300)
    for p in sorted(out.glob("*.jpg")):
        print(p, f"{p.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
