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


def scene_view(i, cam_x, noise=0.0, seed=0):
    """A slanted table seen obliquely, with a block standing 4 cm above it in the middle of the image:
    what a dish on a table looks like to the fit (one dominant plane, a smaller part off that plane)."""
    T = np.eye(4)
    T[0, 3] = cam_x
    v, u = np.mgrid[0:H, 0:W]
    dx, dy = (u - K[0, 2]) / K[0, 0], (v - K[1, 2]) / K[1, 1]
    # table: p_z = 0.45 - 0.5 * p_y (depth falls towards the bottom of the image) ; ray p = c + z * (dx, dy, 1)
    z = 0.45 / (1.0 + 0.5 * dy)
    block = (np.abs(cam_x + z * dx) < 0.04) & (np.abs(z * dy + 0.02) < 0.03)      # footprint of the block, in the world
    z = np.where(block, z - 0.04, z)
    if noise:
        z = z * (1.0 + np.random.default_rng(seed + i).normal(scale=noise, size=z.shape))
    return DepthView(i, z.astype(np.float32), K, T), block


def test_a_dominant_plane_does_not_bend_what_stands_on_it():
    """On an obliquely seen table, depth is itself a ramp across the image: scale and tilt are then nearly
    the same thing for the table, and a careless fit trades one against the other with huge opposite
    values that cancel on the table but throw the dish off. Found on the synthetic bowl (rim lost)."""
    truth, block = scene_view(0, 0.0)
    others = [scene_view(1, 0.03, noise=0.003)[0], scene_view(2, -0.03, noise=0.003)[0], scene_view(3, 0.05, noise=0.003)[0]]
    noisy = scene_view(0, 0.0, noise=0.003, seed=9)[0]
    bias = depth_bias_from_views(noisy, others)
    fixed = bias.apply(noisy.depth)
    moved = rel_err(fixed, noisy.depth)
    assert moved[block].max() < 0.002 and moved.max() < 0.002, (moved[block].max(), moved.max())   # nothing to correct: nothing moves
    # and a real bias is still removed, on the table and on the block alike
    wrong = bent(noisy, scale=1.015, tilt_rel=(0.02, 0.01))
    bias = depth_bias_from_views(wrong, others)
    err = rel_err(bias.apply(wrong.depth), truth.depth)
    assert np.median(err[block]) < 0.004 and np.median(err[~block]) < 0.004, (np.median(err[block]), np.median(err[~block]))
