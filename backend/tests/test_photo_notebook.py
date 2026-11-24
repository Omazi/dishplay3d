"""The "photo express" trial (one photograph -> a 3D model by generative AI, on Colab): what can be checked
without the model. The model itself cannot run in the automated checks, and scikit-image / PyTorch are not
dependencies of the calculator: the surface-extraction check below is skipped here and runs on Colab instead
(`photo_express.py --self-test`, second cell of the notebook's step 3)."""
import json
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import make_photo_notebook  # noqa: E402
import photo_express  # noqa: E402


def cells():
    return json.loads((ROOT / "colab" / "photo_express.ipynb").read_text())["cells"]


def test_the_notebook_is_the_generated_one_and_carries_the_program():
    text = json.dumps(make_photo_notebook.build(), ensure_ascii=False, indent=1) + "\n"
    assert (ROOT / "colab" / "photo_express.ipynb").read_text() == text, "run python tools/make_photo_notebook.py"
    written = ["".join(c["source"]) for c in cells() if "".join(c["source"]).startswith("%%writefile /content/photo_express.py")]
    assert len(written) == 1
    assert written[0].split("\n", 1)[1].rstrip("\n") == (ROOT / "tools" / "photo_express.py").read_text().rstrip("\n")


def test_nothing_outside_the_licence_rule_is_installed_or_asked_for():
    """TripoSR's own requirements bring an MPL package, a GPL build of FFmpeg and a web interface; and recent
    versions of the background remover default to a non-commercial model. None of it may come back. (This
    looks at what the notebook asks for, not at everything pip then resolves.)"""
    code = ["".join(c["source"]) for c in cells() if c["cell_type"] == "code" and not "".join(c["source"]).startswith("%%writefile")]
    commands = "\n".join(line for c in code for line in c.splitlines() if line.lstrip().startswith("!"))
    for word in ("requirements.txt", "torchmcubes", "ffmpeg", "gradio", "nvdiffrast", "xatlas", "moderngl"):
        assert word not in commands, word
    assert photo_express.TRIPOSR_COMMIT in commands                       # the model's code at a fixed commit
    source = (ROOT / "tools" / "photo_express.py").read_text()
    assert "rembg.new_session(CUTOUT_MODEL)" in source and photo_express.CUTOUT_MODEL == "u2net"
    assert "rembg.new_session()" not in source                            # the default can be BRIA RMBG: not permissive
    assert len(photo_express.WEIGHTS_REVISION) == 40                      # the weights at a fixed revision
    assert "weights_only=True" in source and "from_pretrained(" not in source.split('"""', 2)[2].replace("TSR.from_pretrained:", "")


def test_a_failed_step_stops_the_notebook_and_old_results_cannot_be_shown():
    code = ["".join(c["source"]) for c in cells() if c["cell_type"] == "code"]
    run = next(c for c in code if "--triposr" in c and not c.startswith("%%writefile"))
    assert run.index("rm -rf /content/resultat") < run.index("photo_express.py") < run.index("assert _exit_code == 0")
    check = next(c for c in code if "--self-test" in c and not c.startswith("%%writefile"))
    assert "assert _exit_code == 0" in check
    first = next(c for c in code if "nvidia-smi" in c)
    assert 'shutil.which("nvidia-smi")' in first                          # a machine without the program must not fail here


def test_the_model_file_loads_under_the_old_and_the_new_parameter_names():
    """transformers 5.9 renamed the image encoder's parameters; TripoSR's file has the older names."""
    e = photo_express.ENCODER
    old = {e + "embeddings.cls_token": 0, e + "encoder.layer.11.attention.attention.query.weight": 1,
           e + "encoder.layer.11.attention.attention.key.bias": 2, e + "encoder.layer.11.attention.attention.value.weight": 3,
           e + "encoder.layer.11.attention.output.dense.weight": 4, e + "encoder.layer.11.intermediate.dense.bias": 5,
           e + "encoder.layer.11.output.dense.weight": 6, e + "encoder.layer.11.layernorm_before.weight": 7,
           e + "pooler.dense.weight": 8, "decoder.layers.0.output.dense.weight": 9}
    new = {e + "embeddings.cls_token", e + "layers.11.attention.q_proj.weight", e + "layers.11.attention.k_proj.bias",
           e + "layers.11.attention.v_proj.weight", e + "layers.11.attention.o_proj.weight", e + "layers.11.mlp.fc1.bias",
           e + "layers.11.mlp.fc2.weight", e + "layers.11.layernorm_before.weight", e + "pooler.dense.weight",
           "decoder.layers.0.output.dense.weight"}                         # outside the encoder: never renamed
    renamed = photo_express.names_for_installed_encoder(old, new)
    assert set(renamed) == new and renamed[e + "layers.11.mlp.fc2.weight"] == 6 and renamed[e + "layers.11.attention.o_proj.weight"] == 4
    assert photo_express.names_for_installed_encoder(old, set(old)) is old   # an older transformers: nothing to do


def box_points(n=40000):
    """Points on the six sides of a box in TripoSR's frame (z up, the photographed side towards +x): 1.0 wide
    along x, 0.8 along y, 0.3 high. The +x side is red, the top green, everything else blue."""
    g = np.random.default_rng(1)
    half = np.array([0.5, 0.4, 0.15])
    side = g.integers(0, 6, n)
    P = g.uniform(-1, 1, (n, 3)) * half
    axis, sign = side // 2, np.where(side % 2 == 0, 1.0, -1.0)
    P[np.arange(n), axis] = sign * half[axis]
    normals = np.zeros((n, 3))
    normals[np.arange(n), axis] = sign
    colours = np.tile(np.array([[30, 30, 220]], np.uint8), (n, 1))
    colours[side == 0] = (220, 30, 30)        # +x: the side the photograph shows
    colours[side == 4] = (30, 220, 30)        # +z: the top
    return P, normals, colours


def test_the_first_small_picture_is_the_side_of_the_photograph_and_the_last_is_the_top():
    P, normals, colours = box_points()
    V, N = photo_express.upright(P), photo_express.upright(normals)
    assert np.allclose(V.max(0) - V.min(0), [0.8, 0.3, 1.0])              # GLB frame: y is up, the front faces +z
    size = 120
    sheet = photo_express.views_sheet(V, colours, N, size=size)
    assert sheet.shape == (size, 5 * size, 3)
    tile = lambda k: sheet[:, size * k:size * (k + 1)].reshape(-1, 3).astype(int)   # noqa: E731
    drawn = lambda t: t[(t != 21).any(1)]                                          # noqa: E731
    share = lambda t, ch: float((t.argmax(1) == ch).mean())                        # noqa: E731
    photo, back, top = drawn(tile(0)), drawn(tile(2)), drawn(tile(4))
    assert min(len(photo), len(back), len(top)) > 1500                    # each picture is filled, no gaps
    # Seen from 20 degrees above, the front side and the top share the picture; the other sides are hidden.
    assert share(photo, 0) > 0.35 and share(photo, 2) < 0.01              # the red side, and nothing of the blue ones
    assert share(back, 0) < 0.01 and share(back, 2) > 0.35                # from behind: a blue side, never the red one
    assert share(top, 1) > 0.99                                           # from above: the top only
    red_rows = np.where((sheet[:, 4 * size:] == (220, 30, 30)).all(-1))[0]
    assert len(red_rows) == 0                                             # (the side walls are not seen from above)
    named = photo_express.name_the_views(sheet, size)
    assert named.shape == sheet.shape and (named != sheet).any()          # the five names are written on it
    assert photo_express.VIEW_NAMES[0] == "photo" and photo_express.VIEW_NAMES[2] == "dos"


def read_glb(path):
    data = Path(path).read_bytes()
    magic, version, total = struct.unpack_from("<4sII", data, 0)
    assert magic == b"glTF" and version == 2 and total == len(data)
    n, kind = struct.unpack_from("<I4s", data, 12)
    assert kind == b"JSON" and n % 4 == 0
    doc = json.loads(data[20:20 + n])
    m, kind = struct.unpack_from("<I4s", data, 20 + n)
    assert kind == b"BIN\0" and m % 4 == 0 and 28 + n + m == len(data)
    return doc, data[28 + n:]


def test_the_model_file_carries_its_colours_as_viewers_expect_them(tmp_path):
    V = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], np.float64)
    F = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
    N = np.array([[-1, -1, -1], [2, 0, 0], [0, 0.5, 0], [0, 0, 0]], np.float64)      # not unit length; one is null
    C = np.array([[255, 255, 255], [128, 128, 128], [0, 0, 0], [220, 30, 30]], np.uint8)
    photo_express.write_glb(tmp_path / "plat.glb", V, F, N, C)
    doc, blob = read_glb(tmp_path / "plat.glb")
    prim = doc["meshes"][0]["primitives"][0]
    assert set(prim["attributes"]) == {"POSITION", "NORMAL", "COLOR_0"} and prim["mode"] == 4
    material = doc["materials"][prim["material"]]
    assert material["pbrMetallicRoughness"]["metallicFactor"] == 0        # no material = a metallic default that washes colours out
    assert material["pbrMetallicRoughness"]["roughnessFactor"] == 1 and material["doubleSided"] is True
    acc, views = doc["accessors"], doc["bufferViews"]
    assert all(v["byteOffset"] % 4 == 0 for v in views) and doc["buffers"][0]["byteLength"] == len(blob)

    def array(k, dtype, width):
        a, v = acc[k], views[acc[k]["bufferView"]]
        return np.frombuffer(blob, dtype, a["count"] * (width if a["type"] != "SCALAR" else 1), v["byteOffset"]).reshape(-1, width)

    assert np.allclose(array(prim["attributes"]["POSITION"], np.float32, 3), V)
    assert acc[prim["attributes"]["POSITION"]]["min"] == [0, 0, 0] and acc[prim["attributes"]["POSITION"]]["max"] == [1, 1, 1]
    normals = array(prim["attributes"]["NORMAL"], np.float32, 3)
    assert np.allclose(np.linalg.norm(normals, axis=1), 1, atol=1e-6)     # unit length, even where none was given
    colour = acc[prim["attributes"]["COLOR_0"]]
    assert colour["componentType"] == 5123 and colour["normalized"] is True and colour["type"] == "VEC4"
    stored = array(prim["attributes"]["COLOR_0"], np.uint16, 4) / 65535.0
    assert np.allclose(stored[0], [1, 1, 1, 1]) and np.allclose(stored[2], [0, 0, 0, 1])
    assert np.allclose(stored[1, :3], 0.2158, atol=0.001)                 # mid grey of a picture (128) is 0.216 in linear light
    assert np.array_equal(array(prim["indices"], np.uint32, 1).reshape(-1, 3), F)
    assert acc[prim["indices"]]["componentType"] == 5125 and acc[prim["indices"]]["count"] == 12


def test_an_iphone_photograph_is_turned_upright_and_reduced(tmp_path):
    from PIL import Image
    im = Image.new("RGB", (3000, 2000), (10, 200, 10))
    exif = im.getexif()
    exif[0x0112] = 6                                                      # "rotate 90 degrees to display"
    im.save(tmp_path / "plat.jpg", exif=exif)
    out = photo_express.open_photo(tmp_path / "plat.jpg")
    assert out.mode == "RGB" and out.size == (1067, 1600)                 # upright (taller than wide), longest side 1600
    (tmp_path / "pas-une-photo.jpg").write_bytes(b"not a picture")
    with pytest.raises(SystemExit) as err:
        photo_express.open_photo(tmp_path / "pas-une-photo.jpg")
    assert "Photo illisible" in str(err.value)


def test_the_surface_extraction_replacement_keeps_the_axes_and_faces_outwards():
    pytest.importorskip("skimage")                                        # present on Colab; not a dependency of the calculator
    vol = np.zeros((40, 48, 56), np.float32)
    vol[5:15, 10:30, 20:50] = 1.0
    v, f = photo_express.surface_in_index_order(vol, 0.5)
    assert np.allclose(v.min(0), [4.5, 9.5, 19.5], atol=0.01) and np.allclose(v.max(0), [14.5, 29.5, 49.5], atol=0.01)
    assert f.max() < len(v) and 5000 < photo_express.signed_volume(v, f) < 6100
    assert len(photo_express.surface_in_index_order(np.zeros((8, 8, 8), np.float32), 0.5)[1]) == 0
