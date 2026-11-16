"""Multi-view geometric consistency of depth maps.

A depth pixel of the reference view is kept as MEASURED only when other views, each with its
own independently computed depth map, see a surface at the same place. A view that sees
*through* the point (its own depth is clearly farther along the same line of sight) is a
free-space violation: evidence that the point is a floater. This is what removes flying
fragments and fattened edges, and what lets weakly textured regions in: a smooth guess of the
stereo matcher survives only if independent pairs agree on it.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .coordinates import invert_rigid


@dataclass
class DepthView:
    frame_id: int
    depth: np.ndarray            # float32 metres, 0 = unknown
    K: np.ndarray
    T_obj_from_cam: np.ndarray
    image: np.ndarray | None = None   # BGR on the depth grid, lightly blurred (photo-consistency)


def consistency_counts(ref: DepthView, others: list[DepthView], rel_tol: float = 0.012, abs_tol: float = 0.0015,
                       violation_factor: float = 2.0, color_tol: float = 48.0, near_front_m: float = 0.03) -> tuple[np.ndarray, np.ndarray]:
    """Per reference pixel: (number of agreeing views, number of contradictions).

    Agreement needs the same place AND the same colour in the other image. A pixel whose depth
    lands on a real surface of a different colour is "seeing through" its own surface (typical on
    weak texture, where the matcher copies the background): that counts as a contradiction, because
    fusing it would both smear the wrong colour and carve away the real surface in front.
    """
    h, w = ref.depth.shape
    agree = np.zeros((h, w), np.uint8)
    viol = np.zeros((h, w), np.uint8)
    vs, us = np.nonzero(ref.depth > 0)
    if len(vs) == 0 or not others:
        return agree, viol
    z = ref.depth[vs, us].astype(np.float64)
    K = ref.K
    pc = np.stack([(us - K[0, 2]) / K[0, 0] * z, (vs - K[1, 2]) / K[1, 1] * z, z], 1)
    po = pc @ ref.T_obj_from_cam[:3, :3].T + ref.T_obj_from_cam[:3, 3]
    a = np.zeros(len(vs), np.uint8)
    f = np.zeros(len(vs), np.uint8)
    col_ref = ref.image[vs, us].astype(np.float32) if ref.image is not None else None
    for o in others:
        T = invert_rigid(o.T_obj_from_cam)
        q = po @ T[:3, :3].T + T[:3, 3]
        zq = q[:, 2]
        ok = zq > 0.03
        uq = np.full(len(zq), -1.0)
        vq = np.full(len(zq), -1.0)
        uq[ok] = q[ok, 0] / zq[ok] * o.K[0, 0] + o.K[0, 2]
        vq[ok] = q[ok, 1] / zq[ok] * o.K[1, 1] + o.K[1, 2]
        ui = np.round(uq).astype(np.int64)
        vi = np.round(vq).astype(np.int64)
        oh, ow = o.depth.shape
        inside = ok & (ui >= 0) & (ui < ow) & (vi >= 0) & (vi < oh)
        d = np.zeros(len(zq))
        d[inside] = o.depth[vi[inside], ui[inside]]
        seen = inside & (d > 0)
        tol = np.maximum(abs_tol, rel_tol * zq)
        same_place = seen & (np.abs(d - zq) <= tol)
        if col_ref is not None and o.image is not None:
            diff = np.zeros(len(zq), np.float32)
            diff[inside] = np.linalg.norm(o.image[vi[inside], ui[inside]].astype(np.float32) - col_ref[inside], axis=1)
            same_color = diff <= color_tol
            f += (same_place & ~same_color).astype(np.uint8)
            same_place &= same_color
        a += same_place.astype(np.uint8)
        # The other view sees farther along this line of sight (it looks through the point), or it
        # places a surface slightly in front of it (same surface, different answer): both contradict.
        # A surface far in front is a genuine occluder and says nothing.
        f += (seen & (d - zq > violation_factor * tol)).astype(np.uint8)
        f += (seen & (zq - d > violation_factor * tol) & (zq - d < near_front_m)).astype(np.uint8)
    agree[vs, us] = a
    viol[vs, us] = f
    return agree, viol


def confirmed_depth(ref: DepthView, others: list[DepthView], min_agree: int = 1, majority: float = 1.5, **kw) -> tuple[np.ndarray, np.ndarray, dict]:
    """(depth with unconfirmed pixels removed, agreeing-view count, stats)."""
    agree, viol = consistency_counts(ref, others, **kw)
    valid = ref.depth > 0
    # Majority rule among the views that have an opinion about this spot.
    keep = valid & (agree >= min_agree) & (agree >= viol * majority)
    out = np.where(keep, ref.depth, 0).astype(np.float32)
    stats = {"valid": int(valid.sum()), "confirmed": int(keep.sum()),
             "violated": int((valid & (agree < viol * majority)).sum()), "neighbours": len(others)}
    return out, agree, stats


def pick_neighbours(ref: DepthView, cache: list[DepthView], max_n: int = 5, min_baseline_m: float = 0.008,
                    max_angle_deg: float = 40.0) -> list[DepthView]:
    """Nearest other views that look at the scene from a usefully different, not too different, place."""
    c0 = ref.T_obj_from_cam[:3, 3]
    z0 = ref.T_obj_from_cam[:3, 2]
    cand = []
    for o in cache:
        if o.frame_id == ref.frame_id:
            continue
        b = float(np.linalg.norm(o.T_obj_from_cam[:3, 3] - c0))
        ang = float(np.degrees(np.arccos(np.clip(np.dot(z0, o.T_obj_from_cam[:3, 2]), -1, 1))))
        if b >= min_baseline_m and ang <= max_angle_deg:
            cand.append((b, o))
    cand.sort(key=lambda t: (t[0], t[1].frame_id))
    return [o for _, o in cand[:max_n]]
