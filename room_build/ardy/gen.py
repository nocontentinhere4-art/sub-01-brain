"""Generate the room's motions with ARDY (runs on the pod; see job.sh). One model load, every clip in specs.json.

    python gen.py specs.json out_dir

specs.json: {"clips": [{"name", "prompt", "duration", "seeds": [..], "pin": {...} | null}, ...]}
`pin` builds end-effector constraints from the clip's own best unconstrained sample, with the room's geometry put in
(in ARDY's skeleton units; the caller scales by this skeleton's hip height / the character's):
    {"frames": [first, last, step], "hips_y": y | null, "feet_floor": true | false,
     "hands": {"Left": [right, up, forward] | null, "Right": ...}}  offsets from the hips in the heading frame
Writes <out_dir>/<name>.json (joints, local quaternions xyzw, root positions, posed joints, contacts, scores) and a
summary. Every sample is kept in <name>_samples/ as .npz.
"""
import json
import math
import os
import sys
import time

import numpy as np
import torch
from scipy.spatial.transform import Rotation as R

from ardy.constraints import (
    LeftFootConstraintSet,
    LeftHandConstraintSet,
    RightFootConstraintSet,
    RightHandConstraintSet,
)
from ardy.model import load_model
from ardy.model.registry import resolve_model_name
from ardy.motion_rep.tools import length_to_mask
from ardy.tools import seed_everything, to_numpy

try:
    from ardy.postprocess import post_process_motion
except Exception as e:  # noqa: BLE001
    print("no post-process:", e)
    post_process_motion = None


def generate(model, device, text, num_frames, seed, constraints, cfg=(2.0, 2.0)):
    seed_everything(seed)
    lengths = torch.tensor([num_frames], device=device)
    observed, mask = None, None
    if constraints:
        observed, mask = model.motion_rep.create_conditions_from_constraints_batched(
            constraints, lengths, to_normalize=True, device=device)
    patch = model.num_frames_per_token
    fps = model.motion_rep.fps
    max_window = (int(10 * fps) // patch) * patch
    history = ((max_window - model.gen_horizon_len) // patch) * patch
    with torch.no_grad():
        motion = model([text], num_frames, num_denoising_steps=int(model.diffusion.num_base_steps),
                       pad_mask=length_to_mask(lengths), first_heading_angle=torch.zeros(1, device=device),
                       motion_mask=mask, observed_motion=observed, cfg_weight=cfg, crop_history_length=history)
        out = model.motion_rep.inverse(motion, is_normalized=True)
    if post_process_motion is not None:
        try:
            out.update(post_process_motion(out["local_rot_mats"], out["root_positions"], out["foot_contacts"],
                                           model.skeleton, constraint_lst=constraints or None))
        except Exception as e:  # noqa: BLE001
            print("  post-process failed:", repr(e))
    return out


def root_speed(out, fps):
    r = out["root_positions"][0]
    return float((r[-1] - r[0])[[0, 2]].norm()) / (len(r) / fps)


def score(out, skel, fps):
    """Lower is better: foot skating (horizontal foot speed while in contact) + jitter (second difference)."""
    P = out["posed_joints"][0]                              # T, J, 3
    C = out["foot_contacts"][0].to(torch.float32)           # T, 4 (LeftFoot, LeftToe, RightFoot, RightToe)
    feet = skel.foot_joint_idx
    v = (P[1:] - P[:-1]) * fps
    skate = 0.0
    for k, j in enumerate(feet):
        c = (C[1:, k] > 0.5) & (C[:-1, k] > 0.5)
        if c.any():
            skate += float(v[c][:, j][:, [0, 2]].norm(dim=-1).mean())
    jitter = float(((P[2:] - 2 * P[1:-1] + P[:-2]) * fps * fps).norm(dim=-1).mean()) / 100
    below = float(torch.clamp(-P[:, feet, 1].min(), min=0))
    return {"skate": round(skate / len(feet), 4), "jitter": round(jitter, 4), "below": round(below, 4),
            "total": round(skate / len(feet) + jitter + 5 * below, 4)}


def pin_constraints(out, skel, pin, device):
    """End-effector constraint sets from the sample's own frames, with the room's heights put in."""
    rots = out["local_rot_mats"][0]
    roots = out["root_positions"][0]
    grots, posed, _ = skel.fk(rots[None], roots[None])
    grots, posed = grots[0].clone(), posed[0].clone()
    T = posed.shape[0]
    f0, f1, st = pin["frames"]
    frames = [f for f in range(f0, min(f1, T - 1) + 1, st)]
    if not frames:
        return []
    ri = skel.root_idx
    neutral = skel.neutral_joints
    floor = -float(neutral[:, 1].min())                         # the toes' depth under the hips in the neutral pose
    rh, lh = skel.hip_joint_idx
    k = floor / pin.get("char_hip_height", floor)               # the room's heights are in the character's metres
    for f in frames:
        p = posed[f]
        if pin.get("hips_y") is not None:
            dy = pin["hips_y"] * k - p[ri, 1]
            p[:, 1] += dy                                        # the whole body goes with the hips
        if pin.get("feet_floor"):
            for names in (skel.left_foot_joint_names, skel.right_foot_joint_names):
                ankle, toe = (skel.bone_index[n] for n in names)
                p[ankle, 1] = floor + neutral[ankle, 1]           # ankle at its neutral height above the floor
                p[toe, 1] = 0.02
        hands = pin.get("hands") or {}
        d = p[rh] - p[lh]
        heading = math.atan2(float(d[2]), -float(d[0]))
        fwd = torch.tensor([math.sin(heading), 0.0, math.cos(heading)], device=p.device)
        right = torch.tensor([math.cos(heading), 0.0, -math.sin(heading)], device=p.device)
        up = torch.tensor([0.0, 1.0, 0.0], device=p.device)
        for side in ("Left", "Right"):
            off = hands.get(side)
            if off is None:
                continue
            hi = skel.bone_index[side + "Hand"]
            p[hi] = p[ri] + (right * off[0] + up * off[1] + fwd * off[2]) * k
        posed[f] = p
    idx = torch.tensor(frames)
    sets = []
    if pin.get("feet_floor") or pin.get("hips_y") is not None:
        sets += [LeftFootConstraintSet(skel, idx, posed[idx], grots[idx], None),
                 RightFootConstraintSet(skel, idx, posed[idx], grots[idx], None)]
    for side, cls in (("Left", LeftHandConstraintSet), ("Right", RightHandConstraintSet)):
        if (pin.get("hands") or {}).get(side) is not None:
            sets.append(cls(skel, idx, posed[idx], grots[idx], None))
    return sets


def export(out, skel, fps, text, seed, sc, path):
    rots = out["local_rot_mats"][0].cpu().numpy()                # T, J, 3, 3
    T, J = rots.shape[:2]
    q = R.from_matrix(rots.reshape(-1, 3, 3)).as_quat().reshape(T, J, 4)   # xyzw
    data = {"prompt": text, "seed": seed, "fps": fps, "T": T, "score": sc,
            "local_quat": np.round(q, 5).tolist(),
            "root": np.round(out["root_positions"][0].cpu().numpy(), 5).tolist(),
            "posed": np.round(out["posed_joints"][0].cpu().numpy(), 4).tolist(),
            "contacts": np.round(out["foot_contacts"][0].to(torch.float32).cpu().numpy(), 3).tolist()}
    json.dump(data, open(path, "w"))


def main():
    specs = json.load(open(sys.argv[1]))
    out_dir = sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    t0 = time.time()
    name = resolve_model_name(specs.get("model", "core"))
    model = load_model(name, device=device)
    skel = model.skeleton
    fps = float(model.motion_rep.fps)
    print(f"loaded {name} in {time.time() - t0:.0f} s; fps {fps}; joints {skel.nbjoints}", flush=True)
    neutral = skel.neutral_joints.cpu().numpy()
    parents = skel.joint_parents.cpu().numpy().tolist()
    json.dump({"model": name, "fps": fps, "joints": skel.bone_order_names, "parents": parents,
               "neutral": np.round(neutral, 5).tolist(), "root_idx": skel.root_idx,
               "hip_height": round(-float(neutral[:, 1].min()), 5),
               "foot_joints": skel.foot_joint_names}, open(os.path.join(out_dir, "skeleton.json"), "w"), indent=1)
    summary = {}
    for spec in specs["clips"]:
        nm, text = spec["name"], spec["prompt"].strip()
        nf = int(round(spec.get("duration", 6.0) * fps))
        sdir = os.path.join(out_dir, nm + "_samples")
        os.makedirs(sdir, exist_ok=True)
        best = None
        rows = []
        for seed in spec.get("seeds", [0]):
            t1 = time.time()
            try:
                out = generate(model, device, text, nf, seed, [], cfg=tuple(spec.get("cfg", [2.0, 2.0])))
            except Exception as e:  # noqa: BLE001
                print(f"{nm} seed {seed}: FAILED {e!r}", flush=True)
                continue
            sc = score(out, skel, fps)
            sc["speed"] = round(root_speed(out, fps), 3)
            if spec.get("select") == "speed":                   # a walk: the sample that really walks, if it is clean enough
                sc["total"] = round(sc["total"] + max(0.0, 1.1 - sc["speed"]), 4)
            rows.append({"seed": seed, **sc, "pinned": False})
            print(f"{nm} seed {seed}: {sc} in {time.time() - t1:.1f} s", flush=True)
            export(out, skel, fps, text, seed, sc, os.path.join(sdir, f"s{seed}.json"))
            if best is None or sc["total"] < best[1]["total"]:
                best = (out, sc, seed)
        if best is None:
            summary[nm] = {"failed": True}
            continue
        out, sc, seed = best
        pin = spec.get("pin")
        if pin:
            try:
                pin = {**pin, "char_hip_height": specs.get("char_hip_height", 0.919)}
                cons = pin_constraints(out, skel, pin, device)
                out2 = generate(model, device, text, nf, seed, cons)
                sc2 = score(out2, skel, fps)
                rows.append({"seed": seed, **sc2, "pinned": True})
                export(out2, skel, fps, text, seed, sc2, os.path.join(sdir, f"s{seed}_pinned.json"))
                print(f"{nm} pinned ({len(cons)} sets): {sc2}", flush=True)
                if sc2["total"] < sc["total"] * 1.6 + 0.02:
                    out, sc = out2, {**sc2, "pinned": True}
            except Exception as e:  # noqa: BLE001
                print(f"{nm} pin failed: {e!r}", flush=True)
        export(out, skel, fps, text, seed, sc, os.path.join(out_dir, nm + ".json"))
        summary[nm] = {"seed": seed, "score": sc, "samples": rows, "frames": nf}
        json.dump(summary, open(os.path.join(out_dir, "summary.json"), "w"), indent=1)
    print(f"done in {time.time() - t0:.0f} s", flush=True)


if __name__ == "__main__":
    main()
