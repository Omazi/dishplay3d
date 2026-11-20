"""Pose of a new view during the scan, tied to what is already reconstructed (reconstruction/live_pose.py).

Measured on a real iPhone capture (a pair of shoes, 85 views): with the tracker's poses as given, 41 % of what
the live engine measured was contradicted by other views and thrown away; with the poses found by the global
refinement at finishing, 11 %. The global refinement needs all the views. During the scan each new view is
tied to the views already processed instead.
"""
import cv2
import numpy as np
import pytest

from reconstruction.coordinates import backproject, invert_rigid, object_from_camera_cv, rotation_angle_deg, transform_points
from reconstruction.live_pose import AnchorConfig, Tie, anchor_pose, common_correction, sample_depth
from tests.synthetic import SyntheticScene, orbit_poses

N_LAP = 120


@pytest.fixture(scope="module")
def world():
    """Three views of the synthetic plate, a few centimetres apart, with their true depth maps."""
    sc = SyntheticScene()
    P = orbit_poses(N_LAP)
    out = []
    for i in (0, 2, 4):
        _, depth = sc.render(P[i])
        out.append((object_from_camera_cv(np.eye(4), P[i]), depth))
    return sc, out


def off(T, shift_mm=(0.0, 0.0, 0.0), rot_deg=(0.0, 0.0, 0.0)):
    """The same camera, reported slightly off (in its own frame)."""
    J = np.eye(4)
    J[:3, :3] = cv2.Rodrigues(np.radians(np.asarray(rot_deg, float)))[0]
    J[:3, 3] = np.asarray(shift_mm, float) / 1000.0
    return T @ J


def ties_for(sc, new, partners, n=1500, noise_px=0.3, seed=0, known=True, wrong_share=0.0):
    """What a matcher would give: points seen in a partner and in the new view. Inside the plate the partner's
    depth is known; on the table around it, it is not (only the two pixels are)."""
    rng = np.random.default_rng(seed)
    T_new, d_new = new
    out = []
    for T_p, d_p in partners:
        vs, us = np.nonzero(d_p > 0)
        sel = rng.choice(len(vs), size=min(n, len(vs)), replace=False)
        px_p = np.stack([us[sel], vs[sel]], 1).astype(np.float64)
        z = d_p[vs[sel], us[sel]].astype(np.float64)
        X = transform_points(T_p, backproject(sc.K, px_p, z))
        xc = transform_points(invert_rigid(T_new), X)
        uv = xc[:, :2] / xc[:, 2:3] * [sc.K[0, 0], sc.K[1, 1]] + [sc.K[0, 2], sc.K[1, 2]]
        ui, vi = np.round(uv[:, 0]).astype(int), np.round(uv[:, 1]).astype(int)
        ok = (xc[:, 2] > 0.05) & (ui >= 0) & (ui < sc.width) & (vi >= 0) & (vi < sc.height)
        ok[ok] &= np.abs(d_new[vi[ok], ui[ok]] - xc[ok, 2]) < 0.002          # really seen in the new view
        on_plate = np.hypot(X[:, 0], X[:, 2]) < 0.12
        depth = np.where(on_plate & known, z, 0.0)
        if wrong_share > 0:
            bad = rng.random(len(depth)) < wrong_share
            depth = np.where(bad, depth * rng.uniform(1.05, 1.12, len(depth)), depth)
        out.append(Tie(sc.K, T_p, (uv + rng.normal(scale=noise_px, size=uv.shape))[ok],
                       (px_p + rng.normal(scale=noise_px, size=px_p.shape))[ok], depth[ok]))
    return out


def pose_error(T, T_true):
    return float(np.linalg.norm(T[:3, 3] - T_true[:3, 3]) * 1000), rotation_angle_deg(T[:3, :3] @ T_true[:3, :3].T)


def test_a_view_reported_off_is_brought_back(world):
    sc, (a, b, c) = world
    T_true = c[0]
    reported = off(T_true, shift_mm=(2.0, -1.5, 2.5), rot_deg=(0.2, -0.25, 0.15))
    assert pose_error(reported, T_true)[0] > 3.0
    T, info = anchor_pose(reported, sc.K, ties_for(sc, c, [a, b]), AnchorConfig(gain=1.0))
    assert T is not None, info
    mm, deg = pose_error(T, T_true)
    assert mm < 0.4 and deg < 0.04, (mm, deg, info)
    assert info["status"] == "anchored" and info["residual_after_px"] < 0.5 * info["residual_before_px"]
    assert info["shift_mm"] == pytest.approx(pose_error(T, reported)[0], abs=0.01)


def test_only_a_share_of_the_correction_is_applied_by_default(world):
    """Each view keeps part of the tracker's own answer, which holds the model back from wandering away from the
    tracker's frame."""
    sc, (a, b, c) = world
    T_true = c[0]
    reported = off(T_true, shift_mm=(2.0, -1.5, 2.5), rot_deg=(0.2, -0.25, 0.15))
    T, info = anchor_pose(reported, sc.K, ties_for(sc, c, [a, b]))
    left = pose_error(T, T_true)[0] / pose_error(reported, T_true)[0]
    assert 0.1 < left < 0.3, left


def test_what_recent_views_have_in_common_is_not_moved_by_the_jitter_of_one():
    """The model as a whole sits 6 mm (and a fraction of a degree) off the tracker's frame; on top of that each
    view has its own jitter, and one of them is plainly wrong."""
    rng = np.random.default_rng(0)
    G = off(np.eye(4), shift_mm=(4.0, -2.0, 4.0), rot_deg=(0.1, 0.3, -0.2))          # common offset, frame of the box
    corrections = []
    for k in range(6):
        T_trk = off(np.eye(4), shift_mm=rng.uniform(-300, 300, 3), rot_deg=rng.uniform(-40, 40, 3))
        jitter = off(np.eye(4), shift_mm=rng.normal(scale=1.0, size=3), rot_deg=rng.normal(scale=0.1, size=3))
        corrections.append(G @ T_trk @ jitter @ invert_rigid(T_trk))
    corrections[2] = off(np.eye(4), shift_mm=(50.0, 0.0, -40.0), rot_deg=(3.0, 0.0, 0.0))    # a wrong one
    C = common_correction(corrections)
    assert np.linalg.norm(C[:3, 3] - G[:3, 3]) * 1000 < 1.5 and rotation_angle_deg(C[:3, :3] @ G[:3, :3].T) < 0.15
    assert common_correction(corrections[:2]) is None, "two views are not enough to say what is common"


def test_a_view_that_cannot_be_tied_is_placed_where_its_neighbours_are(world):
    """After a while the model sits several millimetres away from the tracker's raw frame. A view left at the
    tracker's pose would contradict everything built before it, and the views tied to it after that."""
    sc, (a, b, c) = world
    T_true = c[0]
    reported = off(T_true, shift_mm=(5.0, -3.0, 4.0), rot_deg=(0.3, 0.2, -0.2))       # the tracker, off by the common offset...
    neighbours = off(T_true, shift_mm=(0.6, 0.4, -0.5), rot_deg=(0.03, 0.0, 0.04))    # ...which the neighbours know, to a jitter
    # no point of known depth: the ties cannot say anything
    T, info = anchor_pose(reported, sc.K, ties_for(sc, c, [a, b], known=False), fallback=neighbours)
    assert info["status"] == "predicted" and np.array_equal(T, neighbours)
    assert info["shift_mm"] == pytest.approx(pose_error(neighbours, reported)[0], abs=0.01)
    # ties that give no acceptable solution (most depths wrong): the neighbours' answer is used if it fits better
    T2, info2 = anchor_pose(reported, sc.K, ties_for(sc, c, [a, b], wrong_share=0.9), AnchorConfig(max_residual_px=0.01),
                            fallback=neighbours)
    assert info2["status"] in ("predicted", "no_improvement")
    # A solution 2 cm away from the tracker is refused even when it is right: measured on real captures, letting
    # the model follow its neighbours instead of the tracker lets it drift centimetres away. The view is then
    # placed where its neighbours are, not left at the tracker's raw pose.
    far = off(T_true, shift_mm=(14.0, -8.0, 12.0))
    assert anchor_pose(far, sc.K, ties_for(sc, c, [a, b]), AnchorConfig(gain=1.0))[1]["status"] in ("too_far_from_tracker", "no_improvement")
    T3, info3 = anchor_pose(far, sc.K, ties_for(sc, c, [a, b]), AnchorConfig(gain=1.0), fallback=neighbours)
    assert info3["status"] == "predicted" and info3["reason"] == "too_far" and np.array_equal(T3, neighbours), info3
    # (the other rule, kept for experiments: "too far" measured from the neighbours' answer)
    T4, info4 = anchor_pose(far, sc.K, ties_for(sc, c, [a, b]), AnchorConfig(gain=1.0, guard_from_tracker=False), fallback=neighbours)
    assert info4["status"] == "anchored" and pose_error(T4, T_true)[0] < 0.5, (info4, pose_error(T4, T_true))


def test_the_distance_between_two_cameras_comes_from_the_points_already_known(world):
    """A camera reported too far along its own motion: every match still lies on its epipolar line, so the
    pictures alone cannot see the error. Points of the dish whose depth is known in the partner can."""
    sc, (a, b, c) = world
    T_true = c[0]
    along = invert_rigid(T_true)[:3, :3] @ (T_true[:3, 3] - a[0][:3, 3])       # motion since the partner, camera frame
    reported = off(T_true, shift_mm=along / np.linalg.norm(along) * 4.0)
    T, info = anchor_pose(reported, sc.K, ties_for(sc, c, [a]), AnchorConfig(gain=1.0))
    assert T is not None and pose_error(T, T_true)[0] < 0.5, (pose_error(T, T_true), info)
    # without any known point there is nothing to tie the distance to: the pose is left as reported
    T2, info2 = anchor_pose(reported, sc.K, ties_for(sc, c, [a], known=False), AnchorConfig(gain=1.0))
    assert T2 is None and info2["status"] == "few_model_points"


def test_a_view_that_already_fits_is_left_alone(world):
    sc, (a, b, c) = world
    T, info = anchor_pose(c[0].copy(), sc.K, ties_for(sc, c, [a, b]))
    assert T is None and info["status"] == "already_consistent"
    assert info["residual_before_px"] < 0.6


def test_wrong_depths_do_not_drag_the_pose(world):
    sc, (a, b, c) = world
    T_true = c[0]
    reported = off(T_true, shift_mm=(2.0, -1.5, 2.5), rot_deg=(0.2, -0.25, 0.15))
    T, info = anchor_pose(reported, sc.K, ties_for(sc, c, [a, b], wrong_share=0.25), AnchorConfig(gain=1.0))
    assert T is not None and pose_error(T, T_true)[0] < 0.6, (pose_error(T, T_true), info)


def test_a_correction_far_from_the_tracker_is_refused(world):
    """The tracker is good to a few millimetres. A solution centimetres away from it means the ties are wrong
    (a moved object, a repeated pattern), not the tracker."""
    sc, (a, b, c) = world
    reported = off(c[0], shift_mm=(30.0, 0.0, 20.0))
    T, info = anchor_pose(reported, sc.K, ties_for(sc, c, [a, b]), AnchorConfig(gain=1.0))
    assert T is None and info["status"] in ("too_far_from_tracker", "no_improvement")


def test_depth_is_not_read_on_an_edge_or_in_a_hole():
    d = np.full((20, 20), 0.40, np.float32)
    d[:, 10:] = 0.50                      # a step: the foreground ends at column 10
    d[5, 3] = 0.0                         # a hole
    px = np.array([[4.0, 12.0], [9.6, 12.0], [10.4, 12.0], [15.0, 12.0], [3.2, 5.1], [3.0, 6.0], [-1.0, 3.0], [25.0, 3.0]])
    z = sample_depth(d, px)
    assert z[0] == pytest.approx(0.40) and z[3] == pytest.approx(0.50)
    assert z[1] == 0 and z[2] == 0        # next to the step: which side the feature lies on is not known
    assert z[4] == 0 and z[5] == 0        # in or next to a hole
    assert z[6] == 0 and z[7] == 0        # outside the picture
