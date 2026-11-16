"""Fusion of validated depth maps (stereo or LiDAR) in the OBJECT frame.

Open3D's TSDF integrates depth that we computed; it does not infer depth from
RGB. The measured coloured point store is kept separately: every point there
comes from a validated depth pixel of a real frame.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
import open3d as o3d

from .coordinates import inside_box, invert_rigid, transform_points

SOURCE_STEREO = 0
SOURCE_LIDAR = 1


@dataclass
class FusionConfig:
    voxel_m: float = 0.003
    trunc_voxels: float = 4.0
    point_voxel_m: float = 0.0025      # dedup grid of the measured point store
    max_depth_m: float = 2.0
    box_margin_m: float = 0.01


@dataclass
class Observation:
    frame_id: int
    source: int
    n_points: int


class LiveFusion:
    def __init__(self, size_m, config: FusionConfig = FusionConfig()):
        self.size_m = tuple(float(v) for v in size_m)
        self.cfg = config
        self.reset()

    def reset(self):
        self.volume = o3d.pipelines.integration.ScalableTSDFVolume(
            voxel_length=self.cfg.voxel_m, sdf_trunc=self.cfg.voxel_m * self.cfg.trunc_voxels,
            color_type=o3d.pipelines.integration.TSDFVolumeColorType.RGB8)
        # Incremental voxel accumulator of measured samples (bounded memory).
        self._keys = np.zeros(0, np.int64)
        self._sum = np.zeros((0, 7), np.float64)  # x, y, z, r, g, b, n_samples
        self._nframes = np.zeros(0, np.int64)
        self._sup = np.zeros(0, np.uint8)
        self._src = np.zeros(0, np.uint8)
        self._raw = 0
        self.observations: list[Observation] = []
        self.integrated_frames: list[int] = []
        self.camera_centres: dict[int, np.ndarray] = {}

    def integrate(self, frame_id: int, image_bgr: np.ndarray, depth: np.ndarray, K: np.ndarray,
                  T_obj_from_cam: np.ndarray, support: np.ndarray | None = None, source: int = SOURCE_STEREO) -> int:
        """Integrate a validated depth map. depth: float32 metres on the colour grid (0 = unknown)."""
        h, w = depth.shape
        if image_bgr.shape[:2] != (h, w):
            image_bgr = cv2.resize(image_bgr, (w, h), interpolation=cv2.INTER_AREA)
        depth = depth.astype(np.float32).copy()
        vs, us = np.nonzero(depth > 0)
        z = depth[vs, us].astype(np.float64)
        pc = np.stack([(us - K[0, 2]) / K[0, 0] * z, (vs - K[1, 2]) / K[1, 1] * z, z], 1)
        po = transform_points(T_obj_from_cam, pc)
        keep = inside_box(po, self.size_m, margin=self.cfg.box_margin_m, below=self.cfg.box_margin_m)
        depth[vs[~keep], us[~keep]] = 0
        vs, us, po = vs[keep], us[keep], po[keep]
        if len(po) == 0:
            return 0
        rgb = np.ascontiguousarray(image_bgr[:, :, ::-1])
        rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
            o3d.geometry.Image(rgb), o3d.geometry.Image(depth), depth_scale=1.0,
            depth_trunc=self.cfg.max_depth_m, convert_rgb_to_intensity=False)
        intr = o3d.camera.PinholeCameraIntrinsic(w, h, K[0, 0], K[1, 1], K[0, 2], K[1, 2])
        self.volume.integrate(rgbd, intr, invert_rigid(T_obj_from_cam))
        sup = support[vs, us] if support is not None else np.ones(len(po), np.uint8)
        self._accumulate(po, rgb[vs, us], sup.astype(np.uint8), source)
        self.observations.append(Observation(frame_id, source, len(po)))
        self.integrated_frames.append(frame_id)
        self.camera_centres[frame_id] = T_obj_from_cam[:3, 3].copy()
        return len(po)

    # ----------------------------------------------------------------- points
    def _cell_keys(self, p: np.ndarray) -> np.ndarray:
        c = np.floor(p / self.cfg.point_voxel_m).astype(np.int64) + 4096
        return (c[:, 0] * 8192 + c[:, 1]) * 8192 + c[:, 2]

    def _accumulate(self, po: np.ndarray, rgb: np.ndarray, sup: np.ndarray, source: int):
        self._raw += len(po)
        nk = self._cell_keys(po)
        uk, inv = np.unique(nk, return_inverse=True)
        vals = np.concatenate([po, rgb.astype(np.float64), np.ones((len(po), 1))], 1)
        fsum = np.stack([np.bincount(inv, weights=vals[:, j], minlength=len(uk)) for j in range(7)], 1)
        fsup = np.zeros(len(uk), np.uint8)
        np.maximum.at(fsup, inv, sup)
        keys = np.concatenate([self._keys, uk])
        allk, ainv = np.unique(keys, return_inverse=True)
        n = len(allk)
        tot = np.zeros((n, 7))
        np.add.at(tot, ainv, np.concatenate([self._sum, fsum]))
        nfr = np.zeros(n, np.int64)
        np.add.at(nfr, ainv, np.concatenate([self._nframes, np.ones(len(uk), np.int64)]))
        sp = np.zeros(n, np.uint8)
        np.maximum.at(sp, ainv, np.concatenate([self._sup, fsup]))
        sr = np.zeros(n, np.uint8)
        np.maximum.at(sr, ainv, np.concatenate([self._src, np.full(len(uk), source, np.uint8)]))
        self._keys, self._sum, self._nframes, self._sup, self._src = allk, tot, nfr, sp, sr

    def measured_points(self):
        """Measured points, one per 2.5 mm cell: (xyz f32, rgb u8, n_frames u16, max pair support u8, source u8)."""
        cnt = self._sum[:, 6:7] if len(self._sum) else np.ones((0, 1))
        xyz = (self._sum[:, :3] / np.maximum(cnt, 1)).astype(np.float32)
        rgb = np.clip(self._sum[:, 3:6] / np.maximum(cnt, 1), 0, 255).astype(np.uint8)
        return xyz, rgb, self._nframes.astype(np.uint16), self._sup.copy(), self._src.copy()

    def raw_point_count(self) -> int:
        return int(self._raw)

    def align_to_model(self, depth: np.ndarray, K: np.ndarray, T_obj_from_cam: np.ndarray, model_mesh,
                       max_corr_m: float = 0.006, max_shift_m: float = 0.015, max_rot_deg: float = 2.0,
                       min_fitness: float = 0.35, max_points: int = 6000):
        """Point-to-plane ICP of a new depth map onto the current fused surface.

        Returns (T_corr in object frame or None, info). The correction is applied only when the
        overlap is sufficient and the correction is small: it compensates tracking drift, it does
        not relocalise an unrelated view.
        """
        info = {"applied": False}
        if model_mesh is None or len(model_mesh.triangles) < 200:
            info["reason"] = "no_model"
            return None, info
        vs, us = np.nonzero(depth > 0)
        if len(vs) < 500:
            info["reason"] = "few_points"
            return None, info
        sel = np.linspace(0, len(vs) - 1, min(max_points, len(vs))).astype(np.int64)
        vs, us = vs[sel], us[sel]
        z = depth[vs, us].astype(np.float64)
        pc = np.stack([(us - K[0, 2]) / K[0, 0] * z, (vs - K[1, 2]) / K[1, 1] * z, z], 1)
        src = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(transform_points(T_obj_from_cam, pc)))
        tgt = o3d.geometry.PointCloud(model_mesh.vertices)
        model_mesh.compute_vertex_normals()
        tgt.normals = model_mesh.vertex_normals
        reg = o3d.pipelines.registration.registration_icp(
            src, tgt, max_corr_m, np.eye(4), o3d.pipelines.registration.TransformationEstimationPointToPlane(),
            o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=30))
        T = np.asarray(reg.transformation)
        shift = float(np.linalg.norm(T[:3, 3]))
        rot = float(np.degrees(np.arccos(np.clip((np.trace(T[:3, :3]) - 1) / 2, -1, 1))))
        info.update(fitness=float(reg.fitness), rmse_m=float(reg.inlier_rmse), shift_m=shift, rot_deg=rot)
        if reg.fitness < min_fitness:
            info["reason"] = "low_overlap"
            return None, info
        if shift > max_shift_m or rot > max_rot_deg:
            info["reason"] = "correction_too_large"
            return None, info
        info["applied"] = True
        return T, info

    def extract_mesh(self) -> o3d.geometry.TriangleMesh:
        return self.volume.extract_triangle_mesh()
