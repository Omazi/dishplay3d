"""Shape where stereo cannot measure: a learned single-image depth model fills the gaps.

Stereo needs texture. A white plate, a smooth cream or a glossy sauce have none, so the depth map of
a view has holes there. A monocular depth network (Depth Anything V2 Small, Apache-2.0) looks at one
photo and predicts the relative shape of everything in it, texture or not. Its output has no metric
scale, so for every view it is tied to the depths that stereo did measure in that same view:

  1. global fit    one affine map (in inverse depth, or in depth if that fits better) from the
                   network's values to the measured depths of the view;
  2. local fit     the remaining ratio measured/predicted is spread smoothly from the measured pixels,
                   so the filled surface meets the measured one without a step;
  3. fill          only pixels of the scan box without a measured depth receive a value.

Filled pixels are never called measured (they are fused as INTERPOLATED) and, like every depth, they
must still be confirmed by other views before they enter the model.

The network runs on the processor through onnxruntime; without the model file or the library the
engine works exactly as before.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import cv2
import numpy as np

MODEL_NAME = "depth_anything_v2_small.onnx"
MODEL_URL = "https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/main/onnx/model.onnx"
MODEL_SHA256 = "afb6a5c28f3b6bf1618c6e43f02073ef9dfdc70e937502d51603e57b0a1df10c"
_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
_STD = np.array([0.229, 0.224, 0.225], np.float32)


def model_path(session_dir: Path | None = None) -> Path:
    env = os.environ.get("DISHPLAY_MONO_MODEL")
    if env:
        return Path(env)
    root = Path(session_dir).parents[1] if session_dir is not None else Path.home() / "dishplay-scan-data"
    return root / "models" / MODEL_NAME


class MonoDepth:
    """Relative depth of one image. Values are only meaningful up to an affine map (see align_and_fill)."""

    def __init__(self, path: Path, short_side: int = 392, threads: int = 0):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        if threads > 0:
            opts.intra_op_num_threads = threads
        self.session = ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.short_side = short_side
        self.square_only = False
        self.seconds = 0.0
        self.calls = 0

    def _run(self, image_bgr: np.ndarray, nh: int, nw: int) -> np.ndarray:
        x = cv2.resize(image_bgr, (nw, nh), interpolation=cv2.INTER_CUBIC)[:, :, ::-1].astype(np.float32) / 255.0
        x = ((x - _MEAN) / _STD).transpose(2, 0, 1)[None]
        y = np.asarray(self.session.run(None, {self.input_name: np.ascontiguousarray(x)})[0], np.float32)
        return y.reshape(y.shape[-2], y.shape[-1])

    def predict(self, image_bgr: np.ndarray, frame_id: int | None = None) -> np.ndarray:
        h, w = image_bgr.shape[:2]
        t = time.perf_counter()
        y = None
        if not self.square_only:
            s = self.short_side / min(h, w)   # keep the picture's proportions; the network works on 14 px patches
            nh, nw = max(14, int(round(h * s / 14)) * 14), max(14, int(round(w * s / 14)) * 14)
            try:
                y = self._run(image_bgr, nh, nw)
            except Exception:
                self.square_only = True       # this export only accepts its training size
        if y is None:
            y = self._run(image_bgr, 518, 518)
        self.seconds += time.perf_counter() - t
        self.calls += 1
        return cv2.resize(y, (w, h), interpolation=cv2.INTER_LINEAR)


def load_default(session_dir: Path | None = None):
    """The model if it is installed on this machine, else None (with the reason)."""
    path = model_path(session_dir)
    if not path.exists():
        return None, f"model_not_found:{path}"
    try:
        return MonoDepth(path), "ok"
    except ImportError:
        return None, "onnxruntime_not_installed"
    except Exception as exc:   # a damaged file or an incompatible runtime must never stop a scan
        return None, f"load_failed:{exc!r}"


def _robust_line(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    keep = np.ones(len(x), bool)
    a = b = 0.0
    for _ in range(3):
        A = np.stack([x[keep], np.ones(keep.sum())], 1)
        (a, b), *_ = np.linalg.lstsq(A, y[keep], rcond=None)
        r = y - (a * x + b)
        mad = np.median(np.abs(r[keep] - np.median(r[keep]))) + 1e-12
        keep = np.abs(r - np.median(r[keep])) < 3.5 * 1.4826 * mad
        if keep.sum() < 50:
            break
    return float(a), float(b)


def align_and_fill(depth: np.ndarray, mono: np.ndarray, roi: np.ndarray, z_range: tuple[float, float],
                   min_anchors: int = 800, max_median_error: float = 0.04, max_local_correction: float = 0.10,
                   max_step: float = 0.02):
    """(depth with gaps filled inside roi, mask of filled pixels or None, info)."""
    info = {"status": "ok", "filled": 0}
    anchors = (depth > 0) & roi & np.isfinite(mono)
    n = int(anchors.sum())
    info["anchors"] = n
    if n < min_anchors:
        info["status"] = "few_measured_pixels"
        return depth, None, info
    x = mono[anchors].astype(np.float64)
    d = depth[anchors].astype(np.float64)
    if float(x.std()) < 1e-9:
        info["status"] = "flat_prediction"
        return depth, None, info
    best = None
    for mode in ("inverse", "direct"):   # the network predicts inverse depth; "direct" covers a model that does not
        y = 1.0 / d if mode == "inverse" else d
        a, b = _robust_line(x, y)
        p = a * x + b
        ok = p > 1e-6
        if ok.mean() < 0.95:
            continue
        z = np.where(ok, (1.0 / np.maximum(p, 1e-6)) if mode == "inverse" else p, d)
        err = float(np.median(np.abs(z - d) / d))
        if best is None or err < best[0]:
            best = (err, mode, a, b)
    if best is None or best[0] > max_median_error:
        info["status"] = "prediction_does_not_match_measurements"
        info["median_error"] = None if best is None else round(best[0], 4)
        return depth, None, info
    err, mode, a, b = best
    info.update(median_error=round(err, 4), mode=mode)
    p = a * mono.astype(np.float64) + b
    valid = np.isfinite(p) & (p > 1e-6)
    z_full = np.where(valid, (1.0 / np.maximum(p, 1e-6)) if mode == "inverse" else p, 0.0)
    # Local agreement: spread the measured/predicted ratio from the measured pixels (normalised blur).
    h, w = depth.shape
    sigma = max(6.0, w / 40.0)
    ratio = np.zeros((h, w), np.float32)
    ratio[anchors] = (d / np.maximum(z_full[anchors], 1e-6)).astype(np.float32)
    num = cv2.GaussianBlur(ratio, (0, 0), sigma)
    den = cv2.GaussianBlur(anchors.astype(np.float32), (0, 0), sigma)
    corr = np.where(den > 0.02, num / np.maximum(den, 1e-6), 1.0)
    corr = np.clip(corr, 1 - max_local_correction, 1 + max_local_correction)
    z_fill = (z_full * corr).astype(np.float32)
    # A prediction is smooth across the edge of an object where the real depth jumps: values on such a
    # step belong to neither side and are left empty.
    k = np.ones((3, 3), np.uint8)
    step = (cv2.dilate(z_fill, k) - cv2.erode(z_fill, k)) / np.maximum(z_fill, 1e-6)
    fill = roi & (depth <= 0) & valid & (z_fill > z_range[0]) & (z_fill < z_range[1]) & (step < max_step)
    out = depth.copy()
    out[fill] = z_fill[fill]
    info["filled"] = int(fill.sum())
    return out, fill, info


class OracleMono:
    """Stand-in for tests and benches: the true depth of a synthetic view, deliberately damaged the way
    a monocular network is wrong (unknown scale and offset, slow distortion across the image, noise).
    It measures what the fill step does with a prediction of that quality, not what the real network gives."""

    def __init__(self, true_depth_by_frame: dict[int, np.ndarray], seed: int = 0, distortion: float = 0.03, noise: float = 0.004):
        self.depths = true_depth_by_frame
        self.rng = np.random.default_rng(seed)
        self.distortion, self.noise = distortion, noise
        self.seconds, self.calls = 0.0, 0

    def predict(self, image_bgr: np.ndarray, frame_id: int | None = None) -> np.ndarray:
        z = self.depths[int(frame_id)].astype(np.float64)
        h, w = image_bgr.shape[:2]
        if z.shape != (h, w):
            z = cv2.resize(z, (w, h), interpolation=cv2.INTER_NEAREST)
        z = np.where(z > 0, z, np.nanmax(np.where(z > 0, z, np.nan)) * 1.5)   # background: far
        v, u = np.mgrid[0:h, 0:w]
        ph = self.rng.uniform(0, 2 * np.pi, 3)
        slow = np.sin(u / w * 3.1 + ph[0]) * np.cos(v / h * 2.3 + ph[1]) + 0.5 * np.sin((u + v) / (w + h) * 5.0 + ph[2])
        inv = (1.0 / z) * (1.0 + self.distortion * slow) + self.rng.normal(scale=self.noise, size=z.shape)
        self.calls += 1
        return (self.rng.uniform(4, 9) * inv + self.rng.uniform(-0.5, 0.5)).astype(np.float32)
