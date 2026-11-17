"""The model as delivered to a menu (reconstruction/delivery.py): clean outline, light file, sharp texture."""
import cv2
import numpy as np
import open3d as o3d

from reconstruction.delivery import decimate_for_web, trim_ragged_border, weld_corners
from reconstruction.exports import glb_accessor, read_glb, write_glb


def grid_mesh(nx=30, nz=30, cell=0.002):
    xs, zs = np.meshgrid(np.arange(nx + 1) * cell, np.arange(nz + 1) * cell, indexing="ij")
    V = np.stack([xs.ravel(), np.zeros(xs.size), zs.ravel()], 1)
    idx = lambda i, j: i * (nz + 1) + j
    T = []
    for i in range(nx):
        for j in range(nz):
            T += [[idx(i, j), idx(i + 1, j), idx(i, j + 1)], [idx(i + 1, j), idx(i + 1, j + 1), idx(i, j + 1)]]
    return V, np.array(T)


def test_tongues_and_teeth_on_the_outline_are_trimmed_and_the_body_is_kept():
    V, T = grid_mesh()
    n_body = len(T)
    # a thin tongue, one triangle wide, sticking 2 cm out of the edge
    base = len(V)
    tongue_v = np.array([[0.060 + 0.002 * k, 0.0, 0.030 + (0.002 if k % 2 else 0.0)] for k in range(1, 11)])
    V2 = np.concatenate([V, tongue_v])
    a, b = 30 * 31 + 15, 30 * 31 + 16                      # two vertices of the edge x = 0.06
    strip = [a, b] + list(range(base, base + 10))
    T2 = np.concatenate([T, [[strip[k], strip[k + 1], strip[k + 2]] for k in range(10)]])
    keep = trim_ragged_border(T2, rounds=4)
    assert keep[n_body:].sum() <= 2, "the tongue is gone"
    assert keep[:n_body].mean() > 0.97, "the body keeps its surface (only corner teeth go)"
    assert trim_ragged_border(T, rounds=0).all()


def sphere(n=40):
    m = o3d.geometry.TriangleMesh.create_sphere(radius=0.05, resolution=n)
    m.compute_vertex_normals()
    V, T, N = np.asarray(m.vertices), np.asarray(m.triangles), np.asarray(m.vertex_normals)
    C = np.where(V[:, [0]] > 0, [[200, 40, 40]], [[40, 40, 200]]).astype(np.uint8)
    cls = (V[:, 1] > 0).astype(np.uint8)
    return V.astype(np.float32), C, N.astype(np.float32), cls, T.astype(np.uint32)


def test_decimation_keeps_the_shape_and_carries_colours_and_classes():
    V, C, N, cls, T = sphere()
    V2, C2, N2, cls2, T2 = decimate_for_web(V, C, N, cls, T, max_triangles=1500)
    assert len(T2) <= 1500 < len(T)
    assert np.abs(np.linalg.norm(V2, axis=1) - 0.05).max() < 0.001          # still the same sphere, within 1 mm
    assert len(C2) == len(N2) == len(cls2) == len(V2) and T2.max() < len(V2)
    red = V2[:, 0] > 0.01
    assert (C2[red, 0] > 150).mean() > 0.95 and set(np.unique(cls2)) <= {0, 1}
    same = decimate_for_web(V, C, N, cls, T, max_triangles=10 ** 6)
    assert len(same[4]) == len(T)                                             # already light: untouched


def test_corners_are_welded_into_a_compact_indexed_mesh():
    V, C, N, cls, T = sphere(12)
    uv_of_vertex = np.stack([V[:, 0] * 5 + 0.5, V[:, 2] * 5 + 0.5], 1)        # one uv per vertex: no seam
    tri_uv = uv_of_vertex[T]
    Vw, Nw, UVw, Pw, Tw = weld_corners(V, N, cls, T, tri_uv)
    assert len(Vw) == len(np.unique(T)) and Tw.shape == T.shape
    assert np.allclose(Vw[Tw], V[T]) and np.allclose(UVw[Tw], tri_uv)
    # a seam (two uvs for the same vertex) duplicates that vertex only
    tri_uv2 = tri_uv.copy()
    tri_uv2[0, 0] += 0.3
    Vw2, _, UVw2, _, Tw2 = weld_corners(V, N, cls, T, tri_uv2)
    assert len(Vw2) == len(Vw) + 1 and np.allclose(UVw2[Tw2], tri_uv2)


def test_texture_can_be_stored_as_jpeg_and_the_file_is_much_lighter(tmp_path):
    V, C, N, cls, T = sphere(12)
    rng = np.random.default_rng(0)
    tex = cv2.GaussianBlur(rng.integers(0, 255, (1024, 1024, 3), dtype=np.uint8), (0, 0), 2)
    uv = np.stack([V[:, 0] * 5 + 0.5, V[:, 2] * 5 + 0.5], 1)
    write_glb(tmp_path / "png.glb", V, T, N, uv=uv, texture_bgr=tex)
    js = write_glb(tmp_path / "jpg.glb", V, T, N, uv=uv, texture_bgr=tex, texture_jpeg_quality=88)
    assert js["images"][0]["mimeType"] == "image/jpeg"
    assert (tmp_path / "jpg.glb").stat().st_size < 0.5 * (tmp_path / "png.glb").stat().st_size
    j, b = read_glb(tmp_path / "jpg.glb")
    v = j["bufferViews"][j["images"][0]["bufferView"]]
    img = cv2.imdecode(np.frombuffer(b[v["byteOffset"]: v["byteOffset"] + v["byteLength"]], np.uint8), 1)
    assert img.shape == tex.shape and np.abs(img.astype(int) - tex).mean() < 6
