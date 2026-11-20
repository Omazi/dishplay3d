"""USDZ export (reconstruction/exports.py): the file an iPhone opens in AR Quick Look, with no app to install.

A .usdz is a zip archive that must not be compressed, whose files must each start on a 64-byte boundary, and
whose first file is the scene description. The scene is written as text (USDA), the texture as a JPEG.
"""
import re
import struct
import zipfile

import cv2
import numpy as np
import pytest

from reconstruction.exports import read_usdz, write_usdz


def quad():
    """Two triangles, 20 cm wide, standing 5 cm above the table, with a texture whose corners differ."""
    V = np.array([[-0.1, 0.05, -0.1], [0.1, 0.05, -0.1], [0.1, 0.05, 0.1], [-0.1, 0.05, 0.1]], np.float32)
    T = np.array([[0, 2, 1], [0, 3, 2]], np.uint32)
    N = np.tile([0.0, 1.0, 0.0], (4, 1)).astype(np.float32)
    uv = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.25, 0.9]], np.float32)   # glTF convention: v runs down
    tex = np.zeros((64, 64, 3), np.uint8)
    tex[:32] = (0, 0, 255)      # top half red (BGR)
    tex[32:] = (255, 0, 0)      # bottom half blue
    return V, T, N, uv, tex


def test_the_archive_is_stored_uncompressed_and_aligned_on_64_bytes(tmp_path):
    V, T, N, uv, tex = quad()
    p = tmp_path / "model.usdz"
    info = write_usdz(p, V, T, N, uv, tex)
    raw = p.read_bytes()
    with zipfile.ZipFile(p) as z:
        assert z.testzip() is None                                        # every checksum is right
        names = z.namelist()
        assert names[0] == "model.usda", "the scene description must be the first file of the archive"
        assert names == ["model.usda", "textures/dish.jpg"]
        for zi in z.infolist():
            assert zi.compress_type == zipfile.ZIP_STORED and zi.compress_size == zi.file_size
            sig, _, flags, method, _, _, _, _, _, n_name, n_extra = struct.unpack_from("<IHHHHHIIIHH", raw, zi.header_offset)
            assert sig == 0x04034B50 and method == 0 and flags == 0
            start = zi.header_offset + 30 + n_name + n_extra
            assert start % 64 == 0, f"{zi.filename} starts at byte {start}"
            assert raw[start:start + zi.file_size] == z.read(zi.filename)
    assert info["bytes"] == len(raw) and info["files"] == ["model.usda", "textures/dish.jpg"]


def test_the_scene_is_in_metres_y_up_and_the_mesh_comes_back(tmp_path):
    V, T, N, uv, tex = quad()
    p = tmp_path / "model.usdz"
    write_usdz(p, V, T, N, uv, tex)
    usda, files = read_usdz(p)
    assert usda.startswith("#usda 1.0")
    assert "metersPerUnit = 1" in usda and 'upAxis = "Y"' in usda
    prim = re.search(r'defaultPrim = "(\w+)"', usda).group(1)
    assert f'def Xform "{prim}"' in usda                                  # the default prim exists
    pts = np.array(re.findall(r"\(([-\d.e]+), ([-\d.e]+), ([-\d.e]+)\)", re.search(r"point3f\[\] points = \[(.*?)\]", usda, re.S).group(1)), float)
    assert pts.shape == (4, 3) and np.allclose(pts, V, atol=1e-5)
    idx = np.array(re.search(r"int\[\] faceVertexIndices = \[(.*?)\]", usda, re.S).group(1).split(","), int)
    cnt = np.array(re.search(r"int\[\] faceVertexCounts = \[(.*?)\]", usda, re.S).group(1).split(","), int)
    assert np.array_equal(idx, T.reshape(-1)) and np.array_equal(cnt, [3, 3])
    nrm = np.array(re.findall(r"\(([-\d.e]+), ([-\d.e]+), ([-\d.e]+)\)", re.search(r"normal3f\[\] normals = \[(.*?)\]", usda, re.S).group(1)), float)
    assert np.allclose(nrm, N, atol=1e-3)
    ext = np.array(re.findall(r"\(([-\d.e]+), ([-\d.e]+), ([-\d.e]+)\)", re.search(r"float3\[\] extent = \[(.*?)\]", usda, re.S).group(1)), float)
    assert np.allclose(ext, [V.min(0), V.max(0)], atol=1e-5)


def test_texture_coordinates_are_turned_the_usd_way_up(tmp_path):
    """glTF counts v from the top of the picture, USD from the bottom. Written as they are, the texture would be
    upside down on the phone while looking right in the browser."""
    V, T, N, uv, tex = quad()
    p = tmp_path / "model.usdz"
    write_usdz(p, V, T, N, uv, tex)
    usda, files = read_usdz(p)
    st = np.array(re.findall(r"\(([-\d.e]+), ([-\d.e]+)\)", re.search(r"texCoord2f\[\] primvars:st = \[(.*?)\]", usda, re.S).group(1)), float)
    assert np.allclose(st, np.stack([uv[:, 0], 1.0 - uv[:, 1]], 1), atol=1e-5)
    img = cv2.imdecode(np.frombuffer(files["textures/dish.jpg"], np.uint8), cv2.IMREAD_COLOR)
    assert img.shape == tex.shape
    assert img[5, 5, 2] > 200 and img[60, 5, 0] > 200                     # still red on top, blue below: not flipped


def test_the_texture_can_be_lossless(tmp_path):
    V, T, N, uv, tex = quad()
    p = tmp_path / "model.usdz"
    info = write_usdz(p, V, T, N, uv, tex, texture_jpeg_quality=None)
    usda, files = read_usdz(p)
    assert info["files"] == ["model.usda", "textures/dish.png"] and "asset inputs:file = @textures/dish.png@" in usda
    assert np.array_equal(cv2.imdecode(np.frombuffer(files["textures/dish.png"], np.uint8), cv2.IMREAD_COLOR), tex)


def test_the_material_reads_the_texture_through_the_mesh_coordinates(tmp_path):
    V, T, N, uv, tex = quad()
    p = tmp_path / "model.usdz"
    write_usdz(p, V, T, N, uv, tex)
    usda, _ = read_usdz(p)
    bound = re.search(r"rel material:binding = <([^>]+)>", usda).group(1)
    assert f'def Material "{bound.rsplit("/", 1)[1]}"' in usda
    assert 'uniform token info:id = "UsdPreviewSurface"' in usda and 'uniform token info:id = "UsdUVTexture"' in usda
    assert "asset inputs:file = @textures/dish.jpg@" in usda
    assert 'inputs:varname = "st"' in usda and "primvars:st" in usda
    # every connection points at something that is defined in the file
    for target in re.findall(r"\.connect = <([^>]+)>", usda):
        prim_path, attr = target.rsplit(".", 1)
        assert f'def Shader "{prim_path.rsplit("/", 1)[1]}"' in usda, target
        assert attr.split(":")[0] == "outputs"
    assert usda.count("{") == usda.count("}") and usda.count("(") == usda.count(")") and usda.count("[") == usda.count("]")


def test_a_real_size_mesh_stays_a_reasonable_file(tmp_path):
    rng = np.random.default_rng(0)
    n = 30000
    V = rng.uniform(-0.15, 0.15, size=(n, 3)).astype(np.float32)
    T = rng.integers(0, n, size=(60000, 3)).astype(np.uint32)
    N = rng.normal(size=(n, 3)).astype(np.float32)
    uv = rng.uniform(size=(n, 2)).astype(np.float32)
    tex = rng.integers(0, 255, size=(256, 256, 3)).astype(np.uint8)
    p = tmp_path / "big.usdz"
    info = write_usdz(p, V, T, N, uv, tex)
    assert info["bytes"] < 6_000_000
    usda, _ = read_usdz(p)
    assert usda.count("(") == usda.count(")")


def test_the_file_is_valid_usd_for_arkit(tmp_path):
    """Checked with Pixar's own library when it is installed (it is not a dependency of the calculator)."""
    pxr = pytest.importorskip("pxr")
    from pxr import Usd, UsdGeom, UsdShade, UsdUtils
    V, T, N, uv, tex = quad()
    p = tmp_path / "model.usdz"
    write_usdz(p, V, T, N, uv, tex)
    stage = Usd.Stage.Open(str(p))
    assert stage and stage.GetDefaultPrim().IsValid()
    assert UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.y and UsdGeom.GetStageMetersPerUnit(stage) == 1.0
    meshes = [x for x in stage.Traverse() if x.IsA(UsdGeom.Mesh)]
    assert len(meshes) == 1
    mesh = UsdGeom.Mesh(meshes[0])
    assert np.allclose(np.array(mesh.GetPointsAttr().Get()), V, atol=1e-5)
    assert list(mesh.GetFaceVertexIndicesAttr().Get()) == T.reshape(-1).tolist()
    mat, _ = UsdShade.MaterialBindingAPI(meshes[0]).ComputeBoundMaterial()
    assert mat and mat.ComputeSurfaceSource()[0]
    checker = UsdUtils.ComplianceChecker(arkit=True, skipARKitRootLayerCheck=True)
    checker.CheckCompliance(str(p))
    assert not checker.GetErrors() and not checker.GetFailedChecks(), (checker.GetErrors(), checker.GetFailedChecks())
