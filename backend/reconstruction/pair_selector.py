"""Choose temporal stereo partners from calibrated, posed views of one epoch."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .coordinates import invert_rigid, project, rotation_angle_deg


@dataclass(frozen=True)
class PairGeometry:
    ref_id: int
    other_id: int
    baseline_m: float
    depth_m: float
    baseline_ratio: float
    axis_angle_deg: float
    forward_fraction: float
    score: float


@dataclass(frozen=True)
class PairLimits:
    min_ratio: float = 0.035   # baseline / distance-to-object
    max_ratio: float = 0.22
    best_ratio: float = 0.09
    max_axis_angle_deg: float = 22.0
    max_forward_fraction: float = 0.55  # |t_z| / |t| in the reference camera
    min_box_visible: float = 0.6


def box_visibility(K, T_cam_from_obj, size_m, width, height) -> float:
    """Fraction of a 5x3x5 grid of sample points of the box that projects inside the image."""
    w, h, d = size_m
    g = np.stack(np.meshgrid(np.linspace(-w / 2, w / 2, 5), np.linspace(0, h, 3), np.linspace(-d / 2, d / 2, 5)), -1).reshape(-1, 3)
    uv, z = project(K, T_cam_from_obj, g)
    ok = (z > 0.05) & (uv[:, 0] >= 0) & (uv[:, 0] < width) & (uv[:, 1] >= 0) & (uv[:, 1] < height)
    return float(ok.mean())


def pair_geometry(ref_id, T_obj_from_ref, other_id, T_obj_from_other, size_m, limits: PairLimits = PairLimits()) -> PairGeometry | None:
    T_ref_from_other = invert_rigid(T_obj_from_ref) @ T_obj_from_other
    # Position of the other camera centre in the reference camera frame.
    t = T_ref_from_other[:3, 3]
    baseline = float(np.linalg.norm(t))
    if baseline < 1e-4:
        return None
    centre_obj = np.array([0.0, size_m[1] / 2, 0.0, 1.0])
    depth = float((invert_rigid(T_obj_from_ref) @ centre_obj)[2])
    if depth <= 0.05:
        return None
    ratio = baseline / depth
    axis_angle = rotation_angle_deg(T_ref_from_other[:3, :3])
    forward = abs(t[2]) / baseline
    if not (limits.min_ratio <= ratio <= limits.max_ratio):
        return None
    if axis_angle > limits.max_axis_angle_deg or forward > limits.max_forward_fraction:
        return None
    score = -abs(np.log(ratio / limits.best_ratio)) - axis_angle / 40.0 - forward
    return PairGeometry(ref_id, other_id, baseline, depth, ratio, axis_angle, forward, float(score))


def select_partners(ref_id: int, views: dict, size_m, max_partners: int = 2, limits: PairLimits = PairLimits(),
                    exclude: set | None = None) -> list[PairGeometry]:
    """views: frame_id -> (T_obj_from_cam, K, (w, h)). Partners favour distinct baseline directions."""
    T_ref, K_ref, wh = views[ref_id]
    if box_visibility(K_ref, np.linalg.inv(T_ref), size_m, *wh) < limits.min_box_visible:
        return []
    cands = []
    for oid, (T_o, K_o, wh_o) in views.items():
        if oid == ref_id or (exclude and oid in exclude):
            continue
        if box_visibility(K_o, np.linalg.inv(T_o), size_m, *wh_o) < limits.min_box_visible:
            continue
        g = pair_geometry(ref_id, T_ref, oid, T_o, size_m, limits)
        if g is not None:
            cands.append((g, T_o[:3, 3] - T_ref[:3, 3]))
    cands.sort(key=lambda c: (-c[0].score, c[0].other_id))
    chosen: list[tuple[PairGeometry, np.ndarray]] = []
    for g, d in cands:
        d = d / np.linalg.norm(d)
        # Avoid two partners on the same side: they would add little independent evidence.
        if any(abs(float(np.dot(d, c[1] / np.linalg.norm(c[1])))) > 0.95 and np.dot(d, c[1]) > 0 for c in chosen):
            continue
        chosen.append((g, d))
        if len(chosen) >= max_partners:
            break
    return [c[0] for c in chosen]
