#!/usr/bin/env python3
"""Turn a scan session into a dataset for a Gaussian-splatting trainer (Nerfstudio format).

  python tools/export_splat_dataset.py                 (latest session in ~/dishplay-scan-data)
  python tools/export_splat_dataset.py <session_dir> --out <folder> [--max-width 1280] [--zip]

The work is done by backend/reconstruction/splat_export.py (format described there).
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from reconstruction.splat_export import export  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session_dir", nargs="?")
    ap.add_argument("--data", default=str(Path.home() / "dishplay-scan-data"))
    ap.add_argument("--out")
    ap.add_argument("--final-dir")
    ap.add_argument("--max-width", type=int, default=1280, help="1280 suits a 4 GB graphics card")
    ap.add_argument("--no-masks", action="store_true", help="train on the whole image instead of the box only")
    ap.add_argument("--zip", action="store_true")
    a = ap.parse_args()
    if a.session_dir:
        sdir = Path(a.session_dir)
    else:
        sessions = sorted((p for p in (Path(a.data) / "sessions").glob("*") if (p / "frames").is_dir()), key=lambda p: p.stat().st_mtime)
        if not sessions:
            sys.exit(f"No session found in {a.data}/sessions")
        sdir = sessions[-1]
    out = Path(a.out) if a.out else sdir / "splat_dataset"
    info = export(sdir, out, a.max_width, Path(a.final_dir) if a.final_dir else None, masks=not a.no_masks)
    print(json.dumps(info))
    print(f"Dataset: {out}")
    if a.zip:
        z = out.with_suffix(".zip")
        with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
            for p in sorted(out.rglob("*")):
                if p.is_file():
                    zf.write(p, p.relative_to(out))
        print(f"Zip: {z} ({z.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
