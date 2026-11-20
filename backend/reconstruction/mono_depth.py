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


class AsyncMono:
    """The depth model on a thread of its own, working ahead of the engine and at the same time as stereo.

    The engine asks for the prediction of a picture as soon as it knows it will need it (`request`), goes on with
    stereo, and collects the prediction when it gets there (`predict`). Both computations release the Python
    interpreter while they run, so on a multi-core PC they really run side by side.

    Finishing (live=False) is in no hurry: `predict` waits for the answer, in the order asked.

    While scanning (live=True) nothing may slow the scan down:
      * `predict` waits at most `live_patience_s`; a prediction that is not ready is not used (returns None) and
        the view keeps what stereo measured, exactly as without the model;
      * at most `ahead` requests wait their turn; older ones are dropped, the newest pictures first;
      * after `give_up_after` answers of which fewer than `min_on_time` came in time, the computer cannot keep
        up: the model steps back and is no longer asked during this scan. Finishing still uses it for every view.
    """

    def __init__(self, model, ahead: int = 3, live_patience_s: float = 0.12, give_up_after: int = 12,
                 min_on_time: float = 0.3, keep: int = 8):
        import threading
        from collections import OrderedDict, deque
        self.model = model
        self.ahead, self.live_patience_s = int(ahead), float(live_patience_s)
        self.give_up_after, self.min_on_time, self.keep = int(give_up_after), float(min_on_time), int(keep)
        self._cv = threading.Condition()
        self._queue: deque = deque()            # (key, image, live); key = (frame id, height, width)
        self._busy: tuple | None = None         # key being computed
        self._ready: OrderedDict = OrderedDict()   # key -> prediction, or the exception the model raised
        self._closed = False
        self._st = {"requested": 0, "computed": 0, "on_time": 0, "late": 0, "dropped": 0, "errors": 0}
        self._recent: deque = deque(maxlen=self.give_up_after)   # live answers: True = in time
        self.stepped_back = False
        self._thread = threading.Thread(target=self._work, name="mono-depth", daemon=True)
        self._thread.start()

    # the engine's report reads these on whatever it is given as a model
    @property
    def seconds(self) -> float:
        return float(getattr(self.model, "seconds", 0.0))

    @property
    def calls(self) -> int:
        return int(getattr(self.model, "calls", 0))

    @staticmethod
    def _key(frame_id: int, image_bgr: np.ndarray) -> tuple:
        """A picture is known by its frame and its size: the scan works on small pictures and the finishing step
        on large ones of the same frames, and a prediction made for one must never be served for the other."""
        return (int(frame_id), int(image_bgr.shape[0]), int(image_bgr.shape[1]))

    def _known(self, key) -> bool:
        return key in self._ready or key == self._busy or any(q[0] == key for q in self._queue)

    def request(self, frame_id: int, image_bgr: np.ndarray, live: bool = False) -> None:
        """Start computing the prediction of this picture in the background (no effect if already asked)."""
        key = self._key(frame_id, image_bgr)
        with self._cv:
            if self._closed or self._known(key) or (live and self.stepped_back):
                return
            if live:
                waiting = [q for q in self._queue if q[2]]
                while len(waiting) >= self.ahead:       # the model is behind: the oldest picture is given up
                    self._queue.remove(waiting.pop(0))
                    self._st["dropped"] += 1
            self._queue.append((key, image_bgr, live))
            self._st["requested"] += 1
            self._cv.notify_all()

    def predict(self, image_bgr: np.ndarray, frame_id: int | None = None, live: bool = False):
        """The prediction for this picture. live=False: always an answer (computed now if it was never asked).
        live=True: the answer if it is ready within `live_patience_s`, else None."""
        if frame_id is None:
            return self.model.predict(image_bgr, None)
        key = self._key(frame_id, image_bgr)
        deadline = time.monotonic() + self.live_patience_s
        with self._cv:
            if not live and not self._known(key) and not self._closed:
                self._queue.appendleft((key, image_bgr, False))      # never asked: next in line
                self._st["requested"] += 1
                self._cv.notify_all()
            while key not in self._ready:
                if self._closed:
                    return None if live else self.model.predict(image_bgr, frame_id)
                if live:
                    left = deadline - time.monotonic()
                    if left <= 0 or not self._known(key):
                        self._answered(False)
                        return None
                    self._cv.wait(left)
                else:
                    if not self._known(key):             # dropped while scanning, wanted now
                        self._queue.appendleft((key, image_bgr, False))
                        self._cv.notify_all()
                    self._cv.wait(0.5)
            out = self._ready.pop(key)
            if live:
                self._answered(True)
        if isinstance(out, BaseException):
            raise out
        return out

    def _answered(self, in_time: bool) -> None:
        self._st["on_time" if in_time else "late"] += 1
        self._recent.append(in_time)
        if len(self._recent) >= self.give_up_after and sum(self._recent) < self.min_on_time * len(self._recent):
            self.stepped_back = True
            for q in [q for q in self._queue if q[2]]:
                self._queue.remove(q)
                self._st["dropped"] += 1

    def _work(self) -> None:
        while True:
            with self._cv:
                while not self._queue and not self._closed:
                    self._cv.wait()
                if self._closed:
                    return
                key, image, _ = self._queue.popleft()
                self._busy = key
            try:
                out = self.model.predict(image, key[0])
            except BaseException as exc:      # handed to whoever collects it; the thread goes on
                out = exc
            with self._cv:
                self._busy = None
                self._st["computed"] += 1
                if isinstance(out, BaseException):
                    self._st["errors"] += 1
                self._ready[key] = out
                while len(self._ready) > self.keep:      # nobody came for the oldest ones
                    self._ready.popitem(last=False)
                self._cv.notify_all()

    def stats(self) -> dict:
        with self._cv:
            return {**self._st, "pending": len(self._queue), "ready": len(self._ready), "stepped_back": self.stepped_back,
                    "mean_seconds": round(self.seconds / self.calls, 3) if self.calls else None}

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._queue.clear()
            self._cv.notify_all()
        self._thread.join(timeout=5)


def load_default(session_dir: Path | None = None):
    """The model if it is installed on this machine, else None (with the reason)."""
    path = model_path(session_dir)
    if not path.exists():
        return None, f"model_not_found:{path}"
    try:
        # Half of the processor for the model, the rest for stereo: the two run at the same time (AsyncMono).
        return MonoDepth(path, threads=max(1, (os.cpu_count() or 2) // 2)), "ok"
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
