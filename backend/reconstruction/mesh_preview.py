"""Partial surface extraction restricted to well-supported regions.

Provenance classes (per vertex / point), shared with the iOS renderer:
  0 MEASURED      supported by validated depth from >= 2 frames nearby
  1 INTERPOLATED  TSDF surface between measured samples (single-frame or sparse support)
  2 ESTIMATED     proposed by a completion provider (never produced by default)
  3 TRACKING      ARKit feature points (iOS only, never sent by the server)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import open3d as o3d
from scipy.spatial import cKDTree

from .coordinates import inside_box

MEASURED, INTERPOLATED, ESTIMATED, TRACKING = 0, 1, 2, 3


@dataclass
class MeshConfig:
    support_radius_m: float = 0.004
    interp_radius_m: float = 0.008
    min_frames_measured: int = 2
    min_component_triangles: int = 40
    min_component_fraction: float = 0.004
    max_triangles: int = 60000
    # Taubin smoothing of the vertex positions (colours untouched). It removes the millimetre-scale
    # crumpling left by view-to-view depth noise without shrinking the shape or closing concavities.
    smooth_iterations: int = 10


def classify_vertices(vertices: np.ndarray, pts: np.ndarray, nframes: np.ndarray, cfg: MeshConfig,
                      weak: np.ndarray | None = None) -> np.ndarray:
    cls = np.full(len(vertices), 255, np.uint8)  # 255 = unsupported -> removed
    if len(pts) == 0 or len(vertices) == 0:
        return cls
    tree = cKDTree(pts.astype(np.float64))
    d, idx = tree.query(vertices, k=8, distance_upper_bound=cfg.interp_radius_m)
    found = np.isfinite(d)
    idx_safe = np.where(found, idx, 0)
    strong = nframes if weak is None else np.where(weak, 0, nframes)  # weak texture never counts as measured
    nf = np.where(found & (d <= cfg.support_radius_m), strong[idx_safe], 0)
    measured = nf.max(1) >= cfg.min_frames_measured
    interp = found[:, 0]
    cls[interp] = INTERPOLATED
    cls[measured] = MEASURED
    return cls


def supported_mesh(mesh: o3d.geometry.TriangleMesh, size_m, pts, nframes, cfg: MeshConfig = MeshConfig(), weak=None):
    """Crop to the box, drop unsupported triangles and tiny islands, decimate, classify.

    No hole filling and no closing: concavities (plate well, bowl) stay open.
    Returns (vertices Nx3 f32, colors Nx3 u8, normals Nx3 f32, classes N u8, triangles Mx3 u32).
    """
    empty = (np.zeros((0, 3), np.float32), np.zeros((0, 3), np.uint8), np.zeros((0, 3), np.float32),
             np.zeros(0, np.uint8), np.zeros((0, 3), np.uint32))
    if len(mesh.triangles) == 0:
        return empty
    V = np.asarray(mesh.vertices)
    keep_v = inside_box(V, size_m, margin=0.005, below=0.005)
    cls = classify_vertices(V, pts, nframes, cfg, weak)
    keep_v &= cls != 255
    T = np.asarray(mesh.triangles)
    keep_t = keep_v[T].all(1)
    mesh.remove_triangles_by_mask(~keep_t)
    mesh.remove_unreferenced_vertices()
    if len(mesh.triangles) == 0:
        return empty
    tri_clusters, n_tri, _ = mesh.cluster_connected_triangles()
    tri_clusters = np.asarray(tri_clusters)
    n_tri = np.asarray(n_tri)
    # Islands: tiny ones are noise; small ones compared with the whole model are detached fragments.
    limit = max(cfg.min_component_triangles, int(cfg.min_component_fraction * len(tri_clusters)))
    mesh.remove_triangles_by_mask(n_tri[tri_clusters] < limit)
    mesh.remove_unreferenced_vertices()
    if cfg.smooth_iterations > 0 and len(mesh.triangles):
        mesh = mesh.filter_smooth_taubin(number_of_iterations=cfg.smooth_iterations,
                                         filter_scope=o3d.geometry.FilterScope.Vertex)
    if len(mesh.triangles) > cfg.max_triangles:
        mesh = mesh.simplify_quadric_decimation(cfg.max_triangles)
    if len(mesh.triangles) == 0:
        return empty
    mesh.compute_vertex_normals()
    V = np.asarray(mesh.vertices)
    cls = classify_vertices(V, pts, nframes, cfg, weak)
    cls[cls == 255] = INTERPOLATED  # decimation can move a vertex slightly off support
    colors = (np.clip(np.asarray(mesh.vertex_colors), 0, 1) * 255).astype(np.uint8) if mesh.has_vertex_colors() else np.full((len(V), 3), 180, np.uint8)
    return (V.astype(np.float32), colors, np.asarray(mesh.vertex_normals).astype(np.float32), cls,
            np.asarray(mesh.triangles).astype(np.uint32))


def surface_area(vertices: np.ndarray, triangles: np.ndarray, classes: np.ndarray | None = None, cls: int | None = None) -> float:
    if len(triangles) == 0:
        return 0.0
    t = triangles
    if classes is not None and cls is not None:
        t = t[(classes[t] == cls).all(1)]
    a = vertices[t[:, 1]] - vertices[t[:, 0]]
    b = vertices[t[:, 2]] - vertices[t[:, 0]]
    return float(0.5 * np.linalg.norm(np.cross(a, b), axis=1).sum())


def isolate_dish(V: np.ndarray, T: np.ndarray, table_band_m: float = 0.004, body_min_m: float = 0.006,
                 cell_m: float = 0.002) -> np.ndarray:
    """Triangle mask that keeps the dish and drops the table around it.

    Footprint = where the model rises above the table (filled, slightly grown). Everything inside the
    footprint is kept, including a low plate floor; outside it, the thin layer at table height is the
    support surface and is removed. Nothing is added or closed: the underside stays open.
    """
    from scipy import ndimage
    if len(T) == 0:
        return np.zeros(0, bool)
    body = V[:, 1] > body_min_m
    if body.sum() < 30:
        return np.ones(len(T), bool)
    lo = V[:, [0, 2]].min(0) - 3 * cell_m
    ij = np.floor((V[:, [0, 2]] - lo) / cell_m).astype(int)
    shape = ij.max(0) + 4
    grid = np.zeros(shape, bool)
    grid[ij[body, 0], ij[body, 1]] = True
    grid = ndimage.binary_closing(grid, iterations=3)
    grid = ndimage.binary_fill_holes(grid)
    grid = ndimage.binary_dilation(grid, iterations=2)
    inside = grid[ij[:, 0], ij[:, 1]]
    keep_v = inside | (V[:, 1] > table_band_m)
    return keep_v[T].all(1)
