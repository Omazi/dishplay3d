#!/usr/bin/env python3
"""Pack a scan session into ONE small zip that can be sent for diagnosis and replayed elsewhere.

  python tools/pack_session.py                      (latest session in ~/dishplay-scan-data)
  python tools/pack_session.py <session_dir> --max-mb 20

Contents: session.json, the final report and picture (report.json, apercu.png), the last live
preview, and the frames (JPEG reduced to --width, every frame if it fits the size budget, else one
in N). The metadata is unchanged: the engine rescales the intrinsics to the reduced images, so
`tools/replay_session.py local <unzipped folder>` works on the pack.
The pack contains your photos of the scene: send it only to people who may see them.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

import cv2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session_dir", nargs="?")
    ap.add_argument("--data", default=str(Path.home() / "dishplay-scan-data"))
    ap.add_argument("--max-mb", type=float, default=20)
    ap.add_argument("--width", type=int, default=960)
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.session_dir:
        sdir = Path(a.session_dir)
    else:
        sessions = sorted(p for p in (Path(a.data) / "sessions").glob("*") if (p / "frames").is_dir())
        if not sessions:
            sys.exit(f"No session found in {a.data}/sessions")
        sdir = sessions[-1]
    metas = sorted((sdir / "frames").glob("*.json"))
    if not metas:
        sys.exit(f"No frame in {sdir}")
    out = Path(a.out) if a.out else sdir.parent / f"{sdir.name}-pack.zip"
    budget = a.max_mb * 1e6
    small = []
    for mp in metas:
        img = cv2.imread(str(mp.with_suffix(".jpg")), cv2.IMREAD_COLOR)
        if img is None:
            continue
        h, w = img.shape[:2]
        if w > a.width:
            img = cv2.resize(img, (a.width, round(h * a.width / w)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])
        if ok:
            small.append((mp, buf.tobytes()))
    total = sum(len(b) for _, b in small)
    step = 1
    while total / step > budget * 0.92 and step < 6:
        step += 1
    chosen = small[::step]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{sdir.name}/PACK.json", json.dumps({"source": sdir.name, "frames_total": len(metas), "frames_packed": len(chosen),
                                                          "every": step, "width": a.width}, indent=1))
        if (sdir / "session.json").exists():
            z.write(sdir / "session.json", f"{sdir.name}/session.json")
        for name in ("report.json", "apercu.png", "manifest.json"):
            if (sdir / "final" / name).exists():
                z.write(sdir / "final" / name, f"{sdir.name}/final/{name}")
        prev = sorted((sdir / "preview").glob("v*.dpg"))
        if prev:
            z.write(prev[-1], f"{sdir.name}/preview/{prev[-1].name}")
        for mp, jpg in chosen:
            z.write(mp, f"{sdir.name}/frames/{mp.name}")
            z.writestr(f"{sdir.name}/frames/{mp.with_suffix('.jpg').name}", jpg)
    print(f"{out}  ({out.stat().st_size / 1e6:.1f} MB, {len(chosen)}/{len(metas)} frames, 1 in {step})")


if __name__ == "__main__":
    main()
