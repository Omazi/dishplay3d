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


def estimate_table_y(V: np.ndarray, lo: float = -0.012, hi: float = 0.03, bin_m: float = 0.001) -> float:
    """Height of the support surface in the box frame. The box base is placed on the table, but a few
    millimetres off is common: the table is taken as the lowest well-populated horizontal layer."""
    y = V[:, 1]
    y = y[(y >= lo) & (y <= hi)]
    if len(y) < 200:
        return 0.0
    hist, edges = np.histogram(y, bins=int(round((hi - lo) / bin_m)), range=(lo, hi))
    hist = np.convolve(hist, np.ones(3), mode="same")
    strong = np.nonzero(hist >= 0.5 * hist.max())[0]
    return float(edges[strong[0]] + 1.5 * bin_m) if len(strong) else 0.0


def fit_table_plane(V: np.ndarray, band_m: float = 0.008, max_slope: float = 0.08) -> tuple[float, float, float]:
    """Table as a plane y = a*x + b*z + c in the box frame. The tracker's plane is good to a few
    millimetres and a degree or two, which matters when the table is cut 4 mm above it."""
    c = estimate_table_y(V)
    a = b = 0.0
    for tol in (band_m, 0.005, 0.003):
        r = V[:, 1] - (a * V[:, 0] + b * V[:, 2] + c)
        sel = np.abs(r) < tol
        if sel.sum() < 200:
            break
        A = np.stack([V[sel, 0], V[sel, 2], np.ones(sel.sum())], 1)
        sol, *_ = np.linalg.lstsq(A, V[sel, 1], rcond=None)
        if abs(sol[0]) > max_slope or abs(sol[1]) > max_slope:   # not a table: keep the level estimate
            break
        a, b, c = (float(v) for v in sol)
    return a, b, c


@dataclass
class DishFootprint:
    """Where the dish stands on the table, seen from above.

    The scan box is rectangular and a plate is round: the corners of the box contain bare table. The
    footprint is the area where the model rises above the table (filled, slightly grown). Inside it
    everything is the dish, including a low plate floor; outside it, the thin layer at table height is
    the support surface. Nothing is added or closed: the underside stays open.
    """
    grid: np.ndarray
    origin: np.ndarray
    cell_m: float
    table_y: float            # table height at the centre of the box
    band_m: float
    slope_x: float = 0.0
    slope_z: float = 0.0
    core: np.ndarray | None = None   # footprint without its outer ring

    @staticmethod
    def from_vertices(V: np.ndarray, table_band_m: float = 0.004, body_min_m: float = 0.006, cell_m: float = 0.002,
                      min_blob_share: float = 0.15, rim_ring_m: float = 0.010) -> "DishFootprint | None":
        from scipy import ndimage
        if len(V) < 30:
            return None
        a, b, c = fit_table_plane(V)
        height = V[:, 1] - (a * V[:, 0] + b * V[:, 2] + c)
        body = height > body_min_m
        if body.sum() < 30:
            return None
        origin = V[:, [0, 2]].min(0) - 3 * cell_m
        ij = np.floor((V[:, [0, 2]] - origin) / cell_m).astype(int)
        grid = np.zeros(ij.max(0) + 4, bool)
        grid[ij[body, 0], ij[body, 1]] = True
        # Bumps of a noisy table are isolated specks; a dish is a large connected area.
        grid = ndimage.binary_closing(grid, iterations=2)   # vertices can be several cells apart
        grid = ndimage.binary_opening(grid, iterations=1)
        lab, n = ndimage.label(grid)
        if n == 0:
            return None
        area = ndimage.sum(grid, lab, np.arange(1, n + 1))
        grid = np.isin(lab, 1 + np.nonzero(area >= min_blob_share * area.max())[0])
        grid = ndimage.binary_closing(grid, iterations=3)
        grid = ndimage.binary_fill_holes(grid)
        grid = ndimage.binary_dilation(grid, iterations=2)
        # Table that shows under an overhanging rim, or just around the foot of the dish, lies in a thin
        # ring along the outline: there the table layer is dropped too. Further in, a low floor is the dish.
        core = ndimage.binary_erosion(grid, iterations=2 + int(round(rim_ring_m / cell_m)))
        return DishFootprint(grid, origin, cell_m, c, table_band_m, a, b, core)

    def height(self, P: np.ndarray) -> np.ndarray:
        return P[:, 1] - (self.slope_x * P[:, 0] + self.slope_z * P[:, 2] + self.table_y)

    def inside(self, P: np.ndarray, core: bool = False) -> np.ndarray:
        grid = self.core if core and self.core is not None else self.grid
        ij = np.floor((P[:, [0, 2]] - self.origin) / self.cell_m).astype(int)
        ok = (ij[:, 0] >= 0) & (ij[:, 0] < grid.shape[0]) & (ij[:, 1] >= 0) & (ij[:, 1] < grid.shape[1])
        out = np.zeros(len(P), bool)
        out[ok] = grid[ij[ok, 0], ij[ok, 1]]
        return out

    def keep(self, P: np.ndarray) -> np.ndarray:
        """True for points of the dish, False for the table around it."""
        return self.inside(P, core=True) | (self.height(P) > self.band_m)

    def hull_xz(self) -> np.ndarray:
        """Convex outline of the footprint in the box frame, as (x, z) points."""
        import cv2
        ii, jj = np.nonzero(self.grid)
        pts = (np.stack([ii, jj], 1) + 0.5) * self.cell_m + self.origin
        return cv2.convexHull(pts.astype(np.float32)).reshape(-1, 2).astype(np.float64)


def crop_mesh(V, C, N, cls, T, keep_t: np.ndarray):
    """Keep the selected triangles and only the vertices they use."""
    used = np.unique(T[keep_t])
    remap = -np.ones(len(V), np.int64)
    remap[used] = np.arange(len(used))
    return V[used], C[used], N[used], cls[used], remap[T[keep_t]].astype(np.uint32)


def isolate_dish(V: np.ndarray, T: np.ndarray, table_band_m: float = 0.004, body_min_m: float = 0.006,
                 cell_m: float = 0.002) -> np.ndarray:
    """Triangle mask that keeps the dish and drops the table around it (see DishFootprint)."""
    if len(T) == 0:
        return np.zeros(0, bool)
    fp = DishFootprint.from_vertices(V, table_band_m, body_min_m, cell_m)
    if fp is None:
        return np.ones(len(T), bool)
    return fp.keep(V)[T].all(1)
