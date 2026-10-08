"""Before/after stills of the Tripo props: the room with the earlier props (`?props=old`) and with the Tripo ones, at the
visual QA's two sizes (1280 and 390), with the page's own loop frozen and both pages stepped alike, so each pair shows the
same moment. Shots: the overview, close-ups of the mug, the headphones on the hook, the sneakers, and him eating the
ramen. Writes docs/design/tripo/<size>_<shot>.webp, each the old frame over (390: beside) the new one. With --set 2 the
second batch (props_tripo2.glb, the car poster) with him at the desk: docs/design/tripo2/.

    python room_build/tripo_stills.py [--set 2|bottle] [--only shot,shot]   # from the repository root; needs what tests/visual needs
"""
import argparse
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.visual.harness import Harness, CHROMIUM          # noqa: E402
from tests.visual.fake_server import Server                 # noqa: E402

OUT = ROOT / "docs/design/tripo"
HOUR = 14
# name -> camera (position, target), or the harness's close-up recipe "hands"
SHOTS = {
    "overview": ((5.2, 5.0, 6.0), (0, 0.6, 0)),
    "mug": ((-0.30, 1.22, -0.62), (-0.50, 1.02, -0.98)),
    "headphones": ((-0.20, 1.45, -0.80), (-0.24, 1.36, -1.40)),
    "sneakers": ((1.05, 0.80, 0.75), (1.70, 0.22, 1.32)),
    "ramen": ((-1.78, 1.62, -0.70), (-1.32, 1.10, -1.00)),   # over his left shoulder, onto the bowl
}
# the second batch: name -> camera; each shot names the props it shows
SHOTS2 = {
    "overview": ((5.2, 5.0, 6.0), (0, 0.6, 0)),
    "desk_monitor_speakers_mouse": ((-1.0, 1.75, -0.25), (-1.05, 1.05, -1.15)),
    "desk_right_console_controller_succulent_speaker": ((-0.35, 1.35, -0.75), (-0.65, 1.05, -1.25)),
    "desk_left_lamp_camera_speaker": ((-1.30, 1.80, -0.62), (-1.66, 1.12, -1.18)),
    "plant": ((-0.90, 1.30, 0.30), (-1.60, 0.50, -0.40)),
    "sill_alarm_figure": ((-1.20, 1.60, 0.50), (-1.87, 1.32, 0.70)),
    "shelf_top_box": ((0.60, 2.60, -0.30), (0.10, 2.20, -1.30)),
    "fridge_cans": ((0.40, 1.90, -0.20), (0.75, 1.30, -1.10)),
    "backpack": ((0.90, 1.20, 0.90), (-0.05, 0.35, 1.24)),
    "door_fan_skateboard_shoeboxes": ((0.70, 1.40, 0.70), (1.60, 0.30, -0.20)),
    "bin": ((-0.30, 0.75, -0.30), (-0.55, 0.30, -1.22)),
    "posters_car": ((-1.20, 1.85, 0.45), (-1.20, 1.85, -1.45)),
}
# the bottle of green tea (--set bottle, ?bottle=old): the desk, a close-up of it in front of the mouse, and him
# drinking from it. `drink` is the forced variant, stepped to the moment the bottle is at his mouth
SHOTS3 = {
    "overview": ((5.2, 5.0, 6.0), (0, 0.6, 0)),
    "desk_bottle": ((-0.50, 1.21, -0.46), (-0.83, 1.03, -0.86)),
    "bottle_close": ((-0.62, 1.12, -0.63), (-0.83, 1.045, -0.85)),
    "drink": "drink",
}
FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)


def label(im, text):
    d = ImageDraw.Draw(im)
    d.rectangle([8, 8, 20 + d.textlength(text, font=FONT), 40], fill=(0, 0, 0))
    d.text((14, 10), text, font=FONT, fill=(255, 255, 255))
    return im


def eating(h, pg, server, what):
    """Him eating the ramen at the desk, the bowl on the table. The harness's snap clears the desk right after act() has
    set the dish out: end the meal with a desk tick and start it again with an eating one."""
    h.goto_scene(pg, "eating", HOUR)
    for sc in ("desk", "eating"):
        server.set_scene(sc, HOUR); pg.wait_for_timeout(1500); pg.evaluate("__qa.step(1/30, 15)")
        if sc == "desk":
            pg.evaluate("__qa.clearFood()")       # the ended meal's bowl stays on the desk until he bins it
    pg.evaluate("__qa.step(1/30, 60); __qa.hud(false)")
    dish = pg.evaluate("(() => { let v = false; scene.traverse(o => { if (o.name === 'F_bowl-broth') { let s = true; "
                       "o.traverseAncestors(a => { if (!a.visible) s = false; }); if (s && o.visible) v = true; } }); return v; })()")
    print(f"{what}: ramen on the table: {dish}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="1", help="1, 2 or bottle")
    ap.add_argument("--only", default="", help="comma-separated shot names to (re)render")
    args = ap.parse_args(); second, bottle = args.set == "2", args.set == "bottle"
    shots_cam, out_dir, old_q = ((SHOTS3, ROOT / "docs/design/prop-bottle", "&bottle=old") if bottle else
                                 (SHOTS2, ROOT / "docs/design/tripo2", "&props=old") if second else
                                 (SHOTS, OUT, "&props=old"))
    if args.only:
        shots_cam = {k: v for k, v in shots_cam.items() if k in args.only.split(",")}
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="tripo_stills_"))
    from playwright.sync_api import sync_playwright
    with Server() as server, sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROMIUM if Path(CHROMIUM).exists() else None,
                                    args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        for size in ("1280", "390"):
            shots = {}
            for tag, q in (("old", old_q), ("new", "")):
                h = Harness(tmp / tag, log=lambda *a: None, cdn_cache=ROOT / "tests/visual/.cdn_cache")
                h.query = q; h.server = server; h.base = server.base; h.browser = browser
                server.set_scene("desk", HOUR)    # a fresh page must start the meal after the harness has cleared the desk
                ctx, pg, st = h.open(size)
                if second or bottle:            # him typing at the desk; neither set has food
                    h.goto_scene(pg, "desk", HOUR)
                    if bottle:                  # park the idle variants (an unknown name does nothing and holds the
                        pg.evaluate("setSeed(1); variant('none', 60)")   # slot), so both pages show the same typing pose
                    pg.evaluate("__qa.step(1/30, 60); __qa.hud(false)")
                else:
                    eating(h, pg, server, f"{size} {tag}")
                for name, cam in shots_cam.items():
                    if cam == "hands":
                        pg.evaluate("__qa.closeup('hands')")
                    elif cam == "drink":        # the forced variant, stepped to where the bottle is at his mouth
                        pg.evaluate("setSeed(1); variant('drink', 7); __qa.step(1/30, 115)")
                        pg.evaluate("(() => { const b = scene.getObjectByName('tea_bottle'); b.updateMatrixWorld(true);"
                                    " const p = new THREE.Vector3().setFromMatrixPosition(b.matrixWorld);"
                                    " camera.position.set(p.x + 0.40, p.y + 0.18, p.z + 0.44); controls.target.copy(p); controls.update(); })()")
                    else:
                        (x, y, z), (a, b, c) = cam
                        pg.evaluate(f"camera.position.set({x}, {y}, {z}); controls.target.set({a}, {b}, {c}); controls.update()")
                    pg.evaluate("__qa.render()")
                    f = tmp / f"{size}_{tag}_{name}.png"
                    pg.screenshot(path=str(f), animations="disabled")
                    shots[(tag, name)] = f
                if st["errors"]:
                    print(f"{size} {tag}: page errors {st['errors'][:3]}")
                ctx.close()
            for name in shots_cam:
                old = label(Image.open(shots[("old", name)]).convert("RGB"), "before")
                new = label(Image.open(shots[("new", name)]).convert("RGB"), "after: Tripo")
                w, hh = old.size
                both = Image.new("RGB", (w, 2 * hh) if size == "1280" else (2 * w, hh))
                both.paste(old, (0, 0)); both.paste(new, (0, hh) if size == "1280" else (w, 0))
                if size == "1280":
                    both = both.resize((w * 3 // 4, hh * 3 // 2))
                both.save(out_dir / f"{size}_{name}.webp", quality=82)
                print(out_dir / f"{size}_{name}.webp")
        browser.close()


if __name__ == "__main__":
    main()
