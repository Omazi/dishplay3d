#!/usr/bin/env python3
"""Download the optional depth model used to fill what stereo cannot measure (uniform or shiny
surfaces). Depth Anything V2 Small, ONNX export, Apache-2.0, about 99 MB, runs on the processor.

  python tools/get_models.py [--data DIR] [--check]

The file is verified against a fixed SHA-256 before it is put in place. Without it the calculator
works exactly as before.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    from reconstruction.mono_depth import MODEL_NAME, MODEL_SHA256, MODEL_URL
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("DISHPLAY_DATA", str(Path.home() / "dishplay-scan-data")))
    ap.add_argument("--check", action="store_true", help="only say whether the model is installed and intact")
    a = ap.parse_args()
    dst = Path(a.data) / "models" / MODEL_NAME
    if dst.exists() and sha256(dst) == MODEL_SHA256:
        print(f"depth model: present ({dst})")
        return 0
    if a.check:
        print(f"depth model: {'damaged' if dst.exists() else 'absent'} ({dst})")
        return 1
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".part")
    print(f"depth model: downloading about 99 MB to {dst} ...")
    try:
        # A connection that stops answering must not hold the calculator's start for ever: 30 s without a byte ends it.
        with urllib.request.urlopen(MODEL_URL, timeout=30) as src, open(tmp, "wb") as out:
            while chunk := src.read(1 << 20):
                out.write(chunk)
    except Exception as exc:
        print(f"depth model: download failed ({exc!r}); the calculator works without it and will try again at its next start")
        tmp.unlink(missing_ok=True)
        return 1
    got = sha256(tmp)
    if got != MODEL_SHA256:
        tmp.unlink()
        print(f"depth model: the downloaded file is not the expected one (sha256 {got}); nothing installed")
        return 1
    tmp.replace(dst)
    print("depth model: installed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
