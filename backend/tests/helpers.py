"""Shared helpers: write synthetic frames as a session folder exactly like the server does."""
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from tests.synthetic import SyntheticScene, frame_meta, orbit_poses

BOX_SIZE = (0.28, 0.08, 0.28)


def box_json(epoch=0, size=BOX_SIZE, T=None):
    T = np.eye(4) if T is None else T
    return {"T_world_from_object": T.reshape(-1).tolist(), "size_m": {"width": size[0], "height": size[1], "depth": size[2]},
            "epoch": epoch, "revision": 0, "scale_confidence": "tracking_only"}


def write_session(root: Path, n=40, scene=None, epoch_of=lambda i: 0, poses=None, sid="synthetic01", box_size=BOX_SIZE,
                  reported_poses=None):
    """reported_poses: what the tracker says (written in the frame files) when it differs from where the camera
    really was (poses, used to render the pictures)."""
    scene = scene or SyntheticScene()
    poses = poses or orbit_poses(n)
    sdir = root / sid
    (sdir / "frames").mkdir(parents=True, exist_ok=True)
    (sdir / "session.json").write_text(json.dumps({"id": sid, "box": box_json(size=box_size), "device": {"platform": "synthetic", "model": "synthetic"},
                                                   "settings": {}, "reference_width_m": 0.24}))
    for i, T in enumerate(poses):
        img, _ = scene.render(T)
        jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()
        meta = frame_meta(scene, i, T if reported_poses is None else reported_poses[i], session_id=sid, epoch=epoch_of(i))
        meta["image"]["sha256"] = hashlib.sha256(jpg).hexdigest()
        (sdir / "frames" / f"{i:06d}.jpg").write_bytes(jpg)
        (sdir / "frames" / f"{i:06d}.json").write_text(json.dumps(meta))
    return sdir
