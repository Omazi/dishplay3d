#!/usr/bin/env python3
"""Turn a scan session into a dataset for a Gaussian-splatting trainer (Nerfstudio format).

  python tools/export_splat_dataset.py                 (latest session in ~/dishplay-scan-data)
  python tools/export_splat_dataset.py <session_dir> --out <folder> [--max-width 1280] [--zip]

Output folder:
  images/000000.jpg ...   the captured views (reduced to --max-width)
  masks/000000.png ...    white = inside the scan box (the trainer ignores the rest of the image)
  transforms.json         one camera per view, OBJECT frame (origin = centre of the box base, +y up, metres)
  init_points.ply         measured points of the finished model, when the session was finished
  LISEZMOI.txt            how to train it

Camera convention: Nerfstudio's `transform_matrix` is camera-to-world with the camera looking along
-z, +y up, which is exactly ARKit's camera frame. So transform_matrix = inverse(T_world_from_object) *
T_world_from_cameraAR, or the refined pose of the finishing step when `final/poses.json` exists.
The principal point is written with pixel corners at integers (cx + 0.5), as COLMAP/Nerfstudio expect.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

C_GL_FROM_CV = np.diag([1.0, -1.0, -1.0, 1.0])

LISEZMOI = """DishPlay Scan - jeu de donnees pour reconstruction neuronale (Gaussian splatting)

1. Telecharger Brush (gratuit, libre) : https://github.com/ArthurBrussee/brush/releases
   Prendre le fichier Windows, le dezipper.
2. Lancer brush_app.exe, puis ouvrir CE dossier (ou le zip) comme jeu de donnees.
3. Laisser l'entrainement tourner (carte 4 Go : compter 10 a 30 minutes), faire tourner le plat a la souris.
4. Faire des captures d'ecran du resultat et exporter le fichier .ply.

Repere : origine au centre de la base de la boite, +y vers le haut, unites en metres.
{views} vues, images de {w} x {h} pixels.
"""


def box_mask(K, T_cam_from_obj, size, shape, grow_px):
    from reconstruction.coordinates import box_corners
    h, w = shape
    C = box_corners(size)
    pc = C @ T_cam_from_obj[:3, :3].T + T_cam_from_obj[:3, 3]
    mask = np.zeros((h, w), np.uint8)
    if (pc[:, 2] <= 0.02).any():   # a corner behind the camera: no reliable outline, keep the whole image
        mask[:] = 255
        return mask
    uv = pc[:, :2] / pc[:, 2:3] * [K[0, 0], K[1, 1]] + [K[0, 2], K[1, 2]]
    cv2.fillConvexPoly(mask, np.round(cv2.convexHull(uv.astype(np.float32))).astype(np.int32), 255)
    if grow_px > 0:
        mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow_px + 1, 2 * grow_px + 1)))
    return mask


def export(sdir: Path, out: Path, max_width: int = 1280, final_dir: Path | None = None, masks: bool = True,
           mask_grow: float = 0.04, jpeg_quality: int = 95) -> dict:
    from reconstruction.coordinates import (intrinsics_matrix, invert_rigid, mat4_from_rowmajor, object_from_camera_cv,
                                            scale_intrinsics)
    sj = json.loads((sdir / "session.json").read_text())
    box = sj["box"]
    T_w_o = np.array(box["T_world_from_object"], float).reshape(4, 4)
    size = (box["size_m"]["width"], box["size_m"]["height"], box["size_m"]["depth"])
    final_dir = final_dir or (sdir / "final")
    refined = {}
    if (final_dir / "poses.json").exists():
        refined = {int(k): np.array(v, float).reshape(4, 4) for k, v in json.loads((final_dir / "poses.json").read_text())["T_object_from_cameraCV"].items()}
    (out / "images").mkdir(parents=True, exist_ok=True)
    if masks:
        (out / "masks").mkdir(exist_ok=True)
    frames = []
    dims = (0, 0)
    for mp in sorted((sdir / "frames").glob("*.json")):
        meta = json.loads(mp.read_text())
        if meta.get("tracking", {}).get("state") != "normal" or int(meta.get("epoch", 0)) != int(box.get("epoch", 0)):
            continue
        img = cv2.imread(str(mp.with_suffix(".jpg")), cv2.IMREAD_COLOR)
        if img is None:
            continue
        fid = int(meta["frame_id"])
        intr = meta["intrinsics"]
        K = intrinsics_matrix(intr["fx"], intr["fy"], intr["cx"], intr["cy"])
        h0, w0 = img.shape[:2]
        if (intr.get("width", w0), intr.get("height", h0)) != (w0, h0):
            K = scale_intrinsics(K, (intr["width"], intr["height"]), (w0, h0))
        w = min(max_width, w0)
        h = int(round(h0 * w / w0))
        if (w, h) != (w0, h0):
            img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
            K = scale_intrinsics(K, (w0, h0), (w, h))
        T_o_cv = refined.get(fid)
        if T_o_cv is None:
            T_o_cv = object_from_camera_cv(T_w_o, mat4_from_rowmajor(meta["T_world_from_cameraAR"]))
        name = f"{fid:06d}"
        cv2.imwrite(str(out / "images" / f"{name}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
        if masks:
            cv2.imwrite(str(out / "masks" / f"{name}.png"), box_mask(K, invert_rigid(T_o_cv), size, (h, w), int(mask_grow * w)))
        frames.append({"file_path": f"images/{name}.jpg", "w": w, "h": h, "fl_x": float(K[0, 0]), "fl_y": float(K[1, 1]),
                       "cx": float(K[0, 2] + 0.5), "cy": float(K[1, 2] + 0.5),
                       "transform_matrix": (T_o_cv @ C_GL_FROM_CV).tolist()})
        dims = (w, h)
    if not frames:
        raise SystemExit(f"No usable view in {sdir}")
    scene = {"camera_model": "OPENCV", "frames": frames,
             "dishplay": {"frame": "object", "units": "m", "up": "+y", "box_size_m": list(size), "refined_poses": len(refined)}}
    n_init = 0
    pts = final_dir / "points.ply"
    if pts.exists():
        import open3d as o3d
        pc = o3d.io.read_point_cloud(str(pts))
        xyz = np.asarray(pc.points, np.float32)
        rgb = (np.clip(np.asarray(pc.colors), 0, 1) * 255).astype(np.uint8) if pc.has_colors() else np.full((len(xyz), 3), 128, np.uint8)
        if len(xyz) >= 100:
            dt = np.dtype([("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("r", "u1"), ("g", "u1"), ("b", "u1")])
            a = np.zeros(len(xyz), dt)
            a["x"], a["y"], a["z"], a["r"], a["g"], a["b"] = xyz[:, 0], xyz[:, 1], xyz[:, 2], rgb[:, 0], rgb[:, 1], rgb[:, 2]
            head = (f"ply\nformat binary_little_endian 1.0\nelement vertex {len(xyz)}\nproperty float x\nproperty float y\n"
                    "property float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n").encode()
            (out / "init_points.ply").write_bytes(head + a.tobytes())
            scene["ply_file_path"] = "init_points.ply"
            n_init = len(xyz)
    (out / "transforms.json").write_text(json.dumps(scene))
    (out / "LISEZMOI.txt").write_text(LISEZMOI.format(views=len(frames), w=dims[0], h=dims[1]), encoding="utf-8")
    return {"views": len(frames), "width": dims[0], "height": dims[1], "init_points": n_init, "refined_poses": len(refined), "masks": masks}


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
