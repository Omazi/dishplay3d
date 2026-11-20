"""Closing the surface: a smooth surface across the holes, a flat base under the dish.

Stereo cannot measure everything (uniform, shiny or hidden parts), and a model with holes does not look like
the dish. Photogrammetry products always close the surface and lay the photographs over it. The same is done
here, with two rules that keep the result honest:

  - what was reconstructed is not touched: its vertices and triangles are returned unchanged, first;
  - everything added is labelled ESTIMATED, and nothing is added farther than `max_gap_m` from real data:
    a hole is bridged, a side that was never seen is not invented;
  - one exception to the distance rule, for what was photographed but could not be measured (a uniform or
    shiny area): a hole wider than that is closed too when it is enclosed by the reconstructed surface, no
    wider than `max_hole_m`, and the cameras looked at it. On real captures those holes showed the dark base
    of the model through the dish. The outside of the model, its back and its underside never qualify.

Method: screened Poisson reconstruction (Open3D, MIT) of the existing vertices and their normals — a
watertight surface that passes through the data and continues it smoothly where data is missing. Only the
parts of that surface lying off the existing mesh are kept, as patches. When the table has been removed,
points facing down are added under the dish at table height so that the base closes flat.
"""
from __future__ import annotations

import numpy as np
import open3d as o3d
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from .coordinates import headroom
from .mesh_preview import ESTIMATED, edge_manifold_triangles


def _border_triangles(PT: np.ndarray, n_vertices: int) -> np.ndarray:
    """Triangles with an edge that no other triangle shares: the rim of a surface that is not closed."""
    T = PT.astype(np.int64)
    e = np.sort(np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]]), 1)
    key = e[:, 0] * (n_vertices + 1) + e[:, 1]
    _, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    return (cnt[inv] == 1).reshape(3, -1).any(0)


def _enclosed_holes(PV: np.ndarray, PT: np.ndarray, core_t: np.ndarray, d_vert: np.ndarray, in_box_v: np.ndarray, scene,
                    cameras: np.ndarray, outward: float, max_hole_m: float, min_seen_share: float,
                    max_cameras: int = 16) -> tuple[np.ndarray, dict]:
    """Among the triangles of the closed surface (PV, PT) that the rule on rims leaves out (core_t: off the
    reconstructed surface and too far from data), those lying in a hole that is enclosed by the reconstructed
    surface, no wider than max_hole_m and seen by the cameras.

    These triangles fall into connected pieces. The middle of a hole enclosed by the surface is a piece of its
    own (breaks in its rim narrower than what the rule on rims mends do not open it), and nothing in it is
    farther from the surface than half its width. Everything that continues the model beyond its outline,
    behind it or under it hangs together in one large piece that reaches far from the surface: it never
    qualifies. Nor does a piece cut by the scan box, or one that reaches the rim of the closed surface itself
    (when the data is an open sheet the closed surface is cut off below it, and a lip hangs from the outline of
    the sheet: enclosed by nothing). A piece must also face the cameras without the reconstructed surface in
    between: what no camera saw is not invented.
    Returns (mask over PT, {"closed", "largest_m", "left_open": {reason: count}}).
    """
    mask = np.zeros(len(PT), bool)
    stats = {"closed": 0, "largest_m": 0.0, "left_open": {}}
    gap = np.nonzero(core_t)[0]
    if len(gap) == 0:
        return mask, stats
    # connected pieces: two triangles belong together when they share an edge
    tri = PT[gap].astype(np.int64)
    e = np.sort(np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), 1)
    owner = np.tile(np.arange(len(gap)), 3)
    key = e[:, 0] * (len(PV) + 1) + e[:, 1]
    order = np.argsort(key, kind="stable")
    k, o = key[order], owner[order]
    same = k[1:] == k[:-1]
    graph = coo_matrix((np.ones(int(same.sum()), np.int8), (o[:-1][same], o[1:][same])), shape=(len(gap), len(gap)))
    n, lab = connected_components(graph, directed=False)
    reach = np.zeros(n)
    np.maximum.at(reach, lab, d_vert[tri].max(1))               # how far from the surface the piece goes
    whole = np.ones(n, bool)
    np.logical_and.at(whole, lab, in_box_v[tri].all(1))        # cut by the scan box: not enclosed
    closed = np.ones(n, bool)
    np.logical_and.at(closed, lab, ~_border_triangles(PT, len(PV))[gap])   # reaches the rim of the closed surface
    fits = reach <= max_hole_m / 2
    stats["left_open"] = {k_: int(v) for k_, v in (("too_wide", (~fits).sum()), ("at_the_edge_of_the_box", (fits & ~whole).sum()),
                                                    ("beyond_the_outline", (fits & whole & ~closed).sum())) if v}
    cand = fits & whole & closed
    if not cand.any():
        return mask, stats
    sel = np.nonzero(cand[lab])[0]
    t3 = PV[tri[sel]]
    nrm = np.cross(t3[:, 1] - t3[:, 0], t3[:, 2] - t3[:, 0])
    area = np.linalg.norm(nrm, axis=1) / 2
    nrm = outward * nrm / np.maximum(2 * area[:, None], 1e-18)
    cen = t3.mean(1)
    cams = np.asarray(cameras, np.float64).reshape(-1, 3)
    cams = cams[np.linspace(0, len(cams) - 1, min(max_cameras, len(cams))).astype(np.int64)]
    seen = np.zeros(len(sel), np.int32)
    for cam in cams:
        v = cam - cen
        dist = np.linalg.norm(v, axis=1)
        dirs = v / np.maximum(dist[:, None], 1e-9)
        facing = np.einsum("ij,ij->i", nrm, dirs) > 0.2
        if not facing.any():
            continue
        rays = np.concatenate([cen[facing] + 1.5e-3 * dirs[facing], dirs[facing]], 1).astype(np.float32)
        t_hit = scene.cast_rays(o3d.core.Tensor(rays))["t_hit"].numpy()
        clear = ~(t_hit < dist[facing] - 3e-3)                  # nothing of the reconstructed surface in between
        seen[np.nonzero(facing)[0][clear]] += 1
    need = min(2, len(cams))
    seen_area = np.zeros(n)
    all_area = np.zeros(n)
    np.add.at(seen_area, lab[sel], area * (seen >= need))
    np.add.at(all_area, lab[sel], area)
    ok = cand & (seen_area >= min_seen_share * np.maximum(all_area, 1e-18))
    unseen = int((cand & ~ok).sum())
    if unseen:
        stats["left_open"]["not_seen_by_the_cameras"] = unseen
    if ok.any():
        mask[gap[ok[lab]]] = True
        stats["closed"] = int(ok.sum())
        stats["largest_m"] = float(2 * reach[ok].max())
    return mask, stats


def close_surface(V, C, N, cls, T, box_size_m, floor_y: float | None = None, floor_xz: np.ndarray | None = None,
                  floor_slope=(0.0, 0.0), max_gap_m: float = 0.008, cell_m: float = 0.002, off_mesh_m: float | None = None,
                  cameras: np.ndarray | None = None, max_hole_m: float = 0.06, min_seen_share: float = 0.35):
    """(V, C, N, cls, T, info) with ESTIMATED patches appended. The inputs come first, unchanged.

    floor_xz: (x, z) positions strictly UNDER the dish (not its convex outline) where the base rests on the
    table at floor_y. max_gap_m: nothing is added farther than this from reconstructed data, so a hole up to
    twice as wide is bridged and anything larger stays open — measured on a real capture, a generous value
    (3 cm) wrapped the object in a bulging skin instead of mending it.

    cameras: positions of the cameras (Nx3, frame of the box). With them, a hole wider than that is closed too
    when it is enclosed by the surface, at most max_hole_m wide, and at least min_seen_share of it faced two
    cameras with nothing in between (see _enclosed_holes). Without them only the rule above applies.
    min_seen_share: what closes the back or the underside of the model is seen by no camera at all (0 %); the
    inside of a hollow (a cup, the opening of a shoe on a real capture: 41 %) is seen at its bottom and not on
    its walls, and is closed."""
    info = {"status": "nothing_to_close", "added_vertices": 0, "added_triangles": 0, "floor": False,
            "holes_closed": 0, "largest_hole_closed_m": 0.0, "holes_left_open": {}}
    if len(T) < 50:
        return V, C, N, cls, T, info
    used = np.unique(T)
    P, Nn, Cc = V[used].astype(np.float64), N[used].astype(np.float64), C[used].astype(np.float64) / 255.0
    Nn /= np.linalg.norm(Nn, axis=1, keepdims=True) + 1e-12
    floor = floor_y is not None and floor_xz is not None and len(floor_xz) >= 3
    n_real = len(P)
    if floor:
        fx = np.asarray(floor_xz, np.float64)
        F = np.stack([fx[:, 0], float(floor_y) + floor_slope[0] * fx[:, 0] + floor_slope[1] * fx[:, 1], fx[:, 1]], 1)
        low = P[:, 1] < np.percentile(P[:, 1], 10)
        base_colour = np.median(Cc[low], 0) * 0.6 if low.any() else np.full(3, 0.3)   # underside: darker than the lowest ring
        P = np.concatenate([P, F])
        Nn = np.concatenate([Nn, np.tile([0.0, -1.0, 0.0], (len(F), 1))])
        Cc = np.concatenate([Cc, np.tile(base_colour, (len(F), 1))])
        info["floor"] = True
    pcd = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(P))
    pcd.normals = o3d.utility.Vector3dVector(Nn)
    pcd.colors = o3d.utility.Vector3dVector(Cc)
    extent = float((P.max(0) - P.min(0)).max()) * 1.1
    depth = int(np.clip(np.ceil(np.log2(max(extent / cell_m, 2.0))), 5, 9))
    with o3d.utility.VerbosityContextManager(o3d.utility.VerbosityLevel.Error):
        pm, _ = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(pcd, depth=depth, scale=1.1, linear_fit=False)
    PV, PT = np.asarray(pm.vertices), np.asarray(pm.triangles)
    if len(PT) == 0:
        return V, C, N, cls, T, info
    # Never farther than max_gap_m from real data (a hole is bridged, an unseen side is not invented), and inside the box.
    d_data, nearest_data = cKDTree(P).query(PV)
    w, h, dd = box_size_m
    in_box_v = (np.abs(PV[:, 0]) <= w / 2 + 0.005) & (np.abs(PV[:, 2]) <= dd / 2 + 0.005) & (PV[:, 1] <= h + 0.005 + headroom(box_size_m))
    if floor:
        in_box_v &= PV[:, 1] >= float(floor_y) + floor_slope[0] * PV[:, 0] + floor_slope[1] * PV[:, 2] - cell_m
    ok_v = (d_data <= max_gap_m) & in_box_v
    # Keep only what the existing mesh does not cover: the patches. "Covered" is not a matter of distance (a hole
    # 3 mm wide is nowhere farther than 1 mm from its own rim, and stayed open): a triangle of the closed surface
    # is covered when the line through its centre, across the surface, meets the mesh within `off` either way.
    scene = o3d.t.geometry.RaycastingScene()
    scene.add_triangles(o3d.core.Tensor(V.astype(np.float32)), o3d.core.Tensor(T.astype(np.uint32)))
    cen = PV[PT].mean(1)
    pm.compute_triangle_normals()
    tn = np.asarray(pm.triangle_normals)
    off = off_mesh_m if off_mesh_m is not None else 2.0 * cell_m
    probe = np.concatenate([cen - off * tn, tn], 1).astype(np.float32)
    covered = scene.cast_rays(o3d.core.Tensor(probe))["t_hit"].numpy() <= 2 * off
    d_vert = scene.compute_distance(o3d.core.Tensor(PV.astype(np.float32))).numpy()
    # Wider holes that the cameras looked at (photographed, not measured): see _enclosed_holes.
    hole_t = np.zeros(len(PT), bool)
    if cameras is not None and len(cameras) and max_hole_m > 2 * max_gap_m:
        # where the closed surface lies on the data, which side is the outside is known from the data
        side = np.einsum("ij,ij->i", tn[covered], Nn[nearest_data[PT[covered, 0]]]) if covered.any() else np.zeros(0)
        outward = -1.0 if len(side) and np.median(side) < 0 else 1.0
        core_t = ~covered & ~ok_v[PT].all(1)                   # what the rule on rims leaves out
        hole_t, holes = _enclosed_holes(PV, PT, core_t, d_vert, in_box_v, scene, cameras, outward, max_hole_m, min_seen_share)
        info.update(holes_closed=holes["closed"], largest_hole_closed_m=holes["largest_m"], holes_left_open=holes["left_open"])
    keep_t = (ok_v[PT].all(1) | hole_t) & ~covered
    if not keep_t.any():
        return V, C, N, cls, T, info
    # A patch cut exactly at the rim of its hole leaves a crack all around (the background shows through).
    # It is extended by two rings of triangles so that it overlaps the surface it mends.
    usable = ok_v[PT].all(1) | hole_t
    for _ in range(2):
        touched = np.zeros(len(PV), bool)
        touched[PT[keep_t].reshape(-1)] = True
        keep_t = usable & (keep_t | touched[PT].any(1))
    PT = PT[keep_t]
    # A patch must hang on the existing surface (or on the base): free-floating pieces are dropped.
    patch = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(PV), o3d.utility.Vector3iVector(PT))
    lab, counts, _ = patch.cluster_connected_triangles()
    lab = np.asarray(lab)
    touching = np.zeros(len(counts), bool)
    np.logical_or.at(touching, lab, (d_vert[PT] <= 2.5 * cell_m).any(1))
    PT = PT[touching[lab]]
    if len(PT) == 0:
        return V, C, N, cls, T, info
    PT = PT[edge_manifold_triangles(PT)]     # the texture atlas refuses an edge shared by three triangles
    if len(PT) == 0:
        return V, C, N, cls, T, info
    pu = np.unique(PT)
    remap = -np.ones(len(PV), np.int64)
    remap[pu] = np.arange(len(pu)) + len(V)
    pm.compute_vertex_normals()
    PN = np.asarray(pm.vertex_normals)[pu]
    # Same side as the surface they continue.
    _, nearest = cKDTree(P).query(PV[pu])
    flip = np.einsum("ij,ij->i", PN, Nn[nearest]) < 0
    PN[flip] *= -1
    PC = (np.clip(np.asarray(pm.vertex_colors)[pu], 0, 1) * 255).astype(np.uint8) if pm.has_vertex_colors() else np.full((len(pu), 3), 128, np.uint8)
    V2 = np.concatenate([V, PV[pu].astype(np.float32)])
    C2 = np.concatenate([C, PC])
    N2 = np.concatenate([N, PN.astype(np.float32)])
    cls2 = np.concatenate([cls, np.full(len(pu), ESTIMATED, np.uint8)])
    T2 = np.concatenate([T, remap[PT].astype(np.uint32)])
    info.update(status="ok", added_vertices=int(len(pu)), added_triangles=int(len(PT)), poisson_depth=depth, max_gap_m=max_gap_m)
    return V2, C2, N2, cls2, T2, info
