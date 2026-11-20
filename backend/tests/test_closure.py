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


def test_no_crack_is_left_between_a_patch_and_the_surface_around_it():
    """Seen in a browser on a real capture: a thin line of background showing all around each closed hole."""
    centre = on_sphere([1.0, 0.8, 0.3])
    hole_r = 0.015
    V, C, N, cls, T = dome(hole_at=centre, hole_radius=hole_r)
    V2, C2, N2, cls2, T2, info = close_surface(V, C, N, cls, T, box_size_m=(0.2, 0.1, 0.2), max_gap_m=0.02)
    # points of the true sphere in a band around the rim of the hole
    rng = np.random.default_rng(1)
    P = rng.normal(size=(60000, 3))
    P = R * P / np.linalg.norm(P, axis=1, keepdims=True)
    d = np.linalg.norm(P - centre, axis=1)
    band = P[(d > hole_r - 0.004) & (d < hole_r + 0.004) & (P[:, 1] > 0.006)]
    assert len(band) > 200
    assert np.percentile(dist_to_mesh(V2, T2, band), 99) < 0.0008


def _object_on(support_y, thin: bool = False):
    """Vertices of an object standing on a support whose height at (x, z) is support_y(x, z): a low dome
    (a dish, 3 cm high) or, with thin=True, a flat slab 1.2 cm thick (a book, a board, a pizza)."""
    g = np.stack(np.meshgrid(np.arange(-0.14, 0.14, 0.003), np.arange(-0.14, 0.14, 0.003)), -1).reshape(-1, 2)
    r = np.linalg.norm(g, axis=1)
    if thin:
        inside = (np.abs(g[:, 0]) < 0.09) & (np.abs(g[:, 1]) < 0.06)
        obj_h = np.where(inside, 0.012, 0.0)
    else:
        inside = r < 0.07
        obj_h = np.where(r < 0.08, 0.03 * np.sqrt(np.clip(1 - (r / 0.08) ** 2, 0, 1)) + 0.004, 0.0)
    y = support_y(g[:, 0], g[:, 1]) + obj_h
    return np.stack([g[:, 0], y, g[:, 1]], 1), inside


def test_the_table_is_not_removed_when_the_support_is_not_a_flat_table():
    """Found on a real capture: a book on a soft bed. The 'table' level was fitted halfway through the uneven
    support and a quarter of the book was cut away with it. Better to leave the surroundings in the model."""
    from reconstruction.mesh_preview import DishFootprint
    flat, dish = _object_on(lambda x, z: np.zeros_like(x))
    fp = DishFootprint.from_vertices(flat)
    assert fp is not None and abs(fp.table_y) < 0.002
    assert fp.keep(flat)[dish].mean() > 0.97 and fp.keep(flat)[np.linalg.norm(flat[:, [0, 2]], axis=1) > 0.10].mean() < 0.05
    blanket = lambda x, z: 0.012 * np.sin(x * 22) + 0.010 * np.cos(z * 17)             # +-2 cm of relief
    soft, slab = _object_on(blanket, thin=True)
    before = DishFootprint.from_vertices(soft, max_below_share=1.0)                    # the rule switched off
    left = before.keep(soft)[~slab].mean()
    assert before is not None and 0.3 < left < 0.9, "without the rule the support is half removed: scraps all around"
    assert DishFootprint.from_vertices(soft) is None                                   # with it: nothing is cut
    # a table with a few millimetres of relief (a cloth lying flat) is still removed
    cloth, dish2 = _object_on(lambda x, z: 0.25 * blanket(x, z))
    fp2 = DishFootprint.from_vertices(cloth)
    assert fp2 is not None and fp2.keep(cloth)[dish2].mean() > 0.97
