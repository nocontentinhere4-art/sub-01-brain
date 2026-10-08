"""CI entry of the visual QA suite (issue #98, G8): the core set of fixed-camera shots of /room with the automated
checks. Skipped where headless Chromium or Playwright is missing (like the other browser tests); set SUB01_VISUAL=1 to
make a skip an error instead. Only hard errors fail (see harness.py); the rest is in the run's report.md, which CI keeps
as an artifact. The heavy set (every scene x hour x size) is opt-in: SUB01_VISUAL_FULL=1, or `--full` by hand."""
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from tests.visual import harness as H          # noqa: E402
from tests.visual import image_checks as IC    # noqa: E402

OUT = Path(os.environ.get("SUB01_VISUAL_OUT", HERE / "out"))


def _skip_unless_browser():
    if H.chromium_ok():
        return
    if os.environ.get("SUB01_VISUAL"):
        pytest.fail("SUB01_VISUAL=1 but playwright / chromium are not available")
    pytest.skip("playwright / chromium not installed")


@pytest.fixture(scope="module")
def run():
    _skip_unless_browser()
    full = bool(os.environ.get("SUB01_VISUAL_FULL"))
    try:
        return H.Harness(OUT, full=full, log=lambda *a: print(*a, flush=True)).run()
    except Exception as e:                                    # a browser that does not start here (no GL, no /dev/shm): skip, as test_browse.py does
        if "chromium" in repr(e).lower() or "browser" in repr(e).lower():
            pytest.skip(f"chromium did not start: {e!r}"[:200])
        raise


def test_room_renders_without_hard_errors(run):
    """The page loads, no JS error, no failed own-origin request, every scene reached, no blank canvas, bed/chair
    penetration within budgets.json."""
    assert run["hard_failures"] == [], "\n".join(run["hard_failures"])


def test_every_core_scene_was_shot(run):
    names = {r["scene"] for r in run["shots"].values()}
    assert names >= {"desk", "eating", "phone", "sleeping", "walking", "door", "window"}
    for k, r in run["shots"].items():
        assert (OUT / f"{k}.png").exists() and (OUT / f"{k}_clean.png").exists(), k
    assert set(run["closeups"]) >= {"face", "hands", "feet", "socks", "desk", "bed"}


def test_mini_brain_was_checked(run):
    """The room's PiP brain (#116: /brain?mini without neurons=1) rendered its fibres, with no neuron forest and no dots."""
    p = run["pip"]
    assert p["started"] and (OUT / "pip_mini_brain.png").exists()
    assert p["render"]["forest"] is False and p["render"]["points"] == 0
    assert p["embed_src"].startswith("/brain?mini") and "neurons=1" not in p["embed_src"]


def test_report_written(run):
    assert (OUT / "report.md").exists() and (OUT / "results.json").exists()


# ---- the image checks on their own (no browser)
def test_exposure_and_flicker_on_synthetic_frames(tmp_path):
    import numpy as np
    from PIL import Image
    a = np.full((64, 64, 3), 128, np.uint8); a[:8] = 0; a[-8:] = 255
    Image.fromarray(a).save(tmp_path / "a.png")
    e = IC.exposure(tmp_path / "a.png")
    assert abs(e["black_frac"] - 0.125) < 1e-6 and abs(e["blown_frac"] - 0.125) < 1e-6
    # a flat patch flipping between two colours every frame = z-fighting; a moving edge = not
    frames = []
    for i in range(5):
        f = np.full((64, 64, 3), 100, np.uint8)
        f[20:30, 20:30] = 200 if i % 2 else 40                 # the fight
        f[:, 40 + i] = 255                                      # an edge that creeps one way
        p = tmp_path / f"f{i}.png"; Image.fromarray(f).save(p); frames.append(p)
    r = IC.flicker(frames)
    assert r["flagged_pixels"] >= 60 and r["regions"], r
    ys, xs = np.nonzero(r["mask"])
    assert xs.min() >= 19 and xs.max() <= 30, "only the flipping patch is flagged, not the moving edge"
