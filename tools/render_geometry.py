#!/usr/bin/env python3
"""Render a DPG1 preview/final geometry file to PNG (software rasteriser, no GPU).

Used for reports and visual checks. Shows points and/or the mesh with simple
shading; interpolated vertices are tinted blue, provisional points dimmed.

  python tools/render_geometry.py session/preview/latest.dpg out.png [--mode mesh|points|both]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from reconstruction.preview_format import decode_geometry  # noqa: E402
from reconstruction.render import contact_sheet  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dpg")
    ap.add_argument("png")
    ap.add_argument("--mode", default="both", choices=["both", "mesh", "points"])
    a = ap.parse_args()
    g = decode_geometry(Path(a.dpg).read_bytes())
    cv2.imwrite(a.png, contact_sheet(g, a.mode))


if __name__ == "__main__":
    main()
