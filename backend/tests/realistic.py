"""Harder synthetic benchmark, modelled on the first real scan (deep plastic bowl of nuts on a
patterned tablecloth, hand-held at night). FOR TESTS AND TUNING ONLY — never shown as a scan.

Differences with tests/synthetic.py: deep concave bowl with a thin rim, almost texture-less
bowl walls, a heap of small items, hand-held trajectory with jitter, tracking drift, sensor
noise, motion blur and small exposure changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
import open3d as o3d

from reconstruction.coordinates import C_AR_FROM_CV, intrinsics_matrix, look_at_ar
from tests.synthetic import _hash_noise, _lathe

RIM_R, RIM_H, WALL, FOOT_R, FLOOR_Y, FLOOR_R = 0.075, 0.055, 0.003, 0.040, 0.004, 0.034
BOX = (0.20, 0.08, 0.20)


def bowl_mesh() -> o3d.geometry.TriangleMesh:
    s = np.linspace(0, 1, 28)
    inner = [(0.0, FLOOR_Y)] + [(FLOOR_R + (RIM_R - WALL - FLOOR_R) * a, FLOOR_Y + (RIM_H - FLOOR_Y) * a ** 1.6) for a in s]
    outer = [(FOOT_R + (RIM_R - FOOT_R) * a, RIM_H * a ** 1.6) for a in s[::-1]]
    return _lathe(np.array(inner + [(RIM_R, RIM_H)] + outer + [(0.0, 0.0005)]), segments=160)


def nuts_mesh(seed: int = 5, n: int = 14) -> o3d.geometry.TriangleMesh:
    rng = np.random.default_rng(seed)
    out = o3d.geometry.TriangleMesh()
    for _ in range(n):
        m = o3d.geometry.TriangleMesh.create_sphere(radius=1.0, resolution=14)
        m.scale(1.0, center=(0, 0, 0))
        V = np.asarray(m.vertices) * rng.uniform([0.008, 0.005, 0.006], [0.013, 0.008, 0.010])
        a = rng.uniform(0, np.pi)
        R = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
        r, th = 0.026 * np.sqrt(rng.uniform()), rng.uniform(0, 2 * np.pi)
        m.vertices = o3d.utility.Vector3dVector(V @ R.T + [r * np.cos(th), FLOOR_Y + rng.uniform(0.006, 0.016), r * np.sin(th)])
        out += m
    return out


@dataclass
class BowlScene:
    width: int = 640
    height: int = 480
    fx: float = 500.0
    box_size: tuple = BOX
    scene: o3d.t.geometry.RaycastingScene = field(init=False)

    def __post_init__(self):
        self.scene = o3d.t.geometry.RaycastingScene()
        table = o3d.geometry.TriangleMesh.create_box(1.2, 0.01, 1.2)
        table.translate([-0.6, -0.01, -0.6])
        self.meshes = {0: table, 1: bowl_mesh(), 2: nuts_mesh()}
        self.ids = {self.scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(m)): k for k, m in self.meshes.items()}
        self.K = intrinsics_matrix(self.fx, self.fx, self.width / 2 - 0.5, self.height / 2 - 0.5)

    def _color(self, p, mat):
        n1, n2 = _hash_noise(p, 160.0, 11), _hash_noise(p, 700.0, 12)
        col = np.zeros((len(p), 3))
        t, b, f = mat == 0, mat == 1, mat == 2
        # tablecloth: large soft pattern + fine weave
        pat = (np.sin(p[t, 0] * 90) * np.sin(p[t, 2] * 90) > 0.3).astype(float)
        col[t] = np.stack([0.80 - 0.18 * pat + 0.10 * n2[t], 0.76 - 0.10 * pat + 0.10 * n2[t], 0.62 - 0.22 * pat + 0.08 * n2[t]], 1)
        # plastic bowl: nearly uniform dark red (the hard part for stereo)
        col[b] = np.stack([0.42 + 0.03 * n1[b], 0.10 + 0.02 * n1[b], 0.08 + 0.02 * n1[b]], 1)
        tex = 0.5 * n1[f] + 0.5 * n2[f]
        col[f] = np.stack([0.55 + 0.35 * tex, 0.36 + 0.30 * tex, 0.18 + 0.20 * tex], 1)
        return np.clip(col, 0, 1)

    def render(self, T_world_from_camera_ar: np.ndarray):
        u, v = np.meshgrid(np.arange(self.width), np.arange(self.height))
        d = np.stack([(u - self.K[0, 2]) / self.K[0, 0], (v - self.K[1, 2]) / self.K[1, 1], np.ones_like(u, float)], -1).reshape(-1, 3)
        T = T_world_from_camera_ar @ C_AR_FROM_CV
        dirs = d @ T[:3, :3].T
        org = np.broadcast_to(T[:3, 3], dirs.shape)
        ans = self.scene.cast_rays(o3d.core.Tensor(np.concatenate([org, dirs], 1).astype(np.float32)))
        t = ans["t_hit"].numpy().astype(np.float64)
        hit = np.isfinite(t)
        geom = ans["geometry_ids"].numpy()
        mat = np.zeros(len(geom), int)
        for gid, k in self.ids.items():
            mat[geom == gid] = k
        pts = org + dirs * np.where(hit, t, 0)[:, None]
        col = self._color(pts, mat)
        nrm = ans["primitive_normals"].numpy().astype(np.float64)
        light = np.array([0.25, 1.0, 0.3]) / np.linalg.norm([0.25, 1.0, 0.3])
        col = col * (0.5 + 0.5 * np.abs(nrm @ light))[:, None]
        col[~hit] = 0.35
        img = (np.clip(col, 0, 1) * 255).astype(np.uint8).reshape(self.height, self.width, 3)[:, :, ::-1].copy()
        return img, np.where(hit, t, 0.0).reshape(self.height, self.width).astype(np.float32)

    def surface_samples(self, n: int = 120000, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
        """(points, material) on the bowl, nuts and the table inside the box."""
        o3d.utility.random.seed(seed)
        rng = np.random.default_rng(seed)
        P = [np.asarray(self.meshes[1].sample_points_uniformly(n).points), np.asarray(self.meshes[2].sample_points_uniformly(n // 4).points)]
        w, _, d = self.box_size
        P.append(np.stack([rng.uniform(-w / 2, w / 2, n // 2), np.zeros(n // 2), rng.uniform(-d / 2, d / 2, n // 2)], 1))
        M = np.concatenate([np.full(len(P[0]), 1), np.full(len(P[1]), 2), np.full(len(P[2]), 0)])
        return np.vstack(P), M

    def visible_samples(self, poses, n: int = 120000) -> tuple[np.ndarray, np.ndarray]:
        G, M = self.surface_samples(n)
        seen = np.zeros(len(G), bool)
        for T in poses:
            Tc = np.linalg.inv(T @ C_AR_FROM_CV)
            pc = G @ Tc[:3, :3].T + Tc[:3, 3]
            z = pc[:, 2]
            u = pc[:, 0] / z * self.K[0, 0] + self.K[0, 2]
            v = pc[:, 1] / z * self.K[1, 1] + self.K[1, 2]
            ok = (z > 0) & (u >= 0) & (u < self.width - 1) & (v >= 0) & (v < self.height - 1)
            _, depth = self.render(T)
            zi = depth[np.round(v[ok]).astype(int), np.round(u[ok]).astype(int)]
            idx = np.nonzero(ok)[0]
            seen[idx[np.abs(zi - z[ok]) < 0.003]] = True
        return G[seen], M[seen]


def handheld_poses(n: int = 110, seed: int = 0, drift_rot_deg: float = 0.03, drift_trans_m: float = 0.0002):
    """Returns (reported poses with tracking drift, true poses). One wobbly lap + a higher partial lap."""
    rng = np.random.default_rng(seed)
    true, rep = [], []
    drift = np.eye(4)
    n1 = int(n * 0.72)
    for i in range(n):
        if i < n1:
            el, az = 36 + 4 * np.sin(i * 0.31), 2 * np.pi * i / n1
        else:
            el, az = 62 + 3 * np.sin(i * 0.4), 2 * np.pi * (i - n1) / (n - n1)
        r = 0.33 + 0.02 * np.sin(i * 0.17) + rng.normal(scale=0.004)
        e = np.radians(el)
        eye = np.array([r * np.cos(e) * np.cos(az), r * np.sin(e), r * np.cos(e) * np.sin(az)])
        tgt = np.array([0, 0.025, 0]) + rng.normal(scale=0.006, size=3)
        T = look_at_ar(eye, tgt, roll_deg=-90 + rng.normal(scale=2))
        true.append(T)
        ax = rng.normal(size=3)
        ax /= np.linalg.norm(ax)
        ang = np.radians(rng.normal(scale=drift_rot_deg))
        Kx = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
        step = np.eye(4)
        step[:3, :3] = np.eye(3) + np.sin(ang) * Kx + (1 - np.cos(ang)) * Kx @ Kx
        step[:3, 3] = rng.normal(scale=drift_trans_m, size=3)
        drift = step @ drift
        rep.append(drift @ T)
    return rep, true


def degrade(img: np.ndarray, rng: np.random.Generator, blur_px: float = 2.5, noise: float = 2.5, gain_sd: float = 0.01) -> np.ndarray:
    """Motion blur (random direction/length), sensor noise, small exposure change."""
    L = rng.uniform(0, blur_px)
    if L > 0.6:
        k = int(np.ceil(L)) * 2 + 1
        ker = np.zeros((k, k), np.float32)
        a = rng.uniform(0, np.pi)
        c = k // 2
        for t in np.linspace(-L / 2, L / 2, 4 * k):
            ker[int(round(c + t * np.sin(a))), int(round(c + t * np.cos(a)))] = 1
        img = cv2.filter2D(img, -1, ker / ker.sum())
    out = img.astype(np.float32) * rng.normal(1.0, gain_sd) + rng.normal(scale=noise, size=img.shape)
    return np.clip(out, 0, 255).astype(np.uint8)
