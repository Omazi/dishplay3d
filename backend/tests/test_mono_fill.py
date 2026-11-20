"""Gap filling from a single-image depth prediction (reconstruction/mono_depth.py).

The real network is not run here: OracleMono stands in for it (true depth of the synthetic view,
damaged by an unknown scale and offset, a slow distortion and noise). These tests check what the
fill step does with such a prediction; they say nothing about the quality of the real network.
"""
import numpy as np
import pytest

from reconstruction.mono_depth import MonoDepth, OracleMono, align_and_fill, load_default, model_path
from tests.realistic import BowlScene, handheld_poses


@pytest.fixture(scope="module")
def view():
    sc = BowlScene()
    _, true = handheld_poses(40, 0)
    img, z = sc.render(true[5])
    return img, z


def _stereo_like(z, rng, hole):
    d = z * (1 + rng.normal(scale=0.002, size=z.shape)).astype(np.float32)
    d[hole] = 0
    d[z <= 0] = 0
    return d.astype(np.float32)


def test_gaps_are_filled_close_to_the_true_surface(view):
    img, z = view
    rng = np.random.default_rng(1)
    h, w = z.shape
    hole = np.zeros_like(z, bool)
    hole[h // 2 - 70: h // 2 + 70, w // 2 - 90: w // 2 + 90] = True   # a large area without any measured depth
    d = _stereo_like(z, rng, hole)
    roi = z > 0
    mono = OracleMono({0: z}, seed=3).predict(img, 0)
    out, fill, info = align_and_fill(d, mono, roi, (0.05, 1.0))
    assert info["status"] == "ok" and info["mode"] == "inverse"
    assert fill is not None and fill[hole & roi].mean() > 0.8
    err = np.abs(out[fill] - z[fill])
    assert np.median(err) < 0.0025 and np.percentile(err, 90) < 0.006, (np.median(err), np.percentile(err, 90))
    # what was measured is never replaced
    assert np.array_equal(out[d > 0], d[d > 0])
    assert not fill[d > 0].any()


def test_a_prediction_that_contradicts_the_measurements_is_ignored(view):
    img, z = view
    rng = np.random.default_rng(2)
    hole = np.zeros_like(z, bool)
    hole[200:280, 250:400] = True
    d = _stereo_like(z, rng, hole)
    nonsense = rng.uniform(0, 10, z.shape).astype(np.float32)
    out, fill, info = align_and_fill(d, nonsense, z > 0, (0.05, 1.0))
    assert fill is None and info["status"] == "prediction_does_not_match_measurements"
    assert np.array_equal(out, d)


def test_too_few_measured_pixels_means_no_fill(view):
    img, z = view
    d = np.zeros_like(z)
    d[100:110, 100:110] = z[100:110, 100:110]
    mono = OracleMono({0: z}).predict(img, 0)
    out, fill, info = align_and_fill(d, mono, z > 0, (0.05, 1.0))
    assert fill is None and info["status"] == "few_measured_pixels"


def test_nothing_is_invented_on_a_depth_step(view):
    img, z = view
    rng = np.random.default_rng(4)
    z2 = z.copy()
    z2[:, 320:] *= 1.25   # a 25 % jump in depth down the middle of the image
    hole = np.zeros_like(z, bool)
    hole[150:330, 300:340] = True
    d = _stereo_like(z2, rng, hole)
    import cv2
    smooth = cv2.GaussianBlur(z2, (0, 0), 3)   # a network blurs the edge
    mono = OracleMono({0: smooth}, seed=5, distortion=0.0, noise=0.0).predict(img, 0)
    out, fill, info = align_and_fill(d, mono, z > 0, (0.05, 2.0))
    assert info["status"] == "ok"
    band = np.zeros_like(hole)
    band[150:330, 318:322] = True
    assert fill[band].mean() < 0.2    # the blurred step itself stays empty
    far = hole & ~np.pad(band, 0) & (np.abs(np.arange(z.shape[1])[None] - 320) > 12)
    assert fill[far].mean() > 0.8     # away from the step the gap is filled


def test_engine_without_a_model_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("DISHPLAY_MONO_MODEL", str(tmp_path / "absent.onnx"))
    assert model_path() == tmp_path / "absent.onnx"
    m, why = load_default()
    assert m is None and why.startswith("model_not_found")


def test_real_model_if_installed(view):
    """Runs only on a machine that has onnxruntime and the model file (never in this repository's CI by default)."""
    pytest.importorskip("onnxruntime")
    if not model_path().exists():
        pytest.skip("depth model not installed (tools/get_models.py)")
    img, z = view
    pred = MonoDepth(model_path()).predict(img)
    assert pred.shape == z.shape and np.isfinite(pred).all() and pred.std() > 0



def test_a_plain_bowl_gets_its_walls_and_they_are_not_called_measured(tmp_path):
    """End to end in the engine, with the simulated prediction: the nearly uniform walls of the bowl,
    which stereo leaves largely empty, are filled; the added surface is accurate and labelled interpolated."""
    import hashlib
    import json

    import cv2
    from scipy.spatial import cKDTree

    from reconstruction.engine import Box, EngineConfig, SessionEngine
    from reconstruction.preview_format import decode_geometry
    from tests.helpers import box_json
    from tests.realistic import BOX
    from tests.synthetic import frame_meta

    sc = BowlScene()
    _, poses = handheld_poses(48, 0)
    bj = box_json(size=BOX)
    (tmp_path / "frames").mkdir()
    truth = {}
    for i, T in enumerate(poses):
        img, truth[i] = sc.render(T)
        jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()
        meta = frame_meta(sc, i, T, session_id="bowl", timestamp=i * 0.3)
        meta["image"]["sha256"] = hashlib.sha256(jpg).hexdigest()
        (tmp_path / "frames" / f"{i:06d}.jpg").write_bytes(jpg)
        (tmp_path / "frames" / f"{i:06d}.json").write_text(json.dumps(meta))
    vis, mat = sc.visible_samples(poses[::3], n=60000)
    wall = (mat == 1) & (vis[:, 1] <= 0.047) & (vis[:, 1] > 0.008)

    def scan(mono):
        eng = SessionEngine(tmp_path, Box.from_json(bj), EngineConfig(hide_table=False))
        eng.mono = mono
        for mp in sorted((tmp_path / "frames").glob("*.json")):
            eng.add_frame(json.loads(mp.read_text()), mp.with_suffix(".jpg"))
            eng.process_pending(live=False)
        eng.flush()
        g = decode_geometry(eng.snapshot(force_mesh=True)[1])
        V = g["verts"].astype(np.float64)
        covered = cKDTree(V).query(vis[wall])[0] < 0.004
        return eng, V, g["vert_rgbc"][:, 3], float(covered.mean())

    _, _, _, c0 = scan(None)
    eng, V, cls, c1 = scan(OracleMono(truth, seed=7))
    st = eng.mono_report()
    assert st["enabled"] and st["views_filled"] > 20 and st["errors"] == 0
    assert 0.1 < st["kept_share"] < 1.0           # other views had their say on what was predicted
    assert (1 - c1) < 0.5 * (1 - c0) and c1 > 0.95, (c0, c1)   # the missing part of the walls is at least halved
    d = sc.scene.compute_distance(__import__("open3d").core.Tensor(V.astype(np.float32))).numpy()
    interp = cls == 1
    assert interp.mean() > 0.2                    # filled from a prediction: interpolated, never "measured"
    assert np.percentile(d[interp], 90) < 0.005, np.percentile(d[interp], 90)
    assert np.percentile(d[cls == 0], 90) < 0.005
    # The same model on a thread of its own, working ahead of the engine: the walls are filled just as well.
    from reconstruction.mono_depth import AsyncMono
    ahead = AsyncMono(OracleMono(truth, seed=7))
    try:
        eng2, V2, cls2, c2 = scan(ahead)
        st2 = eng2.mono_report()
    finally:
        ahead.close()
    assert st2["errors"] == 0 and st2["views_filled"] >= 0.9 * st["views_filled"], (st2, st)
    assert c2 > c1 - 0.03, (c1, c2)
    assert st2["parallel"]["computed"] >= st2["views_filled"] and not st2["parallel"]["stepped_back"]
    assert "not_ready" not in st2["skipped"], "finishing never goes without a prediction"
