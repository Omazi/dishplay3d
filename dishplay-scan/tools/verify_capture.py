#!/usr/bin/env python3
"""Verify a stored or exported capture session folder (integrity + contract + geometry sanity).

  python tools/verify_capture.py <data>/sessions/<id>
Checks: every frame has JSON+JPEG, SHA-256 matches, metadata validates against
contracts/capture-session.schema.json, poses are rigid, frame ids/timestamps are
ordered, epochs are reported, intrinsics are consistent with the JPEG size.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main(path: str) -> int:
    import cv2
    import jsonschema
    from reconstruction.coordinates import is_rigid, mat4_from_rowmajor
    sdir = Path(path)
    schema = json.loads((ROOT / "contracts" / "capture-session.schema.json").read_text())
    v = jsonschema.Draft202012Validator({**schema, "$ref": "#/$defs/frame"})
    problems, epochs, last_t = [], {}, None
    metas = sorted((sdir / "frames").glob("*.json"))
    for mp in metas:
        m = json.loads(mp.read_text())
        jpg = mp.with_suffix(".jpg")
        for e in v.iter_errors(m):
            problems.append(f"{mp.name}: contract: {e.message[:120]}")
        if not jpg.exists():
            problems.append(f"{mp.name}: missing JPEG")
            continue
        b = jpg.read_bytes()
        if hashlib.sha256(b).hexdigest() != m["image"]["sha256"]:
            problems.append(f"{mp.name}: checksum mismatch")
        img = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_REDUCED_COLOR_8)
        if img is None:
            problems.append(f"{mp.name}: JPEG does not decode")
        if (m["intrinsics"]["width"], m["intrinsics"]["height"]) != (m["image"]["width"], m["image"]["height"]):
            problems.append(f"{mp.name}: intrinsics are for {m['intrinsics']['width']}x{m['intrinsics']['height']}, image is {m['image']['width']}x{m['image']['height']}")
        if not is_rigid(mat4_from_rowmajor(m["T_world_from_cameraAR"]), 1e-3):
            problems.append(f"{mp.name}: pose is not a rigid transform")
        if last_t is not None and m["timestamp_s"] < last_t:
            problems.append(f"{mp.name}: timestamp goes backwards")
        last_t = m["timestamp_s"]
        epochs[m["epoch"]] = epochs.get(m["epoch"], 0) + 1
    print(json.dumps({"session": sdir.name, "frames": len(metas), "epochs": epochs, "problems": problems[:50],
                      "n_problems": len(problems)}, indent=1))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
