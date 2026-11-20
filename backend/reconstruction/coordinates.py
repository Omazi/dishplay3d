"""Coordinate conventions for DishPlay Scan.

All units are metres. ``T_A_from_B`` is a 4x4 homogeneous transform that maps
coordinates expressed in frame B to frame A: ``x_A = T_A_from_B @ x_B``.
Matrices travel on the wire as 16 numbers in ROW-MAJOR order (see
contracts/capture-session.schema.json); Swift ``simd_float4x4`` is column-major
in memory, so the iOS client converts explicitly.

Frames
------
world      ARKit world of one tracking epoch (y up, gravity aligned).
object     Box frame chosen by the user: origin at the centre of the box base,
           +y up (normal of the table plane), x = width, z = depth.
cameraAR   ARKit camera: x right, y up, z towards the viewer, for the image in
           the sensor-native (landscape) orientation that matches K.
cameraCV   OpenCV camera: x right, y down, z forward.  cameraCV = cameraAR * C
           with C = diag(1, -1, -1, 1).
"""
from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np

C_AR_FROM_CV = np.diag([1.0, -1.0, -1.0, 1.0])  # equal to its own inverse


def mat4_from_rowmajor(values: Sequence[float]) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64)
    if arr.shape != (16,):
        raise ValueError(f"expected 16 row-major values, got shape {arr.shape}")
    m = arr.reshape(4, 4)
    if not np.allclose(m[3], [0, 0, 0, 1], atol=1e-6):
        raise ValueError("last row of a rigid transform must be [0, 0, 0, 1]")
    return m


def mat4_to_rowmajor(m: np.ndarray) -> list[float]:
    return [float(v) for v in np.asarray(m, dtype=np.float64).reshape(16)]


def invert_rigid(T: np.ndarray) -> np.ndarray:
    R = T[:3, :3]
    t = T[:3, 3]
    out = np.eye(4)
    out[:3, :3] = R.T
    out[:3, 3] = -R.T @ t
    return out


def is_rigid(T: np.ndarray, tol: float = 1e-3) -> bool:
    R = T[:3, :3]
    return bool(np.allclose(R.T @ R, np.eye(3), atol=tol) and abs(np.linalg.det(R) - 1) < tol)


def object_from_camera_cv(T_world_from_object: np.ndarray, T_world_from_camera_ar: np.ndarray) -> np.ndarray:
    """T_object_from_cameraCV = inverse(T_world_from_object) * T_world_from_cameraAR * C."""
    return invert_rigid(T_world_from_object) @ T_world_from_camera_ar @ C_AR_FROM_CV


def camera_cv_from_object(T_world_from_object: np.ndarray, T_world_from_camera_ar: np.ndarray) -> np.ndarray:
    return invert_rigid(object_from_camera_cv(T_world_from_object, T_world_from_camera_ar))


def intrinsics_matrix(fx: float, fy: float, cx: float, cy: float) -> np.ndarray:
    return np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]])


def scale_intrinsics(K: np.ndarray, src_size: tuple[int, int], dst_size: tuple[int, int]) -> np.ndarray:
    """Adjust K for an image resized from src (w, h) to dst (w, h).

    Uses the pixel-centre convention (pixel i covers [i-0.5, i+0.5]) so that
    cx' = (cx + 0.5) * s - 0.5.
    """
    sx = dst_size[0] / src_size[0]
    sy = dst_size[1] / src_size[1]
    out = K.astype(np.float64).copy()
    out[0, 0] *= sx
    out[1, 1] *= sy
    out[0, 2] = (K[0, 2] + 0.5) * sx - 0.5
    out[1, 2] = (K[1, 2] + 0.5) * sy - 0.5
    return out


def crop_intrinsics(K: np.ndarray, x0: float, y0: float) -> np.ndarray:
    out = K.astype(np.float64).copy()
    out[0, 2] -= x0
    out[1, 2] -= y0
    return out


def transform_points(T: np.ndarray, pts: np.ndarray) -> np.ndarray:
    pts = np.asarray(pts, dtype=np.float64).reshape(-1, 3)
    return pts @ T[:3, :3].T + T[:3, 3]


def project(K: np.ndarray, T_cam_from_obj: np.ndarray, pts_obj: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Project object points into a CV camera. Returns (uv Nx2, depth N)."""
    pc = transform_points(T_cam_from_obj, pts_obj)
    z = pc[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        uv = (pc[:, :2] / z[:, None]) * [K[0, 0], K[1, 1]] + [K[0, 2], K[1, 2]]
    return uv, z


def backproject(K: np.ndarray, uv: np.ndarray, depth: np.ndarray) -> np.ndarray:
    uv = np.asarray(uv, dtype=np.float64).reshape(-1, 2)
    depth = np.asarray(depth, dtype=np.float64).reshape(-1)
    x = (uv[:, 0] - K[0, 2]) / K[0, 0] * depth
    y = (uv[:, 1] - K[1, 2]) / K[1, 1] * depth
    return np.stack([x, y, depth], axis=1)


def box_corners(size_m: Iterable[float]) -> np.ndarray:
    """Eight corners of the capture box in object coordinates (y up, base at y=0).

    size_m is ALWAYS (width along x, height along y, depth along z).
    """
    w, h, d = [float(v) for v in size_m]
    xs = (-w / 2, w / 2)
    ys = (0.0, h)
    zs = (-d / 2, d / 2)
    return np.array([[x, y, z] for x in xs for y in ys for z in zs])


def headroom(size_m: Sequence[float]) -> float:
    """Height kept above the top of the scan box, in metres.

    The box is set by hand in the app and is often a little low; a pose that drifts by a few millimetres also
    tilts a flat object out of a tight box. Nothing stands in the air above a dish, so what is measured above
    the top of the box, within its outline, is the dish itself. It is kept up to half the height of the box,
    at least 2 cm and at most 6 cm (the search range of the matcher grows with it). The sides and the base are
    not widened: the table and the neighbours of the dish are there.
    """
    return float(min(max(0.5 * float(size_m[1]), 0.02), 0.06))


def volume_corners(size_m: Iterable[float], margin: float = 0.0, below: float = 0.0, above: float = 0.0) -> np.ndarray:
    """Eight corners of the box widened by `margin` on its four sides, `below` under its base, `above` over its top."""
    w, h, d = [float(v) for v in size_m]
    xs = (-w / 2 - margin, w / 2 + margin)
    ys = (-below, h + above)
    zs = (-d / 2 - margin, d / 2 + margin)
    return np.array([[x, y, z] for x in xs for y in ys for z in zs])


def inside_box(pts_obj: np.ndarray, size_m: Sequence[float], margin: float = 0.0, below: float = 0.0,
               above: float | None = None) -> np.ndarray:
    """size_m = (width x, height y, depth z). `above`: what is kept over the top (as `margin` when not given)."""
    w, h, d = size_m
    p = pts_obj
    return (
        (np.abs(p[:, 0]) <= w / 2 + margin)
        & (np.abs(p[:, 2]) <= d / 2 + margin)
        & (p[:, 1] >= -below)
        & (p[:, 1] <= h + (margin if above is None else above))
    )


def rotation_angle_deg(R: np.ndarray) -> float:
    c = (np.trace(R) - 1.0) / 2.0
    return float(np.degrees(np.arccos(np.clip(c, -1.0, 1.0))))


def look_at_ar(eye: Sequence[float], target: Sequence[float], up: Sequence[float] = (0, 1, 0), roll_deg: float = 0.0) -> np.ndarray:
    """ARKit-style T_world_from_cameraAR looking from eye to target (camera -z forward)."""
    eye = np.asarray(eye, float)
    z = eye - np.asarray(target, float)
    z /= np.linalg.norm(z)
    x = np.cross(np.asarray(up, float), z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    R = np.stack([x, y, z], axis=1)
    if roll_deg:
        a = np.radians(roll_deg)
        Rz = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
        R = R @ Rz
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = eye
    return T
