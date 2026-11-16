#!/usr/bin/env python3
"""Convert one Objectron capture (real iPhone video + ARKit poses + annotated 3D box) into a DishPlay
session folder that the engine can replay. Real handheld data with real tracking noise, used to tune
the reconstruction on something other than synthetic renders. The data itself is not redistributed.

  python tools/import_objectron.py --video video.MOV --geometry geometry.pbdata --annotation a.pbdata \
      --schema-dir <dir with the *_pb2.py generated from Objectron's .proto files> --out session_dir

Objectron: https://github.com/google-research-datasets/Objectron (C-UDA licence, computational use).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

import cv2
import numpy as np


def read_frames(path: Path, ar):
    buf = path.read_bytes()
    i, out = 0, []
    while i < len(buf):
        (n,) = struct.unpack("<I", buf[i:i + 4])
        i += 4
        f = ar.ARFrame()
        f.ParseFromString(buf[i:i + n])
        i += n
        out.append(f)
    return out


def box_from_annotation(seq, grow_xz: float, grow_y: float):
    o = seq.objects[0]
    R = np.array(o.rotation, float).reshape(3, 3)
    t = np.array(o.translation, float)
    s = np.array(o.scale, float)
    up = np.array([0.0, 1.0, 0.0])           # ARKit world: gravity-aligned, +y up
    k = int(np.argmax(np.abs(R.T @ up)))       # box axis closest to vertical
    h = s[k]
    a, b = [j for j in range(3) if j != k]
    x = R[:, a] - up * (R[:, a] @ up)
    x /= np.linalg.norm(x)
    z = np.cross(x, up)
    T = np.eye(4)
    T[:3, 0], T[:3, 1], T[:3, 2] = x, up, z
    T[:3, 3] = t - up * h / 2
    size = (float(s[a] * grow_xz), float(h * grow_y), float(s[b] * grow_xz))
    return T, size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--geometry", required=True)
    ap.add_argument("--annotation", required=True)
    ap.add_argument("--schema-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--every", type=int, default=3, help="keep one video frame out of N")
    ap.add_argument("--grow-xz", type=float, default=2.2, help="box footprint relative to the annotated object")
    ap.add_argument("--grow-y", type=float, default=1.15)
    ap.add_argument("--rotate", choices=["ccw", "cw"], default="ccw", help="portrait video -> sensor landscape")
    ap.add_argument("--jpeg-quality", type=int, default=90)
    a = ap.parse_args()
    sys.path.insert(0, a.schema_dir)
    import a_r_capture_metadata_pb2 as ar
    import annotation_data_pb2 as ann

    frames = read_frames(Path(a.geometry), ar)
    seq = ann.Sequence()
    seq.ParseFromString(Path(a.annotation).read_bytes())
    T_box, size = box_from_annotation(seq, a.grow_xz, a.grow_y)
    out = Path(a.out)
    (out / "frames").mkdir(parents=True, exist_ok=True)
    box = {"T_world_from_object": T_box.reshape(-1).tolist(), "size_m": {"width": size[0], "height": size[1], "depth": size[2]},
           "epoch": 0, "revision": 0, "scale_confidence": "tracking_only"}
    (out / "session.json").write_text(json.dumps({"id": out.name, "box": box, "settings": {},
                                                  "device": {"platform": "ios", "model": "objectron-capture"}}))
    cap = cv2.VideoCapture(a.video)
    n = 0
    for i, f in enumerate(frames):
        ok, img = cap.read()
        if not ok:
            break
        if i % a.every:
            continue
        c = f.camera
        if img.shape[0] > img.shape[1]:   # stored portrait; intrinsics and pose are for the landscape sensor image
            img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE if a.rotate == "ccw" else cv2.ROTATE_90_CLOCKWISE)
        K = np.array(c.intrinsics, float).reshape(3, 3)
        w, h = int(c.image_resolution_width), int(c.image_resolution_height)
        jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, a.jpeg_quality])[1].tobytes()
        meta = {
            "schema": "dishplay.frame/1", "session_id": out.name, "frame_id": n, "epoch": 0, "timestamp_s": float(f.timestamp),
            "image": {"width": img.shape[1], "height": img.shape[0], "encoding": "jpeg", "orientation": "sensor_native",
                      "sha256": hashlib.sha256(jpg).hexdigest()},
            "intrinsics": {"fx": K[0, 0], "fy": K[1, 1], "cx": K[0, 2], "cy": K[1, 2], "width": w, "height": h},
            "distortion": {"status": "not_provided"},
            "T_world_from_cameraAR": [float(v) for v in c.transform],
            "tracking": {"state": "normal"},
            "camera_format": {"width": w, "height": h, "fps": 30, "device": "objectron"},
            "quality": {},
        }
        (out / "frames" / f"{n:06d}.jpg").write_bytes(jpg)
        (out / "frames" / f"{n:06d}.json").write_text(json.dumps(meta))
        n += 1
    print(f"{n} frames -> {out}  box size (w,h,d) m = {tuple(round(v, 3) for v in size)}")


if __name__ == "__main__":
    main()
