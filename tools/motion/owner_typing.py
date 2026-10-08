# The owner's own typing (MediaPipe hand landmarks from his overhead video, branch data/owner-typing) reduced to what the
# page drives per frame: each finger's joint bends, the thumb's segments, each hand's turn over the desk and its travel.
#
#   python3 tools/motion/owner_typing.py overhead_landmarks.json web/room/mh/owner_typing.json
#
# - Fingers 2-5: MCP / PIP / DIP bend from `world` (the hand's own 3D shape; MCP against the finger's own metacarpal
#   line, wrist->knuckle). The spread from `img`: the first phalanx's turn from the middle finger's, seen from above
#   (+ = away from it); the middle finger keeps the hand's line. (World's palm plane is skewed - its knuckles sit 3 cm
#   apart - and fanned the fingers 17-50 deg.)
# - Reach: each finger's wrist->fingertip seen from above, over the palm's length seen from above. From overhead the
#   bends lie mostly in depth, which `world` gets wrong here (its palm pitched 49 deg up, the knuckles 3 cm apart): its
#   bends folded our fingertips under the knuckles, while the image shows his fingers reaching nearly their full length.
#   The page keeps the take's bends in proportion and in time and scales each finger's curl until our reach matches.
# - Thumb: its metacarpal's turn from the index metacarpal's line seen from above (+ = away), its MCP and IP bend.
# - The hand's turn over the desk, from `img` (straight from above that is the reliable part; MediaPipe's world depth
#   is not: it puts the knuckles 3 cm apart and the palms on edge):
#   - yaw: the wrist->middle-knuckle line's angle in the image (+ = toward his right);
#   - roll: from the palm's foreshortening, knuckle width over palm length against the rig's own flat-hand ratio
#     (thumb side up, as MediaPipe's depth says);
#   - pitch: from the palm's length in the image against the rig's, at the image scale below (knuckles up).
# - Travel: the wrist's and the index fingertip's image tracks, scaled by palm width (the rig's knuckle width over his flat
#   left hand's in pixels), relative to the middle of his two index fingertips over the take (his home row). The page
#   places each hand by its index fingertip (his tips sit 7.1 cm apart, about F-J); the wrist follows by the arm.
# - Jitter: a gaussian over +-2 frames (sigma 1 frame) on every series; sigma 2 on the reach.
# - Loop: the last 0.5 s crossfades into the first (smoothstep), so the loop has no seam.
import json, sys
import numpy as np

RIG_PALM = 0.0700        # m, the rig's index->little knuckle distance (both hands 0.069-0.071)
RIG_LEN = 0.0876         # m, the rig's wrist->middle knuckle (right hand)
RIG_RATIO = 0.79         # the rig's knuckle width over palm length, flat
XFADE = 15               # frames (0.5 s)
SPEED = 0.75             # the owner: "a bit slower" than his own


def unit(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def smooth(x, sigma=1.0):
    k = np.exp(-0.5 * (np.arange(-2, 3) / sigma) ** 2); k /= k.sum()
    pad = np.concatenate([x[:2][::-1], x, x[-2:][::-1]], axis=0)
    return np.stack([np.convolve(pad[:, j], k, mode="valid") for j in range(x.shape[1])], axis=1) if x.ndim == 2 else np.convolve(pad, k, mode="valid")


def loop(x):
    n = len(x) - XFADE; out = x[:n].copy()
    for i in range(XFADE):
        a = (i + 1) / (XFADE + 1); a = a * a * (3 - 2 * a)
        out[i] = x[n + i] * (1 - a) + x[i] * a
    return out


def main(src, dst):
    d = json.load(open(src)); W, H = d["size"]; F = d["frames"]
    get = lambda side, key: np.array([[h[key] for h in f["hands"] if h["side"] == side][0] for f in F], float)
    img = {s: get(s, "img")[:, :, :2] * [W, H] for s in ("Left", "Right")}
    scale = RIG_PALM / np.median(np.linalg.norm(img["Left"][:, 5] - img["Left"][:, 17], axis=1))   # m per px (his left hand lies flat)
    home = ((img["Left"][:, 8] + img["Right"][:, 8]) / 2).mean(axis=0)   # px, his index fingertips' middle
    out = {"source": "data/owner-typing mocap_src/owner_typing/overhead_landmarks.json (MediaPipe, the owner's overhead video; video not committed)",
           "fps": d["video_fps"], "speed": SPEED, "xfade_frames": XFADE, "m_per_px": round(float(scale), 6), "hands": {}}
    for side in ("Left", "Right"):
        w = get(side, "world"); im = img[side]
        ang = lambda u, v: np.degrees(np.arccos(np.clip((unit(u) * unit(v)).sum(-1), -1, 1)))
        hi = im[:, 9] - im[:, 0]; li = im[:, 17] - im[:, 5]
        side_l = np.sign(hi[:, 0] * li[:, 1] - hi[:, 1] * li[:, 0])          # (which way l lies from h in the image)
        def img_angle(u, v):                                                  # u's turn from v in the image, + toward l's side
            return np.degrees(np.arctan2(v[:, 0] * u[:, 1] - v[:, 1] * u[:, 0], (u * v).sum(1))) * side_l
        mid = im[:, 10] - im[:, 9]
        G = []
        for i, (a, b, c, e) in zip((2, 3, 4, 5), ((5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20))):
            mcp, pip, dip = ang(w[:, a] - w[:, 0], w[:, b] - w[:, a]), ang(w[:, b] - w[:, a], w[:, c] - w[:, b]), ang(w[:, c] - w[:, b], w[:, e] - w[:, c])
            spread = np.zeros(len(F)) if i == 3 else (-1 if i == 2 else 1) * img_angle(im[:, b] - im[:, a], mid)
            G.append(np.stack([mcp, pip, dip, spread], 1))
        G = np.concatenate(G, 1)                                             # [mcp, pip, dip, spread] x fingers 2-5
        # each finger's reach seen from above: wrist->fingertip over wrist->middle knuckle, both in the image (wrist and tip:
        # MediaPipe's knuckle points sit further back on the hand than our bones' heads)
        reach = np.stack([np.linalg.norm(im[:, e] - im[:, 0], axis=1) / np.linalg.norm(hi, axis=1) for e in (8, 12, 16, 20)], 1)
        # the thumb: [its metacarpal's turn from the index metacarpal's line in the image (+ = away from it), MCP, IP]
        T = np.stack([-img_angle(im[:, 2] - im[:, 1], im[:, 5] - im[:, 0]), ang(w[:, 2] - w[:, 1], w[:, 3] - w[:, 2]), ang(w[:, 3] - w[:, 2], w[:, 4] - w[:, 3])], 1)
        yaw = np.degrees(np.arctan2(hi[:, 0], -hi[:, 1]))
        ratio = np.linalg.norm(li, axis=1) / np.linalg.norm(hi, axis=1)
        roll = np.degrees(np.arccos(np.clip(ratio / RIG_RATIO, -1, 1)))
        pitch = np.degrees(np.arccos(np.clip(np.linalg.norm(hi, axis=1) * scale / RIG_LEN, -1, 1)))
        pos = np.stack([(im[:, 0, 0] - home[0]) * scale, -(im[:, 0, 1] - home[1]) * scale], 1)   # m: his right, forward
        tip = np.stack([(im[:, 8, 0] - home[0]) * scale, -(im[:, 8, 1] - home[1]) * scale], 1)   # (the index fingertip: what places the hand)
        ser = {"G": G, "reach": reach, "thumb": T, "yaw": yaw, "roll": roll, "pitch": pitch, "wrist": pos, "tip2": tip}
        ser = {k: loop(smooth(v, 2.0 if k == "reach" else 1.0)) for k, v in ser.items()}   # (reach: frame-to-frame noise read as strokes)
        out["hands"][side] = {k: np.round(v, 4 if k in ("wrist", "tip2") else 2).tolist() for k, v in ser.items()}
        med = np.median(G, 0).reshape(4, 4)
        print(side, "median [mcp pip dip spread] index..little:", np.round(med).astype(int).tolist(),
              "reach", np.round(np.median(reach, 0), 2).tolist(), "thumb [spread mcp ip]", np.round(np.median(T, 0)).astype(int).tolist(), "yaw %.1f roll %.1f pitch %.1f" % (np.median(yaw), np.median(roll), np.median(pitch)),
              "wrist x %.3f..%.3f y %.3f..%.3f m" % (pos[:, 0].min(), pos[:, 0].max(), pos[:, 1].min(), pos[:, 1].max()))
    out["frames"] = len(out["hands"]["Left"]["yaw"])
    json.dump(out, open(dst, "w"), separators=(",", ":"))
    print("frames", out["frames"], "loop %.2f s at %.2fx" % (out["frames"] / out["fps"] / SPEED, SPEED), "m/px %.5f" % scale)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
