"""Pose of a new view during the scan, tied to what is already reconstructed.

The phone's tracker places each view to within a few millimetres. For two views a few centimetres apart
that is several per cent of the distance between them, and the depth computed from the pair is off by as
much: the views then contradict each other and much of what was measured is thrown away while scanning
(41 % on a real capture of a pair of shoes with the tracker's poses, 11 % with the poses found by the global
refinement of the finishing step).

The global refinement needs all the views. During the scan, each new view is instead tied to the views
already processed:

  * points of the dish matched in a view that already has a depth map are known in 3-D: they must project
    where they are seen in the new view. This is what fixes the distance between the cameras, which the
    pictures alone cannot see;
  * every other match (table, background, the whole picture) must lie on its epipolar line: this fixes the
    orientation of the new view and the direction of its motion;
  * the answer must stay close to the tracker's.

Only a share of the correction is applied (`gain`): each view keeps part of the tracker's own answer, which
holds the model back from wandering away from the tracker's frame. Variants that looked better on paper were
measured on six real captures and were less reliable (correcting each view fully and giving back only the
offset common to neighbours; computing the depth with the exact pose and placing it with a leaked one): see
docs/TEST_REPORT.md.

When the ties cannot give a pose (too few known points, no solution that fits), the view is not left at the
tracker's raw pose, which by then may be several millimetres away from where the model is: it is placed where
its neighbours say the model is (`common_correction`), so that one view without ties does not start a chain
of views that contradict everything before them.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from scipy.optimize import least_squares

from .coordinates import backproject, invert_rigid, transform_points


@dataclass
class AnchorConfig:
    min_model_points: int = 40       # matched points with a known depth; below this the pose is left as reported
    leave_below_px: float = 0.8      # the reported pose already fits what is built to within this: left alone
    gain: float = 0.8                # share of the correction that is applied
    prior_shift_m: float = 0.004     # size of the error expected from the tracker (position, orientation)...
    prior_rot_deg: float = 0.4
    prior_weight: float = 3.0        # ...and how many matches one such deviation weighs (squared)
    max_shift_m: float = 0.015       # a solution farther than this from the tracker is not a tracker error
    max_rot_deg: float = 1.5
    improve_to: float = 0.7          # the residual must fall to this share of what it was...
    max_residual_px: float = 1.5     # ...and below this
    loss_px: float = 1.0             # matches off by more than this weigh less and less
    max_points_per_view: int = 800   # of each kind (known depth / epipolar only), spread over the matches
    guard_from_tracker: bool = True  # "too far" is measured from the tracker's pose (else from the neighbours' answer)


@dataclass
class Tie:
    """What one view already processed says about the new one: the same points seen in both."""
    K: np.ndarray                    # intrinsics of the processed view
    T_obj_from_cam: np.ndarray       # its pose (fixed)
    px_new: np.ndarray               # Nx2 pixels in the new view
    px_partner: np.ndarray           # Nx2 pixels in the processed view
    depth: np.ndarray                # N depths in the processed view (metres), 0 = unknown


def sample_depth(depth: np.ndarray, px: np.ndarray, max_rel_step: float = 0.02) -> np.ndarray:
    """Depth under each (sub)pixel position, 0 where it cannot be trusted: outside the picture, in or next to
    a hole, or next to a step (on which side of an edge a feature lies is not known to a pixel)."""
    h, w = depth.shape
    px = np.asarray(px, np.float64).reshape(-1, 2)
    out = np.zeros(len(px))
    iu, iv = np.round(px[:, 0]).astype(np.int64), np.round(px[:, 1]).astype(np.int64)
    ok = (iu >= 1) & (iu < w - 1) & (iv >= 1) & (iv < h - 1)
    if not ok.any():
        return out
    idx = np.nonzero(ok)[0]
    win = np.stack([depth[iv[idx] + dv, iu[idx] + du] for dv in (-1, 0, 1) for du in (-1, 0, 1)], 1).astype(np.float64)
    centre = win[:, 4]
    good = (win > 0).all(1) & (win.max(1) - win.min(1) <= max_rel_step * np.maximum(centre, 1e-6))
    idx = idx[good]
    if len(idx) == 0:
        return out
    u, v = px[idx, 0], px[idx, 1]
    u0 = np.clip(np.floor(u).astype(np.int64), iu[idx] - 1, iu[idx])
    v0 = np.clip(np.floor(v).astype(np.int64), iv[idx] - 1, iv[idx])
    a, b = u - u0, v - v0
    out[idx] = ((1 - a) * (1 - b) * depth[v0, u0] + a * (1 - b) * depth[v0, u0 + 1]
                + (1 - a) * b * depth[v0 + 1, u0] + a * b * depth[v0 + 1, u0 + 1])
    return out


def _delta(xi: np.ndarray) -> np.ndarray:
    D = np.eye(4)
    D[:3, :3] = cv2.Rodrigues(np.asarray(xi[:3], np.float64).reshape(3, 1))[0]
    D[:3, 3] = xi[3:]
    return D


def _spread(n: int, limit: int) -> np.ndarray:
    return np.arange(n) if n <= limit else np.linspace(0, n - 1, limit).astype(np.int64)


class _Problem:
    """Residuals of a candidate pose T0 * delta(xi) of the new view."""

    def __init__(self, K: np.ndarray, ties: list[Tie], cfg: AnchorConfig):
        self.K, self.cfg = K, cfg
        self.f = float(K[0, 0])
        Xo, px = [], []
        self.epi = []            # (rays in the new view Nx3, rays in the processed view Nx3, T_cam_from_obj of that view)
        for t in ties:
            known = np.asarray(t.depth) > 0
            if known.any():
                sel = np.nonzero(known)[0][_spread(int(known.sum()), cfg.max_points_per_view)]
                Xo.append(transform_points(t.T_obj_from_cam, backproject(t.K, t.px_partner[sel], t.depth[sel])))
                px.append(np.asarray(t.px_new, np.float64)[sel])
            if (~known).sum() >= 8:
                sel = np.nonzero(~known)[0][_spread(int((~known).sum()), cfg.max_points_per_view)]
                self.epi.append((self._rays(t.px_new[sel], K), self._rays(t.px_partner[sel], t.K), invert_rigid(t.T_obj_from_cam)))
        self.Xo = np.concatenate(Xo) if Xo else np.zeros((0, 3))
        self.px = np.concatenate(px) if px else np.zeros((0, 2))
        self.n_epi = int(sum(len(e[0]) for e in self.epi))
        # The whole picture gives thousands of epipolar matches, the dish sometimes a few dozen known points.
        # When the views already processed disagree among themselves (a second pass over a place seen long
        # before), the matches must not outvote the points: it is against the points that the depth of this
        # view will be judged. Both kinds weigh the same in total.
        self.w_epi = min(1.0, float(np.sqrt(2.0 * len(self.Xo) / max(1, self.n_epi))))
        self.at(np.eye(4))

    @staticmethod
    def _rays(px, K):
        px = np.asarray(px, np.float64).reshape(-1, 2)
        return np.stack([(px[:, 0] - K[0, 2]) / K[0, 0], (px[:, 1] - K[1, 2]) / K[1, 1], np.ones(len(px))], 1)

    def at(self, T0: np.ndarray):
        self.T0 = T0
        self.Xc0 = transform_points(invert_rigid(T0), self.Xo) if len(self.Xo) else self.Xo
        self.A = [Tc @ T0 for _, _, Tc in self.epi]          # new camera -> processed camera, before the correction

    def reprojection(self, xi: np.ndarray) -> np.ndarray:
        """Mx2 pixel errors of the points whose depth is known."""
        R = cv2.Rodrigues(np.asarray(xi[:3], np.float64).reshape(3, 1))[0]
        Xc = (self.Xc0 - xi[3:]) @ R                          # R^T (X - t), written for row vectors
        z = np.maximum(Xc[:, 2], 0.02)
        uv = Xc[:, :2] / z[:, None] * [self.K[0, 0], self.K[1, 1]] + [self.K[0, 2], self.K[1, 2]]
        return uv - self.px

    def epipolar(self, xi: np.ndarray) -> np.ndarray:
        """Signed distances to the epipolar lines (pixels) of the matches whose depth is not known."""
        if not self.epi:
            return np.zeros(0)
        D = _delta(xi)
        out = []
        for (x1, x2, _), A in zip(self.epi, self.A):
            T = A @ D
            t = T[:3, 3]
            n = np.linalg.norm(t)
            if n < 1e-6:
                out.append(np.zeros(len(x1)))
                continue
            t = t / n
            E = np.array([[0, -t[2], t[1]], [t[2], 0, -t[0]], [-t[1], t[0], 0]]) @ T[:3, :3]
            Ex1 = x1 @ E.T
            Etx2 = x2 @ E
            den = Ex1[:, 0] ** 2 + Ex1[:, 1] ** 2 + Etx2[:, 0] ** 2 + Etx2[:, 1] ** 2
            out.append(np.sum(x2 * Ex1, 1) / np.sqrt(np.maximum(den, 1e-18)) * self.f)
        return np.concatenate(out)

    def residuals(self, xi: np.ndarray) -> np.ndarray:
        c = self.cfg
        prior = c.prior_weight * np.concatenate([xi[:3] / np.radians(c.prior_rot_deg), xi[3:] / c.prior_shift_m])
        return np.concatenate([self.reprojection(xi).reshape(-1), self.w_epi * self.epipolar(xi), prior])

    def fit(self, T: np.ndarray) -> float:
        """Median distance (pixels) between where the known points are seen and where the pose T puts them."""
        self.at(T)
        return float(np.median(np.linalg.norm(self.reprojection(np.zeros(6)), axis=1)))


def anchor_pose(T_tracker: np.ndarray, K: np.ndarray, ties: list[Tie], cfg: AnchorConfig | None = None,
                starts: tuple = (), fallback: np.ndarray | None = None) -> tuple[np.ndarray | None, dict]:
    """Pose (T_obj_from_cam) of the new view tied to the views already processed, or None when the reported pose
    is kept.

    starts: other first guesses (the correction found for a neighbour applied to this view).
    fallback: where the neighbours say this view is (see common_correction). Used as a first guess, as the
    place the solution must stay close to, and as the answer when the ties give none ("predicted").

    info: status ("anchored", "predicted", "already_consistent", "few_model_points", "no_improvement",
    "too_far_from_tracker"), model_points, epipolar_matches, residual_before_px, residual_after_px, shift_mm,
    rot_deg (of what is applied, from the tracker's pose).
    """
    cfg = cfg or AnchorConfig()
    prob = _Problem(K, ties, cfg)
    info = {"status": "few_model_points", "model_points": int(len(prob.Xo)), "epipolar_matches": prob.n_epi}

    def predicted(why: str):
        info.update(status="predicted", reason=why, shift_mm=float(np.linalg.norm(fallback[:3, 3] - T_tracker[:3, 3]) * 1000))
        return fallback, info

    if len(prob.Xo) < cfg.min_model_points:
        return predicted("few_model_points") if fallback is not None else (None, info)
    before = prob.fit(T_tracker)
    info["residual_before_px"] = before
    if before <= cfg.leave_below_px:
        info["status"] = "already_consistent"
        return None, info
    fallback_fits = fallback is not None and prob.fit(fallback) <= cfg.improve_to * before
    start, best = T_tracker, before
    for T in ((fallback,) if fallback is not None else ()) + tuple(starts):
        r = prob.fit(T)
        if r < best:
            start, best = T, r
    prob.at(start)
    sol = least_squares(prob.residuals, np.zeros(6), x_scale=np.full(6, 1e-3), loss="soft_l1", f_scale=cfg.loss_px, max_nfev=30)
    T_solved = start @ _delta(sol.x)
    err = np.linalg.norm(prob.reprojection(sol.x), axis=1)
    after = float(np.median(err))
    info["residual_after_px"] = after
    info["inliers"] = int((err < 2.5 * cfg.loss_px).sum())
    if after > min(cfg.improve_to * before, cfg.max_residual_px) or info["inliers"] < 0.5 * cfg.min_model_points:
        info["status"] = "no_improvement"
        return predicted("no_improvement") if fallback_fits else (None, info)
    # The whole correction, measured from the tracker's own pose (in the camera's frame)...
    D = invert_rigid(T_tracker) @ T_solved
    w = cv2.Rodrigues(D[:3, :3])[0].ravel()
    info["solved_shift_mm"], info["solved_rot_deg"] = float(np.linalg.norm(D[:3, 3]) * 1000), float(np.degrees(np.linalg.norm(w)))
    # ...and how far the solution is from where this view was expected (the neighbours' answer when there is one).
    E = invert_rigid(fallback if fallback is not None and not cfg.guard_from_tracker else T_tracker) @ T_solved
    if (np.linalg.norm(E[:3, 3]) > cfg.max_shift_m
            or np.degrees(np.linalg.norm(cv2.Rodrigues(np.ascontiguousarray(E[:3, :3]))[0])) > cfg.max_rot_deg):
        info["status"] = "too_far_from_tracker"
        return predicted("too_far") if fallback_fits else (None, info)
    T = T_tracker @ _delta(np.concatenate([cfg.gain * w, cfg.gain * D[:3, 3]]))
    info.update(status="anchored", shift_mm=float(np.linalg.norm(T[:3, 3] - T_tracker[:3, 3]) * 1000),
                rot_deg=cfg.gain * info["solved_rot_deg"])
    return T, info


def _twist(C: np.ndarray) -> np.ndarray:
    """Small rigid transform -> (rotation vector, translation)."""
    return np.concatenate([cv2.Rodrigues(np.ascontiguousarray(C[:3, :3]))[0].ravel(), C[:3, 3]])


def common_correction(corrections: list[np.ndarray], min_views: int = 3) -> np.ndarray | None:
    """What the last few tied views have in common: where the model as a whole sits relative to the tracker's
    frame. corrections: for each of those views, C = T_tied * inverse(T_tracker), in the frame of the box.
    Their median (rotation vector and translation, component by component) is not moved by the jitter of one
    view. None with fewer than `min_views` views."""
    if len(corrections) < min_views:
        return None
    return _delta(np.median(np.stack([_twist(C) for C in corrections]), axis=0))
