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


def test_splat_dataset_cameras_match_the_engine(tmp_path):
    """The Nerfstudio-format export, read back with the OpenGL convention, sees the box where the engine does."""
    import json
    import sys
    from pathlib import Path

    import cv2
    import numpy as np

    from reconstruction.coordinates import box_corners, invert_rigid, mat4_from_rowmajor, object_from_camera_cv
    from tests.helpers import BOX_SIZE, write_session
    from reconstruction.splat_export import export

    sdir = write_session(tmp_path, n=6)
    out = tmp_path / "ds"
    info = export(sdir, out, max_width=320)
    assert info["views"] == 6 and info["width"] == 320
    scene = json.loads((out / "transforms.json").read_text())
    C = box_corners(BOX_SIZE)
    for fr in scene["frames"]:
        meta = json.loads((sdir / "frames" / (Path(fr["file_path"]).stem + ".json")).read_text())
        # engine convention (OpenCV camera) at the original size
        T = invert_rigid(object_from_camera_cv(np.eye(4), mat4_from_rowmajor(meta["T_world_from_cameraAR"])))
        pc = C @ T[:3, :3].T + T[:3, 3]
        k = meta["intrinsics"]
        s = fr["w"] / k["width"]
        u_cv = (pc[:, 0] / pc[:, 2] * k["fx"] + k["cx"] + 0.5) * s
        v_cv = (pc[:, 1] / pc[:, 2] * k["fy"] + k["cy"] + 0.5) * s
        # exported convention: camera-to-world, camera looks along -z, +y up, pixel corners at integers
        w2c = np.linalg.inv(np.array(fr["transform_matrix"]))
        q = C @ w2c[:3, :3].T + w2c[:3, 3]
        u_gl = fr["fl_x"] * q[:, 0] / -q[:, 2] + fr["cx"]
        v_gl = fr["fl_y"] * -q[:, 1] / -q[:, 2] + fr["cy"]
        assert np.abs(u_gl - u_cv).max() < 0.05 and np.abs(v_gl - v_cv).max() < 0.05
        mask = cv2.imread(str(out / fr["file_path"].replace("images", "masks").replace(".jpg", ".png")), 0)
        assert mask is not None and mask.shape == (fr["h"], fr["w"]) and 0 < (mask > 0).mean() < 1
        inside = (u_gl >= 0) & (u_gl < fr["w"]) & (v_gl >= 0) & (v_gl < fr["h"])
        assert (mask[v_gl[inside].astype(int), u_gl[inside].astype(int)] > 0).all()


def test_colab_notebook_embeds_the_current_trainer():
    """The notebook must carry exactly backend/reconstruction/splat_train.py (it cannot fetch it from the private repository)."""
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    nb = json.loads((root / "colab" / "essai_neuronal.ipynb").read_text())
    cell = next("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code" and "".join(c["source"]).startswith("%%writefile"))
    assert cell.split("\n", 1)[1].rstrip("\n") == (root / "backend" / "reconstruction" / "splat_train.py").read_text().rstrip("\n")
