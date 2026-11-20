"""Global pose refinement (reconstruction/bundle.py).

Measured on a real iPhone capture (a book filmed from 26 cm): the refinement stopped after its 40 steps with
1.15 px of reprojection error, far from converged, and the very firm ties to the tracker's frame-to-frame
motion kept it there (0.72 px after 300 steps). With ties three times looser it converged to 0.35 px. A second,
looser stage now runs when the first one leaves a high error; when the first stage is already good nothing changes.
"""
import cv2
import numpy as np
import pytest

from reconstruction.bundle import BundleConfig, refine_poses
from reconstruction.coordinates import invert_rigid, object_from_camera_cv
from reconstruction.stereo_depth import View
from tests.synthetic import SyntheticScene, orbit_poses

SIZE = (0.28, 0.08, 0.28)


def _views(jitter_mm: float, jitter_deg: float, n: int = 22, seed: int = 3):
    """Views of the synthetic plate; the reported poses carry independent frame-to-frame tracking noise."""
    sc = SyntheticScene()
    poses = orbit_poses(4 * n)[:n]                       # a quarter of a lap: neighbours overlap well
    rng = np.random.default_rng(seed)
    views, truth = {}, {}
    for i, T_ar in enumerate(poses):
        img, _ = sc.render(T_ar)
        T_true = object_from_camera_cv(np.eye(4), T_ar)
        J = np.eye(4)
        J[:3, :3] = cv2.Rodrigues(rng.normal(scale=np.radians(jitter_deg), size=3))[0]
        J[:3, 3] = rng.normal(scale=jitter_mm / 1000.0, size=3)
        views[i] = View(i, img, sc.K.copy(), T_true @ J)   # the camera is reported slightly off
        truth[i] = T_true
    return views, truth


def _shape_error_mm(poses: dict, truth: dict) -> float:
    """How far the camera positions are from the true ones once the two trajectories are laid over each other
    (best rigid fit, no scaling). The refinement keeps the first camera where the tracker put it, so only the
    shape of the trajectory can be judged, not its place."""
    ids = sorted(poses)
    A = np.array([poses[k][:3, 3] for k in ids])
    B = np.array([truth[k][:3, 3] for k in ids])
    a0, b0 = A - A.mean(0), B - B.mean(0)
    U, _, Vt = np.linalg.svd(a0.T @ b0)
    D = np.diag([1.0, 1.0, np.sign(np.linalg.det(U @ Vt))])
    R = (U @ D @ Vt).T
    return float(np.median(np.linalg.norm(a0 @ R.T - b0, axis=1)) * 1000)


@pytest.fixture(scope="module")
def noisy():
    return _views(jitter_mm=1.5, jitter_deg=0.15)


def test_a_second_looser_stage_runs_when_the_first_leaves_a_high_error(noisy):
    views, truth = noisy
    reported = {i: v.T_obj_from_cam.copy() for i, v in views.items()}
    firm = refine_poses({i: View(i, v.image, v.K, reported[i].copy(), features=v.features) for i, v in views.items()}, SIZE,
                        cfg=BundleConfig(relax_factor=1.0))
    both = refine_poses({i: View(i, v.image, v.K, reported[i].copy(), features=v.features) for i, v in views.items()}, SIZE)
    assert firm.info.get("relaxed") is False and both.info.get("relaxed") is True
    assert both.info["reproj_first_stage_px"] > 0.5                                   # the reason the second stage ran
    assert both.info["reproj_after_px"] < 0.7 * both.info["reproj_first_stage_px"]
    assert both.applied and firm.applied
    # A smaller reprojection error is not proof of better cameras (pushing the firm stage to convergence lowers
    # it and makes them worse): the trajectory itself is compared with the true one.
    e_reported, e_firm, e_both = _shape_error_mm(reported, truth), _shape_error_mm(firm.poses, truth), _shape_error_mm(both.poses, truth)
    assert e_both < e_firm and e_both < 0.5 * e_reported, (e_reported, e_firm, e_both)


def test_the_looser_stage_needs_enough_points_to_hold_the_cameras(noisy):
    """With few tracked points looser ties let the cameras slide: the second stage is then not allowed, even
    when the first one leaves a high error."""
    from reconstruction.stereo_depth import StereoParams
    views, _ = noisy
    few = StereoParams(sift_features=500)
    fresh = lambda: {i: View(i, v.image, v.K, v.T_obj_from_cam.copy()) for i, v in views.items()}
    guarded = refine_poses(fresh(), SIZE, few, cfg=BundleConfig(relax_above_px=0.05))
    assert guarded.info["obs_per_view"] < 300 and guarded.info["relaxed"] is False
    forced = refine_poses(fresh(), SIZE, few, cfg=BundleConfig(relax_above_px=0.05, relax_min_obs_per_view=0))
    assert forced.info["reproj_first_stage_px"] > 0.05      # the trigger was met: only the guard made the difference


def test_good_tracking_is_left_to_the_first_stage():
    views, truth = _views(jitter_mm=0.05, jitter_deg=0.005)
    res = refine_poses(views, SIZE)
    assert res.info.get("relaxed") is False
    assert res.info["reproj_after_px"] < 0.5
