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


def _size_ratio(poses: dict, reference: dict) -> float:
    """Size of one camera trajectory relative to another (spread of the camera positions)."""
    ids = sorted(poses)
    A = np.array([poses[k][:3, 3] for k in ids])
    B = np.array([reference[k][:3, 3] for k in ids])
    return float(np.sqrt(((A - A.mean(0)) ** 2).sum() / ((B - B.mean(0)) ** 2).sum()))


@pytest.fixture(scope="module")
def noisy():
    return _views(jitter_mm=1.5, jitter_deg=0.15)


def test_a_second_looser_stage_runs_when_the_first_leaves_a_high_error(noisy):
    views, truth = noisy
    reported = {i: v.T_obj_from_cam.copy() for i, v in views.items()}
    firm = refine_poses({i: View(i, v.image, v.K, reported[i].copy(), features=v.features) for i, v in views.items()}, SIZE,
                        cfg=BundleConfig(relax_factors=()))
    both = refine_poses({i: View(i, v.image, v.K, reported[i].copy(), features=v.features) for i, v in views.items()}, SIZE)
    assert firm.info.get("relaxed") is False and both.info.get("relaxed") is True
    assert both.info["reproj_first_stage_px"] > 0.5                                   # the reason the second stage ran
    assert both.info["reproj_after_px"] < 0.7 * both.info["reproj_first_stage_px"]
    assert both.applied and firm.applied
    # A smaller reprojection error is not proof of better cameras (pushing the firm stage to convergence lowers
    # it and makes them worse): the trajectory itself is compared with the true one.
    e_reported, e_firm, e_both = _shape_error_mm(reported, truth), _shape_error_mm(firm.poses, truth), _shape_error_mm(both.poses, truth)
    assert e_both < e_firm and e_both < 0.5 * e_reported, (e_reported, e_firm, e_both)
    # the looser stage may reshape the trajectory, not resize it: the size of the scene comes from the tracker
    assert abs(_size_ratio(both.poses, reported) - 1.0) < 0.004, _size_ratio(both.poses, reported)


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


def test_a_second_stage_that_slides_away_does_not_cost_the_first(noisy, monkeypatch):
    """Found on a real capture (boxes on a shelf, a flat scene): with nearly free cameras the second stage
    reached a low reprojection error far from the tracker; it was selected, then the whole refinement was
    refused and the scan fell back to the raw tracker poses — worse than before. A second stage is now kept
    only if it stays near the tracker; otherwise the next setting is tried, and the first stage stands."""
    import reconstruction.bundle as bundle
    views, truth = noisy
    real = bundle.least_squares

    class Slid:
        def __init__(self, x, n_cams):
            self.x = x.copy()
            self.x[n_cams * 3: n_cams * 6] += 0.2          # every camera moved by 20 cm and more
            self.nfev = 5

    def fake(fun, x0, *a, **kw):
        if kw.get("args") == (10.0,):
            return Slid(np.asarray(x0, float), len(views))
        return real(fun, x0, *a, **kw)

    monkeypatch.setattr(bundle, "least_squares", fake)
    res = refine_poses({i: View(i, v.image, v.K, v.T_obj_from_cam.copy(), features=v.features) for i, v in views.items()}, SIZE)
    tried = res.info["second_stage"]
    assert tried[0]["ties_x"] == 10.0 and tried[0]["kept"] is False and tried[0]["max_shift_mm"] > 100
    assert res.applied, "the refinement as a whole is not thrown away"
    assert res.info["max_shift_mm"] < 50
    assert len(tried) == 2 and tried[1]["ties_x"] == 3.0      # the intermediate setting got its chance
    reported = {i: v.T_obj_from_cam for i, v in views.items()}
    assert _shape_error_mm(res.poses, truth) < 0.6 * _shape_error_mm(reported, truth)
