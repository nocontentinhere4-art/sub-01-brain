"""Pure-image checks of the visual QA harness (issue #98, G8): exposure, flicker (z-fighting), contact sheets.

Everything here works on PNG screenshots with Pillow + numpy; no browser. Used by harness.py and testable on its own.
"""
import numpy as np
from PIL import Image, ImageDraw


def load_rgb(path, crop=None):
    im = Image.open(path).convert("RGB")
    if crop:
        im = im.crop(tuple(crop))
    return np.asarray(im, dtype=np.int16)


def exposure(path, crop=None, black=6, white=250):
    """Fractions of pure-black and blown-out pixels, plus a few luminance statistics, inside `crop` (the 3D canvas)."""
    a = load_rgb(path, crop)
    mx = a.max(axis=2)
    lum = (0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2])
    n = mx.size
    return {"black_frac": round(float((mx <= black).sum() / n), 4), "blown_frac": round(float((a.min(axis=2) >= white).sum() / n), 4),
            "mean_lum": round(float(lum.mean()), 1), "p05_lum": round(float(np.percentile(lum, 5)), 1),
            "p95_lum": round(float(np.percentile(lum, 95)), 1), "pixels": int(n)}


def flicker(paths, crop=None, delta=40, min_flips=2, flat=18):
    """Z-fighting shows as pixels that jump back and forth between two colours from frame to frame. The harness moves
    the camera a little in ONE direction between frames, so a silhouette edge or a specular highlight changes with one
    sign (monotonically), while two coplanar surfaces fighting for the depth buffer flip to and fro. Over N frames a
    pixel is flagged when it changes by more than `delta` (0-255 luminance) between consecutive frames with alternating
    sign at least `min_flips` times AND it sits on a flat patch of the first frame (its 3x3 luminance range below
    `flat`: not an edge). Returns the flagged fraction, the densest 32-px cells and the mask."""
    frames = [load_rgb(p, crop) for p in paths]
    if len(frames) < 3:
        return {"frames": len(frames), "flicker_frac": 0.0, "flagged_pixels": 0, "regions": []}
    lum = [(0.2126 * f[..., 0] + 0.7152 * f[..., 1] + 0.0722 * f[..., 2]) for f in frames]
    diffs = [b - a for a, b in zip(lum, lum[1:])]
    flips = np.zeros(lum[0].shape, dtype=np.int16)
    for d0, d1 in zip(diffs, diffs[1:]):
        flips += ((np.abs(d0) > delta) & (np.abs(d1) > delta) & (np.sign(d0) != np.sign(d1))).astype(np.int16)
    l0 = np.pad(lum[0], 1, mode="edge")
    stack = np.stack([l0[dy:dy + lum[0].shape[0], dx:dx + lum[0].shape[1]] for dy in range(3) for dx in range(3)])
    interior = (stack.max(axis=0) - stack.min(axis=0)) < flat
    mask = (flips >= min_flips) & interior
    frac = float(mask.sum() / mask.size)
    regions = []
    if mask.any():
        h, w = mask.shape
        cell = 32
        dens = mask[:h // cell * cell, :w // cell * cell].reshape(h // cell, cell, w // cell, cell).sum(axis=(1, 3))
        for idx in np.argsort(dens.ravel())[::-1][:5]:
            r, c = divmod(int(idx), dens.shape[1])
            if dens[r, c] < 8:
                break
            regions.append({"box": [c * cell, r * cell, (c + 1) * cell, (r + 1) * cell], "pixels": int(dens[r, c])})
    return {"frames": len(frames), "flicker_frac": round(frac, 5), "flagged_pixels": int(mask.sum()), "regions": regions, "mask": mask}


def specks(path, crop=None, thresh=150, max_area=40, max_box=9, min_fill=0.45):
    """Small bright isolated blobs: pixels brighter than `thresh` (max over RGB), labelled into 8-connected components;
    a component is a speck when it covers at most `max_area` pixels, fits in a `max_box` square and fills at least
    `min_fill` of its bounding box (a disc or a bead, not a thin line). A long thin fibre is not counted, but its bright
    beads and crossings are (the mini brain: ~140 on main), so this is a texture figure rather than a dots detector.
    Returns the count, the centres of the largest 20, the mask and the bright fraction of the frame."""
    from scipy import ndimage
    a = load_rgb(path, crop)
    bright = a.max(axis=2) > thresh
    lab, n = ndimage.label(bright, structure=np.ones((3, 3)))
    out, mask = [], np.zeros(bright.shape, bool)
    if n:
        objs = ndimage.find_objects(lab)
        areas = ndimage.sum(bright, lab, index=np.arange(1, n + 1))
        for i, (sl, area) in enumerate(zip(objs, areas), start=1):
            h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
            if area <= max_area and h <= max_box and w <= max_box and area / (h * w) >= min_fill:
                out.append({"x": int((sl[1].start + sl[1].stop) / 2), "y": int((sl[0].start + sl[0].stop) / 2), "area": int(area)})
                mask[lab == i] = True
    out.sort(key=lambda d: -d["area"])
    return {"specks": len(out), "largest": out[:20], "mask": mask, "bright_frac": round(float(bright.mean()), 4)}


def save_mask(mask, base_path, out_path, crop=None):
    """The first frame with the flagged pixels painted magenta: where the flicker is."""
    im = Image.open(base_path).convert("RGB")
    if crop:
        im = im.crop(tuple(crop))
    a = np.asarray(im).copy()
    a[mask] = (255, 0, 255)
    Image.fromarray(a).save(out_path)


def contact_sheet(items, out_path, cols=4, thumb_w=400, label_h=18):
    """A grid of labelled thumbnails: items = [(label, path)]. JPEG, small enough for docs/."""
    ims = []
    for label, p in items:
        im = Image.open(p).convert("RGB")
        im.thumbnail((thumb_w, thumb_w * 2))
        ims.append((label, im))
    if not ims:
        return None
    th = max(im.height for _, im in ims)
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * thumb_w, rows * (th + label_h)), (12, 12, 16))
    d = ImageDraw.Draw(sheet)
    for i, (label, im) in enumerate(ims):
        r, c = divmod(i, cols)
        x, y = c * thumb_w, r * (th + label_h)
        sheet.paste(im, (x + (thumb_w - im.width) // 2, y + label_h))
        d.text((x + 4, y + 3), label[:60], fill=(220, 220, 230))
    sheet.save(out_path, quality=82)
    return out_path
