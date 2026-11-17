"""Closing the surface: a smooth surface across the holes, a flat base under the dish.

Stereo cannot measure everything (uniform, shiny or hidden parts), and a model with holes does not look like
the dish. Photogrammetry products always close the surface and lay the photographs over it. The same is done
here, with two rules that keep the result honest:

  - what was reconstructed is not touched: its vertices and triangles are returned unchanged, first;
  - everything added is labelled ESTIMATED, and nothing is added farther than `max_gap_m` from real data:
    a hole is bridged, a side that was never seen is not invented.

Method: screened Poisson reconstruction (Open3D, MIT) of the existing vertices and their normals — a
watertight surface that passes through the data and continues it smoothly where data is missing. Only the
parts of that surface lying off the existing mesh are kept, as patches. When the table has been removed,
points facing down are added under the dish at table height so that the base closes flat.
"""
from __future__ import annotations

import numpy as np
import open3d as o3d
from scipy.spatial import cKDTree

from .mesh_preview import ESTIMATED, edge_manifold_triangles


def close_surface(V, C, N, cls, T, box_size_m, floor_y: float | None = None, floor_xz: np.ndarray | None = None,
                  floor_slope=(0.0, 0.0), max_gap_m: float = 0.008, cell_m: float = 0.002, off_mesh_m: float | None = None):
    """(V, C, N, cls, T, info) with ESTIMATED patches appended. The inputs come first, unchanged.

    floor_xz: (x, z) positions strictly UNDER the dish (not its convex outline) where the base rests on the
    table at floor_y. max_gap_m: nothing is added farther than this from reconstructed data, so a hole up to
    twice as wide is bridged and anything larger stays open — measured on a real capture, a generous value
    (3 cm) wrapped the object in a bulging skin instead of mending it."""
    info = {"status": "nothing_to_close", "added_vertices": 0, "added_triangles": 0, "floor": False}
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
    d_data, _ = cKDTree(P).query(PV)
    w, h, dd = box_size_m
    ok_v = (d_data <= max_gap_m) & (np.abs(PV[:, 0]) <= w / 2 + 0.005) & (np.abs(PV[:, 2]) <= dd / 2 + 0.005) & (PV[:, 1] <= h + 0.005)
    if floor:
        ok_v &= PV[:, 1] >= float(floor_y) + floor_slope[0] * PV[:, 0] + floor_slope[1] * PV[:, 2] - cell_m
    # Keep only what lies off the existing mesh: the patches.
    scene = o3d.t.geometry.RaycastingScene()
    scene.add_triangles(o3d.core.Tensor(V.astype(np.float32)), o3d.core.Tensor(T.astype(np.uint32)))
    cen = PV[PT].mean(1)
    d_mesh = scene.compute_distance(o3d.core.Tensor(cen.astype(np.float32))).numpy()
    off = off_mesh_m if off_mesh_m is not None else 0.75 * cell_m
    keep_t = ok_v[PT].all(1) & (d_mesh > off)
    if not keep_t.any():
        return V, C, N, cls, T, info
    # A patch cut exactly at the rim of its hole leaves a crack all around (the background shows through).
    # It is extended by two rings of triangles so that it overlaps the surface it mends.
    usable = ok_v[PT].all(1)
    for _ in range(2):
        touched = np.zeros(len(PV), bool)
        touched[PT[keep_t].reshape(-1)] = True
        keep_t = usable & (keep_t | touched[PT].any(1))
    PT = PT[keep_t]
    # A patch must hang on the existing surface (or on the base): free-floating pieces are dropped.
    patch = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(PV), o3d.utility.Vector3iVector(PT))
    lab, counts, _ = patch.cluster_connected_triangles()
    lab = np.asarray(lab)
    d_vert = scene.compute_distance(o3d.core.Tensor(PV.astype(np.float32))).numpy()
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
