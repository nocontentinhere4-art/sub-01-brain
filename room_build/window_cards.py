"""The view out of SUB-01's window (#98 G7): the photographic plates that web/room/window_view.js layers behind the glass.

The owner asked for the most realistic view possible, so the plates are photographs, all CC0, cut out and prepared here:
  sky.webp     1024 x 2304  six real skies from Poly Haven (CC0), one per row: clear, partly cloudy, overcast, sunset, dusk,
                            night; each row is ±70° of azimuth and -2..50° of elevation of the tonemapped equirectangular
                            panorama, with the sun or the moon kept out of the crop (the shader draws its own)
  mid.webp     2048 x 1134  by day: "Suginami City 2024-05-06" (Wikimedia Commons, public domain by its author), the view
                            over the low houses of the ward next to Kichijōji, the sky cut out; 40 m behind the glass
  mid_n.webp   2048 x 1134  at night: "Blue illuminated buildings in Tokyo" (Commons, CC0), the same kind of view with its
                            real lit windows, mapped into the same metre frame; the two cross-fade through the blue hour
  mid_l.webp   2048 x 1134  the night plate's lit windows, found automatically (bright warm blobs), each with an id so that
                            the shader can switch some of them off and on (R pane, G kind, B id; see window_view.js)
  far.webp     2048 x  556  "Illuminated buildings at twilight in Minato-ku, Tokyo, view from Rainbow Bridge" (Commons, CC0;
                            a Pixabay photograph from 2016, when Pixabay's licence was CC0), the sky and the water cut out
  near.webp    1024 x 1024  a utility pole and its cables, drawn as silhouettes (the only drawn plate; nothing else fits)
  noise.webp    256 x  256  G: rain streaks   B, A: raindrop refraction offsets
  plates.json               what was used: source, author, licence, sha1, the metres each plate covers (the shader's LAYERS)

Sources are fetched into room_build/plates/ (not committed; ~120 MB) by `python room_build/window_cards.py --fetch`,
politely (Wikimedia rate-limits shared addresses: one request at a time, backoff on 429). Then:

    python room_build/window_cards.py            # writes web/room/window/* and prints the sizes
    python room_build/window_cards.py --preview  # also room_build/out/window_plates.png

Everything written is deterministic for a given set of sources (no randomness in the photo plates; one fixed seed for the
drawn pole and the noise).
"""
import argparse
import hashlib
import json
import math
import random
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

Image.MAX_IMAGE_PIXELS = None
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "room" / "window"
SRC = ROOT / "room_build" / "plates"
GROUND = -8.2               # the street, metres below the window's centre line (a third-floor room)
SEED = 20261002
BUDGET = 1.5 * 1024 * 1024  # all files together (the task's asset budget)
UA = "SUB01-room-window/1.0 (https://github.com/nocontentinhere4-art/sub-01) python-urllib"

# --- the sources ---------------------------------------------------------------------------------------------------
COMMONS = {
    "mid_day": "File:Suginami_City_2024-05-06.jpg",
    "mid_night": "File:Blue_illuminated_buildings_in_Tokyo.jpg",
    "far": "File:Illuminated_buildings_at_twilight_in_Minato-ku,_Tokyo,_view_from_Rainbow_Bridge_(2016-12-10_by_xegxef_@Pixabay_2086645).jpg",
}
FREE = ("CC0", "PUBLIC DOMAIN")      # licences accepted (free for any use); checked on fetch and recorded in plates.json
# Poly Haven HDRIs (all CC0): id -> (row, the azimuth of the crop's centre in the panorama, degrees from its left edge)
SKIES = [
    ("kloofendal_43d_clear_puresky", 0, 330.0),          # clear day: the blue away from the sun
    ("kloofendal_48d_partly_cloudy_puresky", 1, 320.0),   # partly cloudy day
    ("kloofendal_overcast_puresky", 2, 60.0),             # overcast
    ("belfast_sunset_puresky", 3, 170.0),                 # sunset: the glow lands at +45° in the view, where the sun sets
    ("qwantani_dusk_2_puresky", 4, 160.0),                # dusk, blue hour
    ("kloppenheim_02_puresky", 5, 120.0),                 # a clear night with stars; the moon's glow kept out
]
SKY_W, SKY_H, SKY_AZ, SKY_EL0, SKY_EL1 = 1024, 384, 70.0, -2.0, 50.0

# --- the diorama: what the plates cover, in metres (window_view.js LAYERS must say the same; tests compare plates.json) -----
LAYERS = {
    "near": {"d": 14.0, "xm": 16.0, "y0": -9.0, "y1": 7.0, "cx": 0.0},
    "mid": {"d": 40.0, "xm": 56.0, "y0": -18.0, "y1": 13.0, "cx": 4.0},      # 2048 x 1134 (36.6 px/m); the horizon at y = 0
    "far": {"d": 200.0, "xm": 48.0, "y0": -1.0, "y1": 11.8, "cx": 8.0},       # 2048 x 546 (42.7 px/m); the skyline's foot at -1.0
}
MID_PX = (2048, 1134)
# where each photograph's horizon is (fraction of its height from the top) and how much of its width is kept (x0, x1)
PHOTOS = {"mid_day": {"horizon": 0.412, "x": (0.0, 1.0)}, "mid_night": {"horizon": 0.552, "x": (0.0, 1.0), "top": 0.22},
          "far": {"horizon": 0.625, "x": (0.0, 0.58), "top": 0.0}}


def http(url, tries=8):
    delay = 6
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503):
                raise
            print(f"  {e.code}, waiting {delay:.0f} s", flush=True)
        time.sleep(delay); delay = min(90, delay * 1.7)
    raise RuntimeError("gave up: " + url)


def fetch():
    """the sources into room_build/plates/, with their licence metadata (Commons: extmetadata; Poly Haven: /info)"""
    SRC.mkdir(parents=True, exist_ok=True)
    meta = json.loads((SRC / "meta.json").read_text()) if (SRC / "meta.json").exists() else {}
    for key, title in COMMONS.items():
        if key in meta and (SRC / f"{key}.jpg").exists():
            continue
        q = urllib.parse.urlencode({"action": "query", "titles": title, "prop": "imageinfo", "iiprop": "url|extmetadata|size|sha1",
                                    "iiurlwidth": "2560", "format": "json"})
        print("commons", title[:70], flush=True)
        page = next(iter(json.loads(http("https://commons.wikimedia.org/w/api.php?" + q))["query"]["pages"].values()))
        ii = page["imageinfo"][0]; em = ii.get("extmetadata", {})
        g = lambda k: (em.get(k, {}).get("value") or "")
        lic = g("LicenseShortName")
        assert any(k in lic.upper() for k in FREE), f"{title}: licence is {lic!r}, not CC0 / public domain"
        meta[key] = {"title": page["title"], "page": ii["descriptionurl"], "license": lic, "license_url": g("LicenseUrl"),
                     "artist_html": g("Artist"), "credit_html": g("Credit"), "width": ii["width"], "height": ii["height"],
                     "sha1": ii["sha1"], "fetched": ii.get("thumburl") or ii["url"]}
        time.sleep(4)
        (SRC / f"{key}.jpg").write_bytes(http(meta[key]["fetched"]))
        (SRC / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
        time.sleep(4)
    for sid, _, _ in SKIES:
        if sid in meta and (SRC / f"{sid}.jpg").exists():
            continue
        print("polyhaven", sid, flush=True)
        info = json.loads(http(f"https://api.polyhaven.com/info/{sid}"))
        meta[sid] = {"title": info.get("name"), "page": f"https://polyhaven.com/a/{sid}", "license": "CC0",
                     "license_url": "https://polyhaven.com/license", "authors": info.get("authors", {}),
                     "fetched": f"https://dl.polyhaven.org/file/ph-assets/HDRIs/extra/Tonemapped%20JPG/{sid}.jpg"}
        (SRC / f"{sid}.jpg").write_bytes(http(meta[sid]["fetched"]))
        (SRC / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    return meta


def sources_ready():
    return (SRC / "meta.json").exists() and all((SRC / f"{k}.jpg").exists() for k in list(COMMONS) + [s[0] for s in SKIES])


# --- helpers -------------------------------------------------------------------------------------------------------
def sky_mask(img, max_row=None, grad_tol=9.0, blur=1.2, feather=1.5, seed_rows=3, erode=1):
    """1 where the sky is: the region of low local gradient connected to the top of the picture (clouds and twilight
    gradients are smooth; the skyline is an edge), limited to rows above `max_row`, eroded one pixel and feathered"""
    from scipy import ndimage
    g = np.asarray(img.convert("L").filter(ImageFilter.GaussianBlur(blur))).astype(np.float32)
    H, W = g.shape
    max_row = H if max_row is None else max_row
    gx = np.zeros_like(g); gy = np.zeros_like(g)
    gx[:, 1:] = np.abs(np.diff(g, axis=1)); gy[1:, :] = np.abs(np.diff(g, axis=0))
    low = np.maximum(gx, gy) < grad_tol
    low[max_row:] = False
    lab, n = ndimage.label(low)
    top_ids = np.unique(lab[:seed_rows]); top_ids = top_ids[top_ids > 0]
    sky = np.isin(lab, top_ids)
    sky[max_row:] = False
    # islands in the sky (clouds with edges, specks) are not buildings: only what connects to the ground stays
    obj = ~sky; obj[max_row:] = True
    lab2, n2 = ndimage.label(obj)
    ground_ids = np.unique(lab2[max_row - 1]) if max_row <= H else np.unique(lab2[-1]); ground_ids = ground_ids[ground_ids > 0]
    sky = ~np.isin(lab2, ground_ids)
    sky[max_row:] = False
    sky = ndimage.binary_closing(sky, iterations=2)                 # jpeg speckle inside the sky
    sky = ndimage.binary_erosion(sky, iterations=erode)             # keep the halo off the skyline
    m = Image.fromarray((sky * 255).astype(np.uint8), "L")
    if feather:
        m = m.filter(ImageFilter.GaussianBlur(feather))
    return np.asarray(m).astype(np.float32) / 255


def cutout(img, mask, target_w):
    """RGBA: the photograph with the sky's alpha removed, premultiplied-resized to target_w (no bright fringes)"""
    a = np.asarray(img.convert("RGB")).astype(np.float32)
    al = (1 - mask)[..., None]
    pre = np.concatenate([a * al, al * 255], -1).astype(np.uint8)
    im = Image.fromarray(pre, "RGBA")
    h = round(im.height * target_w / im.width)
    im = im.resize((target_w, h), Image.LANCZOS)
    q = np.asarray(im).astype(np.float32); a2 = np.maximum(q[..., 3:4], 1) / 255
    return Image.fromarray(np.concatenate([np.clip(q[..., :3] / a2, 0, 255), q[..., 3:4]], -1).astype(np.uint8), "RGBA")


def fade_edges(im, px=48):
    """alpha fades to 0 over the left and right edges (the shader clamps: beyond the plate the sky shows)"""
    a = np.asarray(im).copy()
    ramp = np.clip(np.arange(a.shape[1]) / px, 0, 1); ramp = np.minimum(ramp, ramp[::-1])
    a[..., 3] = (a[..., 3] * ramp[None, :]).astype(np.uint8)
    return Image.fromarray(a, "RGBA")


def equirect_crop(img, center_az, half_az=SKY_AZ, el0=SKY_EL0, el1=SKY_EL1, size=(SKY_W, SKY_H)):
    """a window of azimuth [center-half, center+half] x elevation [el0, el1] from an equirectangular panorama"""
    W, H = img.size
    x0 = (center_az - half_az) / 360 * W; x1 = (center_az + half_az) / 360 * W
    y0 = (90 - el1) / 180 * H; y1 = (90 - el0) / 180 * H
    # the crop may cross the seam: roll the image first
    shift = int(round(-x0)) if x0 < 0 else (-int(round(x1 - W)) if x1 > W else 0)
    if shift:
        a = np.asarray(img); img = Image.fromarray(np.roll(a, shift, axis=1)); x0 += shift; x1 += shift
    return img.crop((int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1)))).resize(size, Image.LANCZOS)


# --- the drawn plate: the utility pole and its cables ---------------------------------------------------------------
def card_near(rng):
    """the utility pole and its cables, 14 m out: real cables are 1-2 cm thick, so at 4x supersampling they are drawn
    as hairlines of varied sag and height that downsample to soft, anti-aliased strands (G8 defect 26: they read as
    drawn lines when they were 3 cm thick, identical and aliased)"""
    W = H = 1024; ss = 4
    img = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    L = LAYERS["near"]; sx = W * ss / L["xm"]; sy = H * ss / (L["y1"] - L["y0"])
    px = lambda x: x * sx; py = lambda y: (L["y1"] - y) * sy
    def rect(x0, y0, x1, y1, c, a=255):
        for dx in (0, -L["xm"], L["xm"]):
            b = [px(x0 + dx), py(y1), px(x1 + dx), py(y0)]
            if b[2] < 0 or b[0] > W * ss: continue
            d.rectangle([round(b[0]), round(b[1]), max(round(b[0]), round(b[2]) - 1), max(round(b[1]), round(b[3]) - 1)], fill=(*c, a))
    def line(pts, c, w_m, a=255):
        for dx in (0, -L["xm"], L["xm"]):
            d.line([(px(x + dx), py(y)) for x, y in pts], fill=(*c, a), width=max(1, round(w_m * sx)))
    x, base, top = 12.3, L["y0"], GROUND + 10.4
    pole = (112, 110, 106); dark = (70, 68, 66)
    rect(x - 0.15, base, x + 0.15, top, pole); rect(x + 0.07, base, x + 0.15, top, dark)
    for yy in (top - 0.5, top - 1.4):                            # cross-arms with insulators
        rect(x - 1.0, yy, x + 1.0, yy + 0.08, dark)
        for i in range(5):
            xx = x - 0.9 + 0.45 * i
            rect(xx - 0.05, yy + 0.08, xx + 0.05, yy + 0.28, (140, 140, 138))
    rect(x + 0.2, top - 2.8, x + 0.95, top - 1.95, (98, 98, 96)); rect(x + 0.25, top - 1.95, x + 0.9, top - 1.8, dark)   # transformers
    rect(x - 0.85, top - 2.5, x - 0.2, top - 1.65, (98, 98, 96))
    # the cables: a bundle of five from the upper arm, two from the lower, each with its own sag and a slight slant
    r2 = random.Random(SEED + 7)
    for y0, sag, w in ((GROUND + 9.9, 0.52, 0.016), (GROUND + 9.72, 0.46, 0.014), (GROUND + 9.55, 0.58, 0.012), (GROUND + 9.3, 0.41, 0.014),
                       (GROUND + 9.0, 0.49, 0.012), (GROUND + 8.35, 0.33, 0.011), (GROUND + 8.1, 0.38, 0.010)):
        slant = r2.uniform(-0.12, 0.12)
        pts = [(L["xm"] * t / 128, y0 + slant * (t / 128 - 0.5) - sag * math.sin(math.pi * t / 128) ** 2) for t in range(129)]
        line(pts, (22, 22, 24), w, a=235)
    # a little grain so the silhouettes do not read as vector art
    a = np.asarray(img).astype(np.float32)
    g = np.random.default_rng(rng.randrange(1 << 30)).random((H * ss, W * ss, 1)).astype(np.float32)
    a[..., :3] *= 0.92 + 0.16 * g
    img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA")
    al = np.asarray(img).astype(np.float32); alpha = al[..., 3:4] / 255
    pre = Image.fromarray(np.concatenate([al[..., :3] * alpha, al[..., 3:4]], -1).astype(np.uint8), "RGBA").resize((W, H), Image.LANCZOS)
    q = np.asarray(pre).astype(np.float32); a2 = np.maximum(q[..., 3:4], 1) / 255
    return Image.fromarray(np.concatenate([np.clip(q[..., :3] / a2, 0, 255), q[..., 3:4]], -1).astype(np.uint8), "RGBA")


def noise_tex(rng):
    """R unused; G: rain streaks; B, A: the refraction offset of raindrops on the glass (128 = none)"""
    S = 256
    g = np.zeros((S, S), np.float32)
    for _ in range(46):
        x0 = int(rng.uniform(0, S)); y0 = int(rng.uniform(0, S)); ln = int(rng.uniform(40, 170)); wd = 1 if rng.random() < 0.7 else 2
        for k in range(ln):
            v = (k / ln) ** 0.6 * rng.uniform(0.8, 1.0)
            for j in range(wd):
                g[(y0 + k) % S, (x0 + j) % S] = max(g[(y0 + k) % S, (x0 + j) % S], v)
    ox = np.zeros((S, S), np.float32); oy = np.zeros((S, S), np.float32)
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    for _ in range(34):
        cx, cy = rng.uniform(0, S), rng.uniform(0, S); rad = rng.uniform(3, 10)
        for dx in (-S, 0, S):
            for dy in (-S, 0, S):
                px, py = xx - (cx + dx), yy - (cy + dy)
                dd = np.sqrt(px * px + py * py) / rad
                m = np.clip(1 - dd, 0, 1)
                prof = np.sin(np.pi * np.clip(dd, 0, 1)) * (0.4 + 0.6 * m)
                ox += np.where(dd < 1, px / rad * prof, 0); oy += np.where(dd < 1, py / rad * prof, 0)
    ox = np.clip(ox, -1, 1); oy = np.clip(oy, -1, 1)
    tex = np.stack([np.zeros_like(g), g, 0.5 + 0.5 * ox, 0.5 + 0.5 * oy], -1)
    return Image.fromarray((tex * 255).astype(np.uint8), "RGBA")


# --- the photographs -----------------------------------------------------------------------------------------------
def into_frame(img, horizon_frac, layer, size, x_keep=(0.0, 1.0), top=0.0, mask=None):
    """map a photograph into the layer's metre frame: its horizon row lands on y = 0, its kept width fills the frame's
    width; rows above `top` are dropped first. Returns the RGB plate at `size` (black where the photo does not reach) and,
    if `mask` is a function(resized photo, horizon row) -> float mask, that mask framed the same way (sky = 1 outside)."""
    W, H = img.size
    img = img.crop((int(W * x_keep[0]), int(H * top), int(W * x_keep[1]), H))
    hz = (horizon_frac - top) / (1 - top)                              # the horizon in the cropped image
    tw, th = size
    ppm = tw / layer["xm"]                                             # pixels per metre
    im = img.resize((tw, max(1, round(img.height * tw / img.width))), Image.LANCZOS)
    hz_row = int(hz * im.height)                                       # where y = 0 is in the resized photo
    y0_row = round(layer["y1"] * ppm - hz_row)                         # the photo's top row in the frame
    out = Image.new("RGB", (tw, th), (0, 0, 0)); out.paste(im, (0, y0_row))
    if mask is None:
        return out, None
    mk = mask(im, hz_row)
    full = np.ones((th, tw), np.float32)
    ys, ye = max(0, y0_row), min(th, y0_row + mk.shape[0])
    full[ys:ye] = mk[ys - y0_row:ye - y0_row]
    return out, full


def photo_plate(src, key, layer, size, grad_tol, feather, mask_max=0.95, erode=1, horizon_fade=0):
    """a photograph in the layer's frame with its sky removed; `horizon_fade` px: the hazy distance just above the
    horizon fades into the sky instead of ending on a line"""
    spec = PHOTOS[key]
    img = Image.open(src).convert("RGB")
    framed, m = into_frame(img, spec["horizon"], layer, size, spec["x"], spec.get("top", 0.0),
                           mask=lambda im, hz: sky_mask(im, max_row=int(hz * mask_max), grad_tol=grad_tol, feather=feather, erode=erode))
    if horizon_fade:
        hz_row = int(layer["y1"] / (layer["y1"] - layer["y0"]) * size[1])
        rows = np.arange(size[1])
        ramp = np.clip((rows - (hz_row - horizon_fade)) / horizon_fade, 0, 1)[:, None].astype(np.float32)
        m = np.maximum(m, 1 - ramp)
    return fade_edges(cutout(framed, m, size[0]), 40), m


def night_lights(night_rgba, min_area=3, max_area=260, lum=0.52):
    """the lit windows of the night photograph: bright blobs, each its own id (R coverage, G kind 0, B id)"""
    from scipy import ndimage
    a = np.asarray(night_rgba).astype(np.float32) / 255
    l = a[..., 0] * 0.35 + a[..., 1] * 0.5 + a[..., 2] * 0.15
    bright = (l > lum) & (a[..., 3] > 0.5)
    lab, n = ndimage.label(bright)
    sizes = ndimage.sum(bright, lab, range(1, n + 1))
    keep = np.zeros(n + 1, bool); keep[1:] = (sizes >= min_area) & (sizes <= max_area)
    ids = np.where(keep[lab], (lab % 250) + 1, 0)
    mask = np.zeros(a.shape[:2] + (3,), np.uint8)
    mask[..., 0] = np.where(ids > 0, 255, 0); mask[..., 2] = ids
    return Image.fromarray(mask, "RGB"), int(keep.sum())


def sky_atlas():
    atlas = Image.new("RGB", (SKY_W, SKY_H * len(SKIES)))
    for sid, row, center in SKIES:
        pan = Image.open(SRC / f"{sid}.jpg").convert("RGB")
        atlas.paste(equirect_crop(pan, center), (0, row * SKY_H))
    return atlas


def build(preview=False):
    if not sources_ready():
        print("sources missing: python room_build/window_cards.py --fetch", file=sys.stderr); sys.exit(2)
    OUT.mkdir(parents=True, exist_ok=True)
    meta = json.loads((SRC / "meta.json").read_text())
    rng = random.Random(SEED)
    files, made = {}, {}
    def save(name, im, **kw):
        im.save(OUT / name, "WEBP", method=6, **kw); files[name] = (OUT / name).stat().st_size; made[name] = im
    mid, mid_mask = photo_plate(SRC / "mid_day.jpg", "mid_day", LAYERS["mid"], MID_PX, grad_tol=7.0, feather=1.2, mask_max=0.985, horizon_fade=28)
    save("mid.webp", mid, quality=78)
    midn, midn_mask = photo_plate(SRC / "mid_night.jpg", "mid_night", LAYERS["mid"], MID_PX, grad_tol=6.0, feather=1.5, mask_max=0.99)
    save("mid_n.webp", midn, quality=72)
    lights, n_lights = night_lights(midn)
    save("mid_l.webp", lights, lossless=True)
    print(f"lit windows found in the night photograph: {n_lights}")
    far, far_mask = photo_plate(SRC / "far.jpg", "far", LAYERS["far"], (2048, 546), grad_tol=6.0, feather=2.0, mask_max=0.99, erode=2)
    save("far.webp", far, quality=75)
    save("sky.webp", sky_atlas(), quality=80)
    save("near.webp", card_near(random.Random(rng.randrange(1 << 30))), quality=85)
    save("noise.webp", noise_tex(np.random.default_rng(SEED)), lossless=True)
    plates = {"layers": LAYERS, "sky": {"rows": [s[0] for s in SKIES], "az": SKY_AZ, "el0": SKY_EL0, "el1": SKY_EL1, "size": [SKY_W, SKY_H]},
              "sizes": {k: list(v.size) for k, v in made.items()}, "bytes": files,
              "sources": {k: {kk: vv for kk, vv in v.items() if kk not in ("artist_html", "credit_html")} | {"artist": strip_html(v.get("artist_html", "")), "credit": strip_html(v.get("credit_html", ""))}
                          if "artist_html" in v else v for k, v in meta.items() if k in COMMONS or k in {sid for sid, _, _ in SKIES}}}
    (OUT / "plates.json").write_text(json.dumps(plates, indent=1, ensure_ascii=False) + "\n")
    files["plates.json"] = (OUT / "plates.json").stat().st_size
    total = sum(files.values())
    for k, v in files.items():
        print(f"{k:<14} {v / 1024:7.1f} KB")
    print(f"{'total':<14} {total / 1024:7.1f} KB  (budget {BUDGET / 1024:.0f} KB)")
    if preview:
        out = ROOT / "room_build" / "out"; out.mkdir(exist_ok=True)
        def over(im, col=(90, 140, 210)):
            bg = Image.new("RGBA", im.size, (*col, 255)); bg.alpha_composite(im); return bg.convert("RGB")
        h = mid.height // 2
        sheet = Image.new("RGB", (2048, h + far.height // 2 + 1024 // 2 + 40), (20, 20, 24))
        sheet.paste(over(mid).resize((1024, h)), (0, 0)); sheet.paste(over(midn, (30, 40, 70)).resize((1024, h)), (1024, 0))
        sheet.paste(over(far, (60, 40, 90)).resize((1024, far.height // 2)), (0, h + 10))
        sheet.paste(lights.resize((1024, far.height // 2)), (1024, h + 10))
        sheet.paste(over(made["near.webp"]).resize((512, 512)), (0, h + far.height // 2 + 20))
        sheet.paste(made["sky.webp"].resize((1024, 512)), (1024, h + far.height // 2 + 20))
        sheet.save(out / "window_plates.png")
        for nm, mk in (("mid_mask", mid_mask), ("midn_mask", midn_mask), ("far_mask", far_mask)):
            Image.fromarray((mk * 255).astype(np.uint8)).save(out / f"{nm}.png")
        print(f"preview: {out / 'window_plates.png'}")
    return files


def strip_html(s):
    import re
    return re.sub(r"<[^>]+>", "", s).strip()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="download the sources into room_build/plates/ (checks each licence)")
    ap.add_argument("--preview", action="store_true")
    a = ap.parse_args()
    if a.fetch:
        fetch()
    f = build(a.preview)
    if sum(f.values()) > BUDGET:
        print("OVER BUDGET", file=sys.stderr); sys.exit(1)
