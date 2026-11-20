import cv2
import numpy as np
import pytest

from reconstruction.coordinates import backproject, invert_rigid, object_from_camera_cv, transform_points
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


def test_reflections_are_left_unknown(scene):
    """A blown-out highlight that sits at different places in the two images must not get a depth."""
    P = orbit_poses(120)
    (va, gt), (vb, _) = make_view(scene, P[0], 0, jpeg=False), make_view(scene, P[1], 1, jpeg=False)
    ys, xs = np.nonzero(gt > 0)
    cy, cx = int(np.median(ys)), int(np.median(xs))
    cv2.circle(va.image, (cx, cy), 14, (255, 255, 255), -1)
    cv2.circle(vb.image, (cx + 9, cy + 6), 14, (255, 255, 255), -1)   # the reflection moved with the camera
    res = compute_pair_depth(va, vb, SIZE)
    assert res.depth is not None
    assert (res.depth[cy - 8:cy + 9, cx - 8:cx + 9] > 0).mean() < 0.02


def test_round_trip_check_does_not_lose_the_sides_of_the_picture():
    """The matcher cannot search the first columns of its 'left' picture (as wide as the largest disparity).
    For the return map the roles are swapped, so that band falls on the other side. Found on real captures:
    25 to 45 % of correctly matched pixels were rejected only because the return map had no value there."""
    import cv2
    from reconstruction.stereo_depth import StereoParams, _lr_checked_disparity
    rng = np.random.default_rng(0)
    H, W, d, dmin, num = 240, 600, 100, 60, 96
    tex = cv2.GaussianBlur((rng.uniform(0, 255, (H, W + 400))).astype(np.float32), (0, 0), 1.2)
    tex = cv2.normalize(tex, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    left = np.ascontiguousarray(tex[:, 150:150 + W])
    right = np.ascontiguousarray(tex[:, 150 + d:150 + d + W])      # the same surface, shifted by d pixels
    disp, valid = _lr_checked_disparity(left, right, dmin, num, StereoParams())
    seen_by_both = np.zeros((H, W), bool)
    seen_by_both[:, d:] = True                                      # a left pixel x has its partner at x - d
    assert valid[seen_by_both].mean() > 0.95, valid[seen_by_both].mean()
    assert np.abs(disp[valid] - d).max() < 1.0
    assert valid[~seen_by_both].mean() < 0.02                       # what only one picture sees is not given a depth


def _close_up_views(targets, eye_height=0.26):
    """Cameras 26 cm above a 53 x 33 cm flat object (a book, a large plate): none of them sees the whole box."""
    from reconstruction.coordinates import C_AR_FROM_CV, intrinsics_matrix, look_at_ar
    K = intrinsics_matrix(900.0, 900.0, 575.5, 431.5)
    views = {}
    for i, (ex, tx) in enumerate(targets):
        T_obj_from_cam = look_at_ar([ex, eye_height, 0.10], [tx, 0.0, 0.0]) @ C_AR_FROM_CV
        views[i] = (T_obj_from_cam, K, (1152, 864))
    return views


def test_a_box_larger_than_the_field_of_view_is_still_scanned():
    """Found on real captures (a book, a pair of shoes): at scanning distance no photograph showed 60 % of the
    box, so every view was set aside without a word and nothing was reconstructed."""
    from reconstruction.pair_selector import box_visibility
    big = (0.53, 0.03, 0.33)
    views = _close_up_views([(-0.10, -0.10), (-0.07, -0.08), (-0.04, -0.06), (0.14, 0.16)])
    assert max(box_visibility(K, np.linalg.inv(T), big, *wh) for T, K, wh in views.values()) < 0.6
    partners = select_partners(0, views, big)
    assert {p.other_id for p in partners} & {1, 2}, "two close-ups of the same part of the box make a pair"
    # a view that looks at another part of the box shares too little with view 0 to be its partner
    assert 3 not in {p.other_id for p in partners}


def test_a_view_that_does_not_see_the_box_gets_no_partner():
    from reconstruction.coordinates import C_AR_FROM_CV, intrinsics_matrix, look_at_ar
    K = intrinsics_matrix(900.0, 900.0, 575.5, 431.5)
    away = look_at_ar([0.0, 0.26, 0.10], [3.0, 0.0, 0.0]) @ C_AR_FROM_CV      # looking far off to the side
    near = look_at_ar([0.03, 0.26, 0.10], [3.0, 0.0, 0.0]) @ C_AR_FROM_CV
    assert select_partners(0, {0: (away, K, (1152, 864)), 1: (near, K, (1152, 864))}, (0.2, 0.05, 0.2)) == []


def test_a_box_set_too_low_does_not_cut_the_top_of_the_dish(scene):
    """The rim of the plate (22 mm) and the food (34 mm) rise above a box only 12 mm high. They used to be
    discarded as "outside the box"; they are the dish, and are measured like the rest."""
    low = (0.28, 0.012, 0.28)
    P = orbit_poses(120)
    (va, gt), (vb, _) = make_view(scene, P[0], 0), make_view(scene, P[1], 1)
    res = compute_pair_depth(va, vb, low)
    assert res.depth is not None, res.report
    vs, us = np.nonzero(gt > 0)
    pts = transform_points(va.T_obj_from_cam, backproject(va.K, np.stack([us, vs], 1), gt[vs, us]))
    high = np.zeros(gt.shape, bool)
    high[vs, us] = (pts[:, 1] > 0.025) & (np.hypot(pts[:, 0], pts[:, 2]) < 0.12)    # top of the food
    assert high.sum() > 300
    got = (res.depth > 0) & high
    assert got.sum() > 0.6 * high.sum(), f"{got.sum()} of {high.sum()} pixels above the box were measured"
    # ... as well as with a box of the right height (the cap of a small sphere is the hardest part of the scene)
    right = compute_pair_depth(va, vb, SIZE).depth
    ok = (right > 0) & high
    assert got.sum() > 0.9 * ok.sum()
    assert np.median(np.abs(res.depth[got] - gt[got])) < np.median(np.abs(right[ok] - gt[ok])) + 0.0015
    # the sides are not widened: the table far around the box is still left out
    far = np.zeros(gt.shape, bool)
    far[vs, us] = (np.abs(pts[:, 0]) > 0.17) | (np.abs(pts[:, 2]) > 0.17)
    assert far.sum() > 1000 and (res.depth[far] > 0).mean() < 0.01


def _top_down(height_map, cam_height=0.40, f=200.0):
    """Depth image of a relief seen from straight above (object y = cam_height - depth)."""
    h, w = height_map.shape
    K = np.array([[f, 0, w / 2 - 0.5], [0, f, h / 2 - 0.5], [0, 0, 1.0]])
    T = np.eye(4)
    T[:3, :3] = [[1, 0, 0], [0, 0, -1], [0, 1, 0]]
    T[:3, 3] = [0, cam_height, 0]
    depth = np.where(np.isnan(height_map), 0.0, cam_height - height_map).astype(np.float32)
    return depth, K, T


def test_only_what_continues_the_dish_is_kept_above_the_box():
    """What rises above the box is kept when it continues a surface that starts inside it (a dish taller than
    its box). A patch that floats above the box on its own is a stereo error - a far surface matched at a
    near depth, measured as such on a plain bowl: thousands of pixels per view, all of them wrong - and the top
    of the box keeps rejecting those as it always did."""
    from reconstruction.stereo_depth import drop_floating_above
    box, margin = (0.3, 0.05, 0.3), 0.01
    vv, uu = np.mgrid[0:120, 0:160]
    r = np.hypot(uu - 80, vv - 60)
    # a mound 9 cm high standing on the table: continuous from inside the box to 3 cm above its top
    mound = 0.09 * np.clip(1 - r / 50.0, 0, 1)
    d, K, T = _top_down(mound)
    out, dropped = drop_floating_above(d, K, T, box, margin)
    assert dropped == 0 and np.array_equal(out, d)
    # the table, and a patch floating 10 cm above it with nothing around it
    flat = np.zeros((120, 160))
    flat[38:62, 58:82] = np.nan                    # the gap left around a depth step
    flat[40:60, 60:80] = 0.10
    d, K, T = _top_down(flat)
    out, dropped = drop_floating_above(d, K, T, box, margin)
    assert dropped == 400 and (out[40:60, 60:80] == 0).all()
    assert np.array_equal(out[flat == 0], d[flat == 0]), "what is inside the box is never touched"
    # a floating patch that only grazes the top of the box: its part above goes, its sliver inside stays as before
    graze = np.zeros((120, 160))
    graze[28:62, 58:92] = np.nan
    graze[30:60, 60:90] = np.linspace(0.059, 0.10, 30)[:, None]      # first row just under the limit (6 cm)
    d, K, T = _top_down(graze)
    out, dropped = drop_floating_above(d, K, T, box, margin)
    assert dropped == 29 * 30 and (out[30, 60:90] > 0).all() and (out[31:60, 60:90] == 0).all()
