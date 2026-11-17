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
    best_ratio: float = 0.11
    max_axis_angle_deg: float = 22.0
    max_forward_fraction: float = 0.55  # |t_z| / |t| in the reference camera
    min_box_visible: float = 0.12   # the reference view must show at least this share of the box...
    min_shared: float = 0.6         # ...and the partner must see this share of what the reference sees


def _box_samples(size_m) -> np.ndarray:
    w, h, d = size_m
    return np.stack(np.meshgrid(np.linspace(-w / 2, w / 2, 7), np.linspace(0, h, 3), np.linspace(-d / 2, d / 2, 7)), -1).reshape(-1, 3)


def box_seen(K, T_cam_from_obj, size_m, width, height) -> np.ndarray:
    """Which sample points of the box (a 7x3x7 grid) project inside the image."""
    uv, z = project(K, T_cam_from_obj, _box_samples(size_m))
    return (z > 0.05) & (uv[:, 0] >= 0) & (uv[:, 0] < width) & (uv[:, 1] >= 0) & (uv[:, 1] < height)


def box_visibility(K, T_cam_from_obj, size_m, width, height) -> float:
    """Fraction of the sample points of the box that projects inside the image."""
    return float(box_seen(K, T_cam_from_obj, size_m, width, height).mean())


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
    # A box larger than the field of view at scanning distance (a large plate, a tray) is never seen whole:
    # what counts is that the reference view shows some of it and that the partner sees the same part.
    seen_ref = box_seen(K_ref, np.linalg.inv(T_ref), size_m, *wh)
    if seen_ref.mean() < limits.min_box_visible:
        return []
    cands = []
    for oid, (T_o, K_o, wh_o) in views.items():
        if oid == ref_id or (exclude and oid in exclude):
            continue
        g = pair_geometry(ref_id, T_ref, oid, T_o, size_m, limits)
        if g is None:
            continue
        seen_o = box_seen(K_o, np.linalg.inv(T_o), size_m, *wh_o)
        if (seen_ref & seen_o).sum() < limits.min_shared * seen_ref.sum():
            continue
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
