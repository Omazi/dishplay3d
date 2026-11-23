"""The "photo express" trial (one photograph -> a 3D model by generative AI, on Colab): what can be checked
without the model. The model itself cannot run in the automated checks."""
import json
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
    """TripoSR's own requirements bring an MPL package, a GPL build of FFmpeg and a web interface; and the
    background remover's default model is non-commercial. None of it may come back."""
    commands = "\n".join(line for c in cells() if c["cell_type"] == "code" and not "".join(c["source"]).startswith("%%writefile")
                         for line in c["source"] if line.lstrip().startswith("!"))
    for word in ("requirements.txt", "torchmcubes", "ffmpeg", "gradio", "nvdiffrast", "xatlas", "moderngl"):
        assert word not in commands, word
    assert photo_express.TRIPOSR_COMMIT in commands                       # the model's code at a fixed commit
    source = (ROOT / "tools" / "photo_express.py").read_text()
    assert "rembg.new_session(CUTOUT_MODEL)" in source and photo_express.CUTOUT_MODEL == "u2net"
    assert "rembg.new_session()" not in source                            # the default is BRIA RMBG: not permissive
    assert len(photo_express.WEIGHTS_REVISION) == 40                      # the weights at a fixed revision
    assert "weights_only=True" in source                                  # weights checked to be plain tensors first


def test_the_small_pictures_show_the_side_that_faces_the_viewer():
    """A ball that is red on the side of +z and blue on the side of -z, with green added on its upper half.
    The first and third pictures look at opposite sides (from 20 degrees above, so a thin edge of the other
    side shows past the top); the last one looks from above and must show the upper half only: no colour of
    a hidden side leaks through."""
    g = np.random.default_rng(0)
    n = g.normal(size=(20000, 3))
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    colours = np.where(n[:, 2:3] > 0, [[220, 0, 30]], [[30, 0, 220]]).astype(np.uint8)
    colours[:, 1] = np.where(n[:, 1] > 0, 200, 0)
    sheet = photo_express.views_sheet(n * 0.4, colours, n, size=120)
    assert sheet.shape == (120, 600, 3)
    tile = lambda k: sheet[:, 120 * k:120 * (k + 1)].reshape(-1, 3).astype(int)     # noqa: E731
    drawn = lambda t: t[(t != 21).any(1)]                                          # noqa: E731
    first, third, top = drawn(tile(0)), drawn(tile(2)), drawn(tile(4))
    assert min(len(first), len(third), len(top)) > 3000                   # the ball fills each picture, no gaps
    red = lambda t: float((t[:, 0] > t[:, 2]).mean())                     # noqa: E731
    assert sorted([red(first) > 0.9, red(third) > 0.9]) == [False, True]  # one side red...
    assert min(red(first), red(third)) < 0.1                              # ...the opposite side blue
    assert float((top[:, 1] > 100).mean()) > 0.99                         # from above: the upper half, nothing else


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


def test_the_surface_extraction_replacement_keeps_the_axes():
    pytest.importorskip("skimage")                                        # present on Colab; not a dependency of the calculator
    vol = np.zeros((40, 48, 56), np.float32)
    vol[5:15, 10:30, 20:50] = 1.0
    v, f = photo_express.surface_in_index_order(vol, 0.5)
    assert np.allclose(v.min(0), [4.5, 9.5, 19.5], atol=0.01) and np.allclose(v.max(0), [14.5, 29.5, 49.5], atol=0.01)
    assert f.max() < len(v)
