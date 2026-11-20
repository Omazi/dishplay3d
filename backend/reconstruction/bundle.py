"""Global pose refinement for finishing (bundle adjustment on SIFT tracks).

ARKit poses are accurate between neighbouring frames but drift over a whole tour, so the first
and last views of a lap do not agree and surfaces get doubled or blurred. Here every camera
pose is refined together so that the same physical points, tracked across many views (including
views of the same place taken much later), reproject consistently.

What keeps it honest:
- ARKit stays the reference for scale and local motion: consecutive frames are tied to their
  ARKit relative motion, the first camera is fixed (the box frame does not move);
- the result is used only if it lowers the reprojection error and stays close to ARKit;
  otherwise the ARKit poses are kept, and the report says so.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import cv2
import numpy as np
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix
from scipy.spatial.transform import Rotation

from .coordinates import invert_rigid
from .stereo_depth import StereoParams, View, _features


@dataclass
class BundleConfig:
    seq_neighbours: int = 3            # match each frame with the next N frames
    loop_max_dist_m: float = 0.06      # also match frames far apart in time but close in space...
    loop_max_angle_deg: float = 20.0   # ...looking in a similar direction
    loop_min_gap: int = 8
    loop_per_frame: int = 2
    min_track_len: int = 3
    max_points: int = 12000
    init_max_reproj_px: float = 25.0
    # Visual-inertial tracking is very accurate from one keyframe to the next: tie consecutive frames
    # firmly to it (measured: loose ties let the cameras slide along their viewing axis).
    prior_trans_m: float = 0.0003      # 1 px of residual per 0.3 mm change of a consecutive relative translation
    prior_rot_rad: float = 0.0004      # 1 px per ~0.023 degree change of a consecutive relative rotation
    max_iterations: int = 40
    # Second stage, only when the first leaves a high error: measured on a real capture (5.5 px of error to
    # start with), 40 steps under the firm ties stopped at 1.15 px and 300 steps reached 0.72 px, while ties
    # three times looser converged to 0.35 px within 120 steps.
    relax_above_px: float = 0.5        # median reprojection error after the first stage that triggers it
    relax_factor: float = 10.0         # how much looser the ties to the tracker are (1 = no second stage)
    relax_iterations: int = 120
    # Looser ties are safe only when the picture itself holds the cameras: with few tracked points they let the
    # cameras slide along their viewing axis (seen on the weakly textured synthetic bowl).
    relax_min_obs_per_view: int = 300
    accept_max_shift_m: float = 0.05
    accept_max_rot_deg: float = 6.0


@dataclass
class BundleResult:
    poses: dict                        # frame_id -> refined T_obj_from_cam (empty when not applied)
    applied: bool
    info: dict = field(default_factory=dict)


def _match(a: View, b: View, size_m, params: StereoParams):
    pa, da = _features(a, size_m, params)
    pb, db = _features(b, size_m, params)
    if da is None or db is None or len(pa) < 30 or len(pb) < 30:
        return np.zeros((0, 2), int)
    knn = cv2.BFMatcher(cv2.NORM_L2).knnMatch(da, db, k=2)
    good = [(m[0].queryIdx, m[0].trainIdx) for m in knn if len(m) == 2 and m[0].distance < 0.72 * m[1].distance]
    if len(good) < 25:
        return np.zeros((0, 2), int)
    g = np.array(good)
    n1 = np.stack([(pa[g[:, 0], 0] - a.K[0, 2]) / a.K[0, 0], (pa[g[:, 0], 1] - a.K[1, 2]) / a.K[1, 1]], 1)
    n2 = np.stack([(pb[g[:, 1], 0] - b.K[0, 2]) / b.K[0, 0], (pb[g[:, 1], 1] - b.K[1, 2]) / b.K[1, 1]], 1)
    E, inl = cv2.findEssentialMat(n1, n2, np.eye(3), method=cv2.RANSAC, prob=0.99, threshold=1.5 / a.K[0, 0], maxIters=300)
    if E is None or inl is None or inl.sum() < 20:
        return np.zeros((0, 2), int)
    return g[inl.ravel() > 0]


def _pairs(ids: list[int], views: dict, cfg: BundleConfig) -> list[tuple[int, int]]:
    out = set()
    for k, i in enumerate(ids):
        for j in ids[k + 1: k + 1 + cfg.seq_neighbours]:
            out.add((i, j))
    C = np.array([views[i].T_obj_from_cam[:3, 3] for i in ids])
    Z = np.array([views[i].T_obj_from_cam[:3, 2] for i in ids])
    for k, i in enumerate(ids):
        d = np.linalg.norm(C - C[k], axis=1)
        ang = np.degrees(np.arccos(np.clip(Z @ Z[k], -1, 1)))
        cand = [m for m in np.argsort(d) if abs(m - k) >= cfg.loop_min_gap and d[m] <= cfg.loop_max_dist_m and ang[m] <= cfg.loop_max_angle_deg]
        for m in cand[: cfg.loop_per_frame]:
            out.add((min(i, ids[m]), max(i, ids[m])))
    return sorted(out)


def _tracks(ids, views, pairs, size_m, params, cfg):
    parent: dict = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    n_matches = 0
    for i, j in pairs:
        for qa, qb in _match(views[i], views[j], size_m, params):
            ra, rb = find((i, int(qa))), find((j, int(qb)))
            if ra != rb:
                parent[ra] = rb
            n_matches += 1
    groups: dict = {}
    for node in list(parent):
        groups.setdefault(find(node), []).append(node)
    tracks = []
    for nodes in groups.values():
        frames = [f for f, _ in nodes]
        if len(nodes) >= cfg.min_track_len and len(set(frames)) == len(frames):  # one keypoint per frame
            tracks.append(nodes)
    return tracks, n_matches


def _triangulate(nodes, views):
    """Linear triangulation from the two most separated views of the track (object frame)."""
    best, pair = -1.0, None
    for a in range(len(nodes)):
        for b in range(a + 1, len(nodes)):
            d = np.linalg.norm(views[nodes[a][0]].T_obj_from_cam[:3, 3] - views[nodes[b][0]].T_obj_from_cam[:3, 3])
            if d > best:
                best, pair = d, (nodes[a], nodes[b])
    if pair is None or best < 0.01:
        return None
    Ps, xs = [], []
    for f, k in pair:
        v = views[f]
        Ps.append(v.K @ invert_rigid(v.T_obj_from_cam)[:3])
        xs.append(v.features[0][k])
    X = cv2.triangulatePoints(Ps[0], Ps[1], np.array(xs[0], float).reshape(2, 1), np.array(xs[1], float).reshape(2, 1))
    if abs(X[3, 0]) < 1e-12:
        return None
    return (X[:3, 0] / X[3, 0])


def _rotate(rv: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Rodrigues rotation of points p (N,3) by rotation vectors rv (N,3)."""
    theta = np.linalg.norm(rv, axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        k = np.where(theta > 1e-12, rv / theta, 0.0)
    c, s = np.cos(theta), np.sin(theta)
    return c * p + s * np.cross(k, p) + (1 - c) * np.sum(k * p, axis=1, keepdims=True) * k


def refine_poses(views: dict, size_m, params: StereoParams | None = None, cfg: BundleConfig | None = None) -> BundleResult:
    """views: frame_id -> View (finishing resolution, ARKit poses). Returns refined poses or applied=False."""
    cfg = cfg or BundleConfig()
    params = params or StereoParams()
    t0 = time.perf_counter()
    ids = sorted(views)
    if len(ids) < 6:
        return BundleResult({}, False, {"reason": "too_few_frames"})
    pairs = _pairs(ids, views, cfg)
    tracks, n_matches = _tracks(ids, views, pairs, size_m, params, cfg)
    cam_index = {f: k for k, f in enumerate(ids)}
    T_co0 = np.array([invert_rigid(views[f].T_obj_from_cam) for f in ids])   # camera <- object, initial
    K = np.array([views[f].K for f in ids])
    pts, obs_cam, obs_pt, obs_xy = [], [], [], []
    for nodes in tracks:
        X = _triangulate(nodes, views)
        if X is None or not np.all(np.isfinite(X)):
            continue
        ok = True
        rows = []
        for f, k in nodes:
            c = cam_index[f]
            xc = T_co0[c, :3, :3] @ X + T_co0[c, :3, 3]
            if xc[2] <= 0.03:
                ok = False
                break
            uv = xc[:2] / xc[2] * [K[c, 0, 0], K[c, 1, 1]] + [K[c, 0, 2], K[c, 1, 2]]
            xy = views[f].features[0][k]
            if np.linalg.norm(uv - xy) > cfg.init_max_reproj_px:
                ok = False
                break
            rows.append((c, xy))
        if ok:
            for c, xy in rows:
                obs_cam.append(c)
                obs_pt.append(len(pts))
                obs_xy.append(xy)
            pts.append(X)
    info = {"frames": len(ids), "pairs": len(pairs), "matches": n_matches, "tracks": len(tracks), "points": len(pts),
            "observations": len(obs_cam)}
    if len(pts) < 200:
        info["reason"] = "too_few_tracks"
        return BundleResult({}, False, info)
    pts = np.array(pts)
    obs_cam, obs_pt, obs_xy = np.array(obs_cam), np.array(obs_pt), np.array(obs_xy, float)
    if len(pts) > cfg.max_points:  # keep the longest tracks
        length = np.bincount(obs_pt, minlength=len(pts))
        keep = np.argsort(-length, kind="stable")[: cfg.max_points]
        remap = -np.ones(len(pts), int)
        remap[keep] = np.arange(len(keep))
        sel = remap[obs_pt] >= 0
        obs_cam, obs_xy, obs_pt = obs_cam[sel], obs_xy[sel], remap[obs_pt[sel]]
        pts = pts[keep]
    nc, npt, nobs = len(ids), len(pts), len(obs_cam)
    rv0 = Rotation.from_matrix(T_co0[:, :3, :3]).as_rotvec()
    t0v = T_co0[:, :3, 3].copy()
    # ARKit relative motion between consecutive frames (camera k+1 <- camera k)
    R0 = T_co0[:, :3, :3]
    Rrel0 = np.einsum("nij,nkj->nik", R0[1:], R0[:-1])
    trel0 = t0v[1:] - np.einsum("nij,nj->ni", Rrel0, t0v[:-1])
    fx, fy, cx, cy = K[obs_cam, 0, 0], K[obs_cam, 1, 1], K[obs_cam, 0, 2], K[obs_cam, 1, 2]

    def unpack(x):
        return x[: nc * 3].reshape(nc, 3), x[nc * 3: nc * 6].reshape(nc, 3), x[nc * 6:].reshape(npt, 3)

    def residuals(x, tie=1.0):
        rv, t, X = unpack(x)
        xc = _rotate(rv[obs_cam], X[obs_pt]) + t[obs_cam]
        z = np.maximum(xc[:, 2], 1e-6)
        ru = xc[:, 0] / z * fx + cx - obs_xy[:, 0]
        rvv = xc[:, 1] / z * fy + cy - obs_xy[:, 1]
        R = Rotation.from_rotvec(rv).as_matrix()
        Rrel = np.einsum("nij,nkj->nik", R[1:], R[:-1])
        trel = t[1:] - np.einsum("nij,nj->ni", Rrel, t[:-1])
        dr = Rotation.from_matrix(np.einsum("nij,nkj->nik", Rrel, Rrel0)).as_rotvec() / (cfg.prior_rot_rad * tie)
        dt = (trel - trel0) / (cfg.prior_trans_m * tie)
        gauge = np.concatenate([(rv[0] - rv0[0]) / 1e-5, (t[0] - t0v[0]) / 1e-6])
        return np.concatenate([ru, rvv, dr.ravel(), dt.ravel(), gauge])

    m = 2 * nobs + 6 * (nc - 1) + 6
    S = lil_matrix((m, nc * 6 + npt * 3), dtype=np.uint8)
    o = np.arange(nobs)
    for half in (0, nobs):
        for d in range(3):
            S[half + o, obs_cam * 3 + d] = 1
            S[half + o, nc * 3 + obs_cam * 3 + d] = 1
            S[half + o, nc * 6 + obs_pt * 3 + d] = 1
    base = 2 * nobs
    for k in range(nc - 1):
        cols = [c * 3 + d for c in (k, k + 1) for d in range(3)] + [nc * 3 + c * 3 + d for c in (k, k + 1) for d in range(3)]
        for r in range(3):
            S[base + k * 3 + r, cols] = 1
            S[base + 3 * (nc - 1) + k * 3 + r, cols] = 1
    g0 = base + 6 * (nc - 1)
    for d in range(3):
        S[g0 + d, d] = 1
        S[g0 + 3 + d, nc * 3 + d] = 1
    x0 = np.concatenate([rv0.ravel(), t0v.ravel(), pts.ravel()])
    r0 = residuals(x0)
    reproj0 = float(np.median(np.hypot(r0[:nobs], r0[nobs:2 * nobs])))
    sol = least_squares(residuals, x0, jac_sparsity=S, method="trf", loss="soft_l1", f_scale=1.5, x_scale="jac",
                        max_nfev=cfg.max_iterations, verbose=0)
    r1 = residuals(sol.x)
    reproj1 = float(np.median(np.hypot(r1[:nobs], r1[nobs:2 * nobs])))
    x, steps, relaxed, reproj_first = sol.x, int(sol.nfev), False, reproj1
    if cfg.relax_factor > 1.0 and reproj1 > cfg.relax_above_px and nobs >= cfg.relax_min_obs_per_view * nc:
        # The tracker's frame-to-frame motion is less exact on this capture than the firm ties assume (fast
        # movement, rolling shutter): continue from where the first stage stopped, with looser ties.
        sol2 = least_squares(residuals, x, jac_sparsity=S, method="trf", loss="soft_l1", f_scale=1.5, x_scale="jac",
                             max_nfev=cfg.relax_iterations, verbose=0, args=(cfg.relax_factor,))
        r2 = residuals(sol2.x, cfg.relax_factor)
        reproj2 = float(np.median(np.hypot(r2[:nobs], r2[nobs:2 * nobs])))
        steps += int(sol2.nfev)
        if reproj2 < 0.8 * reproj1:
            x, reproj1, relaxed = sol2.x, reproj2, True
    rv, t, _ = unpack(x)
    R = Rotation.from_rotvec(rv).as_matrix()
    poses, shift, rot = {}, [], []
    for k, f in enumerate(ids):
        T = np.eye(4)
        T[:3, :3], T[:3, 3] = R[k], t[k]
        Toc = invert_rigid(T)
        poses[f] = Toc
        shift.append(float(np.linalg.norm(Toc[:3, 3] - views[f].T_obj_from_cam[:3, 3])))
        dR = Toc[:3, :3] @ views[f].T_obj_from_cam[:3, :3].T
        rot.append(float(np.degrees(np.arccos(np.clip((np.trace(dR) - 1) / 2, -1, 1)))))
    info.update(reproj_before_px=reproj0, reproj_after_px=reproj1, max_shift_mm=max(shift) * 1000, median_shift_mm=float(np.median(shift)) * 1000,
                max_rot_deg=max(rot), seconds=time.perf_counter() - t0, iterations=steps, relaxed=relaxed,
                reproj_first_stage_px=reproj_first, obs_per_view=round(nobs / nc))
    ok = (reproj1 < 0.9 * reproj0 or reproj1 < 0.6) and max(shift) <= cfg.accept_max_shift_m and max(rot) <= cfg.accept_max_rot_deg
    if not ok:
        info["reason"] = "not_better_or_too_far_from_arkit"
        return BundleResult({}, False, info)
    return BundleResult(poses, True, info)
