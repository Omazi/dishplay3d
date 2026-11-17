"""The model as delivered to a menu: clean outline, light file.

The reconstruction is kept in full beside it (mesh.ply, model_vertexcolor.glb); what goes on a web page must
load in seconds on a phone and look finished: no teeth along the outline, a few megabytes.
"""
from __future__ import annotations

import numpy as np
import open3d as o3d
from scipy.spatial import cKDTree


def trim_ragged_border(T: np.ndarray, rounds: int = 3) -> np.ndarray:
    """Mask of the triangles kept after removing, `rounds` times, those whose three vertices all lie on the
    outline: teeth, spikes and tongues one cell wide have no vertex inside the surface and go; the body of
    the surface, whose border triangles each reach one vertex inside, stays."""
    keep = np.ones(len(T), bool)
    T = np.asarray(T, np.int64)
    if len(T) == 0:
        return keep
    n = int(T.max()) + 1
    for _ in range(rounds):
        idx = np.nonzero(keep)[0]
        if len(idx) == 0:
            break
        t = T[idx]
        e = np.sort(np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]]), axis=1)
        uniq, cnt = np.unique(e[:, 0] * n + e[:, 1], return_counts=True)
        outline = uniq[cnt == 1]
        on_outline = np.zeros(n, bool)
        on_outline[outline // n] = True
        on_outline[outline % n] = True
        loose = on_outline[t].all(1)
        if not loose.any():
            break
        keep[idx[loose]] = False
    return keep


def decimate_for_web(V, C, N, cls, T, max_triangles: int = 60000):
    """Fewer triangles, same shape (quadric decimation); colours and classes come from the nearest original vertex."""
    if len(T) <= max_triangles:
        return V, C, N, cls, T
    m = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(np.asarray(V, np.float64)), o3d.utility.Vector3iVector(np.asarray(T, np.int32)))
    m = m.simplify_quadric_decimation(int(max_triangles))
    m.remove_degenerate_triangles()
    m.remove_unreferenced_vertices()
    m.compute_vertex_normals()
    V2, T2 = np.asarray(m.vertices), np.asarray(m.triangles)
    used = np.unique(T)
    _, nn = cKDTree(np.asarray(V, np.float64)[used]).query(V2)
    src = used[nn]
    N2 = np.asarray(m.vertex_normals)
    flip = np.einsum("ij,ij->i", N2, np.asarray(N, np.float64)[src]) < 0      # keep the original orientation
    N2 = np.where(flip[:, None], -N2, N2)
    return V2.astype(np.float32), np.asarray(C)[src], N2.astype(np.float32), np.asarray(cls)[src], T2.astype(np.uint32)


def weld_corners(V, N, cls, T, tri_uv):
    """Indexed mesh from per-corner texture coordinates: a vertex is duplicated only where the atlas has a seam.
    Returns (vertices, normals, uv, provenance, triangles)."""
    T = np.asarray(T, np.int64)
    uv = np.asarray(tri_uv, np.float64).reshape(-1, 2)
    vid = T.reshape(-1)
    q = np.round(uv * 65535.0).astype(np.int64)
    key = np.stack([vid, q[:, 0], q[:, 1]], 1)
    uniq, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    src = vid[first]
    return (np.asarray(V, np.float32)[src], np.asarray(N, np.float32)[src], uv[first].astype(np.float32),
            np.asarray(cls, np.float32)[src], inv.reshape(-1, 3).astype(np.uint32))
