import cv2
import numpy as np
import pytest

from reconstruction.coordinates import invert_rigid, object_from_camera_cv
from reconstruction.pair_selector import pair_geometry, select_partners
from reconstruction.stereo_depth import StereoParams, View, combine_depths, compute_pair_depth
from tests.synthetic import SyntheticScene, orbit_poses

SIZE = (0.28, 0.08, 0.28)


@pytest.fixture(scope="module")
def scene():
    return SyntheticScene()


def make_view(scene, T, i, jpeg=True):
    img, gt = scene.render(T)
    if jpeg:
        img = cv2.imdecode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])[1], cv2.IMREAD_COLOR)
    return View(i, img, scene.K, object_from_camera_cv(np.eye(4), T)), gt


@pytest.mark.parametrize("roll", [-90.0, 0.0])
@pytest.mark.parametrize("pair", [(0, 1), (1, 0), (0, 2)])
def test_pair_depth_matches_ground_truth(scene, roll, pair):
    P = orbit_poses(120, roll_deg=roll)
    (va, gt), (vb, _) = make_view(scene, P[pair[0]], pair[0]), make_view(scene, P[pair[1]], pair[1])
    res = compute_pair_depth(va, vb, SIZE)
    assert res.depth is not None, res.report
    m = res.depth > 0
    err = np.abs(res.depth[m] - gt[m])
    assert m.sum() > 20000
    assert np.median(err) < 0.003  # 3 mm at ~0.4 m with a 640x480 preview image
    assert np.percentile(err, 95) < 0.012


def test_wrong_pose_is_rejected_or_corrected(scene):
    P = orbit_poses(120)
    (va, gt), (vb, _) = make_view(scene, P[0], 0), make_view(scene, P[1], 1)
    bad = vb.T_obj_from_cam.copy()
    a = np.radians(4.0)
    Rz = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    bad[:3, :3] = bad[:3, :3] @ Rz
    vb2 = View(1, vb.image, vb.K, bad)
    res = compute_pair_depth(va, vb2, SIZE)
    assert res.report.residual_arkit_px > 2.0  # the inconsistency is detected
    if res.depth is not None:
        assert res.report.pose_source == "corrected"
        m = res.depth > 0
        assert np.median(np.abs(res.depth[m] - gt[m])) < 0.01


def test_pair_selection_rejects_degenerate():
    P = orbit_poses(120)
    T = [object_from_camera_cv(np.eye(4), p) for p in P]
    assert pair_geometry(0, T[0], 0, T[0], SIZE) is None  # no baseline
    # pure forward motion
    fwd = T[0].copy()
    fwd[:3, 3] += T[0][:3, 2] * 0.03
    assert pair_geometry(0, T[0], 1, fwd, SIZE) is None
    # pure rotation on the spot (no translation) gives no stereo either
    rot = T[0].copy()
    a = np.radians(5)
    rot[:3, :3] = rot[:3, :3] @ np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    assert pair_geometry(0, T[0], 1, rot, SIZE) is None
    K = np.array([[500, 0, 319.5], [0, 500, 239.5], [0, 0, 1.0]])
    views = {i: (T[i], K, (640, 480)) for i in range(6)}
    partners = select_partners(2, views, SIZE)
    assert 1 <= len(partners) <= 2 and all(p.other_id != 2 for p in partners)


def test_combine_depths_removes_disagreement():
    a = np.full((4, 4), 0.5, np.float32)
    b = a.copy()
    b[0, 0] = 0.6  # disagreeing pair -> unknown, never averaged
    c = np.zeros_like(a)
    c[1, 1] = 0.5
    d, s = combine_depths([a, b])
    assert d[0, 0] == 0 and d[1, 1] == pytest.approx(0.5) and s[1, 1] == 2
    d2, s2 = combine_depths([c, np.zeros_like(c)])
    assert d2[1, 1] == pytest.approx(0.5) and s2[1, 1] == 1
