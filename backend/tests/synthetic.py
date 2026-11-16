"""Synthetic scenes for AUTOMATED TESTS ONLY.

A textured concave plate with a food item on a textured table is ray-cast from
ARKit-convention camera poses. Ground-truth geometry lets tests measure the
reconstruction error. Never used for anything shown to a user.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import open3d as o3d

from reconstruction.coordinates import C_AR_FROM_CV, intrinsics_matrix, look_at_ar, mat4_to_rowmajor

# Plate profile (metres): well floor at 8 mm, rim at 22 mm, outer radius 12 cm.
WELL_FLOOR = 0.008
RIM_HEIGHT = 0.022
RIM_INNER_R = 0.105
RIM_OUTER_R = 0.12
FOOT_R = 0.08
FOOD_CENTER = np.array([0.035, WELL_FLOOR + 0.004, 0.01])
FOOD_RADIUS = 0.022


def plate_top_height(r: np.ndarray) -> np.ndarray:
    r = np.asarray(r, float)
    well = WELL_FLOOR + (RIM_HEIGHT - WELL_FLOOR) * np.clip(r / RIM_INNER_R, 0, 1) ** 2
    return np.where(r <= RIM_INNER_R, well, RIM_HEIGHT)


def _lathe(profile: np.ndarray, segments: int = 128) -> o3d.geometry.TriangleMesh:
    verts, tris = [], []
    n = len(profile)
    for s in range(segments):
        a = 2 * np.pi * s / segments
        for r, y in profile:
            verts.append([r * np.cos(a), y, r * np.sin(a)])
    for s in range(segments):
        s2 = (s + 1) % segments
        for i in range(n - 1):
            a, b = s * n + i, s * n + i + 1
            c, d = s2 * n + i, s2 * n + i + 1
            tris += [[a, c, b], [b, c, d]]
    m = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(np.array(verts)), o3d.utility.Vector3iVector(np.array(tris)))
    return m


def build_plate(with_food: bool = True) -> o3d.geometry.TriangleMesh:
    rs = np.linspace(0.0, RIM_INNER_R, 40)
    top = [(r, float(plate_top_height(r))) for r in rs]
    profile = top + [(RIM_OUTER_R, RIM_HEIGHT), (FOOT_R, 0.0005), (0.0, 0.0005)]
    plate = _lathe(np.array(profile))
    if with_food:
        food = o3d.geometry.TriangleMesh.create_sphere(radius=FOOD_RADIUS, resolution=40)
        food.translate(FOOD_CENTER)
        plate += food
    return plate


def _hash_noise(p: np.ndarray, freq: float, seed: int) -> np.ndarray:
    """Smooth 3-D value noise in [0, 1]."""
    q = p * freq
    i = np.floor(q).astype(np.int64)
    f = q - i
    f = f * f * (3 - 2 * f)

    def h(ix, iy, iz):
        v = (ix * 73856093) ^ (iy * 19349663) ^ (iz * 83492791) ^ (seed * 2654435761)
        v = (v ^ (v >> 13)) * 1274126177
        return ((v ^ (v >> 16)) & 0xFFFF) / 65535.0

    out = 0.0
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                w = (f[:, 0] if dx else 1 - f[:, 0]) * (f[:, 1] if dy else 1 - f[:, 1]) * (f[:, 2] if dz else 1 - f[:, 2])
                out = out + w * h(i[:, 0] + dx, i[:, 1] + dy, i[:, 2] + dz)
    return out


def surface_color(p: np.ndarray, material: np.ndarray, uniform_plate: bool = False) -> np.ndarray:
    n1 = _hash_noise(p, 180.0, 1)
    n2 = _hash_noise(p, 600.0, 2)
    tex = 0.6 * n1 + 0.4 * n2
    col = np.zeros((len(p), 3))
    table = material == 0
    plate = material == 1
    food = material == 2
    col[table] = np.stack([0.45 + 0.35 * tex[table], 0.30 + 0.25 * tex[table], 0.18 + 0.15 * tex[table]], 1)
    if uniform_plate:
        col[plate] = 0.93
    else:
        speck = (n2[plate] > 0.62).astype(float)
        col[plate] = np.stack([0.80 + 0.15 * tex[plate] - 0.4 * speck, 0.78 + 0.12 * tex[plate] - 0.35 * speck, 0.70 + 0.10 * tex[plate] - 0.2 * speck], 1)
    col[food] = np.stack([0.45 + 0.4 * tex[food], 0.22 + 0.3 * tex[food], 0.08 + 0.1 * tex[food]], 1)
    return np.clip(col, 0, 1)


@dataclass
class SyntheticScene:
    width: int = 640
    height: int = 480
    fx: float = 500.0
    uniform_plate: bool = False
    with_food: bool = True
    box_size: tuple = (0.28, 0.08, 0.28)  # (w, h, d) -> converted below
    scene: o3d.t.geometry.RaycastingScene = field(init=False)

    def __post_init__(self):
        self.scene = o3d.t.geometry.RaycastingScene()
        table = o3d.geometry.TriangleMesh.create_box(1.2, 0.01, 1.2)
        table.translate([-0.6, -0.01, -0.6])
        self.ids = {}
        self.ids[self.scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(table))] = 0
        plate = _lathe(np.array([(r, float(plate_top_height(r))) for r in np.linspace(0.0, RIM_INNER_R, 40)] + [(RIM_OUTER_R, RIM_HEIGHT), (FOOT_R, 0.0005), (0.0, 0.0005)]))
        self.ids[self.scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(plate))] = 1
        if self.with_food:
            food = o3d.geometry.TriangleMesh.create_sphere(radius=FOOD_RADIUS, resolution=40)
            food.translate(FOOD_CENTER)
            self.ids[self.scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(food))] = 2
        self.K = intrinsics_matrix(self.fx, self.fx, self.width / 2 - 0.5, self.height / 2 - 0.5)

    def render(self, T_world_from_camera_ar: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Return (BGR uint8 image, depth float32 metres along the CV z axis)."""
        u, v = np.meshgrid(np.arange(self.width), np.arange(self.height))
        d_cv = np.stack([(u - self.K[0, 2]) / self.K[0, 0], (v - self.K[1, 2]) / self.K[1, 1], np.ones_like(u, float)], -1).reshape(-1, 3)
        T_w_cv = T_world_from_camera_ar @ C_AR_FROM_CV
        dirs = d_cv @ T_w_cv[:3, :3].T
        origin = np.broadcast_to(T_w_cv[:3, 3], dirs.shape)
        rays = o3d.core.Tensor(np.concatenate([origin, dirs], 1).astype(np.float32))
        ans = self.scene.cast_rays(rays)
        t = ans["t_hit"].numpy().astype(np.float64)
        geom = ans["geometry_ids"].numpy()
        normals = ans["primitive_normals"].numpy().astype(np.float64)
        hit = np.isfinite(t)
        pts = origin + dirs * np.where(hit, t, 0)[:, None]
        material = np.array([self.ids.get(int(g), 0) for g in np.unique(geom)])
        lut = {int(g): self.ids.get(int(g), 0) for g in np.unique(geom)}
        mat = np.vectorize(lambda g: lut.get(int(g), 0))(geom) if len(lut) else np.zeros_like(geom)
        col = surface_color(pts, mat, self.uniform_plate)
        light = np.array([0.3, 1.0, 0.2])
        light /= np.linalg.norm(light)
        shade = 0.55 + 0.45 * np.abs(normals @ light)
        col = col * shade[:, None]
        col[~hit] = 0.5
        img = (np.clip(col, 0, 1) * 255).astype(np.uint8).reshape(self.height, self.width, 3)[:, :, ::-1].copy()
        depth = np.where(hit, t, 0.0).reshape(self.height, self.width).astype(np.float32)  # d_cv has z=1, so t == z
        del material
        return img, depth


def orbit_poses(n: int, radius: float = 0.38, elevations=(35.0, 60.0), roll_deg: float = -90.0, noise_rot_deg: float = 0.0,
                noise_trans_m: float = 0.0, seed: int = 0, center=(0.0, 0.03, 0.0), return_true: bool = False):
    """Continuous path: one lap at the first elevation, then part of a lap higher.

    With noise, the returned poses are the *reported* (tracking) poses; pass
    return_true=True to also get the exact poses used for rendering.
    """
    rng = np.random.default_rng(seed)
    poses, true_poses = [], []
    drift = np.eye(4)
    n1 = int(n * 0.7)
    for i in range(n):
        if i < n1:
            el, az = elevations[0], 2 * np.pi * i / n1
        else:
            el, az = elevations[1], 2 * np.pi * (i - n1) / max(1, n - n1)
        e = np.radians(el)
        eye = np.array([radius * np.cos(e) * np.cos(az), radius * np.sin(e), radius * np.cos(e) * np.sin(az)])
        T = look_at_ar(eye, center, roll_deg=roll_deg)
        true_poses.append(T.copy())
        if noise_rot_deg or noise_trans_m:
            # Random-walk drift of the tracking world (smooth, like visual-inertial odometry).
            axis = rng.normal(size=3)
            axis /= np.linalg.norm(axis)
            ang = np.radians(rng.normal(scale=noise_rot_deg))
            Kx = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
            step = np.eye(4)
            step[:3, :3] = np.eye(3) + np.sin(ang) * Kx + (1 - np.cos(ang)) * Kx @ Kx
            step[:3, 3] = rng.normal(scale=noise_trans_m, size=3)
            drift = step @ drift
            T = drift @ T
        poses.append(T)
    return (poses, true_poses) if return_true else poses


def frame_meta(scene: SyntheticScene, frame_id: int, T_world_from_camera_ar: np.ndarray, session_id: str = "synthetic",
               epoch: int = 0, timestamp: float | None = None) -> dict:
    K = scene.K
    return {
        "schema": "dishplay.frame/1",
        "session_id": session_id,
        "frame_id": frame_id,
        "epoch": epoch,
        "timestamp_s": float(timestamp if timestamp is not None else frame_id * 0.4),
        "image": {"width": scene.width, "height": scene.height, "encoding": "jpeg", "orientation": "sensor_native"},
        "intrinsics": {"fx": K[0, 0], "fy": K[1, 1], "cx": K[0, 2], "cy": K[1, 2], "width": scene.width, "height": scene.height},
        "distortion": {"status": "none_synthetic"},
        "T_world_from_cameraAR": mat4_to_rowmajor(T_world_from_camera_ar),
        "tracking": {"state": "normal"},
        "camera_format": {"width": scene.width, "height": scene.height, "fps": 30, "device": "synthetic"},
        "quality": {"sharpness": 1.0},
        "synthetic": True,
    }


def distance_to_scene(scene: SyntheticScene, pts: np.ndarray) -> np.ndarray:
    """Unsigned distance (m) from object-frame points (box at world origin) to the true surfaces."""
    q = o3d.core.Tensor(np.asarray(pts, np.float32))
    return scene.scene.compute_distance(q).numpy()


def visible_ground_truth(scene: SyntheticScene, poses, box_size=(0.28, 0.08, 0.28), n=150000, seed=0) -> np.ndarray:
    """Ground-truth surface samples (inside the box) that at least one camera actually saw."""
    rng = np.random.default_rng(seed)
    plate = (o3d.utility.random.seed(seed), build_plate(scene.with_food).sample_points_uniformly(n))[1]
    P = np.asarray(plate.points)
    w, _, d = box_size
    table = np.stack([rng.uniform(-w / 2, w / 2, n), np.zeros(n), rng.uniform(-d / 2, d / 2, n)], 1)
    G = np.vstack([P, table])
    seen = np.zeros(len(G), bool)
    for T in poses:
        T_cv_w = np.linalg.inv(T @ C_AR_FROM_CV)
        pc = G @ T_cv_w[:3, :3].T + T_cv_w[:3, 3]
        z = pc[:, 2]
        u = pc[:, 0] / z * scene.K[0, 0] + scene.K[0, 2]
        v = pc[:, 1] / z * scene.K[1, 1] + scene.K[1, 2]
        ok = (z > 0) & (u >= 0) & (u < scene.width - 1) & (v >= 0) & (v < scene.height - 1)
        _, depth = scene.render(T)
        zi = depth[np.round(v[ok]).astype(int), np.round(u[ok]).astype(int)]
        vis = np.zeros(len(G), bool)
        vis[np.nonzero(ok)[0]] = np.abs(zi - z[ok]) < 0.004
        seen |= vis
    return G[seen]
