"""The room's raycasts see the room as it is (2026-10-07, the freeze investigation): camRoom() builds a bounding-volume
tree on every room mesh from the first frame, and the keyboard cut (splitBox) and cutBox re-index room_static after
that. A tree built on the old index made raycasts miss what was re-indexed: the visual checks' desk columns found 3794
surfaces where there are 5124, so the desk check passed walking_8 and eating_19 with a forearm in the desk. Through
the page's trees a raycast must find what one without them finds.
Skipped where headless Chromium or Playwright is missing, like test_visual.py."""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from tests.visual import harness as H          # noqa: E402
from tests.visual.fake_server import Server    # noqa: E402

COLUMNS = """() => { const st = room.getObjectByName('room_static'), ms = []; st.traverse(m => { if (m.isMesh) ms.push(m); });
  const cnt = c => c.cols.reduce((s, x) => s + (x ? x.length : 0), 0);
  const trees = ms.filter(m => m.geometry.boundsTree).length;
  const through = cnt(__qa.columns('desk_trees', -1.92, -0.30, -1.47, -0.72));
  const saved = ms.map(m => m.geometry.boundsTree); ms.forEach(m => { m.geometry.boundsTree = undefined; });
  const plain = cnt(__qa.columns('desk_plain', -1.92, -0.30, -1.47, -0.72));
  ms.forEach((m, i) => { m.geometry.boundsTree = saved[i]; });
  return {trees, of: ms.length, through, plain}; }"""


def test_raycasts_through_the_rooms_trees_see_the_whole_room(tmp_path):
    if not H.chromium_ok():
        pytest.skip("playwright / chromium not installed")
    from playwright.sync_api import sync_playwright
    h = H.Harness(tmp_path, log=lambda *a: None)
    with Server() as server, sync_playwright() as p:
        h.server = server; h.base = server.base
        exe = H.CHROMIUM if Path(H.CHROMIUM).exists() else None      # (the harness's rule: CI has Playwright's own Chromium)
        h.browser = p.chromium.launch(executable_path=exe, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        ctx, pg, st = h.open("1280")                                   # (the page ran live through its boot: camRoom built its trees)
        r = pg.evaluate(COLUMNS)
        h.browser.close()
    assert r["trees"] > 0, r                                           # (the trees are there: this checks them, not their absence)
    assert r["through"] == r["plain"], r
