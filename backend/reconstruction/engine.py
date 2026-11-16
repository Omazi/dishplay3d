"""Progressive reconstruction engine for ONE session (one worker process).

Deterministic for a given frame order and configuration: the replay tool and
the live worker both drive this class.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import open3d as o3d

from .coordinates import (inside_box, intrinsics_matrix, invert_rigid, mat4_from_rowmajor, object_from_camera_cv,
                          scale_intrinsics, transform_points)
from .consistency import DepthView, confirmed_depth, depth_scale_from_views, pick_neighbours
from .fusion import SOURCE_LIDAR, SOURCE_STEREO, FusionConfig, LiveFusion
from .mesh_preview import INTERPOLATED, MEASURED, DishFootprint, MeshConfig, crop_mesh, supported_mesh, surface_area
from .pair_selector import PairLimits, select_partners
from .preview_format import encode_geometry
from .stereo_depth import StereoParams, View, combine_depths, compute_pair_depth

PROVISIONAL = 4
ENGINE_VERSION = "p1-0.3.0"


@dataclass
class EngineConfig:
    preview_width: int = 640
    max_partners: int = 2
    retry_limit: int = 4
    snapshot_min_interval_s: float = 2.0
    snapshot_every_frames: int = 3
    max_snapshot_points: int = 100000
    max_snapshot_triangles: int = 60000
    mesh_min_frames: int = 3
    use_lidar: bool = False
    lidar_min_confidence: int = 2
    blur_ratio: float = 0.35
    outlier_dist_m: float = 0.003   # displayed points farther than this from the fused surface are hidden
    # Multi-view confirmation (see consistency.py): a frame is fused `confirm_lag` keyframes after it
    # arrives, so that views taken before AND after it can confirm or contradict its depth.
    confirm_min_views: int = 1
    confirm_lag: int = 2
    confirm_window: int = 12
    confirm_neighbours: int = 5
    # Baseline-length correction: each depth map is rescaled (one number) to agree with the views
    # already accepted, see consistency.depth_scale_from_views.
    hide_table: bool = True      # the box is rectangular, a plate is not: bare table in the corners is not shown
    scale_to_views: bool = True
    scale_max_dev: float = 0.06
    scale_gain: float = 0.8
    align_to_model: bool = False  # experimental: measured worse on synthetic data, see docs/TEST_REPORT.md
    max_backlog_live: int = 12  # beyond this, older frames are stored but deferred to finishing
    fusion: FusionConfig = field(default_factory=FusionConfig)
    mesh: MeshConfig = field(default_factory=MeshConfig)
    # live: no half-resolution pass (keeps the per-view cost low); finishing turns it on
    stereo: StereoParams = field(default_factory=lambda: StereoParams(coarse_fill=False))
    limits: PairLimits = field(default_factory=PairLimits)


@dataclass
class Box:
    T_world_from_object: np.ndarray
    size_m: tuple  # (width x, height y, depth z) in metres
    epoch: int
    revision: int = 0

    @staticmethod
    def from_json(d: dict) -> "Box":
        s = d["size_m"]
        return Box(mat4_from_rowmajor(d["T_world_from_object"]), (float(s["width"]), float(s["height"]), float(s["depth"])),
                   int(d.get("epoch", 0)), int(d.get("revision", 0)))


@dataclass
class FrameRecord:
    frame_id: int
    epoch: int
    meta: dict
    image_path: Path
    depth_path: Path | None
    conf_path: Path | None
    received_at: float
    status: str = "received"
    reason: str = ""
    attempts: int = 0
    sharpness: float = 0.0
    integrated_at: float | None = None


def point_to_mesh_distance(mesh, pts: np.ndarray) -> np.ndarray:
    import open3d as o3d
    scene = o3d.t.geometry.RaycastingScene()
    scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(mesh))
    return scene.compute_distance(o3d.core.Tensor(np.asarray(pts, np.float32))).numpy()


def laplacian_sharpness(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_32F).var())


class SessionEngine:
    def __init__(self, session_dir: Path, box: Box, config: EngineConfig | None = None,
                 emit: Callable[[dict], None] | None = None, clock: Callable[[], float] = time.time):
        self.dir = Path(session_dir)
        self.cfg = config or EngineConfig()
        self.emit = emit or (lambda e: None)
        self.clock = clock
        self.frames: dict[int, FrameRecord] = {}
        self.views: dict[int, View] = {}
        self.version = 0
        self.last_snapshot_t = 0.0
        self.frames_since_snapshot = 0
        self.pair_reports: list[dict] = []
        self.alignments: list[dict] = []
        self.pose_overrides: dict[int, np.ndarray] = {}   # refined T_obj_from_cam (finishing only)
        self._model_mesh = None
        self._depth_cache: list[DepthView] = []     # recent raw depth maps (bounded window)
        self._awaiting: list[tuple[int, np.ndarray]] = []  # (frame id, pair-support map) not fused yet
        self.confirm_stats = {"valid": 0, "confirmed": 0, "violated": 0}
        self.scale_stats = {"applied": 0, "skipped": 0, "abs_dev_sum": 0.0}
        self._scale_raw: list[float] = []
        self.latencies: list[float] = []
        self.snapshot_log: list[dict] = []
        self.paused = False
        self.set_box(box, reprocess=False)

    # ------------------------------------------------------------------ setup
    def set_box(self, box: Box, reprocess: bool = True):
        """Box revision: rebuild the volume from stored frames; never transform fused data silently."""
        self.box = box
        self.fusion = LiveFusion(box.size_m, self.cfg.fusion)
        self._model_mesh = None
        self._depth_cache = []
        self._awaiting = []
        self._scale_raw = []
        self.views.clear()
        if reprocess:
            for rec in self.frames.values():
                rec.attempts = 0
                rec.status = "received" if rec.epoch == box.epoch else "other_epoch"
            self.emit({"type": "status", "state": "box_revised", "box_revision": box.revision})

    # ----------------------------------------------------------------- frames
    def add_frame(self, meta: dict, image_path: Path, depth_path: Path | None = None, conf_path: Path | None = None,
                  received_at: float | None = None) -> FrameRecord:
        fid = int(meta["frame_id"])
        rec = FrameRecord(fid, int(meta.get("epoch", 0)), meta, Path(image_path), depth_path, conf_path,
                          received_at if received_at is not None else self.clock())
        self.frames[fid] = rec
        if rec.epoch != self.box.epoch:
            rec.status, rec.reason = "other_epoch", "tracking_epoch_differs_from_box"
            self._frame_event(rec)
        elif meta.get("tracking", {}).get("state") != "normal":
            rec.status, rec.reason = "rejected", "tracking_not_normal"
            self._frame_event(rec)
        return rec

    def _view(self, fid: int) -> View:
        v = self.views.get(fid)
        if v is not None:
            return v
        rec = self.frames[fid]
        img = cv2.imread(str(rec.image_path), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"cannot decode image of frame {fid}")
        intr = rec.meta["intrinsics"]
        K_full = intrinsics_matrix(intr["fx"], intr["fy"], intr["cx"], intr["cy"])
        h0, w0 = img.shape[:2]
        if (intr.get("width", w0), intr.get("height", h0)) != (w0, h0):
            K_full = scale_intrinsics(K_full, (intr["width"], intr["height"]), (w0, h0))
        w = min(self.cfg.preview_width, w0)
        h = int(round(h0 * w / w0))
        if (w, h) != (w0, h0):
            img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
            K = scale_intrinsics(K_full, (w0, h0), (w, h))
        else:
            K = K_full
        T_w_c = mat4_from_rowmajor(rec.meta["T_world_from_cameraAR"])
        v = View(fid, img, K, object_from_camera_cv(self.box.T_world_from_object, T_w_c))
        if fid in self.pose_overrides:
            v.T_obj_from_cam = self.pose_overrides[fid]
        self.views[fid] = v
        if len(self.views) > 400:  # bounded cache; images are reloaded from disk on demand
            for old in sorted(self.views)[: len(self.views) - 400]:
                if old != fid:
                    del self.views[old]
        return v

    def _candidates(self) -> dict:
        out = {}
        for fid, rec in self.frames.items():
            if rec.epoch == self.box.epoch and rec.status not in ("rejected", "other_epoch"):
                v = self._view(fid)
                out[fid] = (v.T_obj_from_cam, v.K, (v.image.shape[1], v.image.shape[0]))
        return out

    def pending(self) -> list[int]:
        return sorted(f for f, r in self.frames.items() if r.status in ("received", "waiting_partner"))

    def awaiting_confirmation(self) -> int:
        return len(self._awaiting)

    def process_pending(self, live: bool = True) -> int:
        """Process frames that still need depth. Returns number of newly integrated frames."""
        todo = [f for f in self.pending() if self.frames[f].status == "received"]
        retry = [f for f in self.pending() if self.frames[f].status == "waiting_partner"]
        if live and len(todo) > self.cfg.max_backlog_live:
            # Keep latency bounded: the oldest unprocessed frames wait for finishing (originals kept).
            for f in todo[: len(todo) - self.cfg.max_backlog_live]:
                self.frames[f].status, self.frames[f].reason = "deferred", "backlog_deferred_to_finish"
                self._frame_event(self.frames[f])
            todo = todo[-self.cfg.max_backlog_live:]
        n = 0
        for fid in todo + retry:
            n += self._process(fid)
        return n

    def _sharpness_ok(self, rec: FrameRecord, view: View) -> bool:
        rec.sharpness = laplacian_sharpness(view.gray_image())
        prev = [r.sharpness for r in self.frames.values() if r.sharpness > 0 and r.frame_id != rec.frame_id]
        if len(prev) >= 5 and rec.sharpness < self.cfg.blur_ratio * float(np.median(prev)):
            rec.status, rec.reason = "rejected", "blurred"
            return False
        return True

    def _process(self, fid: int) -> int:
        rec = self.frames[fid]
        try:
            ref = self._view(fid)
        except ValueError:
            rec.status, rec.reason = "rejected", "image_decode_failed"
            self._frame_event(rec)
            return 0
        if rec.attempts == 0 and not self._sharpness_ok(rec, ref):
            self._frame_event(rec)
            return 0
        if self.cfg.use_lidar and rec.depth_path is not None:
            return self._integrate_lidar(rec, ref)
        cands = self._candidates()
        partners = select_partners(fid, cands, self.box.size_m, self.cfg.max_partners, self.cfg.limits)
        depths, reports = [], []
        if partners:
            rec.attempts += 1
        for g in partners:
            res = compute_pair_depth(ref, self._view(g.other_id), self.box.size_m, self.cfg.stereo)
            rep = asdict(res.report)
            rep.update(baseline_ratio=g.baseline_ratio, axis_angle_deg=g.axis_angle_deg)
            reports.append(rep)
            self.pair_reports.append(rep)
            if res.depth is not None:
                depths.append(res.depth)
        if not depths:
            if rec.attempts >= self.cfg.retry_limit:
                rec.status, rec.reason = "rejected", "no_valid_pair"
            else:
                rec.status = "waiting_partner"
                rec.reason = reports[-1]["reason"] if reports else "no_partner_geometry_yet"
            self._frame_event(rec, reports)
            return 0
        depth, support = combine_depths(depths)
        if self.cfg.scale_to_views:
            depth = self._rescale(fid, depth, ref)
        # Not fused yet: wait for neighbouring views so the depth can be confirmed or contradicted.
        self._depth_cache.append(DepthView(fid, depth, ref.K, ref.T_obj_from_cam, cv2.GaussianBlur(ref.image, (5, 5), 0)))
        if len(self._depth_cache) > self.cfg.confirm_window:
            self._depth_cache.pop(0)
        self._awaiting.append((fid, support))
        rec.status, rec.reason = "depth_ready", ""
        return self._fuse_ready(flush=False)

    def _rescale(self, fid: int, depth: np.ndarray, ref: View) -> np.ndarray:
        probe = DepthView(fid, depth, ref.K, ref.T_obj_from_cam)
        est = depth_scale_from_views(probe, pick_neighbours(probe, self._depth_cache, self.cfg.confirm_neighbours),
                                     self.cfg.scale_max_dev)
        if est is None:
            self.scale_stats["skipped"] += 1
            return depth
        raw = est[0]
        # The accepted views are a consensus, not the truth. Only part of the difference is applied:
        # each view keeps a share of its own tracker-given scale, so the consensus cannot wander away
        # from the tracker's average scale while the view-to-view scatter is divided by five.
        self._scale_raw.append(raw)
        s = float(np.clip(raw ** self.cfg.scale_gain, 1 - self.cfg.scale_max_dev, 1 + self.cfg.scale_max_dev))
        self.scale_stats["applied"] += 1
        self.scale_stats["abs_dev_sum"] += abs(s - 1)
        return (depth * np.float32(s)).astype(np.float32)

    def _fuse_ready(self, flush: bool) -> int:
        """Fuse frames whose depth can now be judged by enough later views (all of them when flushing)."""
        n_done = 0
        keep_waiting = [] if flush else self._awaiting[-self.cfg.confirm_lag:] if self.cfg.confirm_lag > 0 else []
        ready = self._awaiting[: len(self._awaiting) - len(keep_waiting)]
        self._awaiting = keep_waiting
        for fid, support in ready:
            rec = self.frames[fid]
            dv = next((d for d in self._depth_cache if d.frame_id == fid), None)
            if dv is None:  # fell out of the window (cannot happen with lag < window); never fuse unchecked depth
                rec.status, rec.reason = "rejected", "confirmation_window_missed"
                self._frame_event(rec)
                continue
            others = pick_neighbours(dv, self._depth_cache, self.cfg.confirm_neighbours)
            depth, agree, st = confirmed_depth(dv, others, self.cfg.confirm_min_views)
            for k in self.confirm_stats:
                self.confirm_stats[k] += st[k]
            ref = self._view(fid)
            # support = number of independent confirmations (other views), at least 2 once confirmed
            sup = np.where(depth > 0, np.minimum(agree.astype(np.int32) + 1, 255), 0).astype(np.uint8)
            n = self.fusion.integrate(fid, ref.image, depth, ref.K, ref.T_obj_from_cam, sup, SOURCE_STEREO, ref.weak_texture())
            rec.status = "integrated" if n > 0 else "rejected"
            rec.reason = "" if n > 0 else ("not_confirmed_by_other_views" if st["valid"] else "no_points_in_box")
            rec.integrated_at = self.clock()
            self._frame_event(rec, points=n)
            if n > 0:
                self.frames_since_snapshot += 1
                self._model_mesh = None
                n_done += 1
        return n_done

    def flush(self) -> int:
        """Fuse the frames still waiting for later views (pause, finish, end of a replay)."""
        return self._fuse_ready(flush=True)

    def _integrate_lidar(self, rec: FrameRecord, ref: View) -> int:
        dmeta = rec.meta["depth"]
        dw, dh = int(dmeta["width"]), int(dmeta["height"])
        depth = np.fromfile(rec.depth_path, "<f4").reshape(dh, dw).astype(np.float32)
        if rec.conf_path is not None and rec.conf_path.exists():
            conf = np.fromfile(rec.conf_path, np.uint8).reshape(dh, dw)
            depth[conf < self.cfg.lidar_min_confidence] = 0
        di = dmeta["intrinsics"]
        K = intrinsics_matrix(di["fx"], di["fy"], di["cx"], di["cy"])
        color = cv2.resize(ref.image, (dw, dh), interpolation=cv2.INTER_AREA)
        depth[~np.isfinite(depth)] = 0
        n = self.fusion.integrate(rec.frame_id, color, depth, K, ref.T_obj_from_cam, None, SOURCE_LIDAR)
        rec.status, rec.reason = ("integrated", "lidar") if n else ("rejected", "lidar_no_points_in_box")
        rec.integrated_at = self.clock()
        self._frame_event(rec, points=n)
        if n:
            self.frames_since_snapshot += 1
        return int(n > 0)

    def _frame_event(self, rec: FrameRecord, reports=None, points: int = 0):
        self.emit({"type": "frame", "frame_id": rec.frame_id, "status": rec.status, "reason": rec.reason,
                   "points": int(points), "pairs": [{k: r[k] for k in ("other_id", "status", "reason", "inliers",
                                                                     "residual_used_px", "pose_source", "valid_pixels")}
                                                    for r in (reports or [])]})

    # --------------------------------------------------------------- coverage
    def coverage(self) -> dict:
        az_bins, el_edges = 12, (30.0, 55.0)
        grid = np.zeros((3, az_bins), int)
        centre = np.array([0.0, self.box.size_m[1] / 2, 0.0])
        for c in self.fusion.camera_centres.values():
            d = c - centre
            az = (np.degrees(np.arctan2(d[2], d[0])) + 360) % 360
            el = np.degrees(np.arctan2(d[1], np.hypot(d[0], d[2])))
            row = 0 if el < el_edges[0] else (1 if el < el_edges[1] else 2)
            grid[row, int(az // (360 / az_bins))] += 1
        return {"azimuth_bins": az_bins, "elevation_edges_deg": list(el_edges), "views_per_bin": grid.tolist(),
                "visited_bins": int((grid > 0).sum()), "total_bins": int(grid.size)}

    # --------------------------------------------------------------- snapshot
    def should_snapshot(self) -> bool:
        if self.frames_since_snapshot == 0:
            return False
        return (self.frames_since_snapshot >= self.cfg.snapshot_every_frames
                or self.clock() - self.last_snapshot_t >= self.cfg.snapshot_min_interval_s)

    def snapshot(self, force_mesh: bool | None = None) -> tuple[dict, bytes] | None:
        t0 = time.perf_counter()
        xyz, rgb, nframes, sup, src = self.fusion.measured_points()
        if len(xyz) == 0:
            return None
        weak = self.fusion.weak_cells()
        pcls = np.where((nframes >= 2) | (sup >= 2), MEASURED, PROVISIONAL).astype(np.uint8)
        pcls[weak] = INTERPOLATED  # confirmed by several views, but the matcher interpolated there
        n_integrated = len(self.fusion.integrated_frames)
        hidden = 0
        want_mesh = n_integrated >= self.cfg.mesh_min_frames if force_mesh is None else force_mesh
        verts = vrgbc = normals = tris = None
        kind = "points"
        areas = {"measured_m2": 0.0, "interpolated_m2": 0.0}
        if want_mesh:
            mcfg = MeshConfig(**{**asdict(self.cfg.mesh), "max_triangles": self.cfg.max_snapshot_triangles})
            V, Cv, N, cls, T = supported_mesh(self.fusion.extract_mesh(), self.box.size_m, xyz, nframes, mcfg, weak)
            table_hidden = False
            if len(T) and self.cfg.hide_table:
                fp = DishFootprint.from_vertices(V)
                if fp is not None:
                    keep_t = fp.keep(V)[T].all(1)
                    if 0 < keep_t.sum() < len(T):
                        V, Cv, N, cls, T = crop_mesh(V, Cv, N, cls, T, keep_t)
                        kp = fp.keep(xyz)
                        xyz, rgb, nframes, sup, pcls, weak = xyz[kp], rgb[kp], nframes[kp], sup[kp], pcls[kp], weak[kp]
                        table_hidden = True
            if len(T):
                verts, normals, tris = V, N, T
                vrgbc = np.concatenate([Cv, cls[:, None]], 1)
                kind = "points+mesh"
                areas = {"measured_m2": surface_area(V, T, cls, MEASURED), "interpolated_m2": surface_area(V, T, cls, INTERPOLATED)}
                # The surface is the consensus of all views. Samples that it contradicts (a view that
                # was slightly off, a guess on a uniform area) are hidden from the point display; they
                # stay in the store and in the exported points.ply.
                clean = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(V.astype(np.float64)),
                                                  o3d.utility.Vector3iVector(T.astype(np.int32)))
                keep = point_to_mesh_distance(clean, xyz) <= self.cfg.outlier_dist_m
                hidden = int((~keep).sum())
                xyz, rgb, nframes, sup, pcls, weak = xyz[keep], rgb[keep], nframes[keep], sup[keep], pcls[keep], weak[keep]
        if len(xyz) > self.cfg.max_snapshot_points:
            sel = np.linspace(0, len(xyz) - 1, self.cfg.max_snapshot_points).astype(np.int64)
        else:
            sel = slice(None)
        p_rgbc = np.concatenate([rgb, pcls[:, None]], 1)[sel]
        self.version += 1
        now = self.clock()
        integrated_ids = list(self.fusion.integrated_frames)
        header = {
            "schema": "dishplay.geometry/1", "engine": ENGINE_VERSION, "version": self.version, "kind": kind,
            "frame": "object", "units": "m", "box_revision": self.box.revision, "epoch": self.box.epoch,
            "box_size_m": list(self.box.size_m), "computed_at": now, "compute_ms": None,
            "last_frame_ids": integrated_ids[-5:], "integrated_frames": n_integrated,
            "received_frames": len(self.frames), "measured_points": int(len(xyz)),
            "confirmed_points": int((pcls == MEASURED).sum()), "hidden_inconsistent_points": hidden, "surface": areas, "coverage": self.coverage(),
            "classes": {"0": "measured", "1": "interpolated", "2": "estimated", "3": "tracking", "4": "provisional_single_view"},
        }
        header["table_hidden"] = bool(want_mesh and locals().get("table_hidden", False))
        header["compute_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        header.update(point_count=int(len(p_rgbc)), vertex_count=0 if verts is None else int(len(verts)),
                      triangle_count=0 if tris is None else int(len(tris)))
        blob = encode_geometry(header, xyz[sel], p_rgbc, verts, vrgbc, normals, tris)
        # Latency: receipt of each newly integrated frame -> first snapshot containing it.
        for fid in integrated_ids:
            rec = self.frames[fid]
            if not getattr(rec, "_in_snapshot", False):
                self.latencies.append(now - rec.received_at)
                rec._in_snapshot = True  # type: ignore[attr-defined]
        self.last_snapshot_t = now
        self.frames_since_snapshot = 0
        self.snapshot_log.append({k: header[k] for k in ("version", "kind", "computed_at", "integrated_frames",
                                                         "measured_points", "confirmed_points")}
                                 | {"triangles": 0 if tris is None else int(len(tris)), "bytes": len(blob),
                                    "compute_ms": header["compute_ms"], "surface": areas})
        return header, blob

    def metrics(self) -> dict:
        lat = np.array(self.latencies) if self.latencies else None
        statuses: dict[str, int] = {}
        reasons: dict[str, int] = {}
        for r in self.frames.values():
            statuses[r.status] = statuses.get(r.status, 0) + 1
            if r.reason:
                reasons[r.reason] = reasons.get(r.reason, 0) + 1
        pr = self.pair_reports
        return {
            "frames": statuses, "reasons": reasons, "snapshots": len(self.snapshot_log),
            "latency_s": None if lat is None else {"median": float(np.median(lat)), "p95": float(np.percentile(lat, 95)), "n": len(lat)},
            "alignment": {"applied": sum(a.get("applied", False) for a in self.alignments),
                          "median_shift_mm": float(np.median([a["shift_m"] for a in self.alignments if a.get("applied")]) * 1000)
                          if any(a.get("applied") for a in self.alignments) else None},
            "confirmation": dict(self.confirm_stats),
            "depth_scale": {"applied": self.scale_stats["applied"], "skipped": self.scale_stats["skipped"],
                            "mean_abs_correction_pct": round(100 * self.scale_stats["abs_dev_sum"] / max(1, self.scale_stats["applied"]), 3)},
            "pairs": {"total": len(pr), "ok": sum(p["status"] == "ok" for p in pr),
                      "corrected_pose": sum(p["pose_source"] == "corrected" for p in pr),
                      "median_residual_px": float(np.nanmedian([p["residual_used_px"] for p in pr])) if pr else None},
        }
