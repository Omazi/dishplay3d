"""Smooth bias of a pair's depth map (reconstruction/consistency.py).

A small error on the relative position of two views (tracking, rolling shutter) does not add noise to their
depth map: it bends it smoothly — a scale, an offset and a tilt in inverse depth. On real captures this bias
reaches several per cent between two pairs of the same view. It is estimated against the views already
accepted and removed, instead of treating the disagreement as outliers.
"""
import numpy as np

from reconstruction.consistency import DepthBias, DepthView, depth_bias_between, depth_bias_from_views

K = np.array([[500.0, 0, 320], [0, 500.0, 240], [0, 0, 1]])
H, W = 480, 640


def plane_view(i, cam_x, tilt=0.35):
    """Depth of a slanted plane (z = 0.40 + tilt * x in the world) seen by a camera shifted along x."""
    T = np.eye(4)
    T[0, 3] = cam_x
    v, u = np.mgrid[0:H, 0:W]
    dx, dy = (u - K[0, 2]) / K[0, 0], (v - K[1, 2]) / K[1, 1]
    # ray: p = (cam_x, 0, 0) + z * (dx, dy, 1); plane: p_z = 0.40 + tilt * p_x
    z = (0.40 + tilt * cam_x) / (1.0 - tilt * dx)
    return DepthView(i, z.astype(np.float32), K, T)


def bent(view, scale=1.0, offset_rel=0.0, tilt_rel=(0.0, 0.0)):
    """The same depth map with the smooth bias a pose error gives (in inverse depth)."""
    w = 1.0 / view.depth.astype(np.float64)
    v, u = np.mgrid[0:H, 0:W]
    wbar = float(np.median(w))
    w2 = scale * w + wbar * (offset_rel + tilt_rel[0] * (u / W - 0.5) + tilt_rel[1] * (v / H - 0.5))
    return DepthView(view.frame_id, (1.0 / w2).astype(np.float32), view.K, view.T_obj_from_cam)


def rel_err(a, b):
    return np.abs(a.astype(np.float64) - b) / b


def test_scale_offset_and_tilt_are_recovered_from_neighbouring_views():
    truth = plane_view(0, 0.0)
    others = [plane_view(1, 0.03), plane_view(2, -0.03), plane_view(3, 0.06)]
    wrong = bent(truth, scale=1.02, offset_rel=-0.01, tilt_rel=(0.03, -0.02))
    assert np.percentile(rel_err(wrong.depth, truth.depth), 90) > 0.015      # the bias is well above the fusion tolerance
    bias = depth_bias_from_views(wrong, others)
    assert isinstance(bias, DepthBias) and bias.samples > 5000
    fixed = bias.apply(wrong.depth)
    assert np.percentile(rel_err(fixed, truth.depth), 99) < 0.003
    assert (fixed > 0).sum() == (wrong.depth > 0).sum()                      # nothing is added or removed


def test_an_unbiased_map_is_left_alone():
    truth = plane_view(0, 0.0)
    bias = depth_bias_from_views(truth, [plane_view(1, 0.03), plane_view(2, -0.03)])
    assert bias is not None
    assert np.percentile(rel_err(bias.apply(truth.depth), truth.depth), 99) < 0.001


def test_a_gross_mismatch_gives_no_estimate():
    truth = plane_view(0, 0.0)
    far = DepthView(0, truth.depth * 1.25, K, truth.T_obj_from_cam)           # not a pose error: something else is wrong
    assert depth_bias_from_views(far, [plane_view(1, 0.03), plane_view(2, -0.03)]) is None


def test_partial_correction_and_bound():
    truth = plane_view(0, 0.0)
    wrong = bent(truth, tilt_rel=(0.04, 0.0))
    bias = depth_bias_from_views(wrong, [plane_view(1, 0.03), plane_view(2, -0.03)])
    half = bias.apply(wrong.depth, gain=0.5)
    e0, e1 = rel_err(wrong.depth, truth.depth), rel_err(half, truth.depth)
    assert 0.4 < np.median(e1[e0 > 0.005] / e0[e0 > 0.005]) < 0.6             # half of the correction is applied
    capped = bias.apply(wrong.depth, max_rel=0.005)
    assert rel_err(capped, wrong.depth).max() < 0.0052                         # never moves a depth more than the bound


def test_two_maps_of_the_same_view_are_brought_together():
    truth = plane_view(0, 0.0)
    a = truth.depth.copy()
    b = bent(truth, scale=0.985, tilt_rel=(-0.02, 0.03)).depth
    a[:, :200] = 0                                                             # they only overlap partly
    b[300:, :] = 0
    bias = depth_bias_between(a, b)
    fixed = bias.apply(b)
    both = (a > 0) & (b > 0)
    assert np.percentile(rel_err(fixed[both], a[both]), 99) < 0.003
    # outside the overlap the correction stays reasonable (no wild extrapolation)
    assert np.percentile(rel_err(fixed[b > 0], truth.depth[b > 0]), 99) < 0.01


def test_a_view_seen_only_in_a_corner_gets_no_tilt():
    """Too little spread to tell a tilt from an offset: only the offset is corrected."""
    truth = plane_view(0, 0.0, tilt=0.0)
    wrong = bent(truth, offset_rel=0.02)
    other = plane_view(1, 0.03, tilt=0.0)
    other.depth[:, 40:] = 0                                                    # the neighbour covers a thin strip only
    bias = depth_bias_from_views(wrong, [other], min_samples=300)
    assert bias is not None and bias.gu == 0.0 and bias.gv == 0.0
    assert np.percentile(rel_err(bias.apply(wrong.depth), truth.depth), 99) < 0.004
