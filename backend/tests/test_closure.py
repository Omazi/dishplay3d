"""Closing the surface (reconstruction/closure.py).

Where nothing could be measured the model had a hole. A smooth surface is now laid across the holes and the
dish gets a flat base on the table, as photogrammetry products do. What was reconstructed is not touched:
its vertices stay where they were, and everything added is labelled ESTIMATED.
"""
import numpy as np
import open3d as o3d
from scipy.spatial import cKDTree

from reconstruction.closure import close_surface
from reconstruction.completion import CompletionProposal, check_measured_protected
from reconstruction.mesh_preview import ESTIMATED, INTERPOLATED, MEASURED

R = 0.06


def dome(hole_at=None, hole_radius=0.015):
    """Upper half of a sphere of radius 6 cm resting on y = 0, optionally with a round hole in its side."""
    m = o3d.geometry.TriangleMesh.create_sphere(radius=R, resolution=70)
    V, T = np.asarray(m.vertices).copy(), np.asarray(m.triangles).copy()
    T = T[(V[T][:, :, 1] > 0.002).all(1)]
    if hole_at is not None:
        T = T[np.linalg.norm(V[T].mean(1) - hole_at, axis=1) > hole_radius]
    used = np.unique(T)
    remap = -np.ones(len(V), int)
    remap[used] = np.arange(len(used))
    V, T = V[used], remap[T]
    N = V / np.linalg.norm(V, axis=1, keepdims=True)
    C = np.full((len(V), 3), 180, np.uint8)
    cls = np.where(V[:, 0] > 0, MEASURED, INTERPOLATED).astype(np.uint8)
    return V.astype(np.float32), C, N.astype(np.float32), cls, T.astype(np.uint32)


def on_sphere(direction):
    d = np.asarray(direction, float)
    return R * d / np.linalg.norm(d)


def dist_to_mesh(V, T, P):
    scene = o3d.t.geometry.RaycastingScene()
    scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(
        o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(V.astype(np.float64)), o3d.utility.Vector3iVector(T.astype(np.int32)))))
    return scene.compute_distance(o3d.core.Tensor(np.asarray(P, np.float32))).numpy()


def test_a_hole_is_closed_with_a_surface_that_follows_the_shape():
    centre = on_sphere([1.0, 0.8, 0.3])
    V, C, N, cls, T = dome(hole_at=centre)
    # points of the true surface inside the hole: not covered before
    rng = np.random.default_rng(0)
    P = centre + rng.normal(scale=0.004, size=(400, 3))
    P = R * P / np.linalg.norm(P, axis=1, keepdims=True)
    assert np.median(dist_to_mesh(V, T, P)) > 0.004
    V2, C2, N2, cls2, T2, info = close_surface(V, C, N, cls, T, box_size_m=(0.2, 0.1, 0.2), max_gap_m=0.02)
    # what existed is untouched and comes first
    assert np.array_equal(V2[:len(V)], V) and np.array_equal(cls2[:len(V)], cls) and np.array_equal(T2[:len(T)], T)
    assert check_measured_protected(V, cls, CompletionProposal(V2, T2, cls2 == ESTIMATED, "test", "n/a"))
    added = cls2[len(V):]
    assert len(added) > 20 and (added == ESTIMATED).all() and info["added_triangles"] > 20
    # the hole is covered, and by a surface that continues the sphere
    assert np.percentile(dist_to_mesh(V2, T2, P), 95) < 0.002
    new = V2[len(V):]
    near_hole = np.linalg.norm(new - centre, axis=1) < 0.02
    assert near_hole.sum() > 10
    assert np.percentile(np.abs(np.linalg.norm(new[near_hole], axis=1) - R), 90) < 0.002
    assert len(C2) == len(V2) == len(N2) and T2.max() < len(V2)


def test_the_dish_gets_a_flat_base_on_the_table():
    V, C, N, cls, T = dome()
    g = np.stack(np.meshgrid(np.arange(-R, R, 0.002), np.arange(-R, R, 0.002)), -1).reshape(-1, 2)
    under = g[np.linalg.norm(g, axis=1) < R - 0.004]                 # strictly under the dome
    V2, C2, N2, cls2, T2, info = close_surface(V, C, N, cls, T, box_size_m=(0.2, 0.1, 0.2), floor_y=0.0, floor_xz=under)
    # the underside is closed at table height
    g = np.stack(np.meshgrid(np.linspace(-0.035, 0.035, 15), [0.0], np.linspace(-0.035, 0.035, 15)), -1).reshape(-1, 3)
    assert np.percentile(dist_to_mesh(V2, T2, g), 95) < 0.003
    assert V2[:, 1].min() > -0.003                      # nothing bulges under the table
    assert (cls2[len(V):] == ESTIMATED).all() and info["floor"]


def test_crumbs_are_removed_and_real_pieces_kept():
    from reconstruction.mesh_preview import drop_small_pieces
    V, C, N, cls, T = dome()
    crumb = np.array([[0.2, 0.0, 0.2], [0.203, 0.0, 0.2], [0.2, 0.0, 0.203]], np.float32)
    V2 = np.concatenate([V, crumb]); T2 = np.concatenate([T, [[len(V), len(V) + 1, len(V) + 2]]]).astype(np.uint32)
    C2 = np.concatenate([C, C[:3]]); N2 = np.concatenate([N, N[:3]]); c2 = np.concatenate([cls, cls[:3]])
    V3, C3, N3, c3, T3, dropped = drop_small_pieces(V2, C2, N2, c2, T2)
    assert dropped == 1 and len(T3) == len(T) and len(V3) == len(V)
    assert drop_small_pieces(V, C, N, cls, T)[5] == 0


def test_a_gap_too_wide_to_guess_is_left_open():
    """Half of the object was never seen: bridging it would be invention, not interpolation."""
    V, C, N, cls, T = dome()
    keep = (V[T][:, :, 0] > 0).all(1)                   # only the +x half exists
    T = T[keep]
    V2, C2, N2, cls2, T2, info = close_surface(V, C, N, cls, T, box_size_m=(0.2, 0.1, 0.2), max_gap_m=0.012)
    far = on_sphere([-1.0, 0.6, 0.0])[None]             # the middle of the missing half
    assert dist_to_mesh(V2, T2, far)[0] > 0.02
    new = V2[len(V):]
    if len(new):
        used = np.unique(T)
        d, _ = cKDTree(V[used]).query(new)
        assert d.max() <= 0.012 + 0.004


def test_nothing_to_close_changes_nothing():
    V, C, N, cls, T = dome()
    empty = (np.zeros((0, 3), np.float32), np.zeros((0, 3), np.uint8), np.zeros((0, 3), np.float32), np.zeros(0, np.uint8), np.zeros((0, 3), np.uint32))
    out = close_surface(*empty, box_size_m=(0.2, 0.1, 0.2))
    assert len(out[0]) == 0 and out[5]["added_triangles"] == 0


def test_triangles_on_an_edge_shared_by_three_are_dropped():
    """The texture atlas refuses a mesh with an edge shared by more than two triangles (found on a real
    capture: one such edge made the whole photo texture fall back to vertex colours)."""
    from reconstruction.mesh_preview import edge_manifold_triangles
    T = np.array([[0, 1, 2], [0, 1, 3], [0, 1, 4], [5, 6, 7], [5, 6, 8]], np.uint32)   # edge 0-1 has three triangles
    keep = edge_manifold_triangles(T)
    assert keep.tolist() == [False, False, False, True, True]
    assert edge_manifold_triangles(T[3:]).all()


def test_closing_never_creates_an_edge_shared_by_three_triangles():
    centre = on_sphere([1.0, 0.8, 0.3])
    V, C, N, cls, T = dome(hole_at=centre)
    V2, C2, N2, cls2, T2, info = close_surface(V, C, N, cls, T, box_size_m=(0.2, 0.1, 0.2), max_gap_m=0.02)
    from reconstruction.mesh_preview import edge_manifold_triangles
    assert edge_manifold_triangles(T2[len(T):]).all()
