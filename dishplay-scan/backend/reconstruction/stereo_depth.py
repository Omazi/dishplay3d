"""Temporal stereo between two posed views: verify/correct the relative pose,
rectify, run StereoSGBM with a left-right check, and triangulate.

The output depth map lives in the reference camera's ORIGINAL (unrectified)
image grid so it can be fused with the reference colour image and intrinsics.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .coordinates import box_corners, invert_rigid, rotation_angle_deg, transform_points


@dataclass
class View:
    frame_id: int
    image: np.ndarray            # BGR uint8 at working resolution
    K: np.ndarray                # 3x3 intrinsics at working resolution
    T_obj_from_cam: np.ndarray   # OpenCV camera -> object
    gray: np.ndarray | None = None
    features: tuple | None = None

    def gray_image(self) -> np.ndarray:
        if self.gray is None:
            self.gray = cv2.cvtColor(self.image, cv2.COLOR_BGR2GRAY)
        return self.gray


@dataclass
class StereoParams:
    block_size: int = 5
    uniqueness: int = 8
    speckle_window: int = 80
    speckle_range: int = 2
    lr_max_diff: float = 1.0
    min_texture: float = 3.0           # mean |gradient| in a 7x7 window (grey levels)
    max_disparities: int = 256
    min_matches: int = 40
    max_residual_px: float = 1.5       # Sampson residual allowed after (optional) correction
    accept_arkit_below_px: float = 0.6  # keep ARKit relative pose when already this consistent
    sift_features: int = 2500
    box_margin_m: float = 0.01
    edge_rel_jump: float = 0.02         # neighbour depth jump (relative) marking an occlusion border
    sparse_rel_tol: float = 0.03
    max_sparse_disagree: float = 0.25


@dataclass
class PairReport:
    ref_id: int
    other_id: int
    status: str
    reason: str = ""
    matches: int = 0
    inliers: int = 0
    residual_arkit_px: float = float("nan")
    residual_used_px: float = float("nan")
    pose_source: str = "arkit"
    rot_correction_deg: float = 0.0
    dir_correction_deg: float = 0.0
    valid_pixels: int = 0
    timings_ms: dict = field(default_factory=dict)


@dataclass
class StereoResult:
    report: PairReport
    depth: np.ndarray | None = None   # float32 metres, reference image grid, 0 = unknown


def _skew(t):
    return np.array([[0, -t[2], t[1]], [t[2], 0, -t[0]], [-t[1], t[0], 0]])


def _box_mask(view: View, size_m, margin: float) -> np.ndarray:
    h, w = view.image.shape[:2]
    corners = box_corners([size_m[0] + 2 * margin, size_m[1] + margin, size_m[2] + 2 * margin])
    corners[:, 1] -= margin / 2
    pc = transform_points(invert_rigid(view.T_obj_from_cam), corners)
    mask = np.zeros((h, w), np.uint8)
    if (pc[:, 2] <= 0.02).any():
        mask[:] = 255
        return mask
    uv = pc[:, :2] / pc[:, 2:3] * [view.K[0, 0], view.K[1, 1]] + [view.K[0, 2], view.K[1, 2]]
    hull = cv2.convexHull(uv.astype(np.float32))
    cv2.fillConvexPoly(mask, np.round(hull).astype(np.int32), 255)
    return mask


def _features(view: View, size_m, params: StereoParams):
    if view.features is None:
        sift = cv2.SIFT_create(nfeatures=params.sift_features)
        mask = cv2.dilate(_box_mask(view, size_m, params.box_margin_m), np.ones((15, 15), np.uint8))
        kps, desc = sift.detectAndCompute(view.gray_image(), mask)
        pts = np.array([k.pt for k in kps], np.float64).reshape(-1, 2)
        view.features = (pts, desc)
    return view.features


def _normalize(pts, K):
    return np.stack([(pts[:, 0] - K[0, 2]) / K[0, 0], (pts[:, 1] - K[1, 2]) / K[1, 1]], 1)


def _sampson_px(E, n1, n2, f):
    x1 = np.hstack([n1, np.ones((len(n1), 1))])
    x2 = np.hstack([n2, np.ones((len(n2), 1))])
    Ex1 = x1 @ E.T
    Etx2 = x2 @ E
    num = np.sum(x2 * Ex1, 1) ** 2
    den = Ex1[:, 0] ** 2 + Ex1[:, 1] ** 2 + Etx2[:, 0] ** 2 + Etx2[:, 1] ** 2
    return np.sqrt(num / np.maximum(den, 1e-18)) * f


def verify_relative_pose(ref: View, other: View, size_m, params: StereoParams, report: PairReport):
    """Return (R, t) mapping ref-camera coords to other-camera coords, or None.

    The ARKit relative pose is the metric initialisation. SIFT matches + RANSAC
    on the essential matrix check it; a correction (rotation and translation
    direction, ARKit baseline length kept) is used only if it reduces the
    epipolar residual and stays close to ARKit.
    """
    T_other_from_ref = invert_rigid(other.T_obj_from_cam) @ ref.T_obj_from_cam
    R_a, t_a = T_other_from_ref[:3, :3], T_other_from_ref[:3, 3]
    p1, d1 = _features(ref, size_m, params)
    p2, d2 = _features(other, size_m, params)
    if d1 is None or d2 is None or len(p1) < params.min_matches or len(p2) < params.min_matches:
        report.status, report.reason = "rejected", "few_features"
        return None
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    knn = matcher.knnMatch(d1, d2, k=2)
    good = [m[0] for m in knn if len(m) == 2 and m[0].distance < 0.75 * m[1].distance]
    report.matches = len(good)
    if len(good) < params.min_matches:
        report.status, report.reason = "rejected", "few_matches"
        return None
    m1 = p1[[g.queryIdx for g in good]]
    m2 = p2[[g.trainIdx for g in good]]
    n1, n2 = _normalize(m1, ref.K), _normalize(m2, other.K)
    f = float(ref.K[0, 0])
    E_a = _skew(t_a / np.linalg.norm(t_a)) @ R_a
    res_a = _sampson_px(E_a, n1, n2, f)
    E, inl = cv2.findEssentialMat(n1, n2, np.eye(3), method=cv2.RANSAC, prob=0.999, threshold=1.0 / f)
    if E is None or E.shape != (3, 3):
        report.status, report.reason = "rejected", "essential_failed"
        return None
    _, R_e, t_e, inl2 = cv2.recoverPose(E, n1, n2, np.eye(3), mask=inl.copy())
    inliers = inl2.ravel() > 0
    report.inliers = int(inliers.sum())
    if report.inliers < params.min_matches * 0.6:
        report.status, report.reason = "rejected", "few_inliers"
        return None
    # Residual of the ARKit pose on matches that agree with *some* rigid motion.
    report.residual_arkit_px = float(np.median(res_a[inliers]))
    t_e = t_e.ravel()
    rot_diff = rotation_angle_deg(R_e @ R_a.T)
    dir_diff = float(np.degrees(np.arccos(np.clip(np.dot(t_e, t_a / np.linalg.norm(t_a)), -1, 1))))
    report.rot_correction_deg, report.dir_correction_deg = rot_diff, dir_diff
    E_c = _skew(t_e) @ R_e
    res_c = float(np.median(_sampson_px(E_c, n1, n2, f)[inliers]))
    use_correction = (
        report.residual_arkit_px > params.accept_arkit_below_px
        and rot_diff < 2.0 and dir_diff < 8.0
        and res_c < 0.7 * report.residual_arkit_px
    )
    if use_correction:
        report.pose_source = "corrected"
        report.residual_used_px = res_c
        R, t = R_e, t_e * np.linalg.norm(t_a)
    else:
        report.residual_used_px = report.residual_arkit_px
        R, t = R_a, t_a
    if report.residual_used_px > params.max_residual_px:
        report.status, report.reason = "rejected", "pose_inconsistent"
        return None
    return R, t, m1[inliers], m2[inliers]


def _texture_mask(gray: np.ndarray, thr: float) -> np.ndarray:
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.blur(np.abs(gx) + np.abs(gy), (7, 7)) / 8.0
    return mag >= thr


def _sgbm(min_disp, num_disp, params: StereoParams):
    bs = params.block_size
    return cv2.StereoSGBM_create(
        minDisparity=int(min_disp), numDisparities=int(num_disp), blockSize=bs,
        P1=8 * 3 * bs * bs, P2=32 * 3 * bs * bs, disp12MaxDiff=-1,
        uniquenessRatio=params.uniqueness, speckleWindowSize=params.speckle_window,
        speckleRange=params.speckle_range, mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY)


def compute_pair_depth(ref: View, other: View, size_m, params: StereoParams = StereoParams()) -> StereoResult:
    import time
    report = PairReport(ref.frame_id, other.frame_id, "ok")
    t0 = time.perf_counter()
    rel = verify_relative_pose(ref, other, size_m, params, report)
    report.timings_ms["pose"] = (time.perf_counter() - t0) * 1000
    if rel is None:
        return StereoResult(report)
    R, t, in1, in2 = rel
    h, w = ref.image.shape[:2]
    size = (w, h)
    t1 = time.perf_counter()
    R1, R2, P1, P2, Q, _, _ = cv2.stereoRectify(ref.K, None, other.K, None, size, R, t.reshape(3, 1),
                                                flags=cv2.CALIB_ZERO_DISPARITY, alpha=-1)
    vertical = abs(P2[1, 3]) > abs(P2[0, 3])
    axis = 1 if vertical else 0
    shift = P2[axis, 3]
    swapped = shift > 0  # 'other' would be on the left/top: swap roles so disparities are positive
    map1 = cv2.initUndistortRectifyMap(ref.K, None, R1, P1, size, cv2.CV_32FC1)
    map2 = cv2.initUndistortRectifyMap(other.K, None, R2, P2, size, cv2.CV_32FC1)
    rect_ref = cv2.remap(ref.image, *map1, cv2.INTER_LINEAR)
    rect_oth = cv2.remap(other.image, *map2, cv2.INTER_LINEAR)
    f_rect = P1[0, 0]
    cx, cy = P1[0, 2], P1[1, 2]
    B = abs(shift) / f_rect
    # Box depth range in rectified reference camera -> disparity search range.
    corners = box_corners([size_m[0] + 0.02, size_m[1] + 0.02, size_m[2] + 0.02])
    corners[:, 1] -= 0.01
    pc = transform_points(invert_rigid(ref.T_obj_from_cam), corners) @ R1.T
    zmin, zmax = max(float(pc[:, 2].min()), 0.08), float(pc[:, 2].max())
    if zmax <= 0.08:
        report.status, report.reason = "rejected", "box_behind_camera"
        return StereoResult(report)
    dmin = int(np.floor(f_rect * B / zmax)) - 2
    dmax = int(np.ceil(f_rect * B / zmin)) + 2
    # Only if the box range is too wide for the matcher, narrow it around the disparities of
    # verified matches (robust percentiles + generous margin). Saturated disparities are rejected below.
    if dmax - dmin > params.max_disparities:
        r1 = cv2.undistortPoints(in1.reshape(-1, 1, 2), ref.K, None, R=R1, P=P1).reshape(-1, 2)
        r2 = cv2.undistortPoints(in2.reshape(-1, 1, 2), other.K, None, R=R2, P=P2).reshape(-1, 2)
        md = np.abs(r1[:, axis] - r2[:, axis])
        if len(md) >= 20:
            lo, hi = np.percentile(md, [1, 99])
            margin = max(0.5 * (hi - lo), 24.0)
            dmin = max(dmin, int(np.floor(lo - margin)))
            dmax = min(dmax, int(np.ceil(hi + margin)))
    report.timings_ms["disparity_range"] = float(dmax - dmin)
    num = int(np.ceil((dmax - dmin) / 16.0) * 16)
    if num > params.max_disparities:
        report.status, report.reason = "rejected", "disparity_range_too_large"
        return StereoResult(report)
    # Region of interest: projected box in rectified reference image.
    uv = pc[:, :2] / pc[:, 2:3] * f_rect + [cx, cy]
    roi = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(roi, np.round(cv2.convexHull(uv.astype(np.float32))).astype(np.int32), 255)
    if swapped:
        left, right = rect_oth, rect_ref
    else:
        left, right = rect_ref, rect_oth
    roi_l = roi
    if vertical:
        left, right, roi_l = left.transpose(1, 0, 2), right.transpose(1, 0, 2), roi.T
    if swapped:
        # disparity is measured on the reference image, which is now on the right:
        # mirror both images so the reference becomes the left image again.
        left, right = right[:, ::-1], left[:, ::-1]
        roi_l = roi_l[:, ::-1]
    left = np.ascontiguousarray(left)
    right = np.ascontiguousarray(right)
    roi_l = np.ascontiguousarray(roi_l)
    ys, xs = np.nonzero(roi_l)
    if len(xs) < 100 or num < 16:
        report.status, report.reason = "rejected", "box_not_visible"
        return StereoResult(report)
    y0, y1 = max(ys.min() - 4, 0), min(ys.max() + 5, left.shape[0])
    x0 = max(xs.min() - dmax - params.block_size - 8, 0)
    x1 = min(xs.max() + 5 + max(0, -dmin), left.shape[1])
    if x1 - x0 < num + params.block_size + 16 or y1 - y0 < params.block_size + 8:
        report.status, report.reason = "rejected", "roi_too_small"
        return StereoResult(report)
    L = left[y0:y1, x0:x1]
    Rr = right[y0:y1, x0:x1]
    gl = cv2.cvtColor(L, cv2.COLOR_BGR2GRAY)
    gr = cv2.cvtColor(Rr, cv2.COLOR_BGR2GRAY)
    matcher = _sgbm(dmin, num, params)
    dl = matcher.compute(gl, gr).astype(np.float32) / 16.0
    dr_flip = matcher.compute(np.ascontiguousarray(gr[:, ::-1]), np.ascontiguousarray(gl[:, ::-1])).astype(np.float32) / 16.0
    dr = dr_flip[:, ::-1]
    report.timings_ms["sgbm"] = (time.perf_counter() - t1) * 1000
    # Disparities at the ends of the search range are saturated (true value may lie outside).
    valid = (dl > dmin + 1.0) & (dl < dmin + num - 2.0)
    yy, xx = np.mgrid[0:dl.shape[0], 0:dl.shape[1]]
    xr = np.round(xx - dl).astype(np.int32)
    inb = valid & (xr >= 0) & (xr < dl.shape[1])
    lr_ok = np.zeros_like(valid)
    lr_ok[inb] = np.abs(dl[inb] - dr[yy[inb], xr[inb]]) <= params.lr_max_diff
    valid &= lr_ok
    valid &= _texture_mask(gl, params.min_texture)
    valid &= roi_l[y0:y1, x0:x1] > 0
    # Undo crop / mirror / transpose to rectified reference coordinates.
    x_full = xx + x0
    y_full = yy + y0
    if swapped:
        x_full = left.shape[1] - 1 - x_full
    if vertical:
        u_rect, v_rect = y_full, x_full
    else:
        u_rect, v_rect = x_full, y_full
    d = dl[valid]
    u = u_rect[valid].astype(np.float64)
    v = v_rect[valid].astype(np.float64)
    Z = f_rect * B / d
    X = (u - cx) * Z / f_rect
    Y = (v - cy) * Z / f_rect
    pts_rect = np.stack([X, Y, Z], 1)
    pts_ref = pts_rect @ R1  # R1 maps unrectified -> rectified, so inverse is R1^T (row-vector form)
    # Keep points inside the box (with margin) in object coordinates.
    pts_obj = transform_points(ref.T_obj_from_cam, pts_ref)
    m = params.box_margin_m
    keep = ((np.abs(pts_obj[:, 0]) <= size_m[0] / 2 + m) & (np.abs(pts_obj[:, 2]) <= size_m[2] / 2 + m)
            & (pts_obj[:, 1] >= -m) & (pts_obj[:, 1] <= size_m[1] + m) & (pts_ref[:, 2] > 0.05))
    pts_ref = pts_ref[keep]
    # Rasterise into the reference image grid (nearest surface wins).
    uv_ref = pts_ref[:, :2] / pts_ref[:, 2:3] * [ref.K[0, 0], ref.K[1, 1]] + [ref.K[0, 2], ref.K[1, 2]]
    ui = np.round(uv_ref[:, 0]).astype(np.int64)
    vi = np.round(uv_ref[:, 1]).astype(np.int64)
    inside = (ui >= 0) & (ui < w) & (vi >= 0) & (vi < h)
    ui, vi, z = ui[inside], vi[inside], pts_ref[inside, 2]
    depth = np.full((h, w), np.inf, np.float32)
    order = np.argsort(-z)  # write far first, near last
    depth[vi[order], ui[order]] = z[order]
    depth[~np.isfinite(depth)] = 0
    # Fill single-pixel holes from rounding only (no interpolation across real gaps).
    filled = cv2.morphologyEx(depth, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    near = cv2.dilate((depth > 0).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    hole = (depth == 0) & near & (filled > 0)
    count = cv2.blur((depth > 0).astype(np.float32), (3, 3)) * 9
    depth[hole & (count >= 5)] = filled[hole & (count >= 5)]
    # Remove "flying pixels" at depth discontinuities (occlusion borders): unknown, not interpolated.
    if params.edge_rel_jump > 0:
        dz = np.zeros_like(depth)
        for ax in (0, 1):
            g = np.abs(np.diff(depth, axis=ax))
            pad = [(0, 0), (0, 0)]
            pad[ax] = (0, 1)
            g1 = np.pad(g, pad)
            pad[ax] = (1, 0)
            g2 = np.pad(g, pad)
            dz = np.maximum(dz, np.maximum(g1, g2))
        both = depth > 0
        nb_ok = cv2.erode(both.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        jump = (dz > params.edge_rel_jump * depth) & nb_ok
        jump = cv2.dilate(jump.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        depth[jump] = 0
    # Validate dense depth against independently triangulated verified matches.
    P_ref = ref.K @ np.hstack([np.eye(3), np.zeros((3, 1))])
    P_oth = other.K @ np.hstack([R, t.reshape(3, 1)])
    X = cv2.triangulatePoints(P_ref, P_oth, in1.T.astype(np.float64), in2.T.astype(np.float64))
    zs = X[2] / X[3]
    ui1 = np.round(in1[:, 0]).astype(int)
    vi1 = np.round(in1[:, 1]).astype(int)
    okp = (ui1 >= 0) & (ui1 < w) & (vi1 >= 0) & (vi1 < h) & (zs > 0)
    dd = depth[vi1[okp], ui1[okp]]
    zz = zs[okp]
    both = dd > 0
    report.timings_ms["sparse_checks"] = float(both.sum())
    if both.sum() >= 15:
        rel = np.abs(dd[both] - zz[both]) / zz[both]
        bad = float((rel > params.sparse_rel_tol).mean())
        report.timings_ms["sparse_disagree"] = bad
        if bad > params.max_sparse_disagree:
            report.status, report.reason = "rejected", "dense_sparse_mismatch"
            return StereoResult(report)
    report.valid_pixels = int((depth > 0).sum())
    report.timings_ms["total"] = (time.perf_counter() - t0) * 1000
    if report.valid_pixels < 200:
        report.status, report.reason = "rejected", "too_few_valid_pixels"
        return StereoResult(report)
    return StereoResult(report, depth)


def combine_depths(depths: list[np.ndarray], rel_tol: float = 0.01, abs_tol: float = 0.002,
                   require_agreement: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Multi-view check on depth maps of the same reference view.

    Returns (depth, support) where support counts agreeing pairs per pixel.
    Pixels seen by several pairs that disagree are removed (unknown), never averaged.
    """
    stack = np.stack(depths, 0)
    valid = stack > 0
    nvalid = valid.sum(0)
    out = np.zeros(stack.shape[1:], np.float32)
    support = np.zeros(stack.shape[1:], np.uint8)
    if len(depths) == 1:
        out = stack[0].copy()
        support = valid[0].astype(np.uint8)
        if require_agreement:
            out[:] = 0
            support[:] = 0
        return out, support
    med = np.median(np.where(valid, stack, np.nan), axis=0) if nvalid.any() else out
    with np.errstate(invalid="ignore"):
        tol = np.maximum(abs_tol, rel_tol * med)
        agree = valid & (np.abs(stack - med[None]) <= tol[None])
    nagree = agree.sum(0)
    multi = nagree >= 2
    single = (nvalid == 1)
    mean_agree = np.where(agree, stack, 0).sum(0) / np.maximum(nagree, 1)
    out[multi] = mean_agree[multi]
    support[multi] = nagree[multi]
    if not require_agreement:
        out[single] = stack.max(0)[single]
        support[single] = 1
    return out, support
