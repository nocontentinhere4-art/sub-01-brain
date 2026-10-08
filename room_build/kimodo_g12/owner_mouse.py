"""python3 owner_mouse.py <mouse_overhead_landmarks.json> <mouse_front_landmarks.json> <out.json>

The owner's right hand on his mouse (data/owner-typing, mocap_src/owner_typing/: MediaPipe's 21 landmarks per frame,
the take from straight above) as the page's mouse hand (web/room/boy_mh.js, mouseHold):

  d     per frame, each finger and thumb segment's direction in his palm's own frame: h = wrist (0) -> middle knuckle (9),
        l = index knuckle (5) -> little knuckle (17) square to h, n = h x l. The page builds the same frame from the
        character's bones (hand -> finger3-1, finger2-1 -> finger5-1) and aims each finger bone along these.
        Thumb finger1-1 1->2, 1-2 2->3, 1-3 3->4; finger i (2 index .. 5 little) i-1 MCP->PIP, i-2 PIP->DIP, i-3 DIP->tip.
        (The page leaves the thumb's root, finger1-1, as recorded and uses 1-2 and 1-3: see mouseHold.)
  hand  per frame, h and l in the desk's axes (forward, his right, up). The page takes h from it and the roll from
        the front take (below).
  move  per frame, the wrist's travel over the pad (forward, his right) about its mean, in palm widths (his 5 -> 17 in
        the image, the median over the take); the page multiplies by the character's own palm width.

The take's camera (from the landmarks, not assumed): his fingers point to image -x, his thumb to +y, the camera looks
down, so forward = -x, his right = -y, up = -z (MediaPipe's world axes are the camera's).
The hand's roll (about h) is taken from the front take, not this one: from straight above, its depth (MediaPipe's
weak axis) puts the roll at 31 deg. From the front, roll lies in the image plane. Two witnesses there give the band:
  - the index -> little knuckle line's angle in the image (median 14 deg);
  - that line's angle below horizontal in the world landmarks (median 21 deg).
The base is the median of the palm's anatomical roll (5 -> 17 square to h, against horizontal), 19 deg. The front
take's own up/down sign is not trusted (its video may be turned); the side that is up, the thumb's, is this take's.
The tracker's frame-to-frame noise (median 1 deg, p90 2-3.6 deg per segment) is taken out by a Gaussian of one frame.
The take loops: its last XF seconds are crossfaded into its first, so the last frame runs on into the first.
The page plays it at 0.75 of his speed (SPEED).
"""
import json
import sys

import numpy as np

XF = 1.0         # crossfade, seconds of the take
SPEED = 0.75     # the page's playback speed
SEG = [(1, 2), (2, 3), (3, 4)] + [(b + k, b + k + 1) for b in (5, 9, 13, 17) for k in range(3)]


def unit(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def gauss(x, sigma=1.0):        # along axis 0, edges held
    r = int(3 * sigma)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    pad = np.concatenate([x[:1].repeat(r, 0), x, x[-1:].repeat(r, 0)])
    return sum(k[i] * pad[i:i + len(x)] for i in range(2 * r + 1))


def front_roll(src):
    """the front take's roll witnesses, degrees: (base, [band lo, band hi])"""
    d = json.load(open(src))
    fr = [f for f in d["frames"] if f["hands"]]
    W = np.array([f["hands"][0]["world"] for f in fr], float)
    P = np.array([f["hands"][0]["img"] for f in fr], float)[:, :, :2] * np.array(d["size"], float)
    img = abs(np.median(np.degrees(np.arctan2(P[:, 17, 1] - P[:, 5, 1], np.abs(P[:, 17, 0] - P[:, 5, 0])))))
    l = W[:, 17] - W[:, 5]
    world = abs(np.median(np.degrees(np.arcsin(l[:, 1] / np.linalg.norm(l, axis=1)))))
    h = unit(W[:, 9] - W[:, 0])
    la = unit(l - (l * h).sum(1, keepdims=True) * h)
    base = abs(np.median(np.degrees(np.arcsin(la[:, 1]))))
    return float(base), sorted([float(img), float(world)])


def main(src, front, out):
    d = json.load(open(src))
    fr = [f for f in d["frames"] if f["hands"]]
    assert len(fr) == len(d["frames"]), "a frame without the hand"
    W = np.array([f["hands"][0]["world"] for f in fr], float)
    I = np.array([f["hands"][0]["img"] for f in fr], float)[:, :, :2] * np.array(d["size"], float)   # (pixels)
    fps = float(d["video_fps"])

    cam = np.diag([-1.0, -1.0, -1.0])   # camera -> desk (forward, right, up): see above
    h = unit(W[:, 9] - W[:, 0])
    l = W[:, 17] - W[:, 5]
    l = unit(l - (l * h).sum(1, keepdims=True) * h)
    n = np.cross(h, l)
    seg = unit(np.stack([W[:, b] - W[:, a] for a, b in SEG], 1))
    d_palm = np.stack([(seg * h[:, None]).sum(2), (seg * l[:, None]).sum(2), (seg * n[:, None]).sum(2)], 2)
    # each finger's spread from the middle finger (its first segment's turn in the palm's plane) from the image, not the
    # world landmarks, which fan them out in depth: index / ring / little 26 / 23 / 31 deg there, 14 / 9 / 8 in the
    # image. The finger's three segments turned about n by the difference (the image's plane: the camera looks down the
    # palm's normal, n's angles and the image's turn the same way)
    spread = {}
    for i, (a, b) in ((2, (5, 6)), (4, (13, 14)), (5, (17, 18))):
        m, f = I[:, 10] - I[:, 9], I[:, b] - I[:, a]
        s_img = np.arctan2(m[:, 0] * f[:, 1] - m[:, 1] * f[:, 0], (m * f).sum(1))
        m2, f2 = d_palm[:, 6, :2], d_palm[:, (i - 1) * 3, :2]
        s_w = np.arctan2(m2[:, 0] * f2[:, 1] - m2[:, 1] * f2[:, 0], (m2 * f2).sum(1))
        c, sn = np.cos(s_img - s_w)[:, None], np.sin(s_img - s_w)[:, None]
        for k in range(3):
            x, y = d_palm[:, (i - 1) * 3 + k, 0].copy()[:, None], d_palm[:, (i - 1) * 3 + k, 1].copy()[:, None]
            d_palm[:, (i - 1) * 3 + k, 0], d_palm[:, (i - 1) * 3 + k, 1] = (x * c - y * sn)[:, 0], (x * sn + y * c)[:, 0]
        spread[i] = (np.degrees(np.median(np.abs(s_w))), np.degrees(np.median(np.abs(s_img))))
    hand = np.concatenate([h @ cam.T, l @ cam.T], 1)
    palm_px = float(np.median(np.linalg.norm(I[:, 17] - I[:, 5], axis=1)))
    wr = I[:, 0] - I[:, 0].mean(0)
    move = np.stack([-wr[:, 0], -wr[:, 1]], 1) / palm_px

    d_palm, hand, move = gauss(d_palm), gauss(hand), gauss(move)

    # the loop: frames [0, N - x) play; the first x are blended from the tail (N - x + i) into the head (i)
    N, x = len(W), int(round(XF * fps))
    a = 0.5 - 0.5 * np.cos(np.pi * np.arange(x) / x)            # (0 -> 1, eased)

    def loop(v):
        o = v[:N - x].copy()
        sh = (-1,) + (1,) * (v.ndim - 1)
        o[:x] = v[N - x:] * (1 - a).reshape(sh) + v[:x] * a.reshape(sh)
        return o

    d_palm = unit(loop(d_palm))
    hand = loop(hand)
    hd, ld = unit(hand[:, :3]), hand[:, 3:]
    ld = unit(ld - (ld * hd).sum(1, keepdims=True) * hd)
    move = loop(move)

    rb, band = front_roll(front)
    r = lambda v, k: [round(float(z), k) for z in np.asarray(v).ravel()]
    json.dump({
        "about": "the owner's right hand on his mouse, from his overhead take (room_build/kimodo_g12/owner_mouse.py)",
        "fps": round(fps, 4), "speed": SPEED, "frames": N - x, "xfade_s": XF,
        "palm_px": round(palm_px, 2), "roll_base": round(rb, 1), "roll_band": [round(x, 1) for x in band],
        "seg": [[1, 1], [1, 2], [1, 3]] + [[i, j] for i in (2, 3, 4, 5) for j in (1, 2, 3)],
        "d": r(d_palm, 3), "hand": r(np.concatenate([hd, ld], 1), 3), "move": r(move, 4),
    }, open(out, "w"), separators=(",", ":"))
    print("spread (world -> image, deg):", {i: f"{w:.0f} -> {g:.0f}" for i, (w, g) in spread.items()})
    print(f"{N} frames at {fps:.2f} fps -> {N - x} looped ({XF} s crossfade), palm {palm_px:.1f} px, "
          f"roll {rb:.1f} deg in [{band[0]:.1f}, {band[1]:.1f}] (front take), travel fwd {move[:, 0].min():+.2f}..{move[:, 0].max():+.2f}, right {move[:, 1].min():+.2f}..{move[:, 1].max():+.2f} palms")


if __name__ == "__main__":
    main(*sys.argv[1:4])
