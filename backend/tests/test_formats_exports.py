import json

import numpy as np
import pytest

from reconstruction.completion import CompletionProposal, NoCompletion, check_measured_protected
from reconstruction.exports import glb_accessor, read_glb, write_glb, write_mesh_ply, write_points_ply
from reconstruction.preview_format import EnvelopeError, decode_frame, decode_geometry, encode_frame, encode_geometry


def test_geometry_roundtrip():
    rng = np.random.default_rng(0)
    pts = rng.normal(size=(101, 3)).astype(np.float32)
    rgbc = rng.integers(0, 255, (101, 4)).astype(np.uint8)
    V = rng.normal(size=(7, 3)).astype(np.float32)
    N = rng.normal(size=(7, 3)).astype(np.float32)
    N /= np.linalg.norm(N, axis=1, keepdims=True)
    T = np.array([[0, 1, 2], [2, 3, 4], [4, 5, 6]], np.uint32)
    blob = encode_geometry({"version": 3, "kind": "points+mesh"}, pts, rgbc, V, rgbc[:7], N, T)
    g = decode_geometry(blob)
    assert g["header"]["point_count"] == 101 and g["header"]["triangle_count"] == 3
    assert np.array_equal(g["points"], pts) and np.array_equal(g["tris"], T)
    assert np.allclose(g["normals"][:, :3] / 127.0, N, atol=0.01)
    with pytest.raises(ValueError):
        decode_geometry(blob + b"\0")


def test_frame_envelope_limits():
    meta = {"frame_id": 1}
    buf = encode_frame(meta, b"\xff\xd8\xffjpeg", b"\0" * 8, b"\1\1")
    m, img, d, c = decode_frame(buf)
    assert m == meta and img.startswith(b"\xff\xd8") and len(d) == 8 and c == b"\1\1"
    for bad in (buf[:-1], b"XXXX" + buf[4:], buf + b"x"):
        with pytest.raises(EnvelopeError):
            decode_frame(bad)


def test_glb_vertex_colors_and_texture(tmp_path):
    V = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32)
    T = np.array([[0, 1, 2]], np.uint32)
    C = np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255]], np.uint8)
    js = write_glb(tmp_path / "a.glb", V, T, normals=np.tile([0, 0, 1.0], (3, 1)), colors=C, provenance=np.array([0, 1, 0], np.float32))
    js2, b = read_glb(tmp_path / "a.glb")
    prim = js2["meshes"][0]["primitives"][0]
    assert set(prim["attributes"]) == {"POSITION", "NORMAL", "COLOR_0", "_PROVENANCE"}
    assert np.array_equal(glb_accessor(js2, b, prim["attributes"]["POSITION"]), V)
    assert np.array_equal(glb_accessor(js2, b, prim["attributes"]["COLOR_0"])[:, :3], C)
    tex = np.zeros((8, 8, 3), np.uint8)
    tex[:, :, 2] = 200
    write_glb(tmp_path / "b.glb", V, T, uv=np.array([[0, 0], [1, 0], [0, 1]], np.float32), texture_bgr=tex)
    js3, _ = read_glb(tmp_path / "b.glb")
    assert js3["images"][0]["mimeType"] == "image/png" and "baseColorTexture" in js3["materials"][0]["pbrMetallicRoughness"]
    # An independent reader (Open3D) loads the file.
    import open3d as o3d
    m = o3d.io.read_triangle_mesh(str(tmp_path / "a.glb"))
    assert len(m.triangles) == 1


def test_ply_files(tmp_path):
    xyz = np.zeros((3, 3), np.float32)
    write_points_ply(tmp_path / "p.ply", xyz, np.zeros((3, 3), np.uint8), np.array([0, 4, 0], np.uint8), np.array([2, 1, 3], np.uint16))
    import open3d as o3d
    assert len(o3d.io.read_point_cloud(str(tmp_path / "p.ply")).points) == 3
    write_mesh_ply(tmp_path / "m.ply", np.eye(3, dtype=np.float32), np.zeros((3, 3), np.uint8), np.eye(3, dtype=np.float32),
                   np.zeros(3, np.uint8), np.array([[0, 1, 2]], np.uint32))
    assert len(o3d.io.read_triangle_mesh(str(tmp_path / "m.ply")).triangles) == 1


def test_completion_disabled_and_protects_measured():
    V = np.random.default_rng(0).normal(size=(10, 3))
    cls = np.zeros(10, np.uint8)
    assert NoCompletion().propose(V, np.zeros((0, 3)), cls, (0.2, 0.1, 0.2)) is None
    moved = V.copy()
    moved[0] += 0.01
    p = CompletionProposal(moved, np.zeros((0, 3)), np.ones(10, bool), "test", "n/a")
    assert not check_measured_protected(V, cls, p)
    ok = CompletionProposal(np.vstack([V, [[5, 5, 5]]]), np.zeros((0, 3)), np.r_[np.zeros(10, bool), True], "test", "n/a")
    assert check_measured_protected(V, cls, ok)


def test_contract_schemas_accept_examples():
    import jsonschema
    from pathlib import Path
    from tests.helpers import box_json
    from tests.synthetic import SyntheticScene, frame_meta, orbit_poses
    root = Path(__file__).resolve().parents[2] / "contracts"
    schema = json.loads((root / "capture-session.schema.json").read_text())
    meta = frame_meta(SyntheticScene(), 0, orbit_poses(4)[0])
    meta["image"]["sha256"] = "0" * 64
    jsonschema.validate(meta, {**schema, "$ref": "#/$defs/frame"})
    jsonschema.validate({"schema": "dishplay.session/1", "box": box_json(), "device": {"platform": "ios", "model": "iPhone"}},
                        {**schema, "$ref": "#/$defs/session_create"})
    bad = dict(meta, T_world_from_cameraAR=[0] * 15)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, {**schema, "$ref": "#/$defs/frame"})
    preview = json.loads((root / "preview-message.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(preview)


def test_isolate_dish_removes_table_keeps_low_plate_floor():
    from reconstruction.mesh_preview import isolate_dish
    # table: 30 cm grid at y=0 ; plate: ring wall up to 2 cm at r=8..10 cm and a floor at y=3 mm inside
    g = np.linspace(-0.15, 0.15, 61)
    X, Z = np.meshgrid(g, g)
    r = np.hypot(X, Z)
    Y = np.where((r > 0.08) & (r < 0.10), 0.02, np.where(r <= 0.08, 0.003, 0.0))
    V = np.stack([X.ravel(), Y.ravel(), Z.ravel()], 1)
    idx = np.arange(61 * 61).reshape(61, 61)
    T = np.concatenate([np.stack([idx[:-1, :-1], idx[1:, :-1], idx[:-1, 1:]], -1).reshape(-1, 3),
                        np.stack([idx[1:, :-1], idx[1:, 1:], idx[:-1, 1:]], -1).reshape(-1, 3)])
    keep = isolate_dish(V, T)
    rc = np.hypot(V[T][:, :, 0].mean(1), V[T][:, :, 2].mean(1))
    assert keep[rc < 0.07].all(), "the low floor inside the plate is part of the dish"
    assert not keep[rc > 0.125].any(), "the table around the plate is removed"
