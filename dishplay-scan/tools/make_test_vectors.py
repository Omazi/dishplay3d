#!/usr/bin/env python3
"""Generate cross-language golden vectors (Python reference -> Swift ScanCore tests).

  python tools/make_test_vectors.py      (rewrites ios/ScanCore/Tests/ScanCoreTests/Vectors/*)
backend/tests/test_vectors.py checks the committed files are still what Python produces.
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from reconstruction.coordinates import (intrinsics_matrix, invert_rigid, look_at_ar, mat4_to_rowmajor,  # noqa: E402
                                        object_from_camera_cv, project, scale_intrinsics)
from reconstruction.preview_format import encode_frame, encode_geometry  # noqa: E402

OUT = ROOT / "ios" / "ScanCore" / "Tests" / "ScanCoreTests" / "Vectors"


def build():
    rng = np.random.default_rng(1234)
    cases = []
    for i in range(6):
        yaw = float(rng.uniform(-np.pi, np.pi))
        c, s = np.cos(yaw), np.sin(yaw)
        T_wo = np.array([[c, 0, s, rng.uniform(-1, 1)], [0, 1, 0, rng.uniform(-1, 0)], [-s, 0, c, rng.uniform(-1, 1)], [0, 0, 0, 1]])
        centre = T_wo[:3, 3] + [0, 0.04, 0]
        eye = centre + np.array([rng.uniform(-0.3, 0.3), rng.uniform(0.15, 0.4), rng.uniform(-0.3, 0.3)])
        T_wc = look_at_ar(eye, centre, roll_deg=float(rng.choice([-90.0, 0.0, 90.0])))
        K = intrinsics_matrix(1440.0 + i, 1440.0 + i, 959.5, 719.5)
        pts = rng.uniform(-0.1, 0.1, (5, 3)) + [0, 0.05, 0]
        T_oc = object_from_camera_cv(T_wo, T_wc)
        uv, z = project(K, invert_rigid(T_oc), pts)
        cases.append({"T_world_from_object": mat4_to_rowmajor(T_wo), "T_world_from_cameraAR": mat4_to_rowmajor(T_wc),
                      "K": {"fx": K[0, 0], "fy": K[1, 1], "cx": K[0, 2], "cy": K[0, 2] * 0 + K[1, 2], "width": 1920, "height": 1440},
                      "points_object": pts.tolist(), "T_object_from_cameraCV": mat4_to_rowmajor(T_oc),
                      "uv": uv.tolist(), "depth": z.tolist()})
    Ks = scale_intrinsics(intrinsics_matrix(1440.0, 1440.0, 959.5, 719.5), (1920, 1440), (640, 480))
    coords = {"cases": cases, "scaled_K_640x480": {"fx": Ks[0, 0], "fy": Ks[1, 1], "cx": Ks[0, 2], "cy": Ks[1, 2]}}
    geo = encode_geometry({"schema": "dishplay.geometry/1", "version": 7, "kind": "points+mesh", "epoch": 0, "box_revision": 0,
                           "computed_at": 1.5, "last_frame_ids": [3, 4], "integrated_frames": 5},
                          np.array([[0, 0, 0], [0.1, 0.2, 0.3]], np.float32), np.array([[255, 0, 0, 0], [0, 255, 0, 4]], np.uint8),
                          np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32), np.array([[1, 2, 3, 0], [4, 5, 6, 1], [7, 8, 9, 0]], np.uint8),
                          np.array([[0, 0, 1], [0, 0, 1], [0, 0, 1]], np.float32), np.array([[0, 1, 2]], np.uint32))
    env = encode_frame({"frame_id": 3}, b"\xff\xd8\xffJPEG", b"\x00\x00\x80\x3f", b"\x02")
    return coords, geo, env


def _close(a, b, tol=1e-9):
    if isinstance(a, dict):
        return isinstance(b, dict) and a.keys() == b.keys() and all(_close(a[k], b[k], tol) for k in a)
    if isinstance(a, list):
        return isinstance(b, list) and len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, (int, float)):
        return abs(a - b) <= tol * max(1.0, abs(a))
    return a == b


def main(check=False):
    coords, geo, env = build()
    files = {"coordinates.json": json.dumps(coords, indent=1).encode(), "geometry.dpg": geo, "frame.dpf": env}
    if check:
        # Binary formats must match exactly; floats in JSON may differ in the last digit across CPUs/BLAS.
        if any((OUT / k).read_bytes() != files[k] for k in ("geometry.dpg", "frame.dpf")):
            return False
        return _close(json.loads((OUT / "coordinates.json").read_text()), coords)
    OUT.mkdir(parents=True, exist_ok=True)
    for k, v in files.items():
        (OUT / k).write_bytes(v)
    return True


if __name__ == "__main__":
    sys.exit(0 if main("--check" in sys.argv) else 1)
