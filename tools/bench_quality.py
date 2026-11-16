#!/usr/bin/env python3
"""Quality benchmark on the hard synthetic bowl (tests/realistic.py). Prints metrics for the last
live preview and for the finished model, and renders both. Used to compare engine changes.

  python tools/bench_quality.py --out /tmp/bench [--frames 110] [--no-finish]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))


def metrics(scene, verts, tris, vis_pts, vis_mat, cls=None):
    from scipy.spatial import cKDTree
    if len(verts) == 0:
        return {"empty": True}
    # Remove the global offset caused by simulated tracking drift (rigid ICP onto the true surface),
    # so the numbers describe the SHAPE; the offset itself is reported.
    import open3d as o3d
    src = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(verts))
    tgt = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(vis_pts))
    reg = o3d.pipelines.registration.registration_icp(src, tgt, 0.01, np.eye(4),
                                                      o3d.pipelines.registration.TransformationEstimationPointToPoint())
    T = np.asarray(reg.transformation)
    offset_mm = float(np.linalg.norm(T[:3, 3]) * 1000)
    verts = verts @ T[:3, :3].T + T[:3, 3]
    d = scene.scene.compute_distance(__import__("open3d").core.Tensor(verts.astype(np.float32))).numpy()
    tree = cKDTree(verts)
    dv, _ = tree.query(vis_pts)
    rim = (vis_mat == 1) & (vis_pts[:, 1] > 0.047)
    wall = (vis_mat == 1) & (vis_pts[:, 1] <= 0.047) & (vis_pts[:, 1] > 0.008)
    extra = {}
    if cls is not None and len(cls) == len(d):
        meas, interp = cls == 0, cls == 1
        extra = {"measured_vertices_pct": float(meas.mean() * 100),
                 "measured_p90_mm": float(np.percentile(d[meas], 90) * 1000) if meas.any() else None,
                 "measured_floaters_pct(>6mm)": float((d[meas] > 0.006).mean() * 100) if meas.any() else None,
                 "interpolated_p90_mm": float(np.percentile(d[interp], 90) * 1000) if interp.any() else None}
    out = {
        **extra,
        "accuracy_median_mm": float(np.median(d) * 1000), "accuracy_p90_mm": float(np.percentile(d, 90) * 1000),
        "floaters_pct(>6mm)": float((d > 0.006).mean() * 100), "far_floaters_pct(>15mm)": float((d > 0.015).mean() * 100),
        "completeness_pct(<4mm)": float((dv < 0.004).mean() * 100),
        "rim_completeness_pct": float((dv[rim] < 0.004).mean() * 100) if rim.any() else None,
        "wall_completeness_pct": float((dv[wall] < 0.004).mean() * 100) if wall.any() else None,
        "nuts_completeness_pct": float((dv[vis_mat == 2] < 0.004).mean() * 100),
        "vertices": int(len(verts)), "triangles": int(len(tris)), "drift_offset_mm": offset_mm,
    }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/bench")
    ap.add_argument("--frames", type=int, default=110)
    ap.add_argument("--no-finish", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-refine", action="store_true", help="skip the global pose refinement when finishing")
    ap.add_argument("--jitter-mm", type=float, default=0.0, help="independent per-frame position noise on reported poses")
    ap.add_argument("--jitter-deg", type=float, default=0.0, help="independent per-frame rotation noise on reported poses")
    ap.add_argument("--dump", action="store_true", help="save the raw fused mesh and the point store for offline experiments")
    a = ap.parse_args()
    from reconstruction.engine import Box, EngineConfig, SessionEngine
    from reconstruction.preview_format import decode_geometry
    from tests.helpers import box_json
    from tests.realistic import BOX, BowlScene, degrade, handheld_poses
    from tests.synthetic import frame_meta
    out = Path(a.out)
    (out / "frames").mkdir(parents=True, exist_ok=True)
    sc = BowlScene()
    rep, true = handheld_poses(a.frames, a.seed)
    rng = np.random.default_rng(a.seed)
    if a.jitter_mm or a.jitter_deg:
        # Frame-to-frame tracking noise (not drift): each reported pose is off by a small independent amount.
        jr = np.random.default_rng(a.seed + 1000)
        out_rep = []
        for T in rep:
            w = jr.normal(scale=np.radians(a.jitter_deg), size=3)
            J = np.eye(4)
            J[:3, :3] = cv2.Rodrigues(w)[0]
            J[:3, 3] = jr.normal(scale=a.jitter_mm / 1000.0, size=3)
            out_rep.append(J @ T)
        rep = out_rep
    bj = box_json(size=BOX)
    (out / "session.json").write_text(json.dumps({"id": "bench", "box": bj, "device": {"platform": "synthetic", "model": "bench"}, "settings": {}}))
    clock = {"t": 0.0}
    # The bench scores the table too (it is part of the ground truth): keep it in the output.
    eng = SessionEngine(out, Box.from_json(bj), EngineConfig(hide_table=False), clock=lambda: clock["t"])
    t0 = time.perf_counter()
    last = None
    for i, (Tr, Tt) in enumerate(zip(rep, true)):
        img, _ = sc.render(Tt)
        jpg = cv2.imencode(".jpg", degrade(img, rng), [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tobytes()
        meta = frame_meta(sc, i, Tr, session_id="bench", timestamp=i * 0.3)
        meta["image"]["sha256"] = hashlib.sha256(jpg).hexdigest()
        (out / "frames" / f"{i:06d}.jpg").write_bytes(jpg)
        (out / "frames" / f"{i:06d}.json").write_text(json.dumps(meta))
        clock["t"] = meta["timestamp_s"]
        eng.add_frame(meta, out / "frames" / f"{i:06d}.jpg", received_at=clock["t"])
        eng.process_pending(live=False)
        if eng.should_snapshot():
            last = eng.snapshot()
    eng.flush()
    last = eng.snapshot() or last
    live_s = time.perf_counter() - t0
    vis_pts, vis_mat = sc.visible_samples(true[::3])
    g = decode_geometry(last[1])
    (out / "live.dpg").write_bytes(last[1])
    if a.dump:
        import open3d as o3d
        xyz, rgb, nfr, sup, src = eng.fusion.measured_points()
        np.savez(out / "store.npz", xyz=xyz, rgb=rgb, nframes=nfr, sup=sup, weak=eng.fusion.weak_cells(),
                 vis_pts=vis_pts, vis_mat=vis_mat)
        o3d.io.write_triangle_mesh(str(out / "raw_mesh.ply"), eng.fusion.extract_mesh())
    res = {"frames": a.frames, "live_seconds": live_s, "engine_metrics": eng.metrics(),
           "live": metrics(sc, g["verts"].astype(np.float64), g["tris"], vis_pts, vis_mat, g["vert_rgbc"][:, 3])}
    if not a.no_finish:
        from reconstruction.refinement import finish_session
        import open3d as o3d
        t1 = time.perf_counter()
        rep_final = finish_session(eng, out / "final", texture=False, refine=not a.no_refine, remove_table=False)
        res["pose_refinement"] = rep_final["pose_refinement"]
        gf = decode_geometry((out / "final" / "final_preview.dpg").read_bytes())
        res["final"] = metrics(sc, gf["verts"].astype(np.float64), gf["tris"], vis_pts, vis_mat, gf["vert_rgbc"][:, 3])
        res["finish_seconds"] = time.perf_counter() - t1
    (out / "bench.json").write_text(json.dumps(res, indent=1, default=float))
    for k in ("live", "final"):
        if k in res:
            print(k, json.dumps({a: (round(b, 2) if isinstance(b, float) else b) for a, b in res[k].items()}))
    if "pose_refinement" in res:
        print("pose_refinement", {k: (round(v, 2) if isinstance(v, float) else v) for k, v in res["pose_refinement"].items()})
    print("frames", res["engine_metrics"]["frames"], "live_s", round(live_s, 1), "finish_s", round(res.get("finish_seconds", 0), 1))


if __name__ == "__main__":
    main()
